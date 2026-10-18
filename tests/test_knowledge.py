"""Knowledge: the notes, their index between markers, add and note, matching and the hooks."""
import json
import os
import unittest

from support import isolated_env
from unittest import mock

from support import (ENCODING, EXIT_FINDINGS, EXIT_OK, StoreTestCase, TempStore,
                     core_text, doc)

from svod import hooks, keys, knowledge
from svod.config import load_config
from svod.errors import LoadError
from svod.yamlio import dump_yaml, read_yaml

# An agent context with the session summary off, knowledge left at its default.
QUIET_CONTEXT = {"agent_context": {"session_summary": False, "prompt_positions": False,
                                   "approval_notice": False}}
PROFILE_CONFIG = "profile_config"

DIRECTORY = "knowledge"
DATE_OLD = "2026-01-10"
DATE_NEW = "2026-03-05"
WORK = "migration-plan"
OTHER_WORK = "frontend-polish"
OUTSIDE = "Hand-written text outside the markers."
SUMMARY_MODE = "profile_config:\n  agent_context:\n    session_start: summary\n"


def note_doc(title, tags, date, status="current", body="First line.\n", source=""):
    """Markdown of a knowledge note."""
    return (f"---\ntitle: {title}\ntags: [{', '.join(tags)}]\nsource: {source}\n"
            f"date: {date}\nstatus: {status}\n---\n\n# {title}\n\n{body}")


