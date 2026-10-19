"""Copy of the engine kept in a store: install, update, migrations, integrity, launcher, notice."""
import datetime as dt
import json
import shutil
import subprocess
import re
import tempfile
import unittest
from pathlib import Path

import task_example as te
from support import (CLI_ENV, CLI_TIMEOUT_SEC, ENCODING, EXIT_FINDINGS, EXIT_OK, EXIT_USAGE,
                     MAIN_BRANCH, REPO_DIR, TempStore, child_env, core_lead, core_text)

import svod
from svod import changelog, keys, migrations, notice, vendor, versions
from svod.config import load_config
from svod.launcher import LAUNCH_ENV, split_argv
from svod.locale import load_core_locale
from svod.paths import lib_dir, package_dir, vendor_dir

OLD = "0.2.0"
NEW = "0.3.0"
NEWER = "0.4.0"
OLD_TAG = f"v{OLD}"
NEW_TAG = f"v{NEW}"
NEWER_TAG = f"v{NEWER}"
SOURCE_DIR = "svod-source"
COPY_MARKER = "[copy 0.3.0]"
ENGINE_BROKEN_LINE = '  engine_broken: "'
LEGACY_FILE = "legacy-notes.md"
RENAMED_FILE = "renamed-notes.md"
MIGRATION_NOTE = f"- {LEGACY_FILE} is renamed to {RENAMED_FILE} by svod update."
EMPTY_REGISTRY = "MIGRATIONS = ()"
TEST_MIGRATION = f'''def rename_legacy(root):
    """Rename the legacy notes of the test store."""
    return rename_file(root, "{LEGACY_FILE}", "{RENAMED_FILE}")


MIGRATIONS = (Migration("{NEW}", rename_legacy),)'''
RELEASE_030 = f"""## [{NEW}] - 2026-10-06

### Changed

- Test release.

### Migration

{MIGRATION_NOTE}

"""
UNRELEASED = "## [Unreleased]\n\n"
VERSION_LINE = '__version__ = "{version}"'
COMMITTER = ("release@example.com", "Release")
PROJECT_ENV = "CLAUDE_PROJECT_DIR"
SESSION_ENV = (PROJECT_ENV, LAUNCH_ENV)
COPIES_DIR = "copies"
CLI_FILE = "lib/svod/cli.py"
UPDATE_COMMAND = "svod update"
STAGING_GLOB = f"{vendor.VENDOR_DIR}-*"
MISSING_SOURCE = "no-such-source"
MISSING_REF = "v9.9.9"
DAY = dt.timedelta(days=1)
HOUR = dt.timedelta(hours=1)
NOW = dt.datetime(2026, 10, 5, 12, 0, tzinfo=dt.timezone.utc)
SKILL = "svod-pipeline"
CLAUDE_SETUP = REPO_DIR / "integrations" / "setup-claude.sh"
PYPROJECT = REPO_DIR / "pyproject.toml"
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*(.+?)\s*$', re.MULTILINE)
PYPROJECT_VERSION_ATTR = '{ attr = "svod.__version__" }'


def source_files(target):
    """Copy the engine (its packaged skills included) and the changelog of this repository."""
    skip = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(REPO_DIR / "svod", target / "svod", ignore=skip)
    shutil.copy(REPO_DIR / "CHANGELOG.md", target / "CHANGELOG.md")


def replace_in(path, old, new):
    """Replace one text in a file, failing when it is not there."""
    text = path.read_text(encoding=ENCODING)
    if old not in text:
        raise AssertionError(f"{old!r} not in {path}")
    path.write_text(text.replace(old, new, 1), encoding=ENCODING)


