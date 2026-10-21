"""Structured plans through the public CLI, with disposable store inputs."""
import json
from unittest import mock

import pytest

import support as fixtures


class PlanningTests(fixtures.StoreTestCase):
    def setUp(self):
        super().setUp()
        self.owner = "work/projects/product"
        self.sb.write(f"{self.owner}/card.md", fixtures.doc("card", status="open"))
        self.plan = {
            "schema_version": 1, "expected": "Usable product",
            "nodes": [{"id": "later", "title": "Later", "expected": "Useful",
                       "state": "open"}],
            "criteria": [{"id": "usable", "statement": "Usable", "verification": "Exercise",
                          "works": ["later"]}],
        }
        self.save_plan()

    def save_plan(self, owner=None, plan=None):
        self.sb.write(f"{owner or self.owner}/plan.yaml", json.dumps(plan or self.plan))

    def summary(self):
        return self.sb.cli("plan", "summary", self.owner, "--json")

    def test_summary_exposes_expected_execution_and_unconfirmed_acceptance(self):
        out = self.summary()
        self.assertEqual(out.returncode, 1, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(data["schema_version"], 1)
        self.assertTrue(data["collected_at"])
        record = data["records"][0]
        self.assertEqual(record["expected"], "Usable product")
        self.assertEqual(record["status"], "open")
        self.assertIsNone(record["actual"])
        self.assertEqual(record["nodes"][0]["state"], "open")
        self.assertEqual(record["criteria"][0]["acceptance"], "unconfirmed")
        self.assertIn("missing_outcome", [d["code"] for d in data["diagnostics"]])

    def test_linked_nested_facts_are_fresh_and_children_outside_plan_are_visible(self):
        feature = "work/features/feature"
        task = "work/tasks/task"
        for ref, parent in [(feature, self.owner), (task, feature),
                            ("work/tasks/omitted", self.owner)]:
            self.sb.write(f"{ref}/card.md", fixtures.doc("card", status="done", parent=parent))
            self.sb.write(f"{ref}/outcome.yaml", json.dumps({
                "schema_version": 1, "actual": "Delivered", "evidence": []}))
        self.plan["nodes"][0] = {"id": "later", "title": "Feature", "expected": "Feature",
                                  "record": feature}
        self.save_plan()
        self.save_plan(feature, {**self.plan, "nodes": [
            {"id": "later", "title": "Task", "expected": "Task", "record": task}]})
        data = json.loads(self.summary().stdout)
        self.assertEqual(len(data["records"]), 2)
        node = data["records"][1]["nodes"][0]
        self.assertEqual((node["state"], node["actual"]), ("done", "Delivered"))
        self.assertIn("unplanned_child", [d["code"] for d in data["diagnostics"]])
        self.sb.write(f"{task}/card.md", fixtures.doc("card", status="blocked", parent=feature))
        self.sb.write(f"{task}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Changed", "evidence": []}))
        node = json.loads(self.summary().stdout)["records"][1]["nodes"][0]
        self.assertEqual((node["state"], node["actual"]), ("blocked", "Changed"))

    def test_safe_summary_has_no_commands_network_gates_or_source_writes(self):
        before = {p: p.read_bytes() for p in self.sb.store.rglob("*") if p.is_file()}
        with mock.patch("subprocess.run", side_effect=AssertionError("command")), \
                mock.patch("socket.socket", side_effect=AssertionError("network")), \
                mock.patch("svod.loader.load_runtime", side_effect=AssertionError("profile")):
            out = self.summary()
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in self.sb.store.rglob("*")
                                  if p.is_file()})

    def test_validate_and_summary_all_use_the_same_validated_facts(self):
        self.sb.write(f"{self.owner}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Result", "evidence": []}))
        self.assertEqual(self.sb.cli("plan", "validate", self.owner).returncode, 0)
        out = self.sb.cli("plan", "summary", "--all", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["records"][0]["actual"], "Result")

    def confirm(self, criterion="usable", result="pass"):
        return self.sb.cli("plan", "confirm", self.owner, "--criterion", criterion,
                           "--result", result, "--actual", "Exercised full behavior",
                           "--evidence", "proof.txt")

    def test_observed_concurrent_acceptance_edit_is_not_lost(self):
        from svod import plan_write
        self.sb.write("proof.txt", "Evidence")
        self.assertEqual(self.confirm().returncode, 0)
        path = self.sb.store / self.owner / "acceptance.yaml"
        original = plan_write.replace
        changed = path.read_bytes() + b"\n "

        def racing(target, content, expected, verify):
            path.write_bytes(changed)
            return original(target, content, expected, verify)

        with mock.patch("svod.plan_write.replace", side_effect=racing):
            self.assertEqual(self.confirm().returncode, 2)
        self.assertEqual(path.read_bytes(), changed)

    def test_changed_input_during_collection_is_reported(self):
        from svod import planning
        original = planning.Collector.visit

        def changing(collector, ref):
            original(collector, ref)
            self.sb.write(f"{self.owner}/card.md", fixtures.doc("card", status="done"))

        with mock.patch.object(planning.Collector, "visit", changing):
            data = json.loads(self.summary().stdout)
        self.assertIn("input_changed", [d["code"] for d in data["diagnostics"]])

    def test_explicit_confirmation_history_definition_and_reopening(self):
        self.sb.write("proof.txt", "Real local verification evidence")
        self.assertEqual(self.confirm().returncode, 0)
        data = json.loads(self.summary().stdout)
        self.assertEqual(data["records"][0]["criteria"][0]["acceptance"], "pass")
        acceptance = self.sb.store / self.owner / "acceptance.yaml"
        history = json.loads(acceptance.read_text())["confirmations"]
        self.assertEqual(len(history), 1)
        self.assertNotIn("human", acceptance.read_text())
        self.plan["criteria"][0]["statement"] = "Changed definition"
        self.save_plan()
        criterion = json.loads(self.summary().stdout)["records"][0]["criteria"][0]
        self.assertEqual(criterion["acceptance"], "review_required")
        self.assertEqual(self.confirm().returncode, 0)
        self.assertEqual(len(json.loads(acceptance.read_text())["confirmations"]), 2)
        self.plan["nodes"][0]["state"] = "done"
        self.save_plan()
        self.assertEqual(self.confirm().returncode, 0)
        self.plan["nodes"][0]["state"] = "active"
        self.save_plan()
        criterion = json.loads(self.summary().stdout)["records"][0]["criteria"][0]
        self.assertEqual(criterion["acceptance"], "review_required")
        self.assertEqual(len(criterion["history"]), 3)
        self.assertEqual(self.confirm(result="fail").returncode, 0)
        self.assertEqual(json.loads(self.summary().stdout)["records"][0]["criteria"][0]
                         ["acceptance"], "fail")

    def test_many_to_many_partial_work_and_dependency_do_not_auto_accept(self):
        self.sb.write("proof.txt", "Evidence")
        self.plan["nodes"].append({"id": "second", "title": "Second", "expected": "Second",
                                    "state": "done"})
        self.plan["criteria"][0]["works"].append("second")
        self.plan["criteria"].append({"id": "other", "statement": "Other",
                                       "verification": "Full check", "works": ["second"],
                                       "dependencies": [{"owner": self.owner,
                                                         "criterion": "usable"}]})
        self.save_plan()
        self.assertEqual(self.confirm("other").returncode, 0)
        criteria = json.loads(self.summary().stdout)["records"][0]["criteria"]
        self.assertEqual([c["acceptance"] for c in criteria], ["unconfirmed", "review_required"])
        self.assertEqual(self.confirm().returncode, 0)
        self.assertEqual(self.confirm("other").returncode, 0)
        criteria = json.loads(self.summary().stdout)["records"][0]["criteria"]
        self.assertEqual([c["acceptance"] for c in criteria], ["pass", "pass"])
        self.plan["criteria"][0]["verification"] = "Different check"
        self.save_plan()
        criteria = json.loads(self.summary().stdout)["records"][0]["criteria"]
        self.assertEqual([c["acceptance"] for c in criteria],
                         ["review_required", "review_required"])

    def test_supporting_record_reverse_criteria_are_computed_not_duplicated(self):
        task = "work/tasks/t"
        self.sb.write(f"{task}/card.md", fixtures.doc("card", parent=self.owner))
        self.plan["nodes"][0] = {"id": "later", "title": "Task", "expected": "Task",
                                  "record": task}
        self.plan["criteria"].append({"id": "other", "statement": "Other",
                                       "verification": "Check", "works": ["later"]})
        self.save_plan()
        node = json.loads(self.summary().stdout)["records"][0]["nodes"][0]
        self.assertEqual(node["supports"], [{"owner": self.owner, "criterion": "usable"},
                                            {"owner": self.owner, "criterion": "other"}])
        self.assertNotIn("supports", (self.sb.store / task / "card.md").read_text())

    def test_confirmation_refuses_missing_evidence_and_preserves_malformed_history(self):
        self.assertEqual(self.confirm().returncode, 2)
        path = self.sb.write(f"{self.owner}/acceptance.yaml", "confirmations: broken")
        self.sb.write("proof.txt", "Evidence")
        self.assertEqual(self.confirm().returncode, 2)
        self.assertEqual(path.read_text(), "confirmations: broken")

    def test_invalidated_evidence_and_missing_support_never_show_current_pass(self):
        self.sb.write("proof.txt", "Evidence")
        task = "work/tasks/t"
        self.sb.write(f"{task}/card.md", fixtures.doc("card", status="done", parent=self.owner))
        self.sb.write(f"{task}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Delivered", "evidence": []}))
        self.plan["nodes"][0] = {"id": "later", "title": "Task", "expected": "Task",
                                  "record": task}
        self.save_plan()
        self.assertEqual(self.confirm().returncode, 0)
        self.assertEqual(json.loads(self.summary().stdout)["records"][0]["criteria"][0]
                         ["acceptance"], "pass")
        self.sb.write("proof.txt", "Changed evidence after verification")
        criterion = json.loads(self.summary().stdout)["records"][0]["criteria"][0]
        self.assertEqual(criterion["acceptance"], "review_required")
        self.assertEqual(self.confirm().returncode, 0)
        self.sb.write(f"{task}/card.md", fixtures.doc("card", status="active", parent=self.owner))
        self.assertEqual(json.loads(self.summary().stdout)["records"][0]["criteria"][0]
                         ["acceptance"], "review_required")

    def test_record_reference_cycle_is_diagnosed(self):
        self.plan["nodes"][0] = {"id": "later", "title": "Self", "expected": "Self",
                                  "record": self.owner}
        self.save_plan()
        self.assertIn("cycle", [d["code"] for d in json.loads(self.summary().stdout)
                                ["diagnostics"]])

    def test_nested_support_reopening_requires_project_reverification(self):
        self.sb.write("proof.txt", "Evidence")
        feature, task = "work/features/f", "work/tasks/t"
        for ref, parent in ((feature, self.owner), (task, feature)):
            self.sb.write(f"{ref}/card.md", fixtures.doc("card", status="done", parent=parent))
            self.sb.write(f"{ref}/outcome.yaml", json.dumps({
                "schema_version": 1, "actual": "Delivered", "evidence": []}))
        self.plan["nodes"][0] = {"id": "later", "title": "Feature", "expected": "Feature",
                                  "record": feature}
        self.save_plan()
        self.save_plan(feature, {"schema_version": 1, "expected": "Feature", "criteria": [],
                                 "nodes": [{"id": "t", "title": "T", "expected": "T",
                                            "record": task}]})
        self.assertEqual(self.confirm().returncode, 0)
        self.sb.write(f"{task}/card.md", fixtures.doc("card", status="active", parent=feature))
        self.assertEqual(json.loads(self.summary().stdout)["records"][0]["criteria"][0]
                         ["acceptance"], "review_required")

    def test_invalid_outcome_is_unknown_and_invalid_evidence_is_diagnosed(self):
        for outcome in ({"schema_version": 1, "actual": "", "evidence": []},
                        {"schema_version": 2, "actual": "Result", "evidence": []},
                        {"schema_version": 1, "actual": "Result", "evidence": ["absent"]}):
            with self.subTest(outcome=outcome):
                self.sb.write(f"{self.owner}/outcome.yaml", json.dumps(outcome))
                data = json.loads(self.summary().stdout)
                self.assertIsNone(data["records"][0]["actual"])
                self.assertTrue(any(d["severity"] == "error" for d in data["diagnostics"]))

    def test_deleted_criterion_confirmation_is_visible_as_history_diagnostic(self):
        self.sb.write("proof.txt", "Evidence")
        self.assertEqual(self.confirm().returncode, 0)
        self.plan["criteria"] = []
        self.save_plan()
        data = json.loads(self.summary().stdout)
        self.assertIn("orphan_confirmation", [d["code"] for d in data["diagnostics"]])

    def test_plan_graph_error_cannot_retain_current_pass(self):
        self.sb.write("proof.txt", "Evidence")
        self.assertEqual(self.confirm().returncode, 0)
        self.plan["nodes"].append({"id": "bad", "title": "Bad", "expected": "Bad",
                                    "parent": "bad"})
        self.save_plan()
        data = json.loads(self.summary().stdout)
        self.assertEqual(data["records"][0]["criteria"][0]["acceptance"], "review_required")

    def test_bad_canvas_nonfinite_geometry_is_refused(self):
        self.sb.cli("plan", "canvas", self.owner)
        path = self.sb.store / self.owner / "plan.canvas"
        value = json.loads(path.read_text())
        value["nodes"][0]["x"] = float("nan")
        path.write_text(json.dumps(value))
        before = path.read_bytes()
        self.assertEqual(self.sb.cli("plan", "canvas", self.owner).returncode, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_oversized_canvas_geometry_is_refused_without_writes_by_real_cli(self):
        out = self.sb.cli_process("plan", "canvas", self.owner)
        self.assertEqual(out.returncode, 1, out.stderr)
        path = self.sb.store / self.owner / "plan.canvas"
        original = path.read_text()
        for key in ("x", "y", "width", "height"):
            with self.subTest(geometry=key):
                value = json.loads(original)
                value["nodes"][0][key] = 10**400
                path.write_text(json.dumps(value))
                before = {p: p.read_bytes() for p in self.sb.store.rglob("*") if p.is_file()}
                out = self.sb.cli_process("plan", "canvas", self.owner)
                self.assertEqual(out.returncode, 2, out.stderr)
                self.assertIn("canvas: Malformed or unowned plan.canvas; refusing overwrite",
                              out.stderr)
                self.assertNotIn("Traceback", out.stderr)
                self.assertEqual(before, {p: p.read_bytes() for p in self.sb.store.rglob("*")
                                          if p.is_file()})

    def test_canvas_and_text_use_facts_and_preserve_layout(self):
        out = self.sb.cli("plan", "canvas", self.owner)
        self.assertEqual(out.returncode, 1, out.stderr)
        path = self.sb.store / self.owner / "plan.canvas"
        canvas = json.loads(path.read_text())
        self.assertEqual(len(canvas["nodes"]), 3)
        self.assertTrue(canvas["edges"])
        first = canvas["nodes"][0]
        first.update(x=321, y=654, width=400, height=500, text="Manual semantic edit")
        path.write_text(json.dumps(canvas))
        self.sb.cli("plan", "canvas", self.owner)
        regenerated = json.loads(path.read_text())
        self.assertEqual([n["id"] for n in canvas["nodes"]],
                         [n["id"] for n in regenerated["nodes"]])
        self.assertEqual([regenerated["nodes"][0][k] for k in ("x", "y", "width", "height")],
                         [321, 654, 400, 500])
        text = self.sb.cli("plan", "summary", self.owner).stdout
        self.assertIn("Usable product", text)
        self.assertIn("unconfirmed", text)
        self.assertIn("unknown", text)
        self.assertNotIn("%", text)
        self.assertNotIn("Manual semantic edit", regenerated["nodes"][0]["text"])
        for content in ("{broken", '{"nodes": [], "edges": []}',
                        '{"svod_generated":"structured-planning-v1","nodes":42,"edges":[]}'):
            path.write_text(content)
            self.assertEqual(self.sb.cli("plan", "canvas", self.owner).returncode, 2)
            self.assertEqual(path.read_text(), content)

    def test_escaping_symlinks_and_parent_conflicts_are_diagnostics(self):
        outside = self.sb.root / "outside"
        outside.mkdir()
        (outside / "card.md").write_text(fixtures.doc("card"))
        link = self.sb.store / "work/tasks/escape"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside, target_is_directory=True)
        self.plan["nodes"][0] = {"id": "later", "title": "Bad", "expected": "Bad",
                                  "record": "work/tasks/escape"}
        self.save_plan()
        self.assertIn("unsafe_path", [d["code"] for d in
                                      json.loads(self.summary().stdout)["diagnostics"]])
        for name in ("acceptance.yaml", "plan.canvas"):
            (self.sb.store / self.owner / name).symlink_to(outside / name)
        self.sb.write("proof.txt", "Evidence")
        self.assertEqual(self.confirm().returncode, 2)
        self.assertEqual(self.sb.cli("plan", "canvas", self.owner).returncode, 2)
        self.assertFalse((outside / "acceptance.yaml").exists())
        self.assertFalse((outside / "plan.canvas").exists())


