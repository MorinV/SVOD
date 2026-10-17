"""Packaged project templates must work without the source clone."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory

from support import (CLI_MODULE, CLI_TIMEOUT_SEC, ENCODING, EXIT_OK, EXIT_USAGE, core_text,
                     git_env)
from svod import keys
from svod.errors import LoadError
from svod.scaffold import DEFAULT_TEMPLATE, RETIRED, TEMPLATES, scaffold

REPO = Path(__file__).resolve().parents[1]
RETIRED_NAME = 'local'
REPLACEMENT = 'standard'


def isolated_env(home):
    """Process environment with git isolated from the developer's configuration."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('SVOD_')}
    return dict(env, **git_env(home), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')


def run_cli(cwd, home, *args):
    """Run the CLI as a black box in cwd."""
    return subprocess.run([sys.executable, '-m', CLI_MODULE, *args], cwd=str(cwd),
                          env=isolated_env(home), capture_output=True, text=True,
                          encoding=ENCODING, timeout=CLI_TIMEOUT_SEC)


def files_of(directory):
    """Bytes of every file under the directory by its relative path, byte-code left out."""
    return {p.relative_to(directory): p.read_bytes() for p in directory.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts}


class ScaffoldTest(unittest.TestCase):
    def test_scaffold_copies_the_template_and_refuses_overwrite(self):
        for name in TEMPLATES:
            with self.subTest(template=name), TemporaryDirectory() as temp:
                target = scaffold(Path(temp) / 'store', name)
                expected = files_of(REPO / 'svod' / 'templates' / name)
                actual = files_of(target)
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

    def test_shipped_templates(self):
        """standard and task ship and standard is the default; the local template is gone."""
        shipped = {p.name for p in (REPO / 'svod' / 'templates').iterdir() if p.is_dir()}
        self.assertEqual(shipped, set(TEMPLATES))
        self.assertEqual(DEFAULT_TEMPLATE, REPLACEMENT)
        self.assertEqual(RETIRED, {RETIRED_NAME: REPLACEMENT})


class RetiredTemplateTest(unittest.TestCase):
    """svod new --template local is a load error naming the standard template."""

    def test_scaffold_refuses_with_the_replacement(self):
        with TemporaryDirectory() as temp:
            target = Path(temp) / 'store'
            with self.assertRaises(LoadError) as caught:
                scaffold(target, RETIRED_NAME)
            self.assertEqual(caught.exception.errors,
                             [core_text(keys.NEW_TEMPLATE_RETIRED, template=RETIRED_NAME,
                                        replacement=REPLACEMENT)])
            self.assertFalse(target.exists())

    def test_cli_new_local_and_default(self):
        """The CLI exits with 2 and the load error; without --template it makes a standard
        store; an unknown name is a usage error listing the templates."""
        with TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / 'home'
            home.mkdir()
            refused = run_cli(base, home, 'new', 'old', '--template', RETIRED_NAME)
            self.assertEqual(refused.returncode, EXIT_USAGE, refused.stdout)
            self.assertIn(core_text(keys.ERROR_LOAD), refused.stderr)
            self.assertIn(f'--template {REPLACEMENT}', refused.stderr)
            self.assertFalse((base / 'old').exists())
            created = run_cli(base, home, 'new', 'fresh')
            self.assertEqual(created.returncode, EXIT_OK, created.stderr)
            self.assertEqual(files_of(base / 'fresh'),
                             files_of(REPO / 'svod' / 'templates' / REPLACEMENT))
            unknown = run_cli(base, home, 'new', 'other', '--template', 'nope')
            self.assertEqual(unknown.returncode, EXIT_USAGE)
            self.assertIn(REPLACEMENT, unknown.stderr)
            self.assertFalse((base / 'other').exists())

    def test_task_template_has_no_local_workflow(self):
        """The task template names neither svod local nor the local workflow."""
        for path, data in files_of(REPO / 'svod' / 'templates' / 'task').items():
            text = data.decode(ENCODING)
            for word in ('svod local', 'local_workflow', 'local-workflow', 'current_process'):
                with self.subTest(path=str(path), word=word):
                    self.assertNotIn(word, text)


if __name__ == '__main__':
    unittest.main()