def make_source(sb):
    """Git repository of Svod releases v0.2.0 and v0.3.0, built from this tree.

    v0.3.0 carries a test migration, a changelog release with a migration note and a marker in
    the engine-broken text of its English locale.
    """
    source = sb.root / SOURCE_DIR
    source.mkdir()
    sb.git(sb.root, "init", "-q", "-b", MAIN_BRANCH, str(source))
    source_files(source)
    replace_in(source / "svod" / "__init__.py", VERSION_LINE.format(version=svod.__version__),
               VERSION_LINE.format(version=OLD))
    sb.commit(source, OLD, author=COMMITTER)
    sb.git(source, "tag", OLD_TAG)
    replace_in(source / "svod" / "__init__.py", VERSION_LINE.format(version=OLD),
               VERSION_LINE.format(version=NEW))
    replace_in(source / "svod" / "migrations.py", EMPTY_REGISTRY, TEST_MIGRATION)
    replace_in(source / "svod" / "locale" / "en.yaml", ENGINE_BROKEN_LINE,
               f"{ENGINE_BROKEN_LINE}{COPY_MARKER} ")
    replace_in(source / "CHANGELOG.md", UNRELEASED, UNRELEASED + RELEASE_030)
    sb.commit(source, NEW, author=COMMITTER)
    sb.git(source, "tag", NEW_TAG)
    return source


def session_drop(extra):
    """Session variables a run does not inherit unless the test sets them."""
    return tuple(name for name in SESSION_ENV if name not in extra)


def clean_env(sb, **extra):
    """Environment of a child process: isolated git, no session project, no hand-over mark."""
    env = child_env(**sb.env, **CLI_ENV, **extra)
    for name in session_drop(extra):
        env.pop(name, None)
    return env


def cli(sb, *args, cwd=None, stdin=None, **extra):
    """Run the CLI in this process with no session project and no hand-over mark."""
    return sb.cli(*args, cwd=cwd, stdin=stdin, drop=session_drop(extra), **extra)


def cli_process(sb, *args, cwd=None, stdin=None, **extra):
    """Run the installed CLI as a black box in a child process, for the launcher tests."""
    return sb.cli_process(*args, cwd=cwd, stdin=stdin, drop=session_drop(extra), **extra)


def append_line(path):
    """Append an empty line to a file, a change that keeps Python code working."""
    with open(path, "a", encoding=ENCODING) as fh:
        fh.write("\n")


def snapshot(root):
    """MANIFEST and VERSION of the copy of a store, None for each one absent."""
    found = []
    for name in (vendor.MANIFEST_FILE, vendor.VERSION_FILE):
        path = vendor_dir(root) / name
        found.append(path.read_text(encoding=ENCODING) if path.is_file() else None)
    return tuple(found)


