"""Execute the shipped, source-grounded example against an installed combined engine.

No general prose converter: the JSON is a reviewed, finite batch with exact sources.
Run on a combined source tree, never claim the pre-core branch alone is deployable.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

import support as fixtures
from svod.approval import digest, digest_matches

SKILL = "svod-planning-transition"
EXAMPLE = fixtures.REPO_DIR / "svod/skills" / SKILL / "references/example.json"


def test_installed_source_grounded_transition():
    sb = fixtures.TempStore()
    try:
        example = json.loads(EXAMPLE.read_text())
        for rel, text in example["sources"].items():
            sb.write(rel, text)
        sb.init_git(remote=False)
        source = sb.root / "candidate-source"
        source.mkdir()
        import test_vendoring as vendoring
        vendoring.source_files(source)
        sb.init_git(source, remote=False)
        sb.git(source, "tag", "transition-test")
        feature = "work/features/search"
        old_bind = ["brief.md", "questions.md", "breakdown.md"]
        old_sha = digest(sb.store / feature, old_bind)
        # Synthetic, fixture-only historical event, never real user consent.
        sb.write(f"{feature}/approval.yaml", "# SYNTHETIC historical fixture only\n"
                 f"brief_approved: '2026-09-01'\nbrief_approved_by: fixture@example.invalid\n"
                 f"brief_approved_sha: {old_sha}\n")
        sb.write("profile/pipelines/feature.yaml", yaml.safe_dump({
            "pipeline": "feature", "steps": [{"id": "approve", "gates": [{
                "gate": "approval", "params": {"bind": old_bind}}]}]}))
        protected = {p: p.read_bytes() for p in sb.store.rglob("*")
                     if p.is_file() and ".git" not in p.parts}
        installed = sb.cli("install", "--from", str(source), "--to", "transition-test",
                           "--no-profile")
        assert installed.returncode == 0, installed.stdout + installed.stderr
        assert all(p.read_bytes() == b for p, b in protected.items())
        assert not list((sb.store / "work").rglob("plan.yaml"))
        delivered_example = sb.store / ".svod/skills" / SKILL / "references/example.json"
        assert delivered_example.read_bytes() == EXAMPLE.read_bytes()
        env = fixtures.child_env(**sb.env, PYTHONDONTWRITEBYTECODE="1")
        env["PYTHONPATH"] = str(sb.store / ".svod/lib")
        commands = []

        def cli(*args, codes=(0,)):
            out = subprocess.run([sys.executable, "-m", "svod.cli", *args], cwd=sb.store,
                                 env=env, capture_output=True, text=True, timeout=60)
            commands.append({"args": list(args), "code": out.returncode,
                             "stdout": out.stdout, "stderr": out.stderr})
            assert out.returncode in codes, commands[-1]
            return out

        probe = subprocess.run([sys.executable, "-c", "import svod; print(svod.__file__)"],
                               cwd=sb.root, env=env, capture_output=True, text=True, check=True)
        assert Path(probe.stdout.strip()).is_relative_to(sb.store / ".svod/lib")
        cli("plan", "confirm", "--help")
        inventory = {}
        for card in (sb.store / "work").rglob("card.md"):
            fields = yaml.safe_load(card.read_text().split("---")[1])
            inventory[card.parent.relative_to(sb.store).as_posix()] = fields
        selected = {example["root"]}
        while True:
            expanded = selected | {ref for ref, fields in inventory.items()
                                   if fields.get("parent") in selected}
            if expanded == selected:
                break
            selected = expanded
        assert selected == set(example["selected"])
        completed = {r for r in selected if inventory[r]["status"] == "done"}
        assert completed == set(example["completed"])
        assert set(inventory) - selected == set(example["outside"])
        # Preview only: exact bytes remain unchanged; orphan is a question, not a new ID.
        assert all(p.read_bytes() == b for p, b in protected.items())
        assert not (sb.store / "work/tasks/missing").exists()

        def batch():
            # This approved finite batch has exact source guards, not guessed prose parsing.
            for rel, text in example["sources"].items():
                if (sb.store / rel).read_text() != text:
                    raise ValueError(f"source conflict: {rel}; ask before changing targets")
            for rel, text in example["targets"].items():
                if not (sb.store / rel).exists():
                    sb.write(rel, text)

        batch()
        assert selected == set(example["converted"]) | set(example["remaining"])
        assert not set(example["converted"]) & set(example["remaining"])
        assert example["remaining"] == []
        summary = json.loads(cli("plan", "summary", example["root"], "--json", codes=(1,)).stdout)
        assert not [d for d in summary["diagnostics"] if d["severity"] == "error"]
        records = {r["record"]: r for r in summary["records"]}
        assert set(records) == {example["root"], feature}
        criteria = {(owner, c["id"]) for owner, r in records.items() for c in r["criteria"]}
        assert criteria == {tuple(c) for c in example["criteria"]}
        assert all(c["acceptance"] == "unconfirmed"
                   for r in records.values() for c in r["criteria"])
        nodes = {n["record"]: n for r in records.values() for n in r["nodes"] if n.get("record")}
        assert selected - {example["root"]} == set(nodes)
        assert nodes["work/tasks/index"]["state"] == "done"
        assert nodes["work/tasks/index"]["actual"] == "Index supports title"
        assert nodes["work/tasks/archive"]["actual"] is None
        for owner in (example["root"], feature):
            cli("plan", "validate", owner, codes=(1,))
            cli("plan", "summary", owner, codes=(1,))
        cli("plan", "summary", "--all", codes=(1,))
        all_data = json.loads(cli("plan", "summary", "--all", "--json", codes=(1,)).stdout)
        assert {r["record"] for r in all_data["records"]} == set(records)
        # Missing proof is refused, never a current PASS or an acceptance file.
        cli("plan", "confirm", feature, "--criterion", "find-fields", "--result", "pass",
            "--actual", "Not evidenced", "--evidence", "missing-proof.txt", codes=(2,))
        assert not (sb.store / feature / "acceptance.yaml").exists()
        # An explicit new verification of this finite fixture's title fact only.
        assert "title: fixture-hit" in (sb.store / "checks/title.txt").read_text()
        sb.write("checks/current-title.txt", "Synthetic fixture verification: title: fixture-hit\n")
        cli("plan", "confirm", feature, "--criterion", "title", "--result", "pass",
            "--actual", "Read fixture title result; author was not verified",
            "--evidence", "checks/current-title.txt")
        after = json.loads(cli("plan", "summary", feature, "--json", codes=(1,)).stdout)
        accepted = {c["id"]: c["acceptance"] for c in after["records"][0]["criteria"]}
        assert accepted == {"find-fields": "unconfirmed", "title": "pass"}
        acceptance = sb.store / feature / "acceptance.yaml"
        assert len(json.loads(acceptance.read_text())["confirmations"]) == 1
        acceptance_bytes = acceptance.read_bytes()
        cli("plan", "canvas", example["root"], codes=(0, 1))
        canvas_path = sb.store / example["root"] / "plan.canvas"
        canvas = json.loads(canvas_path.read_text())
        retained = canvas["nodes"][0]["id"]
        canvas["nodes"][0].update(x=1234, y=-567, width=456, height=321)
        canvas_path.write_text(json.dumps(canvas))
        plan_path = sb.store / example["root"] / "plan.yaml"
        plan = yaml.safe_load(plan_path.read_text())
        plan["expected"] += " (manual clarification)"
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
        manual = plan_path.read_bytes()
        note = sb.store / "backfill-notes.md"
        question_bytes = note.read_bytes()
        batch()
        cli("plan", "canvas", example["root"], codes=(0, 1))
        repeated = json.loads(canvas_path.read_text())
        moved = next(n for n in repeated["nodes"] if n["id"] == retained)
        assert [moved[k] for k in ("x", "y", "width", "height")] == [1234, -567, 456, 321]
        assert {n["id"] for n in canvas["nodes"]} == {n["id"] for n in repeated["nodes"]}
        assert len({n["id"] for n in repeated["nodes"]}) == len(repeated["nodes"])
        assert plan_path.read_bytes() == manual
        assert note.read_bytes() == question_bytes
        assert acceptance.read_bytes() == acceptance_bytes
        for owner in records:
            data = yaml.safe_load((sb.store / owner / "plan.yaml").read_text())
            assert len({n["id"] for n in data["nodes"]}) == len(data["nodes"])
        # Changed source refuses the finite batch without overwriting target refinements.
        source_path = sb.store / feature / "brief.md"
        source_path.write_text(source_path.read_text() + "New conflicting requirement\n")
        try:
            batch()
        except ValueError as exc:
            assert "source conflict" in str(exc)
        else:
            raise AssertionError("A changed source must be reviewed")
        assert plan_path.read_bytes() == manual
        source_path.write_bytes(protected[source_path])
        assert all(p.read_bytes() == b for p, b in protected.items())
        # Separate fixture-only profile selection; retain steps/gates, change binds/source.
        pipeline_path = sb.store / "profile/pipelines/feature.yaml"
        old_pipeline = yaml.safe_load(pipeline_path.read_text())
        standard = fixtures.REPO_DIR / "svod/templates/standard/profile/pipelines/feature.yaml"
        new_pipeline = yaml.safe_load(standard.read_text())
        approve = next(s for s in new_pipeline["steps"] if s["id"] == "approve")
        new_bind = approve["gates"][0]["params"]["bind"]
        assert new_bind == ["brief.md", "questions.md", "plan.yaml"]
        assert digest_matches(sb.store / feature, old_bind, None, old_sha)
        assert not digest_matches(sb.store / feature, new_bind, None, old_sha)
        old_pipeline["steps"][0]["gates"][0]["params"]["bind"] = new_bind
        pipeline_path.write_text(yaml.safe_dump(old_pipeline))
        assert yaml.safe_load(pipeline_path.read_text()) == old_pipeline
        # Exercise the real approval gate on preserved bytes, not only digest comparison.
        from svod.config import load_config
        from svod.context import Context
        from svod.gates import ApprovalGate, Status
        from svod.subject import Subject
        ctx = Context(load_config(sb.store))
        subject = Subject(id=feature, path=sb.store / feature)
        params = {"marker": "brief_approved", "file": "approval.yaml", "bind": old_bind}
        assert ApprovalGate(params).evaluate(ctx, subject).status == Status.PASS
        drift = ApprovalGate({**params, "bind": new_bind}).evaluate(ctx, subject)
        assert drift.status == Status.FAIL and drift.facts["reason"] == "drift"
        approval_path = sb.store / feature / "approval.yaml"
        assert approval_path.read_bytes() == protected[approval_path]
        report = {"inventory": inventory, "selected": sorted(selected),
                  "converted": example["converted"], "remaining": example["remaining"],
                  "outside": example["outside"], "criteria": sorted(criteria),
                  "historical_approval_preserved": True, "old_bind_current": True,
                  "new_bind_stale": True, "installed_import": probe.stdout.strip(),
                  "commands": commands}
        (sb.root / "verification.json").write_text(json.dumps(report, indent=2))
        artifacts = os.environ.get("SVOD_TRANSITION_ARTIFACTS")
        if artifacts:
            import tempfile
            destination = Path(tempfile.mkdtemp(prefix="installed-roundtrip-", dir=artifacts))
            shutil.copytree(sb.root, destination, dirs_exist_ok=True)
    finally:
        sb.cleanup()
