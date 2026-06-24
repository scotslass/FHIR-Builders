"""Data quality rule engine.

Given an iterable of FHIR resources, runs every applicable registered rule
against each one and collects the resulting violations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

import quality_rules  # noqa: F401  ensures builtin rules are registered
from quality_rules.base import Severity, Violation
from quality_rules.registry import rules_for


@dataclass
class EngineResult:
    """Aggregated outcome of a quality-check run."""

    violations: list[Violation] = field(default_factory=list)
    resources_checked: int = 0
    by_resource_type: Counter = field(default_factory=Counter)

    def severity_counts(self) -> dict[str, int]:
        """Return {severity_name: count} across all violations."""
        counts: Counter = Counter(str(v.severity) for v in self.violations)
        return dict(counts)

    def max_severity(self) -> Severity | None:
        """Highest severity seen across all violations, or None if clean."""
        if not self.violations:
            return None
        return max(v.severity for v in self.violations)


class RuleEngine:
    """Evaluates resources against the registered rule set.

    Parameters
    ----------
    disabled:
        Rule ids to skip for this run.
    """

    def __init__(self, disabled: set[str] | None = None) -> None:
        self.disabled = disabled or set()
        # Cache rule lookups per resource type to avoid re-filtering each time.
        self._rule_cache: dict[str, list] = {}

    def _rules_for(self, resource_type: str) -> list:
        if resource_type not in self._rule_cache:
            self._rule_cache[resource_type] = rules_for(resource_type, self.disabled)
        return self._rule_cache[resource_type]

    def evaluate_resource(self, resource: dict) -> list[Violation]:
        """Run every applicable rule against a single resource."""
        resource_type = resource.get("resourceType", "")
        violations: list[Violation] = []
        for rule in self._rules_for(resource_type):
            violations.extend(rule.evaluate(resource))
        return violations

    def run(self, resources: Iterable[dict]) -> EngineResult:
        """Evaluate every resource in ``resources`` and aggregate the results."""
        result = EngineResult()
        for resource in resources:
            result.resources_checked += 1
            result.by_resource_type[resource.get("resourceType", "")] += 1
            result.violations.extend(self.evaluate_resource(resource))
        return result
