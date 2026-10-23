"""Standard record roots cover the approved hierarchy without a flat task registry."""
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parents[1] / "svod/templates/standard"


def test_standard_roots_cover_nested_work():
    expected = {
        "project": ["work/projects"],
        "feature": ["work/features", "work/projects/*/features"],
        "task": ["work/headless/tasks", "work/hotfix", "work/features/*/tasks",
                 "work/projects/*/tasks", "work/projects/*/features/*/tasks"],
        "research": ["work/headless/research", "work/features/*/research",
                     "work/projects/*/research", "work/projects/*/features/*/research"],
    }
    for name, roots in expected.items():
        data = yaml.safe_load((TEMPLATE / f"profile/pipelines/{name}.yaml").read_text())
        assert data["subject"]["params"]["roots"] == roots


def test_research_can_produce_task_or_research():
    data = yaml.safe_load((TEMPLATE / "profile/pipelines/research.yaml").read_text())
    outcome = next(step for step in data["steps"] if step["id"] == "outcome")
    refs = [gate for gate in outcome["gates"] if gate["gate"] == "ref_exists"]
    assert len(refs) == 1
    assert refs[0]["params"]["pipelines"] == ["task", "research"]
