---
name: svod-questions
description: Use when svod status names the questions step of any record in work/, or whenever the work depends on something you do not know.
---

# Asking questions

1. Add everything you do not know that changes the work (behaviour, data, boundaries, effects, priorities) with `svod ask <record> "<question>" --context "<options and what each would change>"`, one call per question; it appends a `## Q:` heading to `questions.md` of the record. When there is nothing to ask, run `svod ask <record> --none`. Never edit `questions.md` yourself: the hook refuses it.
2. Do not invent answers, defaults or "reasonable assumptions". Read the code, `knowledge/` and the record first; ask only what they do not answer.
3. The questions are numbered in file order; `svod ask` prints the number of each.
4. Ask them in the chat in one message, then wait for the person. Do not go on with the step meanwhile.
5. Right after the person answers in the chat, record each answer with `svod answer <record> --q <n> <the person's words>`: it writes `A: …` under question n and works only while the person has just written.
6. Leave an unanswered question open and say so; `svod status <record>` keeps the record here and says how many answers are missing.
7. A new unknown later goes in with `svod ask` and to the chat the same way. A change of `questions.md` voids an approval bound to it: ask for a fresh "Approved".
