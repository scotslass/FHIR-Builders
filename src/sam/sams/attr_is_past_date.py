"""SAM: ``Attr_IsPastDate`` — the date is chronologically before today.

PIQI standard-library Simple Attribute SAM. Prerequisite: ``Attr_IsDate``. This
is the terminal SAM of the birthDate chain — its PASS/FAIL is the chain's verdict
(a future-dated birthDate is a FAIL).
"""

from __future__ import annotations

from datetime import date

from sam.base import SAM, Outcome
from sam.registry import register_sam
from sam.sams._fhirdate import parse_fhir_date


@register_sam
class AttrIsPastDate(SAM):
    mnemonic = "Attr_IsPastDate"
    name = "Attribute is a past date"
    success_alias = "date is in the past"
    failure_alias = "date is not in the past"
    input_type = "Simple_Attribute"
    prerequisite = "Attr_IsDate"
    hdqt_dimension = "Plausibility"
    execution_type = "Primitive_Logic"

    def evaluate(self, value) -> Outcome:
        parsed = parse_fhir_date(value.value)
        if parsed is None:
            # The Attr_IsDate prerequisite normally guarantees a parseable date;
            # be defensive if invoked standalone.
            return Outcome.FAIL
        return Outcome.PASS if parsed < date.today() else Outcome.FAIL
