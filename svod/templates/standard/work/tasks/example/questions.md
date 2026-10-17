# Questions: EXAMPLE-1

<!--
Everything the agent does not know and must not invent, one `## Q:` per question. Ask the person
in the chat, wait, then record each answer with svod answer work/tasks/<name> --q <n> <text>.
A record with nothing to ask holds the single line: none
-->

## Q: Which field holds the user's name: `display_name` or `first_name`?
Options: `display_name` (shown in the UI) or `first_name` (from the profile).
A: display_name; fall back to "Hello" when it is empty.

## Q: Is the greeting translated?
A: Not in this task.
