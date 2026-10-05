"""Queries resolved in the root and in the other checkouts of the store."""
import datetime as dt
import unittest
from pathlib import Path

from support import EXIT_OK, MAIN_BRANCH, REMOTE, SharedStoreTestCase, doc

from svod.approval import write_mark
from svod.context import Context
from svod.loader import load_runtime
from svod.providers.openspec_change import DEFAULT_ARCHIVE, DEFAULT_ROOT, METADATA_FILE
from svod.resolve import by_key, resolve

CHANGES = Path(DEFAULT_ROOT)
CHECKOUT_LINE = "  In the checkout {dir}, not in the default branch yet"
NEW = "store-tk-2_new"
EDITED = "store-tk-1_edit"
ARCHIVING = "store-tk-3_archive"
MENTION = "store-tk-5_card"
CLEAN = "store-ops_clean"


def change(sb, name, key, base=None, approved=True):
    """Change with spec and design; approved unless told otherwise."""
    root = CHANGES / name
    meta = [f"ticket: {key}"] + (["approved: yes"] if approved else [])
    sb.write(root / METADATA_FILE, "\n".join(meta) + "\n", base)
    sb.write(root / "specs" / "cap" / "spec.md", "# spec\n", base)
    sb.write(root / "design.md", "# design\n", base)


class CheckoutResolveTest(SharedStoreTestCase):
    """A change added, edited or archived in a checkout is found there, not only in the root."""

    @classmethod
    def build(cls, sb):
        """Master with c-1 and c-3; checkouts adding c-2, editing c-1, archiving c-3, a mention."""
        sb.init_git()
        change(sb, "c-1", "tk-1")
        change(sb, "c-3", "tk-3")
        sb.write("projects/gamma/onepager.md", doc("onepager", "No tasks yet."))
        sb.commit(message="master")
        sb.push()
        cls.paths = {}
        for name in (NEW, EDITED, ARCHIVING, MENTION, CLEAN):
            cls.paths[name] = sb.parent / name
            sb.git(sb.store, "worktree", "add", "-q", "-b", name, str(cls.paths[name]),
                   f"{REMOTE}/{MAIN_BRANCH}")
        change(sb, "c-2", "tk-2", base=cls.paths[NEW], approved=False)
        sb.write(CHANGES / "c-1" / "progress.txt", "3", base=cls.paths[EDITED])
        sb.commit(cls.paths[EDITED], "progress")
        (cls.paths[ARCHIVING] / CHANGES / DEFAULT_ARCHIVE).mkdir(parents=True)
        sb.git(cls.paths[ARCHIVING], "mv", str(CHANGES / "c-3"),
               str(CHANGES / DEFAULT_ARCHIVE))
        sb.write("projects/gamma/onepager.md", doc("onepager", "Tasks: tk-5."),
                 base=cls.paths[MENTION])
        runtime = load_runtime(sb.store)
        cls.runtime = runtime
        cls.ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())

    def found(self, query):
        """(pipeline, id, checkout directory name or None, exists) of every match."""
        matches = resolve(self.ctx, self.runtime.pipelines, query).matches
        return [(p.name, s.id, s.checkout.name if s.checkout else None, s.exists)
                for p, s in matches]

    def test_resolution(self):
        """Only in a checkout, in both, moved to the archive, a mention only in a checkout."""
        cases = (
            ("tk-2", [("task", "c-2", NEW, True)]),
            ("c-2", [("task", "c-2", NEW, True)]),
            ("tk-1", [("task", "c-1", EDITED, True)]),
            ("tk-3", [("task", "c-3", ARCHIVING, True)]),
            ("tk-5", [("task", "tk-5", MENTION, False)]),
            ("tk-9", [("task", "tk-9", None, False)]),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.found(query), expected)

    def test_by_key_drops_the_placeholder(self):
        """A key with a change only in a checkout has no not-found subject of the root."""
        pairs = by_key(self.ctx, self.runtime.pipelines, "tk-2")
        self.assertEqual([s.exists for _, s in pairs], [True])

    def test_status_is_counted_in_the_checkout(self):
        """The status names the checkout and reads the change files there."""
        cases = (
            ("tk-2", NEW, "Next step: get the plan approved."),
            ("tk-1", EDITED, "  progress +3\n"),
            ("tk-3", ARCHIVING, "Next step: task closed."),
            ("tk-5", MENTION, "Warning: the container has no design document, write it first."),
        )
        for query, checkout, text in cases:
            with self.subTest(query=query):
                out = self.sb.cli("status", query)
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                lines = out.stdout.splitlines()
                self.assertEqual(lines[1], CHECKOUT_LINE.format(dir=checkout))
                self.assertIn(text, out.stdout)
                self.assertNotIn(CLEAN, out.stdout)

    def test_status_from_a_checkout_sees_the_others(self):
        """Run from one checkout, a change of another is found there; its own is in the root."""
        out = self.sb.cli("status", "tk-1", cwd=self.paths[NEW])
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn(CHECKOUT_LINE.format(dir=EDITED), out.stdout)
        out = self.sb.cli("status", "tk-2", cwd=self.paths[NEW])
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertNotIn("In the checkout", out.stdout)


class CheckoutApproveTest(SharedStoreTestCase):
    """approve from the root writes into the checkout holding the change."""

    @classmethod
    def build(cls, sb):
        """A change that exists only in a checkout."""
        sb.init_git()
        sb.push()
        cls.checkout = sb.parent / NEW
        sb.git(sb.store, "worktree", "add", "-q", "-b", NEW, str(cls.checkout),
               f"{REMOTE}/{MAIN_BRANCH}")
        change(sb, "c-2", "tk-2", base=cls.checkout, approved=False)

    def test_approve_writes_in_the_checkout(self):
        """The fields land in the checkout's metadata, reported relative to it."""
        write_mark(self.sb.store, ["tk-2"], dt.datetime.now().astimezone())
        out = self.sb.cli("approve", "tk-2")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn(f"{CHANGES / 'c-2' / METADATA_FILE}", out.stdout)
        text = (self.checkout / CHANGES / "c-2" / METADATA_FILE).read_text(encoding="utf-8")
        self.assertIn("approved: ", text)


if __name__ == "__main__":
    unittest.main()
