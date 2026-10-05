"""A store made from examples/task with a service repository and a task work directory."""
import datetime as dt
import shutil

from support import CONFIG_FILE, ENCODING, REMOTE, REPO_DIR, TempStore

from svod.approval import write_mark

EXAMPLE = REPO_DIR / "examples" / "task"
KEY = "PROJ-1"
OTHER_KEY = "PROJ-2"
CHANGE_NAME = "add-greeting"
CHANGE = f"openspec/changes/{CHANGE_NAME}"
ARCHIVED = f"openspec/changes/archive/{CHANGE_NAME}"
META = f"{CHANGE}/.openspec.yaml"
META_TEXT = f"schema: spec-driven\nticket: {KEY}\n"
PLAN = {
    "proposal.md": "# Proposal\n\nSay hello.\n",
    "design.md": "# Design\n\nPrint a line.\n",
    "specs/greeting/spec.md": "# Greeting\n\nThe service says hello.\n",
    "tasks.md": f"## {KEY}\n\n- [ ] print hello\n",
}
SERVICE = "service"
WORKTREE = f"{SERVICE}-{KEY}_greeting"
BRANCH = f"{KEY}_greeting"
CODE_FILE = "main.go"
CODE_TEXT = "package main\n"
MAIN_BRANCH_REF = "HEAD:main"


def make_task_store():
    """TempStore whose store is a copy of the example, in git with a pushed remote."""
    sb = TempStore()
    shutil.copytree(EXAMPLE, sb.store, dirs_exist_ok=True)
    sb.init_git()
    return sb


def set_config(sb, **values):
    """Replace or add top-level keys of the svod.yaml of the store."""
    path = sb.store / CONFIG_FILE
    lines = [line for line in path.read_text(encoding=ENCODING).splitlines()
             if line.split(":", 1)[0] not in values]
    lines += [f"{key}: {value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding=ENCODING)


def propose(sb):
    """Create the change with the task key."""
    sb.write(META, META_TEXT)


def specify(sb):
    """Write the plan of the change."""
    for name, text in PLAN.items():
        sb.write(f"{CHANGE}/{name}", text)


def approve(sb):
    """Leave a fresh mark and record the approval as the CLI does."""
    write_mark(sb.store, [KEY], dt.datetime.now().astimezone())
    out = sb.cli("approve", KEY)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)


def service(sb):
    """Main checkout of the service repository next to the store."""
    path = sb.parent / SERVICE
    if not path.exists():
        sb.init_git(path)
    return path


def make_worktree(sb):
    """Task work directory of the service on a branch naming the key."""
    sb.git(service(sb), "worktree", "add", "-q", "-b", BRANCH, str(sb.parent / WORKTREE))
    return sb.parent / WORKTREE


def implement(sb):
    """One own commit in the work directory."""
    worktree = sb.parent / WORKTREE
    sb.write(CODE_FILE, CODE_TEXT, base=worktree)
    sb.commit(worktree, f"{KEY}: print hello")


def merge(sb):
    """Push the task branch into the default branch of the remote."""
    sb.git(sb.parent / WORKTREE, "push", "-q", REMOTE, MAIN_BRANCH_REF)


def archive(sb):
    """Move the change into the archive."""
    target = sb.store / ARCHIVED
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(sb.store / CHANGE), str(target))
