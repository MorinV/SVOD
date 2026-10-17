"""The docs shipped in the local template are copies of docs/ that must not drift."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DOCS = ROOT / "svod" / "templates" / "local" / "docs"
DOCS = ("local-workflow.md", "reference.md", "updating.md")


class CopiesTest(unittest.TestCase):
    """Every copy equals its original byte for byte."""

    def test_docs(self):
        """The docs of the local template equal docs/."""
        for name in DOCS:
            with self.subTest(doc=name):
                self.assertEqual((ROOT / "docs" / name).read_bytes(),
                                 (TEMPLATE_DOCS / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
