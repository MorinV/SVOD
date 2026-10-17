"""Documentation blocks rendered from pipeline declarations: content, write and staleness."""
import tempfile
import unittest
from pathlib import Path

from support import (EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, StoreTestCase, TempStore, core_text,
                     make_profile)

from svod import keys
from svod.context import Context
from svod.document import MARKER_BEGIN, RENDER_COMMAND, block
from svod.errors import LoadError
from svod.gates import CORE_GATES
from svod.loader import load_runtime

BEGIN = "<!-- pipeline:task:begin -->"
END = "<!-- pipeline:task:end -->"
BEFORE = "# Guide\n\nProse before.\n\n"
AFTER = "\nProse after.\n"
DOC = "docs/guide.md"
EXCLUDED = "skills/tool/guide.md"
HIDDEN = ".hidden/guide.md"
TASK_ROWS = (
    "| entry | the container holds a document of type design, if the task is in a container "
    "(block); the container holds a document of type test-strategy, if the task is in a "
    "container (warning) | - | Warning: the container has no design document, write it first.; "
    "Warning: the container has no test pyramid. |",
    "| propose | the subject exists | - | propose a change |",
    "| specification (required) | spec (...); design | - | write the delta spec; write design.md |",
    "| approve (required), code frozen until passed | approved | - | get the plan approved |",
    "| review | no gate: the last mile outside the store, never passes | - | open a pull request |",
    "| done | archived | - | when passed: task closed |",
)
FLOW_LINES = (
    "flowchart LR",
    '  entry{{"entry<br/>• the container holds a document of type design, if the task is in a '
    'container (block)<br/>• the container holds a document of type test-strategy, if the task '
    'is in a container (warning)"}}',
    '  s1["specification"]',
    '  s2["approve<br/>code frozen until passed"]',
    '  done(["done<br/>task closed"])',
    "  entry --> s0 --> s1 --> s2 --> s3 --> s4 --> s5 --> done",
    "  class s1 required",
    "  class s2 required_frozen",
)


def marked(body=""):
    """Document text with an empty or given task block between prose."""
    return f"{BEFORE}{BEGIN}\n{body}{END}\n{AFTER}"


class RenderTest(StoreTestCase):
    """Block content and the render command on the test profile."""

    store_kwargs = {"render_exclude": "[skills]"}

    def setUp(self):
        """Loaded runtime of the test store."""
        super().setUp()
        self.runtime = load_runtime(self.sb.store)
        self.ctx = Context(self.runtime.config, self.runtime.locale)

    def lines(self, name):
        """Rendered block lines of a pipeline."""
        return block(self.ctx, self.runtime.pipeline(name))

    def test_block_content(self):
        """Markers, generated note, flowchart with styles, legend and step table."""
        lines = self.lines("task")
        self.assertEqual((lines[0], lines[-1]), (BEGIN, END))
        for token in ("pipelines/task.yaml", RENDER_COMMAND.format(name="task")):
            with self.subTest(token=token):
                self.assertIn(token, lines[1])
        for line in FLOW_LINES + TASK_ROWS:
            with self.subTest(line=line):
                self.assertIn(line, lines)
        self.assertIn("  class s1 optional", self.lines("project"))
        self.assertIn("| review | review ... | - | decide whether to continue |", self.lines("note"))

    def test_print_and_unknown(self):
        """Without --write the block goes to stdout; an unknown pipeline is a usage error."""
        out = self.sb.cli("render", "task")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(out.stdout.rstrip("\n").split("\n"), self.lines("task"))
        unknown = self.sb.cli("render", "ghost")
        self.assertEqual(unknown.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.RENDER_UNKNOWN, name="ghost"), unknown.stderr)

    def test_write(self):
        """--write replaces the content between markers only, skipping excluded and hidden trees."""
        for rel in (DOC, EXCLUDED, HIDDEN):
            self.sb.write(rel, marked("stale\n"))
        out = self.sb.cli("render", "task", "--write")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(out.stdout, core_text(keys.RENDER_WRITTEN, path=DOC) + "\n")
        body = "\n".join(self.lines("task")[1:-1]) + "\n"
        self.assertEqual((self.sb.store / DOC).read_text(encoding="utf-8"), marked(body))
        for rel in (EXCLUDED, HIDDEN):
            with self.subTest(rel=rel):
                self.assertEqual((self.sb.store / rel).read_text(encoding="utf-8"),
                                 marked("stale\n"))
        again = self.sb.cli("render", "task", "--write")
        self.assertEqual(again.stdout, core_text(keys.RENDER_CURRENT, path=DOC) + "\n")
        none = self.sb.cli("render", "note", "--write")
        self.assertEqual(none.returncode, EXIT_FINDINGS)
        self.assertIn(MARKER_BEGIN.format(name="note"), none.stderr)


