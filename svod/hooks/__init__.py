"""Agent hooks: the summary at session start, positions named in a prompt, guards before a tool.

Every hook reads one event of Claude Code or Codex as JSON on stdin, prints its JSON answer or
nothing, and never fails: a store that does not load is reported in one line instead of silence.

Modules, each importing only those above it: protocol (the event JSON), shell (shell commands),
store (finding and loading the store), prompt (the prompt hook), guard (the pre-tool rules),
external (the external-effects rule), events (the answer to each event).
"""
from ..keys import HOOK_APPROVAL_MARKED_UNNAMED
from .events import HANDLERS, answer, pre_tool, run, session_start
from .external import default_external, external_command, external_reason, program_words
from .guard import (DOT_GIT, QUESTIONS_FILE, Guard, Guarded, approval_lines, broken_reason,
                    checkout_dir, edit_touches, existing_dir, guarded_files, ignored_paths,
                    inside, main_checkout, main_reason, main_text, patch_targets,
                    questions_file, read_text, tool_paths, tool_reason)
from .prompt import (QUESTION_REPLY_CLOSE, QUESTION_REPLY_OPEN, REASON_MARKED,
                     VARIANT_SEPARATOR, approval_keys, awaits_approval, folded, human_answers,
                     is_agent_message, mark_human, marked_step, marked_text, nfc, positions,
                     prompt_hook, queries, says_go, subject_names)
from .protocol import (CONTEXT, DECISION, DECISION_REASON, DENY, EVENT_NAME, EVENT_PRE_TOOL,
                       EVENT_PROMPT, EVENT_SESSION_START, EVENTS, FIELD_CWD, FIELD_INPUT,
                       FIELD_PROMPT, FIELD_TOOL, HOOK_EVENT_NAMES, OUTPUT, PROJECT_ENV, absolute,
                       context_output, deny_output, event_cwd)
from .shell import (bash_paths, bash_reads_only, bash_writes_approval, command_segments,
                    python_reads_metadata, segment_reads_only, shell_tokens)
from .store import (ENGINE_BROKEN_FALLBACK, agent_context_setting, broken_text, config_of,
                    context_of, first_error, key_gates, load, query_keys, store_root)

__all__ = [
    "HOOK_APPROVAL_MARKED_UNNAMED",
    "HANDLERS", "answer", "pre_tool", "run", "session_start",
    "default_external", "external_command", "external_reason", "program_words",
    "DOT_GIT", "QUESTIONS_FILE", "Guard", "Guarded", "approval_lines", "broken_reason",
    "checkout_dir", "edit_touches", "existing_dir", "guarded_files", "ignored_paths", "inside",
    "main_checkout", "main_reason", "main_text", "patch_targets", "questions_file", "read_text",
    "tool_paths", "tool_reason",
    "QUESTION_REPLY_CLOSE", "QUESTION_REPLY_OPEN", "REASON_MARKED", "VARIANT_SEPARATOR",
    "approval_keys", "awaits_approval", "folded", "human_answers", "is_agent_message",
    "mark_human", "marked_step", "marked_text", "nfc", "positions", "prompt_hook", "queries",
    "says_go", "subject_names",
    "CONTEXT", "DECISION", "DECISION_REASON", "DENY", "EVENT_NAME", "EVENT_PRE_TOOL",
    "EVENT_PROMPT", "EVENT_SESSION_START", "EVENTS", "FIELD_CWD", "FIELD_INPUT", "FIELD_PROMPT",
    "FIELD_TOOL", "HOOK_EVENT_NAMES", "OUTPUT", "PROJECT_ENV", "absolute", "context_output",
    "deny_output", "event_cwd",
    "bash_paths", "bash_reads_only", "bash_writes_approval", "command_segments",
    "python_reads_metadata", "segment_reads_only", "shell_tokens",
    "ENGINE_BROKEN_FALLBACK", "agent_context_setting", "broken_text", "config_of", "context_of",
    "first_error", "key_gates", "load", "query_keys", "store_root",
]
