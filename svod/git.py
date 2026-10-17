"""Git invocation with a timeout and explicit failure."""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .yamlio import ENCODING

GIT = "git"
GIT_TIMEOUT_SEC = 5
QUOTE_PATH_OFF = ("-c", "core.quotepath=false")
PORCELAIN_WORKTREE = "worktree "
PORCELAIN_BRANCH = "branch "
PORCELAIN_BARE = "bare"
BRANCH_PREFIX = "refs/heads/"
NUL = "\0"
COMMON_DIR = ("rev-parse", "--git-common-dir")


@dataclass(frozen=True)
class GitResult:
    """Outcome of one git call: stripped stdout on success, a reason otherwise."""

    ok: bool
    out: str = ""
    error: str = ""


def run_git(cwd, *args, timeout=GIT_TIMEOUT_SEC, env=None):
    """Run git in cwd; never raises, failures carry the first line of stderr as the reason.

    env, when given, is added to the environment of the process.
    """
    full_env = {**os.environ, **env} if env else None
    try:
        proc = subprocess.run([GIT, "-C", str(cwd), *args], capture_output=True, text=True,
                              encoding=ENCODING, timeout=timeout, env=full_env)
    except subprocess.TimeoutExpired:
        return GitResult(ok=False, error=f"git {' '.join(args)}: timeout {timeout}s")
    except OSError as exc:
        return GitResult(ok=False, error=f"git {' '.join(args)}: {exc}")
    if proc.returncode != 0:
        first = next(iter(proc.stderr.strip().splitlines()), "")
        return GitResult(ok=False, error=f"git {' '.join(args)}: {first}")
    return GitResult(ok=True, out=proc.stdout.strip())


def common_dir_file(root, name, run=None):
    """File of the given name in the git common directory of root, shared by its worktrees.

    None when root is not in a git repository. run replaces run_git.
    """
    out = (run or run_git)(root, *COMMON_DIR)
    if not out.ok:
        return None
    return (Path(root) / out.out).resolve() / name


@dataclass(frozen=True)
class Worktree:
    """One checkout of a repository: its directory and the branch checked out, if any."""

    path: Path
    branch: str | None = None


def worktree_list(cwd, run=None):
    """(checkouts of the repository holding cwd, the main one first; error or None).

    Bare entries and directories that no longer exist are left out. run replaces run_git.
    """
    out = (run or run_git)(cwd, "worktree", "list", "--porcelain")
    if not out.ok:
        return [], out.error
    found, path, branch, bare = [], None, None, False
    for line in out.out.splitlines() + [""]:
        if line.startswith(PORCELAIN_WORKTREE):
            path, branch, bare = Path(line[len(PORCELAIN_WORKTREE):]), None, False
        elif line.startswith(PORCELAIN_BRANCH):
            branch = line[len(PORCELAIN_BRANCH):].removeprefix(BRANCH_PREFIX)
        elif line == PORCELAIN_BARE:
            bare = True
        elif not line and path is not None:
            if not bare and path.is_dir():
                found.append(Worktree(path.resolve(), branch))
            path = None
    return found, None


def changed_calls(base):
    """Git arguments of the calls listing what a checkout changed against base."""
    calls = (("diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"),
             ("diff", "--name-only", "--no-renames", "-z", "HEAD"),
             ("ls-files", "--others", "--exclude-standard", "-z"))
    return [(*QUOTE_PATH_OFF, *args) for args in calls]


def changed_paths(cwd, base, run=None):
    """(paths relative to the checkout that differ from base, errors).

    A path differs when it was committed since the merge base with base, changed and not
    committed, or is untracked and not ignored. Paths git could not list are missing, with
    the reason among the errors. run replaces run_git.
    """
    paths, errors = set(), []
    for args in changed_calls(base):
        out = (run or run_git)(cwd, *args)
        if out.ok:
            paths.update(p for p in out.out.split(NUL) if p)
        else:
            errors.append(out.error)
    return paths, errors
