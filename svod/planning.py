"""Read-only planning facts. No workflow evaluation or executable profile loading."""
from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from svod.frontmatter import read_frontmatter
from svod.plan_schema import (Invalid, acceptance_schema, outcome_schema, parse, plan_schema,
                              strings, text)
from svod import plan_write


def digest(value: Any) -> str:
    content = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(content).hexdigest()


class Collector:
    """One request's primary facts and reference indexes, without executing policy."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.diagnostics: list[dict[str, str]] = []
        self.records: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, dict[str, Any]] = {}
        self.children: dict[str, list[str]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.inputs: dict[str, bytes | None] = {}
        for kind in ("projects", "features", "tasks", "research"):
            for card in sorted((root / "work" / kind).glob("*/card.md")):
                ref = card.parent.relative_to(root).as_posix()
                try:
                    self.safe(ref + "/card.md")
                    self.track(ref + "/card.md")
                    data = read_frontmatter(card) or {}
                    parent = data.get("parent")
                    if isinstance(parent, str) and parent:
                        self.children.setdefault(parent, []).append(ref)
                except Invalid as exc:
                    self.diagnostic(exc.code, ref, str(exc))

    def diagnostic(self, code: str, path: str, message: str,
                   severity: str = "error") -> None:
        item = {"code": code, "path": path, "message": message, "severity": severity}
        if item not in self.diagnostics:
            self.diagnostics.append(item)

    def safe(self, ref: str) -> Path:
        path = Path(ref)
        if (path.is_absolute() or ".." in path.parts or "\\" in ref or "\x00" in ref
                or not path.parts):
            raise Invalid("unsafe_path", "Path must resolve inside the store without traversal")
        try:
            resolved = (self.root / path).resolve()
        except (OSError, ValueError, RuntimeError) as exc:
            raise Invalid("unsafe_path", "Path cannot be safely resolved inside the store") from exc
        if not resolved.is_relative_to(self.root):
            raise Invalid("unsafe_path", "Path must resolve inside the store without traversal")
        return self.root / path

    def load(self, ref: str, schema: Any) -> dict[str, Any] | None:
        try:
            self.track(ref)
            return schema(parse(self.safe(ref).read_text(encoding="utf-8")))
        except Invalid as exc:
            self.diagnostic(exc.code, ref, str(exc))
        except (OSError, UnicodeError):
            self.diagnostic("unreadable", ref, "Missing or unreadable planning input")
        return None

    def track(self, ref: str) -> None:
        if ref not in self.inputs:
            try:
                self.inputs[ref] = plan_write.read_bytes(self.safe(ref))
            except OSError as exc:
                raise Invalid("unreadable", f"Missing or unreadable planning input: {ref}") from exc

    def unchanged(self) -> bool:
        for ref, before in self.inputs.items():
            try:
                if plan_write.read_bytes(self.safe(ref)) != before:
                    return False
            except (Invalid, OSError):
                return False
        return True

    def evidence(self, evidence: list[str]) -> None:
        from urllib.parse import urlsplit
        for ref in evidence:
            if ref.startswith(("https://", "http://")):
                try:
                    if not urlsplit(ref).netloc:
                        raise ValueError("Missing URL authority")
                except ValueError as exc:
                    raise Invalid("evidence", "Invalid evidence URL") from exc
                continue
            path = self.safe(ref)
            self.track(ref)
            if not path.is_file():
                raise Invalid("missing_evidence", "Missing evidence file")

    def evidence_identity(self, evidence: list[str]) -> str:
        self.evidence(evidence)
        return digest({ref: hashlib.sha256(self.inputs[ref] or b"").hexdigest()
                       if ref in self.inputs else ref for ref in evidence})

    def fact(self, ref: str) -> dict[str, Any]:
        if ref in self.facts:
            return self.facts[ref]
        fact: dict[str, Any] = {"record": ref, "state": "unknown", "actual": None,
                                "evidence": [], "parent": None}
        self.facts[ref] = fact
        try:
            path = self.safe(ref + "/card.md")
            self.track(ref + "/card.md")
            card = read_frontmatter(path)
            if not card:
                raise Invalid("missing_record", "Missing or invalid card.md")
            fact.update(state=card.get("status", "unknown"), parent=card.get("parent"))
            outcome = self.safe(ref + "/outcome.yaml")
            self.track(ref + "/outcome.yaml")
            if ref.startswith("work/research/"):
                return fact
            if not outcome.exists():
                self.diagnostic("missing_outcome", ref + "/outcome.yaml",
                                "Actual result is unknown", "warning")
            else:
                value = self.load(ref + "/outcome.yaml", outcome_schema)
                if value:
                    self.evidence(value["evidence"])
                    fact.update(actual=value["actual"], evidence=value["evidence"])
        except Invalid as exc:
            self.diagnostic(exc.code, ref, str(exc))
        return fact

    def visit(self, ref: str) -> None:
        if ref in self.records:
            return
        fact = self.fact(ref)
        record: dict[str, Any] = {"record": ref, "status": fact["state"],
                                  "actual": fact["actual"], "evidence": fact["evidence"],
                                  "expected": None, "nodes": [], "criteria": []}
        self.records[ref] = record
        plan = self.load(ref + "/plan.yaml", plan_schema)
        if plan is None:
            return
        self.plans[ref] = plan
        record["expected"] = plan["expected"]
        nodes = {n["id"]: n for n in plan["nodes"]}
        graph: dict[str, list[str]] = {}
        linked = set()
        for node in plan["nodes"]:
            edges = node["dependencies"] + ([node["parent"]] if "parent" in node else [])
            graph[node["id"]] = edges
            for target in edges:
                if target not in nodes:
                    self.diagnostic("missing_node", ref, f"Unknown node {target}")
            item = {**node, "state": node.get("state", "unknown"),
                    "actual": node.get("actual")}
            if "record" in node:
                target = node["record"]
                linked.add(target)
                child = self.fact(target)
                item.update(state=child["state"], actual=child["actual"],
                            evidence=child["evidence"])
                if child["parent"] != ref:
                    self.diagnostic("parent_conflict", target, f"Expected parent {ref}")
                if target.startswith(("work/projects/", "work/features/")):
                    self.visit(target)
            record["nodes"].append(item)
        self.cycles(graph, ref)
        for item in record["nodes"]:
            item["blocked_by"] = [key for key in item["dependencies"]
                                  if key not in nodes or next(
                                      (n["state"] for n in record["nodes"] if n["id"] == key),
                                      "unknown") != "done"]
        for child_ref in self.children.get(ref, []):
            if child_ref not in linked:
                self.diagnostic("unplanned_child", child_ref,
                                f"Absent from plan of {ref}", "warning")
        for criterion in plan["criteria"]:
            for work in criterion["works"]:
                if work not in nodes:
                    self.diagnostic("missing_node", ref, f"Unknown supporting node {work}")
            record["criteria"].append({**criterion, "acceptance": "unconfirmed"})
            for dependency in criterion["dependencies"]:
                self.visit(dependency["owner"])

    def cycles(self, graph: dict[str, list[str]], path: str) -> None:
        active: set[str] = set()
        done: set[str] = set()

        def walk(key: str) -> None:
            if key in active:
                self.diagnostic("cycle", path, f"Cycle at {key}")
                return
            if key in done:
                return
            active.add(key)
            for target in graph.get(key, []):
                walk(target)
            active.remove(key)
            done.add(key)

        for key in graph:
            walk(key)

    def result(self, owner: str | None) -> dict[str, Any]:
        owners = [owner] if owner else sorted(
            p.parent.relative_to(self.root).as_posix()
            for p in (self.root / "work/projects").glob("*/card.md"))
        for ref in owners:
            self.visit(ref)
        graph = {}
        for ref, record in self.records.items():
            for c in record["criteria"]:
                graph[ref + "#" + c["id"]] = [
                    d["owner"] + "#" + d["criterion"] for d in c["dependencies"]]
        for targets in graph.values():
            for target in targets:
                if target not in graph:
                    self.diagnostic("missing_criterion", target, "Unknown criterion dependency")
        self.cycles(graph, owner or "--all")
        record_graph = {ref: [n["record"] for n in r["nodes"] if "record" in n]
                        for ref, r in self.records.items()}
        self.cycles(record_graph, owner or "--all")
        reverse: dict[str, list[dict[str, str]]] = {}
        for ref, record in self.records.items():
            nodes = {n["id"]: n for n in record["nodes"]}
            for criterion in record["criteria"]:
                for work in criterion["works"]:
                    target = nodes.get(work, {}).get("record", ref + ":node:" + work)
                    support = {"owner": ref, "criterion": criterion["id"]}
                    if support not in reverse.setdefault(target, []):
                        reverse[target].append(support)
        for ref, record in self.records.items():
            for node in record["nodes"]:
                node["supports"] = reverse.get(node.get("record", ref + ":node:" + node["id"]), [])
        self.acceptances()
        if not self.unchanged():
            self.diagnostic("input_changed", owner or "--all",
                            "Inputs changed during collection; repeat query", "warning")
        return {"schema_version": 1, "collected_at": datetime.now(timezone.utc).isoformat(),
                "records": list(self.records.values()), "diagnostics": self.diagnostics}

    def acceptances(self) -> None:
        criteria = {(ref, c["id"]): c for ref, r in self.records.items() for c in r["criteria"]}

        def definition(key: tuple[str, str], seen: set[tuple[str, str]]) -> Any:
            if key in seen or key not in criteria:
                return {"unresolved": key}
            criterion = criteria[key]
            return {"criterion": {k: criterion[k] for k in (
                "id", "statement", "verification", "works", "dependencies")},
                "dependencies": [definition((d["owner"], d["criterion"]), seen | {key})
                                 for d in criterion["dependencies"]]}

        def work(key: tuple[str, str], seen: set[tuple[str, str]]) -> Any:
            if key in seen or key not in criteria:
                return None
            ref, _ = key
            criterion = criteria[key]
            nodes = {n["id"]: n for n in self.records[ref]["nodes"]}
            def supporting(node: Any, visited: set[str]) -> Any:
                if not node:
                    return node
                # Outcome paths alone do not identify the verified supporting result.
                # Include already tracked bytes at every nested/dependency work boundary.
                node = {**node, "evidence_identity": digest({
                    evidence: hashlib.sha256(self.inputs[evidence] or b"").hexdigest()
                    if evidence in self.inputs else evidence
                    for evidence in node.get("evidence", [])})}
                if node.get("record") not in self.records:
                    return node
                nested = node["record"]
                if nested in visited:
                    return {"cycle": nested}
                return {"node": node, "children": [supporting(n, visited | {nested})
                        for n in self.records[nested]["nodes"]]}

            return {"works": [supporting(nodes.get(w), {ref}) for w in criterion["works"]],
                    "dependencies": [work((d["owner"], d["criterion"]), seen | {key})
                                     for d in criterion["dependencies"]]}

        for ref, record in self.records.items():
            history = []
            path = ref + "/acceptance.yaml"
            try:
                self.track(path)
                if self.inputs[path] is not None:
                    value = self.load(path, acceptance_schema)
                    if value is not None:
                        history = value["confirmations"]
            except Invalid as exc:
                self.diagnostic(exc.code, path, str(exc))
            known = {c["id"] for c in record["criteria"]}
            for entry in history:
                if entry["criterion"] not in known:
                    self.diagnostic("orphan_confirmation", path,
                                    f"Historical confirmation of removed {entry['criterion']}",
                                    "warning")
            for c in record["criteria"]:
                key = (ref, c["id"])
                c["definition"] = digest(definition(key, set()))
                c["work_fingerprint"] = digest(work(key, set()))
                c["history"] = [h for h in history if h["criterion"] == c["id"]]
                if c["history"]:
                    latest = c["history"][-1]
                    valid = (latest["definition"] == c["definition"]
                             and latest["work_fingerprint"] == c["work_fingerprint"])
                    try:
                        valid = (valid and self.evidence_identity(latest["evidence"])
                                 == latest["evidence_fingerprint"])
                    except Invalid as exc:
                        self.diagnostic(exc.code, path, str(exc))
                        valid = False
                    c["acceptance"] = latest["result"] if valid else "review_required"
        resolved: set[tuple[str, str]] = set()

        def resolve(key: tuple[str, str], active: set[tuple[str, str]]) -> str:
            if key in active or key not in criteria:
                return "review_required"
            c = criteria[key]
            if key not in resolved:
                states = [resolve((d["owner"], d["criterion"]), active | {key})
                          for d in c["dependencies"]]
                if c["acceptance"] == "pass" and any(s != "pass" for s in states):
                    c["acceptance"] = "review_required"
                resolved.add(key)
            return str(c["acceptance"])

        for key in criteria:
            resolve(key, set())
        if any(d["severity"] == "error" for d in self.diagnostics):
            for c in criteria.values():
                if c["acceptance"] == "pass":
                    c["acceptance"] = "review_required"


def collect(root: Path, owner: str | None) -> dict[str, Any]:
    """Collect current facts without a persistent cache or workflow evaluation."""
    return Collector(root).result(owner)


def command(root: Path, args: Any) -> int:
    """Render planning facts at the CLI boundary."""
    from svod.plan_views import canvas, read_canvas, render_text
    if args.operation == "summary" and bool(args.record) == bool(args.all):
        print("Choose exactly one record or --all", file=sys.stderr)
        return 2
    try:
        collector = Collector(root)
        data = collector.result(args.record)
        if args.operation == "confirm":
            errors = [d for d in data["diagnostics"] if d["severity"] == "error"]
            if errors:
                raise Invalid("invalid_plan", "Resolve plan diagnostics before confirmation")
            criterion = next((c for c in collector.records[args.record]["criteria"]
                              if c["id"] == args.criterion), None)
            if criterion is None:
                raise Invalid("missing_criterion", "Unknown criterion ID")
            text(args.actual)
            strings(args.evidence)
            collector.evidence(args.evidence)
            path = collector.safe(args.record + "/acceptance.yaml")
            expected = collector.inputs[args.record + "/acceptance.yaml"]
            existing: dict[str, Any] = (
                acceptance_schema(parse(expected.decode())) if expected else {
                    "schema_version": 1, "confirmations": []})
            existing["confirmations"].append({
                "criterion": args.criterion, "definition": criterion["definition"],
                "work_fingerprint": criterion["work_fingerprint"], "result": args.result,
                "actual": args.actual, "evidence": args.evidence,
                "evidence_fingerprint": collector.evidence_identity(args.evidence),
                "recorded_at": datetime.now(timezone.utc).isoformat()})
            plan_write.replace(path, (json.dumps(existing, indent=2) + "\n").encode(), expected,
                               collector.unchanged)
            print(f"Recorded verification of {args.record}#{args.criterion}: {args.result}")
            return 0
        if args.operation == "canvas":
            path = collector.safe(args.record + "/plan.canvas")
            expected = plan_write.read_bytes(path)
            previous = read_canvas(expected)
            content = canvas(data, previous)
            plan_write.replace(path, (json.dumps(content, indent=2) + "\n").encode(), expected,
                               collector.unchanged)
            print(path.relative_to(root))
        elif getattr(args, "json", False):
            print(json.dumps(data, ensure_ascii=False, allow_nan=False))
        else:
            print(render_text(data))
        return int(bool(data["diagnostics"]))
    except (Invalid, OSError, UnicodeError) as exc:
        print(f"{getattr(exc, 'code', 'write')}: {exc}", file=sys.stderr)
        return 2
