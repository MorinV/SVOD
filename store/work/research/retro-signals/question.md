# Question: which evidence signals predict rework

## The question

Over the finished records of a store, which events of the evidence log, or patterns of them, are more frequent in records that needed rework than in records that did not?

Rework, for this research: a later hotfix whose `cause` names the record, a `position_changed` back to an earlier step after `checks`, or an `approval_drift` after the contract approval.

## Why it matters

A retrospective that reports every event is noise. One that names two or three signals with a measured link to rework tells a team what to change in its process: ask more questions, split a task, run the checks earlier.

## Candidates to test

These are guesses, not findings:

- `approval_drift` on the contract approval (the plan changed after the person saw it);
- the number of `position_changed` lines that go back to `questions` or `contract`;
- `hook_denied` with `rule: plan` (the agent tried to code before the approval);
- `checks_run` with `passed: false` before the first pass, and their count;
- `unknown_gate` on a step that later passed (a check nobody could run at the time).

## What answer would change the plan

- One or two signals with a clear link: the retro of a record shows them first, and the feature that builds the retro starts from them.
- No signal with a link: the log needs other facts (for example the size of the diff or the number of questions), and the evidence format changes before any retro is built.
- Too little data: keep collecting in `store/` of this repository and in one team store; set a date to look again.
