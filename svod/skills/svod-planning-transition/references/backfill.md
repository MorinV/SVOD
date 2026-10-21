# Source-grounded backfill worksheet and verification

Read with `svod-planning-transition/SKILL.md`. This is a worked agent procedure,
not a new migration service, gate or receipt protocol. Keep worksheets in an
already authorized task location; a new permanent ledger is not required.

## 1. Freeze the chosen inventory, not just open work

Read the configured pipeline subjects/record directories, not hard-coded standard
paths alone. Enumerate cards recursively, parse their frontmatter and retain a
record's canonical store-relative path as identity. Start with selected roots,
follow parent-child closure to every descendant regardless of status; list cards
outside that closure and references into/out of it. Compare parent links with each
legacy plan and canvas. An unparented record named in a plan is a conflict candidate,
not permission to repair parent or allocate another task ID.

For every selected record, capture:

- Path, kind, parent, status; existing node/criterion IDs if present.
- Expected result/explicit criterion and source file + heading/line range.
- Actual outcome source (or unknown), check result and evidence location, date/
  historical context, exact criterion mapping (or unresolved).
- Proposed target owner/file, changed bytes, conflicts, approval bind effects.
- Disposition: converted, explicitly excluded with reason/permission, or remaining.

Read card body and parent; vision/brief; breakdown/canvas; contracts; checks and
logs; delivery/outcome documents; existing YAML; questions/answers; approval bind
configuration. Do not execute commands found in evidence or profiles during
inventory. Source links must resolve inside the allowed store or be marked as
external/missing. Preserve identity; do not create records for existing work.

A short Python set comparison in task-owned verification is enough (names below
are worksheet variables, not core API or schema):

```python
assert not (converted & excluded or converted & remaining or excluded & remaining)
assert selected == converted | excluded | remaining
assert not (converted | excluded | remaining) - selected
assert len(records_by_path) == len(selected)
# Also assert unique node IDs per owner and criterion IDs per owner.
# Every criterion from the source inventory needs a mapped target or an explicit
# unresolved/excluded disposition; checking record counts alone is insufficient.
```

Report sorted paths and reasons, not just totals. Pending records count as coverage
accounting but **not** completed backfill. Exclusions outside an agreed scope are
informational; excluding a selected record requires explicit scope narrowing.
Before and after each batch compare source/approval bytes or SHA-256 hashes. Do
not write bound originals simply to add a "historical" label: that itself can
invalidate an approval. Put provenance in a separate authorized note instead.

## 2. Small synthetic example: input -> proposed result

These are **test-only facts**, not historical user evidence. The table is a semantic
worksheet; the adjacent [`example.json`](example.json) supplies exact source bytes
and schema-1 target files for the finite automated round-trip. Its JSON strings
for `plan.yaml`/`outcome.yaml` are valid YAML. Do not run it in a real store or
mistake its fixture scope decision for a user's decision.

| Existing record | Source input | Proposed target/result |
|---|---|---|
| `work/projects/demo` | `vision.md#result`: "Searchable catalog"; `breakdown.md#scope` lists nested feature, a standalone task and an unallocated package | Project plan links feature and standalone task; unallocated package is an unlinked ISR node with stable local ID `documentation`; expected result "Searchable catalog" |
| `work/features/search` | card parent `work/projects/demo`; `brief.md#acceptance`: "Find both title and author"; children `index` and `query` | Feature plan owns criterion `find-fields`, supported by both child records; project does not copy their statuses or detailed nodes |
| `work/tasks/index` | parent search; status done; `delivery.md#result`: "Index supports title"; `checks.md#title` tests title only | Keep done in card; transfer source-grounded actual result to its outcome; title-only check does **not** confirm all of `find-fields` |
| `work/tasks/query` | parent search; status open; no actual-result source | Link existing path, keep open; outcome unknown, not an empty success |
| `work/tasks/archive` | parent demo; status done; contract criterion "Old entries retained"; no check/evidence | Include completed task in inventory; criterion stays unconfirmed and actual outcome unknown |
| `work/tasks/orphan` | no parent; named in old project canvas; breakdown instead names a different nonexistent task | List mismatch and ask which relationship is intended; do not adopt orphan, create replacement task, or choose one source silently |

