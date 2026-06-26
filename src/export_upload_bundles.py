#!/usr/bin/env python3
"""Export drag-and-drop-ready FHIR Bundle files for the Medplum Batch tool.

Produces files you can drag into https://app.medplum.com/batch (a wrapper around
the FHIR batch/transaction API). Files are numbered in the required **upload
order**, because Synthea patient bundles reference Organizations/Practitioners by
conditional reference (``Organization?identifier=...``) that only resolve against
resources already loaded:

    00_hospitalInformation.json     <- upload 1st (Organizations + Locations)
    01_practitionerInformation.json <- upload 2nd (Practitioners)
    02_patient_00_<name>.json       <- upload 3rd, 4th, ...
    02_patient_01_<name>.json
    ...

Every resource is tagged ``synthetic`` (so it can be found/deleted later by
``_tag``). ~10% of patients carry injected data-quality defects; the ground
truth is written to ``defect_manifest.json`` and the upload list to
``UPLOAD_ORDER.md``.

Patient files larger than --max-bytes (Medplum's sync body limit is ~8 MB) are
skipped and reported, so every emitted file uploads cleanly.

Usage:
    python src/export_upload_bundles.py                       # 50 patients, clinical-only
    python src/export_upload_bundles.py --max-patients 100 --no-clinical-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from seed.corruptor import corrupt
from seed.loader import (
    filter_clinical,
    list_bundle_files,
    load_bundle,
    tag_bundle_synthetic,
)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "raw" / "synthea" / "extracted"
DEFAULT_OUT = PROJECT_ROOT / "data" / "exports" / "upload"


def _safe_name(filename: str) -> str:
    """First name token from a Synthea filename, e.g. 'Adriana394'."""
    return filename.split("_")[0]


def _write(path: Path, bundle: dict) -> int:
    """Write a bundle and return its size in bytes."""
    data = json.dumps(bundle)
    path.write_text(data, encoding="utf-8")
    return len(data.encode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export numbered, drag-and-drop-ready bundle files for Medplum.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-patients", type=int, default=50,
                        help="Number of patient files to emit (default 50).")
    parser.add_argument("--clinical-only", action="store_true", default=True,
                        help="Strip non-clinical resources to shrink files (default on).")
    parser.add_argument("--no-clinical-only", dest="clinical_only", action="store_false")
    parser.add_argument("--defect-fraction", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--max-bytes", type=int, default=7_000_000,
                        help="Skip patient files larger than this (Medplum limit ~8 MB).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not any(args.source_dir.glob("*.json")):
        print(f"ERROR: no Synthea JSON in {args.source_dir}. Run seed_medplum.py "
              "--download first, or point --source-dir at an extracted set.",
              file=sys.stderr)
        return 2

    info_files, patient_files = list_bundle_files(args.source_dir)
    patient_files = patient_files[: args.max_patients] if args.max_patients > 0 else patient_files

    args.out.mkdir(parents=True, exist_ok=True)
    order: list[str] = []

    # ── info bundles (upload first) ─────────────────────────────────────────
    info_map = {"hospitalInformation": "00_hospitalInformation.json",
                "practitionerInformation": "01_practitionerInformation.json"}
    for src in info_files:
        out_name = next((v for k, v in info_map.items() if src.name.startswith(k)), None)
        if out_name is None:
            continue
        bundle = load_bundle(src)
        tag_bundle_synthetic(bundle)
        size = _write(args.out / out_name, bundle)
        order.append(out_name)
        print(f"info  {out_name}  ({size/1_000_000:.2f} MB, {len(bundle.get('entry', []))} entries)")

    # ── patient bundles: load, filter, tag ──────────────────────────────────
    bundles = [load_bundle(p) for p in patient_files]
    if args.clinical_only:
        removed = sum(filter_clinical(b) for b in bundles)
        print(f"clinical-only filter removed {removed} non-clinical resources")
    for b in bundles:
        tag_bundle_synthetic(b)

    # ── drop oversized bundles BEFORE corrupting, so the manifest (ground
    #    truth) covers exactly the files that get emitted ──────────────────────
    keep: list[tuple[Path, dict]] = []
    skipped = 0
    for src, bundle in zip(patient_files, bundles):
        size = len(json.dumps(bundle).encode("utf-8"))
        if size > args.max_bytes:
            skipped += 1
            print(f"SKIP  {_safe_name(src.name)}  ({size/1_000_000:.2f} MB > limit)")
        else:
            keep.append((src, bundle))

    kept_bundles = [b for _, b in keep]
    manifest = corrupt(kept_bundles, fraction=args.defect_fraction, seed=args.seed)
    corrupted_idx = {p["bundle_index"] for p in manifest["patients"] if p["defect"]["applied"]}

    # ── write the kept patient files, numbered contiguously ─────────────────
    written = 0
    for i, (src, bundle) in enumerate(keep):
        defect = "  [DEFECT]" if i in corrupted_idx else ""
        out_name = f"02_patient_{i:02d}_{_safe_name(src.name)}.json"
        size = _write(args.out / out_name, bundle)
        order.append(out_name)
        written += 1
        print(f"pat   {out_name}  ({size/1_000_000:.2f} MB){defect}")

    # ── manifest + human-readable upload order ──────────────────────────────
    (args.out / "defect_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_order_doc(args.out, order, manifest, skipped)

    print(f"\nWrote {written} patient file(s) ({skipped} skipped for size) + "
          f"{len(info_files)} info file(s) to {args.out}")
    print(f"Upload order is documented in {args.out / 'UPLOAD_ORDER.md'}")
    return 0


def _write_order_doc(out: Path, order: list[str], manifest: dict, skipped: int) -> None:
    lines = [
        "# Medplum upload order",
        "",
        "Upload these files at <https://app.medplum.com/batch> **in this order**.",
        "The two info files MUST go first — patient bundles reference their",
        "Organizations/Practitioners by identifier. Do not upload a file twice.",
        "",
    ]
    for n, name in enumerate(order, start=1):
        lines.append(f"{n}. `{name}`")
    lines += [
        "",
        f"- Patients corrupted with defects: **{manifest['corrupted_patients']}** "
        f"(see `defect_manifest.json`).",
        f"- Expected quality-rule violations: {', '.join(manifest['expected_rule_ids']) or '(none)'}.",
    ]
    if skipped:
        lines.append(f"- {skipped} patient file(s) skipped for exceeding the size limit.")
    (out / "UPLOAD_ORDER.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
