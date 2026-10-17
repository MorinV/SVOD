"""Compact local plans and observed command evidence; no service adapters."""
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from .errors import LoadError, LocalWorkflowError
from .yamlio import ENCODING, parse_yaml

PLAN = "testing/plan.yaml"
RECEIPT = "testing/process/receipt.json"
LOG = "testing/process/command.log"


def unique_json_object(pairs):
    """JSON object of the pairs; LocalWorkflowError when a field repeats."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise LocalWorkflowError("duplicate JSON field")
        value[key] = item
    return value


def strict_yaml(path):
    """YAML mapping of the file read by the shared loader; LocalWorkflowError when malformed.

    OSError of reading passes through as it is; a load error becomes a LocalWorkflowError (a
    ValueError), which the local workflow reports as a refused input.
    """
    try:
        value = parse_yaml(Path(path).read_text(encoding=ENCODING), path)
    except LoadError as exc:
        raise LocalWorkflowError(str(exc)) from None
    if not isinstance(value, dict):
        raise LocalWorkflowError("expected YAML mapping")
    return value


def confined(root, relative):
    """Path of a plain relative path under root; refused when it escapes or crosses a symlink."""
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise LocalWorkflowError("invalid local path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or relative != pure.as_posix():
        raise LocalWorkflowError("path escapes task")
    path = root
    for part in pure.parts:
        path /= part
        if path.is_symlink():
            raise LocalWorkflowError("symlink local path")
    return path


def load_policy(subject, *, recorded=False):
    """Validated compact process plan of the subject; recorded skips the live workspace checks."""
    data = strict_yaml(confined(subject.path, PLAN))
    if (set(data) != {"version", "kind", "contract", "workspace", "command"}
            or type(data["version"]) is not int or data["version"] != 1
            or data["kind"] != "process"):
        raise LocalWorkflowError("expected exact compact process plan fields")
    contract = confined(subject.path, data["contract"])
    if not contract.is_file() or not contract.read_text(encoding="utf-8").strip():
        raise LocalWorkflowError("missing compact contract")
    workspace = data["workspace"]
    if (not isinstance(workspace, str) or not Path(workspace).is_absolute()
            or str(Path(workspace)) != workspace or ".." in Path(workspace).parts
            or (not recorded and (str(Path(workspace).resolve()) != workspace
                                  or not Path(workspace).is_dir()))):
        raise LocalWorkflowError("workspace must be an explicit absolute Git directory")
    command = data["command"]
    if command is not None and (not isinstance(command, list) or not command
            or any(not isinstance(arg, str) or "\0" in arg for arg in command)
            or not command[0]):
        raise LocalWorkflowError("command must be argv or null")
    return data


def git_ref(workspace):
    """Return HEAD only for an ordinary clean Git root (including untracked files)."""
    def git(*args):
        """Stripped stdout of a git command in the workspace; raises when it fails."""
        result = subprocess.run(["git", "-C", workspace, *args], capture_output=True,
                                text=True, check=True, timeout=20)
        return result.stdout.strip()
    if git("rev-parse", "--show-toplevel") != workspace:
        raise LocalWorkflowError("workspace must be the Git root")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise LocalWorkflowError("source workspace is dirty")
    return git("rev-parse", "HEAD")


def sha(raw):
    """Hex sha256 of the bytes."""
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    """Hex sha256 of the value as canonical JSON."""
    return sha(json.dumps(value, sort_keys=True).encode())


def plan_patterns(ctx, subject, *, recorded=False):
    """Globs the contract approval binds, else the plan and its contract."""
    from .workflow_policy import contract_approval
    ref = contract_approval(ctx, subject)
    if ref is not None:
        return list(ref.params["bind"])
    policy = load_policy(subject, recorded=recorded)
    return [PLAN, policy["contract"]]


def validate(ctx, subject, *, recorded=False):
    """Receipt checked against log, observations, current bindings and optionally live source."""
    from .workflow_policy import contract_approval
    from .approval import digest
    policy = load_policy(subject, recorded=recorded)
    ref = contract_approval(ctx, subject)
    if ref is not None and not ref.impl.evaluate(ctx, subject).passed:
        raise LocalWorkflowError("missing current human approval")
    data = json.loads(confined(subject.path, RECEIPT).read_bytes(),
                      object_pairs_hook=unique_json_object)
    fields = {"command", "cwd", "git_ref", "git_ref_after", "exit_code", "log", "log_sha",
              "contract_sha", "approval_sha", "source_error"}
    if not isinstance(data, dict) or set(data) != fields:
        raise LocalWorkflowError("invalid command result")
    if (not isinstance(data["git_ref"], str)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", data["git_ref"])
            or data["git_ref_after"] != data["git_ref"] or data["source_error"] is not None):
        raise LocalWorkflowError("source changed during command")
    if data["log"] != LOG:
        raise LocalWorkflowError("invalid command log location")
    log = confined(subject.path, LOG).read_bytes()
    if (data["command"] != policy["command"] or data["cwd"] != policy["workspace"]
            or (not recorded and data["git_ref"] != git_ref(policy["workspace"]))
            or data["contract_sha"] != digest(subject.path,
                                              plan_patterns(ctx, subject, recorded=recorded))
            or data["approval_sha"] != (sha(confined(subject.path, ref.params["file"]).read_bytes())
                                        if ref is not None else None)
            or data["log_sha"] != sha(log)):
        raise LocalWorkflowError("command result is stale")
    if policy["command"] is None:
        if data["exit_code"] is not None or log != b"No command selected.\n":
            raise LocalWorkflowError("invalid skipped command")
    elif type(data["exit_code"]) is not int or data["exit_code"] != 0:
        raise LocalWorkflowError("command did not succeed")
    return data
