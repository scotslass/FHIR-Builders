"""Shared quality-check orchestration.

A single place that builds a resource source (Medplum or a local file), runs the
rule engine, and returns the result. Both the CLI (``run_quality_check.py``) and
the web API import this, so they evaluate data through *identical* logic — there
is no second code path that could drift.

This module deliberately does no argument parsing, config loading, or reporting;
callers resolve their own settings and decide what to do with the result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from rule_engine import EngineResult, RuleEngine


# ── Coverage ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TypeCoverage:
    """How much of one resource type a run actually evaluated.

    ``total`` is the count available in the source (``None`` when unknown, e.g.
    offline file runs where there is no cheap total). ``truncated`` is True when
    a cap stopped the run short of everything available.
    """

    resource_type: str
    fetched: int
    total: int | None = None

    @property
    def truncated(self) -> bool:
        return self.total is not None and self.fetched < self.total


@dataclass
class CheckResult:
    """An engine run plus the coverage context needed to report it honestly."""

    engine: EngineResult
    coverage: list[TypeCoverage] = field(default_factory=list)
    cap: int = 0  # per-type limit applied (0 = no cap)

    @property
    def complete(self) -> bool:
        """True when no resource type was truncated by the cap."""
        return not any(c.truncated for c in self.coverage)


# ── Resource sources ─────────────────────────────────────────────────────────

def resources_from_file(path: Path) -> Iterator[dict]:
    """Yield FHIR resources from a local NDJSON file or a JSON Bundle.

    Useful for offline runs against synthetic fixtures (no Medplum needed).
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return
    # JSON Bundle (or a single resource)?
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


def resources_from_medplum(
    resource_types: list[str], params: dict, limit: int, page_size: int
) -> Iterator[dict]:
    """Yield resources of each requested type from Medplum."""
    from medplum_client import MedplumClient  # lazy import so offline mode needs no creds

    with MedplumClient(page_size=page_size) as client:
        for resource_type in resource_types:
            yield from client.search(resource_type, params=params or None, limit=limit)


# ── Orchestration ────────────────────────────────────────────────────────────

def run_check(
    *,
    resource_types: list[str] | None = None,
    disabled: set[str] | None = None,
    limit: int = 0,
    page_size: int = 100,
    params: dict[str, str] | None = None,
    from_file: Path | None = None,
) -> EngineResult:
    """Fetch resources from the chosen source and run the rule engine.

    Exactly one source is used: ``from_file`` if given, otherwise Medplum search
    over ``resource_types``. ``limit`` caps resources per type (0 = no cap).
    Returns the raw :class:`EngineResult`; for coverage-aware runs against
    Medplum use :func:`run_check_medplum`.
    """
    if from_file is not None:
        resources: Iterable[dict] = resources_from_file(from_file)
    else:
        resources = resources_from_medplum(
            resource_types or [], params or {}, limit, page_size
        )
    return RuleEngine(disabled=disabled).run(resources)


def run_check_medplum(
    *,
    resource_types: list[str],
    disabled: set[str] | None = None,
    limit: int = 0,
    page_size: int = 100,
    params: dict[str, str] | None = None,
) -> CheckResult:
    """Run a Medplum check and report per-type coverage (fetched vs available).

    Issues one cheap ``_summary=count`` request per resource type to learn the
    total available, then evaluates up to ``limit`` of each. The returned
    :class:`CheckResult` carries the coverage so callers can show "evaluated N of
    M" and flag any truncation. One open client connection is shared across the
    counts and the searches.
    """
    from medplum_client import MedplumClient  # lazy import so offline mode needs no creds

    engine = RuleEngine(disabled=disabled)
    result = EngineResult()
    coverage: list[TypeCoverage] = []
    with MedplumClient(page_size=page_size) as client:
        for resource_type in resource_types:
            total = client.count(resource_type, params=params or None)
            fetched = 0
            for resource in client.search(resource_type, params=params or None, limit=limit):
                fetched += 1
                result.resources_checked += 1
                result.by_resource_type[resource.get("resourceType", "")] += 1
                for record in engine.evaluate_resource(resource):
                    result.record(record)
            coverage.append(TypeCoverage(resource_type=resource_type, fetched=fetched, total=total))
    return CheckResult(engine=result, coverage=coverage, cap=limit)
