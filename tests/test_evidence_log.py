"""Evidence log: the line format, append and summary, the settings, and every point that writes."""
import datetime as dt
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import task_example as te
import test_local_workflow as local_fixture
from support import ENCODING, EXIT_OK, ME, StoreTestCase, TempStore

from svod import evidence_log as ev
from svod import hooks
from svod import local_runner
from svod.approval import MARK_FILE, write_mark
from svod.config import load_config
from svod.errors import LoadError
from svod.gates import unknown
from svod.pipeline import GateRef, Outcome
from svod.position import Position
from svod.subject import Subject

PIPELINE = "task"
SUBJECT = "openspec/changes/add-greeting"
CHANGE = te.CHANGE_NAME
LOG_NAME = "openspec__changes__add-greeting.jsonl"
FIELDS = ["at", "event", "subject", "pipeline", "step", "facts"]
LONG = "x" * 300
IGNORE_LINE = "evidence/"
WARNING_HEAD = "svod: the evidence log is not written"
LOCAL_TASK = "demo-task"


def events(entries):
    """Event codes of the entries, in order."""
    return [entry["event"] for entry in entries]


class RecordTest(StoreTestCase):
    """record, read and summary over a plain test store."""

    def test_line_format_and_append(self):
        """One JSON object per line, in the field order, appended; long strings cut."""
        self.assertTrue(ev.record(self.sb.store, PIPELINE, SUBJECT, ev.EVENT_POSITION_CHANGED,
                                  "spec", **{"from": None, "to": "spec"}))
        self.assertTrue(ev.record(self.sb.store, PIPELINE, SUBJECT, ev.EVENT_UNKNOWN_GATE,
                                  gate="g", reason=LONG))
        path = self.sb.store / ev.EVIDENCE_DIR / PIPELINE / LOG_NAME
        self.assertEqual(path, ev.log_path(self.sb.store, PIPELINE, SUBJECT))
        lines = path.read_text(encoding=ENCODING).splitlines()
        self.assertEqual(2, len(lines))
        first, second = (json.loads(line) for line in lines)
        self.assertEqual(FIELDS, list(first))
        self.assertIsNotNone(dt.datetime.fromisoformat(first["at"]).tzinfo)
        self.assertEqual({"event": "position_changed", "subject": SUBJECT, "pipeline": PIPELINE,
                          "step": "spec", "facts": {"from": None, "to": "spec"}},
                         {k: v for k, v in first.items() if k != "at"})
        self.assertEqual(ev.FACT_LIMIT, len(second["facts"]["reason"]))
        self.assertIsNone(second["step"])
        self.assertEqual(events(ev.read(self.sb.store, PIPELINE, SUBJECT)),
                         ["position_changed", "unknown_gate"])

    def test_store_log_unknown_event_and_torn_line(self):
        """No subject: the store log; an unknown code raises; a torn line is left out."""
        ev.record(self.sb.store, None, None, ev.EVENT_HOOK_DENIED, rule="mark", tool="Write")
        path = self.sb.store / ev.EVIDENCE_DIR / (ev.STORE_LOG + ev.LOG_SUFFIX)
        self.assertTrue(path.is_file())
        with path.open("a", encoding=ENCODING) as stream:
            stream.write('{"at": "2026-')
        self.assertEqual(["hook_denied"], events(ev.read(self.sb.store, None, None)))
        with self.assertRaises(ValueError):
            ev.record(self.sb.store, PIPELINE, SUBJECT, "made_up")
        self.assertEqual([], ev.read(self.sb.store, PIPELINE, "absent"))

    def test_summary(self):
        """Counts by event code and the sum of the seconds facts."""
        ev.record(self.sb.store, PIPELINE, SUBJECT, ev.EVENT_CHECKS_RUN, workspace="w", code=0,
                  seconds=1.25, passed=True)
        ev.record(self.sb.store, PIPELINE, SUBJECT, ev.EVENT_CHECKS_RUN, workspace="w", code=1,
                  seconds=0.5, passed=False)
        ev.record_action(self.sb.store, PIPELINE, SUBJECT, "lint", 0, 2.0)
        ev.record(self.sb.store, PIPELINE, SUBJECT, ev.EVENT_DELIVERED)
        self.assertEqual({"events": {"checks_run": 2, "action_run": 1, "delivered": 1},
                          "seconds": 3.75}, ev.summary(self.sb.store, PIPELINE, SUBJECT))
        action = ev.read(self.sb.store, PIPELINE, SUBJECT)[2]
        self.assertEqual({"action": "lint", "code": 0, "seconds": 2.0}, action["facts"])

    def test_write_error_is_said_once(self):
        """A file in the place of evidence/: nothing raised, one line on stderr."""
        self.sb.write(ev.EVIDENCE_DIR, "not a directory")
        with mock.patch.object(ev, "_warned", False), \
                mock.patch("sys.stderr") as stderr:
            for _ in range(2):
                self.assertFalse(ev.record(self.sb.store, PIPELINE, SUBJECT, ev.EVENT_DELIVERED))
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertEqual(1, written.count(WARNING_HEAD))


