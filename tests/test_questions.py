"""Questions before work: the file format, the questions_answered gate, svod ask and answer."""
import datetime as dt
import json
import unittest

from support import ENCODING, EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, ME, core_text
from test_relations import FEATURES, RESEARCH, WorkStoreTestCase, write_work

from svod import keys
from svod.approval import MARK_AT
from svod.gates import Status
from svod.questions import (HUMAN_MARK_FILE, MARK_SHA, answered_text, asked_text,
                            fresh_human_mark, human_mark_path, parse_questions, prompt_sha,
                            write_human_mark)

PASS, FAIL = Status.PASS, Status.FAIL
WORK = f"{RESEARCH}/r1"
FILE = f"{WORK}/questions.md"
TWO = """# Questions

## Q: Which database?
Context of the question.

## Q: Who owns the API?
A: the platform team
  by: someone, at: 2026-10-01, prompt: 0123456789ab
"""
PROMPT = "Postgres, and the platform team owns it"
WINDOW_MINUTES = 10
STALE = dt.timedelta(minutes=WINDOW_MINUTES + 1)


class ParseTest(unittest.TestCase):
    """The format of the questions file."""

    def test_parse(self):
        """Questions in order with their answers; none; nothing."""
        found = parse_questions(TWO)
        self.assertEqual([(q.text, q.answer) for q in found.items],
                         [("Which database?", ""), ("Who owns the API?", "the platform team")])
        self.assertEqual(len(found.unanswered), 1)
        self.assertTrue(parse_questions("  none\n").none)
        self.assertFalse(parse_questions("# Questions\n").items)
        self.assertEqual(parse_questions("## Q: x\nA:   \n").items[0].answer, "")

    def test_answered_text(self):
        """A new answer goes after the section; an existing one is replaced with its by line."""
        by = "  by: me, at: 2026-10-17, prompt: abc"
        first = answered_text(TWO, 1, "Postgres", by)
        self.assertIn("Context of the question.\nA: Postgres\n" + by + "\n\n## Q: Who", first)
        second = answered_text(first, 2, "nobody", by)
        self.assertNotIn("platform team", second)
        self.assertNotIn("someone", second)
        self.assertTrue(second.endswith(f"A: nobody\n{by}\n"))
        self.assertEqual([q.answer for q in parse_questions(second).items],
                         ["Postgres", "nobody"])

    def test_asked_text(self):
        """A question goes after a blank line, its context under it; none or no file: afresh."""
        added = asked_text(TWO, "Which cache?", "Redis or none")
        self.assertTrue(added.startswith(TWO.rstrip() + "\n\n## Q: Which cache?\nRedis or none\n"))
        self.assertEqual([q.text for q in parse_questions(added).items],
                         ["Which database?", "Who owns the API?", "Which cache?"])
        for text in (None, "none\n", "  NONE \n"):
            with self.subTest(text=text):
                self.assertEqual(asked_text(text, "Which cache?"), "## Q: Which cache?\n")


class QuestionsGateTest(WorkStoreTestCase):
    """questions_answered over the file of the subject."""

    def evaluate(self, text=None, params=None):
        """Gate result for the research work with the questions file text, None for no file."""
        write_work(self.sb, WORK)
        path = self.sb.store / FILE
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding=ENCODING)
        return self.run_gate("questions_answered", params, "research", WORK)

    def test_reasons(self):
        """missing, empty, unanswered with the count, none and every question answered."""
        answered = TWO.replace("Context of the question.", "A: Postgres")
        cases = (
            (None, FAIL, {"total": 0, "count": 0, "reason": "missing"}),
            ("# Questions\n", FAIL, {"total": 0, "count": 0, "reason": "empty"}),
            (TWO, FAIL, {"total": 2, "count": 1, "reason": "unanswered"}),
            ("none\n", PASS, {"total": 0, "count": 0}),
            (answered, PASS, {"total": 2, "count": 0}),
        )
        for text, status, facts in cases:
            with self.subTest(text=text):
                result = self.evaluate(text)
                self.assertEqual((result.status, result.facts), (status, facts))

    def test_file_param(self):
        """The file param names another file under the subject."""
        write_work(self.sb, WORK)
        self.sb.write(f"{WORK}/ask.md", "none\n")
        result = self.run_gate("questions_answered", {"file": "ask.md"}, "research", WORK)
        self.assertEqual(result.status, PASS)


