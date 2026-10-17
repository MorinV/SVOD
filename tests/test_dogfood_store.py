"""The store of this repository (store/): Svod's own work runs through the standard template.

The checks run on a copy, so status and its evidence log never write into the repository.
"""
import re
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from support import CLI_ENV, ENCODING, EXIT_OK, REPO_DIR, git_env, run_cli

STORE = REPO_DIR / "store"
WORK = "work"
CARD = "card.md"
# Files of one machine, kept out of version control by store/.gitignore.
LOCAL = ("__pycache__", ".claude", ".svod-local.yaml", "checks.log", "work.yaml")
RECORDS = ("work/features/0.5-release", "work/tasks/autonomy-by-kind",
           "work/tasks/external-phrase-match", "work/tasks/command-gate-in-template",
           "work/research/retro-signals")
SERVICE = "services: [svod]"
# Absolute paths of a machine: home directories, temporary directories, this checkout.
ABSOLUTE = re.compile(r"(?<![\w.])/(?:home|root|Users|tmp|private|var/folders)/")


def records(store):
    """Ids of every work record of the store: work/<kind>/<name> holding card.md."""
    return sorted(p.parent.relative_to(store).as_posix()
                  for p in (store / WORK).glob(f"*/*/{CARD}"))


def store_files():
    """Files of store/ that are committed: every file but those of one machine."""
    return [p for p in STORE.rglob("*")
            if p.is_file() and not any(part in LOCAL for part in p.relative_to(STORE).parts)]


class DogfoodStoreTest(unittest.TestCase):
    """store/ validates, resolves its records and lists open work, on a copy."""

    def setUp(self):
        """Copy store/ without the files of one machine into a temporary directory."""
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        home = base / "home"
        home.mkdir()
        self.store = base / "repo" / "store"
        shutil.copytree(STORE, self.store, ignore=shutil.ignore_patterns(*LOCAL))
        self.env = {**git_env(home), **CLI_ENV}

    def cli(self, *args):
        """Run svod in the copy of the store."""
        return run_cli(args, self.store, self.env, drop=("CLAUDE_PROJECT_DIR",))

    def test_validate(self):
        """svod validate is green."""
        done = self.cli("validate")
        self.assertEqual(done.returncode, EXIT_OK, done.stdout + done.stderr)

    def test_records_resolve(self):
        """Every record resolves to itself, names the svod service and has tags."""
        found = records(self.store)
        self.assertEqual(sorted(RECORDS), [r for r in found if r in RECORDS])
        for record in found:
            with self.subTest(record=record):
                card = (self.store / record / CARD).read_text(encoding=ENCODING)
                self.assertIn(SERVICE, card)
                self.assertRegex(card, r"(?m)^tags: \[\S")
                done = self.cli("status", record)
                self.assertEqual(done.returncode, EXIT_OK, done.stdout + done.stderr)
                self.assertEqual(done.stdout.splitlines()[0], record)

    def test_active_lists_the_open_records(self):
        """svod active is not empty and names every open record."""
        done = self.cli("active")
        self.assertEqual(done.returncode, EXIT_OK, done.stderr)
        for record in RECORDS:
            self.assertIn(f"- {record} - ", done.stdout)

    def test_no_absolute_paths(self):
        """No committed file of the store holds an absolute path of this machine."""
        files = store_files()
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding=ENCODING, errors="replace")
            with self.subTest(file=path.relative_to(STORE).as_posix()):
                self.assertNotIn(str(REPO_DIR), text)
                self.assertIsNone(ABSOLUTE.search(text))


if __name__ == "__main__":
    unittest.main()
