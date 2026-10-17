"""The command gate: exit codes, the output tail, timeouts, places and the disk cache."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from support import StoreTestCase, TempStore

from svod import command_cache
from svod.command_gate import CommandGate
from svod.config import load_config
from svod.context import Context
from svod.errors import ParamError
from svod.gates import CORE_GATES, Gate, Status
from svod.loader import load_runtime
from svod.subject import Subject

PASS, FAIL, UNKNOWN = Status.PASS, Status.FAIL, Status.UNKNOWN
PY = sys.executable
KEY = "PROJ-1"
SERVICE = "app"
WORKSPACE_GATE = "test_workspace"
COUNT_SCRIPT = ("import pathlib, sys; p = pathlib.Path(sys.argv[1]); "
                "p.write_text(p.read_text() + 'x' if p.exists() else 'x'); print('ran')")


class ServicesConfig:
    """Store config with the services mapping and the workspace gate given by the test."""

    def __init__(self, config, services, workspace_gate=None):
        """Wrap the loaded config."""
        self._config = config
        self.services = services
        self.workspace_gate = workspace_gate

    def __getattr__(self, name):
        """Everything else from the loaded config."""
        return getattr(self._config, name)


class FixedWorkspaceGate(Gate):
    """Workspace gate naming one work directory for the key."""

    name = WORKSPACE_GATE
    found: list = []

    def worktrees(self, ctx, keys):
        """The fixed pairs when the test key is asked."""
        return (list(self.found) if KEY in keys else []), []

    def evaluate(self, ctx, subject):
        """Never evaluated here."""
        raise NotImplementedError


class CommandGateTest(StoreTestCase):
    """The gate against a real store repository."""

    def setUp(self):
        """Store under git with one tracked file; a counter outside the repository."""
        super().setUp()
        self.sb.write("src/data.txt", "one\n")
        self.sb.init_git(remote=False)
        self.counter = self.sb.root / "count.txt"

    def ctx(self, config=None):
        """Fresh context: a new run with an empty memory."""
        return Context(config or load_config(self.sb.store))

    def runs(self):
        """How many times the counting command ran."""
        return len(self.counter.read_text()) if self.counter.exists() else 0

    def counting(self, **params):
        """Params of a command that counts its runs and passes."""
        return {"argv": [PY, "-c", COUNT_SCRIPT, str(self.counter)], **params}

    def evaluate(self, params, ctx=None, subject=None):
        """Result of the gate for a subject without keys."""
        subject = subject or Subject(id="one", path=self.sb.store)
        return CommandGate(params).evaluate(ctx or self.ctx(), subject)

    def test_registered_as_core_gate(self):
        """The gate joins the core registry under its name."""
        self.assertIs(CORE_GATES["command"], CommandGate)

    def test_pass_and_fail_with_tail(self):
        """Exit 0 passes; another code fails with the last 20 lines, cut to 2000 characters."""
        ok = self.evaluate({"argv": [PY, "-c", "print('fine')"], "cache": False})
        self.assertEqual(ok.status, PASS)
        self.assertEqual((ok.facts["code"], ok.facts["detail"], ok.facts["cached"]),
                         (0, "fine", False))
        script = ("import sys\nfor i in range(30): print(f'line {i}')\n"
                  "print('oops', file=sys.stderr)\nsys.exit(3)")
        bad = self.evaluate({"argv": [PY, "-c", script], "cache": False})
        self.assertEqual((bad.status, bad.facts["code"]), (FAIL, 3))
        lines = bad.facts["detail"].splitlines()
        self.assertEqual(len(lines), 20)
        self.assertEqual((lines[0], lines[-1]), ("line 11", "oops"))
        long = self.evaluate({"argv": [PY, "-c", "print('y' * 5000); raise SystemExit(1)"],
                              "cache": False})
        self.assertEqual(long.facts["detail"], "y" * 2000)

    def test_env_and_no_bytecode(self):
        """env reaches the command, with bytecode writing off."""
        script = ("import os, sys; sys.exit(0 if os.environ['SVOD_X'] == 'v' and "
                  "os.environ['PYTHONDONTWRITEBYTECODE'] == '1' else 1)")
        result = self.evaluate({"argv": [PY, "-c", script], "env": {"SVOD_X": "v"}})
        self.assertEqual(result.status, PASS)

    def test_timeout_and_missing_places_are_unknown(self):
        """A timeout, a missing directory, an unknown service or program: UNKNOWN with a reason."""
        cases = (
            {"argv": [PY, "-c", "import time; time.sleep(30)"], "timeout": 0.5},
            {"argv": [PY, "-c", "pass"], "cwd": "absent"},
            {"argv": [PY, "-c", "pass"], "service": "nowhere"},
            {"argv": ["svod-no-such-program"]},
        )
        for params in cases:
            with self.subTest(params=params):
                result = self.evaluate(params)
                self.assertEqual(result.status, UNKNOWN)
                self.assertTrue(result.reason)
                self.assertEqual((result.facts["code"], result.facts["cached"]), ("", False))
        timeout = self.evaluate(cases[0])
        self.assertIn("0.5s", timeout.reason)

    def test_cache_hit_and_misses(self):
        """A second run hits; a changed file, a file changed again and a commit miss."""
        params = self.counting()
        first = self.evaluate(params)
        self.assertEqual((first.status, first.facts["cached"], self.runs()), (PASS, False, 1))
        hit = self.evaluate(params)
        self.assertEqual((hit.status, hit.facts["cached"], hit.facts["detail"], self.runs()),
                         (PASS, True, "ran", 1))
        steps = (
            lambda: self.sb.write("src/data.txt", "two\n"),
            lambda: self.sb.write("src/data.txt", "three\n"),
            lambda: self.sb.write("src/new.txt", "new\n"),
            lambda: self.sb.commit(message="next"),
        )
        for number, change in enumerate(steps, start=2):
            change()
            with self.subTest(change=number):
                self.assertFalse(self.evaluate(params).facts["cached"])
                self.assertEqual(self.runs(), number)
                self.assertTrue(self.evaluate(params).facts["cached"])
                self.assertEqual(self.runs(), number)

    def test_argv_and_watch_enter_the_key(self):
        """Another argv misses; a watched ignored file misses when its content changes."""
        self.sb.write(".gitignore", "build/\n")
        self.sb.write("build/out.txt", "a\n")
        self.sb.commit(message="ignore")
        params = self.counting(watch=["build"])
        self.evaluate(params)
        self.assertTrue(self.evaluate(params).facts["cached"])
        self.sb.write("build/out.txt", "b\n")
        self.assertFalse(self.evaluate(params).facts["cached"])
        other = {**params, "argv": [*params["argv"], "extra"]}
        self.assertFalse(self.evaluate(other).facts["cached"])
        self.assertEqual(self.runs(), 3)

    def test_failure_is_cached(self):
        """A FAIL is a result too and is kept."""
        params = {"argv": [PY, "-c", "raise SystemExit(2)"]}
        self.assertEqual(self.evaluate(params).facts["cached"], False)
        again = self.evaluate(params)
        self.assertEqual((again.status, again.facts["code"], again.facts["cached"]),
                         (FAIL, 2, True))

    def test_cache_false_runs_every_time(self):
        """cache: false runs in every run, never cached; one run evaluates it once."""
        params = self.counting(cache=False)
        for expected in (1, 2):
            self.assertFalse(self.evaluate(params).facts["cached"])
            self.assertEqual(self.runs(), expected)
        ctx = self.ctx()
        self.evaluate(params, ctx)
        self.evaluate(params, ctx)
        self.assertEqual(self.runs(), 3)

    def test_command_writing_into_the_source_is_not_stored(self):
        """A result is not stored when the command changed what git sees; the last one is."""
        script = "import pathlib, uuid; pathlib.Path('src', uuid.uuid4().hex).write_text('x')"
        params = {"argv": [PY, "-c", script]}
        self.assertFalse(self.evaluate(params).facts["cached"])
        self.assertFalse(self.evaluate(params).facts["cached"])
        common = self.sb.store / ".git" / command_cache.CACHE_DIR
        self.assertEqual(list(common.glob("*.json")), [])
        self.assertEqual(len(list((common / command_cache.LAST_DIR).glob("*.json"))), 1)

    def test_entry_lives_in_git_common_dir(self):
        """The record is a JSON file in the cache directory of the git common dir."""
        self.evaluate(self.counting())
        entries = list((self.sb.store / ".git" / command_cache.CACHE_DIR).glob("*.json"))
        self.assertEqual(len(entries), 1)
        record = command_cache.load(entries[0])
        self.assertEqual((record.code, record.tail), (0, "ran"))
        self.assertTrue(record.time)
        self.assertGreaterEqual(record.duration, 0)

    def test_cwd_relative_to_store(self):
        """cwd is a directory of the store."""
        script = "import os, sys; sys.exit(0 if os.path.basename(os.getcwd()) == 'src' else 1)"
        self.assertEqual(self.evaluate({"argv": [PY, "-c", script], "cwd": "src"}).status, PASS)

    def test_service_directory_and_subject_worktree(self):
        """service runs in the subject's work directory of that repository, else in the service."""
        service = self.sb.init_git(self.sb.parent / SERVICE, remote=False)
        worktree = self.sb.parent / f"{SERVICE}-{KEY}"
        self.sb.git(service, "worktree", "add", "-q", "-b", KEY, str(worktree))
        other = self.sb.init_git(self.sb.parent / "other", remote=False)
        script = "import os; print(os.getcwd())"
        params = {"argv": [PY, "-c", script], "service": SERVICE, "cache": False}
        services = {SERVICE: f"../{SERVICE}"}
        plain = ServicesConfig(load_config(self.sb.store), services)
        self.assertEqual(self.evaluate(params, self.ctx(plain)).facts["detail"],
                         str(service.resolve()))
        ref = SimpleNamespace(impl=FixedWorkspaceGate())
        pipelines = {"p": SimpleNamespace(gate_refs=lambda: [ref])}
        keyed = Subject(id="one", path=self.sb.store, keys={KEY})
        config = ServicesConfig(load_config(self.sb.store), services, WORKSPACE_GATE)
        cases = (([(other, "other"), (worktree, SERVICE)], keyed, worktree),
                 ([(other, "other")], keyed, service),
                 ([(worktree, SERVICE)], Subject(id="one", path=self.sb.store), service))
        for found, subject, expected in cases:
            with self.subTest(found=found, keys=subject.keys):
                FixedWorkspaceGate.found = found
                ctx = Context(config, pipelines=pipelines)
                self.assertEqual(self.evaluate(params, ctx, subject).facts["detail"],
                                 str(expected.resolve()))

    def test_placeholders_of_argv(self):
        """{id}, {path} and {root} are replaced in argv; other braces stay as written."""
        script = "import sys; print('|'.join(sys.argv[1:]))"
        self.sb.write("work/tasks/x/card.md", "x\n")
        subject = Subject(id="tasks/x", path=self.sb.store / "work" / "tasks" / "x")
        result = self.evaluate({"argv": [PY, "-c", script, "{id}", "{path}/a", "{root}", "{a}"],
                                "cache": False}, subject=subject)
        self.assertEqual(result.facts["detail"],
                         f"tasks/x|work/tasks/x/a|{self.sb.store.resolve()}|{{a}}")

    def test_action_variables_in_a_pipeline(self):
        """A gate of a loaded pipeline gives the command the variables of an action."""
        names = ("SVOD_ID", "SVOD_PIPELINE", "SVOD_SERVICES", "SVOD_CHECKS_APP", "SVOD_ACTION")
        script = f"import os; print('|'.join(os.environ.get(n, '-') for n in {names!r}))"
        gate = CommandGate({"argv": [PY, "-c", script], "cache": False})
        config = ServicesConfig(load_config(self.sb.store), {SERVICE: f"../{SERVICE}"})
        config.profile_config = {"checks": {SERVICE: ["make", "test"]}}
        pipelines = {"p": SimpleNamespace(name="p", steps=[], gate_refs=lambda: [SimpleNamespace(
            impl=gate)])}
        subject = Subject(id="one", path=self.sb.store,
                          attrs={"frontmatter": {"services": [SERVICE]}})
        # The test may itself run under svod do (the store's checks action): start from an
        # environment without SVOD_ variables, as a session of the agent would.
        outer = {name: value for name, value in os.environ.items() if not name.startswith("SVOD_")}
        with mock.patch.dict(os.environ, {**outer, "SVOD_ACTION": "checks", "SVOD_ID": "outer"},
                             clear=True):
            found = gate.evaluate(Context(config, pipelines=pipelines), subject)
            alone = gate.evaluate(Context(config), subject)
        self.assertEqual(found.facts["detail"], f"one|p|{SERVICE}|make test|")
        self.assertEqual(alone.facts["detail"], "outer|-|-|-|checks")

    def test_params(self):
        """Wrong params are load errors."""
        bad = (
            {},
            {"argv": []},
            {"argv": "make test"},
            {"argv": ["make"], "service": "app", "cwd": "app"},
            {"argv": ["make"], "timeout": 0},
            {"argv": ["make"], "timeout": True},
            {"argv": ["make"], "watch": []},
            {"argv": ["make"], "watch": ["../x"]},
            {"argv": ["make"], "watch": ["/abs"]},
            {"argv": ["make"], "env": {"A": 1}},
            {"argv": ["make"], "cache": "no"},
            {"argv": ["make"], "shell": True},
        )
        for params in bad:
            with self.subTest(params=params), self.assertRaises(ParamError):
                CommandGate(params)
        CommandGate({"argv": ["make"], "timeout": 1.5, "watch": ["docs/**/*.md"],
                     "env": {"A": "1"}, "cache": False, "service": "app"})


