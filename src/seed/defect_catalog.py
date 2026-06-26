"""Catalog of data-quality defects injected into synthetic patient data.

Design constraints
------------------
1. **Always loadable.** Each defect must leave the resource *structurally valid
   FHIR* so Medplum's profile validation accepts it on write — otherwise the
   whole patient transaction Bundle is rejected. We therefore corrupt by
   removing *optional* elements or by substituting plausible-but-wrong values,
   never by removing required (1..1) elements or violating a required code
   binding.
2. **Labelled.** Every defect maps to the built-in rule id that should catch it
   (see ``quality_rules.builtin``), so the seeded data doubles as a test set
   with known ground truth (see ``corruptor`` and ``verify_seed``).

Each mutated resource is additionally tagged ``defect:<code>`` so it can be
located directly in Medplum (``GET /Patient?_tag=http://example.org/test-data|defect:missing-birthdate``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# meta.tag system shared by every synthetic resource this tool writes.
TEST_DATA_SYSTEM = "http://example.org/test-data"
SYNTHETIC_TAG = {"system": TEST_DATA_SYSTEM, "code": "synthetic"}

# Observation.value[x] forms the engine recognises (mirrors the built-in rule).
_VALUE_KEYS = (
    "valueQuantity", "valueCodeableConcept", "valueString", "valueBoolean",
    "valueInteger", "valueRange", "valueRatio", "valueSampledData",
    "valueTime", "valueDateTime", "valuePeriod",
)


def add_tag(resource: dict, code: str) -> None:
    """Add a ``{TEST_DATA_SYSTEM, code}`` tag to ``resource.meta`` (idempotent)."""
    meta = resource.setdefault("meta", {})
    tags = meta.setdefault("tag", [])
    tag = {"system": TEST_DATA_SYSTEM, "code": code}
    if tag not in tags:
        tags.append(tag)


# ── defect mutators ─────────────────────────────────────────────────────────
# Each returns True if it actually changed the resource, else False.

def _missing_birthdate(resource: dict) -> bool:
    if "birthDate" in resource:
        del resource["birthDate"]
        return True
    return False


def _implausible_birthdate(resource: dict) -> bool:
    # A syntactically valid FHIR date, but in the future — trips the
    # plausibility rule while still loading cleanly.
    resource["birthDate"] = "2099-12-31"
    return True


def _missing_gender(resource: dict) -> bool:
    # gender is optional (0..1); removing it is valid FHIR but trips the
    # gender rule ("gender is missing"). We avoid an *invalid* code because the
    # required value-set binding would make Medplum reject the write.
    if "gender" in resource:
        del resource["gender"]
        return True
    return False


def _missing_loinc(resource: dict) -> bool:
    # Observation.code is required (1..1) but CodeableConcept.coding is optional.
    # Drop the coding (the LOINC), preserving free-text so the resource is still
    # valid. Trips observation-code-present.
    code = resource.get("code")
    if not isinstance(code, dict) or not code.get("coding"):
        return False
    display = next((c.get("display") for c in code["coding"] if c.get("display")), None)
    resource["code"] = {"text": display or "Unknown measurement"}
    return True


def _missing_value(resource: dict) -> bool:
    # Strip every value[x], component and dataAbsentReason from a completed
    # Observation so it trips observation-has-value. Force status to 'final' so
    # the rule (which only applies to completed observations) fires.
    changed = False
    for key in _VALUE_KEYS:
        if key in resource:
            del resource[key]
            changed = True
    for key in ("component", "dataAbsentReason"):
        if key in resource:
            del resource[key]
            changed = True
    if changed:
        resource["status"] = "final"
    return changed


def _missing_encounter_subject(resource: dict) -> bool:
    # Encounter.subject is optional (0..1); removing it is valid FHIR but trips
    # encounter-subject-present.
    if "subject" in resource:
        del resource["subject"]
        return True
    return False


@dataclass(frozen=True)
class Defect:
    """A single injectable defect and the rule that should catch it."""

    code: str               # short kebab-case label, also the meta.tag code
    resource_type: str      # FHIR type the defect is applied to
    rule_id: str            # built-in rule expected to flag it
    description: str
    apply: Callable[[dict], bool]
    # Optional predicate to pick a *suitable* target resource of resource_type.
    predicate: Callable[[dict], bool] | None = None


def _has_coding(obs: dict) -> bool:
    return bool((obs.get("code") or {}).get("coding"))


CATALOG: list[Defect] = [
    Defect("missing-birthdate", "Patient", "patient-birthdate-present",
           "Remove Patient.birthDate", _missing_birthdate),
    Defect("implausible-birthdate", "Patient", "patient-birthdate-plausible",
           "Set Patient.birthDate to a future date", _implausible_birthdate),
    Defect("missing-gender", "Patient", "patient-gender-valid",
           "Remove Patient.gender", _missing_gender),
    Defect("missing-loinc", "Observation", "observation-code-present",
           "Strip the LOINC coding from Observation.code", _missing_loinc,
           predicate=_has_coding),
    Defect("missing-value", "Observation", "observation-has-value",
           "Remove value[x] from a completed Observation", _missing_value),
    Defect("missing-encounter-subject", "Encounter", "encounter-subject-present",
           "Remove Encounter.subject", _missing_encounter_subject),
]

CATALOG_BY_CODE: dict[str, Defect] = {d.code: d for d in CATALOG}
