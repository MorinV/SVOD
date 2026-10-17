"""Active summary: open subjects by owner and progress, and by other checkouts of the store."""
import json

from . import keys
from .checkouts import worktree_scopes
from .gates import DEFAULT_RELATION_FIELD, pipeline_subjects, relation_field
from .identity import my_email
from .pipeline import (GROUP_MINE_ACTIVE, GROUP_MINE_IDLE, GROUP_THEIRS, GROUP_THEIRS_COLLAPSED,
                       GROUP_WORKTREE)
from .position import FACT_STEP, evaluate, position
from .relations import active_children, flatten, subject_by_id, tree
from .render import FACT_KEYS, INDENT, KEYS_SEPARATOR, step_text, subject_facts
from .subject import ATTR_FRONTMATTER

GROUP_ORDER = (GROUP_MINE_ACTIVE, GROUP_MINE_IDLE, GROUP_THEIRS)
DEFAULT_HEADINGS = {
    GROUP_MINE_ACTIVE: keys.ACTIVE_MINE_ACTIVE,
    GROUP_MINE_IDLE: keys.ACTIVE_MINE_IDLE,
    GROUP_THEIRS: keys.ACTIVE_THEIRS,
    GROUP_THEIRS_COLLAPSED: keys.ACTIVE_THEIRS_COLLAPSED,
    GROUP_WORKTREE: keys.ACTIVE_WORKTREE,
}
FACT_FRONTMATTER = "frontmatter"
HOOK_EVENT = "SessionStart"
HOOK_OUTPUT = "hookSpecificOutput"
HOOK_EVENT_NAME = "hookEventName"
HOOK_CONTEXT = "additionalContext"


def ordered(pipelines, order):
    """Pipelines listed in order first, the rest by name."""
    rank = {name: i for i, name in enumerate(order)}
    return sorted(pipelines, key=lambda p: (rank.get(p.name, len(rank)), p.name))


def heading(pipeline, group):
    """Locale key of a group heading, overridden by the pipeline when declared."""
    return pipeline.active.headings.get(group, DEFAULT_HEADINGS[group])


def in_progress(ctx, pipeline, subject):
    """Whether the in-progress gate passed and its fact, when named, is positive."""
    spec = pipeline.active
    if spec.in_progress is None:
        return False
    outcome = evaluate(ctx, spec.in_progress, subject)
    if not outcome.passed:
        return False
    if spec.fact is None:
        return True
    value = outcome.result.facts.get(spec.fact)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def item_line(locale, pipeline, pos):
    """Summary line of one subject with its next step."""
    facts = subject_facts(pos)
    if not facts[FACT_KEYS]:
        facts[FACT_KEYS] = locale.text(keys.ACTIVE_NO_KEYS)
    facts[FACT_STEP] = step_text(locale, pos) or ""
    facts[FACT_FRONTMATTER] = pos.subject.attrs.get(ATTR_FRONTMATTER) or {}
    item = pipeline.active.item if pipeline.active is not None else None
    return INDENT + locale.text(item or keys.ACTIVE_ITEM, **facts)


def collapsed(locale, pipeline, authors):
    """One line counting the team's subjects per author."""
    counts = {}
    for author in authors:
        counts[author] = counts.get(author, 0) + 1
    who = KEYS_SEPARATOR.join(locale.text(keys.ACTIVE_AUTHOR_COUNT, author=a, count=n)
                              for a, n in sorted(counts.items()))
    return locale.text(heading(pipeline, GROUP_THEIRS_COLLAPSED), count=len(authors), who=who)


def worktree_blocks(pipeline, scopes):
    """(a block per checkout with the open subjects it changed, ids of every subject changed)."""
    blocks, seen = [], set()
    for scope in scopes:
        lines = []
        for subject in pipeline.subject.impl.touched(scope.ctx, scope.paths):
            seen.add(subject.id)
            if subject.archived:
                continue
            pos = position(scope.ctx, pipeline, subject)
            if not pos.done:
                lines.append(item_line(scope.ctx.locale, pipeline, pos))
        if lines:
            title = scope.ctx.locale.text(heading(pipeline, GROUP_WORKTREE), dir=scope.name)
            blocks.append([title] + lines)
    return blocks, seen


