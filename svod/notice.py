"""Notice of a newer engine release for a store that keeps its own copy, checked at most daily."""
import datetime as dt
import json

from .git import common_dir_file, run_git
from .keys import UPDATE_AVAILABLE
from .vendor import has_copy, read_stamp
from .versions import is_newer, latest_tag, tag_version

CACHE_FILE = "svod-update-check.json"
CHECK_INTERVAL = dt.timedelta(days=1)
CHECK_TIMEOUT_SEC = 3
FIELD_CHECKED = "checked_at"
FIELD_LATEST = "latest"
FIELD_SOURCE = "source"
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0"}
ENCODING = "utf-8"


def now():
    """Current local time with its offset."""
    return dt.datetime.now().astimezone()


def read_cache(path):
    """The cached check as a mapping, empty when absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def fresh(cache, source, at):
    """Whether the cached check is of the same source and younger than the interval."""
    if cache.get(FIELD_SOURCE) != source:
        return False
    try:
        checked = dt.datetime.fromisoformat(str(cache.get(FIELD_CHECKED)))
    except ValueError:
        return False
    if checked.tzinfo is None:
        return False
    return dt.timedelta(0) <= at - checked < CHECK_INTERVAL


def remote_latest(root, source):
    """Newest release version tagged in the source, or None when it cannot be read."""
    out = run_git(root, "ls-remote", "--tags", "--refs", source, timeout=CHECK_TIMEOUT_SEC,
                  env=NO_PROMPT)
    if not out.ok:
        return None
    tag = latest_tag(out.out)
    return tag_version(tag) if tag else None


def latest_known(root, source, at):
    """Newest release of the source: cached for a day, the cache kept in the git directory.

    A failed check is remembered too, keeping the last known release, so an offline session
    start does not wait for the network every time. None off git.
    """
    path = common_dir_file(root, CACHE_FILE)
    if path is None:
        return None
    cache = read_cache(path)
    if fresh(cache, source, at):
        return cache.get(FIELD_LATEST)
    latest = remote_latest(root, source)
    if latest is None and cache.get(FIELD_SOURCE) == source:
        latest = cache.get(FIELD_LATEST)
    path.write_text(json.dumps({FIELD_CHECKED: at.isoformat(), FIELD_LATEST: latest,
                                FIELD_SOURCE: source}), encoding=ENCODING)
    return latest


def update_notice(config, locale, at=None):
    """Line about a newer release than the copy of the store, or None; never raises."""
    try:
        if not config.update_check or not has_copy(config.root):
            return None
        stamp = read_stamp(config.root)
        if not stamp.source or not stamp.version:
            return None
        latest = latest_known(config.root, stamp.source, at or now())
        if not is_newer(latest, stamp.version):
            return None
        return locale.text(UPDATE_AVAILABLE, latest=latest, current=stamp.version)
    except Exception:
        return None


def with_notice(lines, notice):
    """Summary lines with the notice first, separated by a blank line."""
    if not notice:
        return lines
    return [notice] + ([""] + lines if lines else [])
