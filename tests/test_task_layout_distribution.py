"""Nested-layout instructions are delivered by the real wheel and bundled installer."""
import os
import shutil
import subprocess
import sys
import unittest
import zipfile

from support import REPO_DIR, TempStore, child_env

from svod import vendor

SKILL = "svod-task-layout-transition"
TEMPLATE = "svod/templates/standard/"
RESOURCES = (
    f"svod/skills/{SKILL}/SKILL.md",
    f"svod/skills/{SKILL}/references/mapping.md",
    TEMPLATE + "README.md",
    TEMPLATE + "AGENTS.md",
    TEMPLATE + "skills/svod-task/SKILL.md",
    TEMPLATE + "skills/svod-feature/SKILL.md",
    TEMPLATE + "skills/svod-project/SKILL.md",
    TEMPLATE + "skills/svod-research/SKILL.md",
    TEMPLATE + "profile/records/task/card.md",
    TEMPLATE + "profile/records/feature/card.md",
    TEMPLATE + "profile/records/feature/plan.yaml",
    TEMPLATE + "profile/records/project/card.md",
    TEMPLATE + "profile/records/project/plan.yaml",
    TEMPLATE + "profile/records/research/card.md",
    TEMPLATE + "profile/locale/en.yaml",
    TEMPLATE + "profile/locale/ru.yaml",
    TEMPLATE + "work/headless/tasks/example/card.md",
    TEMPLATE + "work/headless/tasks/example/contract.md",
    TEMPLATE + "work/headless/tasks/example/questions.md",
)


class TaskLayoutDistributionTest(unittest.TestCase):
    def setUp(self):
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)

    def test_wheel_delivers_layout_instruction_and_nested_template(self):
        source = self.sb.root / "wheel-source"
        source.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(REPO_DIR / name, source / name)
        shutil.copytree(REPO_DIR / "svod", source / "svod",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wheels = self.sb.root / "wheels"
        wheels.mkdir()
        env = child_env(**self.sb.env)
        built = subprocess.run(
            [sys.executable, "-c", "from setuptools.build_meta import build_wheel; "
             f"build_wheel({str(wheels)!r})"], cwd=source, env=env,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        wheel_files = list(wheels.glob("*.whl"))
        self.assertEqual(len(wheel_files), 1)
        extracted = self.sb.root / "extracted"
        with zipfile.ZipFile(wheel_files[0]) as archive:
            for name in RESOURCES:
                self.assertIn(name, archive.namelist())
                self.assertEqual(archive.read(name), (REPO_DIR / name).read_bytes())
            self.assertNotIn(TEMPLATE + "work/tasks/example/card.md", archive.namelist())
            self.assertFalse(any("__pycache__" in n or n.endswith(".pyc")
                                 for n in archive.namelist()))
            archive.extractall(extracted)
        env["PYTHONPATH"] = str(extracted)
        probe = (
            "from pathlib import Path; import svod; "
            f"assert Path(svod.__file__).is_relative_to(Path({str(extracted)!r})); "
            f"p=Path(svod.__file__).parent/'skills'/{SKILL!r}; "
            "assert 'collision' in (p/'SKILL.md').read_text(); "
            "assert 'approval.yaml' in (p/'references/mapping.md').read_text()"
        )
        read = subprocess.run([sys.executable, "-c", probe], cwd=self.sb.root, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(read.returncode, 0, read.stdout + read.stderr)
        help_result = subprocess.run([sys.executable, "-m", "svod.cli", "record", "new", "--help"],
                                     cwd=self.sb.root, env=env, capture_output=True,
                                     text=True, timeout=60)
        self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)

    def test_engine_only_install_keeps_existing_records_and_ships_guide(self):
        import test_vendoring as fixtures
        source = self.sb.root / "source"
        source.mkdir()
        fixtures.source_files(source)
        self.sb.init_git(source, remote=False)
        self.sb.commit(source, "synthetic layout candidate")
        self.sb.git(source, "tag", "layout-test")
        protected = {
            "work/tasks/done/card.md": b"---\nkind: task\nstatus: done\n---\n",
            "work/tasks/done/approval.yaml": b"historical: preserve-original-bytes\n",
            "work/tasks/done/work.yaml": b"app: ../existing-task-name\n",
        }
        for rel, data in protected.items():
            path = self.sb.store / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        installed = self.sb.cli("install", "--from", str(source), "--to", "layout-test",
                                "--no-profile")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        for rel, data in protected.items():
            self.assertEqual((self.sb.store / rel).read_bytes(), data)
        for rel in ("SKILL.md", "references/mapping.md"):
            self.assertEqual((self.sb.store / ".svod/skills" / SKILL / rel).read_bytes(),
                             (REPO_DIR / vendor.SKILLS_SOURCE / SKILL / rel).read_bytes())
        self.assertEqual(vendor.copy_errors(self.sb.store), [])
        target = self.sb.root / "agent-skills"
        linked = subprocess.run(
            ["bash", "-c", 'source "$1"; link_skills "$2" "$3"', "layout-test",
             str(REPO_DIR / "integrations/common.sh"), str(target), str(self.sb.store)],
            env=child_env(**self.sb.env), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
        self.assertTrue(os.path.samefile(target / SKILL, self.sb.store / ".svod/skills" / SKILL))


if __name__ == "__main__":
    unittest.main()
