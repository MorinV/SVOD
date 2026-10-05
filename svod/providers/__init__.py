"""Subject providers of the core, by name."""
from .base import Provider
from .container import ContainerProvider
from .frontmatter_doc import FrontmatterDocProvider
from .openspec_change import OpenspecChangeProvider

CORE_PROVIDERS = {cls.name: cls for cls in (
    OpenspecChangeProvider, ContainerProvider, FrontmatterDocProvider,
)}

__all__ = ["CORE_PROVIDERS", "Provider"]
