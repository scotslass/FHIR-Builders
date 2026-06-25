"""Core types for the FHIR-to-PIQI mapping layer.

PIQI assesses data once it has been placed into the PIQI Data Model. The simplest
PIQI shape is a *Simple Attribute*: a single named value (PIQI's own example is
``{"effectiveDateTime": "20230111135518"}``). A mapper's job is to extract a
field from a FHIR resource and present it as one of these shapes — and nothing
more: it reshapes, it does not judge pass/fail.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimpleAttribute:
    """A PIQI Simple Attribute: an optional single value.

    ``value`` is the raw value as it appeared in the source (e.g. a FHIR ``date``
    string), preserved as-is. ``None`` means the source field was absent or
    empty — a well-formed *unpopulated* attribute. Whether "unpopulated" is a
    problem is for ``Attr_IsPopulated`` to decide, not the mapper.
    """

    value: str | None = None

    @property
    def is_populated(self) -> bool:
        """True if the attribute carries non-empty content."""
        return self.value is not None and str(self.value).strip() != ""
