"""A provider declared by the profile, and the missing text yielding to another pipeline."""
import tempfile
import unittest
from pathlib import Path

from support import EXIT_OK, EXIT_USAGE, TempStore, make_profile

from svod import keys
from svod.locale import FALLBACK_LOCALE, load_locale

GATES = """
import re

from svod.gates import Gate, KeyGate, verdict
from svod.providers import Provider
from svod.subject import Subject

KEY_RE = re.compile(r"(?<![\\w-])(tk-\\d+)(?!\\d)")
LISTED = "lite.txt"
ENCODING = "utf-8"


class Ticket(KeyGate):
    name = "ticket"

    def match(self, query):
        found = KEY_RE.search(query)
        return found.group(1) if found else None

    def find(self, text):
        return set(KEY_RE.findall(text))


class Never(Gate):
    name = "never"

    def evaluate(self, ctx, subject):
        return verdict(False)

    def describe(self, params, locale):
        return "never"


class Lite(Provider):
    name = "lite"

    def listed(self, ctx):
        path = ctx.root / LISTED
        return path.read_text(encoding=ENCODING).split() if path.is_file() else []

    def enumerate(self, ctx):
        return [Subject(id=key, path=None, keys=frozenset({key})) for key in self.listed(ctx)]

    def match_key(self, key, ctx):
        return [s for s in self.enumerate(ctx) if s.id == key]


GATES = {cls.name: cls for cls in (Ticket, Never)}
PROVIDERS = {Lite.name: Lite}
"""
TASK = """
pipeline: task
subject: { provider: openspec_change, key_gate: ticket }
missing: { gate: never, text: task.missing }
steps:
  - id: propose
    text: task.propose
    gates: [ { gate: exists } ]
"""
LITE = """
pipeline: lite
header: lite.header
subject: { provider: lite, key_gate: ticket }
steps:
  - id: work
    text: lite.work
    gates: [ { gate: never } ]
"""
LOCALE = """
task:
  missing: "Task {keys}: nothing is known."
  propose: "propose a change"
lite:
  header: "Light task {id}"
  work: "do the work"
"""


class ProfileProviderTest(unittest.TestCase):
    """The profile provider resolves keys; the other pipeline's missing text stays silent."""

    @classmethod
    def setUpClass(cls):
        """A store listing tk-2 as a light task."""
        cls.tmp = tempfile.TemporaryDirectory()
        profile = make_profile(Path(cls.tmp.name) / "p", {"task.yaml": TASK, "lite.yaml": LITE},
                               LOCALE, gates={"lite.py": GATES})
        cls.sb = TempStore(profile=profile)
        cls.sb.write("lite.txt", "tk-2\n")
        cls.texts = load_locale(FALLBACK_LOCALE, profile)

    @classmethod
    def tearDownClass(cls):
        """Remove the store and the profile."""
        cls.sb.cleanup()
        cls.tmp.cleanup()

    def test_validate(self):
        """The profile provider loads."""
        out = self.sb.cli("validate")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)

    def test_light_task_shown_missing_text_silent(self):
        """tk-2: the light position only; tk-3: the missing text and exit 2."""
        out = self.sb.cli("status", "tk-2")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(out.stdout.splitlines()[0], self.texts.text("lite.header", id="tk-2"))
        self.assertIn(self.texts.text(keys.STATUS_NEXT_STEP, step=self.texts.text("lite.work")),
                      out.stdout)
        self.assertEqual(out.stderr, "")
        out = self.sb.cli("status", "tk-3")
        self.assertEqual(out.returncode, EXIT_USAGE)
        self.assertEqual(out.stderr.strip(), self.texts.text("task.missing", keys="tk-3"))


if __name__ == "__main__":
    unittest.main()
