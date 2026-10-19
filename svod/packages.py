"""Predetermined reviewed local packages. Trusted scripts, NOT an OS sandbox."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .actions import script_path
from .context import Context
from .loader import load_runtime
from .resolve import resolve

ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, rel: str) -> Path:
    """Only lexical relative paths, with no symlink components."""
    path = Path(rel)
    if not rel or path.is_absolute() or ".." in path.parts or str(path) != rel:
        raise ValueError("unsafe relative path")
    target = root / path
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("symlink path is not supported")
    return target


def runtime_record(root: Path, record: str):
    runtime = load_runtime(root)
    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    matches = [(p, s) for p, s in resolve(ctx, runtime.pipelines, record).matches if s.exists]
    if len(matches) != 1:
        raise ValueError("record must resolve exactly once")
    return ctx, *matches[0]


def validate(root: Path, record: str, package: dict[str, Any]) -> dict[str, Any]:
    """Strict admission, exact pipeline IDs and a separately reviewed fixture declaration."""
    if (not isinstance(package, dict) or set(package) != {"version", "id", "record", "steps"}
            or type(package["version"]) is not int or package["version"] != 1
            or not isinstance(package["id"], str) or not ID.fullmatch(package["id"])
            or package["record"] != record or not isinstance(package["steps"], list)
            or not 1 <= len(package["steps"]) <= 100):
        raise ValueError("invalid package schema/version/record")
    ctx, pipeline, subject = runtime_record(root, record)
    reviewed = ctx.config.profile_config.get("local_packages", {})
    seen = set()
    for step in package["steps"]:
        fields = {"id", "step_id", "action", "args", "timeout", "inputs", "outputs"}
        if (not isinstance(step, dict) or set(step) != fields
                or not isinstance(step["id"], str) or not ID.fullmatch(step["id"])
                or step["id"] in seen or not isinstance(step["action"], str)
                or not isinstance(step["args"], list)
                or not all(isinstance(a, str) and "\0" not in a for a in step["args"])
                or type(step["timeout"]) not in (float, int)
                or not math.isfinite(step["timeout"]) or not 0 < step["timeout"] <= 600):
            raise ValueError("invalid step schema/id/args/timeout")
        seen.add(step["id"])
        declaration = reviewed.get(step["action"]) if isinstance(reviewed, dict) else None
        if (not isinstance(declaration, dict)
                or set(declaration) != {"sha256", "kind", "args", "inputs", "outputs"}
                or declaration["kind"] not in ("action", "check")
                or any(step[k] != declaration[k] for k in ("args", "inputs", "outputs"))):
            raise ValueError("action is not an exact reviewed local declaration")
        script = script_path(ctx, step["action"])
        if (script is None or any(p.is_symlink() for p in (script, *script.parents))
                or digest(script.read_bytes()) != declaration["sha256"]):
            raise ValueError("reviewed script changed or missing")
        from .position import steps_of
        from .pipeline import step_applies
        routes = [s for s in steps_of(ctx, pipeline, subject)
                  if s.id == step["step_id"] and s.action == step["action"]
                  and step_applies(s, subject)]
        if len(routes) != 1:
            raise ValueError("exact applicable pipeline step_id/action required")
        for field in ("inputs", "outputs"):
            if (not isinstance(step[field], list)
                    or not all(isinstance(p, str) for p in step[field])
                    or len(set(step[field])) != len(step[field])):
                raise ValueError("invalid path declarations")
            for rel in step[field]:
                safe_path(root, rel)
        if set(step["inputs"]) & set(step["outputs"]):
            raise ValueError("inputs and outputs must be separate")
    return package


def add_parser(commands) -> None:
    parser = commands.add_parser("package", help="reviewed local execution and saved context")
    operations = parser.add_subparsers(dest="operation", required=True)
    for name in ("validate", "run", "status", "resume", "read"):
        operation = operations.add_parser(name)
        operation.add_argument("record")
        operation.add_argument("target")
        operation.add_argument("--json", action="store_true")
        if name == "resume":
            operation.add_argument("--decision", required=True)
        if name == "read":
            operation.add_argument("--step", required=True, help="saved step ID to page")
            operation.add_argument("--offset", type=int, default=0)
            operation.add_argument("--limit", type=int, default=4096)


def manifests(root: Path, package: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for rel in sorted({p for s in package["steps"] for k in ("inputs", "outputs") for p in s[k]}):
        path = safe_path(root, rel)
        if not path.exists():
            result[rel] = {"type": "missing"}
        elif path.is_file():
            result[rel] = {"type": "file", "sha256": digest(path.read_bytes())}
        else:
            raise ValueError("significant paths must be regular files or missing")
    return result


def snapshot(root: Path, record: str, commands: str | None = None) -> str:
    from .actions import action_env, trust_digest
    ctx, pipeline, subject = runtime_record(root, record)
    # Command snapshot is immutable, while successful steps advance record environment.
    env = action_env(ctx, pipeline, subject)
    return digest(json.dumps([commands or trust_digest(ctx, pipeline), env],
                             sort_keys=True).encode())



def policy(root: Path, record: str, step: dict[str, Any]):
    """The do policy, plus exact route and fail-closed entry/freeze checks; never force."""
    from .actions import trust_required, trusted_reason
    from .position import freeze, position
    ctx, pipeline, subject = runtime_record(root, record)
    if trust_required(ctx, subject):
        reason = trusted_reason(ctx, pipeline, subject, step["action"])
        if reason:
            raise ValueError(reason)
        if step["args"]:
            raise ValueError("trusted dispatch does not accept extra arguments")
    pos = position(ctx, pipeline, subject)
    if (freeze(ctx, pipeline, subject) or pos.blocked or pos.current_blocked
            or pos.unknown or pos.violations):
        raise ValueError("policy frozen, blocked or unknown; USER decision required")
    route = next((s for s in pos.steps if s.step.id == step["step_id"]
                  and s.step.action == step["action"]), None)
    if route is None:
        raise ValueError("pipeline step not applicable")
    if (pos.done is None and not route.passed
            and (pos.current is None or pos.steps.index(route) > pos.steps.index(pos.current))):
        raise ValueError("pipeline step not reached")
    return ctx, pipeline, subject


def project(state: dict[str, Any]) -> dict[str, Any]:
    return {k: state[k] for k in ("run_id", "record", "revision", "status", "reason", "steps")} | {
        "remaining": [s["id"] for s in state["steps"] if s["status"] != "succeeded"],
        "decision_owner": "USER" if state["status"] != "succeeded" else None,
        "read": f"svod package read {state['record']} {state['run_id']} --step <id>"}


def execute(root: Path, directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    from .actions import Run
    from .cli import do_action
    from argparse import Namespace
    from .package_store import save
    package = state["package"]
    from .actions import trust_digest
    initial_ctx, initial_pipeline, _ = runtime_record(root, state["record"])
    commands = trust_digest(initial_ctx, initial_pipeline)
    for step, saved in zip(package["steps"], state["steps"], strict=True):
        if saved["status"] == "succeeded":
            continue
        try:
            validate(root, state["record"], package)
            if snapshot(root, state["record"]) != state["snapshot"]:
                raise ValueError("commands/config/environment changed")
            if manifests(root, package) != state["boundary"]:
                raise ValueError("significant input/output changed")
            ctx, pipeline, subject = policy(root, state["record"], step)
        except (OSError, ValueError) as exc:
            state.update(status="waiting", reason=str(exc))
            save(directory, state)
            return state
        attempt = len(saved["logs"])
        ref = f"{step['id']}-{attempt}.log"
        log = directory / ref
        import os
        with log.open("xb") as output:
            os.chmod(log, 0o600)
            saved.update(status="running")
            saved["logs"].append({"ref": ref, "sha256": None, "bytes": None})
            state.update(status="running", reason=None)
            save(directory, state)  # durable intent BEFORE spawn
            dispatch = Namespace(command="do", name=step["action"], query=state["record"],
                                 extra=step["args"], timeout=step["timeout"], list=False,
                                 force=False, _package=step, _output=output)
            code = do_action(ctx, list(ctx.pipelines.values()), dispatch)
            run = getattr(dispatch, "_result", Run(code))
            output.flush()
            os.fsync(output.fileno())
        data = log.read_bytes()
        saved["logs"][-1].update(sha256=digest(data), bytes=len(data))
        saved.update(status="succeeded" if run.code == 0 else "failed", code=run.code,
                     timed_out=run.timed_out, excerpt=data[-512:].decode("utf-8", "replace"))
        if run.code == 0:
            current = manifests(root, package)
            # Only declared outputs of this successful step advance the expected boundary.
            for rel in step["outputs"]:
                state["boundary"][rel] = current[rel]
            state["snapshot"] = snapshot(root, state["record"], commands)
            current_ctx, current_pipeline, _ = runtime_record(root, state["record"])
            if trust_digest(current_ctx, current_pipeline) != commands:
                state.update(status="waiting", reason="commands changed during action")
                save(directory, state)
                return state
            if current != state["boundary"]:
                state.update(status="waiting", reason="unexpected significant input/output change")
                save(directory, state)
                return state
        state.update(status="waiting" if run.code else "running",
                     reason=(f"{step['id']}: exit {run.code}; USER decision required"
                             if run.code else None))
        save(directory, state)
        if run.code:
            return state
    state.update(status="succeeded", reason=None)
    save(directory, state)
    return state


def sources(directory: Path, state: dict[str, Any], step_id: str | None) -> bytes:
    """Exact merged stdout/stderr bytes, in step/attempt order. No arbitrary path reader."""
    steps = state["steps"] if step_id is None else [s for s in state["steps"] if s["id"] == step_id]
    if not steps:
        raise ValueError("unknown step")
    parts = []
    for step in steps:
        for index, log in enumerate(step["logs"]):
            if log["ref"] != f"{step['id']}-{index}.log":
                raise ValueError("invalid log reference")
            path = safe_path(directory, log["ref"])
            if not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_nlink != 1:
                raise ValueError("missing or unsafe log source")
            data = path.read_bytes()
            if log["sha256"] is not None and (
                    digest(data) != log["sha256"] or len(data) != log["bytes"]):
                raise ValueError("corrupt log source")
            parts.append(data)
    if not parts:
        raise ValueError("step has no saved source")
    return b"".join(parts)


def read_source(directory: Path, state: dict[str, Any], args) -> None:
    data = sources(directory, state, args.step)
    # Offsets/limits count Unicode codepoints, not bytes: never split a UTF-8 character.
    text = data.decode("utf-8", "replace")
    if args.offset < 0 or args.offset > len(text) or not 1 <= args.limit <= 65536:
        raise ValueError("invalid source range")
    end = min(len(text), args.offset + args.limit)
    page = {"text": text[args.offset:end], "offset": args.offset, "next_offset": end,
            "eof": end == len(text), "unit": "unicode-codepoints"}
    if args.json:
        print(json.dumps(page, ensure_ascii=False, sort_keys=True))
    else:
        print(page["text"], end="")


def resume(root: Path, directory: Path, state: dict[str, Any], decision: dict[str, Any]):
    from .package_store import save
    if (not isinstance(decision, dict)
            or set(decision) != {"run_id", "revision", "operation"}
            or decision["run_id"] != state["run_id"]
            or type(decision["revision"]) is not int or decision["revision"] != state["revision"]
            or decision["operation"] not in ("retry-check", "continue", "stop")):
        raise ValueError("stale or invalid USER decision")
    if state["status"] in ("running", "pending", "unknown"):
        raise ValueError("unknown effects: inspect actual state and create a new package")
    if state["status"] != "waiting":
        raise ValueError("run is not waiting")
    if decision["operation"] == "stop":
        state.update(status="stopped", reason="USER stopped run")
        save(directory, state)
        return state
    # Fresh errors always outrank a simultaneous decision; no rewrite on refusal.
    if any(s["logs"] for s in state["steps"]):
        sources(directory, state, None)
    validate(root, state["record"], state["package"])
    if (snapshot(root, state["record"]) != state["snapshot"]
            or manifests(root, state["package"]) != state["boundary"]):
        raise ValueError("stale commands/config/significant inputs or outputs")
    index = next((i for i, s in enumerate(state["steps"]) if s["status"] != "succeeded"), None)
    if index is None:
        raise ValueError("all steps completed but final boundary failed; "
                         "inspect and create new package")
    saved = state["steps"][index]
    step = state["package"]["steps"][index]
    ctx, _, _ = policy(root, state["record"], step)
    kind = ctx.config.profile_config["local_packages"][step["action"]]["kind"]
    if saved["status"] == "failed":
        if decision["operation"] != "retry-check" or kind != "check":
            raise ValueError("failed mutation cannot be retried; only reviewed safe checks")
    elif saved["status"] != "pending" or decision["operation"] != "continue":
        raise ValueError("decision does not match next operation")
    saved["status"] = "pending"
    save(directory, state)
    return execute(root, directory, state)


def command(root: Path, args) -> int:
    """Saved-state readers deliberately precede all runtime/gate loading."""
    import sys
    from . import package_store as store
    from .errors import LoadError
    try:
        if args.operation in ("validate", "run"):
            package = json.loads(Path(args.target).read_bytes())
            validate(root, args.record, package)
            if args.operation == "validate":
                print(json.dumps({"valid": True, "package": package["id"]}))
                return 0
            directory, state = store.create(root, args.record, package,
                                            snapshot(root, args.record), manifests(root, package))
            with store.lock(directory):
                state = execute(root, directory, state)
        else:
            directory, state = store.load(root, args.record, args.target)
            if args.operation == "status":
                state = store.observed(directory, state)
            elif args.operation == "resume":
                with store.lock(directory, create=False):
                    directory, state = store.load(root, args.record, args.target)
                    state = resume(root, directory, state,
                                   json.loads(Path(args.decision).read_bytes()))
            elif args.operation == "read":
                read_source(directory, state, args)
                return 0
            else:
                raise ValueError("unknown operation")
        data = project(state)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, sort_keys=True))
        else:
            print(f"{data['run_id']} {data['status']} revision={data['revision']}")
            for step in data["steps"]:
                print(f"{step['id']}: {step['status']} logs=" +
                      ",".join(log["ref"] for log in step["logs"]))
                if step["status"] == "failed":
                    print("excerpt: " + step["excerpt"])
            print(f"reason: {data['reason']} remaining: {','.join(data['remaining'])}")
            print(data["read"])
        return 0 if state["status"] == "succeeded" or args.operation == "status" else 1
    except (OSError, ValueError, TypeError, KeyError, LoadError) as exc:
        print(f"package: {exc}", file=sys.stderr)
        return 2
