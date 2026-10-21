"""Standard structured planning opt-in without changing legacy profiles."""
import yaml

import support as fixtures
from svod.approval import digest
from svod.scaffold import scaffold


def test_standard_scaffold_plans_and_primary_result_bindings(tmp_path):
    root = scaffold(tmp_path / "store")
    out = fixtures.run_cli(["validate"], root, fixtures.CLI_ENV)
    assert out.returncode == 0, out.stderr
    for kind in ("project", "feature"):
        out = fixtures.run_cli(["record", "new", kind, "sample"], root, fixtures.CLI_ENV)
        assert out.returncode == 0, out.stderr
        ref = f"work/{kind}s/sample"
        plan = root / ref / "plan.yaml"
        assert plan.exists(), "Scaffolding must supply plan.yaml, not manual breakdown"
        out = fixtures.run_cli(["plan", "validate", ref], root, fixtures.CLI_ENV)
        assert out.returncode == 1  # absent actual outcome is unknown
        assert "missing_outcome" in out.stdout
        pipeline = yaml.safe_load((root / f"profile/pipelines/{kind}.yaml").read_text())
        steps = {s["id"]: s for s in pipeline["steps"]}
        assert "plan.yaml" in str(steps["breakdown"]["gates"])
        deliver = steps["deliver"]["gates"][0]["params"]["bind"]
        assert {"outcome.yaml", "acceptance.yaml"} <= set(deliver)
        if kind == "feature":
            bind = steps["approve"]["gates"][0]["params"]["bind"]
            assert "plan.yaml" in bind
            assert not {"outcome.yaml", "acceptance.yaml", "plan.canvas"} & set(bind)
            before = digest(root / ref, bind)
            (root / ref / "outcome.yaml").write_text("actual: changed")
            (root / ref / "acceptance.yaml").write_text("confirmations: []")
            assert digest(root / ref, bind) == before
            plan.write_text(plan.read_text() + "# definition edit\n")
            assert digest(root / ref, bind) != before
        else:
            ids = list(steps)
            assert ids.index("architecture") < ids.index("approve") < ids.index("breakdown")


def test_unchanged_legacy_profile_and_yaml_still_work():
    sb = fixtures.TempStore()
    try:
        before = {p: p.read_bytes() for p in fixtures.TEST_PROFILE.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
        out = sb.cli("validate")
        assert out.returncode == 0, out.stderr
        assert before == {p: p.read_bytes() for p in fixtures.TEST_PROFILE.rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts}
        from svod.yamlio import parse_yaml
        assert parse_yaml("first: &a [x]\nsecond: *a\n", "legacy.yaml")["second"] == ["x"]
    finally:
        sb.cleanup()
