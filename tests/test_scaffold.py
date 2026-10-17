"""Packaged project templates must work without the source clone."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory

import yaml

from support import CLI_MODULE, CLI_TIMEOUT_SEC, ENCODING, EXIT_OK, git_env
from svod.scaffold import scaffold

EXAMPLE_TASK = 'tasks/example'
EXAMPLE_FILES = ('EXAMPLE-card.md', 'contract.md', 'testing/plan.yaml')
EXAMPLE_PLAN = 'testing/plan.yaml'
PLAN_KEYS = {'version', 'kind', 'contract', 'workspace', 'command'}
FIRST_STEP = 'Next step: Prepare a compact contract.md'
PLACEHOLDER_REASON = 'workspace must be an explicit absolute Git directory'
ACTIVE_HEADING = 'Local tasks:'
ACTIVE_ITEM = f'  - {EXAMPLE_TASK} - Prepare a compact contract.md'


def isolated_env(home):
    """Process environment with git isolated from the developer's configuration."""
    return dict(os.environ, **git_env(home), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')


def run_cli(store, home, *args):
    """Run the CLI as a black box in the store."""
    return subprocess.run([sys.executable, '-m', CLI_MODULE, *args], cwd=str(store),
                          env=isolated_env(home), capture_output=True, text=True,
                          encoding=ENCODING, timeout=CLI_TIMEOUT_SEC)


class ScaffoldTest(unittest.TestCase):
    def test_scaffold_copies_the_template_and_refuses_overwrite(self):
        repo = Path(__file__).resolve().parents[1]
        for name in ('local', 'task'):
            with self.subTest(template=name), TemporaryDirectory() as temp:
                target = scaffold(Path(temp) / 'store', name)
                source = repo / 'svod' / 'templates' / name
                expected = {p.relative_to(source): p.read_bytes()
                            for p in source.rglob('*')
                            if p.is_file() and '__pycache__' not in p.parts}
                actual = {p.relative_to(target): p.read_bytes()
                          for p in target.rglob('*') if p.is_file()}
                self.assertTrue(expected)
                self.assertEqual(actual, expected)
                with self.assertRaises(ValueError):
                    scaffold(target, name)
                self.assertEqual((target / 'svod.yaml').read_bytes(), actual[Path('svod.yaml')])

    def test_unknown_template_is_refused_before_creating_destination(self):
        with TemporaryDirectory() as temp:
            target = Path(temp) / 'store'
            with self.assertRaises(ValueError):
                scaffold(target, '../outside')
            self.assertFalse(target.exists())


class LocalTemplateExampleTest(unittest.TestCase):
    def test_fresh_local_store_shows_the_example_task(self):
        """A new local store validates, stops the example task at the contract with the
        reason and lists it in the active summary."""
        with TemporaryDirectory() as temp:
            store = scaffold(Path(temp) / 'store', 'local')
            home = Path(temp) / 'home'
            home.mkdir()
            for name in EXAMPLE_FILES:
                self.assertTrue((store / EXAMPLE_TASK / name).is_file(), name)
            plan = yaml.safe_load((store / EXAMPLE_TASK / EXAMPLE_PLAN).read_text(ENCODING))
            self.assertEqual(set(plan), PLAN_KEYS)
            subprocess.run(['git', 'init', '-q', str(store)], env=isolated_env(home),
                           check=True, capture_output=True)
            validate = run_cli(store, home, 'validate')
            self.assertEqual(validate.returncode, EXIT_OK, validate.stdout + validate.stderr)
            status = run_cli(store, home, 'status', EXAMPLE_TASK)
            self.assertEqual(status.returncode, EXIT_OK, status.stderr)
            self.assertIn(FIRST_STEP, status.stdout)
            self.assertIn(PLACEHOLDER_REASON, status.stdout)
            active = run_cli(store, home, 'active')
            self.assertEqual(active.returncode, EXIT_OK, active.stderr)
            self.assertIn(ACTIVE_HEADING, active.stdout)
            self.assertIn(ACTIVE_ITEM, active.stdout)
