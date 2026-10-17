# Brief: Svod 0.5

## Problem

0.4 keeps one agent on one compact local task. A team with several service repositories needs a dispatcher store: projects, features, tasks and research as records, questions answered by a person before the work starts, code in worktrees of the services, checks that a script decides, and a log of how the work went. Everything for that is on `main` under `[Unreleased]`, untagged; nobody can `svod install` it without `--to <ref>`.

## Users

- Teams that keep their work records in a store next to their service repositories.
- Agents (Claude Code, Codex) that run the steps of those records through the hooks and the skills.
- This repository itself: the store in `store/` runs its own development (`docs/dogfooding.md`).

## In scope

- Everything `CHANGELOG.md` lists under `[Unreleased]`: `svod new --template standard`; `services` in `svod.yaml`; the gates `command`, `has_children`, `children_done`, `ref_exists`, `questions_answered`; `svod answer`; actions and `svod do`; `autonomy`; the human mark and the external-effects rule; knowledge notes and `svod knowledge`; the evidence log; `svod approve --confirm`.
- The tasks of `breakdown.md`: autonomy by the kind of work, the go-ahead phrase matched as a command, the `command` gate usable from the standard template.
- The release notes: the **Migration** subsection of 0.5.0 in `CHANGELOG.md`, the `Status` paragraph of `README.md`, the tag `v0.5.0`.

## Out of scope

- Retrospective rules over the evidence log: `work/research/retro-signals` asks which signals are worth them first.
- A tracker, CI of the services, review or deployment gates in the standard template.
- Windows support of the actions.

## Acceptance

- `svod new <dir> --template standard`, `svod validate`, `svod status` and `svod active` work on a fresh store and on `store/` of this repository.
- Every task of `breakdown.md` is done or moved out of the release by the person.
- `CHANGELOG.md` has `## [0.5.0] - <date>` with a **Migration** subsection, the README status names 0.5, the tests pass on Python 3.10 and 3.13.
