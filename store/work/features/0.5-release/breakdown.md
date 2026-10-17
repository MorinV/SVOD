# Breakdown: Svod 0.5

| task | result |
|---|---|
| `work/tasks/autonomy-by-kind` | `autonomy.hotfix` relaxes the approvals of a `kind: hotfix` subject, and `status` prints the level that applies to the subject, not the pipeline's. |
| `work/tasks/external-phrase-match` | A reply that negates the phrase ("не давай", "don't go ahead") no longer lifts the refusal of a command with an external effect. |
| `work/tasks/command-gate-in-template` | The standard template's `checks` and `integration` steps can be decided by the `command` gate once `services` are declared, without editing the pipeline by hand. |

Release chores (CHANGELOG 0.5.0 with **Migration**, README status, tag `v0.5.0`) are done on the feature after the tasks, not as tasks of their own.
