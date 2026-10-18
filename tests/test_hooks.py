"""Agent hooks: session start summary, prompt positions and approval marks, pre-tool guards."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import task_example as te
from support import CLI_MODULE, CONFIG_FILE, ENCODING, EXIT_OK

from svod import git, hooks
from svod.approval import (HUMAN_FILE, HUMAN_GO, HUMAN_SHA, MARK_AT, MARK_KEYS, clear_mark,
                           fresh_human_mark, human_digest, human_path, read_human_mark, read_mark,
                           write_human_mark)
from svod.locale import Locale, load_core_locale
from svod.gates import ExistsGate
from svod.pipeline import parse_pipeline
from svod.subject import Subject

NO_OUTPUT = None
NO_MARK = None
DENIED_PLAN = f"work directory of {te.KEY} is not allowed"
DENIED_FIELDS = "plan_approved, plan_approved_by, plan_approved_sha"
DENIED_MAIN = "is read-only"
DENIED_MARK = "approval mark"
DENIED_BROKEN = "writes outside the store are refused"
DENIED_SCOPE = "svod allow"
DENIED_UNRESOLVED = "Cannot resolve shell write destinations"
MARK_PATH = ".git/svod-approval.json"
ENGINE_BROKEN = "failed to load"
POSITION = f"{te.CHANGE_NAME} ({te.KEY})"
MARKED = "is recorded and stays fresh"
WAIT = "wait for the approval"
UNNAMED_COMMAND = "svod approve <key>"
COMMON_DIR = ("rev-parse", "--git-common-dir")
MAX_EDIT_CALLS = 6  # Includes validated service worktree identity and repository relation.
NESTED = "nested"
NOTES = "notes.md"
LOCAL_CONFIG = ".svod.local.yaml"
SIDE_CHECKOUT = "store-side"
SIDE_BRANCH = "side"
ELSEWHERE = "elsewhere"
DENIED_HUMAN = "every message of a person"
DENIED_QUESTIONS = "svod answer"
DENIED_QUESTIONS_ASK = "svod ask"
DENIED_EXTERNAL = "effect outside this machine"
HUMAN_PATH = f".git/{HUMAN_FILE}"
QUESTIONS = f"{te.CHANGE}/questions.md"
WINDOW = 10
STALE_MINUTES = 20


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


def counting_git(calls):
    """run_git that records (directory, arguments) of every call before running git."""
    real = git.run_git

    def run(cwd, *args, **kwargs):
        """Record the call, then run it."""
        calls.append((str(cwd), args))
        return real(cwd, *args, **kwargs)
    return run


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
        cls.sb.write(te.META, te.META_TEXT + "services: [service]\n")
        te.set_config(cls.sb, services="{service: ../service}")
        cls.sb.commit(message=f"{te.KEY}: plan")
        cls.worktree = te.make_worktree(cls.sb)
        cls.sb.write(f"{te.CHANGE}/work.yaml", f"service: {cls.worktree}\n")
        cls.sb.commit(message="declare write scope")
        cls.sb.write(te.CODE_FILE, te.CODE_TEXT, base=cls.worktree)
        cls.sb.write(te.CODE_FILE, te.CODE_TEXT, base=te.service(cls.sb))
        cls.meta = cls.sb.store / te.META
        cls.meta_text = cls.meta.read_text(encoding=ENCODING)
        cls.config_path = cls.sb.store / CONFIG_FILE
        cls.config_text = cls.config_path.read_text(encoding=ENCODING)

    @classmethod
    def tearDownClass(cls):
        """Restore the environment and remove the store."""
        cls.patcher.stop()
        cls.sb.cleanup()

    def tearDown(self):
        """Drop the approval and the mark a case left."""
        self.meta.write_text(self.meta_text, encoding=ENCODING)
        self.config_path.write_text(self.config_text, encoding=ENCODING)
        clear_mark(self.sb.store)

    def answer(self, event_name, event, fallback=None):
        """Parsed hook answer, or None."""
        found = hooks.answer(event_name, event, fallback)
        return json.loads(found) if found else None

    def set_agent_context(self, **values):
        """Set optional hook output controls in the example store config."""
        lines = ["profile_config:", "  agent_context:"]
        lines.extend(f"    {name}: {'true' if enabled else 'false'}"
                     for name, enabled in values.items())
        self.config_path.write_text(self.config_text.rstrip() + "\n" + "\n".join(lines) + "\n",
                                    encoding=ENCODING)


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
                   f"*** Move to: {wt}/moved.go"), DENIED_SCOPE),
            ("bash in work dir before approval", False, wt, bash("echo x > main.go"),
             DENIED_PLAN),
            ("bash in-place edit in work dir before approval", False, wt,
             bash("sed -i 's/a/b/' main.go"), DENIED_PLAN),
            ("bash dd in work dir before approval", False, wt,
             bash("printf x | dd of=main.go"), DENIED_PLAN),
            ("bash python in work dir before approval", False, wt,
             bash("python3 -c \"open('main.go', 'w').write('x')\""), DENIED_PLAN),
            ("bash into work dir from the store before approval", False, store,
             bash(f"cp /tmp/x.go {wt}/main.go"), DENIED_PLAN),
            ("bash git checkout in work dir before approval", False, wt,
             bash("git checkout -- main.go"), DENIED_PLAN),
            ("bash reads in work dir before approval", False, wt,
             bash("cat main.go | grep main && git status && git log -1"), NO_OUTPUT),
            ("bash in work dir after approval", True, wt, bash("echo x > main.go"), NO_OUTPUT),
            ("bash writes elsewhere before approval", False, store,
             bash(f"echo x > {sb.root}/{ELSEWHERE}.txt"), DENIED_SCOPE),
            ("write of the approval mark", False, store, write(store / MARK_PATH, "{}"),
             DENIED_MARK),
            ("bash writes the approval mark", False, store,
             bash(f"echo '{{}}' > {MARK_PATH}"), DENIED_MARK),
            ("bash reads the approval mark", False, store, bash(f"cat {MARK_PATH}"), NO_OUTPUT),
            ("edit in work dir after approval", True, wt, edit(code), NO_OUTPUT),
            ("patch in work dir after approval", True, wt,
             patch(f"*** Update File: {te.CODE_FILE}\n@@\n-a\n+b"), NO_OUTPUT),
            ("edit in a main checkout of a service", False, wt,
             edit(sb.parent / te.SERVICE / te.CODE_FILE), DENIED_SCOPE),
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
            ("bash python reads metadata before writing review evidence", False, store,
             bash(f"""python3 <<'PY'
