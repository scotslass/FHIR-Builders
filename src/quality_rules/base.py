"""Core types for data quality rules.

A rule inspects a single FHIR resource (a plain ``dict`` as returned by the
Medplum REST API) and reports zero or more violations. Subclass :class:`Rule`,
declare the resource types it applies to, and implement :meth:`Rule.check`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.IntEnum):
    """How serious a rule violation is.

    An ``IntEnum`` so members are orderable: ``Severity.ERROR > Severity.WARNING``.
    """

    INFO = 1
    WARNING = 2
    ERROR = 3

    def __str__(self) -> str:  # noqa: D105 - trivial
        return self.name.lower()

    @classmethod
    def from_str(cls, value: str) -> "Severity":
        """Parse a severity from its lowercase name (``error``/``warning``/``info``)."""
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown severity: {value!r}") from exc


@dataclass(frozen=True)
class Violation:
    """A single failed check against one resource."""

    rule_id: str
    severity: Severity
    resource_type: str
    resource_id: str
    message: str

    def as_row(self) -> dict[str, str]:
        """Flatten to a CSV-friendly dict."""
        return {
            "rule_id": self.rule_id,
            "severity": str(self.severity),
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "message": self.message,
        }


class Rule:
    """Base class for all data quality rules.

    Subclasses set the class attributes below and implement :meth:`check`.

    Attributes
    ----------
    id:
        Stable, kebab-case identifier (e.g. ``"patient-birthdate-present"``).
        Used to enable/disable rules and to label violations.
    description:
        Human-readable statement of what the rule enforces.
    severity:
        Default :class:`Severity` applied to violations this rule produces.
    resource_types:
        Tuple of FHIR resource type names the rule applies to. A rule only runs
        against resources whose ``resourceType`` is in this tuple.
    """

    id: str = ""
    description: str = ""
    severity: Severity = Severity.WARNING
    resource_types: tuple[str, ...] = ()

    def applies_to(self, resource: dict) -> bool:
        """Return True if this rule should run against ``resource``."""
        return resource.get("resourceType") in self.resource_types

    def check(self, resource: dict) -> list[str]:
        """Inspect ``resource`` and return a list of violation messages.

        An empty list means the resource passed this rule. Each message
        describes one problem and is paired with this rule's :attr:`severity`
        by the engine.
        """
        raise NotImplementedError

    def evaluate(self, resource: dict) -> list[Violation]:
        """Run :meth:`check` and wrap each message in a :class:`Violation`."""
        resource_type = resource.get("resourceType", "")
        resource_id = resource.get("id", "")
        return [
            Violation(
                rule_id=self.id,
                severity=self.severity,
                resource_type=resource_type,
                resource_id=resource_id,
                message=message,
            )
            for message in self.check(resource)
        ]