@pytest.mark.parametrize("support", ["direct", "nested", "dependency"])
@pytest.mark.parametrize("mutation", ["changed", "deleted"])
def test_supporting_outcome_evidence_bytes_invalidate_confirmation(support, mutation):
    sb = fixtures.TempStore()
    try:
        owner, feature, task = "work/projects/p", "work/features/f", "work/tasks/t"
        for ref, parent in ((owner, None), (feature, owner),
                            (task, feature if support == "nested" else owner)):
            sb.write(f"{ref}/card.md", fixtures.doc("card", status="done", parent=parent))
            sb.write(f"{ref}/outcome.yaml", json.dumps({
                "schema_version": 1, "actual": "Delivered",
                "evidence": ["task-proof.txt"] if ref == task else []}))
        proof = sb.write("task-proof.txt", "PASS")
        sb.write("proof.txt", "Independent criterion verification")
        node = {"id": "n", "title": "Work", "expected": "Delivered",
                "record": feature if support == "nested" else task}
        criterion = {"id": "c", "statement": "C", "verification": "Check", "works": ["n"]}
        plan = {"schema_version": 1, "expected": "Product", "nodes": [node],
                "criteria": [criterion]}
        if support == "nested":
            sb.write(f"{feature}/plan.yaml", json.dumps({**plan, "criteria": [], "nodes": [
                {**node, "record": task}]}))
        if support == "dependency":
            plan["criteria"] = [{**criterion, "id": "base"}, {
                **criterion, "works": [],
                "dependencies": [{"owner": owner, "criterion": "base"}]}]
        sb.write(f"{owner}/plan.yaml", json.dumps(plan))

        def confirm(cid):
            out = sb.cli("plan", "confirm", owner, "--criterion", cid, "--result", "pass",
                         "--actual", "Verified", "--evidence", "proof.txt")
            assert out.returncode == 0, out.stderr

        def current():
            out = sb.cli("plan", "summary", owner, "--json")
            return next(c for c in json.loads(out.stdout)["records"][0]["criteria"]
                        if c["id"] == "c")

        if support == "dependency":
            confirm("base")
        confirm("c")
        before = current()
        assert before["acceptance"] == "pass"
        if mutation == "changed":
            proof.write_text("FAIL: retracted result")
        else:
            proof.unlink()
        after = current()
        assert after["acceptance"] == "review_required"
        assert after["work_fingerprint"] != before["work_fingerprint"]
        assert after["history"] == before["history"]
    finally:
        sb.cleanup()


