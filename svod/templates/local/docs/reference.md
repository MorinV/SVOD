# Svod — format reference

## Overview

- A **pipeline** is a YAML declaration of an ordered process: entry conditions, steps, a done condition.
- A **step** is one stage of the pipeline; it passes when all of its gates pass.
- A **gate** is a named check (a Python class) over a subject; it returns PASS, FAIL or UNKNOWN plus facts.
- A **store** is the directory tree rooted at `svod.yaml`, usually a git repository.
- A **subject** is one instance the pipeline is evaluated for (a change, a container directory, a document), supplied by a **provider**.
- A **position** is the result of evaluating a pipeline for one subject: marks, the next step, the code freeze, warnings, order violations.
- An **action** is a bash script of the profile that `svod do` runs for one subject with its facts in the environment, see [Actions](#actions).
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
| `profile_config` | no | mapping / `{}` | profile settings exposed as `ctx.config.profile_config`; the core checks only its `agent_context` mapping, read by the [hooks](#hooks): its keys are `session_summary`, `prompt_positions`, `approval_notice` and `knowledge`, each a bool; any other key or a non-bool value is a load error naming the key. Its `checks` mapping (service name to an argv list, `{app: [pytest, -q]}`, or a shell line), written by `init --wizard`, reaches the [actions](#actions) as `SVOD_CHECKS_<NAME>` |
| `workspace_gate` | no | string / none | name of a gate with a `worktrees(ctx, keys)` method (see [Writing a custom gate](#writing-a-custom-gate)); it tells the `pre-tool` hook which directories are work directories of a subject; without it that check is off |
| `main_checkout_read_only` | no | bool / `false` | the `pre-tool` hook refuses edits in the main checkout of the store repository, except paths git ignores; work goes into worktrees |
| `knowledge` | no | mapping / `{dir: knowledge, limit_lines: 20}` | where the [knowledge](#knowledge) notes live (`dir`, relative to the root) and how many note lines a hook adds at most (`limit_lines`, a positive integer); any other key is a load error |
| `update_check` | no | bool / `true` | with a [copy of the engine](#vendored-copy) in the store, the session start summary says when a newer release is out, checked at most once a day; `false` turns the check off |
| `services` | no | mapping / `{}` | service repositories the works of the store are about: name to a directory relative to the root (`{app: ../app}`); an absolute path, a non-string value or a directory that does not exist is a load error naming the service; resolved and exposed as `ctx.config.services` (name to `Path`); the core does not read it, profile gates may |
| `evidence` | no | mapping / `{}` | the [evidence log](#evidence): `enabled` (bool, `true`) writes it, `commit` (bool, `true`) keeps it in version control; any other key or a non-bool value is a load error |
| `autonomy` | no | mapping / `{}` | level of each pipeline: which approval steps become optional; see [Autonomy](#autonomy) |
| `external_effects` | no | mapping / none | extends and exempts the commands the `pre-tool` hook holds for a person; see [External effects](#external-effects) |

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
services: { app: ../app, api: ../api }
knowledge: { dir: knowledge, limit_lines: 20 }
evidence: { commit: false }
autonomy: { task: supervised, hotfix: autonomous, note: guided }
external_effects:
  deny: ["^make deploy"]
  allow: ["^git push origin feature/"]
  phrases: [go ahead, давай, выполняй]
profile_config:
  publishing: { mode: review }
```

### Autonomy

`autonomy` maps a pipeline name, or a kind of work, to a level; the level decides which approval steps (steps with an `approval` gate) a subject waits for. A name that is neither a loaded pipeline nor a kind of work (`hotfix`), or a level not in the list, is a load error.

| level | approval steps |
|---|---|
| `guided` | all as declared |
| `supervised` | a step with an approval gate of `purpose: result` becomes optional |
| `autonomous` | every approval step becomes optional |

The level of a subject is that of its kind of work, `autonomy[kind]` for the `kind` of its frontmatter (`subject.attrs.frontmatter`), when that kind is `hotfix` and has a level; else that of its pipeline, `autonomy[<pipeline>]` (`svod.loader.subject_level`). A relaxed step is `optional`, neither `required` nor `blocks_code`, so it never becomes the position, takes no part in violations and freezes no code (the `pre-tool` rule of frozen code and `svod local` included). Its gates still show marks, the approval fields stay guarded, `approve` still records an approval. The pipeline file is not touched.

The steps are relaxed by the level of the pipeline as loaded (`svod.loader.apply_autonomy`); the declared steps are kept beside them. For a subject whose kind has a level, `position()` and `freeze()` take the declared steps relaxed by that level instead (`svod.loader.subject_steps`, through `svod.position.steps_of`), whether it is looser or stricter than the pipeline's: with `{task: supervised, hotfix: autonomous}` a hotfix of the `task` pipeline has no required approval step and no code freeze, while a task keeps its contract approval. `status` prints `status.autonomy` with the level of the pipeline under the header of a subject whose pipeline has one.

### External effects

The `pre-tool` [hook](#hooks) refuses a shell command with an effect outside this machine, whatever the autonomy, until a person in the chat says go ahead.

| key | req | type / default | meaning |
|---|---|---|---|
| `deny` | no | list of regular expressions / `[]` | more commands to hold, besides the standard list |
| `allow` | no | list of regular expressions / `[]` | commands never held, the standard list included |
| `phrases` | no | list of strings / `[go ahead, давай, выполняй]` | phrases of a reply that lift the refusal |

A phrase counts in a reply (letter case and Unicode form ignored, as whole words) only on a line of its own: nothing but spaces before it on the line, nothing but punctuation after it. A phrase inside a sentence is no answer, however it is placed, so no list of negations is needed: `Давай, пушь`, `ок, давай.`, `Нет, не давай`, `давай не будем` and `Хорошо, давай сначала посмотрим дифф` do not say go ahead; `давай`, `Go ahead!` and `Looks good.\ngo ahead\nthen close it` do.

Every pattern is searched (`re.search`) in each simple command of the line: its words joined by single spaces, from the program on (leading `VAR=value`, `env`, `sudo`, `nohup`, `command`, `exec`, `time`, `nice` dropped). An invalid pattern or an unknown key is a load error.

### Approval by a person

An approval is two acts: a person writes a phrase in the chat, then the agent records it with `approve`. The engine owns the mark file and its format; the store decides the phrases and the window.

| key | req | type / default | meaning |
|---|---|---|---|
| `phrases` | no | list of strings / `[]` | phrases that approve; the `prompt` [hook](#hooks) matches them against a whole prompt |
| `window_minutes` | no | positive int / `10` | how long a mark stays fresh |

The mark is `svod-approval.json` in the git common directory of the store (so every worktree of the store shares it, and it is never committed): `{"at": "<ISO time with offset>", "keys": [<keys named in the prompt>]}`. The prompt hook writes it from a real human answer. `approve` requires a fresh mark for the subject, ready preceding nonoptional stages and bound files not modified after the answer. It consumes only this subject's named keys, preserving other keys and the original timestamp; an unnamed mark is single-use. Do not call the internal mark writer to manufacture human consent. `approve --step <id>` selects a specific applicable approval stage; otherwise the first unsatisfied applicable approval is selected.

**The human mark.** The prompt hook also leaves `svod-human.json` next to the approval mark in the git common directory, on every reply of a person (never on a message of another agent): `{"at": "<ISO time with offset>", "sha": "<sha256 hex of the reply, stripped>", "go": <bool>}`. For a reply to a question of the agent the text is its answers joined by newlines. `go` is true when the reply holds one of `external_effects.phrases` where it says go ahead (see [External effects](#external-effects)). The mark is fresh for `window_minutes`, like the approval mark; each reply replaces it, and a redelivered event older than the window leaves none. `svod.approval` owns it: `write_human_mark(root, text, go)`, called only by the prompt hook, `read_human_mark(root)` and `fresh_human_mark(root, minutes)`. It shows that a person has just written, and when, not what they said. [`answer`](#questions-before-work) refuses without a fresh one whose `sha` is 64 lowercase hex digits and does not consume it: one message may answer several questions, and the agent copies the answer from the chat. The [external-effects rule](#external-effects) lets a held command run only while the mark is fresh and its `go` is true.

Agents without a prompt hook (Cursor, Aider, a plain terminal) have no mark to leave. For them `approve <query> --confirm` asks the person at the terminal instead: with no fresh mark and stdin a terminal, it prints on stderr what is approved (`approve.confirm_plan`: the keys of the subject, the step, the approval file; `approve.confirm_files`: the bound files and the version to record) and asks `approve.confirm_question`; only `y` or `yes` (letter case ignored) records the approval, with the approver from the local config or git as usual, and any other answer or end of input refuses with `approve.not_confirmed` and writes nothing. The person answers in the terminal, not the agent: input from a pipe or a file is not a terminal, so it refuses with `approve.no_mark` as without `--confirm`. A fresh mark, when there is one, is used as without the flag. Like the hooks, this keeps a careless agent from approving its own plan, not a determined one that can fake a terminal.

### Local config

The file named by `local_config` holds what differs per person. It is optional: when absent, nothing is read and the `active` summary starts with `active.no_local_config`; `init` creates it, and `init --wizard` writes it again when the login or the email it is given differs, keeping its other keys. Unknown keys and non-string values are load errors.

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
| `action` | no | identifier matching the step-id syntax | name of a script `<profile>/actions/<action>.sh` that takes the step; while the step is the position of an existing subject, `status` prints `status.run` (`svod do <action> <id>`) after the next step and its skill; `validate` checks that the script exists, see [Actions](#actions) |

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
- id: build
  role: builder
  action: start-task
  text: task.step.build
  gates: [ { gate: progress, label: mark.progress } ]
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
2. **Marks** — when the subject exists, every step gate with a `label` (optional steps included) is shown as a mark: the gate's `display` when set, else `status.mark.<pass|fail|unknown>` with the rendered label. A step with no labelled gate is shown as one mark of its own: its `title` when declared, else its `id`; it passes when the step passes and is unknown when a gate of it could not be checked.
3. **Done** — evaluated after the step gates. When it passes, its `text` becomes the step line (inside `status.next_step`) and nothing else is computed; entry warnings and UNKNOWNs are still printed. A done gate that is UNKNOWN is reported and evaluation goes on.
4. **Steps** — only non-optional steps count. A step passes when it has gates and all of them pass; FAIL and UNKNOWN both mean not passed. Every UNKNOWN gate of a non-optional step is reported.
5. **Violations** — a passed step preceded by a `required` step that did not pass; one line per pair, text from `violations` or `status.violation` with `{later}`, `{earlier}`. Computed also when the entry blocks; never for a missing subject.
6. **Blocked** — with a blocking entry there is no current step: the entry `text` is printed as is (not wrapped in `status.next_step`); if the pipeline has any `blocks_code` step and the subject exists, `status.do_not_touch_blocked` is printed.
7. **Current step** — the first non-optional step that did not pass. Its step `entry` is evaluated now (same rules as 1). Text: a failed blocking step entry's `text`; else the `text` of the first gate that did not pass, when it has one; else the step `text`. Facts come from that gate (or entry). All steps passed and done did not: the `pending` text of done when declared, else no step line.
8. **Code freeze** — when the subject exists and a `blocks_code` step lies at or after the current step, `status.do_not_touch` is printed with the facts of that step's first open gate and `{step}` = its id. Checks that decide on the code without a whole position (the readiness check of local `checks`) use `freeze()`: the first applicable `blocks_code` step whose applicable gates do not all pass; a step without gates is open with its own text, an UNKNOWN gate is open and carries its reason. Unlike the status line, `freeze()` never holds the code for a passed `blocks_code` step that lies after an unpassed one.
9. **Step skill** — printed after the step line when the current step has a `role`, bindings are configured and the text does not come from a blocking entry.
10. **Errors while reading** — an `OSError` raised by a gate becomes UNKNOWN with the error as reason; any other exception becomes UNKNOWN with the reason `gate <name> raised <error>`, so a broken gate leaves its step unpassed instead of failing the command or the hook.
11. **Missing subject** — a subject the provider did not find (`exists: false`, see [Subject providers](#subject-providers)). When the pipeline declares `missing` and that gate FAILs, `status` prints its `text` on stderr instead of a position — only when the query shows no position at all: another pipeline presenting the same query is the answer; on PASS or UNKNOWN the position is computed. A position of a missing subject never has order violations (rule 5) nor the code freeze (rules 6 and 8): nothing has been done for it yet, so there is no order to break and no plan to wait for.

Output order of a `status` block: header, the checkout line (`status.checkout`, for a subject of another checkout), marks, children, blank line, step line, skill line, code freeze, UNKNOWN lines, warnings, violations. A step text ending with a period loses it inside `status.next_step`, which ends the sentence itself.

**Children.** The pipeline lists children when its `active` block declares `children` (by the `parent` field), else when a step or the `done` gate uses [`has_children`](#has_children) or [`children_done`](#children_done): then the `pipelines` of those uses with their `field`, in the order of first mention. For an existing subject with at least one such child, the block `status.children` follows the marks with one line per child, in the order of the child pipelines, then of the provider: `status.child_done` when the child is done (as `children_done` decides), `status.child` with `{step}`, the id of its current step, or `status.child_open` when it has no current step (a blocking entry, or every step passed and `done` did not). Facts `{id}`, `{pipeline}` of the child. Archived children are listed too, as the gates count them. Without children, or for a pipeline that lists none, there is no block. The positions are computed once, when the status is collected; `--format json` gives every position `children: [{id, pipeline, current, done}]` (`current` the step id or `null`, an empty list without children).

```text
work/features/login
  + split
  - finish
  Children:
    work/tasks/form - done
    work/tasks/token - check

  Next step: finish the tasks.
```

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

Next to `marker` live `<marker>_by` (who approved) and `<marker>_sha` (sha256 over the relative path and content of every file matched by `bind`, in path order); `approve` writes all three, line by line, keeping every other line of the file. `svod.approval.read_fields(path, marker)` returns them as `(date, by, sha)` stripped text (empty when absent; `LoadError` when the file is not valid YAML) and `svod.approval.write_fields(path, marker, date, by, sha)` writes them: the gate and `approve` use only these two, and a custom gate should too. With `ignore` or `strip` the content of each file is normalized before hashing, line by line: a blank (whitespace-only) line or a line matched by any `ignore` expression (`re.search` on the line as written, anchor with `^` yourself) is dropped; then every `strip` expression, in the declared order, has its matches removed (`re.sub`). A line `strip` changed is tidied: runs of `,` and `;` shrink to one, separators before `)` and empty parentheses go, whitespace before `, ; . :` goes, whitespace runs shrink to one space, separators (`, ; . :`, en and em dash) are trimmed from its start and, except the full stop, from its end, and its original indent is kept; a line left with nothing but whitespace and separators is dropped like a blank one. The kept lines are joined by `\n`. Without `ignore` and `strip` the digest is over the raw bytes, as before.

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

**Where the frontmatter comes from.** `field` reads no file itself: it reads `attrs.frontmatter`, which the [provider](#subject-providers) fills when it finds the subject.

| provider | `attrs.frontmatter` |
|---|---|
| `frontmatter_doc` | the frontmatter of the subject file itself |
| `container` | the frontmatter of the head document: the first `*.md` directly in the container directory, by name, whose frontmatter `type` equals the provider's `head_type`; empty without `head_type` or without such a document |
| `openspec_change` | always empty |
| a profile provider | whatever it puts there |

A `container` has no param naming a file by path, and nothing below the top level of the container is read. A `field` on a file the provider does not pick up, such as `posts/<name>/draft.md` without `head_type: draft` and `type: draft` in that file, sees an empty field and FAILs on every evaluation. Give that file a `type` and declare it as `head_type`, check that the document exists with [`doc_type`](#doc_type), or write a profile gate that reads the file (see [Writing a custom gate](#writing-a-custom-gate)). With an always empty frontmatter only `present: false` passes.

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

### `command`

A check by a script instead of a question to the agent: a linter, the tests, a link check, a frontmatter schema.

| param | req | type / default | meaning |
|---|---|---|---|
| `argv` | yes | non-empty list of strings | the command and its arguments, run without a shell; `{id}` (the subject id), `{path}` (the subject path relative to the store root, the id when it has none) and `{root}` (the absolute store root) are replaced in every item, other braces stay as written |
| `service` | no, not with `cwd` | string | name from `services` of `svod.yaml`: the command runs in the work directory of the subject in that repository (found by the gate named in `workspace_gate`, by the subject's keys), else in the service directory itself |
| `cwd` | no, not with `service` | string / the store root | directory relative to the store root |
| `timeout` | no | positive number / `120` | seconds before the command and its process group are stopped |
| `watch` | no | non-empty list of paths or globs / none | files relative to the directory whose content also enters the cache key, for inputs git does not see (ignored or generated files); a directory counts with every file below it; no absolute path, no `..` |
| `env` | no | mapping of strings / `{}` | added to the environment of the command |
| `cache` | no | bool / `true` | `false` runs the command in every run of `svod`, never from the disk |

The command runs as the local runner runs it: argv without a shell, stdout and stderr together, in a POSIX session of its own whose process group is stopped after it exits, with `PYTHONDONTWRITEBYTECODE=1`. A gate of a loaded pipeline adds the variables an [action](#actions) of the subject gets (`SVOD_ROOT`, `SVOD_ID`, `SVOD_KEY`, `SVOD_PIPELINE`, `SVOD_KIND`, `SVOD_SERVICES`, `SVOD_SERVICE_<NAME>`, `SVOD_CHECKS_<NAME>`, `SVOD_SUBJECT_PATH`, `SVOD_LOCALE`, `SVOD_FM_<NAME>`) with `SVOD_ACTION` empty, so a profile script behaves as under `svod do`; `env` comes on top. The substituted `argv` and these variables enter the cache key. PASS when it exits with 0, FAIL with any other code. UNKNOWN, never cached, when it does not finish within `timeout`, cannot start, its directory does not exist, `service` is not declared, or the system is not POSIX; the reason says which. Facts: `code` (the exit code), `detail` (the last 20 lines of the output, at most its last 2000 characters; the reason when UNKNOWN), `cached` (`true` when the result came from the disk), `duration` (seconds of the run that produced it); `code` and `duration` are empty when UNKNOWN. One run of `svod` evaluates one command in one directory once, however many steps and marks use it.

**Cache.** `status` and the hooks show the result without running the command again while its source is unchanged. When the directory is in a git repository, the result is kept in `<git common dir>/svod-command-cache/<key>.json` (code, tail of the output, UTC start time, duration), shared by every worktree of the repository; the directory can be removed at any time. The key is sha256 over `argv`, `env`, the directory's path inside its repository, `HEAD`, `git status --porcelain --untracked-files=all`, the content of every file that differs from `HEAD` or is untracked and not ignored, and the content of the `watch` files. Files are hashed by content up to 1000 files and 8 MiB together, beyond that by size and modification time. A new commit, a changed, added or removed file, another argv or env each make a new key, and the command runs again. Outside git nothing is cached and `cached` is always `false`.

The command must be idempotent and must not write into its source: a result is stored only when git sees the directory after the run as before it, so a command that writes there runs again on every `status`. Output for tools goes outside the repository or into ignored paths. A long command makes the first `status` after each change as slow as itself: give it a `timeout` that fits a hook.
### `has_children`

| param | req | type / default | meaning |
|---|---|---|---|
| `pipelines` | yes | non-empty list of pipeline names | pipelines whose subjects may be children |
| `field` | no | string / `parent` | frontmatter field of a child naming its parent |

A child is an existing subject of one of `pipelines` (read through `ctx.pipelines` and the pipeline's provider, once per run) whose `field` in `attrs.frontmatter` equals the `id` of the subject. The value is compared after stripping whitespace, a leading `./` and trailing `/`: with the `container` provider and `head_type`, `parent: work/features/login` names the container `work/features/login`. PASS with at least one child, else FAIL. UNKNOWN when a pipeline name is not loaded. Facts: `total`.

### `children_done`

| param | req | type / default | meaning |
|---|---|---|---|
| `pipelines` | yes | non-empty list of pipeline names | pipelines whose subjects may be children |
| `field` | no | string / `parent` | frontmatter field of a child naming its parent |

Children as in `has_children`. Each child's [position](#position-rules) is computed in its own pipeline (`svod.position.position`); a child is done when its `done` gate passes, or, for a pipeline without `done`, when no entry blocks and every non-optional step passed. PASS when there is at least one child and every child is done. FAIL carries the fact `reason`: `none` (no children) or `open`. UNKNOWN when a pipeline name is not loaded, or on a cycle: the `field` leads from the subject through subjects of any pipeline back to itself (reason `cycle: <id> -> … -> <id>`); a cycle met while the positions of children are computed is UNKNOWN in that child. Facts: `done`, `total`, `open` (ids of the children not done, joined by `, `), `reason` on FAIL. A parent pipeline uses it as `done`, `has_children` as a step:

```yaml
pipeline: feature
subject: { provider: container, params: { roots: [work/features], head_type: work } }
done: { gate: children_done, params: { pipelines: [task] }, text: feature.done }
steps:
  - id: split
    text: feature.step.split
    gates: [ { gate: has_children, params: { pipelines: [task] } } ]
```

### `ref_exists`

| param | req | type | meaning |
|---|---|---|---|
| `field` | yes | string | frontmatter field holding the id of another subject (`cause`, `leads_to`, `parent`) |
| `pipelines` | yes | non-empty list of pipeline names | pipelines the subject must belong to |

The value is read as in `has_children`. PASS when an existing subject of one of `pipelines` has that `id`. FAIL carries the fact `reason`: `missing` (the field is empty or absent) or `unknown` (no such subject). UNKNOWN when a pipeline name is not loaded. Facts: `value`, `pipeline` (where it was found) on PASS, `reason` on FAIL.

### `questions_answered`

| param | req | type / default | meaning |
|---|---|---|---|
| `file` | no | string / `questions.md` | questions file under the subject directory |

PASS when every question of the file has a non-empty answer, or the file is the single line `none`. FAIL carries the fact `reason`: `missing` (no file, or the subject is not a directory), `empty` (neither questions nor `none`), `unanswered`. Facts: `total` (questions), `count` (questions without an answer), `reason` on FAIL. The format and `answer` are in [Questions before work](#questions-before-work).

### Questions before work

Questions the agent has before the work starts go into the questions file of the subject:

```markdown
## Q: Which database?
Context of the question, optional.
A: Postgres 16
  by: someone, at: 2026-10-17, prompt: 3f2a9c01b7de

## Q: Who owns the API?
```

A question is a line `## Q: <question>`; its section runs to the next heading of level one or two. Its answer is the first line of the section starting with `A:`, stripped; an empty one does not count. A file holding only `none` (letter case and surrounding whitespace ignored) says there is nothing to ask.

`svod ask <query> "<question>" [--context "<text>"]` adds the agent's question at the end of the subject's file (the same file as for `answer`, below) as `## Q: <question>`, followed by the context line when given (whitespace runs of each joined into one line), one blank line after what is already there; it creates the file when absent and replaces a file saying `none`. `svod ask <query> --none` writes the single line `none` when the file has no question (an absent file, or one with neither questions nor `none`). It prints `ask.done` with the number of the question and the `answer` command to record its answer, or `ask.none`. It refuses (exit 1) an empty question (`ask.empty`), a question together with `--none` (`ask.conflict`), a context that would read as an answer or a heading (`ask.misread`) and `--none` for a file with questions (`ask.has_questions`). No mark is needed and nothing is committed. The pre-tool [hook](#hooks) refuses every other write of the file, so questions come only from `ask` and answers only from `answer`.

`svod answer <query> --q <n> <text>` writes the person's answer under question `n` (from 1) of the subject's file — the `file` of the first `questions_answered` gate use of its pipeline, else `questions.md` — as `A: <text>` (whitespace runs joined into one line) followed by `  by: <approver>, at: <date>, prompt: <first 12 hex digits of the mark's sha>`; the approver is found as for `approve` (local login, else email, else git `user.email`). An existing answer of the question is replaced with its `by` lines; otherwise the lines go after the last non-blank line of the section. It refuses (exit 1) without a fresh [human mark](#approval-by-a-person) (`answer.no_mark`), without the file (`answer.no_file`), for a number with no question (`answer.no_question`), for an empty text (`answer.empty`) and without an approver (`approve.no_approver`). Nothing is committed. The agent copies the answer from the chat; the mark proves only that the person has just written there.

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
| `children` | no | list of pipeline names / `[]` | pipelines whose open subjects are shown under a subject of this one, see below; also the children `status` lists |

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

**Tree.** A subject of a pipeline listed in `children` whose frontmatter `parent` names an open subject of this pipeline (compared as in [`has_children`](#has_children)) is printed right under the parent's line, indented one `INDENT` more per level, in its own pipeline's `item` (`active.item` when that pipeline has no `active` block), and is left out of its own group. Children come in the order of `children`, then of the provider; their own `children` nest further, at any depth (project → feature → task). Only open children are shown (archived and done ones are skipped, as are subjects shown under a checkout), and only under a parent whose line is printed: under a done parent, a parent shown by checkout or one hidden in `theirs_collapsed`, a child stays in its own group. A subject whose parents lead back to it (a cycle) is printed in its own group, and a subject is printed once. Subjects of every pipeline are enumerated once per run (`svod.relations`, shared with the relation gates); names in `children` that are not loaded are ignored.

```yaml
# project.yaml
active: { children: [feature] }
# feature.yaml
active: { children: [task] }
```

```text
Your work without progress:
  - work/projects/shop (no key) - write the vision
    - work/features/login (no key) - finish the tasks
      - work/tasks/token (no key) - check
    - work/features/search (no key) - split into tasks

Your work without progress:
  - work/tasks/loose (no key) - build
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

## Actions

An action is routine work of a step written once as a bash script of the profile, so the agent runs one command (`svod do start-task PROJ-1`) instead of reasoning through the same five steps every time. Actions run on Linux and macOS.

- **Format.** `<profile>/actions/<name>.sh`, where `<name>` matches the step-id syntax `^[a-z][a-z0-9_-]*$`. The executable bit is not needed: the script is run as the argv `bash <script> [extra args]`, without a shell around it. The first non-empty line after the shebang, when it is a comment, is its description in `svod do --list`.
- **Run.** `svod do <action> <query> [-- extra args]` resolves the query as `status` does (exact name, then tracker key, then substring, in the store and its other checkouts) and needs exactly one existing subject. The working directory is the store root; the output goes to the terminal as it is, not captured; the exit code of the script is the exit code of `svod do`. A script running longer than 600 s (`--timeout <seconds>`, a positive number, sets another limit) is stopped with its process group, `do.timeout` is printed and the exit code is 124. Each run that started is an `action_run` line of the [evidence log](#evidence): the action, its exit code (124 after the timeout, null when interrupted), the seconds and the first step naming the action.
- **Step.** A step may name its action with `action: <name>` (see [Step](#step)): `svod status` then prints `status.run` with the command for the subject, and `validate` reports a step whose script does not exist.
- **Position.** When every applicable step naming the action lies ahead of the subject (after its current step, or an entry holds it before any step), `svod do` prints `do.not_current` on stderr and exits 2 without running; `--force` runs it after the same warning. A step already passed, the current one, one before it, a subject that is done and an action no step names run without a word: running a script again is safe, it is idempotent.

Environment of the script: the environment of `svod`, without inherited `SVOD_SERVICE_*` and `SVOD_FM_*`, plus the variables below. `svod do` passes no record argument: the scripts read `SVOD_ID`. A script run by hand takes the record as its argument, which wins over the variables it inherited (see [the standard template's actions](#the-standard-templates-actions)).

| variable | value |
|---|---|
| `SVOD_ROOT` | absolute path of the store root |
| `SVOD_ID` | id of the subject (what `status` prints in its header) |
| `SVOD_KEY` | the first tracker key of the subject in sorted order, or empty |
| `SVOD_PIPELINE` | name of the subject's pipeline |
| `SVOD_KIND` | frontmatter field `kind` of the subject, or empty |
| `SVOD_SERVICES` | frontmatter field `services` (a list or a comma separated string), joined by commas, or empty |
| `SVOD_SERVICE_<NAME>` | absolute path of every service declared in `svod.yaml` `services` (a path, or a mapping with `path`), the name in upper case with every sign other than a letter, digit or `_` as `_` |
| `SVOD_CHECKS_<NAME>` | the check command of every service in `profile_config.checks` of `svod.yaml`, an argv list quoted as a shell line, a string as written; named as services are; a variable already set in the environment wins |
| `SVOD_SUBJECT_PATH` | absolute path of the subject (in the checkout that holds its version), or empty |
| `SVOD_LOCALE` | the locale of the store |
| `SVOD_ACTION` | the name of the action: the marker of a run by `svod do`; empty when a [`command`](#command) gate runs a script |
| `SVOD_FM_<NAME>` | every other scalar frontmatter field (strings, numbers, `true`/`false`, dates as ISO, empty for `null`), named as services are; lists and mappings are left out |

**Idempotence is the script's job.** The engine does not remember that an action ran; the position comes from files and git. Every script first checks whether its work is already done (the branch exists, the file is written, the directory is created) and then says so and exits 0, so running it twice, or after a session that stopped half way, is safe. Exit non-zero only for a real failure, with a message on stderr saying what to do.

```bash
# profile/actions/start-task.sh
# Start the work on a task: write its work note once.
set -eu
note="$SVOD_SUBJECT_PATH/work.md"
if [ -f "$note" ]; then
  echo "already started: $note"
  exit 0
fi
printf '# Work on %s (%s)\n' "$SVOD_ID" "${SVOD_KEY:-no key}" > "$note"
echo "started: $note"
```

### The standard template's actions

`profile/actions/` of `svod new --template standard` holds `start-task.sh`, `checks.sh`, `pr.sh` and `cleanup.sh`, each sourcing `_env.sh`; they run under `svod do` and by hand as `bash profile/actions/<name>.sh work/<kind>/<name> [options]` from the store root.

- **The record.** The first argument not starting with `--` is the record, the others are options. Under `svod do` (no record argument) the `SVOD_` variables are used. A record argument naming another record than `SVOD_ID`, or a `SVOD_ROOT` other than the working directory, makes the inherited variables stale: `SVOD_ACTION`, `SVOD_ROOT`, `SVOD_ID`, `SVOD_KEY`, `SVOD_KIND`, `SVOD_PIPELINE`, `SVOD_SERVICES`, `SVOD_SUBJECT_PATH`, `SVOD_SERVICE_*` and `SVOD_FM_*` are dropped and found again from the argument, `card.md` and `svod.yaml`. So `checks.sh` running a test suite that runs these scripts on another store acts on the record it was given there, never on the outer one.
- **Names.** The worktree of service `<service>` for the record `work/<kind>/<name>` of pipeline `<pipeline>` is `<directory holding the service checkout>/<service>-<pipeline>-<name>`, on the branch `<pipeline>/<name>`. The checkout is the absolute path of the service (`SVOD_SERVICE_<NAME>`, else `services.<name>` of `svod.yaml`, else `../<name>`), so a store inside its service gets the worktree next to the checkout. `<pipeline>` is `SVOD_PIPELINE`, else `<kind>` without its final `s`. `work.yaml` lists `<service>: <path relative to the store root>` (`app: ../app-task-login`) and can be committed.
- **`checks.sh --check`.** Writes nothing: it runs the checks of every service again (in the worktree of `work.yaml`, else the checkout) with their output on stdout and exits 0 when all pass. A record naming no services exits 0 printing `no services declared ...`; a record without `checks.md` exits 1 without running anything (`not checked yet ...`), which keeps the gate cheap before the first real run. The task step `checks` and the feature step `integration` use it next to `checks.md`:

```yaml
- { gate: artifact, params: { path: checks.md }, label: work.mark.checks }
- { gate: command, params: { argv: [bash, profile/actions/checks.sh, "{id}", --check], cwd: . }, label: work.mark.checks_pass }
```

The result is cached by the state of the store repository (its `HEAD`, status and changed files), which holds `checks.md` with the commit of every service: the checks run again after each change in the store, a new `checks.md` included, and a commit in a service outside the store is seen once `checks.sh` runs again. No `watch` is needed. Without git around the store nothing is cached and every `status` runs the checks.

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
| `status.autonomy` | `{level}` |
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
| `status.run` | `{action}`, `{query}` (the subject id, quoted for the shell when needed) |
| `status.children` | — |
| `status.child` | `{id}`, `{pipeline}`, `{step}` |
| `status.child_done`, `status.child_open` | `{id}`, `{pipeline}` |
| `status.mark.pass`, `status.mark.fail`, `status.mark.unknown` | `{label}` |
| `active.mine_active`, `active.mine_idle`, `active.theirs`, `active.no_keys`, `active.hook_tail`, `active.no_identity` | — |
| `active.no_local_config` | `{file}` |
| `active.worktree` | `{dir}` |
| `active.none` | — (printed by `active` when no pipeline declares `active`; not in the hook) |
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
| `hook.approval_marked` | `{minutes}`, `{keys}`, `{commands}` (`svod approve <key>` of each key, joined by `; `) |
| `hook.approval_marked_unnamed` | `{minutes}` (the approval named no key) |
| `hook.approval_joiners` | — (words joining keys after an approval phrase, separated by spaces) |
| `hook.deny_approval` | `{fields}`, `{file}` |
| `hook.deny_plan` | `{keys}`, `{text}` |
| `hook.deny_main` | `{main}` |
| `hook.deny_mark` | `{file}` |
| `hook.deny_broken` | `{reason}` |
| `hook.knowledge_head` | — (heading of the [knowledge](#knowledge) lines a hook adds) |
| `hook.deny_human`, `hook.deny_questions` | `{file}` |
| `hook.deny_external` | `{command}`, `{phrases}`, `{minutes}` |
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
| `approve.confirm_plan` | `{subject}`, `{step}`, `{marker}`, `{file}` |
| `approve.confirm_files` | `{sha}` |
| `approve.confirm_question`, `approve.not_confirmed` | `{subject}` |
| `do.usage`, `do.list_no_description`, `do.no_current` | — |
| `do.unknown` | `{name}`, `{script}` |
| `do.failed` | `{name}`, `{reason}` |
| `do.timeout` | `{name}`, `{seconds}` |
| `do.list_item` | `{name}`, `{description}` |
| `do.list_none` | `{dir}` |
| `do.not_current` | `{name}`, `{step}`, `{id}`, `{current}` (`do.no_current` when an entry holds the subject) |
| `wizard.not_tty`, `wizard.prompt_service`, `wizard.checks_auto`, `wizard.unchanged`, `wizard.aborted`, `wizard.next` | — |
| `wizard.prompt_login`, `wizard.prompt_hooks` | `{default}` |
| `wizard.services_current` | `{services}` (`name=path` joined by `, `) |
| `wizard.prompt_path`, `wizard.prompt_checks` | `{name}`, `{default}` |
| `wizard.bad_service` | `{name}`, `{path}` |
| `wizard.bad_pair` | `{flag}`, `{value}` |
| `wizard.prompt_autonomy` | `{name}`, `{default}`, `{levels}` |
| `wizard.bad_level` | `{name}`, `{level}`, `{levels}` |
| `wizard.unknown_pipeline`, `wizard.unknown_service` | `{name}`, `{names}` |
| `wizard.bad_checks` | `{name}`, `{command}`, `{reason}` |
| `wizard.bad_hooks` | `{answer}` |
| `wizard.written` | `{keys}` (the changed keys of `svod.yaml`) |
| `wizard.write_failed` | `{reason}` (the keys that would differ) |
| `wizard.hooks_manual` | `{command}` |
| `wizard.hooks_failed` | `{command}`, `{code}` |
| `setup.no_source`, `setup.not_tty` | — |
| `setup.prompt_source` | `{default}` |
| `setup.git_failed` | `{reason}`, `{path}` |
| `setup.committed` | `{sha}`, `{path}` |
| `setup.stopped` | `{step}`, `{path}` |
| `setup.done` | `{path}` |
| `doctor.config_ok` | `{count}` |
| `doctor.config_fail` | `{error}` |
| `doctor.services_none`, `doctor.copy_none`, `doctor.evidence_off`, `doctor.knowledge_none` | — |
| `doctor.service_ok`, `doctor.service_missing`, `doctor.service_not_git` | `{name}`, `{path}` |
| `doctor.hooks_ok`, `doctor.hooks_python` | `{file}`, `{python}` |
| `doctor.hooks_none` | `{files}`, `{command}` |
| `doctor.hooks_partial` | `{file}`, `{events}` |
| `doctor.hooks_unreadable` | `{file}`, `{reason}` |
| `doctor.copy_ok` | `{version}` |
| `doctor.version_ok` | `{current}`, `{latest}` |
| `doctor.version_newer` | `{current}`, `{latest}`, `{command}` |
| `doctor.version_unchecked` | `{current}`, `{reason}` |
| `doctor.evidence_ok` | `{dir}` |
| `doctor.evidence_fail` | `{dir}`, `{reason}` |
| `doctor.knowledge_ok` | `{path}`, `{count}` |
| `doctor.knowledge_stale`, `doctor.local_missing` | `{path}` |
| `doctor.local_ok` | `{path}`, `{login}` |
| `doctor.local_invalid` | `{path}`, `{error}` |
| `doctor.local_not_configured` | `{field}` |
| `gate.exists`, `gate.archived`, `gate.git_pushed` | — |
| `gate.artifact_path` | `{path}` |
| `gate.artifact_glob` | `{glob}`, `{min}` |
| `gate.approval` | `{marker}`, `{file}` |
| `gate.approval_bound` | `{marker}`, `{file}`, `{bind}` |
| `gate.field_equals`, `gate.field_not_equals` | `{name}`, `{value}` |
| `gate.field_present`, `gate.field_absent`, `gate.field_date_not_past`, `gate.field_date_past` | `{name}` |
| `gate.doc_type`, `gate.doc_type_container` | `{type}` |
| `gate.git_pushed_repo` | `{repo}` |
| `gate.command` | `{argv}` (the argv as a shell would quote it), `{where}` (`service`, `cwd` or `.`) |
| `gate.children_done`, `gate.has_children`, `gate.ref_exists` | `{pipelines}`, `{field}` |
| `gate.questions_answered` | `{file}` |
| `answer.done` | `{file}`, `{number}`, `{question}`, `{by}`, `{sha}` |
| `answer.no_mark`, `answer.empty` | — |
| `answer.no_file` | `{file}` |
| `answer.no_question` | `{file}`, `{number}`, `{count}` |
| `ask.done` | `{file}`, `{number}`, `{question}`, `{query}` |
| `ask.none` | `{file}` |
| `ask.empty`, `ask.conflict` | — |
| `ask.misread` | `{context}` |
| `ask.has_questions` | `{file}`, `{count}` |
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
| `knowledge.added`, `knowledge.exists` | `{path}` |
| `knowledge.no_file` | `{path}` (the file given to `knowledge add`) |
| `knowledge.item` | `{title}`, `{path}`, `{tags}`, `{date}`, `{status}` |
| `knowledge.none` | — |
| `retro.item` | `{number}`, `{rule}`, `{subject}` (what the decision is about), `{text}` |
| `retro.facts` | `{facts}` (`name=value` pairs) |
| `retro.proposed` | `{file}`, `{kind}`, `{text}` |
| `retro.none`, `retro.usage`, `retro.hint` | — |
| `retro.no_number` | `{number}`, `{count}` |
| `retro.recorded` | `{decision}`, `{number}`, `{rule}`, `{path}` |
| `retro.rule_failed` | `{reason}` |
| `retro.rule.dirty_checks` | `{count}`, `{runs}` |
| `retro.rule.approval_drift`, `retro.rule.approval_drift_questions` | `{step}`, `{count}` |
| `retro.rule.hook_denials` | `{hook_rule}`, `{count}`, `{step}` |
| `retro.rule.hotfix_cause` | `{work}`, `{count}`, `{hotfixes}` |
| `retro.rule.instant_steps` | `{pipeline}`, `{step}`, `{count}`, `{seconds}` |
| `retro.rule.long_step` | `{pipeline}`, `{step}`, `{count}`, `{works}`, `{share}` |
| `retro.change.approval_drift`, `retro.change.approval_drift_questions` | `{step}`, `{count}` |
| `retro.change.hook_denials` | `{hook_rule}`, `{count}`, `{step}` |
| `retro.change.hotfix_cause` | `{work}`, `{count}`, `{hotfixes}` |
| `retro.change.long_step` | `{pipeline}`, `{step}`, `{count}`, `{works}`, `{share}` |

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

`ctx` carries `config` (`root`, `default_branch`, `workspaces`, …), `locale` (may be `None` in tests), `today`, `bindings`, `root`, `pipelines` — loaded pipelines by name, for a gate that consults another pipeline (for example its subject provider as `ctx.pipelines[name].subject.impl`) — and `cache`, the memory of one run shared by every context rooted in another checkout: `cache.git(cwd, *args)` runs git once per directory and arguments, `cache.prefetch([(cwd, args), …])` runs the calls not known yet in parallel (a pool of `GIT_WORKERS` threads), `cache.value(key, compute)` keeps a value computed from files. Nothing is written to disk: hooks and sessions run in parallel. A gate reads git through `ctx.cache`, not `run_git`; `worktree_list` and `changed_paths` of `svod.git` take it as `run`. `cache.git` returns a `GitResult` (`svod.git`), not a string: `ok` tells whether git succeeded, `out` is its stripped stdout, `error` the first line of stderr on failure.

A gate that raises does not break `status` or a hook: its outcome is UNKNOWN with the reason `gate <name> raised <error>`, so the step stays unpassed and the status says why. Return `unknown(reason)` yourself for the cases you foresee; an exception is for the ones you did not.

`Result(status, facts={}, display=None, reason=None)`: `status` is `Status.PASS`, `Status.FAIL` or `Status.UNKNOWN`; `facts` fill texts; `display` replaces the standard mark line; `reason` is shown for UNKNOWN. Helpers: `verdict(ok, **facts)` and `unknown(reason, **facts)`.

**Workspace gate.** The gate named by `workspace_gate` in `svod.yaml` must be instantiable without params and implement `worktrees(ctx, keys)`: `(pairs, errors)` where every pair is `(directory, repository name)` of a work directory of the keys and `errors` lists git failures. The `pre-tool` hook only uses the directory. `svod/templates/task/profile/gates/git_work.py` has one.

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
| `approve <query>` | `--step <id>`, `--confirm` | records the ready selected applicable approval with date, approver and digest, consuming this subject's mark keys; refuses changed-after-answer inputs; with `--confirm` and no fresh mark asks the person at a terminal, see [Approval by a person](#approval-by-a-person); nothing is committed | 0 recorded, 1 refused, 2 not found or ambiguous |
| `ask <query>` | `<question>`, `--context`, `--none` | adds a question at the end of the subject's questions file, or writes `none` with `--none`; see [Questions before work](#questions-before-work); nothing is committed | 0 recorded, 1 refused, 2 not found or ambiguous |
| `answer <query>` | `--q <n>`, `<text>` | writes the person's answer under question `n` of the subject's questions file with the approver, the date and the prompt digest of a fresh human mark; see [Questions before work](#questions-before-work); nothing is committed | 0 recorded, 1 refused, 2 not found or ambiguous |
| `new <directory>` | `--template standard\|task\|local` | creates an absent directory from installed templates without a pre-existing store; default local, never merges or overwrites | 0 created, 1 refused |
| `setup <directory>` | `--template standard\|task\|local`, `--from`, `--to`, `--locale en\|ru`, `--login`, `--email`, `--service <name>=<path>`, `--autonomy <pipeline>=<level>`, `--checks <service>=<command>`, `--hooks project\|global\|none` | makes an instance in one command: `new`, `git init` and a first commit, `install`, `init --wizard`, the hooks; see [Setup](#setup) | 0 done; the code of the step that failed (1 also for git and an existing directory); 2 refused before anything is made: no `--login` without a terminal, a bad `--service`, no source or no ref |
| `do <action> <query> [-- args]` | `--list`, `--force`, `--timeout <seconds>` | runs the [action](#actions) script `<profile>/actions/<action>.sh` for the one existing subject the query resolves to, in the store root, with the output not captured; extra args after `--` go to the script; `--list` prints every action with its description; an action of a step the subject has not reached is refused with `do.not_current` unless `--force`; `--timeout` replaces the 600 s limit | the exit code of the script (124 after the timeout); 2 unknown action, missing arguments, not found, ambiguous, a step not reached without `--force`, a bad `--timeout` or the script did not start |
| `local <action> <query>` | — | `prepare` diagnoses readiness, `checks` runs the chosen argv, `verify` validates the live result, `deliver` records and reads back local completion; see [local-workflow.md](local-workflow.md) | 0 success, 1 failed/refused, 2 invalid root/load/arguments |
| `hook <event>` | — | answers one agent hook event, `session-start`, `prompt` or `pre-tool`, read as JSON on stdin; see [Hooks](#hooks) | 0 always |
| `init` | `--login`, `--email`, `--force` | writes the local config; without `--login` asks at a terminal, and fails without one; the email defaults to `git config user.email`; an existing file is kept unless `--force` | 0 written, 1 exists, 2 no login or no `local_config` |
| `init --wizard` | `--wizard`, `--login`, `--email`, `--service <name>=<path>`, `--autonomy <pipeline>=<level>`, `--checks <service>=<command>`, `--hooks project\|global\|none` | sets up a store, see [the wizard](#the-wizard); each of the last four flags runs it too and is repeatable but `--hooks` | 0 done, 1 the hook setup failed, 2 an answer refused, no terminal and no flags, or input ended |
| `doctor` | `--format text\|json` | checks that the store is ready to work in, see [the doctor](#the-doctor) | 0 no check failed, 1 a check failed |
| `install` | `--from`, `--to` | puts a copy of the engine into `.svod/` of the store, see [Vendored copy](#vendored-copy); refuses when `.svod/` exists | 0 done, 1 refused or the store does not validate after it, 2 nothing fetched (the store is unchanged) |
| `update` | `--from`, `--to` | replaces the copy in `.svod/`, migrates the store, validates it with the new engine, prints the changelog between the versions and the migration notes; refuses without `.svod/` | as `install` |
| `knowledge <action>` | `--tags`, `--title`, `--source` | `index`, `add <file>`, `note "<text>"`, `list`: see [Knowledge](#knowledge) | 0 done, 1 the note exists, 2 no such file or the config does not load |
| `retro <query>` | `--all`, `--accept <n>`, `--reject <n>`, `--note <text>` | prints the proposals of the [retrospective](#retrospective) for the works the query resolves to, or with `--all` for every open work: number, rule, facts, proposed change; `--accept` or `--reject` records the decision on proposal `n` in `evidence/decisions.yaml` (with `--note`), after which it is not shown again; `--accept` prints the diff to apply by hand, no file is changed | 0 listed or recorded; 2 wrong arguments, not found, ambiguous, no such number, or profile rules or decisions that do not load |
| `migrate` | `--since <version>` | applies the [migrations](#migrations) of the versions after `<version>` up to the running engine and prints what they changed; `update` runs it in the new copy | 0 done, 1 a migration failed, 2 not a version |

`init`, `install`, `update` and `migrate` read `svod.yaml` at most for the locale (`init --wizard` reads and edits it, and asks for the pipelines only when the store loads), `knowledge` reads only `svod.yaml`, `doctor` reports a store that does not load as one failed check, so they work while the store does not load. Every other command except `validate` and `hook` exits with 2 and `error.load` when the store does not load, and with 2 and `error.not_root` when no root is found. PyYAML is a dependency of the package: without it the engine does not import, so neither the CLI nor `hook` answers.

### Setup

`svod setup <directory>` does what five commands do, each step calling the function of its command:

1. `svod new <directory> --template <template>`, `standard` by default; `--locale` is written to `svod.yaml`;
2. `git init -b main`;
3. `svod install --from <source> --to <ref>`. The source is `--from`, else where the running `svod` was installed from, read from the `direct_url.json` of its distribution (PEP 610): the URL and the requested revision of `pip install git+<url>@<ref>`, the directory of `pip install [-e] <dir>`. An install from an index or an archive tells nothing: at a terminal the source is asked (`setup.prompt_source`, the Svod repository by default), without one it is refused with `setup.no_source`. The ref is `--to`, else the one installed, else the newest `vX.Y.Z` tag of the source;
4. `svod init --wizard` with `--login`, `--email`, `--service`, `--autonomy`, `--checks`, see [the wizard](#the-wizard); a `--service` path is relative to the new directory;
5. one commit of the whole directory but what its `.gitignore` keeps out (the local config), `setup.committed`; when git has no `user.name` or `user.email`, the login and email of the local config stand in;
6. the hooks, `--hooks`, at a terminal asked last (`wizard.prompt_hooks`), registered as by the wizard after the commit, so `.claude/` with the paths of this machine stays out of it. The script is `integrations/setup-claude.sh` next to the package, else in the source directory, else in a clone of the ref; it runs with the directory of the running Python first on `PATH`, so the hooks run the Python that has this `svod` (a virtualenv or pipx install).

It asks only at a terminal and only when `--login` or `--hooks` is missing; then the wizard asks every question the flags do not answer. Without a terminal a missing `--login` is refused with `setup.not_tty` and `--hooks` defaults to `none`. A missing login, a bad `--service`, no source and no ref are refused before the directory is made. A failed step stops with `setup.stopped`, which names it; the directory is kept, to finish the remaining steps by hand or to remove. It ends with `setup.done`. `setup` is run by the engine at hand, never handed over to a [copy](#vendored-copy) in `.svod/`.

### The wizard

`svod init --wizard`, run in a store made by `svod new`, asks in turn, each question showing its default from `svod.yaml` in brackets (an empty answer takes it):

1. login and email (`wizard.prompt_login`, `init.prompt_email`), the defaults from the local config, the email else from `git config user.email`; skipped when `svod.yaml` names no `local_config`;
2. services, one at a time (`wizard.prompt_service`, `wizard.prompt_path`, default `../<name>`), until an empty name; a path must be a directory holding `.git`, relative to the store root or absolute (written relative);
3. the autonomy of every loaded pipeline and of every other name already in `autonomy` (`wizard.prompt_autonomy`): `guided`, `supervised` or `autonomous`;
4. the check command of every service (`wizard.prompt_checks`), split as a shell would (`shlex`) and written as an argv list to `profile_config.checks`; an empty answer keeps the current one, or none, leaving `checks.sh` of the standard template to find the command by the files;
5. where to register the Claude Code hooks (`wizard.prompt_hooks`): `project` (the default) runs `integrations/setup-claude.sh --project <store>`, `global` runs it with the store as argument, `none` skips it. The script is run from the clone the package was installed from; an installed package without it (a wheel, a copy in `.svod/`) prints the `git clone` and setup command to run instead (`wizard.hooks_manual`).

A refused answer at a terminal is said and asked again; at the end of input nothing is written (`wizard.aborted`). Without a terminal the answers come from the flags, those not given keep `svod.yaml` as it is, `--hooks` defaults to `none`, and a refused one stops before anything is written; with neither a terminal nor a flag it refuses with `wizard.not_tty`, which names the flags. At a terminal a question answered by a flag is not asked; services given as flags are listed, and more can be added.

`svod.yaml` is edited line by line, never dumped whole: only the lines of a changed key are rewritten (`services`, `autonomy`, `checks` inside `profile_config`), a mapping written on one line (`autonomy: {task: supervised}`) stays on one line, a new key goes after its commented example (`# services:` and the indented comment lines under it) or at the end. The result is parsed back and compared with the answers; any difference is refused with `wizard.write_failed` and nothing is written. The local config is written only when it changes. It ends with `wizard.next`: run `svod doctor`.

### The doctor

`svod doctor` prints one line per check, `ok: <text>`, `warn: <text>` or `fail: <text>`, in this order; each check reads only what it needs, so a store that does not load still gets the others:

| check (`name` in JSON) | fail | warn |
|---|---|---|
| `config`: the store loads as for `validate` (config, profile, pipelines, gates, locale) | it does not; the further errors follow, indented | — |
| `service`, one per entry of `services` | the directory is missing or holds no `.git` | — |
| `hooks`: the svod hooks in `<store>/.claude/settings.json` and `$CLAUDE_CONFIG_DIR/settings.json` (`~/.claude` by default) | the program a hook runs (after `NAME=value` and `env`) is neither an executable path nor on `PATH` | none registered in either file, an event missing, a file that is not JSON |
| `copy`: the [copy of the engine](#vendored-copy) against its `MANIFEST` | it differs, or has no `MANIFEST` | — |
| `version`: the engine (the copy's `version`, else the running one) against the newest `vX.Y.Z` tag of its source, through the cache of the [update notice](#update-notice) | — | a newer release, with `svod update` or the `pip install` command; not checked (`update_check: false`, off git or offline) |
| `evidence`: a temporary file can be written in `evidence/` (the store root before the directory exists); skipped with `evidence.enabled: false` | it cannot | — |
| `knowledge`: the table between the markers of `knowledge/INDEX.md` is what `svod knowledge index` would write now | — | it is not, or the file is missing while notes exist |
| `local_config`: the file named by `local_config` exists and reads | it does not | `svod.yaml` names none |

`--format json` prints `{"ok": <no check failed>, "checks": [{"name", "status", "text", "details"}, ...]}`. The exit code is 0 when no check failed, warnings included, and 1 otherwise.

## Hooks

`svod hook <event>` is registered as a command hook of Claude Code or Codex (`integrations/setup-claude.sh`, `integrations/setup-codex.sh`). The scripts link the skills of the store, `<store>/skills/<name>/SKILL.md`, when it has any, else those of its copy in `.svod/skills`, else those of the clone they run from. They print `-> engine: <file of the svod package>`, the engine the hooks import: the one installed in the Python when it imports without `PYTHONPATH` (an editable install of another checkout shows here), else the clone on `PYTHONPATH`. `--engine <clone>` puts that clone on `PYTHONPATH` of every hook whatever is installed; a directory without `svod/cli.py` is refused (exit 2). Both agents send the same event JSON (`hook_event_name`, `cwd`, `prompt`, `tool_name`, `tool_input`); the answer is `hookSpecificOutput` with `hookEventName` and either `additionalContext` or `permissionDecision: deny` with `permissionDecisionReason`. Nothing to say prints nothing. The exit code is always 0. A store that does not load is reported as `hook.engine_broken` in `additionalContext` instead of silence (for `pre-tool`, only for file edits in the store); a write outside the store is then refused with `hook.deny_broken`, since nothing guards it until the store loads again.

**The store of the session** is the one holding `CLAUDE_PROJECT_DIR`, else the event `cwd`; else the store at `--root`, a fallback for sessions in a work directory outside the store. No store: silence.

Optional `profile_config.agent_context` booleans `session_summary`, `prompt_positions` and `approval_notice` default on for compatibility. Setting them to false suppresses those context outputs, not native approval marking, agent-message filtering or pre-tool protection. The local template turns them off and uses explicit per-task status; `active` remains available on request. These controls do not guarantee token savings or enforce a sandbox. `knowledge` (default on) adds the [knowledge](#knowledge) notes matching the work, whatever `session_summary` says: on `session-start` after the summary when it is on, alone when it is off (the local template), on `prompt` after the positions.

| event | agent event | does |
|---|---|---|
| `session-start` | `SessionStart` | the `active` summary, as `active --hook`, preceded by the [update notice](#update-notice); then the knowledge notes |
| `prompt` | `UserPromptSubmit` | human mark, approval mark and positions, see below; silent on messages of other agents |
| `pre-tool` | `PreToolUse` | refuses the tool call by the rules below |

`prompt`:

- **Human mark.** Every reply of a person leaves the [human mark](#approval-by-a-person) `svod-human.json`, silently: nothing is added to the context.
- **Approval.** When the prompt, as a whole, is one of `approval.phrases` (letter case ignored), optionally followed by keys joined by separators or the words of `hook.approval_joiners`, and closing `.` or `!`, the hook writes the approval mark with those keys (`svod.approval.write_mark`) and says so: `hook.approval_marked` names the keys and the `svod approve <key>` command of each, `hook.approval_marked_unnamed` is said when no key was named. A phrase inside a longer text does not approve. In the positions of the same answer, a subject of a marked key whose next step is that approval gets the variant `<text>_marked` of the step text (with `{keys}`, the marked key) when the locale has it, and no next step otherwise: the answer never asks to wait for the approval it has just recorded.
- **Positions.** Keys the `key_gate` of any pipeline recognises in the prompt, then exact names (the last path segment of the id, at least 8 characters, as a whole word) of open subjects, at most three queries. For each, the `status` block of every existing subject it resolves to, between `hook.position_head` and `hook.position_tail`. A key with nothing in the store adds nothing.

`pre-tool` watches `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash` and `apply_patch` (Codex; the files of the patch are read from its `*** Update File:`, `*** Add File:`, `*** Delete File:` and `*** Move to:` lines, relative to `cwd`). It refuses:

1. **Approval fields.** A file whose path ends with the `file` of an `approval` step gate of any pipeline is a metadata file; its fields are `<marker>`, `<marker>_by` and `<marker>_sha`. Refused: `Write` that changes their lines, `Edit`/`MultiEdit` whose old or new text names one, an `apply_patch` section whose changed lines name one, and a `Bash` command naming the file and a field that writes into it (`>`/`>>` to it, `sed -i`, `perl -i`, `yq -i`, `tee` to it, `cp`/`mv` onto it, a `python -c` or heredoc script holding its path as a string literal). Text: `hook.deny_approval`. Only `svod approve` writes them.
2. **Read-only main checkout.** With `main_checkout_read_only` in the `svod.yaml` of the store holding the path: a path in the first checkout of `git worktree list` of that store, not in a nested repository nor in the git directory, and not ignored by git. A checkout whose `.git` is a directory is the main one without asking git; `git worktree list` is asked only for a `.git` file. Text: `hook.deny_main`.
3. **Frozen code.** With `workspace_gate`: the nearest directory above the path holding `.git` is a work directory when a key gate finds a key in its name and `worktrees(ctx, {key})` of the workspace gate returns it. Each existing, not archived subject of that key (in the store and its other checkouts) is checked: the first gate of a `blocks_code` step that does not pass refuses the edit, with `hook.deny_plan` carrying its step text. A key without a subject is not refused. The standard template has the pair in `profile/gates/work.py`: `workspace_gate: work_tree` returns the worktrees `work.yaml` of a record lists (`<service>: <directory>`, relative to the store root) for its id, its id-slug or the `key` of its `card.md`, and `key_gate: work_id` of the task pipeline reads a worktree directory name `<service>-<pipeline>-<name>` as every record id it may mean (`app-task-login` names `work/tasks/login`; a service or a name holding `-` gives several candidates), and `work_tree` keeps the one whose `work.yaml` lists the directory; a directory without `-<pipeline>-` names no record and is not frozen.
4. **Shell commands.** `Bash` is checked against the same rules through the paths it names: every token of the command that exists or looks like a file (a suffix or a directory part) read as a path from its `cwd`; the `cwd` itself counts for the code freeze. A command made only of programs known not to write files (`cat`, `ls`, `grep`, `git status`/`log`/`diff`, `svod`, …) without a redirection is let through before the store is loaded, so no profile gate runs for it; an interpreter, an in-place edit, `git checkout`/`reset`/`stash`/… or an unknown program counts as a write. The approval mark file is refused to every write, by name (`hook.deny_mark`).
5. **Human mark and questions.** The human mark `svod-human.json` is refused to every write like the approval mark (`hook.deny_human`). A file named `questions.md` below the root of a store (in a work record, not at the root) is refused to `Write`, `Edit`, `MultiEdit`, `apply_patch` and writing `Bash` commands (`hook.deny_questions`, naming both commands): [`svod ask`](#questions-before-work) adds the questions, `svod answer` the answers.
6. **External effects.** Before anything else, and also for commands that only read, each simple command of a `Bash` line (and the script of `sh -c`/`bash -c`) is matched against the standard list: `git push` but `--dry-run`/`-n`; `git merge` and `git rebase` in a main checkout (whose `.git` is a directory: the checkout of a service or of the store, not a worktree; `-C` counts); `gh pr merge`; `gh release` but `list`, `view`, `download`; `npm publish`; `pip upload`, `twine upload` (also `python -m`); `docker push`; `kubectl apply`/`delete`; `terraform apply`/`destroy`; `ssh`; `scp`; `rsync` with a remote (`host:path`, `user@host:path`, `rsync://`). [`external_effects`](#external-effects) adds `deny` patterns and exempts `allow` ones. A match is refused with `hook.deny_external`, whatever the [autonomy](#autonomy), unless the human mark is fresh and its `go` is true: the agent asks in the chat, the person answers with a phrase, the agent runs the command. Without a store the rule is off; a store whose `svod.yaml` does not load gets the standard list and the default phrases. Only `svod.yaml` is read for it, so a read-only command still loads no profile.

The hooks run as the same user as the agent and see only the tool calls the agent makes through them: they stop a careless agent, not one that sets out to write a file the user can write. Profile gates are Python the hooks run on every event: open only stores you trust.

Every git call of one event goes through one run cache (`svod.cache.RunCache`), the gates of the store and the approval mark included, so no call repeats within the event. Rule 3 checks the freeze of the subjects of the key before it asks the workspace gate about the directory: an edit in the work directory of an approved subject costs none of the git calls of the gate. Rule 3 and `svod local` share one code-freeze rule, `svod.position.freeze`.

The hooks are the package `svod.hooks`, each module importing only those before it: `protocol` (the event JSON), `shell` (tokens of a command, programs known to only read, the paths a command names, the python script exception of rule 1), `store` (the store of the session and its loading), `prompt`, `guard` (the `pre-tool` rules), `external` (the external-effects rule) and `events` (the answer to each event, `svod hook`).

## Knowledge

What the team has learned lives in the store as notes, one markdown file per topic under `knowledge/` (`knowledge.dir` of `svod.yaml`), and reaches the agent without being asked for.

**A note** is `knowledge/<topic>.md`, subdirectories allowed, with this frontmatter; a file whose frontmatter has neither `title` nor `tags` is not a note, nor are `INDEX.md` and `README.md`: they are left out of the index, of `list` and of the lines given to the agent.

| field | meaning |
|---|---|
| `title` | name of the note; without it, the first heading, else the file name |
| `tags` | list of tags (a comma separated string is read too); compared without letter case |
| `source` | id of the work the note came from, for example `work/research/x`, or empty |
| `date` | ISO date of the note; the index and the hook lines put the newest first |
| `status` | `current` (also when absent) or `superseded`; a superseded note stays in the index and is never given to the agent |

Notes come from research automatically (the profile template writes them) and by hand through the commands.

**Commands** (`svod knowledge <action>`; tags are separated by commas):

- `index` rewrites the table of every note (title linked to the file, tags, source, date, status; newest first) in `knowledge/INDEX.md` between `<!-- knowledge:index:begin -->` and `<!-- knowledge:index:end -->`. Text outside the markers is kept; a file without them gets them at its end, a missing file is created. Prints `render.written` or `render.current`.
- `add <file> --tags a,b [--title <t>] [--source <id>]` copies a markdown file into `knowledge/<slug of the title>.md`. The fields of its own frontmatter win and the given tags are added to its tags; missing fields are filled in: the title from `--title`, else the first heading, else the file name, `date` today, `status: current`. A file whose frontmatter already holds every field and the tags is copied byte for byte. An existing note is not overwritten (`knowledge.exists`, exit 1).
- `note "<text>" --tags a,b --title "<t>" [--source <id>]` writes `knowledge/<slug of the title>.md`: the frontmatter, the title as a heading and the text.
- `list [--tags a,b]` prints every note as `knowledge.item`, only those sharing a tag with `--tags`; `knowledge.none` when there is none.

`add` and `note` rewrite the index after writing the note. Nothing is committed.

**Given to the agent.** The [hooks](#hooks) add a block headed `hook.knowledge_head` with one line per current note sharing a tag with the work at hand: `- <title> (<path>): <first non-empty line of the body that is not a heading>`, newest first, at most `knowledge.limit_lines` lines. The tags of a work are the `tags` of its frontmatter (`subject.attrs.frontmatter`, given by the `container` and `frontmatter_doc` providers). `session-start` takes the tags of every existing, not archived subject of the pipelines with an `active` block, after the summary, and also when `session_summary` is off; `prompt` takes those of the subjects the prompt names, found as for the positions (keys and exact names). A work without tags adds nothing. `profile_config.agent_context.knowledge: false` turns the block off, and the prompt is then not searched for it.

```yaml
knowledge:
  dir: knowledge
  limit_lines: 20
profile_config:
  agent_context:
    knowledge: true
```

## Evidence

The evidence log keeps the facts of the course of each piece of work, for rules that later look back over many of them. It holds codes, ids, counts, exit codes and seconds: no texts of the plan, of instructions or of commands, no output, no secrets. It does not measure tokens. It is secondary: a failed write is said once on stderr (`svod: the evidence log is not written: <error>`) and never changes the outcome or the exit code of the command.

**Where.** `evidence/<pipeline>/<subject id>.jsonl` under the store root, `/` of the id written as `__` (`evidence/task/openspec__changes__add-login.jsonl`); an event tied to no subject goes to `evidence/store.jsonl`. Lines are only appended, each by one write of one line.

**Line.** One JSON object per event: `{"at": "<ISO time with offset>", "event": "<code>", "subject": "<id>", "pipeline": "<name>", "step": "<step id>" or null, "facts": {...}}`. A fact is a string of at most 100 characters, a number, a bool or null; seconds are rounded to milliseconds.

| event | written by | step | facts |
|---|---|---|---|
| `position_changed` | `status`, when the current step differs from `to` of the last such line (the first status of a subject with a current step writes one) | the current step | `from`, `to`: step ids, null when no step is current (done, or held by an entry) |
| `step_passed` | `status`, with a `position_changed`, for each passed step from `from` up to the new current step | the step | — |
| `unknown_gate` | `status`, for a gate that could not be checked, once per gate and reason at one position | the current step | `gate`, `reason` (its first 100 characters) |
| `approval_recorded` | `approve`, recorded | the approved step | `by`: the approver |
| `approval_drift` | `approve`, refused with `approve.changed_after_mark` | the step | — |
| `approval_refused` | `approve`, any other refusal of an open subject | the step when known | `reason`: the locale key without `approve.` (`no_mark`, `not_ready`, …) |
| `checks_run` | `local checks`, when it returns a result | — | `service` (from the receipt) or `workspace` (the name of the source directory), `code`: exit code or null, `seconds`, `passed` |
| `delivered` | `local deliver`, recorded | — | — |
| `hook_denied` | the `pre-tool` [hook](#hooks), each refusal; the subject is the one holding a path of the call, else the open subject of a key in the name of its work directory, else none | — | `rule`: `approval`, `plan`, `main`, `mark`, `broken`, `external`, `questions` (`hook.deny_questions`) or `human` (`hook.deny_human`), null when the text is none of theirs; `tool` |
| `action_run` | `svod do`, each run that started, through `svod.evidence_log.record_action(root, pipeline, subject_id, action, code, seconds, step=None)` | the first step naming the action, or null | `action`, `code` (the exit code, 124 after the timeout, null when interrupted), `seconds` |

A `not found` or ambiguous `approve`, a `local` command that raises and a hook without a store of the session write nothing.

**svod.yaml.** `evidence.enabled: false` turns the log off. `evidence.commit: false` keeps it local: the first write adds the line `evidence/` to the `.gitignore` of the store when no line names the directory yet.

```yaml
evidence:
  enabled: true
  commit: false
```

**API.** `svod.evidence_log`: `record(root, pipeline, subject_id, event, step=None, **facts)` appends one event and returns whether a line was written (an unknown event code is a `ValueError`); `read(root, pipeline, subject_id)` returns the events in order, leaving out a torn line; `summary(root, pipeline, subject_id)` returns `{"events": {<code>: <count>}, "seconds": <sum of the seconds facts>}`. With `pipeline` or `subject_id` None they use the store log.

## Retrospective

At the end of a work `svod retro <query>` reads the [evidence log](#evidence) and the relations between works and proposes changes of the profile, each with the facts behind it. No model is asked and nothing is applied: the agent shows the list to the person, the person decides, and `svod retro <query> --accept <n>` or `--reject <n>` records the decision, after which the proposal is not shown again.

**Works.** The query resolves as for `status`: every existing subject it names (none, or an ambiguous name, exits with 2). `--all` takes every existing, not archived subject of every pipeline. Every rule runs for every work; a proposal with the same rule, code and subject is listed once.

**Core rules** (`svod.retro.rules.RULES`; the thresholds are constants of that module):

| rule | the decision is about | proposes when | proposal | change |
|---|---|---|---|---|
| `dirty_checks` | the work | at least `DIRTY_MIN` = 2 `checks_run` with `passed: false` on a dirty tree: a `reason` fact containing `dirty`, or, without a reason, a command that exited with 0 (the source check refused the result) | keep what the checks write out of git, or run them with `PYTHONDONTWRITEBYTECODE=1` | `.gitignore`, line `__pycache__/` |
| `approval_drift` | the work | at least `DRIFT_MIN` = 2 `approval_drift` on one step; the variant `approval_drift_questions` when a questions step (a `questions_answered` gate or the role `questions`) was current or passed after the first `approval_recorded` or `approval_drift` of that step | split the contract; ask the questions before writing it | the skill of the step, a note |
| `hook_denials` | the work | at least `DENIALS_MIN` = 3 `hook_denied` of one `rule` in the log of the work; the step is the one current at most of them | the skill of the step does not make the rule clear | the skill of the step, a note |
| `hotfix_cause` | the work named as the cause | at least `HOTFIX_MIN` = 2 subjects with `kind: hotfix` whose `cause` names one existing work; found from that work or from any of its hotfixes | the decision there was weak: a research, or a knowledge note | `<knowledge dir>/<name of the work>.md`, a note |
| `instant_steps` | the pipeline | a step that is not optional (as declared or by [autonomy](#autonomy)) passed in each of the last `INSTANT_WORKS` = 3 works whose log saw it current or passed, current for less than `INSTANT_SECONDS` = 60 s each time, or never | make the step optional | the pipeline file at `steps: <id>`, line `optional: true` |
| `long_step` | the pipeline | in at least `LONG_WORKS` = 3 works one step was current for more than `LONG_SHARE` = 50% of the time of the work | split the step or give it an [action](#actions) | the pipeline file at `steps: <id>`, a note |

The time of a step runs from the `position_changed` onto it to the next one; the step current at the end counts up to the last line of the log. The step of an event without its own is the one current at it. The works of a pipeline are all the logs in `evidence/<pipeline>/`, finished and removed works included, ordered by their last line. The skill of a step is the first skill bound to its role in the [bindings file](#bindings-file), at its `skill_path`; without bindings, or for no step, the pipeline file.

**Relations.** `svod.retro.engine.build_graph(ctx)` builds, once per run, the graph of every existing subject of `ctx.pipelines` by the frontmatter fields `parent`, `cause` and `leads_to` (a reference read as `ref_exists` reads it): `graph.nodes` (id to `(pipeline, subject)`), `graph.target(id, field)` (the id the field of a work names, or empty) and `graph.pointing(field, id)` (every work whose field names the id).

**Output.** Each proposal is `retro.item` (number, rule, what the decision is about, text), `retro.facts` and, with a change, `retro.proposed`; `retro.none` when there is nothing. `--accept <n>` prints `retro.recorded`, then `retro.hint` and a diff to apply by hand (`--- a/<file>`, `+++ b/<file>`, `@@ <anchor> @@` when known, `+<line>`); in this version no file is changed. `--reject <n>` prints `retro.recorded` only. `--note "<text>"` goes with either and is kept in the decision. A rule that raises is left out with `retro.rule_failed` on stderr; the others still run.

**decisions.yaml.** `evidence/decisions.yaml` is a YAML list, one item per decision, appended in order:

| field | meaning |
|---|---|
| `rule` | name of the rule |
| `code` | what tells proposals of the rule apart: `dirty_tree`, a step id, a hook rule, `weak_decision` |
| `subject` | the work, the pipeline (`instant_steps`, `long_step`) or the cause (`hotfix_cause`) the decision is about |
| `decision` | `accepted` or `rejected` |
| `at` | ISO time with offset |
| `note` | the `--note` text, or null |

A proposal with the `rule`, `code` and `subject` of a decision, whatever it was, is not shown again; delete the item to see it again. With `evidence.commit: false` the directory is kept out of git as for the log. A file that is not a list of mappings exits with 2 and `error.load` and is never overwritten.

**Rules of the profile.** `<profile>/retro/<module>.py` declares `RULES = {name: cls}` and is loaded as the [gate modules](#writing-a-custom-gate) are: the key equals `cls.name`; a name taken by a core rule or another module, a value that is not a `Rule` subclass, a missing `RULES` or an import failure exits with 2 and `error.load`; files starting with `_` are skipped.

`Rule` (in `svod.retro.rules`):

| member | meaning |
|---|---|
| `name` | registry name |
| `scope` | `subject` (default) or `pipeline`: what a proposal is about when it does not say |
| `evaluate(self, ctx, subject, log, graph)` | returns a list of `Proposal`; only reads |
| `propose(self, code, facts, change=None, subject=None, text_key=None)` | a `Proposal` of the rule, text key `retro.rule.<name>` unless given |

`Proposal(rule, code, facts, text_key, change=None, subject=None)`: `facts` are shown and fill the texts; `subject` is what the decision is about (filled by `scope` when None); `change` is `{"file": <path relative to the root>, "kind": "note" or "line", "text": <locale key or text>, "anchor": <place in the file, optional>}`, made by `change(file, text, kind="note", anchor=None)`. `text_key` and the change `text` are locale keys filled with the facts, or shown as written when the locale has no such key. `log` holds the work: `entries` (its events), `pipeline`, `subject_id`, `of(pipeline, subject_id)` (another log) and `works()` (every non-empty log of the pipeline, oldest first). Helpers of `svod.retro.rules`: `of_event(entries, event)`, `durations(entries)`, `passed_steps(entries)`, `current_steps(entries)`, `step_at(entries, index)`, `skill_file(ctx, pipeline, step_id)`, `pipeline_file(ctx, pipeline)`.

```python
from svod.retro.rules import Rule, change, of_event


class ManyActionsRule(Rule):
    """A work that ran more than five actions: say which file to look at."""

    name = "many_actions"

    def evaluate(self, ctx, subject, log, graph):
        """One proposal when the log holds more than five action_run lines."""
        count = len(of_event(log.entries, "action_run"))
        if count <= 5:
            return []
        return [self.propose("actions", {"count": count},
                             change("profile/actions/README.md", "retro.change.many_actions"))]


RULES = {ManyActionsRule.name: ManyActionsRule}
```

```yaml
# <profile>/locale/en.yaml
retro:
  rule:
    many_actions: "{count} actions ran in one work: look for a step to merge"
  change:
    many_actions: "Merge the actions that always run together."
```

## Vendored copy

A store may keep its own copy of the engine, so the whole team runs one version through git. How a team installs and updates it is in [updating.md](updating.md).

| path under the store root | content |
|---|---|
| `.svod/lib/svod/` | the engine package, locale files included |
| `.svod/skills/<name>/` | the skills of the release (`svod/templates/local/skills/` of the Svod repository) |
| `.svod/VERSION` | YAML: `version` (the engine version), `source` (git URL or local path it was fetched from), `ref` (the tag or branch taken) |
| `.svod/MANIFEST` | one line per file under `lib/` and `skills/`: its sha256, two spaces, its POSIX path relative to `.svod/`; sorted by path |
| `.svod/.gitignore` | keeps byte-code (`__pycache__/`) out of the repository |

Byte-code files (`__pycache__/`, `*.pyc`) are neither listed nor checked. The integration scripts are not copied. The installed `svod` does not run a copy that differs from its MANIFEST: it runs itself and says so on stderr. The MANIFEST is written by the engine that made the copy, so it catches hand edits, not a copy made to deceive: pin and review the release you install.

**Launcher.** Every `svod` command first looks for the store it works on: `--root`, else upwards from the working directory; for `hook`, the [store of the session](#hooks), from the event read once on stdin. When that store has `.svod/lib/svod` and the running engine is not that package, the command is run again as `python -m svod.cli <the same arguments>` with `.svod/lib` first on `PYTHONPATH` and the event passed on stdin; the exit code is that of the copy. `SVOD_LAUNCHED` (set to the `.svod/lib` handed over to) keeps it from handing over twice. `install` and `update` are never handed over: the engine at hand runs them, so a broken copy can still be replaced. Without a copy the installed engine runs, as before. The hooks registered by the setup scripts call `<python> -m svod.cli`, which goes through the same launcher.

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
