#!/usr/bin/env python3
"""Load a folder of prepared FHIR bundle files into Medplum via the async API.

This is the reliable bulk-load path for hosted Medplum: each bundle is posted
with ``Prefer: respond-async``, so the work runs in a background job that does
NOT consume the FHIR interaction rate limit. (Drag-and-drop and synchronous
POSTs share that limit and get throttled — async does not.)

Designed for an iterative workflow — generate more patient files with
``export_upload_bundles.py``, then re-run this; it is **idempotent for
patients**: any patient already present (matched by its Synthea identifier) is
skipped, so only new patients are added.

Expected folder layout (as produced by export_upload_bundles.py):

    00_hospitalInformation.json     (info: Organizations + Locations)
    01_practitionerInformation.json (info: Practitioners)
    02_patient_*.json               (one transaction Bundle per patient)

Order is enforced: info bundles first (patient conditional references resolve
against them), patients second.

Usage:
    python src/load_bundles_async.py                       # load data/exports/upload
    python src/load_bundles_async.py --dir data/exports/upload --force-info
    python src/load_bundles_async.py --no-skip-loaded      # re-post even existing patients
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from seed.defect_catalog import SYNTHETIC_TAG, TEST_DATA_SYSTEM
from seed.loader import (
    SYNTHEA_IDENTIFIER_SYSTEM,
    bundle_has_patient,
    load_bundle,
    patient_identifier,
)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DIR = PROJECT_ROOT / "data" / "exports" / "upload"
TAG = f"{TEST_DATA_SYSTEM}|{SYNTHETIC_TAG['code']}"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Async-load a folder of FHIR bundle files into Medplum.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                        help="Folder of prepared bundle files (default data/exports/upload).")
    parser.add_argument("--skip-loaded", action="store_true", default=True,
                        help="Skip patients already in Medplum (default on).")
    parser.add_argument("--no-skip-loaded", dest="skip_loaded", action="store_false")
    parser.add_argument("--force-info", action="store_true",
                        help="Post info bundles even if Organizations are already present.")
    parser.add_argument("--poll-timeout", type=int, default=900,
                        help="Max seconds to wait for submitted patient jobs (default 900).")
    parser.add_argument("--poll-interval", type=int, default=8,
                        help="Seconds between progress polls (default 8).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dir.is_dir():
        print(f"ERROR: not a directory: {args.dir}", file=sys.stderr)
        return 2

    files = sorted(args.dir.glob("*.json"))
    info_files, patient_files = [], []
    for path in files:
        if path.name in ("defect_manifest.json",):
            continue
        bundle = load_bundle(path)
        (patient_files if bundle_has_patient(bundle) else info_files).append((path, bundle))
    if not info_files and not patient_files:
        print(f"ERROR: no bundle files found in {args.dir}", file=sys.stderr)
        return 2
    print(f"Found {len(info_files)} info bundle(s) and {len(patient_files)} patient bundle(s) "
          f"in {args.dir}")

    _load_env()
    from medplum_client import MedplumClient, MedplumError

    with MedplumClient() as client:
        try:
            client.authenticate()
        except MedplumError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        # ── info bundles first (idempotent: ifNoneExist server-side) ─────────
        already = client.count("Organization", {"_tag": TAG})
        if already and not args.force_info:
            print(f"Skipping info bundles — {already} synthetic Organization(s) already "
                  f"present (use --force-info to re-post).")
        else:
            for path, bundle in info_files:
                _submit_and_wait(client, path.name, bundle, args)

        # ── patients (idempotent by Synthea identifier) ─────────────────────
        start_count = client.count("Patient", {"_tag": TAG})
        submitted: list[tuple[str, str]] = []   # (label, job_url)
        skipped = 0
        for path, bundle in patient_files:
            ident = patient_identifier(bundle)
            if args.skip_loaded and ident and client.count(
                    "Patient", {"identifier": f"{SYNTHEA_IDENTIFIER_SYSTEM}|{ident}"}):
                skipped += 1
                continue
            try:
                job = client.post_bundle_async(bundle)
                submitted.append((path.name, job))
                print(f"  submitted {path.name}")
            except MedplumError as exc:
                print(f"  ! {path.name} not accepted: {exc}")

        print(f"\nSubmitted {len(submitted)} patient job(s); skipped {skipped} already loaded.")
        if submitted:
            _wait_for_patients(client, start_count + len(submitted), args)

        final = client.count("Patient", {"_tag": TAG})
        print(f"\nTagged Patients now in Medplum: {final}")
        return 0


def _submit_and_wait(client, name: str, bundle: dict, args) -> None:
    """Submit one info bundle async and wait for its job to finish."""
    from medplum_client import MedplumError
    try:
        job = client.post_bundle_async(bundle)
    except MedplumError as exc:
        print(f"  ! {name} not accepted: {exc}")
        return
    print(f"  posting {name} (async) ...")
    deadline = time.time() + args.poll_timeout
    while time.time() < deadline:
        code, status = client.async_job_status(job)
        if code == 200:
            print(f"    {name}: job {status}")
            return
        time.sleep(args.poll_interval)
    print(f"    {name}: still processing server-side (poll timeout)")


def _wait_for_patients(client, target: int, args) -> None:
    """Poll the tagged Patient count until it reaches ``target`` or times out.

    Patient count is a clean completion signal: each patient transaction creates
    exactly one Patient, and it's far cheaper than polling every job.
    """
    deadline = time.time() + args.poll_timeout
    while time.time() < deadline:
        current = client.count("Patient", {"_tag": TAG})
        print(f"  progress: {current}/{target} patients loaded", flush=True)
        if current >= target:
            return
        time.sleep(args.poll_interval)
    print("  poll timeout — some jobs may still be processing server-side; "
          "re-run later to confirm (already-loaded patients will be skipped).")


if __name__ == "__main__":
    sys.exit(main())
