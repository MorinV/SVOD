---
name: svod-pipeline
description: Use when changing profile/pipelines/*.yaml, profile/gates/*.py, profile/locale/*.yaml or svod.yaml - adding or removing a step, gate, approval or blocks_code - and before svod validate or svod render.
---

# Changing a Svod pipeline

The pipeline `profile/pipelines/<name>.yaml` defines the process. [The reference](https://github.com/MorinV/SVOD/blob/main/docs/reference.md) (`docs/reference.md` of the Svod repository) defines every key and wins over this skill. Land the change through the usual repository process, without a task card.

1. Before editing, agree with the person on the pipeline file, the step, the condition that passes it (a file, a field, an approval, a Git state), its flags (`required`, `blocks_code`, `optional`) and the text shown while it fails. A condition files and Git cannot show is no gate: keep a step without gates, which never passes, or drop it.
2. Pick a gate from the table below. Write a profile gate in `profile/gates/<module>.py` only when none fits ([Writing a custom gate](https://github.com/MorinV/SVOD/blob/main/docs/reference.md#writing-a-custom-gate)); keep it read-only and fast, because gates run on every `svod status` and in every hook.
3. Add the step to `steps` in its place, with `id` and `text`. Give an approval gate `purpose: contract` or `purpose: result` and the bound files in `bind`; Svod finds approvals by purpose, not by step name.
4. Add each new text key to every `profile/locale/<locale>.yaml`. Write it as an instruction: the next action with its command or file. Add `<text>_<reason>` keys where a gate's `reason` needs another instruction.
5. For a new kind of work, add a pipeline file with its `subject`; to list it at session start, add an `active` block and its name to `active_order` in `svod.yaml`.
6. To attach a skill, give the step a `role` and add a rule to the bindings file, for example `{ when: { has_file: go.mod }, skill: impl-go }`.
7. Put a value that changes often into `profile_config` in `svod.yaml` and read it in the gate. A gate that calls the network caches the answer and returns UNKNOWN on failure, never PASS.
8. Run `svod validate` and `svod render <pipeline>`, and `svod status <record>` on one affected record when a position should change. `svod render <pipeline> --write` updates only documents holding `<!-- pipeline:<name>:begin -->` markers.
9. For a new mechanism (gate, recorder, hook), add positive and negative tests on synthetic declarations, not on a copy of the live pipeline. Check that `when` gives the same answer in status, code freeze, approval and completion.
10. Tell the person which obligation changed, what passed and what stayed unchecked. Before removing a `required` step, find everything that reads it; never remove one to unblock a single record.

| Condition | Gate |
|---|---|
| a file or a glob exists in the subject | `artifact` |
| a frontmatter or metadata field has a value | `field` |
| a person approved in the chat, bound to the files' content | `approval` |
| a document of a type exists in the container | `doc_type` |
| the subject is archived | `archived` |
| the work is in the default branch | `git_pushed` |
| the subject exists at all | `exists` |
