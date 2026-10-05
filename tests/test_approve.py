"""The approval mark, the approve command, line-wise field writing and texts by reason."""
import datetime as dt
import json
import shutil
import unittest

import yaml

from support import (ENCODING, EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, ME, TEST_PROFILE,
                     StoreTestCase, TempStore)

from svod.approval import (MARK_AT, MARK_KEYS, digest, is_fresh, mark_path, read_mark,
                             set_fields, write_mark)
from svod.config import load_config
from svod.errors import LoadError
from svod.locale import Locale
from svod.providers.openspec_change import DEFAULT_ROOT, METADATA_FILE
from svod.render import gate_text

CHANGE = f"{DEFAULT_ROOT}/c-1"
META = f"{CHANGE}/{METADATA_FILE}"
BIND = ["design.md", "specs/**/spec.md"]
UNBOUND_GATE = "params: { marker: approved, file: .openspec.yaml }"
BOUND_GATE = ("params: { marker: approved, file: .openspec.yaml, "
              "bind: [design.md, \"specs/**/spec.md\"] }")
IGNORE = ["^PR [0-9]+$"]
IGNORING_GATE = ("params: { marker: approved, file: .openspec.yaml, "
                 "bind: [design.md, \"specs/**/spec.md\"], ignore: [\"^PR [0-9]+$\"] }")
STRIP = [", opened [0-9-]+$"]
STRIPPING_GATE = ("params: { marker: approved, file: .openspec.yaml, "
                  "bind: [design.md, \"specs/**/spec.md\"], ignore: [\"^PR [0-9]+$\"], "
                  "strip: [\", opened [0-9-]+$\"] }")
KEEP = "ticket: tk-1\n# kept comment\nextra: value\n"
WINDOW = 10
MINUTE = dt.timedelta(minutes=1)
PROFILE_DIR = "bound-profile"


def bound_profile(root, gate=BOUND_GATE):
    """Copy of the test profile whose approval step declares the given gate params."""
    target = root / PROFILE_DIR
    shutil.copytree(TEST_PROFILE, target)
    pipeline = target / "pipelines" / "task.yaml"
    text = pipeline.read_text(encoding=ENCODING)
    pipeline.write_text(text.replace(UNBOUND_GATE, gate), encoding=ENCODING)
    return target


class ApproveTest(StoreTestCase):
    """svod approve writes the fields only after a fresh mark that names the subject."""

    GATE = BOUND_GATE

    def setUp(self):
        """Store with a bound approval step and one change in git."""
        super().setUp()
        config = self.sb.store / "svod.yaml"
        text = config.read_text(encoding=ENCODING)
        self.sb.write("svod.yaml", text.replace(
            str(TEST_PROFILE), str(bound_profile(self.sb.root, self.GATE))))
        self.sb.init_git(remote=False)
        self.sb.write(META, KEEP)
        self.sb.write(f"{CHANGE}/design.md", "# design\n")
        self.sb.write(f"{CHANGE}/specs/cap/spec.md", "# spec\n")
        self.sb.commit(message="change")
        self.change = self.sb.store / CHANGE

    def meta(self):
        """Parsed metadata of the change."""
        return yaml.safe_load((self.sb.store / META).read_text(encoding=ENCODING))

    def mark(self, keys=(), minutes_ago=0):
        """Leave a mark as the prompt hook would."""
        at = dt.datetime.now().astimezone() - minutes_ago * MINUTE
        write_mark(self.sb.store, keys, at)

    def test_fresh_mark_writes_fields_and_is_consumed(self):
        """Three fields written, other lines kept, gate passes; a second approve is refused."""
        self.mark()
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertIn("Nothing is committed", out.stdout)
        text = (self.sb.store / META).read_text(encoding=ENCODING)
        self.assertTrue(text.startswith(KEEP), text)
        meta = self.meta()
        self.assertEqual(str(meta["approved"]), dt.date.today().isoformat())
        self.assertEqual(meta["approved_by"], ME[0])
        self.assertEqual(meta["approved_sha"], digest(self.change, BIND))
        self.assertIsNone(read_mark(self.sb.store))
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)
        again = self.sb.cli("approve", "tk-1")
        self.assertEqual(again.returncode, EXIT_FINDINGS)
        self.assertIn("No fresh approval", again.stderr)

    def test_refusals(self):
        """No mark, a stale mark and a mark for another key write nothing."""
        cases = ((None, "No fresh approval"), ((), WINDOW + 1, "No fresh approval"),
                 (("Tk-2",), 0, "names Tk-2, not tk-1"))
        for case in cases:
            keys_and_age, message = case[:-1], case[-1]
            with self.subTest(case=case):
                mark_path(self.sb.store).unlink(missing_ok=True)
                if keys_and_age[0] is not None:
                    self.mark(*keys_and_age)
                out = self.sb.cli("approve", "tk-1")
                self.assertEqual(out.returncode, EXIT_FINDINGS)
                self.assertIn(message, out.stderr)
                self.assertNotIn("approved", self.meta())
        self.assertIsNotNone(read_mark(self.sb.store), "a refused mark is not consumed")

    def test_mark_with_the_key(self):
        """A mark naming the subject key in any case approves it."""
        self.mark(("Tk-1",))
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)

    def test_reapproval_replaces_the_fields(self):
        """A legacy date is overwritten in place, not duplicated."""
        set_fields(self.sb.store / META, {"approved": "2026-01-01"})
        self.mark()
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        text = (self.sb.store / META).read_text(encoding=ENCODING)
        self.assertEqual(text.count("approved:"), 1)
        self.assertEqual(str(self.meta()["approved"]), dt.date.today().isoformat())

    def test_unknown_query_and_no_approver(self):
        """Nothing found is a usage error; without any identity the approval is refused."""
        self.assertEqual(self.sb.cli("approve", "tk-99").returncode, EXIT_USAGE)
        self.sb.git(self.sb.store, "config", "--unset", "user.email")
        self.mark()
        out = self.sb.cli("approve", "tk-1")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertIn("Who approves is unknown", out.stderr)


