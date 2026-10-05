"""Active summary: open subjects by owner and progress, and by other checkouts of the store."""
import json

from . import keys
from .checkouts import worktree_scopes
from .identity import my_email
from .pipeline import (GROUP_MINE_ACTIVE, GROUP_MINE_IDLE, GROUP_THEIRS, GROUP_THEIRS_COLLAPSED,
                       GROUP_WORKTREE)
from .position import FACT_STEP, evaluate, position
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
    return INDENT + locale.text(pipeline.active.item or keys.ACTIVE_ITEM, **facts)


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


def pipeline_blocks(ctx, pipeline, me, show_all, scopes=()):
    """Blocks of one pipeline: subjects changed in other checkouts, by checkout, then the groups."""
    locale = ctx.locale
    groups = {group: [] for group in GROUP_ORDER}
    authors = []
    blocks, seen = worktree_blocks(pipeline, scopes)
    for subject in pipeline.subject.impl.enumerate(ctx):
        if subject.archived or subject.id in seen:
            continue
        pos = position(ctx, pipeline, subject)
        if pos.done:
            continue
        line = item_line(locale, pipeline, pos)
        email, name = subject.author or ("", "")
        if me and email and email != me:
            groups[GROUP_THEIRS].append(line)
            authors.append(name or email)
        elif in_progress(ctx, pipeline, subject):
            groups[GROUP_MINE_ACTIVE].append(line)
        else:
            groups[GROUP_MINE_IDLE].append(line)
    for group in GROUP_ORDER:
        lines = groups[group]
        if not lines:
            continue
        if group == GROUP_THEIRS and not show_all:
            blocks.append([collapsed(locale, pipeline, authors)])
        else:
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
    for pipeline in shown:
        for block in pipeline_blocks(ctx, pipeline, me, show_all, scopes):
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
