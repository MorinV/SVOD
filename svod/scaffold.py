"""Copy a bundled example into a new store without modifying existing files."""
import shutil
from pathlib import Path

from . import keys
from .errors import LoadError
from .locale import bootstrap_locale

TEMPLATES = ('standard', 'task')
DEFAULT_TEMPLATE = 'standard'
# A template no longer shipped and the one that replaces it.
RETIRED = {'local': 'standard'}


def scaffold(destination, template=DEFAULT_TEMPLATE):
    """Create an absent destination from packaged assets; never merge or overwrite.

    A retired template is a LoadError naming its replacement; an unknown one a ValueError.
    """
    if template in RETIRED:
        raise LoadError([bootstrap_locale().text(keys.NEW_TEMPLATE_RETIRED, template=template,
                                                 replacement=RETIRED[template])])
    if template not in TEMPLATES:
        raise ValueError('unknown template')
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination already exists; choose a new directory')
    source = Path(__file__).with_name('templates') / template
    if not source.is_dir():
        raise ValueError('template is missing from this installation')
    shutil.copytree(source, destination,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    return destination
