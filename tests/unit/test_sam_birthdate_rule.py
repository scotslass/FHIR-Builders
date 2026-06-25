"""End-to-end acceptance: the birthDate SAM chain firing through the engine.

These cover the four acceptance criteria using FHIR ``Patient`` resources as the
fixtures, exercised through the normal ``RuleEngine`` path (no SAM-special code).
"""

from quality_rules.base import Severity
from quality_rules.sam_rules import PatientBirthDateIsValid
from rule_engine import RuleEngine

RULE_ID = "patient-birthdate-is-valid"


def patient(birth_date=...):
    p = {"resourceType": "Patient", "id": "p"}
    if birth_date is not ...:
        p["birthDate"] = birth_date
    return p


def run(p):
    return RuleEngine().run([p])


# ── Through the engine (the registered rule fires via the normal path) ──────────

def test_valid_past_birthdate_passes():
    result = run(patient("1992-03-14"))
    assert [v for v in result.violations if v.rule_id == RULE_ID] == []
    assert [c for c in result.could_not_assess if c.rule_id == RULE_ID] == []


def test_missing_birthdate_is_could_not_assess_not_fail():
    result = run(patient())  # no birthDate key at all
    cnas = [c for c in result.could_not_assess if c.rule_id == RULE_ID]
    assert len(cnas) == 1
    assert cnas[0].mnemonic == "Attr_IsPopulated"
    assert [v for v in result.violations if v.rule_id == RULE_ID] == []


def test_nondate_birthdate_is_could_not_assess():
    result = run(patient("not-a-date"))
    cnas = [c for c in result.could_not_assess if c.rule_id == RULE_ID]
    assert len(cnas) == 1
    assert cnas[0].mnemonic == "Attr_IsDate"
    assert [v for v in result.violations if v.rule_id == RULE_ID] == []


def test_future_birthdate_fails():
    result = run(patient("2999-01-01"))
    viols = [v for v in result.violations if v.rule_id == RULE_ID]
    assert len(viols) == 1
    assert viols[0].severity is Severity.WARNING
    assert [c for c in result.could_not_assess if c.rule_id == RULE_ID] == []


# ── The rule object directly (registration + projection) ────────────────────────

def test_rule_is_registered_and_applies_to_patient_only():
    rule = PatientBirthDateIsValid()
    assert rule.id == RULE_ID
    assert rule.applies_to(patient("1992-03-14")) is True
    assert rule.applies_to({"resourceType": "Observation"}) is False


def test_could_not_assess_does_not_trip_fail_gate():
    # The SAM rule runs alongside the legacy birthDate rules. Disable the legacy
    # presence rule so the only finding for a clean, birthDate-less patient is the
    # SAM chain's could-not-assess — which is not a violation, so max_severity
    # stays None and the fail_on gate is not tripped.
    clean_but_no_birthdate = {
        "resourceType": "Patient",
        "id": "p",
        "name": [{"family": "Synthetic", "given": ["Ada"]}],
        "gender": "female",
    }
    engine = RuleEngine(disabled={"patient-birthdate-present"})
    result = engine.run([clean_but_no_birthdate])
    assert result.violations == []
    assert result.max_severity() is None
    cnas = [c for c in result.could_not_assess if c.rule_id == RULE_ID]
    assert len(cnas) == 1
