"""Agent hooks: the summary at session start, positions named in a prompt, guards before a tool.

Every hook reads one event of Claude Code or Codex as JSON on stdin, prints its JSON answer or
nothing, and never fails: a store that does not load is reported in one line instead of silence.
"""
import ast
import importlib.util
import json
import os
import re
import shlex
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

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
QUESTION_REPLY_OPEN = "<send_user_message_question_reply>"
QUESTION_REPLY_CLOSE = "</send_user_message_question_reply>"
FIELD_CWD = "cwd"
FIELD_TOOL = "tool_name"
FIELD_INPUT = "tool_input"
PROJECT_ENV = "CLAUDE_PROJECT_DIR"
YAML_MODULE = "yaml"
MISSING_YAML = "PyYAML is not installed (python3 -m pip install pyyaml)"
ENGINE_BROKEN_FALLBACK = "The pipeline engine failed to load: {reason}."
MORE_ERRORS = " (+{count})"
AGENT_MESSAGE_TAG = "<agent-message"
AGENT_MESSAGE_PREFIX = "Another Claude session sent a message"
MAX_QUERIES = 3
MIN_NAME = 8
NORMAL_FORM = "NFC"
NAME_RE = r"(?<![\w-]){name}(?![\w-])"
PHRASE_RE = r"\s*{phrase}(?!\w)"
APPROVAL_END_RE = re.compile(r"[\s.!]*$")
TAIL_SEPARATOR_RE = re.compile(r"[\s,;:&+/\u2013\u2014-]+")
KEY_GAP = " "
ID_SEPARATOR = "/"
BLOCK_SEPARATOR = "\n\n"
LINE_SEPARATOR = "\n"
FIELDS_SEPARATOR = ", "
COMMANDS_SEPARATOR = "; "
APPROVE_COMMAND = "svod approve {key}"
HOOK_APPROVAL_MARKED_UNNAMED = "hook.approval_marked_unnamed"
VARIANT_SEPARATOR = "_"
REASON_MARKED = "marked"
FACT_KEYS = "keys"
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
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$|^\*\*\* Move to: (.+)$")
PATCH_CHANGED = ("+", "-")
DOT_GIT = ".git"
ENCODING = "utf-8"
FIELD_LINE_RE = r"^\s*(?:{fields})\s*:"
FIELD_ALTERNATION = "|"
SEGMENT = r"[^\n|;&]*?"
IN_PLACE = r"\s(?:-[A-Za-z]*i\b|--in-?place\b)"
PATH_END = r"(?![\w.])"
REDIRECT_TO = r">>?\s*['\"]?[^\s'\"<>|;&]*"
IN_PLACE_TOOLS = r"\b(?:sed|perl|yq)\b"
TEE = r"\btee\b"
COPY_TO = r"\b(?:cp|mv)\b"
COPY_END = r"['\"]?\s*(?:$|[|;&])"
QUOTED = r"['\"][^'\"\n]*{path}['\"]"
PYTHON_SCRIPT = re.compile(r"\bpython[\d.]*\b" + SEGMENT + r"(?:\s-c\b|<<)", re.MULTILINE)
SHELL_OPERATORS_NEWLINE = "\n"
SHELL_OPERATORS = frozenset({"|", "||", "&&", ";", ";;", "&", "|&", "(", ")", "{", "}"})
REDIRECT_CHAR = ">"
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPTION_PREFIX = "-"
OPTION_VALUE = "="
PATH_SEPARATOR = "/"
MAX_TOKENS = 500
COMMAND_PREFIXES = frozenset({"env", "command", "builtin", "time", "nice", "exec"})
READ_ONLY_COMMANDS = frozenset({
    "cat", "ls", "grep", "egrep", "fgrep", "rg", "ag", "head", "tail", "less", "more", "wc",
    "find", "stat", "file", "diff", "cmp", "pwd", "which", "type", "whereis", "echo", "printf",
    "true", "false", "test", "[", "[[", "cd", "pushd", "popd", "export", "set", "unset", "date",
    "sleep", "tree", "du", "df", "sort", "uniq", "cut", "tr", "awk", "sed", "jq", "yq",
    "basename", "dirname", "realpath", "readlink", "md5sum", "sha256sum", "shasum", "hexdump",
    "xxd", "strings", "column", "nl", "tac", "rev", "comm", "join", "paste", "fold", "seq",
    "uname", "hostname", "whoami", "id", "git", "svod",
})
GIT_COMMAND = "git"
GIT_VALUE_OPTIONS = ("-C", "-c")
GIT_WRITE_SUBCOMMANDS = frozenset({
    "checkout", "switch", "reset", "stash", "merge", "rebase", "cherry-pick", "revert",
    "apply", "am", "pull", "clean", "rm", "mv", "restore",
})
FIND_COMMAND = "find"
FIND_WRITE_FLAGS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir"})
IN_PLACE_COMMANDS = frozenset({"sed", "perl", "yq"})
IN_PLACE_RE = re.compile(IN_PLACE)
PYTHON_HEREDOC = re.compile(
    r"<<[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\n(.*?)^\2\s*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class Guarded:
    """A metadata file of subjects, as trailing path parts, and the approval fields it holds."""

    parts: tuple
    fields: tuple


def nfc(text):
    """Text in Unicode NFC."""
    return unicodedata.normalize(NORMAL_FORM, text)


def folded(text):
    """Text comparable across Unicode forms and letter case."""
    return nfc(text).casefold()


def context_output(event_name, text):
    """Hook answer adding text to the context of the agent."""
    return json.dumps({OUTPUT: {EVENT_NAME: HOOK_EVENT_NAMES[event_name], CONTEXT: text}},
                      ensure_ascii=False)


def deny_output(reason):
    """Hook answer refusing the tool call with the reason."""
    return json.dumps({OUTPUT: {EVENT_NAME: HOOK_EVENT_NAMES[EVENT_PRE_TOOL], DECISION: DENY,
                                DECISION_REASON: reason}}, ensure_ascii=False)


def first_error(errors):
    """First load error and how many more there are."""
    if not errors:
        return ""
    rest = len(errors) - 1
    return errors[0] + (MORE_ERRORS.format(count=rest) if rest else "")


def broken_text(root, reason):
    """One line about the engine that did not load, in the locale of the store when readable."""
    reason = " ".join(str(reason).split())
    try:
        from .locale import error_locale
        from .keys import HOOK_ENGINE_BROKEN
        return error_locale(root).text(HOOK_ENGINE_BROKEN, reason=reason)
    except Exception:
        return ENGINE_BROKEN_FALLBACK.format(reason=reason)


def store_root(event, fallback=None):
    """Store of the session: the one holding the project directory or the event cwd, else fallback.

    None when neither lies in a store.
    """
    from .paths import CONFIG_FILE, find_root
    for candidate in (os.environ.get(PROJECT_ENV), event.get(FIELD_CWD)):
        if isinstance(candidate, str) and candidate:
            root = find_root(Path(candidate).expanduser())
            if root is not None:
                return root
    if fallback:
        root = Path(fallback).expanduser().resolve()
        return root if (root / CONFIG_FILE).is_file() else None
    return None


def load(root):
    """(runtime, None) of the store, or (None, reason) when it does not load."""
    from .errors import LoadError
    from .loader import load_runtime
    try:
        return load_runtime(root), None
    except LoadError as exc:
        return None, first_error(exc.errors)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def context_of(runtime, cache=None):
    """Evaluation context of a loaded store; cache, when given, is the memory of the event."""
    from .context import Context
    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    if cache is not None:
        ctx.cache = cache
    return ctx


def agent_context_setting(runtime, name):
    """Whether an optional agent-context output is enabled (legacy defaults on)."""
    profile = getattr(runtime.config, "profile_config", {})
    settings = profile.get("agent_context", {}) if isinstance(profile, dict) else {}
    return not (isinstance(settings, dict) and settings.get(name) is False)


def key_gates(pipelines):
    """Key gates of the pipelines that declare one."""
    return [p.subject.key_impl for p in pipelines if p.subject.key_impl is not None]


def query_keys(pipelines, text):
    """Keys the key gates recognise in a query, each gate asked until nothing is left, in order."""
    found = []
    for gate in key_gates(pipelines):
        rest = text
        key = gate.match(rest)
        while key:
            found.append(key)
            cut = re.sub(re.escape(key), KEY_GAP, rest, flags=re.IGNORECASE)
            if cut == rest:
                break
            rest = cut
            key = gate.match(rest)
    return list(dict.fromkeys(found))


def is_agent_message(prompt):
    """The prompt is a message of another agent, not a request of a person."""
    return AGENT_MESSAGE_TAG in prompt or prompt.lstrip().startswith(AGENT_MESSAGE_PREFIX)


def approval_keys(runtime, prompt):
    """Keys named by an approving prompt, or None when the prompt does not approve.

    The prompt approves when it is, as a whole, a configured phrase optionally followed by keys
    joined by separators or the joining words of the locale, and closing punctuation.
    """
    from .keys import HOOK_APPROVAL_JOINERS
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
            left = re.sub(re.escape(key), KEY_GAP, left, flags=re.IGNORECASE)
        if all(folded(token) in joiners for token in TAIL_SEPARATOR_RE.split(left) if token):
            return keys
    return None


def human_answers(prompt):
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
    if any(not isinstance(reply, dict) or not isinstance(reply.get("answer"), str)
           for reply in replies):
        return []
    return [reply["answer"] for reply in replies]


def subject_names(ctx, pipelines):
    """Last path segment of the id of every open subject, long enough to be named on purpose."""
    names = []
    for pipeline in pipelines:
        for subject in pipeline.subject.impl.enumerate(ctx):
            name = subject.id.rsplit(ID_SEPARATOR, 1)[-1]
            if subject.exists and not subject.archived and len(name) >= MIN_NAME:
                names.append(name)
    return list(dict.fromkeys(names))


def queries(ctx, pipelines, prompt):
    """Keys, then exact subject names named in the prompt; at most MAX_QUERIES."""
    text = folded(prompt)
    names = [n for n in subject_names(ctx, pipelines)
             if re.search(NAME_RE.format(name=re.escape(folded(n))), text)]
    return list(dict.fromkeys(query_keys(pipelines, prompt) + names))[:MAX_QUERIES]


def awaits_approval(pos):
    """Whether the next step of the position is an approval gate that has not passed."""
    from .gates import ApprovalGate
    if pos.text_from_entry or pos.current is None:
        return False
    first = pos.current.first_open
    return first is not None and isinstance(first.ref.impl, ApprovalGate)


def marked_step(locale, pos, marked):
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


def positions(ctx, pipelines, named, marked=()):
    """Status blocks of the existing subjects the queries resolve to, without repeats.

    marked: keys whose approval mark the prompt has just recorded.
    """
    from .checkouts import subject_context
    from .position import position
    from .render import render_position, step_skills
    from .resolve import resolve
    found = []
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


def session_start(event, fallback):
    """The active summary of the store, or a line about the engine that did not load."""
    from .active import hook_payload, summarize
    root = store_root(event, fallback)
    if root is None:
        return None
    runtime, reason = load(root)
    if runtime is None:
        return context_output(EVENT_SESSION_START, broken_text(root, reason))
    if not agent_context_setting(runtime, "session_summary"):
        return None
    from .notice import update_notice, with_notice
    lines = summarize(context_of(runtime), runtime.pipelines, False)
    lines = with_notice(lines, update_notice(runtime.config, runtime.locale))
    return hook_payload(runtime.locale, lines) if lines else None


def marked_text(locale, keys, minutes):
    """Notice of a recorded approval mark: with the command for each key named, or unnamed."""
    from .keys import HOOK_APPROVAL_MARKED
    if not keys:
        return locale.text(HOOK_APPROVAL_MARKED_UNNAMED, minutes=minutes)
    return locale.text(HOOK_APPROVAL_MARKED, minutes=minutes, keys=FIELDS_SEPARATOR.join(keys),
                       commands=COMMANDS_SEPARATOR.join(APPROVE_COMMAND.format(key=key)
                                                        for key in keys))


def prompt_hook(event, fallback, at=None):
    """Mark a human prompt; a verified redelivery keeps its original event time.

    ``at`` is for a trusted integration replaying the same actual human event, never
    for treating an old answer as approval of a new plan. Expired events cannot mark.
    """
    from .approval import MARK_AT, is_fresh, write_mark
    from .keys import HOOK_POSITION_HEAD, HOOK_POSITION_TAIL
    prompt = event.get(FIELD_PROMPT)
    if not isinstance(prompt, str) or not prompt.strip() or is_agent_message(prompt):
        return None
    root = store_root(event, fallback)
    if root is None:
        return None
    runtime, reason = load(root)
    if runtime is None:
        return context_output(EVENT_PROMPT, broken_text(root, reason))
    locale = runtime.locale
    ctx = context_of(runtime)
    blocks = []
    answers = human_answers(prompt)
    approvals = [keys for answer in answers
                 if (keys := approval_keys(runtime, answer)) is not None]
    keys = list(dict.fromkeys(key for group in approvals for key in group)) if approvals else None
    fresh = at is None or is_fresh({MARK_AT: at.isoformat()}, runtime.config.approval_window)
    marked = (keys is not None and fresh
              and write_mark(ctx.root, keys, at=at, run=ctx.cache.git) is not None)
    if marked and agent_context_setting(runtime, "approval_notice"):
        blocks.append(marked_text(locale, keys, runtime.config.approval_window))
    if agent_context_setting(runtime, "prompt_positions"):
        found = positions(ctx, runtime.pipelines, queries(ctx, runtime.pipelines, "\n".join(answers)),
                          keys if marked else ())
        if found:
            blocks += [locale.text(HOOK_POSITION_HEAD), *found, locale.text(HOOK_POSITION_TAIL)]
    return context_output(EVENT_PROMPT, BLOCK_SEPARATOR.join(blocks)) if blocks else None


def guarded_files(pipelines):
    """Metadata files holding approval fields, from the approval gates of every pipeline step."""
    from .approval import field_names
    from .gates import PARAM_FILE, PARAM_MARKER
    from .workflow_policy import approval_refs
    found = {}
    for pipeline in pipelines:
        for ref in approval_refs(pipeline):
            parts = Path(ref.params[PARAM_FILE]).parts
            fields = found.setdefault(parts, [])
            fields += [f for f in field_names(ref.params[PARAM_MARKER]) if f not in fields]
    return [Guarded(parts, tuple(fields)) for parts, fields in found.items()]


def approval_lines(text, fields):
    """Lines of the text setting any of the fields, stripped."""
    pattern = re.compile(FIELD_LINE_RE.format(
        fields=FIELD_ALTERNATION.join(re.escape(f) for f in fields)))
    return [line.strip() for line in text.splitlines() if pattern.match(line)]


def read_text(path):
    """Text of the file, or an empty string."""
    try:
        return Path(path).read_text(encoding=ENCODING)
    except (OSError, UnicodeDecodeError):
        return ""


def python_reads_metadata(command, name):
    """Recognize only explicit Path(...).read_text/read_bytes uses of metadata literals.

    Unknown syntax, path aliases and write operations retain the conservative guard.
    This is a narrow false-positive fix, not a general Python side-effect analyser.
    """
    scripts = list(PYTHON_SCRIPT.finditer(command))
    if len(scripts) != 1:
        return False
    invocation = scripts[0]
    # The exception must cover exactly one Python command, never sibling commands
    # or a -c argument supplied by another program in the shell expression.
    if re.fullmatch(r"\s*(?:[A-Za-z0-9_./~-]+/)?", command[:invocation.start()]) is None:
        return False
    heredoc = (PYTHON_HEREDOC.match(command, invocation.end() - 2)
               if invocation.group().endswith("<<") else None)
    try:
        if invocation.group().endswith("<<"):
            if (heredoc is None or not heredoc.group(1)
                    or command[heredoc.end():].strip()):
                return False
            header = shlex.split(command[:invocation.end() - 2])
            if header[1:] not in ([], ["-"], ["-u"], ["-u", "-"]):
                return False
            source = heredoc.group(3)
        else:
            if "$" in command or "`" in command:
                return False
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            lexer.commenters = ""
            args = list(lexer)
            if len(args) != 3 or args[1] != "-c":
                return False
            source = args[2]
        tree = ast.parse(source)
    except (ValueError, IndexError, SyntaxError):
        return False
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    literals = [node for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.endswith(name)]
    if not literals:
        return False

    def path_expression(node):
        if isinstance(node, (ast.Constant, ast.Name)):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return path_expression(node.left) and path_expression(node.right)
        if isinstance(node, ast.Call):
            func = node.func
            constructor = (isinstance(func, ast.Name) and func.id == "Path"
                           or isinstance(func, ast.Attribute) and func.attr == "Path"
                           and isinstance(func.value, ast.Name) and func.value.id == "pathlib")
            return constructor and not node.keywords and all(path_expression(arg) for arg in node.args)
        return False

    def filename(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return Path(node.value).name
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return filename(node.right)
        if isinstance(node, ast.Call) and path_expression(node) and node.args:
            return filename(node.args[-1])
        return None

    # A decoy read must not bless other arbitrary operations in the same script.
    # Keep the exception to the small receipt-writing vocabulary; unfamiliar calls,
    # dynamically named destinations and rebinding these helpers remain guarded.
    reserved = {"Path", "pathlib", "yaml", "hashlib", "dict", "print"}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.Import, ast.ImportFrom,
                                                               ast.Assign, ast.Expr, ast.Assert)):
            return False
        if isinstance(node, ast.Import) and any(alias.name not in {"pathlib", "yaml", "hashlib"}
                                               or alias.asname for alias in node.names):
            return False
        if isinstance(node, ast.ImportFrom) and (node.module != "pathlib" or node.level
                                                 or any(alias.name != "Path" or alias.asname
                                                        for alias in node.names)):
            return False
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in reserved:
            return False
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            return False
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"Path", "dict", "print"}:
            continue
        if not isinstance(func, ast.Attribute):
            return False
        if isinstance(func.value, ast.Name) and (func.value.id, func.attr) in {
                ("pathlib", "Path"), ("yaml", "safe_load"), ("yaml", "safe_dump"),
                ("hashlib", "sha256")}:
            continue
        if func.attr in {"read_text", "read_bytes"} and path_expression(func.value):
            continue
        if func.attr in {"write_text", "write_bytes"} and path_expression(func.value):
            destination = filename(func.value)
            if destination and destination not in {name, ".", ".."}:
                continue
        if func.attr in {"encode", "hexdigest"}:
            continue
        return False

    for literal in literals:
        child = literal
        while child in parents:
            parent = parents[child]
            if (isinstance(parent, ast.Attribute) and parent.value is child
                    and parent.attr in ("read_text", "read_bytes")):
                call = parents.get(parent)
                if isinstance(call, ast.Call) and call.func is parent and path_expression(child):
                    break
            child = parent
        else:
            return False
    return True


