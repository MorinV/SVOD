"""Store root lookup that needs nothing beyond the standard library."""
from pathlib import Path

CONFIG_FILE = "svod.yaml"
VENDOR_DIR = ".svod"
LIB_DIR = "lib"
PACKAGE_DIR = "svod"


def find_root(start):
    """Nearest directory from start upwards holding the config file, or None."""
    start = Path(start).resolve()
    for candidate in (start, *start.parents):
        if (candidate / CONFIG_FILE).is_file():
            return candidate
    return None


def vendor_dir(root):
    """The .svod directory of a store holding its copy of the engine."""
    return Path(root) / VENDOR_DIR


def lib_dir(root):
    """Directory to put on the import path to load the copy of the store."""
    return vendor_dir(root) / LIB_DIR


def package_dir(root):
    """The copied package of the store."""
    return lib_dir(root) / PACKAGE_DIR
