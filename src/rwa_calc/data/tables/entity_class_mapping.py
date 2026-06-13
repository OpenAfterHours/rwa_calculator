"""
Entity-type to exposure-class mappings.

Pipeline position:
    Consumed by ``engine.classifier`` (entity_type → SA/IRB class via
    ``replace_strict``), ``data.tables.guarantor_rw`` (entity / guarantor
    SA-RW expression builders, including the hierarchy facility-share
    SA RW preview), and the
    SA / IRB / CRM guarantee branches that need to derive a guarantor's
    SA exposure class from its entity_type.

Key responsibilities:
- Map every supported ``entity_type`` input string to its CRR / Basel 3.1
  Standardised Approach exposure class (CRR Art. 112).
- Map every supported ``entity_type`` to its IRB exposure class — different
  from the SA class for RGLA / PSE counterparties (CRR Art. 147(3)/(4)(b)).
- Provide the inverse SA-class → tuple-of-entity-types mapping used by the
  entity-level SA RW preview (``data.tables.guarantor_rw.build_entity_rw_expr``).

References:
- CRR Art. 112 Table A2 — SA exposure classes
- CRR Art. 128 — high-risk items (SA-only, 150% unconditional)
- CRR Art. 134 — Other Items (SA-only, no IRB class)
- CRR Art. 147(3) — RGLA/PSE sovereign-equivalence under IRB
- CRR Art. 147(4)(b) — RGLA/PSE institution treatment under IRB
"""

from __future__ import annotations

from rwa_calc.domain.enums import ExposureClass

# entity_type → SA exposure class (for risk weight lookup)
ENTITY_TYPE_TO_SA_CLASS: dict[str, str] = {
    "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_sovereign": ExposureClass.RGLA.value,
    "rgla_institution": ExposureClass.RGLA.value,
    "pse_sovereign": ExposureClass.PSE.value,
    "pse_institution": ExposureClass.PSE.value,
    "mdb": ExposureClass.MDB.value,
    "mdb_named": ExposureClass.MDB.value,
    "international_org": ExposureClass.INTERNATIONAL_ORGANISATION.value,
    "institution": ExposureClass.INSTITUTION.value,
    "bank": ExposureClass.INSTITUTION.value,
    "ccp": ExposureClass.INSTITUTION.value,
    "financial_institution": ExposureClass.INSTITUTION.value,
    "corporate": ExposureClass.CORPORATE.value,
    "company": ExposureClass.CORPORATE.value,
    "individual": ExposureClass.RETAIL_OTHER.value,
    "retail": ExposureClass.RETAIL_OTHER.value,
    # Alias for "individual" / "retail" per CRR Art. 112(1)(h) — natural-person non-SME obligors.
    "natural_person": ExposureClass.RETAIL_OTHER.value,
    # Art. 112(1)(g): SL is a corporate sub-type under SA, not a separate class.
    # The sl_type column (from the specialised_lending join) drives SL-specific
    # risk weight lookup; the exposure_class_sa column is CORPORATE.
    "specialised_lending": ExposureClass.CORPORATE.value,
    "equity": ExposureClass.EQUITY.value,
    "covered_bond": ExposureClass.COVERED_BOND.value,
    "other_cash": ExposureClass.OTHER.value,
    "other_gold": ExposureClass.OTHER.value,
    "other_items_in_collection": ExposureClass.OTHER.value,
    "other_tangible": ExposureClass.OTHER.value,
    "other_residual_lease": ExposureClass.OTHER.value,
    # High-risk items (CRR Art. 128): 150% unconditional
    "high_risk": ExposureClass.HIGH_RISK.value,
    "high_risk_venture_capital": ExposureClass.HIGH_RISK.value,
    "high_risk_private_equity": ExposureClass.HIGH_RISK.value,
    "high_risk_speculative_re": ExposureClass.HIGH_RISK.value,
}

# entity_type → IRB exposure class (for IRB formula selection)
# Other Items (Art. 134) are SA-only — no IRB class exists for these.
# High-risk items (Art. 128) are SA-only — they map to HIGH_RISK for SA treatment.
ENTITY_TYPE_TO_IRB_CLASS: dict[str, str] = {
    "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_institution": ExposureClass.INSTITUTION.value,
    "pse_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "pse_institution": ExposureClass.INSTITUTION.value,
    "mdb": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "mdb_named": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "international_org": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "institution": ExposureClass.INSTITUTION.value,
    "bank": ExposureClass.INSTITUTION.value,
    "ccp": ExposureClass.INSTITUTION.value,
    "financial_institution": ExposureClass.INSTITUTION.value,
    "corporate": ExposureClass.CORPORATE.value,
    "company": ExposureClass.CORPORATE.value,
    "individual": ExposureClass.RETAIL_OTHER.value,
    "retail": ExposureClass.RETAIL_OTHER.value,
    # Alias for "individual" / "retail" per CRR Art. 112(1)(h) — natural-person non-SME obligors.
    "natural_person": ExposureClass.RETAIL_OTHER.value,
    "specialised_lending": ExposureClass.SPECIALISED_LENDING.value,
    "equity": ExposureClass.EQUITY.value,
    "covered_bond": ExposureClass.COVERED_BOND.value,
    "other_cash": ExposureClass.OTHER.value,
    "other_gold": ExposureClass.OTHER.value,
    "other_items_in_collection": ExposureClass.OTHER.value,
    "other_tangible": ExposureClass.OTHER.value,
    "other_residual_lease": ExposureClass.OTHER.value,
    # High-risk items (Art. 128) are SA-only — they map to OTHER for IRB
    # (no separate IRB treatment; HIGH_RISK is an SA exposure class).
    "high_risk": ExposureClass.HIGH_RISK.value,
    "high_risk_venture_capital": ExposureClass.HIGH_RISK.value,
    "high_risk_private_equity": ExposureClass.HIGH_RISK.value,
    "high_risk_speculative_re": ExposureClass.HIGH_RISK.value,
}

# Inverse of ENTITY_TYPE_TO_SA_CLASS: SA exposure class → tuple of entity_types.
# Derived at module load so any addition to ENTITY_TYPE_TO_SA_CLASS automatically
# flows through to consumers (e.g. the entity-level SA RW preview
# `build_entity_rw_expr` in data/tables/guarantor_rw.py).
ENTITY_TYPES_BY_SA_CLASS: dict[str, tuple[str, ...]] = {
    sa_class: tuple(et for et, c in ENTITY_TYPE_TO_SA_CLASS.items() if c == sa_class)
    for sa_class in dict.fromkeys(ENTITY_TYPE_TO_SA_CLASS.values())
}
