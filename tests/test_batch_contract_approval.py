"""Package consent through real native prompt and CLI on disposable standard stores."""
import json
import shutil
from tempfile import TemporaryDirectory
import unittest

from test_standard_template import StandardStore
from svod.approval import read_mark


class BatchContractApprovalTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sb = StandardStore(self.temp.name)
        self.assertEqual(self.sb.cli("init", "--login", "tester").returncode, 0)
        self.records = [f"work/tasks/{name}" for name in ("alpha", "bravo", "charlie")]
        for index, record in enumerate(self.records):
            shutil.copytree(self.sb.store / "work/tasks/example", self.sb.store / record)
            self.sb.edit(f"{record}/card.md", "status: archived", "status: open")
            self.sb.edit(f"{record}/card.md", "services: []", "services: [app]")
            self.sb.edit(f"{record}/card.md", "key: EXAMPLE-1",
                         "key: TK-2" if index == 1 else "key:")

    def prompt(self, text="Approved"):
        event = json.dumps({"cwd": str(self.sb.store), "prompt": text})
        from support import run_cli
        return run_cli(["hook", "prompt"], self.sb.store, self.sb.env, stdin=event)

    def command(self, *records, prepare=False, step="approve"):
        args = ["approve", *records, "--step", step]
        if prepare:
            args.append("--prepare")
        return self.sb.cli(*args)

    def assert_unapproved(self):
        for record in self.records:
            self.assertFalse((self.sb.store / record / "approval.yaml").exists())

    def test_single_unnamed_reply_remains_single_use(self):
        self.prompt()
        first = self.command(self.records[0])
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.command(self.records[1])
        self.assertNotEqual(second.returncode, 0)
        self.assertIsNone(read_mark(self.sb.store))

    def test_fresh_reply_records_all_selected_contracts_once(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        applied = self.command("TK-2", self.records[0])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        from svod.approval import digest, read_fields
        from svod import evidence_log
        for record in self.records[:2]:
            base = self.sb.store / record
            fields = read_fields(base / "approval.yaml", "contract_approved")
            self.assertTrue(fields[0])
            self.assertEqual(fields[1], "tester")
            self.assertEqual(fields[2], digest(base, ["card.md", "contract.md", "questions.md"],
                                             ["^status:"]))
            events = evidence_log.read(self.sb.store, "task", record)
            self.assertEqual(sum(e["event"] == "approval_recorded" for e in events), 1)
            self.assertFalse(read_fields(base / "approval.yaml", "result_approved")[0])
        self.assertFalse((self.sb.store / self.records[2] / "approval.yaml").exists())
        self.assertIsNone(read_mark(self.sb.store))
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)

    def test_named_keyless_path_is_a_single_record_identity(self):
        self.prompt(f"Approved {self.records[0]}")
        applied = self.command(self.records[0])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIsNone(read_mark(self.sb.store))

    def test_named_package_consumes_only_selected_identities(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt(f"Approved {self.records[0]} and TK-2 and {self.records[2]}")
        applied = self.command(*self.records[:2])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(read_mark(self.sb.store)["keys"], [self.records[2]])
        self.assertEqual(self.command(self.records[2]).returncode, 0)

    def test_path_continuation_cannot_authorize_prepared_package(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        prompted = self.prompt(f"Approved {self.records[0]}/and and TK-2")
        self.assertEqual(prompted.returncode, 0, prompted.stderr)
        applied = self.command(*self.records[:2])
        self.assertNotEqual(applied.returncode, 0, applied.stdout)
        self.assert_unapproved()
        self.assertIsNone(read_mark(self.sb.store))

    def test_native_identity_lookalikes_never_mint_package_consent(self):
        import subprocess
        import sys
        from support import child_env

        def cli(*args, stdin=None):
            return subprocess.run([sys.executable, "-m", "svod.cli", *args],
                                  cwd=self.sb.store, env=child_env(base=self.sb.env),
                                  input=stdin, capture_output=True, text=True, timeout=60)

        preview = cli("approve", *self.records[:2], "--step", "approve", "--prepare")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        alpha = self.records[0]
        lookalikes = (
            (f"{alpha}/and", "TK-2"),
            (f"and/{alpha}", "TK-2"),
            (f"/{alpha}", "TK-2"),
            (f"{alpha}/", "TK-2"),
            (f"and{alpha}", "TK-2"),
            (f"{alpha}and", "TK-2"),
            (f"and-{alpha}", "TK-2"),
            (f"{alpha}-and", "TK-2"),
            (f"and_{alpha}", "TK-2"),
            (f"{alpha}_and", "TK-2"),
            (f"and.{alpha}", "TK-2"),
            (f"{alpha}.and", "TK-2"),
            (alpha, "and/TK-2"),
            (alpha, "TK-2/and"),
            (alpha, "andTK-2"),
            (alpha, "TK-2and"),
            (alpha, "and-TK-2"),
            (alpha, "TK-2-and"),
            (alpha, "and_TK-2"),
            (alpha, "TK-2_and"),
            (f"{alpha}/and", "TK-2/and"),
        )
        for path, key in lookalikes:
            with self.subTest(path=path, key=key):
                event = json.dumps({"cwd": str(self.sb.store),
                                    "prompt": f"Approved {path} and {key}"})
                prompted = cli("hook", "prompt", stdin=event)
                self.assertEqual(prompted.returncode, 0, prompted.stderr)
                applied = cli("approve", *self.records[:2], "--step", "approve")
                self.assertNotEqual(applied.returncode, 0, applied.stdout)
                self.assert_unapproved()
                self.assertIsNone(read_mark(self.sb.store))

    def test_complete_package_identities_retain_separator_grammar(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        for separator in (" and ", ", ", "; ", ": ", " & ", " + ", " / ",
                          " – ", " — ", " - ", "\n", ", and "):
            with self.subTest(separator=separator):
                prompted = self.prompt(f"Approved {self.records[0]}{separator}TK-2!")
                self.assertEqual(prompted.returncode, 0, prompted.stderr)
                mark = read_mark(self.sb.store)
                self.assertIsNotNone(mark)
                self.assertEqual(set(mark["keys"]), {self.records[0], "TK-2"})
                self.assertTrue(mark.get("package"))
        applied = self.command(*self.records[:2])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIsNone(read_mark(self.sb.store))

    def test_second_write_failure_rolls_back_and_preserves_consent(self):
        from unittest import mock
        from svod import approval_package
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        original = read_mark(self.sb.store)
        writer = approval_package.write_fields
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args[0])
            writer(*args, **kwargs)
            if len(calls) == 2:
                raise OSError("fixture disk failure")

        with mock.patch.object(approval_package, "write_fields", side_effect=fail_second):
            failed = self.command(*self.records[:2])
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("fixture disk failure", failed.stderr)
        self.assert_unapproved()
        self.assertEqual(read_mark(self.sb.store), original)
        self.assertEqual(self.command(*self.records[:2]).returncode, 0)

    def test_one_prepared_record_uses_the_package_route(self):
        self.assertEqual(self.command(self.records[0], prepare=True).returncode, 0)
        self.prompt()
        applied = self.command(self.records[0])
        self.assertEqual(applied.returncode, 0, applied.stderr)

    def test_changed_selection_and_inputs_refuse_without_partial_writes(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        mark = read_mark(self.sb.store)
        for selection in (self.records, self.records[1:], [self.records[0]],
                          [self.records[0], self.records[0]], ["absent", self.records[0]]):
            with self.subTest(selection=selection):
                self.assertNotEqual(self.command(*selection).returncode, 0)
                self.assert_unapproved()
                self.assertEqual(read_mark(self.sb.store), mark)
        self.sb.write(f"{self.records[1]}/contract.md", "# replaced contract\n")
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)
        self.assert_unapproved()
        self.assertEqual(read_mark(self.sb.store), mark)

    def test_reprepared_package_needs_a_new_reply(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)
        self.assert_unapproved()
        self.prompt()
        self.assertEqual(self.command(*self.records[:2]).returncode, 0)

    def test_preparation_cannot_reuse_earlier_bare_consent(self):
        self.prompt()
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)
        self.assert_unapproved()

    def test_package_prerequisites_and_contract_purpose_are_rechecked(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        self.sb.write(f"{self.records[1]}/questions.md", "## Q: unresolved?\n")
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)
        self.assert_unapproved()
        self.assertNotEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.assertNotEqual(self.command(*self.records[:2], prepare=True,
                                         step="deliver").returncode, 0)

    def test_expired_package_consent_is_not_consumed(self):
        import datetime as dt
        from svod.approval import mark_path
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        path = mark_path(self.sb.store)
        data = read_mark(self.sb.store)
        data["at"] = (dt.datetime.now().astimezone() - dt.timedelta(days=1)).isoformat()
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)
        self.assert_unapproved()
        self.assertEqual(read_mark(self.sb.store), data)

    def test_foreign_named_reply_cannot_approve_package(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt(f"Approved {self.records[2]}")
        self.assertNotEqual(self.command(*self.records[:2]).returncode, 0)
        self.assert_unapproved()

    def test_pending_package_cannot_be_edited_directly(self):
        from support import run_cli
        from svod.approval_package import package_path
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        path = package_path(self.sb.store)
        for tool, payload in (("Write", {"file_path": str(path), "content": "{}"}),
                              ("Bash", {"command": f"printf '{{}}' > {path}"})):
            event = {"cwd": str(self.sb.store), "tool_name": tool, "tool_input": payload}
            out = run_cli(["hook", "pre-tool"], self.sb.store, self.sb.env,
                          stdin=json.dumps(event))
            self.assertIn("deny", out.stdout)

    def test_redelivered_package_reply_never_becomes_single_record_consent(self):
        import datetime as dt
        from svod.hooks.prompt import prompt_hook
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        event_time = dt.datetime.now().astimezone()
        event = {"cwd": str(self.sb.store), "prompt": "Approved"}
        prompt_hook(event, self.sb.store, at=event_time)
        self.assertEqual(self.command(*self.records[:2]).returncode, 0)
        prompt_hook(event, self.sb.store, at=event_time)
        self.assertNotEqual(self.command(self.records[2]).returncode, 0)
        self.assertEqual(self.command(*self.records[1:], prepare=True).returncode, 0)
        prompt_hook(event, self.sb.store, at=event_time)
        self.assertNotEqual(self.command(self.records[2]).returncode, 0)

    def test_package_prompt_notice_names_one_complete_apply_command(self):
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        prompt = self.prompt()
        self.assertIn(f"svod approve {self.records[0]} {self.records[1]} --step approve",
                      prompt.stdout)

    def test_input_drift_during_write_rolls_back_all_selected_approvals(self):
        from unittest import mock
        from svod import approval_package
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        mark = read_mark(self.sb.store)
        writer = approval_package.write_fields

        def drift(*args, **kwargs):
            writer(*args, **kwargs)
            self.sb.write(f"{self.records[1]}/contract.md", "changed during writing\n")

        with mock.patch.object(approval_package, "write_fields", side_effect=drift):
            out = self.command(*self.records[:2])
        self.assertNotEqual(out.returncode, 0)
        self.assert_unapproved()
        self.assertEqual(read_mark(self.sb.store), mark)

    def test_rollback_preserves_a_new_human_event(self):
        from unittest import mock
        from svod import approval_package
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        writer = approval_package.write_fields
        newer = []

        def new_reply(*args, **kwargs):
            writer(*args, **kwargs)
            self.prompt(f"Approved {self.records[2]}")
            newer[:] = [read_mark(self.sb.store)]

        with mock.patch.object(approval_package, "write_fields", side_effect=new_reply):
            out = self.command(*self.records[:2])
        self.assertNotEqual(out.returncode, 0)
        self.assert_unapproved()
        self.assertEqual(read_mark(self.sb.store), newer[0])

    def test_unreadable_pending_package_cannot_downgrade_bare_consent(self):
        from svod.approval_package import package_path
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        package_path(self.sb.store).write_text("{broken", encoding="utf-8")
        self.prompt()
        self.assertNotEqual(self.command(self.records[2]).returncode, 0)
        self.assert_unapproved()

    def test_rollback_restores_existing_bytes_and_reports_failed_restoration(self):
        from unittest import mock
        from pathlib import Path
        from svod import approval_package
        before = "# existing evidence\nresult_approved: 2026-01-01\nextra: keep\n"
        target = self.sb.store / self.records[0] / "approval.yaml"
        self.sb.write(f"{self.records[0]}/approval.yaml", before)
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        mark = read_mark(self.sb.store)
        writer = approval_package.write_fields

        def fail(*args, **kwargs):
            writer(*args, **kwargs)
            raise OSError("write failed")

        with mock.patch.object(approval_package, "write_fields", side_effect=fail):
            out = self.command(*self.records[:2])
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(target.read_text(), before)
        self.assertEqual(read_mark(self.sb.store), mark)
        with mock.patch.object(approval_package, "write_fields", side_effect=fail), \
                mock.patch.object(Path, "write_bytes", side_effect=OSError("restore failed")):
            out = self.command(*self.records[:2])
        self.assertIn("rollback incomplete", out.stderr)
        self.assertEqual(read_mark(self.sb.store), mark)

    def test_mark_consumption_failure_restores_package_and_approvals(self):
        from unittest import mock
        from svod import approval_package
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        mark = read_mark(self.sb.store)
        pending = approval_package.package_path(self.sb.store).read_bytes()
        with mock.patch.object(approval_package, "consume_mark",
                               side_effect=OSError("mark failed")):
            out = self.command(*self.records[:2])
        self.assertNotEqual(out.returncode, 0)
        self.assert_unapproved()
        self.assertEqual(read_mark(self.sb.store), mark)
        self.assertEqual(approval_package.package_path(self.sb.store).read_bytes(), pending)
        self.assertEqual(self.command(*self.records[:2]).returncode, 0)

    def test_contract_package_does_not_grant_external_authority(self):
        from svod.approval import read_human_mark
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        self.prompt()
        self.assertFalse(read_human_mark(self.sb.store)["go"])
        self.assertNotEqual(self.command(*self.records[:2], step="deliver").returncode, 0)
        self.assertEqual(self.command(*self.records[:2]).returncode, 0)
        self.assertFalse(read_human_mark(self.sb.store)["go"])

    def test_ambiguous_or_duplicate_preview_preserves_existing_pending_package(self):
        from svod.approval_package import package_path
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        pending = package_path(self.sb.store).read_bytes()
        for records in (["a", self.records[0]], [self.records[0], self.records[0]],
                        ["absent", self.records[0]]):
            with self.subTest(records=records):
                self.assertNotEqual(self.command(*records, prepare=True).returncode, 0)
                self.assertEqual(package_path(self.sb.store).read_bytes(), pending)
                self.assert_unapproved()

    def test_native_subprocess_approves_three_contracts_after_prompt(self):
        import subprocess
        import sys
        from support import child_env
        from svod.approval import read_fields

        def cli(*args, stdin=None):
            return subprocess.run([sys.executable, "-m", "svod.cli", *args],
                                  cwd=self.sb.store, env=child_env(base=self.sb.env),
                                  input=stdin, capture_output=True, text=True, timeout=60)

        preview = cli("approve", *self.records, "--step", "approve", "--prepare")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        marked = cli("hook", "prompt", stdin=json.dumps({"cwd": str(self.sb.store),
                                                        "prompt": "Approved"}))
        self.assertEqual(marked.returncode, 0, marked.stderr)
        applied = cli("approve", *reversed(self.records), "--step", "approve")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        for record in self.records:
            self.assertTrue(read_fields(self.sb.store / record / "approval.yaml",
                                        "contract_approved")[0])

    def test_empty_pending_metadata_cannot_downgrade_bare_consent(self):
        from svod.approval_package import package_path
        self.assertEqual(self.command(*self.records[:2], prepare=True).returncode, 0)
        package_path(self.sb.store).write_text("{}", encoding="utf-8")
        self.prompt()
        self.assertNotEqual(self.command(self.records[2]).returncode, 0)
        self.assert_unapproved()

    def test_preview_displays_exact_bindings_without_approval_writes(self):
        preview = self.command(*self.records[:2], prepare=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        for record in self.records[:2]:
            self.assertIn(record, preview.stdout)
            self.assertIn(f"{record}/contract.md", preview.stdout)
        self.assertNotIn(self.records[2], preview.stdout)
        self.assertIn("approve", preview.stdout)
        self.assertRegex(preview.stdout, r"[0-9a-f]{64}")
        self.assert_unapproved()
        self.assertIsNone(read_mark(self.sb.store))
