---
name: svod-pipeline
description: Use when changing Svod pipelines or gates. Simplify obligations first and verify the changed mechanism.
---

# Creating and changing Svod pipelines

A pipeline is a YAML file in the profile (`<profile>/pipelines/<name>.yaml`). It is the authority for the selected process, not a copy of historical requirements. Changes follow the project's repository policy; do not invent an additional task or approval merely to change Svod itself. Keep history without automatically migrating consent or replaying retired validators.

The format of every key is in [docs/reference.md](../../docs/reference.md). This skill is the order of work; when it and the reference disagree, the reference wins.

## 1. Agree on the change first

Establish the requested functional boundary before touching files; ask only for unresolved decisions that affect it:

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
svod render <pipeline>          # inspect the declaration's documentation
svod status <selected query>    # when a concrete affected position needs checking
```

Choose checks by changed risk. Routine composition of supported steps normally needs validate/render, not a full lifecycle, all tasks, independent review or two mandatory pasted status blocks. Use `render --write` only when maintained documentation has the relevant markers. Report concise actual results and limitations instead of full successful output.

For a new or changed mechanism, use synthetic declarations and focused positive/negative regressions. Trace YAML, recorders, hooks, completion readers and bindings together. Do not freeze a copy of mutable production policy into mechanism tests. `when` predicates must agree across status, code freeze and approval; use approval `purpose: contract` or `purpose: result` instead of guessing stage names.

## 5. Show the change

Tell the human what obligation changed, what actually passed and what remains unverified. Land only within the project's authorized Git/publication boundaries. Local delivery never grants merge/push/deploy permission. Removing an obligation requires tracing live consumers, not just deleting its visible YAML step.

## Do not

- Do not encode a decision that changes often into a gate parameter scattered across pipelines — put the value in `profile_config` and read it in the gate.
- Do not make a gate call the network on every evaluation; if it must, cache it and return UNKNOWN on failure, never PASS.
- Do not remove a `required` step to unblock one subject. Fix the subject or ask the human.
