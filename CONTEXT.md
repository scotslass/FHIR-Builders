# my-fhir-app — Project Context

## What this does
Python toolchain that reads clinical FHIR data from a Medplum database and
evaluates each resource against configurable data quality rules. Violations are
collected by the rule engine and written to a dated report under `outputs/`.

## Scripts
- src/run_quality_check.py — main CLI: fetch from Medplum → run rules → report
- src/medplum_client.py     — Medplum FHIR REST client (OAuth2 + paginated search)
- src/rule_engine.py        — loads registered rules, evaluates them per resource
- src/report.py             — writes violation CSV + summary to outputs/
- src/quality_rules/        — rule definitions (base.py, registry.py, builtin.py)

## Config
- config/quality_rules.cfg — engine defaults (page size, default resource types, fail_on)
- config/validation.cfg    — default paths for the validation test suite
- .env                     — Medplum base URL, client id, client secret

## Key rules to know
- Test and fixture data is SYNTHETIC ONLY — never commit real patient data (PHI).
- Never log full FHIR resource bodies; log resource type + id only.
- New quality rules go in src/quality_rules/ and use the @register decorator.
- A rule's check() returns a list of violation messages; empty list == pass.

## Current status
- Scaffolding created. Medplum client, engine, registry, and example builtin
  rules are stubbed and unit-tested. Live Medplum fetch not yet wired to creds.
- PIQI SAM rule source added (branch feat/synthetic-seeder-and-async-loader):
  - Engine is now tri-state — EngineResult has a `could_not_assess` channel
    distinct from `violations`; report CSV/DB gained a `status` column.
  - New packages: `src/sam/` (SAM base/registry/runner + 3 birthDate SAMs) and
    `src/piqi_mapping/` (FHIR→PIQI mapper dispatcher). Bridge rule
    `patient-birthdate-is-valid` in `src/quality_rules/sam_rules.py`.
  - Pluggability proof: `Attr_IsFutureDate` + `person.gender` mapper +
    `sam_rules_proof.py` (kept as 2nd example). See docs/sam-*.md.
  - 53 tests pass. Not committed yet.
- [update this each session]

## Testing
- Unit tests: tests/unit/ — run with `pytest tests/unit/`
- conftest.py holds shared fixtures (synthetic FHIR resources) — edit there.
