"""svod record new makes a record from the skeletons; svod next prints the position in one line."""
import json
import os
import shutil
import unittest
from tempfile import TemporaryDirectory

from support import (ENCODING, EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, PYTHONPATH_ENV, child_env,
                     core_text)
from test_standard_template import SERVICE, StandardStore

from svod import keys
from svod.frontmatter import read_frontmatter
from svod.records import fill, split_list, yaml_list, yaml_scalar

TASK = "work/tasks/login"
HOTFIX = "work/tasks/hot"
FEATURE = "work/features/greet"
PARENT = "work/features/greet"
RECORDS = "profile/records"
SKELETONS = {"task": ("card.md", "contract.md", "questions.md"),
             "feature": ("brief.md", "card.md", "questions.md"),
             "project": ("card.md", "questions.md", "vision.md"),
             "research": ("card.md", "question.md", "questions.md")}
ROOTS = {"task": "work/tasks", "feature": "work/features", "project": "work/projects",
         "research": "work/research"}
NEXT_STEP_PREFIX = "Next step: "
SKILL_PREFIX = "Step skill: "
RUN_PREFIX = "Run: "
FIELDS = ("id", "step", "text", "skill", "action", "run")


def frontmatter(sb, record):
    """Frontmatter of card.md of a record."""
    return read_frontmatter(sb.store / record / "card.md")


def status_lines(text):
    """(next-step text, skill, run command) of a text status block, each None when absent."""
    found = {NEXT_STEP_PREFIX: None, SKILL_PREFIX: None, RUN_PREFIX: None}
    for line in (raw.strip() for raw in text.splitlines()):
        for prefix in found:
            if line.startswith(prefix):
                found[prefix] = line[len(prefix):]
    step = found[NEXT_STEP_PREFIX]
    return (step[:-1] if step else None), found[SKILL_PREFIX], found[RUN_PREFIX]