class VersionsTest(unittest.TestCase):
    """Semantic versions and release tags."""

    def test_compare(self):
        """Newer, ranges and tags follow semantic order, not text order."""
        cases = (
            (versions.is_newer, ("0.10.0", "0.9.0"), True),
            (versions.is_newer, ("0.2.0", "0.2.0"), False),
            (versions.is_newer, (None, "0.2.0"), False),
            (versions.is_newer, ("1.0", "0.2.0"), False),
            (versions.in_range, ("0.3.0", "0.2.0", "0.3.0"), True),
            (versions.in_range, ("0.2.0", "0.2.0", "0.3.0"), False),
            (versions.in_range, ("0.4.0", "0.2.0", "0.3.0"), False),
            (versions.in_range, ("0.1.0", None, "0.3.0"), True),
            (versions.tag_version, ("v1.2.3",), "1.2.3"),
            (versions.tag_version, ("1.2.3",), None),
            (versions.tag_version, ("v1.2",), None),
        )
        for func, args, expected in cases:
            with self.subTest(func=func.__name__, args=args):
                self.assertEqual(func(*args), expected)

    def test_latest_tag(self):
        """The newest vX.Y.Z of ls-remote output; other tags are ignored."""
        line = "{sha}\trefs/tags/{tag}"
        cases = (
            (("v0.2.0", "v0.10.0", "v0.9.1"), "v0.10.0"),
            (("v0.2.0", "release", "v1.0.0-rc1"), "v0.2.0"),
            ((), None),
        )
        for tags, expected in cases:
            with self.subTest(tags=tags):
                output = "\n".join(line.format(sha="0" * 40, tag=t) for t in tags)
                self.assertEqual(versions.latest_tag(output), expected)

    def test_package_version_matches_pyproject(self):
        """The version is declared once, in svod/__init__.py, and the package metadata carries it.

        pyproject.toml has no version of its own: its only version line takes it from
        svod.__version__ (checked always). The metadata importlib.metadata.version("svod")
        returns is then compared with svod.__version__, but only when that metadata was built
        from this tree: an editable install whose direct_url.json names this directory, or an
        install whose svod/__init__.py is the one imported here. Metadata of an install from
        another checkout says nothing about this tree, so the comparison is skipped with the
        place it came from rather than passed or failed on someone else's version. CI installs
        this checkout with pip install -e ., so there it always runs. An editable install of
        this tree made before a version bump keeps the old metadata until it is reinstalled;
        that fails, because the installed version really is stale.
        """
        import importlib.metadata as metadata
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        declared = PYPROJECT_VERSION_RE.findall(PYPROJECT.read_text(encoding=ENCODING))
        self.assertEqual(declared, [PYPROJECT_VERSION_ATTR])
        try:
            dist = metadata.distribution("svod")
        except metadata.PackageNotFoundError:
            self.skipTest("svod is not installed: no package metadata to compare with")
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        url = urlparse(direct.get("url", ""))
        editable_root = (Path(url2pathname(url.path)).resolve()
                         if url.scheme == "file" and direct.get("dir_info", {}).get("editable")
                         else None)
        located = Path(dist.locate_file("svod/__init__.py")).resolve()
        if editable_root != REPO_DIR.resolve() and located != Path(svod.__file__).resolve():
            origin = editable_root or located.parent
            self.skipTest(f"installed svod {metadata.version('svod')} comes from {origin}, "
                          f"not from {REPO_DIR}; pip install -e . here to compare")
        self.assertEqual(metadata.version("svod"), svod.__version__,
                         "package metadata is stale: pip install -e . again")


CHANGELOG = f"""# Changelog

## [Unreleased]

## [0.4.0] - 2026-11-01

### Migration

- Rename the key a to b by hand.

## [{NEW}] - 2026-10-06

### Added

- Something.

### Migration

none

## [{OLD}] - 2026-10-05

### Migration

- none.
"""


class ChangelogTest(unittest.TestCase):
    """Releases between two versions and their migration notes."""

    def test_between(self):
        """Releases after old up to new, in the order written, with their notes."""
        cases = (
            (OLD, NEWER, ["0.4.0", NEW], {"0.4.0": ["- Rename the key a to b by hand."], NEW: []}),
            (OLD, NEW, [NEW], {NEW: []}),
            (NEW, NEW, [], {}),
            (None, OLD, [OLD], {OLD: []}),
        )
        for old, new, expected, notes in cases:
            with self.subTest(old=old, new=new):
                found = changelog.between(CHANGELOG, old, new)
                self.assertEqual([r.version for r in found], expected)
                self.assertEqual({r.version: r.migration() for r in found}, notes)
                for release in found:
                    self.assertTrue(release.lines[0].startswith(f"## [{release.version}]"))
                    self.assertTrue(release.lines[-1].strip())

    def test_repository_changelog(self):
        """The changelog of this repository has the current release with a Migration section."""
        text = (REPO_DIR / changelog.CHANGELOG_FILE).read_text(encoding=ENCODING)
        found = {r.version: r for r in changelog.releases(text)}
        self.assertIn(svod.__version__, found)
        for release in found.values():
            with self.subTest(version=release.version):
                self.assertIn(f"### {changelog.MIGRATION_HEADING}", release.lines)


def migration(version, log):
    """Test migration recording its version in log."""
    def apply(root):
        log.append(version)
        return []
    return migrations.Migration(version, apply)


