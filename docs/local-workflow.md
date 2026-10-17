# Compact local workflow

## Create a store

Install Python 3.10+, Git and the current Svod engine. Run `svod new <new-directory>`; an existing destination is refused, not overwritten. `--template task` selects the older OpenSpec/Git example. The local template is opt-in and does not migrate an existing profile.

Initialize the store's Git repository and local identity (`svod init --login <your-login>`). Configure your agent's actual prompt hook before recording approvals; the setup scripts in the framework clone support Claude Code and Codex and modify user configuration only when you explicitly run them. Other agent integrations must deliver actual human events, not agent summaries. Never synthesize a human approval by writing marker files or replaying a historical answer for new inputs.

The supplied AGENTS.md is project guidance, not sandbox enforcement. Load the efficient-execution skill when performing tasks; when using the source clone, the integration setup scripts discover its skills. Vendored installs include skills under `.svod/skills/`. Without an integration that loads skills, explicitly read the relevant skill or copy its guidance into your project's agent instructions.

## Prepare one task

Create `tasks/<name>/` with a canonical `<KEY>-card.md`, compact `contract.md` and `testing/plan.yaml`. A key is optional for addressing: the exact path `tasks/<name>` is unambiguous. Keep the card to description, implementation steps and acceptance; put result, boundaries, authorized effects, checks and risks into the contract. Do not create a full design/spec/WBS set for a small task without a content need. Larger projects may maintain a WBS and dependency diagram separately from bound scope.

Use the schema below, substituting a real clean canonical absolute Git root and a real argv appropriate to the contract:

```yaml
version: 1
kind: process
contract: contract.md
workspace: /absolute/path/to/clean/source
command: [python3, -m, unittest, discover, -s, tests]
```

The source checkout must contain a commit and be clean, including untracked files. Task records and logs must be outside it. An ordinary `git worktree add` provides isolation; Svod adds no source snapshot/import lifecycle. Set Git permissions according to the project; this template does not grant commit, merge, push or deploy consent. Do not copy unrelated dirty input automatically.

`command: null` explicitly means no command selected, not successful testing. This can support non-code work when its contract and selected policy permit it; substantive acceptance still needs honest evidence.

## Execute

Run `svod status tasks/<name>`. `svod local prepare tasks/<name>` is optional read-only readiness diagnosis. Present the exact ready contract and plan to the human; after their separate fresh approval, record it with:

```bash
svod approve tasks/<name> --step initial_approve
```

Implement within the agreed effects and maintain a clean exact source commit before final execution. Then:

```bash
svod local checks tasks/<name>
svod local deliver tasks/<name>
svod status tasks/<name>
```

`checks` runs argv without a shell, retains combined command output and the real exit status, and validates source identity before and after. A failed command or source/contract/approval drift does not become PASS. Command subprocesses have a bounded timeout; POSIX process-group cleanup is best effort, not containment of malicious descendants or a sandbox. Never place secrets into a command or its output: command logs retain what the command emits.

`verify` is a live diagnostic, not another mandatory operation between checks and deliver. Avoid an identical direct final run followed by the same recorded run on unchanged input. Development RED/GREEN and changed source require appropriate new checks.

## Completion and cleanup

`deliver` records only a validated local result and immediately reads it back. It still honors applicable required YAML conditions. Status after completion validates saved contract/plan/approval/result/log bindings without requiring the disposable source checkout to exist. A fresh checks/verify/deliver still requires live clean source. Tampering or a new unsatisfied required condition invalidates completion.

Local completion identifies the checked commit. It does not establish code installation, merge, remote publication, deployment, test adequacy or authenticated provenance against a user deliberately rewriting all local evidence. Preserve real decisions and primary logs. Before separately authorized worktree removal, stop executors and save required evidence outside the worktree. Never force-remove dirty or locked worktrees.

## Context and extensions

The local template disables automatic session summary, prompt positions and approval notices through `profile_config.agent_context`. Native marking and edit protections remain available; explicit `status <query>` and `active` are unchanged. JSON status is bounded advisory data, not execution authorization; it does not contain the full text of instructions/logs or authenticate consent.

Review, CI/static/JUnit/E2E, external trackers, project maps, SSH/DB operations and automatic publication are separate project decisions, not prerequisites of this local route. Conditional declarations and semantic approval purposes let a project compose its chosen guarantees. Change policy through the project's own repository process and test the changed mechanism instead of preserving obsolete ceremony.
