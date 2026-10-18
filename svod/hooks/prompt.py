"""The prompt hook: the approval phrase and its mark, positions of the subjects a prompt names."""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ..approval import MARK_AT, is_fresh, write_human_mark, write_mark
from ..checkouts import subject_context
from ..config import DEFAULT_EXTERNAL_PHRASES, DEFAULT_WINDOW_MINUTES
from ..gates import ApprovalGate
from ..keys import (HOOK_APPROVAL_JOINERS, HOOK_APPROVAL_MARKED, HOOK_APPROVAL_MARKED_UNNAMED,
                    HOOK_POSITION_HEAD, HOOK_POSITION_TAIL)
from ..knowledge import knowledge_context, publication_reply
from ..position import position
from ..render import render_position, step_skills
from ..resolve import resolve
from .protocol import EVENT_PROMPT, FIELD_PROMPT, Event, context_output
from .store import (agent_context_setting, broken_text, config_of, context_of, cut_key, load,
                    query_keys, store_root)

if TYPE_CHECKING:
    from ..approval import Run
    from ..config import Config
    from ..context import Context
    from ..loader import Runtime
    from ..locale import Locale
    from ..pipeline import Pipeline
    from ..position import Position

QUESTION_REPLY_OPEN = "<send_user_message_question_reply>"
QUESTION_REPLY_CLOSE = "</send_user_message_question_reply>"
REPLY_ANSWER = "answer"
AGENT_MESSAGE_TAG = "<agent-message"
AGENT_MESSAGE_PREFIX = "Another Claude session sent a message"
MAX_QUERIES = 3
MIN_NAME = 8
NORMAL_FORM: Final = "NFC"
NAME_RE = r"(?<![\w-]){name}(?![\w-])"
PHRASE_RE = r"\s*{phrase}(?!\w)"
GO_RE = r"(?<!\w){phrase}(?!\w)"
# Nothing but punctuation and spaces: no further word.
NO_WORD_RE = re.compile(r"[\W_]*")
LINE_BREAK = "\n"
APPROVAL_END_RE = re.compile(r"[\s.!]*$")
TAIL_SEPARATOR_RE = re.compile(r"[\s,;:&+/–—-]+")
ID_SEPARATOR = "/"
BLOCK_SEPARATOR = "\n\n"
LINE_SEPARATOR = "\n"
FIELDS_SEPARATOR = ", "
COMMANDS_SEPARATOR = "; "
APPROVE_COMMAND = "svod approve {key}"
VARIANT_SEPARATOR = "_"
REASON_MARKED = "marked"
FACT_KEYS = "keys"
SETTING_POSITIONS = "prompt_positions"
SETTING_NOTICE = "approval_notice"


def nfc(text: str) -> str:
    """Text in Unicode NFC."""
    return unicodedata.normalize(NORMAL_FORM, text)


def folded(text: str) -> str:
    """Text comparable across Unicode forms and letter case."""
    return nfc(text).casefold()


def is_agent_message(prompt: str) -> bool:
    """The prompt is a message of another agent, not a request of a person."""
    return AGENT_MESSAGE_TAG in prompt or prompt.lstrip().startswith(AGENT_MESSAGE_PREFIX)


def approval_keys(runtime: Runtime, prompt: str) -> list[str] | None:
    """Keys named by an approving prompt, or None when the prompt does not approve.

    The prompt approves when it is, as a whole, a configured phrase optionally followed by keys
    joined by separators or the joining words of the locale, and closing punctuation.
    """
    text = nfc(prompt).strip()
    joiners = {folded(w) for w in runtime.locale.text(HOOK_APPROVAL_JOINERS).split()}
    for phrase in runtime.config.approval_phrases:
        pattern = PHRASE_RE.format(phrase=re.escape(nfc(phrase).strip()))
        found = re.match(pattern, text, re.IGNORECASE)
        if not found:
            continue
        rest = APPROVAL_END_RE.sub("", text[found.end():])
        keys = query_keys(runtime.pipelines, rest)
        left = rest
        for key in keys:
            left = cut_key(left, key)
        if all(folded(token) in joiners for token in TAIL_SEPARATOR_RE.split(left) if token):
            return keys
    return None


