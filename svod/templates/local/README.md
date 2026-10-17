# Local Svod store

Set up the store:

    git init
    svod init --login <your-login>
    svod validate
    svod render local

Connect the agent's hooks with `integrations/setup-claude.sh <store>` or `integrations/setup-codex.sh <store>` from the framework clone; without the prompt hook no approval can be recorded.

A task lives in `tasks/<name>/`: the card `<KEY>-card.md`, the contract `contract.md` and the plan `testing/plan.yaml`. Show the contract and the plan to the person; after they write "Approved" in the chat:

    svod approve tasks/<name> --step initial_approve
    svod local checks tasks/<name>
    svod local deliver tasks/<name>
    svod status tasks/<name>

The agent follows `AGENTS.md` and the skills in `skills/`. The terms, the plan format and every command: [docs/local-workflow.md](docs/local-workflow.md).