class KnowledgeFilesTest(StoreTestCase):
    """Entries, the index, add and note in a store without git."""

    def write_notes(self):
        """An old current note, a new current one and a superseded one."""
        self.sb.write(f"{DIRECTORY}/retries.md",
                      note_doc("Retries", ["api", "Net"], DATE_OLD, body="Use backoff.\n"))
        self.sb.write(f"{DIRECTORY}/db/vacuum.md",
                      note_doc("Vacuum", ["db"], DATE_NEW, body="\nTune autovacuum.\nMore.\n",
                               source="work/research/pg"))
        self.sb.write(f"{DIRECTORY}/old-vacuum.md",
                      note_doc("Old vacuum", ["db"], DATE_OLD, status="superseded"))

    def test_entries_skip_the_index_and_sort_by_date(self):
        """Every note under the directory, INDEX.md skipped, newest first, tags lower-cased."""
        self.write_notes()
        self.sb.write(f"{DIRECTORY}/{knowledge.INDEX_FILE}", "# Knowledge\n")
        found = knowledge.entries(self.sb.store)
        self.assertEqual(["Vacuum", "Old vacuum", "Retries"], [e.title for e in found])
        self.assertEqual(("api", "net"), found[-1].tags)
        self.assertEqual("knowledge/db/vacuum.md", found[0].rel)
        self.assertEqual("Tune autovacuum.", found[0].lead)
        self.assertEqual("work/research/pg", found[0].source)

    def test_readme_and_files_without_note_fields_are_not_notes(self):
        """README.md and a file naming neither title nor tags stay out of the index and matching."""
        self.write_notes()
        self.sb.write(f"{DIRECTORY}/README.md", "---\ntitle: About\ntags: [db]\n---\n# About\n")
        self.sb.write(f"{DIRECTORY}/plain.md", "# Plain\n\nNo frontmatter.\n")
        self.sb.write(f"{DIRECTORY}/dated.md", "---\ndate: 2026-05-01\n---\n# Dated\n")
        self.sb.write(f"{DIRECTORY}/tagged.md", "---\ntags: [db]\n---\n# Tagged\n\nKept.\n")
        found = [e.title for e in knowledge.entries(self.sb.store)]
        self.assertEqual(["Vacuum", "Old vacuum", "Retries", "Tagged"], found)
        index = knowledge.index_text(self.sb.store)
        for name in ("About", "Plain", "Dated"):
            self.assertNotIn(name, index)
        self.assertNotIn("About", "\n".join(knowledge.matching(self.sb.store, ["db"], 20)))

    def test_index_is_written_between_markers_and_rebuilt(self):
        """Generated table between the markers; text outside kept; a second run changes nothing."""
        self.write_notes()
        path, changed = knowledge.write_index(self.sb.store)
        self.assertTrue(changed)
        text = path.read_text(encoding=ENCODING)
        self.assertIn(knowledge.MARKER_BEGIN, text)
        self.assertIn(knowledge.MARKER_END, text)
        self.assertIn("| [Vacuum](db/vacuum.md) | db | work/research/pg | 2026-03-05 | current |",
                      text)
        self.assertLess(text.index("Vacuum"), text.index("Retries"))
        self.assertEqual(text.split(knowledge.MARKER_BEGIN + "\n")[1].split(
            "\n" + knowledge.MARKER_END)[0], knowledge.index_text(self.sb.store))
        self.assertEqual((path, False), knowledge.write_index(self.sb.store))
        path.write_text(f"# Our knowledge\n\n{OUTSIDE}\n\n{knowledge.MARKER_BEGIN}\nstale\n"
                        f"{knowledge.MARKER_END}\n\nFooter.\n", encoding=ENCODING)
        self.sb.write(f"{DIRECTORY}/new.md", note_doc("Newest", ["x"], "2026-04-01"))
        self.assertTrue(knowledge.write_index(self.sb.store)[1])
        text = path.read_text(encoding=ENCODING)
        self.assertTrue(text.startswith(f"# Our knowledge\n\n{OUTSIDE}\n"))
        self.assertTrue(text.endswith(f"{knowledge.MARKER_END}\n\nFooter.\n"))
        self.assertNotIn("stale", text)
        self.assertLess(text.index("Newest"), text.index("Vacuum"))

    def test_index_markers_are_appended_to_a_file_without_them(self):
        """A file without the markers keeps its text and gets the block at its end."""
        path = self.sb.write(f"{DIRECTORY}/{knowledge.INDEX_FILE}", f"# Index\n\n{OUTSIDE}\n")
        knowledge.write_index(self.sb.store)
        text = path.read_text(encoding=ENCODING)
        self.assertTrue(text.startswith(f"# Index\n\n{OUTSIDE}\n\n{knowledge.MARKER_BEGIN}\n"))

    def test_add_creates_frontmatter_from_arguments_and_heading(self):
        """A file without frontmatter gets one: title from the first heading, tags, source."""
        source = self.sb.write("draft.md", "# Retry policy\n\nUse exponential backoff.\n")
        path = knowledge.add(self.sb.store, source, "API, net", source="work/research/x",
                             date=DATE_NEW)
        self.assertEqual(self.sb.store / DIRECTORY / "retry-policy.md", path)
        entry = knowledge.entries(self.sb.store)[0]
        self.assertEqual(("Retry policy", ("api", "net"), "work/research/x", DATE_NEW, "current"),
                         (entry.title, entry.tags, entry.source, entry.date, entry.status))
        self.assertEqual("Use exponential backoff.", entry.lead)
        with self.assertRaises(FileExistsError):
            knowledge.add(self.sb.store, source, ["api"])
        titled = knowledge.add(self.sb.store, source, ["api"], title="Backoff")
        self.assertEqual("backoff.md", titled.name)

    def test_add_keeps_a_complete_frontmatter_byte_for_byte(self):
        """A file whose frontmatter already holds every field and the tags is copied as is."""
        text = note_doc("Ready", ["db"], DATE_OLD)
        source = self.sb.write("ready.md", text)
        path = knowledge.add(self.sb.store, source, ["db"])
        self.assertEqual(text, path.read_text(encoding=ENCODING))
        merged = knowledge.add(self.sb.store, self.sb.write("more.md", note_doc(
            "More", ["db"], DATE_OLD)), ["api"])
        self.assertEqual(("db", "api"), knowledge.read_entry(self.sb.store, merged).tags)

    def test_note_creates_a_slugged_file(self):
        """A note of a text is named after its title, unicode kept."""
        path = knowledge.note(self.sb.store, "Vacuum big tables nightly.", ["db"],
                              "Вакуум Postgres", date=DATE_NEW)
        self.assertEqual("вакуум-postgres.md", path.name)
        entry = knowledge.read_entry(self.sb.store, path)
        self.assertEqual(("Вакуум Postgres", ("db",), "Vacuum big tables nightly."),
                         (entry.title, entry.tags, entry.lead))
        with self.assertRaises(FileExistsError):
            knowledge.note(self.sb.store, "again", ["db"], "Вакуум Postgres")

    def test_matching_by_tags_status_and_limit(self):
        """Current notes sharing a tag, newest first, cut at the limit; superseded never."""
        self.write_notes()
        self.assertEqual(
            ["- Vacuum (knowledge/db/vacuum.md): Tune autovacuum.",
             "- Retries (knowledge/retries.md): Use backoff."],
            knowledge.matching(self.sb.store, ["DB", "net"], 20))
        self.assertEqual(1, len(knowledge.matching(self.sb.store, ["db", "api"], 1)))
        self.assertEqual([], knowledge.matching(self.sb.store, ["other"], 20))
        self.assertEqual([], knowledge.matching(self.sb.store, [], 20))
        self.assertNotIn("Old vacuum", "\n".join(knowledge.matching(self.sb.store, ["db"], 20)))

    def test_config_keys(self):
        """knowledge.dir and knowledge.limit_lines are read and checked."""
        config = self.sb.store / "svod.yaml"
        base = config.read_text(encoding=ENCODING)
        self.assertEqual(("knowledge", 20), (load_config(self.sb.store).knowledge_dir,
                                             load_config(self.sb.store).knowledge_limit))
        config.write_text(base + "knowledge: {dir: kb, limit_lines: 3}\n", encoding=ENCODING)
        loaded = load_config(self.sb.store)
        self.assertEqual(("kb", 3), (loaded.knowledge_dir, loaded.knowledge_limit))
        config.write_text(base + "knowledge: {limit_lines: 0, depth: 1}\n", encoding=ENCODING)
        with self.assertRaises(LoadError) as caught:
            load_config(self.sb.store)
        self.assertEqual(2, len(caught.exception.errors))

    def test_cli(self):
        """add, note, list and index through the command line."""
        self.sb.write("draft.md", "# Retry policy\n\nUse backoff.\n")
        out = self.sb.cli("knowledge", "add", "draft.md", "--tags", "api,net", "--source", "w/1")
        self.assertEqual(EXIT_OK, out.returncode, out.stderr)
        self.assertIn("knowledge/retry-policy.md", out.stdout)
        self.assertIn("knowledge/INDEX.md", out.stdout)
        out = self.sb.cli("knowledge", "note", "Tune autovacuum.", "--tags", "db",
                          "--title", "Vacuum")
        self.assertEqual(EXIT_OK, out.returncode, out.stderr)
        out = self.sb.cli("knowledge", "note", "again", "--tags", "db", "--title", "Vacuum")
        self.assertEqual(EXIT_FINDINGS, out.returncode)
        listed = self.sb.cli("knowledge", "list", "--tags", "db").stdout
        self.assertIn("Vacuum (knowledge/vacuum.md) [db]", listed)
        self.assertNotIn("Retry policy", listed)
        self.assertIn("Retry policy", self.sb.cli("knowledge", "list").stdout)
        out = self.sb.cli("knowledge", "index")
        self.assertEqual(EXIT_OK, out.returncode)
        self.assertIn("Up to date", out.stdout)
        self.assertNotEqual(EXIT_OK, self.sb.cli("knowledge", "add", "absent.md",
                                                 "--tags", "x").returncode)


