# my-fhir-app

Python toolchain that reads clinical FHIR data from a **Medplum** database and
evaluates it against a configurable set of **data quality rules**. Each resource
is scored against the rules that apply to its type, and violations are written
to a dated report under `outputs/`.

---

## How it works

1. **Connect** — `src/medplum_client.py` authenticates to a Medplum FHIR server
   using the OAuth2 client-credentials flow and exposes paginated FHIR search.
2. **Fetch** — the runner pulls resources of the requested types (e.g. `Patient`,
   `Observation`, `Encounter`) from Medplum.
3. **Evaluate** — `src/rule_engine.py` runs every registered rule that applies to
   each resource. A rule returns zero or more violation messages.
4. **Report** — `src/report.py` writes a per-violation CSV plus a summary to
   `outputs/`.

```
Medplum FHIR API ──▶ medplum_client ──▶ rule_engine ──▶ report (CSV + summary)
                                            ▲
                                            └── quality_rules/  (rule definitions)
```

---

## Scripts

| Script | Purpose |
|---|---|
| `src/run_quality_check.py` | Main CLI. Fetches resources from Medplum, runs the rule engine, writes a report. |
| `src/medplum_client.py` | Medplum FHIR REST client (auth + paginated search + bundle/create/delete writes). |
| `src/rule_engine.py` | Loads registered rules and evaluates them against resources. |
| `src/report.py` | Writes violation CSVs and a run summary to `outputs/`. |
| `src/quality_rules/` | Rule definitions. Add new rules here. |
| `src/seed_medplum.py` | Seeds Medplum with synthetic Synthea patients (with injected defects) via the sync API. |
| `src/export_upload_bundles.py` | Writes numbered, drag-and-drop-ready bundle files + manifest to a folder. |
| `src/load_bundles_async.py` | Loads a folder of bundle files into Medplum via the **async** API (bypasses the rate limit); idempotent for patients. |
| `src/seed/` | Seeding internals: Synthea download/tag (`loader`), defect definitions (`defect_catalog`), corruptor. |
| `src/verify_seed.py` | Checks a quality report against the seed manifest (did the injected defects get caught?). |
| `src/delete_test_patients.py` | Deletes everything tagged `synthetic` (repeatable re-seeding). |

---

## Quick start

```bash
# 1. Install dependencies
pip install -r docs/requirements.txt

# 2. Copy and fill in credentials
cp .env.example .env   # then edit .env with your Medplum client id/secret

# 3. Run a quality check against Patient + Observation resources
python src/run_quality_check.py --resource Patient --resource Observation

# 4. Run every rule for a single resource type, limited to 500 records
python src/run_quality_check.py --resource Patient --limit 500
```

---

## Seeding test data

`src/seed_medplum.py` populates Medplum with synthetic **Synthea** patients so
the quality engine has realistic clinical data to evaluate. It also injects a
known set of data-quality defects into ~10% of patients, so a quality run can be
scored against ground truth.

Pipeline: **download** a pre-generated Synthea population → **tag** every
resource `synthetic` → **corrupt** ~10% with defects (writing a manifest) →
**load** the info bundles, then each patient transaction Bundle, into Medplum.

```bash
# Dry run — build + corrupt locally, write bundles + manifest, NO network.
python src/seed_medplum.py --dry-run

# Smoke test — download the data and load just 3 patients.
python src/seed_medplum.py --download --max-patients 3

# Full load — 100 patients.
python src/seed_medplum.py --max-patients 100

# Verify the engine caught the injected defects, then clean up.
python src/run_quality_check.py --resource Patient --resource Observation --resource Encounter
python src/verify_seed.py
python src/delete_test_patients.py --dry-run   # then drop --dry-run to delete
```

**Defects injected** (each maps to the built-in rule that should catch it, and
every corrupted resource is tagged `defect:<code>`):

| Defect | Resource | Caught by rule |
|---|---|---|
| `missing-birthdate` | Patient | `patient-birthdate-present` |
| `implausible-birthdate` (future date) | Patient | `patient-birthdate-plausible` |
| `missing-gender` | Patient | `patient-gender-valid` |
| `missing-loinc` (LOINC stripped, text kept) | Observation | `observation-code-present` |
| `missing-value` | Observation | `observation-has-value` |
| `missing-encounter-subject` | Encounter | `encounter-subject-present` |

