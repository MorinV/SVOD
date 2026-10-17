"""svod update merges the files the template gave the store; validate and doctor follow up."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import (ENCODING, EXIT_FINDINGS, EXIT_OK, MAIN_BRANCH, TempStore, core_text)
from test_vendoring import VERSION_LINE, replace_in, source_files

import svod
from svod import keys, profile_merge as pm, update, vendor
from svod.launcher import LAUNCH_ENV
from svod.doctor import CHECK_TEMPLATE, OK, WARN, template_checks
from svod.locale import load_core_locale
from svod.paths import package_dir, vendor_dir
from svod.scaffold import scaffold

TEMPLATE = "task"
OLD = "0.2.0"
NEW = "0.3.0"
OLD_TAG = f"v{OLD}"
NEW_TAG = f"v{NEW}"
COMMITTER = ("release@example.com", "Release")
TEMPLATE_DIR = Path("svod") / "templates" / TEMPLATE
RU = "profile/locale/ru.yaml"
EN = "profile/locale/en.yaml"
BINDINGS = "profile/bindings.yaml"
NOTES = "profile/NOTES.md"
MINE = "profile/mine.md"
CONFIG = "svod.yaml"
RU_OLD = '    propose: "Предложение"'
RU_NEW = '    propose: "Предложение изменения"'
EN_OLD = '  header: "{id} ({keys})"'
EN_NEW = '  header: "{id} [{keys}]"'
EN_STORE_OLD = '  done: "nothing left, the change is archived"'
EN_STORE_NEW = '  done: "all done"'
WINDOW_OLD = "  window_minutes: 10"
WINDOW_NEW = "  window_minutes: 15"
WINDOW_STORE = "  window_minutes: 30"
NOTES_TEXT = "# Notes of the profile\n"
MINE_TEXT = "mine\n"
BINDINGS_STORE = "roles: {}\n"
LABELS = ("store", "template a", "template b")
SESSION_ENV = ("CLAUDE_PROJECT_DIR", LAUNCH_ENV)


def merge_source(base):
    """Git repository of Svod releases v0.2.0 and v0.3.0; v0.3.0 changes the task template."""
    source = Path(base) / "svod-merge-source"
    source.mkdir()
    sb_git = TempStore()
    try:
        sb_git.git(base, "init", "-q", "-b", MAIN_BRANCH, str(source))
        source_files(source)
        init = source / "svod" / "__init__.py"
        replace_in(init, VERSION_LINE.format(version=svod.__version__),
                   VERSION_LINE.format(version=OLD))
        sb_git.commit(source, OLD, author=COMMITTER)
        sb_git.git(source, "tag", OLD_TAG)
        replace_in(init, VERSION_LINE.format(version=OLD), VERSION_LINE.format(version=NEW))
        template = source / TEMPLATE_DIR
        replace_in(template / RU, RU_OLD, RU_NEW)
        replace_in(template / EN, EN_OLD, EN_NEW)
        replace_in(template / CONFIG, WINDOW_OLD, WINDOW_NEW)
        (template / NOTES).write_text(NOTES_TEXT, encoding=ENCODING)
        sb_git.commit(source, NEW, author=COMMITTER)
        sb_git.git(source, "tag", NEW_TAG)
    finally:
        shutil.rmtree(sb_git.root, ignore_errors=True)
    return source


def write(path, text):
    """Write a file, its directories included."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=ENCODING)


def text_of(root, rel):
    """Text of a file of a directory."""
    return (Path(root) / rel).read_text(encoding=ENCODING)


class DecideTest(unittest.TestCase):
    """What the merge does with one template file."""

    def test_rules(self):
        """Skipped, replaced, kept, merged or conflicting, by the three versions."""
        base, theirs = b"a\nb\nc\n", b"A\nb\nc\n"
        cases = (
            ("same templates", base, b"x\n", base, None),
            ("store has theirs", base, theirs, theirs, None),
            ("untouched store", base, base, theirs, (pm.UPDATED, theirs)),
            ("new file", None, None, theirs, (pm.ADDED, theirs)),
            ("dropped file", base, base, None, (pm.REMOVED, None)),
            ("removed by the store", base, None, theirs, (pm.KEPT, None)),
            ("changed, then dropped", base, b"z\n", None, (pm.KEPT, b"z\n")),
            ("clean merge", base, b"a\nb\nC\n", theirs, (pm.MERGED, b"A\nb\nC\n")),
        )
        for name, b, o, t, expected in cases:
            with self.subTest(case=name):
                found = pm.decide("f", b, o, t, LABELS)
                self.assertEqual(None if found is None else (found.kind, found.content),
                                 expected)

    def test_conflict(self):
        """Both sides change one line: git markers with the labels."""
        found = pm.decide("f", b"a\n", b"store\n", b"template\n", LABELS)
        self.assertEqual(found.kind, pm.CONFLICT)
        text = found.content.decode()
        for line in ("<<<<<<< store", "store", "=======", "template", ">>>>>>> template b"):
            self.assertIn(line + "\n", text)

    def test_no_git(self):
        """Without git the merge stops with a clear error; a plain replacement needs none."""
        with mock.patch.object(pm.shutil, "which", return_value=None):
            with self.assertRaises(pm.MergeError) as raised:
                pm.decide("f", b"a\n", b"b\n", b"c\n", LABELS)
            self.assertIn("git", str(raised.exception))
            self.assertEqual(pm.decide("f", b"a\n", b"a\n", b"c\n", LABELS).kind, pm.UPDATED)


