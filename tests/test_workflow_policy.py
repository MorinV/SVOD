"""Generic workflow declarations, semantic selection and applicability."""
import importlib
import unittest
from pathlib import Path

import yaml

from svod.errors import ParamError
from svod.gates import ApprovalGate, ArtifactGate, ExistsGate
from svod.pipeline import parse_pipeline
from svod.position import position
from svod.subject import Subject


SYNTHETIC_YAML = """
pipeline: synthetic-route
subject:
  provider: synthetic-subjects
steps:
  - id: orchard
    text: synthetic.orchard
    gates:
      - gate: consent-alias
        purpose: scope_x
        params:
          marker: accepted_pear
          file: consent.yaml
          bind: [pear.md, inputs/*.yaml]
  - id: meadow
    text: synthetic.meadow
    gates:
      - gate: consent-alias
        purpose: result-y
        params:
          marker: accepted_grass
          file: decision.yaml
          bind: [grass.md]
"""


class SyntheticApproval(ApprovalGate):
    """Approval subclass with a name unrelated to production stage names."""

    name = "consent-alias"


def declaration():
    """Return fresh data through the real YAML decoder, not live profile policy."""
    return yaml.safe_load(SYNTHETIC_YAML)


def parse_case(test, data):
    """Assert successful real parsing without depending on the future API."""
    pipeline, errors = parse_pipeline(data, Path("synthetic-policy.yaml"))
    test.assertEqual(errors, [])
    test.assertIsNotNone(pipeline)
    assert pipeline is not None
    return pipeline


def bind_case(test, data):
    """Bind only synthetic gate instances; no provider, store or network needed."""
    pipeline = parse_case(test, data)
    registry = {"consent-alias": SyntheticApproval, "approval": ExistsGate,
                "artifact": ArtifactGate}
    for ref in pipeline.gate_refs():
        ref.impl = registry[ref.gate](ref.params)
    return pipeline


class DeclarationParserTest(unittest.TestCase):
    """FR-1/7: new declaration support and fail-closed invalid inputs."""

    def test_purpose_is_preserved_with_arbitrary_stages_and_markers(self):
        pipeline = parse_case(self, declaration())
        self.assertEqual([s.id for s in pipeline.steps], ["orchard", "meadow"])
        self.assertEqual([s.gates[0].purpose for s in pipeline.steps],
                         ["scope_x", "result-y"])
        self.assertEqual(pipeline.steps[0].gates[0].params["marker"], "accepted_pear")

    def test_step_when_is_preserved(self):
        data = declaration()
        for step in data["steps"]:
            step["gates"][0].pop("purpose")
        data["steps"][0]["when"] = "needs_scope"
        pipeline = parse_case(self, data)
        self.assertEqual(pipeline.steps[0].when, "needs_scope")
        self.assertIsNone(pipeline.steps[1].when)

    def test_step_gate_when_is_preserved(self):
        data = declaration()
        for step in data["steps"]:
            step["gates"][0].pop("purpose")
        data["steps"][0]["gates"][0]["when"] = "needs_scope"
        pipeline = parse_case(self, data)
        self.assertEqual(pipeline.steps[0].gates[0].when, "needs_scope")

    def test_absent_purpose_is_allowed(self):
        data = declaration()
        for step in data["steps"]:
            step["gates"][0].pop("purpose")
        pipeline = parse_case(self, data)
        self.assertIsNone(pipeline.steps[0].gates[0].purpose)

    def test_invalid_purpose_is_rejected(self):
        for value in ("", " ", "9scope", "Scope", "scope.one", "scope x", 3, False):
            with self.subTest(value=value):
                data = declaration()
                data["steps"][0]["gates"][0]["purpose"] = value
                pipeline, errors = parse_pipeline(data, "invalid-purpose.yaml")
                self.assertIsNone(pipeline)
                self.assertTrue(any("purpose" in error for error in errors), errors)

    def test_invalid_applicability_is_rejected(self):
        for location in ("step", "gate"):
            for value in ("", " ", "needs scope", "needs_scope == true", 3, False):
                with self.subTest(location=location, value=value):
                    data = declaration()
                    for step in data["steps"]:
                        step["gates"][0].pop("purpose")
                    target = data["steps"][0]
                    if location == "gate":
                        target = target["gates"][0]
                    target["when"] = value
                    pipeline, errors = parse_pipeline(data, "invalid-when.yaml")
                    self.assertIsNone(pipeline)
                    self.assertTrue(any("when" in error for error in errors), errors)

    def test_unknown_declaration_field_remains_rejected(self):
        data = declaration()
        for step in data["steps"]:
            step["gates"][0].pop("purpose")
        data["steps"][0]["unrecognized-mechanism"] = True
        pipeline, errors = parse_pipeline(data, "unknown.yaml")
        self.assertIsNone(pipeline)
        self.assertTrue(any("unrecognized-mechanism" in error for error in errors))


