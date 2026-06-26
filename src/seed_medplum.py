#!/usr/bin/env python3
"""Seed a Medplum database with synthetic Synthea patients for quality testing.

Pipeline
--------
1. **Acquire**  a pre-generated Synthea population (FHIR R4 sample data).
2. **Tag**      every resource with a ``synthetic`` meta.tag so the whole load
                can be found and deleted later.
3. **Corrupt**  ~10% of patients with known data-quality defects, writing a
                ground-truth manifest to data/exports/.
4. **Load**     POST the shared info bundles first, then each patient
                transaction Bundle, to Medplum.

Each patient bundle is posted **whole** — Synthea wires its internal references
with ``urn:uuid``, which Medplum only resolves within a single transaction.

Usage
-----
    # Dry run: build + corrupt locally, write bundles + manifest, no network.
    python src/seed_medplum.py --dry-run

    # Smoke test: actually load 3 patients into Medplum.
    python src/seed_medplum.py --max-patients 3

    # Full load: 100 patients (large — ~100k+ resources).
    python src/seed_medplum.py --max-patients 100

Options:
    --max-patients N     patients to load (default 100; 0 = all available)
    --defect-fraction F  share of patients to corrupt (default 0.10)
    --seed N             RNG seed for the corruptor (default 1234)
    --source-dir PATH    extracted Synthea JSON dir (default data/raw/synthea/extracted)
    --download           download + unzip the Synthea archive if source-dir is empty
    --dry-run            write tagged/corrupted bundles + manifest locally; do not POST
    --manifest PATH      manifest output path (default data/exports/defect_manifest.json)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from seed.corruptor import corrupt
from seed.loader import (
    download_and_extract,
    filter_clinical,
    list_bundle_files,
    load_bundle,
    summarize_response,
    tag_bundle_synthetic,
)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "raw" / "synthea" / "extracted"
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "exports" / "defect_manifest.json"
DEFAULT_BUNDLES_OUT = PROJECT_ROOT / "data" / "exports" / "bundles"


def _load_env() -> None:
    """Load MEDPLUM_* from the project's .env (real env vars still win)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            print(
                f"WARNING: found {env_path} but python-dotenv is not installed; "
                "it was NOT loaded. Use the project venv (.venv/bin/python).",
                file=sys.stderr,
            )
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed Medplum with synthetic Synthea patients (with injected defects).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--max-patients", type=int, default=50,
                        help="Patients to load (default 50; 0 = all available).")
    parser.add_argument("--clinical-only", action="store_true",
                        help="Strip non-clinical resources (Claim, ExplanationOfBenefit, "
                             "Provenance, DocumentReference, etc.) to cut per-patient volume.")
    parser.add_argument("--defect-fraction", type=float, default=0.10,
                        help="Share of patients to corrupt (default 0.10).")
    parser.add_argument("--seed", type=int, default=1234,
                        help="RNG seed for the corruptor (default 1234).")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE,
                        help="Directory of extracted Synthea JSON bundles.")
    parser.add_argument("--download", action="store_true",
                        help="Download + unzip the Synthea archive if source-dir is empty.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write tagged/corrupted bundles + manifest locally; do not POST.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                        help="Manifest output path.")
    parser.add_argument("--bundles-out", type=Path, default=DEFAULT_BUNDLES_OUT,
                        help="Where --dry-run writes the prepared bundles.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ── 1. acquire ──────────────────────────────────────────────────────────
    source_dir: Path = args.source_dir
    if not any(source_dir.glob("*.json")):
        if args.download:
            print(f"Downloading Synthea sample data into {source_dir} ...")
            download_and_extract(source_dir)
        else:
            print(
                f"ERROR: no Synthea JSON found in {source_dir}.\n"
                "       Re-run with --download to fetch it, or point --source-dir "
                "at an extracted Synthea sample-data directory.",
                file=sys.stderr,
            )
            return 2

    info_files, patient_files = list_bundle_files(source_dir)
    if not patient_files:
        print(f"ERROR: no patient bundles found in {source_dir}", file=sys.stderr)
        return 2

    if args.max_patients and args.max_patients > 0:
        patient_files = patient_files[: args.max_patients]

    print(f"Loaded {len(patient_files)} patient bundle(s) and "
          f"{len(info_files)} info bundle(s) from {source_dir}")

    # ── 2. load, optionally filter, and tag every resource synthetic ────────
    patient_bundles = [load_bundle(p) for p in patient_files]
    info_bundles = [load_bundle(p) for p in info_files]

    if args.clinical_only:
        removed = sum(filter_clinical(b) for b in patient_bundles)
        print(f"Clinical-only filter removed {removed} non-clinical resource(s).")

    tagged = sum(tag_bundle_synthetic(b) for b in patient_bundles)
    tagged += sum(tag_bundle_synthetic(b) for b in info_bundles)
    print(f"Tagged {tagged} resources as synthetic.")

    # ── 3. corrupt ~fraction of patients (writes ground-truth manifest) ─────
    manifest = corrupt(patient_bundles, fraction=args.defect_fraction, seed=args.seed)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Injected defects into {manifest['corrupted_patients']} patient(s); "
          f"expected rule ids: {', '.join(manifest['expected_rule_ids']) or '(none)'}")
    print(f"Manifest written to {args.manifest}")

    # ── 4. load (or dry-run) ────────────────────────────────────────────────
    if args.dry_run:
        args.bundles_out.mkdir(parents=True, exist_ok=True)
        for src, bundle in zip(patient_files, patient_bundles):
            (args.bundles_out / src.name).write_text(json.dumps(bundle), encoding="utf-8")
        print(f"DRY RUN: wrote {len(patient_bundles)} prepared bundle(s) to "
              f"{args.bundles_out}. No data was sent to Medplum.")
        return 0

    return _post_all(info_bundles, patient_bundles, patient_files)


def _post_all(info_bundles, patient_bundles, patient_files) -> int:
    """POST info bundles first, then patient bundles, summarising results."""
    _load_env()
    from medplum_client import MedplumClient, MedplumError

    total_ok = 0
    total_err = 0
    with MedplumClient() as client:
        try:
            client.authenticate()
        except MedplumError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        print("\nPosting info bundles (Organizations / Practitioners) first ...")
        for bundle in info_bundles:
            ok, errors = _post_one(client, bundle)
            total_ok += ok
            total_err += len(errors)
            for msg in errors[:5]:
                print(f"  ! {msg}")

        print(f"\nPosting {len(patient_bundles)} patient bundle(s) ...")
        for i, (bundle, src) in enumerate(zip(patient_bundles, patient_files), start=1):
            try:
                ok, errors = _post_one(client, bundle)
            except MedplumError as exc:
                total_err += 1
                print(f"  [{i}/{len(patient_bundles)}] {src.name}: FAILED — {exc}")
                continue
            total_ok += ok
            total_err += len(errors)
            flag = "ok" if not errors else f"{len(errors)} entry error(s)"
            print(f"  [{i}/{len(patient_bundles)}] {src.name}: {ok} created, {flag}")
            for msg in errors[:3]:
                print(f"      ! {msg}")

    print(f"\nDone. {total_ok} resources created, {total_err} errors.")
    return 0 if total_err == 0 else 1


def _post_one(client, bundle: dict):
    response = client.post_bundle(bundle)
    return summarize_response(response)


if __name__ == "__main__":
    sys.exit(main())
