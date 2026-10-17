"""Retrospective: each core rule over a synthetic evidence log, decisions and profile rules."""
import datetime as dt
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from support import CLI_ENV, ENCODING, EXIT_OK, EXIT_USAGE, ME, dedent, git_env, run_cli

from svod import evidence_log as ev
from svod.retro import decisions, rules
from svod.yamlio import read_yaml

TASK = "task"
FEATURE = "feature"
TASKS = "work/tasks"
WORK_A = "work/tasks/alpha"
WORK_B = "work/tasks/bravo"
WORK_C = "work/tasks/charlie"
WORK_D = "work/tasks/delta"
HOTFIX_A = "work/tasks/fix-one"
HOTFIX_B = "work/tasks/fix-two"
LOGIN = "work/features/login"
TASK_SKILL = "skills/svod-task/SKILL.md"
TASK_FILE = "profile/pipelines/task.yaml"
START = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.timezone.utc)
INSTANT_SEC = 10
SLOW_SEC = 120
LONG_SEC = 900
DECISIONS = "evidence/decisions.yaml"
NOTE = "the checks write a cache"

CARD = """\
---
type: card
kind: {kind}
key:
services: [app]
parent:
cause: {cause}
tags: []
status: open
---

# {name}
"""

ALWAYS_RULE = '''\
"""A profile rule that always proposes one note for the work."""
from svod.retro.rules import Rule, change


class AlwaysRule(Rule):
    """Proposes one note per work."""

    name = "always"

    def evaluate(self, ctx, subject, log, graph):
        """One proposal with the number of log entries."""
        return [self.propose("note", {"entries": len(log.entries)},
                             change("README.md", "Plain text of the change."),
                             text_key="Count the entries.")]


RULES = {AlwaysRule.name: AlwaysRule}
'''

CLASHING_RULE = '''\
from svod.retro.rules import Rule


class Dirty(Rule):
    name = "dirty_checks"


RULES = {Dirty.name: Dirty}
'''


class Clock:
    """Stand-in for datetime.datetime in the evidence log: now() is a set moment."""

    def __init__(self, when):
        """Remember the moment."""
        self.when = when

    def now(self, tz=None):
        """The set moment."""
        return self.when


class RetroStore:
    """A store made from the standard template with a few work records and git."""

    def __init__(self, temp):
        """Scaffold the store, add the records, make it a git repository."""
        from svod.scaffold import scaffold

        self.base = Path(temp)
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {**os.environ, **git_env(self.home), **CLI_ENV,
                    "GIT_AUTHOR_NAME": ME[1], "GIT_AUTHOR_EMAIL": ME[0],
                    "GIT_COMMITTER_NAME": ME[1], "GIT_COMMITTER_EMAIL": ME[0]}
        self.store = scaffold(self.base / "store", "standard")
        for rel in (WORK_A, WORK_B, WORK_C, WORK_D):
            self.card(rel, "task")
        self.card(HOTFIX_A, "hotfix", LOGIN)
        self.card(HOTFIX_B, "hotfix", LOGIN)
        self.card(LOGIN, "feature")
        subprocess.run(["git", "-C", str(self.store), "init", "-q", "-b", "main"], env=self.env,
                       check=True, capture_output=True)

    def card(self, rel, kind, cause=""):
        """Write the card of a work record."""
        path = self.store / rel / "card.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CARD.format(kind=kind, cause=cause, name=rel), encoding=ENCODING)

    def record(self, offset, subject, event, step=None, pipeline=TASK, **facts):
        """Append an event to the log of the subject at START plus offset seconds."""
        clock = SimpleNamespace(datetime=Clock(START + dt.timedelta(seconds=offset)))
        with mock.patch.object(ev, "dt", clock):
            assert ev.record(self.store, pipeline, subject, event, step, **facts)

    def move(self, seconds, subject, before, after, passed=()):
        """A position change from before to after, the passed steps first, as status writes."""
        for step in passed:
            self.record(seconds, subject, ev.EVENT_STEP_PASSED, step)
        self.record(seconds, subject, ev.EVENT_POSITION_CHANGED, after,
                    **{ev.FACT_FROM: before, ev.FACT_TO: after})

    def cli(self, *args):
        """Run svod in the store, in this process."""
        return run_cli(args, self.store, {**git_env(self.home), **CLI_ENV})


class RetroTestCase(unittest.TestCase):
    """A fresh store per test."""

    def setUp(self):
        """Temporary directory and store."""
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = RetroStore(temp.name)

    def retro(self, *args):
        """Run svod retro and expect success; its standard output."""
        done = self.sb.cli("retro", *args)
        self.assertEqual(EXIT_OK, done.returncode, done.stdout + done.stderr)
        return done.stdout

    def rule_lines(self, out, rule):
        """Item lines of one rule in the output of the list."""
        return [line for line in out.splitlines() if f". {rule} (" in line]