from pathlib import Path
p = Path('{te.CHANGE_NAME}')
raw = (p / '.openspec.yaml').read_bytes()
(p / 'review/independent.md').write_bytes(raw + b'plan_approved_sha')
PY"""), DENIED_UNRESOLVED),
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

    def test_python_metadata_reads_do_not_look_like_approval_writes(self):
        """Only explicit inline Path reads may mention guarded metadata and approval fields."""
        guarded = [hooks.Guarded(("task", ".openspec.yaml"),
                                 ("plan_approved_sha",))]
        allowed = (
            ("heredoc reads metadata and writes review evidence elsewhere", """python3 <<'PY'
from pathlib import Path
import yaml

p = Path('task')
metadata = yaml.safe_load((p / '.openspec.yaml').read_text())
raw = metadata['plan_approved_sha'].encode()
(p / 'review/independent.md').write_bytes(raw)
(p / 'review/independent.yaml').write_text(yaml.safe_dump(metadata))
PY"""),
            ("dash-c reads metadata and writes another file",
             "python3 -c \"from pathlib import Path; "
             "value = Path('task/.openspec.yaml').read_text(); "
             "Path('result.txt').write_text('plan_approved_sha=' + value)\""),
            ("inline path reads bytes",
             "python3 -c \"from pathlib import Path; "
             "Path('task/.openspec.yaml').read_bytes(); plan_approved_sha = True\""),
        )
        blocked = (
            ("write_text to metadata",
             "python3 -c \"from pathlib import Path; "
             "Path('task/.openspec.yaml').write_text('plan_approved_sha: x')\""),
            ("write_bytes to metadata",
             "python3 -c \"from pathlib import Path; "
             "Path('task/.openspec.yaml').write_bytes(b'plan_approved_sha: x')\""),
            ("open append to metadata",
             "python3 -c \"open('task/.openspec.yaml', 'a').write('plan_approved_sha: x')\""),
            ("open overwrite of metadata",
             "python3 -c \"open('task/.openspec.yaml', 'w').write('plan_approved_sha: x')\""),
            ("mixed metadata read and write", """python3 <<'PY'
from pathlib import Path

Path('task/.openspec.yaml').read_text()
Path('task/.openspec.yaml').write_text('plan_approved_sha: x')
PY"""),
            ("decoy read before dynamically named metadata write",
             "python3 -c \"from pathlib import Path; "
             "Path('safe/.openspec.yaml').read_text(); "
             "Path('target').joinpath('.open' + 'spec.yaml').write_text("
             "'plan_approved_sha: forged')\""),
            ("metadata write before a decoy heredoc read", """python3 -c "open(
'target/.openspec.yaml', 'w').write('plan_approved_sha: forged')"; cat <<'PY'
from pathlib import Path
Path('safe/.openspec.yaml').read_text()
PY"""),
            ("non-python decoy before actual python metadata writer",
             "echo -c \"from pathlib import Path; "
             "Path('safe/.openspec.yaml').read_text(); plan_approved_sha=True\"; "
             "python3 -c \"open('target/.openspec.yaml', 'w').write("
             "'plan_approved_sha: forged')\""),
            ("safe dash-c followed by node command",
             "python3 -c \"from pathlib import Path; "
             "Path('safe/.openspec.yaml').read_text(); plan_approved_sha=True\"; "
             "node -e \"process.exit(0)\""),
            ("safe dash-c followed by touch command",
             "python3 -c \"from pathlib import Path; "
             "Path('safe/.openspec.yaml').read_text(); plan_approved_sha=True\"; "
             "touch marker"),
            ("quoted heredoc followed by shell command", """python3 <<'PY'
