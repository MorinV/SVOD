"""Core gates, results and the gate registry with profile modules."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import support
from support import StoreTestCase, doc, make_profile

from svod.approval import digest, normalized
from svod.config import load_config
from svod.context import Context
from svod.errors import LoadError, ParamError
from svod.gates import CORE_GATES, KeyGate, Status, build_registries, build_registry
from svod.providers import CORE_PROVIDERS
from svod.locale import load_locale
from svod.subject import ATTR_CONTAINER, ATTR_FRONTMATTER, Subject

TODAY = dt.date(2026, 9, 15)
YESTERDAY = "2026-09-14"
TOMORROW = "2026-09-16"
PASS, FAIL, UNKNOWN = Status.PASS, Status.FAIL, Status.UNKNOWN


class CoreGateTest(StoreTestCase):
    """Each core gate against small fixtures."""

    def setUp(self):
        """Store with one subject directory and one container."""
        super().setUp()
        self.ctx = Context(load_config(self.sb.store), today=TODAY)
        self.item = self.sb.store / "items" / "one"
        self.sb.write("items/one/design.md", "# d\n")
        self.sb.write("items/one/specs/a/spec.md", "# a\n")
        self.sb.write("items/one/specs/b/spec.md", "# b\n")
        self.sb.write("items/one/meta.yaml", "approved: 2026-09-10\nempty: ''\n")
        self.sb.write("items/one/broken.yaml", "approved: [\n")
        self.sb.write("items/one/records/r-1/notes.md", "# r\n")
        self.sb.write("boxes/alpha/Design/solution.md", doc("design"))
        self.sb.write("boxes/alpha/notes.md", "no frontmatter\n")

    def subject(self, **overrides):
        """Existing subject rooted at the item directory."""
        values = {"id": "one", "path": self.item}
        values.update(overrides)
        return Subject(**values)

    def run_gate(self, name, params=None, **subject):
        """Evaluate a core gate against the subject."""
        return CORE_GATES[name](params).evaluate(self.ctx, self.subject(**subject))

    def test_gates(self):
        """Status and facts of each gate in passing and failing situations."""
        fm = {ATTR_FRONTMATTER: {"status": "active", "review": TOMORROW, "old": YESTERDAY}}
        cases = (
            ("exists", None, {}, PASS, {}),
            ("exists", None, {"exists": False}, FAIL, {}),
            ("archived", None, {"archived": True}, PASS, {}),
            ("archived", None, {}, FAIL, {}),
            ("artifact", {"path": "design.md"}, {}, PASS, {"count": 1}),
            ("artifact", {"path": "tasks.md"}, {}, FAIL, {"count": 0}),
            ("artifact", {"glob": "specs/**/spec.md"}, {}, PASS, {"count": 2}),
            ("artifact", {"glob": "specs/**/spec.md", "min": 3}, {}, FAIL, {"count": 2}),
            ("artifact", {"path": "records/r-1"}, {}, PASS, {"count": 1}),
            ("artifact", {"glob": "records/*"}, {}, PASS, {"count": 1}),
            ("artifact", {"path": "design.md"}, {"exists": False}, FAIL, {"count": 0}),
            ("approval", {"marker": "approved", "file": "meta.yaml"}, {}, PASS,
             {"value": "2026-09-10", "marker": "approved", "by": "", "date": "2026-09-10"}),
            ("approval", {"marker": "empty", "file": "meta.yaml"}, {}, FAIL,
             {"value": "", "marker": "empty", "by": "", "date": "", "reason": "missing"}),
            ("approval", {"marker": "approved", "file": "absent.yaml"}, {}, FAIL,
             {"value": "", "marker": "approved", "by": "", "date": "", "reason": "missing"}),
            ("approval", {"marker": "approved", "file": "broken.yaml"}, {}, UNKNOWN,
             {"value": "", "marker": "approved", "by": "", "date": ""}),
            ("field", {"name": "status", "equals": "active"}, {"attrs": fm}, PASS,
             {"value": "active"}),
            ("field", {"name": "status", "equals": "archived"}, {"attrs": fm}, FAIL,
             {"value": "active"}),
            ("field", {"name": "status", "not_equals": "active"}, {"attrs": fm}, FAIL,
             {"value": "active"}),
            ("field", {"name": "status", "not_equals": "draft"}, {"attrs": fm}, PASS,
             {"value": "active"}),
            ("field", {"name": "outcome", "not_equals": "active"}, {"attrs": fm}, FAIL,
             {"value": ""}),
            ("field", {"name": "outcome", "present": True}, {"attrs": fm}, FAIL, {"value": ""}),
            ("field", {"name": "outcome", "present": False}, {"attrs": fm}, PASS, {"value": ""}),
            ("field", {"name": "review", "date_not_past": True}, {"attrs": fm}, PASS,
             {"value": TOMORROW}),
            ("field", {"name": "old", "date_not_past": True}, {"attrs": fm}, FAIL,
             {"value": YESTERDAY}),
            ("field", {"name": "old", "date_not_past": False}, {"attrs": fm}, PASS,
             {"value": YESTERDAY}),
            ("field", {"name": "status", "date_not_past": True}, {"attrs": fm}, FAIL,
             {"value": "active"}),
            ("doc_type", {"type": "design", "scope": "container"},
             {"attrs": {ATTR_CONTAINER: "boxes/alpha"}}, PASS, {}),
            ("doc_type", {"type": "wbs", "scope": "container"},
             {"attrs": {ATTR_CONTAINER: "boxes/alpha"}}, FAIL, {}),
            ("doc_type", {"type": "design", "scope": "container"}, {}, FAIL, {}),
            ("doc_type", {"type": "design"}, {"path": self.sb.store / "boxes" / "alpha"},
             PASS, {}),
        )
        for name, params, subject, status, facts in cases:
            with self.subTest(gate=name, params=params, subject=subject):
                result = self.run_gate(name, params, **subject)
                self.assertEqual(result.status, status)
                self.assertEqual(result.facts, facts)
                if status is UNKNOWN:
                    self.assertTrue(result.reason)

    def test_param_validation(self):
        """Bad params are rejected at construction."""
        cases = (
            ("artifact", {}),
            ("artifact", {"path": "a", "glob": "b"}),
            ("artifact", {"path": "a", "min": 0}),
            ("artifact", {"path": "a", "min": True}),
            ("artifact", {"path": "a", "min": 2}),
            ("approval", {"marker": "m"}),
            ("approval", {"marker": "m", "file": "f", "bind": []}),
            ("approval", {"marker": "m", "file": "f", "bind": "design.md"}),
            ("approval", {"marker": "m", "file": "f", "bind": [""]}),
            ("approval", {"marker": "m", "file": "f", "ignore": ["^x"]}),
            ("approval", {"marker": "m", "file": "f", "bind": ["a"], "ignore": []}),
            ("approval", {"marker": "m", "file": "f", "bind": ["a"], "ignore": "^x"}),
            ("approval", {"marker": "m", "file": "f", "bind": ["a"], "ignore": ["("]}),
            ("approval", {"marker": "m", "file": "f", "strip": ["x"]}),
            ("approval", {"marker": "m", "file": "f", "bind": ["a"], "strip": []}),
            ("approval", {"marker": "m", "file": "f", "bind": ["a"], "strip": "x"}),
            ("approval", {"marker": "m", "file": "f", "bind": ["a"], "strip": ["["]}),
            ("field", {"name": "n"}),
            ("field", {"name": "n", "equals": "a", "present": True}),
            ("field", {"name": "n", "equals": "a", "not_equals": "b"}),
            ("field", {"name": "n", "present": "yes"}),
            ("doc_type", {"type": "t", "scope": "galaxy"}),
            ("exists", {"anything": 1}),
            ("git_pushed", {"repo": 1}),
        )
        for name, params in cases:
            with self.subTest(gate=name, params=params):
                with self.assertRaises(ParamError):
                    CORE_GATES[name](params)


class BoundApprovalTest(StoreTestCase):
    """approval with bind: missing, legacy, drift and a matching version."""

    BIND = ["design.md", "specs/**/spec.md"]
    PARAMS = {"marker": "approved", "file": "meta.yaml", "bind": BIND}

    def setUp(self):
        """Subject directory with bound files."""
        super().setUp()
        self.ctx = Context(load_config(self.sb.store), today=TODAY)
        self.item = self.sb.store / "items" / "one"
        self.sb.write("items/one/design.md", "# d\n")
        self.sb.write("items/one/specs/a/spec.md", "# a\n")
        self.sb.write("items/one/notes.md", "# not bound\n")

    def evaluate(self, meta):
        """Result of the bound gate for the given metadata text."""
        self.sb.write("items/one/meta.yaml", meta)
        return CORE_GATES["approval"](self.PARAMS).evaluate(
            self.ctx, Subject(id="one", path=self.item))

    def test_reasons(self):
        """Every failure names its reason; only all three fields with the current digest pass."""
        sha = digest(self.item, self.BIND)
        cases = (
            ("other: 1\n", FAIL, "missing"),
            ("approved: 2026-09-10\n", FAIL, "legacy"),
            ("approved: 2026-09-10\napproved_by: me\n", FAIL, "legacy"),
            (f"approved: 2026-09-10\napproved_sha: {sha}\n", FAIL, "legacy"),
            ("approved: 2026-09-10\napproved_by: me\napproved_sha: 0bad\n", FAIL, "drift"),
            (f"approved: 2026-09-10\napproved_by: me\napproved_sha: {sha}\n", PASS, None),
        )
        for meta, status, reason in cases:
            with self.subTest(meta=meta):
                result = self.evaluate(meta)
                self.assertEqual(result.status, status)
                self.assertEqual(result.facts.get("reason"), reason)

    def test_drift_facts_and_unbound_files(self):
        """A bound file edit is drift with who and when; an unbound one changes nothing."""
        sha = digest(self.item, self.BIND)
        meta = f"approved: 2026-09-10\napproved_by: me\napproved_sha: {sha}\n"
        self.sb.write("items/one/notes.md", "# edited\n")
        self.assertEqual(self.evaluate(meta).status, PASS)
        self.sb.write("items/one/specs/b/spec.md", "# new capability\n")
        result = self.evaluate(meta)
        self.assertEqual((result.status, result.facts["reason"], result.facts["by"],
                          result.facts["date"]), (FAIL, "drift", "me", "2026-09-10"))


class IgnoredLinesApprovalTest(StoreTestCase):
    """approval with bind and ignore: blank and ignored lines do not change the version."""

    BIND = ["design.md", "tasks.md"]
    IGNORE = [r"^PR \[#(\d+)\]\(\S*/pull-requests/\1\)"]
    PARAMS = {"marker": "approved", "file": "meta.yaml", "bind": BIND, "ignore": IGNORE}
    TASKS = "# tasks\n\n## PR 1\n\n- [ ] 1.1 do\n"
    LINK = "PR [#7](https://git.example.com/repos/r/pull-requests/7), opened 2026-09-25"

    def setUp(self):
        """Subject directory with bound files."""
        super().setUp()
        self.ctx = Context(load_config(self.sb.store), today=TODAY)
        self.item = self.sb.store / "items" / "one"
        self.sb.write("items/one/design.md", "# d\n")
        self.sb.write("items/one/tasks.md", self.TASKS)

    def evaluate(self, sha):
        """Result of the gate for an approval carrying the digest."""
        self.sb.write("items/one/meta.yaml",
                      f"approved: 2026-09-10\napproved_by: me\napproved_sha: {sha}\n")
        return CORE_GATES["approval"](self.PARAMS).evaluate(
            self.ctx, Subject(id="one", path=self.item))

    def test_without_ignore_the_digest_is_raw(self):
        """No ignore and an empty ignore give the sha256 of the raw content, as before."""
        raw = digest(self.item, self.BIND)
        self.assertEqual(digest(self.item, self.BIND, None), raw)
        self.assertEqual(digest(self.item, self.BIND, []), raw)
        self.assertNotEqual(digest(self.item, self.BIND, self.IGNORE), raw)

    def test_edits_and_the_version(self):
        """A link line and blank lines keep the normalized version; a content line changes it."""
        cases = (
            ("link", self.TASKS.replace("## PR 1\n\n", f"## PR 1\n\n{self.LINK}\n\n"), True),
            ("blank lines", self.TASKS.replace("\n", "\n \n\t\n"), True),
            ("no final newline", self.TASKS.rstrip("\n"), True),
            ("link of another number",
             self.TASKS + self.LINK.replace("pull-requests/7", "pull-requests/8"), False),
            ("indented link", self.TASKS + " " + self.LINK, False),
            ("content", self.TASKS.replace("do", "do more"), False),
        )
        before = digest(self.item, self.BIND, self.IGNORE)
        for name, text, same in cases:
            with self.subTest(edit=name):
                self.sb.write("items/one/tasks.md", text)
                self.assertEqual(digest(self.item, self.BIND, self.IGNORE) == before, same)
                self.assertEqual(self.evaluate(before).passed, same)

    def test_raw_digest_is_still_accepted(self):
        """An approval with the raw digest passes while the files are unchanged, drifts after."""
        raw = digest(self.item, self.BIND)
        self.assertEqual(self.evaluate(raw).status, PASS)
        self.sb.write("items/one/tasks.md", self.TASKS.replace("do", "do more"))
        result = self.evaluate(raw)
        self.assertEqual((result.status, result.facts["reason"]), (FAIL, "drift"))

    def test_normalized_digest_needs_ignore(self):
        """Without ignore only the raw digest passes, the normalized one drifts."""
        params = {k: v for k, v in self.PARAMS.items() if k != "ignore"}
        sha = digest(self.item, self.BIND, self.IGNORE)
        self.sb.write("items/one/meta.yaml",
                      f"approved: 2026-09-10\napproved_by: me\napproved_sha: {sha}\n")
        result = CORE_GATES["approval"](params).evaluate(self.ctx, Subject(id="one", path=self.item))
        self.assertEqual((result.status, result.facts["reason"]), (FAIL, "drift"))

    def test_normalized(self):
        """Blank and matched lines go, the rest keeps its order joined by newlines."""
        cases = (
            (b"a\n\nb\n", [], b"a\nb"),
            (b"a\n  \r\nPR [#1](x/pull-requests/1) tail\nb", self.IGNORE, b"a\nb"),
            (b"PR [#1](x/pull-requests/2)\n", self.IGNORE, b"PR [#1](x/pull-requests/2)"),
        )
        for content, ignore, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(normalized(content, ignore), expected)


class StrippedApprovalTest(StoreTestCase):
    """approval with strip: links, dates and statuses cut out of lines do not change the version."""

    BIND = ["design.md", "tasks.md"]
    IGNORE = [r"^waits: "]
    STRIP = [r"(?:PR )?\[#\d+\]\([^)\s]*/pull-requests/\d+\)",
             r"(?:,\s*)?opened \d{4}-\d{2}-\d{2}",
             r",\s*merged(?: and deployed)?(?: \d{4}-\d{2}-\d{2})?",
             r"^Link:(?:\s*not opened$)?"]
    PARAMS = {"marker": "approved", "file": "meta.yaml", "bind": BIND, "ignore": IGNORE,
              "strip": STRIP}
    URL = "https://git.example.com/repos/r/pull-requests/{n}"
    TASKS = ("# tasks\n\n| # | PR | depends |\n|---|---|---|\n| 1 | `svc` | PR 0 merged |\n\n"
             "## PR 1\n\nLink: not opened\n\n- [ ] 1.1 do\n  - nested step\n")

    def setUp(self):
        """Subject directory with bound files."""
        super().setUp()
        self.ctx = Context(load_config(self.sb.store), today=TODAY)
        self.item = self.sb.store / "items" / "one"
        self.sb.write("items/one/design.md", "# d\n")
        self.sb.write("items/one/tasks.md", self.TASKS)

    def link(self, number, tail=""):
        """Markdown link to a pull request with an optional tail."""
        return f"[#{number}]({self.URL.format(n=number)}){tail}"

    def evaluate(self, sha, params=None):
        """Result of the gate for an approval carrying the digest."""
        self.sb.write("items/one/meta.yaml",
                      f"approved: 2026-09-10\napproved_by: me\napproved_sha: {sha}\n")
        return CORE_GATES["approval"](params or self.PARAMS).evaluate(
            self.ctx, Subject(id="one", path=self.item))

    def current(self):
        """Digest under the declared ignore and strip."""
        return digest(self.item, self.BIND, self.IGNORE, self.STRIP)

    def test_mechanical_and_meaningful_edits(self):
        """Links, dates, statuses and waits keep the version; a word of meaning changes it."""
        opened = f"Link: {self.link(7)}, opened 2026-09-24"
        cases = (
            ("link line", self.TASKS.replace("Link: not opened", opened), True),
            ("date changed", self.TASKS.replace(
                "Link: not opened", opened.replace("09-24", "09-25")), True),
            ("merged", self.TASKS.replace("Link: not opened", f"{opened}, merged"), True),
            ("merged and deployed with date", self.TASKS.replace(
                "Link: not opened", f"{opened}, merged and deployed 2026-09-28"), True),
            ("link in a table cell", self.TASKS.replace("`svc` |", f"`svc` {self.link(8)} |"),
             True),
            ("link after an item", self.TASKS.replace("1.1 do", f"1.1 do — PR {self.link(9)}"),
             True),
            ("link in a nested item", self.TASKS.replace(
                "nested step", f"nested step {self.link(9)}"), True),
            ("waits line", self.TASKS.replace("- [ ] 1.1", "waits: PR 2\n\n- [ ] 1.1"), True),
            ("dependency cell", self.TASKS.replace("PR 0 merged", "PR 0"), False),
            ("meaning after the link", self.TASKS.replace(
                "Link: not opened", f"{opened}, based on PR 6"), False),
            ("content", self.TASKS.replace("do", "do more"), False),
        )
        before = self.current()
        for name, text, same in cases:
            with self.subTest(edit=name):
                self.sb.write("items/one/tasks.md", text)
                self.assertEqual(self.current() == before, same)
                self.assertEqual(self.evaluate(before).passed, same)

    def test_meaning_after_the_link_survives_status_edits(self):
        """What follows the link keeps its version while the statuses around it change."""
        base = f"Link: {self.link(26)}, opened 2026-09-28, based on PR 6"
        self.sb.write("items/one/tasks.md", self.TASKS.replace("Link: not opened", base))
        before = self.current()
        for text in (f"{base}, merged", base.replace("09-28", "09-29"),
                     base.replace("Link: ", "")):
            with self.subTest(line=text):
                self.sb.write("items/one/tasks.md", self.TASKS.replace("Link: not opened", text))
                self.assertEqual(self.current(), before)

    def test_older_digests_are_accepted(self):
        """Ignore-only and raw digests pass while the files are unchanged and drift after."""
        older = (digest(self.item, self.BIND, self.IGNORE), digest(self.item, self.BIND))
        for sha in older:
            with self.subTest(sha=sha):
                self.assertNotEqual(sha, self.current())
                self.assertEqual(self.evaluate(sha).status, PASS)
        self.sb.write("items/one/tasks.md",
                      self.TASKS.replace("Link: not opened", f"Link: {self.link(7)}"))
        for sha in older:
            with self.subTest(sha=sha, edited=True):
                result = self.evaluate(sha)
                self.assertEqual((result.status, result.facts["reason"]), (FAIL, "drift"))

    def test_stripped_digest_needs_strip(self):
        """Without strip the digest recorded with it drifts."""
        params = {k: v for k, v in self.PARAMS.items() if k != "strip"}
        result = self.evaluate(self.current(), params)
        self.assertEqual((result.status, result.facts["reason"]), (FAIL, "drift"))

    def test_normalized(self):
        """Cut lines are tidied, indent kept, and dropped when only separators are left."""
        cases = (
            (b"Link: not opened\n", b""),
            (b"Link: [#1](x/pull-requests/1), opened 2026-09-24, merged\n", b""),
            (b"Link: [#2](x/pull-requests/2), opened 2026-09-24; gate PASS.\n", b"gate PASS."),
            (b"| 1 | `a` [#3](x/pull-requests/3) | b |\n", b"| 1 | `a` | b |"),
            (b"  - step [#4](x/pull-requests/4).\n", b"  - step."),
            (b"waits: PR 1\n...\n", b"..."),
            (b"PR 3 merged\n", b"PR 3 merged"),
            (b"svc ([#5](x/pull-requests/5)) done\n", b"svc done"),
            (b"wave ([T-1](x), PR [#6](x/pull-requests/6))\n", b"wave ([T-1](x))"),
        )
        for content, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(normalized(content, self.IGNORE, self.STRIP), expected)


class GitPushedGateTest(StoreTestCase):
    """git_pushed against a real repository."""

    def evaluate(self):
        """Evaluate the gate at the store root."""
        ctx = Context(load_config(self.sb.store))
        return CORE_GATES["git_pushed"]().evaluate(ctx, Subject(id="x", path=None))

    def test_pushed_ahead_and_failure(self):
        """Zero ahead passes, commits ahead fail with a count, no repository is UNKNOWN."""
        unknown = self.evaluate()
        self.assertEqual(unknown.status, UNKNOWN)
        self.assertTrue(unknown.reason)
        self.sb.init_git()
        self.assertEqual(self.evaluate().status, PASS)
        self.sb.write("new.md", "x\n")
        self.sb.commit()
        ahead = self.evaluate()
        self.assertEqual((ahead.status, ahead.facts), (FAIL, {"count": 1}))

    def test_failure_reason_is_one_line(self):
        """A missing default branch is UNKNOWN with the first line of git stderr as reason."""
        self.sb.init_git(remote=False)
        unknown = self.evaluate()
        self.assertEqual(unknown.status, UNKNOWN)
        self.assertTrue(unknown.reason)
        self.assertNotIn("\n", unknown.reason)


class RegistryTest(unittest.TestCase):
    """Loading profile gate modules."""

    def profile(self, gates):
        """Temporary profile with gate modules."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return make_profile(Path(tmp.name), {}, "", gates=gates)

    def test_test_profile_gates_are_registered(self):
        """The toy gates join the core ones."""
        registry = build_registry(support.TEST_PROFILE)
        self.assertTrue(set(CORE_GATES) < set(registry))
        self.assertTrue(issubclass(registry["ticket"], KeyGate))
        self.assertIn("progress", registry)

    def test_private_modules_are_skipped(self):
        """Modules starting with an underscore are helpers, not gate modules."""
        registry = build_registry(self.profile({"_helper.py": "VALUE = 1\n"}))
        self.assertEqual(set(registry), set(CORE_GATES))

    def test_registry_errors(self):
        """Collisions and malformed modules fail the load."""
        cases = (
            ("core collision", {"a.py": """
                from svod.gates import Gate
                class Exists(Gate):
                    name = "exists"
                GATES = {"exists": Exists}
             """}, "already registered"),
            ("profile collision", {"a.py": """
                from svod.gates import Gate
                class A(Gate):
                    name = "same"
                GATES = {"same": A}
             """, "b.py": """
                from svod.gates import Gate
                class B(Gate):
                    name = "same"
                GATES = {"same": B}
             """}, "already registered"),
            ("no GATES", {"a.py": "VALUE = 1\n"}, "GATES mapping"),
            ("not a gate", {"a.py": "GATES = {'x': object}\n"}, "not a Gate subclass"),
            ("name mismatch", {"a.py": """
                from svod.gates import Gate
                class A(Gate):
                    name = "other"
                GATES = {"mine": A}
             """}, "declares name"),
            ("import failure", {"a.py": "raise RuntimeError('boom')\n"}, "import failed"),
            ("provider core collision", {"a.py": """
                from svod.providers import Provider
                class P(Provider):
                    name = "container"
                GATES = {}
                PROVIDERS = {"container": P}
             """}, "provider name already registered"),
            ("not a provider", {"a.py": "GATES = {}\nPROVIDERS = {'x': object}\n"},
             "not a Provider subclass"),
            ("providers not a mapping", {"a.py": "GATES = {}\nPROVIDERS = [1]\n"},
             "PROVIDERS must map"),
        )
        for name, gates, message in cases:
            with self.subTest(name=name):
                with self.assertRaises(LoadError) as ctx:
                    build_registry(self.profile(gates))
                self.assertIn(message, str(ctx.exception))


    def test_profile_provider(self):
        """PROVIDERS of a profile module join the core providers."""
        profile = self.profile({"a.py": """
            from svod.gates import Gate
            from svod.providers import Provider
            class Shelf(Provider):
                name = "shelf"
            GATES = {}
            PROVIDERS = {"shelf": Shelf}
         """})
        gates, providers = build_registries(profile)
        self.assertEqual(set(gates), set(CORE_GATES))
        self.assertEqual(set(providers), set(CORE_PROVIDERS) | {"shelf"})


