"""YAML reading and writing shared by the loaders: one loader, duplicate keys refused."""
import yaml

from .errors import LoadError

ENCODING = "utf-8"
MERGE_TAG = "tag:yaml.org,2002:merge"
MAPPING_CONTEXT = "while constructing a mapping"
DUPLICATE_KEY = "duplicate key"


class UniqueLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses a mapping naming the same key twice.

    Merge keys (<<) are left to the safe loader: a key of the mapping itself may override a
    merged one, as YAML allows.
    """

    def construct_mapping(self, node, deep=False):
        """Mapping of the node; ConstructorError at the second occurrence of a key."""
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == MERGE_TAG:
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                repeated = key in seen
                seen.add(key)
            except TypeError:
                continue
            if repeated:
                raise yaml.constructor.ConstructorError(
                    MAPPING_CONTEXT, node.start_mark, f"{DUPLICATE_KEY}: {key}",
                    key_node.start_mark)
        return super().construct_mapping(node, deep=deep)


def parse_yaml(text, source):
    """Parse YAML text with the unique loader, raising LoadError that names the source."""
    try:
        return yaml.load(text, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise LoadError([f"{source}: invalid YAML: {exc}"]) from None


def read_yaml(path):
    """Parse a YAML file, raising LoadError when it is absent, not UTF-8 or malformed."""
    try:
        with open(path, encoding=ENCODING) as fh:
            text = fh.read()
    except FileNotFoundError:
        raise LoadError([f"{path}: file not found"]) from None
    except UnicodeDecodeError as exc:
        raise LoadError([f"{path}: not {ENCODING}: {exc}"]) from None
    return parse_yaml(text, path)


def dump_yaml(data):
    """YAML text of the data, keys in the given order, non-ASCII kept as is."""
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
