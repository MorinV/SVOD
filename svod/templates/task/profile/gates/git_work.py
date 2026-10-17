"""Task keys, task work directories next to the store and the merge of the task work.

A work directory is a checkout in the workspaces whose directory name and branch both name a key
of the task, for example ../service-PROJ-123_short-slug on the branch PROJ-123_short-slug. Own
commits name a key in the message. Nothing is fetched: remote branches are as of the last fetch.
"""
import re
from pathlib import Path

from svod import keys as core_keys
from svod.errors import ParamError
from svod.gates import FACT_REASON, Gate, KeyGate, Result, Status

PARAM_PATTERN = "pattern"
PARAM_MIN_AHEAD = "min_ahead"
PARAM_OR_MERGED = "or_merged"
DEFAULT_PATTERN = r"[A-Z][A-Z0-9]{1,9}-[0-9]+"
KEY_RE = r"(?<![A-Za-z0-9])({pattern})(?![0-9])"
MENTION_RE = r"(?<![A-Za-z0-9]){key}(?![0-9])"
DOT_GIT = ".git"
REMOTE = "origin"
REMOTE_HEAD = f"{REMOTE}/HEAD"
FALLBACK_BRANCH = f"{REMOTE}/main"
COMMON_DIR = ("rev-parse", "--git-common-dir")
SHOW_BRANCH = ("branch", "--show-current")
MESSAGE_FORMAT = "--format=%B%x00"
MESSAGE_END = "\0"
NO_COMMITS = "0"
ITEM_SEPARATOR = ", "
REASON_SEPARATOR = "; "

FACT_AHEAD = "ahead"
FACT_AHEAD_ALL = "ahead_all"
FACT_AHEAD_MAX = "ahead_max"
FACT_COUNT = "count"
FACT_WORKTREES = "worktrees"
FACT_PATHS = "paths"
FACT_OPEN = "open"
FACT_REPOS = "repos"
REASON_NO_REPOS = "no_repos"
REASON_OPEN = "open"
REASON_NO_COMMIT = "no_commit"

DESCRIBE_KEY = "gate.key"
DESCRIBE_WORKTREE = "gate.worktree"
DESCRIBE_WORKTREE_AHEAD = "gate.worktree_ahead"
DESCRIBE_OR_MERGED = "gate.worktree_or_merged"
DESCRIBE_MERGED = "gate.merged"
WORKTREE_DISPLAY = "worktree.display"
WORKTREE_NONE = "worktree.none"
WORKTREE_REMOVED = "worktree.removed"
WORKTREE_ITEM = "worktree.item"
WORKTREE_ITEM_FOREIGN = "worktree.item_foreign"
WORKTREE_ITEM_UNKNOWN = "worktree.item_unknown"
MERGED_DISPLAY = "merged.display"
MERGED_NONE = "merged.none"
MARK_KEYS = {Status.PASS: core_keys.MARK_PASS, Status.FAIL: core_keys.MARK_FAIL,
             Status.UNKNOWN: core_keys.MARK_UNKNOWN}


def mentions(text, key):
    """Whether the text names the key as a whole word in any letter case: PROJ-1 is not PROJ-10."""
    return re.search(MENTION_RE.format(key=re.escape(key)), text, re.IGNORECASE) is not None


def own_commits(messages, keys):
    """Messages naming any of the keys."""
    return [m for m in messages if any(mentions(m, key) for key in keys)]


def common_dir(ctx, path):
    """Resolved git common directory of a checkout, or None when git fails."""
    out = ctx.cache.git(path, *COMMON_DIR)
    return (Path(path) / out.out).resolve() if out.ok else None


def remote_default(ctx, path):
    """(remote default branch of the repository at path, None) or (None, reason).

    origin/HEAD when it is set, else the default branch of the store, else origin/main.
    """
    head = ctx.cache.git(path, "rev-parse", "--abbrev-ref", REMOTE_HEAD)
    if head.ok and head.out and head.out != REMOTE_HEAD:
        return head.out, None
    for ref in dict.fromkeys((ctx.config.default_branch, FALLBACK_BRANCH)):
        if ctx.cache.git(path, "rev-parse", "--verify", "--quiet", ref).ok:
            return ref, None
    return None, f"{Path(path).name}: no {REMOTE} default branch"


def commits_ahead(ctx, path, keys):
    """(own, all, None) commits ahead of the remote default branch, or (None, None, reason)."""
    ref, reason = remote_default(ctx, path)
    if reason:
        return None, None, reason
    out = ctx.cache.git(path, "log", MESSAGE_FORMAT, f"{ref}..HEAD")
    if not out.ok:
        return None, None, out.error
    messages = [m.strip() for m in out.out.split(MESSAGE_END)[:-1]]
    return len(own_commits(messages, keys)), len(messages), None


def mark(ctx, status, key, **facts):
    """Mark line of a gate with its own label, or None without a locale."""
    if ctx.locale is None:
        return None
    return ctx.locale.text(MARK_KEYS[status], label=ctx.locale.text(key, **facts))


