"""Semantic versions of the engine and its release tags."""
import re
from pathlib import Path

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TAG_PREFIX = "v"
TAG_REF_PREFIX = "refs/tags/"
VERSION_ASSIGN_RE = re.compile(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
PACKAGE_INIT = Path("svod") / "__init__.py"
ENCODING = "utf-8"
FIELD_SEPARATOR = "\t"


def parse(version):
    """(major, minor, patch) of a version string, or None when it is not X.Y.Z."""
    found = VERSION_RE.match(str(version or "").strip())
    return tuple(int(part) for part in found.groups()) if found else None


def tag_version(tag):
    """Version named by a release tag vX.Y.Z, or None."""
    if not tag.startswith(TAG_PREFIX):
        return None
    version = tag[len(TAG_PREFIX):]
    return version if parse(version) else None


def is_newer(candidate, current):
    """Whether candidate is a later version than current; False when either is not X.Y.Z."""
    a, b = parse(candidate), parse(current)
    return a is not None and b is not None and a > b


def in_range(version, after, upto):
    """Whether after < version <= upto; after None means no lower bound."""
    value = parse(version)
    low = parse(after) if after else None
    high = parse(upto)
    if value is None or high is None:
        return False
    return (low is None or value > low) and value <= high


def latest_tag(remote_output):
    """Newest vX.Y.Z tag listed by git ls-remote --tags, or None."""
    tags = []
    for line in remote_output.splitlines():
        ref = line.split(FIELD_SEPARATOR)[-1].strip()
        if not ref.startswith(TAG_REF_PREFIX):
            continue
        tag = ref[len(TAG_REF_PREFIX):]
        if tag_version(tag):
            tags.append(tag)
    return max(tags, key=lambda t: parse(tag_version(t)), default=None)


def source_version(tree):
    """Engine version declared in svod/__init__.py of a source tree, or None."""
    path = Path(tree) / PACKAGE_INIT
    try:
        found = VERSION_ASSIGN_RE.search(path.read_text(encoding=ENCODING))
    except OSError:
        return None
    return found.group(1) if found and parse(found.group(1)) else None
