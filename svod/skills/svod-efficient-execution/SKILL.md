---
name: svod-efficient-execution
description: Use when running one record of a Svod store to completion - before svod status, svod approve or svod do on a task - so that the checks run once and are recorded.
---

# Executing a Svod task

1. Run `svod status <record>` and do only its next step. Read that record's card, contract and the files the step names, not other records or old logs.
2. While status says "Do not touch the code", edit only the files of the record.
3. Show the files the approval binds to the person; after they write "Approved", run `svod approve <record> --step <id>`. Never write `approval.yaml` yourself: an edit of a bound file voids the approval, then repeat this step.
4. Change only what the contract allows, only in the work directories of the record.
5. Choose tests by risk: links for text, affected behavior and regressions for code, positive and negative cases for a new mechanism.
6. Commit everything, then run the checks once as status names them (`svod do <action> <record>`; `svod do --list` lists the actions). A manual run beforehand only doubles the time.
7. On failure read the log the checks write, fix, commit, run the checks again.
8. Delegate a subtask only with its own files, check and stop condition; keep its logs in files.
9. Report the result, the checked commits, what stayed unchecked and what needs the person's permission: merge, push, deploy, worktree removal.

Process changes: the `svod-pipeline` skill.
