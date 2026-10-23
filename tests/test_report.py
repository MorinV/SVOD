"""svod report: time in each step, approval rounds, failed checks, denials, actions."""
import datetime as dt
import json
import unittest
from tempfile import TemporaryDirectory

from support import EXIT_OK, EXIT_USAGE, core_text
from test_retro import START, TASK, WORK_A, WORK_B, WORK_C, RetroStore

from svod import evidence_log as ev
from svod import report

GONE = "work/tasks/gone"
NOW = START + dt.timedelta(hours=2)
WIDTH = 80


def entry(offset, event, step=None, **facts):
    """A log entry at START plus offset seconds; None as offset leaves the time out."""
    at = None if offset is None else (START + dt.timedelta(seconds=offset)).isoformat()
    return {"at": at, "event": event, "subject": WORK_A, "pipeline": TASK, "step": step,
            "facts": facts}


def move(offset, before, after):
    """A position_changed entry."""
    return entry(offset, ev.EVENT_POSITION_CHANGED, after, **{"from": before, "to": after})


class StepTimesTest(unittest.TestCase):
    def test_moves_give_the_time_of_each_step(self):
        """Consecutive moves bound a step; a step current twice is summed; the last is open."""
        entries = [move(0, None, "card"), move(60, "card", "implement"),
                   move(None, "implement", "checks"), move(660, "implement", "card"),
                   move(720, "card", "checks")]
        self.assertEqual([{"step": "card", "seconds": 120, "open": False},
                          {"step": "implement", "seconds": 600, "open": False},
                          {"step": "checks", "seconds": 7200 - 720, "open": True}],
                         report.step_times(entries, NOW))

    def test_a_move_to_no_step_closes_the_time(self):
        """Done: nothing counts until now."""
        entries = [move(0, None, "card"), move(30, "card", None)]
        self.assertEqual([{"step": "card", "seconds": 30, "open": False}],
                         report.step_times(entries, NOW))

    def test_no_moves_no_time(self):
        """A step never reported through status has no time."""
        self.assertEqual([], report.step_times([entry(0, ev.EVENT_STEP_PASSED, "card")], NOW))


class RecordReportTest(unittest.TestCase):
    def test_counters_of_one_record(self):
        """Approval rounds, failed checks, denials by rule and actions from the log."""
        entries = [
            entry(0, ev.EVENT_APPROVAL_DRIFT, "approve"),
            entry(1, ev.EVENT_APPROVAL_RECORDED, "approve", by="me"),
            entry(2, ev.EVENT_APPROVAL_REFUSED, "approve", reason="no_mark"),
            entry(3, ev.EVENT_CHECKS_RUN, service="app", code=1, seconds=2.0, passed=False),
            entry(4, ev.EVENT_CHECKS_RUN, workspace="app", code=0, seconds=1.0, passed=False),
            entry(5, ev.EVENT_CHECKS_RUN, service="app", code=0, seconds=1.0, passed=True),
            entry(6, ev.EVENT_HOOK_DENIED, rule="plan", tool="Edit"),
            entry(7, ev.EVENT_HOOK_DENIED, rule=None, tool="Bash"),
            entry(8, ev.EVENT_HOOK_DENIED, rule="plan", tool="Write"),
            entry(9, ev.EVENT_ACTION_RUN, "implement", action="start", code=0, seconds=1.5),
        ]
        found = report.record_report(TASK, WORK_A, entries, NOW)
        self.assertEqual({"rounds": 2, "recorded": 1, "drift": 1}, found["approvals"])
        self.assertEqual(3, found["checks"]["runs"])
        self.assertEqual([(1, False), (0, False)],
                         [(f["code"], f["passed"]) for f in found["checks"]["failed"]])
        self.assertEqual([{"rule": "plan", "count": 2}, {"rule": None, "count": 1}],
                         found["denials"])
        self.assertEqual([{"at": entries[-1]["at"], "step": "implement", "action": "start",
                           "code": 0, "seconds": 1.5}], found["actions"])
        self.assertEqual(len(entries), found["events"])

    def test_pipeline_sums_and_medians(self):
        """Steps and actions over the records having them; counters over every record."""
        one = report.record_report(TASK, WORK_A, [
            move(0, None, "card"), move(100, "card", None),
            entry(1, ev.EVENT_APPROVAL_DRIFT, "approve"),
            entry(2, ev.EVENT_ACTION_RUN, action="start", code=0, seconds=4.0),
            entry(3, ev.EVENT_ACTION_RUN, action="start", code=2, seconds=2.0)], NOW)
        two = report.record_report(TASK, WORK_B, [
            move(0, None, "card"), move(300, "card", None),
            entry(1, ev.EVENT_HOOK_DENIED, rule="main")], NOW)
        three = report.record_report(TASK, GONE, [move(0, None, "implement"),
                                                  move(50, "implement", None)], NOW)
        summary = report.pipeline_summary([one, two, three])
        self.assertEqual(3, summary["records"])
        self.assertEqual([{"step": "card", "records": 2, "sum": 400, "median": 200},
                          {"step": "implement", "records": 1, "sum": 50, "median": 50}],
                         summary["steps"])
        self.assertEqual({"sum": 1, "median": 0}, summary["approval_rounds"])
        self.assertEqual({"sum": 0, "median": 0}, summary["failed_checks"])
        self.assertEqual({"sum": 1, "median": 0, "rules": [{"rule": "main", "count": 1}]},
                         summary["denials"])
        self.assertEqual([{"action": "start", "records": 1, "runs": 2, "failed": 1, "sum": 6,
                           "median": 6}], summary["actions"])

    def test_clock(self):
        """Seconds as H:MM:SS, hours past a day included."""
        self.assertEqual(["0:00:00", "0:01:05", "1:00:00", "50:00:01"],
                         [report.clock(s) for s in (0, 65, 3600, 180001)])


