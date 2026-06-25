# Implementation Plan — SAM-Based Data Quality Rule Source (PIQI)

> Status: **Planned** (no code written yet). This is the agreed plan of approach
> for adding HL7 PIQI **Simple Assessment Modules (SAMs)** as a new rule source
> the existing quality engine can fire from, proven end-to-end with the
> `Patient.birthDate` chain.
>
> Companion documents: [`sam-requirements.md`](sam-requirements.md) (what to build
> and why) and [`../README.md`](../README.md) (existing engine).

---

## 1. Decisions locked

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | How `COULD_NOT_ASSESS` surfaces | **Native tri-state, channel-additive** | First-class `Outcome`; `result.violations` keeps meaning "FAILs", CNA goes in a separate channel. Backward-compatible, NFR2-safe by construction, CNA cannot trip the `fail_on` gate. |
| 2 | SAM definition style | **Hybrid: code + declarative metadata attrs** | Metadata (mnemonic, aliases, dimension, prereq, …) as class attributes (FR6); logic in `evaluate()`. Matches existing `Rule` idiom (NFR5); leaves NFR1's data-driven door open without building a loader now. |
| 3 | Registered rule id | **`patient-birthdate-is-valid`** (kebab) | Follows the existing kebab-case id convention. Diverges intentionally from the requirement's literal `Patient.birthDate.IsValidBirthdate`. |
| 4 | FHIR version & parsing | **R4 + plain `dict` access** | Confirmed from existing code ([`builtin.py`](../src/quality_rules/builtin.py) treats `birthDate` as R4 `date`, gender as R4 value set; no `fhir.resources` library). NFR4 says match the existing convention. |

---

## 2. Existing conventions this must honor

The requirement repeatedly says "match existing conventions." These are the
load-bearing facts discovered in the codebase:

| Concern | How it works today | Source |
|---|---|---|
| Rule contract | `Rule` base class: class attrs (`id`, `description`, `severity`, `resource_types`) + `check(resource: dict) -> list[str]` (messages = fail, `[]` = pass) + `evaluate(resource) -> list[Violation]` | `src/quality_rules/base.py` |
| Registration | `@register` decorator keyed on `id`, populates module-level `_REGISTRY` | `src/quality_rules/registry.py` |
| Discovery | New rule modules go live by being imported in `__init__.py` (import-for-side-effect) — **not** auto-scanning | `src/quality_rules/__init__.py` |
| Engine | `RuleEngine.run()` calls `rule.evaluate(resource)` per applicable rule and collects `Violation`s | `src/rule_engine.py` |
| FHIR parsing | Plain `dict` access, FHIR R4, no FHIR library | `src/quality_rules/builtin.py` |
| Outcomes | **Binary only** today — a violation or nothing. No `COULD_NOT_ASSESS`. | `src/quality_rules/base.py` |
| Tests | pytest, `pythonpath = src`, fixtures in `tests/conftest.py`, one test module per source module | `pytest.ini`, `tests/conftest.py` |

---

## 3. Target architecture — three independent plug points

```
FHIR Patient (dict)
      │
      ▼
src/piqi_mapping/              ← FHIR→PIQI mapper registry, keyed by PIQI path
   base.py                       SimpleAttribute(value: str | None)
   dispatcher.py                 @register_mapper("person.birthDate")           [FR11]
   patient_birthdate.py          fn(patient) -> SimpleAttribute   (reshape only) [FR7,FR9]
      │  SimpleAttribute
      ▼
src/sam/                       ← PIQI domain, zero FHIR knowledge
   base.py                       SAM base: mnemonic, name, success/failure alias,
                                   input_type, prerequisite, hdqt_dimension,
                                   execution_type; evaluate(input) -> Result     [item 1, FR1, FR6]
   registry.py                   @register_sam — mnemonic → SAM instance         [item 2, FR10]
   runner.py                     walk prereq chain by mnemonic, short-circuit    [item 3, FR2,FR3,FR4,FR12]
   sams/
     attr_is_populated.py
     attr_is_date.py             prerequisite = "Attr_IsPopulated"
     attr_is_past_date.py        prerequisite = "Attr_IsDate"
      │  Result (PASS / FAIL / COULD_NOT_ASSESS)
      ▼
src/quality_rules/sam_rules.py ← thin Rule wrapper, @register'd                  [item 5, FR8]
   id = "patient-birthdate-is-valid"
   resource_types = ("Patient",)
   overrides evaluate(): FHIR → mapper → chain runner → project to Violation/CNA
```

**Why three separate packages:** it makes the plug points *physically*
independent. Adding a SAM never touches `piqi_mapping/`; adding a mapper never
touches `sam/`; both are decoupled from the engine. The birthDate chain becomes
the reusable template, not bespoke one-off code.

### Chain semantics (runner, no field-specific logic — FR12)

Given the **terminal** SAM mnemonic, walk `prerequisite` links back to the root,
execute root→terminal, short-circuit on the first non-`PASS`:

- Any **non-terminal prerequisite** ≠ `PASS` → whole chain = `COULD_NOT_ASSESS` (FR3).
- All prerequisites pass → the **terminal** SAM's `PASS`/`FAIL` is the result (FR4).
- Cycle guard on prerequisite resolution.

This yields exactly the four acceptance outcomes:

| FHIR `Patient.birthDate` | Halts at | Result |
|---|---|---|
| valid past date (e.g. `1992-03-14`) | — (completes) | **PASS** |
| missing entirely | `Attr_IsPopulated` | **COULD_NOT_ASSESS** |
| non-date string | `Attr_IsDate` | **COULD_NOT_ASSESS** |
| future date | `Attr_IsPastDate` (terminal) | **FAIL** |