class ToyGateTest(StoreTestCase):
    """Profile gates are used through the same interface."""

    def test_progress_and_ticket(self):
        """The toy progress gate reads its counter; the ticket gate recognises keys."""
        registry = build_registry(support.TEST_PROFILE)
        config = load_config(self.sb.store)
        ctx = Context(config, load_locale("en", config.profile))
        path = self.sb.store / "work"
        path.mkdir()
        progress = registry["progress"]()
        cases = (("", FAIL, 0), ("3", PASS, 3), ("x", UNKNOWN, 0))
        for text, status, ahead in cases:
            with self.subTest(text=text):
                if text:
                    (path / "progress.txt").write_text(text, encoding="utf-8")
                result = progress.evaluate(ctx, Subject(id="w", path=path))
                self.assertEqual((result.status, result.facts["ahead"]), (status, ahead))
        self.assertEqual(progress.evaluate(ctx, Subject(id="w", path=path)).status, UNKNOWN)
        ticket = registry["ticket"]()
        self.assertEqual(ticket.match("see tk-12 please"), "tk-12")
        self.assertIsNone(ticket.match("xtk-12"))
        self.assertEqual(ticket.find("tk-1, tk-22 and tk-1"), {"tk-1", "tk-22"})
        keyed = ticket.evaluate(ctx, Subject(id="c", path=None, keys=frozenset({"tk-1"})))
        self.assertEqual(keyed.status, PASS)


if __name__ == "__main__":
    unittest.main()