class ApproveIgnoringLinesTest(ApproveTest):
    """With ignore, approve records the normalized digest, which survives ignored lines."""

    GATE = IGNORING_GATE

    def test_fresh_mark_writes_fields_and_is_consumed(self):
        """The recorded digest is the normalized one; an ignored line keeps the approval."""
        self.mark()
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        sha = self.meta()["approved_sha"]
        self.assertEqual(sha, digest(self.change, BIND, IGNORE))
        self.assertNotEqual(sha, digest(self.change, BIND))
        self.sb.write(f"{CHANGE}/design.md", "# design\n\nPR 7\n")
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)
        self.sb.write(f"{CHANGE}/design.md", "# design v2\n")
        self.assertNotIn("+ approved", self.sb.cli("status", "tk-1").stdout)


class ApproveStrippingTest(ApproveTest):
    """With strip, approve records the digest under ignore and strip, which survives the cut."""

    GATE = STRIPPING_GATE

    def test_fresh_mark_writes_fields_and_is_consumed(self):
        """The recorded digest is the one with strip; a cut tail keeps the approval."""
        self.mark()
        self.assertEqual(self.sb.cli("approve", "tk-1").returncode, EXIT_OK)
        sha = self.meta()["approved_sha"]
        self.assertEqual(sha, digest(self.change, BIND, IGNORE, STRIP))
        self.sb.write(f"{CHANGE}/design.md", "# design, opened 2026-09-24\n\nPR 7\n")
        self.assertNotEqual(sha, digest(self.change, BIND, IGNORE))
        self.assertIn("+ approved", self.sb.cli("status", "tk-1").stdout)
        self.sb.write(f"{CHANGE}/design.md", "# design v2, opened 2026-09-24\n")
        self.assertNotIn("+ approved", self.sb.cli("status", "tk-1").stdout)


class MarkTest(StoreTestCase):
    """The mark lives in the git common directory and is fresh only inside the window."""

    def test_mark_location_and_freshness(self):
        """Written next to the objects of the store; fresh within the window only."""
        self.sb.init_git(remote=False)
        now = dt.datetime.now().astimezone()
        path = write_mark(self.sb.store, ["Tk-1"], now)
        self.assertEqual(path.parent, (self.sb.store / ".git").resolve())
        mark = json.loads(path.read_text(encoding=ENCODING))
        self.assertEqual(mark[MARK_KEYS], ["Tk-1"])
        cases = ((now, True), (now + WINDOW * MINUTE, True), (now + (WINDOW + 1) * MINUTE, False),
                 (now - MINUTE, False))
        for at, fresh in cases:
            with self.subTest(at=at):
                self.assertEqual(is_fresh(mark, WINDOW, at), fresh)
        self.assertFalse(is_fresh({MARK_AT: "yesterday"}, WINDOW, now))
        self.assertFalse(is_fresh(None, WINDOW, now))

    def test_outside_git_there_is_no_mark(self):
        """A store outside git has nowhere to keep the mark."""
        self.assertIsNone(write_mark(self.sb.store, []))
        self.assertIsNone(read_mark(self.sb.store))


class SetFieldsTest(unittest.TestCase):
    """Line-wise writing keeps comments and order."""

    def test_set_fields(self):
        """Existing fields are replaced in place, new ones appended, unsafe values quoted."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        path = sb.write("meta.yaml", "a: 1\n# note\nb: 2")
        set_fields(path, {"b": "x@example.com", "c": "has: colon", "d": "0123"})
        self.assertEqual(path.read_text(encoding=ENCODING),
                         'a: 1\n# note\nb: x@example.com\nc: "has: colon"\nd: "0123"\n')


class ApprovalConfigTest(unittest.TestCase):
    """The approval block of svod.yaml."""

    def test_values_and_errors(self):
        """Phrases and window are read; bad shapes are load errors."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        base = sb.store.joinpath("svod.yaml").read_text(encoding=ENCODING)
        sb.write("svod.yaml", base + "approval: { phrases: [ok go], window_minutes: 3 }\n")
        config = load_config(sb.store)
        self.assertEqual((config.approval_phrases, config.approval_window), (("ok go",), 3))
        cases = (("approval: [a]\n", "must be a mapping"),
                 ("approval: { colour: red }\n", "unknown key: colour"),
                 ("approval: { phrases: ok }\n", "phrases must be a list"),
                 ("approval: { window_minutes: 0 }\n", "window_minutes must be a positive"))
        for text, message in cases:
            with self.subTest(text=text):
                sb.write("svod.yaml", base + text)
                with self.assertRaises(LoadError) as ctx:
                    load_config(sb.store)
                self.assertIn(message, str(ctx.exception))


class TextVariantTest(unittest.TestCase):
    """A text takes its <key>_<reason> variant when the locale has one."""

    def test_variants(self):
        """Reason with a variant, reason without one, no reason."""
        locale = Locale({"step": "base", "step_drift": "drift by {by}"})
        cases = (({"reason": "drift", "by": "me"}, "drift by me"),
                 ({"reason": "legacy"}, "base"), ({}, "base"))
        for facts, text in cases:
            with self.subTest(facts=facts):
                self.assertEqual(gate_text(locale, "step", facts), text)


if __name__ == "__main__":
    unittest.main()