class ReportCommandTest(unittest.TestCase):
    def setUp(self):
        """A store where alpha moved card -> implement and bravo is still at card."""
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = RetroStore(temp.name)
        self.sb.move(0, WORK_A, None, "card")
        self.sb.move(120, WORK_A, "card", "implement", passed=["card"])
        self.sb.record(200, WORK_A, ev.EVENT_CHECKS_RUN, service="app", code=1, seconds=3.0,
                       passed=False)
        self.sb.record(300, WORK_A, ev.EVENT_HOOK_DENIED, rule="plan", tool="Edit")
        self.sb.record(400, WORK_A, ev.EVENT_ACTION_RUN, "implement", action="start-task",
                       code=0, seconds=1.25)
        self.sb.move(3720, WORK_A, "implement", None, passed=["implement"])
        self.sb.move(0, WORK_B, None, "card")
        self.sb.record(0, GONE, ev.EVENT_APPROVAL_DRIFT, "approve")

    def run_report(self, *args):
        """Run svod report and expect success; its standard output."""
        done = self.sb.cli("report", *args)
        self.assertEqual(EXIT_OK, done.returncode, done.stdout + done.stderr)
        return done.stdout

    def test_one_record_as_text(self):
        """A few aligned lines, none wider than 80 columns."""
        out = self.run_report(WORK_A)
        lines = out.splitlines()
        self.assertEqual(core_text("report.record", id=WORK_A, pipeline=TASK), lines[0])
        self.assertEqual(["  step card          0:02:00",
                          "  step implement     1:00:00",
                          "  approval rounds    0: recorded 0, drift 0",
                          "  failed checks      1 of 1 (app 1)",
                          "  hook denials       1 (plan 1)",
                          "  action start-task  runs 1, failed 0, 0:00:01"], lines[1:])
        self.assertTrue(all(len(line) <= WIDTH for line in lines))

    def test_the_open_step_counts_until_now(self):
        """The current step of bravo is marked open."""
        out = self.run_report(WORK_B)
        self.assertIn(core_text("report.open", time="").strip(), out.splitlines()[1])

    def test_a_record_without_evidence(self):
        """An existing record with an empty log says so."""
        out = self.run_report(WORK_C)
        self.assertIn(core_text("report.no_evidence"), out)

    def test_json_holds_the_same_data(self):
        """--format json: the records with their steps and counters."""
        data = json.loads(self.run_report(WORK_A, "--format", "json"))
        self.assertIsNotNone(dt.datetime.fromisoformat(data["now"]).tzinfo)
        (found,) = data["records"]
        self.assertEqual((TASK, WORK_A), (found["pipeline"], found["id"]))
        self.assertEqual([("card", 120, False), ("implement", 3600, False)],
                         [(s["step"], s["seconds"], s["open"]) for s in found["steps"]])
        self.assertEqual([{"rule": "plan", "count": 1}], found["denials"])
        self.assertEqual(["start-task"], [a["action"] for a in found["actions"]])

    def test_all_reports_every_pipeline_with_history(self):
        """--all: a summary per pipeline, and the records of every log, removed ones too."""
        data = json.loads(self.run_report("--all", "--format", "json"))
        by_name = {p["pipeline"]: p for p in data["pipelines"]}
        self.assertIn("feature", by_name)
        task = by_name[TASK]
        self.assertEqual(3, task["summary"]["records"])
        self.assertEqual({WORK_A, WORK_B, GONE}, {r["id"] for r in task["records"]})
        self.assertEqual({"sum": 1, "median": 0}, task["summary"]["approval_rounds"])
        text = self.run_report("--all")
        self.assertIn(core_text("report.pipeline", pipeline=TASK, records=3), text)
        self.assertIn(core_text("report.record", id=GONE, pipeline=TASK), text)

    def test_wrong_arguments(self):
        """Neither or both of query and --all, or a query naming nothing."""
        for args in ((), (WORK_A, "--all"), ("no-such-work",)):
            with self.subTest(args=args):
                self.assertEqual(EXIT_USAGE, self.sb.cli("report", *args).returncode)


if __name__ == "__main__":
    unittest.main()
