#!/usr/bin/env python3
"""Delete everything this tool seeded into Medplum (tagged ``synthetic``).

Searches each resource type for the synthetic meta.tag and deletes the matches,
making re-seeding repeatable.

NOTE ON VOLUME: a full 100-patient Synthea load is ~100k+ resources, so a full
delete issues a great many requests and can take a while. For throwaway test
data, the cleanest reset is often a disposable Medplum *Project* you can delete
wholesale — see the README. This script is the per-resource fallback.

Usage:
    python src/delete_test_patients.py --dry-run          # count what would go
    python src/delete_test_patients.py                    # delete (default types)
    python src/delete_test_patients.py --type Patient --type Observation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seed.loader import tag_query

PROJECT_ROOT = Path(__file__).parent.parent

# Resource types Synthea emits, ordered leaf-first so references are removed
# before the resources they point at (best-effort; Medplum allows dangling
# literal references, so order is not strictly required).
DEFAULT_TYPES = [
    "ExplanationOfBenefit", "Claim", "DiagnosticReport", "DocumentReference",
    "MedicationAdministration", "MedicationRequest", "Medication",
    "Immunization", "Procedure", "Observation", "CarePlan", "CareTeam",
    "Condition", "AllergyIntolerance", "Encounter", "Provenance",
    "SupplyDelivery", "Device", "ImagingStudy", "Patient",
    # Administrative resources created by the hospitalInformation /
    # practitionerInformation *info* bundles — must be cleaned up too, and
    # last, since clinical resources reference them.
    "PractitionerRole", "Practitioner", "HealthcareService", "Location",
    "Organization",
]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", action="append", default=[],
                        help="Resource type to clean (repeatable). Default: all Synthea types.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only count tagged resources; delete nothing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_env()
    from medplum_client import MedplumClient, MedplumError

    types = args.type or DEFAULT_TYPES
    params = tag_query()
    total = 0
    with MedplumClient() as client:
        try:
            client.authenticate()
        except MedplumError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        for resource_type in types:
            ids = [r["id"] for r in client.search(resource_type, params=dict(params))
                   if r.get("id")]
            if not ids:
                continue
            print(f"{resource_type}: {len(ids)} tagged resource(s)"
                  f"{' (dry run)' if args.dry_run else ''}")
            total += len(ids)
            if args.dry_run:
                continue
            for rid in ids:
                try:
                    client.delete(resource_type, rid)
                except MedplumError as exc:
                    print(f"  ! failed to delete {resource_type}/{rid}: {exc}")

    verb = "would delete" if args.dry_run else "deleted"
    print(f"\n{verb} {total} tagged resource(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
