"""Core subject providers and query resolution."""
import unittest
from pathlib import Path

import support
from support import PEER, StoreTestCase, doc

from svod.config import load_config
from svod.context import Context
from svod.gates import build_registries
from svod.loader import load_runtime
from svod.providers import CORE_PROVIDERS
from svod.providers.openspec_change import DEFAULT_ARCHIVE, DEFAULT_ROOT, METADATA_FILE
from svod.resolve import resolve
from svod.subject import ATTR_CONTAINER, ATTR_FRONTMATTER

CHANGES = Path(DEFAULT_ROOT)
ARCHIVE = CHANGES / DEFAULT_ARCHIVE
CONTAINER_ALPHA = "projects/alpha"


def build_store(sb):
    """Containers, changes and notes shared by the provider tests."""
    sb.write("projects/alpha/Onepager.md", doc("onepager", "Work: tk-101, tk-102, tk-1010."))
    sb.write("projects/alpha/Design/solution.md", doc("design"))
    sb.write("projects/alphabet/Onepager.md", doc("onepager", "Nothing yet.", status="archived"))
    sb.write("projects/beta/Onepager.md", doc("onepager", "Work: tk-201."))
    sb.write("projects/beta/stray.txt", "tk-202\n")
    sb.write(CHANGES / "c-101" / METADATA_FILE, "ticket: tk-101\nepic: tk-999\n")
    sb.write(CHANGES / "c-101-more" / "tasks.md", "## 1. tk-101 more\n\n- [ ] tk-555 inline\n")
    sb.write(CHANGES / "c-300" / METADATA_FILE, "ticket: tk-300\n")
    sb.write(ARCHIVE / "2026-08-01-c-102" / METADATA_FILE, "ticket: tk-102\n")
    sb.write("notes/README.md", "# notes\n")
    sb.write("notes/001 First question.md", doc("note", status="active", review="2026-10-01"))
    sb.write("notes/002 Closed question.md", doc("note", status="archived"))
    sb.write("notes/003 Bare.md", "no frontmatter\n")
    sb.init_git(remote=False)
    sb.write(CHANGES / "c-300" / "proposal.md", "# peer\n")
    sb.commit(message="peer work", author=PEER)
    sb.write(CHANGES / "c-400" / METADATA_FILE, "ticket: tk-400\n")


