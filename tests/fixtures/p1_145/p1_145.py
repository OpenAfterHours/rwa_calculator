"""
P1.145 fixtures: deterministic dedup of duplicate model_permissions rows.

Pipeline position:
    fixture-builder output → test-writer → engine-implementer (classifier.py fix)

Key responsibilities:
- Produce two orderings of a 9-row model_permissions table where a single
  model_id ("UK_CORP_DUP_01") has two conflicting approach rows (AIRB + SA).
  Ordering 1 (AIRB-first): 7 baseline rows, then Row A (advanced_irb), then Row B (standardised).
  Ordering 2 (SA-first):   7 baseline rows, then Row B (standardised), then Row A (advanced_irb).
- Produce a single counterparty, loan and rating row for EXP-DUP-001 / CP-DUP-001,
  sufficient for the pipeline to reach the classifier.

Defect under test (pre-fix):
    In classifier.py _resolve_model_permissions(), the boolean aggregation via
    `.max().over("exposure_reference")` uses any-permission-wins union semantics.
    When both an AIRB row and an SA row exist for the same (model_id, exposure_class),
    AIRB is incorrectly granted rather than being blocked by the SA-precedence rule
    (CRR Art. 150(1) PPU carve-out). Additionally, `unique(keep="first")` picks a
    row-level diagnostic that depends on physical row order in the LazyFrame, making
    `_model_permission_diagnostic` non-deterministic.

Post-fix assertion:
    For EXP-DUP-001 with model_id="UK_CORP_DUP_01":
    - model_airb_permitted = False  (SA-precedence override blocks AIRB)
    - model_firb_permitted = False  (no FIRB row)
    - model_slotting_permitted = False
    - _model_permission_diagnostic = "filter_rejected"
    - approach = "standardised"
    Result is identical for both orderings (order-stability invariant).

References:
    - CRR Art. 143 (IRB permission scope)
    - CRR Art. 150(1) (PPU carve-out — SA wins over IRB on conflict)
    - engine/classify/ (_resolve_model_permissions)
    - src/rwa_calc/data/schemas.py:515-522 (MODEL_PERMISSIONS_SCHEMA)
    - src/rwa_calc/domain/enums.py:109-124 (ApproachType)

Usage:
    from tests.fixtures.p1_145.p1_145 import (
        build_model_permissions_airb_first,
        build_model_permissions_sa_first,
        EXPOSURE_REF,
        COUNTERPARTY_REF,
        MODEL_ID,
    )
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
# Scenario constants — referenced by tests for assertions
# ---------------------------------------------------------------------------

EXPOSURE_REF = "EXP-DUP-001"
COUNTERPARTY_REF = "CP-DUP-001"

#: model_id shared by both conflicting permission rows
MODEL_ID = "UK_CORP_DUP_01"

VALUE_DATE = date(2024, 1, 1)
MATURITY_DATE = date(2027, 1, 1)

#: Exposure PD — 1% (standard corporate, well within IRB PD floor)
INTERNAL_PD: float = 0.01

#: Exposure LGD — 30% (A-IRB modelled)
INTERNAL_LGD: float = 0.30

#: Drawn amount — notional only; RWA is not asserted
DRAWN_AMOUNT: float = 1_000_000.0


# ---------------------------------------------------------------------------
# Minimal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ModelPermission:
    """A single model permission row for P1.145."""

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None = None
    excluded_book_codes: str | None = None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


@dataclass(frozen=True)
class _Counterparty:
    """Minimal counterparty for P1.145: UK corporate, not in default."""

    counterparty_reference: str
    entity_type: str
    country_code: str | None
    annual_revenue: float
    total_assets: float
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """Minimal loan for P1.145: single drawn exposure, book_code="GENERAL"."""

    loan_reference: str
    counterparty_reference: str
    book_code: str
    currency: str
    drawn_amount: float
    interest: float
    seniority: str
    value_date: date
    maturity_date: date
    lgd: float
    beel: float

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "book_code": self.book_code,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "lgd": self.lgd,
            "beel": self.beel,
        }


@dataclass(frozen=True)
class _Rating:
    """Internal PD rating linking CP-DUP-001 to model UK_CORP_DUP_01."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    pd: float
    model_id: str
    rating_date: date

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "pd": self.pd,
            "model_id": self.model_id,
            "rating_date": self.rating_date,
        }


# ---------------------------------------------------------------------------
# Baseline 7-row permission set (mirrors the existing model_permissions builder)
# ---------------------------------------------------------------------------


def _baseline_permissions() -> list[_ModelPermission]:
    """
    Return the 7 baseline model permission rows from the shared fixture.

    These rows are taken verbatim from
    tests/fixtures/model_permissions/model_permissions.py so the rest of the
    integration surface remains intact when both orderings are used in tests.
    """
    return [
        # Corporate FIRB (UK-wide)
        _ModelPermission(
            model_id="UK_CORP_PD_01",
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="GB",
        ),
        # Corporate AIRB (UK-wide, TRADE_FINANCE excluded)
        _ModelPermission(
            model_id="UK_CORP_AIRB_01",
            exposure_class="corporate",
            approach="advanced_irb",
            country_codes="GB",
            excluded_book_codes="TRADE_FINANCE",
        ),
        # Institution FIRB (all geographies)
        _ModelPermission(
            model_id="INST_FIRB_01",
            exposure_class="institution",
            approach="foundation_irb",
        ),
        # Retail mortgage AIRB (UK-wide)
        _ModelPermission(
            model_id="UK_RTL_AIRB_01",
            exposure_class="retail_mortgage",
            approach="advanced_irb",
            country_codes="GB",
        ),
        # Retail QRRE AIRB (UK-wide)
        _ModelPermission(
            model_id="UK_RTL_AIRB_02",
            exposure_class="retail_qrre",
            approach="advanced_irb",
            country_codes="GB",
        ),
        # Retail other AIRB (UK-wide)
        _ModelPermission(
            model_id="UK_RTL_AIRB_03",
            exposure_class="retail_other",
            approach="advanced_irb",
            country_codes="GB",
        ),
        # German corporate FIRB (DE only)
        _ModelPermission(
            model_id="DE_CORP_PD_01",
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="DE",
        ),
    ]


