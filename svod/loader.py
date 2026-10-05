"""Loads a store: config, registries, pipelines and locale."""
from dataclasses import dataclass

from .bindings import check_bindings, load_bindings
from .config import load_config
from .errors import LoadError, LocaleError
from .gates import build_registries
from .keys import CORE_KEYS
from .locale import load_locale
from .pipeline import bind_pipeline, parse_pipeline
from .yamlio import read_yaml

PIPELINES_DIR = "pipelines"
PIPELINE_GLOB = "*.yaml"


@dataclass
class Runtime:
    """Everything loaded for one store."""

    config: object
    locale: object
    gates: dict
    pipelines: list
    bindings: object = None

    def by_name(self):
        """Pipelines keyed by name, for gates that consult another pipeline."""
        return {p.name: p for p in self.pipelines}

    def pipeline(self, name):
        """Pipeline by name."""
        return next(p for p in self.pipelines if p.name == name)


def load_pipelines(profile, gates, providers):
    """Parse and bind every pipeline of the profile; return (pipelines, errors)."""
    pipelines, errors, names = [], [], set()
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


def description_errors(pipelines, locale):
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


def load_runtime(root):
    """Load the store at root; raise LoadError listing every problem found."""
    config = load_config(root)
    gates, providers = build_registries(config.profile)
    pipelines, errors = load_pipelines(config.profile, gates, providers)
    names = {p.name for p in pipelines}
    for name in config.active_order:
        if name not in names:
            errors.append(f"active_order: unknown pipeline: {name}")
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
                   bindings=bindings)
