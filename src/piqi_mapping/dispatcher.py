"""FHIR-to-PIQI mapper registry and dispatcher.

A small registry of named mappers keyed by the PIQI model path they produce
(e.g. ``"person.birthDate"``). Each mapper is a callable that takes a FHIR
resource (a plain ``dict``) and returns a PIQI attribute shape. Adding a mapping
for a new field means writing one new mapper and registering it here — never
editing a growing conditional (FR11).
"""

from __future__ import annotations

from typing import Callable

# Maps PIQI path -> mapper callable (FHIR resource dict -> PIQI attribute).
_MAPPERS: dict[str, Callable[[dict], object]] = {}


def register_mapper(piqi_path: str) -> Callable[[Callable], Callable]:
    """Decorator registering a mapper under the PIQI path it produces.

    Raises ``ValueError`` if a mapper is already registered for ``piqi_path``.
    """

    def decorator(fn: Callable[[dict], object]) -> Callable[[dict], object]:
        if piqi_path in _MAPPERS:
            raise ValueError(f"duplicate PIQI path mapper: {piqi_path!r}")
        _MAPPERS[piqi_path] = fn
        return fn

    return decorator


def map_field(piqi_path: str, resource: dict):
    """Run the mapper registered for ``piqi_path`` against ``resource``.

    Raises ``KeyError`` if no mapper is registered for that path.
    """
    try:
        mapper = _MAPPERS[piqi_path]
    except KeyError as exc:
        raise KeyError(f"no FHIR mapper registered for PIQI path {piqi_path!r}") from exc
    return mapper(resource)


def is_registered(piqi_path: str) -> bool:
    """Return True if a mapper is registered for ``piqi_path``."""
    return piqi_path in _MAPPERS


def clear() -> None:
    """Empty the mapper registry. Intended for tests."""
    _MAPPERS.clear()