class MigrationsTest(unittest.TestCase):
    """The registry applies the migrations after the old version up to the new one."""

    def test_pending(self):
        """Only versions in (old, new], oldest first, whatever the registry order."""
        cases = (
            ("0.1.0", "0.3.0", ["0.2.0", "0.2.1", "0.3.0"]),
            ("0.2.0", "0.2.1", ["0.2.1"]),
            ("0.3.0", "0.3.0", []),
            ("0.3.0", "0.1.0", []),
        )
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                log = []
                registry = [migration(v, log) for v in ("0.3.0", "0.2.0", "0.4.0", "0.2.1")]
                applied = migrations.apply(Path(tempfile.gettempdir()), old, new, registry)
                self.assertEqual(log, expected)
                self.assertEqual([version for version, _ in applied], expected)

    def test_shipped_registry(self):
        """Release 0.2.0 ships no migration."""
        self.assertEqual(migrations.pending("0.1.0", svod.__version__), [])

    def test_helpers(self):
        """Key and file renames change only what they name and report it."""
        root = Path(tempfile.mkdtemp(prefix="svod-migrate-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        config = "locale: en\nold_key: 1\nnested:\n  old_key: 2\n"
        (root / "svod.yaml").write_text(config, encoding=ENCODING)
        (root / "a.md").write_text("a", encoding=ENCODING)
        cases = (
            (lambda: migrations.rename_config_key(root, "old_key", "new_key"),
             [migrations.Change("migrate.renamed_key",
                                {"old": "old_key", "new": "new_key", "file": "svod.yaml"})]),
            (lambda: migrations.rename_config_key(root, "absent", "x"), []),
            (lambda: migrations.rename_file(root, "a.md", "docs/b.md"),
             [migrations.Change("migrate.renamed_file", {"old": "a.md", "new": "docs/b.md"})]),
            (lambda: migrations.rename_file(root, "a.md", "docs/b.md"), []),
        )
        for index, (call, expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(call(), expected)
        self.assertEqual((root / "svod.yaml").read_text(encoding=ENCODING),
                         "locale: en\nnew_key: 1\nnested:\n  old_key: 2\n")
        self.assertTrue((root / "docs" / "b.md").is_file())
        locale = load_core_locale("en")
        for change in cases[0][1] + cases[2][1]:
            with self.subTest(key=change.key):
                self.assertTrue(locale.text(change.key, **change.facts))


SHARED_SOURCE = {}


def shared_source():
    """(TempStore holding the source, the source) built once for the module."""
    if not SHARED_SOURCE:
        origin = TempStore()
        SHARED_SOURCE.update(origin=origin, source=make_source(origin))
    return SHARED_SOURCE["origin"], SHARED_SOURCE["source"]


def tearDownModule():
    """Remove the shared source and the copies saved from it."""
    if SHARED_SOURCE:
        SHARED_SOURCE.pop("origin").cleanup()
        SHARED_SOURCE.clear()


class SourceTestCase(unittest.TestCase):
    """A Svod source repository with two releases, shared by the tests of the module."""

    @classmethod
    def setUpClass(cls):
        """Take the source, built once."""
        cls.origin, cls.source = shared_source()

    def setUp(self):
        """A fresh store from the example, in git."""
        self.sb = te.make_task_store()
        self.addCleanup(self.sb.cleanup)

    def install(self, ref=OLD_TAG):
        """Install the given release into the store, failing the test when it does not."""
        out = cli(self.sb, "install", "--from", str(self.source), "--to", ref)
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        return out

    def restore(self, ref=OLD_TAG):
        """Put a pristine copy of the release into the store, installing it once per class.

        A copy does not depend on the store it was built in, so later tests reuse it instead
        of cloning and validating again.
        """
        saved = self.origin.root / COPIES_DIR / ref
        shutil.rmtree(vendor_dir(self.sb.store), ignore_errors=True)
        if not saved.is_dir():
            self.install(ref)
            shutil.copytree(vendor_dir(self.sb.store), saved)
            return
        shutil.copytree(saved, vendor_dir(self.sb.store))


class DeliveryTest(SourceTestCase):
    """install and update between two releases of a source repository."""

    def test_install_then_update(self):
        """The copy, VERSION and MANIFEST; migration, changelog and notes on update; no commit."""
        head = self.sb.git(self.sb.store, "rev-parse", "HEAD")
        self.sb.write(LEGACY_FILE, "notes\n")
        out = self.install()
        self.assertIn(core_text(keys.UPDATE_INSTALLED, new=OLD, ref=OLD_TAG,
                                path=vendor.VENDOR_DIR), out.stdout)
        stamp = vendor.read_stamp(self.sb.store)
        self.assertEqual(stamp, vendor.Stamp(OLD, str(self.source.resolve()), OLD_TAG, "task", OLD))
        self.assertTrue((package_dir(self.sb.store) / "locale" / "en.yaml").is_file())
        self.assertTrue((vendor_dir(self.sb.store) / "skills" / SKILL / "SKILL.md").is_file())
        self.assertFalse((vendor_dir(self.sb.store) / "integrations").exists())
        self.assertEqual(vendor.changed_files(vendor_dir(self.sb.store)), [])
        manifest = (vendor_dir(self.sb.store) / vendor.MANIFEST_FILE).read_text(encoding=ENCODING)
        paths = [line.split("  ", 1)[1] for line in manifest.splitlines()]
        self.assertEqual(paths, sorted(paths))
        self.assertIn("lib/svod/cli.py", paths)

        out = cli(self.sb, "update")
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertEqual(vendor.read_stamp(self.sb.store).version, NEW)
        self.assertEqual(vendor.read_stamp(self.sb.store).ref, NEW_TAG)
        for expected in (core_text(keys.UPDATE_UPDATED, old=OLD, new=NEW, ref=NEW_TAG,
                                   path=vendor.VENDOR_DIR),
                         core_text(keys.MIGRATE_VERSION, version=NEW),
                         core_text(keys.MIGRATE_RENAMED_FILE, old=LEGACY_FILE, new=RENAMED_FILE),
                         core_lead(keys.VALIDATE_OK),
                         core_text(keys.UPDATE_CHANGELOG, old=OLD, new=NEW),
                         f"## [{NEW}]", MIGRATION_NOTE, core_text(keys.UPDATE_NEXT)):
            with self.subTest(expected=expected):
                self.assertIn(expected, out.stdout)
        self.assertNotIn(f"## [{OLD}]", out.stdout)
        self.assertFalse((self.sb.store / LEGACY_FILE).exists())
        self.assertTrue((self.sb.store / RENAMED_FILE).is_file())
        self.assertEqual(self.sb.git(self.sb.store, "rev-parse", "HEAD"), head)
        self.assertEqual(list(self.sb.store.glob(STAGING_GLOB)), [])

    def test_default_ref_is_newest_tag(self):
        """Without --to the newest release tag is taken."""
        out = cli(self.sb, "install", "--from", str(self.source))
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(vendor.read_stamp(self.sb.store).ref, NEW_TAG)

    def test_refusals_and_failures_leave_the_store(self):
        """A refused command or a failed fetch changes nothing, the copy included."""
        cases = (
            (False, ("update",), EXIT_FINDINGS, core_text(keys.UPDATE_MISSING)),
            (False, ("install", "--from", MISSING_SOURCE), EXIT_USAGE, MISSING_SOURCE),
            (False, ("install", "--from", "{source}", "--to", MISSING_REF), EXIT_USAGE,
             MISSING_REF),
            (True, ("install", "--from", "{source}"), EXIT_FINDINGS,
             core_text(keys.UPDATE_EXISTS)),
            (True, ("update", "--to", MISSING_REF), EXIT_USAGE, MISSING_REF),
            (True, ("update", "--from", MISSING_SOURCE, "--to", NEW_TAG), EXIT_USAGE,
             MISSING_SOURCE),
        )
        for installed, args, code, message in cases:
            with self.subTest(installed=installed, args=args):
                shutil.rmtree(vendor_dir(self.sb.store), ignore_errors=True)
                if installed:
                    self.restore()
                before = snapshot(self.sb.store)
                out = cli(self.sb, *[a.format(source=self.source) for a in args])
                self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                self.assertIn(message, out.stderr)
                self.assertEqual(snapshot(self.sb.store), before)
                self.assertEqual(list(self.sb.store.glob(STAGING_GLOB)), [])


class ManifestTest(SourceTestCase):
    """validate checks the copy against its MANIFEST."""

    def test_modified_copy(self):
        """Changed, added or removed files are named; byte-code is not."""
        cli_file = CLI_FILE
        extra = "lib/svod/extra.py"
        skill = f"skills/{SKILL}/SKILL.md"
        cases = (
            ("clean", lambda d: None, None),
            ("byte-code", lambda d: (d / "lib/svod/__pycache__").mkdir() or
             (d / "lib/svod/__pycache__/cli.pyc").write_bytes(b"0"), None),
            ("changed", lambda d: append_line(d / cli_file), cli_file),
            ("added", lambda d: (d / extra).write_text("x", encoding=ENCODING), extra),
            ("removed", lambda d: (d / skill).unlink(), skill),
            ("manifest only", lambda d: (shutil.rmtree(d / vendor.LIB_DIR),
                                        shutil.rmtree(d / vendor.SKILLS_DIR),
                                        (d / vendor.VERSION_FILE).unlink()), cli_file),
            ("no manifest", lambda d: (d / vendor.MANIFEST_FILE).unlink(), vendor.MANIFEST_FILE),
        )
        for name, spoil, named in cases:
            with self.subTest(case=name):
                self.restore()
                log = self.sb.write(".svod/package-runs/run-1/step.log", "retained\n")
                spoil(vendor_dir(self.sb.store))
                out = cli(self.sb, "validate")
                self.assertEqual(log.read_text(encoding=ENCODING), "retained\n")
                if named is None:
                    self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                    continue
                self.assertEqual(out.returncode, EXIT_FINDINGS)
                self.assertIn(named, out.stderr)
                self.assertIn(UPDATE_COMMAND, out.stderr)

    def test_runtime_only_directory_validates(self):
        """Package run logs do not imply an installed engine or require a MANIFEST."""
        log = self.sb.write(".svod/package-runs/run-1/step.log", "retained runtime log\n")
        before = log.read_bytes()
        out = cli_process(self.sb, "validate")
        self.assertEqual(out.returncode, EXIT_OK, out.stdout + out.stderr)
        self.assertNotIn(vendor.MANIFEST_FILE, out.stderr)
        self.assertEqual(log.read_bytes(), before)
        self.assertFalse((vendor_dir(self.sb.store) / vendor.MANIFEST_FILE).exists())

    def test_incomplete_copy_requires_manifest(self):
        """Even partial installation indicators require integrity metadata beside runtime logs."""
        for name in (*vendor.COVERED, vendor.VERSION_FILE):
            with self.subTest(indicator=name):
                directory = vendor_dir(self.sb.store)
                shutil.rmtree(directory, ignore_errors=True)
                log = self.sb.write(".svod/package-runs/run-1/step.log", "retained\n")
                indicator = directory / name
                if name in vendor.COVERED:
                    indicator.mkdir()
                else:
                    indicator.write_text("version: incomplete\n", encoding=ENCODING)
                out = cli_process(self.sb, "validate")
                self.assertEqual(out.returncode, EXIT_FINDINGS, out.stdout + out.stderr)
                self.assertIn(vendor.MANIFEST_FILE, out.stderr)
                self.assertIn(UPDATE_COMMAND, out.stderr)
                self.assertEqual(log.read_text(encoding=ENCODING), "retained\n")

    def test_no_copy_no_check(self):
        """A store without .svod has nothing to check."""
        self.assertEqual(vendor.copy_errors(self.sb.store), [])


class SplitArgvTest(unittest.TestCase):
    """The launcher reads the store and the command from the arguments, without a store."""

    def test_split_argv(self):
        """The --root value and the command, whatever the global options before it."""
        cases = (
            (["status", "X"], (None, "status")),
            (["--root", "/s", "hook", "prompt"], ("/s", "hook")),
            (["--root=/s", "validate"], ("/s", "validate")),
            (["--version"], (None, None)),
            (["--root"], (None, None)),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(split_argv(argv), expected)


class LauncherTest(SourceTestCase):
    """The installed CLI hands commands over to the copy of the store."""

    def test_hand_over(self):
        """Inside a store with a copy the copy runs, once; elsewhere the installed engine runs."""
        self.restore(NEW_TAG)
        outside = self.sb.root / "home"
        lib = str(lib_dir(self.sb.store).resolve())
        cases = (
            ("store", self.sb.store, {}, NEW),
            ("subdirectory", self.sb.store / "profile", {}, NEW),
            ("--root", outside, {"root": True}, NEW),
            ("handed over already", self.sb.store, {LAUNCH_ENV: lib}, svod.__version__),
            ("outside", outside, {}, svod.__version__),
        )
        for name, cwd, extra, version in cases:
            with self.subTest(case=name):
                args = ["--root", str(self.sb.store)] if extra.pop("root", False) else []
                out = cli(self.sb, *args, "--version", cwd=cwd, **extra)
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                self.assertEqual(out.stdout.strip(), f"svod {version}")

    def test_modified_copy_is_not_run(self):
        """A copy differing from its MANIFEST does not run: the installed engine does, and says so.

        A child process: `python -m svod.cli` is started as an agent starts it, importing svod
        through PYTHONPATH, and the refusal must reach the real stderr of that process.
        """
        self.restore(NEW_TAG)
        append_line(vendor_dir(self.sb.store) / CLI_FILE)
        out = cli_process(self.sb, "--version")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(out.stdout.strip(), f"svod {svod.__version__}")
        self.assertIn(CLI_FILE, out.stderr)

    def test_hook_hands_over_with_stdin(self):
        """A hook finds the store in the event and the copy reads the same event.

        A child process: the event is read once from the real stdin of the installed CLI and must
        reach the copy, a second process, intact.
        """
        self.restore(NEW_TAG)
        te.set_config(self.sb, unknown_key="1")
        outside = self.sb.root / "home"
        in_store = json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.sb.store)})
        elsewhere = json.dumps({"hook_event_name": "SessionStart", "cwd": str(outside)})
        cases = (
            ("event cwd", in_store, {}, [], True),
            ("project directory", elsewhere, {PROJECT_ENV: str(self.sb.store)}, [], True),
            ("fallback root", elsewhere, {}, ["--root", str(self.sb.store)], True),
            ("no store", elsewhere, {}, [], False),
        )
        for name, sent, extra, args, copied in cases:
            with self.subTest(case=name):
                out = cli_process(self.sb, *args, "hook", "session-start", cwd=outside,
                                  stdin=sent, **extra)
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                self.assertEqual(COPY_MARKER in out.stdout, copied, out.stdout)
                if copied:
                    self.assertIn("unknown_key", out.stdout)
                else:
                    self.assertEqual(out.stdout, "")


class NoticeTest(unittest.TestCase):
    """A newer release than the copy is announced, checked at most once a day."""

    def setUp(self):
        """A store in git with a copy of version 0.2.0 from a source tagged up to 0.3.0."""
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)
        self.sb.init_git(remote=False)
        self.source = self.sb.root / SOURCE_DIR
        self.sb.init_git(self.source, remote=False)
        for tag in (OLD_TAG, NEW_TAG):
            self.sb.git(self.source, "tag", tag)
        package_dir(self.sb.store).mkdir(parents=True)
        vendor.write_stamp(vendor_dir(self.sb.store), vendor.Stamp(OLD, str(self.source), OLD_TAG))
        self.locale = load_core_locale("en")

    def notice(self, at, update_check=True):
        """The notice for the store at the given time."""
        config = load_config(self.sb.store, local=False)
        if not update_check:
            te.set_config(self.sb, update_check="false")
            config = load_config(self.sb.store, local=False)
            self.assertFalse(config.update_check)
        return notice.update_notice(config, self.locale, at)

    def cache(self):
        """The cached check, empty when absent."""
        git_dir = Path(self.sb.git(self.sb.store, "rev-parse", "--absolute-git-dir"))
        return notice.read_cache(git_dir / notice.CACHE_FILE)

    def test_once_a_day(self):
        """The first check reads the source; later ones within a day read the cache."""
        available = core_text(keys.UPDATE_AVAILABLE, latest=NEW, current=OLD)
        newer = core_text(keys.UPDATE_AVAILABLE, latest=NEWER, current=OLD)
        moved = self.sb.root / "moved"
        steps = (
            ("first check", lambda: None, NOW, available, NEW),
            ("cached", lambda: self.sb.git(self.source, "tag", NEWER_TAG), NOW + HOUR, available,
             NEW),
            ("next day", lambda: None, NOW + DAY + HOUR, newer, NEWER),
            ("offline", lambda: self.source.rename(moved), NOW + 2 * DAY + 2 * HOUR, newer,
             NEWER),
        )
        for name, change, at, expected, cached in steps:
            with self.subTest(step=name):
                change()
                self.assertEqual(self.notice(at), expected)
                self.assertEqual(self.cache().get(notice.FIELD_LATEST), cached)

    def test_silence(self):
        """No notice when off, unreachable, up to date, without a copy or outside git."""
        cases = (
            ("switched off", lambda: None, False),
            ("unreachable", lambda: shutil.rmtree(self.source), True),
            ("up to date", lambda: vendor.write_stamp(
                vendor_dir(self.sb.store), vendor.Stamp(NEW, str(self.source), NEW_TAG)), True),
            ("no copy", lambda: shutil.rmtree(package_dir(self.sb.store)), True),
            ("outside git", lambda: shutil.rmtree(self.sb.store / ".git"), True),
        )
        for name, change, update_check in cases:
            with self.subTest(case=name):
                self.setUp()
                change()
                self.assertIsNone(self.notice(NOW, update_check))

    def test_with_notice(self):
        """The notice goes first, apart from the summary."""
        cases = (
            (["a"], None, ["a"]),
            ([], "n", ["n"]),
            (["a"], "n", ["n", "", "a"]),
        )
        for lines, text, expected in cases:
            with self.subTest(lines=lines, text=text):
                self.assertEqual(notice.with_notice(lines, text), expected)


class SetupSkillsTest(SourceTestCase):
    """The setup scripts link the skills of the copy of the store when it has one."""

    def test_skill_links(self):
        """With a copy the skill links point into .svod/skills, without one into the repository.

        A child process: the setup script is bash and finds svod through PYTHONPATH.
        """
        cases = (
            ("copy", True, vendor_dir(self.sb.store) / "skills" / SKILL),
            ("repository", False, REPO_DIR / "svod" / "skills" / SKILL),
        )
        for name, installed, target in cases:
            with self.subTest(case=name):
                shutil.rmtree(vendor_dir(self.sb.store), ignore_errors=True)
                if installed:
                    self.restore()
                home = Path(tempfile.mkdtemp(prefix="svod-claude-"))
                self.addCleanup(shutil.rmtree, home, ignore_errors=True)
                out = subprocess.run(["bash", str(CLAUDE_SETUP), str(self.sb.store)],
                                     env=clean_env(self.sb, CLAUDE_CONFIG_DIR=str(home)),
                                     capture_output=True, text=True, encoding=ENCODING,
                                     timeout=CLI_TIMEOUT_SEC)
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                link = home / "skills" / SKILL
                self.assertEqual(link.resolve(), target.resolve())


if __name__ == "__main__":
    unittest.main()