def _dup_row_a() -> _ModelPermission:
    """
    Row A — the AIRB permission for UK_CORP_DUP_01.

    Represents an IRB grant that is overridden by the coexisting SA row (Row B)
    under CRR Art. 150(1) PPU semantics.
    """
    return _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="advanced_irb",
        country_codes="GB",
    )


def _dup_row_b() -> _ModelPermission:
    """
    Row B — the SA (PPU) permission for UK_CORP_DUP_01.

    The presence of this row must block all IRB flags for any exposure mapped
    to UK_CORP_DUP_01 in the same exposure class, per CRR Art. 150(1): SA wins.
    """
    return _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="standardised",
        country_codes="GB",
    )


# ---------------------------------------------------------------------------
# Public LazyFrame builders — two physical orderings
# ---------------------------------------------------------------------------


def build_model_permissions_airb_first() -> pl.LazyFrame:
    """
    Return a 9-row model_permissions LazyFrame with AIRB row before SA row.

    Ordering: 7 baseline rows, then Row A (advanced_irb), then Row B (standardised).

    This is Ordering 1 from the P1.145 scenario. The SA-precedence rule must
    produce model_airb_permitted=False regardless of this physical ordering.
    """
    rows = [*_baseline_permissions(), _dup_row_a(), _dup_row_b()]
    return pl.DataFrame(
        [r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA)
    ).lazy()


def build_model_permissions_sa_first() -> pl.LazyFrame:
    """
    Return a 9-row model_permissions LazyFrame with SA row before AIRB row.

    Ordering: 7 baseline rows, then Row B (standardised), then Row A (advanced_irb).

    This is Ordering 2 from the P1.145 scenario. The SA-precedence rule must
    produce model_airb_permitted=False regardless of this physical ordering.
    """
    rows = [*_baseline_permissions(), _dup_row_b(), _dup_row_a()]
    return pl.DataFrame(
        [r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA)
    ).lazy()


# ---------------------------------------------------------------------------
# Public DataFrame factories for upstream bundle rows
# ---------------------------------------------------------------------------


def create_p1145_counterparty() -> pl.DataFrame:
    """
    Return the P1.145 counterparty as a single-row DataFrame.

    CP-DUP-001 is a UK corporate used only to test classifier behaviour on the
    duplicate-permission model; no regulatory arithmetic is asserted.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            entity_type="corporate",
            country_code="GB",
            annual_revenue=500_000_000.0,
            total_assets=1_000_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1145_loan() -> pl.DataFrame:
    """
    Return the P1.145 loan as a single-row DataFrame.

    EXP-DUP-001 is the single drawn exposure that joins to the duplicate-permission
    model via the rating row. book_code="GENERAL" does not match any exclusion list.
    internal_lgd=0.30 is provided to qualify for AIRB if the permission permitted it.
    """
    rows = [
        _Loan(
            loan_reference=EXPOSURE_REF,
            counterparty_reference=COUNTERPARTY_REF,
            book_code="GENERAL",
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            lgd=INTERNAL_LGD,
            beel=0.0,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1145_rating() -> pl.DataFrame:
    """
    Return the P1.145 rating as a single-row DataFrame.

    Links CP-DUP-001 to model_id="UK_CORP_DUP_01" with PD=1%. The model_id
    is the join key that causes the classifier to consult the duplicate permission
    rows and exercise the SA-precedence resolution path.
    """
    rows = [
        _Rating(
            rating_reference="RAT-DUP-001",
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="internal",
            pd=INTERNAL_PD,
            model_id=MODEL_ID,
            rating_date=VALUE_DATE,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1145_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.145 parquet files and return a mapping of name -> path.

    Files written:
        model_permissions_airb_first.parquet  — Ordering 1 (9 rows)
        model_permissions_sa_first.parquet    — Ordering 2 (9 rows)
        counterparty.parquet                  — 1 row (CP-DUP-001)
        loan.parquet                          — 1 row (EXP-DUP-001)
        rating.parquet                        — 1 row (CP-DUP-001 → UK_CORP_DUP_01)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    # Two model_permissions orderings — written as eager DataFrames
    for name, lf in [
        ("model_permissions_airb_first", build_model_permissions_airb_first()),
        ("model_permissions_sa_first", build_model_permissions_sa_first()),
    ]:
        path = output_dir / f"{name}.parquet"
        lf.collect().write_parquet(path)
        saved[name] = path

    # Upstream bundle rows
    for name, df in [
        ("counterparty", create_p1145_counterparty()),
        ("loan", create_p1145_loan()),
        ("rating", create_p1145_rating()),
    ]:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.145 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<42} {len(df):>2} row(s)  ->  {path.name}")
    print("-" * 70)
    print("Scenario: UK_CORP_DUP_01 has both advanced_irb and standardised rows.")
    print("Post-fix: SA-precedence rule sets model_airb_permitted=False for")
    print("          EXP-DUP-001 regardless of which ordering is physically first.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1145_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