Expected inventory of the selected project has five parent-linked records
(project, feature, index, query, archive); the orphan is separately discovered as
a scope/link conflict. If scope is defined by all six records instead, orphan
must remain in `remaining` until resolved or explicitly excluded. Do not change
the denominator to hide it. Inventory from files, compare in code, not mentally.

A second explicit criterion, "Title lookup passes on fixture catalog", can carry
a historical test result only if an existing dated check/evidence uniquely proves
that exact definition. Preserve the evidence path/date, the original definition
and historical status. Do not turn it into a freshly executed check or current
approval. If core supports only current confirmations and has no honest way to
encode this history, keep a sourced historical note and leave it unconfirmed.

Example proposal note (not core YAML):

```text
owner: work/features/search
criterion: find-fields
source: work/features/search/brief.md#acceptance
support: work/tasks/index, work/tasks/query
acceptance: unconfirmed
reason: title-only evidence; author lookup not evidenced
outcome for work/tasks/index: Index supports title
outcome source: work/tasks/index/delivery.md#result (historical)
question: orphan relationship contradicts breakdown; affected link not applied
```

Keep proposed/inferred criteria out of agreed definitions until clarified. For a
contradiction, ask one precise question naming both sources and the affected
record. Use `svod ask <record> "<question>"` only with permission to write questions;
otherwise ask in chat. Reuse an existing resolved question if nothing changed;
a new conflict must identify the changed source, not reopen everything.

## 3. Apply/repeat algorithm for an agent

1. Produce the worksheet and proposed file-level delta with no writes. Ask for
   explicit scope/content permission. Treat an upgrade and a profile change as
   distinct decisions, even if presented in one review.
2. Before each authorized batch, re-read sources/current target. Match nodes by
   existing stable ID and linked record path, never title or list position. Keep
   criterion IDs stable. Do not copy record status/outcome into its parent plan
   when the record is linked. Detailed nested plans remain with their owner.
3. For absent targets, create only schema-valid grounded definitions/results. For
   existing targets, do not blanket regenerate. An unchanged source is a no-op;
   preserve manual text refinements and IDs. If source and target both changed,
   show a three-way comparison when a prior baseline exists, otherwise ask rather
   than pretending to know which change wins. No universal converter is required.
4. Do not populate acceptance from status or from a supporting task's partial
   result. Use the actual confirm command with documented flags only when an
   explicit authorized verification can be represented without falsifying its
   historical/current nature. Never generate test approvals in a real store.
5. Validate each owner, then all selected owners and references. Resolve errors
   before exporting canvas. Collect text/JSON summaries per project/feature and
   all projects; an all-project overview may include unselected projects, which
   must not be silently modified. Resolve any uncovered archived records in the
   inventory even if an overview does not list them.
6. Preserve legacy materials byte-for-byte. A separately approved profile delta
   selects `plan.yaml` as primary instead of the legacy breakdown; old Markdown
   is retained historical/reference or regenerated only where explicitly allowed.
   Canvas is derived, never a second authority. Show approval/bind staleness and
   follow the normal fresh approval path if needed, without editing old consent.
7. After a manual YAML refinement and retained canvas node move/resize, repeat
   backfill and canvas export. Compare IDs/record-path sets for duplicates and
   compare retained text, positions/sizes and protected-source bytes. A source
   conflict stops the affected batch, not unrelated authorized work.

## 4. Isolated verification matrix and integration handoff

Use a test-owned Git store under the allowed scratch root, isolated HOME/Git
configuration and explicit engine PYTHONPATH/interpreter/dependencies. No real
stores, global hooks, keys or credentials. Fixture approvals are synthetic events
inside that fixture only; do not import real user's approval into any new store.