class SettingsTest(unittest.TestCase):
    """evidence in svod.yaml: enabled, commit and .gitignore, and its validation."""

    def store(self, value):
        """Store whose svod.yaml has the evidence block."""
        sb = TempStore(evidence=value)
        self.addCleanup(sb.cleanup)
        return sb

    def test_defaults_and_values(self):
        """Absent: on and committed; each key read."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        config = load_config(sb.store)
        self.assertEqual((True, True), (config.evidence_enabled, config.evidence_commit))
        config = load_config(self.store("{enabled: false, commit: false}").store)
        self.assertEqual((False, False), (config.evidence_enabled, config.evidence_commit))

    def test_errors(self):
        """A non-mapping, an unknown key and a non-bool value are load errors."""
        cases = (("[1]", "evidence must be a mapping"),
                 ("{keep: true}", "evidence: unknown key: keep"),
                 ("{commit: 1}", "evidence.commit must be a boolean"))
        for value, message in cases:
            with self.subTest(value=value):
                with self.assertRaises(LoadError) as found:
                    load_config(self.store(value).store)
                self.assertIn(message, str(found.exception))

    def test_disabled_writes_nothing(self):
        """enabled: false: no file and no directory."""
        sb = self.store("{enabled: false}")
        self.assertFalse(ev.record(sb.store, PIPELINE, SUBJECT, ev.EVENT_DELIVERED))
        self.assertFalse((sb.store / ev.EVIDENCE_DIR).exists())

    def test_uncommitted_adds_one_gitignore_line(self):
        """commit: false: evidence/ added once, after a line without a newline; kept if named."""
        sb = self.store("{commit: false}")
        sb.write(ev.GITIGNORE, "*.tmp")
        for _ in range(2):
            ev.record(sb.store, PIPELINE, SUBJECT, ev.EVENT_DELIVERED)
        self.assertEqual(f"*.tmp\n{IGNORE_LINE}\n",
                         (sb.store / ev.GITIGNORE).read_text(encoding=ENCODING))
        sb.write(ev.GITIGNORE, "/evidence/\n")
        ev.record(sb.store, PIPELINE, SUBJECT, ev.EVENT_DELIVERED)
        self.assertEqual("/evidence/\n", (sb.store / ev.GITIGNORE).read_text(encoding=ENCODING))

    def test_committed_leaves_gitignore(self):
        """commit: true (the default): no .gitignore is written."""
        sb = self.store("{commit: true}")
        ev.record(sb.store, PIPELINE, SUBJECT, ev.EVENT_DELIVERED)
        self.assertFalse((sb.store / ev.GITIGNORE).exists())


class UnknownGateTest(StoreTestCase):
    """unknown_gate: once per gate and reason at one position."""

    def test_once_per_position(self):
        """Two statuses at the same position write one unknown_gate; a move writes it again."""
        ref = GateRef(gate="merged", params={}, where="step")
        pos = Position(pipeline=SimpleNamespace(name=PIPELINE),
                       subject=Subject(id=SUBJECT, path=self.sb.store),
                       unknown=[Outcome(ref, unknown(LONG))])
        ctx = SimpleNamespace(root=self.sb.store)
        ev.note_position(ctx, pos)
        ev.note_position(ctx, pos)
        entries = ev.read(self.sb.store, PIPELINE, SUBJECT)
        self.assertEqual(["unknown_gate"], events(entries))
        self.assertEqual({"gate": "merged", "reason": LONG[:ev.FACT_LIMIT]}, entries[0]["facts"])


class TaskPointsTest(unittest.TestCase):
    """status, approve and the pre-tool hook of the task example write their events."""

    def setUp(self):
        """A proposed change in the task example, git isolated, no project directory."""
        self.sb = te.make_task_store()
        self.addCleanup(self.sb.cleanup)
        patcher = mock.patch.dict(os.environ, self.sb.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(hooks.PROJECT_ENV, None)
        te.propose(self.sb)

    def log(self):
        """Events of the change."""
        return ev.read(self.sb.store, PIPELINE, CHANGE)

    def status(self):
        """Run status of the key and check it succeeds."""
        out = self.sb.cli("status", te.KEY)
        self.assertEqual(EXIT_OK, out.returncode, out.stderr)

    def test_status_writes_only_changes(self):
        """First status, the same position again, then a move after the plan is written."""
        self.status()
        self.status()
        te.specify(self.sb)
        self.status()
        entries = self.log()
        self.assertEqual(["position_changed", "step_passed", "position_changed"], events(entries))
        self.assertEqual({"from": None, "to": "spec"}, entries[0]["facts"])
        self.assertEqual("spec", entries[1]["step"])
        self.assertEqual(("approve", {"from": "spec", "to": "approve"}),
                         (entries[2]["step"], entries[2]["facts"]))

    def test_approve_outcomes(self):
        """Refused without a mark, drift after a changed plan, then recorded with the approver."""
        te.specify(self.sb)
        self.sb.cli("approve", te.KEY)
        write_mark(self.sb.store, [te.KEY],
                   dt.datetime.now().astimezone() - dt.timedelta(minutes=2))
        self.sb.cli("approve", te.KEY)
        te.approve(self.sb)
        entries = self.log()
        self.assertEqual(["approval_refused", "approval_drift", "approval_recorded"],
                         events(entries))
        self.assertEqual({"reason": "no_mark"}, entries[0]["facts"])
        self.assertEqual("approve", entries[1]["step"])
        self.assertEqual(("approve", {"by": ME[0]}), (entries[2]["step"], entries[2]["facts"]))

    def deny(self, cwd, tool, data):
        """Answer of the pre-tool hook, which must be a refusal."""
        found = hooks.answer(hooks.EVENT_PRE_TOOL, {"cwd": str(cwd), "tool_name": tool,
                                                    "tool_input": data})
        self.assertEqual(hooks.DENY, json.loads(found)[hooks.OUTPUT][hooks.DECISION])

    def test_hook_denials(self):
        """Approval field and frozen code: the change's log; mark and broken: the store log."""
        te.specify(self.sb)
        self.sb.commit(message=f"{te.KEY}: plan")
        worktree = te.make_worktree(self.sb)
        self.deny(self.sb.store, "Edit", {"file_path": str(self.sb.store / te.META),
                                          "old_string": "a", "new_string": "plan_approved: x"})
        self.deny(self.sb.store, "Write", {"file_path": str(worktree / te.CODE_FILE),
                                           "content": "x"})
        self.deny(self.sb.store, "Write", {"file_path": str(self.sb.store / MARK_FILE),
                                           "content": "{}"})
        self.assertEqual([{"rule": "approval", "tool": "Edit"}, {"rule": "plan", "tool": "Write"}],
                         [entry["facts"] for entry in self.log()
                          if entry["event"] == "hook_denied"])
        self.sb.write("profile/pipelines/task.yaml", "pipeline: [\n")
        self.deny(self.sb.store, "Write", {"file_path": str(self.sb.parent / "elsewhere.txt"),
                                           "content": "x"})
        self.assertEqual([{"rule": "mark", "tool": "Write"}, {"rule": "broken", "tool": "Write"}],
                         [entry["facts"] for entry in ev.read(self.sb.store, None, None)])

    def test_status_survives_unwritable_log(self):
        """A file in the place of evidence/: status answers as before, one line on stderr."""
        self.sb.write(ev.EVIDENCE_DIR, "not a directory")
        with mock.patch.object(ev, "_warned", False):
            out = self.sb.cli("status", te.KEY)
        self.assertEqual(EXIT_OK, out.returncode)
        self.assertEqual(1, out.stderr.count(WARNING_HEAD))


