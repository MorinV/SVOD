"""The pending text of done: the next step once every step passed and done did not."""
import tempfile
import unittest
from pathlib import Path

from support import EXIT_OK, TempStore, doc, make_profile

from svod.context import Context
from svod.document import block
from svod.loader import load_runtime

PIPELINE = """
pipeline: box
subject:
  provider: container
  params: { roots: [boxes], head_type: onepager }
done: { gate: field, params: { name: status, equals: closed }, text: box.done, pending: box.close }
steps:
  - id: onepager
    text: box.write
    gates: [ { gate: doc_type, params: { type: onepager } } ]
"""
LOCALE = """
box:
  write: "write the onepager"
  close: "close the box"
  done: "box closed"
gate:
  field_equals: "{name} is {value}"
"""
PENDING_ROW = ("| done | status is closed | - | when every step passed and it did not: close the box; "
               "when passed: box closed |")


class PendingTest(unittest.TestCase):
    """Pending text in status and in the rendered table."""

    @classmethod
    def setUpClass(cls):
        """A store with an open box, a box missing its onepager and a closed box."""
        cls.tmp = tempfile.TemporaryDirectory()
        profile = make_profile(Path(cls.tmp.name) / "p", {"box.yaml": PIPELINE}, LOCALE)
        cls.sb = TempStore(profile=profile)
        cls.sb.write("boxes/open/one.md", doc("onepager"))
        cls.sb.write("boxes/empty/notes.md", doc("doc"))
        cls.sb.write("boxes/shut/one.md", doc("onepager", status="closed"))

    @classmethod
    def tearDownClass(cls):
        """Remove the store and the profile."""
        cls.sb.cleanup()
        cls.tmp.cleanup()

    def test_status(self):
        """Every step passed: pending; a step open: its text; done passed: the done text."""
        cases = (("open", "Next step: close the box."), ("empty", "Next step: write the onepager."),
                 ("shut", "Next step: box closed."))
        for query, text in cases:
            with self.subTest(query=query):
                out = self.sb.cli("status", query)
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                self.assertIn(text, out.stdout)

    def test_render(self):
        """The done row names the pending text before the done text."""
        runtime = load_runtime(self.sb.store)
        lines = block(Context(runtime.config, runtime.locale), runtime.pipeline("box"))
        self.assertIn(PENDING_ROW, lines)


if __name__ == "__main__":
    unittest.main()
