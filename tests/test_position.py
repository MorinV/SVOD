"""position() rules and the status output on the test profile."""
import dataclasses
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from support import EXIT_OK, EXIT_USAGE, SharedStoreTestCase, doc

from svod.context import Context
from svod.gates import ArchivedGate, Gate, Status, unknown, verdict
from svod.loader import load_runtime
from svod.pipeline import GateRef, Pipeline, SEVERITY_BLOCK, Step, SubjectSpec
from svod.position import freeze, position
from svod.providers.openspec_change import DEFAULT_ARCHIVE, DEFAULT_ROOT, METADATA_FILE
from svod.render import render_position, status_report
from svod.subject import Subject

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
        self.assertFalse(any(line.startswith("  +") for line in out))
        pos = self.pos("tk-1")
        self.assertIsNone(pos.current)
        self.assertEqual(pos.violations, [])
        self.assertEqual(pos.steps, [])
        self.assertEqual(pos.marks, [])
        structured = self.sb.cli("status", "tk-1", "--format", "json")
        self.assertEqual(structured.returncode, EXIT_OK, structured.stderr)
        historical = json.loads(structured.stdout)["positions"][0]
        self.assertTrue(historical["done"])
        self.assertEqual(historical["done_outcome"]["gate"], "archived")
        self.assertEqual(historical["done_outcome"]["status"], "pass")
        for name in ("entries", "steps", "marks", "current_entries"):
            self.assertNotIn(name, historical)
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

    def test_unlabelled_steps_are_marked_by_id(self):
        """A step without a labelled gate is one mark of its own, in step order, by its id."""
        lines = self.status("full")
        marks = lines[1:lines.index("")]
        self.assertEqual(marks[-1], "  - close")
        self.assertEqual(len(marks), len(self.pos("full").steps))

    def test_step_text_period_is_not_doubled(self):
        """A step text ending with a period keeps one period inside the next-step line."""
        from svod.render import sentence
        self.assertEqual(sentence("Do it."), "Do it")
        self.assertEqual(sentence("Do it"), "Do it")
        self.assertEqual(sentence("Wait..."), "Wait...")

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

    def test_eff4_current_entry_capture_retains_block_and_failed_done(self):
        """S1 capture actual native outcomes before collector refactor, no reruns."""
        pos = self.pos("unready")
        self.assertEqual(pos.current.step.id, "close")
        self.assertTrue(pos.text_from_entry)
        self.assertEqual(len(getattr(pos, "current_entries", [])), 2,
                         "EFF-4 must retain both actual current entry outcomes")
        self.assertIs(pos.current_blocked, pos.current_entries[1])
        self.assertIsNone(pos.done)
        self.assertIsNotNone(pos.done_outcome)
        self.assertFalse(pos.done_outcome.passed)

    def test_eff4_done_early_return_does_not_evaluate_current_entries(self):
        """Successful done must retain its actual outcome but no current entry checks."""
        pos = self.pos("tk-1")
        self.assertIsNotNone(pos.done)
        self.assertIs(getattr(pos, "done_outcome", None), pos.done)
        self.assertEqual(pos.current_entries, [])
        self.assertIsNone(pos.current_blocked)

    def test_eff4_default_text_golden_before_refactor(self):
        """Native missing/default text bytes are independent of new JSON projection."""
        result = self.sb.cli("status", UNKNOWN_KEY)
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, UNKNOWN_TEXT + "\n")
        self.assertEqual(self.status("tk-777"),
                         ["Task tk-777", "", "  Next step: propose a change."])

    def test_several_changes_per_key_are_all_rendered(self):
        """All subjects matched by a key are rendered one after another."""
        pipeline = self.runtime.pipeline("task")
        subjects = pipeline.subject.impl.enumerate(self.ctx)[:2]
        lines = []
        for subject in subjects:
            lines += render_position(self.ctx.locale, position(self.ctx, pipeline, subject))
        self.assertIn("Task c-10", lines)
        self.assertIn("Task c-2", lines)