class DescribeTest(unittest.TestCase):
    """Gate descriptions from the core locale and their validation."""

    def test_core_descriptions(self):
        """Each core gate describes its params in words."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        locale = load_runtime(sb.store).locale
        cases = (
            ("exists", {}, "the subject exists"),
            ("archived", {}, "archived"),
            ("artifact", {"path": "design.md"}, "design.md exists"),
            ("artifact", {"glob": "specs/*.md", "min": 2}, "at least 2 of specs/*.md"),
            ("approval", {"marker": "ok", "file": "meta.yaml"}, "ok is set in meta.yaml"),
            ("field", {"name": "status", "equals": "active"}, "status is active"),
            ("field", {"name": "status", "not_equals": "active"},
             "status is set and is not active"),
            ("field", {"name": "outcome", "present": True}, "outcome is filled in"),
            ("field", {"name": "outcome", "present": False}, "outcome is empty"),
            ("field", {"name": "review", "date_not_past": True},
             "review is a date not in the past"),
            ("field", {"name": "review", "date_not_past": False}, "review is a date in the past"),
            ("doc_type", {"type": "design"}, "a document of type design"),
            ("doc_type", {"type": "design", "scope": "container"},
             "the container holds a document of type design"),
            ("git_pushed", {}, "the store has no commits ahead of origin"),
            ("git_pushed", {"repo": "svc"}, "svc has no commits ahead of origin"),
        )
        for name, params, text in cases:
            with self.subTest(gate=name, params=params):
                self.assertEqual(CORE_GATES[name](params).describe(params, locale), text)

    def test_missing_description_fails_the_load(self):
        """A label-less use of a profile gate needs gate.<name> in the locale."""
        pipeline = """
            pipeline: toy
            subject: { provider: container, params: { roots: [boxes] } }
            steps:
              - id: first
                text: toy.first
                gates: [ { gate: shiny } ]
        """
        gate = """
            from svod.gates import Gate, verdict

            class Shiny(Gate):
                name = "shiny"

                def evaluate(self, ctx, subject):
                    return verdict(True)

            GATES = {"shiny": Shiny}
        """
        cases = (('toy:\n  first: "first"\n', "missing locale key: gate.shiny"),
                 ('toy:\n  first: "first"\ngate:\n  shiny: "it shines"\n', None))
        for locale_text, error in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                profile = make_profile(Path(tmp) / "p", {"toy.yaml": pipeline}, locale_text,
                                       gates={"shiny.py": gate})
                sb = TempStore(profile=profile)
                self.addCleanup(sb.cleanup)
                if error is None:
                    runtime = load_runtime(sb.store)
                    ref = runtime.pipelines[0].steps[0].gates[0]
                    self.assertEqual(ref.impl.describe(ref.params, runtime.locale), "it shines")
                    continue
                with self.assertRaises(LoadError) as ctx:
                    load_runtime(sb.store)
                self.assertIn(error, str(ctx.exception))
                self.assertIn("steps[0].gates[0]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
