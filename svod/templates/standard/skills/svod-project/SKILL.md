---
name: svod-project
description: Use for a record in work/projects/<name>/ when svod status names a project step - vision, researches, architecture, approve, breakdown, children, deliver.
---

# Running a project

1. Run `svod status work/projects/<name>` and do only its next step.
2. vision: write `card.md` (frontmatter `type: card`, `services`, `tags`) and `vision.md`: goal, who gains, measure of success, limits.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. researches: turn each question no one can answer yet into `work/research/<topic>/card.md` with `parent: work/projects/<name>`; run them with `skills/svod-research/SKILL.md`.
5. architecture: record each decision in `adr/<nnn>-<slug>.md` with frontmatter `type: adr`: context, decision, alternatives, consequences.
6. approve: show `vision.md`, `questions.md` and `adr/`; after the person writes "Approved", run `svod approve work/projects/<name> --step approve`. Never write `approval.yaml`.
7. breakdown: fill `plan.yaml`: schema_version: 1, expected, nodes, criteria. Nodes: id/title/expected, optional record/parent/dependencies. Criteria: id/statement/verification/works, optional owner+criterion dependencies. Make features/tasks with `parent: work/projects/<name>`; link records without copying state/outcome. Run `svod plan validate <record>`; breakdown.md is history/derived only.
8. children: run each with `skills/svod-feature/SKILL.md` or `skills/svod-task/SKILL.md`; check them with `svod status <record>`.
9. deliver: write own `outcome.yaml` with schema_version: 1, nonempty actual and evidence list. Read `svod plan summary <record>`; verify criteria explicitly with `svod plan confirm <record> --criterion <id> --result pass --actual '<observed result>' --evidence <file-or-URL>`. This is verification, not human consent; done children never imply acceptance. Show outcome/acceptance; after "Approved" run `svod approve work/projects/<name> --step deliver`. Optional `svod plan canvas <record>` preserves generated layout.
10. Set `status: done` in `card.md` and report what changed and what stayed open.
