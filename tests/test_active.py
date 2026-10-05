"""The active summary, its hook form and flag validation."""
import json
import unittest
from pathlib import Path

from support import (EXIT_OK, EXIT_USAGE, MAIN_BRANCH, OTHER_PEER, PEER, REMOTE,
                     SharedStoreTestCase, StoreTestCase, doc)

from svod.active import summarize
from svod.context import Context
from svod.loader import load_runtime
from svod.position import position
from svod.render import render_position
from svod.providers.openspec_change import DEFAULT_ARCHIVE, DEFAULT_ROOT, METADATA_FILE

CHANGES = Path(DEFAULT_ROOT)
ORDER = "active_order"
HDR_ACTIVE = "Your work in progress:"
HDR_IDLE = "Your work without progress:"
HDR_TEAM = "In progress for the team:"
HDR_NOTES = "Your open notes:"
HDR_TEAM_NOTES = "Team notes:"
STEP_BUILD = "start building in a workspace"
STEP_VERIFY = "run the mandatory cases, report in the change"
STEP_REVIEW = "decide whether to continue"
HDR_WORKTREE = "In progress in the checkout {dir}:"


def change(sb, name, key=None, progress=None, approved=True, archived=False):
    """Change with spec, design and approval; progress written when given."""
    root = (CHANGES / DEFAULT_ARCHIVE if archived else CHANGES) / name
    meta = ([f"ticket: {key}"] if key else []) + (["approved: yes"] if approved else [])
    sb.write(root / METADATA_FILE, "\n".join(meta) + "\n")
    sb.write(root / "specs" / "cap" / "spec.md", "# spec\n")
    sb.write(root / "design.md", "# design\n")
    if progress is not None:
        sb.write(root / "progress.txt", progress)


def line(name, keys, step):
    """Summary line of a task."""
    return f"  - {name} ({keys}) - {step}"


def section(lines, header):
    """Lines of a block after its header up to the next empty line."""
    if header not in lines:
        return None
    rest = lines[lines.index(header) + 1:]
    return rest[:rest.index("")] if "" in rest else rest


class ActiveSummaryTest(SharedStoreTestCase):
    """Grouping, collapsing, ordering and the hook form."""

    @classmethod
    def build(cls, sb):
        """Own and team changes and notes in a git store."""
        sb.write("svod.yaml", sb.store.joinpath("svod.yaml").read_text("utf-8")
                 + f"{ORDER}: [task, note]\n")
        sb.init_git()
        change(sb, "c-1", "tk-1", progress="2")
        change(sb, "c-2", "tk-2", progress="0")
        change(sb, "c-3", None, approved=False)
        change(sb, "c-9", "tk-9", archived=True)
        sb.write("notes/001 Mine.md", doc("note", review="2000-01-01"))
        sb.write("notes/002 Closed.md", doc("note", status="closed"))
        sb.write("notes/003 Archived.md", doc("note", status="archived"))
        sb.commit(message="mine")
        change(sb, "c-4", "tk-4")
        change(sb, "c-6", "tk-6")
        sb.write("notes/004 Theirs.md", doc("note", review="2000-01-01"))
        sb.commit(message="peer", author=PEER)
        change(sb, "c-5", "tk-5")
        sb.commit(message="other", author=OTHER_PEER)
        change(sb, "c-7", "tk-7", progress="1")
        cls.out = sb.cli("active")
        cls.out_all = sb.cli("active", "--all")
        cls.lines = cls.out.stdout.splitlines()
        cls.lines_all = cls.out_all.stdout.splitlines()

    def test_exit_codes(self):
        """The summary exits with zero."""
        for out in (self.out, self.out_all):
            self.assertEqual(out.returncode, EXIT_OK, out.stderr)

    def test_mine_groups(self):
        """In progress needs the gate to pass with a positive fact; the rest is idle."""
        self.assertEqual(section(self.lines, HDR_ACTIVE), [
            line("c-1", "tk-1", STEP_VERIFY),
            line("c-7", "tk-7", STEP_VERIFY),
        ])
        self.assertEqual(section(self.lines, HDR_IDLE), [
            line("c-2", "tk-2", STEP_VERIFY),
            line("c-3", "no key", "get the plan approved"),
        ])
        self.assertNotIn("c-9", self.out.stdout)

    def test_team_collapsed_and_expanded(self):
        """Team work is one line per pipeline by default, expanded with --all."""
        self.assertIn("In progress for the team: 3 (Another Peer - 1, Peer Person - 2)"
                      " · expand: svod active --all", self.lines)
        self.assertNotIn("c-4", self.out.stdout)
        self.assertEqual(section(self.lines_all, HDR_TEAM), [
            line("c-4", "tk-4", STEP_BUILD),
            line("c-5", "tk-5", STEP_BUILD),
            line("c-6", "tk-6", STEP_BUILD),
        ])

    def test_pipeline_headings_item_and_order(self):
        """The note pipeline uses its own headings and item, after the task pipeline."""
        self.assertEqual(section(self.lines, HDR_NOTES), [f"  - 001 Mine: {STEP_REVIEW}"])
        self.assertIn("Team notes: 1 (Peer Person - 1)", self.lines)
        self.assertEqual(section(self.lines_all, HDR_TEAM_NOTES),
                         [f"  - 004 Theirs: {STEP_REVIEW}"])
        self.assertLess(self.lines.index(HDR_ACTIVE), self.lines.index(HDR_NOTES))
        self.assertNotIn("Closed", self.out.stdout)
        self.assertNotIn("Archived", self.out.stdout)

    def test_hook(self):
        """--hook wraps the same text in SessionStart JSON with the status hint."""
        out = self.sb.cli("active", "--hook")
        self.assertEqual(out.returncode, EXIT_OK)
        payload = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "SessionStart")
        text = payload["additionalContext"]
        self.assertTrue(text.startswith(self.out.stdout.rstrip("\n")))
        self.assertTrue(text.endswith("svod status <query>"))

    def test_rule7_active_and_status_agree(self):
        """Each summary step is the status next step of the same subject."""
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale)
        pipeline = runtime.pipeline("task")
        summary = summarize(ctx, runtime.pipelines, show_all=True)
        for subject in pipeline.subject.impl.enumerate(ctx):
            if subject.archived:
                continue
            with self.subTest(change=subject.id):
                status = render_position(runtime.locale, position(ctx, pipeline, subject))
                step = next(s for s in status if s.startswith("  Next step: "))
                step = step.removeprefix("  Next step: ").removesuffix(".")
                item = next(s for s in summary if s.startswith(f"  - {subject.id} ("))
                self.assertTrue(item.endswith(f") - {step}"), item)


