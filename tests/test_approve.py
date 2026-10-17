"""The approval mark, the approve command, line-wise field writing and texts by reason."""
import datetime as dt
import io
import json
import shutil
import unittest
from unittest import mock

import yaml

from support import (ENCODING, EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, ME, TEST_PROFILE,
                     StoreTestCase, TempStore)

from svod.approval import (MARK_AT, MARK_KEYS, digest, is_fresh, mark_path, read_fields,
                             read_mark, set_fields, write_fields, write_mark)
from svod.approve import approval_ref, approve, candidates, pending_prerequisites
from svod.config import load_config
from svod.context import Context
from svod.errors import LoadError
from svod.gates import Status
from svod.loader import load_runtime
from svod.locale import Locale
from svod.providers.openspec_change import DEFAULT_ROOT, METADATA_FILE
from svod.render import gate_text

CHANGE = f"{DEFAULT_ROOT}/c-1"
META = f"{CHANGE}/{METADATA_FILE}"
CHANGE2 = f"{DEFAULT_ROOT}/c-2"
META2 = f"{CHANGE2}/{METADATA_FILE}"
BIND = ["design.md", "specs/**/spec.md"]
UNBOUND_GATE = "params: { marker: approved, file: .openspec.yaml }"
BOUND_GATE = ("params: { marker: approved, file: .openspec.yaml, "
              "bind: [design.md, \"specs/**/spec.md\"] }")
IGNORE = ["^PR [0-9]+$"]
IGNORING_GATE = ("params: { marker: approved, file: .openspec.yaml, "
                 "bind: [design.md, \"specs/**/spec.md\"], ignore: [\"^PR [0-9]+$\"] }")
STRIP = [", opened [0-9-]+$"]
STRIPPING_GATE = ("params: { marker: approved, file: .openspec.yaml, "
                  "bind: [design.md, \"specs/**/spec.md\"], ignore: [\"^PR [0-9]+$\"], "
                  "strip: [\", opened [0-9-]+$\"] }")
KEEP = "ticket: tk-1\n# kept comment\nextra: value\n"
WINDOW = 10
MINUTE = dt.timedelta(minutes=1)
PROFILE_DIR = "bound-profile"
SECOND_PROFILE_DIR = "second-approval-profile"
SECOND_STEP = "changes_approval"
SECOND_META = f"{CHANGE}/review/approval.yaml"
SECOND_BIND = ["review/code.yaml", "review/zed.yaml"]


def bound_profile(root, gate=BOUND_GATE):
    """Copy of the test profile whose approval step declares the given gate params."""
    target = root / PROFILE_DIR
    shutil.copytree(TEST_PROFILE, target)
    pipeline = target / "pipelines" / "task.yaml"
    text = pipeline.read_text(encoding=ENCODING)
    pipeline.write_text(text.replace(UNBOUND_GATE, gate), encoding=ENCODING)
    return target


def second_approval_profile(root):
    """Test profile with a native second approval after completed build and verification."""
    target = bound_profile(root)
    second = root / SECOND_PROFILE_DIR
    target.rename(second)
    pipeline = second / "pipelines" / "task.yaml"
    text = pipeline.read_text(encoding=ENCODING)
    step = f"""  - id: {SECOND_STEP}
    required: true
    text: task.step.review
    gates:
      - {{ gate: artifact, params: {{ path: review/code.yaml }} }}
      - {{ gate: artifact, params: {{ path: review/zed.yaml }} }}
      - gate: approval
        params:
          marker: changes_approved
          file: review/approval.yaml
          bind: [review/code.yaml, review/zed.yaml]
        label: mark.approved
"""
    pipeline.write_text(text.replace("  - id: review\n", step + "  - id: review\n"),
                        encoding=ENCODING)
    return second


def two_changes(sb, gate):
    """Commit two changes into a store whose approval step declares the gate; the first's path."""
    config = sb.store / "svod.yaml"
    text = config.read_text(encoding=ENCODING)
    sb.write("svod.yaml", text.replace(str(TEST_PROFILE), str(bound_profile(sb.root, gate))))
    sb.init_git(remote=False)
    sb.write(META, KEEP)
    sb.write(f"{CHANGE}/design.md", "# design\n")
    sb.write(f"{CHANGE}/specs/cap/spec.md", "# spec\n")
    sb.write(META2, "ticket: tk-2\n")
    sb.write(f"{CHANGE2}/design.md", "# second design\n")
    sb.write(f"{CHANGE2}/specs/cap/spec.md", "# second spec\n")
    sb.commit(message="change")
    return sb.store / CHANGE