class ArchiveHistoryTest(unittest.TestCase):
    """Archive presentation must not replay the live workflow or attest delivery."""

    def pipeline(self, live_gate, done_gate=None):
        """Small declaration independent of installed workflow policy."""
        entry = GateRef("live", {}, "entry", severity=SEVERITY_BLOCK, impl=live_gate)
        check = GateRef("live", {}, "step", label="live", impl=live_gate)
        step = Step("live", "live.next", True, False, True, None, [check], [entry])
        done = GateRef("archived", {}, "done", text="history", impl=(
            done_gate if done_gate is not None else ArchivedGate()))
        return Pipeline("synthetic", Path("synthetic.yaml"), SubjectSpec("synthetic", None, {}),
                        [step], entry=[entry], done=done)

    def test_archived_native_done_skips_all_live_gates(self):
        """An archived outcome alone supplies history, never individual check PASS."""
        live = PassGate()
        pipeline = self.pipeline(live)
        subject = Subject("history", None, archived=True)
        for entries in (pipeline.entry, []):
            with (self.subTest(entry=bool(entries)),
                  patch.object(live, "evaluate", side_effect=AssertionError("live gate replay"))):
                pos = position(None, dataclasses.replace(pipeline, entry=entries), subject)
        self.assertTrue(pos.done.passed)
        self.assertIs(pos.done, pos.done_outcome)
        self.assertIs(pos.done.ref, pipeline.done)
        self.assertEqual(pos.text, "history")
        self.assertEqual(pos.facts, {})
        for name in ("entries", "steps", "marks", "current_entries", "unknown", "warnings",
                     "violations"):
            self.assertEqual(getattr(pos, name), [], name)
        for name in ("current", "blocked", "current_blocked", "do_not_touch"):
            self.assertIsNone(getattr(pos, name), name)

    def test_active_native_done_still_evaluates_live_gates(self):
        """The shortcut requires explicit provider archive metadata."""
        live = PassGate()
        pipeline = self.pipeline(live)
        for entries in (pipeline.entry, []):
            with self.subTest(entry=bool(entries)):
                with patch.object(live, "evaluate", side_effect=AssertionError("live gate replay")):
                    pos = position(None, dataclasses.replace(pipeline, entry=entries),
                                   Subject("active", None))
                self.assertIsNone(pos.done)
                self.assertIn("live gate replay", pos.unknown[0].result.reason)

    def test_active_arbitrary_done_retains_live_outcomes(self):
        """Existing successful active done still contains evaluated entries and marks."""
        live = PassGate()
        with patch.object(live, "evaluate", wraps=live.evaluate) as evaluate_live:
            pos = position(None, self.pipeline(live, PassGate()), Subject("active", None))
        self.assertEqual(evaluate_live.call_count, 2)
        self.assertTrue(pos.done.passed)
        self.assertEqual(len(pos.entries), 1)
        self.assertEqual(len(pos.steps), 1)
        self.assertTrue(pos.steps[0].passed)
        self.assertEqual(pos.marks, [("live", pos.steps[0].outcomes)])

    def test_arbitrary_done_still_evaluates_live_gates(self):
        """A done gate's name or PASS does not qualify it as native archive history."""
        for archived in (False, True):
            with self.subTest(archived=archived):
                live = PassGate()
                with patch.object(live, "evaluate", side_effect=AssertionError("live gate replay")):
                    pos = position(None, self.pipeline(live, PassGate()),
                                   Subject("subject", None, archived=archived))
                self.assertIn("live gate replay", pos.unknown[0].result.reason)

    def test_raising_gate_is_unknown_not_a_crash(self):
        """A gate that raises leaves its step unpassed and names the error as the reason."""
        live = PassGate()
        with patch.object(live, "evaluate", side_effect=ValueError("boom")):
            pos = position(None, self.pipeline(live, PassGate()), Subject("subject", None))
        self.assertEqual(pos.unknown[0].result.status, Status.UNKNOWN)
        self.assertEqual(pos.unknown[0].result.reason, "gate live raised ValueError: boom")
        self.assertFalse(pos.steps[0].passed)

    def test_failed_or_unknown_historical_done_is_not_success(self):
        """Retain the actual done result once; failure must not manufacture history."""
        for result in (verdict(False), unknown("archive unreadable")):
            with self.subTest(status=result.status):
                done = ArchivedGate()
                with patch.object(done, "evaluate", return_value=result) as evaluate_done:
                    pos = position(None, self.pipeline(PassGate(), done),
                                   Subject("history", None, archived=True))
                evaluate_done.assert_called_once()
                self.assertIsNone(pos.done)
                self.assertIs(pos.done_outcome.result, result)
                self.assertEqual(pos.unknown, [pos.done_outcome]
                                 if result.status is Status.UNKNOWN else [])


