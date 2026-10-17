"""Loading of config, pipelines and locale; the validate command."""
import tempfile
import unittest
from pathlib import Path

import support
from support import (EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, TempStore, core_lead, core_text,
                     make_profile)

from svod import keys
from svod.config import DEFAULT_BRANCH_FALLBACK, find_root, load_config
from svod.errors import LoadError, LocaleError
from svod.loader import load_runtime
from svod.locale import Locale, load_locale
from svod.pipeline import parse_pipeline

MINIMAL_PIPELINE = """
    pipeline: toy
    subject: { provider: container, params: { roots: [boxes] } }
    steps:
      - id: first
        text: toy.first
        gates: [ { gate: exists } ]
"""
MINIMAL_LOCALE = """
    toy:
      first: "first step"
"""


def pipeline_dict(**overrides):
    """Minimal valid pipeline mapping with overrides applied."""
    data = {
        "pipeline": "toy",
        "subject": {"provider": "container", "params": {"roots": ["boxes"]}},
        "steps": [{"id": "first", "text": "toy.first", "gates": [{"gate": "exists"}]}],
    }
    data.update(overrides)
    return data


class ConfigTest(unittest.TestCase):
    """svod.yaml discovery and validation."""

    def setUp(self):
        """Temporary store with the test profile."""
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)

    def test_find_root_walks_up(self):
        """The root is found from nested directories and not above the store."""
        nested = self.sb.store / "a" / "b"
        nested.mkdir(parents=True)
        cases = ((self.sb.store, self.sb.store), (nested, self.sb.store), (self.sb.parent, None))
        for start, expected in cases:
            with self.subTest(start=start):
                found = find_root(start)
                self.assertEqual(found, expected.resolve() if expected else None)

    def test_valid_config(self):
        """Paths resolve against the root; missing default branch falls back."""
        self.sb.write("svod.yaml", f"locale: en\nprofile: {support.TEST_PROFILE}\n")
        config = load_config(self.sb.store)
        self.assertEqual(config.profile, support.TEST_PROFILE.resolve())
        self.assertEqual(config.default_branch, DEFAULT_BRANCH_FALLBACK)
        self.assertIsNone(config.workspaces)
        self.assertEqual(config.active_order, ())
        self.assertEqual(config.profile_config, {})

    def test_profile_config_is_passed_through(self):
        """profile_config reaches the profile as written; the core reads none of its keys."""
        cases = (
            ("empty", "", {}),
            ("nested", "profile_config:\n  landing: { mode: pr, target: main }\n",
             {"landing": {"mode": "pr", "target": "main"}}),
        )
        for name, extra, expected in cases:
            with self.subTest(name=name):
                self.sb.write("svod.yaml",
                              f"locale: en\nprofile: {support.TEST_PROFILE}\n{extra}")
                self.assertEqual(load_config(self.sb.store).profile_config, expected)

    def test_invalid_configs(self):
        """Each broken config yields a LoadError naming the problem."""
        profile = support.TEST_PROFILE
        cases = (
            ("unknown key", f"locale: en\nprofile: {profile}\ncolour: red\n", "unknown key: colour"),
            ("missing locale", f"profile: {profile}\n", "missing key: locale"),
            ("missing profile dir", "locale: en\nprofile: nowhere\n", "profile directory not found"),
            ("not a mapping", "- a\n- b\n", "expected a mapping"),
            ("bad yaml", "locale: [\n", "invalid YAML"),
            ("empty string", f"locale: ''\nprofile: {profile}\n", "locale must be a non-empty"),
            ("bad order", f"locale: en\nprofile: {profile}\nactive_order: task\n", "active_order"),
            ("bad profile config", f"locale: en\nprofile: {profile}\nprofile_config: [a]\n",
             "profile_config must be a mapping"),
        )
        for name, text, message in cases:
            with self.subTest(name=name):
                self.sb.write("svod.yaml", text)
                with self.assertRaises(LoadError) as ctx:
                    load_config(self.sb.store)
                self.assertIn(message, str(ctx.exception))


