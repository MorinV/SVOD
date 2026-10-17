"""The release workflow: version and CHANGELOG section of a tree, read by the engine's parser."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from support import CLI_TIMEOUT_SEC, ENCODING, EXIT_FINDINGS, EXIT_OK, REPO_DIR

import svod
from svod import changelog, versions

WORKFLOW = REPO_DIR / ".github" / "workflows" / "release.yml"
SCRIPT = REPO_DIR / ".github" / "scripts" / "release_notes.py"
SCRIPT_CALL = "python3 .github/scripts/release_notes.py"
MIGRATION_LINE = f"### {changelog.MIGRATION_HEADING}"
TREE_VERSION = "1.2.3"
TREE_CHANGELOG = """# Changelog

## [Unreleased]

- Pending.

## [1.2.3] - 2026-10-17

### Added

- A thing.

### Migration

none.

## [1.2.2] - 2026-10-16

- Older.
"""
TREE_NOTES = "### Added\n\n- A thing.\n\n### Migration\n\nnone.\n"


def run_script(*args):
    """Run the release notes script of this checkout."""
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding=ENCODING, timeout=CLI_TIMEOUT_SEC, check=False)


def make_tree(root, version=TREE_VERSION, text=TREE_CHANGELOG):
    """A source tree with svod/__init__.py of version and the changelog text."""
    package = Path(root) / versions.PACKAGE_INIT
    package.parent.mkdir(parents=True)
    package.write_text(f'__version__ = "{version}"\n', encoding=ENCODING)
    if text is not None:
        (Path(root) / changelog.CHANGELOG_FILE).write_text(text, encoding=ENCODING)
    return root


class RepositoryReleaseTest(unittest.TestCase):
    """The current tree has what the workflow needs to release it."""

    def test_version_is_the_package_version(self):
        """version prints svod.__version__."""
        result = run_script("version")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertEqual(result.stdout.strip(), svod.__version__)

    def test_notes_are_the_current_section(self):
        """notes prints the section of the current version without its heading."""
        result = run_script("notes")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        text = (REPO_DIR / changelog.CHANGELOG_FILE).read_text(encoding=ENCODING)
        release = {r.version: r for r in changelog.releases(text)}[svod.__version__]
        self.assertEqual(result.stdout.splitlines(), list(release.lines[2:]))
        self.assertIn(MIGRATION_LINE, result.stdout.splitlines())
        self.assertNotIn(f"## [{svod.__version__}]", result.stdout)


class TreeReleaseTest(unittest.TestCase):
    """--root reads another tree: the commit to release."""

    def test_notes_of_a_tree(self):
        """Only the section of the tree's version, from its first line to its last."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            self.assertEqual(run_script("--root", root, "version").stdout, f"{TREE_VERSION}\n")
            result = run_script("--root", root, "notes")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertEqual(result.stdout, TREE_NOTES)

    def test_missing_section_fails(self):
        """A version without a section, or without a changelog, exits 1 and names it."""
        cases = {"no section": TREE_CHANGELOG.replace("## [1.2.3] - 2026-10-17\n", ""),
                 "empty section": "## [1.2.3]\n\n## [1.2.2]\n\n- Older.\n",
                 "no changelog": None}
        for name, text in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                result = run_script("--root", make_tree(tmp, text=text), "notes")
                self.assertEqual(result.returncode, EXIT_FINDINGS)
                self.assertEqual(result.stdout, "")
                self.assertIn(f"## [{TREE_VERSION}]", result.stderr)

    def test_missing_version_fails(self):
        """A tree whose version is not X.Y.Z exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script("--root", make_tree(tmp, version="dev"), "version")
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertEqual(result.stdout, "")


class WorkflowTest(unittest.TestCase):
    """release.yml runs on a version change on main, by hand too, and may write tags."""

    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding=ENCODING))

    def test_triggers(self):
        """Push to main touching svod/__init__.py, and workflow_dispatch."""
        triggers = self.workflow[True]  # YAML 1.1 reads the key on as true
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertEqual(triggers["push"]["paths"], [versions.PACKAGE_INIT.as_posix()])
        self.assertIn("workflow_dispatch", triggers)

    def test_job_writes_contents_and_uses_the_script(self):
        """The job may write contents, reads the tree with the script and releases with gh."""
        (job,) = self.workflow["jobs"].values()
        self.assertEqual(job["permissions"], {"contents": "write"})
        runs = "\n".join(step.get("run", "") for step in job["steps"])
        self.assertIn(f"{SCRIPT_CALL} --root target version", runs)
        self.assertIn(f"{SCRIPT_CALL} --root target notes", runs)
        self.assertIn('git tag -a "$TAG"', runs)
        self.assertIn('gh release create "$TAG"', runs)
        steps = "\n".join(f"{step.get('uses', '')} {step.get('run', '')}" for step in job["steps"])
        self.assertNotIn("pypi", steps.casefold())


if __name__ == "__main__":
    unittest.main()
