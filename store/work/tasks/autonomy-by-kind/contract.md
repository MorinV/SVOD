# Contract: autonomy-by-kind

<!--
What the person approves together with card.md and questions.md
(svod approve work/tasks/autonomy-by-kind --step approve). Any edit afterwards voids the approval.
Draft: the answers to questions.md may change the rule below.
-->

## Result

The autonomy level of a subject is the level of its frontmatter `kind` when `autonomy` names it, else the level of its pipeline. Positions, the code freeze, `svod local` and the `status` line `Autonomy: <level>` use the level of the subject.

## Boundaries

- `svod`: `svod/loader.py` (keep the declared steps; no more rewriting at load), `svod/position.py` (relax the approval steps per subject), `svod/status.py` (the printed level), `svod/config.py` if the kinds change; their tests; `docs/reference.md` and its copy in `svod/templates/local/docs/`; `CHANGELOG.md`.
- Not touched: the pipelines and locale of the templates, the approval gate, the hooks other than through `svod.position.freeze`.

## Effects

Commits on the task branch in the worktree of `svod`. Push and the pull request only after the person says so.

## Checks

`bash profile/actions/checks.sh work/tasks/autonomy-by-kind` runs `python3 -m pytest -q` in the worktree, with new tests for two subjects of one pipeline at different levels.

## Risks

`validate` and `render` read the loaded steps without a subject: they keep showing the declared steps, so the diagram of a pipeline no longer shows a relaxed approval as optional. Say so in the reference.