class ApprovalSelectionTest(unittest.TestCase):
    """FR-1/7: select declared approval instances, never reserved names."""

    def policy(self):
        """Local import keeps missing-API scaffolding out of parser RED cases."""
        return importlib.import_module("svod.workflow_policy")

    def test_approval_instances_are_selected_in_declaration_order(self):
        policy = self.policy()
        data = declaration()
        data["steps"].insert(0, {"id": "approve", "text": "synthetic.fake",
                                  "gates": [{"gate": "approval", "params": {}}]})
        pipeline = bind_case(self, data)
        refs = policy.approval_refs(pipeline)
        self.assertEqual(refs, [pipeline.steps[1].gates[0], pipeline.steps[2].gates[0]])
        self.assertTrue(all(isinstance(ref.impl, ApprovalGate) for ref in refs))

    def test_purpose_selects_one_ref_without_stage_or_marker_conventions(self):
        policy = self.policy()
        pipeline = bind_case(self, declaration())
        self.assertEqual(policy.approval_refs(pipeline, "result-y"),
                         [pipeline.steps[1].gates[0]])
        self.assertIs(policy.approval_ref(pipeline, "scope_x"), pipeline.steps[0].gates[0])

    def test_missing_purpose_raises_instead_of_falling_back(self):
        policy = self.policy()
        pipeline = bind_case(self, declaration())
        self.assertEqual(policy.approval_refs(pipeline, "absent"), [])
        with self.assertRaises(ParamError):
            policy.approval_ref(pipeline, "absent")
        with self.assertRaises(ParamError):
            policy.binding_patterns(pipeline, "absent")

    def test_two_distinct_refs_with_one_purpose_are_ambiguous(self):
        policy = self.policy()
        data = declaration()
        data["steps"][1]["gates"][0]["purpose"] = "scope_x"
        pipeline = bind_case(self, data)
        self.assertEqual(len(policy.approval_refs(pipeline, "scope_x")), 2)
        with self.assertRaises(ParamError):
            policy.approval_ref(pipeline, "scope_x")
        with self.assertRaises(ParamError):
            policy.binding_patterns(pipeline, "scope_x")

    def test_identical_ref_repeated_across_steps_is_deduplicated(self):
        policy = self.policy()
        data = declaration()
        duplicate = yaml.safe_load(yaml.safe_dump(data["steps"][0]["gates"][0]))
        duplicate["label"] = "synthetic.different-presentation"
        data["steps"][1]["gates"].append(duplicate)
        pipeline = bind_case(self, data)
        self.assertEqual(policy.approval_refs(pipeline),
                         [pipeline.steps[0].gates[0], pipeline.steps[1].gates[0]])
        self.assertIs(policy.approval_ref(pipeline, "scope_x"), pipeline.steps[0].gates[0])

    def test_same_marker_with_different_bind_is_ambiguous(self):
        policy = self.policy()
        data = declaration()
        duplicate = yaml.safe_load(yaml.safe_dump(data["steps"][0]["gates"][0]))
        duplicate["params"]["bind"] = ["different.md"]
        data["steps"][1]["gates"].append(duplicate)
        pipeline = bind_case(self, data)
        self.assertEqual(len(policy.approval_refs(pipeline, "scope_x")), 2)
        with self.assertRaises(ParamError):
            policy.approval_ref(pipeline, "scope_x")

    def test_purpose_and_when_are_part_of_ref_identity(self):
        policy = self.policy()
        for field, value in (("purpose", "another"), ("when", "needs_scope")):
            with self.subTest(field=field):
                data = declaration()
                duplicate = yaml.safe_load(yaml.safe_dump(data["steps"][0]["gates"][0]))
                duplicate[field] = value
                data["steps"][1]["gates"].append(duplicate)
                pipeline = bind_case(self, data)
                self.assertEqual(len(policy.approval_refs(pipeline)), 3)
                if field == "when":
                    with self.assertRaises(ParamError):
                        policy.approval_ref(pipeline, "scope_x")
                else:
                    self.assertIs(policy.approval_ref(pipeline, "another"),
                                  pipeline.steps[1].gates[1])

    def test_binding_patterns_returns_a_copy(self):
        policy = self.policy()
        pipeline = bind_case(self, declaration())
        patterns = policy.binding_patterns(pipeline, "scope_x")
        self.assertEqual(patterns, ["pear.md", "inputs/*.yaml"])
        patterns.append("not-declared.md")
        self.assertEqual(policy.binding_patterns(pipeline, "scope_x"),
                         ["pear.md", "inputs/*.yaml"])
        self.assertEqual(pipeline.steps[0].gates[0].params["bind"],
                         ["pear.md", "inputs/*.yaml"])

    def test_unbound_approval_has_no_binding_patterns(self):
        policy = self.policy()
        data = declaration()
        data["steps"][0]["gates"][0]["params"].pop("bind")
        self.assertEqual(policy.binding_patterns(bind_case(self, data), "scope_x"), [])

    def test_untagged_approval_is_in_unfiltered_selection(self):
        policy = self.policy()
        data = declaration()
        data["steps"][0]["gates"][0].pop("purpose")
        pipeline = bind_case(self, data)
        self.assertEqual(policy.approval_refs(pipeline),
                         [pipeline.steps[0].gates[0], pipeline.steps[1].gates[0]])
        self.assertEqual(policy.approval_refs(pipeline, "scope_x"), [])

    def test_supported_yaml_order_and_approval_count_changes_need_no_new_expectations(self):
        policy = self.policy()
        for count in (0, 1, 4):
            with self.subTest(count=count):
                data = declaration()
                template = data["steps"][0]["gates"][0]
                data["steps"] = []
                for index in reversed(range(count)):
                    ref = yaml.safe_load(yaml.safe_dump(template))
                    ref["purpose"] = f"choice_{index}"
                    ref["params"]["marker"] = f"fruit_{index}"
                    ref["params"]["bind"] = [f"fruit-{index}.md"]
                    data["steps"].append({"id": f"field_{index}", "text": "synthetic.field",
                                          "when": f"needs_{index}", "gates": [ref]})
                if not data["steps"]:
                    data["steps"] = [{"id": "empty", "text": "synthetic.empty", "gates": []}]
                pipeline = bind_case(self, data)
                expected = [ref for step in data["steps"] for ref in step["gates"]]
                self.assertEqual([ref.params["marker"] for ref in policy.approval_refs(pipeline)],
                                 [ref["params"]["marker"] for ref in expected])
                for ref in expected:
                    self.assertEqual(policy.binding_patterns(pipeline, ref["purpose"]),
                                     ref["params"]["bind"])


