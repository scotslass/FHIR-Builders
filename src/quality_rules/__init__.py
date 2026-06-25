"""Data quality rules package.

Importing this package registers all bundled rules so the engine can discover
them via :mod:`quality_rules.registry`.
"""

from quality_rules import builtin  # noqa: F401  (import for side-effect: registration)
from quality_rules import sam_rules  # noqa: F401  (import for side-effect: registration)
from quality_rules import sam_rules_proof  # noqa: F401  (pluggability proof)

__all__ = ["base", "registry", "builtin", "sam_rules", "sam_rules_proof"]
