"""The packaged templates, the examples, the skills and the docs are copies that must not drift."""
import filecmp
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "svod" / "templates"
PAIRS = (
    (ROOT / "examples" / "task", TEMPLATES / "task"),
    (ROOT / "examples" / "local", TEMPLATES / "local"),
    (ROOT / "skills", TEMPLATES / "local" / "skills"),
)
DOCS = ("local-workflow.md", "reference.md", "updating.md")


def differences(left, right):
    """Paths that differ, are missing on one side or could not be compared, recursively."""
    cmp = filecmp.dircmp(left, right, ignore=["__pycache__"])
    found = [left / name for name in cmp.diff_files + cmp.left_only + cmp.funny_files]
    found += [right / name for name in cmp.right_only]
    for name, sub in cmp.subdirs.items():
        found += differences(left / name, right / name)
    return found


class CopiesTest(unittest.TestCase):
    """Every copy equals its original byte for byte."""

    def test_directories(self):
        """examples/ and skills/ equal the packaged templates."""
        for left, right in PAIRS:
            with self.subTest(copy=left.relative_to(ROOT).as_posix()):
                self.assertEqual(differences(left, right), [])

    def test_docs(self):
        """The docs shipped in the local template equal docs/."""
        for name in DOCS:
            with self.subTest(doc=name):
                original = (ROOT / "docs" / name).read_bytes()
                self.assertEqual(original, (TEMPLATES / "local" / "docs" / name).read_bytes())
                self.assertEqual(original, (ROOT / "examples" / "local" / "docs" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
