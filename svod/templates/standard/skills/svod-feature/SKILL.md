---
name: svod-feature
description: Use for a record in work/features/<name>/ when svod status names a feature step - brief, breakdown, approve, children, integration, deliver.
---

# Running a feature

1. Run `svod status work/features/<name>` and do only its next step.
2. brief: write `card.md` (frontmatter `type: card`, `services`, `parent`, `tags`) and `brief.md`: problem, users, scope in and out, acceptance.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. breakdown: fill scaffolded `plan.yaml` (schema_version: 1, expected, nodes, criteria). Nodes have stable id/title/expected, optional record/parent/dependencies; criteria have id/statement/verification/works, optional owner+criterion dependencies. Make tasks with `parent: work/features/<name>` and link records. Linked state/actual come only from records. Run `svod plan validate <record>`; breakdown.md is history/derived only.
5. approve: show `brief.md`, `questions.md` and `plan.yaml`; after the person writes "Approved", run `svod approve work/features/<name> --step approve`. Never write `approval.yaml`. Changed binds require fresh consent; acceptance/outcome/canvas are not plan definitions.
6. children: take each task to done with `skills/svod-task/SKILL.md`; check them with `svod status work/tasks/<task>`.
7. integration: after the tasks are merged, run `bash profile/actions/checks.sh work/features/<name>` on the service checkouts; on failure read `checks.log` and open a hotfix task.
8. deliver: write `outcome.yaml` with schema_version: 1, actual and evidence list. Read `svod plan summary <record>`. Explicitly verify criteria via `svod plan confirm <record> --criterion <id> --result pass --actual '<observed result>' --evidence <file-or-URL>`; this is not human consent. Done tasks do not auto-accept criteria. Show primary outcome/acceptance/checks; after "Approved" run `svod approve work/features/<name> --step deliver`.
9. Set `status: done` in `card.md` of the feature and report what changed and what stayed unchecked.