class ActiveWorktreeTest(SharedStoreTestCase):
    """Changes of the other checkouts of the store: a group per checkout, duplicates by it."""

    NEW = "store-TK-2_new"
    EDITED = "store-TK-1_edit"
    ARCHIVING = "store-ops_archive"
    CLEAN = "store-ops_clean"
    NOTE = "store-ops_note"

    @classmethod
    def build(cls, sb):
        """Master with c-1 and c-3; worktrees adding, editing, archiving a change or clean."""
        sb.init_git()
        change(sb, "c-1", "tk-1")
        change(sb, "c-3", "tk-3")
        sb.commit(message="master")
        sb.push()
        base = f"{REMOTE}/{MAIN_BRANCH}"
        paths = {}
        for name in (cls.NEW, cls.EDITED, cls.ARCHIVING, cls.CLEAN, cls.NOTE):
            paths[name] = sb.parent / name
            sb.git(sb.store, "worktree", "add", "-q", "-b", name, str(paths[name]), base)
        change(sb, "c-2", "tk-2", progress="1")
        (sb.store / CHANGES / "c-2").rename(paths[cls.NEW] / CHANGES / "c-2")
        sb.write("notes/005 Draft.md", doc("note", review="2000-01-01"), base=paths[cls.NOTE])
        sb.write(CHANGES / "c-1" / "progress.txt", "3", base=paths[cls.EDITED])
        sb.commit(paths[cls.EDITED], "progress")
        (paths[cls.ARCHIVING] / CHANGES / DEFAULT_ARCHIVE).mkdir(parents=True)
        sb.git(paths[cls.ARCHIVING], "mv", str(CHANGES / "c-3"), str(CHANGES / DEFAULT_ARCHIVE))
        cls.out = sb.cli("active")
        cls.lines = cls.out.stdout.splitlines()

    def test_group_per_worktree(self):
        """An untracked change and a committed edit show under their checkouts with their steps."""
        self.assertEqual(self.out.returncode, EXIT_OK, self.out.stderr)
        self.assertEqual(section(self.lines, HDR_WORKTREE.format(dir=self.NEW)),
                         [line("c-2", "tk-2", STEP_VERIFY)])
        self.assertEqual(section(self.lines, HDR_WORKTREE.format(dir=self.EDITED)),
                         [line("c-1", "tk-1", STEP_VERIFY)])
        self.assertEqual(section(self.lines, HDR_WORKTREE.format(dir=self.NOTE)),
                         [f"  - 005 Draft: {STEP_REVIEW}"])

    def test_duplicates_and_quiet_checkouts(self):
        """Changed or archived in a checkout: not in the root groups; clean checkouts are silent."""
        self.assertEqual(self.out.stdout.count("c-1 ("), 1)
        self.assertNotIn("c-3", self.out.stdout)
        self.assertNotIn(self.CLEAN, self.out.stdout)
        self.assertNotIn(self.ARCHIVING, self.out.stdout)
        self.assertNotIn(HDR_IDLE, self.lines)


class ActiveEdgeTest(StoreTestCase):
    """Empty summaries, missing identity and flag validation."""

    def test_empty_summary_prints_nothing(self):
        """No open work: empty output and exit 0, also in hook mode."""
        for args in (("active",), ("active", "--hook")):
            with self.subTest(args=args):
                out = self.sb.cli(*args)
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                self.assertEqual(out.stdout, "")

    def test_without_identity_everything_is_mine_with_a_warning(self):
        """Without any email team work is shown as own work, under a warning line."""
        self.sb.init_git(remote=False)
        change(self.sb, "c-4", "tk-4")
        self.sb.commit(message="peer", author=PEER)
        self.sb.git(self.sb.store, "config", "--unset", "user.email")
        out = self.sb.cli("active")
        self.assertTrue(out.stdout.startswith("Who you are is unknown"), out.stdout)
        self.assertIn(HDR_IDLE, out.stdout)
        self.assertNotIn(HDR_TEAM, out.stdout)

    def test_flags_outside_active_are_rejected(self):
        """--all and --hook belong to active only."""
        for args in (("status", "x", "--all"), ("--hook", "validate"), ("validate", "--all"),
                     ("status", "x", "--hook")):
            with self.subTest(args=args):
                out = self.sb.cli(*args)
                self.assertEqual(out.returncode, EXIT_USAGE)
                self.assertIn("unrecognized arguments", out.stderr)


if __name__ == "__main__":
    unittest.main()
