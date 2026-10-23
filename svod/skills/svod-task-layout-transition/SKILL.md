---
name: svod-task-layout-transition
description: Move all SVOD records to nested work paths safely.
---

# Transition an existing store to nested work paths

## When to use

Use only for an explicitly authorized store-layout transition, including done,
archived and Git-untracked records. This is a bounded, agent-led move, not an
automatic engine migration or a general legacy-path registry. Read the matching
source's layout documentation and `references/mapping.md` inside this skill directory.

## Prerequisites and discovery

- Read the store's AGENTS.md, contract, svod.yaml, local profile and next step via
  `svod status <record>`. `svod active` is not a complete inventory.
- Identify the actual launcher, interpreter, imported engine, selected source/ref
  and hooks. Verify nested layout support before writes; do not assume an engine
  update has changed local pipeline roots, placement or outcome gates.
- Separate permission to install the selected engine, change local policy and move
  the selected store's content. Do not change other installations or personal
  agent runtimes. Use the existing bundled/shared installation mode.
- In bundled stores this guide is `.svod/skills/svod-task-layout-transition/`;
  in source/shared installations it is the package's
  `svod/skills/svod-task-layout-transition/`. Agent setup picks a whole skills
  directory; store-local skills may mask it. Read the explicit package path rather
  than replacing local skills. Installed resources can be read-only.

## Procedure

1. **Inventory every record before moving anything.** Walk configured roots and
   old roots on disk, not just Git-tracked files or active work. Record canonical
   old path, kind, status, parent, links, plan ownership and work.yaml association.
   Include nested and already-moved records. Identify symlinks, unsafe paths,
   missing parents, cycles and custom-provider records; stop the affected scope
   rather than following or silently dropping them.
2. **Build an explicit old → new mapping** in task-owned output using the reference.
   Resolve project/feature ownership from source evidence, not names. Research is
   a peer of task, never a container: outcome is knowledge, task or research;
   leads_to records provenance, not containment. A research-originated successor
   belongs to the appropriate project/feature or headless root, not beneath the
   research. Resolve legacy outcome: feature/hotfix with the person; never relabel
   kinds or invent ownership. Include all completed records in the mapping.
3. **Run collision preflight before writes.** Reject duplicate destinations,
   pre-existing nonmatching files/directories, overlapping move sources/targets,
   ambiguous ownership and duplicate short names used by live references. Resolve
   references to full canonical paths. Do not merge same-named records or overwrite
   a target. Present every conflict and ask; proceed only with independent,
   explicitly authorized records. Plan parent/child moves as one operation so an
   ancestor rename cannot hide or duplicate a child.
4. **Snapshot and rehearse on an isolated full copy.** Preserve untracked/ignored
   record material; omit live .git/worktree control and credentials as appropriate.
   Hash every record-relative file; keep original historical artifacts and
   approval.yaml bytes. Record mutable-file exceptions individually. Preserve
   work.yaml contents, existing worktree directories and branch names unchanged.
   Verify native commands load the intended candidate/profile, not the live store.
5. **Apply the reviewed mapping on the copy.** Move complete record directories,
   including hidden and historical files. Update current card parent, leads_to,
   live knowledge links and structured plan.yaml record/criterion-owner references
   by exact identifier mapping. Update current local profile/AGENTS/README and
   actionable instructions. Classify each reference before editing; do not run
   global string replacement over historical evidence, logs, transcripts,
   acceptance history, old plans or approval artifacts. Preserve original bytes
   of historical artifacts; keep old identifiers there as provenance.
6. **Show approval drift honestly.** Never edit approval.yaml, recompute stored
   approval hashes, forge/replay consent or call svod approve from historical chat.
   Changed bound card/plan/inputs can invalidate old approval despite identical
   approval bytes. Report drift and require a fresh human event through normal
   gates before affected work resumes. Historical PASS is not a fresh check.
7. **Verify the complete copy, then apply only with live-write authorization.**
   Reconcile inventory ↔ mapping ↔ resulting cards programmatically: equal counts,
   each original exactly once, no losses/duplicates, expected old paths absent,
   every done/archived/untracked record accounted for. Compare every preserved
   file's bytes and original approvals; account explicitly for every edited live
   file. Run `svod validate`, `svod active --all`, exact `svod status <record>` for
   each moved record, `svod plan validate <owner>` and `svod plan summary <owner>`.
   Check parent/plan agreement, research target kinds, worktree lookup and frozen
   code refusal through actual hooks on disposable worktrees. Do not touch live
   worktrees to manufacture a test. Report pre-existing incomplete gates separately
   from structural errors and new regressions.
8. **Repeat the reconciliation read-only.** An already-migrated target maps to
   itself; do not recreate legacy roots, duplicate records or replay edits. Before
   live application recheck source snapshots and destinations for concurrent
   changes; stop on drift. After authorized application read back the same targets
   and repeat byte/count/reference/native checks. Retain the finite mapping and
   evidence with this transition only, not a permanent global alias registry.

## Pitfalls and verification

- Installation alone does not move records or authorize profile replacement.
  Preserve independent/custom profiles; inspect their own provider declarations.
- Existing work.yaml, worktree and branch names are not renamed or removed.
  A new path identifier must still resolve the same worktree and enforce approvals.
- External references outside the chosen store are reported, never silently edited.
- Report selected source/ref, exact scope/counts, conflicts, changed live references,
  preserved history, drift, native results and remaining blockers. A successful
  package/distribution test proves delivery of this guide, not a live migration.
- Do not commit, push, merge, deploy or delete worktrees without separate permission.
