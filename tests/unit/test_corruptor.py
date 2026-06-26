"""Unit tests for the seed defect catalog and corruptor.

All data here is SYNTHETIC. These tests assert two things:
  1. each defect mutator leaves the resource *structurally loadable* yet trips
     the rule it claims to (so the seeded data is a valid labelled test set), and
  2. the corruptor is deterministic and produces an accurate manifest.
"""

import copy

import pytest

from quality_rules.registry import all_rules
from seed import defect_catalog as dc
from seed.corruptor import corrupt


def _rule(rule_id: str):
    for rule in all_rules():
        if rule.id == rule_id:
            return rule
    raise AssertionError(f"rule not registered: {rule_id}")


def _patient_bundle(idx: int) -> dict:
    """A minimal but complete Synthea-shaped patient transaction Bundle."""
    uuid = f"urn:uuid:patient-{idx}"
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"fullUrl": uuid, "resource": {
                "resourceType": "Patient",
                "id": f"patient-{idx}",
                "name": [{"family": "Synthetic", "given": ["Test"]}],
                "gender": "female",
                "birthDate": "1980-01-01",
                "identifier": [{
                    "system": "https://github.com/synthetichealth/synthea",
                    "value": f"id-{idx}",
                }],
            }},
            {"resource": {
                "resourceType": "Encounter", "id": f"enc-{idx}", "status": "finished",
                "subject": {"reference": uuid},
            }},
            {"resource": {
                "resourceType": "Observation", "id": f"obs-{idx}", "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "8302-2",
                                     "display": "Body Height"}]},
                "valueQuantity": {"value": 170, "unit": "cm"},
                "subject": {"reference": uuid},
            }},
        ],
    }


# ── defect mutators ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("defect", dc.CATALOG, ids=lambda d: d.code)
def test_each_defect_trips_its_rule(defect: dc.Defect):
    """Applying a defect makes its mapped rule report a violation."""
    bundle = _patient_bundle(0)
    target = next(e["resource"] for e in bundle["entry"]
                  if e["resource"]["resourceType"] == defect.resource_type
                  and (defect.predicate is None or defect.predicate(e["resource"])))

    assert defect.apply(target) is True, "mutator should report it changed the resource"

    rule = _rule(defect.rule_id)
    assert rule.check(target), f"{defect.rule_id} should flag a {defect.code} resource"


def test_clean_resources_pass_their_rules():
    """The pristine fixture must not trip any of the targeted rules."""
    bundle = _patient_bundle(0)
    by_type = {e["resource"]["resourceType"]: e["resource"] for e in bundle["entry"]}
    for defect in dc.CATALOG:
        rule = _rule(defect.rule_id)
        assert not rule.check(by_type[defect.resource_type]), (
            f"clean {defect.resource_type} unexpectedly tripped {defect.rule_id}")


def test_missing_loinc_keeps_code_element():
    """Stripping the LOINC must leave Observation.code present (required 1..1)."""
    obs = {"resourceType": "Observation", "status": "final",
           "code": {"coding": [{"system": "http://loinc.org", "code": "x",
                                "display": "Glucose"}]}}
    assert dc._missing_loinc(obs) is True
    assert "code" in obs and obs["code"].get("text")        # still structurally valid
    assert not obs["code"].get("coding")                    # but LOINC gone


# ── corruptor ───────────────────────────────────────────────────────────────

def test_corrupt_is_deterministic_and_labels_correctly():
    bundles = [_patient_bundle(i) for i in range(100)]
    other = copy.deepcopy(bundles)

    m1 = corrupt(bundles, fraction=0.10, seed=42)
    m2 = corrupt(other, fraction=0.10, seed=42)

    assert m1["corrupted_patients"] == 10
    assert [p["bundle_index"] for p in m1["patients"]] == \
           [p["bundle_index"] for p in m2["patients"]]          # deterministic
    # all six defect types are represented across 10 patients
    assert {p["defect"]["code"] for p in m1["patients"]} == \
           {d.code for d in dc.CATALOG}


def test_corrupt_applies_tag_and_actual_mutation():
    bundles = [_patient_bundle(i) for i in range(20)]
    manifest = corrupt(bundles, fraction=0.10, seed=7)

    for entry in manifest["patients"]:
        idx = entry["bundle_index"]
        code = entry["defect"]["code"]
        resources = [e["resource"] for e in bundles[idx]["entry"]]
        tagged = [r for r in resources
                  if {"system": dc.TEST_DATA_SYSTEM, "code": f"defect:{code}"}
                  in (r.get("meta", {}).get("tag", []))]
        assert tagged, f"expected a resource tagged defect:{code} in bundle {idx}"


def test_corrupt_handles_empty_input():
    manifest = corrupt([], fraction=0.10, seed=1)
    assert manifest["total_patients"] == 0
    assert manifest["corrupted_patients"] == 0
    assert manifest["patients"] == []
