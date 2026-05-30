"""
P1.130 fixtures: Aggregator summaries must reflect post-floor RWA when the output floor
binds (PRA PS1/26 Art. 92(2A)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer

Scenario design:

    Three corporate counterparties (ALL UNRATED — no external CQS / rating):
        CP_IRB_1: corporate, used by EXP_IRB_1 (F-IRB, PD=0.10%)
        CP_IRB_2: corporate, used by EXP_IRB_2 (F-IRB, PD=0.15%)
        CP_SA_1:  corporate, used by EXP_SA_1  (SA, unrated → 100%)

    Exposures:
        EXP_IRB_1: EAD=100,000,000, F-IRB senior unsecured, LGD=0.40, M=2.5y, PD=0.10%
        EXP_IRB_2: EAD=100,000,000, F-IRB senior unsecured, LGD=0.40, M=2.5y, PD=0.15%
        EXP_SA_1:  EAD=50,000,000,  SA (standardised), unrated corporate → 100% RW

    Config under test: CalculationConfig.basel_3_1(), reporting_date=date(2030,1,1)
        -> floor factor 0.725; OF-ADJ = 0.

Why the floor BINDS (hand-calc):

        F-IRB K (Basel 3.1, unscaled, no SME factor):
            Both exposures are low-PD (0.10% / 0.15%) senior corporate.
            Approximate IRB K using Basel formula:
                PD=0.001: N(…) ≈ 0.42 → K ≈ 0.40 × (0.42 − 0.001 × 0.42) × 12.5 ≈ 2.1%
                          RWA_1 ≈ 100m × 2.1% ≈ 2,100,000
                PD=0.0015: K ≈ ~2.5% → RWA_2 ≈ 2,500,000
                U-TREA (modelled) ≈ 4,600,000 (well below threshold)

        S-TREA (SA-equivalent of IRB rows):
            Both IRB corporates are UNRATED → SA RW = 100%.
            EAD_1 = EAD_2 = 100m → SA-equiv = 100m + 100m = 200,000,000

        Floor threshold = 0.725 × 200,000,000 + 0 = 145,000,000
            145,000,000 >> 4,600,000  =>  FLOOR BINDS

        Floored modelled RWA = floor_threshold = 145,000,000
        SA control (EXP_SA_1, unrated → 100%): RWA = 50,000,000 (not in U-TREA / S-TREA)

        total_rwa_post_floor = 145,000,000 + 50,000,000 = 195,000,000
        total_rwa_pre_floor  =   4,600,000 + 50,000,000 =  54,600,000  (approx)

    Critical constraint: ALL corporates are UNRATED (no external_cqs, no cqs column in
    ratings rows). SA-equivalent RW = 100% (not 75%, which would be CQS 3 under B31).
    This makes S-TREA = 200m and sets the 145m threshold.

Model permissions wiring:
    EXP_IRB_1 and EXP_IRB_2 carry an internal rating (model_id=CORP_FIRB_P1130) on
    their respective counterparties. One model_permission row grants foundation_irb for
    exposure_class=corporate. EXP_SA_1's counterparty has no internal rating → SA.

References:
    - PRA PS1/26 Art. 92(2A): TREA = max(U-TREA, x * S-TREA + OF-ADJ)
    - PRA PS1/26 Art. 92(5): floor factor 72.5% for reporting dates >= 2030
    - PRA PS1/26 Art. 161(1)(aa): F-IRB senior unsecured LGD = 40%
    - PRA PS1/26 Art. 122(2) Table 6: unrated corporate SA RW = 100%

Usage:
    uv run python tests/fixtures/p1_130/p1_130.py
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
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
CP_IRB_1: str = "CP-P1130-IRB-1"
CP_IRB_2: str = "CP-P1130-IRB-2"
CP_SA_1: str = "CP-P1130-SA-1"

# Loan / exposure references
LOAN_IRB_1: str = "LN-P1130-IRB-1"
LOAN_IRB_2: str = "LN-P1130-IRB-2"
LOAN_SA_1: str = "LN-P1130-SA-1"

# Rating references
RATING_IRB_1: str = "RTG-P1130-IRB-1"
RATING_IRB_2: str = "RTG-P1130-IRB-2"

# Model ID (unique to this scenario to avoid cross-test interference)
MODEL_ID: str = "CORP-FIRB-P1130"

# Dates
VALUE_DATE: date = date(2029, 1, 1)
MATURITY_DATE: date = date(2031, 7, 1)  # approx 2.5y from value date
RATING_DATE: date = date(2029, 1, 2)

# EADs
EAD_IRB_1: float = 100_000_000.0
EAD_IRB_2: float = 100_000_000.0
EAD_SA_1: float = 50_000_000.0

# IRB parameters
PD_IRB_1: float = 0.0010  # 0.10%
PD_IRB_2: float = 0.0015  # 0.15%
LGD_FIRB: float = 0.40  # Basel 3.1 F-IRB senior unsecured corporate (Art. 161(1)(aa))
EFFECTIVE_MATURITY: float = 2.5  # years

# Floor factor (2030+ fully phased; test config uses reporting_date=2030-01-01)
FLOOR_FACTOR: float = 0.725

# Hand-calc expected values (binding-floor precondition check)
# S-TREA: unrated corporate → 100% SA RW; 100m + 100m = 200m
EXPECTED_S_TREA: float = 200_000_000.0
EXPECTED_FLOOR_THRESHOLD: float = FLOOR_FACTOR * EXPECTED_S_TREA  # 145,000,000
# SA control EXP_SA_1: unrated corporate 100% → RWA = 50m
EXPECTED_SA_RWA: float = 50_000_000.0
# Post-floor total (floor binds; floored_modelled_rwa + SA control):
EXPECTED_TOTAL_RWA_POST_FLOOR: float = EXPECTED_FLOOR_THRESHOLD + EXPECTED_SA_RWA  # 195,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
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
    is_defaulted: bool

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
            "is_defaulted": self.is_defaulted,
        }


@dataclass(frozen=True)
class _Rating:
    """Internal rating row linking a counterparty to a model for IRB routing."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
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
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """Model permission granting F-IRB for the corporate exposure class."""

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


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1130_counterparties() -> pl.DataFrame:
    """
    Return 3 P1.130 counterparties as a DataFrame.

    All three are unrated corporate entities.  No cqs / external rating is set
    on any counterparty or rating row — this is load-bearing: unrated corporates
    receive a 100% SA risk weight (PRA PS1/26 Art. 122(2) Table 6 unrated column),
    producing S-TREA = 200m and a binding floor threshold of 145m.

    CP_IRB_1 and CP_IRB_2: paired with internal ratings (model CORP-FIRB-P1130),
        enabling F-IRB routing.  annual_revenue=200m avoids the Basel 3.1
        large-corporate threshold (>GBP 440m) that would block F-IRB.
    CP_SA_1: no internal rating → routes purely through SA.
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_IRB_1,
            counterparty_name="P1.130 IRB Corporate 1 Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=400_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=CP_IRB_2,
            counterparty_name="P1.130 IRB Corporate 2 Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=400_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=CP_SA_1,
            counterparty_name="P1.130 SA Corporate 1 Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=400_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1130_loans() -> pl.DataFrame:
    """
    Return 3 P1.130 loan rows as a DataFrame.

    LOAN_IRB_1 (EXP_IRB_1):
        CP_IRB_1, EAD=100,000,000, F-IRB, LGD=0.40, M=2.5y, PD=0.10% (via rating)
    LOAN_IRB_2 (EXP_IRB_2):
        CP_IRB_2, EAD=100,000,000, F-IRB, LGD=0.40, M=2.5y, PD=0.15% (via rating)
    LOAN_SA_1 (EXP_SA_1):
        CP_SA_1, EAD=50,000,000, SA (no internal rating → standardised)
        lgd=None (not consumed by SA path).

    LGD=0.40 on the IRB rows realises the Basel 3.1 F-IRB senior unsecured
    corporate supervisory LGD (PRA PS1/26 Art. 161(1)(aa), reduced from CRR's 45%).
    """
    rows = [
        _Loan(
            loan_reference=LOAN_IRB_1,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_IRB_1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_IRB_1,
            interest=0.0,
            lgd=LGD_FIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
        _Loan(
            loan_reference=LOAN_IRB_2,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_IRB_2,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_IRB_2,
            interest=0.0,
            lgd=LGD_FIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
        _Loan(
            loan_reference=LOAN_SA_1,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_SA_1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_SA_1,
            interest=0.0,
            lgd=0.45,  # default fallback; SA path does not consume LGD
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1130_ratings() -> pl.DataFrame:
    """
    Return 2 internal rating rows as a DataFrame (IRB counterparties only).

    Both ratings are internal, reference model CORP-FIRB-P1130, and carry
    a PD but NO cqs column value — this is critical: cqs=null means the
    counterparty is unrated externally.  The internal PD drives F-IRB K.

    CP_SA_1 intentionally has NO rating row, so the pipeline cannot route
    it through IRB and uses SA (unrated corporate → 100% RW).
    """
    rows = [
        _Rating(
            rating_reference=RATING_IRB_1,
            counterparty_reference=CP_IRB_1,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BBB",
            pd=PD_IRB_1,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RATING_IRB_2,
            counterparty_reference=CP_IRB_2,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BBB",
            pd=PD_IRB_2,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1130_model_permission() -> pl.DataFrame:
    """
    Return the P1.130 model permission as a single-row DataFrame.

    Grants foundation_irb (F-IRB) for exposure_class=corporate.
    Dedicated MODEL_ID=CORP-FIRB-P1130 avoids cross-test interference with
    the shared test model (TEST_FULL_IRB) used in B31-F group tests.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1130_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.130 parquet files and return a mapping of name to path.

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
        ("counterparty", create_p1130_counterparties()),
        ("loan", create_p1130_loans()),
        ("rating", create_p1130_ratings()),
        ("model_permission", create_p1130_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.130 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>2} row(s)  ->  {path.name}")
    print("-" * 70)
    print("Scenario: Output floor binding — unrated F-IRB + SA corporates")
    print(f"  S-TREA (unrated → 100%): {EXPECTED_S_TREA:,.0f}")
    print(f"  Floor threshold (×{FLOOR_FACTOR}): {EXPECTED_FLOOR_THRESHOLD:,.0f}")
    print(f"  SA control EXP_SA_1 RWA: {EXPECTED_SA_RWA:,.0f}")
    print(f"  total_rwa_post_floor:    {EXPECTED_TOTAL_RWA_POST_FLOOR:,.0f}")
    print("  Floor BINDS: U-TREA << 145m (low PD + 40% LGD on 200m EAD)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1130_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