class RecordNewTest(unittest.TestCase):
    """The record of each pipeline of the standard template, its frontmatter and its refusals."""

    def setUp(self):
        """A standard store with a service next to it."""
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = StandardStore(temp.name)

    def new(self, *args):
        """svod record new with the arguments."""
        return self.sb.cli("record", "new", *args)

    def test_every_pipeline_gets_its_skeletons(self):
        """The files of profile/records/<pipeline>/ land in the root of the pipeline's provider."""
        for pipeline, files in SKELETONS.items():
            with self.subTest(pipeline=pipeline):
                made = self.new(pipeline, "first")
                self.assertEqual(made.returncode, EXIT_OK, made.stderr)
                record = self.sb.store / ROOTS[pipeline] / "first"
                self.assertEqual(tuple(sorted(p.name for p in record.iterdir())), files)
                self.assertEqual((record / "questions.md").read_text(encoding=ENCODING),
                                 "none\n")
                fm = read_frontmatter(record / "card.md")
                self.assertEqual((fm["type"], fm["kind"], fm["status"]),
                                 ("card", pipeline, "open"))
                self.assertNotIn("{", (record / "card.md").read_text(encoding=ENCODING))
                self.assertIn(f"{ROOTS[pipeline]}/first", made.stdout)
        validate = self.sb.cli("validate")
        self.assertEqual(validate.returncode, EXIT_OK, validate.stdout + validate.stderr)

    def test_options_land_in_the_frontmatter(self):
        """kind, parent, services, tags, key; the record validates and stays at its first step."""
        made = self.new("task", "login", "--kind", "hotfix", "--parent", PARENT,
                        "--services", "app, web", "--tags", "a,b", "--key", "PROJ-7")
        self.assertEqual(made.returncode, EXIT_OK, made.stderr)
        fm = frontmatter(self.sb, TASK)
        self.assertEqual((fm["kind"], fm["parent"], fm["services"], fm["tags"], fm["key"]),
                         ("hotfix", PARENT, ["app", "web"], ["a", "b"], "PROJ-7"))
        bare = self.new("task", "bare")
        self.assertEqual(bare.returncode, EXIT_OK, bare.stderr)
        fm = frontmatter(self.sb, "work/tasks/bare")
        self.assertEqual((fm["kind"], fm["parent"], fm["services"], fm["key"]),
                         ("task", None, [], None))
        card = (self.sb.store / "work/tasks/bare/card.md").read_text(encoding=ENCODING)
        self.assertIn("\nkey:\n", card)
        self.assertEqual(self.sb.cli("validate").returncode, EXIT_OK)
        nxt = json.loads(self.sb.cli("next", "work/tasks/bare", "--format", "json").stdout)
        self.assertEqual(nxt["step"], "card")
        status = self.sb.cli("status", "work/tasks/bare").stdout
        self.assertIn("name the services in card.md", status)
        self.assertIn("- services named", status)

    def test_existing_record_is_refused(self):
        """A second record new of the same name exits 1 and changes nothing."""
        self.assertEqual(self.new("task", "login").returncode, EXIT_OK)
        card = self.sb.store / TASK / "card.md"
        card.write_text("mine\n", encoding=ENCODING)
        again = self.new("task", "login", "--kind", "hotfix")
        self.assertEqual(again.returncode, EXIT_FINDINGS)
        self.assertEqual(again.stderr.strip(),
                         core_text(keys.RECORD_EXISTS, path=TASK))
        self.assertEqual(card.read_text(encoding=ENCODING), "mine\n")

    def test_empty_directory_is_filled(self):
        """An empty directory is no record yet."""
        (self.sb.store / TASK).mkdir(parents=True)
        made = self.new("task", "login")
        self.assertEqual(made.returncode, EXIT_OK, made.stderr)
        self.assertTrue((self.sb.store / TASK / "card.md").is_file())

    def test_refusals(self):
        """Unknown pipeline, a name that is no directory name, a pipeline without skeletons."""
        unknown = self.new("story", "x")
        self.assertEqual(unknown.returncode, EXIT_USAGE)
        self.assertIn("story", unknown.stderr)
        for name in ("a/b", ".hidden", "two words", ""):
            with self.subTest(name=name):
                bad = self.new("task", name)
                self.assertEqual(bad.returncode, EXIT_USAGE)
                self.assertIn(core_text(keys.RECORD_BAD_NAME, name=name), bad.stderr)
        shutil.rmtree(self.sb.store / RECORDS / "research")
        missing = self.new("research", "cache")
        self.assertEqual(missing.returncode, EXIT_USAGE)
        self.assertIn(f"{RECORDS}/research", missing.stderr)
        self.assertFalse((self.sb.store / "work/research/cache").exists())

    def test_fill_and_lists(self):
        """Placeholders are replaced, other braces kept; values quoted only when YAML needs it."""
        self.assertEqual(fill("a: {key}\nb: {x}  \n# {name}\n", {"key": "", "name": "n"}),
                         "a:\nb: {x}  \n# n\n")
        self.assertEqual(split_list(" a, ,b ,"), ["a", "b"])
        self.assertEqual(yaml_list([]), "[]")
        self.assertEqual(yaml_list(["app", "my app"]), '[app, "my app"]')
        self.assertEqual(yaml_scalar("work/features/x"), "work/features/x")
        self.assertEqual(yaml_scalar("a: b"), '"a: b"')

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "bash actions")
    def test_start_task_makes_the_record_with_record_new(self):
        """start-task.sh without card.md runs svod record new, then makes the worktree; twice."""
        engine = {PYTHONPATH_ENV: child_env()[PYTHONPATH_ENV]}
        for _ in range(2):
            started = self.sb.action("start-task.sh", TASK, SVOD_SERVICES=SERVICE,
                                     SVOD_KEY="PROJ-9", **engine)
            self.assertEqual(started.returncode, EXIT_OK, started.stderr)
        fm = frontmatter(self.sb, TASK)
        self.assertEqual((fm["kind"], fm["services"], fm["key"]), ("task", [SERVICE], "PROJ-9"))
        self.assertTrue((self.sb.store / TASK / "contract.md").is_file())
        self.assertTrue((self.sb.base / f"{SERVICE}-task-login" / ".git").exists())


