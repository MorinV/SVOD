"""Native knowledge lifecycle acceptance, on disposable stores only."""
import json
import os

from unittest import mock

from support import StoreTestCase

from svod import hooks, knowledge
from svod.frontmatter import read_frontmatter
from svod.scaffold import scaffold


class SupersedeTest(StoreTestCase):
    def test_supersede_preserves_crlf_body(self):
        old = knowledge.note(self.sb.store, "Old", ["db"], "Old")
        knowledge.note(self.sb.store, "New", ["db"], "New")
        old.write_bytes(old.read_bytes().replace(b"\n", b"\r\n"))
        before = old.read_bytes().split(b"---\r\n", 2)[-1]
        self.assertEqual(0, self.sb.cli("knowledge", "supersede", "knowledge/old.md",
                                        "--by", "knowledge/new.md").returncode)
        self.assertTrue(old.read_bytes().endswith(before))

    def test_symlink_index_is_refused_before_retiring_note(self):
        old = knowledge.note(self.sb.store, "Old", ["db"], "Old")
        knowledge.note(self.sb.store, "New", ["db"], "New")
        outside = self.sb.write("outside.md", "Untouched")
        (old.parent / "INDEX.md").symlink_to(outside)
        before = old.read_bytes()
        result = self.sb.cli("knowledge", "supersede", "knowledge/old.md",
                             "--by", "knowledge/new.md")
        self.assertEqual(1, result.returncode)
        self.assertEqual(before, old.read_bytes())
        self.assertEqual("Untouched", outside.read_text())

    def test_rejects_invalid_targets_cycles_and_escapes_without_writes(self):
        old = knowledge.note(self.sb.store, "Old body", ["db"], "Old")
        new = knowledge.note(self.sb.store, "New body", ["db"], "New")
        self.sb.write("outside.md", new.read_text())
        self.sb.write("knowledge/plain.md", "No note frontmatter")
        (old.parent / "escape.md").symlink_to(self.sb.store / "outside.md")
        for target in ("knowledge/old.md", "knowledge/missing.md", "outside.md",
                       "knowledge/plain.md", "knowledge/escape.md"):
            before = old.read_bytes()
            result = self.sb.cli("knowledge", "supersede", "knowledge/old.md", "--by", target)
            self.assertNotEqual(0, result.returncode, target)
            self.assertEqual(before, old.read_bytes())
        self.assertEqual(0, self.sb.cli("knowledge", "supersede", "knowledge/old.md",
                                        "--by", "knowledge/new.md").returncode)
        before = new.read_bytes()
        self.assertNotEqual(0, self.sb.cli("knowledge", "supersede", "knowledge/new.md",
                                           "--by", "knowledge/old.md").returncode)
        self.assertEqual(before, new.read_bytes())

    def test_supersede_cli_preserves_bodies_and_refreshes_context(self):
        old = knowledge.note(self.sb.store, "Original body.", ["db"], "Old")
        new = knowledge.note(self.sb.store, "Replacement body.", ["db"], "New")
        before = new.read_bytes()
        body = knowledge.split_document(old.read_text())[1]
        result = self.sb.cli("knowledge", "supersede", "knowledge/old.md",
                             "--by", "knowledge/new.md")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, new.read_bytes())
        self.assertEqual(body, knowledge.split_document(old.read_text())[1])
        self.assertEqual("knowledge/new.md", read_frontmatter(old)["superseded_by"])
        self.assertEqual(1, len(knowledge.matching(self.sb.store, ["db"])))
        self.assertIn("superseded", (old.parent / "INDEX.md").read_text())
        snapshot = old.read_bytes()
        self.assertEqual(0, self.sb.cli("knowledge", "supersede", "knowledge/old.md",
                                        "--by", "knowledge/new.md").returncode)
        self.assertEqual(snapshot, old.read_bytes())