class ApproveTest(StoreTestCase):
    """svod approve writes the fields only after a fresh mark that names the subject."""

    GATE = BOUND_GATE

    def setUp(self):
        """Store with a bound approval step and one change in git."""
        super().setUp()
        self.change = two_changes(self.sb, self.GATE)

    def meta(self):
        """Parsed metadata of the change."""
        return yaml.safe_load((self.sb.store / META).read_text(encoding=ENCODING))

    def mark(self, keys=(), minutes_ago=0):
        """Leave a mark as the prompt hook would."""
        at = dt.datetime.now().astimezone() - minutes_ago * MINUTE
        write_mark(self.sb.store, keys, at)

    def test_fresh_mark_writes_fields_and_is_consumed(self):
        """Three fields written, other lines kept, gate passes; a second approve is refused."""
        self.mark()
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn("Nothing is committed", out.stdout)
        text = (self.sb.store / META).read_text(encoding=ENCODING)
        self.assertTrue(text.startswith(KEEP), text)
        meta = self.meta()
        self.assertEqual(str(meta["approved"]), dt.date.today().isoformat())
        self.assertEqual(meta["approved_by"], ME[0])
        self.assertEqual(meta["approved_sha"], digest(self.change, BIND))
        self.assertIsNone(read_mark(self.sb.store))
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)
        again = self.sb.cli("approve", "tk-1")
        self.assertEqual(again.returncode, EXIT_FINDINGS)
        self.assertIn("No fresh approval", again.stderr)

    def test_refusals(self):
        """No mark, a stale mark and a mark for another key write nothing."""
        cases = ((None, "No fresh approval"), ((), WINDOW + 1, "No fresh approval"),
                 (("Tk-2",), 0, "names Tk-2, not tk-1"))
        for case in cases:
            keys_and_age, message = case[:-1], case[-1]
            with self.subTest(case=case):
                mark_path(self.sb.store).unlink(missing_ok=True)
                if keys_and_age[0] is not None:
                    self.mark(*keys_and_age)
                out = self.sb.cli("approve", "tk-1")
                self.assertEqual(out.returncode, EXIT_FINDINGS)
                self.assertIn(message, out.stderr)
                self.assertNotIn("approved", self.meta())
        self.assertIsNotNone(read_mark(self.sb.store), "a refused mark is not consumed")

    def test_mark_with_the_key(self):
        """A mark naming the subject key in any case approves it."""
        self.mark(("Tk-1",))
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)

    def test_grouped_mark_is_consumed_one_key_at_a_time(self):
        """Separate CLI calls approve both named keys while retaining the original time."""
        at = dt.datetime.now().astimezone()
        write_mark(self.sb.store, ("TK-1", "tK-2"), at)
        original = read_mark(self.sb.store)

        first = self.sb.cli("approve", "Tk-1")
        self.assertEqual(first.returncode, EXIT_OK, first.stderr)
        remaining = read_mark(self.sb.store)
        self.assertEqual(remaining[MARK_AT], original[MARK_AT])
        self.assertEqual({key.casefold() for key in remaining[MARK_KEYS]}, {"tk-2"})

        second = self.sb.cli("approve", "TK-2")
        self.assertEqual(second.returncode, EXIT_OK, second.stderr)
        self.assertIsNone(read_mark(self.sb.store))

    def test_consumed_key_refusal_does_not_consume_another_group_key(self):
        """Repeating an already consumed key is refused and leaves the other key usable."""
        self.mark(("Tk-1", "TK-2"))
        self.assertEqual(self.sb.cli("approve", "tK-1").returncode, EXIT_OK)
        remaining = read_mark(self.sb.store)

        repeated = self.sb.cli("approve", "TK-1")
        self.assertEqual(repeated.returncode, EXIT_FINDINGS)
        self.assertEqual(read_mark(self.sb.store), remaining)

        other = self.sb.cli("approve", "tk-2")
        self.assertEqual(other.returncode, EXIT_OK, other.stderr)
        self.assertIsNone(read_mark(self.sb.store))

    def test_expired_remaining_group_key_is_refused_and_retained(self):
        """A remaining key keeps the shared window and is not consumed after it expires."""
        self.mark(("tk-1", "tk-2"))
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        remaining = read_mark(self.sb.store)
        write_mark(self.sb.store, remaining[MARK_KEYS],
                   dt.datetime.now().astimezone() - (WINDOW + 1) * MINUTE)
        expired = read_mark(self.sb.store)

        refused = self.sb.cli("approve", "tk-2")
        self.assertEqual(refused.returncode, EXIT_FINDINGS)
        self.assertIn("No fresh approval", refused.stderr)
        self.assertEqual(read_mark(self.sb.store), expired)

    def test_reapproval_replaces_the_fields(self):
        """A legacy date is overwritten in place, not duplicated."""
        set_fields(self.sb.store / META, {"approved": "2026-01-01"})
        self.mark()
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        text = (self.sb.store / META).read_text(encoding=ENCODING)
        self.assertEqual(text.count("approved:"), 1)
        self.assertEqual(str(self.meta()["approved"]), dt.date.today().isoformat())

    def test_unknown_query_and_no_approver(self):
        """Nothing found is a usage error; without any identity the approval is refused."""
        self.assertEqual(self.sb.cli("approve", "tk-99").returncode, EXIT_USAGE)
        self.sb.git(self.sb.store, "config", "--unset", "user.email")
        self.mark()
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn("Who approves is unknown", out.stderr)


