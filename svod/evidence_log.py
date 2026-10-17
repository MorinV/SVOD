"""Evidence log: facts of the course of each piece of work, one JSON line per event.

The log of a subject is evidence/<pipeline>/<subject id, / as __>.jsonl in the store; an event
tied to no subject goes to evidence/store.jsonl. Lines are only ever appended. A line holds
codes, ids, counts and seconds: no free text, no instruction texts, no secrets. The log is
secondary: a failed write is said once on stderr and never fails the command that wrote it.
"""
from __future__ import annotations

import datetime as dt
import functools
import inspect
import json
import os
import re
import string
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from . import keys
from .config import load_config
from .errors import LoadError
from .gates import PARAM_MARKER, ApprovalGate
from .yamlio import ENCODING

if TYPE_CHECKING:
    from .context import Context
    from .hooks.guard import Guard
    from .locale import Locale
    from .pipeline import Pipeline
    from .position import Position
    from .render import Report

EVIDENCE_DIR = "evidence"
LOG_SUFFIX = ".jsonl"
STORE_LOG = "store"
ID_SEPARATOR = "/"
ID_REPLACEMENT = "__"
GITIGNORE = ".gitignore"
IGNORE_LINE = EVIDENCE_DIR + "/"
IGNORE_FORMS = frozenset({EVIDENCE_DIR, IGNORE_LINE, "/" + EVIDENCE_DIR, "/" + IGNORE_LINE})
FILE_MODE = 0o644
FACT_LIMIT = 100
SECONDS_DIGITS = 3
WARNING = "svod: the evidence log is not written: {error}"

FIELD_AT = "at"
FIELD_EVENT = "event"
FIELD_SUBJECT = "subject"
FIELD_PIPELINE = "pipeline"
FIELD_STEP = "step"
FIELD_FACTS = "facts"

EVENT_STEP_PASSED = "step_passed"
EVENT_POSITION_CHANGED = "position_changed"
EVENT_APPROVAL_RECORDED = "approval_recorded"
EVENT_APPROVAL_DRIFT = "approval_drift"
EVENT_APPROVAL_REFUSED = "approval_refused"
EVENT_CHECKS_RUN = "checks_run"
EVENT_DELIVERED = "delivered"
EVENT_HOOK_DENIED = "hook_denied"
EVENT_UNKNOWN_GATE = "unknown_gate"
EVENT_ACTION_RUN = "action_run"
EVENTS = frozenset({EVENT_STEP_PASSED, EVENT_POSITION_CHANGED, EVENT_APPROVAL_RECORDED,
                    EVENT_APPROVAL_DRIFT, EVENT_APPROVAL_REFUSED, EVENT_CHECKS_RUN,
                    EVENT_DELIVERED, EVENT_HOOK_DENIED, EVENT_UNKNOWN_GATE, EVENT_ACTION_RUN})

FACT_FROM = "from"
FACT_TO = "to"
FACT_BY = "by"
FACT_REASON = "reason"
FACT_SERVICE = "service"
FACT_WORKSPACE = "workspace"
FACT_CODE = "code"
FACT_SECONDS = "seconds"
FACT_PASSED = "passed"
FACT_GATE = "gate"
FACT_ACTION = "action"
FACT_MARKER = "marker"

SUMMARY_EVENTS = "events"
SUMMARY_SECONDS = "seconds"

RULE_APPROVAL = "approval"
RULE_PLAN = "plan"
RULE_MAIN = "main"
RULE_MARK = "mark"
RULE_BROKEN = "broken"
RULE_EXTERNAL = "external"
RULE_QUESTIONS = "questions"
RULE_HUMAN = "human"
# The locale key of each refusal of the pre-tool hook, in the order they are told apart.
RULE_KEYS = ((RULE_APPROVAL, keys.HOOK_DENY_APPROVAL), (RULE_PLAN, keys.HOOK_DENY_PLAN),
             (RULE_MAIN, keys.HOOK_DENY_MAIN), (RULE_MARK, keys.HOOK_DENY_MARK),
             (RULE_BROKEN, keys.HOOK_DENY_BROKEN), (RULE_EXTERNAL, keys.HOOK_DENY_EXTERNAL),
             (RULE_QUESTIONS, keys.HOOK_DENY_QUESTIONS), (RULE_HUMAN, keys.HOOK_DENY_HUMAN))