def human_answers(prompt: str) -> list[str]:
    """Extract only actual answers from a UI reply, never the questions/options."""
    text = prompt.strip()
    if not text.startswith(QUESTION_REPLY_OPEN):
        return [prompt]
    if not text.endswith(QUESTION_REPLY_CLOSE):
        return []
    try:
        replies = json.loads(text[len(QUESTION_REPLY_OPEN):-len(QUESTION_REPLY_CLOSE)])
    except ValueError:
        return []
    if not isinstance(replies, list) or not replies:
        return []
    if any(not isinstance(reply, dict) or not isinstance(reply.get(REPLY_ANSWER), str)
           for reply in replies):
        return []
    return [reply[REPLY_ANSWER] for reply in replies]


def go_at(text: str, start: int, end: int) -> bool:
    """Whether the phrase found at text[start:end] says go ahead by where it stands.

    It does only when it stands on a line of its own: nothing but spaces before it on the
    line and nothing but punctuation after it. A phrase inside a sentence, however placed, is
    no answer, so a negation on the line ("не давай", "давай не будем") never counts as one.
    """
    line_start = text.rfind(LINE_BREAK, 0, start) + 1
    line_end = text.find(LINE_BREAK, end)
    before = text[line_start:start]
    after_line = text[end:] if line_end < 0 else text[end:line_end]
    return not before.strip() and NO_WORD_RE.fullmatch(after_line) is not None


def says_go(text: str, phrases: Iterable[str]) -> bool:
    """Whether the text says go ahead with one of the phrases, letter case and form aside.

    The phrase counts as whole words on a line of its own, punctuation after it allowed; a
    reply that mentions it inside a sentence does not say go.
    """
    found = folded(text).strip()
    return any(go_at(found, match.start(), match.end())
               for phrase in phrases if phrase.strip()
               for match in re.finditer(GO_RE.format(phrase=re.escape(folded(phrase).strip())),
                                        found))


def mark_human(root: Path, answers: list[str], config: Config | None,
               at: dt.datetime | None = None, run: Run | None = None) -> Path | None:
    """Leave the human mark of a reply of a person; its path, or None when none is left.

    The text is the reply, or the answers of a reply to a question joined by lines. A store
    whose svod.yaml does not load gets the default phrases and window. An event older than the
    window leaves no mark, nor does a git directory that cannot be written.
    """
    text = LINE_SEPARATOR.join(answers).strip()
    if not text:
        return None
    window = config.approval_window if config else DEFAULT_WINDOW_MINUTES
    if at is not None and not is_fresh({MARK_AT: at.isoformat()}, window):
        return None
    phrases = config.external_phrases if config else DEFAULT_EXTERNAL_PHRASES
    try:
        return write_human_mark(root, text, go=says_go(text, phrases), at=at, run=run)
    except OSError:
        return None


def subject_names(ctx: Context, pipelines: Iterable[Pipeline]) -> list[str]:
    """Last path segment of the id of every open subject, long enough to be named on purpose."""
    names: list[str] = []
    for pipeline in pipelines:
        for subject in pipeline.subject.impl.enumerate(ctx):
            name = subject.id.rsplit(ID_SEPARATOR, 1)[-1]
            if subject.exists and not subject.archived and len(name) >= MIN_NAME:
                names.append(name)
    return list(dict.fromkeys(names))


def queries(ctx: Context, pipelines: list[Pipeline], prompt: str) -> list[str]:
    """Keys, then exact subject names named in the prompt; at most MAX_QUERIES."""
    text = folded(prompt)
    names = [n for n in subject_names(ctx, pipelines)
             if re.search(NAME_RE.format(name=re.escape(folded(n))), text)]
    return list(dict.fromkeys(query_keys(pipelines, prompt) + names))[:MAX_QUERIES]


def awaits_approval(pos: Position) -> bool:
    """Whether the next step of the position is an approval gate that has not passed."""
    if pos.text_from_entry or pos.current is None:
        return False
    first = pos.current.first_open
    return first is not None and isinstance(first.ref.impl, ApprovalGate)