class NativeContractSelectionTest(unittest.TestCase):
    """Native exact-path resolution with fixture-owned policy and bindings."""

    def setUp(self):
        from unittest import mock
        from support import TempStore
        from svod.context import Context
        from svod.loader import load_runtime

        self.store = TempStore()
        self.addCleanup(self.store.cleanup)
        patcher = mock.patch.dict('os.environ', self.store.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.store.store / 'openspec/changes/service'
        self.store.write('openspec/changes/service/.openspec.yaml', 'ticket: tk-987\n')
        runtime = load_runtime(self.store.store)
        self.ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        # Keep the native exact-path provider, but select fixture-owned policy.
        data = declaration()
        data['steps'][0]['blocks_code'] = True
        data['steps'][0]['gates'][0].pop('purpose')
        data['steps'][0]['gates'][0]['params']['bind'] = ['pear.md']
        data['steps'][0]['gates'].append({'gate': 'artifact', 'params': {'path': 'pear.md'}})
        data['steps'][1]['gates'][0].pop('purpose')
        discussion = {'id': 'discussion', 'text': 'synthetic.discussion', 'blocks_code': True,
                      'gates': [{'gate': 'consent-alias',
                                 'params': {'marker': 'discussion', 'file': 'discussion.yaml',
                                            'bind': ['discussion.md']}}]}
        data['steps'].insert(0, discussion)
        runtime.pipeline('task').steps = bind_case(self, data).steps
        self.subject = Subject('service', self.path, keys=frozenset({'tk-987'}))

    def test_service_contract_selected_by_declared_inputs_not_first_blocker(self):
        from svod.workflow_policy import contract_approval, subject_pipeline

        pipeline, _ = subject_pipeline(self.ctx, self.subject)
        ref = contract_approval(self.ctx, self.subject)
        blockers = [r for s in pipeline.steps if s.blocks_code for r in s.gates
                    if isinstance(r.impl, ApprovalGate)]
        self.assertIsNot(ref, blockers[0])
        artifacts = {r.params.get('path') or r.params.get('glob')
                     for s in pipeline.steps for r in s.gates
                     if not isinstance(r.impl, ApprovalGate)} - {None}
        self.assertTrue(artifacts.intersection(ref.params['bind']))

    def test_two_formal_blockers_deny_instead_of_selecting_first(self):
        from copy import deepcopy
        from svod.workflow_policy import contract_approval, subject_pipeline

        pipeline, _ = subject_pipeline(self.ctx, self.subject)
        ref = contract_approval(self.ctx, self.subject)
        duplicate = deepcopy(ref)
        duplicate.params['marker'] = 'different_decision'
        next(s for s in pipeline.steps if s.blocks_code).gates.append(duplicate)
        with self.assertRaises(ValueError):
            contract_approval(self.ctx, self.subject)

    def test_selected_contract_missing_bind_and_ambiguity_refuse(self):
        from svod.workflow_policy import contract_approval, subject_pipeline
        from copy import deepcopy

        pipeline, _ = subject_pipeline(self.ctx, self.subject)
        ref = contract_approval(self.ctx, self.subject)
        ref.purpose = 'contract'
        bind = ref.params.pop('bind')
        with self.assertRaises(ValueError):
            contract_approval(self.ctx, self.subject)
        ref.params['bind'] = bind
        duplicate = deepcopy(ref)
        duplicate.params['file'] = 'distinct.yaml'
        pipeline.steps[-1].gates.append(duplicate)
        with self.assertRaises(ValueError):
            contract_approval(self.ctx, self.subject)

    def test_inapplicable_tagged_contract_does_not_fall_back_to_other_blockers(self):
        from svod.workflow_policy import contract_approval

        ref = contract_approval(self.ctx, self.subject)
        ref.purpose = 'contract'
        ref.when = 'absent_predicate'
        self.assertIsNone(contract_approval(self.ctx, self.subject))

    def test_skipped_duplicate_does_not_hide_applicable_declared_contract(self):
        from copy import deepcopy
        from svod.workflow_policy import contract_approval, subject_pipeline

        pipeline, _ = subject_pipeline(self.ctx, self.subject)
        ref = contract_approval(self.ctx, self.subject)
        duplicate = deepcopy(ref)
        duplicate.purpose = 'contract'
        duplicate.when = 'absent_predicate'
        next(s for s in pipeline.steps if s.blocks_code).gates.insert(0, duplicate)
        ref.purpose = 'contract'
        self.assertIs(contract_approval(self.ctx, self.subject), ref)


    def test_result_bootstrap_excludes_contract_reuses_and_selects_tagged_identity(self):
        from svod.workflow_policy import result_approval, same_approval

        ref = result_approval(self.ctx, self.subject)
        self.assertIsNotNone(ref)
        self.assertTrue(same_approval(ref.impl, ref))
        ref.purpose = 'result'
        ref.params['marker'] = 'fruit_result'
        ref.impl.params['marker'] = 'fruit_result'
        self.assertIs(result_approval(self.ctx, self.subject), ref)

    def test_result_ambiguity_refuses_but_skipped_duplicate_is_not_consent(self):
        from copy import deepcopy
        from svod.workflow_policy import result_approval, subject_pipeline

        pipeline, _ = subject_pipeline(self.ctx, self.subject)
        ref = result_approval(self.ctx, self.subject)
        ref.purpose = 'result'
        duplicate = deepcopy(ref)
        duplicate.params['marker'] = 'fruit_other'
        stage = next(step for step in pipeline.steps if ref in step.gates)
        stage.gates.insert(0, duplicate)
        with self.assertRaises(ValueError):
            result_approval(self.ctx, self.subject)
        duplicate.when = 'absent_predicate'
        self.assertIs(result_approval(self.ctx, self.subject), ref)


class ApplicabilityTest(unittest.TestCase):
    """FR-1/7: subject attrs drive applicability, not stages or subject IDs."""

    def test_step_applicability_uses_truthiness_and_missing_is_false(self):
        policy = importlib.import_module("svod.workflow_policy")
        data = declaration()
        data["steps"][0]["when"] = "needs_scope"
        pipeline = parse_case(self, data)
        for attrs, expected in (({}, False), ({"needs_scope": False}, False),
                                ({"needs_scope": 0}, False), ({"needs_scope": ""}, False),
                                ({"needs_scope": True}, True), ({"needs_scope": "yes"}, True)):
            with self.subTest(attrs=attrs):
                subject = Subject("synthetic", None, attrs=attrs)
                self.assertIs(policy.step_applies(pipeline.steps[0], subject), expected)
                self.assertIs(policy.step_applies(pipeline.steps[1], subject), True)

    def fixture(self):
        """Isolate native position from parser support for the new optional field.

        Only legacy-supported YAML is parsed; the agreed Step.when value is then
        attached to its real Step instance so old position behavior is exercised.
        """
        data = yaml.safe_load("""
        pipeline: synthetic-position
        subject: {provider: synthetic-subjects}
        steps:
          - id: conditional
            text: synthetic.conditional
            required: true
            blocks_code: true
            gates: [{gate: approval}]
          - id: completed
            text: synthetic.completed
            gates: [{gate: approval}]
          - id: remaining
            text: synthetic.remaining
            gates: [{gate: approval}]
        """)
        pipeline = parse_case(self, data)
        pipeline.steps[0].when = "needs_scope"
        for step, exists in zip(pipeline.steps, (False, True, False), strict=False):
            # A separate real subject per evaluation makes fixed PASS/FAIL data,
            # without mocking position or requiring filesystem approval records.
            step.gates[0].impl = FixedExistence(exists)
        return pipeline

    def test_skipped_stage_is_not_current(self):
        pipeline = self.fixture()
        for attrs in ({}, {"needs_scope": False}):
            with self.subTest(attrs=attrs):
                pos = position(None, pipeline, Subject("synthetic", None, attrs=attrs))
                self.assertEqual(pos.current.step.id, "remaining")

    def test_skipped_required_stage_is_not_an_order_violation(self):
        pipeline = self.fixture()
        pos = position(None, pipeline, Subject("synthetic", None))
        self.assertEqual(pos.violations, [])

    def test_skipped_blocking_stage_does_not_freeze_code(self):
        pipeline = self.fixture()
        pos = position(None, pipeline, Subject("synthetic", None))
        self.assertIsNone(pos.do_not_touch)

    def test_applicable_required_stage_still_blocks_and_reports_order_violation(self):
        pipeline = self.fixture()
        pos = position(None, pipeline, Subject("synthetic", None, attrs={"needs_scope": True}))
        self.assertEqual(pos.current.step.id, "conditional")
        self.assertEqual([(v.later, v.earlier) for v in pos.violations],
                         [("completed", "conditional")])
        self.assertEqual(pos.do_not_touch["step"], "conditional")


class FixedExistence(ExistsGate):
    """Synthetic outcome data using the real ExistsGate mechanism."""

    def __init__(self, exists):
        super().__init__()
        self.exists = exists

    def evaluate(self, ctx, subject):
        return super().evaluate(ctx, Subject("gate-fixture", None, exists=self.exists))


class CurrentContractMechanismTest(unittest.TestCase):
    """Current metadata and consent; no copied production stage policy."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        self.subject = Subject('synthetic-current', self.task)

    def test_current_consent_requires_native_marker_and_matching_bound_bytes(self):
        from svod.approval import digest, field_names, set_fields
        from svod.gates import ApprovalGate
        contract = self.task / 'compact.md'
        contract.write_text('Current synthetic contract\n')
        gate = ApprovalGate({'marker': 'fruit_accepted', 'file': 'current.yaml',
                             'bind': ['compact.md']})
        self.assertFalse(gate.evaluate(None, self.subject).passed)
        marker, by, sha = field_names('fruit_accepted')
        set_fields(self.task / 'current.yaml', {marker: '2026-10-10',
                   by: 'synthetic-only', sha: digest(self.task, ['compact.md'])})
        self.assertTrue(gate.evaluate(None, self.subject).passed)
        contract.write_text('Unapproved new bytes\n')
        self.assertFalse(gate.evaluate(None, self.subject).passed)


class LayeringTest(unittest.TestCase):
    """Policy sits below position and approve: no import cycle, hidden or not."""

    def imported(self, module):
        """Sibling modules a svod module imports anywhere in its source."""
        import ast
        import svod
        tree = ast.parse((Path(svod.__file__).parent / f"{module}.py").read_text("utf-8"))
        return {node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module}

    def test_policy_imports_neither_position_nor_approve(self):
        self.assertFalse({"position", "approve"} & self.imported("workflow_policy"))

    def test_position_and_pipeline_import_no_policy_layer(self):
        self.assertFalse({"workflow_policy", "approve"} & self.imported("position"))
        self.assertFalse({"workflow_policy", "approve", "position"} & self.imported("pipeline"))

    def test_shared_names_stay_importable(self):
        from svod import approve, position, pipeline, workflow_policy
        self.assertIs(workflow_policy.step_applies, pipeline.step_applies)
        self.assertIs(position.applies, pipeline.applies)
        self.assertIs(position.evaluate, pipeline.evaluate)
        self.assertIs(approve.applicable_approvals, workflow_policy.applicable_approvals)


if __name__ == "__main__":
    unittest.main()
