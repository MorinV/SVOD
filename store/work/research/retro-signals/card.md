---
type: card
kind: research
services: [svod]
parent:
tags: [evidence, retro, engine]
outcome:
status: open
---

# Which evidence signals predict rework

## Description

The evidence log (`evidence/<pipeline>/<subject>.jsonl`, `svod/evidence_log.py`) records position changes, passed steps, approvals and their drift, refusals of the hooks, checks and deliveries. Before any retrospective rule is built on it, find which of these signals, read over many finished records, actually come before rework: a task reopened, a hotfix with `cause` naming it, a contract approved again after a change. This store is the first source of real data.

`outcome` stays empty until the findings exist.
