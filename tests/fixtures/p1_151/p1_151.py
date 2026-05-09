"""
Generate P1.151 fixtures: B31 F-IRB purchased receivables LGD routing.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (irb/namespace.py)

Key responsibilities:
- Produce one counterparty row: corporate, GB, pd=0.01, annual_revenue=null
  (no annual_revenue forces the engine to treat as large corporate / no SME reduction).
- Produce three loan rows, all referencing CP_PR_CORP_001, all senior on-balance,
  no collateral, no CRM, F-IRB path:
    LOAN_PR_SENIOR_001   — purchased_receivables_subtype="senior"
                           LGD = 40%  (Art. 161(1)(e))  EAD = 1,000,000
    LOAN_PR_SUB_001      — purchased_receivables_subtype="subordinated"
                           LGD = 100% (Art. 161(1)(f))  EAD = 500,000
    LOAN_PR_DILUTION_001 — purchased_receivables_subtype="dilution_risk"
                           LGD = 100% (Art. 161(1)(g))  EAD = 200,000
- Produce one rating row: internal PD = 0.01, model_id="UK_CORP_FIRB_PR_01".
- Produce one model-permissions row: corporate foundation_irb.
- Produce empty facility_mapping and lending_mapping (no mappings needed).

Scenario rationale:
    Basel 3.1 Art. 161(1) differentiates three purchased-receivables sub-types that
    each attract a distinct supervisory LGD under F-IRB:

    (e) Senior purchased corporate receivables where PD is determined per Art. 160(2)(a):
        LGD = 40%.  This aligns with the reduced non-FSE senior unsecured rate introduced
        by Art. 161(1)(aa), but applies specifically when the pool-level PD is estimated
        top-down from a provider's EL estimate for default risk.

    (f) Subordinated purchased corporate receivables:
        LGD = 100%.  Unchanged from CRR — reflects the structural subordination within
        a receivables pool (e.g., first-loss tranche held by a purchasing bank).

    (g) Dilution risk of purchased corporate receivables:
        LGD = 100% under Basel 3.1 (up from CRR 75%).  The PRA raised the dilution LGD
        to reflect the position that dilution losses (reduction of receivables through
        set-offs, contra-charges, rebates, disputes) receive no recovery benefit.

    Without the purchased_receivables_subtype routing, all three rows would fall through
    to the generic senior corporate path (LGD = 40% under B31, formerly 45% under CRR),
    producing correct capital for the senior row but an ~60 pp LGD understatement for
    subordinated, and a 60 pp LGD understatement for dilution risk.

Hand-calculation (B31 F-IRB, CalculationConfig.basel_3_1(), reporting_date=2027-12-31):

    Common parameters:
        PD floor  = max(0.01, 0.0005) = 0.01   (B31 Art. 163(1) corporate floor = 0.05%)
        Residual maturity = (2028-12-31 - 2027-12-31) = 365 days = 1.0y
        M         = max(1.0, min(5.0, 1.0)) = 1.0y  (standard 1-year floor, exact)
        b(PD)     = (0.11852 - 0.05478 x ln(0.01))^2 = (0.11852 + 0.05478 x 4.60517)^2
                  = (0.11852 + 0.25237)^2 = (0.37089)^2 = 0.13756
        MA        = (1 + (1.0 - 2.5) x 0.13756) / (1 - 1.5 x 0.13756)
                  = (1 - 0.34390) / (1 - 0.20634)
                  = 0.65610 / 0.79366 = 0.82672
        R(PD)     = 0.12 x f(PD) + 0.24 x (1 - f(PD))
                  where f(PD) = (1 - exp(-50 x 0.01)) / (1 - exp(-50))
                              = (1 - exp(-0.5)) / 1 = 1 - 0.60653 = 0.39347
                  R     = 0.12 x 0.39347 + 0.24 x 0.60653
                        = 0.04722 + 0.14557 = 0.19279
        N(.)      = standard normal CDF, G(.) = its inverse

    Row A — LOAN_PR_SENIOR_001 (purchased_receivables_subtype="senior"):
        LGD   = 0.40  (Art. 161(1)(e))
        EAD   = 1,000,000
        K_A   = (LGD x N[(G(0.01) + sqrt(R/(1-R)) x G(0.999)) / sqrt(1-R)] - PD x LGD) x MA
        N[(G(0.01) + sqrt(0.19279/0.80721) x G(0.999)) / sqrt(0.80721)]
             = N[(-2.3263 + 0.48848 x 3.0902) / 0.89845]
             = N[(-2.3263 + 1.5097) / 0.89845]
             = N[-0.91007]  ≈ 0.18138
        K_A   = (0.40 x 0.18138 - 0.01 x 0.40) x 0.82672
              = (0.07255 - 0.004) x 0.82672
              = 0.06855 x 0.82672 = 0.056677
        RWA_A = K_A x 12.5 x EAD = 0.056677 x 12.5 x 1,000,000 = 708,466  (approx)

    Row B — LOAN_PR_SUB_001 (purchased_receivables_subtype="subordinated"):
        LGD   = 1.00  (Art. 161(1)(f))
        EAD   = 500,000
        K_B   = (1.00 x 0.18138 - 0.01 x 1.00) x 0.82672
              = (0.18138 - 0.01) x 0.82672
              = 0.17138 x 0.82672 = 0.141694
        RWA_B = 0.141694 x 12.5 x 500,000 = 885,583  (approx)

    Row C — LOAN_PR_DILUTION_001 (purchased_receivables_subtype="dilution_risk"):
        LGD   = 1.00  (Art. 161(1)(g))
        EAD   = 200,000
        K_C   = K_B (same PD, same LGD) = 0.141694
        RWA_C = 0.141694 x 12.5 x 200,000 = 354,233  (approx)

    Baseline (wrong — no subtype routing, all three default to senior corporate LGD = 40%):
        LGD_baseline = 0.40 (non-FSE senior, Art. 161(1)(aa))
        K_base = K_A = 0.056677
        RWA_B_wrong = 0.056677 x 12.5 x 500,000 = 354,233 (vs correct 885,583 — ~60% low)
        RWA_C_wrong = 0.056677 x 12.5 x 200,000 = 141,693 (vs correct 354,233 — ~60% low)

    Key assertions:
        LGD_A  = 0.40  (senior — matches non-FSE senior corporate baseline)
        LGD_B  = 1.00  (subordinated — 2.5x the baseline)
        LGD_C  = 1.00  (dilution risk — 2.5x the baseline under B31)
        RWA_B / RWA_A ≈ (1.00/0.40) x (500,000/1,000,000) = 1.25  (approx — same K shape)

References:
    - PRA PS1/26 Art. 161(1)(e): F-IRB senior purchased receivables LGD = 40%
    - PRA PS1/26 Art. 161(1)(f): F-IRB subordinated purchased receivables LGD = 100%
    - PRA PS1/26 Art. 161(1)(g): F-IRB dilution risk LGD = 100% (up from CRR 75%)
    - PRA PS1/26 Art. 160(2)(a): top-down PD estimation for purchased receivable pools
    - BCBS CRE32.3–CRE32.5: purchased receivable F-IRB treatment overview
    - docs/specifications/basel31/firb-calculation.md § "Supervisory LGD (Art. 161)"
    - src/rwa_calc/data/schemas.py: LOAN_SCHEMA (purchased_receivables_subtype — Wave 4)

Note on schema field:
    ``purchased_receivables_subtype`` (pl.String, nullable, values: null / "senior" /
    "subordinated" / "dilution_risk") is a new column added to FACILITY_SCHEMA and
    LOAN_SCHEMA by the engine-implementer (Wave 4). Until the field is registered,
    dtypes_of(LOAN_SCHEMA) will not include it. We therefore write the loan parquet
    using the base schema and then append the column via ``with_columns``. Once the
    engine adds the field, the ``with_columns`` call becomes a no-op update on an
    already-typed column.

Usage:
    uv run python tests/fixtures/p1_151/p1_151.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_PR_CORP_001"
LOAN_REF_SENIOR = "LOAN_PR_SENIOR_001"
LOAN_REF_SUB = "LOAN_PR_SUB_001"
LOAN_REF_DILUTION = "LOAN_PR_DILUTION_001"
RATING_REF = "RTG_PR_CORP_001"
MODEL_ID = "UK_CORP_FIRB_PR_01"

# Reporting and maturity dates
REPORTING_DATE = date(2027, 12, 31)
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2028, 12, 30)
RATING_DATE = date(2027, 1, 1)

# Common financial parameters
PD: float = 0.01  # 1.00% — well above B31 corporate PD floor (0.05%)
# annual_revenue=None: forces engine to treat as non-SME (no SME correlation reduction)

# Drawn amounts per row
DRAWN_SENIOR: float = 1_000_000.0
DRAWN_SUB: float = 500_000.0
DRAWN_DILUTION: float = 200_000.0

# ---------------------------------------------------------------------------
# Supervisory LGD values (Art. 161(1)(e)/(f)/(g) under Basel 3.1)
# ---------------------------------------------------------------------------

# Art. 161(1)(e): senior purchased corporate receivables — aligns with non-FSE senior.
LGD_SENIOR: float = 0.40  # 40%

# Art. 161(1)(f): subordinated purchased corporate receivables.
LGD_SUB: float = 1.00  # 100%

# Art. 161(1)(g): dilution risk of purchased corporate receivables.
# Increased from CRR 75% to Basel 3.1 100%.
LGD_DILUTION: float = 1.00  # 100%

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer reference)
# ---------------------------------------------------------------------------

# F-IRB parameters (Basel 3.1, no 1.06 scaling factor)
# PD = 0.01, M = 1.0y (365/365), R ≈ 0.19279
# b(PD) ≈ 0.13756, MA ≈ 0.82672
# N[(G(PD) + sqrt(R/(1-R)) x G(0.999)) / sqrt(1-R)] ≈ 0.18138

# Row A — senior (LGD=0.40, EAD=1,000,000)
EXPECTED_RWA_SENIOR: float = 708_466.0  # approx; test should allow ±500

# Row B — subordinated (LGD=1.00, EAD=500,000)
EXPECTED_RWA_SUB: float = 885_583.0  # approx; test should allow ±500

# Row C — dilution risk (LGD=1.00, EAD=200,000)
EXPECTED_RWA_DILUTION: float = 354_233.0  # approx; test should allow ±500

# Baseline (wrong — all rows default to LGD=0.40 without subtype routing)
BASELINE_RWA_SUB_WRONG: float = 354_233.0  # same as correct RWA_C — 60% too low for row B
BASELINE_RWA_DILUTION_WRONG: float = 141_693.0  # 60% too low for row C


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.151 corporate counterparty with F-IRB internal rating.

    entity_type=corporate routes to IRB CORPORATE class under CalculationConfig.basel_3_1().
    annual_revenue=None: no SME firm-size reduction in the asset correlation formula
    (treated conservatively as large corporate).
    is_financial_sector_entity=False: no FI scalar.
    country_code=GB: domestic GBP counterparty.
    default_status=False: performing exposure.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.151 internal F-IRB rating row.

    rating_type=internal with pd=0.01 and model_id="UK_CORP_FIRB_PR_01" routes the
    counterparty to F-IRB under CalculationConfig.basel_3_1().
    cqs=None: no external ECAI rating — pure F-IRB path.
    """

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


