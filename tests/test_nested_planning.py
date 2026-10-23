"""Structured planning uses record kinds, not a nested path's first segment."""
import json

import pytest

import support as fixtures


@pytest.fixture
def store():
    sb = fixtures.TempStore()
    try:
        yield sb
    finally:
        sb.cleanup()


def record(sb, ref, kind, parent=None, plan=None):
    fields = {"kind": kind, "status": "done"}
    if parent:
        fields["parent"] = parent
    sb.write(f"{ref}/card.md", fixtures.doc("card", **fields))
    if kind != "research":
        sb.write(f"{ref}/outcome.yaml", json.dumps({
            "schema_version": 1, "actual": "Delivered", "evidence": []}))
    if plan is not None:
        sb.write(f"{ref}/plan.yaml", json.dumps(plan))


def plan(*refs):
    return {"schema_version": 1, "expected": "Delivered", "criteria": [], "nodes": [
        {"id": f"n{i}", "title": "Work", "expected": "Delivered", "record": ref}
        for i, ref in enumerate(refs)]}


def summary(sb, owner):
    out = sb.cli("plan", "summary", owner, "--json")
    return out, json.loads(out.stdout)


def test_nested_tasks_are_facts_not_plan_owners(store):
    owner = "work/projects/p"
    feature = f"{owner}/features/f"
    task = f"{feature}/tasks/t"
    record(store, owner, "project", plan=plan(feature))
    record(store, feature, "feature", owner, plan(task))
    record(store, task, "task", feature)
    out, data = summary(store, owner)
    assert out.returncode == 0, data["diagnostics"]
    assert [r["record"] for r in data["records"]] == [owner, feature]
    assert data["records"][1]["nodes"][0]["actual"] == "Delivered"


@pytest.mark.parametrize("research", [
    "work/projects/p/research/r", "work/projects/p/features/f/research/r",
    "work/features/f/research/r", "work/headless/research/r",
    "custom/inquiries/r",
])
def test_research_kind_does_not_require_task_outcome(store, research):
    owner = "work/projects/p"
    record(store, owner, "project", plan=plan(research))
    record(store, research, "research", owner)
    out, data = summary(store, owner)
    assert out.returncode == 0, data["diagnostics"]
    assert data["records"][0]["nodes"][0]["state"] == "done"
    assert data["records"][0]["nodes"][0]["actual"] is None


@pytest.mark.parametrize("child,kind", [
    ("work/projects/p/tasks/t", "task"),
    ("work/projects/p/research/r", "research"),
    ("work/projects/p/features/f/tasks/t", "task"),
    ("work/projects/p/features/f/research/r", "research"),
    ("work/features/f/tasks/t", "task"),
    ("work/features/f/research/r", "research"),
    ("work/headless/tasks/t", "task"),
    ("work/headless/research/r", "research"),
    ("work/hotfix/h", "hotfix"),
])
def test_nested_unplanned_children_remain_visible(store, child, kind):
    owner = "work/projects/p"
    record(store, owner, "project", plan=plan())
    record(store, child, kind, owner)
    _, data = summary(store, owner)
    assert any(d["code"] == "unplanned_child" and d["path"] == child
               for d in data["diagnostics"])


def test_all_includes_standalone_and_unlinked_nested_plan_owners_only(store):
    owners = ["work/projects/p", "work/features/solo", "work/projects/p/features/f"]
    for ref in owners:
        record(store, ref, "project" if ref == owners[0] else "feature", plan=plan())
    record(store, "work/features/solo/tasks/t", "task")
    # An explicit kind takes precedence over a misleading legacy directory name.
    record(store, "work/features/not-an-owner", "task")
    store.write("work/projects/p/archive/experiment/card.md", "not a record")
    store.write("work/projects/p/archive/experiment/plan.yaml", "invalid: plan")
    out = store.cli("plan", "summary", "--all", "--json")
    data = json.loads(out.stdout)
    assert out.returncode == 0, data["diagnostics"]
    assert {r["record"] for r in data["records"]} == set(owners)


def test_malformed_kind_does_not_crash_all_inventory(store):
    record(store, "work/projects/p", "project", plan=plan())
    store.write("work/features/bad/card.md", "---\ntype: card\nkind: [feature]\n---\n")
    out = store.cli("plan", "summary", "--all", "--json")
    assert out.returncode == 0, out.stderr
    assert [r["record"] for r in json.loads(out.stdout)["records"]] == ["work/projects/p"]


def test_nested_support_confirmation_reopens_without_rewriting_history(store):
    owner, feature = "work/projects/p", "work/projects/p/features/f"
    task = f"{feature}/tasks/t"
    owner_plan = plan(feature)
    owner_plan["criteria"] = [{"id": "c", "statement": "Usable", "verification": "Exercise",
                                "works": ["n0"]}]
    record(store, owner, "project", plan=owner_plan)
    record(store, feature, "feature", owner, plan(task))
    record(store, task, "task", feature)
    store.write("proof.txt", "Verified")
    out = store.cli("plan", "confirm", owner, "--criterion", "c", "--result", "pass",
                    "--actual", "Checked", "--evidence", "proof.txt")
    assert out.returncode == 0, out.stderr
    acceptance = store.store / owner / "acceptance.yaml"
    before = acceptance.read_bytes()
    _, data = summary(store, owner)
    assert data["records"][0]["criteria"][0]["acceptance"] == "pass"
    store.write(f"{task}/card.md", fixtures.doc("card", kind="task", status="active",
                                              parent=feature))
    _, data = summary(store, owner)
    assert data["records"][0]["criteria"][0]["acceptance"] == "review_required"
    assert acceptance.read_bytes() == before


def test_declared_custom_feature_is_a_linked_plan_owner_without_policy_loading(store):
    owner, feature, task = "work/projects/p", "custom/initiatives/f", "custom/jobs/t"
    record(store, owner, "project", plan=plan(feature))
    record(store, feature, "feature", owner, plan(task))
    record(store, task, "task", feature)
    out, data = summary(store, owner)
    assert out.returncode == 0, data["diagnostics"]
    assert [r["record"] for r in data["records"]] == [owner, feature]


def test_research_descendants_omitted_from_owner_plan_are_visible(store):
    owner = "work/features/f"
    research, next_research, task = (f"{owner}/research/r", f"{owner}/research/r2",
                                     f"{owner}/tasks/t")
    record(store, owner, "feature", plan=plan(research))
    record(store, research, "research", owner)
    record(store, next_research, "research", research)
    record(store, task, "task", next_research)
    _, data = summary(store, owner)
    assert {d["path"] for d in data["diagnostics"] if d["code"] == "unplanned_child"} == {
        next_research, task}


def test_research_parent_is_provenance_for_sibling_task_in_owner_plan(store):
    owner = "work/projects/p/features/f"
    research, task = f"{owner}/research/r", f"{owner}/tasks/t"
    record(store, owner, "feature", plan=plan(research, task))
    record(store, research, "research", owner)
    record(store, task, "task", research)
    out, data = summary(store, owner)
    assert out.returncode == 0, data["diagnostics"]
    assert len(data["records"]) == 1
    assert data["records"][0]["nodes"][1]["actual"] == "Delivered"
    # Provenance must not hide an actual ownership conflict.
    other = "work/projects/other"
    record(store, research, "research", other)
    _, data = summary(store, owner)
    assert any(d["code"] == "parent_conflict" and d["path"] == task
               for d in data["diagnostics"])