> **⚠️ Volume.** Synthea patients carry full clinical histories — **100 patients
> ≈ 120k resources**. The load issues one transaction per patient and can take a
> while; the quality run then evaluates everything. Use `--max-patients` to work
> with a smaller set. Every write is tagged `synthetic`, and the cleanest reset
> for throwaway data is a disposable Medplum **Project** you can delete wholesale
> (`delete_test_patients.py` is the per-resource fallback).

### Hosted Medplum: use the async loader

Hosted Medplum (`api.medplum.com`) enforces a rate limit (~50k "points" / ~48s)
**and** an ~8 MB request-body cap. A single Synthea patient bundle exhausts the
rate budget, so the synchronous path (`seed_medplum.py`, the app's drag-and-drop
Batch tool, individual POSTs) gets throttled after ~one patient. The reliable
path is the **async API** — post with `Prefer: respond-async`; the background job
does not consume the rate quota and raises the body limit to ~50 MB.

The two-step reusable workflow:

```bash
# 1. Generate numbered bundle files (clinical-only, 10% defects) into a folder.
python src/export_upload_bundles.py --max-patients 50

# 2. Async-load that folder: info bundles first, then patients. Re-running only
#    adds NEW patients (already-loaded ones are skipped by Synthea identifier),
#    so you can grow the test set incrementally.
python src/load_bundles_async.py --dir data/exports/upload
```

To add more patients later, regenerate/extend the folder and re-run step 2 —
existing patients are skipped, new ones are loaded. For heavy/rich loads with no
limits at all, point `MEDPLUM_BASE_URL` at a local self-hosted Medplum.

All defects are *structurally valid FHIR* by design, so Medplum accepts them on
write — the corruption removes optional elements or substitutes plausible-but-
wrong values rather than producing invalid resources. The seeded population is
**synthetic only** (no PHI), and `data/raw/` is gitignored.

---

## Configuration

| File | Purpose |
|---|---|
| `.env` | Medplum base URL, client id, client secret (gitignored). |
| `config/quality_rules.cfg` | Engine defaults: enabled rule sets, severities, fetch page size, default resource types. |
| `config/validation.cfg` | Default input/output paths for the validation test suite. |

Key settings in `quality_rules.cfg`:

- `[medplum] page_size` — FHIR search page size used when paginating (default: 100)
- `[engine] resource_types` — default resource types to evaluate when none are passed on the CLI
- `[engine] fail_on` — minimum severity that makes the run exit non-zero (`error`, `warning`, or `none`)

All settings can be overridden at runtime with matching CLI flags.

---

## Writing rules

Rules live in `src/quality_rules/`. A rule subclasses `Rule`, declares the FHIR
resource types it applies to, and implements `check()`:

```python
from quality_rules.base import Rule, Severity
from quality_rules.registry import register

@register
class PatientHasBirthDate(Rule):
    id = "patient-birthdate-present"
    description = "Patient must have a birthDate"
    severity = Severity.ERROR
    resource_types = ("Patient",)

    def check(self, resource: dict) -> list[str]:
        if not resource.get("birthDate"):
            return ["birthDate is missing"]
        return []
```

The `@register` decorator adds the rule to the registry; the engine picks it up
automatically. See `src/quality_rules/builtin.py` for more examples.

---

## PIQI SAM rules

The engine also supports **Simple Assessment Modules (SAMs)** from the HL7 PIQI
Framework as a rule source, running *alongside* the rules above. A SAM is a
small, named check returning `PASS` / `FAIL` / `COULD_NOT_ASSESS`; SAMs chain via
prerequisites, and the chain is wired into the engine as an ordinary registered
rule. Incoming FHIR resources are translated into PIQI attribute shapes by a
mapping layer before any SAM runs.

```
FHIR resource ─▶ piqi_mapping (FHIR→PIQI) ─▶ sam.runner (SAM chain) ─▶ Rule (engine)
```

The worked example is the `Patient.birthDate` chain
(`Attr_IsPopulated → Attr_IsDate → Attr_IsPastDate`), registered as the rule
`patient-birthdate-is-valid`. `COULD_NOT_ASSESS` outcomes are reported in a
separate channel (CSV `status=could_not_assess`) and never trip the `fail_on`
gate, so they are scored distinctly from failures.

