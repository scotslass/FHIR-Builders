"""Each SAM in isolation (FR1) — no chain, no engine, no FHIR mapper involved."""

from piqi_mapping.base import SimpleAttribute
from sam.base import Outcome
from sam.sams.attr_is_date import AttrIsDate
from sam.sams.attr_is_past_date import AttrIsPastDate
from sam.sams.attr_is_populated import AttrIsPopulated


def attr(value):
    return SimpleAttribute(value=value)


def test_is_populated_pass_and_fail():
    assert AttrIsPopulated().evaluate(attr("1992-03-14")) is Outcome.PASS
    assert AttrIsPopulated().evaluate(attr(None)) is Outcome.FAIL
    assert AttrIsPopulated().evaluate(attr("   ")) is Outcome.FAIL


def test_is_date_tolerates_fhir_partial_precision():
    assert AttrIsDate().evaluate(attr("1992-03-14")) is Outcome.PASS
    assert AttrIsDate().evaluate(attr("1992-03")) is Outcome.PASS
    assert AttrIsDate().evaluate(attr("1992")) is Outcome.PASS


def test_is_date_rejects_non_dates():
    assert AttrIsDate().evaluate(attr("not-a-date")) is Outcome.FAIL
    assert AttrIsDate().evaluate(attr("2023-13-40")) is Outcome.FAIL  # impossible calendar


def test_is_past_date_pass_and_fail():
    assert AttrIsPastDate().evaluate(attr("1992-03-14")) is Outcome.PASS
    assert AttrIsPastDate().evaluate(attr("2999-01-01")) is Outcome.FAIL


def test_sam_metadata_is_retrievable():
    sam = AttrIsPastDate()
    assert sam.mnemonic == "Attr_IsPastDate"
    assert sam.prerequisite == "Attr_IsDate"
    assert sam.failure_alias  # human-readable message exists for reporting (FR6)
    assert sam.hdqt_dimension
