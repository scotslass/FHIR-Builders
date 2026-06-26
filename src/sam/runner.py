"""SAM chain runner.

Executes a prerequisite chain of SAMs in order and reduces it to a single
:class:`Result`. The runner is entirely generic: it contains no field names, no
hardcoded mnemonics, and no knowledge of any specific SAM — it works for any
chain of registered SAMs (FR12).

Chain semantics (per PIQI):

* The chain order is resolved by walking ``prerequisite`` links back from the
  terminal SAM to the root, then executing root -> terminal.
* If any **prerequisite** (non-terminal) SAM does not return ``PASS``, the chain
  short-circuits to ``COULD_NOT_ASSESS`` — the downstream condition cannot be
  assessed, which is distinct from a ``FAIL`` (FR3).
* If every prerequisite passes, the **terminal** SAM's ``PASS``/``FAIL`` is the
  chain's result (FR4).
"""

from __future__ import annotations

from dataclasses import dataclass

from sam.base import SAM, Outcome
from sam.registry import get_sam


@dataclass(frozen=True)
class Result:
    """The outcome of running a SAM chain.

    ``sam_mnemonic`` is the SAM that determined the result (the failing/halting
    prerequisite, or the terminal SAM), and ``message`` is that SAM's
    success/failure alias — so callers can report a human-readable reason.
    """

    outcome: Outcome
    sam_mnemonic: str
    message: str = ""


def resolve_chain(terminal_mnemonic: str) -> list[SAM]:
    """Return the SAMs from root to ``terminal_mnemonic`` by walking prerequisites.

    Raises ``ValueError`` if a prerequisite cycle is detected.
    """
    chain: list[SAM] = []
    seen: set[str] = set()
    mnemonic: str | None = terminal_mnemonic
    while mnemonic is not None:
        if mnemonic in seen:
            raise ValueError(
                f"cycle in SAM prerequisite chain at mnemonic {mnemonic!r}"
            )
        seen.add(mnemonic)
        sam = get_sam(mnemonic)
        chain.append(sam)
        mnemonic = sam.prerequisite
    chain.reverse()  # root first, terminal last
    return chain


def run_chain(terminal_mnemonic: str, value) -> Result:
    """Run the chain ending at ``terminal_mnemonic`` against ``value``."""
    chain = resolve_chain(terminal_mnemonic)
    *prerequisites, terminal = chain

    for sam in prerequisites:
        outcome = sam.evaluate(value)
        if outcome is not Outcome.PASS:
            # A prerequisite was not satisfied: downstream cannot be assessed.
            return Result(
                outcome=Outcome.COULD_NOT_ASSESS,
                sam_mnemonic=sam.mnemonic,
                message=sam.failure_alias or f"prerequisite {sam.mnemonic} not met",
            )

    outcome = terminal.evaluate(value)
    message = terminal.success_alias if outcome is Outcome.PASS else terminal.failure_alias
    return Result(outcome=outcome, sam_mnemonic=terminal.mnemonic, message=message)
