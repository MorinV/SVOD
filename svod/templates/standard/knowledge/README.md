# Knowledge

Lasting answers the team and the agents read before asking again: how a service behaves, why a decision holds, where a value comes from.

- One topic per file: `knowledge/<topic>.md`, a title, the answer first, then the details.
- Open it with frontmatter: `title`, `tags` (a list), `source`, `date`, `status: current`; a file with neither `title` nor `tags` is not a note and stays out of `INDEX.md` and of the agent's context. `svod knowledge note` and `svod knowledge add` write the frontmatter.
- Name the source of every claim: a file, a command, a research record (`work/research/<name>`) or a person and a date.
- A research with `outcome: knowledge` writes its answer here and names the file in its card: `knowledge: knowledge/<topic>.md`.
- Fix a wrong answer in place and say what changed; delete a topic nobody needs.
