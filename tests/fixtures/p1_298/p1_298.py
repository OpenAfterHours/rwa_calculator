"""
P1.298 fixtures: third-country PSE guarantors and the CRR Art. 116(5) jurisdiction gate.

Built in memory (no parquet, so nothing to register in ``generate_all.py``). Two
books, both run end-to-end through ``PipelineOrchestrator``:

SA book (``build_sa_bundle``, PermissionMode.STANDARDISED) — one GBP 1,000,000
senior term loan per scenario, each fully covered by one guarantor:

    loan             obligor (pre-CRM RW)        guarantor                   expected g
    L_US_NULL        US company, equiv=True 100% PSE US CQS1, flag null      100% (declined)
    L_US_TRUE        GB company, unrated  100%   PSE US CQS1, flag True       20%
    L_GB_NULL        GB company, unrated  100%   PSE GB CQS1, flag null       20%
    L_NOCTRY_NULL    GB company, unrated  100%   PSE (no country) CQS1, null 100% (declined)
    L_US_CQS6        GB company, CQS6     150%   PSE US CQS6, flag null      100% (now beneficial)
    L_RGLA_US        GB company, unrated  100%   RGLA US CQS1, flag null      20% (RGLA control)
    L_PSE_DIRECT     PSE US unrated, flag null (no guarantee)                100% direct (P1.252)

``L_US_NULL``'s obligor is a US counterparty WITH equivalence asserted, so a gate
wired to the obligor's ``cp_*`` jurisdiction instead of the guarantor's would
grant the 20%.

IRB book (``build_irb_bundle``) — the ``pse_rgla_guarantor`` fixture (an F-IRB
corporate borrower whose own weight is above 100% in both regimes, guaranteed by
rated PSE and unrated RGLA guarantors with no PD, so the guaranteed leg is
priced by RWSM via ``guarantor_rw_sa``) with its two GB PSE guarantors moved to
the US: the CQS2 one with the flag given by ``cqs2_flag``, the CQS3 one with
``cqs3_flag``.

References:
    - CRR Art. 116(5); PS1/26 Art. 116(3A)
    - CRR Art. 235(1); PS1/26 Art. 235(1)(a)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.pse_rgla_guarantor.pse_rgla_guarantor import (
    GUARANTOR_PSE_CQS2_REF,
    GUARANTOR_PSE_CQS3_REF,
    create_pse_rgla_counterparties,
    create_pse_rgla_facilities,
    create_pse_rgla_guarantees,
    create_pse_rgla_loans,
    create_pse_rgla_model_permission,
    create_pse_rgla_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

VALUE_DATE: date = date(2026, 1, 2)
MATURITY_DATE: date = date(2031, 1, 2)  # 5y — no maturity mismatch, not short-term
EAD: float = 1_000_000.0

NON_EQUIVALENT_RW: float = 1.00  # CRR Art. 116(5) "Otherwise ... 100 %"
TABLE_2A_CQS1: float = 0.20  # Art. 116(2) Table 2A (identical in both regimes)
TABLE_1B_CQS1: float = 0.20  # Art. 115(1)(b) Table 1B
OBLIGOR_UNRATED_RW: float = 1.00  # unrated corporate, both regimes
OBLIGOR_CQS6_RW: float = 1.50  # corporate CQS6, both regimes

# loan -> (obligor, guarantor or None, expected guarantor_rw or None,
#          expected rwa_final, pre-fix rwa_final)
SA_SCENARIOS: dict[str, tuple[str, str | None, float | None, float, float]] = {
    "L_US_NULL": (
        "CP_BORR_US_EQUIV",
        "CP_G_PSE_US_NULL",
        NON_EQUIVALENT_RW,
        EAD * 1.00,
        EAD * 0.20,
    ),
    "L_US_TRUE": ("CP_BORR_UNRATED", "CP_G_PSE_US_TRUE", TABLE_2A_CQS1, EAD * 0.20, EAD * 0.20),
    "L_GB_NULL": ("CP_BORR_UNRATED", "CP_G_PSE_GB_NULL", TABLE_2A_CQS1, EAD * 0.20, EAD * 0.20),
    "L_NOCTRY_NULL": (
        "CP_BORR_UNRATED",
        "CP_G_PSE_NOCTRY_NULL",
        NON_EQUIVALENT_RW,
        EAD * 1.00,
        EAD * 0.20,
    ),
    "L_US_CQS6": ("CP_BORR_CQS6", "CP_G_PSE_US_CQS6", NON_EQUIVALENT_RW, EAD * 1.00, EAD * 1.50),
    "L_RGLA_US": ("CP_BORR_UNRATED", "CP_G_RGLA_US_NULL", TABLE_1B_CQS1, EAD * 0.20, EAD * 0.20),
    "L_PSE_DIRECT": ("CP_PSE_DIRECT_US_NULL", None, None, EAD * 1.00, EAD * 1.00),
}

# The PSE counterparties outside the UK (or with no country) whose
# is_equivalent_jurisdiction is null — what the SA011 warning counts.
SA_UNASSERTED_PSE_COUNTERPARTIES: tuple[str, ...] = (
    "CP_G_PSE_US_NULL",
    "CP_G_PSE_NOCTRY_NULL",
    "CP_G_PSE_US_CQS6",
    "CP_PSE_DIRECT_US_NULL",
)

# (reference, entity_type, country, is_equivalent_jurisdiction, external CQS)
_SA_COUNTERPARTIES: tuple[tuple[str, str, str | None, bool | None, int | None], ...] = (
    ("CP_BORR_UNRATED", "corporate", "GB", None, None),
    ("CP_BORR_CQS6", "corporate", "GB", None, 6),
    ("CP_BORR_US_EQUIV", "corporate", "US", True, None),
    ("CP_G_PSE_US_NULL", "pse_institution", "US", None, 1),
    ("CP_G_PSE_US_TRUE", "pse_institution", "US", True, 1),
    ("CP_G_PSE_GB_NULL", "pse_institution", "GB", None, 1),
    ("CP_G_PSE_NOCTRY_NULL", "pse_institution", None, None, 1),
    ("CP_G_PSE_US_CQS6", "pse_institution", "US", None, 6),
    ("CP_G_RGLA_US_NULL", "rgla_institution", "US", None, 1),
    ("CP_PSE_DIRECT_US_NULL", "pse_institution", "US", None, None),
)


def build_sa_bundle() -> RawDataBundle:
    """The SA book: one fully guaranteed loan per guarantor scenario, plus one direct PSE loan."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": ref,
                "counterparty_name": f"P1.298 {ref}",
                "entity_type": entity_type,
                "country_code": country,
                "is_equivalent_jurisdiction": equivalent,
                "annual_revenue": 100_000_000.0 if entity_type == "corporate" else None,
                "total_assets": 500_000_000.0 if entity_type == "corporate" else None,
                "default_status": False,
                "is_financial_sector_entity": False,
                "apply_fi_scalar": False,
            }
            for ref, entity_type, country, equivalent, _cqs in _SA_COUNTERPARTIES
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": f"RTG_{ref}",
                "counterparty_reference": ref,
                "rating_type": "external",
                "rating_agency": "Moody's",
                "cqs": cqs,
                "pd": None,
                "rating_date": VALUE_DATE,
                "is_solicited": True,
            }
            for ref, _et, _country, _equivalent, cqs in _SA_COUNTERPARTIES
            if cqs is not None
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": loan_ref,
                "product_type": "term_loan",
                "book_code": "CORP_LENDING",
                "counterparty_reference": obligor,
                "value_date": VALUE_DATE,
                "maturity_date": MATURITY_DATE,
                "currency": "GBP",
                "drawn_amount": EAD,
                "interest": 0.0,
                "seniority": "senior",
            }
            for loan_ref, (obligor, *_rest) in SA_SCENARIOS.items()
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    guarantees = pl.DataFrame(
        [
            {
                "guarantee_reference": f"GTE_{loan_ref}",
                "guarantee_type": "guarantee",
                "guarantor": guarantor,
                "currency": "GBP",
                "maturity_date": MATURITY_DATE,
                "amount_covered": EAD,
                "percentage_covered": 1.0,
                "beneficiary_type": "loan",
                "beneficiary_reference": loan_ref,
                "protection_type": "guarantee",
                "includes_restructuring": True,
                "original_maturity_years": 5.0,
                "guarantor_seniority": "senior",
            }
            for loan_ref, (_obligor, guarantor, *_rest) in SA_SCENARIOS.items()
            if guarantor is not None
        ],
        schema=dtypes_of(GUARANTEE_SCHEMA),
    )
    return make_raw_bundle(
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=guarantees,
        ratings=ratings,
    )