class Forest:
    """Open subjects of the summary and the children shown under their parents.

    A subject is shown under its parent when the parent's pipeline names the subject's pipeline
    in `active.children`, the parent is open and its line is shown; such a subject is left out of
    its own group. A subject on a cycle of parents is shown in its own group.
    """

    def __init__(self, ctx, pipelines, show_all, seen):
        """Summary over the pipelines; seen: (pipeline, id) of subjects shown by checkout."""
        self.ctx = ctx
        self.pipelines = list(pipelines)
        self.show_all = show_all
        self.seen = seen
        self.positions = {}
        self.entries = {}
        self.hosts = {}
        self.printed_memo = {}

    def position(self, pipeline, subject):
        """Position of the subject, computed once."""
        key = (pipeline.name, subject.id)
        if key not in self.positions:
            self.positions[key] = position(self.ctx, pipeline, subject)
        return self.positions[key]

    def is_open(self, pipeline, subject):
        """Whether the subject is neither archived, done nor shown under a checkout."""
        if subject.archived or (pipeline.name, subject.id) in self.seen:
            return False
        return not self.position(pipeline, subject).done

    def add(self, pipeline, subject, collapsed):
        """Record an open subject of a group of the root; collapsed when its line is hidden."""
        self.entries[(pipeline.name, subject.id)] = collapsed

    def parent(self, pipeline, subject):
        """(pipeline, subject) of the open parent whose pipeline shows this one, or None."""
        ref = relation_field(subject, DEFAULT_RELATION_FIELD)
        if not ref:
            return None
        for host in self.pipelines:
            if pipeline.name not in active_children(host):
                continue
            found = subject_by_id(self.ctx, host, ref)
            if found is not None and self.is_open(host, found):
                return host, found
        return None

    def on_cycle(self, pipeline, subject):
        """Whether the parents lead from the subject back to it."""
        start = (pipeline.name, subject.id)
        met = {start}
        step = self.parent(pipeline, subject)
        while step is not None:
            key = (step[0].name, step[1].id)
            if key == start:
                return True
            if key in met:
                return False
            met.add(key)
            step = self.parent(*step)
        return False

    def host(self, pipeline, subject):
        """The parent the subject is shown under when that parent is shown, or None."""
        key = (pipeline.name, subject.id)
        if key not in self.hosts:
            found = self.parent(pipeline, subject)
            if found is not None and self.on_cycle(pipeline, subject):
                found = None
            self.hosts[key] = found
        return self.hosts[key]

    def printed(self, pipeline, subject):
        """Whether the line of the subject is shown: under a shown parent or in its group."""
        key = (pipeline.name, subject.id)
        if key not in self.printed_memo:
            self.printed_memo[key] = (self.nested(pipeline, subject)
                                      or self.entries.get(key) is False)
        return self.printed_memo[key]

    def nested(self, pipeline, subject):
        """Whether the subject is shown under its parent instead of its own group."""
        found = self.host(pipeline, subject)
        return found is not None and self.printed(*found)

    def keep(self, pipeline, subject):
        """Whether a child goes under its parent: open and not on a cycle of parents."""
        return self.is_open(pipeline, subject) and not self.on_cycle(pipeline, subject)

    def lines(self, pipeline, subject, placed):
        """Lines of the open children under a shown subject, indented by depth."""
        nodes = tree(self.ctx, self.pipelines, pipeline, subject, self.keep, placed)
        locale = self.ctx.locale
        return [INDENT * (depth + 1)
                + item_line(locale, node.pipeline, self.position(node.pipeline, node.subject))
                for depth, node in flatten(nodes)]


def pipeline_entries(ctx, forest, pipeline, me, scopes=()):
    """(blocks of other checkouts, [(subject, position, foreign author)] of open subjects)."""
    blocks, seen = worktree_blocks(pipeline, scopes)
    forest.seen |= {(pipeline.name, subject_id) for subject_id in seen}
    entries = []
    for subject in pipeline_subjects(ctx, pipeline):
        if not forest.is_open(pipeline, subject):
            continue
        email, name = subject.author or ("", "")
        foreign = (name or email) if me and email and email != me else None
        forest.add(pipeline, subject, foreign is not None and not forest.show_all)
        entries.append((subject, forest.position(pipeline, subject), foreign))
    return blocks, entries


def pipeline_blocks(ctx, forest, pipeline, found, placed):
    """Blocks of one pipeline: subjects changed in other checkouts, by checkout, then the groups.

    found: what pipeline_entries returned; placed: (pipeline, id) of the lines shown so far.
    """
    locale = ctx.locale
    blocks, entries = found
    groups = {group: [] for group in GROUP_ORDER}
    authors = []
    for subject, pos, foreign in entries:
        if forest.nested(pipeline, subject) or (pipeline.name, subject.id) in placed:
            continue
        if foreign is not None:
            group = GROUP_THEIRS
            authors.append(foreign)
        elif in_progress(ctx, pipeline, subject):
            group = GROUP_MINE_ACTIVE
        else:
            group = GROUP_MINE_IDLE
        if group == GROUP_THEIRS and not forest.show_all:
            continue
        placed.add((pipeline.name, subject.id))
        groups[group].append(item_line(locale, pipeline, pos))
        groups[group] += forest.lines(pipeline, subject, placed)
    for group in GROUP_ORDER:
        lines = groups[group]
        if group == GROUP_THEIRS and authors and not forest.show_all:
            blocks.append([collapsed(locale, pipeline, authors)])
        elif lines:
            blocks.append([locale.text(heading(pipeline, group))] + lines)
    return blocks


def local_config_notice(ctx):
    """Line asking to create the configured local config when it is missing, else None."""
    config = ctx.config
    if config.local_path is None or config.local_found:
        return None
    return ctx.locale.text(keys.ACTIVE_NO_LOCAL_CONFIG,
                           file=config.local_path.relative_to(config.root).as_posix())


def summarize(ctx, pipelines, show_all=False):
    """Summary lines over every pipeline with an active block; empty when nothing is open.

    A missing local config is the first line; unknown identity is a warning before the work.
    """
    me = my_email(ctx)
    lines = []
    shown = ordered([p for p in pipelines if p.active], ctx.config.active_order)
    scopes = worktree_scopes(ctx) if shown else []
    forest = Forest(ctx, pipelines, show_all, set())
    found = [pipeline_entries(ctx, forest, pipeline, me, scopes) for pipeline in shown]
    placed = set()
    for pipeline, entries in zip(shown, found, strict=True):
        for block in pipeline_blocks(ctx, forest, pipeline, entries, placed):
            lines += ([""] if lines else []) + block
    head = [line for line in (local_config_notice(ctx),) if line]
    if lines and not me:
        head.append(ctx.locale.text(keys.ACTIVE_NO_IDENTITY))
    return head + ([""] if head and lines else []) + lines


def hook_payload(locale, lines):
    """SessionStart hook JSON carrying the summary and the status hint."""
    text = "\n".join(lines + ["", locale.text(keys.ACTIVE_HOOK_TAIL)])
    return json.dumps({HOOK_OUTPUT: {HOOK_EVENT_NAME: HOOK_EVENT, HOOK_CONTEXT: text}},
                      ensure_ascii=False)
