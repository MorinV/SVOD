# Svod develops itself with Svod

`store/` in this repository is a store made by `svod new store --template standard`. Its one service is the repository itself (`services: {svod: ..}` in `store/svod.yaml`), so the work on the engine is recorded the way a team records the work on its services: features, tasks and research in `store/work/`, questions answered by a person, contracts approved in the chat, checks, delivery, and the evidence log that a retrospective will read. Every friction met on the way is a finding about the product; the first run's are at the end.

What is in it now:

| record | state |
|---|---|
| `work/features/0.5-release` | brief and breakdown written; questions wait for the person |
| `work/tasks/autonomy-by-kind` | card, questions, draft contract; questions wait |
| `work/tasks/external-phrase-match` | card, questions, draft contract; questions wait |
| `work/tasks/command-gate-in-template` | card, questions; the contract depends on the answers |
| `work/research/retro-signals` | question written; findings and `outcome` open |
| `knowledge/docs-and-their-template-copies-match-byte-for-byte.md` | a convention of this repository, given to the agent on the tags `docs`, `tests`, `engine` |

## Set up, once per clone

Run from `store/`, with the engine of this clone (`pip install -e .` from the root, or `PYTHONPATH=<clone>` and `python3 -m svod.cli` in place of `svod`):

```bash
cd store
svod init --login <your-login> --email <the email of your commits>
svod validate
svod active
```

Give `--email` the address your commits carry: `active` tells your records from the team's by the author of the last commit, and without it `init` takes `git config user.email` of the clone.

Connect Claude Code to this store only, from the root of the clone:

```bash
bash integrations/setup-claude.sh --project store
```

It writes `store/.claude/settings.json` and links skills into `store/.claude/skills/`, both with absolute paths of your machine: they are ignored by `store/.gitignore`, never committed. Run it again after moving the clone or switching Python. Start Claude Code in `store/`. The hooks call the `svod` that `python3` imports; when an editable install points at another checkout, the hooks run that checkout's engine, not the one you are changing (finding 12).

## Run a piece of work

The skills in `store/skills/` say each step in detail; `svod status work/<kind>/<name>` always names the next one. In short, for a task:

1. **Record.** `work/tasks/<name>/card.md` with frontmatter `type: card`, `kind: task` (or `hotfix` with `cause:`), `key:` (empty: this store has no tracker), `services: [svod]`, `parent: work/features/<feature>` or empty, `tags: [...]`, `status: open`; a title, a description, acceptance. Copy a record of `store/work/tasks/`; the commented format is `svod/templates/standard/work/tasks/example/card.md`.
2. **Questions.** `questions.md`: one `## Q: <question>` per unknown with the options, or the single line `none`. Ask them in the chat in one message and wait. After the person answers, record each answer: `svod answer work/tasks/<name> --q <n> "<their words>"`. With the hooks on, the agent cannot write `questions.md` itself (finding 1): until that is fixed, write the questions before connecting the hooks, or let the person save the file the agent proposes in the chat.
3. **Contract.** `contract.md`: result, boundaries per service (files of this repository), effects, checks, risks.
4. **Approval.** Show card, questions and contract; the person writes `Approved` as the whole reply; then `svod approve work/tasks/<name> --step approve`. Never edit `approval.yaml`. Any later edit of a bound file voids it.
5. **Worktree.** `svod do start-task work/tasks/<name>` makes a worktree of this repository next to the clone, `<clone dir>-<name>`, on the branch `<name>`, and lists it in `work.yaml`. Use `svod do`, not `bash profile/actions/start-task.sh` (finding 2). Change engine code only there and commit there. The worktree carries its own copy of `store/` from the branch point: change records only in the checkout you run `svod` from.
6. **Checks.** From `store/`, with the test suite isolated from the variables of the action (finding 3):

   ```bash
   SVOD_CHECKS_SVOD='env -u SVOD_ROOT -u SVOD_ID -u SVOD_SUBJECT_PATH -u SVOD_SERVICES -u SVOD_KEY -u SVOD_KIND -u SVOD_PIPELINE -u SVOD_LOCALE -u SVOD_SERVICE_SVOD PYTHONPATH=. python3 -m pytest -q' \
     bash profile/actions/checks.sh work/tasks/<name>
   ```

   It writes `checks.md` (committed) and `checks.log` (ignored). It refuses while the worktree has uncommitted changes.
7. **Delivery.** `svod do pr work/tasks/<name>` prints the pull request text. `git push` is held by the pre-tool hook until the person's reply starts with "go ahead" or "давай" (and, until `external-phrase-match` is done, merely contains it). Under `autonomy: {task: supervised}` the result approval is optional; when the person approves anyway, `svod approve work/tasks/<name> --step deliver`.
8. **Close.** After the merge set `status: done` in the card, then `svod do cleanup work/tasks/<name>` removes clean worktrees; delete the merged branch with `git branch -d <name>`.

