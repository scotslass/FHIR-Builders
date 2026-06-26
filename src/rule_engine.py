"""Data quality rule engine.

Given an iterable of FHIR resources, runs every applicable registered rule
against each one and collects the resulting violations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

import quality_rules  # noqa: F401  ensures builtin rules are registered
from quality_rules.base import CouldNotAssess, Severity, Violation
from quality_rules.registry import rules_for


@dataclass
class EngineResult:
    """Aggregated outcome of a quality-check run.

    ``violations`` holds ``FAIL`` outcomes (as before). ``could_not_assess`` is a
    separate channel for ``COULD_NOT_ASSESS`` outcomes — kept distinct so they
    are not scored as failures and never affect :meth:`max_severity` or the
    ``fail_on`` exit gate.
    """

    violations: list[Violation] = field(default_factory=list)
    could_not_assess: list[CouldNotAssess] = field(default_factory=list)
    resources_checked: int = 0
    by_resource_type: Counter = field(default_factory=Counter)

    def severity_counts(self) -> dict[str, int]:
        """Return {severity_name: count} across all violations."""
        counts: Counter = Counter(str(v.severity) for v in self.violations)
        return dict(counts)

    def max_severity(self) -> Severity | None:
        """Highest severity seen across all violations, or None if clean.

        Could-not-assess outcomes are excluded by design.
        """
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

    def evaluate_resource(self, resource: dict) -> list:
        """Run every applicable rule against a single resource.

        Returns a flat list of outcome records. A record is a :class:`Violation`
        (``FAIL``) or a :class:`CouldNotAssess` (``COULD_NOT_ASSESS``); rules that
        pass contribute nothing. Existing rules only ever return ``Violation``s,
        so their behavior is unchanged.
        """
        resource_type = resource.get("resourceType", "")
        records: list = []
        for rule in self._rules_for(resource_type):
            records.extend(rule.evaluate(resource))
        return records

    def run(self, resources: Iterable[dict]) -> EngineResult:
        """Evaluate every resource in ``resources`` and aggregate the results."""
        result = EngineResult()
        for resource in resources:
            result.resources_checked += 1
            result.by_resource_type[resource.get("resourceType", "")] += 1
            for record in self.evaluate_resource(resource):
                if isinstance(record, CouldNotAssess):
                    result.could_not_assess.append(record)
                else:
                    result.violations.append(record)
        return result
