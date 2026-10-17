---
type: card
kind: task
key:
services: [svod]
parent: work/features/0.5-release
tags: [hooks, external-effects, engine]
status: open
---

# A negated go-ahead must not lift the external-effects refusal

## Description

`pre-tool` holds a command with an external effect (`git push`, publish, deploy) until the human mark says go ahead (`svod/hooks/external.py`, `external_reason`). The prompt hook sets `go` in that mark when the reply holds one of `external_effects.phrases` anywhere as whole words, letter case aside (`svod/hooks/prompt.py`, `says_go` with `GO_RE`). So "не давай", "don't go ahead", "давай сначала тесты" and "what does выполняй mean?" all say go: a refusal of the person lifts the guard it was meant to keep.

Proposal: a phrase says go only as a command, either at the start of the reply (`давай, пушь`, `go ahead and publish`) or as the whole reply, the way `approval.phrases` already match (`svod/hooks/prompt.py`, the approval matcher: the whole prompt, optionally followed by keys). A phrase in the middle of a sentence, or after a negation, says nothing.

## Acceptance

- "давай", "Давай!", "go ahead", "go ahead and push" set `go: true` in `svod-human.json`.
- "не давай", "don't go ahead", "no, не выполняй", "давай не будем", "what does go ahead mean here" set `go: false`.
- `docs/reference.md` (The human mark, External effects) says where the phrase must stand; the copy in `svod/templates/local/docs/` is equal to it.
- Tests in `tests/test_hooks.py` cover each case above in English and Russian.