APPROVE_PREFIX = "approve."
APPROVE_REFUSALS = (keys.APPROVE_NO_MARK, keys.APPROVE_FOREIGN_KEY, keys.APPROVE_NO_GATE,
                    keys.APPROVE_NO_STEP, keys.APPROVE_STEP_NO_GATE, keys.APPROVE_NOT_READY,
                    keys.APPROVE_CHANGED_AFTER_MARK, keys.APPROVE_NO_APPROVER,
                    keys.APPROVE_NOT_CONFIRMED)
RESULT_PASSED = "passed"
RESULT_EXIT_CODE = "exit_code"
RESULT_RECEIPT = "receipt"
RECEIPT_CWD = "cwd"

F = TypeVar("F", bound=Callable[..., Any])

_warned = False


def warn(error: object) -> None:
    """Say on stderr, once per process, that the log was not written."""
    global _warned
    if not _warned:
        _warned = True
        print(WARNING.format(error=" ".join(str(error).split())), file=sys.stderr)


def file_name(name: str) -> str:
    """A pipeline name or a subject id as one file name: / becomes __."""
    return name.replace(ID_SEPARATOR, ID_REPLACEMENT)


def log_path(root: str | Path, pipeline: str | None, subject_id: str | None) -> Path:
    """The log of the subject, or the store log when no subject is named."""
    base = Path(root) / EVIDENCE_DIR
    if pipeline is None or subject_id is None:
        return base / (STORE_LOG + LOG_SUFFIX)
    return base / file_name(pipeline) / (file_name(subject_id) + LOG_SUFFIX)


def settings(root: str | Path) -> tuple[bool, bool]:
    """(enabled, commit) of the evidence block of svod.yaml; off when the config does not load."""
    try:
        config = load_config(root, local=False)
    except LoadError:
        return False, True
    return config.evidence_enabled, config.evidence_commit


def ignore(root: str | Path) -> None:
    """Add evidence/ to the .gitignore of the store unless a line already names it."""
    path = Path(root) / GITIGNORE
    text = path.read_text(encoding=ENCODING) if path.is_file() else ""
    if IGNORE_FORMS & {line.strip() for line in text.splitlines()}:
        return
    gap = "\n" if text and not text.endswith("\n") else ""
    with path.open("a", encoding=ENCODING) as stream:
        stream.write(gap + IGNORE_LINE + "\n")


def fact_value(value: Any) -> Any:
    """A fact as stored: strings cut to FACT_LIMIT, seconds rounded, scalars only."""
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, SECONDS_DIGITS)
    return str(value)[:FACT_LIMIT]


def line_of(pipeline: str | None, subject_id: str | None, event: str, step: str | None,
            facts: dict[str, Any]) -> str:
    """One log line of an event, ending with a newline."""
    entry = {FIELD_AT: dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             FIELD_EVENT: event, FIELD_SUBJECT: subject_id, FIELD_PIPELINE: pipeline,
             FIELD_STEP: step,
             FIELD_FACTS: {name: fact_value(value) for name, value in facts.items()}}
    return json.dumps(entry, ensure_ascii=False) + "\n"


def record(root: str | Path, pipeline: str | None, subject_id: str | None, event: str,
           step: str | None = None, **facts: Any) -> bool:
    """Append one event to the log of the subject; whether a line was written.

    The line is written by one append of one write call. Nothing is written when the evidence
    is off or the config does not load; a failed write is said once on stderr, never raised.
    """
    if event not in EVENTS:
        raise ValueError(f"unknown evidence event: {event}")
    try:
        enabled, commit = settings(root)
        if not enabled:
            return False
        path = log_path(root, pipeline, subject_id)
        data = line_of(pipeline, subject_id, event, step, facts).encode(ENCODING)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not commit:
            ignore(root)
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
        try:
            os.write(handle, data)
        finally:
            os.close(handle)
        return True
    except (OSError, ValueError) as exc:
        warn(exc)
        return False


