"""Native wave-2 seams on isolated standard stores; no installed engine changes."""
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import test_standard_template as fixtures
from support import run_cli
from svod.approval import read_fields


class PackageTrustIntegrationTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = fixtures.StandardStore(temp.name)
        self.records = ["work/tasks/alpha", "work/tasks/bravo"]
        for record in self.records:
            shutil.copytree(self.sb.store / fixtures.EXAMPLE, self.sb.store / record)
            self.sb.edit(f"{record}/card.md", fixtures.ARCHIVED, fixtures.OPEN)
            self.sb.edit(f"{record}/card.md", "services: []", "services: [app]")
            self.sb.edit(f"{record}/card.md", "key: EXAMPLE-1", "key:")
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        self.sb.edit("svod.yaml", "profile_config:\n", "profile_config:\n"
                     "  trusted_actions:\n"
                     "    start-task: [bash, profile/actions/start-task.sh, '{id}']\n"
                     "    checks: [bash, profile/actions/checks.sh, '{id}']\n"
                     "  checks:\n    app: [test, -e, .git]\n")
        self.assertEqual(self.sb.cli("init", "--login", "tester").returncode, 0)

    def prompt(self, text="Approved"):
        return run_cli(["hook", "prompt"], self.sb.store, self.sb.env,
                       stdin=json.dumps({"cwd": str(self.sb.store), "prompt": text}))

    def approve_package(self):
        args = ("approve", *self.records, "--step", "approve")
        prepared = self.sb.cli(*args, "--prepare")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.prompt()
        applied = self.sb.cli(*args)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        return prepared

    def hook(self, tool, data, cwd=None):
        result = run_cli(["hook", "pre-tool"], self.sb.store, self.sb.env,
                         stdin=json.dumps({"cwd": str(cwd or self.sb.store),
                                           "tool_name": tool, "tool_input": data}))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}

    def test_native_knowledge_and_retro_routes_are_usable_without_blanket_exemption(self):
        for command in ("svod knowledge publish work/research/cache",
                        "svod knowledge supersede knowledge/old.md --by knowledge/new.md",
                        "svod retro apply work/tasks/alpha"):
            output = self.hook("Bash", {"command": command})
            self.assertNotEqual(output.get("permissionDecision"), "deny", output)
        for command in ("svod knowledge publish work/research/cache ; python3 bad.py",
                        "svod knowledge publish work/research/cache --root /outside"):
            self.assertEqual(self.hook("Bash", {"command": command})["permissionDecision"],
                             "deny")

    def test_combined_metadata_guards_and_on_edit_context_remain_fail_closed(self):
        self.sb.write("knowledge/relevant.md", "---\ntitle: Secret\ntags: [db]\n---\nContext\n")
        path = self.sb.store / "svod.yaml"
        path.write_text(path.read_text() + "\nknowledge:\n  on_edit: true\n"
                        "  file_tags: {'**': [db]}\n")
        names = ("svod-approval.json", "svod-human.json", "svod-approval-package.json",
                 "svod-knowledge-publish.json", "svod-write-grants.json",
                 "svod-write-grants-request.json")
        for name in names:
            for tool, data in (("Write", {"file_path": f".git/{name}", "content": "{}"}),
                               ("Bash", {"command": f"echo '{{}}' > .git/{name}"})):
                output = self.hook(tool, data)
                self.assertEqual(output.get("permissionDecision"), "deny", (name, output))
                self.assertNotIn("additionalContext", output)
        outside = self.hook("Write", {"file_path": str(self.sb.base / "outside.py"),
                                      "content": "x"})
        self.assertEqual(outside["permissionDecision"], "deny")
        self.assertNotIn("additionalContext", outside)

    def test_package_records_reviewed_trust_for_native_actions_and_command_gates(self):
        prepared = self.approve_package()
        self.assertIn("trusted_actions", prepared.stdout)
        for record in self.records:
            trust = read_fields(self.sb.store / record / "approval.yaml", "trusted_actions")
            self.assertTrue(trust[2], "package failed to record trust approval")
        record = self.records[0]
        started = self.sb.cli("do", "start-task", record)
        self.assertEqual(started.returncode, 0, started.stderr)
        checked = self.sb.cli("do", "checks", record)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        status = self.sb.cli("status", record, "--format", "json", "--fresh")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("positions", json.loads(status.stdout))
        # Compact JSON still evaluates children/trust gates; edited executable
        # configuration must never get run through status --fresh.
        sentinel = self.sb.base / "unreviewed-check-ran"
        self.sb.write("profile/actions/checks.sh", f"#!/bin/bash\ntouch '{sentinel}'\n")
        untrusted = self.sb.cli("do", "checks", record)
        self.assertNotEqual(untrusted.returncode, 0)
        status = self.sb.cli("status", record, "--format", "json", "--fresh")
        self.assertFalse(sentinel.exists(), status.stdout + status.stderr)
        position = json.loads(status.stdout)["positions"][0]
        self.assertEqual(position["current"], "checks")
        self.assertEqual(position["unknown"][0]["gate"], "command")
        self.assertEqual(position["unknown"][0]["status"], "unknown")

    def test_package_consent_does_not_authorize_external_grants_or_research_close(self):
        record = self.records[0]
        self.sb.write("work/research/joint/card.md", "---\ntype: card\noutcome: knowledge\n"
                      "status: open\ntags: [db]\n---\n# Joint\n")
        self.sb.write("work/research/joint/findings.md", "# Findings\nExact result.\n")
        args = ("allow", record, "--for", "30m", "--path", str(self.sb.base / "external"))
        self.assertNotEqual(self.sb.cli(*args).returncode, 0)
        self.assertNotEqual(self.sb.cli("knowledge", "publish", "work/research/joint").returncode,
                            0)
        self.approve_package()
        # An approval-form reply is not the configured human go-ahead for these routes.
        self.assertNotEqual(self.sb.cli(*args).returncode, 0)
        self.assertNotEqual(self.sb.cli("knowledge", "publish", "work/research/joint").returncode,
                            0)
        self.assertFalse((self.sb.store / "knowledge/joint.md").exists())
        denied = self.hook("Write", {"file_path": str(self.sb.base / "external/x"),
                                     "content": "x"}, self.sb.store / record)
        self.assertEqual(denied["permissionDecision"], "deny")
        # Prepare the exact grant again, bind a new go-ahead and prove native scope works.
        self.sb.cli(*args)
        self.prompt("go ahead")
        self.assertEqual(self.sb.cli(*args).returncode, 0)
        allowed = self.hook("Write", {"file_path": str(self.sb.base / "external/x"),
                                      "content": "x"}, self.sb.store / record)
        self.assertNotEqual(allowed.get("permissionDecision"), "deny")
        self.assertEqual(self.hook("Bash", {"command": "git push origin HEAD"})[
            "permissionDecision"], "deny")
        self.assertFalse((self.sb.store / "knowledge/joint.md").exists())
        self.prompt("Do not publish yet.")
        self.sb.cli("knowledge", "publish", "work/research/joint")
        self.prompt("go ahead")
        self.prompt("Do not publish.")
        self.assertNotEqual(self.sb.cli("knowledge", "publish", "work/research/joint").returncode,
                            0)
        self.assertFalse((self.sb.store / "knowledge/joint.md").exists())
        self.sb.cli("knowledge", "publish", "work/research/joint")
        self.prompt("go ahead")
        published = self.sb.cli("knowledge", "publish", "work/research/joint")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertIn("published_by: tester", (self.sb.store / "knowledge/joint.md").read_text())
        self.assertIn("status: done", (self.sb.store / "work/research/joint/card.md").read_text())

    def test_old_standard_profile_merges_without_install_or_lost_customization(self):
        from svod import profile_merge
        repo = Path(__file__).resolve().parents[1]
        old = self.sb.base / "old-template"
        old.mkdir()
        paths = subprocess.check_output([
            "git", "ls-tree", "-r", "--name-only", "b4194ca", "--",
            "svod/templates/standard"], cwd=repo, text=True).splitlines()
        for name in paths:
            rel = Path(name).relative_to("svod/templates/standard")
            target = old / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "show", f"b4194ca:{name}"],
                                                       cwd=repo))
        store = self.sb.base / "old-store"
        shutil.copytree(old, store)
        config = store / "svod.yaml"
        config.write_text(config.read_text() + "\n# Retained operator customization\n")
        mine = store / "profile/private-note.md"
        mine.write_text("Keep my profile\n")
        changes = profile_merge.plan(old, repo / "svod/templates/standard", store,
                                     "0.6.0", "wave-2")
        self.assertFalse([c.path for c in changes if c.kind == profile_merge.CONFLICT])
        profile_merge.apply(store, changes)
        result = run_cli(["validate"], store, self.sb.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Retained operator customization", config.read_text())
        self.assertEqual(mine.read_text(), "Keep my profile\n")
        self.assertIn("publish", (store / "profile/pipelines/research.yaml").read_text())
        self.assertFalse((store / ".svod").exists())

    def test_trust_change_after_preview_invalidates_whole_package(self):
        args = ("approve", *self.records, "--step", "approve")
        self.assertEqual(self.sb.cli(*args, "--prepare").returncode, 0)
        self.sb.write("profile/actions/extra.sh", "# New unreviewed dependency\ntrue\n")
        self.prompt()
        self.assertNotEqual(self.sb.cli(*args).returncode, 0)
        for record in self.records:
            self.assertFalse((self.sb.store / record / "approval.yaml").exists())
