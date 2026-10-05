---
name: svod-pipeline
description: Create or change a Svod pipeline — add a pipeline, a step, a gate, texts, or bind a skill to a role — and prove the change with validate, status and render. Use when someone asks to change how work flows (a new step, a new check before code, a new kind of work), or when a gate gives a wrong answer.
---

# Creating and changing Svod pipelines

A pipeline is a YAML file in the profile (`<profile>/pipelines/<name>.yaml`). The engine computes the position of a piece of work from files and git, so a change to a pipeline changes what every agent is told to do next. Make it small, prove it, and show the human what changed in the rendered documentation.

The format of every key is in [docs/reference.md](../../docs/reference.md). This skill is the order of work; when it and the reference disagree, the reference wins.

## 1. Agree on the change first

Before touching files, state in the chat, in plain words:

- what kind of work the change is about (task, project, note…) and which pipeline file holds it;
- the new or changed step and the condition that makes it pass — a file that exists, a field value, an approval, a git state;
- whether the step must block code (`blocks_code`), must not be skipped (`required`), or only shows a mark (`optional`);
- what the agent should be told when the step is not passed — this becomes the locale text.

A condition that cannot be checked from files or git is not a gate. Say so and keep it as a step without gates (it never passes and stays the last mile) or drop it.

## 2. Pick a gate

Use a core gate when one fits; write a profile gate only when none does.

| Condition | Gate |
|---|---|
| a file or a glob exists in the subject | `artifact` |
| a frontmatter or metadata field has a value | `field` |
| a person approved the plan in the chat, bound to the plan's content | `approval` |
| a document of a type exists in the container | `doc_type` |
| the subject is archived | `archived` |
| the work is in the default branch | `git_pushed` |
| the subject exists at all | `exists` |

A profile gate is a Python class in `<profile>/gates/`; how to write one, its facts and `describe` — [Writing a custom gate](../../docs/reference.md#writing-a-custom-gate). Keep checks read-only and fast: gates run on every `status` and in hooks.

## 3. Edit the pipeline and the texts

- Add the step at its place in `steps`; give it an `id` and a `text`.
- Every text is a locale key. Add it to every `<profile>/locale/<locale>.yaml` the profile ships. Write the text as an instruction to the agent: what to do next, with the command or file name.
- Reasons: when a gate reports different `reason` facts, add `<text>_<reason>` keys for the cases that need a different instruction.
- A new kind of work is a new pipeline file with its `subject` (provider and params). Add it to `active_order` in `svod.yaml` if it should appear in the start-of-session summary.
- A skill for a step: give the step a `role` and add a rule to the bindings file, for example `{ when: { has_file: go.mod }, skill: impl-go }`.

## 4. Prove it

```bash
svod validate                    # declarations, texts in every locale, bindings
svod status <KEY or name>        # position of one real subject before and after
svod render <pipeline> --write   # refresh the pipeline diagram in the docs
```

`validate` must be clean. Run `status` on at least one real subject that the change affects and one it should not affect, and paste both outputs into the chat. If the position moved for a subject that is not supposed to move, the gate or its params are wrong.

If the profile has tests (a `tests/profile/` fixture or similar), add a case for the new gate or step: a subject where it passes and one where it fails.

## 5. Show the change

Tell the human, in a few lines: the step before and after, the rendered diagram diff, and which current subjects changed their position. Then land the change like any other change to the repository.

## Do not

- Do not encode a decision that changes often into a gate parameter scattered across pipelines — put the value in `profile_config` and read it in the gate.
- Do not make a gate call the network on every evaluation; if it must, cache it and return UNKNOWN on failure, never PASS.
- Do not remove a `required` step to unblock one subject. Fix the subject or ask the human.
