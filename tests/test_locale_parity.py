"""Every shipped en/ru locale pair has the same keys and the same placeholders per key."""
import string
import unittest

from support import REPO_DIR

from svod.locale import read_locale_file

LOCALE_DIRS = (
    REPO_DIR / "svod" / "locale",
    REPO_DIR / "svod" / "templates" / "task" / "profile" / "locale",
    REPO_DIR / "svod" / "templates" / "local" / "profile" / "locale",
)
LOCALES = ("en", "ru")


def placeholders(template):
    """Field names of the format template, such as name or frontmatter[status]."""
    return {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}


class LocaleParityTest(unittest.TestCase):
    def test_pairs_share_keys_and_placeholders(self):
        """A translation neither drops nor adds a key or a placeholder."""
        for directory in LOCALE_DIRS:
            en, ru = (read_locale_file(directory / f"{name}.yaml") for name in LOCALES)
            with self.subTest(locale_dir=str(directory.relative_to(REPO_DIR))):
                self.assertTrue(en)
                self.assertEqual(sorted(set(en) - set(ru)), [], "keys missing in ru")
                self.assertEqual(sorted(set(ru) - set(en)), [], "keys missing in en")
                differing = {key: (placeholders(en[key]), placeholders(ru[key]))
                             for key in en.keys() & ru.keys()
                             if placeholders(en[key]) != placeholders(ru[key])}
                self.assertEqual(differing, {}, "placeholders differ: key -> (en, ru)")


if __name__ == "__main__":
    unittest.main()
