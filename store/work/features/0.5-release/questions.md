# Questions: 0.5 release

<!--
One `## Q:` per unknown; the person answers in the chat, the agent records the answer with
svod answer work/features/0.5-release --q <n> <text>. Never write A: lines by hand.
-->

## Q: Do the three tasks of breakdown.md block the 0.5.0 tag, or may some ship in 0.5.1?
Options: all three block the tag (the release waits for them); only `external-phrase-match` blocks it (a guard rail that lets a negation through) and the others follow in 0.5.1; none blocks it (tag `[Unreleased]` as it is, the tasks go to 0.5.1).
A: Yes, the three tasks block the 0.5.0 tag (chat: «да»).
  by: morinv, at: 2026-10-17, prompt: 4cb9d719caa0

## Q: Does 0.5.0 break anything for a store made by 0.4?
Options: no (every new key is opt-in; Migration: none); yes, in behaviour: the prompt hook now leaves `svod-human.json` on every reply and `pre-tool` holds `git push` until a go-ahead (Migration: tell teams to expect the go-ahead question).
A: Does not matter: there is nothing on 0.4 to break (chat: «необязательно - на 0.4 нет ничего»).
  by: morinv, at: 2026-10-17, prompt: 4cb9d719caa0
