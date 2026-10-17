# Working with Svod

1. Run `svod status tasks/<name>` and do its next step. Terms: `docs/local-workflow.md`.
2. Execute a task with `skills/svod-efficient-execution/SKILL.md`; change `profile/pipelines/*.yaml` with `skills/svod-pipeline/SKILL.md`.
3. Keep a task in `tasks/<name>/`: `<KEY>-card.md`, `contract.md`, `testing/plan.yaml`.
4. After the person writes "Approved" in the chat, run `svod approve tasks/<name> --step initial_approve`. Never edit `approval.yaml`.
5. Run the plan's command once with `svod local checks tasks/<name>`, then `svod local deliver tasks/<name>`.
6. Ask the person before merge, push, deploy, using credentials, writing outside the store and the plan's `workspace`, or removing a worktree; read the target back after such a write.
7. Never reset, stash or clean a checkout you did not create.
