"""Path-scoped pre-tool writes on disposable standard instances."""
import json
import os
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

import test_standard_template as fixtures
from svod.hooks.events import pre_tool
from svod.approval import write_human_mark
from svod.hooks.prompt import prompt_hook


class ScopedWritesTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = fixtures.StandardStore(temp.name)
        self.sb.edit(f"{fixtures.EXAMPLE}/card.md", fixtures.ARCHIVED, fixtures.OPEN)
        self.env = mock.patch.dict(os.environ, self.sb.env)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def issue(self, *paths):
        args = ("allow", fixtures.EXAMPLE, "--for", "30m",
                *(part for path in paths for part in ("--path", str(path))))
        self.assertNotEqual(self.sb.cli(*args).returncode, 0)
        prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, self.sb.store)
        result = self.sb.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)

    def reason(self, tool, data, cwd=None):
        result = pre_tool({"cwd": str(cwd or self.sb.store), "tool_name": tool,
                           "tool_input": data}, self.sb.store)
        if result is None:
            return None
        output = json.loads(result)["hookSpecificOutput"]
        self.assertEqual(output.get("permissionDecision"), "deny", output)
        return output["permissionDecisionReason"]

    def test_sed_options_cannot_hide_write_scripts(self):
        for command in (f"sed -n 'w {self.sb.base}/escape' input.txt",
                        f"sed -e 'w {self.sb.base}/escape' input.txt",
                        f"sed -n -e 'w {self.sb.base}/escape' input.txt"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.reason("Bash", {"command": command}))

    def test_quoted_operators_never_change_the_effective_cwd(self):
        (self.sb.store / "child").mkdir()
        command = "echo '&&' cd child && echo ESCAPE > ../quote-escape"
        self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertIsNone(self.reason("Bash", {"command": "echo '&&' > notes.md"}))

    def test_printf_variable_assignment_cannot_redirect_cwd_outside_scope(self):
        import subprocess
        (self.sb.store / "child").mkdir()
        outside = self.sb.base / "external-child-root"
        (outside / "child").mkdir(parents=True)
        for option in ("-v CDPATH", "-vCDPATH"):
            command = f"printf {option} {outside} && cd child && echo ESCAPE > marker"
            with self.subTest(option=option):
                denial = self.reason("Bash", {"command": command})
                if denial is None:
                    subprocess.run(["bash", "-c", command], cwd=self.sb.store,
                                   env=self.sb.env, check=True, capture_output=True)
                self.assertFalse((outside / "child/marker").exists())
                self.assertIsNotNone(denial)
        self.assertIsNone(self.reason("Bash", {"command": "printf '%s' text > notes.md"}))

    def test_inherited_cdpath_cannot_change_resolved_write_destination(self):
        (self.sb.store / "child").mkdir()
        outside = self.sb.base / "external-child-root"
        (outside / "child").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"CDPATH": str(outside)}):
            self.assertIsNotNone(self.reason("Bash", {"command":
                "cd child && echo ESCAPE > marker"}))
            self.assertIsNone(self.reason("Bash", {"command":
                "cd ./child && echo SAFE > marker"}))
            self.assertIsNone(self.reason("Bash", {"command":
                f"cd {self.sb.store}/child && echo SAFE > marker"}))

    def test_broken_runtime_refuses_unresolved_shell_effects(self):
        self.sb.write("svod.yaml", "broken: [\n")
        outside = self.sb.base / "outside"
        self.assertIsNotNone(self.reason("Bash", {"command":
            f'''python3 -c 'open("{outside}", "w").write("x")' '''}))
        self.assertIsNone(self.reason("Bash", {"command": "echo fixed > notes.md"}))

    def test_harmless_stat_and_silent_grep_remain_read_only(self):
        for command in ("stat notes.md", "stat -f '%N' notes.md", "grep -s x notes.md"):
            with self.subTest(command=command):
                self.assertIsNone(self.reason("Bash", {"command": command}))

    def test_editable_work_yaml_cannot_authorize_arbitrary_or_foreign_roots(self):
        self.sb.edit(f"{fixtures.EXAMPLE}/card.md", "services: []", "services: [app]")
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        self.sb.cli("init", "--login", "tester")
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        arbitrary = self.sb.base / "arbitrary"
        arbitrary.mkdir()
        foreign = self.sb.base / "foreign"
        self.sb.git(self.sb.store, "worktree", "add", "-q", "-b", "foreign", str(foreign))
        for tree in (arbitrary, foreign, self.sb.service, self.sb.service / "child"):
            tree.mkdir(exist_ok=True)
            self.sb.write(f"{fixtures.EXAMPLE}/work.yaml", f"app: {tree}\n")
            with self.subTest(tree=str(tree)):
                self.assertIsNotNone(self.reason("Write", {"file_path": str(tree / "x")},
                                                 self.sb.store / fixtures.EXAMPLE))

    def test_native_allow_rejects_explicit_nonconsent(self):
        from svod.hooks.prompt import prompt_hook
        target = self.sb.base / "outside"
        args = ("allow", fixtures.EXAMPLE, "--for", "30m", "--path", str(target))
        self.sb.cli(*args)
        prompt_hook({"cwd": str(self.sb.store),
                     "prompt": "Do not grant access to any external paths."}, self.sb.store)
        result = self.sb.cli(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIsNotNone(self.reason("Write", {"file_path": str(target / "a")},
                                         self.sb.store / fixtures.EXAMPLE))

    def test_grant_requires_prepared_request_before_go_and_unchanged_selection(self):
        from svod.hooks.prompt import prompt_hook
        target = self.sb.base / "requested"
        args = ("allow", fixtures.EXAMPLE, "--for", "30m", "--path", str(target))
        prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, self.sb.store)
        self.assertNotEqual(self.sb.cli(*args).returncode, 0, "unbound go is not consent")
        prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, self.sb.store)
        changed = self.sb.cli("allow", fixtures.EXAMPLE, "--for", "30m", "--path",
                              str(self.sb.base / "substituted"))
        self.assertNotEqual(changed.returncode, 0, "post-reply path substitution")
        self.sb.cli(*args)
        prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, self.sb.store)
        allowed = self.sb.cli(*args)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertNotEqual(self.sb.cli(*args).returncode, 0, "no replay")

    def test_prepared_request_rejects_record_content_changes(self):
        from svod.hooks.prompt import prompt_hook
        args = ("allow", fixtures.EXAMPLE, "--for", "30m", "--path",
                str(self.sb.base / "requested"))
        self.assertNotEqual(self.sb.cli(*args).returncode, 0)
        prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, self.sb.store)
        self.sb.write(f"{fixtures.EXAMPLE}/contract.md", "Changed after consent\n")
        self.assertNotEqual(self.sb.cli(*args).returncode, 0)
        for command in ("echo '{}' > .git/svod-write-grants-request.json",
                        "cp notes.md .git/svod-write-grants-request.json"):
            self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertIsNotNone(self.reason("Write", {"file_path": str(
            self.sb.store / ".git/svod-write-grants-request.json")}))

    def test_native_workflow_scripts_retain_conservative_refusal(self):
        for command in ("python3 -m pytest -q", "git add notes.md", "git commit -m local",
                        f"bash profile/actions/start-task.sh {fixtures.EXAMPLE}",
                        f"bash profile/actions/checks.sh {fixtures.EXAMPLE}",
                        "svod init --login tester"):
            with self.subTest(command=command):
                self.assertIn("unknown program effects", self.reason("Bash", {"command": command}))

    def trusted_task(self):
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        self.sb.edit("svod.yaml", "profile_config:\n", "profile_config:\n"
                     "  trusted_actions:\n"
                     "    start-task: [bash, profile/actions/start-task.sh, '{id}']\n"
                     "    checks: [bash, profile/actions/checks.sh, '{id}']\n"
                     "  checks:\n    app: [test, -e, .git]\n")
        self.sb.edit(f"{fixtures.EXAMPLE}/card.md", "services: []", "services: [app]")
        self.sb.cli("init", "--login", "tester")
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)

    def test_trusted_standard_start_task_native_dispatch(self):
        self.trusted_task()
        command = f"svod do start-task {fixtures.EXAMPLE}"
        self.assertIsNone(self.reason("Bash", {"command": command}))
        result = self.sb.cli("do", "start-task", fixtures.EXAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not filesystem-isolated", result.stderr)
        tree = self.sb.base / fixtures.WORKTREE
        self.assertTrue((tree / ".git").is_file())
        self.assertEqual((self.sb.store / fixtures.EXAMPLE / "work.yaml").read_text(),
                         f"app: ../{fixtures.WORKTREE}\n")

    def test_trusted_checks_exact_configured_script_dispatch(self):
        self.trusted_task()
        self.assertEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)
        command = f"bash profile/actions/checks.sh {fixtures.EXAMPLE}"
        self.assertIsNone(self.reason("Bash", {"command": command}))
        checked = self.sb.cli("do", "checks", fixtures.EXAMPLE)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        report = self.sb.store / fixtures.EXAMPLE / "checks.md"
        self.assertIn("passed", report.read_text())
        self.assertIn("test -e .git", report.read_text())
        self.assertEqual(self.sb.cli("validate").returncode, 0)

    def test_trust_snapshot_cannot_be_forged_by_direct_tools(self):
        self.trusted_task()
        path = self.sb.store / fixtures.EXAMPLE / "approval.yaml"
        self.assertIsNotNone(self.reason("Edit", {"file_path": str(path),
            "old_string": "trusted_actions_sha: old", "new_string": "trusted_actions_sha: forged"}))

    def test_value_only_edit_cannot_forge_trusted_snapshot(self):
        from svod.actions import trust_digest
        from svod.context import Context
        from svod.loader import load_runtime

        self.trusted_task()
        path = self.sb.store / fixtures.EXAMPLE / "approval.yaml"
        old_sha = next(line.split(": ", 1)[1] for line in path.read_text().splitlines()
                       if line.startswith("trusted_actions_sha:"))
        self.sb.edit("svod.yaml", "app: [test, -e, .git]", "app: [echo, changed]")
        runtime = load_runtime(self.sb.store)
        pipeline = next(p for p in runtime.pipelines if p.name == "task")
        sha = trust_digest(Context(runtime.config, runtime.locale), pipeline)
        for tool, data in (("Edit", {"old_string": old_sha, "new_string": sha}),
                           ("MultiEdit", {"edits": [{"old_string": old_sha,
                                                     "new_string": sha}]})):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.reason(tool, {"file_path": str(path), **data}))
        self.assertNotEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)
        self.assertFalse((self.sb.store / fixtures.EXAMPLE / "work.yaml").exists())

    def test_status_refuses_changed_executable_gate(self):
        self.trusted_task()
        for action in ("start-task", "checks"):
            result = self.sb.cli("do", action, fixtures.EXAMPLE)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sb.cli("status", fixtures.EXAMPLE).returncode, 0)
        marker = self.sb.base / "outside-gate"
        self.sb.edit("profile/pipelines/task.yaml",
                     'argv: [bash, profile/actions/checks.sh, "{id}", --check]',
                     f'argv: [bash, -c, "printf changed > {marker}"]')
        result = self.sb.cli("status", fixtures.EXAMPLE, "--fresh")
        self.assertFalse(marker.exists(), result.stdout + result.stderr)
        self.assertIn("configuration changed", result.stdout + result.stderr)

    def test_removing_trust_cannot_restore_legacy_check_execution(self):
        self.trusted_task()
        for action in ("start-task", "checks"):
            result = self.sb.cli("do", action, fixtures.EXAMPLE)
            self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.sb.base / "outside-status"
        self.sb.edit("svod.yaml", "  trusted_actions:\n"
                     "    start-task: [bash, profile/actions/start-task.sh, '{id}']\n"
                     "    checks: [bash, profile/actions/checks.sh, '{id}']",
                     "  trusted_actions: {}")
        self.sb.edit("svod.yaml", "app: [test, -e, .git]",
                     f"app: 'printf bypass > {marker}'")
        status = self.sb.cli("status", fixtures.EXAMPLE, "--fresh")
        self.assertFalse(marker.exists(), status.stdout + status.stderr)
        self.assertIn("configuration changed", status.stdout + status.stderr)
        for result in (self.sb.action("checks.sh", fixtures.EXAMPLE, "--check"),
                       self.sb.cli("do", "checks", fixtures.EXAMPLE)):
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(marker.exists())

    def test_sourced_non_shell_helper_changes_invalidate_native_trust(self):
        self.trusted_task()
        helper = self.sb.store / "profile/actions/lib/helper.inc"
        self.sb.write("profile/actions/lib/helper.inc", ":\n")
        action = self.sb.store / "profile/actions/start-task.sh"
        action.write_text(action.read_text() + '\n. "$SVOD_ROOT/profile/actions/lib/helper.inc"\n')
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        command = f"svod do start-task {fixtures.EXAMPLE}"
        self.assertIsNone(self.reason("Bash", {"command": command}))
        marker = self.sb.base / "outside-helper"
        helper.write_text(f"printf injected > {marker}\n")
        self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertNotEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        self.assertIsNone(self.reason("Bash", {"command": command}))
        self.assertEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)
        self.assertTrue(marker.exists(), "Freshly reviewed internals are explicitly trusted")

    def test_trust_snapshot_rejects_symlink_helpers(self):
        self.trusted_task()
        outside = self.sb.base / "helper.inc"
        outside.write_text(":\n")
        helper = self.sb.store / "profile/actions/helper.inc"
        helper.symlink_to(outside)
        result = self.sb.approve(fixtures.EXAMPLE, "approve")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(self.reason("Bash", {"command":
            f"svod do start-task {fixtures.EXAMPLE}"}))

    def test_trust_changes_cannot_inherit_approval(self):
        self.trusted_task()
        command = f"svod do start-task {fixtures.EXAMPLE}"
        self.sb.edit("svod.yaml", "app: [test, -e, .git]", "app: [echo, changed]")
        self.assertIsNotNone(self.reason("Bash", {"command": command}))
        result = self.sb.cli("do", "start-task", fixtures.EXAMPLE)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.sb.store / fixtures.EXAMPLE / "work.yaml").exists())

    def test_changed_trust_requires_reply_after_configuration(self):
        self.trusted_task()
        self.sb.edit("profile/actions/start-task.sh", "# Start a task:", "# Reviewed action:")
        from svod.approval import write_mark
        import datetime as dt
        write_mark(self.sb.store, [], dt.datetime.now().astimezone() - dt.timedelta(minutes=1))
        # Record evidence predates the reply, but changed trust configuration does not.
        result = self.sb.cli("approve", fixtures.EXAMPLE, "--step", "approve")
        self.assertNotEqual(result.returncode, 0)

    def test_trusted_dispatch_refuses_extra_cli_arguments(self):
        self.trusted_task()
        result = self.sb.cli("do", "start-task", fixtures.EXAMPLE, "--", "evil")
        self.assertNotEqual(result.returncode, 0)

    def test_direct_trusted_checks_uses_native_configuration_not_environment(self):
        self.trusted_task()
        started = self.sb.action("start-task.sh", fixtures.EXAMPLE)
        self.assertEqual(started.returncode, 0, started.stderr)
        checked = self.sb.action("checks.sh", fixtures.EXAMPLE, SVOD_CHECKS_APP="false")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("not filesystem-isolated", checked.stderr)
        self.assertIn("test -e .git", (self.sb.store / fixtures.EXAMPLE / "checks.md").read_text())

    def test_trusted_action_is_not_an_interpreter_or_shell_sibling_exemption(self):
        self.trusted_task()
        native = f"svod do start-task {fixtures.EXAMPLE}"
        script = f"bash profile/actions/start-task.sh {fixtures.EXAMPLE}"
        for command in (native + "; echo x", native + " && true", native + " > output",
                        native + "$(echo x)", native + " extra", native + " --force",
                        script + "; true", script + " extra", script + " --check",
                        script.replace("profile/actions", "other/actions"),
                        "svod do cleanup " + fixtures.EXAMPLE,
                        "svod do start-task missing", "bash evil.sh", "python3 -m pytest -q",
                        "python3 -c 'print(1)'", "bash -c 'python3 evil.py'",
                        "git push", "gh pr merge", "npm publish"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertIsNone(self.reason("Bash", {"command": native}))
        self.assertIsNone(self.reason("Bash", {"command": script}))
        for command in ("cat svod.yaml", "git status --short", "svod status " + fixtures.EXAMPLE):
            self.assertIsNone(self.reason("Bash", {"command": command}))

    def test_trust_script_and_path_mutations_require_new_native_approval(self):
        self.trusted_task()
        command = f"svod do start-task {fixtures.EXAMPLE}"
        self.sb.edit("profile/actions/start-task.sh", "# Start a task:", "# Reviewed action:")
        self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertNotEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        self.assertIsNone(self.reason("Bash", {"command": command}))
        self.sb.edit("svod.yaml", "[bash, profile/actions/start-task.sh, '{id}']",
                     "[bash, profile/actions/checks.sh, '{id}']")
        self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertNotEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)

    def test_adding_trust_after_task_approval_does_not_inherit_it(self):
        self.trusted_task()
        path = self.sb.store / fixtures.EXAMPLE / "approval.yaml"
        path.write_text("\n".join(line for line in path.read_text().splitlines()
                                 if not line.startswith("trusted_actions")) + "\n")
        self.assertIsNotNone(self.reason("Bash", {"command":
            f"svod do start-task {fixtures.EXAMPLE}"}))
        self.assertNotEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)

    def test_trusted_checks_native_cli_and_pre_tool_process(self):
        import subprocess
        import sys
        self.trusted_task()
        self.sb.edit("svod.yaml", "app: [test, -e, .git]",
                     "app: [python3, -c, 'print(12345)']")
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        for name in ("start-task", "checks"):
            command = f"svod do {name} {fixtures.EXAMPLE}"
            hook = subprocess.run([sys.executable, "-m", "svod.cli", "hook", "pre-tool"],
                cwd=self.sb.store, env=self.sb.env, capture_output=True, text=True,
                input=json.dumps({"cwd": str(self.sb.store), "tool_name": "Bash",
                                  "tool_input": {"command": command}}))
            self.assertEqual(hook.returncode, 0, hook.stderr)
            self.assertEqual(hook.stdout, "")
            run = subprocess.run([sys.executable, "-m", "svod.cli", "do", name, fixtures.EXAMPLE],
                cwd=self.sb.store, env=self.sb.env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("not filesystem-isolated", run.stderr)
        log = self.sb.store / fixtures.EXAMPLE / "checks.log"
        self.assertIn("12345", log.read_text())
        self.assertIn("passed", (log.parent / "checks.md").read_text())

    def test_trusted_dispatch_rejects_read_only_main_checkout(self):
        self.trusted_task()
        self.sb.edit("svod.yaml", "workspace_gate: work_tree",
                     "workspace_gate: work_tree\nmain_checkout_read_only: true")
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        self.assertIsNotNone(self.reason("Bash", {"command":
            f"svod do start-task {fixtures.EXAMPLE}"}))

    def test_trusted_check_mode_cannot_use_environment_override(self):
        self.trusted_task()
        self.assertEqual(self.sb.cli("do", "start-task", fixtures.EXAMPLE).returncode, 0)
        self.assertEqual(self.sb.cli("do", "checks", fixtures.EXAMPLE).returncode, 0)
        checked = self.sb.action("checks.sh", fixtures.EXAMPLE, "--check", SVOD_CHECKS_APP="false")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("not filesystem-isolated", checked.stderr)
        self.sb.edit("svod.yaml", "app: [test, -e, .git]", "app: [echo, changed]")
        self.assertNotEqual(self.sb.action("checks.sh", fixtures.EXAMPLE, "--check").returncode, 0)

    def test_malformed_trust_configuration_denies_at_native_hook_boundary(self):
        from svod.hooks.events import answer
        self.trusted_task()
        self.sb.edit("svod.yaml", "  trusted_actions:\n"
                     "    start-task: [bash, profile/actions/start-task.sh, '{id}']\n"
                     "    checks: [bash, profile/actions/checks.sh, '{id}']",
                     "  trusted_actions: bad")
        result = answer("pre-tool", {"cwd": str(self.sb.store), "tool_name": "Bash",
            "tool_input": {"command": f"bash profile/actions/start-task.sh {fixtures.EXAMPLE}"}},
            self.sb.store)
        self.assertEqual(json.loads(result)["hookSpecificOutput"].get("permissionDecision"), "deny")

    def test_direct_writes_stay_inside_instance(self):
        self.assertIsNone(self.reason("Write", {"file_path": str(self.sb.store / "notes.md")}))
        self.assertIn("svod allow", self.reason(
            "Write", {"file_path": str(self.sb.base / "outside.txt")}))

    def test_native_allow_is_record_bound_and_requires_fresh_human(self):
        target = self.sb.base / "outside"
        args = ("allow", fixtures.EXAMPLE, "--for", "30m", "--path", str(target))
        denied = self.sb.cli(*args)
        self.assertNotEqual(denied.returncode, 0)
        prompt_hook({"cwd": str(self.sb.store), "prompt": "go ahead"}, self.sb.store)
        allowed = self.sb.cli(*args)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        cwd = self.sb.store / fixtures.EXAMPLE
        self.assertIsNone(self.reason("Write", {"file_path": str(target / "a")}, cwd))
        self.assertIsNotNone(self.reason("Write", {"file_path": str(target / "a")}))
        self.assertIsNotNone(self.reason("Write", {"file_path": str(target.parent / "other")}, cwd))
        self.assertNotEqual(self.sb.cli(*args).returncode, 0, "no automatic renewal")

    def test_declared_worktree_selects_one_record_but_not_foreign_tree(self):
        tree = self.sb.base / "app-task-example"
        self.sb.edit(f"{fixtures.EXAMPLE}/card.md", "services: []",
                     f"services: [{fixtures.SERVICE}]")
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        self.sb.git(self.sb.service, "worktree", "add", "-q", "-b", "scoped", str(tree))
        self.sb.write(f"{fixtures.EXAMPLE}/work.yaml", f"app: {tree}\n")
        self.sb.cli("init", "--login", "tester")
        self.assertEqual(self.sb.approve(fixtures.EXAMPLE, "approve").returncode, 0)
        self.assertIsNone(self.reason("Write", {"file_path": str(tree / "a")}, tree))
        self.assertIsNotNone(self.reason("Write", {"file_path": str(self.sb.service / "a")}, tree))
        write_human_mark(self.sb.store, "allow")
        target = self.sb.base / "permitted"
        self.issue(target)
        self.assertIsNone(self.reason("Write", {"file_path": str(target / "a")}, tree))

    def test_grant_file_cannot_be_edited_or_renamed_through_tools(self):
        for tool, data in (("Write", {"file_path": str(self.sb.store / ".git" /
                                                       "svod-write-grants.json")}),
                           ("Bash", {"command": "echo '[]' > .git/svod-write-grants.json"})):
            with self.subTest(tool=tool):
                self.assertIn("grant", self.reason(tool, data) or "")

    def test_shell_destinations_not_read_sources_and_compound_cwd(self):
        outside = self.sb.base / "outside"
        for command in (f"echo x > {outside}", f"printf x | tee {outside}",
                        f"cp notes.md {outside}", f"mv notes.md {outside}",
                        f"sed -i 's/a/b/' {outside}",
                        f"cd {self.sb.base} && echo x > outside",
                        f"sh -c 'echo x > {outside}'"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.reason("Bash", {"command": command}))
        self.assertIsNone(self.reason("Bash", {"command": f"cp {outside} notes.md"}))

    def test_unknown_dynamic_malformed_truncated_shell_is_refused(self):
        for command in ("python3 -c 'open(\"x\", \"w\")'", "echo x > $TARGET",
                        "echo x > 'unterminated", "echo " + "x " * 501,
                        "awk 'BEGIN {print 1 > \"/tmp/out\"}'", "git config key value"):
            with self.subTest(command=command[:80]):
                self.assertIsNotNone(self.reason("Bash", {"command": command}))

    def test_missing_targets_and_path_resolution_fail_closed(self):
        for tool, data in (("Write", {}), ("Edit", {"file_path": "\x00"}),
                           ("apply_patch", {"command": "*** Begin Patch\n*** End Patch"})):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.reason(tool, data))

    def test_symlinks_patches_expired_foreign_and_invalid_grants(self):
        outside = self.sb.base / "outside"
        outside.mkdir()
        link = self.sb.store / "escape"
        link.symlink_to(outside, target_is_directory=True)
        self.assertIsNotNone(self.reason("Write", {"file_path": str(link / "x")}))
        self.assertIsNotNone(self.reason("apply_patch", {"command":
            f"*** Begin Patch\n*** Update File: notes.md\n*** Move to: {outside}/x\n"
            "@@\n-a\n+b\n*** End Patch"}))
        write_human_mark(self.sb.store, "allow explicit roots")
        self.issue(outside, self.sb.base / "second")
        cwd = self.sb.store / fixtures.EXAMPLE
        data = {"file_path": str(outside / "x")}
        self.assertIsNone(self.reason("Write", data, cwd))
        state = self.sb.store / ".git" / "svod-write-grants.json"
        original = json.loads(state.read_text())
        for field, value in (("record", "foreign"), ("expires", "2000-01-01T00:00:00+00:00"),
                             ("paths", ["relative"]), ("expires", "invalid")):
            state.write_text(json.dumps([{**original[0], field: value}]))
            self.assertIsNotNone(self.reason("Write", data, cwd))
        state.write_text("broken")
        self.assertIsNotNone(self.reason("Write", data, cwd))

    def test_grant_never_overrides_remote_metadata_or_frozen_code(self):
        write_human_mark(self.sb.store, "allow")
        self.issue(self.sb.base)
        cwd = self.sb.store / fixtures.EXAMPLE
        prompt_hook({"cwd": str(self.sb.store), "prompt": "No remote effects."}, self.sb.store)
        self.assertIn("outside this machine", self.reason("Bash", {"command": "git push"}, cwd))
        for name in ("questions.md", "approval.yaml"):
            self.assertIsNotNone(self.reason("Write", {"file_path": str(cwd / name),
                                                       "content": "contract_approved: yes"}, cwd))

    def test_grant_protects_freeze_for_arbitrarily_named_declared_tree(self):
        tree = self.sb.base / "arbitrary"
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        self.sb.edit(f"{fixtures.EXAMPLE}/card.md", "services: []", "services: [app]")
        self.sb.git(self.sb.service, "worktree", "add", "-q", "-b", "freeze", str(tree))
        self.sb.write(f"{fixtures.EXAMPLE}/work.yaml", f"app: {tree}\n")
        self.issue(tree)
        self.assertIn("until its plan is approved", self.reason(
            "Write", {"file_path": str(tree / "x")}, tree))

    def test_protected_state_ancestors_and_unsupported_copy_boundaries(self):
        for command in ("rm -rf .git", "mv .git saved", "cp -r source .",
                        "echo x > ~/elsewhere", "echo x >&2"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.reason("Bash", {"command": command}))

    def test_shell_grant_allows_literal_destinations_and_checks_actual_copy_leaf(self):
        target = self.sb.base / "target"
        target.mkdir()
        write_human_mark(self.sb.store, "allow")
        self.issue(target)
        cwd = self.sb.store / fixtures.EXAMPLE
        for command in (f"echo x > {target}/a", f"printf x | tee -a {target}/a",
                        f"cp /outside/read-only {target}/a", f"mv a {target}/a",
                        f"sed -i.bak 's/a/b/' {target}/a", f"cd {target} && echo x > a",
                        f"sh -c 'echo x > {target}/a'"):
            with self.subTest(command=command):
                self.assertIsNone(self.reason("Bash", {"command": command}, cwd))
        (target / "source").symlink_to(self.sb.base / "escape")
        self.assertIsNotNone(self.reason("Bash", {"command": f"cp source {target}"}, cwd))

    def test_absent_ambiguous_and_stale_human_never_issue_grant(self):
        import datetime as dt
        target = str(self.sb.base / "target")
        args = ("--for", "30m", "--path", target)
        write_human_mark(self.sb.store, "allow", at=dt.datetime.now().astimezone()
                         - dt.timedelta(hours=1))
        self.assertNotEqual(self.sb.cli("allow", fixtures.EXAMPLE, *args).returncode, 0)
        write_human_mark(self.sb.store, "allow")
        self.assertNotEqual(self.sb.cli("allow", "not-found", *args).returncode, 0)
        card = (self.sb.store / fixtures.EXAMPLE / "card.md").read_text()
        self.sb.write("work/tasks/example-other/card.md", card)
        self.assertNotEqual(self.sb.cli("allow", "EXAMPLE-1", *args).returncode, 0)
        shared = self.sb.base / "shared"
        shared.mkdir()
        for record in (fixtures.EXAMPLE, "work/tasks/example-other"):
            self.sb.write(f"{record}/work.yaml", f"app: {shared}\n")
        self.assertIsNotNone(self.reason("Write", {"file_path": str(shared / "a")}, shared))

    def test_newlines_and_option_side_effects_cannot_hide_destinations(self):
        for command in (f"echo harmless\ncp notes.md {self.sb.base}/outside",
                        "cat <(python3 evil.py)", "rg --pre evil script",
                        "svod new /outside", "sed 's/x/y/w /outside' notes.md",
                        "cp --parents source .", "printf x | tee --output-error=exit /outside"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.reason("Bash", {"command": command}))

    def test_patch_deletion_and_moves_cannot_remove_approval_fields(self):
        cwd = self.sb.store / fixtures.EXAMPLE
        (cwd / "approval.yaml").write_text("contract_approved: yes\n")
        for text in ("*** Delete File: approval.yaml",
                     "*** Update File: approval.yaml\n*** Move to: ordinary.yaml\n@@\n x\n"):
            self.assertIsNotNone(self.reason("apply_patch", {"command":
                f"*** Begin Patch\n{text}\n*** End Patch"}, cwd))

    def test_direct_tool_variants_and_approved_patch_move(self):
        outside = self.sb.base / "outside"
        cwd = self.sb.store / fixtures.EXAMPLE
        for tool, field in (("Edit", "file_path"), ("MultiEdit", "file_path"),
                            ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.reason(tool, {field: str(outside)}, cwd))
        write_human_mark(self.sb.store, "allow")
        self.issue(outside)
        self.assertIsNone(self.reason("apply_patch", {"command":
            f"*** Begin Patch\n*** Update File: notes.md\n*** Move to: {outside}/x\n"
            "@@\n-a\n+b\n*** End Patch"}, cwd))

    def test_directory_removal_cannot_erase_guarded_record_metadata(self):
        self.assertIsNotNone(self.reason("Bash", {"command": f"rm -r {fixtures.EXAMPLE}"}))
