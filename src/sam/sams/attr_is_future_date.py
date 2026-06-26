"""SAM: ``Attr_IsFutureDate`` — the date is chronologically after today.

Pluggability proof (PIQI standard-library SAM). Added as a *new file* plus one
registration line in ``sam/sams/__init__.py`` — no edits to the SAM base class,
registry, chain runner, or any birthDate SAM. It reuses the existing
``Attr_IsDate`` SAM as its prerequisite purely by mnemonic, demonstrating that
chains compose across independently-authored SAMs.
"""

from __future__ import annotations

from datetime import date

from sam.base import SAM, Outcome
from sam.registry import register_sam
from sam.sams._fhirdate import parse_fhir_date


@register_sam
class AttrIsFutureDate(SAM):
    mnemonic = "Attr_IsFutureDate"
    name = "Attribute is a future date"
    success_alias = "date is in the future"
    failure_alias = "date is not in the future"
    input_type = "Simple_Attribute"
    prerequisite = "Attr_IsDate"
    hdqt_dimension = "Plausibility"
    execution_type = "Primitive_Logic"

    def evaluate(self, value) -> Outcome:
        parsed = parse_fhir_date(value.value)
        if parsed is None:
            return Outcome.FAIL
        return Outcome.PASS if parsed > date.today() else Outcome.FAIL