def bash_writes_approval(command, guarded):
    """The command writes into a metadata file and names one of its approval fields.

    A python script counts only when the path of the file is a string literal in it, not a
    mention inside a text the script writes elsewhere.
    """
    for item in guarded:
        name = item.parts[-1]
        if name not in command or not any(f in command for f in item.fields):
            continue
        path = re.escape(name) + PATH_END
        if (PYTHON_SCRIPT.search(command) and re.search(QUOTED.format(path=path), command)
                and not python_reads_metadata(command, name)):
            return True
        patterns = (REDIRECT_TO + path, IN_PLACE_TOOLS + SEGMENT + IN_PLACE,
                    TEE + SEGMENT + path, COPY_TO + SEGMENT + path + COPY_END)
        if any(re.search(p, command, re.MULTILINE) for p in patterns):
            return True
    return False


def shell_tokens(command):
    """Tokens of a shell command line by line, operators as tokens of their own.

    A line shlex cannot parse is split on blanks; a long command is cut at MAX_TOKENS.
    """
    tokens = []
    for line in command.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens += list(lexer)
        except ValueError:
            tokens += line.split()
        tokens.append(SHELL_OPERATORS_NEWLINE)
    return tokens[:MAX_TOKENS]


def command_segments(tokens):
    """Simple commands of a token list, split at the shell operators."""
    segments, current = [], []
    for token in tokens:
        if token in SHELL_OPERATORS or token == SHELL_OPERATORS_NEWLINE:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def git_subcommand(words):
    """Subcommand of a git command line, its options skipped; None without one."""
    skip = False
    for word in words:
        if skip:
            skip = False
        elif word in GIT_VALUE_OPTIONS:
            skip = True
        elif not word.startswith(OPTION_PREFIX):
            return word
    return None


