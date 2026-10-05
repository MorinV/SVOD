"""Role bindings: the skill line of status and the validation of bindings files."""
import unittest

from support import StoreTestCase, dedent, doc

from svod.context import Context
from svod.errors import LoadError
from svod.loader import load_runtime
from svod.providers.openspec_change import DEFAULT_ROOT, METADATA_FILE
from svod.render import status_report

BINDINGS_FILE = "bindings.yaml"
BINDINGS = """
    skill_path: "skills/{skill}/SKILL.md"
    probe: { gate: dirs, fact: paths }
    roles:
      builder:
        - { when: { has_file: pyproject.toml }, skill: impl-py }
        - { when: { has_file: go.mod }, skill: null }
      checker:
        - { skill: ext-check, external: true }
      closer:
        - { skill: ext-close, external: true }
"""
SKILL_FILE = "skills/impl-py/SKILL.md"
PYTHON_MARK = "pyproject.toml"
GO_MARK = "go.mod"
NEXT_BUILD = "  Next step: start building in a workspace."
NEXT_VERIFY = "  Next step: run the mandatory cases, report in the change."
SKILL_PREFIX = "  Step skill:"


def change(sb, key, approved=True, progress=None, repos=()):
    """Change of the test profile up to the build step, with repository directories."""
    root = f"{DEFAULT_ROOT}/c-{key}"
    meta = [f"ticket: {key}"] + (["approved: 2026-09-10"] if approved else [])
    sb.write(f"{root}/{METADATA_FILE}", "\n".join(meta) + "\n")
    sb.write(f"{root}/specs/cap/spec.md", "# spec\n")
    sb.write(f"{root}/design.md", "# design\n")
    if progress is not None:
        sb.write(f"{root}/progress.txt", progress)
    for name, mark in repos:
        sb.write(f"{root}/repos/{name}/{mark}", "\n")


class SkillLineTest(StoreTestCase):
    """The skill line follows the next step when the current step has a bound role."""

    store_kwargs = {"bindings": BINDINGS_FILE}

    def setUp(self):
        """Store with bindings, one skill file and changes at the build and verify steps."""
        super().setUp()
        self.sb.write(BINDINGS_FILE, dedent(BINDINGS))
        self.sb.write(SKILL_FILE, "# skill\n")
        change(self.sb, "tk-1", repos=(("one", PYTHON_MARK),))
        change(self.sb, "tk-2", repos=(("one", PYTHON_MARK), ("two", GO_MARK)))
        change(self.sb, "tk-3", repos=(("two", GO_MARK),))
        change(self.sb, "tk-4")
        change(self.sb, "tk-5", progress="1")
        change(self.sb, "tk-6", approved=False)
        self.sb.write("projects/unready/Onepager.md", doc("onepager"))
        self.sb.write("projects/ready/Onepager.md", doc("onepager", closing="yes"))
        for name in ("unready", "ready"):
            self.sb.write(f"projects/{name}/Design/solution.md", doc("design"))
            self.sb.write(f"projects/{name}/Design/pyramid.md", doc("test-strategy"))
            self.sb.write(f"projects/{name}/Plan/wbs.md", doc("wbs"))
        self.runtime = load_runtime(self.sb.store)

    def status(self, key, bindings=True):
        """Status lines of one change, with or without the bindings in the context."""
        ctx = Context(self.runtime.config, self.runtime.locale,
                      bindings=self.runtime.bindings if bindings else None)
        report = status_report(ctx, self.runtime.pipelines, key)
        self.assertTrue(report.ok, report.err)
        return report.out

    def test_skill_line(self):
        """One skill, a skill per directory, not assigned, external."""
        cases = (
            ("tk-1", NEXT_BUILD, "  Step skill: impl-py"),
            ("tk-2", NEXT_BUILD, "  Step skill: one -> impl-py, two -> none"),
            ("tk-3", NEXT_BUILD, "  Step skill: not assigned (role builder)"),
            ("tk-4", NEXT_BUILD, "  Step skill: not assigned (role builder)"),
            ("tk-5", NEXT_VERIFY, "  Step skill: ext-check"),
            ("ready", "  Next step: close the container.", "  Step skill: ext-close"),
        )
        for key, step, line in cases:
            with self.subTest(key=key):
                out = self.status(key)
                self.assertEqual(out[out.index(step) + 1], line)

    def test_no_line_without_role_or_bindings(self):
        """No role, no bindings, or a step held by its own blocking entry: no skill line."""
        for key, bindings in (("tk-6", True), ("tk-1", False), ("unready", True)):
            with self.subTest(key=key, bindings=bindings):
                out = self.status(key, bindings)
                self.assertFalse([line for line in out if line.startswith(SKILL_PREFIX)])


class BindingsValidationTest(StoreTestCase):
    """validate reports every inconsistency between bindings, pipelines and skills."""

    store_kwargs = {"bindings": BINDINGS_FILE}

    def load_error(self, text):
        """LoadError text of the store with the given bindings file."""
        self.sb.write(BINDINGS_FILE, dedent(text))
        with self.assertRaises(LoadError) as ctx:
            load_runtime(self.sb.store)
        return str(ctx.exception)

    def test_errors(self):
        """Each broken bindings file names its problem."""
        cases = (
            ("undescribed role", BINDINGS.replace("      checker:\n        - { skill: ext-check, "
                                                  "external: true }\n", ""),
             "role checker is not described in bindings.yaml"),
            ("missing skill", BINDINGS.replace("skill: impl-py", "skill: impl-none"),
             "skill impl-none not found"),
            ("unknown condition", BINDINGS.replace("has_file: go.mod", "has_dir: go"),
             "unknown key: has_dir"),
            ("unknown probe gate", BINDINGS.replace("gate: dirs", "gate: nope"),
             "unknown gate: nope"),
            ("no probe", BINDINGS.replace("    probe: { gate: dirs, fact: paths }\n", ""),
             "probe: required when a rule has when"),
            ("bad skill path", BINDINGS.replace("skills/{skill}/SKILL.md", "skills/SKILL.md"),
             "skill_path: must be a path template"),
            ("rule without skill", BINDINGS.replace("{ skill: ext-check, external: true }",
                                                    "{ external: true }"),
             "missing key: skill"),
        )
        for name, text, message in cases:
            with self.subTest(name=name):
                self.assertIn(message, self.load_error(text))

    def test_external_skill_needs_no_file(self):
        """An external skill passes without a file; a present local skill passes too."""
        self.sb.write(BINDINGS_FILE, dedent(BINDINGS))
        self.sb.write(SKILL_FILE, "# skill\n")
        self.assertIsNotNone(load_runtime(self.sb.store).bindings)


if __name__ == "__main__":
    unittest.main()