class PlanTest(unittest.TestCase):
    """plan and apply over template directories and a store."""

    def setUp(self):
        """base and theirs templates, a store made from base."""
        self.temp = Path(tempfile.mkdtemp(prefix="svod-merge-test-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.base, self.theirs, self.root = (self.temp / n for n in ("base", "theirs", "store"))
        for directory in (self.base, self.theirs, self.root):
            write(directory / CONFIG, "a: 1\n")
            write(directory / "profile/same.yaml", "same\n")
            write(directory / "profile/gone.yaml", "gone\n")
            write(directory / "README.md", "readme\n")
        write(self.theirs / "profile/new.yaml", "new\n")
        (self.theirs / "profile/gone.yaml").unlink()
        write(self.theirs / CONFIG, "a: 2\n")
        write(self.theirs / "README.md", "changed readme\n")
        write(self.theirs / "profile/__pycache__/x.pyc", "x")
        write(self.root / MINE, MINE_TEXT)

    def test_plan_and_apply(self):
        """Template files under the scope only; the store's own files are left alone."""
        outcomes = pm.plan(self.base, self.theirs, self.root, OLD, NEW)
        self.assertEqual([(o.path, o.kind) for o in outcomes],
                         [("profile/gone.yaml", pm.REMOVED), ("profile/new.yaml", pm.ADDED),
                          (CONFIG, pm.UPDATED)])
        pm.apply(self.root, outcomes)
        self.assertEqual(text_of(self.root, CONFIG), "a: 2\n")
        self.assertEqual(text_of(self.root, "profile/new.yaml"), "new\n")
        self.assertFalse((self.root / "profile/gone.yaml").exists())
        self.assertEqual(text_of(self.root, "README.md"), "readme\n")
        self.assertEqual(text_of(self.root, MINE), MINE_TEXT)
        self.assertFalse((self.root / "profile/__pycache__").exists())
        self.assertEqual(pm.plan(self.base, self.theirs, self.root), [])


class MarkerTest(unittest.TestCase):
    """validate names every file of the scope left with a conflict marker, before other errors."""

    def test_conflict_errors(self):
        """Markers in svod.yaml and the profile count; elsewhere or longer ones do not."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / CONFIG, "a: 1\n<<<<<<< store\n")
            write(root / "profile/x.md", "<<<<<<<\n")
            write(root / "profile/y.md", "<<<<<<<< not a marker\n")
            write(root / "docs/z.md", "<<<<<<< store\n")
            self.assertEqual(pm.conflict_markers(root), [("profile/x.md", 1), (CONFIG, 2)])
            self.assertTrue(all("svod update" in e for e in pm.conflict_errors(root)))

    def test_validate(self):
        """The marker files come first, then the error of the YAML that does not load."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        out = sb.cli("validate")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        write(sb.store / "profile/notes.md", "<<<<<<< store\nmine\n=======\n")
        out = sb.cli("validate")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn("profile/notes.md:1: conflict marker", out.stderr)
        with open(sb.store / CONFIG, "a", encoding=ENCODING) as fh:
            fh.write("<<<<<<< store\nx: 1\n")
        out = sb.cli("validate")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        lines = out.stderr.splitlines()
        self.assertIn("profile/notes.md:1:", lines[1])
        self.assertIn("svod.yaml:", lines[2])
        self.assertIn("invalid YAML", out.stderr)


class StampTest(unittest.TestCase):
    """VERSION carries the template fields only when known."""

    def test_round_trip(self):
        """Old stamps read with empty template fields; new ones keep them."""
        with tempfile.TemporaryDirectory() as temp:
            vendor.write_stamp(temp, vendor.Stamp(OLD, "src", OLD_TAG))
            self.assertNotIn("template", text_of(temp, vendor.VERSION_FILE))
            full = vendor.Stamp(NEW, "src", NEW_TAG, TEMPLATE, OLD)
            vendor.write_stamp(temp, full)
            with mock.patch.object(vendor, "vendor_dir", return_value=Path(temp)):
                self.assertEqual(vendor.read_stamp(temp), full)


class IdentifyTest(unittest.TestCase):
    """install names the template whose profile the store holds unchanged."""

    def test_identify(self):
        """Each packaged template is found in a store made from it; a changed profile is not."""
        home = Path(svod.__file__).resolve().parent / "templates"
        with tempfile.TemporaryDirectory() as temp:
            for name in ("task", "standard"):
                with self.subTest(template=name):
                    store = scaffold(Path(temp) / name, name)
                    self.assertEqual(pm.identify(store, [home]), (name, home / name))
            write(Path(temp) / "task" / BINDINGS, BINDINGS_STORE)
            self.assertIsNone(pm.identify(Path(temp) / "task", [home]))


class DoctorTemplateTest(unittest.TestCase):
    """doctor warns when the profile follows an older template than the engine's."""

    def test_checks(self):
        """No copy: nothing; no template: warn; older template: warn; same: ok."""
        locale = load_core_locale("en")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(template_checks(root, locale), [])
            package_dir(root).mkdir(parents=True)
            cases = (
                (vendor.Stamp(NEW, "s", NEW_TAG), WARN, core_text(keys.DOCTOR_TEMPLATE_UNKNOWN)),
                (vendor.Stamp(NEW, "s", NEW_TAG, TEMPLATE, OLD), WARN,
                 core_text(keys.DOCTOR_TEMPLATE_OLDER, template=TEMPLATE, profile=OLD,
                           version=NEW, path=Path(".svod/lib/svod/templates/task"))),
                (vendor.Stamp(NEW, "s", NEW_TAG, TEMPLATE, NEW), OK,
                 core_text(keys.DOCTOR_TEMPLATE_OK, template=TEMPLATE, version=NEW)),
                (vendor.Stamp(NEW, "s", NEW_TAG, TEMPLATE), OK,
                 core_text(keys.DOCTOR_TEMPLATE_OK, template=TEMPLATE, version=NEW)),
            )
            for stamp, status, text in cases:
                with self.subTest(stamp=stamp):
                    vendor.write_stamp(vendor_dir(root), stamp)
                    found = template_checks(root, locale)
                    self.assertEqual([(c.name, c.status, c.text) for c in found],
                                     [(CHECK_TEMPLATE, status, text)])


class TemplateNameTest(unittest.TestCase):
    """--template names a template, never a path."""

    def test_path_refused(self):
        """A name with a separator or a dot directory merges nothing."""
        locale = load_core_locale("en")
        stamp = vendor.Stamp(OLD, "s", OLD_TAG, TEMPLATE, OLD)
        with tempfile.TemporaryDirectory() as temp:
            for name in ("../task", "a/b", "..", "."):
                with self.subTest(name=name):
                    found = update.profile_plan(Path(temp), locale, False, stamp, name,
                                                Path(temp), NEW, True)
                    self.assertFalse(found.merged)
                    self.assertEqual((found.template, found.template_version), (TEMPLATE, OLD))
                    self.assertEqual(found.errors, (core_text(keys.UPDATE_PROFILE_NO_TEMPLATE,
                                                              template=name),))


class UpdateProfileTest(unittest.TestCase):
    """install records the template; update merges the profile three ways."""

    @classmethod
    def setUpClass(cls):
        """The source with two releases, built once."""
        cls.origin = Path(tempfile.mkdtemp(prefix="svod-merge-origin-"))
        cls.source = merge_source(cls.origin)

    @classmethod
    def tearDownClass(cls):
        """Remove the source."""
        shutil.rmtree(cls.origin, ignore_errors=True)

    def setUp(self):
        """A store made from the task template, with v0.2.0 installed."""
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)
        shutil.rmtree(self.sb.store)
        scaffold(self.sb.store, TEMPLATE)
        out = self.cli("install", "--to", OLD_TAG)
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertEqual(vendor.read_stamp(self.sb.store),
                         vendor.Stamp(OLD, str(self.source.resolve()), OLD_TAG, TEMPLATE, OLD))
        self.assertIn(core_text(keys.UPDATE_PROFILE_MERGED, template=TEMPLATE, new=OLD, count=0),
                      out.stdout)

    def cli(self, *args):
        """Run install or update from the source in this process."""
        return self.sb.cli(*args, "--from", str(self.source), drop=SESSION_ENV)

    def path(self, rel):
        """A file of the store."""
        return self.sb.store / rel

    def edit_store(self):
        """Change the store: a line of en.yaml, the line of svod.yaml the template changes too,
        a file the template keeps, and a file of its own."""
        replace_in(self.path(EN), EN_STORE_OLD, EN_STORE_NEW)
        replace_in(self.path(CONFIG), WINDOW_OLD, WINDOW_STORE)
        write(self.path(BINDINGS), BINDINGS_STORE)
        write(self.path(MINE), MINE_TEXT)

    def test_merge(self):
        """Replaced, merged, added and conflicting files; the store's own files untouched."""
        self.edit_store()
        out = self.cli("update", "--to", NEW_TAG)
        self.assertEqual(out.returncode, EXIT_FINDINGS, out.stdout + out.stderr)
        theirs = self.source / TEMPLATE_DIR
        self.assertNotIn("<<<<<<<", text_of(self.sb.store, RU))
        self.assertIn(RU_NEW, text_of(self.sb.store, RU))
        self.assertEqual(text_of(self.sb.store, NOTES), NOTES_TEXT)
        en = text_of(self.sb.store, EN)
        self.assertIn(EN_NEW, en)
        self.assertIn(EN_STORE_NEW, en)
        config = text_of(self.sb.store, CONFIG)
        for line in ("<<<<<<< store", WINDOW_STORE, "=======", WINDOW_NEW,
                     f">>>>>>> template {NEW}"):
            self.assertIn(line + "\n", config)
        self.assertEqual(text_of(self.sb.store, BINDINGS), BINDINGS_STORE)
        self.assertNotEqual(text_of(theirs, BINDINGS), BINDINGS_STORE)
        self.assertEqual(text_of(self.sb.store, MINE), MINE_TEXT)
        for key, path in ((keys.UPDATE_PROFILE_ADDED, NOTES), (keys.UPDATE_PROFILE_UPDATED, RU),
                          (keys.UPDATE_PROFILE_MERGED_FILE, EN),
                          (keys.UPDATE_PROFILE_CONFLICT, CONFIG)):
            with self.subTest(key=key):
                self.assertIn(core_text(key, path=path), out.stdout)
        self.assertIn(core_text(keys.UPDATE_PROFILE_MERGED, template=TEMPLATE, new=NEW, count=4),
                      out.stdout)
        self.assertIn(core_text(keys.UPDATE_PROFILE_RESOLVE), out.stderr)
        self.assertIn("svod.yaml:", out.stderr)
        self.assertIn("conflict marker", out.stderr)
        self.assertEqual(vendor.read_stamp(self.sb.store).template_version, NEW)

    def test_no_profile_then_named(self):
        """--no-profile leaves the profile behind; doctor warns; update then has no base until
        the template is named again."""
        out = self.cli("update", "--to", NEW_TAG, "--no-profile")
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertIn(core_text(keys.UPDATE_PROFILE_OFF), out.stdout)
        self.assertFalse(self.path(NOTES).exists())
        stamp = vendor.read_stamp(self.sb.store)
        self.assertEqual((stamp.version, stamp.template, stamp.template_version),
                         (NEW, TEMPLATE, OLD))
        locale = load_core_locale("en")
        self.assertEqual([c.status for c in template_checks(self.sb.store, locale)], [WARN])
        out = self.cli("update", "--to", NEW_TAG)
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertIn(core_text(keys.UPDATE_PROFILE_LAGS, template=TEMPLATE, profile=OLD,
                                old=NEW, path=Path(".svod/lib/svod/templates/task")),
                      out.stderr)
        self.assertEqual(vendor.read_stamp(self.sb.store).template_version, OLD)
        out = self.cli("update", "--to", NEW_TAG, "--template", TEMPLATE)
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertEqual(vendor.read_stamp(self.sb.store).template_version, NEW)
        self.assertEqual([c.status for c in template_checks(self.sb.store, locale)], [OK])

    def test_unknown_template(self):
        """A VERSION written before the template was recorded: update says so and merges
        nothing."""
        stamp = vendor.read_stamp(self.sb.store)
        vendor.write_stamp(vendor_dir(self.sb.store),
                           vendor.Stamp(stamp.version, stamp.source, stamp.ref))
        out = self.cli("update", "--to", NEW_TAG)
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertIn(core_text(keys.UPDATE_PROFILE_UNKNOWN, command="svod update"), out.stdout)
        self.assertFalse(self.path(NOTES).exists())
        self.assertIsNone(vendor.read_stamp(self.sb.store).template)


if __name__ == "__main__":
    unittest.main()
