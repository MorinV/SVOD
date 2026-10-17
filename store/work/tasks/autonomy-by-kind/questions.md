# Questions: autonomy-by-kind

<!--
One `## Q:` per unknown; the person answers in the chat, the agent records the answer with
svod answer work/tasks/autonomy-by-kind --q <n> <text>. Never write A: lines by hand.
-->

## Q: When both the pipeline and the kind have a level, which one applies to a subject?
Options: the kind wins (a hotfix is `autonomous` even in a `guided` task pipeline); the more permissive of the two; the stricter of the two (a kind can only tighten).
A: The level of the kind applies (chat: «kind»).
  by: morinv, at: 2026-10-17, prompt: 4cb9d719caa0

## Q: Which kinds may `autonomy` name: only `hotfix`, or any value of the frontmatter field `kind`?
Options: only `hotfix` as now (`AUTONOMY_KINDS` in `svod/config.py`); any kind, which makes a typo in a kind name impossible to report at load; kinds a profile declares (a new key, more surface).
A: Only hotfix for now (chat: «оставим пока hotfix»).
  by: morinv, at: 2026-10-17, prompt: 4cb9d719caa0
