"""Core types for PIQI Simple Assessment Modules (SAMs).

A SAM is a small, named, composable check from the HL7 PIQI Framework. It takes a
typed input (here, a PIQI Simple Attribute) and returns one of three outcomes:
``PASS``, ``FAIL``, or ``COULD_NOT_ASSESS``. A SAM may declare a prerequisite SAM
(by mnemonic) that must pass before it is meaningful to run.

Subclass :class:`SAM`, set the declarative metadata attributes, and implement
:meth:`SAM.evaluate`. Metadata stays as class attributes so a future data-driven
loader (PIQI SAM definition JSON) could populate them without code changes, and
so existing logging/reporting can show human-readable aliases at runtime.
"""

from __future__ import annotations

import enum


class Outcome(enum.Enum):
    """The result of evaluating a SAM (or a SAM chain)."""

    PASS = "pass"
    FAIL = "fail"
    COULD_NOT_ASSESS = "could_not_assess"

    def __str__(self) -> str:  # noqa: D105 - trivial
        return self.value


class SAM:
    """Base class for a PIQI Simple Assessment Module.

    Attributes mirror the PIQI SAM anatomy. Subclasses override the metadata and
    implement :meth:`evaluate`.

    Attributes
    ----------
    mnemonic:
        Stable identifier used for registration and prerequisite references
        (e.g. ``"Attr_IsPopulated"``). SAMs reference each other only by this
        string, never by direct import.
    name:
        Human-readable name.
    success_alias / failure_alias:
        Human-readable messages for a pass / fail, surfaced in reporting.
    input_type:
        The PIQI input shape this SAM consumes (e.g. ``"Simple_Attribute"``).
    prerequisite:
        Mnemonic of a SAM that must pass first, or ``None`` for a root SAM.
    hdqt_dimension:
        The HDQT data-quality dimension this SAM assesses (e.g. ``"Validity"``).
    execution_type:
        PIQI execution type. All SAMs in this iteration use ``"Primitive_Logic"``.
    """

    mnemonic: str = ""
    name: str = ""
    success_alias: str = ""
    failure_alias: str = ""
    input_type: str = "Simple_Attribute"
    prerequisite: str | None = None
    hdqt_dimension: str = ""
    execution_type: str = "Primitive_Logic"

    def evaluate(self, value) -> Outcome:
        """Assess ``value`` and return an :class:`Outcome`.

        ``value`` is whatever the SAM's ``input_type`` describes — for the
        Simple Attribute SAMs here, a
        :class:`piqi_mapping.base.SimpleAttribute`.
        """
        raise NotImplementedError