class ConfirmTest(StoreTestCase):
    """svod approve --confirm asks the person at a terminal when no fresh mark exists."""

    def setUp(self):
        """Store with a bound approval step and one change in git, no mark."""
        super().setUp()
        self.change = two_changes(self.sb, BOUND_GATE)

    def meta(self):
        """Parsed metadata of the change."""
        return yaml.safe_load((self.sb.store / META).read_text(encoding=ENCODING))

    def confirm(self, answer, tty=True, confirm=True):
        """Run approve in this process with stdin a terminal or not and the answer typed.

        Returns the report, what was printed on stderr and the input mock.
        """
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        stdin = mock.Mock()
        stdin.isatty.return_value = tty
        typed = (mock.Mock(side_effect=answer) if isinstance(answer, BaseException)
                 else mock.Mock(return_value=answer))
        err = io.StringIO()
        with mock.patch("sys.stdin", stdin), mock.patch("builtins.input", typed), \
                mock.patch("sys.stderr", err):
            report = approve(ctx, runtime.pipelines, "tk-1", confirm=confirm)
        return report, err.getvalue(), typed

    def test_yes_at_a_terminal_records_the_approval(self):
        """y or yes at a terminal writes the three fields after showing the bound files."""
        for answer in ("y", " YES "):
            with self.subTest(answer=answer):
                set_fields(self.sb.store / META, {"approved": "", "approved_by": "",
                                                  "approved_sha": ""})
                report, err, typed = self.confirm(answer)
                self.assertTrue(report.ok, report.err)
                typed.assert_called_once()
                self.assertIn("Approve tk-1? [y/N]", err)
                self.assertIn(f"{CHANGE}/design.md", err)
                self.assertIn(f"{CHANGE}/specs/cap/spec.md", err)
                meta = self.meta()
                self.assertEqual(str(meta["approved"]), dt.date.today().isoformat())
                self.assertEqual(meta["approved_by"], ME[0])
                self.assertEqual(meta["approved_sha"], digest(self.change, BIND))
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)

    def test_other_answer_or_end_of_input_records_nothing(self):
        """n, an empty answer or end of input refuse without writing."""
        for answer in ("n", "", "yes please", EOFError()):
            with self.subTest(answer=answer):
                report, err, typed = self.confirm(answer)
                self.assertFalse(report.ok)
                self.assertTrue(report.refused)
                self.assertIn("not confirmed at the terminal", report.err[0])
                typed.assert_called_once()
                self.assertNotIn("approved", self.meta())

    def test_without_terminal_or_flag_the_old_refusal_stands(self):
        """No terminal, or no --confirm, refuses as before without asking."""
        for tty, confirm in ((False, True), (True, False)):
            with self.subTest(tty=tty, confirm=confirm):
                report, err, typed = self.confirm("y", tty=tty, confirm=confirm)
                self.assertFalse(report.ok)
                self.assertIn("No fresh approval", report.err[0])
                typed.assert_not_called()
                self.assertEqual(err, "")
                self.assertNotIn("approved", self.meta())

    def test_piped_answer_is_not_a_confirmation(self):
        """y piped into the command line is not a terminal: refused, nothing written."""
        out = self.sb.cli("approve", "tk-1", "--confirm", stdin="y\n")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn("No fresh approval", out.stderr)
        self.assertNotIn("Approve tk-1?", out.stderr)
        self.assertNotIn("approved", self.meta())

    def test_fresh_mark_is_used_without_asking(self):
        """With a fresh mark --confirm asks nothing and consumes the mark as before."""
        write_mark(self.sb.store, ("tk-1",))
        report, err, typed = self.confirm("n")
        self.assertTrue(report.ok, report.err)
        typed.assert_not_called()
        self.assertIsNone(read_mark(self.sb.store))
        self.assertEqual(self.meta()["approved_by"], ME[0])