class LocalPointsTest(unittest.TestCase):
    """local checks and deliver write checks_run and delivered."""

    def setUp(self):
        """The store of the local workflow tests, its contract approved."""
        self.fx = local_fixture.LocalWorkflowTest()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.fx.consent()

    def test_checks_and_deliver(self):
        """A passing run, then the delivery, each one line of the task log."""
        self.assertTrue(local_runner.checks(self.fx.root, LOCAL_TASK)["passed"])
        local_runner.deliver(self.fx.root, LOCAL_TASK)
        (path,) = (self.fx.root / ev.EVIDENCE_DIR).glob("*/*.jsonl")
        entries = [json.loads(line) for line in path.read_text(encoding=ENCODING).splitlines()]
        self.assertEqual(["approval_recorded", "checks_run", "delivered"], events(entries))
        facts = entries[1]["facts"]
        self.assertEqual({"workspace": self.fx.source.name, "code": 0, "passed": True},
                         {k: v for k, v in facts.items() if k != "seconds"})
        self.assertIsInstance(facts["seconds"], float)

    def test_failed_run_is_recorded(self):
        """A failing command: checks_run with its exit code and passed false."""
        self.fx.plan["command"] = [*self.fx.plan["command"][:2], "raise SystemExit(3)"]
        self.fx.save_plan()
        self.fx.consent()
        result = local_runner.checks(self.fx.root, LOCAL_TASK)
        self.assertFalse(result["passed"])
        (path,) = (self.fx.root / ev.EVIDENCE_DIR).glob("*/*.jsonl")
        last = json.loads(path.read_text(encoding=ENCODING).splitlines()[-1])
        self.assertEqual(("checks_run", 3, False),
                         (last["event"], last["facts"]["code"], last["facts"]["passed"]))


if __name__ == "__main__":
    unittest.main()
