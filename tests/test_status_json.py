"""EFF-4 S1 single native evaluation, privacy and text/exit parity."""
import dataclasses
import json
import unittest
from pathlib import Path

from svod.pipeline import parse_pipeline
from svod.position import position
from svod.render import Report
from svod.status import Collection, StatusItem
from svod.status_json import to_json

from support import StoreTestCase
import importlib


def module(test, name):
    return importlib.import_module(name)

from test_position import change
from svod.context import Context
from svod.gates import Gate, unknown, verdict
from svod.loader import load_runtime
from svod.render import status_report
from svod.resolve import Resolution
from svod.subject import Subject
from unittest.mock import patch


class CountingGate(Gate):
    name = "counter"

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def evaluate(self, ctx, subject):
        self.calls += 1
        return self.result


class StatusJsonContractTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        change(self.sb, "c-4", "tk-4", spec=True, design=True)
        self.runtime = load_runtime(self.sb.store)
        self.ctx = Context(self.runtime.config, self.runtime.locale)

    def test_single_collector_serializer_never_runs_gate_twice(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        pipeline = self.runtime.pipeline("task")
        counter = CountingGate(verdict(False))
        step = pipeline.step("approve")
        replaced = dataclasses.replace(step, gates=[dataclasses.replace(step.gates[0], impl=counter)])
        pipeline = dataclasses.replace(pipeline, steps=[replaced if s.id == step.id else s for s in pipeline.steps])
        collection = collector.collect_status(self.ctx, [pipeline], "tk-4")
        self.assertEqual(counter.calls, 1)
        data = serializer.to_json(collection)
        again = serializer.to_json(collection)
        self.assertEqual(counter.calls, 1)
        self.assertEqual(data, again)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["query"], "tk-4")
        self.assertEqual(data["report"], {"ok": True, "refused": False, "exit_code": 0})
        self.assertEqual(data["positions"][0]["current"], "approve")
        self.assertEqual(collection.report, status_report(self.ctx, [self.runtime.pipeline("task")], "tk-4"))

    def test_json_unknown_private_reason_facts_display_are_not_dumped(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        pipeline = self.runtime.pipeline("task")
        step = pipeline.step("approve")
        private = "PRIVATE_TOKEN_DO_NOT_SERIALIZE"
        counter = CountingGate(dataclasses.replace(unknown(private, secret=private), display=private))
        replaced = dataclasses.replace(step, gates=[dataclasses.replace(step.gates[0], impl=counter)])
        pipeline = dataclasses.replace(pipeline, steps=[replaced if s.id == step.id else s for s in pipeline.steps])
        collection = collector.collect_status(self.ctx, [pipeline], "tk-4")
        data = serializer.to_json(collection)
        self.assertNotIn(private, json.dumps(data))
        outcome = next(s for s in data["positions"][0]["steps"] if s["id"] == "approve")["outcomes"][0]
        self.assertEqual(outcome["status"], "unknown")
        self.assertEqual(outcome["reason_code"], "unknown_detail")
        self.assertNotIn("secret", outcome["facts"])
        self.assertEqual(counter.calls, 1)

    def test_explicit_text_and_json_cli_preserve_default_text_and_exit(self):
        baseline = self.sb.cli("status", "tk-4")
        self.assertEqual(baseline.returncode, 0)
        text = self.sb.cli("status", "tk-4", "--format", "text")
        self.assertEqual((text.returncode, text.stdout, text.stderr),
                         (baseline.returncode, baseline.stdout, baseline.stderr))
        structured = self.sb.cli("status", "tk-4", "--format", "json")
        self.assertEqual(structured.returncode, baseline.returncode)
        self.assertEqual(structured.stderr, "")
        self.assertEqual(json.loads(structured.stdout)["report"]["exit_code"], baseline.returncode)

    def test_collector_missing_error_preserves_native_exit_two(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        native = status_report(self.ctx, self.runtime.pipelines, "tk-50")
        collection = collector.collect_status(self.ctx, self.runtime.pipelines, "tk-50")
        self.assertEqual(collection.report, native)
        self.assertEqual(serializer.to_json(collection)["report"],
                         {"ok": False, "refused": False, "exit_code": 2})

    def test_json_root_load_and_parse_failures_are_safe(self):
        self.sb.write("svod.yaml", "PRIVATE_TOKEN: [malformed")
        result = self.sb.cli("status", "tk-4", "--format", "json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        self.assertEqual(data["error"]["reason_code"], "invalid_load")
        self.assertNotIn("PRIVATE_TOKEN", result.stdout)
        malformed = self.sb.cli("status", "tk-4", "--format", "json", "--PRIVATE_TOKEN")
        self.assertEqual(malformed.returncode, 2)
        self.assertEqual(json.loads(malformed.stdout)["error"]["reason_code"], "invalid_arguments")
        self.assertNotIn("PRIVATE_TOKEN", malformed.stdout + malformed.stderr)
        (self.sb.store / "svod.yaml").unlink()
        absent = self.sb.cli("status", "tk-4", "--format", "json")
        self.assertEqual(json.loads(absent.stdout)["error"]["reason_code"], "invalid_root")

    def test_optional_unknown_kept_without_required_unknown_or_second_call(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        pipeline = self.runtime.pipeline("task")
        optional = pipeline.step("approve")
        counter = CountingGate(unknown("PRIVATE_OPTIONAL"))
        optional = dataclasses.replace(optional, id="optional", optional=True, required=False,
                                       gates=[dataclasses.replace(optional.gates[0], impl=counter)])
        pipeline = dataclasses.replace(pipeline, steps=[*pipeline.steps, optional])
        collection = collector.collect_status(self.ctx, [pipeline], "tk-4")
        data = serializer.to_json(collection)
        self.assertEqual(counter.calls, 1)
        self.assertEqual(data["positions"][0]["current"], "approve")
        self.assertEqual(data["positions"][0]["unknown"], [])
        self.assertEqual(data["positions"][0]["steps"][-1]["outcomes"][0]["status"], "unknown")

    def test_missing_suppression_ambiguous_and_done_shortcut_no_second_engine(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        pipeline = self.runtime.pipeline("task")
        missing_gate = CountingGate(verdict(False))
        absent = Subject("absent", None, exists=False)
        present = pipeline.subject.impl.resolve("tk-4", self.ctx)[0]
        missing_pipeline = dataclasses.replace(pipeline, missing=dataclasses.replace(pipeline.missing, impl=missing_gate))
        resolution = Resolution(matches=[(missing_pipeline, absent), (pipeline, present)])
        with patch.object(collector, "resolve", return_value=resolution):
            collection = collector.collect_status(self.ctx, [pipeline], "tk-4")
        data = serializer.to_json(collection)
        self.assertTrue(data["report"]["ok"])
        self.assertEqual(collection.report.err, [])
        self.assertTrue(data["positions"][0]["missing_suppressed"])
        self.assertEqual([action["subject"]["id"] for action in data["next_action"]], [present.id])
        self.assertEqual(data["positions"][0]["evaluation"], "not_evaluated")
        self.assertEqual(missing_gate.calls, 1)
        with patch.object(collector, "resolve", return_value=dataclasses.replace(resolution, ambiguous=True)):
            ambiguous = serializer.to_json(collector.collect_status(self.ctx, [pipeline], "tk-4"))
        self.assertEqual(ambiguous["positions"], [])
        self.assertEqual(ambiguous["report"]["exit_code"], 2)
        self.assertEqual(missing_gate.calls, 1)
        done_counter = CountingGate(verdict(True))
        current_counter = CountingGate(verdict(False))
        step = pipeline.step("approve")
        step = dataclasses.replace(step, entry=[dataclasses.replace(pipeline.entry[0], impl=current_counter)])
        terminal = dataclasses.replace(pipeline, done=dataclasses.replace(pipeline.done, impl=done_counter),
                                       steps=[step if s.id == step.id else s for s in pipeline.steps])
        final = collector.collect_status(self.ctx, [terminal], "tk-4")
        projected = serializer.to_json(final)["positions"][0]
        self.assertTrue(projected["done"])
        self.assertEqual(projected["current_entries"], [])
        self.assertEqual(projected["current_entry_evaluation"], "not_evaluated")
        self.assertEqual((done_counter.calls, current_counter.calls), (1, 0))

    def test_real_native_queries_and_multicheckout_no_projection_gate_calls(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        self.sb.write("projects/alpha/Onepager.md", "---\ntype: onepager\n---\n")
        self.sb.write("projects/alphabet/Onepager.md", "---\ntype: onepager\n---\n")
        for query in ("tk-4", "c-4", "alpha", "lph", "zeta", "tk-50"):
            with self.subTest(query=query):
                native = self.sb.cli("status", query)
                explicit = self.sb.cli("status", query, "--format", "text")
                structured = self.sb.cli("status", query, "--format", "json")
                self.assertEqual((native.returncode, native.stdout, native.stderr),
                                 (explicit.returncode, explicit.stdout, explicit.stderr))
                self.assertEqual(json.loads(structured.stdout)["report"]["exit_code"], native.returncode)
                self.assertEqual(structured.stderr, "")
        pipeline = self.runtime.pipeline("task")
        subject = pipeline.subject.impl.resolve("tk-4", self.ctx)[0]
        other = dataclasses.replace(subject, checkout=self.sb.store)
        with patch.object(collector, "resolve", return_value=Resolution(matches=[(pipeline, subject), (pipeline, other)])):
            collection = collector.collect_status(self.ctx, [pipeline], "tk-4")
        with patch("svod.position.evaluate", side_effect=AssertionError("serializer evaluated")):
            data = serializer.to_json(collection)
        self.assertEqual(len(data["positions"]), 2)
        self.assertEqual(data["positions"][1]["checkout"], self.sb.store.name)

    def test_unknown_gate_cannot_smuggle_allowlisted_facts(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        pipeline = self.runtime.pipeline("task")
        step = pipeline.step("approve")
        counter = CountingGate(dataclasses.replace(unknown("PRIVATE"), facts={"reason": "PRIVATE", "count": 123, "path": "../PRIVATE"}))
        step = dataclasses.replace(step, gates=[dataclasses.replace(step.gates[0], impl=counter, gate="untrusted")])
        pipeline = dataclasses.replace(pipeline, steps=[step if s.id == step.id else s for s in pipeline.steps])
        data = serializer.to_json(collector.collect_status(self.ctx, [pipeline], "tk-4"))
        outcome = next(s for s in data["positions"][0]["steps"] if s["id"] == "approve")["outcomes"][0]
        self.assertEqual(outcome["facts"], {})
        self.assertNotIn("PRIVATE", json.dumps(data))

    def test_native_instruction_variant_and_refused_exit_one(self):
        collector = module(self, "svod.status")
        serializer = module(self, "svod.status_json")
        from svod.render import Report
        pipeline = self.runtime.pipeline("task")
        step = pipeline.step("approve")
        counter = CountingGate(verdict(False, reason="missing"))
        step = dataclasses.replace(step, gates=[dataclasses.replace(step.gates[0], impl=counter)])
        pipeline = dataclasses.replace(pipeline, steps=[step if s.id == step.id else s for s in pipeline.steps])
        base = step.gates[0].text or step.text
        with patch.dict(self.ctx.locale._strings, {base + "_missing": "Missing approval."}):
            collection = collector.collect_status(self.ctx, [pipeline], "tk-4")
        projected = serializer.to_json(collection)
        self.assertEqual(projected["positions"][0]["instruction"]["variant_key"], base + "_missing")
        collection.report = Report(False, refused=True)
        self.assertEqual(serializer.to_json(collection)["report"]["exit_code"], 1)
        self.assertEqual(counter.calls, 1)


class NextActionTest(unittest.TestCase):
    """Compact captured planning state needs no executor/evidence prerequisites."""

    def capture(self, result=None):
        pipeline, errors = parse_pipeline({
            "pipeline": "synthetic", "subject": {"provider": "unused"},
            "steps": [
                {"id": "skipped", "when": "needs_extra", "text": "step.skipped",
                 "gates": [{"gate": "artifact", "params": {"path": "never.md"}}]},
                {"id": "outline", "role": "planner", "text": "step.outline",
                 "gates": [
                     {"gate": "artifact", "purpose": "contract", "params": {"path": "contract.md"}},
                     {"gate": "artifact", "when": "needs_extra", "params": {"path": "private.md"}}]},
                {"id": "later", "text": "step.later",
                 "gates": [{"gate": "artifact", "params": {"path": "review/code.yaml"}}]},
            ]}, Path("synthetic.yaml"))
        self.assertEqual(errors, [])
        assert pipeline is not None
        counter = CountingGate(result if result is not None else dataclasses.replace(verdict(False), reason="missing"))
        for ref in pipeline.gate_refs():
            ref.impl = counter
        subject = Subject("feature/sample/tasks/task", None, keys=frozenset({"SAMPLE-1"}))
        pos = position(None, pipeline, subject)
        item = StatusItem(pipeline, subject, None, position=pos, instruction_variant="step.outline_missing")
        return Collection("SAMPLE-1", Resolution(matches=[(pipeline, subject)]), Report(True), [item]), counter

    def test_early_planning_compact_action_preserves_v1_shape(self):
        collection, counter = self.capture()
        data = to_json(collection)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["positions"][0]["current"], "outline")
        self.assertEqual(set(data) - {"next_action"}, {"version", "query", "resolution", "report", "positions"})
        self.assertEqual(data.get("next_action"), [{
            "pipeline": "synthetic", "subject": {"id": "feature/sample/tasks/task", "exists": True, "keys": ["SAMPLE-1"]},
            "checkout": None, "state": "live", "stage": "outline", "role": "planner",
            "instruction": {"base_key": "step.outline", "variant_key": "step.outline_missing", "from_entry": False},
            "inputs": [{"gate": "artifact", "purpose": "contract", "kind": "path", "ref": "contract.md"}],
            "blocker": {"gate": "artifact", "status": "fail", "reason_code": "missing", "facts": {}, "severity": None},
            "version": {"value": None, "reason_code": "not_captured"},
        }])
        self.assertEqual(counter.calls, 2)

    def test_declared_inputs_are_confined_deduplicated_and_bounded(self):
        collection, _ = self.capture()
        ref = collection.items[0].position.current.outcomes[0].ref
        ref.params = {"path": "contract.md", "glob": "specs/**/spec.md",
                      "bind": ["contract.md", "specs/**/spec.md", "../escape", "/absolute",
                               "bad\\path", "https://host/secret", "raw secret", *[f"inputs/{i}.md" for i in range(200)]],
                      "secret": "PRIVATE", "file": "PRIVATE"}
        action = to_json(collection)["next_action"][0]
        self.assertEqual(action["inputs"][:4], [
            {"gate": "artifact", "purpose": "contract", "kind": kind, "ref": value}
            for kind, value in (("path", "contract.md"), ("glob", "specs/**/spec.md"),
                                ("bind", "contract.md"), ("bind", "specs/**/spec.md"))])
        self.assertEqual(len(action["inputs"]), 32)
        self.assertNotIn("PRIVATE", json.dumps(action))
        ref.params = {"bind": ["contract.md"] * 200}
        self.assertEqual(len(to_json(collection)["next_action"][0]["inputs"]), 1)

    def test_entry_blocker_inputs_and_no_stage_from_uncaptured_policy(self):
        collection, _ = self.capture()
        item = collection.items[0]
        outcome = item.position.current.first_open
        item.position.blocked = dataclasses.replace(outcome, ref=dataclasses.replace(
            outcome.ref, params={"path": "planning/registration.yaml"}, severity="block"))
        item.position.current = None
        item.position.text_from_entry = True
        action = to_json(collection)["next_action"][0]
        self.assertIsNone(action["stage"])
        self.assertEqual(action["blocker"]["severity"], "block")
        self.assertEqual(action["inputs"], [{"gate": "artifact", "purpose": "contract",
                                           "kind": "path", "ref": "planning/registration.yaml"}])

    def test_safe_command_error_has_no_next_action(self):
        from svod.status_json import error_json
        self.assertEqual(error_json("invalid_load").get("next_action"), [])

    def test_unknown_stale_blockers_remain_captured_and_projection_is_pure(self):
        for result in (unknown("PRIVATE raw error", secret="PRIVATE"),
                       dataclasses.replace(verdict(False), reason="stale")):
            with self.subTest(status=result.status):
                collection, counter = self.capture(result)
                collection.items[0].subject.author_of = lambda: self.fail("author callback")
                before = counter.calls
                with patch("svod.position.evaluate", side_effect=AssertionError("gate evaluation")), \
                     patch("svod.status.resolve", side_effect=AssertionError("resolution")), \
                     patch("builtins.open", side_effect=AssertionError("file read")), \
                     patch.object(Path, "read_text", side_effect=AssertionError("file read")), \
                     patch.object(Path, "glob", side_effect=AssertionError("glob")), \
                     patch("subprocess.run", side_effect=AssertionError("git/process")):
                    first = to_json(collection)
                    self.assertEqual(first, to_json(collection))
                action = first["next_action"][0]
                self.assertEqual(action["blocker"]["status"], result.status.value)
                self.assertEqual(action["blocker"]["reason_code"], "stale" if result.reason == "stale" else "unknown_detail")
                self.assertEqual(action["version"], {"value": None, "reason_code": "not_captured"})
                self.assertNotIn("PRIVATE", json.dumps(first))
                self.assertFalse({"permission", "capability", "execute", "ledger", "goal"} & action.keys())
                self.assertEqual(counter.calls, before)

    def test_archived_history_has_no_action_or_live_evidence(self):
        from svod.gates import ArchivedGate
        from svod.pipeline import GateRef
        collection, counter = self.capture()
        item = collection.items[0]
        item.subject.archived = True
        item.pipeline.done = GateRef("archived", {}, "done", text="history.done", impl=ArchivedGate({}))
        item.position = position(None, item.pipeline, item.subject)
        action = to_json(collection)["next_action"][0]
        self.assertEqual(action["state"], "historical")
        for key in ("stage", "role", "instruction", "blocker"):
            self.assertIsNone(action[key])
        self.assertEqual(action["inputs"], [])
        self.assertEqual((item.position.entries, item.position.steps, item.position.marks), ([], [], []))
        self.assertEqual(counter.calls, 2)

    def test_completed_live_and_pending_done_preserve_captured_terminal_state(self):
        collection, _ = self.capture()
        pos = collection.items[0].position
        outcome = pos.current.first_open
        pos.current = None
        pos.done_outcome = outcome
        action = to_json(collection)["next_action"][0]
        self.assertEqual(action["state"], "live")
        self.assertEqual(action["blocker"]["reason_code"], "missing")
        pos.done = dataclasses.replace(outcome, result=verdict(True))
        action = to_json(collection)["next_action"][0]
        self.assertEqual(action["state"], "completed")
        self.assertIsNone(action["blocker"])
        self.assertIsNone(action["instruction"])
        self.assertEqual(action["inputs"], [])

    def test_unresolved_ambiguous_and_missing_do_not_invent_action(self):
        collection, _ = self.capture()
        collection.items = []
        collection.resolution = Resolution(matches=[], ambiguous=True)
        self.assertEqual(to_json(collection)["next_action"], [])
        collection, _ = self.capture()
        item = collection.items[0]
        item.missing = item.position.current.first_open
        item.position = None
        item.subject.exists = False
        action = to_json(collection)["next_action"][0]
        self.assertEqual(action["state"], "not_evaluated")
        self.assertIsNone(action["stage"])
        self.assertIsNone(action["instruction"])
        self.assertEqual(action["blocker"]["status"], "fail")
        self.assertEqual(action["inputs"], [])
