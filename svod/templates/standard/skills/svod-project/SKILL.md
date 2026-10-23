---
name: svod-project
description: Run project planning, child work and delivery steps.
---

# Running a project

1. Run `svod status <record>`; do only its next step. Projects live at work/projects/P.
2. vision: fill card.md (type: card, services, tags) and vision.md: goal, beneficiaries, success measure, limits.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. researches: investigate unknowns at `<record>/research/R`, parent: <record>, with `skills/svod-research/SKILL.md`. Research is task's peer; outcomes: knowledge/task/research, never feature.
5. architecture: adr/<nnn>-<slug>.md with type: adr; context, decision, alternatives, consequences.
6. approve: show vision.md, questions.md, adr/; after fresh "Approved": `svod approve <record> --step approve`. Never edit approval.yaml.
7. breakdown: plan.yaml has schema_version: 1, expected, nodes, criteria. Nodes: stable id/title/expected, optional record/parent/dependencies; criteria: id/statement/verification/works, optional owner+criterion dependencies. Features/tasks/research: `<record>/features/F`, `<record>/tasks/T`, `<record>/research/R`, parent: <record>. Feature children: `<feature-record>/tasks/T` or `<feature-record>/research/R`, parent: <feature-record>. Link canonical paths, never duplicate feature tasks in project or copy state/outcome. `svod plan validate <record>`; breakdown.md is history/derived.
8. children: follow each record's named skill; `svod status <child-record>`.
9. deliver: write outcome.yaml (schema_version: 1, actual, evidence). Read `svod plan summary <record>`; explicitly verify then `svod plan confirm <record> --criterion <id> --result pass --actual '<result>' --evidence <file-or-URL>`. Done is not acceptance/consent. Show outcome/acceptance; after "Approved": `svod approve <record> --step deliver`. Changed binds require fresh consent. Optional `svod plan canvas <record>` preserves layout.
10. Set status: done; report changes and remaining work.
