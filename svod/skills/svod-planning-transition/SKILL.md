---
name: svod-planning-transition
description: Backfill existing SVOD plans without inventing acceptance.
---

# Transition an existing store to structured planning

## When to use

Use for a selected store's structured-planning upgrade or historical backfill,
including completed projects/features and their children. This is an agent-led,
source-grounded procedure, not a natural-language converter or a new workflow gate.
Do not run a mass backfill merely because a new engine is available.

## Prerequisites and discovery

1. Read the store's `AGENTS.md`, `svod.yaml`, local policy and current task contract.
   Run `svod active` and `svod status <transition-record>` for the authorized work;
   **active is not the inventory**. Respect the next step and existing write limits.
2. Identify the store root, launcher/interpreter, imported engine path, version and
   source/ref. Compare `svod --version` inside and outside the store. Inspect
   `.svod/VERSION` and `.svod/MANIFEST` if bundled; inspect the installed package's
   metadata/source checkout if shared. Inspect the hooks' interpreter/PYTHONPATH,
   profile pipelines, approval `bind`, children gates and template/customizations.
   Record unknown provenance as a blocker, not an assumed latest version.
3. Find this skill at `.svod/skills/svod-planning-transition/SKILL.md` in a bundled
   store or `svod/skills/svod-planning-transition/SKILL.md` in the selected source/
   installed package. Read `references/backfill.md` **inside this skill directory**
   (not relative to the store). It contains the worked example and verification
   matrix. Packaged resources may be read-only; write proposals in authorized
   task-owned output, never inside the installed skill.

