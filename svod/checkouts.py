"""Other checkouts of the store repository and contexts rooted in them."""
from dataclasses import dataclass, replace

from .context import Context
from .git import changed_calls, changed_paths, worktree_list


@dataclass(frozen=True)
class Scope:
    """Another checkout of the store: directory name, a context rooted there, paths it changed."""

    name: str
    ctx: Context
    paths: frozenset


def rooted(ctx, root):
    """Context of the store moved to another root; configuration, locale, pipelines and the
    memory of the run stay."""
    return Context(replace(ctx.config, root=root), ctx.locale, today=ctx.today,
                   bindings=ctx.bindings, pipelines=ctx.pipelines, cache=ctx.cache)


def worktree_scopes(ctx):
    """Scopes of the other checkouts of the store repository that differ from the default branch.

    A checkout differs by commits since the merge base, uncommitted changes or untracked files.
    """
    found, _ = worktree_list(ctx.root, ctx.cache.git)
    others = [w for w in found if w.path != ctx.root]
    base = ctx.config.default_branch
    ctx.cache.prefetch((w.path, args) for w in others for args in changed_calls(base))
    scopes = []
    for worktree in others:
        paths, _ = changed_paths(worktree.path, base, ctx.cache.git)
        if paths:
            scopes.append(Scope(worktree.path.name, rooted(ctx, worktree.path), frozenset(paths)))
    return scopes


def subject_context(ctx, subject):
    """Context the subject was read in: its checkout when it came from another one."""
    return rooted(ctx, subject.checkout) if subject.checkout is not None else ctx