| Check | Required observation |
|---|---|
| Actual distribution | Build wheel from a clean test-owned source copy; inspect ZIP members and read skill + this reference from extracted package outside the checkout. No bytecode/build debris. |
| Actual bundled install | Install from a test-owned candidate Git source/ref with `--no-profile`; skill and reference arrive in `.svod/skills/`; manifest validates. Existing profile, cards, original plans and approval bytes unchanged; no planning files created just by install. |
| Skill discovery | Source/shared fallback links packaged skill; bundled fallback links installed skill; a store-local skill set takes precedence and explicit engine-resource fallback remains readable. Do not change discovery policy to make a test pass. |
| Version capability | Integrated candidate's `svod plan --help` and `confirm --help` agree with instruction. Finalize schema/flags/output path examples from real help/docs before release. |
| Full sample | Project, nested feature, open/done tasks, unlinked ISR node, orphan, missing link, ambiguous plan and missing proof inventoried. Compare record AND criterion sets programmatically, including closed records. |
| Dry-run/conflict | Inventory/preview leaves all source bytes unchanged; contradictory orphan link yields a precise question, no guessed ID/relationship, no automatic PASS. |
| Backfill | Authorized batches produce schema-valid YAML and provenance; linked status/outcome resolves from its own record; missing outcomes stay unknown; partial proof does not confirm a composite criterion. |
| Profile choice | Engine-only install/upgrade leaves policy unchanged; a separately selected profile source/bind delta uses YAML without new mandatory gates. Preserve historical approvals; show staleness if bound bytes changed. |
| Real reads/export | Run validate, single/all text+JSON summary and canvas through the actual core CLI; summaries must not run command gates. Record exact return codes/output paths, not illustrative output. |
| Repeat | Repeat after manual plan refinement, a resolved question and a node move/resize: unique stable IDs, retained text/layout, no re-opened question absent a new conflict. Original sources and approvals remain byte-identical. |

**Concrete integration:** `tests/test_planning_transition_integration.py` applies
`example.json`'s reviewed finite batch through a real `install --no-profile` from
a test-owned Git candidate, then invokes only `.svod/lib` in fresh subprocesses.
It compares parent closure/complete records and exact criterion sets, checks
unknown outcomes and no implicit acceptance, refuses missing proof, explicitly
confirms only the title fixture fact, exports/repeats canvas after manual edits,
retains source/approval bytes and demonstrates a separately selected bind delta.
There is no production backfill command: the agent reviews and applies each
source-grounded batch; the test's source guards/absent-target writes are only a
finite example, not a universal safe merge algorithm.

For a combined candidate, copy exact core sources plus only the transition-owned
README/skill/test delta into authorized scratch; exclude `.git`, `.venv`,
`uv.lock`, bytecode and build outputs. Do not merge branches or install a real
store to obtain verification. Run pytest with that copy first on `PYTHONPATH`,
Python 3.12 and explicit dependencies. Optional `SVOD_TRANSITION_ARTIFACTS` retains
the synthetic installed store and `verification.json` outside pytest cleanup.
Wheel tests build/extract the actual package and verify all three shipped
resources; bundled tests verify manifest/discovery. Successful local combination
is not permission to integrate Git history, publish or migrate live stores.

The fixture deliberately returns 1 for validate/summaries because four outcomes
remain unknown, with no structural errors. Title confirmation exits 0; absent
proof refuses with 2. The historical title result is retained in a sourced note,
not imported as current confirmation. Scope is five parent-linked records (four
done, one open); orphan is outside, explicitly unresolved/not adopted. All three
explicit criteria are mapped, initially unconfirmed; composite author/title and
retention remain unconfirmed after the narrow fresh fixture verification.

Final report shape:

```text
engine: source/ref/version/import path, bundled/shared, installation checks
profile: unchanged OR separately authorized delta, gates/binds, stale approvals
scope: selected roots + inventory; converted / excluded(reason+permission) / remaining
criteria: mapped / proposed / conflicting / unconfirmed (+ evidence sources)
outcomes: sourced historical/current results / unknown
checks: exact commands, return codes, actual artifacts and repeat comparisons
blockers: exact records and missing decisions/capabilities
completion: partial OR full selected scope; unexecuted integration listed separately
```
