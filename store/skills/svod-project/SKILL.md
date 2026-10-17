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
7. breakdown: make features and tasks with `parent: work/projects/<name>`; list them in `breakdown.md`.
8. children: run each with `skills/svod-feature/SKILL.md` or `skills/svod-task/SKILL.md`; check them with `svod status <record>`.
9. deliver: write each child's outcome into `breakdown.md`, show it; after "Approved" run `svod approve work/projects/<name> --step deliver`.
10. Set `status: done` in `card.md` and report what changed and what stayed open.
