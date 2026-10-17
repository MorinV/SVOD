"""Autonomy levels of svod.yaml: which approval steps become optional, the status line."""
import tempfile
import unittest
from pathlib import Path

import task_example as te
from support import EXIT_OK, TempStore, core_text, make_profile

from svod import keys
from svod.config import AUTONOMY_LEVELS
from svod.context import Context
from svod.errors import LoadError
from svod.loader import load_runtime, subject_level
from svod.position import freeze, position

PIPELINE_FILE = "toy.yaml"
PIPELINE = """
    pipeline: toy
    subject: { provider: container, params: { roots: [boxes] } }
    steps:
      - id: first
        text: toy.first
        gates: [ { gate: exists } ]
      - id: plan
        required: true
        blocks_code: true
        text: toy.plan
        gates:
          - { gate: approval, params: { marker: planned, file: meta.yaml }, purpose: contract }
      - id: accept
        required: true
        text: toy.accept
        gates:
          - { gate: approval, params: { marker: accepted, file: meta.yaml }, purpose: result }
"""
LOCALE = """
    toy:
      first: "first step"
      plan: "approve the plan"
      accept: "accept the result"
"""
DECLARED = {"first": (False, False, False), "plan": (False, True, True),
            "accept": (False, True, False)}
OPTIONAL = (True, False, False)


