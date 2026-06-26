"""SAM: ``Attr_IsDate`` — the attribute parses as a valid date.

PIQI standard-library Simple Attribute SAM. Prerequisite: ``Attr_IsPopulated``
(an empty value can't be a date, and the chain reports that as could-not-assess
rather than a date failure). Tolerates FHIR partial dates (``YYYY``,
``YYYY-MM``, ``YYYY-MM-DD``).
"""

from __future__ import annotations

from sam.base import SAM, Outcome
from sam.registry import register_sam
from sam.sams._fhirdate import parse_fhir_date


@register_sam
class AttrIsDate(SAM):
    mnemonic = "Attr_IsDate"
    name = "Attribute is a date"
    success_alias = "value is a valid date"
    failure_alias = "value is not a valid date"
    input_type = "Simple_Attribute"
    prerequisite = "Attr_IsPopulated"
    hdqt_dimension = "Validity"
    execution_type = "Primitive_Logic"

    def evaluate(self, value) -> Outcome:
        return Outcome.PASS if parse_fhir_date(value.value) is not None else Outcome.FAIL
