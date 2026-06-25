"""FHIR mapper: ``Patient.gender`` -> PIQI ``person.gender``.

Pluggability proof. Added as a *new file* plus one registration line in
``piqi_mapping/__init__.py`` — no edits to the dispatcher, the SimpleAttribute
type, or the birthDate mapper. Demonstrates that mapping a second FHIR field is
purely additive.
"""

from __future__ import annotations

from piqi_mapping.base import SimpleAttribute
from piqi_mapping.dispatcher import register_mapper

PIQI_PATH = "person.gender"


@register_mapper(PIQI_PATH)
def map_patient_gender(resource: dict) -> SimpleAttribute:
    """Map a FHIR ``Patient`` dict to the ``person.gender`` Simple Attribute."""
    return SimpleAttribute(value=resource.get("gender"))
