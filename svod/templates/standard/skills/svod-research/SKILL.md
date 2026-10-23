---
name: svod-research
description: Investigate questions without changing service code.
---

# Running a research

1. Run `svod status <record>`; do only its next step. Use canonical paths: `<owner>/research/R` under project/feature (including project features), otherwise `work/headless/research/R`. Create with `svod record new research <name> --parent <owner>`; omit --parent for headless.
2. question: fill card.md (type: card, parent, tags), question.md: question, why it matters, which answer changes the plan. Parent is the containing project/feature, not research provenance.
3. findings: findings.md has sources, experiments, answer. Source every claim; label guesses. Change no service code.
4. outcome in card.md:
   - `task` or `research`: `svod record new <pipeline> <name> --parent <owner>` creates the successor under its project/feature; omit --parent for headless. Set `leads_to: <successor-record>` to its canonical path. Research is task's peer, not a container: provenance never makes it the successor's parent. A feature is not a research outcome.
   - `knowledge`: `svod knowledge publish <record>` shows the findings snapshot and requests publication/close. After the person's next configured go-ahead, repeat. Changed findings require a new request/reply. The command creates the provenance-tagged note, updates the index, sets knowledge and status: done; never set these manually instead of consent.
5. For task/research outcomes show findings and successor; set status: done only after human agreement. Status reads/hooks never publish or close research.
6. Report answer, sources and unknowns.
