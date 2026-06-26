"""SAM: ``Attr_IsPopulated`` — the attribute has content.

PIQI standard-library Simple Attribute SAM. Root of the birthDate chain (no
prerequisite). It owns the "is the data present?" check — the FHIR mapper must
hand through missing data as an unpopulated attribute rather than swallowing it,
so that this SAM (not the mapper) reports the gap.
"""

from __future__ import annotations

from sam.base import SAM, Outcome
from sam.registry import register_sam


@register_sam
class AttrIsPopulated(SAM):
    mnemonic = "Attr_IsPopulated"
    name = "Attribute is populated"
    success_alias = "value is populated"
    failure_alias = "value is not populated"
    input_type = "Simple_Attribute"
    prerequisite = None
    hdqt_dimension = "Completeness"
    execution_type = "Primitive_Logic"

    def evaluate(self, value) -> Outcome:
        return Outcome.PASS if value.is_populated else Outcome.FAIL