class ProviderTest(StoreTestCase):
    """Providers constructed directly with the toy key gate."""

    def setUp(self):
        """Store with containers, changes and notes."""
        super().setUp()
        build_store(self.sb)
        self.ctx = Context(load_config(self.sb.store))
        self.ticket = build_registries(support.TEST_PROFILE)[0]["ticket"]()

    def provider(self, name, **params):
        """Core provider with the toy key gate."""
        return CORE_PROVIDERS[name](params, self.ticket)

    def test_openspec_change_enumerate(self):
        """Active changes then archive, with keys, container, archive flag and author."""
        changes = self.provider("openspec_change", containers=["projects"],
                                ignore_fields=["epic"])
        found = {s.id: s for s in changes.enumerate(self.ctx)}
        self.assertEqual(list(found), ["c-101", "c-101-more", "c-300", "c-400",
                                       "2026-08-01-c-102"])
        cases = (
            ("c-101", {"tk-101"}, CONTAINER_ALPHA, False),
            ("c-101-more", {"tk-101"}, CONTAINER_ALPHA, False),
            ("c-300", {"tk-300"}, None, False),
            ("2026-08-01-c-102", {"tk-102"}, CONTAINER_ALPHA, True),
        )
        for change, keys, container, archived in cases:
            with self.subTest(change=change):
                subject = found[change]
                self.assertEqual(set(subject.keys), keys)
                self.assertEqual(subject.attrs[ATTR_CONTAINER], container)
                self.assertEqual(subject.archived, archived)
                self.assertTrue(subject.exists)
        self.assertEqual(found["c-300"].author, PEER)
        self.assertEqual(found["c-101"].author, support.ME)
        self.assertIsNone(found["c-400"].author)

    def test_openspec_change_by_key(self):
        """All changes by key; unknown and ignored keys give a not-found subject."""
        changes = self.provider("openspec_change", containers=["projects"],
                                ignore_fields=["epic"])
        cases = (
            ("tk-101", ["c-101", "c-101-more"], True, CONTAINER_ALPHA),
            ("tk-102", ["2026-08-01-c-102"], True, CONTAINER_ALPHA),
            ("tk-999", ["tk-999"], False, None),
            ("tk-201", ["tk-201"], False, "projects/beta"),
            ("tk-202", ["tk-202"], False, None),
            ("tk-10", ["tk-10"], False, None),
        )
        for key, ids, exists, container in cases:
            with self.subTest(key=key):
                found = changes.match_key(key, self.ctx)
                self.assertEqual([s.id for s in found], ids)
                self.assertTrue(all(s.exists == exists for s in found))
                self.assertTrue(all(s.attrs[ATTR_CONTAINER] == container for s in found))

    def test_openspec_change_by_name(self):
        """Exact directory name, active or archived, in any case; never a substring."""
        changes = self.provider("openspec_change", containers=["projects"])
        cases = (
            ("c-101", ["c-101"]),
            ("C-101-MORE", ["c-101-more"]),
            ("2026-08-01-c-102", ["2026-08-01-c-102"]),
            ("c-10", []),
            ("c-102", []),
            ("openspec/changes/c-101", ["c-101"]),
            ("openspec/changes/archive/2026-08-01-c-102", ["2026-08-01-c-102"]),
        )
        for query, ids in cases:
            with self.subTest(query=query):
                self.assertEqual([s.id for s in changes.match_exact(query, self.ctx)], ids)
                self.assertEqual(changes.match_substring(query, self.ctx), [])

    def test_container(self):
        """Containers with head frontmatter, keys and name matching."""
        containers = self.provider("container", roots=["projects", "missing"],
                                   head_type="onepager")
        found = {s.id: s for s in containers.enumerate(self.ctx)}
        self.assertEqual(list(found), [CONTAINER_ALPHA, "projects/alphabet", "projects/beta"])
        alpha = found[CONTAINER_ALPHA]
        self.assertEqual(set(alpha.keys), {"tk-101", "tk-102", "tk-1010"})
        self.assertEqual(alpha.attrs[ATTR_CONTAINER], CONTAINER_ALPHA)
        self.assertEqual(alpha.attrs[ATTR_FRONTMATTER]["type"], "onepager")
        self.assertTrue(found["projects/alphabet"].archived)
        self.assertFalse(alpha.archived)
        cases = (
            ("exact", "ALPHA", [CONTAINER_ALPHA]),
            ("exact", "projects/ALPHA", [CONTAINER_ALPHA]),
            ("exact", "missing/alpha", []),
            ("substring", "alpha", [CONTAINER_ALPHA, "projects/alphabet"]),
            ("substring", "bet", ["projects/alphabet", "projects/beta"]),
            ("exact", "alp", []),
        )
        for mode, query, ids in cases:
            with self.subTest(mode=mode, query=query):
                method = containers.match_exact if mode == "exact" else containers.match_substring
                self.assertEqual([s.id for s in method(query, self.ctx)], ids)

    def test_frontmatter_doc(self):
        """Documents under the glob with frontmatter, excluding listed names."""
        notes = self.provider("frontmatter_doc", glob="notes/*.md", exclude=["README.md"])
        found = {s.id: s for s in notes.enumerate(self.ctx)}
        self.assertEqual(list(found), ["001 First question", "002 Closed question"])
        self.assertEqual(found["001 First question"].attrs[ATTR_FRONTMATTER]["review"],
                         "2026-10-01")
        self.assertTrue(found["002 Closed question"].archived)
        self.assertEqual([s.id for s in notes.match_substring("first", self.ctx)],
                         ["001 First question"])
        self.assertEqual(notes.match_exact("001 first question", self.ctx)[0].id,
                         "001 First question")


class ResolveTest(StoreTestCase):
    """Query resolution across the test profile pipelines."""

    def setUp(self):
        """Test profile runtime over the shared store."""
        super().setUp()
        build_store(self.sb)
        self.runtime = load_runtime(self.sb.store)
        self.ctx = Context(self.runtime.config, self.runtime.locale)

    def test_resolution_order(self):
        """Exact name, then key, then substring; several names are ambiguous."""
        cases = (
            ("alpha", [("project", CONTAINER_ALPHA)], False),
            ("tk-101", [("task", "c-101"), ("task", "c-101-more")], False),
            ("Tk-101", [("task", "c-101"), ("task", "c-101-more")], False),
            ("tk-777", [("task", "tk-777")], False),
            ("c-101-more", [("task", "c-101-more")], False),
            ("lphab", [("project", "projects/alphabet")], False),
            ("bet", [("project", "projects/alphabet"), ("project", "projects/beta")], True),
            ("zeta", [], False),
        )
        for query, expected, ambiguous in cases:
            with self.subTest(query=query):
                found = resolve(self.ctx, self.runtime.pipelines, query)
                self.assertEqual([(p.name, s.id) for p, s in found.matches], expected)
                self.assertEqual(found.ambiguous, ambiguous)


if __name__ == "__main__":
    unittest.main()
