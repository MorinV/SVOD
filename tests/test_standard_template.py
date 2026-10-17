"""The standard template: a dispatcher store with project, feature, task and research pipelines."""
import datetime as dt
import os
import re
import string
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from support import (CLI_ENV, ENCODING, EXIT_OK, ME, REPO_DIR, git_env, run_cli)

from svod.approval import write_mark
from svod.locale import read_locale_file
from svod.scaffold import scaffold

TEMPLATE = REPO_DIR / "svod" / "templates" / "standard"
EXAMPLE = "work/tasks/example"
HOTFIX = "work/tasks/hotfix-login"
RESEARCH = "work/research/cache"
SERVICE = "app"
BRANCH = "task/example"
WORKTREE = f"{SERVICE}-task-example"
CHECK_FILE = "greeting.txt"
SKILL_WORDS = 250
AGENTS_WORDS = 150
PIPELINES = ("project", "feature", "task", "research")
SKILLS = ("svod-task", "svod-feature", "svod-project", "svod-research", "svod-questions")
ACTIONS = ("start-task.sh", "checks.sh", "pr.sh", "cleanup.sh")
LOCALES = ("en", "ru")
PAST_SEC = 120

FIRST_STEP = "name the services in card.md"
APPROVE_STEP = "svod approve work/tasks/<name> --step approve"
FROZEN = "Do not touch the code"
IMPLEMENT_STEP = "bash profile/actions/start-task.sh work/tasks/<name>"
CHECKS_STEP = "bash profile/actions/checks.sh work/tasks/<name>"
CLOSE_STEP = "after the merge set status: done in card.md"
DONE_TEXT = "done: status is done in card.md"
CAUSE_STEP = "a hotfix names its cause in card.md"
KNOWLEDGE_STEP = "write the answer to knowledge/<topic>.md"
ARCHIVED = "status: archived"
OPEN = "status: open"
ACTIVE_ITEM = f"  - {EXAMPLE} - name the services"
ACTIVE_HEADING = "Tasks:"
NO_SERVICES = "no services declared"
GATE_CHECKS = f"profile_config:\n  checks:\n    {SERVICE}: [test, -f, {CHECK_FILE}]\n"


def placeholders(template):
    """Field names of a format template."""
    return {f for _, f, _, _ in string.Formatter().parse(template) if f is not None}


def words(path):
    """Number of words of a text file."""
    return len(path.read_text(encoding=ENCODING).split())


class StandardStore:
    """A store made by svod new --template standard, with a service repository next to it."""

    def __init__(self, temp):
        """Scaffold the store, make git repositories of it and of the service."""
        self.base = Path(temp)
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {**os.environ, **git_env(self.home), **CLI_ENV,
                    "GIT_AUTHOR_NAME": ME[1], "GIT_AUTHOR_EMAIL": ME[0],
                    "GIT_COMMITTER_NAME": ME[1], "GIT_COMMITTER_EMAIL": ME[0]}
        self.store = scaffold(self.base / "store", "standard")
        self.service = self.base / SERVICE
        for repo in (self.store, self.service):
            repo.mkdir(exist_ok=True)
            self.git(repo, "init", "-q", "-b", "main")
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "init")

    def git(self, repo, *args):
        """Run git in a repository."""
        return subprocess.run(["git", "-C", str(repo), *args], env=self.env, check=True,
                              capture_output=True, text=True, encoding=ENCODING).stdout

    def cli(self, *args):
        """Run svod in the store, in this process."""
        return run_cli(args, self.store, {**git_env(self.home), **CLI_ENV})

    def action(self, name, record, *options, cwd=None, **extra):
        """Run an action script from the store root as an agent would.

        The SVOD_ variables of the process running the tests are left out, so a run of the
        suite by an action never hands its own record to these scripts.
        """
        env = {k: v for k, v in self.env.items() if not k.startswith("SVOD_")}
        return subprocess.run(["bash", f"profile/actions/{name}", record, *options],
                              cwd=str(cwd or self.store), env={**env, **extra},
                              capture_output=True, text=True, encoding=ENCODING)

    def edit(self, rel, old, new):
        """Replace a fragment of a store file."""
        path = self.store / rel
        text = path.read_text(encoding=ENCODING)
        assert old in text, (rel, old)
        path.write_text(text.replace(old, new, 1), encoding=ENCODING)

    def write(self, rel, text, base=None):
        """Write a file under the store or another base."""
        path = Path(base or self.store) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=ENCODING)

    def approve(self, record, step):
        """A person's fresh unnamed approval, then svod approve of the step."""
        past = time.time() - PAST_SEC
        for path in (self.store / record).iterdir():
            os.utime(path, (past, past))
        write_mark(self.store, [], dt.datetime.now().astimezone())
        return self.cli("approve", record, "--step", step)


