---
name: svod-task
description: Use for a record in work/tasks/<name>/ (kind task or hotfix) when svod status names a task step - card, contract, approve, implement, checks, deliver - or before start-task.sh, checks.sh, pr.sh or cleanup.sh.
---

# Running a task

1. Run `svod status work/tasks/<name>` and do only its next step.
2. card: copy `work/tasks/example/` and set `status: open`, or run `bash profile/actions/start-task.sh work/tasks/<name>`; fill `card.md`: `kind`, `services`, `parent`, a hotfix also `cause`; description and acceptance.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. contract: write `contract.md`: result, boundaries per service, effects, checks, risks. A hotfix skips this and the approval.
5. approve: show `card.md`, `questions.md` and `contract.md`; after the person writes "Approved", run `svod approve work/tasks/<name> --step approve`. Never write `approval.yaml`; editing a bound file voids the approval.
6. implement: run `bash profile/actions/start-task.sh work/tasks/<name>`; change code only in the worktrees of `work.yaml` and only what `contract.md` allows; commit with the task key.
7. checks: commit everything, run `bash profile/actions/checks.sh work/tasks/<name>`; on failure read `checks.log`, fix, commit, run again. Never write `checks.md` by hand.
8. deliver: print the PR text with `bash profile/actions/pr.sh work/tasks/<name>`; ask the person before push or a PR; after "Approved" run `svod approve work/tasks/<name> --step deliver`.
9. After the merge set `status: done` in `card.md`, then run `bash profile/actions/cleanup.sh work/tasks/<name>`.
10. Write `outcome.yaml`: schema_version: 1, actual, evidence (files/URLs). Read `svod plan summary <owner>`; verify then `svod plan confirm <owner> --criterion <id> --result pass --actual '<result>' --evidence <file-or-URL>`. Done/partial contribution is not acceptance/consent; reopened work needs review.