@pytest.mark.parametrize("swap_at", [1, 2])
@pytest.mark.parametrize("ancestor", [False, True])
def test_replacement_parent_swap_never_creates_files_outside_store(swap_at, ancestor):
    import os
    from svod import plan_write
    from svod.plan_schema import Invalid

    sb = fixtures.TempStore()
    try:
        parent = sb.store / "outputs" / "owner"
        parent.mkdir(parents=True)
        outside = sb.root / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"untouched")
        destination = parent / "acceptance.yaml"
        destination.write_bytes(b"original")
        moved = sb.store / "original-parent"
        swapped = parent.parent if ancestor else parent
        outside_creations = []
        original_open = os.open
        calls = 0

        def monitored_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            outside_creations.extend(p.name for p in outside.iterdir() if p != sentinel)
            return fd

        def verify():
            nonlocal calls
            calls += 1
            if calls == swap_at:
                swapped.rename(moved)
                swapped.symlink_to(outside, target_is_directory=True)
            return calls < swap_at

        # Return True on the first verification to reproduce the post-check race.
        def racing_verify():
            result = verify()
            return True if calls == 1 else result

        with mock.patch.object(os, "open", side_effect=monitored_open), \
                pytest.raises((Invalid, OSError)):
            plan_write.replace(destination, b"SENSITIVE CONFIRMATION", b"original", racing_verify)
        assert outside_creations == []
        assert list(outside.iterdir()) == [sentinel]
        assert sentinel.read_bytes() == b"untouched"
        original_parent = moved / "owner" if ancestor else moved
        assert (original_parent / "acceptance.yaml").read_bytes() == b"original"
        assert sorted(p.name for p in original_parent.iterdir()) == ["acceptance.yaml"]
    finally:
        sb.cleanup()


