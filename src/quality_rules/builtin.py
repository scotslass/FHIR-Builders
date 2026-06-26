"""Bundled example data quality rules.

These cover the most common clinical-data completeness checks and double as
worked examples for writing your own. Add new rules here (or in a sibling
module that is imported) and decorate them with ``@register``.
"""

from __future__ import annotations

from quality_rules.base import Rule, Severity
from quality_rules.registry import register

# Value sets used below. FHIR R4 administrative gender.
_VALID_GENDERS = {"male", "female", "other", "unknown"}


# ── Patient rules ─────────────────────────────────────────────────────────────

@register
class PatientHasName(Rule):
    id = "patient-name-present"
    description = "Patient must have at least one name with a family or given part"
    severity = Severity.ERROR
    resource_types = ("Patient",)

    def check(self, resource: dict) -> list[str]:
        names = resource.get("name") or []
        for name in names:
            if name.get("family") or name.get("given"):
                return []
        return ["Patient has no usable name (missing family and given)"]


@register
class PatientHasBirthDate(Rule):
    id = "patient-birthdate-present"
    description = "Patient must have a birthDate"
    severity = Severity.ERROR
    resource_types = ("Patient",)

    def check(self, resource: dict) -> list[str]:
        if not resource.get("birthDate"):
            return ["birthDate is missing"]
        return []


@register
class PatientBirthDatePlausible(Rule):
    id = "patient-birthdate-plausible"
    description = "Patient.birthDate must be a real, non-future date after 1900"
    severity = Severity.WARNING
    resource_types = ("Patient",)

    # FHIR birthDate is a `date`: YYYY, YYYY-MM, or YYYY-MM-DD. We only need the
    # year for a plausibility check, so parse leniently and ignore partial dates.
    def check(self, resource: dict) -> list[str]:
        birth_date = resource.get("birthDate")
        if not birth_date:
            return []  # absence is the concern of patient-birthdate-present
        from datetime import date

        year_part = str(birth_date)[:4]
        if not year_part.isdigit():
            return [f"birthDate {birth_date!r} is not a parseable date"]
        year = int(year_part)
        today = date.today()
        if year > today.year:
            return [f"birthDate {birth_date!r} is in the future"]
        if year < 1900:
            return [f"birthDate {birth_date!r} predates 1900 (implausible)"]
        return []


@register
class PatientGenderValid(Rule):
    id = "patient-gender-valid"
    description = "Patient.gender must be a valid FHIR administrative gender code"
    severity = Severity.WARNING
    resource_types = ("Patient",)

    def check(self, resource: dict) -> list[str]:
        gender = resource.get("gender")
        if gender is None:
            return ["gender is missing"]
        if gender not in _VALID_GENDERS:
            return [f"gender {gender!r} is not a valid administrative gender code"]
        return []


# ── Observation rules ─────────────────────────────────────────────────────────

@register
class ObservationHasCode(Rule):
    id = "observation-code-present"
    description = "Observation must carry a code (what was measured)"
    severity = Severity.ERROR
    resource_types = ("Observation",)

    def check(self, resource: dict) -> list[str]:
        coding = (resource.get("code") or {}).get("coding") or []
        if not coding:
            return ["Observation.code has no coding"]
        return []


@register
class ObservationHasValue(Rule):
    id = "observation-has-value"
    description = (
        "A completed Observation should report a value or an explicit dataAbsentReason"
    )
    severity = Severity.WARNING
    resource_types = ("Observation",)

    # Any of these value[x] forms satisfies the rule.
    _VALUE_KEYS = (
        "valueQuantity", "valueCodeableConcept", "valueString", "valueBoolean",
        "valueInteger", "valueRange", "valueRatio", "valueSampledData",
        "valueTime", "valueDateTime", "valuePeriod",
    )

    def check(self, resource: dict) -> list[str]:
        if resource.get("status") not in ("final", "amended", "corrected"):
            return []  # only completed observations are expected to have a value
        if any(key in resource for key in self._VALUE_KEYS):
            return []
        if resource.get("dataAbsentReason"):
            return []
        if resource.get("component"):
            return []  # value lives on components
        return ["completed Observation has no value[x] and no dataAbsentReason"]


# ── Encounter rules ─────────────────────────────────────────────────────────

@register
class EncounterHasStatus(Rule):
    id = "encounter-status-present"
    description = "Encounter must have a status"
    severity = Severity.ERROR
    resource_types = ("Encounter",)

    def check(self, resource: dict) -> list[str]:
        if not resource.get("status"):
            return ["Encounter.status is missing"]
        return []


@register
class EncounterHasSubject(Rule):
    id = "encounter-subject-present"
    description = "Encounter must reference a subject (patient)"
    severity = Severity.ERROR
    resource_types = ("Encounter",)

    def check(self, resource: dict) -> list[str]:
        subject = resource.get("subject") or {}
        if not subject.get("reference"):
            return ["Encounter.subject reference is missing"]
        return []
