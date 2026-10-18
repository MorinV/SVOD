---
name: svod-research
description: Use for a record in work/research/<name>/ when svod status names a research step - question, findings, outcome - or when a question needs an investigation before any code.
---

# Running a research

1. Run `svod status work/research/<name>` and do only its next step.
2. question: write `card.md` (frontmatter `type: card`, `parent`, `tags`) and `question.md`: the question, why it matters, which answer would change the plan.
3. findings: write `findings.md`: sources, experiments, the answer. Give every claim its source or command; mark guesses as guesses. Change no service code.
4. outcome: set `outcome` in `card.md`:
   - `hotfix` or `feature`: make `work/tasks/<name>/` with `kind: hotfix` or `work/features/<name>/`, then set `leads_to: work/<kind>/<name>`;
   - `knowledge`: run `svod knowledge publish work/research/<name>` to show the exact findings snapshot and request publication/close. After the person's next reply is a configured go-ahead, repeat the command. Changed findings need a new request and reply. The command creates the provenance-tagged note, updates the index, then sets `knowledge` and `status: done`; never set these manually as a substitute for consent.
5. For other outcomes, show `findings.md` and the outcome to the person; set `status: done` in `card.md` when they agree. Status reads and ordinary hooks never publish or close research.
6. Report the answer in two sentences, its sources and what stays unknown.
