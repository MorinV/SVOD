"""Loads a store: config, registries, pipelines and locale."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .bindings import Bindings, check_bindings, load_bindings
from .config import (AUTONOMY_AUTONOMOUS, AUTONOMY_KINDS, AUTONOMY_SUPERVISED, FIELD_AUTONOMY,
                     FIELD_WORKSPACE_GATE, Config, load_config)
from .errors import LoadError, LocaleError, ParamError
from .gates import ApprovalGate, build_registries
from .keys import CORE_KEYS
from .locale import load_locale
from .pipeline import Pipeline, Step, bind_pipeline, parse_pipeline
from .yamlio import read_yaml

if TYPE_CHECKING:
    from .gates import Gate
    from .locale import Locale
    from .providers import Provider

PIPELINES_DIR = "pipelines"
PIPELINE_GLOB = "*.yaml"
WORKTREES_METHOD = "worktrees"
PURPOSE_RESULT = "result"


@dataclass
class Runtime:
    """Everything loaded for one store."""

    config: Config
    locale: Locale
    gates: dict[str, type[Gate]]
    pipelines: list[Pipeline]
    bindings: Bindings | None = None
    # A gate instance with worktrees(ctx, keys); None when not configured.
    workspace_gate: Any = None

    def by_name(self) -> dict[str, Pipeline]:
        """Pipelines keyed by name, for gates that consult another pipeline."""
        return {p.name: p for p in self.pipelines}

    def pipeline(self, name: str) -> Pipeline:
        """Pipeline by name."""
        return next(p for p in self.pipelines if p.name == name)


def load_pipelines(profile: Path, gates: dict[str, type[Gate]],
                   providers: dict[str, type[Provider]]) -> tuple[list[Pipeline], list[str]]:
    """Parse and bind every pipeline of the profile; return (pipelines, errors)."""
    pipelines: list[Pipeline] = []
    errors: list[str] = []
    names: set[str] = set()
    directory = profile / PIPELINES_DIR
    if not directory.is_dir():
        return [], [f"{directory}: pipelines directory not found"]
    for path in sorted(directory.glob(PIPELINE_GLOB)):
        try:
            data = read_yaml(path)
        except LoadError as exc:
            errors.extend(exc.errors)
            continue
        pipeline, parse_errors = parse_pipeline(data, path)
        errors.extend(parse_errors)
        if pipeline is None:
            continue
        if pipeline.name in names:
            errors.append(f"{path.name}: duplicate pipeline name: {pipeline.name}")
            continue
        names.add(pipeline.name)
        bind_errors = bind_pipeline(pipeline, gates, providers)
        errors.extend(bind_errors)
        if not bind_errors:
            pipelines.append(pipeline)
    return pipelines, errors


def description_errors(pipelines: list[Pipeline], locale: Locale) -> list[str]:
    """Gate uses shown in the documentation without a label whose description does not render."""
    errors = []
    for pipeline in pipelines:
        for ref in pipeline.documented_refs():
            if ref.label or ref.impl is None:
                continue
            try:
                ref.impl.describe(ref.params, locale)
            except LocaleError as exc:
                errors.append(f"{pipeline.source.name}: {ref.where}: {exc}")
    return errors


def workspace_gate(name: str | None, gates: dict[str, type[Gate]]) -> tuple[Gate | None, list[str]]:
    """(instance of the gate naming task workspaces, errors); (None, []) when not configured."""
    if name is None:
        return None, []
    cls = gates.get(name)
    if cls is None:
        return None, [f"{FIELD_WORKSPACE_GATE}: unknown gate: {name}"]
    if not callable(getattr(cls, WORKTREES_METHOD, None)):
        return None, [f"{FIELD_WORKSPACE_GATE}: {name} has no {WORKTREES_METHOD}(ctx, keys)"]
    try:
        return cls(), []
    except ParamError as exc:
        return None, [f"{FIELD_WORKSPACE_GATE}: {exc}"]


def approval_step(step: Step, purpose: str | None = None) -> bool:
    """Whether the step has an approval gate, of the given purpose when one is given."""
    return any(isinstance(ref.impl, ApprovalGate) and (purpose is None or ref.purpose == purpose)
               for ref in step.gates)


def relaxed(step: Step, level: str) -> Step:
    """The step as the autonomy level runs it: an approval step it lifts becomes optional.

    supervised lifts the approvals of the result, autonomous every approval; an optional step
    is neither required nor blocks code. Any other step, and every step under guided, is kept.
    """
    lifted = (level == AUTONOMY_AUTONOMOUS and approval_step(step)
              or level == AUTONOMY_SUPERVISED and approval_step(step, PURPOSE_RESULT))
    return replace(step, optional=True, required=False, blocks_code=False) if lifted else step


def apply_autonomy(pipelines: list[Pipeline], autonomy: dict[str, str]) -> list[str]:
    """Relax the approval steps of each pipeline by its autonomy level; return the errors.

    The loaded steps are replaced, the declaration files are not touched. A name that is
    neither a loaded pipeline nor a kind of work is an error. A kind (hotfix) has no effect
    here: the steps are shared by every subject of the pipeline.
    """
    names = {p.name for p in pipelines}
    errors = [f"{FIELD_AUTONOMY}: unknown pipeline: {name}" for name in autonomy
              if name not in names and name not in AUTONOMY_KINDS]
    for pipeline in pipelines:
        level = autonomy.get(pipeline.name)
        if level:
            pipeline.steps = [relaxed(step, level) for step in pipeline.steps]
    return errors


def load_runtime(root: Path) -> Runtime:
    """Load the store at root; raise LoadError listing every problem found."""
    config = load_config(root)
    gates, providers = build_registries(config.profile)
    pipelines, errors = load_pipelines(config.profile, gates, providers)
    workspaces, gate_errors = workspace_gate(config.workspace_gate, gates)
    errors.extend(gate_errors)
    names = {p.name for p in pipelines}
    for name in config.active_order:
        if name not in names:
            errors.append(f"active_order: unknown pipeline: {name}")
    errors.extend(apply_autonomy(pipelines, config.autonomy))
    required = set(CORE_KEYS)
    for pipeline in pipelines:
        required |= pipeline.locale_keys()
    try:
        locale = load_locale(config.locale, config.profile, required)
    except LoadError as exc:
        errors.extend(exc.errors)
        locale = None
    if locale is not None:
        errors.extend(description_errors(pipelines, locale))
    bindings = None
    if config.bindings is not None:
        try:
            bindings = load_bindings(config.bindings, gates)
            errors.extend(check_bindings(bindings, pipelines, config.root))
        except LoadError as exc:
            errors.extend(exc.errors)
    if errors:
        raise LoadError(errors)
    return Runtime(config=config, locale=locale, gates=gates, pipelines=pipelines,
                   bindings=bindings, workspace_gate=workspaces)
