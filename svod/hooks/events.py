"""Answers to the three hook events; a failure becomes a line in the context, never an error."""
import json
import sys

from ..active import hook_payload, summarize
from ..config import SESSION_FULL, SESSION_INDEX, index_limit, session_start_mode
from ..knowledge import knowledge_context
from ..evidence_log import note_denial
from ..index import session_index
from ..notice import update_notice, with_notice
from .external import external_reason
from .guard import Guard, broken_reason, tool_reason
from .prompt import prompt_hook
from .protocol import (BASH_TOOL, EVENT_PRE_TOOL, EVENT_PROMPT, EVENT_SESSION_START, FIELD_INPUT,
                       FIELD_TOOL, GUARDED_TOOLS, command_of, context_output, deny_output)
from .shell import bash_reads_only
from .store import broken_text, context_of, load, store_root


def session_start(event, fallback):
    """What a session starts with, by agent_context.session_start; or a line about the engine
    that did not load.

    index (the default): the index of the open records alone, frontmatter and headings only.
    summary: the active summary with the update notice, then the knowledge notes of the open
    work. off: the knowledge notes alone. The notes follow agent_context.knowledge.
    """
    root = store_root(event, fallback)
    if root is None:
        return None
    runtime, reason = load(root)
    if runtime is None:
        return context_output(EVENT_SESSION_START, broken_text(root, reason))
    ctx = context_of(runtime)
    profile_config = runtime.config.profile_config
    mode = session_start_mode(profile_config)
    if mode == SESSION_INDEX:
        lines = session_index(ctx, runtime.pipelines, index_limit(profile_config))
        return context_output(EVENT_SESSION_START, "\n".join(lines)) if lines else None
    summary = mode == SESSION_FULL
    lines = summarize(ctx, runtime.pipelines, False) if summary else []
    lines += knowledge_context(runtime, ctx, gap=bool(lines))
    if summary:
        lines = with_notice(lines, update_notice(runtime.config, runtime.locale))
    return hook_payload(runtime.locale, lines) if lines else None


def pre_tool(event, fallback):
    """Refusal of a tool call by the pre-tool rules, or None.

    Refused: edits of approval fields, the marks, the questions of a record, frozen code or a
    read-only checkout, and commands with an external effect. The external rule needs only
    svod.yaml, so a command that only reads is still answered before the store is loaded.
    """
    tool = event.get(FIELD_TOOL)
    data = event.get(FIELD_INPUT)
    if tool not in GUARDED_TOOLS or not isinstance(data, dict):
        return None
    root = store_root(event, fallback)
    if tool == BASH_TOOL:
        reason = external_reason(root, event, command_of(data))
        if reason:
            return deny_output(reason)
        if bash_reads_only(command_of(data)):
            return None
    guard = Guard(root)
    try:
        reason = tool_reason(guard, event, tool, data)
    except (OSError, ValueError, RuntimeError):
        return deny_output("Cannot resolve write destination; supply literal valid paths.")
    if reason:
        note_denial(guard, event, tool, data, reason)
        return deny_output(reason)
    if guard.broken:
        reason = broken_reason(guard, event, tool, data)
        if reason:
            note_denial(guard, event, tool, data, reason)
            return deny_output(reason)
        if tool != BASH_TOOL:
            return context_output(EVENT_PRE_TOOL, broken_text(guard.root, guard.broken))
    return None


HANDLERS = {EVENT_SESSION_START: session_start, EVENT_PROMPT: prompt_hook,
            EVENT_PRE_TOOL: pre_tool}


def answer(event_name, event, fallback=None):
    """JSON answer to one hook event, or None; failures become a line in the context."""
    try:
        return HANDLERS[event_name](event, fallback)
    except Exception as exc:
        try:
            root = store_root(event, fallback)
        except Exception:
            root = None
        return context_output(event_name, broken_text(root, f"{type(exc).__name__}: {exc}"))


def run(event_name, fallback=None, stream=None):
    """Read the event from the stream (stdin by default), print the answer; always 0."""
    try:
        event = json.load(stream or sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    found = answer(event_name, event, fallback)
    if found:
        print(found)
    return 0
