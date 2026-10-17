# Contract: EXAMPLE-1

<!--
What the person approves together with card.md and questions.md
(svod approve work/tasks/<name> --step approve). Any edit afterwards voids the approval.
-->

## Result

The start page of `app` greets a signed-in user as "Hello, <display_name>".

## Boundaries

- `app`: the start page template and its view; nothing else.
- Not touched: translations, the user model, other pages.

## Effects

Commits on the task branch in the `app` worktree. Push, merge and deploy only after the person says so.

## Checks

`bash profile/actions/checks.sh work/tasks/<name>` runs the tests of `app`, with a new test for both greetings.

## Risks

An empty `display_name` would print "Hello, "; the fallback and its test cover it.