@pytest.mark.parametrize("bad_input", ["outcome.yaml", "acceptance.yaml", "card.md",
                                       "proof.txt", "unrelated-card", "unreadable"])
def test_unreadable_inputs_are_structured_at_summary_and_confirm(bad_input):
    from svod import plan_write

    sb = fixtures.TempStore()
    try:
        owner = "work/projects/p"
        sb.write(f"{owner}/card.md", fixtures.doc("card"))
        sb.write(f"{owner}/plan.yaml", json.dumps({
            "schema_version": 1, "expected": "Product", "nodes": [], "criteria": [
                {"id": "c", "statement": "C", "verification": "Check", "works": []}]}))
        sb.write(f"{owner}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Result", "evidence": ["proof.txt"]}))
        sb.write("proof.txt", "Proof")
        target = (sb.store / "work/tasks/unrelated/card.md" if bad_input == "unrelated-card"
                  else sb.store / ("proof.txt" if bad_input == "proof.txt"
                                   else f"{owner}/{bad_input}"))
        if bad_input != "unreadable":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            target.mkdir()
        read = plan_write.read_bytes

        def unreadable(path):
            if bad_input == "unreadable" and path.name == "outcome.yaml":
                raise PermissionError("fixture cannot read outcome")
            return read(path)

        with mock.patch.object(plan_write, "read_bytes", side_effect=unreadable):
            out = sb.cli("plan", "summary", owner, "--json")
            assert out.returncode == 1, out.stderr
            diagnostics = json.loads(out.stdout)["diagnostics"]
            assert "unreadable" in [d["code"] for d in diagnostics]
            out = sb.cli("plan", "confirm", owner, "--criterion", "c", "--result", "pass",
                         "--actual", "Checked", "--evidence", "proof.txt")
            assert out.returncode == 2, out.stderr
            assert "invalid_plan" in out.stderr
        assert not (sb.store / owner / "acceptance.yaml").is_file()
    finally:
        sb.cleanup()