class SecondApprovalTest(StoreTestCase):
    """An explicit --step records a later approval only after its stage is ready."""

    def setUp(self):
        super().setUp()
        config = self.sb.store / "svod.yaml"
        text = config.read_text(encoding=ENCODING)
        profile = second_approval_profile(self.sb.root)
        self.sb.write("svod.yaml", text.replace(str(TEST_PROFILE), str(profile)))
        self.sb.init_git(remote=False)
        self.sb.write(META, KEEP)
        self.sb.write(f"{CHANGE}/design.md", "# design\n")
        self.sb.write(f"{CHANGE}/specs/cap/spec.md", "# spec\n")
        self.sb.write(f"{CHANGE}/progress.txt", "1\n")
        self.sb.write(f"{CHANGE}/report.md", "# verification\n")
        self.sb.write(f"{CHANGE}/review/code.yaml", "head: abc\n")
        self.sb.write(f"{CHANGE}/review/zed.yaml", "shown: true\n")
        self.sb.commit(message="two approvals")
        self.change = self.sb.store / CHANGE

    def mark(self):
        write_mark(self.sb.store, ("Tk-1",))

    def approve_plan(self):
        self.mark()
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)

    def review_meta(self):
        return yaml.safe_load((self.sb.store / SECOND_META).read_text(encoding=ENCODING))

    def second_gate_result(self):
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        pipeline = runtime.pipeline("task")
        subject = pipeline.subject.impl.resolve("tk-1", ctx)[0]
        return approval_ref(pipeline, SECOND_STEP).impl.evaluate(ctx, subject)

    def test_explicit_step_writes_only_the_second_approval_and_digest(self):
        """A fresh second human approval writes its own file and leaves plan approval intact."""
        self.approve_plan()
        plan_meta = (self.sb.store / META).read_text(encoding=ENCODING)
        self.mark()

        out = self.sb.cli("approve", "tk-1", "--step", SECOND_STEP)

        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual((self.sb.store / META).read_text(encoding=ENCODING), plan_meta)
        meta = self.review_meta()
        self.assertEqual(str(meta["changes_approved"]), dt.date.today().isoformat())
        self.assertEqual(meta["changes_approved_by"], ME[0])
        self.assertEqual(meta["changes_approved_sha"], digest(self.change, SECOND_BIND))
        self.assertIsNone(read_mark(self.sb.store))

    def test_premature_second_step_is_refused_without_consuming_the_mark(self):
        """A missing first approval keeps the second stage closed and preserves the mark."""
        self.mark()
        marked = read_mark(self.sb.store)

        out = self.sb.cli("approve", "tk-1", "--step", SECOND_STEP)

        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn("approve", out.stderr)
        self.assertEqual(read_mark(self.sb.store), marked)
        self.assertFalse((self.sb.store / SECOND_META).exists())

    def test_missing_and_nonapproval_steps_are_refused_without_consuming_mark(self):
        """--step must name a real step containing a native approval gate."""
        cases = (("absent", "no step absent"),
                 ("spec", "step spec has no native approval gate"))
        for step, message in cases:
            with self.subTest(step=step):
                self.mark()
                marked = read_mark(self.sb.store)
                out = self.sb.cli("approve", "tk-1", "--step", step)
                self.assertEqual(out.returncode, EXIT_FINDINGS)
                self.assertIn(message, out.stderr)
                self.assertEqual(read_mark(self.sb.store), marked)

    def test_selected_step_artifacts_must_pass_before_approval(self):
        """A selected non-approval gate cannot be bypassed with --step."""
        self.approve_plan()
        (self.change / "review/zed.yaml").unlink()
        self.mark()
        marked = read_mark(self.sb.store)

        out = self.sb.cli("approve", "tk-1", "--step", SECOND_STEP)

        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn(SECOND_STEP, out.stderr)
        self.assertEqual(read_mark(self.sb.store), marked)
        self.assertFalse((self.sb.store / SECOND_META).exists())

    def test_second_approval_becomes_stale_when_bound_review_changes(self):
        """The core approval gate rejects review evidence changed after approval."""
        self.approve_plan()
        self.mark()
        out = self.sb.cli("approve", "tk-1", "--step", SECOND_STEP)
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(self.second_gate_result().status, Status.PASS)

        self.sb.write(f"{CHANGE}/review/code.yaml", "head: changed\n")
        result = self.second_gate_result()
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.facts["reason"], "drift")

    def test_second_approval_refuses_review_changed_after_chat_response(self):
        """The CLI preserves an old mark until the person approves the regenerated review."""
        self.approve_plan()
        write_mark(self.sb.store, ("Tk-1",), dt.datetime.now().astimezone() - MINUTE)
        old_mark = read_mark(self.sb.store)
        self.sb.write(f"{CHANGE}/review/code.yaml", "head: regenerated\n")

        refused = self.sb.cli("approve", "tk-1", "--step", SECOND_STEP)

        self.assertEqual(refused.returncode, EXIT_FINDINGS)
        self.assertIn("changed after the person's chat response", refused.stderr)
        self.assertEqual(read_mark(self.sb.store), old_mark)
        self.assertFalse((self.sb.store / SECOND_META).exists())

        self.mark()
        accepted = self.sb.cli("approve", "tk-1", "--step", SECOND_STEP)
        self.assertEqual(accepted.returncode, EXIT_OK, accepted.stderr)
        self.assertEqual(self.review_meta()["changes_approved_sha"],
                         digest(self.change, SECOND_BIND))

    def test_bound_file_stat_error_refuses_without_consuming_mark(self):
        """An unreadable exact version fails closed and preserves the human mark."""
        self.approve_plan()
        self.mark()
        marked = read_mark(self.sb.store)
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())

        with mock.patch("svod.approve.bound_files", side_effect=OSError("unreadable")):
            report = approve(ctx, runtime.pipelines, "tk-1", step=SECOND_STEP)

        self.assertFalse(report.ok)
        self.assertTrue(report.refused)
        self.assertIn("changed after the person's chat response", report.err[0])
        self.assertEqual(read_mark(self.sb.store), marked)
        self.assertFalse((self.sb.store / SECOND_META).exists())


