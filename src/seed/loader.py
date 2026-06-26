"""Load Synthea sample bundles, tag them synthetic, and post them to Medplum.

Responsibilities
----------------
* download + unzip the Synthea "sample data, FHIR R4" archive (once),
* split the files into the two shared *info* bundles (Organizations /
  Practitioners) and the per-patient bundles,
* stamp every resource with the ``synthetic`` tag,
* POST bundles to Medplum in the required order (info first, patients second),
  summarising per-entry success/failure.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from seed.defect_catalog import SYNTHETIC_TAG, TEST_DATA_SYSTEM

# Canonical Synthea sample-data download (latest, FHIR R4). ~30 MB, ~113
# patients plus hospitalInformation / practitionerInformation bundles.
SYNTHEA_URL = (
    "https://synthetichealth.github.io/synthea-sample-data/downloads/latest/"
    "synthea_sample_data_fhir_latest.zip"
)

_INFO_PREFIXES = ("hospitalInformation", "practitionerInformation")

# Stable identifier Synthea stamps on every Patient — used to detect whether a
# patient is already loaded (idempotent re-runs).
SYNTHEA_IDENTIFIER_SYSTEM = "https://github.com/synthetichealth/synthea"

# Resource types stripped by the clinical-only filter: financial, document and
# provenance "noise" that the quality engine doesn't evaluate. This exact set is
# verified reference-safe against the Synthea sample data — no retained clinical
# resource references any of these via an in-bundle ``urn:uuid``, so removing
# them never breaks a transaction. (Re-check with the scan in the README before
# adding a type here.)
NON_CLINICAL_TYPES = frozenset({
    "Claim", "ExplanationOfBenefit", "Provenance", "DocumentReference",
    "SupplyDelivery", "Device", "ImagingStudy",
})


# ── acquisition ─────────────────────────────────────────────────────────────

def download_and_extract(dest_dir: Path, url: str = SYNTHEA_URL) -> Path:
    """Download the Synthea zip and extract its JSON into ``dest_dir``.

    Returns ``dest_dir``. Skips the download if the directory already holds
    extracted ``*.json`` files.
    """
    import httpx

    dest_dir.mkdir(parents=True, exist_ok=True)
    if any(dest_dir.glob("*.json")):
        return dest_dir
    with httpx.Client(timeout=300.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for member in zf.namelist():
            if member.endswith(".json"):
                # flatten any internal directory structure
                target = dest_dir / Path(member).name
                target.write_bytes(zf.read(member))
    return dest_dir


# ── discovery ───────────────────────────────────────────────────────────────

def _is_info_file(path: Path) -> bool:
    return path.name.startswith(_INFO_PREFIXES)


def list_bundle_files(source_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return ``(info_files, patient_files)`` found under ``source_dir``.

    Patient files are sorted by name for deterministic ordering/sampling.
    """
    json_files = sorted(source_dir.glob("*.json"))
    info = [p for p in json_files if _is_info_file(p)]
    patients = [p for p in json_files if not _is_info_file(p)]
    return info, patients


def load_bundle(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bundle_has_patient(bundle: dict) -> bool:
    """True if the Bundle contains a Patient resource (i.e. it's a patient file)."""
    return any((e.get("resource") or {}).get("resourceType") == "Patient"
               for e in bundle.get("entry", []))


def patient_identifier(bundle: dict) -> str | None:
    """Return the Synthea Patient identifier value in a bundle, if present.

    Used to check whether a patient is already loaded before re-posting (the
    patient bundles use POST, which is not idempotent on its own).
    """
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") != "Patient":
            continue
        for ident in resource.get("identifier", []):
            if ident.get("system") == SYNTHEA_IDENTIFIER_SYSTEM and ident.get("value"):
                return ident["value"]
        return None
    return None


def filter_clinical(bundle: dict) -> int:
    """Drop :data:`NON_CLINICAL_TYPES` entries from a Bundle in place.

    Returns the number of entries removed. Reduces per-patient volume (helps
    with Medplum's request-size and rate limits) without breaking referential
    integrity — see the note on :data:`NON_CLINICAL_TYPES`.
    """
    entries = bundle.get("entry", [])
    kept = [e for e in entries
            if (e.get("resource") or {}).get("resourceType") not in NON_CLINICAL_TYPES]
    removed = len(entries) - len(kept)
    bundle["entry"] = kept
    return removed


# ── tagging ─────────────────────────────────────────────────────────────────

def tag_bundle_synthetic(bundle: dict) -> int:
    """Stamp every resource in a Bundle with the synthetic meta.tag.

    Returns the number of resources tagged. Idempotent.
    """
    count = 0
    for entry in bundle.get("entry", []):
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            continue
        meta = resource.setdefault("meta", {})
        tags = meta.setdefault("tag", [])
        if SYNTHETIC_TAG not in tags:
            tags.append(dict(SYNTHETIC_TAG))
        count += 1
    return count


# ── posting ─────────────────────────────────────────────────────────────────

def summarize_response(response_bundle: dict) -> tuple[int, list[str]]:
    """Return ``(ok_count, error_messages)`` from a Medplum response Bundle."""
    ok = 0
    errors: list[str] = []
    for entry in response_bundle.get("entry", []):
        status = str((entry.get("response") or {}).get("status", ""))
        if status[:1] in ("2",):
            ok += 1
        else:
            outcome = (entry.get("response") or {}).get("outcome", {})
            detail = ""
            for issue in outcome.get("issue", []) if isinstance(outcome, dict) else []:
                detail = issue.get("diagnostics") or issue.get("details", {}).get("text", "")
                if detail:
                    break
            errors.append(f"{status} {detail}".strip())
    return ok, errors


def tag_query() -> dict[str, str]:
    """FHIR search param selecting all resources this tool wrote."""
    return {"_tag": f"{TEST_DATA_SYSTEM}|{SYNTHETIC_TAG['code']}"}
