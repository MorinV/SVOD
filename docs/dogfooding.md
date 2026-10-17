# Svod develops itself with Svod

The sources of Svod (this repository) hold no store. The work on the engine is run from an instance of the standard template, the repository [MorinV/svod-rnd](https://github.com/MorinV/svod-rnd), laid out next to a clone of the sources:

```
~/Projects/
  svod-rnd/     the instance: svod.yaml, profile/, skills/, work/, knowledge/, evidence/, .svod/ (the engine it pins)
  SVOD/         a clone of this repository: the one service of the instance, services: {svod: ../SVOD}
```

This is the layout every user of Svod has: one instance next to the repositories it is about, agents started from the instance, worktrees of the services next to them (`~/Projects/svod-task-<name>` for a task of the service `svod`).

## Setting it up

```bash
pip install git+https://github.com/MorinV/SVOD@v0.5.0
git clone https://github.com/MorinV/svod-rnd ~/Projects/svod-rnd
git clone https://github.com/MorinV/SVOD ~/Projects/SVOD
cd ~/Projects/svod-rnd && svod init --login <your-login> && svod doctor
bash ~/Projects/SVOD/integrations/setup-claude.sh --project ~/Projects/svod-rnd
```

The instance pins its engine in `.svod/` (`svod install`, `svod update`); the installed `svod` hands every command over to that copy. Records (`work/`), knowledge and the evidence log are committed in the instance; `.svod-local.yaml`, `.claude/` and `checks.log` are not.

## Working through it

- A new piece of work: `svod do start-task work/tasks/<name>` after writing `card.md` (or copy a record), then `svod status work/tasks/<name>` at every step; `svod next` is planned for 0.6.
- Questions before work: `svod ask work/tasks/<name> "<question>"`, the person answers in the chat, `svod answer work/tasks/<name> --q <n> <text>`.
- Approval: show the bound files, wait for "Approved" or "Одобряю" alone in the chat, `svod approve work/tasks/<name> --step approve`.
- Implementation in the worktree `~/Projects/svod-task-<name>` on the branch `task/<name>`; `svod do checks work/tasks/<name>` runs the suite there and writes `checks.md`; after the merge `status: done` in `card.md` and `svod do cleanup`.
- At the end of a feature: `svod retro work/features/<name>`.

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
17. **A store inside its service repository (resolved by the layout above: the instance is a repository of its own).** `checks.sh:38` refuses a dirty service, and record edits in `store/` make the service dirty: the feature's integration checks (no worktree) need every record change committed first, and `checks.sh` then writes `checks.md` into the same repository. `svod active` walks every worktree of the repository (25 agent worktrees here) for changed records.
18. **A store does not follow its template.** This store was made from the standard template before the template's actions, gates, pipelines, locale and skills changed; `svod do start-task` then made worktrees by the old name with absolute paths in `work.yaml` (finding 2 again). The profile had to be copied from the template by hand and `workspace_gate: work_tree` added to `svod.yaml`. Nothing in the engine tells a store that its template moved on, and nothing updates it: a candidate for the next plan (`svod update --profile`, or a stamp of the template version in `svod.yaml` that `doctor` compares).
19. **A test that assumes a clean environment fails under the checks action.** `tests/test_command_gate.py::test_action_variables_in_a_pipeline` patched two `SVOD_` variables and expected the others absent; under `svod do checks` the suite inherits `SVOD_PIPELINE`, `SVOD_SERVICES` and the rest, so the test failed in every task worktree. The test now starts from an environment without `SVOD_` variables. Any test of this repository that reads the environment must do the same, since the repository checks itself through the action.
