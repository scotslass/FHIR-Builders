"""Inject known defects into a fraction of synthetic patient bundles.

Given a list of Synthea patient transaction Bundles, deterministically pick
~``fraction`` of them and apply one defect from :data:`seed.defect_catalog.CATALOG`
to each (rotating through the catalog so every defect type is represented when
there are enough patients). Mutated resources are tagged ``defect:<code>``.

Returns a manifest describing exactly which patient got which defect — the
ground truth a quality run is scored against (see ``verify_seed``).
"""

from __future__ import annotations

import random

from seed.defect_catalog import CATALOG, Defect, add_tag


def _first_resource(bundle: dict, resource_type: str,
                    predicate=None) -> dict | None:
    """Return the first resource of ``resource_type`` in a Bundle, or None."""
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") != resource_type:
            continue
        if predicate is not None and not predicate(resource):
            continue
        return resource
    return None


def _patient_label(bundle: dict) -> dict[str, str]:
    """Extract a human/identifier label for the Patient in a bundle."""
    patient = _first_resource(bundle, "Patient") or {}
    name = ""
    for nm in patient.get("name", []):
        given = " ".join(nm.get("given", []))
        name = f"{given} {nm.get('family', '')}".strip()
        if name:
            break
    # Synthea stamps a stable identifier under its own system.
    identifier = ""
    for ident in patient.get("identifier", []):
        if ident.get("system", "").endswith("synthetichealth/synthea"):
            identifier = ident.get("value", "")
            break
    return {"name": name, "synthea_id": identifier, "fhir_id": patient.get("id", "")}


def corrupt(bundles: list[dict], fraction: float = 0.10,
            seed: int = 1234) -> dict:
    """Apply defects to ~``fraction`` of ``bundles`` in place.

    Parameters
    ----------
    bundles:
        Patient transaction Bundles (mutated in place).
    fraction:
        Share of patients to corrupt (0.10 = 10%). At least one patient is
        corrupted when the list is non-empty.
    seed:
        RNG seed so the same input yields the same corrupted set every run.

    Returns
    -------
    dict
        A manifest: run parameters plus a ``patients`` list, one entry per
        corrupted patient with the defect applied and the rule expected to
        catch it.
    """
    total = len(bundles)
    manifest: dict = {
        "fraction": fraction,
        "seed": seed,
        "total_patients": total,
        "corrupted_patients": 0,
        "expected_rule_ids": [],
        "patients": [],
    }
    if total == 0:
        return manifest

    k = max(1, round(total * fraction))
    rng = random.Random(seed)
    targets = sorted(rng.sample(range(total), min(k, total)))

    expected_rules: set[str] = set()
    for i, idx in enumerate(targets):
        bundle = bundles[idx]
        defect: Defect = CATALOG[i % len(CATALOG)]
        target = _first_resource(bundle, defect.resource_type, defect.predicate)

        applied = bool(target) and defect.apply(target)
        if applied:
            add_tag(target, f"defect:{defect.code}")
            expected_rules.add(defect.rule_id)

        label = _patient_label(bundle)
        manifest["patients"].append({
            **label,
            "bundle_index": idx,
            "defect": {
                "code": defect.code,
                "rule_id": defect.rule_id,
                "resource_type": defect.resource_type,
                "description": defect.description,
                "applied": applied,
            },
        })

    manifest["corrupted_patients"] = sum(
        1 for p in manifest["patients"] if p["defect"]["applied"]
    )
    manifest["expected_rule_ids"] = sorted(expected_rules)
    return manifest