class FailGate(Gate):
    """Fails with one fact for any subject."""

    name = "fail"

    def evaluate(self, ctx, subject):
        """Always FAIL with a count."""
        return verdict(False, count=2)


class FreezeTest(unittest.TestCase):
    """freeze(): the first open gate of an applicable blocks_code step."""

    def ref(self, gate, text=None, when=None):
        """Step gate use of a synthetic gate."""
        return GateRef(gate.name, {}, "step", text=text, when=when, impl=gate)

    def step(self, step_id, gates, blocks_code=True, when=None):
        """Synthetic step with its own text."""
        return Step(step_id, f"{step_id}.text", True, False, blocks_code, None, gates, [],
                    when=when)

    def frozen(self, *steps, attrs=None):
        """freeze() over a synthetic pipeline of the steps."""
        pipeline = Pipeline("synthetic", Path("synthetic.yaml"),
                            SubjectSpec("synthetic", None, {}), list(steps))
        return freeze(None, pipeline, Subject("subject", None, attrs=attrs or {}))

    def test_all_gates_pass_is_not_frozen(self):
        """Passed blocks_code steps and open steps without blocks_code do not freeze."""
        self.assertIsNone(self.frozen(self.step("plan", [self.ref(FailGate())], False),
                                      self.step("approve", [self.ref(PassGate())])))

    def test_first_open_gate_gives_text_and_facts(self):
        """The gate's own text wins over the step text; facts come from that gate."""
        found = self.frozen(self.step("approve", [self.ref(PassGate()),
                                                  self.ref(FailGate(), text="gate.text")]))
        self.assertEqual((found.step.id, found.text, found.facts, found.gate),
                         ("approve", "gate.text", {"count": 2}, "fail"))
        self.assertFalse(found.unknown)
        self.assertIsNone(found.reason)
        found = self.frozen(self.step("approve", [self.ref(FailGate())]))
        self.assertEqual(found.text, "approve.text")

    def test_step_without_gates_is_open_with_its_text(self):
        """A gateless blocks_code step never passes: the step text, no facts, no gate."""
        found = self.frozen(self.step("approve", []))
        self.assertEqual((found.text, found.facts, found.gate), ("approve.text", {}, None))

    def test_unknown_gate_is_open_and_carries_reason(self):
        """A gate that raises is UNKNOWN: it freezes and names the error."""
        gate = PassGate()
        with patch.object(gate, "evaluate", side_effect=ValueError("boom")):
            found = self.frozen(self.step("approve", [self.ref(gate)]))
        self.assertTrue(found.unknown)
        self.assertEqual(found.reason, "gate pass raised ValueError: boom")

    def test_inapplicable_steps_and_gates_are_skipped(self):
        """A step or gate use whose when attribute is falsy does not freeze."""
        self.assertIsNone(self.frozen(self.step("approve", [self.ref(FailGate())], when="big"),
                                      self.step("review", [self.ref(FailGate(), when="big")])))
        found = self.frozen(self.step("approve", [self.ref(FailGate())], when="big"),
                            attrs={"big": True})
        self.assertEqual(found.step.id, "approve")

    def test_passed_later_step_does_not_freeze_unlike_status(self):
        """Status keeps the freeze line for a passed blocks_code step after an open one."""
        steps = (self.step("spec", [self.ref(FailGate())], False),
                 self.step("approve", [self.ref(PassGate())]))
        self.assertIsNone(self.frozen(*steps))
        pipeline = Pipeline("synthetic", Path("synthetic.yaml"),
                            SubjectSpec("synthetic", None, {}), list(steps))
        pos = position(None, pipeline, Subject("subject", None))
        self.assertEqual(pos.do_not_touch, {"step": "approve"})


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
