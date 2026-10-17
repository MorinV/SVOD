"""svod doctor: one line per check, JSON on request, exit 1 only when a check fails."""
import json
import shlex
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from support import ENCODING, EXIT_FINDINGS, EXIT_OK
from test_wizard import LOGIN, SERVICE, WizardStore

from svod.doctor import FAIL, OK, WARN, hooks_format_error, interpreter, settings_files

NEWEST = "0.4.0"
LATEST = "svod.notice.latest_known"


def statuses(found):
    """Status of each named check, failures and warnings joined per name."""
    result = {}
    for check in found["checks"]:
        result.setdefault(check["name"], set()).add(check["status"])
    return result


def settings(path, python):
    """Write a Claude Code settings.json whose svod hooks run the given python."""
    base = f"{shlex.quote(python)} -m svod.cli"
    hooks = {name: [{"hooks": [{"type": "command", "command": f"{base} hook {event}"}]}]
             for name, event in (("SessionStart", "session-start"), ("UserPromptSubmit", "prompt"),
                                 ("PreToolUse", "pre-tool"))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": hooks}), encoding=ENCODING)


class DoctorStore(WizardStore):
    """A store set up by the wizard, its doctor run with a fixed newest release."""

    def doctor(self, *args, latest=NEWEST):
        """Run svod doctor in this process with the release check answered."""
        with mock.patch(LATEST, return_value=latest):
            return self.cli("doctor", *args)


class DoctorTest(unittest.TestCase):
    def test_healthy_store(self):
        """A store set up by the wizard with its index written passes every check."""
        with TemporaryDirectory() as temp:
            ds = DoctorStore(temp)
            done = ds.cli("init", "--login", LOGIN, "--service", f"{SERVICE}=../app")
            self.assertEqual(done.returncode, EXIT_OK, done.stderr)
            settings(ds.store / ".claude" / "settings.json", sys.executable)
            self.assertEqual(ds.cli("knowledge", "index").returncode, EXIT_OK)
            result = ds.doctor()
            self.assertEqual(result.returncode, EXIT_OK, result.stdout + result.stderr)
            lines = result.stdout.splitlines()
            self.assertTrue(lines)
            self.assertTrue(all(line.startswith(f"{OK}: ") for line in lines), result.stdout)
            self.assertIn(f"ok: service {SERVICE}: {ds.service.resolve()}", lines)
            self.assertIn("hooks registered in", result.stdout)
            data = json.loads(ds.doctor("--format", "json").stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(set(statuses(data)), {"config", "service", "hooks", "copy",
                                                   "version", "evidence", "knowledge",
                                                   "local_config"})
            self.assertEqual({s for v in statuses(data).values() for s in v}, {OK})

    def test_broken_store(self):
        """A service without git, hooks of a missing python, a modified copy, no local config,
        an evidence path that is a file and a stale index: fail, JSON says which."""
        with TemporaryDirectory() as temp:
            ds = DoctorStore(temp)
            plain = ds.base / "plain"
            plain.mkdir()
            ds.cli("init", "--service", f"{SERVICE}=../app", "--login", LOGIN)
            (ds.store / ".svod-local.yaml").unlink()
            text = (ds.store / "svod.yaml").read_text(encoding=ENCODING)
            (ds.store / "svod.yaml").write_text(text.replace(
                "  app: ../app\n", "  app: ../app\n  plain: ../plain\n  gone: ../gone\n"),
                encoding=ENCODING)
            settings(ds.store / ".claude" / "settings.json", str(ds.base / "no-python"))
            copy = ds.store / ".svod"
            (copy / "lib" / "svod").mkdir(parents=True)
            (copy / "lib" / "svod" / "__init__.py").write_text("x = 1\n", encoding=ENCODING)
            (copy / "MANIFEST").write_text("", encoding=ENCODING)
            (ds.store / "evidence").write_text("not a directory\n", encoding=ENCODING)
            (ds.store / "knowledge" / "late.md").write_text("---\ntitle: Late\n---\nNew.\n",
                                                             encoding=ENCODING)
            result = ds.doctor("--format", "json", latest="9.9.9")
            self.assertEqual(result.returncode, EXIT_FINDINGS, result.stderr)
            data = json.loads(result.stdout)
            self.assertFalse(data["ok"])
            found = statuses(data)
            for name in ("config", "service", "hooks", "copy", "evidence", "local_config"):
                with self.subTest(check=name):
                    self.assertIn(FAIL, found[name])
            self.assertEqual(found["service"], {OK, FAIL})
            self.assertEqual(found["knowledge"], {WARN})
            texts = " ".join(c["text"] for c in data["checks"])
            self.assertIn("plain", texts)
            self.assertIn("no-python", texts)
            self.assertIn("vendored copy modified", texts)
            self.assertIn("svod knowledge index", texts)
            text = ds.doctor()
            self.assertEqual(text.returncode, EXIT_FINDINGS)
            self.assertIn("fail: service plain:", text.stdout)

    def test_hooks_and_release_warnings(self):
        """No hooks anywhere and a newer release are warnings, not failures."""
        with TemporaryDirectory() as temp:
            ds = DoctorStore(temp)
            ds.cli("init", "--login", LOGIN, "--hooks", "none")
            self.assertEqual(ds.cli("knowledge", "index").returncode, EXIT_OK)
            result = ds.doctor(latest="9.9.9")
            self.assertEqual(result.returncode, EXIT_OK, result.stdout)
            self.assertIn("warn: no svod hooks in", result.stdout)
            self.assertIn("--project", result.stdout)
            self.assertIn("warn: engine", result.stdout)
            self.assertIn("release 9.9.9 is out", result.stdout)
            unchecked = ds.doctor(latest=None)
            self.assertIn("newest release not checked", unchecked.stdout)

    def test_user_settings_follow_claude_config_dir(self):
        """Hooks in $CLAUDE_CONFIG_DIR/settings.json count; a partial set is a warning."""
        with TemporaryDirectory() as temp:
            ds = DoctorStore(temp)
            ds.cli("init", "--login", LOGIN)
            path = Path(ds.env["CLAUDE_CONFIG_DIR"]) / "settings.json"
            settings(path, sys.executable)
            data = json.loads(path.read_text(encoding=ENCODING))
            del data["hooks"]["PreToolUse"]
            path.write_text(json.dumps(data), encoding=ENCODING)
            result = ds.doctor()
            self.assertIn(f"warn: hooks in {path} lack pre-tool", result.stdout)

    def test_hooks_format(self):
        """Both agents: events map to groups of handlers; Codex also refuses keys it does not
        read and wants command handlers with whole-second timeouts."""
        handler = {"type": "command", "command": "python3 -m svod.cli hook prompt", "timeout": 20}
        good = {"hooks": {"UserPromptSubmit": [{"hooks": [handler]}]}}
        self.assertIsNone(hooks_format_error(good, codex=True))
        self.assertIsNone(hooks_format_error({**good, "permissions": {}}, codex=False))
        self.assertIsNone(hooks_format_error({"permissions": {}}, codex=False))
        cases = (
            ("claude list", [], False, "not a JSON object"),
            ("claude group", {"hooks": {"Stop": ["x"]}}, False, "hooks.Stop[0] must be"),
            ("claude handler", {"hooks": {"Stop": [{"hooks": [{}]}]}}, False,
             "hooks.Stop[0].hooks[0] must be an object with a type"),
            ("codex top key", {**good, "permissions": {}}, True, "unknown key permissions"),
            ("codex group key", {"hooks": {"Stop": [{"hooks": [], "when": 1}]}}, True,
             "hooks.Stop[0]: unknown key when"),
            ("codex prompt handler", {"hooks": {"Stop": [{"hooks": [{"type": "prompt"}]}]}},
             True, "must be a command handler"),
            ("codex timeout", {"hooks": {"Stop": [{"hooks": [{**handler, "timeout": 0}]}]}},
             True, "timeout must be a positive integer"),
        )
        for name, data, codex, expected in cases:
            with self.subTest(case=name):
                self.assertIn(expected, hooks_format_error(data, codex) or "")

    def test_codex_files_are_checked(self):
        """The store's .codex/hooks.json and $CODEX_HOME/hooks.json are among the files."""
        root, home = Path("/store"), Path("/home/me")
        files = settings_files(root, {"HOME": str(home), "CODEX_HOME": "/codex"})
        self.assertEqual(files, [root / ".claude/settings.json", root / ".codex/hooks.json",
                                 home / ".claude/settings.json", Path("/codex/hooks.json")])
        self.assertIn(home / ".codex/hooks.json", settings_files(root, {"HOME": str(home)}))

    def test_interpreter_of_a_hook_command(self):
        """The program after assignments and env."""
        self.assertEqual(interpreter("PYTHONPATH=/x /usr/bin/python3 -m svod.cli hook prompt"),
                         "/usr/bin/python3")
        self.assertEqual(interpreter("env A=1 python3 -m svod.cli hook prompt"), "python3")
        self.assertIsNone(interpreter("'unbalanced"))


if __name__ == "__main__":
    unittest.main()
