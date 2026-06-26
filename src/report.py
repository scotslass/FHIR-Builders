"""Report writer for quality-check runs.

Writes one CSV row per violation and prints a human-readable summary. Output
filenames follow the project convention: ``quality_report_{mm-dd-yyyy}.csv``.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from rule_engine import EngineResult

CSV_FIELDNAMES = ["rule_id", "severity", "status", "resource_type", "resource_id", "message"]


def report_filename(prefix: str = "quality_report") -> str:
    """Return a dated report filename like ``quality_report_06-23-2026.csv``."""
    return f"{prefix}_{date.today():%m-%d-%Y}.csv"


def write_csv(result: EngineResult, output_path: Path) -> Path:
    """Write all outcomes in ``result`` to ``output_path`` as CSV.

    One row per failure (``status=fail``) followed by one row per could-not-assess
    outcome (``status=could_not_assess``). The ``status`` column lets downstream
    consumers tell the two apart.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for violation in result.violations:
            writer.writerow(violation.as_row())
        for cna in result.could_not_assess:
            writer.writerow(cna.as_row())
    return output_path


def format_summary(result: EngineResult) -> str:
    """Build a multi-line summary of a run for stdout / a log file."""
    lines = [
        "── Quality check summary ──────────────────────────────",
        f"Resources checked : {result.resources_checked}",
    ]
    for resource_type, count in sorted(result.by_resource_type.items()):
        lines.append(f"  {resource_type or '(unknown)':<20} {count}")
    lines.append(f"Total violations  : {len(result.violations)}")
    severity_counts = result.severity_counts()
    for sev in ("error", "warning", "info"):
        if sev in severity_counts:
            lines.append(f"  {sev:<20} {severity_counts[sev]}")
    if result.could_not_assess:
        lines.append(f"Could not assess  : {len(result.could_not_assess)}")
    lines.append("───────────────────────────────────────────────────────")
    return "\n".join(lines)
