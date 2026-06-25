"""Pluggability-proof SAM rule (throwaway second worked example).

Demonstrates rule-registration plug point #3: wiring a *second* SAM chain into
the engine is "copy the birthDate pattern, change the path and mnemonic." This is
a new file that reuses :class:`~quality_rules.sam_rules.SamChainRule` unchanged;
it edits no birthDate file. Registered live via one import line in
``quality_rules/__init__.py``.

It pairs the new ``person.gender`` mapper with the existing ``Attr_IsPopulated``
SAM (a one-link chain) to assess whether ``Patient.gender`` is populated.
"""

from __future__ import annotations

from quality_rules.base import Severity
from quality_rules.registry import register
from quality_rules.sam_rules import SamChainRule


@register
class PatientGenderIsPopulated(SamChainRule):
    id = "patient-gender-is-populated"
    description = "Patient.gender is populated (PIQI SAM chain: Attr_IsPopulated)"
    severity = Severity.WARNING
    resource_types = ("Patient",)

    piqi_path = "person.gender"
    terminal_sam = "Attr_IsPopulated"
