"""SAM registry and the ``@register_sam`` decorator.

SAM classes register themselves at import time, keyed by mnemonic. Prerequisite
links are resolved through this registry (mnemonic -> instance), so SAMs never
import one another directly. Mirrors the ``quality_rules.registry`` idiom.
"""

from __future__ import annotations

from sam.base import SAM

# Maps mnemonic -> SAM instance. Populated by the @register_sam decorator.
_REGISTRY: dict[str, SAM] = {}


def register_sam(sam_cls: type[SAM]) -> type[SAM]:
    """Class decorator that registers a :class:`SAM` subclass by its mnemonic.

    Raises ``ValueError`` if the SAM has no ``mnemonic`` or if its mnemonic
    collides with an already-registered SAM.
    """
    if not sam_cls.mnemonic:
        raise ValueError(f"{sam_cls.__name__} must define a non-empty `mnemonic`")
    if sam_cls.mnemonic in _REGISTRY:
        raise ValueError(f"duplicate SAM mnemonic: {sam_cls.mnemonic!r}")
    _REGISTRY[sam_cls.mnemonic] = sam_cls()
    return sam_cls


def get_sam(mnemonic: str) -> SAM:
    """Return the registered SAM instance for ``mnemonic``.

    Raises ``KeyError`` if no SAM is registered under that mnemonic.
    """
    try:
        return _REGISTRY[mnemonic]
    except KeyError as exc:
        raise KeyError(f"no SAM registered under mnemonic {mnemonic!r}") from exc


def is_registered(mnemonic: str) -> bool:
    """Return True if a SAM is registered under ``mnemonic``."""
    return mnemonic in _REGISTRY


def clear() -> None:
    """Empty the registry. Intended for tests."""
    _REGISTRY.clear()
