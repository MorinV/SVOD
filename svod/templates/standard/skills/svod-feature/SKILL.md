---
name: svod-feature
description: Run standalone or project-owned feature steps.
---

# Running a feature

1. Run `svod status <record>`; do only its next step. Feature paths: `work/projects/P/features/F` (parent: work/projects/P) or `work/features/F` (empty parent). Create with `svod record new feature <name> --parent <project>`; omit --parent for standalone.
2. brief: fill card.md (type: card, services, parent, tags) and brief.md: problem, users, scope, acceptance.
3. questions: follow `skills/svod-questions/SKILL.md`.
4. breakdown: fill plan.yaml: schema_version: 1, expected, nodes, criteria. Nodes: stable id/title/expected, optional record/parent/dependencies; criteria: id/statement/verification/works, optional owner+criterion dependencies. Children: `<record>/tasks/T` or `<record>/research/R`, parent: <record>, including project features. Link canonical paths; state/actual come from records. Research outcomes: knowledge/task/research, not feature. `svod plan validate <record>`; breakdown.md is historical/derived.
5. approve: show brief.md, questions.md, plan.yaml; after fresh "Approved": `svod approve <record> --step approve`. Never edit approval.yaml; changed binds need fresh consent. Outcome/acceptance/canvas are not definitions.
6. children: use their named skills; `svod status <child-record>`.
7. integration: after merge, `bash profile/actions/checks.sh <record>`; inspect checks.log on failure.
8. deliver: write outcome.yaml (schema_version: 1, actual, evidence). Read `svod plan summary <record>`; explicitly verify then `svod plan confirm <record> --criterion <id> --result pass --actual '<result>' --evidence <file-or-URL>`. Done never auto-accepts criteria. Show outcome/acceptance/checks; after "Approved": `svod approve <record> --step deliver`.
9. Set status: done; report changes and unchecked work.