def build_irb_bundle(*, cqs2_flag: bool | None, cqs3_flag: bool | None) -> RawDataBundle:
    """The ``pse_rgla_guarantor`` IRB book with both PSE guarantors moved to the US.

    Args:
        cqs2_flag: ``is_equivalent_jurisdiction`` for the CQS2 PSE guarantor.
        cqs3_flag: ``is_equivalent_jurisdiction`` for the CQS3 PSE guarantor.
    """
    reference = pl.col("counterparty_reference")
    moved = reference.is_in([GUARANTOR_PSE_CQS2_REF, GUARANTOR_PSE_CQS3_REF])
    counterparties = create_pse_rgla_counterparties().with_columns(
        pl.when(moved).then(pl.lit("US")).otherwise(pl.col("country_code")).alias("country_code"),
        pl.when(reference == GUARANTOR_PSE_CQS2_REF)
        .then(pl.lit(cqs2_flag, dtype=pl.Boolean))
        .when(reference == GUARANTOR_PSE_CQS3_REF)
        .then(pl.lit(cqs3_flag, dtype=pl.Boolean))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
        .alias("is_equivalent_jurisdiction"),
    )
    return make_raw_bundle(
        facilities=create_pse_rgla_facilities(),
        loans=create_pse_rgla_loans(),
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=create_pse_rgla_guarantees(),
        ratings=create_pse_rgla_ratings(),
        model_permissions=create_pse_rgla_model_permission(),
    )
