"""Resolving a query to subjects across pipelines and the other checkouts of the store."""
from dataclasses import dataclass, field, replace

from .checkouts import worktree_scopes
from .providers.base import covers


@dataclass
class Resolution:
    """Matched (pipeline, subject) pairs; ambiguous when a name matched several."""

    matches: list = field(default_factory=list)
    ambiguous: bool = False


def exact_pairs(ctx, pipelines, query):
    """Pairs of subjects named exactly as the query."""
    return [(p, s) for p in pipelines for s in p.subject.impl.match_exact(query, ctx)]


def key_pairs(ctx, pipelines, query):
    """Pairs of every subject addressed by the key recognised in the query."""
    found = []
    for pipeline in pipelines:
        key_gate = pipeline.subject.key_impl
        key = key_gate.match(query) if key_gate else None
        if key:
            found.extend((pipeline, s) for s in pipeline.subject.impl.match_key(key, ctx))
        else:
            found.extend((pipeline, s) for s in pipeline.subject.impl.enumerate(ctx)
                         if query.casefold() in {value.casefold() for value in s.keys})
    return found


def substring_pairs(ctx, pipelines, query):
    """Pairs of subjects whose name contains the query."""
    return [(p, s) for p in pipelines for s in p.subject.impl.match_substring(query, ctx)]


def changed_in(ctx, pipeline, subject, paths):
    """Whether a checkout changed a path grounding the subject."""
    return any(covers(rel, paths) for rel in pipeline.subject.impl.evidence(ctx, subject))


def across(ctx, pipelines, query, phase, scopes):
    """Pairs of one phase in the root and in the other checkouts; a checkout's version wins.

    A subject read in a checkout counts only when that checkout changed what grounds it; the
    first such checkout wins. A found subject of the root grounded in paths a checkout changed,
    but not yielded there, was moved or removed in that checkout and is left out. A subject the
    provider did not find is dropped when its pipeline found any.
    """
    taken = {}
    for scope in scopes:
        for pipeline, subject in phase(scope.ctx, pipelines, query):
            if changed_in(scope.ctx, pipeline, subject, scope.paths):
                taken.setdefault((pipeline.name, subject.id),
                                 (pipeline, replace(subject, checkout=scope.ctx.root)))
    pairs = []
    for pipeline, subject in phase(ctx, pipelines, query):
        ident = (pipeline.name, subject.id)
        if ident in taken:
            pairs.append(taken.pop(ident))
        elif not subject.exists or not any(changed_in(ctx, pipeline, subject, scope.paths)
                                           for scope in scopes):
            pairs.append((pipeline, subject))
    pairs += taken.values()
    found = {p.name for p, s in pairs if s.exists}
    return [(p, s) for p, s in pairs if s.exists or p.name not in found]


def by_key(ctx, pipelines, query, scopes=None):
    """Pairs of every subject the key in the query addresses, in the root and other checkouts."""
    scopes = worktree_scopes(ctx) if scopes is None else scopes
    return across(ctx, pipelines, query, key_pairs, scopes)


def single_or_ambiguous(pairs):
    """Resolution of a name phase: one match, or several flagged as ambiguous."""
    return Resolution(matches=pairs, ambiguous=len(pairs) > 1)


def resolve(ctx, pipelines, query):
    """Exact name, then tracker key, then substring; each in the root and the other checkouts."""
    scopes = worktree_scopes(ctx)
    exact = across(ctx, pipelines, query, exact_pairs, scopes)
    if exact:
        return single_or_ambiguous(exact)
    keyed = by_key(ctx, pipelines, query, scopes)
    if keyed:
        return Resolution(matches=keyed)
    return single_or_ambiguous(across(ctx, pipelines, query, substring_pairs, scopes))