@pytest.mark.parametrize("location", ["outcome", "confirmation", "argument"])
def test_malformed_evidence_url_is_diagnostic_not_parser_exception(location):
    sb = fixtures.TempStore()
    try:
        owner = "work/projects/p"
        sb.write(f"{owner}/card.md", fixtures.doc("card"))
        sb.write(f"{owner}/plan.yaml", json.dumps({
            "schema_version": 1, "expected": "Product", "nodes": [], "criteria": [
                {"id": "c", "statement": "C", "verification": "Check", "works": []}]}))
        sb.write(f"{owner}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Result", "evidence": []}))
        sb.write("proof.txt", "Proof")

        def confirm(evidence):
            return sb.cli("plan", "confirm", owner, "--criterion", "c", "--result", "pass",
                          "--actual", "Checked", "--evidence", evidence)

        assert confirm("proof.txt").returncode == 0
        acceptance = sb.store / owner / "acceptance.yaml"
        if location == "outcome":
            sb.write(f"{owner}/outcome.yaml", json.dumps({
                "schema_version": 1, "actual": "Result", "evidence": ["http://["]}))
        elif location == "confirmation":
            value = json.loads(acceptance.read_text())
            value["confirmations"][0]["evidence"] = ["http://["]
            acceptance.write_text(json.dumps(value))
        before = acceptance.read_bytes()
        out = confirm("http://[")
        assert out.returncode == 2, out.stderr
        assert "evidence" in out.stderr or "invalid_plan" in out.stderr
        assert acceptance.read_bytes() == before
        if location != "argument":
            out = sb.cli("plan", "summary", owner, "--json")
            assert out.returncode == 1, out.stderr
            data = json.loads(out.stdout)
            assert "evidence" in [d["code"] for d in data["diagnostics"]]
            assert data["records"][0]["criteria"][0]["acceptance"] == "review_required"
    finally:
        sb.cleanup()


