"""The copy of the engine kept in a store: layout, VERSION, MANIFEST and the integrity check."""
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import LoadError
from .paths import LIB_DIR, PACKAGE_DIR, VENDOR_DIR, package_dir, vendor_dir
from .yamlio import dump_yaml, read_yaml

SKILLS_DIR = "skills"
SKILLS_SOURCE = Path(PACKAGE_DIR) / SKILLS_DIR
# Where the skills of older sources lie, for svod update --to an earlier release: 0.4 and 0.5
# kept them in the local template, 0.3 at the root of the repository.
LEGACY_SKILLS = (Path(PACKAGE_DIR) / "templates" / "local" / SKILLS_DIR, Path(SKILLS_DIR))
VERSION_FILE = "VERSION"
MANIFEST_FILE = "MANIFEST"
IGNORE_FILE = ".gitignore"
IGNORED_DIR = "__pycache__"
IGNORED_SUFFIXES = (".pyc", ".pyo")
IGNORE_TEXT = f"{IGNORED_DIR}/\n"
COVERED = (LIB_DIR, SKILLS_DIR)
FIELD_VERSION = "version"
FIELD_SOURCE = "source"
FIELD_REF = "ref"
ENCODING = "utf-8"
MANIFEST_SEPARATOR = "  "
CHUNK = 1 << 16
STAGING_PREFIX = f"{VENDOR_DIR}-new-"
BACKUP_PREFIX = f"{VENDOR_DIR}-old-"
LIST_SEPARATOR = ", "
MODIFIED = "vendored copy modified: {files}; run svod update --to {ref} to restore"
UNKNOWN_REF = "<ref>"
NO_MANIFEST = "vendored copy has no {manifest}: run svod update to restore"


@dataclass(frozen=True)
class Stamp:
    """What VERSION records: the engine version, where it came from and the ref taken."""

    version: str | None
    source: str | None
    ref: str | None


def has_copy(root):
    """Whether the store carries a copy of the engine."""
    return package_dir(root).is_dir()


def read_stamp(root):
    """VERSION of the copy, with empty fields when absent or unreadable."""
    try:
        data = read_yaml(vendor_dir(root) / VERSION_FILE)
    except (OSError, LoadError):
        data = None
    data = data if isinstance(data, dict) else {}
    values = [data.get(f) for f in (FIELD_VERSION, FIELD_SOURCE, FIELD_REF)]
    return Stamp(*[str(v) if v is not None else None for v in values])


def write_stamp(directory, stamp):
    """Write VERSION into a copy directory."""
    data = {FIELD_VERSION: stamp.version, FIELD_SOURCE: stamp.source, FIELD_REF: stamp.ref}
    (Path(directory) / VERSION_FILE).write_text(dump_yaml(data), encoding=ENCODING)


def ignored(path):
    """Whether a file is a byte-code artefact that never belongs to the copy."""
    return IGNORED_DIR in path.parts or path.suffix in IGNORED_SUFFIXES


def sha256(path):
    """Hex sha256 of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def covered_files(directory):
    """POSIX paths, relative to the copy directory, of every file under lib/ and skills/."""
    directory = Path(directory)
    found = []
    for name in COVERED:
        base = directory / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(directory)
            if (path.is_file() or path.is_symlink()) and not ignored(rel):
                found.append(rel.as_posix())
    return sorted(found)


def digests(directory):
    """Mapping of every covered file to its sha256."""
    directory = Path(directory)
    return {rel: sha256(directory / rel) for rel in covered_files(directory)}


def write_manifest(directory):
    """Write MANIFEST: one sha256 and path per covered file, sorted by path."""
    lines = [f"{sha}{MANIFEST_SEPARATOR}{rel}" for rel, sha in sorted(digests(directory).items())]
    (Path(directory) / MANIFEST_FILE).write_text("".join(f"{line}\n" for line in lines),
                                                 encoding=ENCODING)


def read_manifest(directory):
    """Mapping of path to sha256 recorded in MANIFEST, or None when it is absent."""
    try:
        text = (Path(directory) / MANIFEST_FILE).read_text(encoding=ENCODING)
    except OSError:
        return None
    recorded = {}
    for line in text.splitlines():
        sha, _, rel = line.partition(MANIFEST_SEPARATOR)
        if rel:
            recorded[rel] = sha
    return recorded


def changed_files(directory):
    """Sorted files of the copy that differ from MANIFEST: changed, added or removed.

    None when MANIFEST is absent.
    """
    recorded = read_manifest(directory)
    if recorded is None:
        return None
    present = digests(directory)
    return sorted(rel for rel in set(recorded) | set(present)
                  if recorded.get(rel) != present.get(rel))


def copy_errors(root):
    """Validation errors of the copy of the store; none without a copy."""
    directory = vendor_dir(root)
    if not directory.is_dir():
        return []
    changed = changed_files(directory)
    if changed is None:
        return [NO_MANIFEST.format(manifest=MANIFEST_FILE)]
    if not changed:
        return []
    ref = read_stamp(root).ref or UNKNOWN_REF
    return [MODIFIED.format(files=LIST_SEPARATOR.join(changed), ref=ref)]


def build(root, tree, stamp):
    """Assemble a new copy from a source tree in a staging directory next to .svod; return it."""
    staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
    try:
        skip = shutil.ignore_patterns(IGNORED_DIR, *[f"*{s}" for s in IGNORED_SUFFIXES])
        shutil.copytree(Path(tree) / PACKAGE_DIR, staging / LIB_DIR / PACKAGE_DIR, ignore=skip)
        skills = next((Path(tree) / d for d in (SKILLS_SOURCE, *LEGACY_SKILLS)
                       if (Path(tree) / d).is_dir()), None)
        if skills is not None:
            shutil.copytree(skills, staging / SKILLS_DIR, ignore=skip)
        write_stamp(staging, stamp)
        (staging / IGNORE_FILE).write_text(IGNORE_TEXT, encoding=ENCODING)
        write_manifest(staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def swap(root, staging):
    """Put the staged copy in place of .svod by renames, the old copy kept until it succeeds."""
    target = vendor_dir(root)
    backup = None
    if target.exists():
        backup = Path(tempfile.mkdtemp(prefix=BACKUP_PREFIX, dir=root))
        os.rmdir(backup)
        os.rename(target, backup)
    try:
        os.rename(staging, target)
    except BaseException:
        if backup is not None:
            os.rename(backup, target)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)