def segment_reads_only(segment):
    """Whether one simple command is known not to write files."""
    words = [w for w in segment if not ASSIGNMENT_RE.match(w) and w not in COMMAND_PREFIXES]
    if not words:
        return True
    name, rest = Path(words[0]).name, words[1:]
    if name == GIT_COMMAND:
        return git_subcommand(rest) not in GIT_WRITE_SUBCOMMANDS
    if name == FIND_COMMAND:
        return not any(w in FIND_WRITE_FLAGS for w in rest)
    if name in IN_PLACE_COMMANDS:
        return not IN_PLACE_RE.search(KEY_GAP + KEY_GAP.join(rest))
    return name in READ_ONLY_COMMANDS


def bash_reads_only(command):
    """Whether every simple command of the line is known not to write files.

    A redirection, an interpreter, an unknown program or an in-place edit counts as a write:
    the guard refuses what it cannot tell apart from an edit.
    """
    tokens = shell_tokens(command)
    if any(REDIRECT_CHAR in token for token in tokens):
        return False
    return all(segment_reads_only(segment) for segment in command_segments(tokens))


def bash_paths(event, command):
    """Tokens of the command read as paths from the event cwd that exist or look like a file.

    A word such as `echo` or `x` names no file; `new.md`, `src/x` or an existing path does.
    """
    paths = []
    for token in shell_tokens(command):
        if token in SHELL_OPERATORS or token == SHELL_OPERATORS_NEWLINE or REDIRECT_CHAR in token:
            continue
        if ASSIGNMENT_RE.match(token) or (token.startswith(OPTION_PREFIX) and OPTION_VALUE in token):
            token = token.split(OPTION_VALUE, 1)[1]
        if not token or token.startswith(OPTION_PREFIX):
            continue
        try:
            path = absolute(event, token)
        except (OSError, ValueError, RuntimeError):
            continue
        if path.exists() or Path(token).suffix or PATH_SEPARATOR in token:
            paths.append(path)
    return paths


