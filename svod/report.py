"""Report from the evidence log: where the time of each record went, and of each pipeline.

Per record: the time each step was current, approval rounds, failed checks, hook denials and
actions run. Per pipeline: sums and medians over every record with a log. Only the events the
log already holds are read; a step never seen current through `status` has no time.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import evidence_log as ev
from . import keys
from .retro.rules import facts_of, moment, of_event

if TYPE_CHECKING:
    from .context import Context
    from .locale import Locale
    from .pipeline import Pipeline
    from .subject import Subject

LOG_GLOB = "*" + ev.LOG_SUFFIX
INDENT = "  "
GAP = "  "
LABEL_LIMIT = 24
ITEMS_SEPARATOR = ", "
ITEM = "{name} {count}"
NO_RULE = "-"
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60

FIELD_PIPELINE = "pipeline"
FIELD_ID = "id"
FIELD_EVENTS = "events"
FIELD_STEPS = "steps"
FIELD_STEP = "step"
FIELD_SECONDS = "seconds"
FIELD_OPEN = "open"
FIELD_APPROVALS = "approvals"
FIELD_ROUNDS = "rounds"
FIELD_RECORDED = "recorded"
FIELD_DRIFT = "drift"
FIELD_CHECKS = "checks"
FIELD_RUNS = "runs"
FIELD_FAILED = "failed"
FIELD_DENIALS = "denials"
FIELD_RULE = "rule"
FIELD_RULES = "rules"
FIELD_COUNT = "count"
FIELD_ACTIONS = "actions"
FIELD_ACTION = "action"
FIELD_CODE = "code"
FIELD_AT = "at"
FIELD_SERVICE = "service"
FIELD_WORKSPACE = "workspace"
FIELD_PASSED = "passed"
FIELD_RECORDS = "records"
FIELD_SUM = "sum"
FIELD_MEDIAN = "median"
FIELD_SUMMARY = "summary"
FIELD_PIPELINES = "pipelines"
FIELD_NOW = "now"
FIELD_APPROVAL_ROUNDS = "approval_rounds"
FIELD_FAILED_CHECKS = "failed_checks"
# Seconds of an action per record, while the summary is made.
SPENT = "spent"


def step_times(entries: list[dict[str, Any]], now: dt.datetime) -> list[dict[str, Any]]:
    """Seconds each step was current, in the order first seen: one move onto it to the next.

    The step current at the last move counts up to now and is open; a move to no step (done,
    or held by an entry) closes the time. A move without a time is left out.
    """
    moves = [(str(facts_of(entry).get(ev.FACT_TO) or ""), at)
             for entry in of_event(entries, ev.EVENT_POSITION_CHANGED)
             if (at := moment(entry)) is not None]
    found: dict[str, dict[str, Any]] = {}
    for i, (step, start) in enumerate(moves):
        if not step:
            continue
        last = i + 1 == len(moves)
        end = now if last else moves[i + 1][1]
        item = found.setdefault(step, {FIELD_STEP: step, FIELD_SECONDS: 0, FIELD_OPEN: False})
        item[FIELD_SECONDS] += max(round((end - start).total_seconds()), 0)
        item[FIELD_OPEN] = item[FIELD_OPEN] or last
    return list(found.values())


def failed(facts: dict[str, Any]) -> bool:
    """Whether a checks_run failed: not passed (a refused result), or a non-zero exit code."""
    code = facts.get(ev.FACT_CODE)
    nonzero = isinstance(code, int) and not isinstance(code, bool) and code != 0
    return facts.get(ev.FACT_PASSED) is False or nonzero


def action_failed(item: dict[str, Any]) -> bool:
    """Whether an action run did not exit with 0 (a timeout or an interruption included)."""
    return item[FIELD_CODE] != 0


def record_report(pipeline: str, subject_id: str, entries: list[dict[str, Any]],
                  now: dt.datetime) -> dict[str, Any]:
    """The report of one record from the entries of its log."""
    checks = of_event(entries, ev.EVENT_CHECKS_RUN)
    failures = [{FIELD_AT: entry.get(ev.FIELD_AT),
                 FIELD_SERVICE: facts_of(entry).get(ev.FACT_SERVICE),
                 FIELD_WORKSPACE: facts_of(entry).get(ev.FACT_WORKSPACE),
                 FIELD_CODE: facts_of(entry).get(ev.FACT_CODE),
                 FIELD_PASSED: facts_of(entry).get(ev.FACT_PASSED),
                 FIELD_SECONDS: facts_of(entry).get(ev.FACT_SECONDS)}
                for entry in checks if failed(facts_of(entry))]
    recorded = len(of_event(entries, ev.EVENT_APPROVAL_RECORDED))
    drift = len(of_event(entries, ev.EVENT_APPROVAL_DRIFT))
    denials = Counter(facts_of(entry).get(FIELD_RULE)
                      for entry in of_event(entries, ev.EVENT_HOOK_DENIED))
    actions = [{FIELD_AT: entry.get(ev.FIELD_AT), FIELD_STEP: entry.get(ev.FIELD_STEP),
                FIELD_ACTION: facts_of(entry).get(ev.FACT_ACTION),
                FIELD_CODE: facts_of(entry).get(ev.FACT_CODE),
                FIELD_SECONDS: facts_of(entry).get(ev.FACT_SECONDS)}
               for entry in of_event(entries, ev.EVENT_ACTION_RUN)]
    return {FIELD_PIPELINE: pipeline, FIELD_ID: subject_id, FIELD_EVENTS: len(entries),
            FIELD_STEPS: step_times(entries, now),
            FIELD_APPROVALS: {FIELD_ROUNDS: recorded + drift, FIELD_RECORDED: recorded,
                              FIELD_DRIFT: drift},
            FIELD_CHECKS: {FIELD_RUNS: len(checks), FIELD_FAILED: failures},
            FIELD_DENIALS: counted(denials),
            FIELD_ACTIONS: actions}


def counted(counter: Counter[Any]) -> list[dict[str, Any]]:
    """Hook rules with their counts, most first, then by name; an unknown rule is null."""
    return [{FIELD_RULE: rule, FIELD_COUNT: count}
            for rule, count in sorted(counter.items(), key=lambda item: (-item[1],
                                                                          str(item[0])))]


def number(value: float) -> float | int:
    """A median as an int when it is whole."""
    return int(value) if float(value).is_integer() else round(value, 1)


def sum_median(values: list[float]) -> dict[str, Any]:
    """{sum, median} of the values; a median of nothing is 0."""
    return {FIELD_SUM: number(sum(values)),
            FIELD_MEDIAN: number(statistics.median(values)) if values else 0}


def seconds_of(value: Any) -> float:
    """A seconds fact as a number; 0 when it is none."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def pipeline_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Sums and medians over the reports of the records of one pipeline.

    A step or an action is summed and its median taken over the records that have it; the
    counters over every record.
    """
    steps: dict[str, list[float]] = {}
    actions: dict[str, dict[str, Any]] = {}
    denials: Counter[Any] = Counter()
    for record in records:
        for item in record[FIELD_STEPS]:
            steps.setdefault(item[FIELD_STEP], []).append(item[FIELD_SECONDS])
        for rule in record[FIELD_DENIALS]:
            denials[rule[FIELD_RULE]] += rule[FIELD_COUNT]
        spent: dict[str, float] = {}
        for run in record[FIELD_ACTIONS]:
            name = str(run[FIELD_ACTION])
            entry = actions.setdefault(name, {FIELD_ACTION: name, FIELD_RUNS: 0, FIELD_FAILED: 0,
                                              SPENT: []})
            entry[FIELD_RUNS] += 1
            entry[FIELD_FAILED] += action_failed(run)
            spent[name] = spent.get(name, 0.0) + seconds_of(run[FIELD_SECONDS])
        for name, seconds in spent.items():
            actions[name][SPENT].append(seconds)
    return {
        FIELD_RECORDS: len(records),
        FIELD_STEPS: [{FIELD_STEP: step, FIELD_RECORDS: len(values), **sum_median(values)}
                      for step, values in steps.items()],
        FIELD_APPROVAL_ROUNDS: sum_median([r[FIELD_APPROVALS][FIELD_ROUNDS] for r in records]),
        FIELD_FAILED_CHECKS: sum_median([len(r[FIELD_CHECKS][FIELD_FAILED]) for r in records]),
        FIELD_DENIALS: {**sum_median([sum(d[FIELD_COUNT] for d in r[FIELD_DENIALS])
                                      for r in records]), FIELD_RULES: counted(denials)},
        FIELD_ACTIONS: [{FIELD_ACTION: name, FIELD_RECORDS: len(entry[SPENT]),
                         FIELD_RUNS: entry[FIELD_RUNS], FIELD_FAILED: entry[FIELD_FAILED],
                         **sum_median(entry[SPENT])}
                        for name, entry in sorted(actions.items())],
    }


def pipeline_logs(root: Path, pipeline: str) -> list[tuple[str, list[dict[str, Any]]]]:
    """(subject id, entries) of every non-empty log of the pipeline, oldest last line first.

    Records no provider finds any more (archived, removed) count too: their log is history.
    """
    directory = ev.log_path(root, pipeline, pipeline).parent
    found = []
    for path in sorted(directory.glob(LOG_GLOB)):
        subject_id = path.stem.replace(ev.ID_REPLACEMENT, ev.ID_SEPARATOR)
        entries = ev.read(root, pipeline, subject_id)
        if entries:
            found.append((subject_id, entries))
    return sorted(found, key=lambda pair: last_time(pair[1]))


def last_time(entries: list[dict[str, Any]]) -> float:
    """POSIX time of the last timed entry; 0 without one."""
    times = [at.timestamp() for at in map(moment, entries) if at is not None]
    return max(times, default=0.0)


def collect(ctx: Context, pairs: list[tuple[Pipeline, Subject]],
            now: dt.datetime) -> dict[str, Any]:
    """Data of the report of the records the query resolved to."""
    return {FIELD_NOW: now.isoformat(timespec="seconds"),
            FIELD_RECORDS: [record_report(p.name, s.id, ev.read(ctx.root, p.name, s.id), now)
                            for p, s in pairs]}


def collect_all(ctx: Context, pipelines: list[Pipeline], now: dt.datetime) -> dict[str, Any]:
    """Data of the report of every pipeline: its summary and the reports of its records."""
    found = []
    for pipeline in pipelines:
        records = [record_report(pipeline.name, subject_id, entries, now)
                   for subject_id, entries in pipeline_logs(ctx.root, pipeline.name)]
        found.append({FIELD_PIPELINE: pipeline.name, FIELD_SUMMARY: pipeline_summary(records),
                      FIELD_RECORDS: records})
    return {FIELD_NOW: now.isoformat(timespec="seconds"), FIELD_PIPELINES: found}


def clock(seconds: float) -> str:
    """Seconds as H:MM:SS."""
    hours, rest = divmod(int(round(seconds)), SECONDS_PER_HOUR)
    minutes, secs = divmod(rest, SECONDS_PER_MINUTE)
    return f"{hours}:{minutes:02}:{secs:02}"


def aligned(rows: list[tuple[str, str]]) -> list[str]:
    """Rows of label and value, indented, the values in one column."""
    width = min(max((len(label) for label, _ in rows), default=0), LABEL_LIMIT)
    return [(INDENT + label.ljust(width) + GAP + value).rstrip() for label, value in rows]


def items(pairs: list[tuple[Any, int]], unknown: str = NO_RULE) -> str:
    """name count pairs joined; a name of None is shown as unknown."""
    return ITEMS_SEPARATOR.join(ITEM.format(name=unknown if name is None else name, count=count)
                                for name, count in pairs)


def rule_items(locale: Locale, text: str, denials: list[dict[str, Any]]) -> str:
    """The text followed by the refusals by hook rule in parentheses when there are any."""
    pairs = [(d[FIELD_RULE], d[FIELD_COUNT]) for d in denials]
    unknown = locale.text(keys.REPORT_UNKNOWN_RULE)
    return f"{text} ({items(pairs, unknown)})" if pairs else text


def record_lines(locale: Locale, record: dict[str, Any]) -> list[str]:
    """A few aligned lines of one record."""
    lines = [locale.text(keys.REPORT_RECORD, id=record[FIELD_ID],
                         pipeline=record[FIELD_PIPELINE])]
    if not record[FIELD_EVENTS]:
        return [*lines, INDENT + locale.text(keys.REPORT_NO_EVIDENCE)]
    rows = []
    for item in record[FIELD_STEPS]:
        key = keys.REPORT_OPEN if item[FIELD_OPEN] else keys.REPORT_TIME
        rows.append((locale.text(keys.REPORT_STEP, step=item[FIELD_STEP]),
                     locale.text(key, time=clock(item[FIELD_SECONDS]))))
    approvals = record[FIELD_APPROVALS]
    rows.append((locale.text(keys.REPORT_APPROVALS),
                 locale.text(keys.REPORT_APPROVALS_VALUE, rounds=approvals[FIELD_ROUNDS],
                             recorded=approvals[FIELD_RECORDED], drift=approvals[FIELD_DRIFT])))
    checks = record[FIELD_CHECKS]
    where = Counter(str(f[FIELD_SERVICE] or f[FIELD_WORKSPACE] or NO_RULE)
                    for f in checks[FIELD_FAILED])
    rows.append((locale.text(keys.REPORT_CHECKS),
                 locale.text(keys.REPORT_CHECKS_VALUE, failed=len(checks[FIELD_FAILED]),
                             runs=checks[FIELD_RUNS])
                 + (f" ({items(sorted(where.items()))})" if where else "")))
    denials = record[FIELD_DENIALS]
    rows.append((locale.text(keys.REPORT_DENIALS),
                 rule_items(locale, str(sum(d[FIELD_COUNT] for d in denials)), denials)))
    runs: dict[str, list[dict[str, Any]]] = {}
    for run in record[FIELD_ACTIONS]:
        runs.setdefault(str(run[FIELD_ACTION]), []).append(run)
    for name, group in sorted(runs.items()):
        rows.append((locale.text(keys.REPORT_ACTION, action=name),
                     locale.text(keys.REPORT_ACTION_VALUE, runs=len(group),
                                 failed=sum(map(action_failed, group)),
                                 time=clock(sum(seconds_of(r[FIELD_SECONDS]) for r in group)))))
    return lines + aligned(rows)


def summary_lines(locale: Locale, pipeline: str, summary: dict[str, Any]) -> list[str]:
    """A few aligned lines of the sums and medians of one pipeline."""
    lines = [locale.text(keys.REPORT_PIPELINE, pipeline=pipeline,
                         records=summary[FIELD_RECORDS])]
    if not summary[FIELD_RECORDS]:
        return lines
    rows = [(locale.text(keys.REPORT_STEP, step=item[FIELD_STEP]),
             locale.text(keys.REPORT_STEP_SUM, sum=clock(item[FIELD_SUM]),
                         median=clock(item[FIELD_MEDIAN]), records=item[FIELD_RECORDS]))
            for item in summary[FIELD_STEPS]]
    for label, field_name in ((keys.REPORT_APPROVALS, FIELD_APPROVAL_ROUNDS),
                              (keys.REPORT_CHECKS, FIELD_FAILED_CHECKS)):
        value = summary[field_name]
        rows.append((locale.text(label), locale.text(keys.REPORT_SUM, sum=value[FIELD_SUM],
                                                     median=value[FIELD_MEDIAN])))
    denials = summary[FIELD_DENIALS]
    rows.append((locale.text(keys.REPORT_DENIALS),
                 rule_items(locale, locale.text(keys.REPORT_SUM, sum=denials[FIELD_SUM],
                                                median=denials[FIELD_MEDIAN]),
                            denials[FIELD_RULES])))
    for item in summary[FIELD_ACTIONS]:
        rows.append((locale.text(keys.REPORT_ACTION, action=item[FIELD_ACTION]),
                     locale.text(keys.REPORT_ACTION_SUM, runs=item[FIELD_RUNS],
                                 failed=item[FIELD_FAILED], sum=clock(item[FIELD_SUM]),
                                 median=clock(item[FIELD_MEDIAN]))))
    return lines + aligned(rows)


def render(locale: Locale, data: dict[str, Any]) -> list[str]:
    """Lines of the report: records one after another; per pipeline its summary first."""
    lines: list[str] = []
    for found in data.get(FIELD_PIPELINES, []):
        lines += [""] if lines else []
        lines += summary_lines(locale, found[FIELD_PIPELINE], found[FIELD_SUMMARY])
        for record in found[FIELD_RECORDS]:
            lines += record_lines(locale, record)
    for record in data.get(FIELD_RECORDS, []):
        lines += record_lines(locale, record)
    return lines
