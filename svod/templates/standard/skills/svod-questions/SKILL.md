---
name: svod-questions
description: Use when svod status names the questions step of any record in work/, or whenever the work depends on something you do not know.
---

# Asking questions

1. Write into `questions.md` of the record everything you do not know that changes the work: behaviour, data, boundaries, effects, priorities. One `## Q: <question>` heading per question; when there is nothing to ask, the file is the single line `none`.
2. Do not invent answers, defaults or "reasonable assumptions". Read the code, `knowledge/` and the record first; ask only what they do not answer.
3. Under each question give the options you see and what each would change; the questions are numbered in file order.
4. Ask them in the chat in one message, then wait for the person. Do not go on with the step meanwhile.
5. Right after the person answers in the chat, record each answer with `svod answer <record> --q <n> <the person's words>`: it writes `A: …` under question n and works only while the person has just written. Never write `A:` lines by hand.
6. Leave an unanswered question open and say so; `svod status <record>` keeps the record here.
7. A new unknown later goes into `questions.md` and to the chat the same way. An edit of `questions.md` voids an approval bound to it: ask for a fresh "Approved".
