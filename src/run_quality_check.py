#!/usr/bin/env python3
"""Run data quality rules against clinical data in a Medplum database.

Fetches FHIR resources from Medplum, evaluates every applicable quality rule,
writes a per-violation CSV report to outputs/, and prints a summary.

Usage:
    python run_quality_check.py [options]

    Resource selection:
        --resource TYPE         # FHIR resource type to evaluate; repeatable.
                                # Defaults to [engine] resource_types in the cfg.
        --status STATUS         # extra FHIR search filter, e.g. --status final
        --limit N               # cap resources per type (0 = no limit)

    Engine:
        --fail-on {error,warning,none}   # min severity that exits non-zero
        --disable RULE_ID                # disable a rule by id; repeatable
        --page-size N                    # FHIR search page size

    I/O:
        --output PATH           # report CSV path (default: outputs/quality_report_<date>.csv)
        --config PATH           # path to quality_rules.cfg
        --from-file PATH        # read resources from a local NDJSON/Bundle file
                                #   instead of Medplum (offline mode)

Examples:
    # Evaluate Patients and Observations from Medplum
    python run_quality_check.py --resource Patient --resource Observation

    # Offline: run rules against a local synthetic Bundle
    python run_quality_check.py --from-file tests/fixtures/sample_bundle.json

    # CI gate: fail the build on any warning or error
    python run_quality_check.py --fail-on warning
"""

from __future__ import annotations

import argparse
import configparser
import json
import sys
from pathlib import Path

from quality_rules.base import Severity
from report import format_summary, report_filename, write_csv
from rule_engine import EngineResult, RuleEngine

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "quality_rules.cfg"
DEFAULT_OUTPUTS = PROJECT_ROOT / "outputs"


def _load_env() -> None:
    """Load MEDPLUM_* (and other) variables from the project's .env file.

    Real shell environment variables always win over .env values. If a .env
    file is present but python-dotenv isn't installed, warn loudly rather than
    silently skip it — otherwise the run fails later with a confusing
    "Missing credentials" error.
    """
    env_path = PROJECT_ROOT / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        if env_path.exists():
            print(
                f"WARNING: found {env_path} but python-dotenv is not installed in this "
                "interpreter, so it was NOT loaded.\n"
                "         Run with the project venv (.venv/bin/python) or install it:\n"
                "         python -m pip install python-dotenv",
                file=sys.stderr,
            )
        return
    load_dotenv(env_path, override=False)


# ── Config ────────────────────────────────────────────────────────────────

def load_config(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if path.exists():
        cfg.read(path)
    return cfg


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# ── Resource sources ────────────────────────────────────────────────────────

def resources_from_file(path: Path):
    """Yield FHIR resources from a local NDJSON file or a JSON Bundle.

    Useful for offline runs against synthetic fixtures (no Medplum needed).
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return
    # JSON Bundle?
    if text.lstrip().startswith("{"):
        doc = json.loads(text)
        if doc.get("resourceType") == "Bundle":
            for entry in doc.get("entry", []):
                resource = entry.get("resource")
                if resource is not None:
                    yield resource
        else:
            yield doc  # a single resource
        return
    # Otherwise treat as NDJSON (one resource per line).
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def resources_from_medplum(resource_types: list[str], params: dict, limit: int, page_size: int):
    """Yield resources of each requested type from Medplum."""
    from medplum_client import MedplumClient  # imported lazily so offline mode needs no creds

    with MedplumClient(page_size=page_size) as client:
        for resource_type in resource_types:
            yield from client.search(resource_type, params=params or None, limit=limit)


# ── CLI ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate clinical FHIR data from Medplum against data quality rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--resource", action="append", default=[],
                        help="FHIR resource type to evaluate (repeatable).")
    parser.add_argument("--status", default=None,
                        help="Optional FHIR 'status' search filter.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max resources per type (0 = no limit).")
    parser.add_argument("--fail-on", choices=["error", "warning", "none"], default=None,
                        help="Minimum severity that causes a non-zero exit code.")
    parser.add_argument("--disable", action="append", default=[],
                        help="Disable a rule by id (repeatable).")
    parser.add_argument("--page-size", type=int, default=None,
                        help="FHIR search page size.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Report CSV path.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Path to quality_rules.cfg.")
    parser.add_argument("--from-file", type=Path, default=None,
                        help="Read resources from a local NDJSON/Bundle file instead of Medplum.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_env()
    cfg = load_config(args.config)

    # Resolve settings: CLI flag > config file > built-in default.
    resource_types = args.resource or _csv_list(
        cfg.get("engine", "resource_types", fallback="Patient")
    )
    page_size = args.page_size or cfg.getint("medplum", "page_size", fallback=100)
    limit = args.limit if args.limit is not None else cfg.getint("medplum", "max_resources", fallback=0)
    fail_on = args.fail_on or cfg.get("engine", "fail_on", fallback="error")
    disabled = set(args.disable) | set(_csv_list(cfg.get("rules", "disabled", fallback="")))

    params: dict[str, str] = {}
    if args.status:
        params["status"] = args.status

    # Pick a resource source.
    if args.from_file:
        if not args.from_file.exists():
            print(f"ERROR: file not found: {args.from_file}", file=sys.stderr)
            return 2
        resources = resources_from_file(args.from_file)
    else:
        resources = resources_from_medplum(resource_types, params, limit, page_size)

    # Run the engine.
    engine = RuleEngine(disabled=disabled)
    result: EngineResult = engine.run(resources)

    # Report.
    output_path = args.output or (DEFAULT_OUTPUTS / report_filename())
    write_csv(result, output_path)
    print(format_summary(result))
    print(f"Report written to {output_path}")

    return _exit_code(result, fail_on)


def _exit_code(result: EngineResult, fail_on: str) -> int:
    """Map the run's max severity to a process exit code, per ``fail_on``."""
    if fail_on == "none":
        return 0
    threshold = Severity.from_str(fail_on)
    worst = result.max_severity()
    if worst is not None and worst.value >= threshold.value:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
