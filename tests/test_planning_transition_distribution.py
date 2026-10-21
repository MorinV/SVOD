"""Actual bundled/wheel distribution; planning behavior is exercised by integration tests."""
import os
import shutil
import subprocess
import sys
import unittest
import zipfile

from support import REPO_DIR, TempStore, child_env

from svod import vendor

SKILL = "svod-planning-transition"
RESOURCES = ("SKILL.md", "references/backfill.md", "references/example.json")


class PlanningTransitionDistributionTest(unittest.TestCase):
    def setUp(self):
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)

    def test_engine_only_install_preserves_content_and_distributes_instruction(self):
        source = self.sb.root / "source"
        source.mkdir()
        # A test-owned Git source, not a commit in the candidate worktree.
        import test_vendoring as fixtures
        fixtures.source_files(source)
        self.sb.init_git(source, remote=False)
        self.sb.commit(source, "synthetic candidate")
        self.sb.git(source, "tag", "candidate-test")
        protected = {
            "profile/pipelines/local.yaml": b"local policy: unchanged\n",
            "work/tasks/closed/card.md": b"---\nkind: task\nstatus: done\n---\n",
            "work/tasks/closed/approval.yaml": b"historical-test-only: never-rebind\n",
            "work/projects/demo/breakdown.md": b"Original historical plan\n",
        }
        for rel, data in protected.items():
            path = self.sb.store / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        installed = self.sb.cli("install", "--from", str(source), "--to", "candidate-test",
                                "--no-profile")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        for rel, data in protected.items():
            self.assertEqual((self.sb.store / rel).read_bytes(), data)
        for rel in RESOURCES:
            expected = (REPO_DIR / vendor.SKILLS_SOURCE / SKILL / rel).read_bytes()
            self.assertEqual((self.sb.store / ".svod/skills" / SKILL / rel).read_bytes(),
                             expected)
        self.assertFalse(list((self.sb.store / "work").rglob("plan.yaml")))
        self.assertFalse(list((self.sb.store / "work").rglob("acceptance.yaml")))
        self.assertFalse(list((self.sb.store / "work").rglob("outcome.yaml")))
        self.assertEqual(vendor.copy_errors(self.sb.store), [])
        target = self.sb.root / "bundled-agent-skills"
        self.link(target)
        self.assertEqual((target / SKILL).resolve(), self.sb.store / ".svod/skills" / SKILL)
        self.assertTrue((target / SKILL / "references/backfill.md").is_file())

    def link(self, target):
        command = 'source "$1"; link_skills "$2" "$3"'
        result = subprocess.run(
            ["bash", "-c", command, "transition-test", str(REPO_DIR / "integrations/common.sh"),
             str(target), str(self.sb.store)],
            env=child_env(**self.sb.env), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_discovery_shared_and_store_override_have_documented_fallback(self):
        target = self.sb.root / "agent-skills"
        self.link(target)
        linked = target / SKILL
        self.assertTrue(linked.is_symlink())
        self.assertEqual(linked.resolve(), REPO_DIR / vendor.SKILLS_SOURCE / SKILL)
        for rel in RESOURCES:
            self.assertTrue((linked / rel).is_file())
        # Store skills take precedence as a whole, not per skill. Do not change discovery.
        linked.unlink()
        self.sb.write("skills/local/SKILL.md", "---\nname: local\n---\nLocal policy\n")
        self.link(target)
        self.assertFalse(os.path.lexists(linked))
        self.assertTrue((target / "local/SKILL.md").is_file())
        fallback = REPO_DIR / vendor.SKILLS_SOURCE / SKILL / "SKILL.md"
        self.assertTrue(fallback.is_file())

    def test_wheel_contains_readable_instruction_outside_checkout(self):
        source = self.sb.root / "wheel-source"
        source.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(REPO_DIR / name, source / name)
        shutil.copytree(REPO_DIR / "svod", source / "svod",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wheels = self.sb.root / "wheels"
        wheels.mkdir()
        env = child_env(**self.sb.env)
        # Build declared backend from an isolated source copy; no checkout build debris.
        build = subprocess.run(
            [sys.executable, "-c", "from setuptools.build_meta import build_wheel; "
             f"build_wheel({str(wheels)!r})"], cwd=source, env=env,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        wheel_files = list(wheels.glob("*.whl"))
        self.assertEqual(len(wheel_files), 1)
        extracted = self.sb.root / "extracted"
        with zipfile.ZipFile(wheel_files[0]) as archive:
            names = archive.namelist()
            self.assertFalse(any("__pycache__" in n or n.endswith(".pyc") for n in names))
            for rel in RESOURCES:
                name = f"svod/skills/{SKILL}/{rel}"
                self.assertIn(name, names)
                self.assertEqual(archive.read(name),
                                 (REPO_DIR / vendor.SKILLS_SOURCE / SKILL / rel).read_bytes())
            archive.extractall(extracted)
        env["PYTHONPATH"] = str(extracted)
        probe = (
            "from pathlib import Path; import svod; "
            f"assert Path(svod.__file__).is_relative_to(Path({str(extracted)!r})); "
            f"p = Path(svod.__file__).parent / 'skills' / {SKILL!r}; "
            "assert 'source-grounded' in (p / 'SKILL.md').read_text(); "
            "assert 'unconfirmed' in (p / 'references/backfill.md').read_text()"
        )
        read = subprocess.run([sys.executable, "-c", probe], cwd=self.sb.root, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(read.returncode, 0, read.stdout + read.stderr)
        version = subprocess.run([sys.executable, "-m", "svod.cli", "--version"],
                                 cwd=self.sb.root, env=env, capture_output=True,
                                 text=True, timeout=60)
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        # Execute planning from the built package, not the checkout or ZIP keywords.
        import json
        example = json.loads((extracted / "svod/skills" / SKILL /
                              "references/example.json").read_text())
        for rel, text in {**example["sources"], **example["targets"]}.items():
            self.sb.write(rel, text)
        summary = subprocess.run(
            [sys.executable, "-m", "svod.cli", "plan", "summary", "--all", "--json"],
            cwd=self.sb.store, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(summary.returncode, 1, summary.stderr)
        data = json.loads(summary.stdout)
        self.assertEqual({r["record"] for r in data["records"]},
                         {"work/projects/demo", "work/features/search"})
        self.assertFalse([d for d in data["diagnostics"] if d["severity"] == "error"])
        artifacts = os.environ.get("SVOD_TRANSITION_ARTIFACTS")
        if artifacts:
            import tempfile
            destination = tempfile.mkdtemp(prefix="wheel-distribution-", dir=artifacts)
            shutil.copytree(wheels, destination, dirs_exist_ok=True)


if __name__ == "__main__":
    unittest.main()
