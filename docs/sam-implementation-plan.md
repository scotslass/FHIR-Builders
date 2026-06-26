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

---

## 11. Future phase — mapping-layer acceleration (design-only)

> Not part of the current iteration. Captured here so the mapping layer can scale
> to many fields/resource types without a rewrite. The current per-field mapper
> functions are correct and stay valid; this is about what goes *inside* a mapper
> as the field count grows.

### Problem

Hand-written `dict.get()` mappers are fine for one field, but verbose and
error-prone for nested/array/choice elements
(`Patient.name.where(use='official').family.first()`,
`Observation.value.ofType(Quantity).value`). The mapping surface is where most of
the future per-field work lives.

### Recommended accelerant: `fhirpath-py` at the mapper body only

Replace the *body* of a mapper with a declarative **FHIRPath** expression, so a
mapper becomes data (`"person.birthDate" -> "Patient.birthDate"`) rather than
code. This advances the NFR1 "SAM/mapping declarable as data" goal that was
deferred, and fits the existing path-keyed dispatcher with no structural change.

Why it wins against the stated priorities:

| Priority | Why fhirpath-py |
|---|---|
| **Code compatibility** (top) | Operates on the same plain `dict` already passed through the engine and `medplum_client`. No model migration; "rule input is a FHIR resource dict" convention preserved; NFR2 intact. |
| **Ease of use** | Nested/array/choice-type extraction collapses to one FHIRPath string instead of nested `.get()` + index guards. |
| **Pluggability** | A mapper collapses to `{piqi_path: fhirpath_expr}` — adding field #2 becomes a data entry, not a function. Dispatcher and SAM layers unchanged. |

### Options considered

| Tool | Verdict |
|---|---|
| **fhirpath-py** (beda-software) — FHIRPath on plain dicts, R4/R5 | **Recommended.** Right layer, no migration, declarative. |
| **fhir.resources** (Pydantic typed models, R5) | Use only at the edge for validation if needed; full adoption forces `dict -> Model` conversion and breaks the dict convention. |
| **fhirpath** (nazrulworld) — FHIRPath + search/FQL | Overkill; query features not needed. |
| **fhirpy / fhirclient** — FHIR clients | Wrong layer; overlaps `medplum_client`, not a mapper. |
| **FHIR Mapping Language / StructureMap** (Matchbox/HAPI) | Standards-grade but a JVM dependency; revisit only at large scale. |
| **LLM-assisted authoring** (Claude) | Good as an authoring-time codegen helper (draft the FHIRPath + a fixture from a sample resource, commit the string). Keep out of the runtime path: non-deterministic, and PHI to a non-BAA endpoint. |

### Integration sketch (when/if adopted)

