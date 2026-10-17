"""Questions before work: the questions file, the human mark and the answer command.

The questions file of a subject holds headings `## Q: <question>`, each followed by a line
`A: <answer>`, or the single line `none` when there is nothing to ask. An answer is written by
`svod answer` only while a fresh human mark is present: the prompt hook leaves it when a person
writes in the chat, so the mark shows that the person has just spoken, not what they said. The
agent copies the answer from the chat; the line under it records the approver, the date and the
digest of the prompt the mark was left for.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import keys
from .approval import MARK_AT, Run, is_fresh, now
from .git import common_dir_file
from .yamlio import ENCODING

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import Pipeline
    from .render import Report
    from .subject import Subject

HUMAN_MARK_FILE = "svod-human.json"
MARK_SHA = "sha"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SHA_SHOWN = 12
DEFAULT_FILE = "questions.md"
NONE_LINE = "none"
QUESTION_RE = re.compile(r"^##\s+Q:\s*(.*?)\s*$")
ANSWER_RE = re.compile(r"^A:\s*(.*?)\s*$")
ANSWER_PREFIX = "A: "
BY_RE = re.compile(r"^\s+by:")
BY_LINE = "  by: {by}, at: {date}, prompt: {sha}"
SECTION_END_RE = re.compile(r"^#{1,2}\s")
NEWLINE = "\n"
FIRST_NUMBER = 1


@dataclass(frozen=True)
class Question:
    """One question: its text, its answer (empty when none) and its lines in the file.

    line is the index of the heading; end is the index just after the last line of the section.
    """

    text: str
    answer: str
    line: int
    end: int


@dataclass(frozen=True)
class Questions:
    """Questions of a file in order, and whether the file is the single line `none`."""

    items: tuple[Question, ...]
    none: bool = False

    @property
    def unanswered(self) -> list[Question]:
        """Questions without an answer."""
        return [q for q in self.items if not q.answer]


def parse_questions(text: str) -> Questions:
    """Questions of a questions file text.

    A section runs from its `## Q:` heading to the next heading of level one or two. Its answer
    is the first line starting with `A:`, stripped.
    """
    if text.strip().casefold() == NONE_LINE:
        return Questions((), none=True)
    lines = text.splitlines()
    heads = [(i, m.group(1)) for i, line in enumerate(lines) if (m := QUESTION_RE.match(line))]
    items = []
    for index, question in heads:
        end = next((i for i in range(index + 1, len(lines)) if SECTION_END_RE.match(lines[i])),
                   len(lines))
        answer = next((m.group(1) for line in lines[index + 1:end]
                       if (m := ANSWER_RE.match(line))), "")
        items.append(Question(question, answer, index, end))
    return Questions(tuple(items))


def answered_text(text: str, number: int, answer: str, by_line: str) -> str:
    """The file text with the answer and its by line under question number (from 1).

    An existing answer of the question is replaced in place together with its by lines;
    otherwise the answer goes after the last non-blank line of the section.
    """
    question = parse_questions(text).items[number - FIRST_NUMBER]
    lines = text.splitlines()
    new = [f"{ANSWER_PREFIX}{answer}", by_line]
    section = range(question.line + 1, question.end)
    found = next((i for i in section if ANSWER_RE.match(lines[i])), None)
    if found is not None:
        stop = found + 1
        while stop < question.end and BY_RE.match(lines[stop]):
            stop += 1
        lines[found:stop] = new
    else:
        last = max((i for i in section if lines[i].strip()), default=question.line)
        lines[last + 1:last + 1] = new
    return NEWLINE.join(lines) + NEWLINE


def human_mark_path(root: Path, run: Run | None = None) -> Path | None:
    """Human mark file in the git common directory of the store; None off git.

    run replaces run_git.
    """
    return common_dir_file(root, HUMAN_MARK_FILE, run)


def prompt_sha(prompt: str) -> str:
    """sha256 hex digest of the prompt text."""
    return hashlib.sha256(prompt.encode(ENCODING)).hexdigest()


def write_human_mark(root: Path, prompt: str, at: dt.datetime | None = None,
                     run: Run | None = None) -> Path | None:
    """Leave the human mark for a prompt a person wrote; return its path or None off git.

    Only the prompt hook calls it, from a real prompt; run replaces run_git.
    """
    path = human_mark_path(root, run)
    if path is None:
        return None
    data = {MARK_AT: (at or now()).isoformat(), MARK_SHA: prompt_sha(prompt)}
    path.write_text(json.dumps(data), encoding=ENCODING)
    return path


def read_human_mark(root: Path) -> dict[str, Any] | None:
    """The human mark as a mapping, or None when absent or unreadable."""
    path = human_mark_path(root)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def fresh_human_mark(root: Path, window_minutes: int,
                     at: dt.datetime | None = None) -> dict[str, Any] | None:
    """The human mark when it is fresh and carries a sha256 hex digest, else None."""
    mark = read_human_mark(root)
    if not is_fresh(mark, window_minutes, at):
        return None
    # A fresh mark is a mapping.
    sha = str(mark.get(MARK_SHA, ""))  # type: ignore[union-attr]
    return mark if SHA_RE.match(sha) else None


def questions_file(pipelines: list[Pipeline]) -> str:
    """File of the first questions_answered gate use among the pipelines, or the default."""
    from .gates import PARAM_FILE, QuestionsAnsweredGate
    for pipeline in pipelines:
        for ref in pipeline.gate_refs():
            if isinstance(ref.impl, QuestionsAnsweredGate):
                return str(ref.params.get(PARAM_FILE, DEFAULT_FILE))
    return DEFAULT_FILE


def refusal(ctx: Context, key: str, **facts: Any) -> Report:
    """Report of a refused answer."""
    from .render import Report
    return Report(ok=False, err=[ctx.locale.text(key, **facts)], refused=True)


def target(ctx: Context, pipelines: list[Pipeline],
           query: str) -> tuple[Subject | None, list[Pipeline], Report | None]:
    """(subject, its pipelines, None) for the one open subject the query names, else a report."""
    from .render import INDENT, Report
    from .resolve import resolve
    found = [(p, s) for p, s in resolve(ctx, pipelines, query).matches
             if s.exists and not s.archived and s.path is not None]
    paths = list(dict.fromkeys(s.path for _, s in found))
    if not paths:
        return None, [], Report(ok=False, err=[ctx.locale.text(keys.STATUS_NOT_FOUND,
                                                               query=query)])
    if len(paths) > 1:
        err = [ctx.locale.text(keys.STATUS_AMBIGUOUS)]
        err += [INDENT + ctx.locale.text(keys.STATUS_CANDIDATE, id=s.id)
                for s in dict((s.path, s) for _, s in found).values()]
        return None, [], Report(ok=False, err=err)
    return found[0][1], [p for p, _ in found], None


def answer(ctx: Context, pipelines: list[Pipeline], query: str, number: int, text: str,
           at: dt.datetime | None = None) -> Report:
    """Write the answer under question number of the subject's questions file.

    Refused without a fresh human mark, for a missing file or question, an empty answer or an
    unknown approver. Nothing is committed and the mark is not consumed: one message of the
    person may answer several questions.
    """
    from .checkouts import subject_context
    from .identity import approver
    from .render import Report
    subject, found, report = target(ctx, pipelines, query)
    if report is not None:
        return report
    # target returns an existing subject with a path when it returns no report.
    base: Path = subject.path  # type: ignore[union-attr,assignment]
    root = subject_context(ctx, subject).root  # type: ignore[arg-type]
    name = questions_file(found)
    path = base / name
    shown = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    if not path.is_file():
        return refusal(ctx, keys.ANSWER_NO_FILE, file=shown)
    content = path.read_text(encoding=ENCODING)
    count = len(parse_questions(content).items)
    if not FIRST_NUMBER <= number <= count:
        return refusal(ctx, keys.ANSWER_NO_QUESTION, file=shown, number=number, count=count)
    words = " ".join(text.split())
    if not words:
        return refusal(ctx, keys.ANSWER_EMPTY)
    mark = fresh_human_mark(ctx.root, ctx.config.approval_window, at)
    if mark is None:
        return refusal(ctx, keys.ANSWER_NO_MARK)
    who = approver(ctx)
    if who is None:
        return refusal(ctx, keys.APPROVE_NO_APPROVER)
    date = (at or now()).date().isoformat()
    sha = str(mark[MARK_SHA])[:SHA_SHOWN]
    by_line = BY_LINE.format(by=who, date=date, sha=sha)
    path.write_text(answered_text(content, number, words, by_line), encoding=ENCODING)
    question = parse_questions(content).items[number - FIRST_NUMBER].text
    return Report(ok=True, out=[ctx.locale.text(keys.ANSWER_DONE, file=shown, number=number,
                                                question=question, by=who, sha=sha)])