def record_action(root: str | Path, pipeline: str | None, subject_id: str | None, action: str,
                  code: int | None, seconds: float, step: str | None = None) -> bool:
    """Append action_run: an action of the subject ran, with its exit code and duration."""
    return record(root, pipeline, subject_id, EVENT_ACTION_RUN, step,
                  **{FACT_ACTION: action, FACT_CODE: code, FACT_SECONDS: seconds})


def read(root: str | Path, pipeline: str | None, subject_id: str | None) -> list[dict[str, Any]]:
    """Events of the subject in the order written; a torn or foreign line is left out."""
    try:
        text = log_path(root, pipeline, subject_id).read_text(encoding=ENCODING)
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get(FIELD_FACTS), dict):
            found.append(entry)
    return found


def summary(root: str | Path, pipeline: str | None, subject_id: str | None) -> dict[str, Any]:
    """Counts of the events of the subject by code and the seconds of every timed event."""
    entries = read(root, pipeline, subject_id)
    seconds = sum(entry[FIELD_FACTS].get(FACT_SECONDS) or 0 for entry in entries
                  if isinstance(entry[FIELD_FACTS].get(FACT_SECONDS), (int, float)))
    return {SUMMARY_EVENTS: dict(Counter(entry.get(FIELD_EVENT) for entry in entries)),
            SUMMARY_SECONDS: round(seconds, SECONDS_DIGITS)}


def template_facts(template: str, text: str) -> dict[str, str] | None:
    """Facts a text was rendered with from the template, or None when it was not."""
    pattern, names = "", set()
    for literal, name, _, _ in string.Formatter().parse(template):
        pattern += re.escape(literal)
        if name is None:
            continue
        pattern += f"(?P={name})" if name in names else f"(?P<{name}>.*?)"
        names.add(name)
    try:
        found = re.fullmatch(pattern, text, flags=re.DOTALL)
    except re.error:
        return None
    return found.groupdict() if found else None


def rendered_from(locales: Iterable[Locale], text: str,
                  candidates: Iterable[str]) -> tuple[str, dict[str, str]] | None:
    """(key, facts) of the first candidate key a text was rendered from, or None."""
    for key in candidates:
        for locale in locales:
            if not locale.has(key):
                continue
            facts = template_facts(locale.text_template(key), text)
            if facts is not None:
                return key, facts
    return None


def note_position(ctx: Context, pos: Position) -> None:
    """Record what a status shows of an existing subject that the log does not hold yet.

    position_changed when the current step differs from the last one recorded, step_passed for
    each step passed between the two, and unknown_gate for a gate that could not be checked,
    once per position.
    """
    try:
        if not pos.subject.exists or not settings(ctx.root)[0]:
            return
        name, subject_id = pos.pipeline.name, pos.subject.id
        entries = read(ctx.root, name, subject_id)
        moves = [entry for entry in entries if entry.get(FIELD_EVENT) == EVENT_POSITION_CHANGED]
        before = moves[-1][FIELD_FACTS].get(FACT_TO) if moves else None
        now = pos.current.step.id if pos.current else None
        if now != before:
            states = [state for state in pos.steps if not state.step.optional]
            ids = [state.step.id for state in states]
            end = ids.index(now) if now in ids else len(ids)
            for state in states[ids.index(before):end] if before in ids else []:
                if state.passed:
                    record(ctx.root, name, subject_id, EVENT_STEP_PASSED, state.step.id)
            record(ctx.root, name, subject_id, EVENT_POSITION_CHANGED, now,
                   **{FACT_FROM: before, FACT_TO: now})
            entries = []
        else:
            last = max((i for i, entry in enumerate(entries)
                        if entry.get(FIELD_EVENT) == EVENT_POSITION_CHANGED), default=-1)
            entries = entries[last + 1:]
        seen = {(entry[FIELD_FACTS].get(FACT_GATE), entry[FIELD_FACTS].get(FACT_REASON))
                for entry in entries if entry.get(FIELD_EVENT) == EVENT_UNKNOWN_GATE}
        for outcome in pos.unknown:
            facts = {FACT_GATE: outcome.ref.gate,
                     FACT_REASON: (outcome.result.reason or "")[:FACT_LIMIT]}
            if (facts[FACT_GATE], facts[FACT_REASON]) not in seen:
                seen.add((facts[FACT_GATE], facts[FACT_REASON]))
                record(ctx.root, name, subject_id, EVENT_UNKNOWN_GATE, now, **facts)
    except Exception as exc:
        warn(exc)