@pytest.mark.parametrize("malformed", ["nul", "symlink_loop"])
@pytest.mark.parametrize("location", ["record", "node", "dependency", "outcome",
                                      "confirmation", "argument", "unrelated-card"])
def test_malformed_paths_are_diagnostic_and_confirmation_is_fail_closed(malformed, location):
    sb = fixtures.TempStore()
    try:
        owner = "work/projects/p"
        sb.write(f"{owner}/card.md", fixtures.doc("card"))
        plan = {"schema_version": 1, "expected": "Product", "nodes": [], "criteria": [
            {"id": "c", "statement": "C", "verification": "Check", "works": []}]}
        sb.write(f"{owner}/plan.yaml", json.dumps(plan))
        sb.write(f"{owner}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Result", "evidence": []}))
        sb.write("proof.txt", "Proof")

        def confirm(record=owner, evidence="proof.txt"):
            return sb.cli("plan", "confirm", record, "--criterion", "c", "--result", "pass",
                          "--actual", "Checked", "--evidence", evidence)

        assert confirm().returncode == 0
        acceptance = sb.store / owner / "acceptance.yaml"
        bad = "bad\x00path" if malformed == "nul" else "badpath"
        if malformed == "symlink_loop":
            (sb.store / bad).symlink_to(bad)
        if location == "node":
            plan["nodes"] = [{"id": "n", "title": "N", "expected": "N", "record": bad}]
        elif location == "dependency":
            plan["criteria"][0]["dependencies"] = [{"owner": bad, "criterion": "c"}]
        elif location == "outcome":
            sb.write(f"{owner}/outcome.yaml", json.dumps({
                "schema_version": 1, "actual": "Result", "evidence": [bad]}))
        elif location == "confirmation":
            value = json.loads(acceptance.read_text())
            value["confirmations"][0]["evidence"] = [bad]
            acceptance.write_text(json.dumps(value))
        elif location == "unrelated-card":
            # Filesystem names cannot contain NUL; exercise discovery with a looping card.
            path = sb.store / "work/tasks/unrelated/card.md"
            path.parent.mkdir(parents=True)
            path.symlink_to("card.md")
        sb.write(f"{owner}/plan.yaml", json.dumps(plan))
        before = acceptance.read_bytes()
        if location != "argument":
            out = sb.cli("plan", "summary", bad if location == "record" else owner, "--json")
            assert out.returncode == 1, out.stderr
            data = json.loads(out.stdout)
            assert "unsafe_path" in [d["code"] for d in data["diagnostics"]]
            assert all(c["acceptance"] != "pass" for r in data["records"]
                       for c in r["criteria"])
        out = confirm(bad if location == "record" else owner,
                      bad if location == "argument" else "proof.txt")
        assert out.returncode == 2, out.stderr
        assert "unsafe_path" in out.stderr or "invalid_plan" in out.stderr
        assert acceptance.read_bytes() == before
        if location == "record":
            out = sb.cli("plan", "canvas", bad)
            assert out.returncode == 2, out.stderr
            assert "unsafe_path" in out.stderr
    finally:
        sb.cleanup()