class OnEditTest(StoreTestCase):
    def test_process_hook_adds_context_only_for_current_notes(self):
        knowledge.note(self.sb.store, "Old", ["db"], "Old")
        knowledge.note(self.sb.store, "New", ["db"], "New")
        self.sb.cli("knowledge", "supersede", "knowledge/old.md", "--by", "knowledge/new.md")
        self.configure("  on_edit: true\n  file_tags: {'src/*.py': [db]}\n")
        event = {"cwd": str(self.sb.store), "tool_name": "MultiEdit",
                 "tool_input": {"file_path": "src/a.py", "edits": []}}
        result = self.sb.cli_process("hook", "pre-tool", stdin=json.dumps(event))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("knowledge/new.md", result.stdout)
        self.assertNotIn("knowledge/old.md", result.stdout)

    def test_invalid_file_tag_configuration_is_rejected(self):
        from svod.config import knowledge_errors
        for config in ({"on_edit": "yes"}, {"file_tags": []},
                       {"file_tags": {"../*.py": ["db"]}},
                       {"file_tags": {"/*.py": ["db"]}},
                       {"file_tags": {"*.py": "db"}}):
            self.assertTrue(knowledge_errors(self.sb.store / "svod.yaml", config))

    def test_matching_never_reads_notes_via_symlink(self):
        outside = self.sb.write("outside.md",
                                "---\ntitle: External\ntags: [db]\n---\nOther project")
        folder = self.sb.store / "knowledge"
        folder.mkdir()
        (folder / "external.md").symlink_to(outside)
        self.assertEqual([], knowledge.matching(self.sb.store, ["db"]))

    def hook(self, tool="Write", **data):
        return hooks.answer(hooks.EVENT_PRE_TOOL,
                            {"cwd": str(self.sb.store), "tool_name": tool, "tool_input": data})

    def configure(self, extra):
        path = self.sb.store / "svod.yaml"
        path.write_text(path.read_text() + "\nknowledge:\n" + extra)

    def test_default_off_and_explicit_mapping_bounds_deduplicates_current_notes(self):
        knowledge.note(self.sb.store, "Relevant", ["db"], "Database")
        knowledge.note(self.sb.store, "Other", ["ui"], "UI")
        self.assertIsNone(self.hook(file_path="src/a.py", content="db"))
        self.configure("  on_edit: true\n  limit_lines: 1\n"
                       "  file_tags: {'src/*.py': [db], 'web/*.js': [ui]}\n")
        result = self.hook(file_path="src/a.py", content="anything")
        self.assertIn("Database", result)
        self.assertNotIn("UI", result)
        result = self.hook("apply_patch", command="*** Begin Patch\n"
                           "*** Add File: src/a.py\n+x\n*** Add File: src/b.py\n+y\n"
                           "*** Add File: web/a.js\n+z\n*** End Patch")
        text = json.loads(result)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(1, text.count("knowledge/"))
        self.assertIsNone(self.hook(file_path="unmapped.py", content="db"))

    def test_unsafe_targets_and_denials_do_not_add_context(self):
        knowledge.note(self.sb.store, "Secret", ["db"], "Database")
        self.configure("  on_edit: true\n  file_tags: {'**': [db]}\n")
        (self.sb.store / "linked").symlink_to(self.sb.root)
        for path in (str(self.sb.root / "outside.py"), "linked/out.py"):
            output = json.loads(self.hook(file_path=path, content="x"))["hookSpecificOutput"]
            self.assertEqual("deny", output["permissionDecision"])
            self.assertNotIn("additionalContext", output)
        result = json.loads(self.hook(file_path="work/tasks/test/questions.md", content="none"))
        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertNotIn("additionalContext", result["hookSpecificOutput"])


class PublishTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.standard = scaffold(self.sb.root / "standard", "standard")
        self.sb.store = self.standard
        self.sb.git(self.standard, "init", "-q")
        self.sb.git(self.standard, "config", "user.name", "Researcher")
        self.sb.git(self.standard, "config", "user.email", "research@example.test")
        self.sb.write(".svod-local.yaml", "login: Researcher\n")
        self.record = "work/research/cache"
        self.card = self.sb.write(f"{self.record}/card.md",
                                 "---\ntype: card\noutcome: knowledge\ntags: [db]\n"
                                 "status: done\n---\n# Cache\n")
        self.findings = self.sb.write(f"{self.record}/findings.md", "# Findings\n\nExact answer.\n")

    def prompt(self, text):
        with mock.patch.dict(os.environ, self.sb.env):
            hooks.answer(hooks.EVENT_PROMPT, {"cwd": str(self.standard), "prompt": text})

    def publish(self):
        return self.sb.cli("knowledge", "publish", self.record)

    def test_explicit_snapshot_then_next_go_publishes_and_closes_with_provenance(self):
        original = self.findings.read_bytes()
        self.prompt("go ahead")
        refused = self.publish()
        self.assertEqual(1, refused.returncode)
        self.assertIn("Exact answer.", refused.stdout)
        self.assertFalse((self.standard / "knowledge/cache.md").exists())
        self.prompt("go ahead")
        result = self.publish()
        self.assertEqual(0, result.returncode, result.stderr)
        note = self.standard / "knowledge/cache.md"
        fields = read_frontmatter(note)
        self.assertEqual(self.record, fields["source"])
        self.assertEqual(["db"], fields["tags"])
        self.assertEqual("Researcher", fields["published_by"])
        self.assertEqual(64, len(fields["prompt_sha"]))
        self.assertEqual(original.decode(), knowledge.split_document(note.read_text())[1])
        self.assertEqual(original, self.findings.read_bytes())
        self.assertEqual("knowledge/cache.md", read_frontmatter(self.card)["knowledge"])
        self.assertEqual("done", read_frontmatter(self.card)["status"])
        before = note.read_bytes()
        self.assertEqual(0, self.publish().returncode)
        self.assertEqual(before, note.read_bytes())

    def test_forged_note_provenance_cannot_authorize_close(self):
        from svod.yamlio import dump_yaml
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        request = self.publish()
        digest = request.stdout.split("Snapshot ", 1)[1].splitlines()[0]
        note = self.standard / "knowledge/cache.md"
        fields = {"title": "Cache", "tags": ["db"], "source": self.record,
                  "status": "current", "publication_sha": digest,
                  "prompt_sha": "0" * 64, "published_by": "Forged"}
        note.write_text("---\n" + dump_yaml(fields) + "---\n" + self.findings.read_text())
        before = note.read_bytes()
        result = self.sb.cli_process("knowledge", "publish", self.record)
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertEqual("open", read_frontmatter(self.card)["status"])
        self.assertNotIn("knowledge", read_frontmatter(self.card))
        self.assertEqual(before, note.read_bytes())

    def test_completed_publication_cannot_reclose_reopened_record_without_new_consent(self):
        self.publish()
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        note = self.standard / "knowledge/cache.md"
        before = note.read_bytes()
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        self.assertEqual(1, self.publish().returncode)
        self.assertEqual("open", read_frontmatter(self.card)["status"])
        self.assertEqual(before, note.read_bytes())
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        self.assertEqual("done", read_frontmatter(self.card)["status"])
        self.assertEqual(before, note.read_bytes())

    def test_later_human_event_invalidates_go_until_a_fresh_request(self):
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        self.publish()
        self.prompt("go ahead")
        self.prompt("No. Do not publish this research.")
        self.prompt("go ahead")
        result = self.sb.cli_process("knowledge", "publish", self.record)
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertEqual("open", read_frontmatter(self.card)["status"])
        self.assertFalse((self.standard / "knowledge/cache.md").exists())
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)

    def test_later_human_event_also_revokes_interrupted_close(self):
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        self.publish()
        self.prompt("go ahead")
        index = self.standard / "knowledge/INDEX.md"
        if index.exists():
            index.unlink()
        index.mkdir()
        self.assertEqual(1, self.publish().returncode)
        note = self.standard / "knowledge/cache.md"
        before = note.read_bytes()
        index.rmdir()
        self.prompt("No. Do not close this research.")
        self.assertEqual(1, self.publish().returncode)
        self.assertEqual("open", read_frontmatter(self.card)["status"])
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        self.assertEqual("done", read_frontmatter(self.card)["status"])
        self.assertEqual(before, note.read_bytes())

    def test_later_refusal_or_unrelated_human_event_blocks_publication(self):
        for text in ("No. Do not publish this research.", "What about latency?", "go ahead"):
            with self.subTest(text=text):
                self.assertEqual(1, self.publish().returncode)
                self.prompt("go ahead")
                self.prompt(text)
                self.assertEqual(1, self.publish().returncode)
                self.assertFalse((self.standard / "knowledge/cache.md").exists())

    def test_real_index_failure_retries_without_rewriting_native_note(self):
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        self.publish()
        self.prompt("go ahead")
        index = self.standard / "knowledge/INDEX.md"
        if index.exists():
            index.unlink()
        index.mkdir()
        failed = self.sb.cli_process("knowledge", "publish", self.record)
        self.assertEqual(1, failed.returncode)
        self.assertEqual("open", read_frontmatter(self.card)["status"])
        note = self.standard / "knowledge/cache.md"
        before = note.read_bytes()
        index.rmdir()
        retry = self.sb.cli_process("knowledge", "publish", self.record)
        self.assertEqual(0, retry.returncode, retry.stderr)
        self.assertEqual(before, note.read_bytes())
        self.assertEqual("done", read_frontmatter(self.card)["status"])

    def test_expired_interrupted_transaction_requires_new_consent(self):
        import datetime as dt
        from svod.approval import now
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        self.publish()
        self.prompt("go ahead")
        index = self.standard / "knowledge/INDEX.md"
        if index.exists():
            index.unlink()
        index.mkdir()
        self.assertEqual(1, self.publish().returncode)
        index.rmdir()
        with mock.patch("svod.approval.now", return_value=now() + dt.timedelta(days=1)):
            self.assertEqual(1, self.publish().returncode)
        self.assertEqual("open", read_frontmatter(self.card)["status"])

    def test_unrelated_reply_cannot_later_be_replaced_by_go(self):
        self.assertEqual(1, self.publish().returncode)
        self.prompt("what about latency?")
        self.prompt("go ahead")
        self.assertEqual(1, self.publish().returncode)
        self.assertFalse((self.standard / "knowledge/cache.md").exists())

    def test_publication_metadata_is_protected_from_direct_and_shell_writes(self):
        self.publish()
        for tool, data in (("Write", {"file_path": str(self.standard / ".git" /
                                                       knowledge.PUBLISH_MARK), "content": "{}"}),
                           ("Bash", {"command": f"echo '{{}}' > .git/{knowledge.PUBLISH_MARK}"})):
            result = hooks.answer(hooks.EVENT_PRE_TOOL,
                                  {"cwd": str(self.standard), "tool_name": tool,
                                   "tool_input": data})
            self.assertEqual("deny", json.loads(result)["hookSpecificOutput"]["permissionDecision"])

    def test_native_transaction_remains_guarded_after_publication(self):
        self.publish()
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        state = self.standard / ".git" / knowledge.PUBLISH_MARK
        before = state.read_bytes()
        calls = (("Write", {"file_path": str(state), "content": "{}"}),
                 ("Edit", {"file_path": str(state), "old_string": "completed",
                           "new_string": "publishing"}),
                 ("apply_patch", {"command": "*** Begin Patch\n*** Delete File: "
                                  + str(state) + "\n*** End Patch"}),
                 ("Bash", {"command": f"rm .git/{knowledge.PUBLISH_MARK}"}))
        for tool, data in calls:
            with self.subTest(tool=tool):
                result = hooks.answer(hooks.EVENT_PRE_TOOL,
                                      {"cwd": str(self.standard), "tool_name": tool,
                                       "tool_input": data})
                self.assertEqual("deny", json.loads(result)["hookSpecificOutput"]
                                 ["permissionDecision"])
                self.assertEqual(before, state.read_bytes())

    def test_rejects_wrong_outcome_missing_findings_and_collision_without_closing(self):
        original = self.card.read_text().replace("status: done", "status: open")
        self.card.write_text(original.replace("outcome: knowledge", "outcome: task"))
        self.assertEqual(1, self.publish().returncode)
        self.card.write_text(original)
        self.findings.unlink()
        self.assertEqual(1, self.publish().returncode)
        self.findings.write_text("Answer\n")
        collision = knowledge.note(self.standard, "Different", ["db"], "Cache")
        before = collision.read_bytes()
        self.assertEqual(1, self.publish().returncode)
        self.assertEqual(before, collision.read_bytes())
        self.assertEqual("open", read_frontmatter(self.card)["status"])

    def test_configured_consent_and_process_cli_close_an_open_record(self):
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        config = self.standard / "svod.yaml"
        config.write_text(config.read_text() + "\nexternal_effects:\n  phrases: [proceed]\n")
        self.assertEqual(1, self.sb.cli_process("knowledge", "publish", self.record).returncode)
        self.prompt("go ahead")
        self.assertEqual(1, self.publish().returncode)
        self.prompt("proceed")
        result = self.sb.cli_process("knowledge", "publish", self.record)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("done", read_frontmatter(self.card)["status"])

    def test_status_and_hooks_do_not_publish_and_findings_metadata_cannot_override_source(self):
        self.findings.write_text("---\nsource: forged\ntags: [forged]\n"
                                 "status: superseded\n---\nBody\n")
        self.sb.cli("status", self.record)
        self.prompt("go ahead")
        self.assertFalse((self.standard / "knowledge/cache.md").exists())
        self.publish()
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        fields = read_frontmatter(self.standard / "knowledge/cache.md")
        self.assertEqual(self.record, fields["source"])
        self.assertEqual(["db"], fields["tags"])
        self.assertEqual("current", fields["status"])

    def test_changed_findings_require_a_new_snapshot(self):
        self.publish()
        self.prompt("go ahead")
        self.findings.write_text("Changed findings\n")
        self.assertEqual(1, self.publish().returncode)
        self.assertFalse((self.standard / "knowledge/cache.md").exists())
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)

    def test_publication_preserves_crlf_findings_and_retries(self):
        raw = b"# Findings\r\n\r\nExact answer.\r\n"
        self.findings.write_bytes(raw)
        self.publish()
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        note = self.standard / "knowledge/cache.md"
        self.assertTrue(note.read_bytes().endswith(raw))
        self.assertEqual(0, self.publish().returncode)

    def test_retry_refuses_changed_note_metadata(self):
        self.publish()
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        note = self.standard / "knowledge/cache.md"
        note.write_text(note.read_text().replace("tags:\n- db", "tags: [forged]"))
        before = note.read_bytes()
        self.assertEqual(1, self.publish().returncode)
        self.assertEqual(before, note.read_bytes())

    def test_completed_publication_consumes_consent(self):
        self.publish()
        self.prompt("go ahead")
        self.assertEqual(0, self.publish().returncode)
        (self.standard / "knowledge/cache.md").unlink()
        self.assertEqual(1, self.publish().returncode)
        self.assertFalse((self.standard / "knowledge/cache.md").exists())

    def test_index_failure_leaves_record_open_and_retry_repairs_close(self):
        from svod.cli import main
        self.card.write_text(self.card.read_text().replace("status: done", "status: open"))
        self.publish()
        self.prompt("go ahead")
        with mock.patch("svod.knowledge.write_index", side_effect=OSError("index failed")):
            result = main(["--root", str(self.standard), "knowledge", "publish", self.record])
        self.assertEqual(1, result)
        self.assertEqual("open", read_frontmatter(self.card)["status"])
        self.assertNotIn("knowledge", read_frontmatter(self.card))
        before = (self.standard / "knowledge/cache.md").read_bytes()
        self.assertEqual(0, self.publish().returncode)
        self.assertEqual("done", read_frontmatter(self.card)["status"])
        self.assertEqual(before, (self.standard / "knowledge/cache.md").read_bytes())
