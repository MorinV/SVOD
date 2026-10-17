# Changelog

Every release of Svod is listed here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Versions follow [semantic versioning](https://semver.org/); before 1.0 a minor release (0.x.0) may break the format of a store, a patch release (0.x.y) does not.

Each release has a **Migration** subsection: what changes in a store on the way to it. `svod update` applies the automatic part itself and prints this subsection for the rest; `none` means nothing to do.

## [Unreleased]

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
