"""Offline package acceptance through the real CLI; no network or agent decisions."""
import hashlib
from contextlib import suppress
import json
import shutil

import yaml

from support import TEST_PROFILE, StoreTestCase, doc


class PackageTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.profile = self.sb.store / "profile"
        shutil.copytree(TEST_PROFILE, self.profile)
        self.sb.write("notes/pilot.md", doc("note"))
        pipeline = self.profile / "pipelines/note.yaml"
        pipeline.write_text(pipeline.read_text().replace("  - id: review\n",
                                                       "  - id: review\n    action: alpha\n"))
        self.script = self.sb.write("profile/actions/alpha.sh", "echo alpha\n")
        self.config = yaml.safe_load((self.sb.store / "svod.yaml").read_text())
        self.config["profile"] = str(self.profile)
        self.config["profile_config"] = {"local_packages": {"alpha": {
            "sha256": hashlib.sha256(self.script.read_bytes()).hexdigest(),
            "kind": "action", "args": [], "inputs": [], "outputs": []}}}
        self.save_config()
        self.package = {"version": 1, "id": "pilot", "record": "pilot", "steps": [
            {"id": "a", "step_id": "review", "action": "alpha", "args": [],
             "timeout": 2, "inputs": [], "outputs": []}]}
        self.path = self.sb.store / "package.json"
        self.save_package()

    def save_config(self):
        self.sb.write("svod.yaml", yaml.safe_dump(self.config))

    def save_package(self):
        self.path.write_text(json.dumps(self.package))

    def call(self, command, *args):
        return self.sb.cli_process("package", command, "pilot", *map(str, args))

    def add_three(self, failing=False):
        pipeline = self.profile / "pipelines/note.yaml"
        data = yaml.safe_load(pipeline.read_text())
        data["steps"] = []
        for name in ("alpha", "beta", "gamma"):
            body = f"echo {name} >> calls\necho {name}\n"
            if name == "beta" and failing:
                body += "test -f fixed || exit 7\n"
            body += (f"touch notes/{name}.done\n"
                     f"{__import__('sys').executable} -c \"from pathlib import Path; "
                     f"p=Path('notes/pilot.md'); p.write_text(p.read_text().replace("
                     f"'status: active', 'status: active\\\\n{name}: true'))\"\n")
            script = self.sb.write(f"profile/actions/{name}.sh", body)
            self.config["profile_config"]["local_packages"][name] = {
                "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                "kind": "check" if name == "beta" else "action", "args": [],
                "inputs": [], "outputs": [f"notes/{name}.done"]}
            data["steps"].append({"id": name, "action": name, "text": "note.step.review",
                                   "gates": [{"gate": "field", "params": {
                                       "name": name, "present": True}}]})
        pipeline.write_text(yaml.safe_dump(data))
        self.package["steps"] = [{"id": n, "step_id": n, "action": n, "args": [],
                                   "timeout": 2, "inputs": [], "outputs": [f"notes/{n}.done"]}
                                  for n in ("alpha", "beta", "gamma")]
        self.save_config()
        self.save_package()

    def test_sequential_run_and_saved_compact_status(self):
        self.add_three()
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual([s["status"] for s in state["steps"]], ["succeeded"] * 3)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\ngamma\n")
        saved = self.call("status", state["run_id"], "--json")
        self.assertEqual(json.loads(saved.stdout), state)

    def decision(self, state, operation="retry-check"):
        path = self.sb.store / "decision.json"
        path.write_text(json.dumps({"run_id": state["run_id"], "revision": state["revision"],
                                    "operation": operation}))
        return path

    def test_failure_latches_until_explicit_check_retry_without_replaying_action(self):
        self.add_three(failing=True)
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual([s["status"] for s in state["steps"]],
                         ["succeeded", "failed", "pending"])
        self.sb.write("fixed", "user repaired fixture")
        waiting = json.loads(self.call("status", state["run_id"], "--json").stdout)
        self.assertEqual(waiting, state)
        decision = self.decision(state)
        resumed = self.call("resume", state["run_id"], "--decision", decision, "--json")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["status"], "succeeded")
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\nbeta\ngamma\n")
        replay = self.call("resume", state["run_id"], "--decision", decision)
        self.assertEqual(replay.returncode, 2)

    def test_full_read_flag_is_rejected_without_changing_saved_run(self):
        state = json.loads(self.call("run", self.path, "--json").stdout)
        directory = self.sb.store / ".svod/package-runs" / state["run_id"]
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        for flags in (("--full",), ("--full", "--json"), ("--step", "a", "--full")):
            with self.subTest(flags=flags):
                result = self.call("read", state["run_id"], *flags)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("error:", result.stderr)
                if "--step" in flags:
                    self.assertIn("unrecognized arguments: --full", result.stderr)
                self.assertEqual(result.stdout, "")
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
        help_result = self.call("read", "--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("--full", help_result.stdout)
        self.assertIn("--step", help_result.stdout)

    def test_read_pages_and_human_log_artifacts_are_read_only_without_runtime(self):
        self.add_three(failing=True)
        state = json.loads(self.call("run", self.path, "--json").stdout)
        directory = self.sb.store / ".svod/package-runs" / state["run_id"]
        before = (directory / "state.json").read_bytes()
        (self.profile / "pipelines/note.yaml").write_text("invalid: configuration")
        result = self.call("read", state["run_id"], "--step", "beta", "--limit", 2, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        page = json.loads(result.stdout)
        self.assertEqual(page["text"], "be")
        self.assertEqual(page["next_offset"], 2)
        self.assertFalse(page["eof"])
        next_page = self.call("read", state["run_id"], "--step", "beta", "--offset", 2,
                              "--limit", 3, "--json")
        self.assertEqual(next_page.returncode, 0, next_page.stderr)
        self.assertEqual(json.loads(next_page.stdout)["text"], "ta\n")
        self.assertTrue(json.loads(next_page.stdout)["eof"])
        # Direct local artifact access is human inspection, not another CLI/API mode.
        for step in state["steps"][:2]:
            self.assertEqual((directory / step["logs"][0]["ref"]).read_bytes(),
                             (step["id"] + "\n").encode())
        self.assertEqual((directory / "state.json").read_bytes(), before)
        self.assertEqual(self.call("status", state["run_id"]).returncode, 0)
        for extra in (("--step", "missing"), ("--step", "beta", "--offset", -1),
                      ("--step", "beta", "--offset", 99), ("--step", "beta", "--limit", 0),
                      ("--step", "beta", "--limit", 65537), ()):
            self.assertEqual(self.call("read", state["run_id"], *extra).returncode, 2)
        log = directory / "beta-0.log"
        log.write_bytes(b"corrupted")
        self.assertEqual(self.call("read", state["run_id"], "--step", "beta").returncode, 2)

    def test_failed_check_cannot_accept_its_own_changed_significant_input(self):
        self.add_three(failing=True)
        self.sb.write("source", "original")
        step = self.package["steps"][1]
        step["inputs"] = ["source"]
        declaration = self.config["profile_config"]["local_packages"]["beta"]
        declaration["inputs"] = ["source"]
        script = self.profile / "actions/beta.sh"
        script.write_text("echo mutated > source\n" + script.read_text())
        declaration["sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
        self.save_config()
        self.save_package()
        state = json.loads(self.call("run", self.path, "--json").stdout)
        self.sb.write("fixed", "repair")
        result = self.call("resume", state["run_id"], "--decision", self.decision(state))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("stale", result.stderr)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\n")

    def test_utf8_pages_and_exact_non_utf8_human_log_artifact(self):
        self.script.write_bytes(b"printf '\\320\\226\\360\\237\\231\\202\\377'\n")
        self.config["profile_config"]["local_packages"]["alpha"]["sha256"] = (
            hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.save_config()
        state = json.loads(self.call("run", self.path, "--json").stdout)
        page = self.call("read", state["run_id"], "--step", "a", "--offset", 1,
                         "--limit", 1, "--json")
        self.assertEqual(json.loads(page.stdout)["text"], "🙂")
        self.assertEqual(page.returncode, 0, page.stderr)
        directory = self.sb.store / ".svod/package-runs" / state["run_id"]
        log = directory / state["steps"][0]["logs"][0]["ref"]
        self.assertEqual(log.read_bytes(), "Ж🙂".encode() + b"\xff")

    def test_crash_state_is_unknown_no_retry_and_read_does_not_repair(self):
        from svod import package_store
        self.add_three(failing=True)
        report = json.loads(self.call("run", self.path, "--json").stdout)
        directory, state = package_store.load(self.sb.store, "pilot", report["run_id"])
        state["status"] = "running"
        state["steps"][1]["status"] = "running"
        package_store.save(directory, state)
        before = (directory / "state.json").read_bytes()
        observed = json.loads(self.call("status", report["run_id"], "--json").stdout)
        self.assertEqual(observed["status"], "unknown")
        self.assertEqual(observed["steps"][1]["status"], "unknown")
        result = self.call("resume", report["run_id"], "--decision", self.decision(observed))
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown", result.stderr)
        self.assertEqual((directory / "state.json").read_bytes(), before)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\n")
        with package_store.lock(directory):
            locked = self.call("resume", report["run_id"], "--decision", self.decision(observed))
            self.assertEqual(locked.returncode, 2)
            self.assertIn("writer", locked.stderr)

    def test_stale_script_input_and_simultaneous_user_decision_never_dispatch(self):
        self.add_three(failing=True)
        self.package["steps"][1]["inputs"] = ["required"]
        self.config["profile_config"]["local_packages"]["beta"]["inputs"] = ["required"]
        self.save_package()
        self.save_config()
        state = json.loads(self.call("run", self.path, "--json").stdout)
        decision = self.decision(state)
        self.sb.write("required", "new input previously missing")
        blocked = self.call("resume", state["run_id"], "--decision", decision)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("stale", blocked.stderr)
        (self.sb.store / "required").unlink()
        self.script.write_text(self.script.read_text() + "echo changed\n")
        blocked = self.call("resume", state["run_id"], "--decision", decision)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("script changed", blocked.stderr)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\n")

    def test_failed_mutation_never_retries_and_user_can_stop(self):
        self.add_three(failing=True)
        self.config["profile_config"]["local_packages"]["beta"]["kind"] = "action"
        self.save_config()
        state = json.loads(self.call("run", self.path, "--json").stdout)
        retry = self.call("resume", state["run_id"], "--decision", self.decision(state))
        self.assertEqual(retry.returncode, 2)
        self.assertIn("mutation", retry.stderr)
        stopped = self.call("resume", state["run_id"], "--decision",
                            self.decision(state, "stop"), "--json")
        self.assertEqual(json.loads(stopped.stdout)["status"], "stopped")
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\n")

    def test_exact_later_occurrence_does_not_use_first_action_route(self):
        pipeline = self.profile / "pipelines/note.yaml"
        text = pipeline.read_text().replace("  - id: outcome\n",
                                           "  - id: outcome\n    action: alpha\n")
        pipeline.write_text(text)
        self.package["steps"][0]["step_id"] = "outcome"
        self.save_package()
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads(result.stdout)
        self.assertIn("not reached", state["reason"])
        self.assertEqual(state["steps"][0]["logs"], [])

    def test_log_symlink_traversal_missing_and_private_state_controls(self):
        self.add_three(failing=True)
        state = json.loads(self.call("run", self.path, "--json").stdout)
        directory = self.sb.store / ".svod/package-runs" / state["run_id"]
        log = directory / "beta-0.log"
        log.unlink()
        self.assertEqual(self.call("read", state["run_id"], "--step", "beta").returncode, 2)
        log.symlink_to(self.path)
        self.assertEqual(self.call("read", state["run_id"], "--step", "beta").returncode, 2)
        self.assertEqual(self.call("status", "../escape").returncode, 2)
        (directory / "state.json").chmod(0o644)
        self.assertEqual(self.call("status", state["run_id"]).returncode, 2)

    def test_timeout_stops_chain_and_never_automatically_retries(self):
        self.script.write_text("echo before\nsleep 30\necho after\n")
        self.config["profile_config"]["local_packages"]["alpha"]["sha256"] = (
            hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.package["steps"][0]["timeout"] = .15
        self.save_config()
        self.save_package()
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["steps"][0]["code"], 124)
        self.assertTrue(state["steps"][0]["timed_out"])
        self.assertEqual(state["steps"][0]["excerpt"], "before\n")

    def test_changed_record_environment_blocks_resume(self):
        self.add_three(failing=True)
        state = json.loads(self.call("run", self.path, "--json").stdout)
        self.sb.write("notes/pilot.md", (self.sb.store / "notes/pilot.md").read_text().replace(
            "status: active", "status: active\nowner: somebody-else"))
        result = self.call("resume", state["run_id"], "--decision", self.decision(state))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("stale", result.stderr)

    def test_successful_action_cannot_refresh_changed_commands_into_trust(self):
        self.add_three()
        script = self.profile / "actions/alpha.sh"
        script.write_text(script.read_text() + "echo '#changed' >> profile/actions/beta.sh\n")
        self.config["profile_config"]["local_packages"]["alpha"]["sha256"] = (
            hashlib.sha256(script.read_bytes()).hexdigest())
        self.save_config()
        result = self.call("run", self.path, "--json")
        state = json.loads(result.stdout)
        self.assertEqual(state["status"], "waiting")
        # Restore exact script bytes; old reviewed commands remain authoritative.
        beta = self.profile / "actions/beta.sh"
        beta.write_text(beta.read_text().removesuffix("#changed\n"))
        continued = self.call("resume", state["run_id"], "--decision",
                              self.decision(state, "continue"), "--json")
        self.assertEqual(continued.returncode, 0, continued.stderr)

    def test_package_dispatch_reuses_do_policy_boundary(self):
        from unittest.mock import patch
        from svod import cli
        with patch.object(cli, "do_action", wraps=cli.do_action) as dispatch:
            result = self.sb.cli("package", "run", "pilot", str(self.path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dispatch.call_count, 1)

    def test_durable_intent_interruptions_before_and_after_spawn_are_unknown(self):
        from unittest.mock import patch
        from svod import actions, package_store
        for after_spawn in (False, True):
            native = actions.run_action

            def interrupted(*args, after_spawn=after_spawn, native=native, **kwargs):
                if after_spawn:
                    native(*args, **kwargs)
                raise KeyboardInterrupt("synthetic interruption")

            with patch.object(actions, "run_action", side_effect=interrupted), \
                    self.assertRaises(KeyboardInterrupt):
                self.sb.cli("package", "run", "pilot", str(self.path))
            directory = sorted((self.sb.store / ".svod/package-runs").glob("run-*"),
                               key=lambda p: p.stat().st_mtime_ns)[-1]
            _, state = package_store.load(self.sb.store, "pilot", directory.name)
            self.assertEqual(state["steps"][0]["status"], "running")
            observed = json.loads(self.call("status", directory.name, "--json").stdout)
            self.assertEqual(observed["status"], "unknown")
            result = self.call("resume", directory.name, "--decision", self.decision(observed))
            self.assertEqual(result.returncode, 2)

    def test_post_spawn_cleanup_error_stays_unknown_and_never_retries_check(self):
        from unittest.mock import patch
        from svod import actions, package_store
        self.script.write_text("echo effect >> effect\necho alpha\n")
        declaration = self.config["profile_config"]["local_packages"]["alpha"]
        declaration.update(kind="check",
                           sha256=hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.save_config()
        with patch.object(actions, "stop_group", side_effect=PermissionError(
                "process group cleanup could not be established")):
            result = self.sb.cli("package", "run", "pilot", str(self.path), "--json")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        directory = next((self.sb.store / ".svod/package-runs").glob("run-*"))
        _, saved = package_store.load(self.sb.store, "pilot", directory.name)
        self.assertEqual(saved["status"], "running")
        self.assertEqual(saved["steps"][0]["status"], "running")
        self.assertIsNone(saved["steps"][0]["logs"][0]["sha256"])
        self.assertIsNone(saved["steps"][0]["logs"][0]["bytes"])
        before = (directory / "state.json").read_bytes()
        observed = json.loads(self.call("status", directory.name, "--json").stdout)
        self.assertEqual(observed["status"], "unknown")
        retry = self.call("resume", directory.name, "--decision", self.decision(observed))
        self.assertEqual(retry.returncode, 2, retry.stdout + retry.stderr)
        self.assertIn("unknown effects", retry.stderr)
        self.assertEqual((directory / "state.json").read_bytes(), before)
        self.assertEqual((self.sb.store / "effect").read_text(), "effect\n")

    def test_pre_spawn_error_does_not_execute_action(self):
        from unittest.mock import patch
        from svod import actions
        with patch.object(actions.subprocess, "Popen", side_effect=PermissionError("spawn denied")):
            result = self.sb.cli("package", "run", "pilot", str(self.path), "--json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["steps"][0]["status"], "failed")
        self.assertEqual(report["steps"][0]["code"], 2)
        self.assertEqual(report["steps"][0]["logs"][0]["bytes"], 0)

    def test_required_state_write_failure_prevents_spawn(self):
        from unittest.mock import patch
        from svod import package_store
        native = package_store.save

        def failing(directory, state):
            if state["status"] == "running":
                raise OSError("required state write failed")
            return native(directory, state)

        with patch.object(package_store, "save", side_effect=failing):
            result = self.sb.cli("package", "run", "pilot", str(self.path))
        self.assertEqual(result.returncode, 2)
        self.assertIn("required state", result.stderr)
        directory = next((self.sb.store / ".svod/package-runs").glob("run-*"))
        self.assertEqual((directory / "a-0.log").read_bytes(), b"")

    def test_required_log_fsync_failure_leaves_unknown_without_next_action(self):
        import os
        from pathlib import Path
        from unittest.mock import patch
        from svod import package_store
        self.add_three()
        native = os.fsync
        open_path = Path.open
        log_fds = set()

        def track_log(path, *args, **kwargs):
            stream = open_path(path, *args, **kwargs)
            if path.suffix == ".log" and args and args[0] == "xb":
                log_fds.add(stream.fileno())
            return stream

        def fail_log(fd):
            if fd in log_fds:
                raise OSError("required log fsync failed")
            return native(fd)

        with patch.object(Path, "open", track_log), \
                patch.object(package_store.os, "fsync", side_effect=fail_log):
            result = self.sb.cli("package", "run", "pilot", str(self.path))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\n")
        directory = next((self.sb.store / ".svod/package-runs").glob("run-*"))
        state = json.loads(self.call("status", directory.name, "--json").stdout)
        self.assertEqual(state["status"], "unknown")

    def test_capture_reaps_descendants_before_terminal_log(self):
        import os
        import time
        self.script.write_text("echo $$ > leader\n(sleep .8; echo escaped > late) &\necho done\n")
        self.config["profile_config"]["local_packages"]["alpha"]["sha256"] = (
            hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.save_config()
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        time.sleep(1)
        self.assertFalse((self.sb.store / "late").exists())
        pid = int((self.sb.store / "leader").read_text())
        with self.assertRaises(ProcessLookupError):
            os.killpg(pid, 0)

    def test_rejects_malformed_declarations_before_execution(self):
        import copy
        original = copy.deepcopy(self.package)
        changes = (("timeout", 0), ("timeout", True), ("timeout", float("nan")),
                   ("args", "echo shell"), ("step_id", "missing"), ("id", "../escape"),
                   ("inputs", ["../outside"]), ("outputs", ["/absolute"]))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.package = copy.deepcopy(original)
                self.package["steps"][0][field] = value
                self.save_package()
                result = self.call("run", self.path)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((self.sb.store / ".svod/package-runs").exists())

    def test_real_cli_kill_after_effect_is_unknown_and_never_replayed(self):
        import os
        import signal
        import subprocess
        import sys
        import time
        from support import child_env
        self.script.write_text("echo effect >> effect\necho ready\nsleep 30\n")
        self.config["profile_config"]["local_packages"]["alpha"]["sha256"] = (
            hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.save_config()
        process = subprocess.Popen([sys.executable, "-m", "svod.cli", "package", "run", "pilot",
                                    str(self.path)], cwd=self.sb.store, env=child_env(),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        group = None
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if (self.sb.store / "effect").exists():
                    break
                time.sleep(.02)
            self.assertTrue((self.sb.store / "effect").exists())
            # Identify only our fixture child for cleanup after deliberately killing the CLI.
            children = subprocess.check_output(["pgrep", "-P", str(process.pid)], text=True)
            group = int(children.splitlines()[0])
            process.kill()
            process.communicate(timeout=5)
            directory = next((self.sb.store / ".svod/package-runs").glob("run-*"))
            state = json.loads(self.call("status", directory.name, "--json").stdout)
            self.assertEqual(state["status"], "unknown")
            rejected = self.call("resume", directory.name, "--decision", self.decision(state))
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual((self.sb.store / "effect").read_text(), "effect\n")
            read = self.call("read", directory.name, "--step", "a")
            self.assertEqual(read.stdout, "ready\n")
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
            if group:
                with suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)

    def test_offline_baseline_equivalent_artifacts_and_actual_output_cost(self):
        import time
        from pathlib import Path
        rows = []
        artifacts = []
        paths, raw_logs = [], []
        for packaged in (False, True):
            fixture = PackageTest()
            fixture.setUp()
            try:
                fixture.add_three()
                # Same scripts/artifacts; intentionally verbose fixture output in both paths.
                for name in ("alpha", "beta", "gamma"):
                    script = fixture.profile / f"actions/{name}.sh"
                    script.write_text(script.read_text() + "printf '%05000d\\n' 0\n")
                    fixture.config["profile_config"]["local_packages"][name]["sha256"] = (
                        hashlib.sha256(script.read_bytes()).hexdigest())
                fixture.save_config()
                calls = []
                start = time.monotonic()
                if packaged:
                    run = fixture.call("run", fixture.path, "--json")
                    calls.append(run)
                    state = json.loads(run.stdout)
                    calls.append(fixture.call("status", state["run_id"], "--json"))
                    calls.append(fixture.call("read", state["run_id"], "--step", "beta",
                                              "--limit", 32, "--json"))
                    directory = fixture.sb.store / ".svod/package-runs" / state["run_id"]
                    paths = [directory / log["ref"] for step in state["steps"]
                             for log in step["logs"]]
                    raw_logs = [p.read_bytes() for p in paths]
                    self.assertEqual(raw_logs, [(name + "\n" + "0" * 5000 + "\n").encode()
                                                for name in ("alpha", "beta", "gamma")])
                else:
                    for name in ("alpha", "beta", "gamma"):
                        calls.append(fixture.sb.cli_process("do", name, "pilot"))
                self.assertTrue(all(c.returncode == 0 for c in calls))
                artifacts.append({p.name: p.read_bytes() for p in
                                  (fixture.sb.store / "notes").iterdir()})
                rows.append({"mode": "package" if packaged else "individual", "calls": len(calls),
                             "bytes_per_call": [len((c.stdout + c.stderr).encode()) for c in calls],
                             "elapsed_seconds": round(time.monotonic() - start, 4)})
            finally:
                fixture.doCleanups()
        self.assertEqual(artifacts[0], artifacts[1])
        rows[1]["execution_calls"] = 1
        rows[0]["execution_calls"] = 3
        rows[1]["human_artifacts"] = {
            "path_template": "<store>/.svod/package-runs/<run-id>/<log-ref>",
            "files": len(paths), "raw_bytes": sum(len(data) for data in raw_logs),
            "cli_api_calls": 0, "included_in_response_bytes": False}
        print("PACKAGE_BASELINE=" + json.dumps(rows, sort_keys=True))
        # Persist only measured evidence on explicit opt-in, never test artifacts in the repository.
        import os
        if os.environ.get("SVOD_PACKAGE_BASELINE"):
            Path(os.environ["SVOD_PACKAGE_BASELINE"]).write_text(json.dumps(rows, indent=2) + "\n")

    def test_text_report_includes_bounded_error_and_exact_log_reference(self):
        self.add_three(failing=True)
        result = self.call("run", self.path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("USER", result.stdout)
        self.assertIn("exit 7", result.stdout)
        self.assertIn("excerpt: beta", result.stdout)
        self.assertIn("beta-0.log", result.stdout)
        self.assertIn("remaining: beta,gamma", result.stdout)

    def test_crash_before_writer_acquisition_is_unknown_not_missing_lock(self):
        from svod import package_store
        directory, state = package_store.create(self.sb.store, "pilot", self.package,
                                                "snapshot", {})
        result = self.call("status", state["run_id"], "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "unknown")
        self.assertTrue((directory / "writer.lock").is_file())

    def test_error_resume_baseline_preserves_mutation_and_artifacts(self):
        import time
        artifacts, rows = [], []
        for packaged in (False, True):
            fixture = PackageTest()
            fixture.setUp()
            try:
                fixture.add_three(failing=True)
                start = time.monotonic()
                calls = []
                if packaged:
                    failed = fixture.call("run", fixture.path, "--json")
                    calls.append(failed)
                    self.assertEqual(failed.returncode, 1)
                    state = json.loads(failed.stdout)
                    calls.append(fixture.call("status", state["run_id"], "--json"))
                    calls.append(fixture.call("read", state["run_id"], "--step", "beta", "--json"))
                    fixture.sb.write("fixed", "user fixture repair")
                    calls.append(fixture.call("resume", state["run_id"], "--decision",
                                              fixture.decision(state), "--json"))
                else:
                    calls.append(fixture.sb.cli_process("do", "alpha", "pilot"))
                    calls.append(fixture.sb.cli_process("do", "beta", "pilot"))
                    self.assertEqual(calls[-1].returncode, 7)
                    fixture.sb.write("fixed", "user fixture repair")
                    calls.append(fixture.sb.cli_process("do", "beta", "pilot"))
                    calls.append(fixture.sb.cli_process("do", "gamma", "pilot"))
                self.assertEqual(calls[-1].returncode, 0)
                self.assertEqual((fixture.sb.store / "calls").read_text(),
                                 "alpha\nbeta\nbeta\ngamma\n")
                artifacts.append({p.name: p.read_bytes() for p in
                                  (fixture.sb.store / "notes").iterdir()})
                rows.append({"mode": "package" if packaged else "individual", "calls": len(calls),
                             "bytes_per_call": [len((c.stdout + c.stderr).encode()) for c in calls],
                             "elapsed_seconds": round(time.monotonic() - start, 4)})
            finally:
                fixture.doCleanups()
        self.assertEqual(artifacts[0], artifacts[1])
        print("ERROR_RESUME_BASELINE=" + json.dumps(rows, sort_keys=True))

    def test_corrupt_saved_state_is_explicit_error_not_traceback(self):
        self.add_three(failing=True)
        state = json.loads(self.call("run", self.path, "--json").stdout)
        path = self.sb.store / ".svod/package-runs" / state["run_id"] / "state.json"
        for invalid in ([], None, {"version": 1}, {"version": 1, "run_id": state["run_id"],
                                                  "record": "pilot", "revision": 4, "steps": None}):
            path.write_text(json.dumps(invalid))
            result = self.call("status", state["run_id"])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_resume_refuses_corrupted_completed_source_before_dispatch(self):
        self.add_three(failing=True)
        state = json.loads(self.call("run", self.path, "--json").stdout)
        directory = self.sb.store / ".svod/package-runs" / state["run_id"]
        (directory / "alpha-0.log").write_bytes(b"corrupt")
        self.sb.write("fixed", "repair")
        result = self.call("resume", state["run_id"], "--decision", self.decision(state))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("corrupt", result.stderr)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\n")

    def test_new_policy_error_outranks_simultaneous_continue_decision(self):
        from unittest.mock import patch
        from svod import packages
        self.add_three()
        original = packages.policy

        def stop_before_beta(root, record, step):
            if step["id"] == "beta":
                raise ValueError("synthetic first policy boundary")
            return original(root, record, step)

        with patch.object(packages, "policy", side_effect=stop_before_beta):
            stopped = self.sb.cli("package", "run", "pilot", str(self.path), "--json")
        state = json.loads(stopped.stdout)
        self.assertEqual(state["steps"][0]["status"], "succeeded")
        self.assertEqual(state["steps"][1]["status"], "pending")
        decision = self.decision(state, "continue")
        with patch.object(packages, "policy", side_effect=ValueError("new error wins")):
            rejected = self.sb.cli("package", "resume", "pilot", state["run_id"],
                                   "--decision", str(decision))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("new error wins", rejected.stderr)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\n")
        continued = self.sb.cli("package", "resume", "pilot", state["run_id"],
                                "--decision", str(decision), "--json")
        self.assertEqual(continued.returncode, 0, continued.stderr)
        self.assertEqual((self.sb.store / "calls").read_text(), "alpha\nbeta\ngamma\n")

    def test_authoritative_package_digest_detects_mutation(self):
        self.add_three(failing=True)
        report = json.loads(self.call("run", self.path, "--json").stdout)
        path = self.sb.store / ".svod/package-runs" / report["run_id"] / "state.json"
        state = json.loads(path.read_bytes())
        self.assertIn("package_digest", state)
        state["package"]["steps"][1]["timeout"] = 3
        path.write_text(json.dumps(state))
        rejected = self.call("status", report["run_id"])
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("corrupt", rejected.stderr)

    def test_invalid_saved_step_status_fails_closed_before_resume(self):
        self.add_three(failing=True)
        report = json.loads(self.call("run", self.path, "--json").stdout)
        path = self.sb.store / ".svod/package-runs" / report["run_id"] / "state.json"
        state = json.loads(path.read_bytes())
        state["steps"][1]["status"] = "invented"
        path.write_text(json.dumps(state))
        result = self.call("status", report["run_id"])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("corrupt", result.stderr)

    def test_successful_last_step_cannot_report_success_after_changing_input(self):
        self.sb.write("source", "original")
        self.package["steps"][0]["inputs"] = ["source"]
        declaration = self.config["profile_config"]["local_packages"]["alpha"]
        declaration["inputs"] = ["source"]
        self.script.write_text("echo mutation > source\n")
        declaration["sha256"] = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.save_config()
        self.save_package()
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["status"], "waiting")
        self.assertIn("unexpected", state["reason"])

    def test_last_action_changed_command_stops_even_without_following_step(self):
        self.script.write_text("echo '#changed' >> profile/actions/alpha.sh\n")
        self.config["profile_config"]["local_packages"]["alpha"]["sha256"] = (
            hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.save_config()
        result = self.call("run", self.path, "--json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("command", json.loads(result.stdout)["reason"])

    def test_no_blind_continuation_after_all_completed_but_invalid_boundary(self):
        self.sb.write("source", "original")
        self.package["steps"][0]["inputs"] = ["source"]
        declaration = self.config["profile_config"]["local_packages"]["alpha"]
        declaration["inputs"] = ["source"]
        self.script.write_text("echo mutation > source\n")
        declaration["sha256"] = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.save_config()
        self.save_package()
        state = json.loads(self.call("run", self.path, "--json").stdout)
        self.sb.write("source", "original")
        result = self.call("resume", state["run_id"], "--decision",
                           self.decision(state, "continue"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_validate_admits_exact_reviewed_local_action_without_execution(self):
        result = self.call("validate", self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("valid", result.stdout)
        self.assertFalse((self.sb.store / ".svod/package-runs").exists())
        self.package["steps"][0]["action"] = "push"
        self.save_package()
        rejected = self.call("validate", self.path)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("reviewed", rejected.stderr)
