---
type: card
kind: task
key: EXAMPLE-1
services: []
parent:
tags: [example]
status: archived
---

# EXAMPLE-1: replace with a one-line task title

<!--
Example task card. Copy work/tasks/example/ to work/tasks/<name>/ for a real task, or let
bash profile/actions/start-task.sh work/tasks/<name> write a bare card. Frontmatter:
  kind      task, or hotfix (no contract, no approval; needs cause:)
  key       tracker key or empty; branches are <key>_<name>
  services  services of svod.yaml this task touches, for example [app]; svod status stops here while it is []
  parent    work/features/<name> or work/projects/<name> this task belongs to, or empty
  cause     hotfix only: the incident or record that made it necessary
  tags      free labels
  status    open until merged, then done; archived keeps a record out of svod active.
            This example is archived, so a new store has no open work: set open in a copy.
-->

## Description

Greet the user by name on the start page of `app` instead of the generic "Hello".

## Acceptance

- The start page shows "Hello, <name>" for a signed-in user.
- An anonymous user still sees "Hello".
