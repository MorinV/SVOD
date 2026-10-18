"""The argv runner: no shell, the timeout, the process group stopped, the output tail."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from svod import run

POSIX_ONLY = "process groups need POSIX"
# A child that only has to be alive when it is stopped; the stop comes within milliseconds.
HOLD_SECONDS = 2
SHORT_TIMEOUT = .2


def python(code):
    """argv running the Python code in this interpreter."""
    return [sys.executable, "-c", code]


@unittest.skipUnless(os.name == "posix", POSIX_ONLY)
class RunArgvTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def run_code(self, argv, timeout=10, env=None):
        """(exit code, output) of argv run in the temp directory."""
        with tempfile.TemporaryFile() as output:
            code = run.run_argv(argv, self.base, output, timeout, env)
            output.seek(0)
            return code, output.read().decode()

    def test_exit_code_output_and_environment(self):
        """stdout and stderr land in output; env is added, bytecode is off, no shell expands."""
        code, text = self.run_code(python(
            "import os, sys; print(os.getcwd()); print(os.environ['EXTRA']); "
            f"print(os.environ['{run.NO_BYTECODE_ENV}']); print(sys.argv[1]); "
            "sys.stderr.write('err\\n'); raise SystemExit(3)") + ["$HOME"], env={"EXTRA": "x"})
        self.assertEqual(code, 3)
        self.assertEqual(text.split(), [str(self.base), "x", "1", "$HOME", "err"])

    def test_timeout_propagates_and_stops_the_child(self):
        """TimeoutExpired propagates; the child is gone by then."""
        marker = self.base / "pid"
        argv = python(f"import os, time; open({str(marker)!r}, 'w').write(str(os.getpid())); "
                      f"time.sleep({HOLD_SECONDS * 10})")
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_code(argv, timeout=SHORT_TIMEOUT)
        pid = int(marker.read_text())
        with self.assertRaises(ProcessLookupError):
            os.killpg(pid, 0)

    def test_missing_program_raises(self):
        """A program that does not exist raises OSError."""
        with self.assertRaises(OSError):
            self.run_code([str(self.base / "no-such-program")])

    def test_descendants_are_stopped_even_after_leader_exits(self):
        """A descendant left behind by the leader gets SIGTERM once the leader exits."""
        marker = self.base / "descendant-stopped"
        # The orphaned descendant leaves the group once it has acknowledged SIGTERM: its zombie
        # belongs to PID 1, and a container init that reaps slowly would otherwise hold the
        # runner in its grace period for seconds after the descendant has already stopped.
        child_code = ("import os, signal, time; from pathlib import Path; "
                      f"signal.signal(signal.SIGTERM, lambda *_: (Path({str(marker)!r}).touch(), "
                      "os.setpgid(0, 0), exit(0))); "
                      f"print('ready', flush=True); time.sleep({HOLD_SECONDS})")
        parent_code = ("import subprocess, sys; "
                       f"p = subprocess.Popen([sys.executable, '-c', {child_code!r}], "
                       "stdout=subprocess.PIPE); "
                       "assert p.stdout.readline() == b'ready\\n'; print('leader exited')")
        code, text = self.run_code(python(parent_code))
        self.assertEqual(code, 0, text)
        self.assertTrue(marker.exists(), "descendant did not acknowledge the group stop")

    @unittest.skipUnless(sys.platform == "darwin", "Darwin zombie-group semantics")
    def test_zombie_leader_probe_is_rechecked_after_owned_child_reap(self):
        """Darwin reports EPERM for a zombie-only group, not ESRCH until reaping."""
        import signal
        import time
        child = subprocess.Popen(python("import time; time.sleep(30)"), start_new_session=True)
        self.addCleanup(lambda: child.wait() if child.poll() is not None else
                        (child.kill(), child.wait()))
        os.killpg(child.pid, signal.SIGTERM)
        deadline = time.monotonic() + 2
        state = ""
        while time.monotonic() < deadline:
            state = subprocess.check_output(
                ["ps", "-o", "stat=", "-p", str(child.pid)], text=True).strip()
            if state.startswith("Z"):
                break
        self.assertTrue(state.startswith("Z"), state)
        with self.assertRaises(PermissionError):
            os.killpg(child.pid, 0)
        # Hold the first poll at the real waitpid/exit race, without faking killpg.
        poll = child.poll
        with patch.object(child, "poll") as mocked:
            # Later polls must retain the real implementation.
            mocked.side_effect = lambda: None if mocked.call_count == 1 else poll()
            native_signal = run.signal_group
            with patch.object(run, "signal_group", wraps=native_signal) as signals:
                # TERM already succeeded; replay its result so the regression reaches probe 0.
                signals.side_effect = lambda proc, sig: (
                    True if sig == signal.SIGTERM else native_signal(proc, sig))
                run.stop_group(child)
        self.assertEqual(child.returncode, -signal.SIGTERM)
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)

    def test_probe_permission_denial_is_not_treated_as_group_absence(self):
        """A genuine probe denial stays an error, with owned child cleanup bounded."""
        child = subprocess.Popen(python("import time; time.sleep(30)"), start_new_session=True)
        self.addCleanup(lambda: child.wait() if child.poll() is not None else
                        (child.kill(), child.wait()))
        native = os.killpg

        def denied_probe(pid, sig):
            if sig == 0:
                raise PermissionError("probe denied")
            return native(pid, sig)

        with patch.object(run.os, "killpg", side_effect=denied_probe), \
                self.assertRaises(PermissionError):
            run.stop_group(child)
        self.assertIsNotNone(child.returncode)

    def test_sigkill_stops_real_term_resistant_group_within_bound(self):
        """A live owned group is not mistaken for the Darwin zombie-only case."""
        import signal
        import time
        child = subprocess.Popen(python(
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); time.sleep(30)"),
            start_new_session=True, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.wait() if child.poll() is not None else
                        (child.kill(), child.wait()))
        assert child.stdout is not None
        self.addCleanup(child.stdout.close)
        self.assertEqual(child.stdout.readline(), "ready\n")
        started = time.monotonic()
        with patch.object(run, "STOP_GRACE_SEC", .1):
            run.stop_group(child)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(child.returncode, -signal.SIGKILL)
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)

    def test_permission_failure_still_reaps_the_child(self):
        """A group that cannot be signalled: the child is killed and reaped, the error raised."""
        child = subprocess.Popen(python(f"import time; time.sleep({HOLD_SECONDS})"),
                                 start_new_session=True)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        with patch.object(run.os, "killpg", side_effect=PermissionError("group denied")), \
                self.assertRaises(PermissionError):
            run.stop_group(child)
        self.assertIsNotNone(child.poll())


class OutputTailTest(unittest.TestCase):
    def test_tail_keeps_the_last_lines_and_characters(self):
        """The last TAIL_LINES lines, at most TAIL_CHARS characters, trailing blanks dropped."""
        lines = [f"line {n}" for n in range(run.TAIL_LINES * 2)]
        with tempfile.TemporaryFile() as output:
            output.write(("\n".join(lines) + "\n\n").encode())
            self.assertEqual(run.output_tail(output), "\n".join(lines[-run.TAIL_LINES:]))
        with tempfile.TemporaryFile() as output:
            output.write(b"x" * (run.TAIL_CHARS * 3))
            self.assertEqual(len(run.output_tail(output)), run.TAIL_CHARS)


class NoLocalRunnerTest(unittest.TestCase):
    def test_gate_and_actions_use_this_runner(self):
        """The command gate and the actions run through svod.run; local_runner is gone."""
        from svod import actions, command_gate
        self.assertIs(command_gate.run_argv, run.run_argv)
        self.assertIs(command_gate.output_tail, run.output_tail)
        self.assertIs(actions.stop_group, run.stop_group)
        for name in ("local_runner", "local_workflow", "local_evidence"):
            with self.subTest(module=name):
                self.assertFalse((Path(run.__file__).parent / f"{name}.py").exists())


if __name__ == "__main__":
    unittest.main()