class ConditionalApprovalTest(StoreTestCase):
    """Synthetic declarations drive native writer applicability and readiness."""

    def setUp(self):
        super().setUp()
        profile = bound_profile(self.sb.root)
        config = self.sb.store / "svod.yaml"
        self.sb.write("svod.yaml", config.read_text(encoding=ENCODING).replace(
            str(TEST_PROFILE), str(profile)))
        self.pipeline_path = profile / "pipelines/task.yaml"
        self.data = yaml.safe_load(self.pipeline_path.read_text(encoding=ENCODING))
        self.data["steps"] = [
            {"id": "orchard", "text": "task.step.review", "required": True,
             "gates": [{"gate": "approval", "purpose": "fruit",
                        "params": {"marker": "pear_accepted", "file": ".openspec.yaml"}}]},
            {"id": "meadow", "text": "task.step.review",
             "gates": [{"gate": "approval", "purpose": "grass",
                        "params": {"marker": "grass_accepted", "file": "decision.yaml"}}]},
        ]
        self.data.pop("violations", None)
        self.sb.init_git(remote=False)
        self.sb.write(META, KEEP)
        self.sb.commit(message="synthetic approvals")

    def runtime_case(self, attrs=None):
        self.pipeline_path.write_text(yaml.safe_dump(self.data), encoding=ENCODING)
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        pipeline = runtime.pipeline("task")
        subject = pipeline.subject.impl.resolve("tk-1", ctx)[0]
        subject.attrs.update(attrs or {})
        return ctx, pipeline, subject

    def test_inapplicable_step_is_refused_without_write_or_mark_consumption(self):
        self.data["steps"][0]["when"] = "needs_fruit"
        ctx, pipeline, subject = self.runtime_case()
        write_mark(self.sb.store, ("tk-1",))
        marked = read_mark(self.sb.store)
        with mock.patch("svod.approve.resolve", return_value=mock.Mock(
                matches=[(pipeline, subject)])):
            report = approve(ctx, [pipeline], "tk-1", step="orchard")
        self.assertFalse(report.ok)
        self.assertTrue(report.refused)
        self.assertEqual(read_mark(self.sb.store), marked)
        self.assertEqual((self.sb.store / META).read_text(encoding=ENCODING), KEEP)

    def test_inapplicable_approval_gate_is_not_an_automatic_candidate(self):
        self.data["steps"][0]["gates"][0]["when"] = "needs_fruit"
        ctx, pipeline, subject = self.runtime_case()
        with mock.patch("svod.approve.resolve", return_value=mock.Mock(
                matches=[(pipeline, subject)])):
            pairs, _ = candidates(ctx, [pipeline], "tk-1")
        self.assertEqual(pairs, [(subject, pipeline.steps[1].gates[0])])

    def test_skipped_prerequisite_and_selected_artifact_allow_real_approval(self):
        self.data["steps"][0]["when"] = "needs_fruit"
        self.data["steps"][1]["gates"].insert(0, {
            "gate": "artifact", "when": "needs_report", "params": {"path": "absent.md"}})
        ctx, pipeline, subject = self.runtime_case()
        self.assertEqual(pending_prerequisites(ctx, pipeline, subject, "meadow"), [])
        write_mark(self.sb.store, ("tk-1",))
        with mock.patch("svod.approve.resolve", return_value=mock.Mock(
                matches=[(pipeline, subject)])):
            report = approve(ctx, [pipeline], "tk-1")
        self.assertTrue(report.ok, report.err)
        self.assertIsNone(read_mark(self.sb.store))
        self.assertIn("grass_accepted", yaml.safe_load(
            (subject.path / "decision.yaml").read_text(encoding=ENCODING)))
        self.assertEqual((self.sb.store / META).read_text(encoding=ENCODING), KEEP)

    def test_gate_only_skipped_prerequisite_does_not_block_later_approval(self):
        self.data["steps"][0]["gates"][0]["when"] = "needs_fruit"
        ctx, pipeline, subject = self.runtime_case()
        self.assertEqual(pending_prerequisites(ctx, pipeline, subject, "meadow"), [])
        self.assertIsNone(approval_ref(pipeline, "orchard", subject))
        self.assertEqual(pending_prerequisites(ctx, pipeline, subject, "orchard"), ["orchard"])

    def test_applicable_prerequisite_and_selected_artifact_still_block(self):
        self.data["steps"][0]["when"] = "needs_fruit"
        self.data["steps"][1]["gates"].insert(0, {
            "gate": "artifact", "when": "needs_report", "params": {"path": "absent.md"}})
        ctx, pipeline, subject = self.runtime_case(
            {"needs_fruit": True, "needs_report": True})
        self.assertIs(approval_ref(pipeline, "orchard", subject), pipeline.steps[0].gates[0])
        self.assertEqual(pending_prerequisites(ctx, pipeline, subject, "meadow"),
                         ["orchard", "meadow"])

    def test_repeated_approval_is_evaluated_once_and_needs_no_extra_human_event(self):
        duplicate = yaml.safe_load(yaml.safe_dump(self.data["steps"][0]["gates"][0]))
        duplicate["label"] = "mark.approved"
        self.data["steps"].insert(1, {"id": "copse", "text": "task.step.review",
                                       "required": True, "gates": [duplicate]})
        ctx, pipeline, subject = self.runtime_case()
        write_mark(self.sb.store, ("tk-1",))
        with mock.patch("svod.approve.resolve", return_value=mock.Mock(
                matches=[(pipeline, subject)])):
            first = approve(ctx, [pipeline], "tk-1")
            self.assertTrue(first.ok, first.err)
            repeated = pipeline.steps[1].gates[0].impl
            with mock.patch.object(repeated, "evaluate", wraps=repeated.evaluate) as evaluate:
                pairs, _ = candidates(ctx, [pipeline], "tk-1")
            self.assertEqual(pairs, [(subject, pipeline.steps[2].gates[0])])
            evaluate.assert_not_called()
            self.assertEqual(pending_prerequisites(ctx, pipeline, subject, "meadow"), [])
            write_mark(self.sb.store, ("tk-1",))
            second = approve(ctx, [pipeline], "tk-1")
        self.assertTrue(second.ok, second.err)
        self.assertIsNone(read_mark(self.sb.store))

    def test_skipped_first_copy_does_not_hide_applicable_duplicate(self):
        duplicate = yaml.safe_load(yaml.safe_dump(self.data["steps"][0]["gates"][0]))
        self.data["steps"][0]["when"] = "needs_fruit"
        self.data["steps"][1]["gates"].insert(0, duplicate)
        ctx, pipeline, subject = self.runtime_case()
        write_mark(self.sb.store, ("tk-1",))
        with mock.patch("svod.approve.resolve", return_value=mock.Mock(
                matches=[(pipeline, subject)])):
            pairs, _ = candidates(ctx, [pipeline], "tk-1")
            self.assertEqual(pairs, [(subject, pipeline.steps[1].gates[0])])
            report = approve(ctx, [pipeline], "tk-1")
        self.assertTrue(report.ok, report.err)

    def test_inapplicable_gate_is_refused_with_explicit_step_and_all_skipped_has_no_candidate(self):
        for stage in self.data["steps"]:
            stage["gates"][0]["when"] = "needs_decision"
        ctx, pipeline, subject = self.runtime_case()
        write_mark(self.sb.store, ("tk-1",))
        marked = read_mark(self.sb.store)
        with mock.patch("svod.approve.resolve", return_value=mock.Mock(
                matches=[(pipeline, subject)])):
            pairs, _ = candidates(ctx, [pipeline], "tk-1")
            self.assertEqual(pairs, [])
            report = approve(ctx, [pipeline], "tk-1", step="orchard")
        self.assertFalse(report.ok)
        self.assertTrue(report.refused)
        self.assertEqual(read_mark(self.sb.store), marked)