class PipelineSchemaTest(unittest.TestCase):
    """Schema validation of pipeline declarations."""

    def test_valid_minimal(self):
        """The minimal declaration parses without errors."""
        pipeline, errors = parse_pipeline(pipeline_dict(), Path("toy.yaml"))
        self.assertEqual(errors, [])
        self.assertEqual([s.id for s in pipeline.steps], ["first"])

    def test_schema_errors(self):
        """Every class of schema error is reported with its location."""
        step = {"id": "first", "text": "toy.first", "gates": [{"gate": "exists"}]}
        second = {"id": "second", "text": "toy.second", "gates": [{"gate": "exists"}]}
        cases = (
            ("unknown top key", pipeline_dict(extra=1), "top level: unknown key: extra"),
            ("missing steps", {k: v for k, v in pipeline_dict().items() if k != "steps"},
             "missing key: steps"),
            ("unknown step key", pipeline_dict(steps=[dict(step, colour="red")]),
             "steps[0]: unknown key: colour"),
            ("unknown gate key", pipeline_dict(steps=[dict(step, gates=[{"gate": "exists",
                                                                          "x": 1}])]),
             "steps[0].gates[0]: unknown key: x"),
            ("duplicate ids", pipeline_dict(steps=[step, step]), "duplicate step id: first"),
            ("bad id", pipeline_dict(steps=[dict(step, id="Bad.Id")]), "id must match"),
            ("step without text", pipeline_dict(steps=[{"id": "first", "gates": [{"gate": "exists"}]}]),
             "text is required unless every gate has its own"),
            ("gateless step without text", pipeline_dict(steps=[{"id": "first"}]),
             "text is required"),
            ("optional and required", pipeline_dict(steps=[dict(step, optional=True,
                                                                 required=True)]),
             "optional excludes"),
            ("flag not boolean", pipeline_dict(steps=[dict(step, required="yes")]),
             "required must be a boolean"),
            ("bad severity", pipeline_dict(entry=[{"gate": "exists", "severity": "loud",
                                                   "text": "t"}]),
             "severity must be one of"),
            ("entry without severity", pipeline_dict(entry=[{"gate": "exists", "text": "t"}]),
             "entry[0]: missing key: severity"),
            ("missing without text", pipeline_dict(missing={"gate": "exists"}),
             "missing: missing key: text"),
            ("missing with severity", pipeline_dict(missing={"gate": "exists", "text": "t",
                                                             "severity": "warn"}),
             "missing: unknown key: severity"),
            ("missing with pending", pipeline_dict(missing={"gate": "exists", "text": "t",
                                                            "pending": "p"}),
             "missing: unknown key: pending"),
            ("step gate with pending", pipeline_dict(steps=[dict(step, gates=[
                {"gate": "exists", "pending": "p"}])]),
             "steps[0].gates[0]: unknown key: pending"),
            ("unknown subject key", pipeline_dict(subject={"provider": "container", "y": 1}),
             "subject: unknown key: y"),
            ("unknown active key", pipeline_dict(active={"colour": 1}),
             "active: unknown key: colour"),
            ("unknown heading", pipeline_dict(active={"headings": {"odd": "k"}}),
             "unknown key: odd"),
            ("violation unknown step", pipeline_dict(violations={"first.nope": "k"}),
             "expected <later step>.<earlier step>"),
            ("violation wrong order", pipeline_dict(
                steps=[dict(step, required=True), second], violations={"first.second": "k"}),
             "first must come after second"),
            ("violation earlier not required", pipeline_dict(
                steps=[step, second], violations={"second.first": "k"}),
             "first is not required"),
        )
        for name, data, message in cases:
            with self.subTest(name=name):
                pipeline, errors = parse_pipeline(data, Path("toy.yaml"))
                self.assertIsNone(pipeline)
                self.assertTrue(any(message in e for e in errors), errors)
                self.assertTrue(all(e.startswith("toy.yaml: ") for e in errors), errors)


class LocaleTest(unittest.TestCase):
    """Locale lookup, substitution and merge."""

    def test_text_substitutes_facts(self):
        """Placeholders are filled from facts."""
        self.assertEqual(Locale({"k": "n={count}"}).text("k", count=3), "n=3")

    def test_missing_key_and_placeholder_raise(self):
        """A missing key or fact is an error, not the raw key."""
        locale = Locale({"k": "n={count}"})
        for key, facts in (("absent", {}), ("k", {})):
            with self.subTest(key=key):
                with self.assertRaises(LocaleError):
                    locale.text(key, **facts)

    def test_profile_overrides_core_and_required_keys(self):
        """Profile strings win over core ones; a required key missing fails the load."""
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(tmp, {}, 'validate:\n  ok: "fine {count}"\nextra: "x"\n')
            locale = load_locale("en", profile, required=("extra",))
            self.assertEqual(locale.text("validate.ok", count=1), "fine 1")
            with self.assertRaises(LoadError) as ctx:
                load_locale("en", profile, required=("extra", "absent.key"))
            self.assertIn("missing key: absent.key", str(ctx.exception))

    def test_bad_locale_files(self):
        """Non-string values and broken templates are load errors."""
        cases = (("list value", "a: [1, 2]\n", "value must be a string"),
                 ("bad template", 'a: "{oops"\n', "bad template"))
        for name, text, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                profile = make_profile(tmp, {}, text)
                with self.assertRaises(LoadError) as ctx:
                    load_locale("en", profile)
                self.assertIn(message, str(ctx.exception))