def inside(root, path):
    """Whether the path lies in the root directory."""
    return root is not None and path.is_relative_to(root)


def existing_dir(path):
    """Nearest existing directory holding the path, or the path itself."""
    for directory in (path, *path.parents):
        if directory.is_dir():
            return directory
    return path


def checkout_dir(path):
    """Nearest directory holding the path that is a git checkout, or None."""
    for directory in (path, *path.parents):
        if (directory / DOT_GIT).exists():
            return directory
    return None


def event_cwd(event):
    """Working directory of the event, else of the process."""
    cwd = event.get(FIELD_CWD)
    return Path(cwd).expanduser() if isinstance(cwd, str) and cwd else Path.cwd()


def absolute(event, raw):
    """Resolved path of a tool argument, relative ones taken from the event cwd."""
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else event_cwd(event) / path).resolve()


def patch_targets(event, patch):
    """(path, changed lines of its section) of every file of an apply_patch text, moves too."""
    sections, current = {}, []
    for line in patch.split(LINE_SEPARATOR):
        found = PATCH_FILE_RE.match(line)
        if found:
            path = absolute(event, (found.group(1) or found.group(2)).strip())
            if found.group(1):
                current = sections.setdefault(path, [])
            else:
                sections[path] = current
            continue
        if line.startswith(PATCH_CHANGED):
            current.append(line)
    return [(path, LINE_SEPARATOR.join(lines)) for path, lines in sections.items()]


