# Local Svod store

Run `git init`, `svod init --login <your-login>`, `svod validate` and `svod render local`.

Create one task at tasks/<name>/ with <KEY>-card.md, contract.md and testing/plan.yaml. Keep the card to description, steps and acceptance; the contract defines result, boundaries, effects, checks and risks. Source and logs must be separate. A plan contains exactly:

    version: 1
    kind: process
    contract: contract.md
    workspace: /absolute/canonical/path/to/clean/git-root
    command: [python3, -m, unittest, discover, -s, tests]

Replace the workspace and command with real choices; null means no command selected, not passing tests. Do not use a fabricated approval or source path. An ordinary clean Git worktree is sufficient; the source must already contain a commit. Configure actual prompt hooks for your agent, show the ready contract/plan to the human, and await their separate fresh approval before:

    svod approve tasks/<name> --step initial_approve
    svod local checks tasks/<name>
    svod local deliver tasks/<name>
    svod status tasks/<name>

`svod local prepare` and `verify` are optional diagnostics. Run no duplicate final command just for ceremony. Completion remains readable after authorized source-worktree cleanup, but new execution/verification/delivery requires live clean source. Local completion does not authorize or prove publication/deployment. Automatic context summaries are off; explicit per-task status remains available.

Read AGENTS.md and the bundled execution/pipeline skills. The template grants no Git push, credentials or external-effect permissions. Full command guide: docs/local-workflow.md. Approval marking depends on an actual agent hook integration; these files alone do not register one.
