"""Explicit, exact-set contract previews in store-local git metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
import uuid

from . import evidence_log, keys
from .approval import (bound_files, consume_mark, digest, field_names, fields_text,
                       is_fresh, mark_path, mark_time, names_any, now, read_mark, write_fields)
from .approve import pending_prerequisites
from .identity import approver
from .checkouts import subject_context
from .git import common_dir_file
from .render import Report
from .resolve import resolve
from .workflow_policy import applicable_approvals

if TYPE_CHECKING:
    from .approval import Run
    from .context import Context
    from .pipeline import Pipeline

PACKAGE_FILE = "svod-approval-package.json"
PACKAGE_TOKEN = "package"


def package_path(root: Path, run: Run | None = None) -> Path:
    """Local pending package; a store without git cannot prepare consent."""
    path = common_dir_file(root, PACKAGE_FILE, run)
    if path is None:
        raise ValueError("package preparation requires git")
    return path


def read_package(root: Path, run: Run | None = None) -> dict[str, Any] | None:
    """Read the pending snapshot, refusing malformed metadata rather than inferring consent."""
    path = package_path(root, run)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid pending package")
    return data


def selection(ctx: Context, pipelines: list[Pipeline], queries: list[str],
              step: str | None) -> list[dict[str, Any]]:
    """Resolve every query exactly once and capture ready contract declarations and inputs."""
    if step != "approve":
        raise ValueError("packages require explicit --step approve")
    items: list[dict[str, Any]] = []
    seen = set()
    for query in queries:
        found = resolve(ctx, pipelines, query)
        matches = [(p, s) for p, s in found.matches if s.exists and not s.archived]
        if found.ambiguous or len(matches) != 1:
            raise ValueError(f"missing or ambiguous record: {query}")
        pipeline, subject = matches[0]
        own = subject_context(ctx, subject)
        base = cast(Path, subject.path)
        identity = str(base.resolve())
        if identity in seen:
            raise ValueError(f"duplicate record: {query}")
        seen.add(identity)
        refs = applicable_approvals(pipeline, subject, step)
        if len(refs) != 1 or refs[0].purpose != "contract":
            raise ValueError(f"not a unique contract-purpose approval: {query}")
        ref = refs[0]
        if pending_prerequisites(ctx, pipeline, subject, step):
            raise ValueError(f"record not ready: {query}")
        bind = ref.params.get("bind")
        files = bound_files(base, bind) if bind else []
        if not files:
            raise ValueError(f"contract inputs missing: {query}")
        items.append({"identity": identity, "record": subject.id,
                      "root": str(own.root.resolve()), "keys": sorted(subject.keys),
                      "pipeline": pipeline.name, "step": step, "gate": ref.gate,
                      "purpose": ref.purpose, "params": ref.params,
                      "inputs": [{"path": path.relative_to(own.root).as_posix(),
                                  "sha": hashlib.sha256(path.read_bytes()).hexdigest()}
                                 for path in files],
                      "sha": digest(base, bind, ref.params.get("ignore"),
                                    ref.params.get("strip"))})
        if ctx.config.profile_config.get("trusted_actions"):
            from .actions import trust_digest
            items[-1]["trusted_actions"] = trust_digest(ctx, pipeline)
    return sorted(items, key=lambda item: item["identity"])


def package_approve(ctx: Context, pipelines: list[Pipeline], queries: list[str],
                    step: str | None, prepare: bool = False) -> Report:
    """Preview an explicit package without writing individual approval evidence."""
    try:
        items = selection(ctx, pipelines, queries, step)
        if not prepare:
            return apply_package(ctx, pipelines, queries, step, items)
        data = {"token": uuid.uuid4().hex, "at": now().isoformat(), "items": items}
        package_path(ctx.root).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        out = ["Prepared contract package (fresh human approval required):"]
        for item in items:
            out.append(f"{item['record']} --step {step} {item['params']['marker']}")
            out.extend(f"  {entry['path']} {entry['sha']}" for entry in item["inputs"])
            if item.get("trusted_actions"):
                out.append(f"  trusted_actions {item['trusted_actions']}")
        return Report(ok=True, out=out)
    except (OSError, ValueError) as exc:
        return Report(ok=False, refused=True,
                      err=[ctx.locale.text(keys.APPROVE_PACKAGE_ERROR, reason=str(exc))])


def fingerprint(data: dict[str, Any]) -> str:
    """Bind consent to this generation and exact displayed snapshot."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def prompt_package(root: Path, named: list[str], at: Any = None,
                   run: Run | None = None) -> str | None:
    """Only a human event after preparation may bind the pending package."""
    try:
        data = read_package(root, run)
        prepared = mark_time(data) if data else None
        if data is None:
            return None
        if prepared is None:
            return "invalid-package"
        if (at or now()) <= prepared:
            return "event-before-preview"
        if data.get("consumed"):
            consumed = mark_time({"at": data.get("consumed_at")})
            return "consumed-event" if consumed is None or (at or now()) <= consumed else None
        items = data["items"]
        if named and not all(names_any(named, [item["record"], *item["keys"]]) for item in items):
            return None
        return fingerprint(data)
    except (OSError, ValueError, KeyError, TypeError):
        return "invalid-package"


