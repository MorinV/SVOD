# Contract: command-gate-in-template

<!--
What the person approves together with card.md and questions.md
(svod approve work/tasks/command-gate-in-template --step approve). Any edit afterwards voids the approval.
Per questions.md: the engine may change too; the template ships a workspace gate over work.yaml.
-->

## Result

The `checks` step of a task and the `integration` step of a feature in the standard template are decided by a script, not only by the presence of `checks.md`: the core gate `command` runs `bash profile/actions/checks.sh {id} --check` in the store root, which repeats the check command of every service of the record in its worktree (`work.yaml`) or checkout and exits 0 only when all pass, writing nothing. The gate's result is cached by the state of the store repository. Without services declared the script exits 0 and says so, so a fresh store is not blocked; without `checks.md` it exits 1 without running anything.

## Boundaries

- `svod`: `svod/command_gate.py` (substitutions `{id}`, `{path}`, `{root}` in argv; the action environment given to the command), `svod/actions.py` (`SVOD_ACTION`, the record argument before inherited variables), `svod/templates/standard/profile/actions/checks.sh` and `_env.sh` (`--check`), `svod/templates/standard/profile/pipelines/task.yaml` and `feature.yaml` (the gate rows), the template README, `tests/test_command_gate.py`, `tests/test_standard_template.py`, `docs/reference.md` and its copy, `CHANGELOG.md`.
- Not touched: the approval gate, the hooks, the other templates.

## Effects

Commits on the task branch in the worktree of `svod`. Push and the pull request only after the person says so.

## Checks

`bash profile/actions/checks.sh work/tasks/command-gate-in-template` runs `python3 -m pytest -q` in the worktree: the template test passes a task to done with the gate on, and a `command` gate test covers the substitutions and the cache.

## Risks

The gate runs the script on every `status` and `active` after any change of the store, the evidence log included; a slow check command slows every status. The cache does not see a new commit in a service made outside the store until `checks.sh` runs again and rewrites `checks.md`.
