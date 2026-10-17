"""The JSON both agents exchange with a hook: event names, fields, answers, paths of an event."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Event = dict[str, Any]

EVENT_SESSION_START = "session-start"
EVENT_PROMPT = "prompt"
EVENT_PRE_TOOL = "pre-tool"
EVENTS = (EVENT_SESSION_START, EVENT_PROMPT, EVENT_PRE_TOOL)
HOOK_EVENT_NAMES = {EVENT_SESSION_START: "SessionStart", EVENT_PROMPT: "UserPromptSubmit",
                    EVENT_PRE_TOOL: "PreToolUse"}
OUTPUT = "hookSpecificOutput"
EVENT_NAME = "hookEventName"
CONTEXT = "additionalContext"
DECISION = "permissionDecision"
DECISION_REASON = "permissionDecisionReason"
DENY = "deny"
FIELD_PROMPT = "prompt"
FIELD_CWD = "cwd"
FIELD_TOOL = "tool_name"
FIELD_INPUT = "tool_input"
PROJECT_ENV = "CLAUDE_PROJECT_DIR"
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITE_TOOL = "Write"
BASH_TOOL = "Bash"
PATCH_TOOL = "apply_patch"
GUARDED_TOOLS = (*EDIT_TOOLS, BASH_TOOL, PATCH_TOOL)
PATH_FIELDS = ("file_path", "notebook_path")
TEXT_FIELDS = ("old_string", "new_string")
EDITS_FIELD = "edits"
CONTENT_FIELD = "content"
COMMAND_FIELD = "command"


def context_output(event_name: str, text: str) -> str:
    """Hook answer adding text to the context of the agent."""
    return json.dumps({OUTPUT: {EVENT_NAME: HOOK_EVENT_NAMES[event_name], CONTEXT: text}},
                      ensure_ascii=False)


def deny_output(reason: str) -> str:
    """Hook answer refusing the tool call with the reason."""
    return json.dumps({OUTPUT: {EVENT_NAME: HOOK_EVENT_NAMES[EVENT_PRE_TOOL], DECISION: DENY,
                                DECISION_REASON: reason}}, ensure_ascii=False)


def event_cwd(event: Event) -> Path:
    """Working directory of the event, else of the process."""
    cwd = event.get(FIELD_CWD)
    return Path(cwd).expanduser() if isinstance(cwd, str) and cwd else Path.cwd()


def absolute(event: Event, raw: str) -> Path:
    """Resolved path of a tool argument, relative ones taken from the event cwd."""
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else event_cwd(event) / path).resolve()


def command_of(data: dict[str, Any]) -> str:
    """Command text of a Bash or apply_patch tool input."""
    return str(data.get(COMMAND_FIELD) or "")