class AnswerTest(WorkStoreTestCase):
    """svod answer writes the answer only with a fresh human mark."""

    def setUp(self):
        """Store under git with a research work holding two questions."""
        super().setUp()
        write_work(self.sb, f"{FEATURES}/login")
        write_work(self.sb, WORK)
        self.sb.write(FILE, TWO)
        self.sb.init_git(remote=False)

    def answer(self, *args):
        """Run svod answer for the research work."""
        return self.sb.cli("answer", "r1", *args)

    def mark(self, at=None, sha=None):
        """Leave the human mark for the prompt, optionally at another time or with another sha."""
        path = write_human_mark(self.sb.store, PROMPT, at)
        if sha is not None:
            data = json.loads(path.read_text(encoding=ENCODING))
            path.write_text(json.dumps({**data, MARK_SHA: sha}), encoding=ENCODING)
        return path

    def text(self):
        """Current questions file."""
        return (self.sb.store / FILE).read_text(encoding=ENCODING)

    def test_contract(self):
        """The mark lies in the git common directory, holds the time and the prompt digest."""
        path = self.mark()
        self.assertEqual(path.name, HUMAN_MARK_FILE)
        self.assertEqual(path, human_mark_path(self.sb.store))
        self.assertEqual(path.parent, (self.sb.store / ".git").resolve())
        data = json.loads(path.read_text(encoding=ENCODING))
        self.assertEqual(data[MARK_SHA], prompt_sha(PROMPT))
        self.assertIsNotNone(dt.datetime.fromisoformat(data[MARK_AT]).tzinfo)
        self.assertIsNotNone(fresh_human_mark(self.sb.store, WINDOW_MINUTES))

    def test_without_mark(self):
        """No mark, a stale one or one without a sha256 digest: refused, nothing written."""
        out = self.answer("--q", "1", "Postgres")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn(core_text(keys.ANSWER_NO_MARK), out.stderr)
        stale = dt.datetime.now().astimezone() - STALE
        for at, sha in ((stale, None), (None, "not-a-digest")):
            with self.subTest(at=at, sha=sha):
                self.mark(at, sha)
                out = self.answer("--q", "1", "Postgres")
                self.assertEqual(out.returncode, EXIT_FINDINGS)
                self.assertIn(core_text(keys.ANSWER_NO_MARK), out.stderr)
        self.assertEqual(self.text(), TWO)

    def test_with_mark(self):
        """A fresh mark: the answer and the by line are written, and the gate passes."""
        self.mark()
        out = self.answer("--q", "1", "Postgres,", "version", "16")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        today = dt.date.today().isoformat()
        sha = prompt_sha(PROMPT)[:12]
        by = f"  by: {ME[0]}, at: {today}, prompt: {sha}"
        self.assertIn(f"A: Postgres, version 16\n{by}\n", self.text())
        self.assertIn(core_text(keys.ANSWER_DONE, number=1, file=FILE,
                                question="Which database?", by=ME[0], sha=sha), out.stdout)
        result = self.run_gate("questions_answered", None, "research", WORK)
        self.assertEqual(result.status, PASS)
        again = self.answer("--q", "2", "nobody")
        self.assertEqual(again.returncode, EXIT_OK, again.stderr)
        self.assertNotIn("platform team", self.text())

    def test_refusals(self):
        """No question with the number, no file, a subject not found."""
        self.mark()
        out = self.answer("--q", "3", "x")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn(core_text(keys.ANSWER_NO_QUESTION, file=FILE, number=3, count=2),
                      out.stderr)
        missing = self.sb.cli("answer", "login", "--q", "1", "x")
        self.assertEqual(missing.returncode, EXIT_FINDINGS)
        self.assertIn(core_text(keys.ANSWER_NO_FILE, file=f"{FEATURES}/login/questions.md"),
                      missing.stderr)
        unknown = self.sb.cli("answer", "nothing-like-this", "--q", "1", "x")
        self.assertEqual(unknown.returncode, EXIT_USAGE)
        self.assertEqual(self.text(), TWO)


