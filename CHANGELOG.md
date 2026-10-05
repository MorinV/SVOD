# Changelog

Every release of Svod is listed here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Versions follow [semantic versioning](https://semver.org/); before 1.0 a minor release (0.x.0) may break the format of a store, a patch release (0.x.y) does not.

Each release has a **Migration** subsection: what changes in a store on the way to it. `svod update` applies the automatic part itself and prints this subsection for the rest; `none` means nothing to do.

## [Unreleased]

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
