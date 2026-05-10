"""
P1.127 fixtures: CRR Art. 159 Pool B EL shortfall — AVA + other_OFR no double-count.

Pipeline position:
    fixture-builder output → test-writer → engine-implementer

Key responsibilities:
- One corporate counterparty (CP-P1127-A, GB, GBP) shared by both exposures.
- Two loan rows for AIRB (model CORP-AIRB-V1):
    EXP-P1127-ND: non-defaulted, EAD=1,500,000, PD=0.0050, LGD=0.45, M=2.5y
    EXP-P1127-D:  defaulted,     EAD=1,000,000, PD=1.0000, LGD=0.65, beel=0.45, M=1.0y
- AVA and other_OFR are columns on the loan parquet (pass-through to CRM processor
  and IRB adjustments stage, then aggregated once by the portfolio aggregator).
- Provisions are a separate SCRA parquet (beneficiary_type="loan") linked to each loan.
- One model-permission row: CORP-AIRB-V1, exposure_class="corporate", approach="advanced_irb".
- One rating row per counterparty: PD=0.0050 for non-defaulted path, PD=1.0 for defaulted.

Regression guard:
    The scenario exercises Art. 159(1) Pool B at the aggregation level to confirm that
    AVA and other_OFR are accumulated exactly once per-exposure — not double-counted by
    the portfolio aggregator — even when one exposure is defaulted (Art. 158(5) BEEL path)
    and one is non-defaulted (standard AIRB EL = PD × LGD × EAD).

Expected per-exposure outputs (hand-calc, for assertions in the acceptance test):
    EXP-P1127-ND:
        EL_ND      = PD × LGD × EAD = 0.0050 × 0.45 × 1,500,000 = 3,375
        pool_b_ND  = provisions(30,000) + AVA(40,000) + other_OFR(10,000) = 80,000
        shortfall_ND = max(0, 3,375 - 80,000) = 0       (excess = 76,625)
    EXP-P1127-D:
        EL_D       = beel × EAD = 0.45 × 1,000,000 = 450,000  (CRR Art. 158(5))
        pool_b_D   = provisions(120,000) + AVA(25,000) + other_OFR(5,000) = 150,000
        shortfall_D = max(0, 450,000 - 150,000) = 300,000  (excess = 0)

Expected aggregated outputs (two-branch Art. 159(3) rule):
    Non-defaulted pool: EL=3,375, pool_b=80,000   → excess  (pool_b > EL)
    Defaulted pool:     EL=450,000, pool_b=150,000 → shortfall (EL > pool_b)
    Art. 159(3): both conditions hold simultaneously (A<B AND D>C), so:
        total_el_shortfall              = 300,000   (defaulted pool only)
        total_el_excess_for_t2_cap      = 76,625    (non-defaulted pool only)
        total_expected_loss             = 453,375
        total_provisions_allocated      = 150,000
        total_ava_amount                = 65,000    (40,000 + 25,000)
        total_other_own_funds_reductions= 15,000    (10,000 + 5,000)
        total_pool_b                    = 230,000   (80,000 + 150,000)

References:
    - CRR Art. 158(5): defaulted EL = best-estimate expected loss (BEEL × EAD)
    - CRR Art. 159(1): Pool B = SCRA + GCRA + AVA + other own funds reductions
    - CRR Art. 159(3): two-branch no-cross-offset rule
    - CRR Art. 34 / Art. 105: Additional value adjustments (AVA)
    - src/rwa_calc/engine/irb/adjustments.py: compute_el_shortfall_excess
    - src/rwa_calc/engine/aggregator/_el_summary.py: compute_el_portfolio_summary
    - src/rwa_calc/engine/crm/processor.py:921-935: AVA/OFR pass-through

Usage:
    uv run python tests/fixtures/p1_127/p1_127.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP-P1127-A"

# Exposure references
LOAN_REF_ND: str = "LN-P1127-ND"  # non-defaulted AIRB exposure
LOAN_REF_D: str = "LN-P1127-D"  # defaulted AIRB exposure

# Rating / model IDs
RATING_REF_ND: str = "RTG-P1127-ND"
RATING_REF_D: str = "RTG-P1127-D"
MODEL_ID: str = "CORP-AIRB-V1"

# Provision references
PROV_REF_ND: str = "PROV-P1127-ND"
PROV_REF_D: str = "PROV-P1127-D"

# Dates
VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE_ND: date = date(2028, 7, 1)  # ~2.5 years from value date
MATURITY_DATE_D: date = date(2027, 1, 1)  # ~1.0 year from value date
RATING_DATE: date = date(2026, 1, 2)

# Non-defaulted exposure inputs
EAD_ND: float = 1_500_000.0
PD_ND: float = 0.0050
LGD_ND: float = 0.45
EFFECTIVE_MATURITY_ND: float = 2.5

# Defaulted exposure inputs
EAD_D: float = 1_000_000.0
PD_D: float = 1.0000
LGD_D: float = 0.65  # LGD-in-default
BEEL_D: float = 0.45  # best-estimate expected loss rate (Art. 158(5))
EFFECTIVE_MATURITY_D: float = 1.0

# Pool B components for non-defaulted exposure
PROV_ND: float = 30_000.0
AVA_ND: float = 40_000.0
OTHER_OFR_ND: float = 10_000.0

# Pool B components for defaulted exposure
PROV_D: float = 120_000.0
AVA_D: float = 25_000.0
OTHER_OFR_D: float = 5_000.0

# Expected per-exposure outputs (for test assertions)
EXPECTED_EL_ND: float = PD_ND * LGD_ND * EAD_ND  # 3_375.0
EXPECTED_POOL_B_ND: float = PROV_ND + AVA_ND + OTHER_OFR_ND  # 80_000.0
EXPECTED_SHORTFALL_ND: float = 0.0  # pool_b > EL
EXPECTED_EXCESS_ND: float = EXPECTED_POOL_B_ND - EXPECTED_EL_ND  # 76_625.0

EXPECTED_EL_D: float = BEEL_D * EAD_D  # 450_000.0
EXPECTED_POOL_B_D: float = PROV_D + AVA_D + OTHER_OFR_D  # 150_000.0
EXPECTED_SHORTFALL_D: float = EXPECTED_EL_D - EXPECTED_POOL_B_D  # 300_000.0
EXPECTED_EXCESS_D: float = 0.0  # EL > pool_b

# Expected portfolio-level aggregates (two-branch Art. 159(3) rule)
EXPECTED_TOTAL_EL: float = EXPECTED_EL_ND + EXPECTED_EL_D  # 453_375.0
EXPECTED_TOTAL_PROV: float = PROV_ND + PROV_D  # 150_000.0
EXPECTED_TOTAL_AVA: float = AVA_ND + AVA_D  # 65_000.0
EXPECTED_TOTAL_OTHER_OFR: float = OTHER_OFR_ND + OTHER_OFR_D  # 15_000.0
EXPECTED_TOTAL_POOL_B: float = EXPECTED_POOL_B_ND + EXPECTED_POOL_B_D  # 230_000.0
# Art. 159(3): non-defaulted has excess, defaulted has shortfall — no cross-offset
EXPECTED_TOTAL_SHORTFALL: float = EXPECTED_SHORTFALL_D  # 300_000.0
EXPECTED_TOTAL_EXCESS_T2: float = EXPECTED_EXCESS_ND  # 76_625.0


# ---------------------------------------------------------------------------
# Minimal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.127 counterparty: corporate, GB, GBP."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    total_assets: float
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.127 loan row — carries AVA and other_OFR as pass-through columns.

    ava_amount and other_own_funds_reductions are optional columns on the
    loan parquet that the CRM processor preserves (processor.py:921-935) and
    the IRB adjustments stage reads to compute Pool B.  They are NOT in
    LOAN_SCHEMA so enforce_schema ignores them — they survive the loader
    as extra columns and are later picked up by compute_el_shortfall_excess().
    """

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    lgd: float
    beel: float
    seniority: str
    effective_maturity: float
    # Pool B pass-through columns (not in LOAN_SCHEMA; preserved by loader)
    ava_amount: float
    other_own_funds_reductions: float

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
            "ava_amount": self.ava_amount,
            "other_own_funds_reductions": self.other_own_funds_reductions,
        }


