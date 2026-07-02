"""Tests for the local web API (src/web/app.py).

No network: the Medplum-backed run is monkeypatched. The TestClient uses a
``localhost`` base_url so the Host-header allowlist accepts it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quality_rules.base import Severity, Violation
from quality_service import CheckResult, TypeCoverage
from rule_engine import EngineResult
from web.app import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), base_url="http://localhost")


def test_resource_types_are_registry_derived(client):
    resp = client.get("/api/resource-types")
    assert resp.status_code == 200
    types = resp.json()["resource_types"]
    # The built-in rules cover at least these three.
    assert {"Patient", "Observation", "Encounter"} <= set(types)


def test_rules_listing(client):
    resp = client.get("/api/rules")
    assert resp.status_code == 200
    rules = resp.json()["rules"]
    assert rules and all({"id", "description", "severity", "resource_types"} <= r.keys() for r in rules)


def test_non_localhost_host_is_rejected():
    # A different base_url => Host header is not in the allowlist.
    evil = TestClient(create_app(), base_url="http://evil.example.com")
    resp = evil.get("/api/resource-types")
    assert resp.status_code == 403


def test_run_rejects_unknown_resource_type(client):
    resp = client.post("/api/run", json={"resource_types": ["NotAType"]})
    assert resp.status_code == 422
    assert "unknown resource type" in resp.json()["error"]


def test_run_rejects_unknown_rule_id(client):
    resp = client.post("/api/run", json={"rule_id": "no-such-rule"})
    assert resp.status_code == 422
    assert "unknown rule id" in resp.json()["error"]


def test_run_serializes_results_and_coverage(client, monkeypatch):
    """A successful run returns summary, coverage, and violation rows."""
    engine = EngineResult()
    engine.resources_checked = 2
    engine.by_resource_type["Patient"] = 2
    engine.record(Violation("patient-birthdate-present", Severity.ERROR, "Patient", "p1", "birthDate is missing"))
    fake = CheckResult(
        engine=engine,
        coverage=[TypeCoverage("Patient", fetched=2, total=10)],
        cap=2,
    )

    import web.app as appmod
    monkeypatch.setattr(appmod, "run_check_medplum", lambda **kw: fake)

    resp = client.post("/api/run", json={"resource_types": ["Patient"], "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["violations"] == 1
    assert data["complete"] is False  # 2 of 10 => truncated
    assert data["coverage"][0]["truncated"] is True
    assert data["violations"][0]["resource_id"] == "p1"


def test_run_surfaces_medplum_error_cleanly(client, monkeypatch):
    from medplum_client import MedplumError

    def boom(**kw):
        raise MedplumError("Missing Medplum credentials.")

    import web.app as appmod
    monkeypatch.setattr(appmod, "run_check_medplum", boom)

    resp = client.post("/api/run", json={})
    assert resp.status_code == 502
    assert "credentials" in resp.json()["error"]
