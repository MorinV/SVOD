"""Nested provider discovery, placement and exact record identities."""

import unittest
from tempfile import TemporaryDirectory

import test_standard_template as fixtures
from support import doc

from svod.config import load_config
from svod.context import Context
from svod.providers.container import ContainerProvider


class NestedLayoutTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = fixtures.StandardStore(temp.name)

    def test_glob_roots_expand_owners_without_duplicates(self):
        paths = ["work/projects/a/tasks/same", "work/projects/b/tasks/same"]
        for path in paths:
            self.sb.write(f"{path}/card.md", doc("card", kind="task"))
        ctx = Context(load_config(self.sb.store))
        provider = ContainerProvider({"roots": ["work/projects/*/tasks", "work/projects/a/tasks"]})
        self.assertEqual([s.id for s in provider.enumerate(ctx)], paths)
        self.assertEqual([s.id for s in provider.match_exact("same", ctx)], paths)
        self.assertEqual([s.id for s in provider.match_exact(paths[1], ctx)], [paths[1]])
        plain = ContainerProvider({"roots": ["work/projects"]})
        self.assertEqual(
            [s.id for s in plain.enumerate(ctx)], ["work/projects/a", "work/projects/b"]
        )

    def test_creation_uses_parent_owner_and_keeps_research_as_provenance(self):
        for pipeline, name, parent, expected in (
            ("project", "p", "", "work/projects/p"),
            ("feature", "f", "work/projects/p", "work/projects/p/features/f"),
            (
                "research",
                "r",
                "work/projects/p/features/f",
                "work/projects/p/features/f/research/r",
            ),
            (
                "task",
                "t",
                "work/projects/p/features/f/research/r",
                "work/projects/p/features/f/tasks/t",
            ),
            (
                "research",
                "r2",
                "work/projects/p/features/f/research/r",
                "work/projects/p/features/f/research/r2",
            ),
            ("task", "solo", "", "work/headless/tasks/solo"),
        ):
            with self.subTest(expected=expected):
                made = self.sb.cli("record", "new", pipeline, name, "--parent", parent)
                self.assertEqual(made.returncode, 0, made.stderr)
                self.assertTrue((self.sb.store / expected / "card.md").is_file(), made.stdout)
        from svod.frontmatter import read_frontmatter

        self.assertEqual(
            read_frontmatter(self.sb.store / "work/projects/p/features/f/tasks/t/card.md")[
                "parent"
            ],
            "work/projects/p/features/f/research/r",
        )

    def test_all_owner_levels_hotfix_and_ambiguous_names(self):
        cases = [
            ("project", "p", "", "work/projects/p", ""),
            ("feature", "f", "", "work/features/f", ""),
            ("feature", "f", "work/projects/p", "work/projects/p/features/f", ""),
            ("task", "same", "work/projects/p", "work/projects/p/tasks/same", ""),
            ("task", "same", "work/features/f", "work/features/f/tasks/same", ""),
            (
                "task",
                "same",
                "work/projects/p/features/f",
                "work/projects/p/features/f/tasks/same",
                "",
            ),
            ("research", "r", "work/projects/p", "work/projects/p/research/r", ""),
            ("research", "r", "work/features/f", "work/features/f/research/r", ""),
            ("research", "r", "", "work/headless/research/r", ""),
            ("task", "h", "work/projects/p", "work/hotfix/h", "hotfix"),
        ]
        for pipeline, name, parent, expected, kind in cases:
            made = self.sb.cli("record", "new", pipeline, name, "--parent", parent, "--kind", kind)
            self.assertEqual(made.returncode, 0, made.stderr)
            self.assertTrue((self.sb.store / expected / "card.md").is_file(), made.stdout)
            self.assertEqual(self.sb.cli("status", expected).returncode, 0)
        self.assertNotEqual(self.sb.cli("status", "same").returncode, 0)
        bad = self.sb.cli("record", "new", "task", "bad", "--parent", "f")
        self.assertEqual(bad.returncode, 2, bad.stderr)
        self.assertIn("Parent", bad.stderr)
        for options in (
            ("--parent", "missing"),
            ("--kind", "feature"),
            ("--parent", "work/projects/p/tasks/same"),
        ):
            bad = self.sb.cli("record", "new", "task", "bad", *options)
            self.assertEqual(bad.returncode, 2, bad.stderr)
        active = self.sb.cli("active")
        self.assertEqual(active.returncode, 0, active.stderr)
        for path in [row[3] for row in cases if row[0] == "task"]:
            self.assertIn(path, active.stdout)

    def test_new_worktrees_are_collision_free_and_reversible_with_plus_names(self):
        from svod.loader import load_runtime

        for owner in ("a", "b", "a+b"):
            self.assertEqual(self.sb.cli("record", "new", "feature", owner).returncode, 0)
            record = f"work/features/{owner}/tasks/same+name"
            self.assertEqual(
                self.sb.cli(
                    "record",
                    "new",
                    "task",
                    "same+name",
                    "--parent",
                    f"work/features/{owner}",
                    "--kind",
                    "task",
                ).returncode,
                0,
            )
            self.sb.edit(f"{record}/card.md", "services: []", "services: [app]")
            # A synthetic approved fixture is not needed to exercise an archived record's action.
            self.sb.edit(f"{record}/card.md", "status: open", "status: archived")
            started = self.sb.action("start-task.sh", record)
            self.assertEqual(started.returncode, 0, started.stderr)
            runtime = load_runtime(self.sb.store)
            ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
            provider = runtime.pipeline("task").subject.impl
            subject = provider.match_exact(record, ctx)[0]
            pairs, errors = runtime.workspace_gate.worktrees(ctx, {record})
            self.assertEqual(errors, [])
            self.assertEqual(len(pairs), 1)
            tree = pairs[0][0]
            gate = runtime.pipeline("task").subject.key_impl
            self.assertIn(record, gate.find(tree.name))
            found = provider.match_key(gate.match(tree.name), ctx)
            self.assertEqual([s.id for s in found], [subject.id])
            again = self.sb.action("start-task.sh", record)
            self.assertEqual(again.returncode, 0, again.stderr)
        trees = self.sb.git(self.sb.service, "worktree", "list", "--porcelain")
        self.assertEqual(trees.count("worktree "), 4)

    def test_nested_cwd_selects_leaf_and_checkout_changes_do_not_select_owner(self):
        from svod.hooks.guard import Guard
        from svod.hooks.protocol import Event
        from svod.loader import load_runtime

        self.assertEqual(self.sb.cli("record", "new", "project", "p").returncode, 0)
        self.assertEqual(
            self.sb.cli("record", "new", "feature", "f", "--parent", "work/projects/p").returncode,
            0,
        )
        leaf = "work/projects/p/features/f/tasks/t"
        self.assertEqual(
            self.sb.cli(
                "record", "new", "task", "t", "--parent", "work/projects/p/features/f"
            ).returncode,
            0,
        )
        guard = Guard(self.sb.store)
        guard.select_scope(Event(cwd=str(self.sb.store / leaf)))
        self.assertIsNotNone(guard.selected)
        self.assertEqual(guard.selected.id, leaf)
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        changed = {f"{leaf}/card.md"}
        for name in ("project", "feature"):
            provider = runtime.pipeline(name).subject.impl
            self.assertEqual(provider.touched(ctx, changed), [], name)
            owner = provider.enumerate(ctx)[0]
            from svod.resolve import changed_in

            self.assertFalse(changed_in(ctx, runtime.pipeline(name), owner, changed))
        self.assertEqual(
            [s.id for s in runtime.pipeline("task").subject.impl.touched(ctx, changed)], [leaf]
        )

    def test_creation_rejects_symlink_roots_and_destinations_before_writes(self):
        outside = self.sb.base / "outside"
        outside.mkdir()
        destination = self.sb.store / "work/headless/tasks/escape"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(outside, target_is_directory=True)
        made = self.sb.cli("record", "new", "task", "escape")
        self.assertEqual(made.returncode, 2, made.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.sb.cli("record", "new", "feature", "f").returncode, 0)
        (self.sb.store / "work/features/f/tasks").symlink_to(outside, target_is_directory=True)
        made = self.sb.cli("record", "new", "task", "escape2", "--parent", "work/features/f")
        self.assertEqual(made.returncode, 2, made.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        made = self.sb.cli("record", "new", "task", "../outside")
        self.assertEqual(made.returncode, 2, made.stderr)

    def test_custom_work_provider_keeps_plain_root_creation(self):
        from svod.loader import load_runtime
        from svod.records import NewRecord

        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        provider_type = type(runtime.pipeline("task").subject.impl)
        provider = provider_type({"roots": ["custom/tasks"]})
        record = NewRecord("task", "legacy", parent="external-parent", kind="anything")
        self.assertEqual(
            provider.creation_target(ctx, record), self.sb.store / "custom/tasks/legacy"
        )

    def test_existing_work_yaml_names_survive_relocation_and_keep_freeze(self):
        from svod.hooks.events import pre_tool
        from svod.loader import load_runtime

        record = "work/features/f/tasks/t"
        self.assertEqual(self.sb.cli("record", "new", "feature", "f").returncode, 0)
        self.assertEqual(
            self.sb.cli(
                "record", "new", "task", "t", "--parent", "work/features/f", "--services", "app"
            ).returncode,
            0,
        )
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        tree = self.sb.base / "app-task-old-name"
        self.sb.git(self.sb.service, "worktree", "add", "-q", "-b", "task/old-name", str(tree))
        self.sb.write(f"{record}/work.yaml", "app: ../app-task-old-name\n")
        event = {
            "cwd": str(tree),
            "tool_name": "Write",
            "tool_input": {"file_path": str(tree / "code.py"), "content": "x"},
        }
        self.assertIsNotNone(pre_tool(event, self.sb.store))
        self.sb.edit(f"{record}/card.md", "status: open", "status: archived")
        started = self.sb.action("start-task.sh", record)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(self.sb.git(tree, "branch", "--show-current").strip(), "task/old-name")
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        self.assertEqual(
            runtime.workspace_gate.worktrees(ctx, {record})[0], [(tree.resolve(), "app")]
        )
        self.assertEqual(
            self.sb.git(self.sb.service, "worktree", "list", "--porcelain").count("worktree "), 2
        )

    def test_missing_nested_card_is_created_at_requested_owner(self):
        from support import child_env

        self.assertEqual(self.sb.cli("record", "new", "feature", "f").returncode, 0)
        record = "work/features/f/tasks/new"
        made = self.sb.action(
            "start-task.sh",
            record,
            SVOD_SERVICES="app",
            **{"PYTHONPATH": child_env()["PYTHONPATH"]},
        )
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertTrue((self.sb.store / record / "card.md").is_file())

    def test_shared_worktree_does_not_select_one_of_two_records(self):
        from svod.hooks.guard import Guard

        for name in ("one", "two"):
            self.assertEqual(
                self.sb.cli("record", "new", "task", name, "--services", "app").returncode, 0
            )
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        tree = self.sb.base / "shared"
        self.sb.git(self.sb.service, "worktree", "add", "-q", "-b", "shared", str(tree))
        for name in ("one", "two"):
            self.sb.write(f"work/headless/tasks/{name}/work.yaml", "app: ../shared\n")
        guard = Guard(self.sb.store)
        guard.select_scope({"cwd": str(tree)})
        self.assertIsNone(guard.selected)
        self.assertEqual(guard.write_roots, [])

    def test_research_task_and_research_outcomes_are_work_not_feature(self):
        from svod.loader import load_runtime

        record = "work/headless/research/r"
        self.assertEqual(self.sb.cli("record", "new", "research", "r").returncode, 0)
        for outcome, expected in (
            ("task", True),
            ("research", True),
            ("hotfix", True),
            ("feature", False),
            ("knowledge", False),
        ):
            self.sb.write(f"{record}/card.md", doc("card", kind="research", outcome=outcome))
            runtime = load_runtime(self.sb.store)
            ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
            subject = runtime.pipeline("research").subject.impl.match_exact(record, ctx)[0]
            self.assertEqual(subject.attrs["to_work"], expected, outcome)

    def test_nested_same_names_are_independently_frozen_until_own_approval(self):
        from svod.hooks.events import pre_tool

        self.assertEqual(self.sb.cli("init", "--login", "tester").returncode, 0)
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../app\n# services:")
        for owner in ("a", "b"):
            self.assertEqual(self.sb.cli("record", "new", "feature", owner).returncode, 0)
            record = f"work/features/{owner}/tasks/same"
            self.assertEqual(
                self.sb.cli(
                    "record",
                    "new",
                    "task",
                    "same",
                    "--parent",
                    f"work/features/{owner}",
                    "--services",
                    "app",
                ).returncode,
                0,
            )
            self.sb.write(f"{record}/contract.md", "# Fixture contract\n")
            self.assertEqual(self.sb.cli("ask", record, "--none").returncode, 0)
            approved = self.sb.approve(record, "approve")
            self.assertEqual(approved.returncode, 0, approved.stderr)
            started = self.sb.action("start-task.sh", record)
            self.assertEqual(started.returncode, 0, started.stderr)
        # Revoke only B's consent by changing an approval-bound document.
        self.sb.write("work/features/b/tasks/same/contract.md", "# Changed fixture contract\n")
        for owner, frozen in (("a", False), ("b", True)):
            tree = self.sb.base / f"app-task-work+features+{owner}+tasks+same"
            event = {
                "cwd": str(tree),
                "tool_name": "Write",
                "tool_input": {"file_path": str(tree / "code.py"), "content": "x"},
            }
            self.assertEqual(pre_tool(event, self.sb.store) is not None, frozen, owner)

    def test_enclosing_declared_worktree_is_not_discarded_for_nested_cwd(self):
        import shutil
        from svod.hooks.guard import Guard

        self.assertEqual(
            self.sb.cli("record", "new", "feature", "f", "--services", "app").returncode, 0
        )
        self.assertEqual(
            self.sb.cli("record", "new", "task", "t", "--parent", "work/features/f").returncode, 0
        )
        tree = self.sb.base / "service-worktree"
        self.sb.git(self.sb.service, "worktree", "add", "-q", "-b", "shared", str(tree))
        shutil.move(str(self.sb.store), tree / "store")
        self.sb.store = tree / "store"
        self.sb.edit("svod.yaml", "# services:", "services:\n  app: ../../app\n# services:")
        self.sb.write("work/features/f/work.yaml", "app: ..\n")
        guard = Guard(self.sb.store)
        guard.select_scope({"cwd": str(self.sb.store / "work/features/f/tasks/t")})
        self.assertIsNone(guard.selected)
        self.assertEqual(guard.write_roots, [])


if __name__ == "__main__":
    unittest.main()