def main_checkout(directory, run=None):
    """(store, main checkout) when the directory lies in a read-only main checkout, else None.

    Nested repositories, the git directory and other worktrees of the store are not the main
    checkout. The checkout of the directory is the nearest one holding .git, which must also
    hold the store; a .git directory there is a main checkout, anything else is asked of git
    worktree list. run replaces run_git.
    """
    from .config import find_root, load_config
    from .errors import LoadError
    from .git import worktree_list
    store = find_root(directory)
    if store is None:
        return None
    try:
        config = load_config(store, local=False)
    except LoadError:
        return None
    if not config.main_checkout_read_only:
        return None
    top = checkout_dir(directory)
    if top is None or checkout_dir(store) != top or DOT_GIT in directory.relative_to(top).parts:
        return None
    if (top / DOT_GIT).is_dir():
        return store, top
    found, _ = worktree_list(store, run)
    if not found or found[0].path != top.resolve():
        return None
    return store, found[0].path


def ignored_paths(main, paths, run=None):
    """Those of the paths that git ignores in the main checkout, as given; run replaces run_git."""
    from .git import run_git
    if not paths:
        return set()
    result = (run or run_git)(main, "check-ignore", "--", *(str(p) for p in paths))
    return set(result.out.splitlines()) if result.ok else set()


