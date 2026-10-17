"""Version and release notes of a Svod source tree, for the release workflow.

python3 .github/scripts/release_notes.py [--root DIR] version   prints the version
python3 .github/scripts/release_notes.py [--root DIR] notes     prints its CHANGELOG section

The parser is the engine's own (svod.changelog) from this checkout; DIR is the tree to
release, the checkout itself by default. Exit 1 when the version or its section is missing.
"""
import argparse
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE_ROOT))

from svod import changelog, versions  # noqa: E402

ENCODING = "utf-8"
EXIT_MISSING = 1


def notes(text, version):
    """Body of the release of version in a changelog text, without its heading; None if absent."""
    for release in changelog.releases(text):
        if release.version == version:
            body = list(release.lines[1:])
            while body and not body[0].strip():
                body.pop(0)
            return "\n".join(body) + "\n"
    return None


def main(argv=None):
    """Print the version or the release notes of the tree; 1 when missing."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(SOURCE_ROOT))
    parser.add_argument("what", choices=("version", "notes"))
    args = parser.parse_args(argv)
    root = Path(args.root)
    version = versions.source_version(root)
    if version is None:
        print(f"no X.Y.Z __version__ in {root / versions.PACKAGE_INIT}", file=sys.stderr)
        return EXIT_MISSING
    if args.what == "version":
        print(version)
        return 0
    path = root / changelog.CHANGELOG_FILE
    body = notes(path.read_text(encoding=ENCODING), version) if path.is_file() else None
    if not body or not body.strip():
        print(f"no section ## [{version}] in {path}", file=sys.stderr)
        return EXIT_MISSING
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
