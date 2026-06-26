"""Unit tests for the rule engine and report aggregation."""

from quality_rules.base import Severity
from rule_engine import RuleEngine


def test_engine_counts_resources(sample_bundle_resources):
    result = RuleEngine().run(sample_bundle_resources)
    assert result.resources_checked == len(sample_bundle_resources)
    assert result.by_resource_type["Patient"] == 3
    assert result.by_resource_type["Observation"] == 2
    assert result.by_resource_type["Encounter"] == 2


def test_engine_finds_expected_violations(sample_bundle_resources):
    result = RuleEngine().run(sample_bundle_resources)
    # The clean resources should produce no violations against themselves.
    flagged_ids = {v.resource_id for v in result.violations}
    assert "patient-good" not in flagged_ids
    assert "obs-good" not in flagged_ids
    assert "enc-good" not in flagged_ids
    # The seeded-bad resources should be flagged.
    assert "patient-missing-birthdate" in flagged_ids
    assert "patient-bad-gender-noname" in flagged_ids
    assert "obs-final-no-value" in flagged_ids
    assert "enc-no-subject" in flagged_ids


def test_engine_max_severity(sample_bundle_resources):
    result = RuleEngine().run(sample_bundle_resources)
    assert result.max_severity() == Severity.ERROR


def test_disabling_a_rule_removes_its_violations(sample_bundle_resources):
    baseline = RuleEngine().run(sample_bundle_resources)
    filtered = RuleEngine(disabled={"patient-birthdate-present"}).run(sample_bundle_resources)
    assert len(filtered.violations) < len(baseline.violations)
    assert all(v.rule_id != "patient-birthdate-present" for v in filtered.violations)


def test_clean_resource_has_no_violations(valid_patient):
    result = RuleEngine().run([valid_patient])
    assert result.violations == []
    assert result.max_severity() is None
