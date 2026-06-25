"""FHIR mapper: ``Patient.birthDate`` -> PIQI ``person.birthDate``.

Extracts the FHIR ``Patient.birthDate`` value and presents it as a PIQI Simple
Attribute. Pure reshaping: it preserves the FHIR ``date`` string as-is (any of
``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``) and performs none of the SAMs' validation.

If ``birthDate`` is absent or ``null``, the result is a well-formed *unpopulated*
Simple Attribute (``value=None``) so that ``Attr_IsPopulated`` — not this mapper
— reports the missing-data condition (FR9).
"""

from __future__ import annotations

from piqi_mapping.base import SimpleAttribute
from piqi_mapping.dispatcher import register_mapper

PIQI_PATH = "person.birthDate"


@register_mapper(PIQI_PATH)
def map_patient_birthdate(resource: dict) -> SimpleAttribute:
    """Map a FHIR ``Patient`` dict to the ``person.birthDate`` Simple Attribute."""
    return SimpleAttribute(value=resource.get("birthDate"))
