"""Agent hooks: the summary at session start, positions named in a prompt, guards before a tool.

Every hook reads one event of Claude Code or Codex as JSON on stdin, prints its JSON answer or
nothing, and never fails: a store that does not load is reported in one line instead of silence.
"""
import importlib.util
import json
import os
import re
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
        from .cli import error_locale
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


def context_of(runtime):
    """Evaluation context of a loaded store."""
    from .context import Context
    return Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                   pipelines=runtime.by_name())


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


def positions(ctx, pipelines, named):
    """Status blocks of the existing subjects the queries resolve to, without repeats."""
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
            pos = position(own, pipeline, subject)
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
    from .notice import update_notice, with_notice
    lines = summarize(context_of(runtime), runtime.pipelines, False)
    lines = with_notice(lines, update_notice(runtime.config, runtime.locale))
    return hook_payload(runtime.locale, lines) if lines else None


def prompt_hook(event, fallback):
    """Approval mark for an approving prompt and positions of the work the prompt names."""
    from .approval import write_mark
    from .keys import HOOK_APPROVAL_MARKED, HOOK_POSITION_HEAD, HOOK_POSITION_TAIL
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
    blocks = []
    keys = approval_keys(runtime, prompt)
    if keys is not None and write_mark(root, keys) is not None:
        blocks.append(locale.text(HOOK_APPROVAL_MARKED, minutes=runtime.config.approval_window))
    ctx = context_of(runtime)
    found = positions(ctx, runtime.pipelines, queries(ctx, runtime.pipelines, prompt))
    if found:
        blocks += [locale.text(HOOK_POSITION_HEAD), *found, locale.text(HOOK_POSITION_TAIL)]
    return context_output(EVENT_PROMPT, BLOCK_SEPARATOR.join(blocks)) if blocks else None


def guarded_files(pipelines):
    """Metadata files holding approval fields, from the approval gates of every pipeline step."""
    from .approval import field_names
    from .gates import PARAM_FILE, PARAM_MARKER, ApprovalGate
    found = {}
    for pipeline in pipelines:
        for step in pipeline.steps:
            for ref in step.gates:
                if isinstance(ref.impl, ApprovalGate):
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
        if PYTHON_SCRIPT.search(command) and re.search(QUOTED.format(path=path), command):
            return True
        patterns = (REDIRECT_TO + path, IN_PLACE_TOOLS + SEGMENT + IN_PLACE,
                    TEE + SEGMENT + path, COPY_TO + SEGMENT + path + COPY_END)
        if any(re.search(p, command, re.MULTILINE) for p in patterns):
            return True
    return False


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


def main_reason(path):
    """Refusal when the path is in the main checkout of a store that keeps it read-only.

    Paths git ignores, nested repositories and other worktrees are not refused.
    """
    from .cli import error_locale
    from .config import find_root, load_config
    from .errors import LoadError
    from .git import run_git, worktree_list
    from .keys import HOOK_DENY_MAIN
    store = find_root(existing_dir(path))
    if store is None:
        return None
    try:
        config = load_config(store, local=False)
    except LoadError:
        return None
    if not config.main_checkout_read_only:
        return None
    found, _ = worktree_list(store)
    if not found or not path.is_relative_to(found[0].path):
        return None
    main = found[0].path
    top = run_git(existing_dir(path), "rev-parse", "--show-toplevel")
    if not top.ok or Path(top.out).resolve() != main:
        return None
    if run_git(main, "check-ignore", "-q", "--", str(path)).ok:
        return None
    return error_locale(store).text(HOOK_DENY_MAIN, main=main)


class Guard:
    """Checks of one pre-tool event against the store of the session."""

    def __init__(self, root):
        """Load the store; without one only the main checkout rule applies."""
        self.root = root
        self.runtime, self.broken = load(root) if root is not None else (None, None)
        self.ctx = context_of(self.runtime) if self.runtime else None
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

    def edit_reason(self, path, touches):
        """Refusal of an edit of the path; touches(fields) tells whether it changes them."""
        fields, name = self.fields_of(path)
        if fields and touches(fields):
            return self.approval_text(fields, name)
        return main_reason(path) or self.plan_reason(path)

    def bash_reason(self, command):
        """Refusal of a shell command writing approval fields."""
        if not bash_writes_approval(command, self.guarded):
            return None
        item = next(i for i in self.guarded if i.parts[-1] in command)
        return self.approval_text(item.fields, Path(*item.parts).as_posix())

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
        """Refusal of an edit in the work directory of a subject whose code is still frozen."""
        from .keys import HOOK_DENY_PLAN
        from .resolve import by_key
        gate = self.runtime.workspace_gate if self.runtime else None
        directory = checkout_dir(path) if gate is not None else None
        if directory is None:
            return None
        for key in sorted(self.dir_keys(directory.name)):
            found, _ = gate.worktrees(self.ctx, {key})
            if directory not in {Path(item[0]).resolve() for item in found}:
                continue
            for pipeline, subject in by_key(self.ctx, self.runtime.pipelines, key):
                if not subject.exists or subject.archived:
                    continue
                text = self.frozen(pipeline, subject)
                if text:
                    return self.runtime.locale.text(HOOK_DENY_PLAN, keys=key, text=text)
        return None

    def frozen(self, pipeline, subject):
        """Text of the first gate of a blocks_code step that did not pass, or None."""
        from .checkouts import subject_context
        from .gates import Status
        from .keys import STATUS_UNKNOWN
        from .position import evaluate
        from .render import gate_text
        own = subject_context(self.ctx, subject)
        locale = self.runtime.locale
        for step in (s for s in pipeline.steps if s.blocks_code):
            if not step.gates:
                return gate_text(locale, step.text, {})
            for ref in step.gates:
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
        return guard.bash_reason(str(data.get(COMMAND_FIELD) or ""))
    if tool == PATCH_TOOL:
        for path, section in patch_targets(event, str(data.get(COMMAND_FIELD) or "")):
            reason = guard.edit_reason(path, lambda fields: any(f in section for f in fields))
            if reason:
                return reason
        return None
    raw = next((data[f] for f in PATH_FIELDS if isinstance(data.get(f), str) and data[f]), None)
    if raw is None:
        return None
    path = absolute(event, raw)
    return guard.edit_reason(path, edit_touches(tool, data, path))


def pre_tool(event, fallback):
    """Refusal of a tool call that edits approval fields, frozen code or a read-only checkout."""
    tool = event.get(FIELD_TOOL)
    data = event.get(FIELD_INPUT)
    if tool not in GUARDED_TOOLS or not isinstance(data, dict):
        return None
    guard = Guard(store_root(event, fallback))
    reason = tool_reason(guard, event, tool, data)
    if reason:
        return deny_output(reason)
    if guard.broken and tool != BASH_TOOL:
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
