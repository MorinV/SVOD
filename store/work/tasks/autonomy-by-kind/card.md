---
type: card
kind: task
key:
services: [svod]
parent: work/features/0.5-release
tags: [autonomy, engine, template-standard]
status: done
---

# Autonomy level by the kind of work, not only by the pipeline

## Description

`autonomy` in `svod.yaml` accepts `hotfix` as a name besides the pipelines, and the standard template sets `hotfix: autonomous`, but the level is applied per pipeline only: `svod/loader.py` (`apply_autonomy`, `relaxed`) replaces the steps of the whole pipeline once at load, and a kind "has no effect here: the steps are shared by every subject of the pipeline". `svod/position.py` (`position`, `freeze`) then computes the position of a `kind: hotfix` task with the steps of the `task` level, and `svod/status.py` prints `Autonomy: supervised` for it although the store says `autonomous` for hotfixes. `svod/config.py` (`AUTONOMY_KINDS`) is the one place that knows `hotfix` is a kind.

Make the level of a subject the level of its kind when `autonomy` names its frontmatter `kind`, else the level of its pipeline, and apply it where the position and the freeze are computed instead of rewriting the loaded steps.

## Acceptance

- In the standard template a `kind: hotfix` task whose card names its `cause` reaches `implement` with every approval step shown as optional, and `status` prints `Autonomy: autonomous` for it; a `kind: task` record of the same pipeline still prints `Autonomy: supervised` and waits for the contract approval.
- The pre-tool code freeze and `svod local` follow the level of the subject (`svod.position.freeze`).
- `docs/reference.md` (section Autonomy) no longer says the kind key is only validated; the copy in `svod/templates/local/docs/` is equal to it.
- Tests cover a pipeline with two subjects of different kinds.
