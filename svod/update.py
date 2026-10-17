"""svod install and svod update: put a released engine into the store as its own copy.

Everything the flow needs is imported here, before the copy is replaced: a process running the
old copy must not import from the new one halfway.
"""
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__, keys
from .changelog import CHANGELOG_FILE, between
from .git import run_git
from .launcher import run_copy
from .paths import PACKAGE_DIR, vendor_dir
from .profile_merge import CONFLICT, KEPT, MergeError, apply, identify, plan
from .vendor import TEMPLATES_DIR, Stamp, build, copy_template, read_stamp, swap
from .versions import latest_tag, source_version

DEFAULT_SOURCE = "https://github.com/MorinV/SVOD.git"
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
OWN_TEMPLATES = Path(__file__).resolve().parent / TEMPLATES_DIR
COMMAND_INSTALL = "svod install"
COMMAND_UPDATE = "svod update"
FILE_KEYS = {"updated": keys.UPDATE_PROFILE_UPDATED, "added": keys.UPDATE_PROFILE_ADDED,
             "removed": keys.UPDATE_PROFILE_REMOVED, "merged": keys.UPDATE_PROFILE_MERGED_FILE,
             CONFLICT: keys.UPDATE_PROFILE_CONFLICT, KEPT: keys.UPDATE_PROFILE_KEPT}


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


@dataclass(frozen=True)
class ProfilePlan:
    """The template fields of the new VERSION, the merge to apply and what to say before it."""

    template: str | None
    template_version: str | None
    outcomes: tuple = ()
    lines: tuple = ()
    errors: tuple = ()
    merged: bool = False


def kept_plan(stamp, *lines, errors=()):
    """No merge: the template fields of the old VERSION stay as they were."""
    return ProfilePlan(stamp.template, stamp.template_version, (), tuple(lines), tuple(errors))


def merge_base(root, locale, install, stamp, template, tree):
    """(template name, base directory) of the merge, or a ProfilePlan saying why there is none.

    install: the template named, else the one whose profile the store holds unchanged, taken
    from the engine running install or from the new one. update: the template recorded in
    VERSION, or named, taken from the old copy; when the profile was last merged with another
    version than the old copy's, there is no base unless the template is named.
    """
    command = COMMAND_INSTALL if install else COMMAND_UPDATE
    if install:
        homes = [OWN_TEMPLATES, Path(tree) / PACKAGE_DIR / TEMPLATES_DIR]
        if template is None:
            found = identify(root, homes)
            if found is None:
                return kept_plan(stamp, locale.text(keys.UPDATE_PROFILE_UNKNOWN, command=command))
            return found
        base = next((Path(h) / template for h in homes if (Path(h) / template).is_dir()), None)
        return template, base
    name = template or stamp.template
    if name is None:
        return kept_plan(stamp, locale.text(keys.UPDATE_PROFILE_UNKNOWN, command=command))
    if template is None and stamp.template_version not in (None, stamp.version):
        return kept_plan(stamp, errors=[locale.text(
            keys.UPDATE_PROFILE_LAGS, template=name, profile=stamp.template_version,
            old=stamp.version, path=copy_template(root, name).relative_to(root))])
    return name, copy_template(root, name)


def profile_plan(root, locale, install, stamp, template, tree, new, merge):
    """What the profile becomes with the new engine: computed before the copy is replaced,
    while the old template is still there; nothing is written."""
    if not merge:
        return kept_plan(stamp, locale.text(keys.UPDATE_PROFILE_OFF))
    if template is not None and (Path(template).name != template or template in (".", "..")):
        return kept_plan(stamp, errors=[locale.text(keys.UPDATE_PROFILE_NO_TEMPLATE,
                                                    template=template)])
    found = merge_base(root, locale, install, stamp, template, tree)
    if isinstance(found, ProfilePlan):
        return found
    name, base = found
    theirs = Path(tree) / PACKAGE_DIR / TEMPLATES_DIR / name
    if not theirs.is_dir() or base is None or not Path(base).is_dir():
        return kept_plan(stamp, errors=[locale.text(keys.UPDATE_PROFILE_NO_TEMPLATE,
                                                    template=name)])
    if install:
        old = __version__ if Path(base).parent == OWN_TEMPLATES else new
    else:
        old = stamp.template_version or stamp.version
    try:
        outcomes = plan(base, theirs, root, old, new)
    except MergeError as exc:
        return ProfilePlan(name, stamp.template_version,
                           errors=(locale.text(keys.UPDATE_PROFILE_FAILED, reason=exc),))
    return ProfilePlan(name, new, tuple(outcomes), merged=True)


def report_profile(locale, profile, new):
    """Print the merge of the profile: each file touched and the conflicts to resolve."""
    for line in profile.lines:
        say(line)
    for line in profile.errors:
        say(line, error=True)
    if not profile.merged:
        return
    say(locale.text(keys.UPDATE_PROFILE_MERGED, template=profile.template, new=new,
                    count=sum(o.kind != KEPT for o in profile.outcomes)))
    for outcome in profile.outcomes:
        say(f"{NOTE_INDENT}{locale.text(FILE_KEYS[outcome.kind], path=outcome.path)}")
    if any(o.kind == CONFLICT for o in profile.outcomes):
        say(locale.text(keys.UPDATE_PROFILE_RESOLVE), error=True)


def deliver(root, locale, install, source=None, ref=None, template=None, merge=True):
    """Install or replace the copy of the store; return the exit code.

    The new copy is assembled next to .svod and renamed into place, so a failed fetch leaves the
    store as it was. The files the template gave the store are merged three ways (unless merge
    is False), then the new copy migrates and validates the store; nothing is committed.
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
        profile = profile_plan(root, locale, install, stamp, template, tree, new, merge)
        swap(root, build(root, tree, Stamp(new, source, ref, profile.template,
                                           profile.template_version)))
        notes = changelog_text(tree)
    key = keys.UPDATE_INSTALLED if install else keys.UPDATE_UPDATED
    say(locale.text(key, old=old, new=new, ref=ref, path=vendor_dir(root).name))
    apply(root, list(profile.outcomes))
    report_profile(locale, profile, new)
    migrated = run_copy(root, [ROOT_FLAG, str(root), CMD_MIGRATE, SINCE_FLAG, old])
    valid = run_copy(root, [ROOT_FLAG, str(root), CMD_VALIDATE])
    if valid != EXIT_OK:
        say(locale.text(keys.UPDATE_INVALID), error=True)
    report_changes(locale, notes, old, new)
    say(locale.text(keys.UPDATE_NEXT))
    return EXIT_OK if migrated == EXIT_OK and valid == EXIT_OK else EXIT_FINDINGS
