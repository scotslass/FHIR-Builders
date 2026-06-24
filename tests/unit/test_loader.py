"""Unit tests for seed loader helpers (tagging + clinical-only filter)."""

from seed.defect_catalog import SYNTHETIC_TAG, TEST_DATA_SYSTEM
from seed.loader import (
    SYNTHEA_IDENTIFIER_SYSTEM,
    NON_CLINICAL_TYPES,
    bundle_has_patient,
    filter_clinical,
    patient_identifier,
    tag_bundle_synthetic,
)


def _bundle(types: list[str]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": {"resourceType": t, "id": f"{t}-1"}} for t in types],
    }


def test_filter_clinical_removes_only_non_clinical():
    bundle = _bundle(["Patient", "Observation", "Claim",
                      "ExplanationOfBenefit", "Encounter", "Provenance"])
    removed = filter_clinical(bundle)

    assert removed == 3  # Claim, ExplanationOfBenefit, Provenance
    kept = {e["resource"]["resourceType"] for e in bundle["entry"]}
    assert kept == {"Patient", "Observation", "Encounter"}
    assert kept.isdisjoint(NON_CLINICAL_TYPES)


def test_filter_clinical_keeps_clinical_only_bundle_intact():
    bundle = _bundle(["Patient", "Observation", "Condition", "Encounter"])
    assert filter_clinical(bundle) == 0
    assert len(bundle["entry"]) == 4


def test_patient_identifier_and_detection():
    patient_bundle = {
        "resourceType": "Bundle", "type": "transaction",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "p1", "identifier": [
                {"system": "urn:other", "value": "x"},
                {"system": SYNTHEA_IDENTIFIER_SYSTEM, "value": "abc-123"},
            ]}},
            {"resource": {"resourceType": "Observation", "id": "o1"}},
        ],
    }
    assert bundle_has_patient(patient_bundle) is True
    assert patient_identifier(patient_bundle) == "abc-123"


def test_info_bundle_has_no_patient_identifier():
    info_bundle = _bundle(["Organization", "Location", "Practitioner"])
    assert bundle_has_patient(info_bundle) is False
    assert patient_identifier(info_bundle) is None


def test_tag_bundle_synthetic_is_idempotent():
    bundle = _bundle(["Patient", "Observation"])
    assert tag_bundle_synthetic(bundle) == 2
    tag_bundle_synthetic(bundle)  # second pass must not duplicate tags

    for entry in bundle["entry"]:
        tags = entry["resource"]["meta"]["tag"]
        assert tags.count(dict(SYNTHETIC_TAG)) == 1
        assert tags[0]["system"] == TEST_DATA_SYSTEM
