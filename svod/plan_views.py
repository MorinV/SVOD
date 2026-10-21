"""Derived text and JSON Canvas views of the same collected planning facts."""
from __future__ import annotations

import json
import math
from typing import Any

from svod.plan_schema import Invalid

MARKER = "structured-planning-v1"


def render_text(data: dict[str, Any]) -> str:
    lines = [f"Collected: {data['collected_at']} (not a transactional snapshot)"]
    for record in data["records"]:
        lines.extend([f"{record['record']} status={record['status']}",
                      f"  Expected: {record['expected'] or 'unknown'}",
                      f"  Actual: {record['actual'] or 'unknown'}"])
        for node in record["nodes"]:
            lines.append(f"  Work {node['id']} [{node['state']}] {node['title']}; "
                         f"actual={node['actual'] or 'unknown'}; "
                         f"blocked_by={','.join(node['blocked_by']) or 'none known'}")
        for criterion in record["criteria"]:
            lines.append(f"  Criterion {criterion['id']} [{criterion['acceptance']}] "
                         f"{criterion['statement']}")
        remaining = [n["id"] for n in record["nodes"] if n["state"] != "done"]
        lines.append(f"  Remaining: {', '.join(remaining) or 'none'}")
    for item in data["diagnostics"]:
        lines.append(f"{item['severity']}: {item['code']} {item['path']}: {item['message']}")
    return "\n".join(lines)


def read_canvas(raw: bytes | None) -> dict[str, Any]:
    if raw is None:
        return {"nodes": [], "edges": []}
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get("svod_generated") != MARKER
                or not isinstance(value.get("nodes"), list)
                or not isinstance(value.get("edges"), list)):
            raise ValueError("Not the reserved generated canvas")
        seen = set()
        for node in value["nodes"]:
            if (not isinstance(node, dict) or not isinstance(node.get("id"), str)
                    or not node["id"] or node.get("type") != "text"
                    or not isinstance(node.get("text"), str)):
                raise ValueError("Invalid canvas node")
            if node["id"] in seen:
                raise ValueError("Duplicate canvas node")
            seen.add(node["id"])
            for key in ("x", "y", "width", "height"):
                if (type(node.get(key)) not in (int, float) or not math.isfinite(node[key])
                        or key in ("width", "height") and node[key] <= 0):
                    raise ValueError("Invalid canvas geometry")
        identities = set(seen)
        for edge in value["edges"]:
            if (not isinstance(edge, dict) or not isinstance(edge.get("id"), str)
                    or not edge["id"] or edge["id"] in identities
                    or not isinstance(edge.get("fromNode"), str)
                    or not isinstance(edge.get("toNode"), str)
                    or edge.get("fromNode") not in seen or edge.get("toNode") not in seen):
                raise ValueError("Invalid canvas edge")
            identities.add(edge["id"])
        return value
    except (ValueError, TypeError, OverflowError) as exc:
        raise Invalid("canvas", "Malformed or unowned plan.canvas; refusing overwrite") from exc


def canvas(data: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    old = {n["id"]: n for n in previous["nodes"]}

    def node(identity: str, facts: Any) -> None:
        index = len(nodes)
        geometry = {"x": (index % 4) * 400, "y": (index // 4) * 300,
                    "width": 360, "height": 240}
        geometry.update({k: old[identity][k] for k in geometry} if identity in old else {})
        nodes.append({"id": identity, "type": "text", **geometry,
                      "text": json.dumps(facts, ensure_ascii=False, sort_keys=True)})

    def edge(source: str, target: str, kind: str) -> None:
        edges.append({"id": f"{kind}:{source}->{target}", "fromNode": source,
                      "toNode": target, "label": kind})

    for record in data["records"]:
        owner = record["record"]
        node(owner, {k: v for k, v in record.items() if k not in ("nodes", "criteria")})
        for work in record["nodes"]:
            identity = owner + ":node:" + work["id"]
            node(identity, work)
            edge(owner, identity, "contains")
            if work.get("parent"):
                edge(owner + ":node:" + work["parent"], identity, "parent")
            for dependency in work["dependencies"]:
                edge(owner + ":node:" + dependency, identity, "depends")
            if work.get("record") in {r["record"] for r in data["records"]}:
                edge(identity, work["record"], "record")
        for criterion in record["criteria"]:
            identity = owner + ":criterion:" + criterion["id"]
            node(identity, criterion)
            edge(owner, identity, "criterion")
            for work in criterion["works"]:
                edge(owner + ":node:" + work, identity, "supports")
            for dependency in criterion["dependencies"]:
                edge(dependency["owner"] + ":criterion:" + dependency["criterion"],
                     identity, "requires")
    known = {n["id"] for n in nodes}
    return {"svod_generated": MARKER, "nodes": nodes,
            "edges": [e for e in edges if e["fromNode"] in known and e["toNode"] in known]}
