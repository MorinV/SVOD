"""The reference names every key the validator accepts, every core gate and provider, its params."""
import argparse
import dataclasses
import re
import unittest

from support import ENCODING, REPO_DIR

from svod import cli
from svod import bindings, config, keys, pipeline
from svod.gates import CORE_GATES, GATES_ATTR, PROVIDERS_ATTR, Result
from svod.locale import LOCALE_ENV
from svod.providers import CORE_PROVIDERS
from svod.subject import ATTR_CONTAINER, ATTR_FRONTMATTER

REFERENCE = REPO_DIR / "docs" / "reference.md"
SECTION_PREFIX = "## "
SUBSECTION_PREFIX = "### "
MENTION = r"`{name}[` ]"
HELP_FLAGS = frozenset({"-h", "--help"})

CONFIG_SECTION = "svod.yaml"
PIPELINE_SECTION = "Pipeline file"
STEP_SECTION = "Step"
GATE_USE_SECTION = "Gate use"
GATES_SECTION = "Core gates"
PROVIDERS_SECTION = "Subject providers"
ACTIVE_SECTION = "Active summary"
BINDINGS_SECTION = "Bindings file"
LOCALE_SECTION = "Locale"
RENDER_SECTION = "Render"
CUSTOM_GATE_SECTION = "Writing a custom gate"
CLI_SECTION = "CLI"

EXPECTED = (
    (CONFIG_SECTION, config.KNOWN_FIELDS),
    (PIPELINE_SECTION, pipeline.PIPELINE_FIELDS | pipeline.SUBJECT_FIELDS),
    (STEP_SECTION, pipeline.STEP_FIELDS),
    (GATE_USE_SECTION, pipeline.ENTRY_FIELDS | pipeline.DONE_FIELDS | pipeline.STEP_GATE_FIELDS
     | pipeline.IN_PROGRESS_FIELDS | frozenset(pipeline.SEVERITIES)),
    (ACTIVE_SECTION, pipeline.ACTIVE_FIELDS | frozenset(pipeline.HEADING_GROUPS)),
    (BINDINGS_SECTION, bindings.TOP_FIELDS | bindings.PROBE_FIELDS | bindings.RULE_FIELDS
     | bindings.WHEN_FIELDS),
    (PROVIDERS_SECTION, frozenset({ATTR_CONTAINER, ATTR_FRONTMATTER})),
    (LOCALE_SECTION, frozenset(keys.CORE_KEYS) | {LOCALE_ENV}),
    (RENDER_SECTION, frozenset({config.FIELD_RENDER_EXCLUDE})),
    (CUSTOM_GATE_SECTION, frozenset({GATES_ATTR, PROVIDERS_ATTR})
     | {f.name for f in dataclasses.fields(Result)}),
)


def split(text, prefix):
    """Heading to body for headings of one level."""
    parts, name = {}, None
    for line in text.splitlines():
        if line.startswith(prefix):
            name = line[len(prefix):].strip().strip("`")
            parts[name] = []
        elif name is not None:
            parts[name].append(line)
    return {k: "\n".join(v) for k, v in parts.items()}


def mentioned(text, name):
    """Whether the text names the key in backticks, alone or followed by an argument."""
    return re.search(MENTION.format(name=re.escape(name)), text) is not None


def cli_options():
    """(command, option) pairs of the CLI; the command is None for global options."""
    parser = cli.build_parser()
    found = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for command, sub in action.choices.items():
                found.append((command, None))
                found += [(command, o) for a in sub._actions for o in a.option_strings
                          if o not in HELP_FLAGS]
        else:
            found += [(None, o) for o in action.option_strings if o not in HELP_FLAGS]
    return found


class ReferenceTest(unittest.TestCase):
    """The reference stays in step with the validator, the registries and the CLI."""

    @classmethod
    def setUpClass(cls):
        """Sections of the reference by heading."""
        cls.sections = split(REFERENCE.read_text(encoding=ENCODING), SECTION_PREFIX)

    def section(self, name):
        """Body of one top-level section."""
        self.assertIn(name, self.sections, f"section {name} is missing")
        return self.sections[name]

    def assert_mentions(self, where, text, names):
        """Every name is mentioned in the text."""
        for name in sorted(names):
            with self.subTest(section=where, key=name):
                self.assertTrue(mentioned(text, name), f"{where}: `{name}` is not documented")

    def test_keys(self):
        """Every accepted key is documented in its section."""
        for where, names in EXPECTED:
            self.assert_mentions(where, self.section(where), names)

    def test_core_gates(self):
        """Every core gate has a subsection naming each of its params."""
        gates = split(self.section(GATES_SECTION), SUBSECTION_PREFIX)
        for name, cls in CORE_GATES.items():
            with self.subTest(gate=name):
                self.assertIn(name, gates)
            self.assert_mentions(name, gates.get(name, ""), cls.PARAMS)

    def test_providers(self):
        """Every core provider has a subsection naming each of its params."""
        providers = split(self.section(PROVIDERS_SECTION), SUBSECTION_PREFIX)
        for name, cls in CORE_PROVIDERS.items():
            with self.subTest(provider=name):
                self.assertIn(name, providers)
            self.assert_mentions(name, providers.get(name, ""), cls.PARAMS)

    def test_cli(self):
        """Every command and flag of the CLI is documented."""
        names = {option or command for command, option in cli_options()}
        self.assert_mentions(CLI_SECTION, self.section(CLI_SECTION), names)


if __name__ == "__main__":
    unittest.main()