Three independent plug points — each addition is **new files + one registration
line**, never an edit to existing SAM/mapping/runner code:

**1. Add a SAM** — new module under `src/sam/sams/`, then one import line in
`src/sam/sams/__init__.py`:

```python
from sam.base import SAM, Outcome
from sam.registry import register_sam

@register_sam
class AttrIsPopulated(SAM):
    mnemonic = "Attr_IsPopulated"          # referenced by other SAMs by this string
    success_alias = "value is populated"
    failure_alias = "value is not populated"
    prerequisite = None                    # or another SAM's mnemonic
    hdqt_dimension = "Completeness"

    def evaluate(self, value) -> Outcome:
        return Outcome.PASS if value.is_populated else Outcome.FAIL
```

**2. Add a FHIR field mapping** — new module under `src/piqi_mapping/`, then one
import line in `src/piqi_mapping/__init__.py`. Register it by the PIQI path it
produces; extract and reshape only (no pass/fail judgment), and pass missing data
through as an unpopulated `SimpleAttribute` so `Attr_IsPopulated` reports it:

```python
from piqi_mapping.base import SimpleAttribute
from piqi_mapping.dispatcher import register_mapper

@register_mapper("person.birthDate")
def map_patient_birthdate(resource: dict) -> SimpleAttribute:
    return SimpleAttribute(value=resource.get("birthDate"))
```

**3. Wire a chain into the engine** — subclass `SamChainRule` (no engine code
changes), set the four attributes, `@register` it, and add one import line in
`src/quality_rules/__init__.py`:

```python
from quality_rules.registry import register
from quality_rules.sam_rules import SamChainRule
from quality_rules.base import Severity

@register
class PatientBirthDateIsValid(SamChainRule):
    id = "patient-birthdate-is-valid"
    resource_types = ("Patient",)
    severity = Severity.WARNING
    piqi_path = "person.birthDate"         # which mapper feeds this rule
    terminal_sam = "Attr_IsPastDate"       # last SAM in the chain
```

A second worked example (`Attr_IsFutureDate` + `Patient.gender`) and a zero-diff
proof of this pluggability live in
[`docs/sam-pluggability-proof.md`](docs/sam-pluggability-proof.md). Full design
rationale is in [`docs/sam-implementation-plan.md`](docs/sam-implementation-plan.md).

---

## Output

Reports are written to `outputs/`:

- `quality_report_{mm-dd-yyyy}.csv` — one row per violation
  (`rule_id`, `severity`, `resource_type`, `resource_id`, `message`).
- A summary is printed to stdout and saved alongside the CSV.

---

## Databases

| File | Description |
|---|---|
| `db/stores/` | Local DuckDB result stores (gitignored, safe to delete). |
| `db/queries/` | Saved SQL used for reporting / trend analysis. |
| `db/schema/` | Schema definitions for any persisted result tables. |

---

## Testing

```bash
# Unit tests
pytest tests/unit/

# Standalone: run the engine against the bundled synthetic fixtures
pytest tests/
```

Shared fixtures live in `tests/conftest.py` — edit there, not in individual test
files. Test data is **synthetic only** — never commit real patient data (PHI).

---

## Project structure

```
my-fhir-app/
├── src/
│   ├── run_quality_check.py   # CLI entrypoint
│   ├── medplum_client.py      # Medplum FHIR REST client
│   ├── rule_engine.py         # rule evaluation engine
│   ├── report.py              # report writer
│   └── quality_rules/         # rule definitions
│       ├── base.py            # Rule base class + Severity/Violation types
│       ├── registry.py        # rule registry + @register decorator
│       └── builtin.py         # bundled example rules
├── config/                    # .cfg config files
├── db/
│   ├── stores/                # DuckDB result stores (gitignored)
│   ├── queries/               # saved SQL
│   └── schema/                # schema definitions
├── data/
│   ├── raw/                   # input data (gitignored)
│   └── exports/               # exports
├── outputs/                   # generated reports
├── docs/                      # requirements.txt + design docs
├── tests/
│   ├── unit/
│   └── fixtures/              # synthetic FHIR fixtures
├── .env                       # credentials (gitignored)
├── CONTEXT.md                 # session context (update each session)
└── README.md
```
