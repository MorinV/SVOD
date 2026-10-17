---
name: svod-feature
description: Use for a record in work/features/<name>/ when svod status names a feature step - brief, breakdown, approve, children, integration, deliver.
---

# Running a feature

1. Run `svod status work/features/<name>` and do only its next step.
2. brief: write `card.md` (frontmatter `type: card`, `services`, `parent`, `tags`) and `brief.md`: problem, users, scope in and out, acceptance.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. breakdown: make one task per independent change, `work/tasks/<task>/card.md` with `parent: work/features/<name>`; list them in `breakdown.md` with one line of result each.
5. approve: show `brief.md`, `questions.md` and `breakdown.md`; after the person writes "Approved", run `svod approve work/features/<name> --step approve`. Never write `approval.yaml`.
6. children: take each task to done with `skills/svod-task/SKILL.md`; check them with `svod status work/tasks/<task>`.
7. integration: after the tasks are merged, run `bash profile/actions/checks.sh work/features/<name>` on the service checkouts; on failure read `checks.log` and open a hotfix task.
8. deliver: show what the feature delivers against `brief.md`; after "Approved" run `svod approve work/features/<name> --step deliver`.
9. Set `status: done` in `card.md` of the feature and report what changed and what stayed unchecked.
