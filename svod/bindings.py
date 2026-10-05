"""Role bindings: which skill serves a step role, chosen by files in the subject's directories."""
from dataclasses import dataclass, field
from pathlib import Path

from .errors import LoadError, ParamError
from .yamlio import read_yaml

FIELD_PROBE = "probe"
FIELD_ROLES = "roles"
FIELD_SKILL_PATH = "skill_path"
FIELD_GATE = "gate"
FIELD_PARAMS = "params"
FIELD_FACT = "fact"
FIELD_WHEN = "when"
FIELD_SKILL = "skill"
FIELD_EXTERNAL = "external"
WHEN_HAS_FILE = "has_file"
SKILL_PLACEHOLDER = "{skill}"
TOP_FIELDS = frozenset({FIELD_PROBE, FIELD_ROLES, FIELD_SKILL_PATH})
PROBE_FIELDS = frozenset({FIELD_GATE, FIELD_PARAMS, FIELD_FACT})
RULE_FIELDS = frozenset({FIELD_WHEN, FIELD_SKILL, FIELD_EXTERNAL})
WHEN_FIELDS = frozenset({WHEN_HAS_FILE})


@dataclass
class Rule:
    """One binding rule: a condition on a directory and the skill it selects, or none."""

    skill: str | None
    when: dict = field(default_factory=dict)
    external: bool = False

    def matches(self, directory):
        """Whether the rule applies to the directory; an unconditional rule always does."""
        if not self.when:
            return True
        if directory is None:
            return False
        return (Path(directory) / self.when[WHEN_HAS_FILE]).is_file()


@dataclass
class Bindings:
    """Probe gate for directories, role rules and where skills live."""

    source: Path
    probe: object
    fact: str | None
    roles: dict
    skill_path: str | None


class _Parser:
    """Collects errors while reading a bindings file."""

    def __init__(self, source):
        """Remember the source for error messages."""
        self.source = Path(source)
        self.errors = []

    def error(self, where, message):
        """Record one error at a location."""
        self.errors.append(f"{self.source.name}: {where}: {message}")

    def mapping(self, data, where, known):
        """Mapping with only known keys, or None."""
        if not isinstance(data, dict):
            self.error(where, "expected a mapping")
            return None
        for key in sorted(set(data) - known, key=str):
            self.error(where, f"unknown key: {key}")
        return data

    def probe(self, data, gates):
        """Gate instance and fact name of the probe block."""
        where = FIELD_PROBE
        data = self.mapping(data, where, PROBE_FIELDS)
        if data is None:
            return None, None
        name, fact = data.get(FIELD_GATE), data.get(FIELD_FACT)
        if not isinstance(fact, str) or not fact:
            self.error(where, f"{FIELD_FACT} must be a non-empty string")
        cls = gates.get(name)
        if cls is None:
            self.error(where, f"unknown gate: {name}")
            return None, fact
        try:
            return cls(data.get(FIELD_PARAMS) or {}), fact
        except ParamError as exc:
            self.error(where, str(exc))
            return None, fact

    def rule(self, data, where):
        """One rule of a role."""
        data = self.mapping(data, where, RULE_FIELDS)
        if data is None:
            return None
        if FIELD_SKILL not in data:
            self.error(where, f"missing key: {FIELD_SKILL}")
        skill = data.get(FIELD_SKILL)
        if skill is not None and (not isinstance(skill, str) or not skill.strip()):
            self.error(where, f"{FIELD_SKILL} must be a non-empty string or null")
        external = data.get(FIELD_EXTERNAL, False)
        if not isinstance(external, bool):
            self.error(where, f"{FIELD_EXTERNAL} must be a boolean")
        when = data.get(FIELD_WHEN) or {}
        when_where = f"{where}.{FIELD_WHEN}"
        if self.mapping(when, when_where, WHEN_FIELDS) is not None:
            if WHEN_HAS_FILE in when and not isinstance(when[WHEN_HAS_FILE], str):
                self.error(when_where, f"{WHEN_HAS_FILE} must be a file name")
        return Rule(skill=skill, when=when if isinstance(when, dict) else {},
                    external=external is True)

    def roles(self, data):
        """Role name to its ordered rules."""
        where = FIELD_ROLES
        if not isinstance(data, dict):
            self.error(where, "expected a mapping of role to rules")
            return {}
        roles = {}
        for role, rules in data.items():
            role_where = f"{where}.{role}"
            if not isinstance(rules, list) or not rules:
                self.error(role_where, "expected a non-empty list of rules")
                continue
            parsed = [self.rule(item, f"{role_where}[{i}]") for i, item in enumerate(rules)]
            roles[str(role)] = [r for r in parsed if r is not None]
        return roles


