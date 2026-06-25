"""Pluggability proof.

Demonstrates that a second SAM (``Attr_IsFutureDate``) and a second FHIR mapping
(``person.gender``) were added by writing only new files plus registration
entries — see ``docs/sam-pluggability-proof.md`` for the zero-diff changeset.

The three plug points exercised here:
  1. SAM plug point        — Attr_IsFutureDate chains on the existing Attr_IsDate.
  2. FHIR mapping plug point — person.gender resolves through the same dispatcher.
  3. Rule registration      — patient-gender-is-populated fires via the engine.
"""

import piqi_mapping  # noqa: F401  registers mappers
import sam.sams  # noqa: F401  registers SAMs
from piqi_mapping.base import SimpleAttribute
from piqi_mapping.dispatcher import map_field
from sam.base import Outcome
from sam.runner import resolve_chain, run_chain
from rule_engine import RuleEngine


# ── Plug point 1: new SAM, chained on existing SAMs by mnemonic ─────────────────

def test_new_sam_chains_on_existing_prerequisites():
    chain = resolve_chain("Attr_IsFutureDate")
    assert [s.mnemonic for s in chain] == [
        "Attr_IsPopulated",
        "Attr_IsDate",
        "Attr_IsFutureDate",
    ]


def test_new_sam_evaluates_through_the_generic_runner():
    assert run_chain("Attr_IsFutureDate", SimpleAttribute("2999-01-01")).outcome is Outcome.PASS
    assert run_chain("Attr_IsFutureDate", SimpleAttribute("1992-03-14")).outcome is Outcome.FAIL
    # Halts on the shared prerequisites, exactly like the birthDate chain.
    assert run_chain("Attr_IsFutureDate", SimpleAttribute(None)).outcome is Outcome.COULD_NOT_ASSESS


# ── Plug point 2: new FHIR mapping via the same dispatcher ──────────────────────

def test_new_mapping_resolves_through_the_dispatcher():
    attr = map_field("person.gender", {"resourceType": "Patient", "id": "p", "gender": "female"})
    assert attr.value == "female"
    absent = map_field("person.gender", {"resourceType": "Patient", "id": "p"})
    assert absent.value is None


# ── Plug point 3: new rule fires through the engine ─────────────────────────────

def test_new_rule_fires_through_the_engine():
    rid = "patient-gender-is-populated"
    with_gender = {"resourceType": "Patient", "id": "p", "gender": "female"}
    without = {"resourceType": "Patient", "id": "q"}

    ok = RuleEngine().run([with_gender])
    assert [v for v in ok.violations if v.rule_id == rid] == []
    assert [c for c in ok.could_not_assess if c.rule_id == rid] == []

    # The chain's only (terminal) SAM is Attr_IsPopulated, with no prerequisite —
    # so an absent gender is a genuine FAIL (a violation), not could-not-assess.
    missing = RuleEngine().run([without])
    viols = [v for v in missing.violations if v.rule_id == rid]
    assert len(viols) == 1
    assert [c for c in missing.could_not_assess if c.rule_id == rid] == []
