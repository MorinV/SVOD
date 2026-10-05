"""position() rules and the status output on the test profile."""
import dataclasses
import unittest
from pathlib import Path

from support import EXIT_OK, EXIT_USAGE, SharedStoreTestCase, doc

from svod.context import Context
from svod.gates import Gate, verdict
from svod.loader import load_runtime
from svod.position import position
from svod.providers.openspec_change import DEFAULT_ARCHIVE, DEFAULT_ROOT, METADATA_FILE
from svod.render import render_position, status_report

CHANGES = Path(DEFAULT_ROOT)
ARCHIVE = CHANGES / DEFAULT_ARCHIVE
FULL_KEYS = "tk-1 tk-2 tk-3 tk-4 tk-5 tk-6 tk-7 tk-8 tk-9 tk-10"

NEXT = "  Next step: {}."
FREEZE = "  Do not touch the code: step approve has not passed."
FREEZE_BLOCKED = "  Do not touch the code: entry conditions are not met."
NO_DESIGN = "  Warning: the container has no design document, write it first."
NO_PYRAMID = "  Warning: the container has no test pyramid."
VIOLATIONS = "  Order violations:"
KNOWN_FILE = "known.txt"
KNOWN_KEYS = ("tk-40", "tk-777")
UNKNOWN_KEY = "tk-50"
UNKNOWN_TEXT = "Task tk-50: nothing is known about it in the store."


class PassGate(Gate):
    """Passes for any subject, found or not."""

    name = "pass"

    def evaluate(self, ctx, subject):
        """Always PASS."""
        return verdict(True)


def change(sb, name, key, spec=False, design=False, approved=False, progress=None,
           report=False, archived=False):
    """Change directory of the test profile with artifacts by flag."""
    root = (ARCHIVE if archived else CHANGES) / name
    meta = [f"ticket: {key}"] + (["approved: 2026-09-10"] if approved else [])
    sb.write(root / METADATA_FILE, "\n".join(meta) + "\n")
    if spec:
        sb.write(root / "specs" / "cap" / "spec.md", "# spec\n")
    if design:
        sb.write(root / "design.md", "# design\n")
    if progress is not None:
        sb.write(root / "progress.txt", progress)
    if report:
        sb.write(root / "report.md", "# report\n")


