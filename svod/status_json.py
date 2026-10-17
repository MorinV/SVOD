"""Bounded allowlisted JSON v1 projection. Never evaluates gates or dumps text."""
import re
from pathlib import PurePosixPath

from .gates import is_done

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
REASONS = frozenset({"missing", "legacy", "drift", "stale", "unsupported", "not_evaluated"})
# Gate-specific primitives only; free values, approval authors/dates and error text are not
# telemetry.
FACT_FIELDS = {
    "exists": {"exists": "bool"}, "archived": {},
    "artifact": {"count": "count"}, "git_pushed": {"ahead": "count"},
    "approval": {"reason": "reason"},
}


def token(value):
    """The value when it is a short identifier-like string, else None."""
    return value if isinstance(value, str) and TOKEN.fullmatch(value) else None


def safe_path(value):
    """The value when it is a bounded plain relative POSIX path, else None."""
    if not isinstance(value, str) or len(value) > 512 or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    return value if all(re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", part) and part not in {".", ".."}
                        for part in path.parts) else None


def facts(outcome):
    """Allowlisted primitive facts of the outcome's gate."""
    result = {}
    for name, kind in FACT_FIELDS.get(outcome.ref.gate, {}).items():
        value = outcome.result.facts.get(name)
        if (kind == "bool" and type(value) is bool
                or kind == "count" and type(value) is int and 0 <= value <= 2**53 - 1):
            result[name] = value
        elif kind == "reason" and isinstance(value, str) and value in REASONS:
            result["reason_code"] = value
    return result


def outcome_json(outcome):
    """JSON of one gate outcome with a reason code instead of text; None without an outcome."""
    if outcome is None:
        return None
    reason = outcome.result.reason
    code = reason if isinstance(reason, str) and reason in REASONS else None
    if reason is not None and code is None:
        code = "unknown_detail"
    return {"gate": token(outcome.ref.gate), "status": outcome.result.status.value,
            "reason_code": code, "facts": facts(outcome), "severity": outcome.ref.severity}


def subject_json(pipeline, subject):
    """JSON of a subject of a pipeline: its id, existence, keys and checkout."""
    return {"pipeline": token(pipeline.name),
            "subject": {"id": safe_path(subject.id), "exists": subject.exists,
                        "keys": [token(k) for k in sorted(subject.keys)[:128] if token(k)]},
            "checkout": token(subject.checkout.name) if subject.checkout is not None else None}


def children_json(children):
    """JSON of the captured child positions: id, pipeline, current step and done."""
    return [{"id": safe_path(pos.subject.id), "pipeline": token(pos.pipeline.name),
             "current": token(pos.current.step.id) if pos.current else None,
             "done": is_done(pos)} for pos in (children or [])[:128]]


def position_json(item):
    """JSON of the captured position of one status item."""
    pos = item.position
    result = subject_json(item.pipeline, item.subject)
    result.update({"missing": outcome_json(item.missing),
                   "missing_suppressed": item.missing_suppressed})
    if pos is None:
        result["evaluation"] = "not_evaluated"
        return result
    result.update({
        "evaluation": "evaluated", "current": token(pos.current.step.id) if pos.current else None,
        "done": pos.done is not None, "entries": [outcome_json(o) for o in pos.entries[:128]],
        "blocked": outcome_json(pos.blocked),
        "current_entries": [outcome_json(o) for o in pos.current_entries[:128]],
        "current_blocked": outcome_json(pos.current_blocked),
        "current_entry_evaluation": "evaluated" if pos.current else "not_evaluated",
        "steps": [{"id": token(s.step.id), "optional": s.step.optional,
                   "required": s.step.required,
                   "outcomes": [outcome_json(o) for o in s.outcomes[:128]],
                   "entry_evaluation": "evaluated" if s is pos.current else "not_evaluated"}
                  for s in pos.steps[:128]],
        "done_outcome": outcome_json(pos.done_outcome),
        "done_evaluation": "evaluated" if pos.done_outcome is not None else "not_evaluated",
        "warnings": [outcome_json(o) for o in pos.warnings[:128]],
        "unknown": [outcome_json(o) for o in pos.unknown[:128]],
        "order": [{"later": token(v.later), "earlier": token(v.earlier)}
                  for v in pos.violations[:128]],
        "freeze": {"active": pos.do_not_touch is not None, "from_entry": pos.frozen_by_entry,
                   "step": token(pos.do_not_touch.get("step")) if pos.do_not_touch else None},
        "marks": [{"step": token(step), "outcomes": [outcome_json(o) for o in marks[:128]]}
                  for step, marks in pos.marks[:128]],
        "instruction": {"base_key": token(pos.text), "variant_key": token(item.instruction_variant),
                        "from_entry": pos.text_from_entry},
        "role": token(pos.current.step.role) if pos.current else None,
        "skills": [{"directory": safe_path(label), "skill": token(skill)}
                   for label, skill in (item.skills or [])[:128]], "refs": [],
        "children": children_json(item.children),
    })
    return result


