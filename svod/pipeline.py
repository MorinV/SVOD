"""Pipeline declarations: schema validation and binding to registries."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ParamError
from .gates import KeyGate

FIELD_PIPELINE = "pipeline"
FIELD_SUBJECT = "subject"
FIELD_ACTIVE = "active"
FIELD_ENTRY = "entry"
FIELD_DONE = "done"
FIELD_MISSING = "missing"
FIELD_STEPS = "steps"
FIELD_VIOLATIONS = "violations"
FIELD_HEADER = "header"
FIELD_PROVIDER = "provider"
FIELD_KEY_GATE = "key_gate"
FIELD_KEY_PARAMS = "key_params"
FIELD_PARAMS = "params"
FIELD_IN_PROGRESS = "in_progress"
FIELD_FACT = "fact"
FIELD_ITEM = "item"
FIELD_HEADINGS = "headings"
FIELD_GATE = "gate"
FIELD_GATES = "gates"
FIELD_WHEN = "when"
FIELD_SEVERITY = "severity"
FIELD_TEXT = "text"
FIELD_LABEL = "label"
FIELD_ID = "id"
FIELD_REQUIRED = "required"
FIELD_OPTIONAL = "optional"
FIELD_BLOCKS_CODE = "blocks_code"
FIELD_ROLE = "role"
FIELD_TITLE = "title"
FIELD_PENDING = "pending"
FIELD_PURPOSE = "purpose"

PIPELINE_FIELDS = frozenset({FIELD_PIPELINE, FIELD_SUBJECT, FIELD_ACTIVE, FIELD_ENTRY,
                             FIELD_DONE, FIELD_MISSING, FIELD_STEPS, FIELD_VIOLATIONS,
                             FIELD_HEADER})
PIPELINE_REQUIRED = (FIELD_PIPELINE, FIELD_SUBJECT, FIELD_STEPS)
SUBJECT_FIELDS = frozenset({FIELD_PROVIDER, FIELD_KEY_GATE, FIELD_KEY_PARAMS, FIELD_PARAMS})
ACTIVE_FIELDS = frozenset({FIELD_IN_PROGRESS, FIELD_ITEM, FIELD_HEADINGS})
IN_PROGRESS_FIELDS = frozenset({FIELD_GATE, FIELD_PARAMS, FIELD_FACT})
ENTRY_FIELDS = frozenset({FIELD_GATE, FIELD_PARAMS, FIELD_WHEN, FIELD_SEVERITY, FIELD_TEXT})
ENTRY_REQUIRED = (FIELD_GATE, FIELD_SEVERITY, FIELD_TEXT)
DONE_FIELDS = frozenset({FIELD_GATE, FIELD_PARAMS, FIELD_TEXT, FIELD_PENDING})
DONE_REQUIRED = (FIELD_GATE, FIELD_TEXT)
MISSING_FIELDS = frozenset({FIELD_GATE, FIELD_PARAMS, FIELD_TEXT})
STEP_FIELDS = frozenset({FIELD_ID, FIELD_TEXT, FIELD_REQUIRED, FIELD_OPTIONAL, FIELD_BLOCKS_CODE,
                         FIELD_ROLE, FIELD_GATES, FIELD_ENTRY, FIELD_TITLE, FIELD_WHEN})
STEP_GATE_FIELDS = frozenset({FIELD_GATE, FIELD_PARAMS, FIELD_LABEL, FIELD_TEXT,
                              FIELD_PURPOSE, FIELD_WHEN})

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"
SEVERITIES = (SEVERITY_BLOCK, SEVERITY_WARN)
GROUP_MINE_ACTIVE = "mine_active"
GROUP_MINE_IDLE = "mine_idle"
GROUP_THEIRS = "theirs"
GROUP_THEIRS_COLLAPSED = "theirs_collapsed"
GROUP_WORKTREE = "worktree"
HEADING_GROUPS = (GROUP_MINE_ACTIVE, GROUP_MINE_IDLE, GROUP_THEIRS, GROUP_THEIRS_COLLAPSED,
                  GROUP_WORKTREE)
VIOLATION_SEPARATOR = "."
VIOLATION_PARTS = 2
STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass
class GateRef:
    """Use of a gate in a pipeline: name, params and presentation."""

    gate: str
    params: dict
    where: str
    label: str | None = None
    text: str | None = None
    when: str | None = None
    severity: str | None = None
    pending: str | None = None
    impl: object = None
    purpose: str | None = None


@dataclass
class Step:
    """One step of a pipeline."""

    id: str
    text: str | None
    required: bool
    optional: bool
    blocks_code: bool
    role: str | None
    gates: list
    entry: list
    title: str | None = None
    when: str | None = None


@dataclass
class SubjectSpec:
    """Which provider supplies subjects and which gate recognises keys."""

    provider: str
    key_gate: str | None
    params: dict
    impl: object = None
    key_impl: object = None
    key_params: dict = field(default_factory=dict)


@dataclass
class ActiveSpec:
    """How the pipeline takes part in the active summary."""

    in_progress: GateRef | None
    fact: str | None
    item: str | None
    headings: dict


@dataclass
class Pipeline:
    """Validated pipeline declaration."""

    name: str
    source: Path
    subject: SubjectSpec
    steps: list
    entry: list = field(default_factory=list)
    done: GateRef | None = None
    missing: GateRef | None = None
    active: ActiveSpec | None = None
    violations: dict = field(default_factory=dict)
    header: str | None = None

    def step(self, step_id):
        """Step by id."""
        return next(s for s in self.steps if s.id == step_id)

    def gate_refs(self):
        """Every gate use in the pipeline."""
        refs = list(self.entry)
        if self.done:
            refs.append(self.done)
        if self.missing:
            refs.append(self.missing)
        if self.active and self.active.in_progress:
            refs.append(self.active.in_progress)
        for step in self.steps:
            refs.extend(step.entry)
            refs.extend(step.gates)
        return refs

    def documented_refs(self):
        """Gate uses shown in the rendered documentation: entry, done, steps and their entry."""
        refs = list(self.entry)
        if self.done:
            refs.append(self.done)
        for step in self.steps:
            refs.extend(step.entry)
            refs.extend(step.gates)
        return refs

    def locale_keys(self):
        """Every locale key the declaration refers to."""
        keys = set(self.violations.values())
        if self.header:
            keys.add(self.header)
        for ref in self.gate_refs():
            keys.update(k for k in (ref.text, ref.label, ref.pending) if k)
        for step in self.steps:
            keys.update(k for k in (step.text, step.title) if k)
        if self.active:
            keys.update(self.active.headings.values())
            if self.active.item:
                keys.add(self.active.item)
        return keys


class _Parser:
    """Collects schema errors while building a Pipeline."""

    def __init__(self, source):
        """Remember the source file for error messages."""
        self.source = Path(source)
        self.errors = []

    def error(self, where, message):
        """Record one error at a location."""
        self.errors.append(f"{self.source.name}: {where}: {message}")

    def mapping(self, data, where, known, required=()):
        """Check a mapping for unknown and missing keys; return it or None."""
        if not isinstance(data, dict):
            self.error(where, "expected a mapping")
            return None
        for key in sorted(set(data) - known, key=str):
            self.error(where, f"unknown key: {key}")
        for key in required:
            if key not in data:
                self.error(where, f"missing key: {key}")
        return data

    def string(self, data, key, where):
        """Optional non-empty string field; presence is checked by mapping()."""
        value = data.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            self.error(where, f"{key} must be a non-empty string")
            return None
        return value

    def flag(self, data, key, where):
        """Optional boolean field, false by default."""
        value = data.get(key, False)
        if not isinstance(value, bool):
            self.error(where, f"{key} must be a boolean")
            return False
        return value

    def token(self, data, key, where):
        """Optional identifier; applicability is not an expression language."""
        value = self.string(data, key, where)
        if value is not None and not STEP_ID_RE.fullmatch(value):
            self.error(where, f"{key} must match {STEP_ID_RE.pattern}")
            return None
        return value

    def params(self, data, where, key=FIELD_PARAMS):
        """Optional params mapping under the key."""
        value = data.get(key, {})
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.error(where, f"{key} must be a mapping")
            return {}
        return value

    def items(self, data, key, where):
        """Optional list field."""
        value = data.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list):
            self.error(where, f"{key} must be a list")
            return []
        return value

    def gate_ref(self, data, where, known, required):
        """Gate use with the allowed presentation fields."""
        data = self.mapping(data, where, known, required)
        if data is None:
            return None
        severity = self.string(data, FIELD_SEVERITY, where)
        if severity and severity not in SEVERITIES:
            self.error(where, f"{FIELD_SEVERITY} must be one of {', '.join(SEVERITIES)}")
        return GateRef(
            gate=self.string(data, FIELD_GATE, where) or "",
            params=self.params(data, where),
            where=where,
            label=self.string(data, FIELD_LABEL, where),
            text=self.string(data, FIELD_TEXT, where),
            when=self.token(data, FIELD_WHEN, where),
            purpose=self.token(data, FIELD_PURPOSE, where),
            severity=severity,
            pending=self.string(data, FIELD_PENDING, where),
        )

    def entry_list(self, data, where):
        """List of entry gates."""
        refs = []
        for i, item in enumerate(self.items(data, FIELD_ENTRY, where)):
            ref = self.gate_ref(item, f"{where}{FIELD_ENTRY}[{i}]", ENTRY_FIELDS, ENTRY_REQUIRED)
            if ref:
                refs.append(ref)
        return refs

    def subject(self, data):
        """Subject block."""
        where = FIELD_SUBJECT
        data = self.mapping(data, where, SUBJECT_FIELDS, (FIELD_PROVIDER,))
        if data is None:
            return SubjectSpec(provider="", key_gate=None, params={})
        return SubjectSpec(
            provider=self.string(data, FIELD_PROVIDER, where) or "",
            key_gate=self.string(data, FIELD_KEY_GATE, where),
            params=self.params(data, where),
            key_params=self.params(data, where, FIELD_KEY_PARAMS),
        )

    def active(self, data):
        """Active summary block."""
        where = FIELD_ACTIVE
        data = self.mapping(data, where, ACTIVE_FIELDS)
        if data is None:
            return None
        in_progress, fact = None, None
        raw = data.get(FIELD_IN_PROGRESS)
        ip_where = f"{where}.{FIELD_IN_PROGRESS}"
        if isinstance(raw, str):
            in_progress = GateRef(gate=raw, params={}, where=ip_where)
        elif raw is not None:
            raw = self.mapping(raw, ip_where, IN_PROGRESS_FIELDS, (FIELD_GATE,))
            if raw is not None:
                in_progress = GateRef(gate=self.string(raw, FIELD_GATE, ip_where) or "",
                                      params=self.params(raw, ip_where), where=ip_where)
                fact = self.string(raw, FIELD_FACT, ip_where)
        headings = {}
        raw_headings = data.get(FIELD_HEADINGS)
        h_where = f"{where}.{FIELD_HEADINGS}"
        if raw_headings is not None:
            raw_headings = self.mapping(raw_headings, h_where, frozenset(HEADING_GROUPS))
            for group in HEADING_GROUPS:
                if raw_headings and group in raw_headings:
                    value = self.string(raw_headings, group, h_where)
                    if value:
                        headings[group] = value
        return ActiveSpec(in_progress=in_progress, fact=fact,
                          item=self.string(data, FIELD_ITEM, where), headings=headings)

    def step(self, data, index):
        """One step with its gates and entry."""
        where = f"{FIELD_STEPS}[{index}]"
        data = self.mapping(data, where, STEP_FIELDS, (FIELD_ID,))
        if data is None:
            return None
        step_id = self.string(data, FIELD_ID, where)
        if step_id and not STEP_ID_RE.match(step_id):
            self.error(where, f"{FIELD_ID} must match {STEP_ID_RE.pattern}")
        gates = []
        for i, item in enumerate(self.items(data, FIELD_GATES, where)):
            ref = self.gate_ref(item, f"{where}.{FIELD_GATES}[{i}]", STEP_GATE_FIELDS,
                                (FIELD_GATE,))
            if ref:
                gates.append(ref)
        step = Step(
            id=step_id or "",
            text=self.string(data, FIELD_TEXT, where),
            required=self.flag(data, FIELD_REQUIRED, where),
            optional=self.flag(data, FIELD_OPTIONAL, where),
            blocks_code=self.flag(data, FIELD_BLOCKS_CODE, where),
            role=self.string(data, FIELD_ROLE, where),
            gates=gates,
            entry=self.entry_list(data, f"{where}."),
            title=self.string(data, FIELD_TITLE, where),
            when=self.token(data, FIELD_WHEN, where),
        )
        if step.optional and (step.required or step.blocks_code):
            self.error(where, f"{FIELD_OPTIONAL} excludes {FIELD_REQUIRED} and {FIELD_BLOCKS_CODE}")
        if not step.text and (not gates or any(not g.text for g in gates)):
            self.error(where, f"{FIELD_TEXT} is required unless every gate has its own")
        return step

    def violations(self, data, steps):
        """Override texts for order violations, keyed later.earlier."""
        where = FIELD_VIOLATIONS
        if data is None:
            return {}
        if not isinstance(data, dict):
            self.error(where, "expected a mapping")
            return {}
        order = {s.id: i for i, s in enumerate(steps)}
        result = {}
        for key, value in data.items():
            parts = str(key).split(VIOLATION_SEPARATOR)
            if len(parts) != VIOLATION_PARTS or not all(p in order for p in parts):
                self.error(where, f"{key}: expected <later step>{VIOLATION_SEPARATOR}<earlier step>")
                continue
            later, earlier = parts
            if order[later] <= order[earlier]:
                self.error(where, f"{key}: {later} must come after {earlier}")
                continue
            if not steps[order[earlier]].required:
                self.error(where, f"{key}: {earlier} is not required")
                continue
            if not isinstance(value, str) or not value.strip():
                self.error(where, f"{key}: text must be a non-empty string")
                continue
            result[str(key)] = value
        return result

    def pipeline(self, data):
        """Whole declaration."""
        data = self.mapping(data, "top level", PIPELINE_FIELDS, PIPELINE_REQUIRED)
        if data is None:
            return None
        name = self.string(data, FIELD_PIPELINE, "top level") or ""
        subject = self.subject(data.get(FIELD_SUBJECT))
        steps = []
        for i, raw in enumerate(self.items(data, FIELD_STEPS, "top level")):
            step = self.step(raw, i)
            if step:
                steps.append(step)
        if FIELD_STEPS in data and not steps:
            self.error(FIELD_STEPS, "at least one step is required")
        seen = set()
        for step in steps:
            if step.id in seen:
                self.error(FIELD_STEPS, f"duplicate step id: {step.id}")
            seen.add(step.id)
        done = None
        if data.get(FIELD_DONE) is not None:
            done = self.gate_ref(data[FIELD_DONE], FIELD_DONE, DONE_FIELDS, DONE_REQUIRED)
        missing = None
        if data.get(FIELD_MISSING) is not None:
            missing = self.gate_ref(data[FIELD_MISSING], FIELD_MISSING, MISSING_FIELDS,
                                    DONE_REQUIRED)
        active = self.active(data[FIELD_ACTIVE]) if data.get(FIELD_ACTIVE) is not None else None
        return Pipeline(
            name=name,
            source=self.source,
            subject=subject,
            steps=steps,
            entry=self.entry_list(data, ""),
            done=done,
            missing=missing,
            active=active,
            violations=self.violations(data.get(FIELD_VIOLATIONS), steps),
            header=self.string(data, FIELD_HEADER, "top level"),
        )


def parse_pipeline(data, source):
    """Validate a raw declaration; return (pipeline or None, errors)."""
    parser = _Parser(source)
    pipeline = parser.pipeline(data)
    return (None if parser.errors else pipeline), parser.errors


def bind_pipeline(pipeline, gates, providers):
    """Instantiate gates and the provider of a parsed pipeline; return errors."""
    errors = []
    prefix = pipeline.source.name

    def make_gate(name, params, where):
        """Gate instance from the registry, or None with an error recorded."""
        cls = gates.get(name)
        if cls is None:
            errors.append(f"{prefix}: {where}: unknown gate: {name}")
            return None
        try:
            return cls(params)
        except ParamError as exc:
            errors.append(f"{prefix}: {where}: {exc}")
            return None

    for ref in pipeline.gate_refs():
        ref.impl = make_gate(ref.gate, ref.params, ref.where)

    spec = pipeline.subject
    if spec.key_gate:
        spec.key_impl = make_gate(spec.key_gate, spec.key_params,
                                  f"{FIELD_SUBJECT}.{FIELD_KEY_GATE}")
        if spec.key_impl is not None and not isinstance(spec.key_impl, KeyGate):
            errors.append(f"{prefix}: {FIELD_SUBJECT}.{FIELD_KEY_GATE}: "
                          f"{spec.key_gate} does not recognise keys")
            spec.key_impl = None
    elif spec.key_params:
        errors.append(f"{prefix}: {FIELD_SUBJECT}: {FIELD_KEY_PARAMS} needs {FIELD_KEY_GATE}")
    cls = providers.get(spec.provider)
    if cls is None:
        errors.append(f"{prefix}: {FIELD_SUBJECT}: unknown provider: {spec.provider}")
    else:
        try:
            spec.impl = cls(spec.params, spec.key_impl)
        except ParamError as exc:
            errors.append(f"{prefix}: {FIELD_SUBJECT}: {exc}")
    return errors
