# Svod store

This store keeps the work on the service repositories next to it (`../app` and so on): what is planned, what was asked, what a person approved and what was checked. The code lives in the services; the store holds the records.

Set it up:

    git init
    svod init --login <your-login>
    svod validate
    svod active

Connect the agent's hooks with `integrations/setup-claude.sh --project <store>` or `integrations/setup-codex.sh <store>` from the framework clone; without the prompt hook no approval can be recorded.

## Records

| kind | where | steps |
|---|---|---|
| project | `work/projects/<name>/` | vision, questions, researches, architecture (`adr/`), approve, breakdown, children, deliver |
| feature | `work/features/<name>/` | brief, questions, breakdown, approve, children, integration, deliver |
| task | `work/tasks/<name>/` | card, questions, contract, approve, implement, checks, deliver |
| hotfix | `work/tasks/<name>/`, `kind: hotfix` | card with `cause`, questions, implement, checks, deliver |
| research | `work/research/<name>/` | question, findings, outcome (hotfix, feature or `knowledge/`) |

Each record has `card.md` with frontmatter `type: card` plus `kind`, `services`, `parent`, `tags`, `status`; see `work/tasks/example/`. A record is done when its card says `status: done`. Approvals live in `approval.yaml` and are written only by `svod approve`.

## Services and actions

Name the services of a task in its card (`services: [app]`). The actions in `profile/actions/` find a service at `SVOD_SERVICE_<NAME>`, else at `services` of `svod.yaml`, else at `../<name>`:

    bash profile/actions/start-task.sh work/tasks/<name>   # card.md if missing, a worktree per service, work.yaml
    bash profile/actions/checks.sh work/tasks/<name>       # SVOD_CHECKS_<NAME> or make/npm/go/pytest; checks.md
    bash profile/actions/pr.sh work/tasks/<name>           # the pull request description
    bash profile/actions/cleanup.sh work/tasks/<name>      # after status: done, removes clean worktrees

Process changes: `profile/pipelines/*.yaml`, texts in `profile/locale/`, skills in `skills/`; run `svod validate` after each change.
