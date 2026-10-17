"""Local config: read over svod.yaml, created by init, used for the identity."""
import unittest

import yaml

from support import (EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, ENCODING, ME, PEER, StoreTestCase,
                     TempStore, core_text)

from svod import keys
from svod.config import load_config
from svod.context import Context
from svod.errors import LoadError
from svod.identity import approver, my_email
from test_active import HDR_IDLE, HDR_TEAM, change

LOCAL = ".local.yaml"
LOCAL_EMAIL = "local@example.com"
LOGIN = "someone"
NO_LOCAL = core_text(keys.ACTIVE_NO_LOCAL_CONFIG, file=LOCAL)
NO_IDENTITY = core_text(keys.ACTIVE_NO_IDENTITY)


def local_store():
    """Store whose svod.yaml names the local config file."""
    return TempStore(local_config=LOCAL)


class LocalConfigTest(unittest.TestCase):
    """Local values win over svod.yaml; a broken local file is a load error."""

    def setUp(self):
        """Store naming a local config."""
        self.sb = local_store()
        self.addCleanup(self.sb.cleanup)

    def test_values(self):
        """What the config holds with and without each local field."""
        cases = (
            (None, False, "en", self.sb.parent, None, None),
            ("", True, "en", self.sb.parent, None, None),
            (f"login: {LOGIN}\nemail: {LOCAL_EMAIL}\n", True, "en", self.sb.parent, LOGIN,
             LOCAL_EMAIL),
            ("workspaces: sub\nlocale: ru\n", True, "ru", self.sb.store / "sub", None, None),
            ("profile_config:\n  landing:\n    open_diff: all\n", True, "en", self.sb.parent, None,
             None),
        )
        for text, found, locale, workspaces, login, email in cases:
            with self.subTest(text=text):
                path = self.sb.store / LOCAL
                path.unlink(missing_ok=True)
                if text is not None:
                    self.sb.write(LOCAL, text)
                config = load_config(self.sb.store)
                self.assertEqual(config.local_found, found)
                self.assertEqual(config.locale, locale)
                self.assertEqual(config.workspaces, workspaces.resolve())
                self.assertEqual(config.login, login)
                self.assertEqual(config.email, email)

    def test_errors(self):
        """Unknown keys, non-strings and non-mappings fail; local=False skips the file."""
        cases = (("colour: red\n", "unknown key: colour"), ("login: [a]\n", "login must be"),
                 ("- a\n", "expected a mapping"),
                 ("profile_config: on\n", "profile_config must be a mapping"),
                 ("login: [\n", "invalid YAML"))
        for text, message in cases:
            with self.subTest(text=text):
                self.sb.write(LOCAL, text)
                with self.assertRaises(LoadError) as ctx:
                    load_config(self.sb.store)
                self.assertIn(message, str(ctx.exception))
                self.assertIsNone(load_config(self.sb.store, local=False).login)

    def test_without_local_config_key(self):
        """No local_config in svod.yaml: nothing is read, nothing is expected."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        config = load_config(sb.store)
        self.assertIsNone(config.local_path)
        self.assertFalse(config.local_found)


class InitTest(StoreTestCase):
    """svod init writes the local config from its arguments."""

    store_kwargs = {"local_config": LOCAL}

    def setUp(self):
        """Store with git so that the email falls back to user.email."""
        super().setUp()
        self.sb.init_git(remote=False)

    def local(self):
        """Parsed local config."""
        return yaml.safe_load((self.sb.store / LOCAL).read_text(encoding=ENCODING))

    def test_arguments(self):
        """Login and email from the arguments; email falls back to git user.email."""
        cases = ((("--login", LOGIN, "--email", LOCAL_EMAIL), {"login": LOGIN,
                                                               "email": LOCAL_EMAIL}),
                 (("--login", LOGIN), {"login": LOGIN, "email": ME[0]}))
        for args, expected in cases:
            with self.subTest(args=args):
                out = self.sb.cli("init", *args, "--force")
                self.assertEqual(out.returncode, EXIT_OK, out.stderr)
                self.assertEqual(self.local(), expected)

    def test_refusals(self):
        """Existing file without --force, no login without a terminal, no local_config key."""
        self.sb.write(LOCAL, f"login: {LOGIN}\n")
        out = self.sb.cli("init", "--login", "other")
        self.assertEqual(out.returncode, EXIT_FINDINGS)
        self.assertEqual(out.stderr.strip(),
                         core_text(keys.INIT_EXISTS, path=self.sb.store / LOCAL))
        self.assertEqual(self.local(), {"login": LOGIN})
        (self.sb.store / LOCAL).unlink()
        out = self.sb.cli("init")
        self.assertEqual(out.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.INIT_NEED_LOGIN), out.stderr)
        self.assertFalse((self.sb.store / LOCAL).exists())

    def test_not_configured(self):
        """Without local_config in svod.yaml init has nowhere to write."""
        sb = TempStore()
        self.addCleanup(sb.cleanup)
        out = sb.cli("init", "--login", LOGIN)
        self.assertEqual(out.returncode, EXIT_USAGE)
        self.assertIn("local_config", out.stderr)

    def test_broken_local_config_is_overwritten(self):
        """A broken local file does not stop init --force from replacing it."""
        self.sb.write(LOCAL, "colour: red\n")
        out = self.sb.cli("init", "--login", LOGIN, "--force")
        self.assertEqual(out.returncode, EXIT_OK, out.stderr)
        self.assertEqual(self.local()["login"], LOGIN)


class IdentityTest(StoreTestCase):
    """Who am I: local email first, git second, a warning when neither is known."""

    store_kwargs = {"local_config": LOCAL}

    def setUp(self):
        """Store with a peer's change in git."""
        super().setUp()
        self.sb.init_git(remote=False)
        change(self.sb, "c-4", "tk-4")
        self.sb.commit(message="peer", author=PEER)

    def ctx(self):
        """Context over the current config."""
        return Context(load_config(self.sb.store))

    def test_identity(self):
        """Email and approver for each combination of local config and git identity."""
        cases = (
            (f"login: {LOGIN}\nemail: {PEER[0]}\n", True, PEER[0], LOGIN),
            (f"email: {LOCAL_EMAIL}\n", True, LOCAL_EMAIL, LOCAL_EMAIL),
            ("", True, ME[0], ME[0]),
            ("", False, "", None),
        )
        for text, git_identity, email, name in cases:
            with self.subTest(text=text, git=git_identity):
                self.sb.write(LOCAL, text)
                if not git_identity:
                    self.sb.git(self.sb.store, "config", "--unset", "user.email")
                self.assertEqual(my_email(self.ctx()), email)
                self.assertEqual(approver(self.ctx()), name)

    def test_summary(self):
        """Missing local config is the first line; the local email decides what is mine."""
        out = self.sb.cli("active")
        self.assertTrue(out.stdout.startswith(NO_LOCAL), out.stdout)
        self.assertIn(HDR_TEAM, out.stdout)
        self.sb.write(LOCAL, f"login: {LOGIN}\nemail: {PEER[0]}\n")
        out = self.sb.cli("active")
        self.assertNotIn(NO_LOCAL, out.stdout)
        self.assertIn(HDR_IDLE, out.stdout)
        self.assertNotIn(NO_IDENTITY, out.stdout)

    def test_no_identity_warns(self):
        """Neither local nor git email: a warning line instead of silently mine."""
        self.sb.write(LOCAL, f"login: {LOGIN}\n")
        self.sb.git(self.sb.store, "config", "--unset", "user.email")
        lines = self.sb.cli("active").stdout.splitlines()
        self.assertTrue(lines[0].startswith(NO_IDENTITY), lines)
        self.assertIn(HDR_IDLE, lines)


if __name__ == "__main__":
    unittest.main()