class TaskKeyGate(KeyGate):
    """Task keys by a regular expression: a query names one in any letter case, a text as written.

    Keys are upper-cased. Param pattern overrides the default PROJ-123 form.
    """

    name = "key"
    PARAMS = frozenset({PARAM_PATTERN})

    def check(self):
        """pattern, when given, is a regular expression."""
        self.require_type(PARAM_PATTERN, str, "a string")
        pattern = KEY_RE.format(pattern=self.params.get(PARAM_PATTERN, DEFAULT_PATTERN))
        try:
            self.text_re = re.compile(pattern)
            self.query_re = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ParamError(f"{self.name}: {PARAM_PATTERN} is not a regular expression: {exc}")

    def match(self, query):
        """First key named by the query, or None."""
        found = self.query_re.search(query)
        return found.group(1).upper() if found else None

    def find(self, text):
        """Keys mentioned in the text."""
        return {m.group(1).upper() for m in self.text_re.finditer(text)}

    def describe(self, params, locale):
        """The subject carries a task key."""
        return locale.text(DESCRIBE_KEY)


class WorktreeGate(Gate):
    """Checkouts in the workspaces whose directory name and branch both name a subject key."""

    name = "worktree"
    PARAMS = frozenset({PARAM_MIN_AHEAD, PARAM_OR_MERGED})

    def check(self):
        """min_ahead, when given, is a positive integer; or_merged is a boolean."""
        value = self.params.get(PARAM_MIN_AHEAD)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or value < 1):
            raise ParamError(f"{self.name}: {PARAM_MIN_AHEAD} must be a positive integer")
        self.require_type(PARAM_OR_MERGED, bool, "a boolean")

    def describe(self, params, locale):
        """A work directory, with at least min_ahead own commits when given; or merged work."""
        if PARAM_MIN_AHEAD in params:
            text = locale.text(DESCRIBE_WORKTREE_AHEAD, min_ahead=params[PARAM_MIN_AHEAD])
        else:
            text = locale.text(DESCRIBE_WORKTREE)
        if params.get(PARAM_OR_MERGED):
            return locale.text(DESCRIBE_OR_MERGED, text=text)
        return text

    @staticmethod
    def candidates(ctx, keys):
        """(checkout, repository name) in the workspaces whose directory name names a key.

        The store and its own worktrees are left out.
        """
        base = ctx.config.workspaces
        if not keys or base is None or not base.is_dir():
            return []
        named = [p for p in sorted(base.iterdir())
                 if any(mentions(p.name, key) for key in keys)
                 and (p / DOT_GIT).exists() and p.resolve() != ctx.root]
        if not named:
            return []
        ctx.cache.prefetch([(ctx.root, COMMON_DIR)]
                           + [(p, args) for p in named for args in (COMMON_DIR, SHOW_BRANCH)])
        store = common_dir(ctx, ctx.root)
        found = []
        for path in named:
            common = common_dir(ctx, path)
            if store is not None and common == store:
                continue
            found.append((path, common.parent.name if common is not None else path.name))
        return found

    def worktrees(self, ctx, keys):
        """((checkout, repository name) whose branch also names a key, git errors) of the keys."""
        found, errors = [], []
        for path, repository in self.candidates(ctx, keys):
            branch = ctx.cache.git(path, *SHOW_BRANCH)
            if not branch.ok:
                errors.append(branch.error)
            elif any(mentions(branch.out, key) for key in keys):
                found.append((path, repository))
        return found, errors

    def evaluate(self, ctx, subject):
        """PASS with a work directory (with min_ahead own commits in one, when given).

        facts: ahead (own commits per directory, None when git failed), ahead_all, ahead_max,
        count, worktrees (one line) and paths (repository name to directory).
        """
        worktrees, reasons = self.worktrees(ctx, subject.keys)
        ahead, total, paths = {}, {}, {}
        for path, repository in worktrees:
            own, every, reason = commits_ahead(ctx, path, subject.keys)
            if reason:
                reasons.append(reason)
            ahead[path.name], total[path.name] = own, every
            paths.setdefault(repository, str(path))
        known = [n for n in ahead.values() if n is not None]
        facts = {FACT_AHEAD: ahead, FACT_AHEAD_ALL: total,
                 FACT_AHEAD_MAX: max(known) if known else None, FACT_COUNT: len(ahead),
                 FACT_WORKTREES: self.items(ctx, ahead, total), FACT_PATHS: paths}
        status = self.status(ahead, known, reasons)
        if status is not Status.PASS and self.params.get(PARAM_OR_MERGED):
            if MergedGate().evaluate(ctx, subject).passed:
                return Result(Status.PASS, facts, self.display(ctx, Status.PASS, facts, True))
        return Result(status, facts, self.display(ctx, status, facts),
                      REASON_SEPARATOR.join(dict.fromkeys(reasons)) or None)

    def status(self, ahead, known, reasons):
        """PASS with a directory, or with min_ahead own commits in one; UNKNOWN when git failed."""
        minimum = self.params.get(PARAM_MIN_AHEAD)
        if ahead and (minimum is None or any(n >= minimum for n in known)):
            return Status.PASS
        return Status.UNKNOWN if reasons else Status.FAIL

    @staticmethod
    def items(ctx, ahead, total):
        """Directories with their own commits ahead, all commits too when they differ."""
        if ctx.locale is None:
            return ITEM_SEPARATOR.join(ahead)
        lines = []
        for name, own in ahead.items():
            if own is None:
                key = WORKTREE_ITEM_UNKNOWN
            else:
                key = WORKTREE_ITEM if own == total[name] else WORKTREE_ITEM_FOREIGN
            lines.append(ctx.locale.text(key, name=name, ahead=own, ahead_all=total[name]))
        return ITEM_SEPARATOR.join(lines)

    @staticmethod
    def display(ctx, status, facts, merged=False):
        """Mark: the directories, their removal after the merge, or their absence."""
        if facts[FACT_COUNT]:
            return mark(ctx, status, WORKTREE_DISPLAY, **facts)
        return mark(ctx, status, WORKTREE_REMOVED if merged else WORKTREE_NONE)


