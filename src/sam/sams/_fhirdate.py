"""Lenient parser for FHIR ``date`` values, shared by date-oriented SAMs.

A FHIR ``date`` is one of ``YYYY``, ``YYYY-MM``, or ``YYYY-MM-DD`` (no time). We
must tolerate partial precision rather than assume a full date. Partial values
are normalized to the earliest valid calendar date they denote (``YYYY`` ->
Jan 1, ``YYYY-MM`` -> the 1st), which is sufficient for the "is a date" and
"is in the past" checks.

This is a small shared utility, not framework code — SAMs import it rather than
importing one another.
"""

from __future__ import annotations

import re
from datetime import date

# Matches a full FHIR date with optional month / day precision.
_FHIR_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def parse_fhir_date(value) -> date | None:
    """Parse a FHIR ``date`` string into a :class:`datetime.date`, or ``None``.

    Returns ``None`` for anything that is not a structurally valid FHIR date
    (wrong shape, or an impossible calendar value like ``2023-13-40``). Partial
    dates are filled to the earliest day they denote.
    """
    if not isinstance(value, str):
        return None
    match = _FHIR_DATE_RE.match(value.strip())
    if not match:
        return None
    year, month, day = match.group(1), match.group(2), match.group(3)
    try:
        return date(int(year), int(month) if month else 1, int(day) if day else 1)
    except ValueError:
        return None  # e.g. month 13 or day 40
