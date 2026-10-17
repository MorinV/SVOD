# Changelog

Every release of Svod is listed here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Versions follow [semantic versioning](https://semver.org/); before 1.0 a minor release (0.x.0) may break the format of a store, a patch release (0.x.y) does not.

Each release has a **Migration** subsection: what changes in a store on the way to it. `svod update` applies the automatic part itself and prints this subsection for the rest; `none` means nothing to do.

## [Unreleased]

### Added

- Actions: `svod do <action> <query> [-- args]` runs the bash script `<profile>/actions/<action>.sh` for one subject in the store root with `SVOD_*` variables (id, key, pipeline, kind, services, frontmatter, service paths), `svod do --list` lists them, a step may declare `action:` (checked by `validate`, offered by `status` as `status.run`); new core keys `status.run` and `do.*`.
- `svod approve <query> --confirm` records an approval that a person confirms with y at a terminal when there is no fresh mark, for agents without a prompt hook; all YAML is read by one loader that refuses repeated keys, and the approval fields are read and written only through `svod.approval.read_fields` and `write_fields`.

### Changed

- The check for a missing PyYAML in `svod` and in the hooks is gone: the engine cannot be imported without it, so the branch never ran. `ruff check svod tests` and `mypy svod` are clean.
- The `merged` gate of the task example leaves out sibling repositories without a remote default branch instead of printing `could not check` for each; `vendor`, `frontmatter` and `local_workflow` read YAML through `svod.yamlio` (repeated keys refused there too, `LoadError` in `local_workflow.ERRORS`); the hook answer no longer carries an unreachable branch for a missing PyYAML, and the reference no longer promises one.
- Removed the unused `gates.build_registry`, `ApprovalGate.effective_bind` and `document.stale_blocks` with the tests that were their only callers.
- `svod.hooks` is a package (`protocol`, `shell`, `store`, `prompt`, `guard`, `events`) with the same public names; the pre-tool code freeze uses `svod.position.freeze`, and `hook.approval_marked_unnamed` is a core locale key (`svod.keys`).
- Code style: `ruff check` passes on the repository config outside three files under parallel edit, `mypy --ignore-missing-imports svod` passes, the core and hook modules carry type annotations, and the local workflow raises `LocalWorkflowError` and `PolicyError` (`svod.errors`, subclasses of both `SvodError` and `ValueError`) instead of bare `ValueError`.

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