class AutonomyLoadTest(unittest.TestCase):
    """The level of a pipeline relaxes its approval steps as loaded, not the declaration."""

    def load(self, autonomy=None):
        """Runtime of a store around the toy profile, with the autonomy block when given."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        profile = make_profile(Path(tmp.name) / "profile", {PIPELINE_FILE: PIPELINE}, LOCALE)
        config = {"autonomy": autonomy} if autonomy is not None else {}
        sb = TempStore(profile=profile, **config)
        self.addCleanup(sb.cleanup)
        self.source = profile / "pipelines" / PIPELINE_FILE
        return load_runtime(sb.store)

    def flags(self, runtime):
        """(optional, required, blocks_code) of each step of the toy pipeline."""
        return {step.id: (step.optional, step.required, step.blocks_code)
                for step in runtime.pipeline("toy").steps}

    def test_levels(self):
        """guided keeps the declaration, supervised lifts the result, autonomous every approval."""
        cases = (
            ("no autonomy", None, DECLARED),
            ("guided", "{toy: guided}", DECLARED),
            ("supervised", "{toy: supervised}", {**DECLARED, "accept": OPTIONAL}),
            ("autonomous", "{toy: autonomous}", {**DECLARED, "plan": OPTIONAL,
                                                  "accept": OPTIONAL}),
            ("kind of work only", "{hotfix: autonomous}", DECLARED),
        )
        for name, autonomy, expected in cases:
            with self.subTest(case=name):
                runtime = self.load(autonomy)
                before = self.source.read_text()
                self.assertEqual(expected, self.flags(runtime))
                self.assertEqual(before, self.source.read_text())

    def test_config_values(self):
        """The levels reach the config as written."""
        runtime = self.load("{toy: supervised, hotfix: autonomous}")
        self.assertEqual({"toy": "supervised", "hotfix": "autonomous"},
                         runtime.config.autonomy)
        self.assertEqual(("guided", "supervised", "autonomous"), AUTONOMY_LEVELS)

    def test_errors(self):
        """An unknown level, an unknown pipeline or a non-mapping is a load error."""
        cases = (
            ("unknown level", "{toy: reckless}", "autonomy.toy must be one of"),
            ("unknown pipeline", "{ghost: guided}", "autonomy: unknown pipeline: ghost"),
            ("not a mapping", "[toy]", "autonomy must be a mapping"),
        )
        for name, autonomy, message in cases:
            with self.subTest(case=name):
                with self.assertRaises(LoadError) as ctx:
                    self.load(autonomy)
                self.assertIn(message, str(ctx.exception))


KIND_PIPELINE_FILE = "task.yaml"
KIND_PIPELINE = PIPELINE.replace("pipeline: toy", "pipeline: task").replace(
    "params: { roots: [boxes] }", "params: { roots: [work], head_type: card }")
CARD = "---\ntype: card\nkind: {kind}\n---\n# Card\n"
HOTFIX = "work/fix"
TASK = "work/feature"


class AutonomyKindTest(unittest.TestCase):
    """The level of the kind of work of a subject wins over that of its pipeline."""

    def load(self, autonomy):
        """Context and task pipeline of a store with a hotfix and a task card."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        profile = make_profile(Path(tmp.name) / "profile", {KIND_PIPELINE_FILE: KIND_PIPELINE},
                               LOCALE)
        sb = TempStore(profile=profile, autonomy=autonomy)
        self.addCleanup(sb.cleanup)
        sb.write(f"{HOTFIX}/card.md", CARD.format(kind="hotfix"))
        sb.write(f"{TASK}/card.md", CARD.format(kind="task"))
        runtime = load_runtime(sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        pipeline = runtime.pipeline("task")
        subjects = {s.id: s for s in pipeline.subject.impl.enumerate(ctx)}
        return ctx, pipeline, subjects

    def required(self, ctx, pipeline, subject):
        """(required steps, blocks_code steps, current step, frozen step) of the subject."""
        pos = position(ctx, pipeline, subject)
        frozen = freeze(ctx, pipeline, subject)
        return ([s.step.id for s in pos.steps if s.step.required],
                [s.step.id for s in pos.steps if s.step.blocks_code],
                pos.current.step.id if pos.current else None,
                frozen.step.id if frozen else None)

    def test_hotfix_level_wins(self):
        """A hotfix under {task: supervised, hotfix: autonomous} has no required approval
        step and no code freeze; a task keeps the contract approval and its freeze."""
        ctx, pipeline, subjects = self.load("{task: supervised, hotfix: autonomous}")
        self.assertEqual(([], [], None, None), self.required(ctx, pipeline, subjects[HOTFIX]))
        self.assertEqual((["plan"], ["plan"], "plan", "plan"),
                         self.required(ctx, pipeline, subjects[TASK]))
        self.assertEqual("autonomous", subject_level(ctx.config.autonomy, pipeline,
                                                     subjects[HOTFIX]))
        self.assertEqual("supervised", subject_level(ctx.config.autonomy, pipeline,
                                                     subjects[TASK]))

    def test_stricter_kind(self):
        """A stricter level of the kind restores the declared steps the pipeline relaxed."""
        ctx, pipeline, subjects = self.load("{task: autonomous, hotfix: guided}")
        self.assertEqual((["plan", "accept"], ["plan"], "plan", "plan"),
                         self.required(ctx, pipeline, subjects[HOTFIX]))
        self.assertEqual(([], [], None, None), self.required(ctx, pipeline, subjects[TASK]))

    def test_kind_without_level(self):
        """A kind of work autonomy does not name follows the level of the pipeline."""
        ctx, pipeline, subjects = self.load("{task: supervised}")
        self.assertEqual((["plan"], ["plan"], "plan", "plan"),
                         self.required(ctx, pipeline, subjects[HOTFIX]))


class AutonomyStatusTest(unittest.TestCase):
    """svod status names the level of the pipeline under the header, when one is set."""

    def setUp(self):
        """Example store with a proposed change."""
        self.sb = te.make_task_store()
        self.addCleanup(self.sb.cleanup)
        te.propose(self.sb)

    def test_status_line(self):
        """The line follows the header with the level set; without one it is absent."""
        line = core_text(keys.STATUS_AUTONOMY, level="supervised")
        out = self.sb.cli("status", te.KEY)
        self.assertEqual(EXIT_OK, out.returncode, out.stderr)
        self.assertNotIn(line, out.stdout)
        te.set_config(self.sb, autonomy="{task: supervised}")
        out = self.sb.cli("status", te.KEY)
        self.assertEqual(EXIT_OK, out.returncode, out.stderr)
        lines = out.stdout.splitlines()
        self.assertEqual(line, lines[1].strip(), out.stdout)


if __name__ == "__main__":
    unittest.main()
