# Structured planning (schema 1)

`svod plan` reads store-relative record paths (not tracker aliases). It does not
compute workflow position, execute gates, run commands, or fetch evidence URLs.
Existing profiles and records are not rewritten. Opt into the standard profile
separately; changed approval binds require fresh consent, not reusing old approval.

## Primary files

`card.md` frontmatter `status` remains authoritative; `parent` is a store-relative
record path. Research frontmatter `outcome` remains its existing routing value.

Project/feature `plan.yaml` has exactly these fields:

```yaml
schema_version: 1
expected: A usable product
nodes:
  - id: feature
    title: Feature
    expected: A usable feature
    record: work/features/example
  - id: later
    title: Unallocated work
    expected: A follow-up result
    parent: feature                 # optional local node ID
    dependencies: [feature]         # optional local node IDs
    state: open                     # optional; ONLY without record
    actual: null                    # optional string; ONLY without record
criteria:
  - id: usable
    statement: The product is usable
    verification: Exercise the documented workflow
    works: [feature, later]         # local node IDs; many-to-many
    dependencies:                  # optional criterion references
      - owner: work/features/example
        criterion: usable
```

All root fields are required. Node `id`, `title`, `expected` and criterion `id`,
`statement`, `verification`, `works` are required. Optional lists default to empty.
IDs match `[A-Za-z0-9][A-Za-z0-9_-]*`. Unknown fields and versions are errors.
Linked nodes cannot carry `state`/`actual`, even null: remove them explicitly when
binding. Nodes with no state are unknown; supported local states are open, active,
blocked, done, unknown. Linked status is read as written, not inferred from children.
Nested feature details stay in that feature's own plan; summaries include nested
plans, and diagnose known direct children omitted from the owner's nodes.

Task/feature/project `outcome.yaml` (optional; absence is explicitly unknown):

```yaml
schema_version: 1
actual: The observed result, not the expected result
evidence: []
```

`evidence` is a root-level list of nonempty strings, each either
an existing store-relative file or an https/http URL. URLs are references only and
are never fetched. Relative files must resolve within the store; missing and
escaping evidence is diagnosed. `actual` must be nonempty. Research is not given
this new outcome meaning.

`acceptance.yaml` is written by explicit confirmation, never by task completion:

```yaml
schema_version: 1
confirmations:
  - criterion: usable
    definition: <sha256 of canonical criterion definition>
    result: pass
    actual: Observed verification result
    evidence: [checks/product.txt]
    recorded_at: '2026-10-21T12:00:00+00:00'
    work_fingerprint: <sha256 of transitive supporting facts>
    evidence_fingerprint: <sha256 of local evidence bytes and URL references>
```

These are verification records, not human approvals. No identity is inferred from
Git. Results: pass/fail. History is append-only. A changed criterion definition
(including dependency definitions), changed supporting facts, reopened work or
unconfirmed dependency makes old evidence historical/review-required, never a
current pass. This conservative fingerprint also requests review after outcomes
change. No universal closure gate is added.

## Commands

```
svod plan validate work/projects/example
svod plan summary work/projects/example [--json]
svod plan summary --all [--json]
svod plan confirm work/projects/example --criterion usable --result pass \
  --actual 'Verified the complete workflow' --evidence checks/product.txt
svod plan canvas work/projects/example
```

Repeat `--evidence` for multiple sources. Confirmation refuses invalid input or
observed concurrent edits. Files are read again before replacement, with an
exclusive per-output lock; this is not a distributed transaction or protection
against a hostile noncooperating writer in the final check/replace interval.

Summary JSON has `schema_version`, `collected_at`, `records`, and structured
`diagnostics` (`code`, `path`, `message`, `severity`). It separates record status,
node execution and criterion acceptance; no task-count completion percentage is
computed. It reports input changes observed during collection; it is not a
transactional snapshot. Exit 1 indicates diagnostics (including unknown outcomes),
0 means no diagnostics, not product acceptance; usage/refusal exits 2.

Canvas is written only to the command's reserved `plan.canvas` output, marked with
`svod_generated: structured-planning-v1`. An existing unmarked or malformed canvas
is refused. JSON Canvas nodes/edges have stable owner-qualified IDs; existing
positions/sizes are retained. Semantic canvas edits never change primary YAML.

The bundled standard feature binds approval to brief/questions/plan definitions;
acceptance/outcome/canvas writes do not change that consent. Project retains
architecture approval before breakdown, with no new plan approval round. Deliver
binds primary outcome/acceptance (and feature integration checks), not breakdown.
Legacy profiles continue using their existing route until explicitly transitioned.

## Local verification

Executed against worktree base c4b8e722af44512bf531834d40024023d3a76af6 on macOS,
Python 3.12.13, PyYAML 6.0.3, pytest 9.1.1, ruff 0.17.1, mypy 2.4.0.
Environment: `TMPDIR=$HOME/.hermes/cache/scratch`, `PYTHONPATH=<this worktree>`.
Command prefix: `uv run --python 3.12 --with PyYAML --with pytest --with ruff --with mypy`.

- `pytest -q --tb=short`: 828 passed, 1927 subtests passed, 263.10 seconds.
- `ruff check svod tests`: all checks passed.
- `mypy --ignore-missing-imports svod`: no issues in 83 source files.
- `git diff --check`: clean.
- `python tests/benchmark_planning.py`: reproducibly builds 100 projects, 1000
  linked tasks, 1000 criteria in scratch, then starts a separate fresh Python CLI
  process for each measurement (no persistent cache). Latest full summary:
  **1.914781 seconds**, 100 records/1000 nodes/1000 criteria, zero diagnostics.
  Single project: **0.531875 seconds**, 1 record/10 nodes/10 criteria, zero
  diagnostics. Both local targets met; these are measurements, not guarantees.
  Standard-template `validate`, plan validate, canvas, and explicit confirmation
  smoke all exited 0; confirmation was read back with one history entry.

TDD began with a public CLI assertion failing on unrecognized `plan`, then green
after the first summary slice. Subsequent observed RED/GREEN slices covered linked
fresh facts/schema rejection, confirmation/history/dependencies, input/write races,
canvas layout/safety, standard scaffolds/binds, evidence edits, nested reopening,
invalid-current-PASS prevention, and computed reverse supports. Existing skeleton
tests were updated to compare all declared skeleton files, not assume card-only.

Scope limitations: discovery intentionally uses the standard `work/projects`,
`work/features`, `work/tasks`, `work/research` layout rather than loading executable
custom providers. URL evidence is not fetched or authenticated. File-race checks
are optimistic, not a transactional snapshot; new/deleted files outside observed
inputs and noncooperating writers in the final replace interval are not a
distributed concurrency guarantee. No live-store migration/install, commits,
publication, or task closure was performed. The uv invocation created local
`.venv` and `uv.lock`; these are execution artifacts, not required feature inputs.
