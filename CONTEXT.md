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
- config/web.cfg           — web UI server settings (port, default_cap, log_level)
- .env                     — Medplum base URL, client id, client secret

## Key rules to know
- Test and fixture data is SYNTHETIC ONLY — never commit real patient data (PHI).
- Never log full FHIR resource bodies; log resource type + id only.
- New quality rules go in src/quality_rules/ and use the @register decorator.
- A rule's check() returns a list of violation messages; empty list == pass.

## Current status
- Synthetic seeder, async loader, and PIQI SAM rule source are MERGED (commit
  cae874c / PR #1). The engine is tri-state — EngineResult has a
  `could_not_assess` channel distinct from `violations`; report CSV/DB carry a
  `status` column. Packages: `src/sam/` (SAM base/registry/runner + birthDate
  SAMs) and `src/piqi_mapping/` (FHIR→PIQI dispatcher); bridge rule
  `patient-birthdate-is-valid`. See docs/sam-*.md.
- Web UI added on branch `feat/web-ui` (see docs/web-ui-plan.md):
  - Shared core `src/quality_service.py` (`run_check` / `run_check_medplum`)
    used by BOTH the CLI and the web API — single evaluation path, no drift.
    `run_check_medplum` also returns per-type coverage (fetched vs total).
  - FastAPI backend `src/web/app.py` (+ `src/run_web.py` launcher) and a single
    static page `src/web/static/index.html`. Localhost-only: binds 127.0.0.1,
    Host-header allowlist (DNS-rebind guard), creds never sent to client.
  - Results show honest coverage ("evaluated N of M", truncation banner).
  - Server settings in `config/web.cfg` (port/default_cap/log_level), loaded by
    `src/web/config.py`; `--port`/`--config` flags override. Host is fixed to
    127.0.0.1 (not configurable, by design).
  - 64 tests pass (test_web_api.py + test_web_config.py). Verified end-to-end
    against live Medplum. NOT committed yet.
- [update this each session]

## Testing
- Unit tests: tests/unit/ — run with `pytest tests/unit/`
- conftest.py holds shared fixtures (synthetic FHIR resources) — edit there.