class StandardTemplateTest(unittest.TestCase):
    def test_new_store_validates_and_keeps_the_example_out_of_active(self):
        """A new standard store validates; the archived example has a status, not an active line."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            created = run_cli(["new", str(sb.base / "other"), "--template", "standard"],
                              sb.base, CLI_ENV)
            self.assertEqual(created.returncode, EXIT_OK, created.stderr)
            validate = sb.cli("validate")
            self.assertEqual(validate.returncode, EXIT_OK, validate.stdout + validate.stderr)
            self.assertIn("4 pipelines", validate.stdout)
            status = sb.cli("status", EXAMPLE)
            self.assertEqual(status.returncode, EXIT_OK, status.stderr)
            self.assertIn(FIRST_STEP, status.stdout)
            self.assertIn("svod-task", status.stdout)
            self.assertNotIn("Order violations", status.stdout)
            active = sb.cli("active")
            self.assertEqual(active.returncode, EXIT_OK, active.stderr)
            self.assertNotIn(EXAMPLE, active.stdout)
            for name in PIPELINES:
                render = sb.cli("render", name)
                self.assertEqual(render.returncode, EXIT_OK, render.stderr)

    def test_task_runs_to_done_with_the_actions(self):
        """card, questions, contract, approval, worktree, checks, result approval, done."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            self.assertEqual(sb.cli("init", "--login", "tester").returncode, EXIT_OK)
            sb.edit(f"{EXAMPLE}/card.md", ARCHIVED, OPEN)
            sb.write("svod.yaml", (sb.store / "svod.yaml").read_text(encoding=ENCODING)
                     + GATE_CHECKS)
            sb.edit(f"{EXAMPLE}/card.md", "services: []", f"services: [{SERVICE}]")
            status = sb.cli("status", EXAMPLE).stdout
            self.assertIn(APPROVE_STEP, status)
            self.assertIn(FROZEN, status)
            early = sb.action("checks.sh", EXAMPLE)
            self.assertNotEqual(early.returncode, EXIT_OK)
            approved = sb.approve(EXAMPLE, "approve")
            self.assertEqual(approved.returncode, EXIT_OK, approved.stderr)
            status = sb.cli("status", EXAMPLE).stdout
            self.assertIn(IMPLEMENT_STEP, status)
            self.assertNotIn(FROZEN, status)

            for _ in range(2):
                started = sb.action("start-task.sh", EXAMPLE)
                self.assertEqual(started.returncode, EXIT_OK, started.stderr)
            worktree = sb.base / WORKTREE
            self.assertTrue((worktree / ".git").exists())
            work = (sb.store / EXAMPLE / "work.yaml").read_text(encoding=ENCODING)
            self.assertEqual(work, f"{SERVICE}: ../{WORKTREE}\n")
            self.assertIn(CHECKS_STEP, sb.cli("status", EXAMPLE).stdout)

            check = {"SVOD_CHECKS_APP": f"test -f {CHECK_FILE}"}
            sb.write(CHECK_FILE, "hello\n", base=worktree)
            dirty = sb.action("checks.sh", EXAMPLE, **check)
            self.assertNotEqual(dirty.returncode, EXIT_OK)
            self.assertIn("uncommitted", dirty.stderr)
            sb.git(worktree, "add", "-A")
            sb.git(worktree, "commit", "-q", "-m", "EXAMPLE-1: greet")
            checked = sb.action("checks.sh", EXAMPLE, **check)
            self.assertEqual(checked.returncode, EXIT_OK, checked.stderr)
            self.assertIn("passed", (sb.store / EXAMPLE / "checks.md").read_text(encoding=ENCODING))
            written = {name: (sb.store / EXAMPLE / name).read_bytes()
                       for name in ("checks.md", "checks.log")}
            again = sb.action("checks.sh", EXAMPLE, "--check", **check)
            self.assertEqual(again.returncode, EXIT_OK, again.stderr)
            self.assertIn(f"{SERVICE} @ ", again.stdout)
            self.assertEqual({name: (sb.store / EXAMPLE / name).read_bytes()
                              for name in written}, written)
            status = sb.cli("status", EXAMPLE).stdout
            self.assertIn(CLOSE_STEP, status)
            self.assertIn("checks pass", status)

            delivered = sb.approve(EXAMPLE, "deliver")
            self.assertEqual(delivered.returncode, EXIT_OK, delivered.stderr)
            pr = sb.action("pr.sh", EXAMPLE)
            self.assertEqual(pr.returncode, EXIT_OK, pr.stderr)
            self.assertTrue(pr.stdout.startswith("EXAMPLE-1: EXAMPLE-1: replace"), pr.stdout)
            self.assertIn("## Result", pr.stdout)
            self.assertNotIn("<!--", pr.stdout)

            refused = sb.action("cleanup.sh", EXAMPLE)
            self.assertNotEqual(refused.returncode, EXIT_OK)
            sb.edit(f"{EXAMPLE}/card.md", OPEN, "status: done")
            status = sb.cli("status", EXAMPLE).stdout
            self.assertIn(DONE_TEXT, status)
            self.assertNotIn(EXAMPLE, sb.cli("active").stdout)
            cleaned = sb.action("cleanup.sh", EXAMPLE)
            self.assertEqual(cleaned.returncode, EXIT_OK, cleaned.stderr)
            self.assertFalse(worktree.exists())
            self.assertEqual(sb.action("cleanup.sh", EXAMPLE).returncode, EXIT_OK)

    def test_argument_wins_over_inherited_variables(self):
        """Variables of another record or store, as a nested run inherits them, are dropped."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            sb.edit(f"{EXAMPLE}/card.md", "services: []", f"services: [{SERVICE}]")
            outer = sb.base / "outer"
            stale = {"SVOD_ACTION": "checks", "SVOD_ID": "work/tasks/outer",
                     "SVOD_SUBJECT_PATH": str(outer / "work/tasks/outer"),
                     "SVOD_SERVICES": "ghost", "SVOD_PIPELINE": "feature",
                     "SVOD_SERVICE_APP": str(outer / "nowhere"), "SVOD_FM_STATUS": "done"}
            started = sb.action("start-task.sh", EXAMPLE, SVOD_ROOT=str(outer), **stale)
            self.assertEqual(started.returncode, EXIT_OK, started.stderr)
            self.assertTrue((sb.base / WORKTREE / ".git").exists())
            self.assertEqual(sb.git(sb.base / WORKTREE, "branch", "--show-current").strip(),
                             BRANCH)
            checked = sb.action("checks.sh", EXAMPLE, "--check",
                                SVOD_ROOT=str(sb.store), **stale)
            self.assertNotEqual(checked.returncode, EXIT_OK)
            self.assertIn(f"not checked yet: run bash profile/actions/checks.sh {EXAMPLE}",
                          checked.stdout)

    def test_store_inside_its_service(self):
        """The worktree goes next to the service checkout; work.yaml holds a relative path."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            store = scaffold(sb.service / "store", "standard")
            sb.write("svod.yaml", (store / "svod.yaml").read_text(encoding=ENCODING)
                     + "services:\n  app: ..\n", base=store)
            sb.edit(f"../{SERVICE}/store/{EXAMPLE}/card.md", "services: []",
                    f"services: [{SERVICE}]")
            started = sb.action("start-task.sh", EXAMPLE, cwd=store)
            self.assertEqual(started.returncode, EXIT_OK, started.stderr)
            self.assertTrue((sb.base / WORKTREE / ".git").exists())
            work = (store / EXAMPLE / "work.yaml").read_text(encoding=ENCODING)
            self.assertEqual(work, f"{SERVICE}: ../../{WORKTREE}\n")

    def test_check_mode_without_services_passes(self):
        """--check of a record naming no services exits 0 and says so; a full run refuses."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            checked = sb.action("checks.sh", EXAMPLE, "--check")
            self.assertEqual(checked.returncode, EXIT_OK, checked.stderr)
            self.assertIn(NO_SERVICES, checked.stdout)
            self.assertFalse((sb.store / EXAMPLE / "checks.log").exists())
            self.assertNotEqual(sb.action("checks.sh", EXAMPLE).returncode, EXIT_OK)

    def test_hotfix_skips_the_contract_and_its_approval(self):
        """kind: hotfix needs a cause, then goes from questions straight to the worktrees."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            card = (sb.store / EXAMPLE / "card.md").read_text(encoding=ENCODING)
            card = card.replace("kind: task", "kind: hotfix").replace("services: []",
                                                                      "services: [app]")
            card = card.replace(ARCHIVED, OPEN)
            sb.write(f"{HOTFIX}/card.md", card)
            sb.write(f"{HOTFIX}/questions.md", "none\n")
            status = sb.cli("status", HOTFIX).stdout
            self.assertIn(CAUSE_STEP, status)
            sb.edit(f"{HOTFIX}/card.md", "parent:", "cause: incident 42\nparent:")
            status = sb.cli("status", HOTFIX).stdout
            self.assertIn(IMPLEMENT_STEP, status)
            self.assertNotIn(FROZEN, status)

    def test_research_outcome_asks_for_its_target(self):
        """outcome: knowledge asks for the knowledge document."""
        with TemporaryDirectory() as temp:
            sb = StandardStore(temp)
            sb.write(f"{RESEARCH}/card.md",
                     "---\ntype: card\nparent:\ntags: []\noutcome: knowledge\nstatus: open\n---\n")
            for name in ("question.md", "findings.md"):
                sb.write(f"{RESEARCH}/{name}", "# x\n")
            self.assertIn(KNOWLEDGE_STEP, sb.cli("status", RESEARCH).stdout)
            sb.edit(f"{RESEARCH}/card.md", "outcome:", "knowledge: knowledge/cache.md\noutcome:")
            self.assertIn("status: done in card.md of the research",
                          sb.cli("status", RESEARCH).stdout)


class StandardTemplateFilesTest(unittest.TestCase):
    def test_locales_share_keys_and_placeholders(self):
        """The en and ru texts of the template have the same keys and placeholders."""
        en, ru = (read_locale_file(TEMPLATE / "profile" / "locale" / f"{n}.yaml") for n in LOCALES)
        self.assertEqual(set(en), set(ru))
        self.assertEqual({k: placeholders(v) for k, v in en.items()},
                         {k: placeholders(v) for k, v in ru.items()})

    def test_skills_agents_and_actions_stay_short_and_described(self):
        """Skills up to 250 words, AGENTS.md up to 150, every action opens with its description."""
        for name in SKILLS:
            with self.subTest(skill=name):
                self.assertLessEqual(words(TEMPLATE / "skills" / name / "SKILL.md"), SKILL_WORDS)
        self.assertLessEqual(words(TEMPLATE / "AGENTS.md"), AGENTS_WORDS)
        for name in ACTIONS:
            with self.subTest(action=name):
                first = (TEMPLATE / "profile" / "actions" / name).read_text(
                    encoding=ENCODING).splitlines()[0]
                self.assertRegex(first, re.compile(r"^# [A-Z].{20,}"))


if __name__ == "__main__":
    unittest.main()
