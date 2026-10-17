---
type: card
kind: task
key:
services: [svod]
parent: work/features/0.5-release
tags: [template-standard, command-gate, checks]
status: done
---

# Turn on the command gate in the standard template when services are declared

## Description

The `checks` step of `profile/pipelines/task.yaml` and the `integration` step of `feature.yaml` in `svod/templates/standard/` pass on the file `checks.md`, which `profile/actions/checks.sh` writes. Both carry a commented line to let the `command` gate decide instead, `{ gate: command, params: { argv: [bash, profile/actions/checks.sh], service: app } }`. Uncommented, that line cannot work:

- with `service`, the command runs in the service checkout (`svod/command_gate.py`, `CommandGate.directory`), where `profile/actions/checks.sh` does not exist;
- the argv is fixed per pipeline and the gate passes no subject to the command, while `checks.sh` needs `work/<kind>/<name>` (`_env.sh` exits 2 without it);
- the standard `svod.yaml` names no `workspace_gate`, so the gate never finds the task worktree and checks the main checkout of the service;
- `checks.sh` writes `checks.md` and `checks.log` into the store: with `cwd` in the store the result is never cached, since the command changed its source.

Make the template's checks decidable by a command once `services` are declared, without editing the pipelines by hand.

## Acceptance

- A store made by `svod new --template standard` with `services: {app: ../app}` and a task with `services: [app]` gets `checks pass` / `checks fail` from the tests of the task worktree, cached until the worktree changes.
- A store without `services` behaves as today (the `checks.md` mark).
- `svod validate` is green on both; `tests/test_standard_template.py` covers both.
