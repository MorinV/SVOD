# Contract: external-phrase-match

<!--
What the person approves together with card.md and questions.md
(svod approve work/tasks/external-phrase-match --step approve). Any edit afterwards voids the approval.
Draft: the answers to questions.md decide the matching rule below.
-->

## Result

`go` of the human mark is true only when the reply starts with one of `external_effects.phrases` (letter case and surrounding punctuation aside) or, per the answer to question 1, is that phrase alone. A phrase elsewhere in the reply, or preceded by a negation, leaves `go` false.

## Boundaries

- `svod`: `svod/hooks/prompt.py` (`says_go`, `GO_RE`), `tests/test_hooks.py`, `docs/reference.md` and its copy in `svod/templates/local/docs/`, `CHANGELOG.md`.
- Not touched: `svod/hooks/external.py` (what is held stays the same), the approval phrases, the locale texts other than the refusal hint if its wording names where the phrase goes.

## Effects

Commits on the task branch in the worktree of `svod`. Push and the pull request only after the person says so.

## Checks

`bash profile/actions/checks.sh work/tasks/external-phrase-match` runs `python3 -m pytest -q` in the worktree, with the cases of the acceptance.

## Risks

A person used to "ok давай" or "да, go ahead" is refused once more and must start the reply with the phrase; the refusal text (`hook.deny_external`) has to say so.
