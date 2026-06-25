# Pluggability Proof — SAM Rule Source

This documents the acceptance-criterion proof that a **second SAM** and a
**second FHIR field mapping** can be added by writing **only new files plus
registration entries**, with **zero modified lines** in any file written for the
birthDate use case.

Exercised by [`tests/unit/test_pluggability_proof.py`](../tests/unit/test_pluggability_proof.py).

## What was added

| Plug point | New file (added) | Registration entry (1 line) |
|---|---|---|
| 1. New SAM | `src/sam/sams/attr_is_future_date.py` | `src/sam/sams/__init__.py` |
| 2. New FHIR mapping | `src/piqi_mapping/patient_gender.py` | `src/piqi_mapping/__init__.py` |
| 3. New chain rule | `src/quality_rules/sam_rules_proof.py` | `src/quality_rules/__init__.py` |
| — Proof test | `tests/unit/test_pluggability_proof.py` | — |

The only edits to *existing* files are the three one-line imports in the
aggregator `__init__.py` modules — the registration entries the requirement
explicitly sanctions ("add one line registering it"). `Attr_IsFutureDate`
declares its prerequisite as the mnemonic string `"Attr_IsDate"`, reusing the
existing SAM with no import of it.

## Framework files with zero modifications

None of these were touched to add the proof:

- `src/sam/base.py` (SAM base class + Outcome)
- `src/sam/registry.py`
- `src/sam/runner.py` (chain runner)
- `src/piqi_mapping/base.py` (SimpleAttribute)
- `src/piqi_mapping/dispatcher.py` (mapping dispatcher)
- `src/quality_rules/sam_rules.py` (SamChainRule + birthDate rule)
- `src/sam/sams/attr_is_populated.py`, `attr_is_date.py`, `attr_is_past_date.py`
- `src/piqi_mapping/patient_birthdate.py`

## How a reviewer verifies the zero-diff claim

Once the birthDate work is committed as a baseline and the proof as a follow-up
commit, the diff of the proof commit must show only the four new files plus the
three one-line registration edits:

```bash
# From the proof commit, list only modified (not added) framework files:
git show --stat <proof-commit>            # expect: 4 new files, 3 __init__ edits
git diff <baseline>..<proof-commit> -- \
    src/sam/base.py src/sam/registry.py src/sam/runner.py \
    src/piqi_mapping/base.py src/piqi_mapping/dispatcher.py \
    src/quality_rules/sam_rules.py \
    src/sam/sams/attr_is_populated.py src/sam/sams/attr_is_date.py \
    src/sam/sams/attr_is_past_date.py src/piqi_mapping/patient_birthdate.py
# ^ must print nothing (zero changes to framework files)
```

## Disposition

The throwaway additions are kept as a **second worked example** of the pattern.
To remove them, delete the four new files and the three registration lines — no
other code changes are required, which is itself the point.
