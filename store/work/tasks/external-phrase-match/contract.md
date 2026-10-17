# Contract: external-phrase-match

<!--
What the person approves together with card.md and questions.md
(svod approve work/tasks/external-phrase-match --step approve). Any edit afterwards voids the approval.
Per questions.md: a line of its own only; "давай не будем" is no go-ahead.
-->

## Result

`go` of the human mark is true only when one of `external_effects.phrases` stands on a line of its own in the reply: nothing but spaces before it on the line, nothing but punctuation after it (letter case aside). A phrase inside a sentence, however placed and negated or not, leaves `go` false; no list of negations is needed.

## Boundaries

- `svod`: `svod/hooks/prompt.py` (`says_go`, `go_at`; the negation constants go), `tests/test_hooks.py`, `docs/reference.md` and its copy in `svod/templates/local/docs/`, `CHANGELOG.md`.
- Not touched: `svod/hooks/external.py` (what is held stays the same), the approval phrases, the locale texts other than the refusal hint if its wording names where the phrase goes.

## Effects

Commits on the task branch in the worktree of `svod`. Push and the pull request only after the person says so.

## Checks

`bash profile/actions/checks.sh work/tasks/external-phrase-match` runs `python3 -m pytest -q` in the worktree, with the cases of the acceptance.

## Risks

A person used to "ok давай" or "да, go ahead" is refused once more and must put the phrase on a line of its own; the refusal text (`hook.deny_external`) has to say so.
