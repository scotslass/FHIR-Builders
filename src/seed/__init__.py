"""Synthetic test-data seeding for Medplum.

This package downloads a pre-generated Synthea population, tags every resource
as synthetic, injects a known set of data-quality defects into a fraction of the
patients (producing a ground-truth manifest), and loads the result into a
Medplum FHIR server.

Entry point: ``src/seed_medplum.py`` (CLI).
"""