A feature goes brief → questions → breakdown (tasks with `parent:`) → approval → children done → integration checks → delivery; a research goes question → findings → `outcome` (`hotfix`/`feature` with `leads_to:`, or `knowledge` with `knowledge:`). Lasting answers go to `knowledge/` through `svod knowledge note "<text>" --tags a,b --title "<title>"`; the hooks give them to the agent on records that share a tag.

**Retro.** `svod status`, `svod approve` and the pre-tool hook append to `store/evidence/<pipeline>/<record>.jsonl`; commit those lines with the record they belong to. There is no retrospective command yet: `work/research/retro-signals` decides which signals one should show, and this store is its first data.

## What is committed

| committed | not committed (`store/.gitignore`, root `.gitignore`) |
|---|---|
| `svod.yaml`, `profile/`, `skills/`, `AGENTS.md`, `README.md` | `.svod-local.yaml`: login and email of one person |
| `work/**`: `card.md`, `brief.md`, `breakdown.md`, `questions.md`, `contract.md`, `question.md`, `findings.md`, `checks.md`, `approval.yaml`, `adr/` | `work.yaml`: worktrees of one machine, absolute paths under `svod do` |
| `knowledge/` with `INDEX.md` | `checks.log` |
| `evidence/**.jsonl` (`evidence: {commit: true}`) | `.claude/`: hooks and skill links with absolute paths |
| | `__pycache__/` of `profile/gates/` |

`tests/test_dogfood_store.py` keeps the store valid on a copy: `svod validate` is green, every record resolves and names `svod`, `svod active` lists the open records, and no committed file holds an absolute path of a machine.

`store/profile/` is the standard template's profile as of 0.5 with two changes in `svod.yaml` (`services`, `workspaces: ../..`) and the example task removed. A later change of `svod/templates/standard/` does not reach it: port it by hand when the store should follow.

## Findings

From the first run (setting up the store, five records, `status`, `active`, `start-task`, `checks`, a knowledge note, the hooks). Paths are in this repository; lines as of commit `ac63114`.

