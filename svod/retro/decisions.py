"""Decisions of a person on retrospective proposals, kept in evidence/decisions.yaml.

The file is a YAML list; each item holds rule, code, subject, decision (accepted or rejected),
at (ISO time with offset) and note (text or null). A proposal with the rule, code and subject of
a decision is not shown again, whatever the decision was.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import evidence_log as ev
from ..errors import LoadError
from ..yamlio import ENCODING, dump_yaml, read_yaml

if TYPE_CHECKING:
    from .rules import Proposal

DECISIONS_FILE = "decisions.yaml"
ACCEPTED = "accepted"
REJECTED = "rejected"
DECISIONS = (ACCEPTED, REJECTED)
FIELD_RULE = "rule"
FIELD_CODE = "code"
FIELD_SUBJECT = "subject"
FIELD_DECISION = "decision"
FIELD_AT = "at"
FIELD_NOTE = "note"
FIELDS = (FIELD_RULE, FIELD_CODE, FIELD_SUBJECT, FIELD_DECISION, FIELD_AT, FIELD_NOTE)


def decisions_path(root: str | Path) -> Path:
    """evidence/decisions.yaml under the store root."""
    return Path(root) / ev.EVIDENCE_DIR / DECISIONS_FILE


def read_decisions(root: str | Path) -> list[dict[str, Any]]:
    """Decisions in the order taken; none without the file.

    LoadError when the file is not a YAML list of mappings: it is never overwritten then.
    """
    path = decisions_path(root)
    if not path.is_file():
        return []
    data = read_yaml(path)
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise LoadError([f"{path}: expected a list of decisions"])
    return data


def decided(entries: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    """(rule, code, subject) of every decision."""
    return {(str(item.get(FIELD_RULE)), str(item.get(FIELD_CODE)),
             str(item.get(FIELD_SUBJECT) or "")) for item in entries}


def record_decision(root: str | Path, proposal: Proposal, decision: str,
                    note: str | None = None) -> Path:
    """Append the decision on the proposal to the file; its path.

    With evidence.commit false the evidence directory is kept out of git, as for the log.
    """
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision: {decision}")
    entries = read_decisions(root)
    entries.append({FIELD_RULE: proposal.rule, FIELD_CODE: proposal.code,
                    FIELD_SUBJECT: proposal.subject or "", FIELD_DECISION: decision,
                    FIELD_AT: dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    FIELD_NOTE: note or None})
    path = decisions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not ev.settings(root)[1]:
        ev.ignore(root)
    path.write_text(dump_yaml(entries), encoding=ENCODING)
    return path