class MergedGate(Gate):
    """The task work is merged: every work directory is in its remote default branch or removed,
    and a known repository has a commit naming the task in that branch.

    Known repositories are those of the work directories; without any, every repository in the
    workspaces except the store that has a remote default branch: one without it cannot hold the
    merged task, so it is left out silently rather than reported as unchecked.
    """

    name = "merged"

    def evaluate(self, ctx, subject):
        """facts: open (directories not merged), count, repos (with a task commit), reason."""
        worktrees, reasons = WorktreeGate().worktrees(ctx, subject.keys)
        known, opened = {}, []
        for path, repository in worktrees:
            known.setdefault(repository, path)
            ref, reason = remote_default(ctx, path)
            count = ctx.cache.git(path, "rev-list", "--count", f"{ref}..HEAD") if ref else None
            if reason or not count.ok:
                reasons.append(reason or count.error)
            elif count.out != NO_COMMITS:
                opened.append(path.name)
        if not worktrees:
            known = {p.name: p for p in self.repositories(ctx)}
        merged = [name for name, path in sorted(known.items())
                  if self.has_task_commit(ctx, path, subject.keys, reasons)]
        facts = {FACT_OPEN: ITEM_SEPARATOR.join(opened), FACT_COUNT: len(opened),
                 FACT_REPOS: ITEM_SEPARATOR.join(merged)}
        reason = self.failure(known, opened, merged, reasons)
        if reason:
            status, facts = Status.FAIL, {**facts, FACT_REASON: reason}
        else:
            status = Status.UNKNOWN if reasons else Status.PASS
        display = None
        if ctx.locale is not None:
            none = ctx.locale.text(MERGED_NONE)
            shown = {**facts, FACT_REPOS: facts[FACT_REPOS] or none,
                     FACT_OPEN: facts[FACT_OPEN] or none}
            display = mark(ctx, status, MERGED_DISPLAY, **shown)
        return Result(status, facts, display,
                      REASON_SEPARATOR.join(dict.fromkeys(reasons)) if status is Status.UNKNOWN else None)

    @staticmethod
    def repositories(ctx):
        """Main checkouts in the workspaces with a remote default branch, never the store."""
        base = ctx.config.workspaces
        if base is None or not base.is_dir():
            return []
        store = common_dir(ctx, ctx.root)
        checkouts = [p for p in sorted(base.iterdir())
                     if (p / DOT_GIT).is_dir() and p.resolve() != ctx.root
                     and (store is None or (p / DOT_GIT).resolve() != store)]
        return [p for p in checkouts if remote_default(ctx, p)[0] is not None]

    @staticmethod
    def failure(known, opened, merged, reasons):
        """Reason of a FAIL, or None: nothing known, a directory not merged, no task commit."""
        if not known and not reasons:
            return REASON_NO_REPOS
        if opened:
            return REASON_OPEN
        if not merged and not reasons:
            return REASON_NO_COMMIT
        return None

    @staticmethod
    def has_task_commit(ctx, path, keys, reasons):
        """Whether the remote default branch of the repository has a commit naming a key."""
        ref, reason = remote_default(ctx, path)
        if reason:
            reasons.append(reason)
            return False
        greps = [f"--grep={key}" for key in sorted(keys)]
        out = ctx.cache.git(path, "log", ref, "--fixed-strings", "--regexp-ignore-case",
                            MESSAGE_FORMAT, *greps)
        if not out.ok:
            reasons.append(out.error)
            return False
        return bool(own_commits(out.out.split(MESSAGE_END), keys))

    def describe(self, params, locale):
        """The work directories are merged or removed, and the remote has a task commit."""
        return locale.text(DESCRIBE_MERGED)


GATES = {cls.name: cls for cls in (TaskKeyGate, WorktreeGate, MergedGate)}