@dataclass(frozen=True)
class _ModelPermission:
    """
    P1.151 model permission: corporate F-IRB, no geographic/book restriction.

    exposure_class=corporate: covers CP_PR_CORP_001.
    approach=foundation_irb: F-IRB path under CalculationConfig.basel_3_1().
    country_codes=None: unrestricted.
    excluded_book_codes=None: no exclusions.
    """

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
class _Loan:
    """
    P1.151 loan row for purchased receivables scenario.

    drawn_amount: face amount of the receivables tranche.
    seniority: "senior" for LOAN_PR_SENIOR_001 / LOAN_PR_DILUTION_001,
               "subordinated" for LOAN_PR_SUB_001.
    lgd, lgd_unsecured: left null — forces F-IRB supervisory LGD selection.
    has_sufficient_collateral_data=False: no collateral data supplied.
    interest=0.0: no accrued interest.
    is_sft=False: not a securities financing transaction.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    is_sft: bool
    book_code: str

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
            "is_sft": self.is_sft,
            "book_code": self.book_code,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1151_counterparty() -> pl.DataFrame:
    """
    Return one P1.151 counterparty row as a DataFrame.

    entity_type=corporate, country_code=GB, not defaulted, no FI scalar.
    annual_revenue is omitted from the dict (null in parquet) so the engine
    cannot apply an SME correlation reduction.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Purchased Receivables Corp (GB) — P1.151",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_financial_sector_entity=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1151_rating() -> pl.DataFrame:
    """
    Return one P1.151 internal rating row as a DataFrame.

    PD=0.01, model_id="UK_CORP_FIRB_PR_01" routes to F-IRB under
    CalculationConfig.basel_3_1() given a matching model_permissions row.
    """
    row = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=COUNTERPARTY_REF,
        rating_type="internal",
        pd=PD,
        model_id=MODEL_ID,
        rating_date=RATING_DATE,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1151_model_permissions() -> pl.DataFrame:
    """
    Return one P1.151 model permission row as a DataFrame.

    model_id=UK_CORP_FIRB_PR_01, exposure_class=corporate, approach=foundation_irb.
    No geographic or book-code restrictions.
    """
    row = _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="foundation_irb",
        country_codes=None,
        excluded_book_codes=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def create_p1151_loans() -> pl.DataFrame:
    """
    Return three P1.151 loan rows as a DataFrame.

    Each row sets ``purchased_receivables_subtype`` to the value that drives the
    Art. 161(1)(e)/(f)/(g) LGD routing. The column is appended after the base
    schema construction because the engine-implementer adds it in Wave 4.
    Once LOAN_SCHEMA declares the field, the ``with_columns`` is a no-op update.

    LOAN_PR_SENIOR_001:
        purchased_receivables_subtype="senior", seniority="senior"
        drawn_amount=1,000,000 → EAD=1,000,000
        Expected LGD = 40% (Art. 161(1)(e))

    LOAN_PR_SUB_001:
        purchased_receivables_subtype="subordinated", seniority="subordinated"
        drawn_amount=500,000 → EAD=500,000
        Expected LGD = 100% (Art. 161(1)(f))

    LOAN_PR_DILUTION_001:
        purchased_receivables_subtype="dilution_risk", seniority="senior"
        drawn_amount=200,000 → EAD=200,000
        Expected LGD = 100% (Art. 161(1)(g))
    """
    _common = dict(
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        interest=0.0,
        is_sft=False,
        book_code="BANKING",
    )

    rows = [
        # ----------------------------------------------------------------
        # Row A — senior purchased receivables (Art. 161(1)(e))
        # purchased_receivables_subtype="senior" → LGD = 40%
        # ----------------------------------------------------------------
        _Loan(
            loan_reference=LOAN_REF_SENIOR,
            drawn_amount=DRAWN_SENIOR,
            seniority="senior",
            **_common,
        ),
        # ----------------------------------------------------------------
        # Row B — subordinated purchased receivables (Art. 161(1)(f))
        # purchased_receivables_subtype="subordinated" → LGD = 100%
        # seniority="subordinated" reinforces the structural ranking; the
        # engine must use purchased_receivables_subtype (not seniority alone)
        # because standard subordinated LGD = 75%, but purchased receivables
        # subordinated = 100% (different rule).
        # ----------------------------------------------------------------
        _Loan(
            loan_reference=LOAN_REF_SUB,
            drawn_amount=DRAWN_SUB,
            seniority="subordinated",
            **_common,
        ),
        # ----------------------------------------------------------------
        # Row C — dilution risk (Art. 161(1)(g))
        # purchased_receivables_subtype="dilution_risk" → LGD = 100%
        # seniority="senior" (dilution risk is not a subordinated claim;
        # it represents a different risk type — reduction of receivables
        # through set-offs/rebates/disputes).
        # ----------------------------------------------------------------
        _Loan(
            loan_reference=LOAN_REF_DILUTION,
            drawn_amount=DRAWN_DILUTION,
            seniority="senior",
            **_common,
        ),
    ]

    base_schema = dtypes_of(LOAN_SCHEMA)
    df = pl.DataFrame([r.to_dict() for r in rows], schema=base_schema)

    # Append purchased_receivables_subtype regardless of whether it is in
    # LOAN_SCHEMA yet. After engine-implementer adds the field, this
    # with_columns is a no-op update on an already-typed column.
    subtype_values = ["senior", "subordinated", "dilution_risk"]
    return df.with_columns(
        pl.Series("purchased_receivables_subtype", subtype_values, dtype=pl.String)
    )


