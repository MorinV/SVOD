# Working with Svod

1. Run `svod active` for open work; run `svod status <record>` with its canonical path and do only its next step.
2. Projects contain `features/`, `tasks/` and `research/`; features contain `tasks/` and `research/`. Standalone features live in `work/features`, standalone tasks/research in `work/headless/{tasks,research}`, hotfixes in `work/hotfix`. The frontmatter of `card.md` names `kind`, `services`, `parent`.
3. Use the skill `svod status` names: `skills/svod-task`, `svod-feature`, `svod-project`, `svod-research`, `svod-questions`.
4. Never guess: add unknowns with `svod ask <record> "<question>"`, ask in the chat, wait for the answer.
5. After the person writes "Approved" (or "Одобряю"), run `svod approve <record> --step <id>`. Never edit `approval.yaml`.
6. Change service code only in the worktrees of `work.yaml`, made by `bash profile/actions/start-task.sh <record>`.
7. Ask the person before push, merge, deploy, credentials or removing a worktree.
8. Write lasting answers to `knowledge/`; read it before asking.
