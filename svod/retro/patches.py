"""Concrete retro patches built from current instance bytes, without writes during planning."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from difflib import unified_diff
from pathlib import Path
import re
from collections.abc import Callable

import yaml

from .rules import Proposal
from .engine import identity
from .. import evidence_log as ev

LIMIT = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*(?:lines|line_limit|line_length))"
                   r"\s*:\s*(?P<value>[0-9]+)")


@dataclass
class Edit:
    """One original and replacement, retained for stale checks and real unified diffs."""

    path: Path
    name: str
    before: bytes | None
    after: bytes

    def diff(self) -> str:
        """Unified diff of actual file contents."""
        lines = unified_diff((self.before or b"").decode().splitlines(keepends=True),
                             self.after.decode().splitlines(keepends=True),
                             fromfile="a/" + self.name, tofile="b/" + self.name)
        return "".join(line if line.endswith("\n") else
                       line + "\n\\ No newline at end of file\n" for line in lines)


@dataclass
class Plan:
    """Selected edits and the instance they belong to."""

    root: Path
    edits: list[Edit]
    applicable: list[Proposal] = field(default_factory=list)
    unsupported: list[Proposal] = field(default_factory=list)


def input_token(root: Path) -> str:
    """Fingerprint instance inputs without writes or following links; omit runtime caches."""
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
               for part in relative.parts):
            continue
        if path.is_symlink():
            entries.append((str(relative), "link", str(path.readlink())))
        elif path.is_file():
            entries.append((str(relative), "file", sha256(path.read_bytes()).hexdigest()))
    return sha256(json.dumps(entries, ensure_ascii=True).encode()).hexdigest()


def plan_token(planned: Plan, inputs: str, selection: list[tuple[str, str]]) -> str:
    """Bind consent to the instance, query resolution, proposals, input bytes and exact edits."""
    payload = {"version": 1, "root": str(planned.root.resolve()), "inputs": inputs,
               "selection": selection,
               "proposals": [asdict(p) for p in planned.applicable + planned.unsupported],
               "edits": [(e.name, e.before.hex() if e.before is not None else None, e.after.hex())
                         for e in planned.edits]}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def safe_path(root: Path, name: str) -> Path:
    """Only literal instance profile files and the root ignore file; never follow links."""
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name \
            or (name != ".gitignore" and relative.parts[:1] != ("profile",)):
        raise ValueError(f"{name}: unsafe target")
    return checked_path(root, name)


def decision_output(root: Path) -> Path:
    """Validate only the review writer's output, never a proposal target."""
    return checked_path(root, "evidence/decisions.yaml")


def checked_path(root: Path, name: str) -> Path:
    """Check an already allowlisted relative path without following symlinks."""
    relative = Path(name)
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"{name}: unsafe symlink")
    if not path.resolve().is_relative_to(root.resolve()) or (path.exists() and not path.is_file()):
        raise ValueError(f"{name}: unsafe target")
    return path


def yaml_node(text: str) -> yaml.Node | None:
    """Parse safely, rejecting aliases and duplicate keys rather than silently choosing."""
    try:
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
               for token in yaml.scan(text)):
            raise ValueError("ambiguous YAML aliases or anchors")
        node = yaml.compose(text)
        check_node(node)
        return node
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc


def check_node(node: yaml.Node | None) -> None:
    """Require unique scalar keys throughout the editable document."""
    if isinstance(node, yaml.MappingNode):
        keys = [key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)]
        if len(keys) != len(node.value) or len(keys) != len(set(keys)):
            raise ValueError("ambiguous YAML mapping keys")
        for _, value in node.value:
            check_node(value)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            check_node(item)


