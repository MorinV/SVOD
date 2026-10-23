# Knowledge

Lasting answers the team and the agents read before asking again: how a service behaves, why a decision holds, where a value comes from.

- One topic per file: `knowledge/<topic>.md`, a title, the answer first, then the details.
- Open it with frontmatter: `title`, `tags` (a list), `source`, `date`, `status: current`; a file with neither `title` nor `tags` is not a note and stays out of `INDEX.md` and of the agent's context. `svod knowledge note` and `svod knowledge add` write the frontmatter.
- Name the source of every claim: a file, a command, a research record (`<record>`) or a person and a date.
- For research with `outcome: knowledge`, run `svod knowledge publish <record>`. It shows the findings snapshot; after the person's next configured go-ahead, repeat it to publish and close. It preserves findings, records source and consent provenance, refuses collisions, and safely retries a matching publication. A manually written `status: done` is not consent.
- Retire a replaced answer with `svod knowledge supersede knowledge/old.md --by knowledge/new.md`: bodies stay intact, the index is updated, and the old note leaves current context. Self-links, cycles and unsafe paths are refused.
- Fix a wrong answer in place and say what changed; delete a topic nobody needs.
