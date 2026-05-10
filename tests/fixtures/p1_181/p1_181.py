"""
Generate P1.181 fixtures: CRR Art. 126(2)(d) commercial RE proportion split.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce two counterparty rows: corporate unrated (CQS=null) and corporate CQS=1.
- Produce three loan rows exercising the Art. 126(2)(d) proportion-split rule:
    LN-CRE-A: LTV=0.40, CP-CRE-CORP-UNRATED → whole loan at 50% (low LTV regression)
    LN-CRE-B: LTV=0.80, CP-CRE-CORP-UNRATED → split: 50%*0.625 + 100%*0.375 = 68.75%
    LN-CRE-C: LTV=0.80, CP-CRE-CORP-CQS1    → split: 50%*0.625 +  20%*0.375 = 38.75%
- Produce two rating rows: null-CQS for unrated, CQS=1 for the CQS-1 counterparty.

Regulatory rule under test (UK CRR Art. 126(2)(d)):
    Where CRE has income cover (rental income >= 1.5x interest), split the exposure:
      - Portion not exceeding 50% of property value → 50% risk weight (Art. 126(2)(a)/(b))
      - Residual portion above 50% MV → unsecured counterparty risk weight (Art. 124(1))
    "Unsecured counterparty risk weight" means the Art. 122 corporate CQS lookup, NOT
    a fixed 100%.  Exposure C discriminates: a naïve 100%-residual fix passes A and B
    but fails C.

Bug in current engine (pre-fix, engine/sa/namespace.py:577-585):
    The residual leg uses the constant `cre_rw_standard` (= 1.00) regardless of
    counterparty CQS.  Art. 126(2)(d) / Art. 124(1) require the counterparty's
    unsecured risk weight, so for a CQS=1 corporate the residual must be 20%, not 100%.

Hand-calculation (CRR, CalculationConfig.crr()):
    CRE constants:
        ltv_threshold = 0.50   (COMMERCIAL_RE_PARAMS["ltv_threshold"])
        cre_rw_secured = 0.50  (COMMERCIAL_RE_PARAMS["rw_low_ltv"])

    Exposure A — LTV=0.40, unrated:
        secured_share  = min(1.0, 0.50/0.40) = 1.0
        residual_share = 0.0
        avg_rw         = 0.50*1.0 + 1.00*0.0 = 0.50
        rwa            = 1_000_000 * 0.50 = 500_000.00

    Exposure B — LTV=0.80, unrated:
        secured_share  = min(1.0, 0.50/0.80) = 0.625
        residual_share = 0.375
        counterparty_rw = 1.00  (Art. 122, unrated)
        avg_rw          = 0.50*0.625 + 1.00*0.375 = 0.6875
        rwa             = 1_000_000 * 0.6875 = 687_500.00

    Exposure C — LTV=0.80, CQS=1:
        secured_share  = 0.625
        residual_share = 0.375
        counterparty_rw = 0.20  (Art. 122 Table 6, CQS=1)
        avg_rw          = 0.50*0.625 + 0.20*0.375 = 0.3875
        rwa             = 1_000_000 * 0.3875 = 387_500.00

Config: CalculationConfig.crr(), is_basel_3_1=False.

Expected outputs (tolerances: 1e-6 on RW, 1e-2 on RWA):
    LN-CRE-A: risk_weight=0.5000, rwa=500_000.00
    LN-CRE-B: risk_weight=0.6875, rwa=687_500.00
    LN-CRE-C: risk_weight=0.3875, rwa=387_500.00

References:
    - UK CRR Art. 126(2)(d): CRE proportion split (secured/residual legs)
    - UK CRR Art. 124(1): residual portion gets unsecured counterparty risk weight
    - UK CRR Art. 122 Table 6: corporate CQS risk weights
    - src/rwa_calc/data/tables/crr_risk_weights.py: CommercialREParams (lines 518-555)
    - src/rwa_calc/engine/sa/namespace.py: _crr_append_real_estate_branches (lines 562-598)
    - docs/specifications/crr/sa-risk-weights.md: CRE section D3.36 bug admonition

Usage:
    uv run python tests/fixtures/p1_181/p1_181.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
COUNTERPARTY_REF_UNRATED: str = "CP-CRE-CORP-UNRATED"
COUNTERPARTY_REF_CQS1: str = "CP-CRE-CORP-CQS1"

# Loan (exposure) references
LOAN_REF_A: str = "LN-CRE-A"  # LTV=0.40, unrated → 50% whole-loan (regression)
LOAN_REF_B: str = "LN-CRE-B"  # LTV=0.80, unrated → 68.75% blended
LOAN_REF_C: str = "LN-CRE-C"  # LTV=0.80, CQS=1  → 38.75% blended (discriminating)

# Rating references
RATING_REF_UNRATED: str = "RTG-CRE-UNRATED"
RATING_REF_CQS1: str = "RTG-CRE-CQS1"

# Common dates (CRR framework — pre-2027 value_date)
VALUE_DATE: date = date(2026, 3, 1)
MATURITY_DATE: date = date(2031, 3, 1)  # 5-year term loan

# All three exposures: EAD = drawn_amount = 1,000,000 GBP (interest=0)
EAD: float = 1_000_000.0

# LTV values
LTV_LOW: float = 0.40  # Exposure A — below 50% threshold → whole loan at 50%
LTV_HIGH: float = 0.80  # Exposures B and C — above 50% threshold → proportion split

# CQS values (Art. 122 Table 6)
# CQS=None → unrated → corporate RW = 100% (Art. 122(1)(d))
# CQS=1    → 20% (Art. 122(1)(a))
CQS_UNRATED: int | None = None
CQS_1: int = 1

# ---------------------------------------------------------------------------
# Expected outputs — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

# CRE proportion-split constants (Art. 126(2))
_LTV_THRESHOLD: float = 0.50  # 50% MV threshold
_CRE_RW_SECURED: float = 0.50  # preferential rate for secured portion

# Exposure A (LTV=0.40, unrated):
#   secured_share = min(1.0, 0.50/0.40) = 1.0 → avg_rw = 0.50
EXPECTED_SECURED_SHARE_A: float = 1.0
EXPECTED_RW_A: float = 0.50
EXPECTED_RWA_A: float = EAD * EXPECTED_RW_A  # 500_000.00

# Exposure B (LTV=0.80, unrated):
#   secured_share = min(1.0, 0.50/0.80) = 0.625; counterparty_rw = 1.00
#   avg_rw = 0.50*0.625 + 1.00*0.375 = 0.6875
EXPECTED_SECURED_SHARE_B: float = 0.625
EXPECTED_RESIDUAL_SHARE_B: float = 0.375
EXPECTED_COUNTERPARTY_RW_UNRATED: float = 1.00  # Art. 122, unrated
EXPECTED_RW_B: float = (
    _CRE_RW_SECURED * EXPECTED_SECURED_SHARE_B
    + EXPECTED_COUNTERPARTY_RW_UNRATED * EXPECTED_RESIDUAL_SHARE_B
)  # 0.6875
EXPECTED_RWA_B: float = EAD * EXPECTED_RW_B  # 687_500.00

# Exposure C (LTV=0.80, CQS=1):
#   secured_share = 0.625; counterparty_rw = 0.20 (Art. 122 CQS=1)
#   avg_rw = 0.50*0.625 + 0.20*0.375 = 0.3875
EXPECTED_COUNTERPARTY_RW_CQS1: float = 0.20  # Art. 122 Table 6, CQS=1
EXPECTED_RW_C: float = (
    _CRE_RW_SECURED * EXPECTED_SECURED_SHARE_B
    + EXPECTED_COUNTERPARTY_RW_CQS1 * EXPECTED_RESIDUAL_SHARE_B
)  # 0.3875
EXPECTED_RWA_C: float = EAD * EXPECTED_RW_C  # 387_500.00

# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    Corporate counterparty for CRE Art. 126(2)(d) proportion-split test.

    entity_type=corporate routes to Art. 122 risk weights on the residual leg.
    is_natural_person=False: institutional, not individual (Art. 126 applies to both,
    but the proposal explicitly sets this to False).
    annual_revenue=None: no SME classification needed for this SA scenario.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_natural_person: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_natural_person": self.is_natural_person,
        }


@dataclass(frozen=True)
class _Loan:
    """
    CRE loan exposure with LTV, income cover, and property type.

    ltv, has_income_cover, and property_type are CLASSIFIER_OUTPUT_SCHEMA columns
    that are also accepted as pass-through input columns by the loader.  Providing
    them on the loan row bypasses the need for a separate collateral row and ensures
    the SA namespace can access them directly during risk weight computation.

    All three exposures share:
        - drawn_amount=1_000_000 GBP (EAD = drawn_amount, interest=0)
        - has_income_cover=True: triggers Art. 126(2) income-cover gate
        - property_type="commercial": routes to _is_commercial_re_class()
        - is_defaulted=False: standard (non-defaulted) CRE path
        - qualifies_as_retail=False: not a retail CRE exposure
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    book_code: str
    is_sft: bool
    # CRE-specific fields: CLASSIFIER_OUTPUT_SCHEMA pass-through columns
    ltv: float
    has_income_cover: bool
    property_type: str
    is_defaulted: bool
    qualifies_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "book_code": self.book_code,
            "is_sft": self.is_sft,
            "ltv": self.ltv,
            "has_income_cover": self.has_income_cover,
            "property_type": self.property_type,
            "is_defaulted": self.is_defaulted,
            "qualifies_as_retail": self.qualifies_as_retail,
        }


