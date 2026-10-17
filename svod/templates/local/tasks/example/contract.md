# Contract: EXAMPLE

<!--
The compact contract a person approves together with testing/plan.yaml
(svod approve tasks/<name> --step initial_approve). The approval is bound to the
exact bytes of both files: any edit after approval invalidates it, comments included.
Replace every paragraph below with the real decision before asking for approval.
-->

## Result

<!-- The single result this task delivers, as the person will judge it. -->
Replace with the result.

## Boundaries

<!-- What is in scope and, explicitly, what is not touched. -->
Replace with the files, modules or behaviour in and out of scope.

## Effects

<!-- Effects the person authorises. Local edits and commits only by default: no push, merge, deployment or credentials unless named here. -->
Local edits and commits in the source checkout named in testing/plan.yaml; nothing else.

## Checks

<!-- How the result is checked; the real argv lives in testing/plan.yaml under command. -->
Replace with what the command in testing/plan.yaml runs and what it proves.

## Risks

<!-- What can go wrong and how it would be noticed or undone. -->
Replace with the known risks, or say there are none worth noting.