class CommandGateOutsideGitTest(StoreTestCase):
    """A directory outside git is never cached."""

    def test_not_cached_outside_git(self):
        """Every run executes the command, with cached false."""
        counter = self.sb.root / "count.txt"
        params = {"argv": [PY, "-c", COUNT_SCRIPT, str(counter)]}
        for expected in (1, 2):
            ctx = Context(load_config(self.sb.store))
            result = CommandGate(params).evaluate(ctx, Subject(id="one", path=self.sb.store))
            self.assertEqual((result.status, result.facts["cached"]), (PASS, False))
            self.assertEqual(len(counter.read_text()), expected)
        self.assertIsNone(command_cache.entry(self.sb.store, params["argv"]))


class CommandDescribeTest(unittest.TestCase):
    """The description names the command and where it runs."""

    def test_describe(self):
        """Service, directory or the store root."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        locale = load_runtime(sb.store).locale
        cases = (
            ({"argv": ["make", "lint"], "service": "app"}, "make lint exits with 0 in app"),
            ({"argv": ["ruff", "check", "a b"], "cwd": "docs"},
             "ruff check 'a b' exits with 0 in docs"),
            ({"argv": ["true"]}, "true exits with 0 in ."),
        )
        for params, text in cases:
            with self.subTest(params=params):
                self.assertEqual(CommandGate(params).describe(params, locale), text)


if __name__ == "__main__":
    unittest.main()