class DirtyChecksTest(RetroTestCase):
    def test_two_dirty_failures_propose_gitignore(self):
        """Failed runs whose command exited 0 are dirty; a failing command is not."""
        for second, code in ((0, 0), (60, 1), (120, 0)):
            self.sb.record(second, WORK_A, ev.EVENT_CHECKS_RUN, workspace="app", code=code,
                           seconds=1.5, passed=False)
        self.sb.record(180, WORK_A, ev.EVENT_CHECKS_RUN, workspace="app", code=0, seconds=1.0,
                       passed=True)
        out = self.retro(WORK_A)
        self.assertEqual([f"1. dirty_checks ({WORK_A}): " + line_text("dirty_checks", count=2,
                                                                        runs=4)],
                         self.rule_lines(out, "dirty_checks"))
        self.assertIn("facts: count=2, runs=4", out)
        self.assertIn("change: .gitignore (line): __pycache__/", out)

    def test_one_dirty_failure_and_a_reason_fact(self):
        """One dirty failure says nothing; a reason fact decides over the exit code."""
        self.sb.record(0, WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        self.sb.record(60, WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False,
                       reason="command did not succeed")
        self.assertEqual([], self.rule_lines(self.retro(WORK_A), "dirty_checks"))
        self.assertTrue(rules.is_dirty({"facts": {"passed": False, "code": 1,
                                                  "reason": "source workspace is dirty"}}))


class ApprovalDriftTest(RetroTestCase):
    def test_two_drifts_propose_a_split_contract(self):
        """Two drifts on one step name the step and the skill of its role."""
        self.sb.record(0, WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")
        self.sb.record(60, WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")
        self.sb.record(90, WORK_A, ev.EVENT_APPROVAL_DRIFT, "deliver")
        out = self.retro(WORK_A)
        self.assertEqual([f"1. approval_drift ({WORK_A}): "
                          + line_text("approval_drift", step="approve", count=2)],
                         self.rule_lines(out, "approval_drift"))
        self.assertIn(f"change: {TASK_SKILL} (note): "
                      + line_text("approval_drift", "retro.change.", step="approve"), out)

    def test_questions_after_the_approval_ask_earlier(self):
        """A questions step current after the approval chooses the variant asking earlier."""
        self.sb.move(0, WORK_A, None, "approve")
        self.sb.record(10, WORK_A, ev.EVENT_APPROVAL_RECORDED, "approve", by="me")
        self.sb.move(20, WORK_A, "approve", "questions")
        self.sb.record(30, WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")
        self.sb.record(40, WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")
        out = self.retro(WORK_A)
        self.assertIn(line_text("approval_drift_questions", step="approve", count=2), out)

    def test_one_drift_says_nothing(self):
        """A single drift is no pattern."""
        self.sb.record(0, WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")
        self.assertEqual([], self.rule_lines(self.retro(WORK_A), "approval_drift"))


class HookDenialsTest(RetroTestCase):
    def test_three_denials_of_one_rule_name_the_skill(self):
        """The step is the current one at the refusals; other rules are counted apart."""
        self.sb.move(0, WORK_A, None, "implement")
        for second in (10, 20, 30):
            self.sb.record(second, WORK_A, ev.EVENT_HOOK_DENIED, rule="plan", tool="Edit")
        for second in (40, 50):
            self.sb.record(second, WORK_A, ev.EVENT_HOOK_DENIED, rule="main", tool="Edit")
        out = self.retro(WORK_A)
        self.assertEqual([f"1. hook_denials ({WORK_A}): "
                          + line_text("hook_denials", hook_rule="plan", count=3,
                                      step="implement")],
                         self.rule_lines(out, "hook_denials"))
        self.assertIn(f"change: {TASK_SKILL} (note)", out)


class HotfixCauseTest(RetroTestCase):
    def test_two_hotfixes_with_one_cause(self):
        """A hotfix and its cause both lead to one proposal about the cause."""
        expected = (f"1. hotfix_cause ({LOGIN}): "
                    + line_text("hotfix_cause", work=LOGIN, count=2,
                                hotfixes=f"{HOTFIX_A}, {HOTFIX_B}"))
        for query in (HOTFIX_A, LOGIN):
            with self.subTest(query=query):
                self.assertEqual([expected], self.rule_lines(self.retro(query), "hotfix_cause"))
        everything = self.retro("--all")
        self.assertEqual(1, len(self.rule_lines(everything, "hotfix_cause")))
        self.assertIn("change: knowledge/login.md (note)", everything)

    def test_one_hotfix_says_nothing(self):
        """One hotfix naming the work is no pattern."""
        self.sb.card(HOTFIX_B, "hotfix", WORK_A)
        self.assertEqual([], self.rule_lines(self.retro(HOTFIX_A), "hotfix_cause"))


class InstantStepsTest(RetroTestCase):
    def works(self, seconds):
        """Three works whose card step lasted the given seconds each."""
        for i, (work, spent) in enumerate(zip((WORK_A, WORK_B, WORK_C), seconds, strict=True)):
            start = i * 1000
            self.sb.move(start, work, None, "card")
            self.sb.move(start + spent, work, "card", "questions", passed=["card"])

    def test_a_step_passing_at_once_in_three_works(self):
        """The step is proposed optional for the pipeline, with a line for its file."""
        self.works((INSTANT_SEC, INSTANT_SEC, 0))
        out = self.retro(WORK_A)
        self.assertEqual([f"1. instant_steps ({TASK}): "
                          + line_text("instant_steps", pipeline=TASK, step="card", count=3,
                                      seconds=INSTANT_SEC)],
                         self.rule_lines(out, "instant_steps"))
        self.assertIn(f"change: {TASK_FILE} (line): optional: true", out)

    def test_never_current_counts_as_instant(self):
        """A step passed on the way, never current, passed at once."""
        for i, work in enumerate((WORK_A, WORK_B, WORK_C)):
            self.sb.move(i * 1000, work, None, "questions", passed=["card"])
        self.assertEqual(1, len(self.rule_lines(self.retro(WORK_A), "instant_steps")))

    def test_one_slow_work_or_too_few_works(self):
        """A slow work among the last three, or only two works, say nothing."""
        self.works((INSTANT_SEC, SLOW_SEC, INSTANT_SEC))
        self.assertEqual([], self.rule_lines(self.retro(WORK_A), "instant_steps"))
        self.sb.move(5000, WORK_D, None, "card")
        self.sb.move(5005, WORK_D, "card", "questions", passed=["card"])
        self.assertEqual([], self.rule_lines(self.retro(WORK_A), "instant_steps"),
                         "the slow work is still among the last three")


class LongStepTest(RetroTestCase):
    def works(self, count, implement):
        """Works moving card -> implement -> checks, implement taking the given seconds."""
        for i, work in enumerate((WORK_A, WORK_B, WORK_C, WORK_D)[:count]):
            start = i * 10000
            self.sb.move(start, work, None, "card")
            self.sb.move(start + 100, work, "card", "implement", passed=["card"])
            self.sb.move(start + 100 + implement, work, "implement", "checks",
                         passed=["implement"])
            self.sb.record(start + 200 + implement, work, ev.EVENT_DELIVERED)

    def test_one_step_over_half_of_three_works(self):
        """The step longest in each work takes more than half of it."""
        self.works(3, LONG_SEC)
        out = self.retro(WORK_A)
        self.assertEqual([f"1. long_step ({TASK}): "
                          + line_text("long_step", pipeline=TASK, step="implement", count=3,
                                      works=3, share=82)],
                         self.rule_lines(out, "long_step"))

    def test_short_steps_say_nothing(self):
        """No step over half the time, or two works only."""
        self.works(3, 100)
        self.assertEqual([], self.rule_lines(self.retro(WORK_A), "long_step"))


class DecisionsTest(RetroTestCase):
    def setUp(self):
        """A store whose task alpha has a dirty_checks and an approval_drift proposal."""
        super().setUp()
        for second in (0, 60):
            self.sb.record(second, WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
            self.sb.record(second + 1, WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")

    def test_accept_records_and_hides_the_proposal(self):
        """--accept writes the decision with its fields and prints the diff hint."""
        listed = self.retro(WORK_A)
        self.assertIn("1. dirty_checks", listed)
        self.assertIn("2. approval_drift", listed)
        out = self.retro(WORK_A, "--accept", "1", "--note", NOTE)
        self.assertIn(f"accepted 1 (dirty_checks) in {DECISIONS}", out)
        self.assertIn("--- a/.gitignore\n+++ b/.gitignore\n+__pycache__/", out)
        entries = read_yaml(self.sb.store / DECISIONS)
        self.assertEqual(1, len(entries))
        self.assertEqual(list(decisions.FIELDS), list(entries[0]))
        self.assertEqual({"rule": "dirty_checks", "code": "dirty_tree", "subject": WORK_A,
                          "decision": "accepted", "note": NOTE},
                         {k: v for k, v in entries[0].items() if k != "at"})
        self.assertIsNotNone(dt.datetime.fromisoformat(entries[0]["at"]).tzinfo)
        after = self.retro(WORK_A)
        self.assertNotIn("dirty_checks", after)
        self.assertIn("1. approval_drift", after)

    def test_reject_then_nothing_left(self):
        """A rejected proposal is not shown again; the hint is not printed."""
        self.retro(WORK_A, "--reject", "2")
        out = self.retro(WORK_A, "--reject", "1")
        self.assertNotIn("+++", out)
        self.assertEqual([("approval_drift", "rejected"), ("dirty_checks", "rejected")],
                         [(e["rule"], e["decision"]) for e in
                          read_yaml(self.sb.store / DECISIONS)])
        self.assertIn(line_text("none", prefix="retro."), self.retro(WORK_A))

    def test_pipeline_rule_decided_for_the_pipeline(self):
        """A decision on a rule over a pipeline holds for every work of it."""
        for i, work in enumerate((WORK_B, WORK_C, WORK_D)):
            self.sb.move(i * 1000, work, None, "questions", passed=["card"])
        listed = self.retro(WORK_B)
        number = next(line.split(".")[0] for line in listed.splitlines()
                      if ". instant_steps" in line)
        self.retro(WORK_B, "--reject", number)
        self.assertEqual(TASK, read_yaml(self.sb.store / DECISIONS)[0]["subject"])
        self.assertNotIn("instant_steps", self.retro(WORK_C))

    def test_wrong_arguments(self):
        """A number outside the list, --note alone, neither or both of query and --all."""
        for args in ((WORK_A, "--accept", "3"), (WORK_A, "--accept", "0"),
                     (WORK_A, "--note", NOTE), (), (WORK_A, "--all"), ("no-such-work",)):
            with self.subTest(args=args):
                self.assertEqual(EXIT_USAGE, self.sb.cli("retro", *args).returncode)
        self.assertFalse((self.sb.store / DECISIONS).exists())

    def test_broken_decisions_file_is_not_overwritten(self):
        """A decisions file that is not a list stops the command."""
        path = self.sb.store / DECISIONS
        path.write_text("rule: x\n", encoding=ENCODING)
        done = self.sb.cli("retro", WORK_A, "--accept", "1")
        self.assertEqual(EXIT_USAGE, done.returncode)
        self.assertIn("expected a list of decisions", done.stderr)
        self.assertEqual("rule: x\n", path.read_text(encoding=ENCODING))


class ProfileRulesTest(RetroTestCase):
    def write_rule(self, name, text):
        """Write a module into profile/retro/."""
        path = self.sb.store / "profile" / "retro" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(text), encoding=ENCODING)

    def test_profile_rule_joins_the_core_ones(self):
        """RULES of a profile module are evaluated; a key text and a plain text are both shown."""
        self.write_rule("always.py", ALWAYS_RULE)
        self.write_rule("_private.py", "raise RuntimeError('never imported')\n")
        self.sb.record(0, WORK_A, ev.EVENT_DELIVERED)
        out = self.retro(WORK_A)
        self.assertIn(f"1. always ({WORK_A}): Count the entries.", out)
        self.assertIn("facts: entries=1", out)
        self.assertIn("change: README.md (note): Plain text of the change.", out)
        accepted = self.retro(WORK_A, "--accept", "1")
        self.assertIn("+Plain text of the change.", accepted)

    def test_bad_profile_modules_are_load_errors(self):
        """A taken name, a missing RULES or an import failure stops the command."""
        cases = {"clash.py": (CLASHING_RULE, "rule name already registered"),
                 "empty.py": ("X = 1\n", "RULES mapping"),
                 "broken.py": ("raise RuntimeError('boom')\n", "import failed")}
        for name, (text, message) in cases.items():
            with self.subTest(module=name):
                self.write_rule(name, text)
                done = self.sb.cli("retro", WORK_A)
                self.assertEqual(EXIT_USAGE, done.returncode)
                self.assertIn(message, done.stderr)
                (self.sb.store / "profile" / "retro" / name).unlink()

    def test_a_rule_that_raises_is_left_out(self):
        """A profile rule raising at evaluate is reported; the others still propose."""
        self.write_rule("always.py", ALWAYS_RULE.replace("return [", "raise ValueError('x')\n"
                                                         "        return ["))
        for second in (0, 60):
            self.sb.record(second, WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        done = self.sb.cli("retro", WORK_A)
        self.assertEqual(EXIT_OK, done.returncode, done.stderr)
        self.assertIn("always: ValueError('x')", done.stderr)
        self.assertIn("1. dirty_checks", done.stdout)


def line_text(name, prefix="retro.rule.", **facts):
    """Text of a core retro key in the locale of the test stores."""
    from support import core_text
    return core_text(prefix + name, **facts)


if __name__ == "__main__":
    unittest.main()
