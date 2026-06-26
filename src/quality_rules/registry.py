"""Rule registry and the ``@register`` decorator.

Rule classes register themselves at import time. The engine asks the registry
for all rules, optionally filtered by resource type or a disabled-id set.
"""

from __future__ import annotations

from quality_rules.base import Rule

# Maps rule id -> Rule subclass. Populated by the @register decorator.
_REGISTRY: dict[str, type[Rule]] = {}


def register(rule_cls: type[Rule]) -> type[Rule]:
    """Class decorator that adds a :class:`Rule` subclass to the registry.

    Raises ``ValueError`` if the rule has no ``id`` or if its id collides with
    an already-registered rule.
    """
    if not rule_cls.id:
        raise ValueError(f"{rule_cls.__name__} must define a non-empty `id`")
    if rule_cls.id in _REGISTRY:
        raise ValueError(f"duplicate rule id: {rule_cls.id!r}")
    _REGISTRY[rule_cls.id] = rule_cls
    return rule_cls


def all_rules(disabled: set[str] | None = None) -> list[Rule]:
    """Return instances of every registered rule, minus any disabled ids."""
    disabled = disabled or set()
    return [cls() for rule_id, cls in _REGISTRY.items() if rule_id not in disabled]


def rules_for(resource_type: str, disabled: set[str] | None = None) -> list[Rule]:
    """Return rule instances that apply to ``resource_type``."""
    return [r for r in all_rules(disabled) if resource_type in r.resource_types]


def clear() -> None:
    """Empty the registry. Intended for tests."""
    _REGISTRY.clear()
