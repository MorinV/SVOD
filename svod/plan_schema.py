"""Strict, versioned planning schemas; deliberately separate from legacy YAML."""
from __future__ import annotations

import re
from typing import Any

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


class Invalid(ValueError):
    """A planning input diagnostic with a stable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StrictLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys at every depth."""


def mapping(loader: StrictLoader, node: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise Invalid("yaml", "Mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def parse(text: str) -> dict[str, Any]:
    """Mappings/lists/scalars only; no explicit tags, anchors, aliases or duplicates."""
    try:
        if any(isinstance(t, (AliasToken, AnchorToken, TagToken)) for t in yaml.scan(text)):
            raise Invalid("yaml", "Anchors, aliases and explicit tags are unsupported")
        value = yaml.load(text, Loader=StrictLoader)
    except yaml.YAMLError as exc:
        raise Invalid("yaml", "Malformed planning YAML") from exc
    if not isinstance(value, dict):
        raise Invalid("schema", "Expected a mapping")
    return value


def fields(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    """Require a closed mapping shape."""
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - (optional or set())):
        raise Invalid("schema", f"Expected fields {sorted(required)}")


def text(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise Invalid("schema", "Expected a nonempty string")


def identifier(value: Any) -> None:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Invalid("schema", "Invalid stable ID")


def strings(value: Any) -> None:
    if not isinstance(value, list):
        raise Invalid("schema", "Expected a list of strings")
    for item in value:
        text(item)


def version(value: dict[str, Any]) -> None:
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise Invalid("schema", "Unsupported schema_version; expected integer 1")


def plan_schema(value: dict[str, Any]) -> dict[str, Any]:
    """Validate structural types before resolving graph references."""
    fields(value, {"schema_version", "expected", "nodes", "criteria"})
    version(value)
    text(value["expected"])
    for collection in ("nodes", "criteria"):
        if not isinstance(value[collection], list):
            raise Invalid("schema", f"{collection} must be a list")
        seen = set()
        for item in value[collection]:
            if collection == "nodes":
                fields(item, {"id", "title", "expected"},
                       {"parent", "dependencies", "record", "state", "actual"})
                text(item["title"])
                text(item["expected"])
                for name in ("parent", "record", "state"):
                    if name in item:
                        text(item[name])
                if "actual" in item and item["actual"] is not None:
                    text(item["actual"])
                if "state" in item and item["state"] not in {
                        "open", "active", "blocked", "done", "unknown"}:
                    raise Invalid("schema", "Unknown local execution state")
                if "record" in item and ("state" in item or "actual" in item):
                    raise Invalid("linked_local_conflict", "Remove local state/actual when binding")
            else:
                fields(item, {"id", "statement", "verification", "works"}, {"dependencies"})
                text(item["statement"])
                text(item["verification"])
                strings(item["works"])
            identifier(item["id"])
            if item["id"] in seen:
                raise Invalid("duplicate_id", f"Duplicate {collection} ID {item['id']}")
            seen.add(item["id"])
            item.setdefault("dependencies", [])
            if collection == "nodes":
                strings(item["dependencies"])
            else:
                if not isinstance(item["dependencies"], list):
                    raise Invalid("schema", "Criterion dependencies must be a list")
                for dependency in item["dependencies"]:
                    fields(dependency, {"owner", "criterion"})
                    text(dependency["owner"])
                    identifier(dependency["criterion"])
            for name in ("dependencies", "works"):
                references = item.get(name, [])
                for index, reference in enumerate(references):
                    if reference in references[:index]:
                        raise Invalid("duplicate_reference", f"Duplicate {name} reference")
    return value


def outcome_schema(value: dict[str, Any]) -> dict[str, Any]:
    fields(value, {"schema_version", "actual", "evidence"})
    version(value)
    text(value["actual"])
    strings(value["evidence"])
    return value


def acceptance_schema(value: dict[str, Any]) -> dict[str, Any]:
    fields(value, {"schema_version", "confirmations"})
    version(value)
    if not isinstance(value["confirmations"], list):
        raise Invalid("schema", "confirmations must be a list")
    for item in value["confirmations"]:
        fields(item, {"criterion", "definition", "result", "actual", "evidence",
                      "recorded_at", "work_fingerprint", "evidence_fingerprint"})
        identifier(item["criterion"])
        for key in ("definition", "actual", "recorded_at", "work_fingerprint",
                    "evidence_fingerprint"):
            text(item[key])
        for key in ("definition", "work_fingerprint", "evidence_fingerprint"):
            if not re.fullmatch(r"[a-f0-9]{64}", item[key]):
                raise Invalid("schema", "Expected SHA256 identity")
        if item["result"] not in ("pass", "fail"):
            raise Invalid("schema", "Expected pass/fail verification result")
        strings(item["evidence"])
        if not item["evidence"]:
            raise Invalid("schema", "Confirmation requires evidence")
        from datetime import datetime
        try:
            stamp = datetime.fromisoformat(item["recorded_at"])
            if stamp.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError as exc:
            raise Invalid("schema", "Expected timezone-aware recorded_at") from exc
    return value
