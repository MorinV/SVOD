# Changelog

Every release of Svod is listed here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Versions follow [semantic versioning](https://semver.org/); before 1.0 a minor release (0.x.0) may break the format of a store, a patch release (0.x.y) does not.

Each release has a **Migration** subsection: what changes in a store on the way to it. `svod update` applies the automatic part itself and prints this subsection for the rest; `none` means nothing to do.

## [Unreleased]

### Changed

- The installed `svod` does not run a copy of the engine that differs from its MANIFEST: it runs itself and says so.
- `examples/` and the root `skills/` are gone: the templates under `svod/templates/` are the one copy, `svod new --template task|local` creates a store from them, the vendored copy and the setup scripts take the skills from there.
- README and the reference say what the hooks are: guard rails against a careless agent, not a security boundary against a determined one.
- Tests run in GitHub Actions on Python 3.10 and 3.13.
- The pre-tool hook checks shell commands against the code freeze and the read-only main checkout through the paths they name, not only file edits: a redirection, an interpreter, an in-place edit or `git checkout` into a frozen work directory is refused like an edit; commands known to only read pass. The approval mark file is refused to every write.
- A store that does not load no longer lets every write through: writes outside the store are refused until it loads, writes inside it stay allowed so it can be repaired.
- `svod local checks` runs the command with `PYTHONDONTWRITEBYTECODE=1`, so the recommended test command leaves the checkout clean.
- The local template's next-step texts name the command to run, show the gate's detail (for example `source workspace is dirty`) and tell a changed contract from a missing approval.
- The setup scripts say that without a store argument the hooks guard only sessions started inside a store.
- A gate that raises no longer fails `status` or a hook: the outcome is UNKNOWN with the reason `gate <name> raised <error>`, the step stays unpassed and the status says why.
- `status` marks every step: a step without a labelled gate is shown as one mark by its `title` or `id`, so a profile without labels still shows where the work stands.
- A step text ending with a period is no longer followed by a second one in the next-step line.
- `svod active` says when no pipeline declares `active` instead of printing nothing.
- The reference documents `GitResult`, the type `ctx.cache.git` returns to a custom gate.
- The examples, the skills and the docs are checked against the packaged templates by a test, so the copies cannot drift.
- Removed the unused `render.missing_text` and `versions.tag_of`; added a `[tool.ruff]` configuration (line length 100, rules E, F, W, B, UP, SIM) without mass reformatting.

### Migration

none

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