@pytest.mark.parametrize("malformed", ["duplicate_edge", "duplicate_node", "shared_id",
                                      "empty_node_id", "empty_edge_id", "missing_type",
                                      "invalid_type", "missing_text", "invalid_text",
                                      "missing_endpoint", "invalid_endpoint", "unknown_endpoint"])
def test_malformed_marked_canvas_is_refused_without_writes(malformed):
    sb = fixtures.TempStore()
    try:
        owner = "work/projects/p"
        sb.write(f"{owner}/card.md", fixtures.doc("card"))
        sb.write(f"{owner}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Result", "evidence": []}))
        sb.write(f"{owner}/plan.yaml", json.dumps({
            "schema_version": 1, "expected": "Product", "criteria": [], "nodes": [
                {"id": "n", "title": "N", "expected": "N"}]}))
        assert sb.cli("plan", "canvas", owner).returncode == 0
        path = sb.store / owner / "plan.canvas"
        value = json.loads(path.read_text())
        node, edge = value["nodes"][0], value["edges"][0]
        if malformed == "duplicate_edge":
            value["edges"].append(dict(edge))
        elif malformed == "duplicate_node":
            value["nodes"].append(dict(node))
        elif malformed == "shared_id":
            edge["id"] = node["id"]
        elif malformed == "empty_node_id":
            node["id"] = ""
            edge["fromNode"] = ""
        elif malformed == "empty_edge_id":
            edge["id"] = ""
        elif malformed == "missing_type":
            del node["type"]
        elif malformed == "invalid_type":
            node["type"] = "unsupported"
        elif malformed == "missing_text":
            del node["text"]
        elif malformed == "invalid_text":
            node["text"] = []
        elif malformed == "missing_endpoint":
            del edge["fromNode"]
        elif malformed == "invalid_endpoint":
            edge["toNode"] = []
        else:
            edge["toNode"] = "unknown"
        path.write_text(json.dumps(value))
        before = {p: p.read_bytes() for p in sb.store.rglob("*") if p.is_file()}
        out = sb.cli("plan", "canvas", owner)
        assert out.returncode == 2, out.stderr
        assert "canvas:" in out.stderr
        assert before == {p: p.read_bytes() for p in sb.store.rglob("*") if p.is_file()}
    finally:
        sb.cleanup()