class KnowledgeHookTest(unittest.TestCase):
    """Session start (summary mode) and prompt hooks add the notes sharing the tags of the work."""

    def setUp(self):
        """Store with two tagged open notes of the note pipeline and two knowledge notes."""
        self.sb = TempStore()
        self.addCleanup(self.sb.cleanup)
        patcher = mock.patch.dict(os.environ, isolated_env(**self.sb.env), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(hooks.PROJECT_ENV, None)
        self.base = (self.sb.store / "svod.yaml").read_text(encoding=ENCODING)
        (self.sb.store / "svod.yaml").write_text(self.base + SUMMARY_MODE, encoding=ENCODING)
        self.sb.write(f"notes/{WORK}.md", doc("note", review="2000-01-01", tags="[db]"))
        self.sb.write(f"notes/{OTHER_WORK}.md", doc("note", review="2000-01-01", tags="[ui]"))
        self.sb.write(f"{DIRECTORY}/vacuum.md", note_doc("Vacuum", ["db"], DATE_NEW,
                                                         body="Tune autovacuum.\n"))
        self.sb.write(f"{DIRECTORY}/old.md", note_doc("Old vacuum", ["db"], DATE_OLD,
                                                      status="superseded"))
        self.sb.write(f"{DIRECTORY}/css.md", note_doc("Css", ["ui"], DATE_OLD,
                                                      body="Use tokens.\n"))
        self.sb.init_git()

    def context(self, event_name, prompt=None):
        """additionalContext of a hook answer, or None."""
        event = {"cwd": str(self.sb.store)}
        if prompt is not None:
            event["prompt"] = prompt
        found = hooks.answer(event_name, event)
        return json.loads(found)[hooks.OUTPUT][hooks.CONTEXT] if found else None

    def set_knowledge(self, enabled):
        """Switch profile_config.agent_context.knowledge, session start giving the summary."""
        setting = f"{SUMMARY_MODE}    knowledge: {str(enabled).lower()}\n"
        (self.sb.store / "svod.yaml").write_text(self.base + setting, encoding=ENCODING)

    def test_session_start_adds_notes_of_every_open_work(self):
        """The notes of the tags of all open works, superseded ones left out."""
        text = self.context(hooks.EVENT_SESSION_START)
        self.assertIn("- Vacuum (knowledge/vacuum.md): Tune autovacuum.", text)
        self.assertIn("- Css (knowledge/css.md): Use tokens.", text)
        self.assertNotIn("Old vacuum", text)

    def test_prompt_adds_notes_of_the_named_work_only(self):
        """A prompt naming one work gets the notes of its tags only; none without a name."""
        text = self.context(hooks.EVENT_PROMPT, f"what is next for {WORK}?")
        self.assertIn("Vacuum (knowledge/vacuum.md)", text)
        self.assertNotIn("Css", text)
        self.assertIsNone(self.context(hooks.EVENT_PROMPT, "hello there"))

    def test_session_start_without_the_summary(self):
        """With the summary off (knowledge on by default) session start gives the notes alone;
        with the summary on they follow it."""
        head = core_text(keys.HOOK_KNOWLEDGE_HEAD)
        text = self.context(hooks.EVENT_SESSION_START)
        self.assertGreater(text.index(head), 0)
        data = read_yaml(self.sb.store / "svod.yaml")
        data[PROFILE_CONFIG] = QUIET_CONTEXT
        (self.sb.store / "svod.yaml").write_text(dump_yaml(data), encoding=ENCODING)
        text = self.context(hooks.EVENT_SESSION_START)
        self.assertTrue(text.startswith(head), text)
        self.assertIn("- Vacuum (knowledge/vacuum.md): Tune autovacuum.", text)

    def test_switched_off(self):
        """agent_context.knowledge: false adds nothing; true is the default behaviour."""
        self.set_knowledge(False)
        self.assertNotIn("Vacuum", self.context(hooks.EVENT_SESSION_START) or "")
        self.assertNotIn("Vacuum", self.context(hooks.EVENT_PROMPT, f"look at {WORK}") or "")
        self.set_knowledge(True)
        self.assertIn("Vacuum", self.context(hooks.EVENT_PROMPT, f"look at {WORK}"))


if __name__ == "__main__":
    unittest.main()
