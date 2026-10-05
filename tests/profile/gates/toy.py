"""Toy gates of the test profile: a progress counter, a ticket key, known keys and directories."""
import re

from svod.gates import Gate, KeyGate, Result, Status, verdict
from svod.subject import ATTR_CONTAINER

PROGRESS_FILE = "progress.txt"
FACT_AHEAD = "ahead"
DISPLAY_KEY = "mark.progress_display"
ENCODING = "utf-8"
TICKET_RE = re.compile(r"(?<![\w-])(tk-\d+)(?!\d)")
REPOS_DIR = "repos"
FACT_PATHS = "paths"
KNOWN_FILE = "known.txt"


class ProgressGate(Gate):
    """Passes when progress.txt holds a number; facts.ahead is that number."""

    name = "progress"

    def evaluate(self, ctx, subject):
        """Read the counter under the subject path."""
        path = subject.path / PROGRESS_FILE if subject.exists and subject.path else None
        if path is None or not path.is_file():
            return Result(Status.FAIL, {FACT_AHEAD: 0})
        text = path.read_text(encoding=ENCODING).strip()
        if not text.isdigit():
            return Result(Status.UNKNOWN, {FACT_AHEAD: 0}, reason=f"not a number: {text}")
        ahead = int(text)
        return Result(Status.PASS, {FACT_AHEAD: ahead},
                      display=ctx.locale.text(DISPLAY_KEY, ahead=ahead))


class TicketGate(KeyGate):
    """Ticket keys of the form tk-<digits>."""

    name = "ticket"

    def match(self, query):
        """Key named by the query, or None."""
        found = TICKET_RE.search(query.casefold())
        return found.group(1) if found else None

    def find(self, text):
        """Keys mentioned in the text."""
        return set(TICKET_RE.findall(text.casefold()))


class DirsGate(Gate):
    """Passes for an existing subject; facts.paths maps each directory under repos/ to its path."""

    name = "dirs"

    def evaluate(self, ctx, subject):
        """Directories under the subject's repos/ folder."""
        if not subject.exists or subject.path is None:
            return Result(Status.FAIL, {FACT_PATHS: {}})
        base = subject.path / REPOS_DIR
        found = sorted(base.iterdir()) if base.is_dir() else []
        paths = {p.name: str(p) for p in found if p.is_dir()}
        return Result(Status.PASS, {FACT_PATHS: paths})


class KnownGate(Gate):
    """Passes for a found subject, a subject in a container, or a key listed in known.txt."""

    name = "known"

    def evaluate(self, ctx, subject):
        """Look the subject up in the store."""
        if subject.exists or subject.attrs.get(ATTR_CONTAINER):
            return verdict(True)
        path = ctx.root / KNOWN_FILE
        listed = set(path.read_text(encoding=ENCODING).split()) if path.is_file() else set()
        return verdict(bool(subject.keys & listed))


GATES = {cls.name: cls for cls in (ProgressGate, TicketGate, DirsGate, KnownGate)}