def marked_step(locale: Locale, pos: Position, marked: Iterable[str]) -> Position:
    """The position told that the person has just approved, when it waits for that approval.

    The next step becomes the variant <text>_marked of the profile, given the key as {keys},
    when the locale has it; otherwise it is dropped, the approval notice naming the command
    instead. Waiting for the approval in the chat is never repeated after the mark is recorded.
    """
    wanted = {folded(m) for m in marked}
    named = sorted(k for k in pos.subject.keys if folded(k) in wanted)
    if not named or not pos.text or not awaits_approval(pos):
        return pos
    variant = f"{pos.text}{VARIANT_SEPARATOR}{REASON_MARKED}"
    if locale.has(variant):
        pos.text, pos.facts = variant, {FACT_KEYS: named[0]}
    else:
        pos.text = None
    return pos


def positions(ctx: Context, pipelines: list[Pipeline], named: Iterable[str],
              marked: Iterable[str] = ()) -> list[str]:
    """Status blocks of the existing subjects the queries resolve to, without repeats.

    marked: keys whose approval mark the prompt has just recorded.
    """
    found: list[str] = []
    for query in named:
        resolution = resolve(ctx, pipelines, query)
        if resolution.ambiguous:
            continue
        for pipeline, subject in resolution.matches:
            if not subject.exists:
                continue
            own = subject_context(ctx, subject)
            pos = marked_step(ctx.locale, position(own, pipeline, subject), marked)
            found.append(LINE_SEPARATOR.join(render_position(ctx.locale, pos,
                                                             step_skills(own, pos))))
    return list(dict.fromkeys(found))


def marked_text(locale: Locale, keys: list[str] | None, minutes: int) -> str:
    """Notice of a recorded approval mark: with the command for each key named, or unnamed."""
    if not keys:
        return locale.text(HOOK_APPROVAL_MARKED_UNNAMED, minutes=minutes)
    return locale.text(HOOK_APPROVAL_MARKED, minutes=minutes, keys=FIELDS_SEPARATOR.join(keys),
                       commands=COMMANDS_SEPARATOR.join(APPROVE_COMMAND.format(key=key)
                                                        for key in keys))


def prompt_hook(event: Event, fallback: str | Path | None,
                at: dt.datetime | None = None) -> str | None:
    """Mark a human prompt; a verified redelivery keeps its original event time.

    Every reply of a person leaves the human mark; an approving one also the approval mark.

    ``at`` is for a trusted integration replaying the same actual human event, never
    for treating an old answer as approval of a new plan. Expired events cannot mark.
    """
    prompt = event.get(FIELD_PROMPT)
    if not isinstance(prompt, str) or not prompt.strip() or is_agent_message(prompt):
        return None
    root = store_root(event, fallback)
    if root is None:
        return None
    runtime, reason = load(root)
    answers = human_answers(prompt)
    if runtime is None:
        mark_human(root, answers, config_of(root), at)
        return context_output(EVENT_PROMPT, broken_text(root, reason))
    locale = runtime.locale
    ctx = context_of(runtime)
    mark_human(ctx.root, answers, runtime.config, at, ctx.cache.git)
    publication_reply(ctx)
    blocks: list[str] = []
    approvals = [keys for answer in answers
                 if (keys := approval_keys(runtime, answer)) is not None]
    keys = list(dict.fromkeys(key for group in approvals for key in group)) if approvals else None
    fresh = at is None or is_fresh({MARK_AT: at.isoformat()}, runtime.config.approval_window)
    marked = (keys is not None and fresh
              and write_mark(ctx.root, keys, at=at, run=ctx.cache.git) is not None)
    if marked and agent_context_setting(runtime, SETTING_NOTICE):
        blocks.append(marked_text(locale, keys, runtime.config.approval_window))
    if agent_context_setting(runtime, SETTING_POSITIONS):
        found = positions(ctx, runtime.pipelines,
                          queries(ctx, runtime.pipelines, LINE_SEPARATOR.join(answers)),
                          keys if marked and keys is not None else ())
        if found:
            blocks += [locale.text(HOOK_POSITION_HEAD), *found, locale.text(HOOK_POSITION_TAIL)]
    blocks += knowledge_context(runtime, ctx, lambda: queries(ctx, runtime.pipelines,
                                                              LINE_SEPARATOR.join(answers)))
    return context_output(EVENT_PROMPT, BLOCK_SEPARATOR.join(blocks)) if blocks else None
