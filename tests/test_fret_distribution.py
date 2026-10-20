"""Offline distribution controls; JSON examples are authored models, not solver evidence."""
import fnmatch
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "svod" / "skills" / "svod-fret"


def test_opt_in_skill_has_review_and_error_boundaries():
    path = SKILL / "SKILL.md"
    assert path.is_file(), "The optional requirements-analysis skill must be distributed"
    content = path.read_text()
    frontmatter = yaml.safe_load(content.split("---", 2)[1])
    assert frontmatter["name"] == "svod-fret"
    assert len(frontmatter["description"]) <= 60
    for term in ("REALIZABLE", "UNREALIZABLE", "UNKNOWN", "ERROR", "launcher.py"):
        assert term in content
    assert "Z3" in content
    assert "references/usage.md" in content


def test_examples_preserve_readable_requirements_and_assumptions():
    for name in ("compatible", "conflict", "invalid", "waiting"):
        source = json.loads((SKILL / "examples" / name / "requirements.json").read_text())
        assert source["assumptions"]
        assert source["requirements"]
        for requirement in source["requirements"]:
            assert requirement["description"]
            assert requirement["text"]
    waiting = json.loads((SKILL / "examples" / "waiting" / "requirements.json").read_text())
    assert {r["id"] for r in waiting["requirements"]} == {
        "WAIT_STATE", "DISPATCH_ACTION", "WAIT_NO_EXECUTION",
    }
    assert "previous occurrence" in waiting["requirements"][0]["text"]
    assert "failure_event" in waiting["requirements"][0]["text"]


def test_skill_scripts_are_data_and_bytecode_is_excluded():
    text = (ROOT / "pyproject.toml").read_text()
    excludes = re.findall(r'"([^"]+)"', text.split("exclude = ", 1)[1].split("\n", 1)[0])
    assert any(fnmatch.fnmatch("svod.skills.svod-fret.scripts", p) for p in excludes)
    patterns = re.findall(r'"([^"]+)"', text.split("[tool.setuptools.exclude-package-data]", 1)[1]
                          .split("\n\n", 1)[0])
    assert any(fnmatch.fnmatch("skills/svod-fret/scripts/__pycache__/unit.pyc", p)
               for p in patterns)
