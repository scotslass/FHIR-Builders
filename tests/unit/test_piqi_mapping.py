"""The FHIR-to-PIQI mapping layer, in isolation from the SAMs."""

import piqi_mapping  # noqa: F401  registers the bundled mappers
from piqi_mapping.base import SimpleAttribute
from piqi_mapping.dispatcher import map_field


def test_maps_present_birthdate():
    attr = map_field(
        "person.birthDate",
        {"resourceType": "Patient", "id": "p", "birthDate": "1992-03-14"},
    )
    assert isinstance(attr, SimpleAttribute)
    assert attr.value == "1992-03-14"
    assert attr.is_populated is True


def test_absent_birthdate_yields_wellformed_unpopulated_attribute():
    # FR9: the mapper must not swallow missing data — it produces an empty
    # Simple Attribute so Attr_IsPopulated (not the mapper) reports the gap.
    attr = map_field("person.birthDate", {"resourceType": "Patient", "id": "p"})
    assert isinstance(attr, SimpleAttribute)
    assert attr.value is None
    assert attr.is_populated is False


def test_mapper_preserves_partial_precision_and_does_not_validate():
    # FR7: extract and reshape only — pass partial dates and even junk through
    # untouched. Judging validity is the SAM's job, not the mapper's.
    assert map_field("person.birthDate", {"birthDate": "1992"}).value == "1992"
    assert map_field("person.birthDate", {"birthDate": "garbage"}).value == "garbage"