Agent setup chooses **one whole skill directory**: store `skills/` with SKILL.md
files wins, then `.svod/skills/`, then source `svod/skills/`. Thus standard stores
can mask this engine skill. Read the explicit bundled/package path above rather
than replacing local skills or changing global agent configuration. Re-registering
hooks or copying/linking a skill needs permission and preserves local policy.
See the actual update behavior in
[Updating SVOD](https://github.com/MorinV/SVOD/blob/main/docs/updating.md).

## Procedure

1. **Separate three permissions:** installing/updating the engine, changing the
   profile's source/binds/gates, and writing backfill content for an exact scope.
   Show paths, source/ref, selected roots, exclusions and proposed changes first.
   No approval for one implies the others. Never synthesize a fresh approval.
2. **Upgrade only if authorized.** Preserve bundled versus shared installation.
   For an existing bundled copy use `svod update --from <source> --to <ref>
   --no-profile`; for a newly authorized bundled installation use `svod install`
   with the same flags. Do not add a bundled copy to a shared store. For shared
   installations use the existing environment/package manager and an explicit
   source/ref, not `svod update` as a substitute for updating that environment.
   Inspect migrations and resulting diff even with `--no-profile`; that flag
   leaves the profile alone, not necessarily every store file. Stop on conflicts.
3. **Inventory read-only before writing.** Enumerate all cards under the configured
   record roots, including done/archived records. Resolve parent links recursively
   for each selected project/feature and compare with brief/vision, breakdown,
   canvas, contracts, checks and outcomes. Find orphan, external and missing links;
   never silently adopt or discard them. Present source locations, conflicts and a
   per-record proposed delta. Details and coverage equations are in the reference.
4. **Map only grounded facts.** Keep existing record paths and stable IDs. Use
   `plan.yaml` for ISR/expected results/criterion definitions, `acceptance.yaml`
   for explicit confirmations, `outcome.yaml` for each record's actual result and
   existing `card.md` for status. Link a nested feature instead of duplicating its
   tasks in the project. Preserve source references in supported fields or an
   adjacent backfill note; do not invent unsupported schema keys.
5. **Preserve uncertainty and history.** Explicit criteria may be transferred;
   inferred criteria remain proposals. Ambiguous sources become a question, not a
   guessed mapping. Done is work status, not criterion acceptance. Historical
   confirmation needs criterion-specific check result AND evidence, its source and
   historical character. If the installed schema cannot represent that honestly,
   retain the evidence in a note and leave the criterion unconfirmed. Missing
   outcomes stay unknown. Never edit/rebind `approval.yaml`, replay consent, or
   call `svod approve` from old conversation text. New approval requires a real
   fresh human event under the store's normal flow.
6. **Review profile transition separately.** Show old/new primary plan, exact
   approval-bound bytes and gates affected. Keep originals and historical approval
   bytes; an unchanged approval file does not make changed bound content approved.
   Do not make Markdown/canvas and YAML competing primary plans. Propose the
   minimum explicit source/bind change, without new mandatory steps; stop the
   affected portion until authorized. A core upgrade alone does not select it.
7. **Apply in reviewable batches** only after scope/content permission. Reconcile
   against current files before each write; keep human refinements and stable
   criterion/node IDs. Unchanged sources mean no-op, not regenerate/overwrite.
   Isolate conflict questions to affected records and continue only independent,
   authorized portions. Do not reopen resolved questions without a new conflict.
8. **Validate and render** using the installed implementation's help and schema.
   The agreed CLI family is listed below. Resolve invalid references, parent/ISR
   disagreement, duplicate IDs and dependency cycles before claiming coverage.
   Read summaries for each selected project/feature and the all-project view;
   export canvas twice with a manual node move between runs. Canvas is derived:
   semantic canvas edits do not update YAML. Preserve layout of retained nodes.
9. **Repeat and report.** Programmatically compare the original inventory with
   converted/excluded/remaining sets, including completed records. Repeat backfill
   and export after a manual YAML refinement and node move: no duplicates, lost
   edits, question churn or changed history. Report unconfirmed criteria, missing
   outcomes, source conflicts, stale approvals and exact blockers. Do not call
   full backfill complete until the entire chosen scope is covered or a human
   explicitly narrows it. Report engine/profile/content verification separately.

## Schema 1 and verified command family

Read `docs/structured-planning.md` in the matching source distribution. Schema 1
project/feature `plan.yaml` requires `schema_version: 1`, `expected`, `nodes`,
`criteria`. Nodes require `id`, `title`, `expected`; link existing work with
`record` (canonical store-relative path), never add `state` or `actual` to linked
nodes, even null. Unlinked nodes may have `state` and `actual`; optional `parent`
and `dependencies` refer to local node IDs. Criteria require `id`, `statement`,
`verification`, `works` (local node IDs); optional criterion dependencies are
`{owner: <record>, criterion: <id>}`. Unknown fields are rejected. Put provenance
in an adjacent authorized note, not invented YAML keys.

`outcome.yaml` requires `schema_version: 1`, nonempty `actual`, `evidence` (list
of existing store-relative files or HTTP(S) references, never fetched). Absence
means unknown. Research keeps its original outcome routing, not this schema.
`acceptance.yaml` is append-only history written by explicit confirmation, not
human consent. It has no historical-kind/source-date import facility: preserve
old evidence in a note and leave unconfirmed rather than forging a current entry.

```sh
svod plan --help
svod plan validate work/projects/demo
svod plan summary work/projects/demo
svod plan summary work/projects/demo --json
svod plan summary --all
svod plan summary --all --json
svod plan canvas work/projects/demo
svod plan confirm --help
# Only after a real, explicitly authorized criterion-specific verification:
svod plan confirm work/features/search --criterion title --result pass \
  --actual 'Verified title lookup on the selected catalog' --evidence checks/title.txt
```

`--result` is `pass` or `fail`; repeat `--evidence` for multiple sources. Never
call confirm merely because a record is done or historical evidence exists.
Changed definitions, support, local evidence or reopened work make confirmations
historical/review-required. Exit 1 from validate/summary means diagnostics,
including unknown outcomes; exit 0 means no diagnostics, not product acceptance.
Refusals/usage exit 2. Distinguish known missing outcomes from structural errors.
Summary does not execute workflow gates. Canvas output is `<record>/plan.canvas`,
reserved with `svod_generated: structured-planning-v1`; existing unmarked or
malformed output is refused. Do not overwrite a legacy canvas to bypass refusal.
Retained stable nodes keep position/size; canvas semantics do not edit YAML.

The standard feature binds contract approval to `brief.md`, `questions.md`,
`plan.yaml`; its deliver bind is `checks.md`, `outcome.yaml`, `acceptance.yaml`.
Project retains architecture approval before breakdown; inspect its actual binds
before selecting a profile delta. Installation alone never opts in a legacy
profile. Prefer a minimal reviewed local delta over replacing customized policy.

The shipped `references/example.json` contains finite synthetic source bytes and
valid schema-1 target YAML (JSON syntax is YAML-compatible), not a generic prose
converter. Tests exercise it through a real bundled installation of combined core
and transition sources; wheel/discovery tests verify resource delivery separately.
If installed help/schema differs or `svod plan` is absent, stop writes and report
that capability mismatch. Passing fixture checks never means a live store was
backfilled, approved or migrated.

## Pitfalls and verification

- Never use an open-work listing as proof of full coverage or task completion as
  proof of acceptance. Do not change statuses to improve the summary.
- Do not delete original plans, replace local policy, install in real stores or
  alter personal agent runtimes without separate authorization.
- A historical PASS may be stale for the current definition. Preserve history and
  show the uncertainty; absence of a fresh run is not PASS.
- Use the reference's isolated verification matrix before reporting a completed
  transition; label every unchecked integration boundary explicitly.
