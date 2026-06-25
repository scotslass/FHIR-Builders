"""The SAM chain runner: prerequisite resolution and short-circuit semantics."""

import sam.sams  # noqa: F401  registers the bundled SAMs
from piqi_mapping.base import SimpleAttribute
from sam.base import Outcome
from sam.runner import resolve_chain, run_chain


def attr(value):
    return SimpleAttribute(value=value)


def test_resolve_chain_orders_root_to_terminal():
    chain = resolve_chain("Attr_IsPastDate")
    assert [s.mnemonic for s in chain] == [
        "Attr_IsPopulated",
        "Attr_IsDate",
        "Attr_IsPastDate",
    ]


def test_completed_chain_passes():
    result = run_chain("Attr_IsPastDate", attr("1992-03-14"))
    assert result.outcome is Outcome.PASS
    assert result.sam_mnemonic == "Attr_IsPastDate"


def test_unpopulated_halts_at_step1_as_could_not_assess():
    result = run_chain("Attr_IsPastDate", attr(None))
    assert result.outcome is Outcome.COULD_NOT_ASSESS
    assert result.sam_mnemonic == "Attr_IsPopulated"


def test_nondate_halts_at_step2_as_could_not_assess():
    result = run_chain("Attr_IsPastDate", attr("not-a-date"))
    assert result.outcome is Outcome.COULD_NOT_ASSESS
    assert result.sam_mnemonic == "Attr_IsDate"


def test_future_date_fails_at_terminal():
    result = run_chain("Attr_IsPastDate", attr("2999-01-01"))
    assert result.outcome is Outcome.FAIL
    assert result.sam_mnemonic == "Attr_IsPastDate"


def test_could_not_assess_is_distinct_from_fail():
    cna = run_chain("Attr_IsPastDate", attr(None)).outcome
    fail = run_chain("Attr_IsPastDate", attr("2999-01-01")).outcome
    assert cna is Outcome.COULD_NOT_ASSESS
    assert fail is Outcome.FAIL
    assert cna is not fail
