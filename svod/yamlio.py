"""YAML reading shared by the loaders."""
import yaml

from .errors import LoadError

ENCODING = "utf-8"


def read_yaml(path):
    """Parse a YAML file, raising LoadError when it is absent or malformed."""
    try:
        with open(path, encoding=ENCODING) as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError:
        raise LoadError([f"{path}: file not found"]) from None
    except yaml.YAMLError as exc:
        raise LoadError([f"{path}: invalid YAML: {exc}"]) from None