class PositionTest(SharedStoreTestCase):
    """Positions of task and project subjects."""

    @classmethod
    def build(cls, sb):
        """Containers and changes covering every rule."""
        sb.write("projects/full/Onepager.md", doc("onepager", FULL_KEYS))
        sb.write("projects/full/Design/solution.md", doc("design"))
        sb.write("projects/full/Design/pyramid.md", doc("test-strategy"))
        sb.write("projects/bare/Onepager.md", doc("onepager", "tk-20 tk-21"))
        sb.write("projects/nopyr/Onepager.md", doc("onepager", "tk-30"))
        sb.write("projects/nopyr/Design/solution.md", doc("design"))
        sb.write("projects/done/Onepager.md", doc("onepager", status="archived"))
        sb.write("projects/order/Onepager.md", doc("onepager"))
        sb.write("projects/order/Plan/wbs.md", doc("wbs"))
        sb.write("projects/closing/Onepager.md", doc("onepager", closing="yes"))
        sb.write("projects/closing/Research/q.md", "# q\n")
        for name in ("closing", "unready"):
            sb.write(f"projects/{name}/Design/solution.md", doc("design"))
            sb.write(f"projects/{name}/Design/pyramid.md", doc("test-strategy"))
            sb.write(f"projects/{name}/Plan/wbs.md", doc("wbs"))
        sb.write("projects/unready/Onepager.md", doc("onepager"))
        change(sb, "2026-01-01-c-1", "tk-1", spec=True, design=True, approved=True,
               report=True, archived=True)
        change(sb, "c-2", "tk-2")
        change(sb, "c-3", "tk-3", spec=True)
        change(sb, "c-4", "tk-4", spec=True, design=True)
        change(sb, "c-5", "tk-5", spec=True, design=True, approved=True)
        change(sb, "c-6", "tk-6", spec=True, design=True, approved=True, progress="2")
        change(sb, "c-7", "tk-7", spec=True, design=True, approved=True, progress="1",
               report=True)
        change(sb, "c-8", "tk-8", spec=True, design=True, approved=True, progress="x")
        change(sb, "c-9", "tk-9", spec=True, design=True, report=True)
        change(sb, "c-10", "tk-10", approved=True)
        change(sb, "c-21", "tk-21", spec=True)
        sb.write(KNOWN_FILE, " ".join(KNOWN_KEYS) + "\n")
        cls.runtime = load_runtime(sb.store)
        cls.ctx = Context(cls.runtime.config, cls.runtime.locale)

    def status(self, query):
        """Rendered status lines for a query that resolves to one subject."""
        report = status_report(self.ctx, self.runtime.pipelines, query)
        self.assertTrue(report.ok, report.err)
        return report.out

    def pos(self, query):
        """Position of the single subject the query resolves to."""
        pipeline = self.runtime.pipeline("project" if not query.startswith("tk-") else "task")
        subject = pipeline.subject.impl.resolve(query, self.ctx)[0]
        return position(self.ctx, pipeline, subject)

    def test_rule1_entry_always_even_without_subject(self):
        """Entry gates run for missing subjects; block stops the position; when skips."""
        cases = (
            ("tk-20", [NO_DESIGN, NO_PYRAMID],
             [NEXT.format("propose a change"), FREEZE, FREEZE_BLOCKED]),
            ("tk-21", [NO_DESIGN, FREEZE_BLOCKED, NO_PYRAMID], ["  Next step:", FREEZE]),
            ("tk-30", [NEXT.format("propose a change"), NO_PYRAMID],
             [NO_DESIGN, FREEZE, FREEZE_BLOCKED]),
            ("tk-40", [NEXT.format("propose a change")],
             [NO_DESIGN, NO_PYRAMID, FREEZE, FREEZE_BLOCKED]),
        )
        for query, present, absent in cases:
            with self.subTest(query=query):
                out = "\n".join(self.status(query))
                for line in present:
                    self.assertIn(line, out)
                for line in absent:
                    self.assertNotIn(line, out)
        blocked = self.pos("tk-21")
        self.assertIsNone(blocked.current)
        self.assertIsNotNone(blocked.blocked)

    def test_rule1_warning_follows_step(self):
        """A warn entry is printed after the next step."""
        out = self.status("tk-30")
        self.assertLess(out.index(NEXT.format("propose a change")), out.index(NO_PYRAMID))

    def test_rule2_done_is_terminal(self):
        """A done subject gets the terminal text and nothing about steps."""
        out = self.status("tk-1")
        self.assertIn(NEXT.format("task closed"), out)
        self.assertNotIn(FREEZE, out)
        self.assertNotIn(VIOLATIONS, out)
        self.assertIn("  + spec (1)   + design", out)
        pos = self.pos("tk-1")
        self.assertIsNone(pos.current)
        self.assertEqual(pos.violations, [])
        self.assertIn(NEXT.format("project closed"), self.status("done"))

    def test_rule3_position_and_text(self):
        """First open step; text from the first open gate, else from the step."""
        cases = (
            ("tk-2", "spec", "write the delta spec"),
            ("tk-3", "spec", "write design.md"),
            ("tk-4", "approve", "get the plan approved"),
            ("tk-5", "build", "start building in a workspace"),
            ("tk-6", "verify", "run the mandatory cases, report in the change"),
            ("tk-7", "review", "open a pull request"),
            ("tk-8", "build", "start building in a workspace"),
            ("tk-777", "propose", "propose a change"),
        )
        for query, step, text in cases:
            with self.subTest(query=query):
                self.assertEqual(self.pos(query).current.step.id, step)
                self.assertIn(NEXT.format(text), self.status(query))

    def test_rule3_gateless_step_never_passes(self):
        """The last step without gates stays the position when all else passed."""
        pos = self.pos("tk-7")
        self.assertEqual(pos.current.step.id, "review")
        self.assertFalse(pos.current.passed)

    def test_rule3_unknown_is_not_passed(self):
        """An UNKNOWN gate keeps the step open and is reported with its reason."""
        pos = self.pos("tk-8")
        self.assertEqual(pos.current.step.id, "build")
        self.assertIn("  could not check: not a number: x", self.status("tk-8"))

    def test_rule4_blocks_code(self):
        """The code freeze is printed up to and including the blocks_code step."""
        cases = (("tk-777", False), ("tk-2", True), ("tk-4", True), ("tk-5", False),
                 ("tk-7", False), ("tk-1", False))
        for query, frozen in cases:
            with self.subTest(query=query):
                out = self.status(query)
                self.assertEqual(FREEZE in out, frozen)

    def test_rule5_violations(self):
        """Passed step after an open required one: override text or general template."""
        cases = (
            ("tk-9", ["    - verified before the plan was approved"]),
            ("tk-10", ["    - step approve passed while the required step spec did not"]),
            ("order", ["    - step wbs passed while the required step design did not",
                       "    - step wbs passed while the required step pyramid did not"]),
        )
        for query, lines in cases:
            with self.subTest(query=query):
                out = self.status(query)
                self.assertIn(VIOLATIONS, out)
                self.assertEqual(out[out.index(VIOLATIONS) + 1:], lines)
        self.assertEqual([(v.later, v.earlier) for v in self.pos("order").violations],
                         [("wbs", "design"), ("wbs", "pyramid")])

    def test_rule6_marks(self):
        """Every labelled gate is marked for existing subjects; display replaces the mark."""
        cases = (
            ("tk-6", ["  + spec (1)   + design", "  + approved", "  progress +2", "  - report"]),
            ("full", ["  + onepager", "  - research (0)", "  + design", "  + pyramid",
                      "  - wbs"]),
            ("closing", ["  + research (1)"]),
        )
        for query, marks in cases:
            with self.subTest(query=query):
                out = self.status(query)
                for mark in marks:
                    self.assertIn(mark, out)
        self.assertEqual(self.pos("tk-777").marks, [])
        self.assertEqual(self.status("tk-777")[:2], ["Task tk-777", ""])

    def test_missing_subject_has_no_violations_and_no_freeze(self):
        """A subject the provider did not find gets neither violations nor the freeze."""
        pipeline = self.runtime.pipeline("task")
        approve = pipeline.step("approve")
        stub = dataclasses.replace(approve.gates[0], impl=PassGate())
        steps = [dataclasses.replace(s, gates=[stub]) if s.id == approve.id else s
                 for s in pipeline.steps]
        patched = dataclasses.replace(pipeline, steps=steps)
        cases = (("tk-777", False), ("tk-2", True))
        for query, exists in cases:
            with self.subTest(query=query):
                subject = pipeline.subject.impl.resolve(query, self.ctx)[0]
                self.assertEqual(subject.exists, exists)
                pos = position(self.ctx, patched, subject)
                self.assertEqual(bool(pos.violations), exists)
                self.assertEqual(pos.do_not_touch is not None, exists)
                self.assertEqual(pos.current.step.id, "propose" if not exists else "spec")

    def test_missing_gate(self):
        """A missing subject nothing is known about is an error; a known one gets a position."""
        cases = (
            (UNKNOWN_KEY, False, [UNKNOWN_TEXT]),
            ("tk-777", True, []),
            ("tk-20", True, []),
            ("tk-2", True, []),
        )
        for query, ok, err in cases:
            with self.subTest(query=query):
                report = status_report(self.ctx, self.runtime.pipelines, query)
                self.assertEqual(report.ok, ok)
                self.assertEqual(report.err, err)
                self.assertEqual(bool(report.out), ok)

    def test_optional_step_outside_position(self):
        """An optional step is marked but never becomes the position."""
        self.assertEqual(self.pos("full").current.step.id, "wbs")
        self.assertNotIn("research", [v.earlier for v in self.pos("order").violations])

    def test_step_entry(self):
        """A step entry runs only at that step: block replaces the text, UNKNOWN is reported."""
        unready = self.status("unready")
        self.assertIn("  Mark the onepager with closing before closing the container.", unready)
        self.assertNotIn("  Next step:", "\n".join(unready))
        closing = self.status("closing")
        self.assertIn(NEXT.format("close the container"), closing)
        self.assertTrue(any(line.startswith("  could not check: git") for line in closing))
        self.assertFalse(any("could not check" in line for line in self.status("full")))

    def test_several_changes_per_key_are_all_rendered(self):
        """All subjects matched by a key are rendered one after another."""
        pipeline = self.runtime.pipeline("task")
        subjects = pipeline.subject.impl.enumerate(self.ctx)[:2]
        lines = []
        for subject in subjects:
            lines += render_position(self.ctx.locale, position(self.ctx, pipeline, subject))
        self.assertIn("Task c-10", lines)
        self.assertIn("Task c-2", lines)


