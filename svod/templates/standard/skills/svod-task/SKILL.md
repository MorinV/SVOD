---
name: svod-task
description: Run task and hotfix steps in their owning work paths.
---

# Running a task

1. Run `svod status <record>`; do only its next step. Use canonical paths. Tasks: `<owner>/tasks/<name>` under project/feature (including project features), otherwise `work/headless/tasks/<name>`; hotfix: `work/hotfix/<name>`.
2. card: `svod record new task <name> --parent <owner> --services app`; omit --parent for headless, --kind hotfix selects hotfix. Alternatively copy `work/headless/tasks/example/`, set status: open. Fill kind, services, containment parent, description, acceptance; hotfix needs cause. Research provenance is not parent.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. contract: write contract.md: result, service boundaries, effects, checks, risks. Hotfix skips contract/approval.
5. approve: show card.md, questions.md, contract.md; after fresh "Approved": `svod approve <record> --step approve`. Never edit approval.yaml; changed binds require fresh consent.
6. implement: `bash profile/actions/start-task.sh <record>`; code only in work.yaml worktrees within contract. Commit with task key only when authorized.
7. checks: `bash profile/actions/checks.sh <record>` after required commits; fix failures from checks.log, rerun. Never handwrite checks.md.
8. deliver: `bash profile/actions/pr.sh <record>`; ask before push/PR; after "Approved": `svod approve <record> --step deliver`.
9. After merge set status: done; ask before `bash profile/actions/cleanup.sh <record>` removes worktrees.
10. Write outcome.yaml: schema_version: 1, actual, evidence. Read `svod plan summary <owner>`; explicitly verify then `svod plan confirm <owner> --criterion <id> --result pass --actual '<result>' --evidence <file-or-URL>`. Done is not acceptance/consent; reopening requires review.
