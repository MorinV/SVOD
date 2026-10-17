"""Answers to the three hook events; a failure becomes a line in the context, never an error."""
import json
import sys

from ..active import hook_payload, summarize
from ..evidence_log import note_denial
from ..notice import update_notice, with_notice
from .guard import Guard, broken_reason, tool_reason
from .prompt import prompt_hook
from .protocol import (BASH_TOOL, EVENT_PRE_TOOL, EVENT_PROMPT, EVENT_SESSION_START, FIELD_INPUT,
                       FIELD_TOOL, GUARDED_TOOLS, command_of, context_output, deny_output)
from .shell import bash_reads_only
from .store import agent_context_setting, broken_text, context_of, load, store_root

SETTING_SUMMARY = "session_summary"


def session_start(event, fallback):
    """The active summary of the store, or a line about the engine that did not load."""
    root = store_root(event, fallback)
    if root is None:
        return None
    runtime, reason = load(root)
    if runtime is None:
        return context_output(EVENT_SESSION_START, broken_text(root, reason))
    if not agent_context_setting(runtime, SETTING_SUMMARY):
        return None
    lines = summarize(context_of(runtime), runtime.pipelines, False)
    lines = with_notice(lines, update_notice(runtime.config, runtime.locale))
    return hook_payload(runtime.locale, lines) if lines else None


def pre_tool(event, fallback):
    """Refusal of a tool call that edits approval fields, frozen code or a read-only checkout."""
    tool = event.get(FIELD_TOOL)
    data = event.get(FIELD_INPUT)
    if tool not in GUARDED_TOOLS or not isinstance(data, dict):
        return None
    if tool == BASH_TOOL and bash_reads_only(command_of(data)):
        return None
    guard = Guard(store_root(event, fallback))
    reason = tool_reason(guard, event, tool, data)
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
