"""Engine skills: in svod/skills, shipped with the package, naming no retired command."""
import re
import unittest

from support import ENCODING, REPO_DIR

from svod import vendor
from svod.frontmatter import read_frontmatter

SKILLS = REPO_DIR / "svod" / "skills"
NAMES = ("svod-efficient-execution", "svod-pipeline", "svod-planning-transition",
         "svod-task-layout-transition")
OPTIONAL_NAMES = ("svod-fret",)
SKILL_FILE = "SKILL.md"
PYPROJECT = REPO_DIR / "pyproject.toml"
PACKAGE_DATA_RE = re.compile(r"\[tool.setuptools.package-data\]\s*svod = \[(.*)\]")
SKILLS_PATTERN = '"skills/**/*"'
LINK_RE = re.compile(r"\]\(([^)]+)\)")
URL_PREFIX = "https://"
# Commands, files and gates of the retired local workflow.
RETIRED = ("svod local", "local-workflow", "local_workflow", "current_process", "templates/local",
           "testing/plan.yaml")
# Documents that describe the current release; the changelog keeps the history.
DOCUMENTS = ("README.md", "docs/reference.md", "integrations/common.sh")


class EngineSkillsTest(unittest.TestCase):
    def test_skills_are_where_vendor_and_setup_take_them(self):
        """Engine and opt-in skills match directory names; vendor/common.sh take them here."""
        found = sorted(p.parent.name for p in SKILLS.glob(f"*/{SKILL_FILE}"))
        self.assertEqual(found, sorted(NAMES + OPTIONAL_NAMES))
        for name in NAMES + OPTIONAL_NAMES:
            with self.subTest(skill=name):
                self.assertEqual(read_frontmatter(SKILLS / name / SKILL_FILE)["name"], name)
        self.assertEqual(REPO_DIR / vendor.SKILLS_SOURCE, SKILLS)
        common = (REPO_DIR / "integrations" / "common.sh").read_text(encoding=ENCODING)
        self.assertIn('PACKAGED_SKILLS="svod/skills"', common)

    def test_package_data_ships_the_skills(self):
        """pyproject.toml ships svod/skills with the package."""
        (data,) = PACKAGE_DATA_RE.findall(PYPROJECT.read_text(encoding=ENCODING))
        self.assertIn(SKILLS_PATTERN, data)

    def test_skills_link_nothing_relative(self):
        """A copy in .svod/skills or a linked skill has no docs next to it: links are URLs."""
        for name in NAMES:
            text = (SKILLS / name / SKILL_FILE).read_text(encoding=ENCODING)
            for link in LINK_RE.findall(text):
                with self.subTest(skill=name, link=link):
                    self.assertTrue(link.startswith(URL_PREFIX))

    def test_no_retired_command_is_named(self):
        """The skills and the documents of the release name no part of the local workflow."""
        paths = [SKILLS / name / SKILL_FILE for name in NAMES + OPTIONAL_NAMES]
        paths += [REPO_DIR / name for name in DOCUMENTS]
        for path in paths:
            text = path.read_text(encoding=ENCODING)
            for word in RETIRED:
                with self.subTest(path=str(path.relative_to(REPO_DIR)), word=word):
                    self.assertFalse(word in text, f"{word} in {path.name}")


if __name__ == "__main__":
    unittest.main()