class AskTest(WorkStoreTestCase):
    """svod ask adds the agent's questions; --none says there is nothing to ask."""

    def setUp(self):
        """Store with a research work without a questions file."""
        super().setUp()
        write_work(self.sb, WORK)

    def ask(self, *args):
        """Run svod ask for the research work."""
        return self.sb.cli("ask", "r1", *args)

    def text(self):
        """Current questions file."""
        return (self.sb.store / FILE).read_text(encoding=ENCODING)

    def gate(self):
        """questions_answered over the research work."""
        return self.run_gate("questions_answered", None, "research", WORK)

    def test_adds_questions(self):
        """The file is created, each question appended with its context; the gate counts them."""
        first = self.ask("Which", "database?", "--context", "Postgres  or\nSQLite")
        self.assertEqual(first.returncode, EXIT_OK, first.stderr)
        self.assertEqual(self.text(), "## Q: Which database?\nPostgres or SQLite\n")
        self.assertIn(core_text(keys.ASK_DONE, file=FILE, number=1, question="Which database?",
                                query="r1"), first.stdout)
        second = self.ask("Who owns the API?")
        self.assertEqual(second.returncode, EXIT_OK, second.stderr)
        self.assertIn(core_text(keys.ASK_DONE, file=FILE, number=2, question="Who owns the API?",
                                query="r1"), second.stdout)
        self.assertEqual(self.text(), "## Q: Which database?\nPostgres or SQLite\n\n"
                                      "## Q: Who owns the API?\n")
        result = self.gate()
        self.assertEqual((result.status, result.facts),
                         (FAIL, {"total": 2, "count": 2, "reason": "unanswered"}))

    def test_none(self):
        """--none writes none for no file or one without questions, and gives way to a question."""
        for before in (None, "# Questions\n"):
            with self.subTest(before=before):
                if before is not None:
                    self.sb.write(FILE, before)
                out = self.ask("--none")
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                self.assertIn(core_text(keys.ASK_NONE, file=FILE), out.stdout)
                self.assertEqual(self.text(), "none\n")
                self.assertEqual(self.gate().status, PASS)
        self.assertEqual(self.ask("Which cache?").returncode, EXIT_OK)
        self.assertEqual(self.text(), "## Q: Which cache?\n")
        refused = self.ask("--none")
        self.assertEqual(refused.returncode, EXIT_FINDINGS)
        self.assertIn(core_text(keys.ASK_HAS_QUESTIONS, file=FILE, count=1), refused.stderr)
        self.assertEqual(self.text(), "## Q: Which cache?\n")

    def test_refusals(self):
        """Empty, with --none, a context read as an answer or a heading, an unknown subject."""
        cases = (
            (("  ",), keys.ASK_EMPTY, {}),
            (("Which?", "--none"), keys.ASK_CONFLICT, {}),
            (("--none", "--context", "x"), keys.ASK_CONFLICT, {}),
            (("Which?", "--context", "A: yes"), keys.ASK_MISREAD, {"context": "A: yes"}),
            (("Which?", "--context", "## Q: other"), keys.ASK_MISREAD,
             {"context": "## Q: other"}),
        )
        for args, key, facts in cases:
            with self.subTest(args=args):
                out = self.ask(*args)
                self.assertEqual(out.returncode, EXIT_FINDINGS)
                self.assertIn(core_text(key, **facts), out.stderr)
        self.assertFalse((self.sb.store / FILE).exists())
        unknown = self.sb.cli("ask", "nothing-like-this", "Which?")
        self.assertEqual(unknown.returncode, EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
