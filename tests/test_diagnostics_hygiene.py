"""Native diagnostics and test-environment hygiene regressions."""
import json
from unittest.mock import patch

import test_relations as relations
from support import StoreTestCase
from test_position import change


class CompactStatusTest(StoreTestCase):
    def test_native_json_omits_empty_optional_values_and_keeps_false_zero(self):
        change(self.sb, "c-4", "tk-4", spec=True, design=True)
        result = self.sb.cli_process("status", "tk-4", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["report"], {"ok": True, "refused": False, "exit_code": 0})
        self.assertFalse(data["resolution"]["ambiguous"])

        def assert_compact(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(child, (None, "", [], {}), key)
                    assert_compact(child)
            elif isinstance(value, list):
                for child in value:
                    assert_compact(child)

        assert_compact(data)
        self.assertNotIn("children", data["positions"][0])
        self.assertEqual(data["positions"][0]["instruction"],
                         data["next_action"][0]["instruction"])
        change(self.sb, "c-5", "tk-5", spec=False, design=False)
        zero = json.loads(self.sb.cli_process("status", "tk-5", "--format", "json").stdout)
        counts = [outcome["facts"]["count"]
                  for step in zero["positions"][0]["steps"]
                  for outcome in step.get("outcomes", []) if "count" in outcome.get("facts", {})]
        self.assertIn(0, counts)
        self.sb.write("svod.yaml", "PRIVATE: [malformed")
        result = self.sb.cli_process("status", "tk-4", "--format", "json")
        self.assertEqual(result.returncode, 2)
        error = json.loads(result.stdout)
        assert_compact(error)
        self.assertEqual(error["resolution"]["kind"], "not_evaluated")
        self.assertNotIn("PRIVATE", result.stdout + result.stderr)


class ChildDetailsTest(relations.WorkStoreTestCase):
    def test_children_opt_in_skips_details_but_retains_completion_gates(self):
        relations.write_work(self.sb, "work/features/parent")
        relations.write_work(self.sb, "work/tasks/child", parent="work/features/parent")
        with patch("svod.status.child_positions", side_effect=AssertionError("detail collection")):
            result = self.sb.cli("status", "parent", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["positions"][0]["done"])
        self.assertNotIn("children", data["positions"][0])
        detailed = self.sb.cli_process("status", "parent", "--format", "json", "--children")
        self.assertEqual(detailed.returncode, 0, detailed.stderr)
        children = json.loads(detailed.stdout)["positions"][0]["children"]
        self.assertEqual(children[0]["id"], "work/tasks/child")
        self.assertFalse(children[0]["done"])
        baseline = self.sb.cli("status", "parent")
        explicit = self.sb.cli("status", "parent", "--children")
        self.assertEqual((baseline.stdout, baseline.stderr), (explicit.stdout, explicit.stderr))
        relations.write_work(self.sb, "work/tasks/child",
                             parent="work/features/parent", status="done")
        completed = self.sb.cli_process("status", "parent", "--format", "json")
        self.assertTrue(json.loads(completed.stdout)["positions"][0]["done"])


class ValidateWarningsTest(StoreTestCase):
    def profile(self, gate_source=""):
        from support import make_profile
        profile = make_profile(self.sb.root / "profile", {"toy.yaml": """
            pipeline: toy
            subject: {provider: container, params: {roots: [work], head_type: work}}
            steps:
              - id: plan
                text: toy.plan
                gates: [{gate: exists}]
        """}, """
            toy:
              plan: Plan
              plan_missing: Missing
              unused: Orphan
        """, gates={"dynamic.py": gate_source} if gate_source else None)
        self.sb.write("svod.yaml", f"profile: {profile}\nlocale: en\n")
        return profile

    def test_unused_locale_and_unbound_steps_warn_without_running_gates(self):
        self.profile()
        with patch("svod.gates.ExistsGate.evaluate", side_effect=AssertionError("gate executed")):
            result = self.sb.cli("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unused-profile-locale", result.stderr)
        self.assertIn("toy.unused", result.stderr)
        self.assertNotIn("toy.plan_missing", result.stderr)
        self.assertIn("no-skill", result.stderr)
        self.assertIn("toy.plan", result.stderr)
        self.assertIn("Configuration is valid", result.stdout)

    def test_dynamic_locale_usage_is_not_confidently_unused(self):
        self.profile("""
from svod.gates import Gate
class Dynamic(Gate):
    name = "dynamic"
    def evaluate(self, ctx, subject):
        return ctx.locale.text(subject.id)
GATES = {"dynamic": Dynamic}
""")
        result = self.sb.cli_process("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("unused-profile-locale", result.stderr)
        self.assertIn("no-skill", result.stderr)


class EnvironmentHygieneTest(StoreTestCase):
    def test_host_pollution_is_removed_but_explicit_overrides_survive(self):
        import os
        from support import child_env
        pollution = {"SVOD_LOCALE": "nonexistent", "SVOD_ROOT": "/hostile",
                     "SVOD_FUTURE_OPTION": "hostile"}
        with patch.dict(os.environ, pollution):
            clean = child_env()
            self.assertFalse(any(name.startswith("SVOD_") for name in clean))
            explicit = child_env(SVOD_LOCALE="ru", SVOD_FUTURE_OPTION="fixture")
            self.assertEqual(explicit["SVOD_LOCALE"], "ru")
            self.assertEqual(explicit["SVOD_FUTURE_OPTION"], "fixture")
            for invoke in (self.sb.cli, self.sb.cli_process):
                result = invoke("validate", cwd=self.sb.parent)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Run from the store root", result.stderr)
                russian = invoke("validate", cwd=self.sb.parent, SVOD_LOCALE="ru")
                self.assertEqual(russian.returncode, 2)
                self.assertNotIn("Run from the store root", russian.stderr)
            self.assertEqual(os.environ["SVOD_LOCALE"], "nonexistent")


class BindingDiagnosticsTest(StoreTestCase):
    profile = ValidateWarningsTest.profile

    def test_static_binding_reachability_and_invalid_configuration_separation(self):
        profile = self.profile()
        pipeline = profile / "pipelines/toy.yaml"
        pipeline.write_text(pipeline.read_text().replace("id: plan", "id: plan\n    role: planner"))
        config = (self.sb.store / "svod.yaml").read_text()
        self.sb.write("svod.yaml", config + "bindings: bindings.yaml\n")
        cases = [
            ("[{skill: external, external: true}]", False),
            ("[{skill: null}]", True),
            ("[{skill: null}, {skill: unreachable, external: true}]", True),
        ]
        for rules, warning in cases:
            with self.subTest(rules=rules):
                self.sb.write("bindings.yaml", "roles:\n  planner: " + rules + "\n")
                result = self.sb.cli_process("validate")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("[no-skill]" in result.stderr, warning)
        self.sb.write("bindings.yaml", "probe: {gate: exists, fact: paths}\nroles:\n"
                      "  planner: [{when: {has_file: dynamic}, skill: ext, external: true}]\n")
        with patch("svod.gates.ExistsGate.evaluate", side_effect=AssertionError("probe executed")):
            conditional = self.sb.cli("validate")
        self.assertEqual(conditional.returncode, 0, conditional.stderr)
        self.assertNotIn("[no-skill]", conditional.stderr)
        self.sb.write("bindings.yaml", "roles: {}\n")
        invalid = self.sb.cli("validate")
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("is not described", invalid.stderr)
        self.assertNotIn("[no-skill]", invalid.stderr)

    def test_literal_custom_description_key_and_instruction_variants_are_used(self):
        profile = self.profile("""
from svod.gates import Gate, verdict
class Custom(Gate):
    name = "custom"
    def evaluate(self, ctx, subject):
        raise AssertionError("validate must not evaluate")
    def describe(self, params, locale):
        return locale.text("custom.description")
GATES = {"custom": Custom}
""")
        pipeline = profile / "pipelines/toy.yaml"
        pipeline.write_text(pipeline.read_text().replace("gate: exists", "gate: custom"))
        locale = profile / "locale/en.yaml"
        with locale.open("a") as stream:
            stream.write('custom:\n  description: "Custom label"\n')
        result = self.sb.cli_process("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("toy.unused", result.stderr)
        self.assertNotIn("custom.description", result.stderr)
        self.assertNotIn("toy.plan_missing", result.stderr)