@dataclass(frozen=True)
class _Rating:
    """
    Rating row for CRE counterparties.

    For CP-CRE-CORP-UNRATED: cqs=None (unrated) → Art. 122 unrated → 100% corporate RW.
    For CP-CRE-CORP-CQS1:    cqs=1               → Art. 122 CQS=1 → 20% corporate RW.

    rating_type=external: signals this is an ECAI-derived CQS, not an internal PD model.
    model_id=None: no IRB model → SA path enforced.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str | None
    rating_value: str | None
    cqs: int | None
    pd: float | None
    rating_date: date
    is_solicited: bool
    model_id: str | None

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


# ---------------------------------------------------------------------------
# CRE loan fixture schema
# (extends LOAN_SCHEMA with CRE pass-through columns)
# ---------------------------------------------------------------------------

_LOAN_FIXTURE_SCHEMA: dict[str, pl.DataType] = {
    **dtypes_of(LOAN_SCHEMA),
    # CLASSIFIER_OUTPUT_SCHEMA pass-through columns — present on input loan rows
    # so the SA namespace can access them without a separate collateral join.
    "ltv": pl.Float64,
    "has_income_cover": pl.Boolean,
    "property_type": pl.String,
    "is_defaulted": pl.Boolean,
    "qualifies_as_retail": pl.Boolean,
}


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1181_counterparties() -> pl.DataFrame:
    """
    Return two P1.181 counterparties as a DataFrame.

    CP-CRE-CORP-UNRATED: corporate, unrated (no external CQS) — drives 100% residual RW
        under Art. 122 unrated and the current buggy engine (both give 100%).
    CP-CRE-CORP-CQS1: corporate, CQS=1 (via rating row) — discriminates the correct
        proportion-split fix from a naïve 100%-residual workaround: correct fix yields
        20% residual; naïve fix stays at 100%.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_UNRATED,
            counterparty_name="CRE Corp Unrated — P1.181",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_natural_person=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_CQS1,
            counterparty_name="CRE Corp CQS1 — P1.181",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1181_loans() -> pl.DataFrame:
    """
    Return three P1.181 loan rows as a DataFrame.

    LN-CRE-A (Exposure A) — LTV=0.40, unrated:
        secured_share = min(1.0, 0.50/0.40) = 1.0 → whole-loan 50% RW.
        Acts as the regression anchor: any correct implementation must produce 50%.

    LN-CRE-B (Exposure B) — LTV=0.80, unrated:
        secured_share=0.625, residual_share=0.375, counterparty_rw=1.00.
        avg_rw = 0.6875. Bug evidence: current engine returns 1.00.

    LN-CRE-C (Exposure C) — LTV=0.80, CQS=1:
        secured_share=0.625, residual_share=0.375, counterparty_rw=0.20.
        avg_rw = 0.3875. Discriminates correct fix from naïve 100%-residual workaround.
    """
    rows = [
        # ====================================================================
        # Exposure A: LTV=0.40, unrated — low-LTV regression
        # secured_share=1.0 → avg_rw=0.50, rwa=500,000
        # ====================================================================
        _Loan(
            loan_reference=LOAN_REF_A,
            counterparty_reference=COUNTERPARTY_REF_UNRATED,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
            book_code="BANKING",
            is_sft=False,
            ltv=LTV_LOW,  # 0.40 — below 50% LTV threshold
            has_income_cover=True,  # income cover met → Art. 126(2) applies
            property_type="commercial",
            is_defaulted=False,
            qualifies_as_retail=False,
        ),
        # ====================================================================
        # Exposure B: LTV=0.80, unrated — high-LTV, residual=100% (unrated)
        # secured_share=0.625, avg_rw=0.6875, rwa=687,500
        # Bug evidence: pre-fix engine yields rwa=1,000,000
        # ====================================================================
        _Loan(
            loan_reference=LOAN_REF_B,
            counterparty_reference=COUNTERPARTY_REF_UNRATED,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
            book_code="BANKING",
            is_sft=False,
            ltv=LTV_HIGH,  # 0.80 — above 50% LTV threshold → proportion split
            has_income_cover=True,
            property_type="commercial",
            is_defaulted=False,
            qualifies_as_retail=False,
        ),
        # ====================================================================
        # Exposure C: LTV=0.80, CQS=1 — high-LTV, residual=20% (CQS=1)
        # secured_share=0.625, avg_rw=0.3875, rwa=387,500
        # Discriminating: naïve 100%-residual fix yields 68.75%, not 38.75%
        # ====================================================================
        _Loan(
            loan_reference=LOAN_REF_C,
            counterparty_reference=COUNTERPARTY_REF_CQS1,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
            book_code="BANKING",
            is_sft=False,
            ltv=LTV_HIGH,  # 0.80 — above 50% LTV threshold
            has_income_cover=True,
            property_type="commercial",
            is_defaulted=False,
            qualifies_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=_LOAN_FIXTURE_SCHEMA)


def create_p1181_ratings() -> pl.DataFrame:
    """
    Return two P1.181 rating rows as a DataFrame.

    RTG-CRE-UNRATED: no external CQS (cqs=None) for CP-CRE-CORP-UNRATED.
        The SA engine finds no external CQS → routes to unrated corporate path
        (Art. 122 Table 6: unrated → 100% RW on any residual portion).

    RTG-CRE-CQS1: CQS=1 for CP-CRE-CORP-CQS1.
        Art. 122 Table 6: CQS=1 → 20% corporate risk weight.
        This CQS is propagated to the exposure row so the SA calculator can
        use it for the residual-leg lookup in the corrected proportion-split.
    """
    rows = [
        # Unrated counterparty — no external CQS
        _Rating(
            rating_reference=RATING_REF_UNRATED,
            counterparty_reference=COUNTERPARTY_REF_UNRATED,
            rating_type="internal",
            rating_agency=None,
            rating_value=None,
            cqs=None,  # null → unrated corporate → Art. 122 100%
            pd=None,
            rating_date=VALUE_DATE,
            is_solicited=False,
            model_id=None,  # no IRB model → SA path
        ),
        # CQS=1 counterparty — external agency rating
        _Rating(
            rating_reference=RATING_REF_CQS1,
            counterparty_reference=COUNTERPARTY_REF_CQS1,
            rating_type="external",
            rating_agency="SP",
            rating_value="AAA",
            cqs=1,  # CQS=1 → Art. 122 Table 6 → 20% corporate RW
            pd=None,
            rating_date=VALUE_DATE,
            is_solicited=True,
            model_id=None,  # no IRB model → SA path
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1181_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.181 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet — 2 rows (CP-CRE-CORP-UNRATED, CP-CRE-CORP-CQS1)
        loan.parquet         — 3 rows (LN-CRE-A, LN-CRE-B, LN-CRE-C)
        rating.parquet       — 2 rows (RTG-CRE-UNRATED, RTG-CRE-CQS1)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1181_counterparties()),
        ("loan", create_p1181_loans()),
        ("rating", create_p1181_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.181 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 126(2)(d) — commercial RE proportion split")
    print()
    print("Bug (pre-fix): residual leg uses cre_rw_standard=1.00 (hardcoded)")
    print("Fix: use counterparty CQS risk weight (Art. 122 corporate lookup)")
    print()
    print(
        f"  LN-CRE-A  LTV={LTV_LOW:.2f}  unrated  RW={EXPECTED_RW_A:.4f}  RWA={EXPECTED_RWA_A:>12,.2f}"
    )
    print(
        f"  LN-CRE-B  LTV={LTV_HIGH:.2f}  unrated  RW={EXPECTED_RW_B:.4f}  RWA={EXPECTED_RWA_B:>12,.2f}"
    )
    print(
        f"  LN-CRE-C  LTV={LTV_HIGH:.2f}  CQS=1    RW={EXPECTED_RW_C:.4f}  RWA={EXPECTED_RWA_C:>12,.2f}"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1181_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
