# Questions: command-gate-in-template

<!--
One `## Q:` per unknown; the person answers in the chat, the agent records the answer with
svod answer work/tasks/command-gate-in-template --q <n> <text>. Never write A: lines by hand.
-->

## Q: May this task change the engine, or only the template?
Options: template only (`svod new` cannot know the service names, so the gate stays commented and the README of the store says how to write it); engine too: the `command` gate takes `service: "*"` or `services: subject` and runs in each service the subject names, with `SVOD_ID` and `SVOD_SUBJECT_PATH` in its environment like `svod do` (`svod/command_gate.py`, `svod/actions.py`).

## Q: Should the template ship a `workspace_gate` that reads `work.yaml`, so the command runs in the task worktree?
Options: yes (a gate in `profile/gates/work.py` returning the worktrees of `work.yaml`; it also turns on the pre-tool code freeze, which is off in the standard template today); no (the command checks the service checkout, and the task branch is checked only after the merge).