def plan(root: Path, proposals: list[Proposal]) -> Plan:
    """Plan deterministic additions without modifying instance state."""
    edits: dict[str, Edit] = {}
    applicable = []
    unsupported = []
    seen: dict[tuple[str, str, str], dict | None] = {}
    replacements: dict[tuple[str, str], str] = {}
    for proposal in proposals:
        key = identity(proposal)
        if key in seen:
            if seen[key] != proposal.change:
                raise ValueError(f"{key}: conflicting proposal identity")
            continue
        seen[key] = proposal.change
        change = proposal.change or {}
        if change.get("file") == ".gitignore" and change.get("kind") == "line" \
                and isinstance(change.get("text"), str) and change["text"].strip() \
                and len(change["text"].splitlines()) == 1 \
                and not change["text"].startswith("retro."):
            path = safe_path(root, ".gitignore")
            before = path.read_bytes() if path.exists() else None
            text = (edits[".gitignore"].after if ".gitignore" in edits else before or b"").decode()
            line = str(change["text"])
            newline = "\r\n" if "\r\n" in text else "\n"
            after = text if line in text.splitlines() else (
                text + (newline if text and not text.endswith("\n") else "") + line + newline)
            edits[".gitignore"] = Edit(path, ".gitignore", before, after.encode())
        elif change.get("kind") == "line" and change.get("text") == "optional: true" \
                and str(change.get("anchor", "")).startswith("steps: "):
            name = str(change["file"])
            path = safe_path(root, name)
            before = path.read_bytes()
            text = (edits[name].after if name in edits else before).decode()
            node = yaml_node(text)
            if not isinstance(node, yaml.MappingNode):
                raise ValueError(f"{name}: expected a pipeline mapping")
            steps = [v for k, v in node.value if k.value == "steps"]
            if len(steps) != 1 or not isinstance(steps[0], yaml.SequenceNode):
                raise ValueError(f"{name}: ambiguous steps")
            target = str(change["anchor"])[len("steps: "):]
            matches = [s for s in steps[0].value if isinstance(s, yaml.MappingNode)
                       and any(k.value == "id" and v.value == target for k, v in s.value)]
            if len(matches) != 1:
                raise ValueError(f"{name}: missing or ambiguous step {target}")
            step = matches[0]
            if step.flow_style:
                raise ValueError(f"{name}: ambiguous flow step")
            optional = [v for k, v in step.value if k.value == "optional"]
            if optional:
                value = optional[0]
                after = text[:value.start_mark.index] + "true" + text[value.end_mark.index:]
            else:
                first_key = step.value[0][0]
                id_key = next(k for k, _ in step.value if k.value == "id")
                lines = text.splitlines(keepends=True)
                # Insert beside the literal id, never inside a preceding block scalar.
                line = id_key.start_mark.line + (id_key is first_key)
                lines.insert(line,
                             " " * first_key.start_mark.column + "optional: true"
                             + ("\r\n" if "\r\n" in text else "\n"))
                after = "".join(lines)
            yaml_node(after)
            edits[name] = Edit(path, name, before, after.encode())
        elif change.get("kind") == "line" \
                and (new := LIMIT.fullmatch(str(change.get("text", "")))) \
                and (old := LIMIT.fullmatch(str(change.get("anchor", "")))) \
                and old["key"] == new["key"]:
            name = str(change["file"])
            path = safe_path(root, name)
            setting = (name, old["key"])
            if setting in replacements and replacements[setting] != new["value"]:
                raise ValueError(f"{name}: conflicting changes for {old['key']}")
            replacements[setting] = new["value"]
            before = path.read_bytes()
            text = (edits[name].after if name in edits else before).decode()
            pattern = re.compile(r"(?m)^(?P<prefix>[ \t]*" + re.escape(old["key"])
                                 + r"[ \t]*:[ \t]*)(?P<value>[0-9]+)(?=[ \t]*(?:#|$))")
            matches = list(pattern.finditer(text))
            if len(matches) != 1 or matches[0]["value"] not in (old["value"], new["value"]):
                raise ValueError(f"{name}: missing, ambiguous or stale line-limit anchor")
            match = matches[0]
            settings = scalar_settings(yaml_node(text), old["key"])
            if len(settings) != 1 or settings[0].tag != "tag:yaml.org,2002:int" \
                    or settings[0].start_mark.index != match.start("value"):
                raise ValueError(f"{name}: ambiguous or non-literal line-limit setting")
            after = text[:match.start("value")] + new["value"] + text[match.end("value"):]
            yaml_node(after)
            edits[name] = Edit(path, name, before, after.encode())
        else:
            unsupported.append(proposal)
            continue
        applicable.append(proposal)
    if applicable and not ev.settings(root)[1]:
        path = safe_path(root, ".gitignore")
        before = path.read_bytes() if path.exists() else None
        text = (edits[".gitignore"].after if ".gitignore" in edits else before or b"").decode()
        if not ev.IGNORE_FORMS & {line.strip() for line in text.splitlines()}:
            newline = "\r\n" if "\r\n" in text else "\n"
            text += (newline if text and not text.endswith("\n") else "") + "evidence/" + newline
            edits[".gitignore"] = Edit(path, ".gitignore", before, text.encode())
    return Plan(root, list(edits.values()), applicable, unsupported)


def scalar_settings(node: yaml.Node | None, name: str) -> list[yaml.ScalarNode]:
    """Actual scalar mapping values for a key, not matches in comments or block strings."""
    found = []
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if key.value == name and isinstance(value, yaml.ScalarNode):
                found.append(value)
            found.extend(scalar_settings(value, name))
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            found.extend(scalar_settings(item, name))
    return found


def apply(planned: Plan, finish: Callable[[], None] | None = None) -> None:
    """Write the already planned byte replacements."""
    for edit in planned.edits:
        safe_path(planned.root, edit.name)
        current = edit.path.read_bytes() if edit.path.exists() else None
        if current != edit.before:
            raise ValueError(f"{edit.name}: stale input; preview again")
    written = []
    try:
        for edit in planned.edits:
            if edit.before == edit.after:
                continue
            written.append(edit)
            edit.path.write_bytes(edit.after)
        if finish is not None:
            finish()
    except OSError as exc:
        failures = []
        for edit in reversed(written):
            try:
                safe_path(planned.root, edit.name)
                if edit.before is None:
                    edit.path.unlink(missing_ok=True)
                else:
                    edit.path.write_bytes(edit.before)
            except (OSError, ValueError) as rollback:
                failures.append(f"{edit.name}: {rollback}")
        if failures:
            raise OSError(f"{exc}; rollback failed: {'; '.join(failures)}") from exc
        raise
