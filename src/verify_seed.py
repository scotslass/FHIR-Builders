#!/usr/bin/env python3
"""Cross-check a quality report against the seed defect manifest.

After seeding and running ``run_quality_check.py``, this confirms the engine
actually flagged the defects we injected: every ``rule_id`` named in the
manifest should appear in the report. It is a coarse, rule-level check (did the
rule fire at all?), not a per-resource match — that's enough to confirm the
seeded defects are being caught.

Usage:
    python src/verify_seed.py                         # newest report in outputs/
    python src/verify_seed.py --report outputs/quality_report_06-23-2026.csv
    python src/verify_seed.py --manifest data/exports/defect_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "exports" / "defect_manifest.json"
DEFAULT_OUTPUTS = PROJECT_ROOT / "outputs"


def _newest_report(outputs_dir: Path) -> Path | None:
    reports = sorted(outputs_dir.glob("quality_report_*.csv"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=None,
                        help="Quality report CSV (default: newest in outputs/).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.manifest.exists():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = set(manifest.get("expected_rule_ids", []))

    report_path = args.report or _newest_report(DEFAULT_OUTPUTS)
    if not report_path or not report_path.exists():
        print("ERROR: no quality report found. Run run_quality_check.py first.",
              file=sys.stderr)
        return 2

    fired: set[str] = set()
    with report_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("rule_id"):
                fired.add(row["rule_id"])

    caught = sorted(expected & fired)
    missed = sorted(expected - fired)

    print(f"Manifest:  {args.manifest}")
    print(f"Report:    {report_path}")
    print(f"Corrupted patients: {manifest.get('corrupted_patients')}")
    print(f"\nExpected rule ids ({len(expected)}):")
    for rule_id in sorted(expected):
        mark = "OK " if rule_id in fired else "!! "
        print(f"  {mark}{rule_id}")

    if missed:
        print(f"\nFAIL: {len(missed)} expected rule(s) did not fire: "
              f"{', '.join(missed)}")
        return 1
    print(f"\nPASS: all {len(caught)} expected rule(s) fired in the report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