class RuntimeTest(unittest.TestCase):
    """Whole-store loading: registries and cross-file checks."""

    def load(self, pipelines, locale_text, **config):
        """Load a store built around a temporary profile."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        profile = make_profile(Path(tmp.name) / "profile", pipelines, locale_text)
        sb = TempStore(profile=profile, **config)
        self.addCleanup(sb.cleanup)
        return load_runtime(sb.store)

    def test_minimal_profile_loads(self):
        """A consistent profile loads into a runtime."""
        runtime = self.load({"toy.yaml": MINIMAL_PIPELINE}, MINIMAL_LOCALE)
        self.assertEqual([p.name for p in runtime.pipelines], ["toy"])

    def test_cross_file_errors(self):
        """Unknown gates, providers, params, locale keys and duplicates are reported."""
        cases = (
            ("unknown gate", MINIMAL_PIPELINE.replace("gate: exists", "gate: nope"),
             "unknown gate: nope"),
            ("unknown provider", MINIMAL_PIPELINE.replace("provider: container", "provider: nope"),
             "unknown provider: nope"),
            ("bad gate params", MINIMAL_PIPELINE.replace("{ gate: exists }",
                                                         "{ gate: artifact, params: { min: 2 } }"),
             "exactly one of path and glob"),
            ("bad provider params", MINIMAL_PIPELINE.replace("roots: [boxes]", "roots: []"),
             "roots must be a non-empty list"),
            ("missing locale key", MINIMAL_PIPELINE.replace("toy.first", "toy.absent"),
             "missing key: toy.absent"),
            ("key gate is not a key gate", MINIMAL_PIPELINE.replace(
                "provider: container,", "provider: container, key_gate: exists,"),
             "exists does not recognise keys"),
        )
        for name, text, message in cases:
            with self.subTest(name=name):
                with self.assertRaises(LoadError) as ctx:
                    self.load({"toy.yaml": text}, MINIMAL_LOCALE)
                self.assertIn(message, str(ctx.exception))

    def test_duplicate_pipeline_and_unknown_order(self):
        """Two files with one name and an unknown active_order entry are errors."""
        with self.assertRaises(LoadError) as ctx:
            self.load({"a.yaml": MINIMAL_PIPELINE, "b.yaml": MINIMAL_PIPELINE}, MINIMAL_LOCALE,
                      active_order="[ghost]")
        self.assertIn("duplicate pipeline name: toy", str(ctx.exception))
        self.assertIn("active_order: unknown pipeline: ghost", str(ctx.exception))


class ValidateCommandTest(unittest.TestCase):
    """svod validate as a black box."""

    def test_test_profile_is_valid(self):
        """The bundled test profile validates from the tests directory."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        out = sb.cli("validate", cwd=support.TESTS_DIR)
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn(core_lead(keys.VALIDATE_OK), out.stdout)

    def test_invalid_profile_lists_errors(self):
        """Validation errors are listed and the exit code is 1."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        text = MINIMAL_PIPELINE.replace("gate: exists", "gate: nope")
        profile = make_profile(Path(tmp.name) / "p", {"toy.yaml": text}, MINIMAL_LOCALE)
        sb = TempStore(profile=profile)
        self.addCleanup(sb.cleanup)
        out = sb.cli("validate")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn(core_text(keys.VALIDATE_FAILED, count=1), out.stderr)
        self.assertIn("unknown gate: nope", out.stderr)

    def test_not_store_root(self):
        """Outside a store the not-root message is printed with exit code 2."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        out = sb.cli("validate", cwd=sb.parent)
        self.assertEqual(out.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.ERROR_NOT_ROOT), out.stderr)
        explicit = sb.cli("--root", str(sb.parent), "validate", cwd=sb.store)
        self.assertEqual(explicit.returncode, EXIT_USAGE)

    def test_ru_locale_not_root(self):
        """The environment picks the core locale used before a config is found."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        sb.env["SVOD_LOCALE"] = "ru"
        out = sb.cli("validate", cwd=sb.parent)
        self.assertEqual(out.returncode, EXIT_USAGE)
        self.assertNotIn(core_text(keys.ERROR_NOT_ROOT), out.stderr)
        self.assertTrue(out.stderr.strip())


if __name__ == "__main__":
    unittest.main()