class ApproveIgnoringLinesTest(ApproveTest):
    """With ignore, approve records the normalized digest, which survives ignored lines."""

    GATE = IGNORING_GATE

    def test_fresh_mark_writes_fields_and_is_consumed(self):
        """The recorded digest is the normalized one; an ignored line keeps the approval."""
        self.mark()
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        sha = self.meta()["approved_sha"]
        self.assertEqual(sha, digest(self.change, BIND, IGNORE))
        self.assertNotEqual(sha, digest(self.change, BIND))
        self.sb.write(f"{CHANGE}/design.md", "# design\n\nPR 7\n")
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)
        self.sb.write(f"{CHANGE}/design.md", "# design v2\n")
        self.assertNotIn("+ approved", self.sb.cli("status", "tk-1").stdout)


class ApproveStrippingTest(ApproveTest):
    """With strip, approve records the digest under ignore and strip, which survives the cut."""

    GATE = STRIPPING_GATE

    def test_fresh_mark_writes_fields_and_is_consumed(self):
        """The recorded digest is the one with strip; a cut tail keeps the approval."""
        self.mark()
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        sha = self.meta()["approved_sha"]
        self.assertEqual(sha, digest(self.change, BIND, IGNORE, STRIP))
        self.sb.write(f"{CHANGE}/design.md", "# design, opened 2026-09-24\n\nPR 7\n")
        self.assertNotEqual(sha, digest(self.change, BIND, IGNORE))
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)
        self.sb.write(f"{CHANGE}/design.md", "# design v2, opened 2026-09-24\n")
        self.assertNotIn("+ approved", self.sb.cli("status", "tk-1").stdout)