def approved_step(pipeline: Pipeline, marker: str | None) -> str | None:
    """Id of the first step whose approval gate writes the marker."""
    for step in pipeline.steps:
        if any(isinstance(ref.impl, ApprovalGate) and ref.params.get(PARAM_MARKER) == marker
               for ref in step.gates):
            return step.id
    return None


def note_approval(ctx: Context, pipelines: list[Pipeline], query: str, step: str | None,
                  report: Report) -> None:
    """Record approval_recorded, approval_drift or approval_refused of an approve report.

    Only a report about one open subject is recorded; not found and ambiguous are not.
    """
    from .resolve import resolve

    if report.ok and report.out:
        found = rendered_from([ctx.locale], report.out[0], [keys.APPROVE_DONE])
    elif report.refused and report.err:
        found = rendered_from([ctx.locale], report.err[0], APPROVE_REFUSALS)
    else:
        return
    if found is None:
        return
    key, facts = found
    matches = [(pipeline, subject) for pipeline, subject in resolve(ctx, pipelines, query).matches
               if subject.exists and not subject.archived]
    if len(matches) != 1:
        return
    pipeline, subject = matches[0]
    step = step or facts.get(FIELD_STEP)
    if key == keys.APPROVE_DONE:
        record(ctx.root, pipeline.name, subject.id, EVENT_APPROVAL_RECORDED,
               step or approved_step(pipeline, facts.get(FACT_MARKER)), by=facts.get(FACT_BY))
    elif key == keys.APPROVE_CHANGED_AFTER_MARK:
        record(ctx.root, pipeline.name, subject.id, EVENT_APPROVAL_DRIFT, step)
    else:
        record(ctx.root, pipeline.name, subject.id, EVENT_APPROVAL_REFUSED, step,
               reason=key.removeprefix(APPROVE_PREFIX))


