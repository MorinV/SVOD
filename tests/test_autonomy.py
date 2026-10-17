"""Autonomy levels of svod.yaml: which approval steps become optional, the status line."""
import tempfile
import unittest
from pathlib import Path

import task_example as te
from support import EXIT_OK, TempStore, core_text, make_profile

from svod import keys
from svod.config import AUTONOMY_LEVELS
from svod.errors import LoadError
from svod.loader import load_runtime

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