class MarkTest(StoreTestCase):
    """The mark lives in the git common directory and is fresh only inside the window."""

    def test_mark_location_and_freshness(self):
        """Written next to the objects of the store; fresh within the window only."""
        self.sb.init_git(remote=False)
        now = dt.datetime.now().astimezone()
        path = write_mark(self.sb.store, ["Tk-1"], now)
        self.assertEqual(path.parent, (self.sb.store / ".git").resolve())
        mark = json.loads(path.read_text(encoding=ENCODING))
        self.assertEqual(mark[MARK_KEYS], ["Tk-1"])
        cases = ((now, True), (now + WINDOW * MINUTE, True), (now + (WINDOW + 1) * MINUTE, False),
                 (now - MINUTE, False))
        for at, fresh in cases:
            with self.subTest(at=at):
                self.assertEqual(is_fresh(mark, WINDOW, at), fresh)
        self.assertFalse(is_fresh({MARK_AT: "yesterday"}, WINDOW, now))
        self.assertFalse(is_fresh(None, WINDOW, now))

    def test_outside_git_there_is_no_mark(self):
        """A store outside git has nowhere to keep the mark."""
        self.assertIsNone(write_mark(self.sb.store, []))
        self.assertIsNone(read_mark(self.sb.store))


class SetFieldsTest(unittest.TestCase):
    """Line-wise writing keeps comments and order."""

    def test_set_fields(self):
        """Existing fields are replaced in place, new ones appended, unsafe values quoted."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        path = sb.write("meta.yaml", "a: 1\n# note\nb: 2")
        set_fields(path, {"b": "x@example.com", "c": "has: colon", "d": "0123"})
        self.assertEqual(path.read_text(encoding=ENCODING),
                         'a: 1\n# note\nb: x@example.com\nc: "has: colon"\nd: "0123"\n')


class FieldsTest(unittest.TestCase):
    """read_fields and write_fields are the one reader and writer of the approval fields."""

    def test_read_and_write(self):
        """Fields round-trip; legacy records, absent files and other shapes read as empty."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        path = sb.store / "meta.yaml"
        self.assertEqual(read_fields(path, "approved"), ("", "", ""))
        sb.write("meta.yaml", "ticket: tk-1\napproved: 2026-01-01\n")
        self.assertEqual(read_fields(path, "approved"), ("2026-01-01", "", ""))
        write_fields(path, "approved", "2026-02-02", "me@example.com", "abc")
        self.assertEqual(read_fields(path, "approved"), ("2026-02-02", "me@example.com", "abc"))
        self.assertTrue(path.read_text(encoding=ENCODING).startswith("ticket: tk-1\n"))
        write_fields(path, "plan", "2026-03-03", "me@example.com")
        self.assertEqual(read_fields(path, "plan"), ("2026-03-03", "me@example.com", ""))
        self.assertNotIn("plan_sha", path.read_text(encoding=ENCODING))
        sb.write("meta.yaml", "- a\n")
        self.assertEqual(read_fields(path, "approved"), ("", "", ""))
        for text in ("approved: [\n", "approved: x\napproved: y\n"):
            with self.subTest(text=text):
                sb.write("meta.yaml", text)
                with self.assertRaises(LoadError):
                    read_fields(path, "approved")