def approval_outcome(func: F) -> F:
    """Decorate approve(ctx, pipelines, query, ...): record the outcome of its report."""
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Run approve, then record its outcome; the report is returned as it is."""
        report = func(*args, **kwargs)
        try:
            bound = signature.bind(*args, **kwargs).arguments
            note_approval(bound["ctx"], bound["pipelines"], bound["query"], bound.get("step"),
                          report)
        except Exception as exc:
            warn(exc)
        return report
    return cast(F, wrapper)


def local_subject(root: str | Path, key: str) -> tuple[Path, str, str] | None:
    """(store root, pipeline, subject id) of the one current subject a local command names.

    The lookup of local_runner.state without its policy: a result is recorded even when the
    source is no longer clean after the command.
    """
    from .context import Context
    from .loader import load_runtime
    from .resolve import exact_pairs, key_pairs

    runtime = load_runtime(Path(root).resolve())
    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    pairs = ([(p, s) for p in runtime.pipelines for s in p.subject.impl.enumerate(ctx)
              if s.id == key] or exact_pairs(ctx, runtime.pipelines, key)
             or key_pairs(ctx, runtime.pipelines, key))
    pairs = [(p, s) for p, s in pairs if s.exists and not s.archived]
    if len(pairs) != 1:
        return None
    return ctx.root, pairs[0][0].name, pairs[0][1].id


def note_local(event: str, root: str | Path, key: str, result: dict[str, Any],
               seconds: float) -> None:
    """Record checks_run or delivered of a local command that returned its result."""
    if not settings(root)[0]:
        return
    found = local_subject(root, key)
    if found is None:
        return
    store, pipeline, subject_id = found
    if event == EVENT_DELIVERED:
        record(store, pipeline, subject_id, EVENT_DELIVERED)
        return
    facts: dict[str, Any] = {}
    try:
        receipt = json.loads(Path(result[RESULT_RECEIPT]).read_text(encoding=ENCODING))
        if receipt.get(FACT_SERVICE):
            facts[FACT_SERVICE] = receipt[FACT_SERVICE]
        else:
            facts[FACT_WORKSPACE] = Path(receipt[RECEIPT_CWD]).name
    except (OSError, ValueError, KeyError, TypeError):
        pass
    facts.update({FACT_CODE: result.get(RESULT_EXIT_CODE), FACT_SECONDS: seconds,
                  FACT_PASSED: bool(result.get(RESULT_PASSED))})
    record(store, pipeline, subject_id, EVENT_CHECKS_RUN, None, **facts)


def local_outcome(event: str) -> Callable[[F], F]:
    """Decorate a local command (root, key) -> result: record the event when it returns."""
    def decorate(func: F) -> F:
        """The command, timed, recording the event after it returns."""
        @functools.wraps(func)
        def wrapper(root: str | Path, key: str, *args: Any, **kwargs: Any) -> Any:
            """Run the command, then record the event; the result is returned as it is."""
            started = time.monotonic()
            result = func(root, key, *args, **kwargs)
            try:
                note_local(event, root, key, result, time.monotonic() - started)
            except Exception as exc:
                warn(exc)
            return result
        return cast(F, wrapper)
    return decorate


def denied_subject(guard: Guard, event: dict[str, Any], tool: str,
                   data: dict[str, Any]) -> tuple[str | None, str | None]:
    """(pipeline, subject id) a refused tool call was about, or (None, None).

    A path in a subject of the store names it; else a work directory whose name holds a key
    names the first open subject of that key.
    """
    from .hooks.guard import checkout_dir, tool_paths
    from .hooks.protocol import BASH_TOOL, event_cwd
    from .resolve import by_key

    if guard.runtime is None or guard.ctx is None or guard.root is None:
        return None, None
    root, ctx, pipelines = guard.root, guard.ctx, guard.runtime.pipelines
    paths = tool_paths(event, tool, data)
    if tool == BASH_TOOL:
        paths.append(event_cwd(event).resolve())
    inside = [path.relative_to(root).as_posix() for path in paths if path.is_relative_to(root)]
    for pipeline in pipelines if inside else []:
        for subject in pipeline.subject.impl.touched(ctx, inside):
            if subject.exists:
                return pipeline.name, subject.id
    for path in paths:
        directory = checkout_dir(path)
        for key in sorted(guard.dir_keys(directory.name)) if directory is not None else []:
            for pipeline, subject in by_key(ctx, pipelines, key):
                if subject.exists and not subject.archived:
                    return pipeline.name, subject.id
    return None, None


def note_denial(guard: Guard, event: dict[str, Any], tool: str, data: dict[str, Any],
                reason: str) -> None:
    """Record hook_denied of a pre-tool refusal: the rule, the tool, the subject when known.

    Nothing is recorded without a store of the session.
    """
    from .locale import error_locale

    try:
        if guard.root is None or not settings(guard.root)[0]:
            return
        locales = [guard.runtime.locale] if guard.runtime is not None else []
        found = rendered_from([*locales, error_locale(guard.root)], reason,
                              [key for _, key in RULE_KEYS])
        rule = next((rule for rule, key in RULE_KEYS if found and key == found[0]), None)
        pipeline, subject_id = denied_subject(guard, event, tool, data)
        record(guard.root, pipeline, subject_id, EVENT_HOOK_DENIED, rule=rule, tool=tool)
    except Exception as exc:
        warn(exc)
