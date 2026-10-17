"""Store configuration: svod.yaml at the store root."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import LoadError
from .paths import CONFIG_FILE
from .yamlio import ENCODING, dump_yaml, read_yaml

FIELD_LOCALE = "locale"
FIELD_PROFILE = "profile"
FIELD_DEFAULT_BRANCH = "default_branch"
FIELD_WORKSPACES = "workspaces"
FIELD_ACTIVE_ORDER = "active_order"
FIELD_RENDER_EXCLUDE = "render_exclude"
FIELD_BINDINGS = "bindings"
FIELD_LOCAL_CONFIG = "local_config"
FIELD_APPROVAL = "approval"
FIELD_PROFILE_CONFIG = "profile_config"
FIELD_WORKSPACE_GATE = "workspace_gate"
FIELD_MAIN_READ_ONLY = "main_checkout_read_only"
FIELD_UPDATE_CHECK = "update_check"
FIELD_SERVICES = "services"
APPROVAL_PHRASES = "phrases"
APPROVAL_WINDOW = "window_minutes"
APPROVAL_FIELDS = frozenset({APPROVAL_PHRASES, APPROVAL_WINDOW})
AGENT_CONTEXT = "agent_context"
SESSION_SUMMARY = "session_summary"
SESSION_START = "session_start"
INDEX_LINES = "index_lines"
AGENT_CONTEXT_FLAGS = frozenset({SESSION_SUMMARY, "prompt_positions", "approval_notice",
                                 "knowledge"})
AGENT_CONTEXT_FIELDS = AGENT_CONTEXT_FLAGS | {SESSION_START, INDEX_LINES}
SESSION_INDEX = "index"
SESSION_FULL = "summary"
SESSION_OFF = "off"
SESSION_MODES = (SESSION_INDEX, SESSION_FULL, SESSION_OFF)
DEFAULT_SESSION_START = SESSION_INDEX
DEFAULT_INDEX_LINES = 40
FIELD_KNOWLEDGE = "knowledge"
KNOWLEDGE_DIR = "dir"
KNOWLEDGE_LIMIT = "limit_lines"
KNOWLEDGE_FIELDS = frozenset({KNOWLEDGE_DIR, KNOWLEDGE_LIMIT})
DEFAULT_KNOWLEDGE_DIR = "knowledge"
DEFAULT_KNOWLEDGE_LIMIT = 20
DEFAULT_WINDOW_MINUTES = 10
REQUIRED_FIELDS = (FIELD_LOCALE, FIELD_PROFILE)
STRING_FIELDS = (FIELD_LOCALE, FIELD_PROFILE, FIELD_DEFAULT_BRANCH, FIELD_WORKSPACES,
                 FIELD_BINDINGS, FIELD_LOCAL_CONFIG, FIELD_WORKSPACE_GATE)
LIST_FIELDS = (FIELD_ACTIVE_ORDER, FIELD_RENDER_EXCLUDE)
BOOL_FIELDS = (FIELD_MAIN_READ_ONLY, FIELD_UPDATE_CHECK)
KNOWN_FIELDS = frozenset(STRING_FIELDS + LIST_FIELDS + BOOL_FIELDS
                         + (FIELD_APPROVAL, FIELD_PROFILE_CONFIG, FIELD_SERVICES,
                            FIELD_KNOWLEDGE))
FIELD_EVIDENCE = "evidence"
EVIDENCE_ENABLED = "enabled"
EVIDENCE_COMMIT = "commit"
EVIDENCE_FIELDS = frozenset({EVIDENCE_ENABLED, EVIDENCE_COMMIT})
KNOWN_FIELDS |= {FIELD_EVIDENCE}
DEFAULT_BRANCH_FALLBACK = "origin/main"
LOCAL_LOGIN = "login"
LOCAL_EMAIL = "email"
LOCAL_FIELDS = (LOCAL_LOGIN, LOCAL_EMAIL, FIELD_WORKSPACES, FIELD_LOCALE)
LOCAL_MAPPINGS = (FIELD_PROFILE_CONFIG,)
FIELD_AUTONOMY = "autonomy"
FIELD_EXTERNAL_EFFECTS = "external_effects"
KNOWN_FIELDS = KNOWN_FIELDS | {FIELD_AUTONOMY, FIELD_EXTERNAL_EFFECTS}
AUTONOMY_GUIDED = "guided"
AUTONOMY_SUPERVISED = "supervised"
AUTONOMY_AUTONOMOUS = "autonomous"
AUTONOMY_LEVELS = (AUTONOMY_GUIDED, AUTONOMY_SUPERVISED, AUTONOMY_AUTONOMOUS)
# Kinds of work (frontmatter `kind` of a subject) autonomy may name besides pipelines.
AUTONOMY_KINDS = frozenset({"hotfix"})
EXTERNAL_DENY = "deny"
EXTERNAL_ALLOW = "allow"
EXTERNAL_PHRASES = "phrases"
EXTERNAL_PATTERNS = (EXTERNAL_DENY, EXTERNAL_ALLOW)
EXTERNAL_FIELDS = frozenset({*EXTERNAL_PATTERNS, EXTERNAL_PHRASES})
DEFAULT_EXTERNAL_PHRASES = ("go ahead", "давай", "выполняй")


@dataclass(frozen=True)
class Config:
    """Validated store configuration with paths resolved against the root."""

    root: Path
    locale: str
    profile: Path
    default_branch: str
    workspaces: Path | None
    active_order: tuple[str, ...]
    render_exclude: tuple[str, ...] = ()
    bindings: Path | None = None
    local_path: Path | None = None
    local_found: bool = False
    login: str | None = None
    email: str | None = None
    approval_phrases: tuple[str, ...] = ()
    approval_window: int = DEFAULT_WINDOW_MINUTES
    profile_config: dict[str, Any] = field(default_factory=dict)
    workspace_gate: str | None = None
    main_checkout_read_only: bool = False
    update_check: bool = True
    services: dict[str, Path] = field(default_factory=dict)
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR
    knowledge_limit: int = DEFAULT_KNOWLEDGE_LIMIT
    evidence_enabled: bool = True
    evidence_commit: bool = True
    autonomy: dict[str, str] = field(default_factory=dict)
    external_deny: tuple[str, ...] = ()
    external_allow: tuple[str, ...] = ()
    external_phrases: tuple[str, ...] = DEFAULT_EXTERNAL_PHRASES


def string_errors(path: Path, data: dict[str, Any], keys: Iterable[str]) -> list[str]:
    """Errors for keys present in data whose value is not a non-empty string."""
    return [f"{path}: {key} must be a non-empty string" for key in keys
            if key in data and (not isinstance(data[key], str) or not data[key].strip())]


def approval_errors(path: Path, data: Any) -> list[str]:
    """Errors of the approval block: known keys, phrases as strings, a positive window."""
    if not isinstance(data, dict):
        return [f"{path}: {FIELD_APPROVAL} must be a mapping"]
    errors = [f"{path}: {FIELD_APPROVAL}: unknown key: {key}"
              for key in sorted(set(data) - APPROVAL_FIELDS)]
    phrases = data.get(APPROVAL_PHRASES, [])
    if not isinstance(phrases, list) or not all(isinstance(x, str) and x.strip() for x in phrases):
        errors.append(f"{path}: {FIELD_APPROVAL}.{APPROVAL_PHRASES} must be a list of strings")
    window = data.get(APPROVAL_WINDOW, DEFAULT_WINDOW_MINUTES)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        errors.append(f"{path}: {FIELD_APPROVAL}.{APPROVAL_WINDOW} must be a positive integer")
    return errors


def services_errors(path: Path, root: Path, data: Any) -> list[str]:
    """Errors of the services mapping: names to relative paths of existing directories."""
    if not isinstance(data, dict):
        return [f"{path}: {FIELD_SERVICES} must be a mapping of names to directories"]
    errors = []
    for name, value in data.items():
        where = f"{path}: {FIELD_SERVICES}.{name}"
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}: {FIELD_SERVICES}: names must be non-empty strings")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"{where} must be a non-empty string")
        elif Path(value).is_absolute():
            errors.append(f"{where} must be relative to the store root: {value}")
        elif not (root / value).is_dir():
            errors.append(f"{where}: service directory not found: {(root / value).resolve()}")
    return errors


def session_mode(value: Any) -> str | None:
    """Mode of a session_start value, or None when it names none; YAML reads `off` as false."""
    if value is False:
        return SESSION_OFF
    return value if isinstance(value, str) and value in SESSION_MODES else None


def agent_context_errors(path: Path, profile_config: Any) -> list[str]:
    """Errors of profile_config.agent_context: a mapping of known keys.

    The switches are booleans, session_start one of SESSION_MODES, index_lines a positive
    integer; session_summary, the old spelling of session_start summary|off, may not say
    otherwise when both are given.
    """
    if not isinstance(profile_config, dict) or AGENT_CONTEXT not in profile_config:
        return []
    where = f"{path}: {FIELD_PROFILE_CONFIG}.{AGENT_CONTEXT}"
    data = profile_config[AGENT_CONTEXT]
    if not isinstance(data, dict):
        return [f"{where} must be a mapping"]
    errors = [f"{where}: unknown key: {key}" for key in sorted(set(data) - AGENT_CONTEXT_FIELDS)]
    errors += [f"{where}.{key} must be a boolean"
               for key in sorted(set(data) & AGENT_CONTEXT_FLAGS)
               if not isinstance(data[key], bool)]
    mode = session_mode(data.get(SESSION_START))
    if SESSION_START in data and mode is None:
        errors.append(f"{where}.{SESSION_START} must be one of {', '.join(SESSION_MODES)}")
    legacy = data.get(SESSION_SUMMARY)
    if mode is not None and isinstance(legacy, bool) \
            and mode != (SESSION_FULL if legacy else SESSION_OFF):
        errors.append(f"{where}: {SESSION_START}: {mode} contradicts "
                      f"{SESSION_SUMMARY}: {str(legacy).lower()}")
    lines = data.get(INDEX_LINES, DEFAULT_INDEX_LINES)
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        errors.append(f"{where}.{INDEX_LINES} must be a positive integer")
    return errors


def agent_context(profile_config: Any) -> dict[str, Any]:
    """profile_config.agent_context as written; empty when absent or not a mapping."""
    data = profile_config.get(AGENT_CONTEXT) if isinstance(profile_config, dict) else None
    return data if isinstance(data, dict) else {}


def session_start_mode(profile_config: Any) -> str:
    """What the session-start hook gives: session_start, else session_summary true|false as
    summary|off, else the index."""
    data = agent_context(profile_config)
    mode = session_mode(data.get(SESSION_START))
    if mode is not None:
        return mode
    legacy = data.get(SESSION_SUMMARY)
    if isinstance(legacy, bool):
        return SESSION_FULL if legacy else SESSION_OFF
    return DEFAULT_SESSION_START


def index_limit(profile_config: Any) -> int:
    """Records the session index lists at most: agent_context.index_lines, 40 by default."""
    lines = agent_context(profile_config).get(INDEX_LINES)
    if isinstance(lines, int) and not isinstance(lines, bool) and lines > 0:
        return lines
    return DEFAULT_INDEX_LINES


def knowledge_errors(path: Path, data: Any) -> list[str]:
    """Errors of the knowledge block: known keys, dir a non-empty string, a positive limit."""
    where = f"{path}: {FIELD_KNOWLEDGE}"
    if not isinstance(data, dict):
        return [f"{where} must be a mapping"]
    errors = [f"{where}: unknown key: {key}" for key in sorted(set(data) - KNOWLEDGE_FIELDS)]
    errors += string_errors(path, data, (KNOWLEDGE_DIR,))
    limit = data.get(KNOWLEDGE_LIMIT, DEFAULT_KNOWLEDGE_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        errors.append(f"{where}.{KNOWLEDGE_LIMIT} must be a positive integer")
    return errors


def evidence_errors(path: Path, data: Any) -> list[str]:
    """Errors of the evidence block: a mapping of known keys with boolean values."""
    if not isinstance(data, dict):
        return [f"{path}: {FIELD_EVIDENCE} must be a mapping"]
    errors = [f"{path}: {FIELD_EVIDENCE}: unknown key: {key}"
              for key in sorted(set(data) - EVIDENCE_FIELDS)]
    errors += [f"{path}: {FIELD_EVIDENCE}.{key} must be a boolean"
               for key in sorted(set(data) & EVIDENCE_FIELDS) if not isinstance(data[key], bool)]
    return errors


def autonomy_errors(path: Path, data: Any) -> list[str]:
    """Errors of the autonomy block: a mapping of names to known levels.

    Whether each name is a pipeline is checked by the loader, which knows the pipelines.
    """
    if not isinstance(data, dict):
        return [f"{path}: {FIELD_AUTONOMY} must be a mapping"]
    return [f"{path}: {FIELD_AUTONOMY}.{name} must be one of {', '.join(AUTONOMY_LEVELS)}"
            for name, level in data.items() if level not in AUTONOMY_LEVELS]


def strings_error(where: str, value: Any) -> str | None:
    """Error of a value that must be a list of non-empty strings, or None."""
    if isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value):
        return None
    return f"{where} must be a list of strings"


def external_errors(path: Path, data: Any) -> list[str]:
    """Errors of the external_effects block: known keys, lists of strings, valid patterns."""
    where = f"{path}: {FIELD_EXTERNAL_EFFECTS}"
    if not isinstance(data, dict):
        return [f"{where} must be a mapping"]
    errors = [f"{where}: unknown key: {key}" for key in sorted(set(data) - EXTERNAL_FIELDS)]
    for key in (*EXTERNAL_PATTERNS, EXTERNAL_PHRASES):
        error = strings_error(f"{where}.{key}", data[key]) if key in data else None
        if error:
            errors.append(error)
        elif key in data and key in EXTERNAL_PATTERNS:
            for pattern in data[key]:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"{where}.{key}: invalid pattern {pattern!r}: {exc}")
    return errors


def read_local(path: Path) -> dict[str, Any]:
    """Validated local config mapping, empty when the file is absent."""
    if not path.is_file():
        return {}
    data = read_yaml(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise LoadError([f"{path}: expected a mapping"])
    known = set(LOCAL_FIELDS) | set(LOCAL_MAPPINGS)
    errors = [f"{path}: unknown key: {key}" for key in sorted(set(data) - known)]
    errors += string_errors(path, data, LOCAL_FIELDS)
    errors += [f"{path}: {key} must be a mapping" for key in LOCAL_MAPPINGS
               if key in data and not isinstance(data[key], dict)]
    if errors:
        raise LoadError(errors)
    return data


def load_config(root: str | Path, local: bool = True) -> Config:
    """Read and validate the config file of the given store root.

    The local config named by local_config is read on top unless local is false: its
    workspaces and locale win, its login and email identify the person.
    """
    root = Path(root).resolve()
    path = root / CONFIG_FILE
    data = read_yaml(path)
    if not isinstance(data, dict):
        raise LoadError([f"{path}: expected a mapping"])
    errors = []
    for key in sorted(set(data) - KNOWN_FIELDS):
        errors.append(f"{path}: unknown key: {key}")
    for key in REQUIRED_FIELDS:
        if key not in data:
            errors.append(f"{path}: missing key: {key}")
    errors += string_errors(path, data, STRING_FIELDS)
    errors += [f"{path}: {key} must be a boolean" for key in BOOL_FIELDS
               if key in data and not isinstance(data[key], bool)]
    if FIELD_APPROVAL in data:
        errors += approval_errors(path, data[FIELD_APPROVAL])
    if not isinstance(data.get(FIELD_PROFILE_CONFIG, {}), dict):
        errors.append(f"{path}: {FIELD_PROFILE_CONFIG} must be a mapping")
    errors += agent_context_errors(path, data.get(FIELD_PROFILE_CONFIG))
    if FIELD_SERVICES in data:
        errors += services_errors(path, root, data[FIELD_SERVICES])
    errors += knowledge_errors(path, data[FIELD_KNOWLEDGE]) if FIELD_KNOWLEDGE in data else []
    if FIELD_EVIDENCE in data:
        errors += evidence_errors(path, data[FIELD_EVIDENCE])
    for key in LIST_FIELDS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            errors.append(f"{path}: {key} must be a list of strings")
    errors += autonomy_errors(path, data.get(FIELD_AUTONOMY, {}))
    errors += external_errors(path, data.get(FIELD_EXTERNAL_EFFECTS, {}))
    if errors:
        raise LoadError(errors)
    profile = root / data[FIELD_PROFILE]
    if not profile.is_dir():
        raise LoadError([f"{path}: profile directory not found: {profile}"])
    local_path = root / data[FIELD_LOCAL_CONFIG] if data.get(FIELD_LOCAL_CONFIG) else None
    own: dict[str, Any] = read_local(local_path) if local and local_path is not None else {}
    workspaces = own.get(FIELD_WORKSPACES, data.get(FIELD_WORKSPACES))
    approval = data.get(FIELD_APPROVAL) or {}
    store_locale: str = data[FIELD_LOCALE]
    knowledge = data.get(FIELD_KNOWLEDGE) or {}
    return Config(
        root=root,
        locale=own.get(FIELD_LOCALE, store_locale),
        profile=profile.resolve(),
        default_branch=data.get(FIELD_DEFAULT_BRANCH, DEFAULT_BRANCH_FALLBACK),
        workspaces=(root / workspaces).resolve() if workspaces else None,
        active_order=tuple(data.get(FIELD_ACTIVE_ORDER, [])),
        render_exclude=tuple(data.get(FIELD_RENDER_EXCLUDE, [])),
        bindings=root / data[FIELD_BINDINGS] if data.get(FIELD_BINDINGS) else None,
        local_path=local_path,
        local_found=local_path is not None and local_path.is_file(),
        login=own.get(LOCAL_LOGIN),
        email=own.get(LOCAL_EMAIL),
        approval_phrases=tuple(approval.get(APPROVAL_PHRASES, [])),
        approval_window=approval.get(APPROVAL_WINDOW, DEFAULT_WINDOW_MINUTES),
        profile_config=data.get(FIELD_PROFILE_CONFIG) or {},
        workspace_gate=data.get(FIELD_WORKSPACE_GATE),
        main_checkout_read_only=data.get(FIELD_MAIN_READ_ONLY, False),
        update_check=data.get(FIELD_UPDATE_CHECK, True),
        services={name: (root / value).resolve()
                  for name, value in (data.get(FIELD_SERVICES) or {}).items()},
        knowledge_dir=knowledge.get(KNOWLEDGE_DIR, DEFAULT_KNOWLEDGE_DIR),
        knowledge_limit=knowledge.get(KNOWLEDGE_LIMIT, DEFAULT_KNOWLEDGE_LIMIT),
        evidence_enabled=(data.get(FIELD_EVIDENCE) or {}).get(EVIDENCE_ENABLED, True),
        evidence_commit=(data.get(FIELD_EVIDENCE) or {}).get(EVIDENCE_COMMIT, True),
        **policy_settings(data),
    )


def policy_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Config fields of the validated autonomy and external_effects blocks."""
    external = data.get(FIELD_EXTERNAL_EFFECTS) or {}
    return {"autonomy": dict(data.get(FIELD_AUTONOMY) or {}),
            "external_deny": tuple(external.get(EXTERNAL_DENY, ())),
            "external_allow": tuple(external.get(EXTERNAL_ALLOW, ())),
            "external_phrases": tuple(external.get(EXTERNAL_PHRASES, DEFAULT_EXTERNAL_PHRASES))}


def write_local(path: str | Path, values: dict[str, Any]) -> None:
    """Write the local config with the non-empty values, in the given order."""
    data = {key: value for key, value in values.items() if value}
    Path(path).write_text(dump_yaml(data), encoding=ENCODING)
