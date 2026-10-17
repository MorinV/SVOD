"""Packaged project templates must work without the source clone."""
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

from svod.scaffold import scaffold


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
