"""The setup scripts of integrations/: project hooks of Claude Code, hooks.json of Codex.

Each test runs a setup script as a black box in a temporary Claude Code or Codex directory,
reads the JSON it wrote and runs the hook command it registered.

The Codex format is checked against the Codex source (github.com/openai/codex, commit
ce0323f2, 2026-10-17; developers.openai.com was not reachable from the test author's network):

- codex-rs/hooks/src/engine/discovery.rs reads `hooks.json` next to each config layer, so the
  user file is `$CODEX_HOME/hooks.json`;
- codex-rs/config/src/hook_config.rs: `HooksFile` has only `description` and `hooks` (unknown
  keys are an error); `hooks` maps event names to matcher groups `{matcher, hooks}`; a command
  handler is `{type: "command", command, timeout}` with the timeout in seconds, plus optional
  `commandWindows`, `async`, `statusMessage`, `additionalContextLimit`;
- codex-rs/core/src/tools/hook_names.rs: file edits arrive as the tool `apply_patch`, matched
  by `apply_patch`, `Write` or `Edit`; shell commands as `Bash`;
- codex-rs/hooks/schema/generated/*.command.output.schema.json: `hookSpecificOutput` with
  `hookEventName` and `additionalContext` (SessionStart, UserPromptSubmit) or
  `permissionDecision` `deny` with `permissionDecisionReason` (PreToolUse), the answer the
  engine gives Claude Code too.

The Claude Code project file is `<project>/.claude/settings.json` with the same `hooks` structure
as the user settings (code.claude.com/docs/en/hooks, "Where hooks are configured").
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from support import CLI_MODULE, CLI_TIMEOUT_SEC, ENCODING, EXIT_OK, EXIT_USAGE, REPO_DIR, TempStore

INTEGRATIONS = REPO_DIR / "integrations"
CLAUDE_SETUP = INTEGRATIONS / "setup-claude.sh"
CODEX_SETUP = INTEGRATIONS / "setup-codex.sh"
PROJECT_FLAG = "--project"
PROJECT_DIR = ".claude"
SETTINGS_FILE = "settings.json"
HOOKS_FILE = "hooks.json"
SKILLS_DIR = "skills"
SKILL = "svod-pipeline"
BACKUP_SUFFIX = ".bak-svod"
UP_TO_DATE = "-> hooks: up to date"
WARNING = "Warning:"
PYTHONPATH_PREFIX = "PYTHONPATH="
PYTHON = "python3"
SHELL = "sh"
DROPPED_ENV = ("CLAUDE_PROJECT_DIR", "SVOD_LAUNCHED", "CLAUDE_CONFIG_DIR", "CODEX_HOME")
EVENTS = {"SessionStart": "session-start", "UserPromptSubmit": "prompt", "PreToolUse": "pre-tool"}
TOOL_EVENT = "PreToolUse"
WATCHED_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "apply_patch")
CODEX_TOP_KEYS = {"description", "hooks"}
CODEX_EVENTS = {"PreToolUse", "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact",
                "SessionStart", "SessionEnd", "UserPromptSubmit", "SubagentStart",
                "SubagentStop", "Stop", "Interrupt"}
CODEX_GROUP_KEYS = {"matcher", "hooks"}
CODEX_HANDLER_KEYS = {"type", "command", "commandWindows", "timeout", "async", "statusMessage",
                      "additionalContextLimit"}
CODEX_EDIT_TOOL = "apply_patch"
CODEX_SHELL_TOOL = "Bash"
COMMAND_TYPE = "command"
FOREIGN_COMMAND = "python3 /tmp/json-hook.py"
FOREIGN_MATCHER = "^Bash$"
OLD_SVOD = "/old/venv/bin/svod"
VENV_DIR = "venv"
DEPS_PTH = "svod-test-deps.pth"
SITE_SCRIPT = "import sysconfig; print(sysconfig.get_paths()['purelib'])"


def read_json(path):
    """The parsed JSON file."""
    return json.loads(Path(path).read_text(encoding=ENCODING))


def write_json(path, data):
    """Write data as a JSON file, creating its directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding=ENCODING)


