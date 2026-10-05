"""Memory of one run: git called once per directory and arguments, parallel reads as sequential."""
import unittest
from unittest import mock

from support import MAIN_BRANCH, REMOTE, SharedStoreTestCase, StoreTestCase

from svod.cache import RunCache
from svod.checkouts import rooted, worktree_scopes
from svod.config import load_config
from svod.context import Context
from svod.git import GitResult, changed_calls, changed_paths, run_git, worktree_list
from svod.subject import Subject

RUN_GIT = "svod.git.run_git"
CHECKOUTS = ("store-a", "store-b", "store-c")
EDITED_FILE = "notes.md"


class RunCacheTest(unittest.TestCase):
    """Git and computed values are asked for once per run."""

    def test_git_called_once_per_call(self):
        """A repeated call is answered from memory, a different one runs git."""
        cases = [
            ("same call", [("/a", ("status",)), ("/a", ("status",))], 1),
            ("other args", [("/a", ("status",)), ("/a", ("log",))], 2),
            ("other dir", [("/a", ("status",)), ("/b", ("status",))], 2),
        ]
        for name, calls, runs in cases:
            with self.subTest(name), mock.patch(RUN_GIT, return_value=GitResult(ok=True)) as git:
                cache = RunCache()
                for cwd, args in calls:
                    cache.git(cwd, *args)
                self.assertEqual(git.call_count, runs)

    def test_prefetch_skips_known(self):
        """Prefetch runs only the calls not asked for yet, each once."""
        with mock.patch(RUN_GIT, return_value=GitResult(ok=True)) as git:
            cache = RunCache()
            cache.git("/a", "status")
            cache.prefetch([("/a", ("status",)), ("/b", ("status",)), ("/b", ("status",)),
                            ("/c", ("log",))])
            cache.git("/b", "status")
            self.assertEqual(git.call_count, 3)

    def test_value_computed_once(self):
        """A value is computed on first use and kept."""
        cache = RunCache()
        compute = mock.Mock(return_value=42)
        self.assertEqual([cache.value("k", compute) for _ in range(3)], [42, 42, 42])
        compute.assert_called_once_with()

    def test_author_read_on_first_use(self):
        """The author of a subject is read once, when first asked for."""
        read = mock.Mock(return_value=("me@example.com", "Me"))
        subject = Subject(id="s", path=None, author_of=read)
        read.assert_not_called()
        self.assertEqual(subject.author, ("me@example.com", "Me"))
        self.assertEqual(subject.author, ("me@example.com", "Me"))
        read.assert_called_once_with()


class RootedCacheTest(StoreTestCase):
    """A context rooted in another checkout shares the memory of the run."""

    def test_rooted_shares_cache(self):
        """Git asked in the rooted context is not asked again in the root one."""
        self.sb.init_git(remote=False)
        ctx = Context(load_config(self.sb.store))
        other = rooted(ctx, self.sb.parent)
        self.assertIs(other.cache, ctx.cache)
        with mock.patch(RUN_GIT, return_value=GitResult(ok=True)) as git:
            other.cache.git(self.sb.store, "status")
            ctx.cache.git(self.sb.store, "status")
            self.assertEqual(git.call_count, 1)


class ParallelReadTest(SharedStoreTestCase):
    """Git read in parallel gives what sequential calls give."""

    @classmethod
    def build(cls, sb):
        """Store with checkouts: one with a commit, one with an uncommitted file, one clean."""
        sb.init_git()
        cls.paths = []
        for name in CHECKOUTS:
            path = sb.parent / name
            sb.git(sb.store, "worktree", "add", "-q", "-b", name, str(path),
                   f"{REMOTE}/{MAIN_BRANCH}")
            cls.paths.append(path)
        sb.write(EDITED_FILE, "committed\n", base=cls.paths[0])
        sb.commit(cls.paths[0], "edit")
        sb.write(EDITED_FILE, "draft\n", base=cls.paths[1])

    def test_prefetch_matches_sequential(self):
        """Every prefetched call holds the result a direct call returns."""
        calls = [(p, args) for p in self.paths for args in changed_calls(MAIN_BRANCH)]
        cache = RunCache()
        cache.prefetch(calls)
        with mock.patch(RUN_GIT) as git:
            parallel = [cache.git(cwd, *args) for cwd, args in calls]
            git.assert_not_called()
        self.assertEqual(parallel, [run_git(cwd, *args) for cwd, args in calls])

    def test_scopes_match_sequential(self):
        """Scopes read in parallel list the checkouts and paths sequential reads find."""
        ctx = Context(load_config(self.sb.store))
        found, _ = worktree_list(self.sb.store)
        sequential = {}
        for worktree in found:
            if worktree.path == ctx.root:
                continue
            paths, _ = changed_paths(worktree.path, ctx.config.default_branch)
            if paths:
                sequential[worktree.path.name] = frozenset(paths)
        parallel = {scope.name: scope.paths for scope in worktree_scopes(ctx)}
        self.assertEqual(parallel, sequential)
        self.assertEqual(set(parallel), set(CHECKOUTS[:2]))


if __name__ == "__main__":
    unittest.main()