---

## 4. Engine change (channel-additive tri-state)

The foundation. Make `Outcome` first-class while keeping `result.violations`
meaning "FAILs," so existing rules and tests are untouched (NFR2 holds by
construction — existing rules only ever emit failures and can never produce CNA).

| File | Change |
|---|---|
| `src/quality_rules/base.py` | Add `Outcome` enum (`PASS`, `FAIL`, `COULD_NOT_ASSESS`). Keep `Violation` as the FAIL record; add a sibling CNA record carrying rule_id, resource ids, message, and SAM metadata (mnemonic/alias/HDQT dimension per FR6). |
| `src/rule_engine.py` | `EngineResult` gains a `could_not_assess` channel; `RuleEngine` collects CNA alongside violations. Engine still only calls `rule.evaluate()` — no SAM-special code path. |
| `src/report.py` | Additive `status`/`outcome` column (defaults to `fail` for existing rows so meaning is preserved); CNA rows written with their own status. `format_summary` gains a "could not assess" count. |
| `db/schema/create_quality_results.sql` | Matching additive `status` column. **(The one consciously-accepted NFR2 tradeoff.)** |
| `tests/unit/test_rule_engine.py` | Existing assertions must still pass unchanged; add CNA-channel assertions. |

**`evaluate()` seam:** existing rules' `evaluate() -> list[Violation]` contract
stays identical. The CNA path lives only on the SAM wrapper rule; the exact
mechanism for draining CNA out of the SAM rule into the engine's CNA channel is
finalized during implementation (kept off the shared/existing rule path).

**Exit code:** because CNA is not in `violations`, `_exit_code()` (which maxes
severity over `violations`) automatically excludes CNA from the `fail_on` gate —
exactly FR3's "not scored the same."

---

## 5. New code — file by file

### `src/sam/` (PIQI domain)
- **`base.py`** — `Outcome` (or import from `quality_rules.base`), `Result`, `SAM` base class with declarative metadata attributes and `evaluate(input) -> Result`. (item 1, FR1, FR6)
- **`registry.py`** — `@register_sam` + mnemonic → instance lookup; mirrors `quality_rules/registry.py`. (item 2, FR10)
- **`runner.py`** — prerequisite-walking chain runner; no field/mnemonic-specific strings. (item 3, FR2, FR3, FR4, FR12)
- **`sams/attr_is_populated.py`** — birthDate has content.
- **`sams/attr_is_date.py`** — parses as a valid date; tolerates FHIR partial dates (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`); prereq `Attr_IsPopulated`.
- **`sams/attr_is_past_date.py`** — chronologically before today; prereq `Attr_IsDate`.

### `src/piqi_mapping/` (FHIR→PIQI)
- **`base.py`** — `SimpleAttribute(value: str | None)`; well-formed-but-empty when the FHIR field is absent (FR9).
- **`dispatcher.py`** — `@register_mapper("person.birthDate")`, lookup by PIQI path (FR11); a registry, not a growing conditional.
- **`patient_birthdate.py`** — extracts `Patient.birthDate` → `SimpleAttribute`; reshape only, no judgment (FR7). R4 + plain dict.

### `src/quality_rules/sam_rules.py` (bridge)
- A `Rule` subclass, `id = "patient-birthdate-is-valid"`, `resource_types = ("Patient",)`, registered via the existing `@register`. Overrides `evaluate()`: FHIR Patient → mapper (`person.birthDate`) → chain runner → project tri-state to Violation (FAIL) / CNA channel / pass. Wired live with a one-line import in `quality_rules/__init__.py` (matches existing manual-import idiom, NFR5). (item 5, FR8)

---

## 6. Tests (acceptance-driven)

- Each SAM in isolation (FR1).
- Runner / chain as a whole.
- Mapper in isolation from the SAMs.
- End-to-end through `RuleEngine` for the four acceptance cases (see table in §3).
- Fixtures: FHIR `Patient` dicts added to `tests/conftest.py`.

---

## 7. Pluggability proof (ships in the PR)

Add, as **new files + registration lines only**:
- a throwaway second SAM `Attr_IsFutureDate` (PIQI standard library),
- a throwaway second FHIR mapping `Patient.gender` → PIQI Simple Attribute,
- a second wrapper rule using them.

Include a test plus a **diff showing zero modified lines** in the birthDate
framework files (`sam/base.py`, `sam/registry.py`, `sam/runner.py`,
`piqi_mapping/dispatcher.py`, and the birthDate SAMs/mapper). The sanctioned
"one registration line" is the aggregator import; framework files stay untouched.
After demonstrating, the throwaway additions may be removed or kept as a second
worked example.

---

## 8. README note

Document how to add (a) a SAM, (b) a SAM chain, and (c) a FHIR field mapping, so
the birthDate chain reads as a template for the next one.

---

## 9. Suggested sequence

1. Engine tri-state (channel-additive); keep existing tests green.
2. `src/sam/` core + three SAMs (+ unit tests).
3. `src/piqi_mapping/` (+ unit tests).
4. `sam_rules.py` bridge + wire into `__init__` + end-to-end tests.
5. Pluggability proof.
6. README note.

---

## 10. Risks / watch-items

- **CSV/DB schema column** — the one accepted NFR2 tradeoff; keep it additive with a backward-compatible default.
- **`evaluate()` seam for CNA** — existing rules' return contract must stay identical; CNA path lives only on the SAM rule.
- **Rule-id convention** — `patient-birthdate-is-valid` (kebab) intentionally diverges from the requirement's literal name.