1. **The agent cannot write questions.** `svod/hooks/guard.py:124` (`questions_file`) and `:225` refuse every `Write`/`Edit` of a `questions.md` in a record, a new one included, while `svod/templates/standard/skills/svod-questions/SKILL.md:8` and the step text `profile/locale/en.yaml:28` tell the agent to write its questions there. `svod answer` writes only answers; there is no command that adds a question. With the hooks on, the questions step cannot be done by the agent at all. Checked with `svod hook pre-tool` on a `Write` of `work/tasks/new-task/questions.md`: refused.
2. **start-task with the store inside the service.** `svod/templates/standard/profile/actions/start-task.sh:36` builds the worktree as `$(dirname repo)/$(basename repo)-<branch>`; with `services: {svod: ..}` and the script run directly, as the template's `README.md:30` says, that is `./..-<branch>`, a worktree inside the store. Under `svod do` the service path is absolute (`svod/actions.py:165`, `action_env`), so the worktree lands next to the clone but `work.yaml` gets an absolute path (`start-task.sh:45`), which cannot be committed. `work.yaml` is therefore ignored here, which makes "in progress" a per-machine fact.
3. **Inherited action variables beat the argument; checks recurse.** `svod/templates/standard/profile/actions/_env.sh:6-7,12,57-60` take `SVOD_ROOT`, `SVOD_ID`, `SVOD_SUBJECT_PATH`, `SVOD_SERVICES` from the environment before the record given as argument, and `:63` exports them. `checks.sh` runs `python3 -m pytest -q` with them set; `tests/test_standard_template.py:65` passes `os.environ` on to its own `start-task.sh`/`checks.sh`, which then act on the outer record: `checks.sh` runs the whole suite again, recursively. `svod do checks work/tasks/autonomy-by-kind` was stopped by the action timeout after 600 s (`svod/actions.py:33`); the suite alone takes about 70 s. With the workaround of step 6 the same checks passed in a task worktree.
4. **The commented `command` gate of the template cannot work.** `svod/templates/standard/profile/pipelines/task.yaml:85` and `feature.yaml:63` suggest `argv: [bash, profile/actions/checks.sh], service: app`. With `service` the command runs in the service checkout (`svod/command_gate.py:158`, `directory`), where `profile/actions/checks.sh` does not exist; the gate passes no record to the command, and `checks.sh` exits 2 without one; `checks.sh` writes `checks.md` into the store, so with `cwd` there the result is never cached. Recorded as `work/tasks/command-gate-in-template`.
5. **No code freeze in the standard template.** Its `svod.yaml` names no `workspace_gate` and its pipelines no `key_gate`, so `blocks_code` of the task approval (`task.yaml:44`) is never enforced by `pre-tool` (rule 3 of the reference needs both), and the `command` gate with `service` checks the main checkout, not the task worktree. `svod status` still prints "Do not touch the code".
6. **Autonomy by kind is validated, not applied.** `svod/loader.py:126` (`apply_autonomy`) relaxes steps per pipeline only; `svod/status.py:86` prints the pipeline's level, so a `kind: hotfix` task shows `Autonomy: supervised` although `svod.yaml` says `hotfix: autonomous`. Recorded as `work/tasks/autonomy-by-kind`.
7. **A negated go-ahead says go.** `svod/hooks/prompt.py:118` (`says_go`, pattern `GO_RE` at `:45`) finds a phrase anywhere as a whole word: "не давай" and "don't go ahead" lift the external-effects refusal. Recorded as `work/tasks/external-phrase-match`.
8. **`svod do` ignores the position.** `svod do start-task` ran while the task was at its questions step (`svod/actions.py:238`, `run_action`); only the next `status` showed the order violation "worktrees were made before the contract was approved". An action a step names could refuse, or warn, while that step is not current.
9. **Actions leave no evidence.** `svod/actions.py:229` (`record_run`) is still the placeholder that does nothing, though `svod/evidence_log.py:204` (`record_action`) exists and the reference lists `action_run`. The start-task and checks runs of this setup are not in the log.
10. **Denials of the new rules have no rule code.** `svod/evidence_log.py:96` (`RULE_KEYS`) has no entry for `hook.deny_questions` or `hook.deny_human`, so those refusals are logged with `rule: null`; a retrospective cannot tell them apart.
11. **The knowledge README is indexed as a note.** `svod/knowledge.py:160` skips only `INDEX.md`, so `knowledge/README.md` of the template appears in `INDEX.md` as a current note titled "Knowledge" with no tags.
12. **The setup script links the wrong skills and may run another engine.** `integrations/common.sh:56` (`skills_source`) links the local template's skills (`svod-efficient-execution`, `svod-pipeline`) into a standard store; the store's own `skills/svod-task` and the rest are not linked, so Claude Code does not offer them as skills. `integrations/common.sh:33` (`svod_command`) registers `python3 -m svod.cli` without `PYTHONPATH` whenever `svod` imports from anywhere; here an editable install of the main checkout, so hooks in a worktree run the main checkout's engine.
13. **The example task is open work.** `svod/templates/standard/work/tasks/example/card.md:8` (`status: open`) puts it in `svod active` and the session summary of every new store, with a next step about `app`; it was removed here, though `skills/svod-task/SKILL.md:9` says to copy it.
14. **One text for two different questions states.** `profile/pipelines/task.yaml:27-30` (and the same step of feature and project) use `work.step.questions` for both a missing file and unanswered questions, so a record whose questions are written and asked still says "write what you do not know into questions.md"; it does not say how many answers are missing.
15. **`workspaces` is read by nothing.** `svod/templates/standard/svod.yaml:4` sets `workspaces: ..`; neither the core nor the template reads it (the actions use `services`). Here it is `../..`, where the worktrees go, for the reader only.
16. **Reference drift.** `docs/reference.md:810` lists `svod new --template local|task` without `standard`; `docs/reference.md:105` and `:109` are two paragraphs titled "The human mark" that disagree (`go` field or not, `svod.approval` or `svod.questions.write_human_mark`).
17. **A store inside its service repository.** `checks.sh:38` refuses a dirty service, and record edits in `store/` make the service dirty: the feature's integration checks (no worktree) need every record change committed first, and `checks.sh` then writes `checks.md` into the same repository. `svod active` walks every worktree of the repository (25 agent worktrees here) for changed records.
18. **A store does not follow its template.** This store was made from the standard template before the template's actions, gates, pipelines, locale and skills changed; `svod do start-task` then made worktrees by the old name with absolute paths in `work.yaml` (finding 2 again). The profile had to be copied from the template by hand and `workspace_gate: work_tree` added to `svod.yaml`. Nothing in the engine tells a store that its template moved on, and nothing updates it: a candidate for the next plan (`svod update --profile`, or a stamp of the template version in `svod.yaml` that `doctor` compares).
19. **A test that assumes a clean environment fails under the checks action.** `tests/test_command_gate.py::test_action_variables_in_a_pipeline` patched two `SVOD_` variables and expected the others absent; under `svod do checks` the suite inherits `SVOD_PIPELINE`, `SVOD_SERVICES` and the rest, so the test failed in every task worktree. The test now starts from an environment without `SVOD_` variables. Any test of this repository that reads the environment must do the same, since the repository checks itself through the action.