class StoreAheadTest(SharedStoreTestCase):
    """The step entry on git state with a real repository."""

    @classmethod
    def build(cls, sb):
        """A closable project in a store one commit ahead of origin."""
        sb.write("projects/closing/Onepager.md", doc("onepager", closing="yes"))
        sb.write("projects/closing/Design/solution.md", doc("design"))
        sb.write("projects/closing/Design/pyramid.md", doc("test-strategy"))
        sb.write("projects/closing/Plan/wbs.md", doc("wbs"))
        sb.init_git()
        sb.write("projects/closing/extra.md", "x\n")
        sb.commit()

    def test_ahead_warning_with_count(self):
        """The warning carries the number of commits ahead."""
        out = self.sb.cli("status", "closing")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn("  The store is ahead of origin by 1 commits.", out.stdout)


class StatusCommandTest(SharedStoreTestCase):
    """svod status as a black box."""

    @classmethod
    def build(cls, sb):
        """Two containers sharing a substring."""
        sb.write("projects/alpha/Onepager.md", doc("onepager"))
        sb.write("projects/alphabet/Onepager.md", doc("onepager"))

    def test_outputs(self):
        """Found, ambiguous and not found queries."""
        cases = (
            ("alpha", EXIT_OK, "Project projects/alpha", ""),
            ("lph", EXIT_USAGE, "", "Several subjects match:\n  projects/alpha\n"
                                    "  projects/alphabet\n"),
            ("zeta", EXIT_USAGE, "", "Nothing matches the query: zeta\n"),
            ("tk-60", EXIT_USAGE, "", "Task tk-60: nothing is known about it in the store.\n"),
        )
        for query, code, out, err in cases:
            with self.subTest(query=query):
                result = self.sb.cli("status", query)
                self.assertEqual(result.returncode, code)
                self.assertIn(out, result.stdout)
                self.assertEqual(result.stderr, err)


if __name__ == "__main__":
    unittest.main()
