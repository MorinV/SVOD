"""Services of the store and the gates over relations between works: children, references."""
import tempfile
import unittest
from pathlib import Path

from support import EXIT_OK, StoreTestCase, TempStore, core_lead, doc, make_profile

from svod import keys
from svod.config import load_config
from svod.context import Context
from svod.errors import LoadError, ParamError
from svod.gates import CORE_GATES, Status
from svod.loader import load_runtime

PASS, FAIL, UNKNOWN = Status.PASS, Status.FAIL, Status.UNKNOWN
HEAD = "work"
SUBJECT = "subject: {{ provider: container, params: {{ roots: [{root}], head_type: work }} }}"
TASKS = "work/tasks"
FEATURES = "work/features"
PROJECTS = "work/projects"
RESEARCH = "work/research"
PIPELINES = {
    "task.yaml": f"""
        pipeline: task
        {SUBJECT.format(root=TASKS)}
        done: {{ gate: field, params: {{ name: status, equals: done }}, text: w.done }}
        steps:
          - id: build
            text: w.step
            gates: [ {{ gate: exists }} ]
    """,
    "feature.yaml": f"""
        pipeline: feature
        {SUBJECT.format(root=FEATURES)}
        done: {{ gate: children_done, params: {{ pipelines: [task] }}, text: w.done }}
        steps:
          - id: split
            text: w.step
            gates: [ {{ gate: has_children, params: {{ pipelines: [task] }} }} ]
    """,
    "project.yaml": f"""
        pipeline: project
        {SUBJECT.format(root=PROJECTS)}
        done: {{ gate: children_done, params: {{ pipelines: [feature] }}, text: w.done }}
        steps:
          - id: plan
            text: w.step
            gates: [ {{ gate: has_children, params: {{ pipelines: [feature] }} }} ]
    """,
    "research.yaml": f"""
        pipeline: research
        {SUBJECT.format(root=RESEARCH)}
        steps:
          - id: ask
            text: w.step
            gates: [ {{ gate: questions_answered }} ]
          - id: lead
            text: w.step
            gates: [ {{ gate: ref_exists, params: {{ field: leads_to, pipelines: [feature] }} }} ]
    """,
}
LOCALE = """
    w:
      done: "done"
      step: "next"
"""


def work_profile(base):
    """Profile of tasks, features, projects and research kept as container works."""
    return make_profile(Path(base) / "profile", PIPELINES, LOCALE)


def write_work(sb, rel, **fields):
    """Work record directory with its head document."""
    sb.write(f"{rel}/{HEAD}.md", doc(HEAD, **fields))


