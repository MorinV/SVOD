# Compact local workflow

## Terms

This guide, `AGENTS.md`, the skills and the `svod status` texts use one word per idea.

| Term | What it is | File or command |
|---|---|---|
| card | the task: description, implementation steps, acceptance | `tasks/<name>/<KEY>-card.md` |
| contract | the promised result, scope, allowed effects, checks and risks | `tasks/<name>/contract.md` |
| plan | the source checkout and the command that checks the result | `tasks/<name>/testing/plan.yaml` |
| approval | the person's "Approved" in the chat, recorded against the current contract and plan | `svod approve tasks/<name> --step initial_approve` writes `approval.yaml` |
| checks | one recorded run of the plan's command on clean committed source | `svod local checks tasks/<name>` writes `testing/process/` |
| deliver | recording passed checks as the task's result | `svod local deliver tasks/<name>` writes `delivery/process.yaml` |
| completion | the state after deliver; status prints "Local completion recorded" | `svod status tasks/<name>` |

Completion names the checked commit and nothing more: merge, push, installation and deployment are separate steps that need their own permission.

## Create a store

```bash
svod new <new-directory>          # refuses an existing directory; --template task gives the OpenSpec/Git example
cd <new-directory>
git init
svod init --login <your-login>
svod validate
```

Connect the hooks before the first approval: run `integrations/setup-claude.sh <store>` or `integrations/setup-codex.sh <store>` from the framework clone (each keeps a backup of the config it edits). The prompt hook turns the person's "Approved" into the mark `svod approve` requires; without it no approval can be recorded.

In this template the session-start and prompt hooks print nothing (`profile_config.agent_context` in `svod.yaml`), so ask for the position with `svod status tasks/<name>`. The prompt hook still marks approvals, and the pre-tool hook still refuses edits of frozen code and of `approval.yaml`.

The agent reads `AGENTS.md` and `skills/*/SKILL.md` of the store; the setup scripts link the skills, and a vendored engine keeps them in `.svod/skills/`.

## Write the card, contract and plan

Create `tasks/<name>/` with the card, the contract and the plan. Address the task by the path `tasks/<name>`; a key is optional. Keep the card short; small tasks need no design, spec or WBS files.

```yaml
version: 1
kind: process
contract: contract.md
workspace: /absolute/path/to/clean/source
command: [python3, -m, unittest, discover, -s, tests]
```

- `workspace`: the absolute root of a Git checkout that has a commit and no changes, untracked files included. Keep task records and logs outside it; `git worktree add` gives an isolated checkout. Never reset, stash or clean someone else's dirty tree to satisfy this.
- `command`: an argv list, run without a shell, or `null`.

`command: null` selects no command. Checks then log "No command selected." with no exit code, and deliver accepts it. Use it only for work without code (a document, a decision) whose contract says how acceptance is shown; it is no evidence that anything was tested.

## Approve

1. `svod status tasks/<name>` names the approval as the next step and freezes the code.
2. Show `contract.md` and `testing/plan.yaml` to the person. `svod local prepare tasks/<name>` prints the parsed plan or why it is not ready; it writes nothing.
3. The person writes `Approved` (`approval.phrases` in `svod.yaml`) in the chat. The mark lasts `approval.window_minutes`, 10 by default.
4. Run `svod approve tasks/<name> --step initial_approve`. It writes the date, the approver and the hash of the contract and the plan into `approval.yaml`.

Any edit of `contract.md` or `testing/plan.yaml` voids the approval: show the new version and repeat steps 3–4. Text written by an agent is never an approval.

## Run checks and deliver

Commit the change in the source checkout and leave it clean, then:

```bash
svod local checks tasks/<name>
svod local deliver tasks/<name>
svod status tasks/<name>
```

Checks run the command once in `workspace` with `PYTHONDONTWRITEBYTECODE=1` and a 600-second timeout, write the combined output to `testing/process/command.log`, and the exit code, the commit and the input hashes to `testing/process/receipt.json`. They fail on a non-zero exit, on source that is dirty before or after the run, and on a contract, plan or approval changed since the approval. Add other build output to the source's `.gitignore`, or it makes the source dirty. Keep secrets out of the command and its output: the log keeps everything.

Run checks again only after the source or the plan changes, and do not run the same command by hand right before them. `svod local verify tasks/<name>` re-validates the receipt against the live source without running anything; it is a diagnostic, not a step.

Deliver re-validates the receipt and writes `delivery/process.yaml`. After that `svod status tasks/<name>` validates the saved contract, plan, approval, receipt and log without the source checkout, so an authorized removal of the checkout keeps completion; an edit of any of those files voids it. Before removing a worktree, stop running processes and keep the logs you need; never force-remove a dirty or locked worktree.

## Extend the process

Review, CI, JUnit, E2E, trackers and publication are not part of this route. Add one as a step in `profile/pipelines/local.yaml` with the `svod-pipeline` skill, then run `svod validate`.
