"""Native deterministic retro application, with disposable instance profiles."""
import test_retro as fixtures
from pathlib import Path
import subprocess
import sys
from unittest import mock

from svod import evidence_log as ev
from svod.retro import patches, rules


def snapshot(root):
    """All instance file bytes, so preview cannot quietly write evidence or caches."""
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class ApplyTest(fixtures.RetroTestCase):
    def native(self, *args):
        """Exercise the real entrypoint with this test's isolated instance."""
        return subprocess.run([sys.executable, "-m", "svod.cli", *args],
                              cwd=self.sb.store, env=self.sb.env, capture_output=True,
                              text=True, timeout=60)

    def accept(self, *flags, runner=None):
        """Explicitly approve a freshly read preview in positive and write-failure controls."""
        run = runner or self.sb.cli
        preview = run("retro", "apply", fixtures.WORK_A)
        self.assertEqual(0, preview.returncode, preview.stdout + preview.stderr)
        token = next(line.removeprefix("Plan token: ") for line in preview.stdout.splitlines()
                     if line.startswith("Plan token: "))
        return run("retro", "apply", fixtures.WORK_A, "--accept", "--plan-token", token, *flags)

    def test_native_optional_preserves_first_key_block_scalar(self):
        """A block title remains the same scalar, not a newly created mapping."""
        path = self.sb.store / fixtures.TASK_FILE
        original = path.read_text().replace(
            "  - id: card\n    title: work.title.card\n",
            "  - title: |-\n      work.title.card\n    id: card\n")
        path.write_text(original)
        expected = fixtures.read_yaml(path)
        expected["steps"][0]["optional"] = True
        for i, work in enumerate((fixtures.WORK_A, fixtures.WORK_B, fixtures.WORK_C)):
            self.sb.move(i * 1000, work, None, "questions", passed=["card"])
        before = snapshot(self.sb.store)
        preview = self.native("retro", "apply", fixtures.WORK_A)
        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertEqual(before, snapshot(self.sb.store))
        accepted = self.accept(runner=self.native)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual(expected, fixtures.read_yaml(path))
        validated = self.native("validate")
        self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)

    def test_native_conflicting_identity_rejected_before_dedup(self):
        """Distinct replacements from a real profile rule cannot disappear in the engine."""
        module = self.sb.store / "profile/retro/conflict.py"
        module.parent.mkdir(exist_ok=True)
        module.write_text('''from svod.retro.rules import Rule, change
class Conflict(Rule):
    name = "conflict"
    def evaluate(self, ctx, subject, log, graph):
        return [self.propose("same", {},
                change("profile/limits.yaml", f"max_lines: {limit}", "line", "max_lines: 120"),
                text_key="limit") for limit in (150, 160)]
RULES = {"conflict": Conflict}
''')
        (self.sb.store / "profile/limits.yaml").write_text("max_lines: 120\n")
        before = snapshot(self.sb.store)
        for flags in ((), ("--accept",)):
            result = self.native("retro", "apply", fixtures.WORK_A, *flags)
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn("conflicting proposal identity", result.stderr)
            self.assertEqual(before, snapshot(self.sb.store))

    def test_native_decision_history_is_not_a_proposal_target(self):
        """A literal limit cannot turn the separate review writer into an edit allowlist."""
        path = self.sb.store / fixtures.DECISIONS
        path.parent.mkdir(exist_ok=True)
        path.write_text('- rule: old\n  code: one\n  subject: work/tasks/alpha\n'
                        '  decision: rejected\n  max_lines: 120\n')
        module = self.sb.store / "profile/retro/target.py"
        module.parent.mkdir(exist_ok=True)
        module.write_text('''from svod.retro.rules import Rule, change
class Target(Rule):
    name = "target"
    def evaluate(self, ctx, subject, log, graph):
        return [self.propose("one", {}, change("evidence/decisions.yaml",
                "max_lines: 150", "line", "max_lines: 120"), text_key="limit")]
RULES = {"target": Target}
''')
        before = snapshot(self.sb.store)
        for flags in ((), ("--accept",)):
            result = self.native("retro", "apply", fixtures.WORK_A, *flags)
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn("unsafe target", result.stderr)
            self.assertEqual(before, snapshot(self.sb.store))

    def test_native_accept_requires_preview_token_and_rejects_changed_inputs(self):
        """Approval binds to the printed read-only preview across separate processes."""
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        module = self.sb.store / "profile/retro/stable.py"
        module.parent.mkdir(exist_ok=True)
        module.write_text("RULES = {}\n")
        before = snapshot(self.sb.store)
        missing = self.native("retro", "apply", fixtures.WORK_A, "--accept")
        self.assertEqual(2, missing.returncode, missing.stdout + missing.stderr)
        self.assertIn("--plan-token", missing.stderr)
        self.assertEqual(before, snapshot(self.sb.store))
        for target in (".gitignore", "profile/limits.yaml", fixtures.DECISIONS, "svod.yaml",
                       fixtures.TASK_FILE, "profile/retro/stable.py", "evidence/new-input.yaml"):
            with self.subTest(target=target):
                preview = self.native("retro", "apply", fixtures.WORK_A)
                self.assertEqual(0, preview.returncode, preview.stderr)
                self.assertEqual(before, snapshot(self.sb.store))
                token = next(line.removeprefix("Plan token: ")
                             for line in preview.stdout.splitlines()
                             if line.startswith("Plan token: "))
                path = self.sb.store / target
                original = path.read_bytes() if path.exists() else None
                path.parent.mkdir(exist_ok=True)
                path.write_bytes((original or b"") + b"# changed since preview\n")
                changed = snapshot(self.sb.store)
                accepted = self.native("retro", "apply", fixtures.WORK_A,
                                       "--accept", "--plan-token", token)
                self.assertEqual(2, accepted.returncode, accepted.stdout + accepted.stderr)
                self.assertIn("stale", accepted.stderr)
                self.assertEqual(changed, snapshot(self.sb.store))
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_rollback_failure_names_unrestored_target(self):
        """Do not hide partial state when the filesystem refuses rollback too."""
        path = self.sb.store / ".gitignore"
        proposal = rules.Proposal("dirty_checks", "x", {}, "ignore",
                                  rules.change(".gitignore", "__pycache__/", "line"))
        planned = patches.plan(self.sb.store, [proposal])
        write = Path.write_bytes
        count = 0
        def broken(path, data):
            nonlocal count
            count += 1
            if count == 1:
                write(path, data)
            raise OSError("storage unavailable")
        with mock.patch.object(Path, "write_bytes", broken), \
                self.assertRaisesRegex(OSError, "rollback failed: .gitignore"):
            patches.apply(planned)
        self.assertIn(b"__pycache__/", path.read_bytes())

    def test_unterminated_input_has_valid_diff_and_missing_ignore_can_be_created(self):
        """Diffs mark missing final newlines instead of gluing removed and added lines."""
        path = self.sb.store / ".gitignore"
        path.write_bytes(b"cache/")
        proposal = rules.Proposal("dirty_checks", "x", {}, "ignore",
                                  rules.change(".gitignore", "__pycache__/", "line"))
        planned = patches.plan(self.sb.store, [proposal])
        self.assertIn("-cache/\n\\ No newline at end of file\n+cache/\n", planned.edits[0].diff())
        path.unlink()
        planned = patches.plan(self.sb.store, [proposal])
        patches.apply(planned)
        self.assertEqual(b"__pycache__/\n", path.read_bytes())

    def test_limit_must_be_yaml_setting_not_block_text_and_identity_must_agree(self):
        """Literal-looking prose is not a setting; duplicate identities cannot disagree."""
        path = self.sb.store / "profile/limits.yaml"
        proposal = rules.Proposal("limits", "one", {}, "limit",
                                  rules.change("profile/limits.yaml", "max_lines: 150", "line",
                                               "max_lines: 120"))
        path.write_text("description: |\n  max_lines: 120\n")
        with self.assertRaises(ValueError):
            patches.plan(self.sb.store, [proposal])
        path.write_text("max_lines: 120\n")
        conflict = rules.Proposal("limits", "one", {}, "limit",
                                  rules.change("profile/limits.yaml", "max_lines: 160", "line",
                                               "max_lines: 120"))
        with self.assertRaisesRegex(ValueError, "conflict"):
            patches.plan(self.sb.store, [proposal, conflict])

    def test_native_process_preview_accept_and_validate(self):
        """Use the real module entrypoint in a scratch instance, not just main in process."""
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        before = snapshot(self.sb.store)
        def native(*args):
            return subprocess.run([sys.executable, "-m", "svod.cli", *args],
                                  cwd=self.sb.store, env=self.sb.env, capture_output=True,
                                  text=True, timeout=60)
        preview = native("retro", "apply", fixtures.WORK_A)
        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertEqual(before, snapshot(self.sb.store))
        accepted = self.accept(runner=native)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertIn("Applied", accepted.stdout)
        validated = native("validate")
        self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)
        again = self.accept(runner=native)
        self.assertEqual(0, again.returncode, again.stderr)
        self.assertIn("No deterministic edits", again.stdout)

    def test_apply_options_and_private_evidence_match_preview(self):
        """Explicit acceptance allows notes; hidden evidence ignore edits are previewed too."""
        config = self.sb.store / "svod.yaml"
        config.write_text(config.read_text().replace("evidence: {commit: true}",
                                                     "evidence: {commit: false}"))
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        ignore = self.sb.store / ".gitignore"
        ignore.write_text("# original\n")
        preview = self.sb.cli("retro", "apply", fixtures.WORK_A)
        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertIn("+evidence/", preview.stdout)
        result = self.accept("--note", "reviewed")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(preview.stdout, result.stdout)
        self.assertEqual("reviewed", fixtures.read_yaml(self.sb.store / fixtures.DECISIONS)[0]
                         ["note"])
        for flags in (("--explain",), ("--accept", "1"), ("--reject", "1")):
            with self.subTest(flags=flags):
                self.assertEqual(2, self.sb.cli("retro", "apply", fixtures.WORK_A,
                                                *flags).returncode)

    def test_literal_lines_preserve_crlf_and_reject_multiline_hints(self):
        """Concrete edits preserve newline style; textual blocks are not ignore patterns."""
        path = self.sb.store / fixtures.TASK_FILE
        original = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(original)
        proposal = rules.Proposal("instant_steps", "card", {}, "optional",
                                  rules.change(fixtures.TASK_FILE, "optional: true", "line",
                                               "steps: card"))
        planned = patches.plan(self.sb.store, [proposal])
        patches.apply(planned)
        self.assertEqual(original.replace(b"  - id: card\r\n",
                                          b"  - id: card\r\n    optional: true\r\n"),
                         path.read_bytes())
        multiline = rules.Proposal("custom", "x", {}, "text",
                                    rules.change(".gitignore", "one\ntwo", "line"))
        self.assertEqual([multiline], patches.plan(self.sb.store, [multiline]).unsupported)

    def test_decision_failure_reported_without_false_success(self):
        """A decision persistence error is explicit, never reported as applied success."""
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        before = snapshot(self.sb.store)
        with mock.patch("svod.retro.decisions.record_decision", side_effect=OSError("disk full")):
            result = self.accept()
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("disk full", result.stderr)
        self.assertEqual(before, snapshot(self.sb.store))

    def test_symlink_decision_output_blocks_profile_writes(self):
        """The evidence output must be safe before any accepted profile change."""
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        outside = self.sb.base / "decisions.yaml"
        outside.write_text("[]\n")
        (self.sb.store / fixtures.DECISIONS).symlink_to(outside)
        before = snapshot(self.sb.store)
        result = self.accept()
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("unsafe", result.stderr)
        self.assertEqual(before, snapshot(self.sb.store))
        self.assertEqual("[]\n", outside.read_text())

    def test_write_failure_rolls_back_batch_and_records_no_acceptance(self):
        """A later target failure restores earlier targets and leaves decisions untouched."""
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        for i, work in enumerate((fixtures.WORK_A, fixtures.WORK_B, fixtures.WORK_C)):
            self.sb.move(i * 1000 + 100, work, None, "questions", passed=["card"])
        before = snapshot(self.sb.store)
        write = Path.write_bytes
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == self.sb.store / fixtures.TASK_FILE and not failed:
                failed = True
                raise OSError("injected write failure")
            return write(path, data)
        with mock.patch.object(Path, "write_bytes", fail_once):
            result = self.accept()
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("injected write failure", result.stderr)
        self.assertEqual(before, snapshot(self.sb.store))

    def test_ambiguous_or_unsafe_yaml_anchors_refused(self):
        """Duplicates, aliases, flow steps and malformed YAML cannot select a unique edit."""
        path = self.sb.store / fixtures.TASK_FILE
        proposal = rules.Proposal("instant_steps", "card", {}, "optional",
                                  rules.change(fixtures.TASK_FILE, "optional: true", "line",
                                               "steps: card"))
        for text in ("steps:\n  - id: card\n  - id: card\n",
                     "steps:\n  - id: card\n    optional: false\n    optional: true\n",
                     "steps:\n  - {id: card, title: keep}\n",
                     "steps:\n  - &shared\n    id: card\n    optional: false\ncopy: *shared\n",
                     "steps:\n  - id: other\n",
                     "steps: [broken"):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    patches.plan(self.sb.store, [proposal])
                self.assertEqual(text, path.read_text())

    def test_literal_existing_line_limit_only_and_conflicts_rejected(self):
        """Concrete literal replacements need one existing exact anchor, never a guessed limit."""
        path = self.sb.store / "profile/limits.yaml"
        before = "# retained\nmax_lines: 120  # budget\nother: 4\n"
        path.write_text(before)
        def proposal(code, text, anchor="max_lines: 120"):
            return rules.Proposal("limits", code, {}, "limit",
                                  rules.change("profile/limits.yaml", text, "line", anchor))
        concrete = proposal("one", "max_lines: 150")
        planned = patches.plan(self.sb.store, [concrete])
        self.assertEqual(1, len(planned.edits))
        self.assertIn("+max_lines: 150  # budget", planned.edits[0].diff())
        with self.assertRaisesRegex(ValueError, "conflict"):
            patches.plan(self.sb.store, [concrete, proposal("two", "max_lines: 160")])
        self.assertEqual(before, path.read_text())
        patches.apply(planned)
        self.assertEqual(before.replace("120", "150"), path.read_text())
        self.assertFalse(patches.plan(self.sb.store, [concrete]).edits[0].diff())
        vague = patches.plan(self.sb.store, [proposal("vague", "increase max_lines")])
        self.assertEqual(1, len(vague.unsupported))
        self.assertFalse(vague.edits)

    def test_multiple_optional_proposals_compose_and_duplicate_is_noop(self):
        """One file can contain two independent accepted changes without losing either."""
        path = self.sb.store / fixtures.TASK_FILE
        proposals = [rules.Proposal("instant_steps", step, {}, "optional",
                                    rules.change(fixtures.TASK_FILE, "optional: true", "line",
                                                 f"steps: {step}"))
                     for step in ("card", "questions", "card")]
        planned = patches.plan(self.sb.store, proposals)
        self.assertEqual(1, len(planned.edits))
        patches.apply(planned)
        steps = fixtures.read_yaml(path)["steps"]
        self.assertTrue(all(s.get("optional") for s in steps if s["id"] in ("card", "questions")))
        again = patches.plan(self.sb.store, proposals)
        self.assertFalse(any(e.diff() for e in again.edits))
        self.assertEqual(2, len(again.applicable))

    def test_unsafe_targets_rejected_without_writes(self):
        """Traversal, absolute paths, symlinks and non-profile targets fail closed."""
        outside = self.sb.base / "outside.yaml"
        outside.write_bytes((self.sb.store / fixtures.TASK_FILE).read_bytes())
        link = self.sb.store / "profile/pipelines/escape.yaml"
        link.symlink_to(outside)
        for target in ("../outside.yaml", str(outside), "profile/pipelines/escape.yaml",
                       "work/tasks/alpha/card.md", "profile/../profile/pipelines/task.yaml"):
            with self.subTest(target=target):
                before = snapshot(self.sb.store)
                proposal = rules.Proposal("instant_steps", "card", {}, "optional",
                                          rules.change(target, "optional: true", "line",
                                                       "steps: card"))
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    patches.plan(self.sb.store, [proposal])
                self.assertEqual(before, snapshot(self.sb.store))
        ignore = self.sb.store / ".gitignore"
        ignore.unlink()
        ignore.symlink_to(outside)
        proposal = rules.Proposal("dirty_checks", "x", {}, "ignore",
                                  rules.change(".gitignore", "cache/", "line"))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            patches.plan(self.sb.store, [proposal])

    def test_stale_batch_rejected_before_any_write(self):
        """Every input is rechecked before writing even the first target."""
        first = self.sb.store / ".gitignore"
        second = self.sb.store / fixtures.TASK_FILE
        proposals = [rules.Proposal("dirty_checks", "dirty_tree", {}, "ignore",
                                    rules.change(".gitignore", "cache/", "line")),
                     rules.Proposal("instant_steps", "card", {}, "optional",
                                    rules.change(fixtures.TASK_FILE, "optional: true", "line",
                                                 "steps: card"))]
        planned = patches.plan(self.sb.store, proposals)
        first_before = first.read_bytes()
        second.write_bytes(second.read_bytes() + b"# concurrent edit\n")
        before = snapshot(self.sb.store)
        with self.assertRaisesRegex(ValueError, "stale"):
            patches.apply(planned)
        self.assertEqual(before, snapshot(self.sb.store))
        self.assertEqual(first_before, first.read_bytes())

    def test_textual_advice_is_non_applicable_and_not_accepted(self):
        """Review acceptance remains separate from actual deterministic application."""
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_APPROVAL_DRIFT, "approve")
        before = snapshot(self.sb.store)
        result = self.accept()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("non-applicable", result.stdout)
        self.assertIn("approval_drift", result.stdout)
        self.assertIn("split the contract", result.stdout)
        self.assertEqual(before, snapshot(self.sb.store))

    def test_optional_step_exact_target_preserves_comments(self):
        """The core instant rule edits only its named step, without reserializing YAML."""
        path = self.sb.store / fixtures.TASK_FILE
        before = path.read_text().replace("  - id: card\n", "  - id: card  # keep\n")
        path.write_text(before)
        for i, work in enumerate((fixtures.WORK_A, fixtures.WORK_B, fixtures.WORK_C)):
            self.sb.move(i * 1000, work, None, "questions", passed=["card"])
        preview = self.sb.cli("retro", "apply", fixtures.WORK_A)
        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertIn("+    optional: true", preview.stdout)
        self.assertEqual(before, path.read_text())
        accepted = self.accept()
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual(before.replace("  - id: card  # keep\n",
                                        "  - id: card  # keep\n    optional: true\n"),
                         path.read_text())
        steps = fixtures.read_yaml(path)["steps"]
        self.assertTrue(next(s for s in steps if s["id"] == "card")["optional"])
        self.assertNotIn("optional", next(s for s in steps if s["id"] == "questions"))

    def test_gitignore_preview_then_explicit_application(self):
        """Preview is an actual read-only diff; acceptance writes that exact addition once."""
        path = self.sb.store / ".gitignore"
        path.write_text("# keep this comment\ncache/\n", encoding="utf-8")
        for second in (0, 60):
            self.sb.record(second, fixtures.WORK_A, ev.EVENT_CHECKS_RUN, code=0, passed=False)
        before = snapshot(self.sb.store)
        preview = self.sb.cli("retro", "apply", fixtures.WORK_A)
        self.assertEqual(0, preview.returncode, preview.stdout + preview.stderr)
        self.assertIn("--- a/.gitignore\n+++ b/.gitignore\n@@", preview.stdout)
        self.assertIn("+__pycache__/", preview.stdout)
        self.assertEqual(before, snapshot(self.sb.store))
        accepted = self.accept()
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        self.assertEqual("# keep this comment\ncache/\n__pycache__/\n", path.read_text())
        self.assertIn("--- a/.gitignore\n+++ b/.gitignore\n@@", accepted.stdout)
        self.assertEqual("accepted", fixtures.read_yaml(self.sb.store / fixtures.DECISIONS)[0]
                         ["decision"])
        again = self.accept()
        self.assertEqual(0, again.returncode, again.stdout + again.stderr)
        self.assertEqual(1, path.read_text().count("__pycache__/"))
        self.assertEqual(1, len(fixtures.read_yaml(self.sb.store / fixtures.DECISIONS)))