class WorkStoreTestCase(StoreTestCase):
    """Store over the work profile, with its runtime and context."""

    def setUp(self):
        """Fresh store with the work profile."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store_kwargs = {"profile": work_profile(tmp.name)}
        super().setUp()

    def context(self):
        """Context with the pipelines loaded now."""
        runtime = load_runtime(self.sb.store)
        return Context(runtime.config, runtime.locale, pipelines=runtime.by_name())

    def subject(self, ctx, pipeline, rel):
        """Subject of the pipeline with the id."""
        return next(s for s in ctx.pipelines[pipeline].subject.impl.enumerate(ctx)
                    if s.id == rel)

    def run_gate(self, name, params, pipeline, rel, ctx=None):
        """Evaluate a core gate against the subject of the pipeline."""
        ctx = ctx or self.context()
        return CORE_GATES[name](params).evaluate(ctx, self.subject(ctx, pipeline, rel))


class ChildrenTest(WorkStoreTestCase):
    """has_children and children_done over the parent field."""

    def setUp(self):
        """A project with two features; login has two tasks, search none."""
        super().setUp()
        write_work(self.sb, f"{PROJECTS}/shop")
        write_work(self.sb, f"{FEATURES}/login", parent=f"{PROJECTS}/shop")
        write_work(self.sb, f"{FEATURES}/search", parent=f"{PROJECTS}/shop/")
        write_work(self.sb, f"{TASKS}/form", parent=f"{FEATURES}/login", status="done")
        write_work(self.sb, f"{TASKS}/token", parent=f"{FEATURES}/login")
        write_work(self.sb, f"{TASKS}/other", parent=f"{FEATURES}/elsewhere", status="done")

    def test_has_children(self):
        """PASS with at least one child; facts.total."""
        params = {"pipelines": ["task"]}
        login = self.run_gate("has_children", params, "feature", f"{FEATURES}/login")
        self.assertEqual((login.status, login.facts), (PASS, {"total": 2}))
        search = self.run_gate("has_children", params, "feature", f"{FEATURES}/search")
        self.assertEqual((search.status, search.facts), (FAIL, {"total": 0}))
        project = self.run_gate("has_children", {"pipelines": ["feature"]}, "project",
                                f"{PROJECTS}/shop")
        self.assertEqual(project.facts, {"total": 2})

    def test_children_done(self):
        """Every child done in its own pipeline; facts done, total, open and the reason."""
        params = {"pipelines": ["task"]}
        login = self.run_gate("children_done", params, "feature", f"{FEATURES}/login")
        self.assertEqual(login.status, FAIL)
        self.assertEqual(login.facts, {"done": 1, "total": 2, "open": f"{TASKS}/token",
                                       "reason": "open"})
        search = self.run_gate("children_done", params, "feature", f"{FEATURES}/search")
        self.assertEqual(search.facts, {"done": 0, "total": 0, "open": "", "reason": "none"})
        write_work(self.sb, f"{TASKS}/token", parent=f"{FEATURES}/login", status="done")
        login = self.run_gate("children_done", params, "feature", f"{FEATURES}/login")
        self.assertEqual((login.status, login.facts),
                         (PASS, {"done": 2, "total": 2, "open": ""}))

    def test_nested_positions(self):
        """A project is done when each feature is done, which asks the positions of its tasks."""
        params = {"pipelines": ["feature"]}
        shop = self.run_gate("children_done", params, "project", f"{PROJECTS}/shop")
        self.assertEqual(shop.facts["open"], f"{FEATURES}/login, {FEATURES}/search")
        write_work(self.sb, f"{TASKS}/token", parent=f"{FEATURES}/login", status="done")
        write_work(self.sb, f"{TASKS}/query", parent=f"{FEATURES}/search", status="done")
        shop = self.run_gate("children_done", params, "project", f"{PROJECTS}/shop")
        self.assertEqual((shop.status, shop.facts["done"]), (PASS, 2))

    def test_custom_field(self):
        """The field param names another relation, cause of a hotfix."""
        write_work(self.sb, f"{TASKS}/hotfix", cause=f"{TASKS}/form", status="done")
        result = self.run_gate("children_done", {"pipelines": ["task"], "field": "cause"},
                               "task", f"{TASKS}/form")
        self.assertEqual((result.status, result.facts["total"]), (PASS, 1))

    def test_cycle_is_unknown(self):
        """A child that leads back to the subject makes children_done UNKNOWN with the chain."""
        write_work(self.sb, f"{FEATURES}/a", parent=f"{FEATURES}/b")
        write_work(self.sb, f"{FEATURES}/b", parent=f"{FEATURES}/a")
        write_work(self.sb, f"{FEATURES}/self", parent=f"{FEATURES}/self")
        params = {"pipelines": ["feature"]}
        result = self.run_gate("children_done", params, "feature", f"{FEATURES}/a")
        self.assertEqual(result.status, UNKNOWN)
        self.assertEqual(result.reason,
                         f"cycle: {FEATURES}/a -> {FEATURES}/b -> {FEATURES}/a")
        own = self.run_gate("children_done", params, "feature", f"{FEATURES}/self")
        self.assertEqual(own.status, UNKNOWN)

    def test_unknown_pipeline(self):
        """A pipeline name the store does not load is UNKNOWN."""
        for name in ("children_done", "has_children"):
            with self.subTest(gate=name):
                result = self.run_gate(name, {"pipelines": ["nope"]}, "feature",
                                       f"{FEATURES}/login")
                self.assertEqual(result.status, UNKNOWN)
                self.assertIn("nope", result.reason)

    def test_status_and_validate(self):
        """The store validates and status shows the feature with the gates described."""
        out = self.sb.cli("validate")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn(core_lead(keys.VALIDATE_OK), out.stdout)
        status = self.sb.cli("status", f"{FEATURES}/search")
        self.assertEqual(status.returncode, EXIT_OK, status.stderr)
        self.assertIn("next", status.stdout)


class RefExistsTest(WorkStoreTestCase):
    """ref_exists: the field names an existing subject of the pipelines."""

    def test_reasons(self):
        """PASS with the pipeline, FAIL missing for an empty field, unknown for no subject."""
        write_work(self.sb, f"{FEATURES}/login")
        write_work(self.sb, f"{RESEARCH}/r1", leads_to=f"./{FEATURES}/login")
        write_work(self.sb, f"{RESEARCH}/r2")
        write_work(self.sb, f"{RESEARCH}/r3", leads_to=f"{FEATURES}/gone")
        params = {"field": "leads_to", "pipelines": ["feature"]}
        cases = (
            ("r1", PASS, {"value": f"{FEATURES}/login", "pipeline": "feature"}),
            ("r2", FAIL, {"value": "", "reason": "missing"}),
            ("r3", FAIL, {"value": f"{FEATURES}/gone", "reason": "unknown"}),
        )
        ctx = self.context()
        for name, status, facts in cases:
            with self.subTest(research=name):
                result = self.run_gate("ref_exists", params, "research", f"{RESEARCH}/{name}",
                                       ctx)
                self.assertEqual((result.status, result.facts), (status, facts))
        wrong = self.run_gate("ref_exists", {"field": "leads_to", "pipelines": ["task"]},
                              "research", f"{RESEARCH}/r1", ctx)
        self.assertEqual(wrong.facts["reason"], "unknown")


class RelationParamsTest(unittest.TestCase):
    """Bad params of the relation gates are rejected at construction."""

    def test_param_validation(self):
        """Pipelines is a non-empty list of names, field a string."""
        cases = (
            ("children_done", {}),
            ("children_done", {"pipelines": []}),
            ("children_done", {"pipelines": "task"}),
            ("children_done", {"pipelines": ["task"], "field": 1}),
            ("has_children", {"pipelines": [""]}),
            ("ref_exists", {"pipelines": ["task"]}),
            ("ref_exists", {"field": "parent"}),
            ("ref_exists", {"field": "parent", "pipelines": ["task"], "extra": 1}),
            ("questions_answered", {"file": 1}),
        )
        for name, params in cases:
            with self.subTest(gate=name, params=params), self.assertRaises(ParamError):
                CORE_GATES[name](params)


class ServicesConfigTest(unittest.TestCase):
    """services of svod.yaml: names to existing directories relative to the store root."""

    def store(self, services):
        """Temporary store whose svod.yaml declares the services as written."""
        sb = TempStore(services=services)
        self.addCleanup(sb.cleanup)
        (sb.parent / "app").mkdir()
        return sb

    def test_resolved(self):
        """Paths are resolved against the store root."""
        sb = self.store("{app: ../app}")
        config = load_config(sb.store)
        self.assertEqual(config.services, {"app": (sb.parent / "app").resolve()})
        self.assertEqual(load_config(self.store("{}").store).services, {})

    def test_errors(self):
        """A missing directory, an absolute path or a wrong type is a load error."""
        cases = (
            ("{app: ../app, api: ../api}", "services.api: service directory not found"),
            ("{app: /tmp}", "services.app must be relative"),
            ("{app: 1}", "services.app must be a non-empty string"),
            ("[app]", "services must be a mapping"),
        )
        for text, error in cases:
            with self.subTest(services=text):
                sb = self.store(text)
                with self.assertRaises(LoadError) as caught:
                    load_config(sb.store)
                self.assertIn(error, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