def apply_package(ctx: Context, pipelines: list[Pipeline], queries: list[str],
                  step: str | None, items: list[dict[str, Any]]) -> Report:
    """Validate the complete selection and human decision before individual writes."""
    data = read_package(ctx.root)
    mark = read_mark(ctx.root)
    if (not data or data.get("consumed") or data.get("items") != items
            or not is_fresh(mark, ctx.config.approval_window)
            or not mark or mark.get(PACKAGE_TOKEN) != fingerprint(data)):
        raise ValueError("package changed or no fresh post-preview consent")
    who = approver(ctx)
    if who is None:
        raise ValueError("approver unknown")
    date = now().date().isoformat()
    out = []
    writes = []
    for item in items:
        path = Path(item["identity"]) / item["params"]["file"]
        if path.is_symlink() or not path.parent.is_dir():
            raise ValueError(f"invalid approval target: {path}")
        before = path.read_bytes() if path.exists() else None
        values = dict(zip(field_names(item["params"]["marker"]),
                          (date, who, item["sha"]), strict=True))
        if item.get("trusted_actions"):
            values.update(zip(field_names("trusted_actions"),
                              (date, who, item["trusted_actions"]), strict=True))
        after = fields_text(before.decode("utf-8") if before is not None else "", values).encode()
        writes.append((path, before, after, item))
        out.append(ctx.locale.text(keys.APPROVE_DONE,
                   file=path.relative_to(item["root"]).as_posix(),
                   marker=item["params"]["marker"], date=date, by=who, sha=item["sha"][:12]))
    selected = {identity for item in items for identity in [item["record"], *item["keys"]]}
    metadata = [package_path(ctx.root), cast(Path, mark_path(ctx.root))]
    backups = {path: path.read_bytes() for path in metadata}
    attempted = []
    metadata_attempted = []
    try:
        for path, before, after, item in writes:
            attempted.append((path, before, after))
            write_fields(path, item["params"]["marker"], date, who, item["sha"])
            if item.get("trusted_actions"):
                write_fields(path, "trusted_actions", date, who, item["trusted_actions"])
            if path.read_bytes() != after:
                raise OSError(f"approval write verification failed: {path}")
        try:
            current = selection(ctx, pipelines, queries, step)
        except (OSError, ValueError) as exc:
            raise OSError(f"package changed during writes: {exc}") from exc
        if current != items or read_mark(ctx.root) != mark or read_package(ctx.root) != data:
            raise OSError("package or human decision changed during writes")
        metadata_attempted.append(metadata[0])
        package_path(ctx.root).write_text(json.dumps({**data, "consumed": True,
                                                    "consumed_at": now().isoformat()}),
                                          encoding="utf-8")
        metadata_attempted.append(metadata[1])
        consume_mark(ctx.root, selected, mark)
    except OSError as exc:
        errors = []
        for path, before, _after in reversed(attempted):
            try:
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(before)
            except OSError as rollback:
                errors.append(f"{path}: {rollback}")
        for path in metadata_attempted:
            try:
                path.write_bytes(backups[path])
            except OSError as rollback:
                errors.append(f"{path}: {rollback}")
        if errors:
            raise OSError(f"{exc}; rollback incomplete: {'; '.join(errors)}") from exc
        raise
    for item in items:
        evidence_log.record(ctx.root, item["pipeline"], item["record"],
                            evidence_log.EVENT_APPROVAL_RECORDED, item["step"], by=who)
    return Report(ok=True, out=out)