def svod_commands(data, event):
    """Commands of the svod hooks of an agent event in a parsed hooks file."""
    return [h["command"] for g in data["hooks"].get(event, []) for h in g["hooks"]
            if h["command"].endswith(f" hook {EVENTS[event]}")]


def tool_matcher(data):
    """The matcher of the group holding the svod pre-tool hook."""
    for group in data["hooks"][TOOL_EVENT]:
        if any(h["command"].endswith(f" hook {EVENTS[TOOL_EVENT]}") for h in group["hooks"]):
            return group["matcher"]
    raise AssertionError("no svod pre-tool hook")


class IntegrationTestCase(unittest.TestCase):
    """A temporary store and agent directory; the setup scripts run with PYTHONPATH set."""

    def setUp(self):
        """Create the store and the agent directory."""
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)
        self.store = self.sb.store.resolve()
        self.agent = Path(tempfile.mkdtemp(prefix="svod-agent-")).resolve()
        self.addCleanup(shutil.rmtree, self.agent, ignore_errors=True)

    def env(self, **extra):
        """Environment of a script or hook run: isolated git and HOME, this engine first."""
        env = dict(os.environ, **self.sb.env, PYTHONPATH=str(REPO_DIR),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        for name in DROPPED_ENV:
            env.pop(name, None)
        env.update(extra)
        return env

    def setup(self, script, *args, **extra):
        """Run a setup script; return the completed process."""
        return subprocess.run(["bash", str(script), *map(str, args)], env=self.env(**extra),
                              capture_output=True, text=True, encoding=ENCODING,
                              timeout=CLI_TIMEOUT_SEC)

    def run_hook(self, command, event, **env):
        """Run a registered hook command through the shell, as the agents do, on an event."""
        payload = json.dumps({"hook_event_name": event, "cwd": str(self.store),
                              "session_id": "test", "prompt": "hello"})
        return subprocess.run([SHELL, "-c", command], input=payload, cwd=str(self.store),
                              env=self.env(**env), capture_output=True, text=True,
                              encoding=ENCODING, timeout=CLI_TIMEOUT_SEC)

    def assert_hook_runs(self, command, event, **env):
        """The hook exits 0 and says nothing or a hookSpecificOutput of its event."""
        out = self.run_hook(command, event, **env)
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        if out.stdout.strip():
            answer = json.loads(out.stdout)
            self.assertEqual(answer["hookSpecificOutput"]["hookEventName"], event)

    def assert_engine_command(self, command, event):
        """An absolute Python running the engine module with the store as --root."""
        words = shlex.split(command)
        if words[0].startswith(PYTHONPATH_PREFIX):
            words = words[1:]
        self.assertTrue(os.path.isabs(words[0]), command)
        self.assertTrue(os.access(words[0], os.X_OK), command)
        self.assertEqual(words[1:], ["-m", CLI_MODULE, "--root", str(self.store),
                                     "hook", EVENTS[event]])

    def assert_registered(self, data):
        """Each svod hook once, an engine command, the tool matcher covering every tool."""
        for event in EVENTS:
            with self.subTest(event=event):
                commands = svod_commands(data, event)
                self.assertEqual(len(commands), 1, commands)
                self.assert_engine_command(commands[0], event)
        for tool in WATCHED_TOOLS:
            self.assertTrue(re.fullmatch(tool_matcher(data), tool), tool)


class ClaudeProjectTest(IntegrationTestCase):
    """setup-claude.sh --project registers the hooks in the project settings of the store."""

    def project(self, *extra):
        """Run the script for the store; return the process."""
        return self.setup(CLAUDE_SETUP, PROJECT_FLAG, self.store, *extra,
                          CLAUDE_CONFIG_DIR=str(self.agent))

    def test_project_settings(self):
        """Hooks and skills go to <store>/.claude, nothing to the user directory, no warning."""
        out = self.project()
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertNotIn(WARNING, out.stderr)
        settings = self.store / PROJECT_DIR / SETTINGS_FILE
        data = read_json(settings)
        self.assert_registered(data)
        self.assertEqual(list(self.agent.iterdir()), [])
        link = self.store / PROJECT_DIR / SKILLS_DIR / SKILL
        self.assertTrue(link.is_symlink())
        self.assertTrue((link / "SKILL.md").is_file())
        for event in EVENTS:
            with self.subTest(run=event):
                self.assert_hook_runs(svod_commands(data, event)[0], event)

    def test_second_run(self):
        """Running again changes nothing and leaves no backup."""
        self.assertEqual(self.project().returncode, EXIT_OK)
        settings = self.store / PROJECT_DIR / SETTINGS_FILE
        before = settings.read_bytes()
        out = self.project()
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn(UP_TO_DATE, out.stdout)
        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(settings.with_name(SETTINGS_FILE + BACKUP_SUFFIX).exists())

    def test_old_command_replaced(self):
        """A hook calling an old svod script gets the engine command in its place."""
        settings = self.store / PROJECT_DIR / SETTINGS_FILE
        old = f"{OLD_SVOD} --root {self.store} hook {EVENTS[TOOL_EVENT]}"
        group = {"matcher": "|".join(WATCHED_TOOLS), "hooks": [{"type": COMMAND_TYPE, "command": old}]}
        write_json(settings, {"hooks": {TOOL_EVENT: [group]}})
        out = self.project()
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        data = read_json(settings)
        self.assert_registered(data)
        self.assertNotIn(OLD_SVOD, json.dumps(data))
        self.assertIn(OLD_SVOD, settings.with_name(SETTINGS_FILE + BACKUP_SUFFIX).read_text(
            encoding=ENCODING))

    def test_usage(self):
        """A missing or extra argument, an unknown flag or a directory without svod.yaml."""
        empty = Path(tempfile.mkdtemp(prefix="svod-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        cases = (
            ("no store", [PROJECT_FLAG]),
            ("two stores", [PROJECT_FLAG, self.store, self.store]),
            ("unknown flag", ["--global"]),
            ("not a store", [PROJECT_FLAG, empty]),
        )
        for name, args in cases:
            with self.subTest(case=name):
                out = self.setup(CLAUDE_SETUP, *args, CLAUDE_CONFIG_DIR=str(self.agent))
                self.assertEqual(out.returncode, EXIT_USAGE, out.stderr)
                self.assertFalse((self.store / PROJECT_DIR).exists())
                self.assertFalse((empty / PROJECT_DIR).exists())


class ClaudeGlobalTest(IntegrationTestCase):
    """Without --project the hooks go to the user settings, with a warning."""

    def test_global_warns(self):
        """The warning names the scope and --project; the store stays untouched."""
        out = self.setup(CLAUDE_SETUP, self.store, CLAUDE_CONFIG_DIR=str(self.agent))
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn(WARNING, out.stderr)
        self.assertIn(PROJECT_FLAG, out.stderr)
        self.assert_registered(read_json(self.agent / SETTINGS_FILE))
        self.assertFalse((self.store / PROJECT_DIR).exists())


class CodexTest(IntegrationTestCase):
    """setup-codex.sh writes a hooks.json Codex accepts, keeping hooks of others."""

    def codex(self):
        """Run the script for the store; return the process."""
        return self.setup(CODEX_SETUP, self.store, CODEX_HOME=str(self.agent))

    def assert_codex_format(self, data):
        """Only the keys Codex reads; command handlers with a timeout in whole seconds."""
        self.assertLessEqual(set(data), CODEX_TOP_KEYS)
        self.assertLessEqual(set(data["hooks"]), CODEX_EVENTS)
        for event, groups in data["hooks"].items():
            for group in groups:
                with self.subTest(event=event, group=group):
                    self.assertLessEqual(set(group), CODEX_GROUP_KEYS)
                    for handler in group["hooks"]:
                        self.assertLessEqual(set(handler), CODEX_HANDLER_KEYS)
                        self.assertEqual(handler["type"], COMMAND_TYPE)
                        self.assertIsInstance(handler["command"], str)
                        timeout = handler.get("timeout", 1)
                        self.assertIsInstance(timeout, int)
                        self.assertGreater(timeout, 0)

    def test_hooks_json(self):
        """The hooks match apply_patch and Bash, run, and the skills are linked."""
        out = self.codex()
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        data = read_json(self.agent / HOOKS_FILE)
        self.assert_codex_format(data)
        self.assert_registered(data)
        for tool in (CODEX_EDIT_TOOL, CODEX_SHELL_TOOL):
            self.assertTrue(re.fullmatch(tool_matcher(data), tool), tool)
        self.assertTrue((self.agent / SKILLS_DIR / SKILL / "SKILL.md").is_file())
        for event in EVENTS:
            with self.subTest(run=event):
                self.assert_hook_runs(svod_commands(data, event)[0], event)

    def test_keeps_other_hooks(self):
        """A hook of another tool stays; the original file is backed up; a rerun is a no-op."""
        hooks_file = self.agent / HOOKS_FILE
        foreign = {"matcher": FOREIGN_MATCHER,
                   "hooks": [{"type": COMMAND_TYPE, "command": FOREIGN_COMMAND}]}
        write_json(hooks_file, {"hooks": {TOOL_EVENT: [foreign]}})
        original = hooks_file.read_bytes()
        self.assertEqual(self.codex().returncode, EXIT_OK)
        data = read_json(hooks_file)
        self.assert_codex_format(data)
        self.assertIn(foreign, data["hooks"][TOOL_EVENT])
        self.assertEqual(hooks_file.with_name(HOOKS_FILE + BACKUP_SUFFIX).read_bytes(), original)
        written = hooks_file.read_bytes()
        out = self.codex()
        self.assertIn(UP_TO_DATE, out.stdout)
        self.assertEqual(hooks_file.read_bytes(), written)


class InterpreterTest(IntegrationTestCase):
    """A Python without the engine gets this repository on PYTHONPATH in the hook command."""

    def make_venv(self):
        """A virtual environment that sees PyYAML but not the installed engine; its bin."""
        venv = self.agent / VENV_DIR
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True,
                       capture_output=True, timeout=CLI_TIMEOUT_SEC)
        python = venv / "bin" / PYTHON
        site = subprocess.run([str(python), "-c", SITE_SCRIPT],
                              check=True, capture_output=True, text=True,
                              timeout=CLI_TIMEOUT_SEC).stdout.strip()
        deps = Path(yaml.__file__).resolve().parent.parent
        Path(site, DEPS_PTH).write_text(f"{deps}\n", encoding=ENCODING)
        return venv / "bin"

    def test_engine_not_installed(self):
        """The venv Python with PYTHONPATH of the repository; the hook runs without it."""
        bin_dir = self.make_venv()
        path = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
        out = self.setup(CLAUDE_SETUP, PROJECT_FLAG, self.store, PATH=path,
                         CLAUDE_CONFIG_DIR=str(self.agent))
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        data = read_json(self.store / PROJECT_DIR / SETTINGS_FILE)
        self.assert_registered(data)
        command = svod_commands(data, TOOL_EVENT)[0]
        words = shlex.split(command)
        self.assertEqual(words[0], PYTHONPATH_PREFIX + str(REPO_DIR))
        self.assertEqual(Path(words[1]).parent, bin_dir)
        session = svod_commands(data, "SessionStart")[0]
        self.assert_hook_runs(session, "SessionStart", PYTHONPATH="")


if __name__ == "__main__":
    unittest.main()
