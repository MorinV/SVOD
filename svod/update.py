"""svod install and svod update: put a released engine into the store as its own copy.

Everything the flow needs is imported here, before the copy is replaced: a process running the
old copy must not import from the new one halfway.
"""
import sys
import tempfile
from pathlib import Path

from . import __version__, keys
from .changelog import CHANGELOG_FILE, between
from .git import run_git
from .launcher import run_copy
from .paths import vendor_dir
from .vendor import Stamp, build, read_stamp, swap
from .versions import latest_tag, source_version

DEFAULT_SOURCE = "https://github.com/OWNER/svod.git"
REMOTE_TIMEOUT_SEC = 60
CLONE_TIMEOUT_SEC = 600
SOURCE_PREFIX = "svod-source-"
TREE_DIR = "tree"
ENCODING = "utf-8"
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
CMD_MIGRATE = "migrate"
CMD_VALIDATE = "validate"
SINCE_FLAG = "--since"
ROOT_FLAG = "--root"
NOTE_INDENT = "  "


def resolved_source(raw):
    """A local path as an absolute path, anything else as given."""
    path = Path(raw).expanduser()
    return str(path.resolve()) if path.exists() else raw


def say(text, error=False):
    """Print a line to stdout, or to stderr for an error."""
    print(text, file=sys.stderr if error else sys.stdout)


def default_ref(root, locale, source):
    """Newest vX.Y.Z tag of the source, or None after saying why there is none."""
    out = run_git(root, "ls-remote", "--tags", "--refs", source, timeout=REMOTE_TIMEOUT_SEC)
    if not out.ok:
        say(locale.text(keys.UPDATE_FETCH_FAILED, source=source, reason=out.error), error=True)
        return None
    tag = latest_tag(out.out)
    if tag is None:
        say(locale.text(keys.UPDATE_NO_TAGS, source=source), error=True)
    return tag


def fetch(root, locale, source, ref, workdir):
    """(source tree of ref, its version) cloned into workdir, or None after saying why."""
    tree = Path(workdir) / TREE_DIR
    out = run_git(workdir, "clone", "-q", "--depth", "1", "--branch", ref, source, str(tree),
                  timeout=CLONE_TIMEOUT_SEC)
    if not out.ok:
        say(locale.text(keys.UPDATE_CLONE_FAILED, ref=ref, source=source, reason=out.error),
            error=True)
        return None
    version = source_version(tree)
    if version is None:
        say(locale.text(keys.UPDATE_NOT_SVOD, ref=ref, source=source), error=True)
        return None
    return tree, version


def changelog_text(tree):
    """CHANGELOG.md of a source tree, empty when it has none."""
    try:
        return (Path(tree) / CHANGELOG_FILE).read_text(encoding=ENCODING)
    except OSError:
        return ""


def report_changes(locale, notes, old, new):
    """Print the releases between the versions and the migration notes they carry."""
    found = between(notes, old, new)
    if found:
        say(locale.text(keys.UPDATE_CHANGELOG, old=old, new=new))
        for release in found:
            say("\n".join(release.lines))
            say("")
    manual = [(r.version, r.migration()) for r in found if r.migration()]
    if not manual:
        say(locale.text(keys.UPDATE_MANUAL_NONE))
        return
    say(locale.text(keys.UPDATE_MANUAL))
    for version, lines in manual:
        say(f"{NOTE_INDENT}{version}:")
        for line in lines:
            say(f"{NOTE_INDENT}{line}")


def deliver(root, locale, install, source=None, ref=None):
    """Install or replace the copy of the store; return the exit code.

    The new copy is assembled next to .svod and renamed into place, so a failed fetch leaves the
    store as it was. Then the new copy migrates and validates the store; nothing is committed.
    """
    root = Path(root)
    exists = vendor_dir(root).exists()
    if install and exists:
        say(locale.text(keys.UPDATE_EXISTS), error=True)
        return EXIT_FINDINGS
    if not install and not exists:
        say(locale.text(keys.UPDATE_MISSING), error=True)
        return EXIT_FINDINGS
    stamp = read_stamp(root)
    source = resolved_source(source or stamp.source or DEFAULT_SOURCE)
    ref = ref or default_ref(root, locale, source)
    if ref is None:
        return EXIT_USAGE
    old = (stamp.version if exists else None) or __version__
    with tempfile.TemporaryDirectory(prefix=SOURCE_PREFIX) as workdir:
        fetched = fetch(root, locale, source, ref, workdir)
        if fetched is None:
            return EXIT_USAGE
        tree, new = fetched
        swap(root, build(root, tree, Stamp(new, source, ref)))
        notes = changelog_text(tree)
    key = keys.UPDATE_INSTALLED if install else keys.UPDATE_UPDATED
    say(locale.text(key, old=old, new=new, ref=ref, path=vendor_dir(root).name))
    migrated = run_copy(root, [ROOT_FLAG, str(root), CMD_MIGRATE, SINCE_FLAG, old])
    valid = run_copy(root, [ROOT_FLAG, str(root), CMD_VALIDATE])
    if valid != EXIT_OK:
        say(locale.text(keys.UPDATE_INVALID), error=True)
    report_changes(locale, notes, old, new)
    say(locale.text(keys.UPDATE_NEXT))
    return EXIT_OK if migrated == EXIT_OK and valid == EXIT_OK else EXIT_FINDINGS
