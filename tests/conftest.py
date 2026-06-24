"""Shared fixtures and helpers for the my-fhir-app test suite.

All test data here is SYNTHETIC — never add real patient data (PHI) to fixtures.

Structure
---------
tests/
    conftest.py                 ← this file: shared fixtures + synthetic data
    unit/                       ← unit tests per module
    fixtures/                   ← synthetic FHIR resource files
"""

import configparser
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Validation paths (read from config/validation.cfg) ───────────────────────

def _read_validation_cfg() -> tuple[Path | None, Path | None]:
    """Read input_resources / output_report from config/validation.cfg, if present."""
    cfg_path = Path(__file__).parent.parent / "config" / "validation.cfg"
    if not cfg_path.exists():
        return None, None
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path)
    section = "validation"
    in_val = cfg.get(section, "input_resources", fallback=None)
    out_val = cfg.get(section, "output_report", fallback=None)
    return (Path(in_val) if in_val else None,
            Path(out_val) if out_val else None)


@pytest.fixture()
def input_resources_path() -> Path | None:
    return _read_validation_cfg()[0]


@pytest.fixture()
def output_report_path() -> Path | None:
    return _read_validation_cfg()[1]


# ── Synthetic FHIR resources ────────────────────────────────────────────────

@pytest.fixture()
def valid_patient() -> dict:
    return {
        "resourceType": "Patient",
        "id": "patient-good",
        "name": [{"family": "Synthetic", "given": ["Ada"]}],
        "gender": "female",
        "birthDate": "1985-04-12",
    }


@pytest.fixture()
def patient_missing_birthdate() -> dict:
    return {
        "resourceType": "Patient",
        "id": "patient-missing-birthdate",
        "name": [{"family": "Testpatient", "given": ["Bob"]}],
        "gender": "male",
    }


@pytest.fixture()
def final_observation_no_value() -> dict:
    return {
        "resourceType": "Observation",
        "id": "obs-final-no-value",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
    }


@pytest.fixture()
def sample_bundle_resources() -> list[dict]:
    """All resources from tests/fixtures/sample_bundle.json."""
    bundle = json.loads((FIXTURES_DIR / "sample_bundle.json").read_text())
    return [entry["resource"] for entry in bundle.get("entry", [])]