class ApprovalConfigTest(unittest.TestCase):
    """The approval block of svod.yaml."""

    def test_values_and_errors(self):
        """Phrases and window are read; bad shapes are load errors."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        base = sb.store.joinpath("svod.yaml").read_text(encoding=ENCODING)
        sb.write("svod.yaml", base + "approval: { phrases: [ok go], window_minutes: 3 }\n")
        config = load_config(sb.store)
        self.assertEqual((config.approval_phrases, config.approval_window), (("ok go",), 3))
        cases = (("approval: [a]\n", "must be a mapping"),
                 ("approval: { colour: red }\n", "unknown key: colour"),
                 ("approval: { phrases: ok }\n", "phrases must be a list"),
                 ("approval: { window_minutes: 0 }\n", "window_minutes must be a positive"))
        for text, message in cases:
            with self.subTest(text=text):
                sb.write("svod.yaml", base + text)
                with self.assertRaises(LoadError) as ctx:
                    load_config(sb.store)
                self.assertIn(message, str(ctx.exception))


class TextVariantTest(unittest.TestCase):
    """A text takes its <key>_<reason> variant when the locale has one."""

    def test_variants(self):
        """Reason with a variant, reason without one, no reason."""
        locale = Locale({"step": "base", "step_drift": "drift by {by}"})
        cases = (({"reason": "drift", "by": "me"}, "drift by me"),
                 ({"reason": "legacy"}, "base"), ({}, "base"))
        for facts, text in cases:
            with self.subTest(facts=facts):
                self.assertEqual(gate_text(locale, "step", facts), text)


if __name__ == "__main__":
    unittest.main()