def create_p1151_facility_mapping() -> pl.DataFrame:
    """
    Return an empty facility-mapping DataFrame conforming to FACILITY_MAPPING_SCHEMA.

    This is a pure loan fixture — no facilities, no mappings needed.
    """
    return pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1151_lending_mapping() -> pl.DataFrame:
    """
    Return an empty lending-mapping DataFrame conforming to LENDING_MAPPING_SCHEMA.

    No multi-debtor / parent-child lending structure in this fixture.
    """
    return pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1151_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.151 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1151_counterparty()),
        ("rating", create_p1151_rating()),
        ("model_permission", create_p1151_model_permissions()),
        ("loan", create_p1151_loans()),
        ("facility_mapping", create_p1151_facility_mapping()),
        ("lending_mapping", create_p1151_lending_mapping()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.151 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: B31 F-IRB purchased receivables LGD routing (Art. 161(1)(e)/(f)/(g))")
    print(f"  Counterparty: {COUNTERPARTY_REF} — corporate, GB, PD={PD:.2%}")
    print(f"  Reporting date: {REPORTING_DATE},  Maturity: {MATURITY_DATE}")
    print(f"  Model: {MODEL_ID} — foundation_irb, corporate")
    print("")
    print(
        f"  {'Loan ref':<28}  {'Subtype':<15}  {'Seniority':<12}  "
        f"{'Drawn':>12}  {'LGD':>5}  {'RWA (approx)':>14}"
    )
    rows_data = [
        (LOAN_REF_SENIOR, "senior", "senior", DRAWN_SENIOR, LGD_SENIOR, EXPECTED_RWA_SENIOR),
        (LOAN_REF_SUB, "subordinated", "subordinated", DRAWN_SUB, LGD_SUB, EXPECTED_RWA_SUB),
        (LOAN_REF_DILUTION, "dilution_risk", "senior", DRAWN_DILUTION, LGD_DILUTION, EXPECTED_RWA_DILUTION),
    ]
    for ref, subtype, seniority, drawn, lgd, rwa in rows_data:
        print(
            f"  {ref:<28}  {subtype:<15}  {seniority:<12}  "
            f"{drawn:>12,.0f}  {lgd:>5.0%}  {rwa:>14,.0f}"
        )
    print("")
    print("  Key assertions:")
    print(f"    LGD_senior     = {LGD_SENIOR:.0%}  (Art. 161(1)(e)) — aligns with non-FSE senior B31")
    print(f"    LGD_sub        = {LGD_SUB:.0%} (Art. 161(1)(f)) — unchanged from CRR")
    print(f"    LGD_dilution   = {LGD_DILUTION:.0%} (Art. 161(1)(g)) — increased from CRR 75%")
    print(f"    Without routing: LGD_sub/dilution wrong at 40% → RWA_B understated by ~60%")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1151_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