@dataclass(frozen=True)
class _Rating:
    """P1.127 internal rating row."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float
    rating_date: date
    is_solicited: bool
    model_id: str

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """P1.127 model permission: AIRB for corporate."""

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None
    excluded_book_codes: str | None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


@dataclass(frozen=True)
class _Provision:
    """P1.127 SCRA provision row — linked to a specific loan."""

    provision_reference: str
    provision_type: str
    ifrs9_stage: int
    currency: str
    amount: float
    as_of_date: date
    beneficiary_type: str
    beneficiary_reference: str

    def to_dict(self) -> dict:
        return {
            "provision_reference": self.provision_reference,
            "provision_type": self.provision_type,
            "ifrs9_stage": self.ifrs9_stage,
            "currency": self.currency,
            "amount": self.amount,
            "as_of_date": self.as_of_date,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1127_counterparty() -> pl.DataFrame:
    """
    Return the P1.127 counterparty as a single-row DataFrame.

    One corporate counterparty CP-P1127-A shared by both the non-defaulted
    and defaulted loans.  annual_revenue=200m keeps the entity below the
    Basel 3.1 large-corp threshold (GBP 440m), avoiding the Art. 147A(1)(d)
    F-IRB restriction that would block AIRB.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P1.127 General Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,  # < 440m large-corp threshold
            total_assets=400_000_000.0,
            default_status=False,  # default status is per-exposure via beel/PD=1
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1127_loans() -> pl.DataFrame:
    """
    Return two P1.127 loan rows as a DataFrame.

    Loan 1 — EXP-P1127-ND (non-defaulted AIRB):
        EAD=1,500,000 GBP, PD=0.0050, LGD=0.45, M=2.5y
        beel=0.0 (non-defaulted — beel unused by Art. 158(1) standard formula)
        ava_amount=40,000, other_own_funds_reductions=10,000

    Loan 2 — EXP-P1127-D (defaulted AIRB):
        EAD=1,000,000 GBP, PD=1.0000, LGD=0.65, M=1.0y
        beel=0.45 (drives Art. 158(5) EL = BEEL × EAD = 450,000)
        ava_amount=25,000, other_own_funds_reductions=5,000

    ava_amount and other_own_funds_reductions are NOT in LOAN_SCHEMA; they
    survive enforce_schema as extra columns (enforce_schema only casts declared
    columns) and are preserved by the CRM processor as Pool B pass-through
    components per processor.py:921-935.
    """
    schema_dtypes = dtypes_of(LOAN_SCHEMA)
    # Add the extra Pool B columns with explicit Float64 types.
    schema_dtypes["ava_amount"] = pl.Float64
    schema_dtypes["other_own_funds_reductions"] = pl.Float64

    rows = [
        _Loan(
            loan_reference=LOAN_REF_ND,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_ND,
            currency="GBP",
            drawn_amount=EAD_ND,
            interest=0.0,
            lgd=LGD_ND,
            beel=0.0,  # non-defaulted: beel not used for EL calc
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY_ND,
            ava_amount=AVA_ND,
            other_own_funds_reductions=OTHER_OFR_ND,
        ),
        _Loan(
            loan_reference=LOAN_REF_D,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_D,
            currency="GBP",
            drawn_amount=EAD_D,
            interest=0.0,
            lgd=LGD_D,
            beel=BEEL_D,  # defaulted: EL = beel × EAD per Art. 158(5)
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY_D,
            ava_amount=AVA_D,
            other_own_funds_reductions=OTHER_OFR_D,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=schema_dtypes)


def create_p1127_ratings() -> pl.DataFrame:
    """
    Return two P1.127 internal rating rows as a DataFrame.

    Both ratings are for counterparty CP-P1127-A and reference model CORP-AIRB-V1.
    The non-defaulted path uses PD=0.0050; the defaulted path uses PD=1.0000.
    Two rows are needed because the ratings table drives model_id propagation
    — both loans share the same counterparty and therefore the same rating
    rows.  The classifier / hierarchy resolver deduplicates per counterparty.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF_ND,
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3B",
            cqs=3,
            pd=PD_ND,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1127_model_permission() -> pl.DataFrame:
    """
    Return the P1.127 model permission as a single-row DataFrame.

    Grants AIRB for the corporate exposure class using CORP-AIRB-V1.
    Dedicated model_id avoids cross-test interference.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="advanced_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def create_p1127_provisions() -> pl.DataFrame:
    """
    Return two P1.127 provision rows as a DataFrame.

    PROV-P1127-ND: SCRA 30,000 GBP for non-defaulted loan LN-P1127-ND
        Stage 1 (performing) — SCRA against specific IRB exposure.
    PROV-P1127-D:  SCRA 120,000 GBP for defaulted loan LN-P1127-D
        Stage 3 (credit-impaired) — specific provision against defaulted exposure.

    Both provisions are beneficiary_type="loan" so the CRM processor matches
    them to their respective loan rows via beneficiary_reference = loan_reference.
    """
    rows = [
        _Provision(
            provision_reference=PROV_REF_ND,
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=PROV_ND,
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_ND,
        ),
        _Provision(
            provision_reference=PROV_REF_D,
            provision_type="SCRA",
            ifrs9_stage=3,
            currency="GBP",
            amount=PROV_D,
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_D,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(PROVISION_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers — one parquet per artefact type
# ---------------------------------------------------------------------------


def save_p1127_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.127 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory.  Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1127_counterparty()),
        ("loan", create_p1127_loans()),
        ("rating", create_p1127_ratings()),
        ("model_permission", create_p1127_model_permission()),
        ("provision", create_p1127_provisions()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.127 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>2} row(s)  ->  {path.name}")
    print("-" * 70)
    print("Scenario: Art. 159 Pool B — AVA + other_OFR no double-count")
    print(
        f"  EXP-P1127-ND: EL={EXPECTED_EL_ND:,.0f}, pool_b={EXPECTED_POOL_B_ND:,.0f}, "
        f"shortfall={EXPECTED_SHORTFALL_ND:,.0f}, excess={EXPECTED_EXCESS_ND:,.0f}"
    )
    print(
        f"  EXP-P1127-D:  EL={EXPECTED_EL_D:,.0f}, pool_b={EXPECTED_POOL_B_D:,.0f}, "
        f"shortfall={EXPECTED_SHORTFALL_D:,.0f}"
    )
    print(
        f"  Portfolio:    total_el={EXPECTED_TOTAL_EL:,.0f}, "
        f"total_pool_b={EXPECTED_TOTAL_POOL_B:,.0f}, "
        f"total_shortfall={EXPECTED_TOTAL_SHORTFALL:,.0f}"
    )
    print(f"  AVA:          {EXPECTED_TOTAL_AVA:,.0f}  other_OFR: {EXPECTED_TOTAL_OTHER_OFR:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1127_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
