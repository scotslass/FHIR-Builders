"""FHIR-to-PIQI mapping layer.

Importing this package registers the bundled field mappers with
:mod:`piqi_mapping.dispatcher`. To add a mapping for a new FHIR field: create a
new mapper module and add one import line here. The dispatcher itself never
changes.
"""

from piqi_mapping import patient_birthdate  # noqa: F401  (import for side-effect)