def load_bindings(path, gates):
    """Read and validate a bindings file; raise LoadError listing every problem."""
    data = read_yaml(path)
    parser = _Parser(path)
    data = parser.mapping(data, "top level", TOP_FIELDS)
    if data is None:
        raise LoadError(parser.errors)
    probe, fact = (None, None)
    if data.get(FIELD_PROBE) is not None:
        probe, fact = parser.probe(data[FIELD_PROBE], gates)
    roles = parser.roles(data.get(FIELD_ROLES, {}))
    skill_path = data.get(FIELD_SKILL_PATH)
    if skill_path is not None and (not isinstance(skill_path, str)
                                   or SKILL_PLACEHOLDER not in skill_path):
        parser.error(FIELD_SKILL_PATH, f"must be a path template with {SKILL_PLACEHOLDER}")
    if any(r.when for rules in roles.values() for r in rules) and probe is None:
        parser.error(FIELD_PROBE, f"required when a rule has {FIELD_WHEN}")
    if parser.errors:
        raise LoadError(parser.errors)
    return Bindings(source=Path(path), probe=probe, fact=fact, roles=roles,
                    skill_path=skill_path)


def check_bindings(bindings, pipelines, root):
    """Errors: a pipeline role without rules, a skill that is neither found nor external."""
    errors = []
    name = bindings.source.name
    for pipeline in pipelines:
        for step in pipeline.steps:
            if step.role and step.role not in bindings.roles:
                errors.append(f"{pipeline.source.name}: steps.{step.id}: role {step.role} "
                              f"is not described in {name}")
    for role, rules in bindings.roles.items():
        for rule in rules:
            if rule.skill is None or rule.external:
                continue
            if bindings.skill_path is None:
                errors.append(f"{name}: {FIELD_ROLES}.{role}: {FIELD_SKILL_PATH} is required "
                              f"for skill {rule.skill}")
                continue
            path = Path(root) / bindings.skill_path.replace(SKILL_PLACEHOLDER, rule.skill)
            if not path.is_file():
                errors.append(f"{name}: {FIELD_ROLES}.{role}: skill {rule.skill} not found at "
                              f"{path}; mark it {FIELD_EXTERNAL}: true if it lives elsewhere")
    return errors


def probe_dirs(ctx, bindings, subject):
    """(label, directory) pairs the probe gate reports for the subject."""
    if bindings.probe is None:
        return []
    result = bindings.probe.evaluate(ctx, subject)
    value = result.facts.get(bindings.fact) if result.passed else None
    if isinstance(value, dict):
        return [(str(label), path) for label, path in value.items()]
    if isinstance(value, (list, tuple)):
        return [(Path(path).name, path) for path in value]
    return []


def resolve_role(ctx, bindings, role, subject):
    """(label, skill or None) per probed directory; one unlabelled item without directories."""
    rules = bindings.roles.get(role, [])
    dirs = probe_dirs(ctx, bindings, subject) if any(r.when for r in rules) else []
    if not dirs:
        rule = next((r for r in rules if r.matches(None)), None)
        return [(None, rule.skill if rule else None)]
    return [(label, next((r.skill for r in rules if r.matches(path)), None))
            for label, path in dirs]