class NextTest(unittest.TestCase):
    """svod next renders the very position svod status shows, in one line or as JSON."""

    def setUp(self):
        """A standard store with a service next to it."""
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = StandardStore(temp.name)

    def assert_same(self, record):
        """next and status agree on the text, the skill and the run command; return the JSON."""
        status = self.sb.cli("status", record)
        line = self.sb.cli("next", record)
        data = self.sb.cli("next", record, "--format", "json")
        for result in (status, line, data):
            self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        fields = json.loads(data.stdout)
        self.assertEqual(tuple(fields), FIELDS)
        text, skill, run = status_lines(status.stdout)
        self.assertEqual((fields["text"], fields["run"]), (text, run and run.split(": ", 1)[-1]))
        self.assertEqual(skill, fields["skill"])
        self.assertEqual(len(line.stdout.splitlines()), 1)
        shown = core_text(keys.NEXT_RUN, command=run.split(": ", 1)[-1]) if run else text
        self.assertEqual(line.stdout.strip(), core_text(
            keys.NEXT_LINE_SKILL, id=record, text=shown, skill=fields["skill"]))
        return fields

    def test_next_step_text(self):
        """A task without services: the card step, its text and its skill."""
        self.assertEqual(self.sb.cli("record", "new", "task", "login").returncode, EXIT_OK)
        fields = self.assert_same(TASK)
        self.assertEqual((fields["id"], fields["step"], fields["skill"], fields["action"],
                          fields["run"]), (TASK, "card", "svod-task", None, None))

    def test_run_command_of_the_step_action(self):
        """A hotfix with a cause stands at implement: the line names svod do start-task."""
        made = self.sb.cli("record", "new", "task", "hot", "--kind", "hotfix",
                           "--services", SERVICE)
        self.assertEqual(made.returncode, EXIT_OK, made.stderr)
        self.sb.edit(f"{HOTFIX}/card.md", "status: open", "cause: incident 42\nstatus: open")
        fields = self.assert_same(HOTFIX)
        self.assertEqual((fields["step"], fields["action"], fields["run"]),
                         ("implement", "start-task", f"svod do start-task {HOTFIX}"))
        line = self.sb.cli("next", "hot").stdout.strip()
        self.assertEqual(line, f"{HOTFIX}: run svod do start-task {HOTFIX} (skill svod-task)")

    def test_feature_and_done(self):
        """A feature at its breakdown; a done record says the done text without a step."""
        self.assertEqual(self.sb.cli("record", "new", "feature", "greet").returncode, EXIT_OK)
        self.assertEqual(self.assert_same(FEATURE)["step"], "breakdown")
        self.sb.edit(f"{FEATURE}/card.md", "status: open", "status: done")
        data = json.loads(self.sb.cli("next", FEATURE, "--format", "json").stdout)
        self.assertEqual((data["step"], data["skill"], data["run"]), (None, None, None))
        self.assertTrue(data["text"])
        line = self.sb.cli("next", FEATURE).stdout.strip()
        self.assertEqual(line, core_text(keys.NEXT_LINE, id=FEATURE, text=data["text"]))

    def test_not_found(self):
        """A query matching nothing is the error of status, exit 2."""
        missing = self.sb.cli("next", "nothing-like-this")
        self.assertEqual(missing.returncode, EXIT_USAGE)
        self.assertEqual(missing.stdout, "")
        self.assertIn(core_text(keys.STATUS_NOT_FOUND, query="nothing-like-this"),
                      missing.stderr)


if __name__ == "__main__":
    unittest.main()