from pathlib import Path
Path('safe/.openspec.yaml').read_text()
plan_approved_sha = True
PY
touch marker"""),
            ("quoted heredoc header followed by sibling command",
             "python3 <<'PY'; ruby -e "
             "'File.write(\"target/\"+\".open\"+\"spec.yaml\", \"plan_approved_sha: forged\")'\n"
             "from pathlib import Path\n"
             "Path('safe/.openspec.yaml').read_text()\n"
             "PY"),
            ("unquoted heredoc", """python3 <<PY
from pathlib import Path
Path('safe/.openspec.yaml').read_text()
plan_approved_sha = True
PY"""),
            ("decoy read before copy to dynamic metadata destination", """python3 <<'PY'
from pathlib import Path
import shutil

Path('safe/.openspec.yaml').read_text()
destination = Path('target') / ('.open' + 'spec.yaml')
shutil.copyfile('plan_approved_sha', destination)
PY"""),
            ("reserved Path name is reassigned",
             "python3 -c \"from pathlib import Path; "
             "Path = wrapper; Path('safe/.openspec.yaml').read_text(); "
             "plan_approved_sha = True\""),
            ("path alias",
             "python3 -c \"from pathlib import Path; "
             "meta = Path('task/.openspec.yaml'); "
             "meta.read_text(); plan_approved_sha = True\""),
            ("unknown path operation",
             "python3 -c \"from pathlib import Path; "
             "Path('task/.openspec.yaml').exists(); plan_approved_sha = True\""),
            ("malformed script",
             "python3 -c \"from pathlib import Path; "
             "Path('task/.openspec.yaml').read_text(; plan_approved_sha = True\""),
        )
        for name, command in allowed:
            with self.subTest(case=name):
                self.assertTrue(hooks.python_reads_metadata(command, ".openspec.yaml"))
                self.assertFalse(hooks.bash_writes_approval(command, guarded))
        for name, command in blocked:
            with self.subTest(case=name):
                self.assertFalse(hooks.python_reads_metadata(command, ".openspec.yaml"))
                self.assertTrue(hooks.bash_writes_approval(command, guarded))

    def test_read_only_main_checkout(self):
        """With the option on, the main checkout refuses edits except ignored paths."""
        sb, store = self.sb, self.sb.store
        side = sb.parent / SIDE_CHECKOUT
        sb.git(store, "worktree", "add", "-q", "-b", SIDE_BRANCH, str(side))
        self.addCleanup(sb.git, store, "worktree", "remove", "--force", str(side))
        config = (store / CONFIG_FILE).read_text(encoding=ENCODING)
        self.addCleanup((store / CONFIG_FILE).write_text, config, encoding=ENCODING)
        te.set_config(sb, main_checkout_read_only="true")
        nested = store / NESTED
        sb.init_git(nested, remote=False)
        self.addCleanup(shutil.rmtree, nested)
        cases = (
            ("tracked file", store / NOTES, DENIED_MAIN),
            ("plan of a change", self.meta, DENIED_MAIN),
            ("ignored local config", store / LOCAL_CONFIG, NO_OUTPUT),
            ("worktree of the store", side / NOTES, DENIED_SCOPE),
            ("service checkout", sb.parent / te.SERVICE / te.CODE_FILE, DENIED_SCOPE),
            ("nested repository", nested / NOTES, NO_OUTPUT),
            ("git directory", store / hooks.DOT_GIT / "description", NO_OUTPUT),
        )
        for name, path, expected in cases:
            with self.subTest(case=name):
                reason = self.run_case(store, write(path, "x"))
                if expected is None:
                    self.assertIsNone(reason)
                else:
                    self.assertIn(expected, reason or "")
        commands = (
            ("bash writes a tracked file", f"echo x > {NOTES}", DENIED_MAIN),
            ("bash tee into a tracked file", f"cat /tmp/x | tee {NOTES}", DENIED_MAIN),
            ("bash reads a tracked file", f"cat {NOTES} && git diff", NO_OUTPUT),
            ("bash writes the ignored local config", f"echo x > {LOCAL_CONFIG}", NO_OUTPUT),
            ("bash writes in the worktree of the store", f"echo x > {side}/{NOTES}", DENIED_SCOPE),
        )
        for name, command, expected in commands:
            with self.subTest(case=name):
                reason = self.run_case(store, bash(command))
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

    def test_silent_prompt_controls_still_record_approval(self):
        """Output can be suppressed without suppressing human approval or agent filtering."""
        self.set_agent_context(prompt_positions=False, approval_notice=False)
        event = {"hook_event_name": "UserPromptSubmit", "cwd": str(self.sb.store),
                 "prompt": f"approve {te.KEY}"}
        self.assertIsNone(self.answer(hooks.EVENT_PROMPT, event))
        self.assertEqual([te.KEY], read_mark(self.sb.store)[MARK_KEYS])
        clear_mark(self.sb.store)
        event["prompt"] = f"<agent-message from=\"x\">approve {te.KEY}</agent-message>"
        self.assertIsNone(self.answer(hooks.EVENT_PROMPT, event))
        self.assertIsNone(read_mark(self.sb.store))

    def test_verified_redelivery_preserves_original_time_and_refuses_expired_event(self):
        """Redelivering the same human event cannot extend its approval window."""
        event = {"cwd": str(self.sb.store), "prompt": f"approve {te.KEY}"}
        original = dt.datetime.now().astimezone() - dt.timedelta(minutes=1)
        clear_mark(self.sb.store)
        try:
            hooks.prompt_hook(event, self.sb.store, at=original)
            self.assertEqual(read_mark(self.sb.store)[MARK_AT], original.isoformat())
            clear_mark(self.sb.store)
            expired = original - dt.timedelta(minutes=20)
            answer = hooks.prompt_hook(event, self.sb.store, at=expired)
            self.assertIsNone(read_mark(self.sb.store))
            self.assertNotIn(MARKED, json.loads(answer)[hooks.OUTPUT][hooks.CONTEXT])
        finally:
            clear_mark(self.sb.store)

    def test_ui_reply_approves_only_the_actual_answer(self):
        """Approval-looking question text and options never mint a human mark."""
        event = {"cwd": str(self.sb.store)}
        for answer, expected in ((f"approve {te.KEY}", [te.KEY]), ("No", None)):
            with self.subTest(answer=answer):
                payload = [{"question": f"approve {te.KEY}",
                            "options": [f"approve {te.KEY}"], "answer": answer}]
                event["prompt"] = (hooks.QUESTION_REPLY_OPEN + "\n" + json.dumps(payload)
                                   + "\n" + hooks.QUESTION_REPLY_CLOSE)
                clear_mark(self.sb.store)
                hooks.prompt_hook(event, self.sb.store)
                mark = read_mark(self.sb.store)
                self.assertEqual(mark[MARK_KEYS] if mark else None, expected)
        self.assertEqual(hooks.human_answers(hooks.QUESTION_REPLY_OPEN + "garbage"
                                            + hooks.QUESTION_REPLY_CLOSE), [])

    def test_explicit_changes_phrase_is_supported_when_configured(self):
        runtime, reason = hooks.load(self.sb.store)
        self.assertIsNone(reason)
        from dataclasses import replace
        runtime.config = replace(runtime.config, approval_phrases=("одобряю", "одобряю изменения"))
        self.assertEqual(hooks.approval_keys(runtime, f"Одобряю изменения {te.KEY}"), [te.KEY])
        self.assertIsNone(hooks.approval_keys(runtime, f"не одобряю изменения {te.KEY}"))

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

    def test_session_summary_can_be_silent(self):
        """The session summary switch suppresses context while legacy remains enabled."""
        self.set_agent_context(session_summary=False)
        self.assertIsNone(self.answer(hooks.EVENT_SESSION_START,
                                      {"hook_event_name": "SessionStart",
                                       "cwd": str(self.sb.store)}))


class HookCostTest(HookTestCase):
    """What one event costs: the store loaded only when needed, each git call made once."""

    def calls(self, event_name, event):
        """(answer, git calls) of one hook event, the store given as the fallback."""
        calls = []
        with mock.patch.object(git, "run_git", counting_git(calls)):
            found = self.answer(event_name, event, self.sb.store)
        return found, calls

    def pre_tool(self, cwd, tool_input):
        """Pre-tool event of a tool call in cwd."""
        tool, data = tool_input
        return {"cwd": str(cwd), "tool_name": tool, "tool_input": data}

    def test_read_only_command_answers_before_loading(self):
        """A command that only reads never loads the store; a writing one does."""
        cases = (
            ("reads", "cat main.go | grep main && git status && git log -1", False),
            ("writes", "echo x > main.go", True),
        )
        for name, command, loads in cases:
            with self.subTest(case=name):
                with mock.patch.object(hooks.guard, "load", wraps=hooks.load) as load:
                    found, calls = self.calls(hooks.EVENT_PRE_TOOL,
                                              self.pre_tool(self.worktree, bash(command)))
                self.assertEqual(loads, load.called)
                if not loads:
                    self.assertIsNone(found)
                    self.assertEqual([], calls)

    def test_edits_have_bounded_validated_worktree_git_calls(self):
        """An allowed edit of a work directory and a refused edit of a read-only main checkout."""
        te.approve(self.sb)
        found, calls = self.calls(hooks.EVENT_PRE_TOOL,
                                  self.pre_tool(self.worktree, edit(self.worktree / te.CODE_FILE)))
        self.assertIsNone(found)
        self.assertLessEqual(len(calls), MAX_EDIT_CALLS, calls)
        te.set_config(self.sb, main_checkout_read_only="true")
        found, calls = self.calls(hooks.EVENT_PRE_TOOL,
                                  self.pre_tool(self.sb.store, write(self.sb.store / NOTES, "x")))
        self.assertIn(DENIED_MAIN, found[hooks.OUTPUT][hooks.DECISION_REASON])
        self.assertLessEqual(len(calls), MAX_EDIT_CALLS, calls)

    def test_no_git_call_is_repeated(self):
        """Session start, a prompt and an approving prompt ask git each question once."""
        store = str(self.sb.store)
        cases = (
            ("session start", hooks.EVENT_SESSION_START, {"cwd": store}),
            ("prompt", hooks.EVENT_PROMPT, {"cwd": store, "prompt": f"what about {te.KEY}"}),
            ("approval", hooks.EVENT_PROMPT, {"cwd": store, "prompt": f"approve {te.KEY}"}),
            ("frozen edit", hooks.EVENT_PRE_TOOL,
             self.pre_tool(self.worktree, edit(self.worktree / te.CODE_FILE))),
        )
        for name, event_name, event in cases:
            with self.subTest(case=name):
                _, calls = self.calls(event_name, event)
                clear_mark(self.sb.store)
                self.assertEqual(len(set(calls)), len(calls), calls)
        _, calls = self.calls(hooks.EVENT_PROMPT, cases[2][2])
        self.assertEqual(1, calls.count((store, COMMON_DIR)), calls)


class ApprovalNoticeTest(HookTestCase):
    """The notice of a recorded mark names the keys and never asks to wait for the approval."""

    def context(self, prompt):
        """Context the prompt hook adds for the prompt."""
        found = self.answer(hooks.EVENT_PROMPT, {"cwd": str(self.sb.store), "prompt": prompt})
        clear_mark(self.sb.store)
        return found[hooks.OUTPUT][hooks.CONTEXT]

    def test_named_and_unnamed(self):
        """Named keys get their command; without keys the placeholder stays."""
        named = self.context(f"approve {te.KEY}")
        self.assertIn(MARKED, named)
        self.assertIn(f"svod approve {te.KEY}", named)
        self.assertNotIn(UNNAMED_COMMAND, named)
        self.assertNotIn(WAIT, named)
        self.assertIn(POSITION, named)
        self.assertIn(WAIT, self.context(f"what about {te.KEY}"))
        self.assertIn(UNNAMED_COMMAND, self.context("LGTM."))

    def test_profile_without_variant_drops_the_next_step(self):
        """Without <text>_marked in the locale the waiting next step is left out."""
        runtime, _ = hooks.load(self.sb.store)
        ctx = hooks.context_of(runtime)
        ctx.locale = Locale({key: text for key, text in runtime.locale._strings.items()
                             if not key.endswith(hooks.VARIANT_SEPARATOR + hooks.REASON_MARKED)})
        found = hooks.positions(ctx, runtime.pipelines, [te.KEY], [te.KEY])
        self.assertTrue(found)
        self.assertNotIn(WAIT, found[0])
        self.assertIn(WAIT, hooks.positions(ctx, runtime.pipelines, [te.KEY])[0])

    def test_core_locales_have_both_notices(self):
        """Every core locale has the named and the unnamed notice."""
        for name in ("en", "ru"):
            with self.subTest(locale=name):
                locale = load_core_locale(name)
                self.assertTrue(locale.has(hooks.HOOK_APPROVAL_MARKED_UNNAMED))
                self.assertIn("{commands}", locale.text_template("hook.approval_marked"))


class ConditionalFreezeTest(unittest.TestCase):
    """Code freeze follows synthetic step and gate applicability declarations."""

    def test_freeze_skips_inapplicable_stages_and_gates(self):
        from types import SimpleNamespace

        pipeline, errors = parse_pipeline({
            "pipeline": "synthetic-freeze", "subject": {"provider": "synthetic"},
            "steps": [{"id": "orchard", "text": "synthetic.orchard",
                       "blocks_code": True, "when": "needs_fruit",
                       "gates": [{"gate": "exists", "when": "needs_seed"}]}],
        }, "synthetic-freeze.yaml")
        self.assertEqual(errors, [])
        assert pipeline is not None
        pipeline.steps[0].gates[0].impl = ExistsGate()
        guard = hooks.Guard.__new__(hooks.Guard)
        guard.ctx = None
        with mock.patch.object(guard, "runtime", SimpleNamespace(
                locale=SimpleNamespace(text=lambda key, **facts: key)), create=True):
            self.assert_freeze_cases(guard, pipeline)

    def assert_freeze_cases(self, guard, pipeline):
        """Both predicates must apply before the failing gate freezes code."""
        for attrs, expected in (({}, None), ({"needs_seed": True}, None),
                                ({"needs_fruit": True}, None),
                                ({"needs_fruit": True, "needs_seed": True}, "synthetic.orchard")):
            with self.subTest(attrs=attrs):
                subject = Subject("synthetic", None, exists=False, attrs=attrs)
                self.assertEqual(guard.frozen(pipeline, subject), expected)


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
        """session-start, prompt and an edit in the store get the line; a read stays silent.

        A write outside the store is refused: nothing guards it until the store loads again.
        """
        cwd = str(self.sb.store)
        outside = self.sb.root / ELSEWHERE / te.CODE_FILE
        cases = (
            ("session start", hooks.EVENT_SESSION_START, {"cwd": cwd}, hooks.CONTEXT),
            ("prompt", hooks.EVENT_PROMPT, {"cwd": cwd, "prompt": "hello"}, hooks.CONTEXT),
            ("edit in the store", hooks.EVENT_PRE_TOOL,
             {"cwd": cwd, "tool_name": "Edit", "tool_input": {"file_path": f"{cwd}/{NOTES}"}},
             hooks.CONTEXT),
            ("edit outside the store", hooks.EVENT_PRE_TOOL,
             {"cwd": cwd, "tool_name": "Edit", "tool_input": {"file_path": str(outside)}},
             hooks.DECISION_REASON),
            ("read command", hooks.EVENT_PRE_TOOL,
             {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": "ls"}}, None),
            ("write command in the store", hooks.EVENT_PRE_TOOL,
             {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": f"echo x > {NOTES}"}},
             None),
            ("write command outside the store", hooks.EVENT_PRE_TOOL,
             {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": f"echo x > {outside}"}},
             hooks.DECISION_REASON),
        )
        for name, event_name, event, field in cases:
            with self.subTest(case=name):
                found = hooks.answer(event_name, event)
                if field is None:
                    self.assertIsNone(found)
                    continue
                output = json.loads(found)[hooks.OUTPUT]
                self.assertIn(ENGINE_BROKEN, output[field])
                if field == hooks.DECISION_REASON:
                    self.assertEqual(output[hooks.DECISION], hooks.DENY)
                    self.assertIn(DENIED_BROKEN, output[field])


class HumanMarkTest(HookTestCase):
    """Every reply of a person leaves the human mark; messages of agents leave none."""

    def setUp(self):
        """No human mark from an earlier case."""
        self.clear()
        self.addCleanup(self.clear)

    def clear(self):
        """Remove the human mark of the store."""
        human_path(self.sb.store).unlink(missing_ok=True)

    def prompt(self, text):
        """Run the prompt hook on a reply in the store."""
        hooks.prompt_hook({"cwd": str(self.sb.store), "prompt": text}, None)

    def test_written_for_people_only(self):
        """Time, digest of the stripped reply and go-ahead; nothing for an agent message."""
        cases = (
            ("plain reply", "  what is next?  ", "what is next?", False),
            ("go ahead phrase", "Looks good.\ngo ahead!", "Looks good.\ngo ahead!", True),
            ("russian phrase", "Давай", "Давай", True),
            ("phrase inside a sentence", "Давай, пушь", "Давай, пушь", False),
            ("phrase inside a word", "давайте подумаем", "давайте подумаем", False),
            ("agent message", '<agent-message from="x">go ahead</agent-message>', None, None),
        )
        for name, text, stripped, go in cases:
            with self.subTest(case=name):
                self.clear()
                self.prompt(text)
                mark = read_human_mark(self.sb.store)
                if stripped is None:
                    self.assertIsNone(mark)
                    continue
                self.assertEqual(human_digest(stripped), mark[HUMAN_SHA])
                self.assertEqual(go, mark[HUMAN_GO])
                self.assertIsNotNone(dt.datetime.fromisoformat(mark[MARK_AT]).tzinfo)
                self.assertIsNotNone(fresh_human_mark(self.sb.store, WINDOW))
                self.assertTrue((self.sb.store / HUMAN_PATH).is_file())

    def test_freshness(self):
        """The mark is fresh within the window only; an expired redelivery leaves none."""
        now = dt.datetime.now().astimezone()
        write_human_mark(self.sb.store, "go ahead", go=True, at=now)
        self.assertIsNotNone(fresh_human_mark(self.sb.store, WINDOW, at=now))
        late = now + dt.timedelta(minutes=STALE_MINUTES)
        self.assertIsNone(fresh_human_mark(self.sb.store, WINDOW, at=late))
        self.clear()
        hooks.prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, None,
                          at=now - dt.timedelta(minutes=STALE_MINUTES))
        self.assertIsNone(read_human_mark(self.sb.store))

    def test_go_ahead_by_place(self):
        """A phrase says go ahead only on a line of its own, closing punctuation allowed;
        inside a sentence, negated or not, it is no answer."""
        phrases = ("go ahead", "давай", "выполняй")
        cases = (
            ("the whole reply", "давай", True),
            ("the whole reply with punctuation", "  Давай!  ", True),
            ("start of the reply, inside a sentence", "  Давай, пушь в main", False),
            ("start, other phrase, inside a sentence", "Go ahead and push it", False),
            ("alone on a line", "Посмотрел дифф, всё хорошо.\nДавай\nПотом закрой задачу", True),
            ("alone on a line with punctuation", "Diff is fine.\n  go ahead!  \nthen close it",
             True),
            ("end of a sentence", "Посмотрел, всё хорошо, давай.", False),
            ("end of a sentence, english", "Looks good to me, go ahead!!", False),
            ("middle of a long reply", "Хорошо, давай посмотрим сначала дифф и потом решим", False),
            ("negated on the line", "Нет, не давай.", False),
            ("negation after the phrase", "давай не будем", False),
            ("negation on another line", "Не трогай тесты.\nДавай", True),
            ("negated line, phrase later alone", "не давай\nвыполняй", True),
            ("inside a word", "давайте подумаем", False),
            ("no phrase", "покажи дифф", False),
        )
        for name, text, go in cases:
            with self.subTest(case=name):
                self.assertEqual(go, hooks.says_go(text, phrases))

    def test_answer_of_a_question_reply(self):
        """A reply to a question of the agent is marked by its answers only."""
        payload = [{"question": "push?", "options": ["go ahead"], "answer": "no"}]
        self.prompt(hooks.QUESTION_REPLY_OPEN + json.dumps(payload) + hooks.QUESTION_REPLY_CLOSE)
        mark = read_human_mark(self.sb.store)
        self.assertEqual(human_digest("no"), mark[HUMAN_SHA])
        self.assertFalse(mark[HUMAN_GO])


class MarkAndQuestionsGuardTest(PreToolTest):
    """The human mark and the questions of a record are written by svod, never by the agent."""

    def test_refusals(self):
        """Writes are refused by tool and by command; reads and other files are let through."""
        store = self.sb.store
        cases = (
            ("write of the human mark", write(store / HUMAN_PATH, "{}"), DENIED_HUMAN),
            ("edit of the human mark", edit(store / HUMAN_PATH), DENIED_HUMAN),
            ("bash writes the human mark", bash(f"echo '{{}}' > {HUMAN_PATH}"), DENIED_HUMAN),
            ("bash reads the human mark", bash(f"cat {HUMAN_PATH}"), NO_OUTPUT),
            ("write of questions", write(store / QUESTIONS, "x"), DENIED_QUESTIONS),
            ("edit of questions", edit(store / QUESTIONS), DENIED_QUESTIONS),
            ("patch of questions", patch(f"*** Add File: {QUESTIONS}\n+x"), DENIED_QUESTIONS),
            ("bash appends to questions", bash(f"echo x >> {QUESTIONS}"), DENIED_QUESTIONS),
            ("bash reads questions", bash(f"cat {QUESTIONS}"), NO_OUTPUT),
            ("questions outside a store", write(self.sb.root / ELSEWHERE / "questions.md", "x"),
             DENIED_SCOPE),
            ("questions at the store root", write(store / "questions.md", "x"), NO_OUTPUT),
            ("svod ask adds a question", bash(f"svod ask {te.CHANGE} 'Which?'"), NO_OUTPUT),
        )
        for name, tool_input, expected in cases:
            with self.subTest(case=name):
                reason = self.run_case(store, tool_input)
                if expected is None:
                    self.assertIsNone(reason)
                else:
                    self.assertIn(expected, reason or "")

    def test_questions_refusal_names_both_commands(self):
        """A refused questions write names svod ask for questions, svod answer for answers."""
        reason = self.run_case(self.sb.store, write(self.sb.store / QUESTIONS, "## Q: x"))
        for command in (DENIED_QUESTIONS_ASK, DENIED_QUESTIONS):
            with self.subTest(command=command):
                self.assertIn(command, reason or "")


class ExternalEffectsTest(PreToolTest):
    """Commands with an external effect wait for a person who says go ahead."""

    def setUp(self):
        """No human mark from an earlier case."""
        human_path(self.sb.store).unlink(missing_ok=True)
        self.addCleanup(human_path(self.sb.store).unlink, missing_ok=True)

    def check(self, cases, cwd=None):
        """Each (name, command, refused) against the pre-tool hook, the store as the fallback."""
        for name, command, refused in cases:
            with self.subTest(case=name):
                reason = self.run_case(cwd or self.sb.store, bash(command), self.sb.store)
                if refused:
                    self.assertIn(DENIED_EXTERNAL, reason or "")
                else:
                    self.assertNotIn(DENIED_EXTERNAL, reason or "")

    def say(self, text):
        """A reply of the person in the chat of the store."""
        hooks.prompt_hook({"cwd": str(self.sb.store), "prompt": text}, None)

    def test_standard_list(self):
        """The standard list is refused; dry runs, reads and local copies are not."""
        self.check((
            ("git push", "git push origin main", True),
            ("git push in a chain", "git add -A && git commit -m x && git push", True),
            ("git push dry run", "git push --dry-run origin main", False),
            ("git push in sh -c", "bash -c 'git push -u origin x'", True),
            ("git status", "git status && git log -1", False),
            ("gh pr merge", "gh pr merge 12 --squash", True),
            ("gh pr view", "gh pr view 12", False),
            ("gh release create", "gh release create v1.0", True),
            ("gh release list", "gh release list", False),
            ("npm publish", "npm publish --access public", True),
            ("npm test", "npm test", False),
            ("pip upload", "pip upload dist/x.whl", True),
            ("twine upload", "twine upload dist/*", True),
            ("python -m twine upload", "python3 -m twine upload dist/*", True),
            ("docker push", "sudo docker push registry/img:1", True),
            ("docker build", "docker build -t img .", False),
            ("kubectl apply", "kubectl -n prod apply -f deploy.yaml", True),
            ("kubectl delete", "kubectl delete pod x", True),
            ("kubectl get", "kubectl get pods", False),
            ("terraform apply", "terraform apply -auto-approve", True),
            ("terraform plan", "terraform plan", False),
            ("ssh", "ssh host uptime", True),
            ("scp", "scp a.txt host:/tmp/", True),
            ("rsync to a host", "rsync -av build/ user@host:/srv/app/", True),
            ("rsync local", "rsync -av build/ /tmp/copy/", False),
            ("env prefix", "FOO=1 env git push", True),
        ))

    def test_merge_and_rebase_in_a_main_checkout(self):
        """merge and rebase are refused in a main checkout, of a service or the store, only."""
        service = self.sb.parent / te.SERVICE
        self.check((("merge in the store", "git merge side", True),
                    ("rebase with -C to the service", f"git -C {service} rebase main", True)))
        self.check((("merge in a service checkout", "git merge side", True),), cwd=service)
        self.check((("merge in a worktree", "git merge main", False),
                    ("rebase in a worktree", "git rebase main", False)), cwd=self.worktree)

    def test_config_deny_and_allow(self):
        """external_effects extends the list and exempts commands by pattern."""
        te.set_config(self.sb, external_effects=(
            '{deny: ["^make deploy"], allow: ["^git push origin feature"]}'))
        self.check((
            ("denied by config", "make deploy ENV=prod", True),
            ("other make target", "make test", False),
            ("allowed by config", "git push origin feature-x", False),
            ("still standard", "git push origin main", True),
        ))

    def test_errors_of_the_block(self):
        """A bad external_effects block does not load."""
        cases = (
            ("unknown key", "{block: [x]}", "external_effects: unknown key: block"),
            ("bad pattern", '{deny: ["("]}', "invalid pattern"),
            ("not a list", "{phrases: go}", "external_effects.phrases must be a list"),
        )
        for name, value, message in cases:
            with self.subTest(case=name):
                te.set_config(self.sb, external_effects=value)
                runtime, reason = hooks.load(self.sb.store)
                self.assertIsNone(runtime)
                self.assertIn(message, reason)

    def test_lifted_by_a_fresh_go_ahead(self):
        """Asked, the person answered go ahead, then the command runs; otherwise it waits."""
        refused = (("git push", "git push origin main", True),)
        allowed = (("git push", "git push origin main", False),)
        self.check(refused)
        self.say("not yet, show me the diff first")
        self.check(refused)
        self.say("Нет, не давай")
        self.check(refused)
        self.say("Хорошо, давай сначала покажешь дифф, а потом решим")
        self.check(refused)
        self.say("Давай")
        self.check(allowed)
        stale = dt.datetime.now().astimezone() - dt.timedelta(minutes=STALE_MINUTES)
        write_human_mark(self.sb.store, "go ahead", go=True, at=stale)
        self.check(refused)
        te.set_config(self.sb, external_effects='{phrases: ["ship it"]}')
        self.say("go ahead")
        self.check(refused)
        self.say("ship it")
        self.check(allowed)

    def test_whatever_the_autonomy(self):
        """An autonomous pipeline lifts its approvals, never the external rule."""
        code = edit(self.worktree / te.CODE_FILE)
        self.assertIn(DENIED_PLAN, self.run_case(self.worktree, code, self.sb.store) or "")
        te.set_config(self.sb, autonomy="{task: autonomous}")
        self.check((("git push", "git push origin main", True),))
        self.assertIsNone(self.run_case(self.worktree, code, self.sb.store))


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
