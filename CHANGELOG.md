# Changelog

Every release of Svod is listed here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Versions follow [semantic versioning](https://semver.org/); before 1.0 a minor release (0.x.0) may break the format of a store, a patch release (0.x.y) does not.

Each release has a **Migration** subsection: what changes in a store on the way to it. `svod update` applies the automatic part itself and prints this subsection for the rest; `none` means nothing to do.

## [Unreleased]

## [0.8.1] - 2026-10-20

### Added

- Optional `svod-fret` skill with an explicit Docker launcher for genuine FRET
  requirements analysis, readable reports and raw solver evidence. It is
  experimental, not a pipeline gate or a dependency of ordinary SVOD commands.

### Migration

- None. Existing profiles and ordinary SVOD commands are unchanged. The optional
  FRET skill requires an explicit Docker build/run; it is not installed into an
  agent profile automatically. Known sporadic solver crashes remain an experimental
  limitation, not a promise of reliable CI-gate operation.

## [0.8.0] - 2026-10-19

### Added

- Reviewed local execution packages: validate, sequential run, saved compact status,
  user-directed resume and bounded per-step readback. Execution reuses profile
  actions and existing policy checks; private durable state and exact source logs
  stay available locally. Trusted actions are not an OS sandbox.
- Interrupted or uncertain post-spawn outcomes remain unknown and cannot be blindly
  retried. Completed actions are not replayed by continuation.

### Fixed

- Runtime-only `.svod/package-runs` no longer triggers missing-MANIFEST validation.
  Incomplete or modified engine copies still fail integrity checks.

### Migration

- Existing profiles are unchanged; packages require explicit reviewed local action
  declarations. No revision-chain approval mechanism or card-name priority added.
- Runtime archives are not an engine copy. Do not run install/update over runtime
  state without separately preserving it: this release does not change directory
  replacement behavior. Keep backups of local package state and logs.

## [0.7.0] - 2026-10-18

### Added

- Exact-set contract approval packages: `svod approve <query> [<query> ...] --step approve --prepare` displays bound inputs and versions before a fresh human reply; the same selection without `--prepare` records every selected contract once with individual evidence. Package replacement, input drift, expiry and subsets refuse; caught filesystem failures use bounded rollback (not crash atomicity).
- Path-scoped pre-tool writes: instance and uniquely selected record worktrees by
  default; explicit native fresh-human `svod allow <query> --for 30m --path <root>`
  grants (repeatable paths), bound to the record and expiry in protected local git
  metadata. Supported shell destinations are distinguished from read sources;
  unresolved/unsupported effects are refused, not treated as a sandbox. Grants do
  not lift remote consent, approval, questions, code freeze or main-checkout guards.
- Explicit `profile_config.trusted_actions` dispatch for configured start-task/checks
  commands and their checks, bound to a fresh task approval and a protected trust
  snapshot. No filename-only or blanket interpreter exemption. Diagnostics document
  the intentional lack of filesystem/subprocess isolation inside trusted code.

### Fixed

- Native prompt-to-approval identity matching accepts canonical keyless record paths, alongside tracker keys, and consumes only selected named identities. Existing unnamed single-record consent remains single-use; contract packages do not authorize results or external effects.
- Darwin timeout cleanup reaps the owned child within a bounded grace before rechecking a zombie-only group's permission-denied existence probe. Only a subsequent ESRCH proves absence; real permission failures still propagate and live groups retain TERM/KILL cleanup.
- Contract package previews bind configured trusted-action snapshots and record them with the individual approvals; trust drift invalidates the whole package. Knowledge publication and retrospective application remain available through bounded native command routes under the combined write guard.
- Close value-only approval edits, executable-gate trust changes through diagnostics,
  trust-removal legacy fallback, shell `printf -v`/`CDPATH` navigation escapes, and
  unhashed non-shell action helpers. Trust snapshots now cover recursive regular
  action dependencies and reject symlinks/special files; trusted internals remain
  explicitly outside filesystem isolation.
- `svod retro apply <query>` previews concrete, read-only unified diffs; `--accept --plan-token <token>` applies only the exact printed preview's deterministic optional-step, missing `.gitignore` line and exact existing literal line-limit edits. Textual advice stays non-applicable. Plans preserve comments, reject unsafe paths, stale inputs and conflicts, and roll back ordinary batch failures before recording acceptance. Existing review-only acceptance and empirical thresholds are unchanged.
- `svod knowledge supersede <old> --by <new>` preserves note bodies and retires replaced knowledge with cycle/path checks and an index refresh.
- `svod knowledge publish <research>` requests an exact findings snapshot and requires the next fresh human go-ahead before provenance-tagged publication and research close; collisions are refused and matching publication retries are idempotent.
- Opt-in `knowledge.on_edit` context uses only explicit instance-relative `knowledge.file_tags` glob-to-tag lists, bounded to current notes and never replacing a hook denial.

### Changed

- Status JSON v1 omits empty optional values recursively, retaining false, zero and required discriminants. Consumers must tolerate absent optional fields, including empty collections in errors and `next_action`. Child details require `--children`; text output and correctness gates are unchanged.
- `validate` emits non-fatal unused-profile-locale and no-skill warnings without evaluating gates or actions; dynamic locale usage is treated conservatively.
- Test helpers and sibling subprocess fixtures discard inherited `SVOD_*` pollution while retaining explicit fixture overrides; production environment policy is unchanged.

### Migration

- Update JSON consumers to treat missing optional fields as empty or unavailable rather than requiring explicit empty values. Status JSON remains version 1; false, zero and required discriminants are retained. Pass `--children` when child details are needed.
- Trusted action dispatch is opt-in: configure `profile_config.trusted_actions` with exact supported action argv before relying on the native start-task/checks route. Present the changed configuration and action dependencies and obtain fresh contract approval; old approvals do not authorize a new trust snapshot, and later trust changes require reapproval. Trusted code is not filesystem or subprocess isolated.
- Review the standard-template profile merge from `svod update --template standard`, including the research publication step and skeleton. `svod knowledge publish <research>` now prepares an exact findings snapshot; obtain the next fresh human go-ahead before publishing and closing the research. Do not turn historical findings or approvals into publication consent.
- For exact-set contract packages, run `svod approve <query> [<query> ...] --step approve --prepare` before requesting a fresh human reply, then apply that same complete selection. Replacement previews, changed inputs or trusted actions, expiry and membership changes require a new preview and reply. Packages cover contracts only, not results or external effects; existing individual approval records remain history.

## [0.6.0] - 2026-10-17

### Added

- `svod report <query>|--all [--format json]` (`svod.report`): from the evidence log, per record the time in each step (the current one counted until now, marked open), approval rounds, failed checks, hook denials by rule and actions run; per pipeline with `--all` their sums and medians; new core keys `report.*`.
- `svod retro --explain` prints for every rule the facts it saw and the threshold it compared them with, whether it proposed or not (`retro.explain*`); the thresholds are per-rule defaults (`Rule.threshold`, `Rule.reaches`) that `retro: {thresholds: {<rule>: <n>}}` in `svod.yaml` overrides, 0 turning a rule off.
- `svod next <query> [--format json]`: the position `svod status` shows, in one line (`<id>: <next step> (skill <name>)`, or `run svod do <action> <id>` for a step with an action) or as JSON `{id, step, text, skill, action, run}`; rendered by `svod.render.one_line` from the same collection, never computed again; new core keys `next.*`.
- `svod record new <pipeline> <name> [--services] [--parent] [--kind] [--tags] [--key]` (`svod.records`): copies `<profile>/records/<pipeline>/` into the first root of the pipeline's subject provider with `{name}`, `{kind}`, `{key}`, `{services}`, `{parent}`, `{tags}`, `{date}` filled, refusing a record that exists; the standard template ships only `card.md` for task, feature, project and research (no questions file or step artifact, so a new record does not skip the questions and contract steps; an instance may add files) and `start-task.sh` uses the command instead of writing `card.md` itself; new core keys `record.*`. A standard store made before gets `profile/records/` from `svod update` (the profile merge); its own `start-task.sh` keeps working as it is.
- `svod setup <dir>` makes an instance in one command: `svod new`, `git init` with a first commit, `svod install` from the source the running `svod` was installed from (`direct_url.json`, else `--from`), `svod init --wizard` with its flags or at a terminal, and the hooks; the README quickstart opens with it.
- `svod update` merges the profile three ways after replacing the engine: `svod.yaml`, `AGENTS.md`, `profile/` and `skills/` of the store against the templates of the old and new engines (`git merge-file`); clean merges are written, conflicts get git markers and are listed; `--no-profile` skips it, `--template <name>` names the template. `.svod/VERSION` records `template` and `template_version` (`svod install` identifies the template by the profile), `svod validate` names every file left with a conflict marker first, and `svod doctor` warns (`template`) when the profile follows an older template than the engine's.

### Changed

- A cheap `svod status`: `status --format json` carries the `command` gate's `code`, `cached`, `stale` and `age`; the cache key of the `command` gate leaves out `evidence/`, `*.log`, `knowledge/INDEX.md` and the new `cache_ignore` of `svod.yaml`; the gate's new `on: current` (default; `always` as before) runs the command only while its step is current or under `svod status --fresh`, and elsewhere shows the last result with `stale`, `age` and the mark `status.mark.stale` (`status.mark.not_run` when it never ran); 50 records take about 0.2 s instead of 3 s.
- `integrations/setup-codex.sh --project <store>` registers the three hooks in `<store>/.codex/hooks.json` and links the skills to `<store>/.codex/skills`; `svod doctor` also reads `<store>/.codex/hooks.json` and `$CODEX_HOME/hooks.json` and checks the format of every hooks file (`doctor.hooks_format`; a Codex file Codex would refuse fails).

- Session start gives the session index (`svod.index`): the open records of every pipeline from their frontmatter and first heading, children under parents, at most `agent_context.index_lines` (40), and the hint to `svod status`/`svod next` a record; no position, gate, command, git or knowledge note. `agent_context.session_start: index|summary|off` chooses it, `index` by default, also in a store that sets nothing (set `summary` to keep the old summary); `session_summary: true|false` still means `summary|off`, a contradiction is a load error. New core keys `index.*`.
- The sources hold no store any more: the work on Svod is recorded in the instance [MorinV/svod-rnd](https://github.com/MorinV/svod-rnd), a standard-template store next to a clone of this repository, as every user's instance is.
- `svod new` makes a `standard` store by default; `--template local` is a load error naming `standard` (`new.template_retired`).
- The argv runner (no shell, a timeout, the process group stopped, the output tail) is `svod.run`, shared by the `command` gate and the actions.
- The engine skills `svod-pipeline` and `svod-efficient-execution` live in `svod/skills/` (in the package data); the vendored copy and the setup scripts take them from there, and they name no `svod local` command.

- Releases are made by CI: `.github/workflows/release.yml` creates the annotated tag `v<version>` and a GitHub Release with the `## [<version>]` section of this changelog when a push to `main` changes `svod/__init__.py` (no PyPI); the section is read by `svod/changelog.py` through `.github/scripts/release_notes.py`. Nobody pushes a tag by hand any more. `workflow_dispatch` with `ref` releases a version already on `main`: run it for `v0.4.0` (8a9851f) and then `v0.5.0` (578a9d5), whose tags were never pushed; see `docs/updating.md`.

### Removed

- The local template (`svod/templates/local`, its copies of `docs/` and `tests/test_copies.py`), `svod local prepare|checks|verify|deliver`, the modules `local_workflow`, `local_evidence` and `local_runner` with `LocalWorkflowError` and the evidence-log decorators of the local commands, and `docs/local-workflow.md`.

### Migration

An instance made from the local template recreates itself from the standard one: `svod new <directory> --template standard`, copy its records into `work/`, then `svod install` there. Run the setup scripts again so the skill links of a clone point at `svod/skills/`.

A store installed by 0.5 has no `template` in `.svod/VERSION`: run `svod update --template standard` once, so the profile merge has its base; `svod doctor` says so until then.

## [0.5.0] - 2026-10-17

### Added

- Tree of works: `active.children` nests open children (by `parent`) under their parent in `svod active` at any depth, `svod status` lists a parent's children after the marks (`status.children`, `status.child`, `status.child_done`, `status.child_open`) and `--format json` gives each position `children`; shared enumeration in `svod.relations`.
- Core gate `command`: a script (linter, tests, link check) decides a step, run without a shell in a service work directory or a store directory; its result is cached in the git common dir by HEAD, status, changed content and `watch`, so `status` does not rerun it until the source changes.
- `services` in `svod.yaml` (`ctx.config.services`), the gates `children_done`, `has_children`, `ref_exists` over relations between works (`parent`, `cause`, `leads_to`) and `questions_answered` over a questions file, and `svod answer <query> --q <n> <text>`, which records a person's answer only while a fresh human mark `svod-human.json` is present.
- Actions: `svod do <action> <query> [-- args]` runs the bash script `<profile>/actions/<action>.sh` for one subject in the store root with `SVOD_*` variables (id, key, pipeline, kind, services, frontmatter, service paths), `svod do --list` lists them, a step may declare `action:` (checked by `validate`, offered by `status` as `status.run`); new core keys `status.run` and `do.*`.
- Knowledge: notes in `knowledge/<topic>.md` (`title`, `tags`, `source`, `date`, `status`), `svod knowledge index|add|note|list` with the index in `knowledge/INDEX.md` between markers, and the hooks add the current notes sharing a tag with the work at hand (`knowledge` in `svod.yaml`, `profile_config.agent_context.knowledge`).
- The evidence log `evidence/<pipeline>/<subject>.jsonl` (`svod.evidence_log`): `status`, `approve`, `local checks`/`deliver` and the `pre-tool` hook append one JSON line per event (position changes, passed steps, approvals, checks, deliveries, refusals, unchecked gates), codes and numbers only; `evidence: {enabled, commit}` in `svod.yaml`, see the reference.
- `svod new <dir> --template standard`: a store next to the service repositories with project, feature, task (hotfix by `kind`) and research pipelines on `card.md` records in `work/`, one skill per pipeline plus `svod-questions`, and the actions `start-task.sh`, `checks.sh`, `pr.sh`, `cleanup.sh` in `profile/actions/`.
- `store/`: Svod's own work runs in a standard-template store inside this repository (the 0.5 release feature, its tasks, a research on retrospective signals, a knowledge note), checked by `tests/test_dogfood_store.py`; how to use it and the findings of the first run are in `docs/dogfooding.md`.
- `svod approve <query> --confirm` records an approval that a person confirms with y at a terminal when there is no fresh mark, for agents without a prompt hook; all YAML is read by one loader that refuses repeated keys, and the approval fields are read and written only through `svod.approval.read_fields` and `write_fields`.
- `svod retro <query>|--all` proposes profile changes from the evidence log and the relations between works, with the facts behind each (six core rules `svod.retro.rules`, profile rules in `<profile>/retro/*.py`); `--accept <n>`/`--reject <n>` keep the decision in `evidence/decisions.yaml` and the proposal is not shown again; nothing is applied and no model is asked.
- `svod init --wizard` asks (or takes as flags `--service`, `--autonomy`, `--checks`, `--hooks`) the login, services, autonomy, check commands (`profile_config.checks`, given to actions as `SVOD_CHECKS_<NAME>`) and hook registration, editing `svod.yaml` line by line with its comments kept; `svod doctor [--format json]` checks the config, services, hooks, the copy of the engine, the newest release, the evidence log, the knowledge index and the local config, one ok/warn/fail line each, exit 1 on a fail.
- `autonomy` in `svod.yaml` (guided, supervised, autonomous per pipeline) makes approval steps optional as loaded and `status` prints `Autonomy: <level>`; the prompt hook leaves the human mark `svod-human.json` on every reply of a person; `pre-tool` refuses writes of that mark and of `questions.md` of a work record, and holds commands with an external effect (`git push`, publish, deploy, remote hosts; `external_effects` in `svod.yaml`) until a fresh reply says go ahead.
- `svod ask <query> "<question>" [--context <text>]` adds the agent's question to the questions file (`svod ask <query> --none`: nothing to ask; new core keys `ask.*`, `hook.deny_questions` names both commands); the standard template freezes code: `workspace_gate: work_tree` reads the worktrees of `work.yaml`, the task pipeline's `key_gate: work_id` the record id-slug ending a worktree name (`app-work+tasks+login`), its questions step says how many answers are missing (`work.step.questions_unanswered`), and its unread `workspaces: ..` is gone.

### Changed

- Actions: `svod do` sets `SVOD_ACTION`, refuses an action of a step not reached yet (`do.not_current`) unless `--force`, takes `--timeout` and writes `action_run` to the evidence log; `hook_denied` tells `questions` and `human` apart; the `command` gate replaces `{id}`, `{path}`, `{root}` in argv and gives a script the action variables; the standard template's scripts let the record argument win over inherited `SVOD_*`, put worktrees at `<service>-<pipeline>-<name>` next to the service checkout on branch `<pipeline>/<name>` with a relative path in `work.yaml`, and `checks.sh --check` backs a `command` gate of the checks and integration steps.
- `autonomy` applies the level of the kind of work (`hotfix`) of a subject before that of its pipeline, in `position()` and `freeze()`; a go-ahead phrase of `external_effects.phrases` counts only at the start of a reply, alone on a line or before closing punctuation, and not after a negation on its line; `session-start` adds the knowledge notes also when `session_summary` is off.
- The check for a missing PyYAML in `svod` and in the hooks is gone: the engine cannot be imported without it, so the branch never ran. `ruff check svod tests` and `mypy svod` are clean.
- The `merged` gate of the task example leaves out sibling repositories without a remote default branch instead of printing `could not check` for each; `vendor`, `frontmatter` and `local_workflow` read YAML through `svod.yamlio` (repeated keys refused there too, `LoadError` in `local_workflow.ERRORS`); the hook answer no longer carries an unreachable branch for a missing PyYAML, and the reference no longer promises one.
- Removed the unused `gates.build_registry`, `ApprovalGate.effective_bind` and `document.stale_blocks` with the tests that were their only callers.
- `svod.hooks` is a package (`protocol`, `shell`, `store`, `prompt`, `guard`, `events`) with the same public names; the pre-tool code freeze uses `svod.position.freeze`, and `hook.approval_marked_unnamed` is a core locale key (`svod.keys`).
- Code style: `ruff check` passes on the repository config outside three files under parallel edit, `mypy --ignore-missing-imports svod` passes, the core and hook modules carry type annotations, and the local workflow raises `LocalWorkflowError` and `PolicyError` (`svod.errors`, subclasses of both `SvodError` and `ValueError`) instead of bare `ValueError`.
- Polish of the first dogfooding run: `knowledge/README.md` and files whose frontmatter has neither `title` nor `tags` are not knowledge notes; the setup scripts link the store's own `skills/*/SKILL.md` before `.svod/skills` and the clone's, print `-> engine: <file>` and take `--engine <clone>` to put a clone on `PYTHONPATH` of the hooks; the example task of the standard template is `status: archived`, so a new store has no open work; the reference has one paragraph on the human mark.

### Migration

A store made by 0.4 keeps working: every new key of `svod.yaml` (`services`, `autonomy`, `external_effects`, `evidence`, `knowledge`, `workspace_gate`) is optional. The standard template is new: `svod new <dir> --template standard`. A store made from the standard template before this release should copy the template's `profile/actions`, `profile/gates/work.py`, pipelines, locale and skills again and add `workspace_gate: work_tree` to its `svod.yaml`: the worktree naming, the questions step and the code freeze changed. Run the setup scripts again so the hooks and the skills of the store are registered.

## [0.4.0] - 2026-10-17

### Added

- Tests run in GitHub Actions on Python 3.10 and 3.13.
- A test keeps the docs of the local template equal to `docs/`, so the copies cannot drift.
- The reference documents `GitResult`, the type `ctx.cache.git` returns to a custom gate.

### Changed

- The pre-tool hook checks shell commands against the code freeze and the read-only main checkout through the paths they name, not only file edits: a redirection, an interpreter, an in-place edit or `git checkout` into a frozen work directory is refused like an edit; commands known to only read pass. The approval mark file is refused to every write.
- A store that does not load no longer lets every write through: writes outside the store are refused until it loads, writes inside it stay allowed so it can be repaired.
- The installed `svod` does not run a copy of the engine that differs from its MANIFEST: it runs itself and says so.
- A gate that raises no longer fails `status` or a hook: the outcome is UNKNOWN with the reason `gate <name> raised <error>`, the step stays unpassed and the status says why.
- `status` marks every step: a step without a labelled gate is shown as one mark by its `title` or `id`, so a profile without labels still shows where the work stands.
- A step text ending with a period is no longer followed by a second one in the next-step line.
- `svod active` says when no pipeline declares `active` instead of printing nothing.
- `svod local checks` runs the command with `PYTHONDONTWRITEBYTECODE=1`, so the recommended test command leaves the checkout clean.
- The local template's next-step texts name the command to run, show the gate's detail (for example `source workspace is dirty`) and tell a changed contract from a missing approval.
- `examples/` and the root `skills/` are gone: the templates under `svod/templates/` are the one copy, `svod new --template task|local` creates a store from them, the vendored copy and the setup scripts take the skills from `svod/templates/local/skills/`.
- The setup scripts say that without a store argument the hooks guard only sessions started inside a store.
- README and the reference say what the hooks are: guard rails against a careless agent, not a security boundary against a determined one.
- The package version is declared once, in `svod/__init__.py`; `pyproject.toml` reads it from there.

- One code-freeze rule, `position.freeze()`, behind the readiness check of local `checks`; applicability and single-gate evaluation live in `pipeline`, so `workflow_policy` no longer imports `position` or `approve`.
- Tests call the CLI in process (only launcher, stdin and setup-script tests start a real `svod`), check texts through locale keys, and CI fails under 85% line coverage.
- The local template lists its tasks in `svod active` and ships `tasks/example/` (card, contract, plan with commented placeholders); a typo or non-bool value in `profile_config.agent_context` is a load error naming the key; the reference says where `field` gets the frontmatter for each provider.
- The local template's `AGENTS.md`, skills and `docs/local-workflow.md` are rewritten as short imperative steps naming a command and a file; the workflow opens with a glossary (card, contract, plan, approval, checks, deliver, completion) and is the one place that explains `command: null`.
- Hooks are cheaper and quieter: a shell command that only reads is answered before the store loads; every git call of an event goes through one cache (the approval mark included), the main checkout is recognised by its `.git` directory, and an edit in an approved work directory skips the workspace gate; the approval notice names the keys and their `svod approve` command (`hook.approval_marked`, new `hook.approval_marked_unnamed`), and the positions next to it no longer ask to wait for that approval (task template: `task.step.approve_marked`).
- The examples, the skills and the docs are checked against the packaged templates by a test, so the copies cannot drift.
- The Russian locale (core and both templates) uses one set of terms (стор, чекаут, слияние/слито, одобрение, субъект), marks status as `+ - ?` like English, and a test keeps every en/ru pair on the same keys and placeholders.
- Removed the unused `render.missing_text` and `versions.tag_of`; added a `[tool.ruff]` configuration (line length 100, rules E, F, W, B, UP, SIM) without mass reformatting.
- `setup-claude.sh --project <store>` registers the hooks in the store's `.claude/settings.json` only (without it the script warns that the hooks run in every project); the hooks call `<absolute python> -m svod.cli` instead of the path of a `svod` script, and both setup scripts are tested end to end and pass shellcheck.

### Migration

Run the setup scripts again (`integrations/setup-claude.sh`, `integrations/setup-codex.sh`, with the store as the argument as before): the skills of a Svod clone moved from `skills/` to `svod/templates/local/skills/`, and the links `~/.claude/skills/svod-*` (and those of Codex) made by 0.3.0 from a clone point at the removed directory. Links to the copy of a store (`.svod/skills/`) keep working. Nothing else: no store file, profile or approval changes.

## [0.3.0] - 2026-10-17

### Added

- A portable compact local workflow: contract, selected native human approval, real command checks on clean Git source and durable local completion. Runtime helpers ship in the engine, without a project-specific integration.
- `svod new <directory> --template local` creates a new store from packaged assets; `--template task` keeps the OpenSpec/Git example available.
- `svod local prepare|checks|verify|deliver <query>` and `status --format json`, including a bounded advisory next action and allowlisted facts without free-form logs or approval identity.
- Declarative step/gate applicability (`when`), semantic approval `purpose`, `approve --step` and independent consumption of named approval keys.
- Optional hook context controls and a reusable efficient-execution skill. Silencing context does not disable human approval marking or edit guards.

### Changed

- Approvals require ready preceding stages and reject bound inputs changed after the human answer. Archived subjects with an archive terminal gate are presented as history without replaying live checks.
- Exact store-relative addressing for directory/OpenSpec subjects. Process-change guidance selects verification by changed risk rather than imposing extra ceremony.

### Migration

Update the engine before using new YAML fields or commands. Existing profiles are not rewritten; the local template is opt-in. Re-present a plan and obtain a fresh real approval if readiness or input timestamps reject an earlier answer. No historical approval/evidence import, tracker, service CI, review or deployment gate is installed. Local completion identifies a checked commit, not merge/push/deploy; `command: null` is not a passed test. No release tag is created by changing this version.

## [0.2.0] - 2026-10-05

### Added

- A store can keep its own copy of the engine in `.svod/`, one version for the whole team through git: `svod install` puts it there, `svod update` replaces it with another release, migrates the store and shows these notes.
- The installed `svod` hands every command over to the copy of the store it runs in, hooks included.
- `svod validate` reports files of the copy changed by hand, against `.svod/MANIFEST`.
- At session start the hooks say when a newer release than the copy is out, at most once a day; `update_check: false` in `svod.yaml` turns it off.
- `svod migrate --since <version>` and `svod --version`.
- The setup scripts link the skills of the copy of the store when it has one.

### Migration

none

## [0.1.0] - 2026-10-05

### Added

- The first public cut: declarative pipelines, gates, subject providers, positions, the active summary, approvals, rendering, hooks for Claude Code and Codex, the example task profile.

### Migration

none