@pytest.mark.parametrize("repeated", ["node_dependencies", "criterion_works",
                                      "criterion_dependencies"])
def test_repeated_graph_references_are_rejected_before_canvas(repeated):
    sb = fixtures.TempStore()
    try:
        owner = "work/projects/p"
        sb.write(f"{owner}/card.md", fixtures.doc("card"))
        sb.write(f"{owner}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Result", "evidence": []}))
        plan = {"schema_version": 1, "expected": "Product", "nodes": [
            {"id": "n", "title": "N", "expected": "N"},
            {"id": "m", "title": "M", "expected": "M", "dependencies": ["n"]}],
            "criteria": [
                {"id": "base", "statement": "Base", "verification": "Check", "works": []},
                {"id": "c", "statement": "C", "verification": "Check", "works": ["m"],
                 "dependencies": [{"owner": owner, "criterion": "base"}]}]}
        path = sb.write(f"{owner}/plan.yaml", json.dumps(plan))
        assert sb.cli("plan", "validate", owner).returncode == 0
        if repeated == "node_dependencies":
            refs = plan["nodes"][1]["dependencies"]
        elif repeated == "criterion_works":
            refs = plan["criteria"][1]["works"]
        else:
            refs = plan["criteria"][1]["dependencies"]
        refs.append(refs[0])
        path.write_text(json.dumps(plan))
        out = sb.cli("plan", "summary", owner, "--json")
        data = json.loads(out.stdout)
        assert "duplicate_reference" in [d["code"] for d in data["diagnostics"]]
        assert out.returncode == 1
        sb.cli("plan", "canvas", owner)
        canvas = json.loads((sb.store / owner / "plan.canvas").read_text())
        ids = [edge["id"] for edge in canvas["edges"]]
        assert len(ids) == len(set(ids))
        assert sb.cli("plan", "canvas", owner).returncode == 1
    finally:
        sb.cleanup()


@pytest.mark.parametrize("change,code", [
    ({"schema_version": 2}, "schema"),
    ({"schema_version": True}, "schema"),
    ({"expected": []}, "schema"),
    ({"extra": "unknown"}, "schema"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A", "record": "../outside"}]},
     "unsafe_path"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A", "record": "missing"}]},
     "missing_record"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A", "record": "work/tasks/t",
                 "state": "done"}]}, "linked_local_conflict"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A", "parent": "a"}]}, "cycle"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A", "dependencies": ["a"]}]},
     "cycle"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A", "parent": "unknown"}]},
     "missing_node"),
    ({"criteria": [{"id": "a", "statement": "A", "verification": "A", "works": ["bad"]}]},
     "missing_node"),
    ({"criteria": [{"id": "a", "statement": "A", "verification": "A", "works": [],
                    "dependencies": [{"owner": "work/projects/product", "criterion": "a"}]}]},
     "cycle"),
    ({"nodes": [{"id": "a", "title": "A", "expected": "A"}] * 2}, "duplicate_id"),
    ({"criteria": [{"id": "a", "statement": "A", "verification": "A", "works": []}] * 2},
     "duplicate_id"),
])
def test_invalid_plans_have_structured_diagnostics(change, code):
    sb = fixtures.TempStore()
    try:
        owner = "work/projects/product"
        sb.write(f"{owner}/card.md", fixtures.doc("card"))
        sb.write(f"{owner}/plan.yaml", json.dumps({
            "schema_version": 1, "expected": "Product", "nodes": [], "criteria": [], **change}))
        out = sb.cli("plan", "summary", owner, "--json")
        assert out.returncode == 1, out.stderr
        assert code in [d["code"] for d in json.loads(out.stdout)["diagnostics"]]
    finally:
        sb.cleanup()


@pytest.mark.parametrize("text", [
    "schema_version: 1\nschema_version: 1\n", "x: &a [x]\ny: *a\n",
    "x: !!str value\n", "[broken", "[]", "schema_version: 1\nx: {a: 1, a: 2}\n",
])
def test_strict_yaml_is_local_to_new_planning_files(text):
    sb = fixtures.TempStore()
    try:
        sb.write("work/projects/p/card.md", fixtures.doc("card"))
        sb.write("work/projects/p/plan.yaml", text)
        out = sb.cli("plan", "summary", "work/projects/p", "--json")
        assert out.returncode == 1, out.stderr
        assert json.loads(out.stdout)["diagnostics"]
    finally:
        sb.cleanup()