def declared_inputs(outcomes):
    """Selected declarations, never expanded or read; bounded even before dedupe."""
    result, seen = [], set()
    for outcome in outcomes[:128]:
        ref = outcome.ref
        bind = ref.params.get("bind", [])
        bind = bind[:128] if isinstance(bind, list) else []
        values = [("path", ref.params.get("path")), ("glob", ref.params.get("glob"))]
        values.extend(("bind", value) for value in bind)
        for kind, value in values:
            if not isinstance(value, str) or len(value) > 512:
                continue
            # Only literal relative paths and simple * / ? patterns are supported.
            checked = value.replace("*", "x").replace("?", "x") if kind != "path" else value
            if safe_path(checked) is None:
                continue
            key = (token(ref.gate), token(ref.purpose), kind, value)
            if key in seen:
                continue
            seen.add(key)
            result.append({"gate": key[0], "purpose": key[1], "kind": kind, "ref": value})
            if len(result) == 32:
                return result
    return result


def next_action_json(item):
    """Advisory projection only: captured outcomes never grant execution authority."""
    pos = item.position
    current = pos.current if pos is not None else None
    blocker = (pos.blocked or pos.current_blocked or (current.first_open if current else None)
               or (pos.done_outcome if pos.done_outcome and not pos.done_outcome.passed
                   else None)) if pos else item.missing
    terminal = item.subject.archived or (pos is not None and pos.done is not None)
    selected = (([blocker] if blocker else [])
                + (current.outcomes[:128] + pos.current_entries[:128] if pos and current else []))
    inputs = declared_inputs(selected) if pos and not terminal else []
    result = subject_json(item.pipeline, item.subject)
    result.update({
        "state": ("historical" if item.subject.archived else "completed" if terminal
                  else "live" if pos else "not_evaluated"),
        "stage": token(current.step.id) if current and not terminal else None,
        "role": token(current.step.role) if current and not terminal else None,
        "instruction": {"base_key": token(pos.text), "variant_key": token(item.instruction_variant),
                        "from_entry": pos.text_from_entry} if pos and not terminal else None,
        "inputs": inputs, "blocker": outcome_json(blocker) if not terminal else None,
        "version": {"value": None, "reason_code": "not_captured"},
    })
    return result


def report_json(report):
    """JSON of a report: ok, refused and the exit code the command returns."""
    return {"ok": report.ok, "refused": report.refused,
            "exit_code": 0 if report.ok else 1 if report.refused else 2}


def to_json(collection):
    """Pure repeatable projection of the already captured answer."""
    found = collection.resolution
    kind = "ambiguous" if found.ambiguous else "matched" if found.matches else "not_found"
    return {"version": 1, "query": collection.query[:512],
            "resolution": {"kind": kind,
                           "ambiguous": found.ambiguous,
                           "candidates": [subject_json(p, s) for p, s in found.matches[:128]]},
            "report": report_json(collection.report),
            "positions": [position_json(item) for item in collection.items[:128]],
            "next_action": [next_action_json(item) for item in collection.items[:128]
                            if not item.missing_suppressed]}


def error_json(code, query=None, exit_code=2):
    """Safe command failure without exceptions/configuration/report text."""
    if code not in {"invalid_root", "invalid_load", "invalid_arguments"}:
        code = "invalid_load"
    return {"version": 1, "query": query[:512] if isinstance(query, str) else None,
            "resolution": {"kind": "not_evaluated", "ambiguous": False, "candidates": []},
            "report": {"ok": False, "refused": exit_code == 1, "exit_code": exit_code},
            "positions": [], "next_action": [], "error": {"reason_code": code}}
