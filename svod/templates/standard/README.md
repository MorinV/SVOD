# Svod store

This store keeps plans, questions, human approvals and checks for service repositories next to it. Code lives in the services; the store holds records.

Set it up:

    git init
    svod init --login <your-login>
    svod validate
    svod active

Connect hooks with `integrations/setup-claude.sh --project <store>` or `integrations/setup-codex.sh <store>` from the framework clone; without the prompt hook no approval can be recorded.

## Records and placement

| kind / owner | canonical path | steps |
|---|---|---|
| project | `work/projects/P` | vision, questions, research, architecture, approve, breakdown, children, deliver |
| feature in project | `work/projects/P/features/F` | brief, questions, breakdown, approve, children, integration, deliver |
| standalone feature | `work/features/F` | same feature steps |
| task in project | `work/projects/P/tasks/T` | card, questions, contract, approve, implement, checks, deliver |
| task in project feature | `work/projects/P/features/F/tasks/T` | same task steps |
| task in standalone feature | `work/features/F/tasks/T` | same task steps |
| research in project | `work/projects/P/research/R` | question, findings, outcome |
| research in project feature | `work/projects/P/features/F/research/R` | same research steps |
| research in standalone feature | `work/features/F/research/R` | same research steps |
| hotfix | `work/hotfix/H` | task with kind: hotfix and cause, no contract approval |
| headless task | `work/headless/tasks/T` | task steps |
| headless research | `work/headless/research/R` | research steps |

`<record>` below means the full canonical store-relative path, not a fixed-depth `work/<kind>/<name>`. Short names may be ambiguous: use the full path. `parent` names the containing project or feature; a feature inside a project is itself the parent of its tasks/research. Research is a peer of task, never a container. Its outcome is `knowledge`, a new `task` or a new `research`; `leads_to` records provenance, not containment. A feature is not a research outcome. Successors belong to their project/feature or headless root.

Each record has card.md with `type: card`, `kind`, `services`, `parent`, `tags`, `status`. See the archived example at `work/headless/tasks/example/`; copied real work needs `status: open`. A record is done when its card says `status: done`. Approvals live in approval.yaml, written only by `svod approve` after a fresh human approval.

Create records from `profile/records/<pipeline>/` skeletons (project/feature also ship plan.yaml):

    svod record new project shop
    svod record new feature login --parent work/projects/shop
    svod record new task form --parent work/projects/shop/features/login --services app
    svod record new research auth --parent work/projects/shop/features/login
    svod record new task tooling --services app
    svod record new task incident --kind hotfix --services app
    svod next <record>

The parent selects placement; omit it for standalone features or headless task/research. Link canonical record paths in plan.yaml and criterion owners; do not duplicate a feature's task nodes in its project's plan. Done children do not imply criterion acceptance.

## Services and actions

Name services in card.md (`services: [app]`). Actions in `profile/actions/` find each service at `SVOD_SERVICE_<NAME>`, else `services` in svod.yaml, else `../<name>`:

    bash profile/actions/start-task.sh <record>   # a worktree per service, work.yaml
    bash profile/actions/checks.sh <record>       # SVOD_CHECKS_<NAME> or detected checks; checks.md
    bash profile/actions/pr.sh <record>           # PR description, not permission to push
    bash profile/actions/cleanup.sh <record>      # only after done and permission to remove

`svod do <action> <record>` runs the configured script. It refuses actions for unreached steps unless --force (not an approval bypass), and times out after 600 s unless --timeout is specified. The record argument wins over inherited SVOD_* variables.

`work.yaml` is the authoritative association with service worktrees. Existing worktree paths, branch names and work.yaml contents stay unchanged during a layout move; do not infer ownership from the new leaf name or rename existing checkouts. Ask before push, merge, deployment or worktree removal.

The task checks and feature integration gates run `checks.sh <record> --check` without writing; no services passes, missing checks.md fails without running. Edit process policy in `profile/pipelines/`, texts in `profile/locale/`, skills in `skills/`; run `svod validate` after changes.

## Existing-store transition

An engine install/update does not move existing records. Read the shipped `svod-task-layout-transition` guide and its `references/mapping.md`: bundled `.svod/skills/svod-task-layout-transition/`, or the source/shared package's `svod/skills/svod-task-layout-transition/`. Local skills may mask engine skills; use this explicit path without replacing local policy.

Inventory **all** existing records, including done, archived and Git-untracked files; prepare an explicit old → new mapping and collision preflight before any move. Rehearse on a complete isolated copy. Update live parents, links and structured plans by exact identifiers; preserve original historical artifacts and approval bytes, never bulk-rewrite history or approval hashes. Report changed-bound-input drift honestly and obtain fresh consent through normal gates. Preserve existing work.yaml, worktree and branch names. Reconcile file bytes, counts and references programmatically, then repeat native checks and read-only reconciliation. Live moves need separate authorization; the finite mapping is transition evidence, not a permanent legacy registry.