def main_text(store, main):
    """Refusal of an edit in the read-only main checkout."""
    from .locale import error_locale
    from .keys import HOOK_DENY_MAIN
    return error_locale(store).text(HOOK_DENY_MAIN, main=main)


def main_reason(path, run=None):
    """Refusal when the path is in the main checkout of a store that keeps it read-only.

    Paths git ignores, nested repositories and other worktrees are not refused. run replaces
    run_git.
    """
    found = main_checkout(existing_dir(path), run)
    if found is None or str(path) in ignored_paths(found[1], [path], run):
        return None
    return main_text(*found)


class Guard:
    """Checks of one pre-tool event against the store of the session.

    Every git call of the event goes through one run cache, the gates of the store included.
    """

    def __init__(self, root):
        """Load the store; without one only the main checkout rule applies."""
        from .cache import RunCache
        self.root = root
        self.cache = RunCache()
        self.runtime, self.broken = load(root) if root is not None else (None, None)
        self.ctx = context_of(self.runtime, self.cache) if self.runtime else None
        self.guarded = guarded_files(self.runtime.pipelines) if self.runtime else []

    def fields_of(self, path):
        """(approval fields, metadata file name) when the path is a guarded metadata file."""
        for item in self.guarded:
            if path.parts[-len(item.parts):] == item.parts:
                return item.fields, Path(*item.parts).as_posix()
        return (), None

    def approval_text(self, fields, name):
        """Refusal of an edit of the approval fields."""
        from .keys import HOOK_DENY_APPROVAL
        return self.runtime.locale.text(HOOK_DENY_APPROVAL, fields=FIELDS_SEPARATOR.join(fields),
                                        file=name)

    def mark_text(self):
        """Refusal of a write of the approval mark, in the locale of the store when readable."""
        from .approval import MARK_FILE
        from .locale import error_locale
        from .keys import HOOK_DENY_MARK
        return error_locale(self.root).text(HOOK_DENY_MARK, file=MARK_FILE)

    def edit_reason(self, path, touches):
        """Refusal of an edit of the path; touches(fields) tells whether it changes them."""
        from .approval import MARK_FILE
        if path.name == MARK_FILE:
            return self.mark_text()
        fields, name = self.fields_of(path)
        if fields and touches(fields):
            return self.approval_text(fields, name)
        return main_reason(path, self.cache.git) or self.plan_reason(path)

    def bash_reason(self, event, command):
        """Refusal of a shell command writing approval fields, the mark, frozen or read-only code."""
        from .approval import MARK_FILE
        if bash_writes_approval(command, self.guarded):
            item = next(i for i in self.guarded if i.parts[-1] in command)
            return self.approval_text(item.fields, Path(*item.parts).as_posix())
        if bash_reads_only(command):
            return None
        if MARK_FILE in command:
            return self.mark_text()
        cwd = event_cwd(event).resolve()
        reason = self.plan_reason(cwd)
        if reason:
            return reason
        by_dir = {}
        for path in bash_paths(event, command):
            by_dir.setdefault(existing_dir(path), []).append(path)
        for directory, paths in by_dir.items():
            found = main_checkout(directory, self.cache.git)
            if found is not None:
                ignored = ignored_paths(found[1], paths, self.cache.git)
                if any(str(p) not in ignored for p in paths):
                    return main_text(*found)
            if directory != cwd:
                reason = self.plan_reason(directory)
                if reason:
                    return reason
        return None

    def dir_keys(self, name):
        """Keys the key gates find in, or read as a query from, a directory name."""
        keys = set()
        for gate in key_gates(self.runtime.pipelines):
            keys |= set(gate.find(name))
            key = gate.match(name)
            if key:
                keys.add(key)
        return keys

    def plan_reason(self, path):
        """Refusal of an edit in the work directory of a subject whose code is still frozen.

        The freeze is checked before the directory is asked of the workspace gate: an edit in
        the work directory of an approved subject needs none of the git calls of the gate.
        """
        from .keys import HOOK_DENY_PLAN
        gate = self.runtime.workspace_gate if self.runtime else None
        directory = checkout_dir(path) if gate is not None else None
        if directory is None:
            return None
        for key in sorted(self.dir_keys(directory.name)):
            text = self.frozen_text(key)
            if not text:
                continue
            found, _ = gate.worktrees(self.ctx, {key})
            if directory in {Path(item[0]).resolve() for item in found}:
                return self.runtime.locale.text(HOOK_DENY_PLAN, keys=key, text=text)
        return None

    def frozen_text(self, key):
        """Freeze text of the first existing, not archived subject of the key, or None."""
        from .resolve import by_key
        for pipeline, subject in by_key(self.ctx, self.runtime.pipelines, key):
            if not subject.exists or subject.archived:
                continue
            text = self.frozen(pipeline, subject)
            if text:
                return text
        return None

    def frozen(self, pipeline, subject):
        """Text of the first gate of a blocks_code step that did not pass, or None."""
        from .checkouts import subject_context
        from .gates import Status
        from .keys import STATUS_UNKNOWN
        from .position import applies, evaluate
        from .render import gate_text
        from .workflow_policy import step_applies
        own = subject_context(self.ctx, subject)
        locale = self.runtime.locale
        for step in (s for s in pipeline.steps if s.blocks_code and step_applies(s, subject)):
            if not step.gates:
                return gate_text(locale, step.text, {})
            for ref in (g for g in step.gates if applies(g, subject)):
                result = evaluate(own, ref, subject).result
                if result.passed:
                    continue
                if result.status is Status.UNKNOWN:
                    return locale.text(STATUS_UNKNOWN, reason=result.reason, gate=ref.gate)
                return gate_text(locale, ref.text or step.text, result.facts)
        return None


