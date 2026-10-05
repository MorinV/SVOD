"""Agent hooks: session start summary, prompt positions and approval marks, pre-tool guards."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import task_example as te
from support import CLI_MODULE, CONFIG_FILE, ENCODING, EXIT_OK

from svod import hooks
from svod.approval import MARK_KEYS, clear_mark, read_mark

NO_OUTPUT = None
NO_MARK = None
DENIED_PLAN = f"work directory of {te.KEY} is not allowed"
DENIED_FIELDS = "plan_approved, plan_approved_by, plan_approved_sha"
DENIED_MAIN = "is read-only"
ENGINE_BROKEN = "failed to load"
POSITION = f"{te.CHANGE_NAME} ({te.KEY})"
MARKED = "approval mark is recorded"
NOTES = "notes.md"
LOCAL_CONFIG = ".svod.local.yaml"
SIDE_CHECKOUT = "store-side"
SIDE_BRANCH = "side"
ELSEWHERE = "elsewhere"


def edit(path, old="a", new="b"):
    """Edit tool input."""
    return "Edit", {"file_path": str(path), "old_string": old, "new_string": new}


def write(path, content):
    """Write tool input."""
    return "Write", {"file_path": str(path), "content": content}


def multi_edit(path, *pairs):
    """MultiEdit tool input."""
    return "MultiEdit", {"file_path": str(path),
                         "edits": [{"old_string": o, "new_string": n} for o, n in pairs]}


def patch(text):
    """apply_patch tool input of Codex."""
    return "apply_patch", {"command": f"*** Begin Patch\n{text}\n*** End Patch"}


def bash(command):
    """Bash tool input."""
    return "Bash", {"command": command}


class HookTestCase(unittest.TestCase):
    """Store from the example with a specified change, a service and its task work directory."""

    @classmethod
    def setUpClass(cls):
        """Build the store once; git isolated and the project directory unset."""
        cls.sb = te.make_task_store()
        cls.patcher = mock.patch.dict(os.environ, cls.sb.env)
        cls.patcher.start()
        os.environ.pop(hooks.PROJECT_ENV, None)
        te.propose(cls.sb)
        te.specify(cls.sb)
        cls.sb.commit(message=f"{te.KEY}: plan")
        cls.worktree = te.make_worktree(cls.sb)
        cls.sb.write(te.CODE_FILE, te.CODE_TEXT, base=cls.worktree)
        cls.sb.write(te.CODE_FILE, te.CODE_TEXT, base=te.service(cls.sb))
        cls.meta = cls.sb.store / te.META
        cls.meta_text = cls.meta.read_text(encoding=ENCODING)

    @classmethod
    def tearDownClass(cls):
        """Restore the environment and remove the store."""
        cls.patcher.stop()
        cls.sb.cleanup()

    def tearDown(self):
        """Drop the approval and the mark a case left."""
        self.meta.write_text(self.meta_text, encoding=ENCODING)
        clear_mark(self.sb.store)

    def answer(self, event_name, event, fallback=None):
        """Parsed hook answer, or None."""
        found = hooks.answer(event_name, event, fallback)
        return json.loads(found) if found else None


class PreToolTest(HookTestCase):
    """Refusals of edits of approval fields, of frozen code and of a read-only main checkout."""

    def run_case(self, cwd, tool_input, fallback=None):
        """Refusal reason of the pre-tool hook, or None when it stays silent."""
        tool, data = tool_input
        found = self.answer(hooks.EVENT_PRE_TOOL,
                            {"hook_event_name": "PreToolUse", "cwd": str(cwd),
                             "tool_name": tool, "tool_input": data}, fallback)
        if found is None:
            return None
        output = found[hooks.OUTPUT]
        self.assertEqual(hooks.DENY, output.get(hooks.DECISION), output)
        return output[hooks.DECISION_REASON]

    def test_work_directory_and_approval_fields(self):
        """Each tool call is refused or let through by the rules."""
        sb, wt, store, meta = self.sb, self.worktree, self.sb.store, self.meta
        code = wt / te.CODE_FILE
        cases = (
            ("edit in work dir before approval", False, wt, edit(code), DENIED_PLAN),
            ("write in work dir before approval", False, wt, write(wt / "new.go", "x"),
             DENIED_PLAN),
            ("multiedit in work dir before approval", False, wt,
             multi_edit(code, ("a", "b")), DENIED_PLAN),
            ("patch relative before approval", False, wt,
             patch(f"*** Update File: {te.CODE_FILE}\n@@\n-a\n+b"), DENIED_PLAN),
            ("patch absolute add before approval", False, store,
             patch(f"*** Add File: {wt}/x.go\n+package main"), DENIED_PLAN),
            ("patch move into work dir before approval", False, store,
             patch(f"*** Update File: {sb.parent}/{te.SERVICE}/{te.CODE_FILE}\n"
                   f"*** Move to: {wt}/moved.go"), DENIED_PLAN),
            ("bash in work dir before approval", False, wt, bash("echo x > main.go"),
             NO_OUTPUT),
            ("edit in work dir after approval", True, wt, edit(code), NO_OUTPUT),
            ("patch in work dir after approval", True, wt,
             patch(f"*** Update File: {te.CODE_FILE}\n@@\n-a\n+b"), NO_OUTPUT),
            ("edit in a main checkout of a service", False, wt,
             edit(sb.parent / te.SERVICE / te.CODE_FILE), NO_OUTPUT),
            ("edit sets an approval field", False, store,
             edit(meta, "schema: spec-driven", "plan_approved: 2026-01-01"), DENIED_FIELDS),
            ("edit of another metadata field", False, store,
             edit(meta, "schema: spec-driven", "schema: other"), NO_OUTPUT),
            ("multiedit removes an approval field", True, store,
             multi_edit(meta, ("plan_approved_by: x", "")), DENIED_FIELDS),
            ("write adds an approval field", False, store,
             write(meta, self.meta_text + "plan_approved: 2026-01-01\n"), DENIED_FIELDS),
            ("write keeps the approval fields", False, store,
             write(meta, self.meta_text + "note: kept\n"), NO_OUTPUT),
            ("patch adds an approval field", False, store,
             patch(f"*** Update File: {te.META}\n@@\n ticket: {te.KEY}\n+plan_approved_by: me"),
             DENIED_FIELDS),
            ("patch near an approval field", False, store,
             patch(f"*** Update File: {te.META}\n@@\n plan_approved: x\n+note: kept"), NO_OUTPUT),
            ("bash appends an approval field", False, store,
             bash(f"echo 'plan_approved: 2026-01-01' >> {te.META}"), DENIED_FIELDS),
            ("bash edits in place", False, store,
             bash(f"sed -i '' 's/plan_approved: .*//' {te.META}"), DENIED_FIELDS),
            ("bash tee", False, store,
             bash(f"echo plan_approved_by: me | tee -a {te.META}"), DENIED_FIELDS),
            ("bash python literal", False, store,
             bash(f"python3 -c \"open('{te.META}', 'a').write('plan_approved: x')\""),
             DENIED_FIELDS),
            ("bash copies over the metadata", False, store,
             bash(f"cp /tmp/plan_approved.yaml {te.META}"), DENIED_FIELDS),
            ("bash reads an approval field", False, store,
             bash(f"grep plan_approved {te.META}"), NO_OUTPUT),
            ("edit in the store, read-only off", False, store, edit(store / NOTES), NO_OUTPUT),
        )
        for name, approved, cwd, tool_input, expected in cases:
            with self.subTest(case=name):
                if approved:
                    te.approve(sb)
                reason = self.run_case(cwd, tool_input, fallback=store)
                self.meta.write_text(self.meta_text, encoding=ENCODING)
                if expected is None:
                    self.assertIsNone(reason)
                else:
                    self.assertIn(expected, reason or "")

    def test_read_only_main_checkout(self):
        """With the option on, the main checkout refuses edits except ignored paths."""
        sb, store = self.sb, self.sb.store
        side = sb.parent / SIDE_CHECKOUT
        sb.git(store, "worktree", "add", "-q", "-b", SIDE_BRANCH, str(side))
        config = (store / CONFIG_FILE).read_text(encoding=ENCODING)
        self.addCleanup((store / CONFIG_FILE).write_text, config, encoding=ENCODING)
        te.set_config(sb, main_checkout_read_only="true")
        cases = (
            ("tracked file", store / NOTES, DENIED_MAIN),
            ("plan of a change", self.meta, DENIED_MAIN),
            ("ignored local config", store / LOCAL_CONFIG, NO_OUTPUT),
            ("worktree of the store", side / NOTES, NO_OUTPUT),
            ("service checkout", sb.parent / te.SERVICE / te.CODE_FILE, NO_OUTPUT),
        )
        for name, path, expected in cases:
            with self.subTest(case=name):
                reason = self.run_case(store, write(path, "x"))
                if expected is None:
                    self.assertIsNone(reason)
                else:
                    self.assertIn(expected, reason or "")

    def test_other_tools_and_missing_store(self):
        """Tools that do not edit, and sessions outside any store, are let through."""
        cases = (
            ("read tool", self.sb.store, ("Read", {"file_path": str(self.meta)}), None),
            ("no store", self.sb.root / ELSEWHERE, edit(self.worktree / te.CODE_FILE), None),
        )
        for name, cwd, tool_input, fallback in cases:
            with self.subTest(case=name):
                self.assertIsNone(self.run_case(cwd, tool_input, fallback))


class PromptTest(HookTestCase):
    """Positions named in a prompt and the approval mark of a whole approving prompt."""

    def test_prompts(self):
        """Context and mark per prompt."""
        cases = (
            ("key in any case", "what is next for proj-1?", POSITION, NO_MARK),
            ("exact name", f"look at {te.CHANGE_NAME} please", POSITION, NO_MARK),
            ("approval as a whole", f"approve {te.KEY}", MARKED, [te.KEY]),
            ("approval with joined keys", f"Approve {te.KEY} and {te.OTHER_KEY}!", MARKED,
             [te.KEY, te.OTHER_KEY]),
            ("approval without keys", "LGTM.", MARKED, []),
            ("phrase inside a text", f"do not approve {te.KEY} yet", POSITION, NO_MARK),
            ("phrase with other words", "approve the plan", NO_OUTPUT, NO_MARK),
            ("message of an agent", f"<agent-message from=\"x\">approve {te.KEY}</agent-message>",
             NO_OUTPUT, NO_MARK),
            ("key unknown to the store", "look at PROJ-9", NO_OUTPUT, NO_MARK),
        )
        for name, prompt, expected, mark in cases:
            with self.subTest(case=name):
                found = self.answer(hooks.EVENT_PROMPT,
                                    {"hook_event_name": "UserPromptSubmit",
                                     "cwd": str(self.sb.store), "prompt": prompt})
                written = read_mark(self.sb.store)
                clear_mark(self.sb.store)
                if expected is None:
                    self.assertIsNone(found)
                else:
                    self.assertIn(expected, found[hooks.OUTPUT][hooks.CONTEXT])
                self.assertEqual(mark, written[MARK_KEYS] if written else None)

    def test_session_start(self):
        """Summary from the store of the cwd or the fallback; silence without a store."""
        elsewhere = self.sb.root / ELSEWHERE
        cases = (
            ("cwd in the store", self.sb.store, None, te.CHANGE_NAME),
            ("fallback store", elsewhere, self.sb.store, te.CHANGE_NAME),
            ("no store", elsewhere, None, NO_OUTPUT),
        )
        for name, cwd, fallback, expected in cases:
            with self.subTest(case=name):
                found = self.answer(hooks.EVENT_SESSION_START,
                                    {"hook_event_name": "SessionStart", "cwd": str(cwd)},
                                    fallback)
                if expected is None:
                    self.assertIsNone(found)
                else:
                    self.assertIn(expected, found[hooks.OUTPUT][hooks.CONTEXT])


class BrokenStoreTest(unittest.TestCase):
    """A store that does not load is reported in one line, by every hook that may speak."""

    def setUp(self):
        """Copy of the example whose profile directory is missing."""
        self.sb = te.make_task_store()
        patcher = mock.patch.dict(os.environ, self.sb.env)
        patcher.start()
        os.environ.pop(hooks.PROJECT_ENV, None)
        self.addCleanup(patcher.stop)
        self.addCleanup(self.sb.cleanup)
        te.set_config(self.sb, profile="missing")

    def test_engine_broken_line(self):
        """session-start, prompt and an edit get the line; a shell command stays silent."""
        cwd = str(self.sb.store)
        cases = (
            (hooks.EVENT_SESSION_START, {"cwd": cwd}, True),
            (hooks.EVENT_PROMPT, {"cwd": cwd, "prompt": "hello"}, True),
            (hooks.EVENT_PRE_TOOL, {"cwd": cwd, "tool_name": "Edit",
                                    "tool_input": {"file_path": f"{cwd}/{NOTES}"}}, True),
            (hooks.EVENT_PRE_TOOL, {"cwd": cwd, "tool_name": "Bash",
                                    "tool_input": {"command": "ls"}}, False),
        )
        for event_name, event, speaks in cases:
            with self.subTest(event=event_name, tool=event.get("tool_name")):
                found = hooks.answer(event_name, event)
                if speaks:
                    context = json.loads(found)[hooks.OUTPUT][hooks.CONTEXT]
                    self.assertIn(ENGINE_BROKEN, context)
                else:
                    self.assertIsNone(found)


class HookCliTest(HookTestCase):
    """svod hook reads stdin, answers JSON and always exits 0."""

    def test_cli(self):
        """A refusal, garbage input and an unrelated tool, as a black box."""
        event = {"cwd": str(self.worktree), "tool_name": "Edit",
                 "tool_input": {"file_path": str(self.worktree / te.CODE_FILE)}}
        cases = (
            ("refusal", hooks.EVENT_PRE_TOOL, json.dumps(event), hooks.DENY),
            ("garbage", hooks.EVENT_PROMPT, "not json", ""),
            ("unrelated tool", hooks.EVENT_PRE_TOOL, json.dumps({"tool_name": "Read"}), ""),
        )
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for name, event_name, stdin, expected in cases:
            with self.subTest(case=name):
                out = subprocess.run(
                    [sys.executable, "-m", CLI_MODULE, "--root", str(self.sb.store), "hook",
                     event_name], input=stdin, capture_output=True, text=True,
                    encoding=ENCODING, env=env, cwd=str(self.sb.root))
                self.assertEqual(EXIT_OK, out.returncode, out.stderr)
                if expected:
                    self.assertIn(expected, out.stdout)
                else:
                    self.assertEqual("", out.stdout)


if __name__ == "__main__":
    unittest.main()
