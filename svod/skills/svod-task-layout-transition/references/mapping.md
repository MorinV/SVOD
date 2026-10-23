# Finite mapping worksheet

Write this worksheet in authorized transition output, not the installed skill.
It is an audit artifact for this move, not an engine registry or path alias service.

## Destination rules

| Kind / owner | Destination |
|---|---|
| project | `work/projects/P` |
| feature owned by project P | `work/projects/P/features/F` |
| standalone feature | `work/features/F` |
| task owned by project P | `work/projects/P/tasks/T` |
| research owned by project P | `work/projects/P/research/R` |
| task owned by project feature F | `work/projects/P/features/F/tasks/T` |
| research owned by project feature F | `work/projects/P/features/F/research/R` |
| task owned by standalone feature F | `work/features/F/tasks/T` |
| research owned by standalone feature F | `work/features/F/research/R` |
| hotfix | `work/hotfix/H` |
| task without project/feature owner | `work/headless/tasks/T` |
| research without project/feature owner | `work/headless/research/R` |

`parent` is the canonical containment owner (project or feature), or empty.
Hotfix remains at its dedicated root; preserve an applicable ownership relationship
only as supported by the selected profile. `cause` and research `leads_to` are
provenance; neither changes the containment path. A new research from research is
a peer under the appropriate project/feature or headless root, never its child.

## Required per-record row

- Original and destination canonical store-relative paths, kind and status.
- Ownership source and resolved parent; unresolved conflicts block that row.
- All current incoming/outgoing references, including plan nodes, criterion owners,
  leads_to, knowledge links and local instructions; external references separately.
- Every record-relative file with size/hash, including hidden/untracked material;
  record original approval.yaml bytes/hash and work.yaml bytes/hash explicitly.
- Exact mutable live files and fields, old/new values and why each changes.
- Preserved historical artifacts and their old path references; never rewrite an
  acceptance/evidence history merely to remove a legacy string.
- Approval-bound changes and observed drift; no rewritten hashes or new consent.
- Collision check result, copy verification, live verification (if authorized).

## Worked mapping (illustrative, not an automatic script)

| Old | Evidence | New |
|---|---|---|
| `work/projects/shop` | project card | `work/projects/shop` |
| `work/features/login` | parent shop | `work/projects/shop/features/login` |
| `work/tasks/form` | parent login | `work/projects/shop/features/login/tasks/form` |
| `work/research/auth` | parent login | `work/projects/shop/features/login/research/auth` |
| `work/tasks/incident` | kind hotfix | `work/hotfix/incident` |
| `work/tasks/tooling` | no owner | `work/headless/tasks/tooling` |
| `work/research/options` | no owner | `work/headless/research/options` |

For a research with outcome task and leads_to form, update the live leads_to to
`work/projects/shop/features/login/tasks/form`. Do not set form's parent to the
research. Change the project plan's feature link and the feature plan's task link;
retain stable node/criterion IDs. Do not duplicate the task in both plans.

## Verification ledger

Compute sets, do not estimate coverage: source records = mapped records;
destination records = unique mapped destinations; no record appears twice.
Track done, archived and Git-untracked records explicitly. Compare all immutable
record-relative files byte-for-byte after applying the path map; compare every
approval.yaml and work.yaml unchanged. List each mutable exception with reviewed
diff and every observed approval drift. Reconcile again with no writes: zero new
moves, duplicate records, history changes or changed worktree names.

Native checks may correctly report unanswered questions, missing checks or stale
approvals. Report those as such; do not mark unfinished work PASS or rewrite its
status to make verification green. Before claiming completion, all structural
failures, collisions and unaccounted files must be resolved or explicitly left as
blockers, and every authorized record must be covered.
