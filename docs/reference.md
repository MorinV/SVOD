# Svod — format reference

## Overview

- A **pipeline** is a YAML declaration of an ordered process: entry conditions, steps, a done condition.
- A **step** is one stage of the pipeline; it passes when all of its gates pass.
- A **gate** is a named check (a Python class) over a subject; it returns PASS, FAIL or UNKNOWN plus facts.
- A **store** is the directory tree rooted at `svod.yaml`, usually a git repository.
- A **subject** is one instance the pipeline is evaluated for (a change, a container directory, a document), supplied by a **provider**.
- A **position** is the result of evaluating a pipeline for one subject: marks, the next step, the code freeze, warnings, order violations.
- The engine reads `svod.yaml` at the store root, loads a **profile** (pipelines, own gates, texts) and answers `status`, `active`, `render` and `validate`; as [hooks](#hooks) of a coding agent it brings the summary and positions into the session and guards the approval and frozen code.

How to read this: every table lists the keys the validator accepts; "req" means the key is required. Anything not listed is rejected with `unknown key`. The code in `svod/` is the source of truth; `tests/profile/` is a complete working profile to copy from.

## svod.yaml

Its presence marks the store root: the CLI walks up from the working directory to the first directory holding it.

| key | req | type / default | meaning |
|---|---|---|---|
| `locale` | yes | string | locale name: core file `svod/locale/<locale>.yaml` and profile file `<profile>/locale/<locale>.yaml` |
| `profile` | yes | string | profile directory relative to the root; must exist |
| `default_branch` | no | string / `origin/main` | ref commits are counted against (`git_pushed`, available to gates as `ctx.config.default_branch`) |
| `workspaces` | no | string / none | directory relative to the root, resolved and exposed as `ctx.config.workspaces`; the core does not read it, profile gates may |
| `active_order` | no | list of strings / `[]` | pipeline names in the order of the `active` summary; every name must be a loaded pipeline |
| `render_exclude` | no | list of strings / `[]` | directories under the root where `render` does not look for markers |
| `bindings` | no | string / none | bindings file relative to the root; without it roles are neither checked nor printed |
| `local_config` | no | string / none | per-person config file relative to the root, kept out of version control; see [Local config](#local-config) |
| `approval` | no | mapping / none | how a person approves in the chat; see [Approval by a person](#approval-by-a-person) |
| `profile_config` | no | mapping / `{}` | profile settings exposed as `ctx.config.profile_config`; hooks also read optional `agent_context` controls described below |
| `workspace_gate` | no | string / none | name of a gate with a `worktrees(ctx, keys)` method (see [Writing a custom gate](#writing-a-custom-gate)); it tells the `pre-tool` hook which directories are work directories of a subject; without it that check is off |
| `main_checkout_read_only` | no | bool / `false` | the `pre-tool` hook refuses edits in the main checkout of the store repository, except paths git ignores; work goes into worktrees |
| `update_check` | no | bool / `true` | with a [copy of the engine](#vendored-copy) in the store, the session start summary says when a newer release is out, checked at most once a day; `false` turns the check off |

```yaml
locale: en
profile: profile
default_branch: origin/main
workspaces: ..
active_order: [task, note]
render_exclude: [docs-archive]
bindings: profile/bindings.yaml
local_config: .local.yaml
approval:
  phrases: [approve, "ok, go"]
  window_minutes: 10
workspace_gate: worktree
main_checkout_read_only: true
update_check: false
profile_config:
  publishing: { mode: review }
```

### Approval by a person

An approval is two acts: a person writes a phrase in the chat, then the agent records it with `approve`. The engine owns the mark file and its format; the store decides the phrases and the window.

| key | req | type / default | meaning |
|---|---|---|---|
| `phrases` | no | list of strings / `[]` | phrases that approve; the `prompt` [hook](#hooks) matches them against a whole prompt |
| `window_minutes` | no | positive int / `10` | how long a mark stays fresh |

The mark is `svod-approval.json` in the git common directory of the store (so every worktree of the store shares it, and it is never committed): `{"at": "<ISO time with offset>", "keys": [<keys named in the prompt>]}`. The prompt hook writes it from a real human answer. `approve` requires a fresh mark for the subject, ready preceding nonoptional stages and bound files not modified after the answer. It consumes only this subject's named keys, preserving other keys and the original timestamp; an unnamed mark is single-use. Do not call the internal mark writer to manufacture human consent. `approve --step <id>` selects a specific applicable approval stage; otherwise the first unsatisfied applicable approval is selected.

### Local config

The file named by `local_config` holds what differs per person. It is optional: when absent, nothing is read and the `active` summary starts with `active.no_local_config`; `init` creates it. Unknown keys and non-string values are load errors.

| key | type | meaning |
|---|---|---|
| `login` | string | the person's login: recorded by `approve` as the approver (`ctx.config.login`) |
| `email` | string | the person's email: decides own and team work in `active` (`ctx.config.email`), falls back to `git config user.email` of the store |
| `workspaces` | string | overrides `workspaces` of `svod.yaml` |
| `locale` | string | overrides `locale` of `svod.yaml` |

```yaml
login: someone
email: someone@example.com
```

Profile layout:

| path | req | content |
|---|---|---|
| `<profile>/pipelines/*.yaml` | yes | one pipeline per file; names are unique |
| `<profile>/gates/*.py` | no | gate modules with `GATES` and, optionally, `PROVIDERS`; files starting with `_` are skipped |
| `<profile>/locale/<locale>.yaml` | yes | profile texts, merged over the core locale |

## Pipeline file

| key | req | type / default | meaning |
|---|---|---|---|
| `pipeline` | yes | string | pipeline name, unique across the profile; used by `render`, `active_order`, `{pipeline}` |
| `subject` | yes | mapping | where subjects come from, see below |
| `steps` | yes | non-empty list | steps in order, see [Step](#step) |
| `header` | no | locale key / `status.header` | first line of a `status` block; facts `{id}`, `{keys}`, `{pipeline}` |
| `entry` | no | list of gate uses / `[]` | entry conditions, evaluated for every subject, see [Gate use](#gate-use) |
| `done` | no | gate use | terminal condition; when it passes the position is final; its `pending` is the next step once every step passed and it did not |
| `missing` | no | gate use | for a subject the provider did not find: when it fails, `status` reports its `text` instead of a position, see [Position rules](#position-rules) |
| `active` | no | mapping | makes the pipeline part of the `active` summary, see [Active summary](#active-summary) |
| `violations` | no | mapping / `{}` | override texts for order violations |

`subject`:

| key | req | type / default | meaning |
|---|---|---|---|
| `provider` | yes | string | provider name, see [Subject providers](#subject-providers) |
| `key_gate` | no | string | name of a `KeyGate`; recognises tracker keys in queries and texts |
| `key_params` | no | mapping / `{}` | params of the `key_gate`, validated by it; only together with `key_gate` |
| `params` | no | mapping / `{}` | provider params |

`violations`: keys are `<later step>.<earlier step>`, values are locale keys (no facts). Both ids must exist, the later step must come after the earlier one, and the earlier step must be `required: true`.

```yaml
pipeline: task
header: task.header
subject:
  provider: openspec_change
  key_gate: ticket
  params: { containers: [projects], ignore_fields: [epic] }
active:
  in_progress: { gate: progress, fact: ahead }
entry:
  - { gate: doc_type, params: { type: design, scope: container }, when: container, severity: block, text: task.entry.no_design }
done: { gate: archived, text: task.done }
steps:
  - id: spec
    required: true
    text: task.step.spec
    gates: [ { gate: artifact, params: { glob: "specs/**/spec.md" }, label: mark.spec } ]
  - id: verify
    text: task.step.verify
    gates: [ { gate: artifact, params: { path: report.md }, label: mark.report } ]
violations:
  verify.spec: task.violation.verify_spec
```

## Step

| key | req | type / default | meaning |
|---|---|---|---|
| `id` | yes | string matching `^[a-z][a-z0-9_-]*$` | unique within the pipeline; used in violations and `{step}` |
| `title` | no | locale key / the `id` | name of the step in the rendered documentation |
| `text` | see below | locale key | next-step text when no failing gate has its own `text` |
| `gates` | no | list of gate uses / `[]` | the step passes when there is at least one gate and all pass |
| `entry` | no | list of gate uses / `[]` | step entry conditions, evaluated only when the position is at this step |
| `required` | no | bool / `false` | a later passed step while this one is not passed is an order violation |
| `optional` | no | bool / `false` | the step only shows marks; it never becomes the position and never takes part in violations |
| `blocks_code` | no | bool / `false` | while the position is at or before this step, `status` prints the code freeze line |
| `role` | no | string | who does the step; resolved to a skill by the [bindings file](#bindings-file) |
| `when` | no | identifier matching the step-id syntax | apply the entire step only when `subject.attrs[when]` is truthy; missing means false |

Constraints:

- `optional` excludes `required` and `blocks_code`.
- `text` is required unless the step has gates and every gate has its own `text`.
- A step without gates never passes: it is the last mile outside the store.

```yaml
- id: approve
  title: task.title.approve
  required: true
  blocks_code: true
  text: task.step.approve
  gates: [ { gate: approval, params: { marker: approved, file: meta.yaml }, label: mark.approved } ]
- id: close
  role: closer
  text: project.step.close
  entry:
    - { gate: git_pushed, severity: warn, text: project.entry.store_ahead }
```

## Gate use

A gate use is a mapping naming a gate. The accepted keys depend on where it stands.

| key | pipeline `entry`, step `entry` | step `gates` | `done`, `missing` | `active.in_progress` | type | meaning |
|---|---|---|---|---|---|---|
| `gate` | req | req | req | req | string | gate name from the registry (core or profile) |
| `params` | opt | opt | opt | opt | mapping / `{}` | gate params, validated by the gate |
| `text` | req | opt | req | — | locale key | text shown when this gate decides the position; facts are the gate's facts (for `missing` also `{id}`, `{keys}`, `{pipeline}`) |
| `pending` | — | — | opt, `done` only | — | locale key | next-step text when every step passed and `done` did not; facts are those of the done gate |
| `severity` | req | — | — | — | `block` or `warn` | effect of a failed entry gate |
| `when` | opt | opt | — | — | subject attribute identifier | the gate applies only when the attribute is truthy; not an expression language |
| `purpose` | — | opt | — | — | identifier | semantic approval selection, e.g. `contract` or `result`, independent of stage name |
| `label` | — | opt | — | — | locale key | makes the gate a mark in `status`; facts are the gate's facts |
| `fact` | — | — | — | opt | fact name | "in progress" also needs this fact to be a number > 0 |

`active.in_progress` may also be a bare gate name: `in_progress: progress`.

**Variants by reason.** When the facts of the gate that decides a text carry a string `reason` and the locale has the key `<text>_<reason>`, that key is rendered instead of `<text>`; otherwise `<text>` is. This applies to the step line (in `status` and `active`) and to warnings. Example: `task.step.approve` is the text for `reason: missing`, `task.step.approve_drift` for `drift`.

`when` names a key of `subject.attrs` (see [Subject providers](#subject-providers)); the rendered documentation phrases it with the locale key `doc.attr.<name>` when present, else with `doc.when`.

Every gate use in `entry`, `done` and `gates` without a `label` must render its description (`missing` is not part of the rendered documentation and needs none) (`describe`, see [Writing a custom gate](#writing-a-custom-gate)); `validate` fails otherwise.

```yaml
entry:
  - { gate: doc_type, params: { type: test-strategy, scope: container }, when: container, severity: warn, text: task.entry.no_pyramid }
done: { gate: field, params: { name: status, equals: closed }, text: note.done }
steps:
  - id: spec
    text: task.step.spec
    gates:
      - { gate: artifact, params: { path: design.md }, label: mark.design, text: task.step.design }
```

## Position rules

`status` and `active` both call one function, `position()`:

An archived subject with a native `archived` terminal gate is historical: the engine reports that terminal outcome without executing live entry/step gates or presenting them as passing. Otherwise the rules below apply, omitting inapplicable steps and gate uses consistently with approval and code guards.

1. **Entry** — the pipeline `entry` gates are evaluated for every subject, found or not, skipping those whose `when` attribute is falsy. The first failed `block` gate blocks the position; failed `warn` gates are printed as warnings after the step line. An entry gate that is UNKNOWN is printed as `status.unknown` instead of its warning; a blocking UNKNOWN still blocks, with no text of its own.
2. **Marks** — when the subject exists, every step gate with a `label` (optional steps included) is shown as a mark: the gate's `display` when set, else `status.mark.<pass|fail|unknown>` with the rendered label.
3. **Done** — evaluated after the step gates. When it passes, its `text` becomes the step line (inside `status.next_step`) and nothing else is computed; entry warnings and UNKNOWNs are still printed. A done gate that is UNKNOWN is reported and evaluation goes on.
4. **Steps** — only non-optional steps count. A step passes when it has gates and all of them pass; FAIL and UNKNOWN both mean not passed. Every UNKNOWN gate of a non-optional step is reported.
5. **Violations** — a passed step preceded by a `required` step that did not pass; one line per pair, text from `violations` or `status.violation` with `{later}`, `{earlier}`. Computed also when the entry blocks; never for a missing subject.
6. **Blocked** — with a blocking entry there is no current step: the entry `text` is printed as is (not wrapped in `status.next_step`); if the pipeline has any `blocks_code` step and the subject exists, `status.do_not_touch_blocked` is printed.
7. **Current step** — the first non-optional step that did not pass. Its step `entry` is evaluated now (same rules as 1). Text: a failed blocking step entry's `text`; else the `text` of the first gate that did not pass, when it has one; else the step `text`. Facts come from that gate (or entry). All steps passed and done did not: the `pending` text of done when declared, else no step line.
8. **Code freeze** — when the subject exists and a `blocks_code` step lies at or after the current step, `status.do_not_touch` is printed with the facts of that step's first open gate and `{step}` = its id.
9. **Step skill** — printed after the step line when the current step has a `role`, bindings are configured and the text does not come from a blocking entry.
10. **Errors while reading** — an `OSError` raised by a gate becomes UNKNOWN with the error as reason.
11. **Missing subject** — a subject the provider did not find (`exists: false`, see [Subject providers](#subject-providers)). When the pipeline declares `missing` and that gate FAILs, `status` prints its `text` on stderr instead of a position — only when the query shows no position at all: another pipeline presenting the same query is the answer; on PASS or UNKNOWN the position is computed. A position of a missing subject never has order violations (rule 5) nor the code freeze (rules 6 and 8): nothing has been done for it yet, so there is no order to break and no plan to wait for.

Output order of a `status` block: header, the checkout line (`status.checkout`, for a subject of another checkout), marks, blank line, step line, skill line, code freeze, UNKNOWN lines, warnings, violations.

## Core gates

Params marked "req" are required; unknown params and wrong types are load errors. Facts are available as `{name}` in the `text` and `label` of the gate use.

### `exists`

No params. PASS when the provider found the subject (`subject.exists`), else FAIL. No facts.

### `artifact`

| param | req | type / default | meaning |
|---|---|---|---|
| `path` | one of `path`, `glob` | string | path under the subject directory |
| `glob` | one of `path`, `glob` | string | glob under the subject directory (`**` allowed) |
| `min` | no | positive int / `1` | minimum number of matches; with `path` only `1` is accepted |

Counts the matches under the subject path (0 when the subject does not exist or its path is not a directory; `path` counts 0 or 1). PASS when the count is at least `min`, else FAIL. Facts: `count`.

### `approval`

| param | req | type | meaning |
|---|---|---|---|
| `marker` | yes | string | top-level field of the YAML file: the approval date |
| `file` | yes | string | YAML file under the subject directory |
| `bind` | no | non-empty list of globs | files under the subject the approval is tied to |
| `ignore` | no, only with `bind` | non-empty list of regular expressions | lines of the bound files that do not change their version |
| `strip` | no, only with `bind` | non-empty list of regular expressions | fragments cut out of every line of the bound files before hashing |

Next to `marker` live `<marker>_by` (who approved) and `<marker>_sha` (sha256 over the relative path and content of every file matched by `bind`, in path order); `approve` writes all three. With `ignore` or `strip` the content of each file is normalized before hashing, line by line: a blank (whitespace-only) line or a line matched by any `ignore` expression (`re.search` on the line as written, anchor with `^` yourself) is dropped; then every `strip` expression, in the declared order, has its matches removed (`re.sub`). A line `strip` changed is tidied: runs of `,` and `;` shrink to one, separators before `)` and empty parentheses go, whitespace before `, ; . :` goes, whitespace runs shrink to one space, separators (`, ; . :`, en and em dash) are trimmed from its start and, except the full stop, from its end, and its original indent is kept; a line left with nothing but whitespace and separators is dropped like a blank one. The kept lines are joined by `\n`. Without `ignore` and `strip` the digest is over the raw bytes, as before.

Without `bind`: PASS when the marker is non-empty after stripping. With `bind`: PASS only when all three fields are set and `<marker>_sha` equals the digest of the files now under any accepted rules: `ignore` with `strip`, then — with `strip` declared — `ignore` alone, then — with either declared — the raw content. `approve` records only the first; the others keep approvals recorded before `strip` or `ignore` was declared valid while the files do not change, which is transitional and goes away once no approval in the store carries such a digest. FAIL carries the fact `reason`: `missing` (no marker, no file or not a mapping), `legacy` (a marker without the approver or the digest), `drift` (the bound files changed after the approval). UNKNOWN when the file is not valid YAML. Facts: `value` and `date` (the marker), `by`, `marker`, `reason` on FAIL. Texts may have variants per reason, see [Gate use](#gate-use).

### `field`

| param | req | type | meaning |
|---|---|---|---|
| `name` | yes | string | frontmatter field of the subject (`attrs.frontmatter`) |
| `equals` | exactly one condition | any, compared as a string | PASS when the field is non-empty and equals it |
| `not_equals` | exactly one condition | any, compared as a string | PASS when the field is non-empty and differs from it |
| `present` | exactly one condition | bool | PASS when "the field is non-empty" equals the value |
| `date_not_past` | exactly one condition | bool | the field is an ISO date; PASS when "date ≥ today" equals the value; not a date → FAIL |

An empty or missing field never equals and never differs. Never UNKNOWN. Facts: `value` (the stripped field or empty).

### `doc_type`

| param | req | type / default | meaning |
|---|---|---|---|
| `type` | yes | string | frontmatter `type` to look for |
| `scope` | no | `subject` or `container` / `subject` | search the subject tree, or the directory named by `attrs.container` |

PASS when some `*.md` under the scope (recursively; a file subject is searched itself) has frontmatter `type` equal to `type`. FAIL when the scope does not exist, including `container` scope without `attrs.container`. No facts.

### `archived`

No params. PASS when the provider marked the subject archived. No facts.

### `git_pushed`

| param | req | type / default | meaning |
|---|---|---|---|
| `repo` | no | string / the store root | repository directory relative to the store root |

Runs `git rev-list --count <default_branch>..HEAD`. PASS when the count is 0, FAIL otherwise, UNKNOWN when git fails or times out (reason: the git error). Facts: `count` (absent when UNKNOWN).

## Subject providers

A subject carries `id`, `path`, `exists`, `archived`, `keys` (tracker keys found by `key_gate`), `author` (email and name of the last commit touching the path, read from git on first use — a provider passes `author_of`, a reader such as `svod.providers.base.author_of(ctx, rel)`), `attrs` and `checkout` (the root of the other checkout it was read in, none for the root itself). Attributes usable in `when`: `container`, `frontmatter`.

A query given to `status` (and `approve`) is resolved across all pipelines in three phases; the first phase that finds anything wins:

1. **exact name** — `match_exact` of every provider. More than one match is an ambiguity error.
2. **tracker key** — for every pipeline with a `key_gate` that recognises a key in the query, `match_key`. Every match is shown.
3. **substring** — `match_substring` of every provider. More than one match is an ambiguity error.

Names are compared after Unicode NFC normalisation and case folding. Nothing found: `status.not_found`.

**Other checkouts.** Every phase runs in the root and in each other checkout of the store repository that differs from `default_branch` (the same checkouts as in the [active summary](#active-summary)), with a context rooted in that checkout. A subject read in a checkout counts only when the checkout changed a path grounding it — the provider's `evidence(ctx, subject)`: the subject path by default; for a not-found subject of `openspec_change`, its container. Such a subject gets `checkout` and replaces the root's subject with the same pipeline and `id` (the checkout is newer; among checkouts the first in `git worktree list` order wins). A found subject of the root grounded in paths a checkout changed, but not yielded by it, was moved or removed there and is left out. A not-found subject is dropped once its pipeline found any subject. `status` evaluates such a subject in its checkout and prints `status.checkout` under the header; `approve` writes into the checkout.

For the active summary every provider also answers `touched(ctx, paths)`: the subjects with a file among the given paths (relative to the root, POSIX form, compared in NFC). The default enumerates every subject; `openspec_change` reads only the changed change directories.

### `openspec_change`

| param | req | type / default | meaning |
|---|---|---|---|
| `root` | no | string / `openspec/changes` | directory of changes, relative to the store root |
| `archive` | no | string / `archive` | subdirectory of `root` holding archived changes |
| `containers` | no | list / `[]` | container roots used to find the container of a change |
| `ignore_fields` | no | list / `[]` | fields of `.openspec.yaml` whose lines are not searched for keys |

Subjects: every directory under `root` except `archive` (active), then every directory under `root/archive` (archived). `id` is the directory name. Keys come from the lines of `.openspec.yaml` (minus ignored fields) and from `## ` headings of `tasks.md`. Matches by exact directory name (active and archived) and by key: all changes carrying the key, or, when none does, one not-found subject (`exists: false`, `id` = the key) so that the pipeline can say "propose a change" or, with `missing`, that nothing is known about the key. Never by substring. Attrs: `container` — the first container (in root order, then by name) whose documents mention a key of the change, or none.

### `container`

| param | req | type | meaning |
|---|---|---|---|
| `roots` | yes | non-empty list of strings | directories whose direct subdirectories are containers |
| `head_type` | no | string | frontmatter `type` of the head document at the top level of a container |

Subjects: every subdirectory of every root; `id` is its path relative to the store root. Keys come from all `*.md` inside. Archived when the head document has `status: archived`. Matches by exact and by substring directory name, never by key. Attrs: `container` (its own relative path), `frontmatter` (the head document's frontmatter, empty without `head_type` or head).

### `frontmatter_doc`

| param | req | type / default | meaning |
|---|---|---|---|
| `glob` | yes | string | glob relative to the store root |
| `exclude` | no | list / `[]` | file names to skip |

Subjects: every file under the glob that has frontmatter; `id` is the file stem, `path` the file. Keys come from the file text. Archived when `status: archived`. Matches by exact and by substring stem. Attrs: `frontmatter`.

```yaml
subject:
  provider: frontmatter_doc
  params: { glob: "notes/*.md", exclude: [README.md] }
```

## Active summary

`active` lists open subjects of every pipeline that has an `active` block, pipelines ordered by `active_order` in `svod.yaml`, the rest by name.

| key | req | type / default | meaning |
|---|---|---|---|
| `in_progress` | no | gate use or gate name | when it passes (and its `fact`, if given, is a number > 0) the subject is "in progress" |
| `item` | no | locale key / `active.item` | line of one subject; facts `{id}`, `{keys}` (or `active.no_keys`), `{pipeline}`, `{step}` (the step line), `{frontmatter}` |
| `headings` | no | mapping of group to locale key | overrides of the group headings |

Groups, always in this order:

| group | who | default heading |
|---|---|---|
| `mine_active` | own subject, `in_progress` passed | `active.mine_active` |
| `mine_idle` | own subject otherwise (always, without `in_progress`) | `active.mine_idle` |
| `theirs` | the last commit on the subject is by another email than `git config user.email` | `active.theirs` |
| `theirs_collapsed` | `theirs` without `--all`: one line, facts `{count}`, `{who}` (`active.author_count` per author) | `active.theirs_collapsed` |
| `worktree` | changed in another checkout of the store repository: one block per checkout, fact `{dir}` (its directory name), shown before the other groups | `active.worktree` |

Other checkouts are the entries of `git worktree list` of the root, except the root itself. A checkout takes part when it differs from `default_branch`: commits since the merge base, uncommitted changes or untracked files that are not ignored. Its subjects are those the provider's `touched` finds among the changed paths; they are evaluated with a context whose root is that checkout (configuration, locale and pipelines stay those of the root). Such a subject is shown under its checkout only: the root's groups skip every subject id a checkout changed, archived or done ones included. Owners are not asked: a checkout on this machine is the person's own.

Archived subjects and subjects whose `done` passes are skipped. A subject without commits counts as own. The person's email comes from the local config, else from `git config user.email`; without either every subject counts as own and, when there is anything to show, the summary starts with `active.no_identity`. A configured but missing local config puts `active.no_local_config` first. Empty groups are omitted; blocks are separated by a blank line. Roles are not resolved here.

```yaml
active:
  in_progress: { gate: progress, fact: ahead }
  item: note.active.item
  headings:
    mine_idle: note.active.mine
    theirs_collapsed: note.active.theirs_collapsed
```

## Bindings file

Maps step roles to skills. Referenced by `bindings` in `svod.yaml`.

| key | req | type | meaning |
|---|---|---|---|
| `skill_path` | when a rule names a non-external skill | string containing `{skill}` | where a skill file lives, relative to the store root |
| `probe` | when a rule has `when` | mapping | gate whose fact gives the directories the conditions are checked in |
| `roles` | no | mapping of role to non-empty list of rules | rules per role, in order |

`probe`:

| key | req | type | meaning |
|---|---|---|---|
| `gate` | yes | string | gate name from the registry |
| `params` | no | mapping | gate params |
| `fact` | yes | string | fact holding directories: a list of paths (labelled by base name) or a mapping label → path |

Rule:

| key | req | type / default | meaning |
|---|---|---|---|
| `skill` | yes | string or `null` | skill name; `null` means the role is known but has no skill yet |
| `when` | no | mapping | condition on a directory; only `has_file` (file name that must exist in the directory) |
| `external` | no | bool / `false` | the skill lives outside the store; its file is not checked |

Resolution for the current step's role: if any rule of the role has `when`, the probe gate is evaluated; when it passes, for each directory the first rule that matches wins (a rule without `when` always matches). Without directories, the first rule without `when` is taken. The `status` line:

- every directory resolves to no skill → `status.skill_unassigned` with `{role}`;
- one skill for all → `status.skill` with `{skill}`;
- otherwise → `status.skill` with a list of `status.skill_item` (`{dir}`, `{skill}`, `status.skill_none` for none).

`validate` checks that every step `role` of every pipeline is described in `roles` and that every non-null, non-external skill exists at `skill_path`.

```yaml
skill_path: "skills/{skill}/SKILL.md"
probe: { gate: dirs, fact: paths }
roles:
  builder:
    - { when: { has_file: pyproject.toml }, skill: impl-py }
    - { when: { has_file: go.mod }, skill: null }
  checker:
    - { skill: ext-check, external: true }
```

## Locale

- Core strings: `svod/locale/<locale>.yaml` inside the package (`en`, `ru`). Profile strings: `<profile>/locale/<locale>.yaml`.
- Files are nested mappings flattened to dotted keys (`status.mark.pass`); every leaf must be a string and a valid `str.format` template.
- The profile file is merged over the core file: a profile may override any core key.
- Placeholders `{name}` are filled with facts by `str.format_map`; `{frontmatter[status]}` works for mappings. A missing placeholder is an error when the text is rendered.
- Load fails when the core file lacks a core key, or when the merged locale lacks a key a pipeline refers to (`header`, `text`, `label`, `title`, `violations` values, `active.item`, `active.headings`).
- Keys looked up by name at run time: `gate.<gate name>` (default `describe`), `doc.attr.<attribute>` (optional wording of `when`) and `<text>_<reason>` (optional variants by reason, see [Gate use](#gate-use)). Keys used inside profile gates are not checked at load time.
- `SVOD_LOCALE` (default `en`) chooses the core locale used before `svod.yaml` is read: for the "not a store root" error. Load errors are reported in the configured locale when `svod.yaml` is readable.

Core keys (all required in every core locale file):

| keys | facts |
|---|---|
| `error.not_root`, `error.load` | — |
| `validate.ok`, `validate.failed` | `{count}` |
| `status.header` | `{id}`, `{keys}`, `{pipeline}` |
| `status.checkout` | `{dir}` |
| `status.next_step` | `{step}` |
| `status.do_not_touch`, `status.do_not_touch_blocked` | facts of the open gate, `{step}` |
| `status.unknown` | `{reason}`, `{gate}` |
| `status.skill` | `{skill}` |
| `status.skill_unassigned` | `{role}` |
| `status.skill_item` | `{dir}`, `{skill}` |
| `status.skill_none`, `status.violations`, `status.ambiguous` | — |
| `status.violation_item` | `{text}` |
| `status.violation` | `{later}`, `{earlier}` |
| `status.not_found` | `{query}` |
| `status.candidate` | `{id}` |
| `status.mark.pass`, `status.mark.fail`, `status.mark.unknown` | `{label}` |
| `active.mine_active`, `active.mine_idle`, `active.theirs`, `active.no_keys`, `active.hook_tail`, `active.no_identity` | — |
| `active.no_local_config` | `{file}` |
| `active.worktree` | `{dir}` |
| `active.theirs_collapsed` | `{count}`, `{who}` |
| `active.author_count` | `{author}`, `{count}` |
| `active.item` | `{id}`, `{keys}`, `{pipeline}`, `{step}`, `{frontmatter}` |
| `doc.generated` | `{source}`, `{command}` |
| `doc.done_text`, `doc.pending_text` | `{text}` |
| `doc.when` | `{when}` |
| `doc.entry`, `doc.done`, `doc.blocks_code`, `doc.legend.required`, `doc.legend.optional`, `doc.legend.frozen`, `doc.head.step`, `doc.head.gates`, `doc.head.role`, `doc.head.next`, `doc.required`, `doc.optional`, `doc.severity.block`, `doc.severity.warn`, `doc.no_gates`, `doc.none`, `doc.placeholder` | — |
| `render.unknown` | `{name}` |
| `render.written`, `render.current` | `{path}` |
| `render.no_markers` | `{name}`, `{marker}` |
| `hook.engine_broken` | `{reason}` |
| `hook.position_head`, `hook.position_tail` | — |
| `hook.approval_marked` | `{minutes}` |
| `hook.approval_joiners` | — (words joining keys after an approval phrase, separated by spaces) |
| `hook.deny_approval` | `{fields}`, `{file}` |
| `hook.deny_plan` | `{keys}`, `{text}` |
| `hook.deny_main` | `{main}` |
| `init.written`, `init.exists` | `{path}` |
| `init.not_configured` | `{field}` |
| `init.need_login`, `init.prompt_login` | — |
| `init.prompt_email` | `{default}` |
| `approve.done` | `{file}`, `{marker}`, `{date}`, `{by}`, `{sha}` |
| `approve.no_mark`, `approve.no_approver` | — |
| `approve.foreign_key` | `{mark_keys}`, `{keys}` |
| `approve.no_gate` | `{query}` |
| `approve.no_step`, `approve.step_no_gate`, `approve.changed_after_mark` | `{query}`, `{step}` |
| `approve.not_ready` | `{query}`, `{step}`, `{pending}` |
| `gate.exists`, `gate.archived`, `gate.git_pushed` | — |
| `gate.artifact_path` | `{path}` |
| `gate.artifact_glob` | `{glob}`, `{min}` |
| `gate.approval` | `{marker}`, `{file}` |
| `gate.approval_bound` | `{marker}`, `{file}`, `{bind}` |
| `gate.field_equals`, `gate.field_not_equals` | `{name}`, `{value}` |
| `gate.field_present`, `gate.field_absent`, `gate.field_date_not_past`, `gate.field_date_past` | `{name}` |
| `gate.doc_type`, `gate.doc_type_container` | `{type}` |
| `gate.git_pushed_repo` | `{repo}` |
| `update.exists`, `update.missing`, `update.manual`, `update.manual_none`, `update.invalid`, `update.next` | — |
| `update.fetch_failed` | `{source}`, `{reason}` |
| `update.no_tags` | `{source}` |
| `update.clone_failed` | `{ref}`, `{source}`, `{reason}` |
| `update.not_svod` | `{ref}`, `{source}` |
| `update.installed`, `update.updated` | `{old}`, `{new}`, `{ref}`, `{path}` |
| `update.changelog` | `{old}`, `{new}` |
| `update.available` | `{latest}`, `{current}` |
| `migrate.version` | `{version}` |
| `migrate.none` | `{old}`, `{new}` |
| `migrate.failed` | `{version}`, `{reason}` |
| `migrate.bad_version` | `{version}` |
| `migrate.renamed_key` | `{old}`, `{new}`, `{file}` |
| `migrate.renamed_file` | `{old}`, `{new}` |

## Render

`render <pipeline>` generates a documentation block from the declaration. Blocks live in markdown files between two marker lines:

```markdown
<!-- pipeline:task:begin -->
<!-- pipeline:task:end -->
```

- Without `--write` the block (with markers) is printed. With `--write` the content between the markers is replaced in every `*.md` under the store root, skipping hidden directories and the `render_exclude` directories; each file is reported as `render.written` or `render.current`. No file with the markers: `render.no_markers`, exit code 1.
- Content: the `doc.generated` line naming the source file and the command, a mermaid `flowchart LR` (entry node, one node per step, done node), a legend of the styles used, a table with the columns step, gates, role, next step; the done row names `doc.pending_text` before `doc.done_text` when done has `pending`.
- Step node: `title` (or `id`), `doc.blocks_code` as a second line. Styles: `required` — bold border, `optional` — dashed, `blocks_code` — red border.
- Gate captions: the `label` when set, else the gate's `describe`; entry gates also get their `when` wording and severity. Placeholders in texts are shown as `doc.placeholder`.
- `document.stale_blocks()` lists blocks whose content differs from a fresh rendering or that name an unknown pipeline — for a linter of the store.

## Writing a custom gate

A profile gate is a class in `<profile>/gates/<module>.py`, registered by the module-level mapping `GATES = {name: cls}`. The key must equal `cls.name`; a name already taken by a core gate or another module, a non-`Gate` value or an import failure is a load error. Modules import the engine as `svod.*`.

`Gate` (in `svod.gates`):

| member | meaning |
|---|---|
| `name` | registry name used in pipelines |
| `PARAMS` | frozenset of accepted param names; others are rejected |
| `REQUIRED` | frozenset of required param names |
| `check(self)` | validates `self.params` values; raise `ParamError`; `require_type(key, kind, label)` helps |
| `evaluate(self, ctx, subject)` | returns a `Result` |
| `describe(self, params, locale)` | what must hold, for the documentation; default: locale key `gate.<name>` formatted with the params |

`ctx` carries `config` (`root`, `default_branch`, `workspaces`, …), `locale` (may be `None` in tests), `today`, `bindings`, `root`, `pipelines` — loaded pipelines by name, for a gate that consults another pipeline (for example its subject provider as `ctx.pipelines[name].subject.impl`) — and `cache`, the memory of one run shared by every context rooted in another checkout: `cache.git(cwd, *args)` runs git once per directory and arguments, `cache.prefetch([(cwd, args), …])` runs the calls not known yet in parallel (a pool of `GIT_WORKERS` threads), `cache.value(key, compute)` keeps a value computed from files. Nothing is written to disk: hooks and sessions run in parallel. A gate reads git through `ctx.cache`, not `run_git`; `worktree_list` and `changed_paths` of `svod.git` take it as `run`.

`Result(status, facts={}, display=None, reason=None)`: `status` is `Status.PASS`, `Status.FAIL` or `Status.UNKNOWN`; `facts` fill texts; `display` replaces the standard mark line; `reason` is shown for UNKNOWN. Helpers: `verdict(ok, **facts)` and `unknown(reason, **facts)`.

**Workspace gate.** The gate named by `workspace_gate` in `svod.yaml` must be instantiable without params and implement `worktrees(ctx, keys)`: `(pairs, errors)` where every pair is `(directory, repository name)` of a work directory of the keys and `errors` lists git failures. The `pre-tool` hook only uses the directory. `examples/task/profile/gates/git_work.py` has one.

`KeyGate(Gate)` additionally implements `match(query)` (the key named by a query, or `None`) and `find(text)` (set of keys in a text); it is used as `subject.key_gate`. Its default `evaluate` passes when the subject has keys, with fact `keys`.

```python
from svod.errors import ParamError
from svod.gates import Gate, verdict

PARAM_MAX = "max"
README = "README.md"
ENCODING = "utf-8"


class ShortReadmeGate(Gate):
    """Passes when README.md of the subject has at most max lines; facts.lines."""

    name = "short_readme"
    PARAMS = frozenset({PARAM_MAX})
    REQUIRED = PARAMS

    def check(self):
        """max is a positive integer."""
        value = self.params[PARAM_MAX]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ParamError(f"{self.name}: {PARAM_MAX} must be a positive integer")

    def evaluate(self, ctx, subject):
        """Count the lines of the README."""
        path = subject.path / README if subject.exists and subject.path else None
        if path is None or not path.is_file():
            return verdict(False, lines=0)
        lines = len(path.read_text(encoding=ENCODING).splitlines())
        return verdict(lines <= self.params[PARAM_MAX], lines=lines)


GATES = {ShortReadmeGate.name: ShortReadmeGate}
```

```yaml
# <profile>/locale/en.yaml
gate:
  short_readme: "README.md has at most {max} lines"
```

**Providers of the profile.** A gate module may also declare `PROVIDERS = {name: cls}`: subject providers joining the core ones under the same rules (the key equals `cls.name`, a taken name is a load error). A provider subclasses `svod.providers.Provider`, is built as `cls(params, key_gate)` (`key_gate` is the pipeline's `KeyGate` instance or `None`; `keys_in(text)` uses it) and declares `name`, `PARAMS`, `REQUIRED`, `check()` like a gate. It implements `enumerate(ctx)` (every subject, for `active`) and any of `match_exact(query, ctx)`, `match_key(key, ctx)`, `match_substring(query, ctx)` (empty by default); `touched(ctx, paths)` and `evidence(ctx, subject)` have defaults by `subject.path` (see [Subject providers](#subject-providers)). `ctx.pipelines` lets it consult another pipeline, for example to skip keys that already have a change.

## CLI

`svod [--root <dir>] <command>` (or `python3 -m svod.cli`). Without `--root` the root is the nearest directory upwards from the working directory that holds `svod.yaml`. Requires PyYAML. `--version` prints the version of the engine that runs; in a store with a [copy of the engine](#vendored-copy), that of the copy.

| command | flags | does | exit codes |
|---|---|---|---|
| `validate` | — | loads config, pipelines, gates, providers, locale, descriptions and bindings, and checks the [copy of the engine](#vendored-copy) against its `MANIFEST`; prints every error | 0 valid, 1 errors |
| `status <query>` | `--format text\|json` | position of every subject the query resolves to; JSON v1 projects captured native outcomes without re-evaluating gates, with bounded allowlisted facts and advisory `next_action`; no free-form logs, approval identity or exception text | 0 found, 2 not found, ambiguous, or only such missing subjects |
| `active` | `--all`, `--hook` | summary of open work, including subjects changed in other checkouts of the store repository; `--all` expands `theirs`; `--hook` prints SessionStart hook JSON (`hookSpecificOutput.additionalContext`, with the [update notice](#update-notice) first and `active.hook_tail` appended); prints nothing when there is neither | 0 |
| `render <pipeline>` | `--write` | prints the documentation block, or writes it between the markers | 0, 1 no markers, 2 unknown pipeline |
| `approve <query>` | `--step <id>` | records the ready selected applicable approval with date, approver and digest, consuming this subject's mark keys; refuses changed-after-answer inputs; nothing is committed | 0 recorded, 1 refused, 2 not found or ambiguous |
| `new <directory>` | `--template local\|task` | creates an absent directory from installed templates without a pre-existing store; default local, never merges or overwrites | 0 created, 1 refused |
| `local <action> <query>` | — | `prepare` diagnoses readiness, `checks` runs the chosen argv, `verify` validates the live result, `deliver` records and reads back local completion; see [local-workflow.md](local-workflow.md) | 0 success, 1 failed/refused, 2 invalid root/load/arguments |
| `hook <event>` | — | answers one agent hook event, `session-start`, `prompt` or `pre-tool`, read as JSON on stdin; see [Hooks](#hooks) | 0 always |
| `init` | `--login`, `--email`, `--force` | writes the local config; without `--login` asks at a terminal, and fails without one; the email defaults to `git config user.email`; an existing file is kept unless `--force` | 0 written, 1 exists, 2 no login or no `local_config` |
| `install` | `--from`, `--to` | puts a copy of the engine into `.svod/` of the store, see [Vendored copy](#vendored-copy); refuses when `.svod/` exists | 0 done, 1 refused or the store does not validate after it, 2 nothing fetched (the store is unchanged) |
| `update` | `--from`, `--to` | replaces the copy in `.svod/`, migrates the store, validates it with the new engine, prints the changelog between the versions and the migration notes; refuses without `.svod/` | as `install` |
| `migrate` | `--since <version>` | applies the [migrations](#migrations) of the versions after `<version>` up to the running engine and prints what they changed; `update` runs it in the new copy | 0 done, 1 a migration failed, 2 not a version |

`init`, `install`, `update` and `migrate` read `svod.yaml` at most for the locale, so they work while the store does not load. Every other command except `validate` and `hook` exits with 2 and `error.load` when the store does not load, and with 2 and `error.not_root` when no root is found. Without PyYAML the CLI exits with 2, or silently with 0 when `--hook` is given; `hook` then answers `session-start` and `prompt` with one line about the missing PyYAML and stays silent on `pre-tool`.

## Hooks

`svod hook <event>` is registered as a command hook of Claude Code or Codex (`integrations/setup-claude.sh`, `integrations/setup-codex.sh`). Both agents send the same event JSON (`hook_event_name`, `cwd`, `prompt`, `tool_name`, `tool_input`); the answer is `hookSpecificOutput` with `hookEventName` and either `additionalContext` or `permissionDecision: deny` with `permissionDecisionReason`. Nothing to say prints nothing. The exit code is always 0. A store that does not load is reported as `hook.engine_broken` in `additionalContext` instead of silence (for `pre-tool`, only for file edits).

**The store of the session** is the one holding `CLAUDE_PROJECT_DIR`, else the event `cwd`; else the store at `--root`, a fallback for sessions in a work directory outside the store. No store: silence.

Optional `profile_config.agent_context` booleans `session_summary`, `prompt_positions` and `approval_notice` default on for compatibility. Setting them to false suppresses those context outputs, not native approval marking, agent-message filtering or pre-tool protection. The local template turns them off and uses explicit per-task status; `active` remains available on request. These controls do not guarantee token savings or enforce a sandbox.

| event | agent event | does |
|---|---|---|
| `session-start` | `SessionStart` | the `active` summary, as `active --hook`, preceded by the [update notice](#update-notice) |
| `prompt` | `UserPromptSubmit` | approval mark and positions, see below; silent on messages of other agents |
| `pre-tool` | `PreToolUse` | refuses the tool call by the rules below |

`prompt`:

- **Approval.** When the prompt, as a whole, is one of `approval.phrases` (letter case ignored), optionally followed by keys joined by separators or the words of `hook.approval_joiners`, and closing `.` or `!`, the hook writes the approval mark with those keys (`svod.approval.write_mark`) and says so (`hook.approval_marked`). A phrase inside a longer text does not approve.
- **Positions.** Keys the `key_gate` of any pipeline recognises in the prompt, then exact names (the last path segment of the id, at least 8 characters, as a whole word) of open subjects, at most three queries. For each, the `status` block of every existing subject it resolves to, between `hook.position_head` and `hook.position_tail`. A key with nothing in the store adds nothing.

`pre-tool` watches `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash` and `apply_patch` (Codex; the files of the patch are read from its `*** Update File:`, `*** Add File:`, `*** Delete File:` and `*** Move to:` lines, relative to `cwd`). It refuses:

1. **Approval fields.** A file whose path ends with the `file` of an `approval` step gate of any pipeline is a metadata file; its fields are `<marker>`, `<marker>_by` and `<marker>_sha`. Refused: `Write` that changes their lines, `Edit`/`MultiEdit` whose old or new text names one, an `apply_patch` section whose changed lines name one, and a `Bash` command naming the file and a field that writes into it (`>`/`>>` to it, `sed -i`, `perl -i`, `yq -i`, `tee` to it, `cp`/`mv` onto it, a `python -c` or heredoc script holding its path as a string literal). Text: `hook.deny_approval`. Only `svod approve` writes them.
2. **Read-only main checkout.** With `main_checkout_read_only` in the `svod.yaml` of the store holding the path: a path in the first checkout of `git worktree list` of that store, not in a nested repository and not ignored by git. Text: `hook.deny_main`.
3. **Frozen code.** With `workspace_gate`: the nearest directory above the path holding `.git` is a work directory when a key gate finds a key in its name and `worktrees(ctx, {key})` of the workspace gate returns it. Each existing, not archived subject of that key (in the store and its other checkouts) is checked: the first gate of a `blocks_code` step that does not pass refuses the edit, with `hook.deny_plan` carrying its step text. A key without a subject is not refused.

Edits by `Bash` are not checked by rules 2 and 3.

## Vendored copy

A store may keep its own copy of the engine, so the whole team runs one version through git. How a team installs and updates it is in [updating.md](updating.md).

| path under the store root | content |
|---|---|
| `.svod/lib/svod/` | the engine package, locale files included |
| `.svod/skills/<name>/` | the skills of the release (`skills/` of the Svod repository) |
| `.svod/VERSION` | YAML: `version` (the engine version), `source` (git URL or local path it was fetched from), `ref` (the tag or branch taken) |
| `.svod/MANIFEST` | one line per file under `lib/` and `skills/`: its sha256, two spaces, its POSIX path relative to `.svod/`; sorted by path |
| `.svod/.gitignore` | keeps byte-code (`__pycache__/`) out of the repository |

Byte-code files (`__pycache__/`, `*.pyc`) are neither listed nor checked. The integration scripts are not copied.

**Launcher.** Every `svod` command first looks for the store it works on: `--root`, else upwards from the working directory; for `hook`, the [store of the session](#hooks), from the event read once on stdin. When that store has `.svod/lib/svod` and the running engine is not that package, the command is run again as `python -m svod.cli <the same arguments>` with `.svod/lib` first on `PYTHONPATH` and the event passed on stdin; the exit code is that of the copy. `SVOD_LAUNCHED` (set to the `.svod/lib` handed over to) keeps it from handing over twice. `install` and `update` are never handed over: the engine at hand runs them, so a broken copy can still be replaced. Without a copy the installed engine runs, as before. Hooks and setup scripts keep calling plain `svod`.

**Integrity.** `validate` compares the files under `.svod/lib/` and `.svod/skills/` with `MANIFEST`: a changed, added or removed file is the error `vendored copy modified: <files>; run svod update --to <ref> to restore`; a copy without `MANIFEST` is an error too. Without `.svod/` there is no check.

**install and update.** `svod install [--from <git URL or path>] [--to <ref>]` creates `.svod/`; `svod update` with the same flags replaces it. The source defaults to `source` of `.svod/VERSION`, for `install` to the Svod repository; a local path to a clone works the same (it is cloned too, so exactly the ref is taken). `--to` defaults to the newest tag `vX.Y.Z` of the source, by semantic version. Steps:

1. `git clone --depth 1 --branch <ref>` into a temporary directory; a failure leaves the store untouched.
2. `svod/` of the clone becomes `.svod/lib/svod/`, `skills/` becomes `.svod/skills/`; `VERSION` and `MANIFEST` are written. The copy is assembled in a directory next to `.svod/` and renamed into place.
3. The new copy runs `migrate --since <old version>` (for `install`, the version of the engine at hand), then `validate`.
4. The releases of `CHANGELOG.md` of the source after the old version up to the new one are printed, then the **Migration** notes they carry, then a reminder: nothing is committed, review `git diff`, commit, open a pull request.

### Migrations

Versions are semantic; before 1.0 a minor release may break a store. `svod/migrations.py` holds `MIGRATIONS`, an ordered registry of `Migration(version, apply)`: `apply(root)` changes the store and returns `Change(key, facts)` items, rendered with the locale. `migrate --since <old>` applies every migration whose version is after `<old>` and up to the running engine, oldest first. Helpers: `rename_config_key(root, old, new)` renames a top-level key of `svod.yaml` keeping every other line, `rename_file(root, old, new)` renames a path under the root. Each release of `CHANGELOG.md` has a `### Migration` subsection describing them and any manual step, `none` when there is nothing.

### Update notice

With `update_check` on (the default) and a copy in the store, `hook session-start` and `active --hook` run `git ls-remote --tags <source>` (timeout 3 s) at most once a day and, when a tag is newer than `version` of `.svod/VERSION`, start the summary with `update.available`. The time and the newest release are cached in `svod-update-check.json` in the git common directory of the store, never committed; a failed check is cached too and says nothing. A store outside git is not checked.

