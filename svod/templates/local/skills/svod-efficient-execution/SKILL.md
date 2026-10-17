---
name: svod-efficient-execution
description: Use when a Svod store has tasks/<name>/ with contract.md and testing/plan.yaml, when AGENTS.md points here, or before svod status, svod approve, svod local checks or svod local deliver. Runs one task to completion with one recorded run of checks.
---

# Executing a Svod task

Terms (card, contract, plan, approval, checks, deliver, completion): `docs/local-workflow.md`.

1. Run `svod status tasks/<name>` and do only its next step. Read that task's card, `contract.md` and `testing/plan.yaml`, not other tasks or old logs.
2. While status says the code is frozen, edit only the card, `contract.md` and `testing/plan.yaml`.
3. Show `contract.md` and `testing/plan.yaml` to the person; after they write "Approved", run `svod approve tasks/<name> --step initial_approve`. Never write `approval.yaml` yourself.
4. Change only what `contract.md` allows. An edit of `contract.md` or `testing/plan.yaml` voids the approval: repeat step 3.
5. Choose tests by risk: links for text, affected behavior and regressions for code, positive and negative cases for a new mechanism.
6. Commit in the plan's `workspace` as the project allows, until `git status --porcelain` there is empty. Run `svod local checks tasks/<name>` once: checks refuse dirty source, and a manual run beforehand only doubles the time.
7. On failure read `testing/process/command.log`, fix, commit, run checks again.
8. Run `svod local deliver tasks/<name>`; confirm `svod status tasks/<name>` prints "Local completion recorded".
9. Delegate a subtask only with its own files, check and stop condition; keep its logs in files.
10. Report the result, the commit from `testing/process/receipt.json`, what stayed unchecked and what needs the person's permission: merge, push, deploy, worktree removal.

Process changes: the `svod-pipeline` skill.
