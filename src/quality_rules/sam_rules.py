"""SAM-sourced quality rules.

Bridges a PIQI SAM chain into the existing rule engine. A :class:`SamChainRule`
is a normal :class:`~quality_rules.base.Rule` — the engine registers and fires it
through its usual path — but instead of a hand-written ``check()``, it:

1. maps the incoming FHIR resource into a PIQI attribute (via the mapping layer),
2. runs a SAM chain against that attribute, and
3. projects the tri-state SAM result onto the engine's outcome model:
   ``PASS`` -> nothing, ``FAIL`` -> a :class:`Violation`, ``COULD_NOT_ASSESS`` ->
   a :class:`CouldNotAssess`.

To wire a new chain: subclass :class:`SamChainRule`, set ``id``,
``resource_types``, ``piqi_path``, and ``terminal_sam``, and ``@register`` it.
No engine, SAM, or mapping-layer code changes.
"""

from __future__ import annotations

import piqi_mapping  # noqa: F401  registers FHIR field mappers
import sam.sams  # noqa: F401  registers the bundled SAMs
from piqi_mapping.dispatcher import map_field
from quality_rules.base import CouldNotAssess, Rule, Severity, Violation
from quality_rules.registry import register
from sam.base import Outcome
from sam.registry import get_sam
from sam.runner import run_chain


class SamChainRule(Rule):
    """A rule whose verdict comes from running a PIQI SAM chain.

    Subclasses set the four attributes below; everything else is generic.

    Attributes
    ----------
    piqi_path:
        The PIQI model path whose mapper extracts this rule's input from the
        FHIR resource (e.g. ``"person.birthDate"``).
    terminal_sam:
        Mnemonic of the last SAM in the chain. Its prerequisites are resolved
        and run ahead of it by the chain runner.
    """

    piqi_path: str = ""
    terminal_sam: str = ""

    def evaluate(self, resource: dict) -> list:
        """Map the FHIR resource, run the SAM chain, and project the result."""
        attribute = map_field(self.piqi_path, resource)
        result = run_chain(self.terminal_sam, attribute)

        resource_type = resource.get("resourceType", "")
        resource_id = resource.get("id", "")

        if result.outcome is Outcome.PASS:
            return []
        if result.outcome is Outcome.FAIL:
            return [
                Violation(
                    rule_id=self.id,
                    severity=self.severity,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    message=result.message,
                )
            ]
        # COULD_NOT_ASSESS — surface SAM metadata for human-readable reporting.
        sam = get_sam(result.sam_mnemonic)
        return [
            CouldNotAssess(
                rule_id=self.id,
                resource_type=resource_type,
                resource_id=resource_id,
                message=result.message,
                mnemonic=result.sam_mnemonic,
                dimension=sam.hdqt_dimension,
            )
        ]


@register
class PatientBirthDateIsValid(SamChainRule):
    id = "patient-birthdate-is-valid"
    description = (
        "Patient.birthDate is populated, a valid date, and in the past "
        "(PIQI SAM chain: Attr_IsPopulated -> Attr_IsDate -> Attr_IsPastDate)"
    )
    severity = Severity.WARNING
    resource_types = ("Patient",)

    piqi_path = "person.birthDate"
    terminal_sam = "Attr_IsPastDate"
