"""The tree of works: children under their parents in active, the children block of status."""
import json
import tempfile
from pathlib import Path

from support import EXIT_OK, StoreTestCase, doc, make_profile

from svod import keys
from svod.active import summarize
from svod.context import Context
from svod.loader import load_runtime
from svod.pipeline import parse_pipeline
from svod.relations import children_of, declared_children, flatten, tree
from svod.render import INDENT

HEAD = "work"
SUBJECT = "subject: {{ provider: container, params: {{ roots: [{root}], head_type: work }} }}"
DONE = "done: { gate: field, params: { name: status, equals: done }, text: w.done }"
PROJECTS = "work/projects"
FEATURES = "work/features"
TASKS = "work/tasks"
EPICS = "work/epics"
PIPELINES = {
    "project.yaml": f"""
        pipeline: project
        {SUBJECT.format(root=PROJECTS)}
        active: {{ children: [feature] }}
        {DONE}
        steps:
          - id: plan
            text: w.plan
            gates: [ {{ gate: has_children, params: {{ pipelines: [feature] }} }} ]
    """,
    "feature.yaml": f"""
        pipeline: feature
        {SUBJECT.format(root=FEATURES)}
        active: {{ children: [task] }}
        {DONE}
        steps:
          - id: split
            text: w.split
            gates: [ {{ gate: has_children, params: {{ pipelines: [task] }} }} ]
          - id: finish
            text: w.finish
            gates: [ {{ gate: children_done, params: {{ pipelines: [task] }} }} ]
    """,
    "task.yaml": f"""
        pipeline: task
        {SUBJECT.format(root=TASKS)}
        active: {{ item: w.task_item, children: [task] }}
        {DONE}
        steps:
          - id: build
            text: w.build
            gates: [ {{ gate: field, params: {{ name: built, present: true }} }} ]
          - id: check
            text: w.check
            gates: [ {{ gate: field, params: {{ name: checked, present: true }} }} ]
    """,
    "epic.yaml": f"""
        pipeline: epic
        {SUBJECT.format(root=EPICS)}
        steps:
          - id: gather
            text: w.gather
            gates:
              - {{ gate: has_children, params: {{ pipelines: [task], field: epic }} }}
              - {{ gate: children_done, params: {{ pipelines: [feature, task], field: epic }} }}
    """,
}
LOCALE = """
    w:
      done: "done"
      plan: "plan"
      split: "split"
      finish: "finish"
      build: "build"
      check: "check"
      gather: "gather"
      task_item: "- task {id}: {step}"
"""
ORDER = "active_order: [project, feature, task]\n"


def write_work(sb, rel, **fields):
    """Work record directory with its head document."""
    sb.write(f"{rel}/{HEAD}.md", doc(HEAD, **fields))


