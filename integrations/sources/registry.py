"""Source adapter registry with plugin discovery.

Built-in adapters are registered explicitly. Third-party adapters are
discovered through the ``atlas_osint.sources`` entry-point group, so a
researcher can ship a source as a separate Python package::

    [project.entry-points."atlas_osint.sources"]
    my_source = "my_package.adapter:MySourceAdapter"
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Iterable

from integrations.sources.base import SourceAdapter
from shared.types import IdentifierType

log = logging.getLogger("atlas.registry")

ENTRY_POINT_GROUP = "atlas_osint.sources"


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        name = adapter.meta.name
        if name in self._adapters:
            raise ValueError(f"duplicate source adapter name: {name}")
        self._adapters[name] = adapter

    def get(self, name: str) -> SourceAdapter | None:
        return self._adapters.get(name)

    def all(self) -> list[SourceAdapter]:
        return sorted(self._adapters.values(), key=lambda a: (a.meta.category.value, a.meta.name))

    def names(self) -> list[str]:
        return sorted(self._adapters)

    def for_input(self, identifier_type: IdentifierType, enabled: Iterable[str] | None = None) -> list[SourceAdapter]:
        allowed = set(enabled) if enabled is not None else None
        return [
            a
            for a in self.all()
            if identifier_type in a.meta.input_types and (allowed is None or a.meta.name in allowed)
        ]

    def load_entry_points(self) -> int:
        loaded = 0
        for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
            try:
                cls = ep.load()
                adapter = cls()
                if not isinstance(adapter, SourceAdapter):
                    log.warning("entry point %s does not provide a SourceAdapter", ep.name)
                    continue
                self.register(adapter)
                loaded += 1
            except Exception:
                log.exception("failed to load source plugin %s", ep.name)
        return loaded


def build_default_registry(load_plugins: bool = True) -> SourceRegistry:
    from integrations.sources.builtin import BUILTIN_ADAPTERS

    registry = SourceRegistry()
    for cls in BUILTIN_ADAPTERS:
        registry.register(cls())
    if load_plugins:
        registry.load_entry_points()
    return registry


_default: SourceRegistry | None = None


def get_registry() -> SourceRegistry:
    global _default
    if _default is None:
        _default = build_default_registry()
    return _default
