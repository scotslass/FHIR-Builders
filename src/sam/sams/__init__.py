"""Bundled SAM definitions.

Each import below registers a SAM via ``@register_sam`` (import-for-side-effect).
To add a new SAM: create a module in this package and add one import line here.
This is the single sanctioned registration edit — no other existing file changes.
"""

from sam.sams import attr_is_date  # noqa: F401
from sam.sams import attr_is_past_date  # noqa: F401
from sam.sams import attr_is_populated  # noqa: F401
