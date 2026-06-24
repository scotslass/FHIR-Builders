"""Unit tests for the bundled quality rules."""

from quality_rules.builtin import (
    EncounterHasSubject,
    ObservationHasValue,
    PatientGenderValid,
    PatientHasBirthDate,
    PatientHasName,
)


def test_valid_patient_passes_all(valid_patient):
    assert PatientHasName().check(valid_patient) == []
    assert PatientHasBirthDate().check(valid_patient) == []
    assert PatientGenderValid().check(valid_patient) == []


def test_missing_birthdate_flagged(patient_missing_birthdate):
    # The fixture has no birthDate → one violation.
    assert len(PatientHasBirthDate().check(patient_missing_birthdate)) == 1
    # Adding a birthDate clears it.
    patient_missing_birthdate["birthDate"] = "1990-01-01"
    assert PatientHasBirthDate().check(patient_missing_birthdate) == []


def test_invalid_gender_flagged():
    bad = {"resourceType": "Patient", "id": "x", "gender": "M"}
    assert len(PatientGenderValid().check(bad)) == 1


def test_patient_missing_name_flagged():
    no_name = {"resourceType": "Patient", "id": "x", "gender": "male"}
    assert len(PatientHasName().check(no_name)) == 1


def test_final_observation_without_value_flagged(final_observation_no_value):
    assert len(ObservationHasValue().check(final_observation_no_value)) == 1


def test_preliminary_observation_without_value_ok():
    prelim = {"resourceType": "Observation", "id": "x", "status": "preliminary",
              "code": {"coding": [{"code": "1"}]}}
    assert ObservationHasValue().check(prelim) == []


def test_encounter_without_subject_flagged():
    enc = {"resourceType": "Encounter", "id": "x", "status": "finished"}
    assert len(EncounterHasSubject().check(enc)) == 1


def test_rule_applies_to_only_declared_types(valid_patient):
    # An Observation rule should not consider a Patient.
    assert ObservationHasValue().applies_to(valid_patient) is False
    assert PatientHasName().applies_to(valid_patient) is True