class TreeTestCase(StoreTestCase):
    """Store of projects, features, tasks and epics kept as container works."""

    def setUp(self):
        """Fresh store with the tree profile and the active order."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store_kwargs = {"profile": make_profile(Path(tmp.name) / "profile", PIPELINES,
                                                     LOCALE)}
        super().setUp()
        config = self.sb.store / "svod.yaml"
        config.write_text(config.read_text(encoding="utf-8") + ORDER, encoding="utf-8")
        self.runtime = None

    def context(self):
        """Context with the pipelines loaded now."""
        self.runtime = load_runtime(self.sb.store)
        return Context(self.runtime.config, self.runtime.locale,
                       pipelines=self.runtime.by_name())

    def text(self, key, **facts):
        """Text of a key in the loaded locale."""
        return self.runtime.locale.text(key, **facts)

    def item(self, rel, step, depth=0, task=False):
        """Summary line of a subject at the depth under its top parent."""
        key = "w.task_item" if task else keys.ACTIVE_ITEM
        facts = {"id": rel, "keys": self.text(keys.ACTIVE_NO_KEYS), "step": step}
        return INDENT * (depth + 1) + self.text(key, **facts)

    def summary(self):
        """Lines of the summary over the loaded pipelines, after the identity warning."""
        ctx = self.context()
        lines = summarize(ctx, self.runtime.pipelines)
        self.assertEqual(lines[:2], [self.text(keys.ACTIVE_NO_IDENTITY), ""])
        return lines[2:]


class ActiveTreeTest(TreeTestCase):
    """Three levels under a project, orphans in their groups, done parents and cycles."""

    def setUp(self):
        """A project with two features, tasks and subtasks, an orphan, a cycle and a done one."""
        super().setUp()
        write_work(self.sb, f"{PROJECTS}/shop")
        write_work(self.sb, f"{FEATURES}/login", parent=f"{PROJECTS}/shop")
        write_work(self.sb, f"{FEATURES}/search", parent=f"{PROJECTS}/shop/")
        write_work(self.sb, f"{TASKS}/form", parent=f"{FEATURES}/login", status="done")
        write_work(self.sb, f"{TASKS}/token", parent=f"{FEATURES}/login", built="yes")
        write_work(self.sb, f"{TASKS}/token-sub", parent=f"{TASKS}/token")
        write_work(self.sb, f"{TASKS}/loose")
        write_work(self.sb, f"{TASKS}/ring-a", parent=f"{TASKS}/ring-b")
        write_work(self.sb, f"{TASKS}/ring-b", parent=f"{TASKS}/ring-a")
        write_work(self.sb, f"{TASKS}/ring-leaf", parent=f"{TASKS}/ring-a")
        write_work(self.sb, f"{PROJECTS}/old", status="done")
        write_work(self.sb, f"{FEATURES}/left", parent=f"{PROJECTS}/old")

    def test_three_levels_under_the_parent(self):
        """Children follow their parent with an indent per level and leave their own groups."""
        lines = self.summary()
        idle = self.text(keys.ACTIVE_MINE_IDLE)
        self.assertEqual(lines, [
            idle,
            self.item(f"{PROJECTS}/shop", ""),
            self.item(f"{FEATURES}/login", self.text("w.finish"), 1),
            self.item(f"{TASKS}/token", self.text("w.check"), 2, task=True),
            self.item(f"{TASKS}/token-sub", self.text("w.build"), 3, task=True),
            self.item(f"{FEATURES}/search", self.text("w.split"), 1),
            "",
            idle,
            self.item(f"{FEATURES}/left", self.text("w.split")),
            "",
            idle,
            self.item(f"{TASKS}/loose", self.text("w.build"), task=True),
            self.item(f"{TASKS}/ring-a", self.text("w.build"), task=True),
            self.item(f"{TASKS}/ring-leaf", self.text("w.build"), 1, task=True),
            self.item(f"{TASKS}/ring-b", self.text("w.build"), task=True),
        ])

    def test_tree_and_children_of(self):
        """tree() follows active.children at any depth; children_of keeps the declared order."""
        ctx = self.context()
        project = self.runtime.pipeline("project")
        shop = next(s for s in project.subject.impl.enumerate(ctx)
                    if s.id == f"{PROJECTS}/shop")
        nodes = tree(ctx, self.runtime.pipelines, project, shop)
        self.assertEqual([(depth, node.subject.id) for depth, node in flatten(nodes)], [
            (0, f"{FEATURES}/login"), (1, f"{TASKS}/form"), (1, f"{TASKS}/token"),
            (2, f"{TASKS}/token-sub"), (0, f"{FEATURES}/search")])
        found = children_of(ctx, self.runtime.pipelines, shop, ["missing", "feature"])
        self.assertEqual([(p.name, s.id) for p, s in found],
                         [("feature", f"{FEATURES}/login"), ("feature", f"{FEATURES}/search")])

    def test_cycle_stops(self):
        """A cycle of references places every subject once."""
        ctx = self.context()
        task = self.runtime.pipeline("task")
        ring = next(s for s in task.subject.impl.enumerate(ctx) if s.id == f"{TASKS}/ring-a")
        nodes = tree(ctx, self.runtime.pipelines, task, ring)
        self.assertEqual([node.subject.id for _, node in flatten(nodes)],
                         [f"{TASKS}/ring-b", f"{TASKS}/ring-leaf"])


class StatusChildrenTest(TreeTestCase):
    """The children block of status and the children of the JSON position."""

    def setUp(self):
        """A feature with a done and an open task, an epic over tasks by its own field."""
        super().setUp()
        write_work(self.sb, f"{FEATURES}/login")
        write_work(self.sb, f"{TASKS}/form", parent=f"{FEATURES}/login", status="done",
                   epic=f"{EPICS}/big")
        write_work(self.sb, f"{TASKS}/token", parent=f"{FEATURES}/login", built="yes")
        write_work(self.sb, f"{TASKS}/lone", epic=f"{EPICS}/big", built="yes", checked="yes")
        write_work(self.sb, f"{EPICS}/big")
        write_work(self.sb, f"{EPICS}/empty")

    def test_children_block(self):
        """After the marks: a heading and a line per child, done or its current step."""
        self.context()
        out = self.sb.cli("status", f"{FEATURES}/login")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        lines = out.stdout.splitlines()
        start = lines.index(INDENT + self.text(keys.STATUS_CHILDREN))
        facts = {"pipeline": "task"}
        self.assertEqual(lines[start + 1:start + 3], [
            INDENT * 2 + self.text(keys.STATUS_CHILD_DONE, id=f"{TASKS}/form", **facts),
            INDENT * 2 + self.text(keys.STATUS_CHILD, id=f"{TASKS}/token", step="check",
                                   **facts),
        ])
        self.assertEqual(lines[start + 3], "")

    def test_children_by_gates(self):
        """Without active.children the relation gates name the pipelines and the field."""
        self.context()
        epic = self.runtime.pipeline("epic")
        self.assertEqual(declared_children(epic), [("task", "epic"), ("feature", "epic")])
        out = self.sb.cli("status", f"{EPICS}/big")
        self.assertIn(INDENT * 2 + self.text(keys.STATUS_CHILD_OPEN, id=f"{TASKS}/lone",
                                             pipeline="task"), out.stdout)
        self.assertIn(INDENT * 2 + self.text(keys.STATUS_CHILD_DONE, id=f"{TASKS}/form",
                                             pipeline="task"), out.stdout)
        empty = self.sb.cli("status", f"{EPICS}/empty")
        self.assertNotIn(self.text(keys.STATUS_CHILDREN), empty.stdout)
        task = self.sb.cli("status", f"{TASKS}/token")
        self.assertNotIn(self.text(keys.STATUS_CHILDREN), task.stdout)

    def test_no_declaration_no_block(self):
        """A pipeline naming no children in active nor in relation gates lists none."""
        pipeline, errors = parse_pipeline({
            "pipeline": "plain", "subject": {"provider": "container"},
            "steps": [{"id": "one", "text": "w.one", "gates": [{"gate": "exists"}]}]},
            "plain.yaml")
        self.assertEqual(errors, [])
        self.assertEqual(declared_children(pipeline), [])

    def test_bad_children_declaration(self):
        """active.children is a list of pipeline names."""
        _, errors = parse_pipeline({
            "pipeline": "plain", "subject": {"provider": "container"},
            "active": {"children": ["task", 3]},
            "steps": [{"id": "one", "text": "w.one", "gates": [{"gate": "exists"}]}]},
            "plain.yaml")
        self.assertEqual(len(errors), 1)
        self.assertIn("children", errors[0])

    def test_json_children(self):
        """The JSON position carries id, pipeline, current step and done of every child."""
        out = self.sb.cli("status", f"{FEATURES}/login", "--format", "json")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(data["positions"][0]["children"], [
            {"id": f"{TASKS}/form", "pipeline": "task", "current": None, "done": True},
            {"id": f"{TASKS}/token", "pipeline": "task", "current": "check", "done": False},
        ])
        lone = json.loads(self.sb.cli("status", f"{TASKS}/lone", "--format", "json").stdout)
        self.assertEqual(lone["positions"][0]["children"], [])
