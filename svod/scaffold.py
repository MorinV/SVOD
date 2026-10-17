"""Copy a bundled example into a new store without modifying existing files."""
import shutil
from pathlib import Path


TEMPLATES = ('local', 'task', 'standard')


def scaffold(destination, template='local'):
    """Create an absent destination from packaged assets; never merge or overwrite."""
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