def edit_touches(tool, data, path):
    """Predicate over approval fields: whether an Edit, MultiEdit or Write changes their lines."""
    if tool == WRITE_TOOL:
        content = str(data.get(CONTENT_FIELD) or "")
        return lambda fields: approval_lines(content, fields) != approval_lines(read_text(path),
                                                                                fields)
    edits = data.get(EDITS_FIELD) or [data]
    texts = [str(edit.get(f) or "") for edit in edits if isinstance(edit, dict)
             for f in TEXT_FIELDS]
    return lambda fields: any(f in text for text in texts for f in fields)


def tool_reason(guard, event, tool, data):
    """Refusal of the tool call, or None."""
    if tool == BASH_TOOL:
        return guard.bash_reason(event, str(data.get(COMMAND_FIELD) or ""))
    if tool == PATCH_TOOL:
        for path, section in patch_targets(event, str(data.get(COMMAND_FIELD) or "")):
            reason = guard.edit_reason(path, lambda fields, section=section: any(f in section
                                                                                for f in fields))
            if reason:
                return reason
        return None
    raw = next((data[f] for f in PATH_FIELDS if isinstance(data.get(f), str) and data[f]), None)
    if raw is None:
        return None
    path = absolute(event, raw)
    return guard.edit_reason(path, edit_touches(tool, data, path))


