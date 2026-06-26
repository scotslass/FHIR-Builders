# Requirements — SAM-Based Data Quality Rule Source (PIQI Framework)

> Canonical, discovery-ready requirements for adding HL7 PIQI **Simple Assessment
> Modules (SAMs)** to `my-fhir-app` as a new rule source. Derived from the
> original `sam-requirement.md` and augmented with codebase-grounding and the
> design decisions agreed during discovery.
>
> Companion: [`sam-implementation-plan.md`](sam-implementation-plan.md) (how to build it).

---

## Background

The existing rules/validation engine evaluates data quality rules against
incoming records. We are introducing **Simple Assessment Modules (SAMs)**, as
defined by the HL7 PIQI Framework, as a new, standardized rule-definition
mechanism that sits **alongside (not replaces)** current rules. A SAM is a small,
composable, named check that takes a typed input (an attribute, element, or the
whole record), returns `PASS` / `FAIL` / `COULD_NOT_ASSESS`, and can declare a
prerequisite SAM that must pass before it runs.

The goal: SAMs become a first-class **rule source** the engine can fire from — a
SAM (or chain of SAMs) registers the same way any other rule registers today, and
its result drives existing scoring/alerting logic.

**Ingestion format: FHIR.** Source data arrives as **FHIR resources** (e.g.
`Patient`), not PIQI's native flat-element model. PIQI is format-agnostic — it
assesses data once placed into the PIQI Data Model (a flat
element/attribute structure: Simple Attribute, CodeableConcept, ObservationValue,
RangedValue) and is not designed to operate on FHIR JSON directly. A
**mapping/transformation step** is therefore required between FHIR ingestion and
SAM evaluation. For this iteration the mapping is scoped narrowly to one field:
`Patient.birthDate`.

---

## Objective

Build the adapter layer that lets the rules engine load, chain, and execute SAMs,
proven end-to-end with **one real chain**: validating `Patient.birthDate`
(ingested as a FHIR `Patient` resource) using three chained SAMs. The chain ships
fully working, tested, and wired into the live engine — but the underlying
architecture (SAM registry, chain runner, FHIR mapping layer) is **pluggable from
day one**, proven by the pluggability acceptance criterion (a second throwaway
SAM/mapping added with zero edits to existing files).

---

## Codebase grounding (confirmed during discovery)

These existing conventions are load-bearing — the SAM layer must conform, not
introduce a parallel pattern.

| Concern | Existing convention | Source |
|---|---|---|
| Rule contract | `Rule` base: class attrs (`id`, `description`, `severity`, `resource_types`) + `check(dict) -> list[str]` + `evaluate(dict) -> list[Violation]` | `src/quality_rules/base.py` |
| Registration | `@register` decorator keyed on `id`; module-level `_REGISTRY` | `src/quality_rules/registry.py` |
| Discovery | New rule modules imported in `__init__.py` (import-for-side-effect); no auto-scan | `src/quality_rules/__init__.py` |
| Engine | `RuleEngine.run()` calls `rule.evaluate()` per applicable rule, collects `Violation`s | `src/rule_engine.py` |
| FHIR parsing | Plain `dict` access, **FHIR R4**, no FHIR library | `src/quality_rules/builtin.py` |
| Outcomes (before this work) | Binary only — violation or nothing; no `COULD_NOT_ASSESS` | `src/quality_rules/base.py` |
| Tests | pytest, `pythonpath = src`, fixtures in `tests/conftest.py` | `pytest.ini`, `tests/conftest.py` |

---

## Scope

### In scope
1. A `SAM` abstraction matching PIQI anatomy: mnemonic, name, success/failure
   alias, input type, prerequisite SAM mnemonic, HDQT dimension, execution type,
   and `evaluate(input) -> Result` where `Result ∈ {PASS, FAIL, COULD_NOT_ASSESS}`.
2. A **SAM registry** — mnemonic → SAM instance, so SAMs reference each other by
   mnemonic (prerequisites) without hard-wired imports.
3. A **SAM chain runner** that executes a prerequisite chain in order,
   short-circuiting to `COULD_NOT_ASSESS` if any prerequisite link does not pass.