- Add one generic `FhirPathMapper` that wraps `fhirpath-py`, registered against a
  PIQI path with its expression. Existing bespoke mappers keep working unchanged
  (the dispatcher doesn't care whether a mapper is code or a FHIRPath wrapper), so
  adoption is **incremental** — `Patient.birthDate` can stay as-is.
- The wrapper still returns a `SimpleAttribute` and **must not judge**: FHIRPath
  returns a list, so the wrapper picks first-match / empty; an empty result becomes
  `value=None`, leaving `Attr_IsPopulated` to report the gap (FR9).

### Watch-items

- **Partial-date precision** stays the SAM's job — FHIRPath returns the raw `date`
  string; `parse_fhir_date` keeps handling `YYYY` / `YYYY-MM` / `YYYY-MM-DD`.
- **R4 vs R5** — pin to R4 to match the current convention (NFR4); revisit on R5 ingest.
- **Dependency budget** — this would be the first runtime FHIR dependency; adopt as a conscious choice.
- **LLM codegen** — authoring-time only; commit the resulting expression, never call an LLM at runtime.

### Tradeoffs / downsides (on record)

Ordered by impact on *this* context (high-volume, correctness-critical, deliberately dependency-light).

**Highest impact**

- **Silent empties corrupt verdicts.** FHIRPath returns an empty collection for *both* "field genuinely absent" *and* "expression is wrong (typo/bad path)". Both collapse to `value=None` -> `Attr_IsPopulated` fails -> a **false `COULD_NOT_ASSESS`**. A bug in the *mapping expression* disguises itself as a *data-quality finding*, silently. Mitigation: a fixture test per expression proving it extracts the value from a known-good resource, so a broken expression fails in our tests, not as a mystery CNA in production.
- **Performance at volume.** FHIRPath is parsed and tree-walk-interpreted at runtime; `resource.get("birthDate")` is essentially free. At ~120k resources / 100 patients this compounds per-field. Mitigation: compile/cache the parsed expression once per mapper (not per resource); map only needed fields. Still slower than dict access — measure before using on hot paths.
- **Trusting a third party for correctness.** FHIRPath is a large spec; a Python implementation may have unimplemented functions or subtle divergences from reference `fhirpath.js`. A conformance bug in the extractor produces wrong quality results. Mitigation: restrict to the simple navigation subset actually used; pin the version; test the expressions relied on.

**Worth knowing**

- **Everything is a collection.** Every mapper must encode "first / single / empty"; for repeating elements (multiple names/identifiers) the choice of *which* match feeds the SAM is implicit in the expression and easy to get wrong.
- **Stringly-typed, weaker tooling.** Expressions are opaque strings — no mypy, no autocomplete, no static check that the path is valid for the resource type; typos surface only at runtime.
- **Second mapping idiom — tension with NFR5.** Mixing code mappers and expression-string mappers means contributors must know both. Mitigation: if adopted, make it the default going forward and migrate deliberately rather than leaving a permanent split.
- **Extraction only, not transformation.** FHIRPath pulls values out; normalization / combining fields / conditional logic still drop back to Python. It is a better extractor, not a complete mapping DSL.
- **First runtime FHIR dependency + bus-factor.** Single small-org maintainer, smaller community than HAPI. Mitigation: pin it, vet release cadence/open issues before committing, keep the `FhirPathMapper` wrapper thin so the engine can be swapped without touching the dispatcher or SAMs.

### Decision stance

The break-even is **field complexity vs. volume/correctness sensitivity**. For flat scalars like `Patient.birthDate`, fhirpath-py is net negative — slower and riskier than the existing one-line `.get()`, for no gain. It pays off only for genuinely nested/array/choice-type fields.

Recommended stance: **keep the hand-written mapper as the default for simple fields; reach for fhirpath-py only for the gnarly nested/choice cases**, and gate any adoption behind the three guardrails below. This preserves the "must not judge / `value=None`" contract while containing the silent-empty and performance risks.

### The three adoption gates (expanded)

Each gate closes one of the highest-impact risks; together they make adoption *safe* rather than merely *convenient*. A FHIRPath engine trades explicit, debuggable code for terse, opaque strings — these buy back the visibility given up.

| Risk | Gate that closes it |
|---|---|
| Slow at volume | **(a)** parse once, evaluate many |
| Typo'd expression -> false "could not assess" | **(b)** value-asserting fixture test per expression |
| Library upgrade silently changes verdicts | **(c)** pinned version + lockfile, fixture tests as the upgrade gate |

**(a) Cached (pre-)compilation — closes the performance risk.**
A FHIRPath engine parses the expression string into a tree, then evaluates that tree against a resource. Parsing is the expensive part and is identical every call. Parse **once** (at registration / first use) and reuse the compiled form per resource — never parse inside the per-resource loop:

```python
# at registration (once):
self._compiled = compile("Patient.birthDate")
# per resource (~120k times):
self._compiled(resource)
```

Pay the parse cost once per *mapper*, not once per *resource*. If the library only exposes one-shot `evaluate(resource, expr)`, wrap it with memoization on the parsed form. Verify the library exposes a compile/evaluate split when evaluating it.

**(b) Per-expression fixture test — closes the silent-empty correctness trap.**
FHIRPath returns an empty collection for *both* a genuinely absent field and a wrong expression (typo/bad path), so a broken expression silently becomes a false `COULD_NOT_ASSESS` that looks like a data problem, not a code problem. For every committed expression, commit a test asserting it extracts a **non-empty value** from a known-good fixture:

```python
def test_birthdate_expression_extracts():
    patient = {"resourceType": "Patient", "id": "p", "birthDate": "1992-03-14"}
    attr = map_field("person.birthDate", patient)
    assert attr.value == "1992-03-14"   # proves the path works, not just "returns empty"
```

The assertion must prove extraction *works* — a test that only checks the absent case (`value is None`) passes even with a broken expression. This moves the failure from production (silent, misattributed) into CI (loud).

**(c) Pinned version (+ lockfile) — closes the third-party-conformance risk.**
Lock the dependency to an exact version, not a floating range:

```
# docs/requirements.txt
fhirpathpy==1.2.1      # pinned — not >=1.2 or unpinned
```

FHIRPath is a large spec and this library is what's trusted to extract values correctly. A silent minor-version bump that changes `ofType()`, partial-date, or empty-collection behavior shifts the engine's *verdicts* with no code change on our side. Pinning (plus a lockfile so transitive deps are pinned too) makes results reproducible and turns upgrades into a deliberate, reviewed event — bump the pin, re-run the (b) fixture tests as the regression gate, confirm nothing moved.

### FHIRPath vs. hand-rolled: decision criteria

**The Claude Code reframe.** The classic argument *for* FHIRPath is "it saves writing tedious extraction boilerplate." But when Claude Code generates a correct hand-written mapper *and* its fixture tests from a sample resource in seconds, that authoring-effort advantage evaporates — the LLM writes either artifact equally well. So the choice should be driven by the **runtime and maintenance properties of the committed artifact**, not by typing effort.

Pick by field shape and operating constraints:

| Dimension | -> Roll your own (Claude-written dict/Python) | -> FHIRPath (fhirpath-py) |
|---|---|---|
| **Field shape** | Flat scalar (`birthDate`, `gender`, `status`) | Nested / repeating / filtered / choice-type (`name.where(use='official').family`, `value.ofType(Quantity)`) |
| **Hot path / volume** | High-throughput (120k-resource runs) — dict access is free | Low-volume or off the hot path |
| **Transformation vs extraction** | Normalizing, combining, conditionals -> must be code | Pure extraction, no logic |
| **Debuggability** | Verdict-critical paths to step through with a stack trace | OK to debug via fixture tests |
| **Dependency tolerance** | Stay dependency-light (current stance) | OK adding one pinned, vetted dep |
| **Who maintains mappings** | Engineers | Analysts/non-engineers contributing mappings as data (NFR1) |
| **Breadth of similar nested paths** | A handful of fields | Dozens of structurally-similar nested paths (amortizes the dep) |

**Decision rule.** Default to a Claude-written hand-rolled mapper. Switch a *specific* field to FHIRPath only when its **shape is genuinely nested/array/choice-type** AND it is **not on the hottest path** AND the dependency is accepted. Any field needing *transformation* beyond extraction stays code regardless. Let field complexity be the trigger; treat volume, transformation needs, and dependency tolerance as vetoes back toward code.

**Applied here.** `Patient.birthDate` and `Patient.gender` are flat scalars on the hot path -> hand-rolled (FHIRPath would be net-negative). A future `Observation.value.ofType(Quantity).value` or `Patient.name.where(use='official').family` is a FHIRPath candidate *if* it clears the volume/dependency vetoes and passes a per-expression fixture test.

### Current decision (this iteration)

**Stick with hand-written `dict` mappers for now**, with an eye on introducing FHIRPath when field complexity makes it worth it. No dependency is added this iteration. Revisit per the decision rule above when the first genuinely nested/array/choice-type field arrives; adoption is incremental (the dispatcher accepts a FHIRPath-backed mapper alongside existing code mappers with no structural change).

### References

- [fhirpath-py (beda-software)](https://github.com/beda-software/fhirpath-py) · [PyPI](https://pypi.org/project/fhirpathpy/)
- [fhirpath (nazrulworld)](https://github.com/nazrulworld/fhirpath)
- [fhir.resources](https://pypi.org/project/fhir.resources/)
- [HL7 FHIRPath Implementations](https://confluence.hl7.org/spaces/FHIRI/pages/161060129/FHIRPath+Implementations)