def tool_paths(event, tool, data):
    """Paths a tool call may write: the file of an edit, the files of a patch, those of a command."""
    if tool == BASH_TOOL:
        command = str(data.get(COMMAND_FIELD) or "")
        return [] if bash_reads_only(command) else bash_paths(event, command)
    if tool == PATCH_TOOL:
        return [path for path, _ in patch_targets(event, str(data.get(COMMAND_FIELD) or ""))]
    raw = next((data[f] for f in PATH_FIELDS if isinstance(data.get(f), str) and data[f]), None)
    return [absolute(event, raw)] if raw is not None else []


def broken_reason(guard, event, tool, data):
    """Refusal of a write outside a store that does not load: nothing guards it until it does.

    Writes inside the store stay allowed, so the store can be repaired; they get the context line.
    """
    from .locale import error_locale
    from .keys import HOOK_DENY_BROKEN
    paths = tool_paths(event, tool, data)
    if all(inside(guard.root, path) for path in paths):
        return None
    reason = " ".join(str(guard.broken).split())
    return error_locale(guard.root).text(HOOK_DENY_BROKEN, reason=reason)


def pre_tool(event, fallback):
    """Refusal of a tool call that edits approval fields, frozen code or a read-only checkout."""
    tool = event.get(FIELD_TOOL)
    data = event.get(FIELD_INPUT)
    if tool not in GUARDED_TOOLS or not isinstance(data, dict):
        return None
    if tool == BASH_TOOL and bash_reads_only(str(data.get(COMMAND_FIELD) or "")):
        return None
    guard = Guard(store_root(event, fallback))
    reason = tool_reason(guard, event, tool, data)
    if reason:
        return deny_output(reason)
    if guard.broken:
        reason = broken_reason(guard, event, tool, data)
        if reason:
            return deny_output(reason)
        if tool != BASH_TOOL:
            return context_output(EVENT_PRE_TOOL, broken_text(guard.root, guard.broken))
    return None


HANDLERS = {EVENT_SESSION_START: session_start, EVENT_PROMPT: prompt_hook,
            EVENT_PRE_TOOL: pre_tool}


def answer(event_name, event, fallback=None):
    """JSON answer to one hook event, or None; failures become a line in the context."""
    if importlib.util.find_spec(YAML_MODULE) is None:
        if event_name == EVENT_PRE_TOOL:
            return None
        return context_output(event_name, ENGINE_BROKEN_FALLBACK.format(reason=MISSING_YAML))
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