4. A **FHIR-to-PIQI mapping layer** that extracts `Patient.birthDate` and presents
   it as a PIQI Simple Attribute. It must:
   - Pass through present/absent/`null` birthDate as populated/unpopulated (do not
     let the mapper swallow missing data — `Attr_IsPopulated` owns that check).
   - Preserve the original FHIR `date` as-is (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`)
     without assuming full precision.
   - Be an isolated, named function/class so more FHIR fields can be mapped later
     without touching SAM or chain-runner code.
5. An **adapter** exposing a chained SAM evaluation as a rule the existing engine
   can register and fire (matching the existing rule pattern).
6. **Three concrete SAMs**, chained for `Patient.birthDate`:
   - `Attr_IsPopulated` — birthDate has content.
   - `Attr_IsDate` — parses as a valid date (prereq `Attr_IsPopulated`).
   - `Attr_IsPastDate` — chronologically before today (prereq `Attr_IsDate`).
7. Wiring the chain into the engine as a registered rule sourcing its input via
   the FHIR-to-PIQI mapping layer.
8. Unit tests using FHIR `Patient` fixtures: valid past date (PASS), missing
   element (CNA, halts step 1), malformed non-date (CNA, halts step 2), future
   date (FAIL, step 3).

### Out of scope (this iteration)
- CodeableConcept, ObservationValue, RangeValue, Element, Data Class, or
  Patient-level SAMs (only the three Simple Attribute SAMs).
- Non-primitive execution types (`Stored_Procedure`, `RESTful_Service`,
  `Regex_Pattern`, `Value_Set_*`) — all three SAMs use `Primitive_Logic`.
- Mapping any FHIR field other than `Patient.birthDate`.
- General-purpose FHIR-to-PIQI conversion (full resources, bundles, etc.).
- FHIR validation/conformance checking (e.g. US Core profiles).
- Building a new engine, scoring/rubric system, or UI.
- Migrating existing rules to SAM form.

---

## Extensibility architecture (three plug points)

Must exist as real, exercised mechanisms even though only one chain ships now.

1. **SAM plug point.** New SAM = one new file implementing `SAM` + one
   registration line by mnemonic. No edits to the registry internals, chain
   runner, or other SAMs. Prerequisite wiring is by mnemonic string, never direct
   object/class reference.
2. **FHIR mapping plug point.** New mapping = one new mapper (function/class)
   FHIR resource → PIQI attribute shape, registered against the PIQI path it
   produces (`person.birthDate`, `person.familyName`, …). The mapping layer is a
   small registry/dispatcher of named mappers, not one growing conditional.
3. **Rule registration plug point.** Wiring a chain into the engine follows the
   engine's existing registration pattern, so chain #2 is "copy the birthDate
   pattern, change the mnemonics and field," not new framework code.

The three plug points are independent of each other. The birthDate chain is the
one concrete instance of all three and should read as a **template**.

---

## Functional Requirements

- **FR1** — Each SAM independently invocable and testable, outside any chain.
- **FR2** — Chain runner accepts an ordered list of mnemonics (or resolves order
  by walking prerequisite links) and stops at the first non-`PASS`.
- **FR3** — A chain halting on an unmet prerequisite surfaces as
  `COULD_NOT_ASSESS`, distinct from `FAIL`; the two must not be scored the same.
- **FR4** — The final SAM in a completed chain determines the ultimate
  `PASS`/`FAIL`.
- **FR5** — SAMs added without modifying the engine's core dispatch/registration
  logic — additive (new file/registration), not a change to shared code.
- **FR6** — Each SAM's metadata (mnemonic, success/failure alias, HDQT dimension)
  retrievable at runtime for human-readable logging/reporting.
- **FR7** — Mapping layer accepts a FHIR `Patient` (JSON), extracts `birthDate`
  into the Simple Attribute shape, without performing the SAM's validation logic
  (extract and reshape; do not judge pass/fail).
- **FR8** — Mapping layer invoked ahead of the SAM chain in the registered rule's
  execution path; the engine's rule input stays "a FHIR resource" to callers.
- **FR9** — If `birthDate` is absent entirely, the mapper still produces a
  well-formed (empty) Simple Attribute so `Attr_IsPopulated` (not the mapper)
  reports the missing-data condition.
- **FR10** — SAM registration self-contained per SAM (decorator / registration
  call / single small list) — never a hardcoded `if/elif` dispatch on mnemonic.
- **FR11** — FHIR-field mappers individually registered and discoverable by the
  PIQI path they produce.
- **FR12** — Chain runner accepts *any* valid ordered list of registered
  mnemonics — no birthDate-specific logic, field names, or hardcoded mnemonics.

---

## Non-Functional Requirements

- **NFR1** — SAM definitions declarable as data where logic is genuinely
  primitive, to keep the door open for non-engineers to contribute metadata; the
  three SAMs may ship as code if a data-driven loader is significantly more effort.
- **NFR2** — No change to the engine's behavior for currently-registered (non-SAM)
  rules.
- **NFR3** — Structured so future SAM input types and FHIR mappings can be added
  per the plug points without restructuring the registry, chain runner, or
  mapping dispatcher.
- **NFR4** — Mapping layer extends to more resource types/fields later; confirm
  FHIR version (R4/R5) and parsing approach against existing ingestion and follow
  it. *(Confirmed: R4 + plain `dict` access.)*
- **NFR5** — Favor straightforward extension (decorator, `register()` call, small
  manifest) over elaborate plugin-discovery (auto-scan, reflection) unless already
  idiomatic. *(Existing code uses manual imports — match that.)*

---

## Acceptance Criteria

- [ ] `patient-birthdate-is-valid` against a FHIR `Patient` with a valid past
      `birthDate` returns PASS.
- [ ] Against a `Patient` with `birthDate` missing entirely returns
      COULD_NOT_ASSESS (not FAIL).
- [ ] Against a `Patient` with a non-date string in `birthDate` returns
      COULD_NOT_ASSESS.
- [ ] Against a `Patient` with a future-dated `birthDate` returns FAIL.
- [ ] All three SAMs independently unit-tested; the chain tested as a whole; the
      FHIR mapping tested in isolation from the SAMs.
- [ ] The rule fires through the engine's normal registration/execution path — no
      special-cased code path for SAMs or FHIR input.
- [ ] A README note explains how to register a new SAM, a new SAM chain, and how
      to extend the FHIR mapping layer to a new field.
- [ ] **Pluggability proof**: a throwaway second SAM (`Attr_IsFutureDate`) and a
      throwaway second mapping (`Patient.gender` → Simple Attribute) each added by
      writing only new files + registration entries, with a diff showing zero
      modified lines in any birthDate framework file. Proof artifact (test + diff)
      included in the PR.

---

## Design decisions (agreed in discovery)

| # | Decision | Choice |
|---|---|---|
| 1 | `COULD_NOT_ASSESS` representation | **Native tri-state, channel-additive** — first-class `Outcome`; `result.violations` keeps meaning "FAILs", CNA in a separate channel. NFR2-safe; CNA excluded from the `fail_on` gate. |
| 2 | SAM definition style | **Hybrid** — code classes with declarative metadata attributes; logic in `evaluate()`. JSON loader deferred (NFR1 permits). |
| 3 | Registered rule id | **`patient-birthdate-is-valid`** (kebab, matching existing ids). |
| 4 | FHIR version / parsing | **R4 + plain `dict`** (matches existing code, NFR4). |

Accepted tradeoff (decision 1): the report CSV and `db/schema` gain an additive
`status`/`outcome` column. Kept backward-compatible via a default of `fail` on
existing rows.

---

## Reference

**PIQI SAM specification:** HL7 Informative Document, Patient Information Quality
Improvement (PIQI) Framework — Simple Assessment Modules (`sams.html`). Standard
SAMs used: `Attr_IsPopulated`, `Attr_IsDate`, `Attr_IsPastDate` (+
`Attr_IsFutureDate` for the pluggability proof).

**Sample FHIR `Patient` input:**

```json
{
  "resourceType": "Patient",
  "id": "example-1",
  "birthDate": "1992-03-14"
}
```

**Target PIQI Simple Attribute shape** the mapper produces:

```json
{
  "person": {
    "birthDate": "1992-03-14"
  }
}
```

**Edge case** — `birthDate` absent (mapper still yields a well-formed empty
Simple Attribute; `Attr_IsPopulated` reports the gap):

```json
{
  "resourceType": "Patient",
  "id": "example-2"
}
```
