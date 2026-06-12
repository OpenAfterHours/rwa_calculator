"""
Generate P1.94d fixtures: Art. 123B(2A) revolving-instalment rule for the Basel 3.1
currency-mismatch multiplier.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py
    apply_currency_mismatch_multiplier)

Key responsibilities:
- Produce one counterparty (CP_P194D): natural person, GB,
  borrower_income_currency=EUR.
- Produce three loan rows exercising the revolving-instalment fork:
    Arm A (P194D_REVOLVING):    is_revolving=True,  drawn=100k, limit=400k,
                                 hedge_coverage_ratio=0.95 (95% of drawn).
    Arm B (P194D_NON_REVOLVING): is_revolving=False, drawn=100k, limit=400k,
                                 hedge_coverage_ratio=0.95 (control — no rescale).
    Arm C (P194D_FULLY_DRAWN):  is_revolving=True,  drawn=100k, limit=100k,
                                 hedge_coverage_ratio=0.95 (fully drawn — waiver holds).
- Two extra columns are appended after the declared LOAN_SCHEMA to carry
  ``is_revolving`` and ``facility_limit`` / ``undrawn_amount`` onto the loan
  row. The engine-implementer will add pass-through for these in
  hierarchy._coerce_loans_to_unified once the revolving branch is wired.
  ``hedge_coverage_ratio`` and ``is_hedged`` are already in LOAN_SCHEMA from
  the P1.94b / P1.94a waves.

Scenario design:

    Art. 123B(2A) changes the DENOMINATOR of the 90%-hedge-coverage waiver for
    revolving facilities: instead of ``hedge_coverage_ratio`` measured against
    the current drawn balance, coverage is measured against the fully-drawn
    committed amount (facility_limit = drawn_amount + undrawn_amount).

    The firm supplies ``hedge_coverage_ratio`` = 0.95 in all three arms, meaning
    the hedge covers 95% of the current drawn balance.

    Arm A (revolving, partially drawn):
        full_draw_base     = max(drawn_amount, facility_limit) = max(100k, 400k) = 400k
        covered_amount     = 0.95 * 100k = 95k
        effective_coverage = 95k / 400k = 0.2375
        waiver             = False OR (0.2375 >= 0.90) = False
        mismatch_applies   = True  (retail_qrre, GBP vs EUR income, not waived)
        RW_adjusted        = min(0.75 * 1.5, 1.50) = 1.125
        RWA                = 100k * 1.125 = 112,500

    Arm B (non-revolving, same amounts):
        effective_coverage = 0.95 (no rescale for non-revolving)
        waiver             = False OR (0.95 >= 0.90) = True
        mismatch_applies   = False
        RW                 = 0.75
        RWA                = 100k * 0.75 = 75,000

    Arm C (revolving, fully drawn — negative control):
        full_draw_base     = max(100k, 100k) = 100k
        covered_amount     = 0.95 * 100k = 95k
        effective_coverage = 95k / 100k = 0.95 >= 0.90
        waiver             = True
        mismatch_applies   = False
        RW                 = 0.75
        RWA                = 100k * 0.75 = 75,000

    Arm A vs. parent rule (Art. 123B(2) without revolving clause):
        Parent: waiver = (0.95 >= 0.90) = True => RW=0.75, RWA=75,000
        Art. 123B(2A): waiver = False    => RW=1.125, RWA=112,500
        Delta: 37,500 additional RWA from the revolving-instalment branch.

Regulatory references:
    - PRA PS1/26 App1 Art. 123B: 1.5x currency-mismatch multiplier for retail/RE.
    - PRA PS1/26 App1 Art. 123B(2): hedge >= 90% of notional suppresses multiplier.
    - PRA PS1/26 App1 Art. 123B(2A): for revolving facilities, the 90%-coverage
      test denominator is the fully-drawn committed amount
      (max(drawn_amount, facility_limit)), not the current drawing.
    - BCBS CRE20.88: revolving-instalment base equivalent.
    - src/rwa_calc/data/schemas.py: FACILITY_SCHEMA (is_revolving:137),
      LOAN_SCHEMA (is_hedged:228, hedge_coverage_ratio:233).
    - engine/hierarchy.py:96-98,1227-1232,3151-3161: QRRE field propagation.
    - engine/sa/namespace.py: apply_currency_mismatch_multiplier:1959-2036 (site
      to extend with the revolving-instalment branch).
    - tests/fixtures/p1_94b/p1_94b.py: sibling — hedge_coverage_ratio gate.

Usage:
    python tests/fixtures/p1_94d/p1_94d.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_P194D"

#: Arm A — revolving, partially drawn: mismatch multiplier fires (revolving branch)
LOAN_REF_REVOLVING: str = "P194D_REVOLVING"

#: Arm B — non-revolving control: mismatch waived (parent Art. 123B(2) holds)
LOAN_REF_NON_REVOLVING: str = "P194D_NON_REVOLVING"

#: Arm C — revolving, fully drawn negative control: waiver holds even under Art. 123B(2A)
LOAN_REF_FULLY_DRAWN: str = "P194D_FULLY_DRAWN"

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2032, 1, 4)

#: Drawn balance for all arms (EAD = drawn, no interest, no CRM)
DRAWN_AMOUNT: float = 100_000.0

#: Undrawn commitment for Arms A and B (facility_limit = 400k, drawn = 100k)
UNDRAWN_AMOUNT_PARTIAL: float = 300_000.0

#: Undrawn commitment for Arm C (fully drawn: limit = 100k, drawn = 100k)
UNDRAWN_AMOUNT_FULLY_DRAWN: float = 0.0

#: Facility limit (= drawn + undrawn) for Arms A and B
FACILITY_LIMIT_PARTIAL: float = 400_000.0

#: Facility limit for Arm C (fully drawn)
FACILITY_LIMIT_FULLY_DRAWN: float = 100_000.0

#: Firm-supplied hedge coverage ratio (coverage of CURRENT drawn balance, all arms)
HEDGE_COVERAGE_RATIO: float = 0.95

#: Art. 123B(2) threshold — unchanged
HEDGE_COVERAGE_THRESHOLD: float = 0.90

# ---------------------------------------------------------------------------
# Regulatory scalars
# ---------------------------------------------------------------------------

#: Base SA risk weight for retail QRRE (PRA PS1/26 Art. 123(1))
SA_RETAIL_QRRE_BASE_RW: float = 0.75

#: Art. 123B currency-mismatch multiplier (PRA PS1/26 Art. 123B)
CURRENCY_MISMATCH_MULTIPLIER: float = 1.50

# ---------------------------------------------------------------------------
# Hand-calculation results for Arm A (revolving, mismatch fires)
# ---------------------------------------------------------------------------

#: full_draw_base = max(100k, 400k) = 400k
FULL_DRAW_BASE_A: float = max(DRAWN_AMOUNT, FACILITY_LIMIT_PARTIAL)

#: covered_amount = hedge_coverage_ratio * drawn_amount = 0.95 * 100k = 95k
COVERED_AMOUNT_A: float = HEDGE_COVERAGE_RATIO * DRAWN_AMOUNT

#: effective_coverage = 95k / 400k = 0.2375 (below 0.90 threshold)
EFFECTIVE_COVERAGE_A: float = COVERED_AMOUNT_A / FULL_DRAW_BASE_A

#: Arm A: revolving + below-threshold effective coverage => multiplier fires
RW_REVOLVING: float = SA_RETAIL_QRRE_BASE_RW * CURRENCY_MISMATCH_MULTIPLIER  # 1.125
RWA_REVOLVING: float = DRAWN_AMOUNT * RW_REVOLVING  # 112,500.00

# ---------------------------------------------------------------------------
# Hand-calculation results for Arm B (non-revolving, waiver holds)
# ---------------------------------------------------------------------------

#: Non-revolving: effective_coverage = hedge_coverage_ratio directly = 0.95 >= 0.90
EFFECTIVE_COVERAGE_B: float = HEDGE_COVERAGE_RATIO  # 0.95

#: Arm B: waiver holds (0.95 >= 0.90 with no rescale) => base RW
RW_NON_REVOLVING: float = SA_RETAIL_QRRE_BASE_RW  # 0.75
RWA_NON_REVOLVING: float = DRAWN_AMOUNT * RW_NON_REVOLVING  # 75,000.00

# ---------------------------------------------------------------------------
# Hand-calculation results for Arm C (revolving fully drawn, waiver holds)
# ---------------------------------------------------------------------------

#: full_draw_base = max(100k, 100k) = 100k (fully drawn, no undrawn headroom)
FULL_DRAW_BASE_C: float = max(DRAWN_AMOUNT, FACILITY_LIMIT_FULLY_DRAWN)

#: covered_amount = 0.95 * 100k = 95k
COVERED_AMOUNT_C: float = HEDGE_COVERAGE_RATIO * DRAWN_AMOUNT

#: effective_coverage = 95k / 100k = 0.95 >= 0.90 => waiver holds
EFFECTIVE_COVERAGE_C: float = COVERED_AMOUNT_C / FULL_DRAW_BASE_C

#: Arm C: even under Art. 123B(2A), waiver holds because no undrawn headroom
RW_FULLY_DRAWN: float = SA_RETAIL_QRRE_BASE_RW  # 0.75
RWA_FULLY_DRAWN: float = DRAWN_AMOUNT * RW_FULLY_DRAWN  # 75,000.00


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.94d counterparty: natural person, GB, borrower income in EUR.

    entity_type=natural_person -> classifier routes to retail_qrre or retail_other.
    borrower_income_currency=EUR: triggers Art. 123B when loan is GBP (mismatch).
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_natural_person: bool
    borrower_income_currency: str

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_natural_person": self.is_natural_person,
            "borrower_income_currency": self.borrower_income_currency,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.94d loan row: GBP retail loan with hedge_coverage_ratio=0.95, is_hedged=False.

    currency=GBP vs. counterparty borrower_income_currency=EUR -> currency mismatch.
    is_hedged=False: is_hedged flag does not suppress the multiplier.
    hedge_coverage_ratio=0.95: the firm-supplied proportion is 95% of the current
        drawn balance. Under Art. 123B(2) (non-revolving / parent rule), this
        exceeds the 0.90 threshold and suppresses the multiplier. Under
        Art. 123B(2A) (revolving), it is rescaled to 95k / facility_limit and
        may fall below 0.90 when the facility is partially drawn.

    Extra columns ``is_revolving``, ``facility_limit``, and ``undrawn_amount`` are
    NOT yet in LOAN_SCHEMA — they are FACILITY_SCHEMA fields that propagate to
    loan rows via hierarchy._propagate_facility_qrre_columns when a parent
    facility exists. The fixture appends them directly as extra columns using
    pl.Series so the SA calculator's calculate_branch can read them from the
    frame without requiring a full pipeline run. The engine-implementer will
    add pass-through for these in _coerce_loans_to_unified in Wave 4.
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
    is_hedged: bool
    hedge_coverage_ratio: float
    is_revolving: bool
    facility_limit: float
    undrawn_amount: float

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
            "is_hedged": self.is_hedged,
            "hedge_coverage_ratio": self.hedge_coverage_ratio,
            "is_revolving": self.is_revolving,
            "facility_limit": self.facility_limit,
            "undrawn_amount": self.undrawn_amount,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p194d_counterparty() -> pl.DataFrame:
    """
    Return the P1.94d counterparty (natural person, GB, income EUR) as a DataFrame.

    entity_type=natural_person -> classifier produces exposure_class=retail_qrre
    (when is_qrre_transactor is set) or retail_other (non-mortgage retail).
    borrower_income_currency=EUR: the GBP loan triggers Art. 123B eligibility.
    The mismatch (GBP loan vs EUR income) is the reverse of the P1.94a/b/f
    pattern (EUR loan vs GBP income) to confirm the multiplier is symmetric.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P194D Test Individual",
        entity_type="natural_person",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=True,
        is_natural_person=True,
        borrower_income_currency="EUR",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p194d_loans() -> pl.DataFrame:
    """
    Return all three P1.94d loan rows as a single DataFrame.

    Build pattern:
    1. Construct the raw row dicts for all three arms.
    2. Build a DataFrame from the declared LOAN_SCHEMA columns only (excluding the
       three extra columns: is_revolving, facility_limit, undrawn_amount), using
       dtypes_of(LOAN_SCHEMA) for correct dtype coercion.
    3. Set is_hedged to the actual False value (it is in LOAN_SCHEMA but
       dtypes_of will leave it null; overwrite with the explicit value).
    4. Set hedge_coverage_ratio to 0.95 (same pattern as p1_94b).
    5. Append is_revolving as pl.Boolean, facility_limit as pl.Float64, and
       undrawn_amount as pl.Float64 as forward-compatible extra columns.

    The three extra columns mirror the fields produced by
    hierarchy._propagate_facility_qrre_columns / _apply_qrre_defaults, so the
    SA calculator's apply_currency_mismatch_multiplier can read them from cols
    without a full pipeline run.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF_REVOLVING,
            product_type="revolving_credit",
            book_code="RETAIL_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            is_hedged=False,
            hedge_coverage_ratio=HEDGE_COVERAGE_RATIO,
            is_revolving=True,
            facility_limit=FACILITY_LIMIT_PARTIAL,
            undrawn_amount=UNDRAWN_AMOUNT_PARTIAL,
        ),
        _Loan(
            loan_reference=LOAN_REF_NON_REVOLVING,
            product_type="term_loan",
            book_code="RETAIL_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            is_hedged=False,
            hedge_coverage_ratio=HEDGE_COVERAGE_RATIO,
            is_revolving=False,
            facility_limit=FACILITY_LIMIT_PARTIAL,
            undrawn_amount=UNDRAWN_AMOUNT_PARTIAL,
        ),
        _Loan(
            loan_reference=LOAN_REF_FULLY_DRAWN,
            product_type="revolving_credit",
            book_code="RETAIL_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            is_hedged=False,
            hedge_coverage_ratio=HEDGE_COVERAGE_RATIO,
            is_revolving=True,
            facility_limit=FACILITY_LIMIT_FULLY_DRAWN,
            undrawn_amount=UNDRAWN_AMOUNT_FULLY_DRAWN,
        ),
    ]

    # Step 1: Strip extra columns before building with the declared schema.
    _extra_cols = {
        "is_hedged",
        "hedge_coverage_ratio",
        "is_revolving",
        "facility_limit",
        "undrawn_amount",
    }
    loan_schema_cols = dtypes_of(LOAN_SCHEMA)
    rows_base = [{k: v for k, v in r.to_dict().items() if k not in _extra_cols} for r in rows]
    df = pl.DataFrame(rows_base, schema=loan_schema_cols)

    # Step 2: Overwrite is_hedged (in LOAN_SCHEMA since p1_94a wave) with explicit False.
    df = df.with_columns(pl.Series("is_hedged", [r.is_hedged for r in rows], dtype=pl.Boolean))

    # Step 3: Set hedge_coverage_ratio (in LOAN_SCHEMA since p1_94b wave) with 0.95.
    df = df.with_columns(
        pl.Series("hedge_coverage_ratio", [r.hedge_coverage_ratio for r in rows], dtype=pl.Float64)
    )

    # Step 4: Append is_revolving — FACILITY_SCHEMA field; not in LOAN_SCHEMA.
    # Propagated from parent facility via hierarchy._propagate_facility_qrre_columns
    # for facility-linked loan rows. Appended directly here for the standalone-loan
    # test path so the SA calculator can read it from the frame's column set.
    df = df.with_columns(
        pl.Series("is_revolving", [r.is_revolving for r in rows], dtype=pl.Boolean)
    )

    # Step 5: Append facility_limit — FACILITY_SCHEMA.limit after alias; not in LOAN_SCHEMA.
    # full_draw_base = max(drawn_amount, facility_limit); needed by the revolving branch.
    df = df.with_columns(
        pl.Series("facility_limit", [r.facility_limit for r in rows], dtype=pl.Float64)
    )

    # Step 6: Append undrawn_amount — hierarchy-derived; carried here for completeness.
    # undrawn_amount = facility_limit - drawn_amount (= 300k for Arms A/B, 0 for Arm C).
    df = df.with_columns(
        pl.Series("undrawn_amount", [r.undrawn_amount for r in rows], dtype=pl.Float64)
    )

    return df


# ---------------------------------------------------------------------------
# Empty helpers
# ---------------------------------------------------------------------------


def create_p194d_empty_facilities() -> pl.DataFrame:
    """Return an empty facilities DataFrame (no standalone facilities in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_SCHEMA))


def create_p194d_empty_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p194d_empty_collateral() -> pl.DataFrame:
    """Return an empty collateral DataFrame."""
    return pl.DataFrame(schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p194d_empty_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p194d_empty_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p194d_empty_ratings() -> pl.DataFrame:
    """Return an empty ratings DataFrame."""
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


def create_p194d_empty_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory
# ---------------------------------------------------------------------------


def build_p1_94d_bundle(*, fixtures_dir: Path | None = None) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P1.94d scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module. The optional ``fixtures_dir`` argument is accepted
    for interface symmetry with other bundle builders.

    Returns:
        RawDataBundle with:
        - 1 counterparty (CP_P194D, natural person, GB, income EUR)
        - 3 loans:
            P194D_REVOLVING    (is_revolving=True,  hedge_coverage_ratio=0.95,
                                facility_limit=400k, undrawn_amount=300k)
            P194D_NON_REVOLVING (is_revolving=False, hedge_coverage_ratio=0.95,
                                facility_limit=400k, undrawn_amount=300k)
            P194D_FULLY_DRAWN  (is_revolving=True,  hedge_coverage_ratio=0.95,
                                facility_limit=100k, undrawn_amount=0)
        - All other LazyFrames: empty, schema-conformant

    Args:
        fixtures_dir: Optional path to fixtures directory. Unused; accepted for
            interface compatibility.
    """
    if fixtures_dir is not None:
        cp_path = fixtures_dir / "counterparty.parquet"
        loans_path = fixtures_dir / "loans.parquet"
        if cp_path.exists() and loans_path.exists():
            counterparties_lf = pl.read_parquet(cp_path).lazy()
            loans_lf = pl.read_parquet(loans_path).lazy()
        else:
            counterparties_lf = create_p194d_counterparty().lazy()
            loans_lf = create_p194d_loans().lazy()
    else:
        counterparties_lf = create_p194d_counterparty().lazy()
        loans_lf = create_p194d_loans().lazy()

    return make_raw_bundle(
        facilities=create_p194d_empty_facilities().lazy(),
        loans=loans_lf,
        counterparties=counterparties_lf,
        facility_mappings=pl.DataFrame(
            schema={"parent_facility_reference": pl.String, "child_reference": pl.String}
        ).lazy(),
        lending_mappings=pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy(),
        org_mappings=None,
        contingents=create_p194d_empty_contingents().lazy(),
        collateral=create_p194d_empty_collateral().lazy(),
        guarantees=create_p194d_empty_guarantees().lazy(),
        provisions=create_p194d_empty_provisions().lazy(),
        ratings=create_p194d_empty_ratings().lazy(),
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p194d_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.94d parquet files and return a mapping of name -> path.

    Two parquet files are written:
    - counterparty.parquet  (1 row: CP_P194D)
    - loans.parquet         (3 rows: P194D_REVOLVING, P194D_NON_REVOLVING,
                             P194D_FULLY_DRAWN)

    The loans parquet includes five schema-extension columns beyond LOAN_SCHEMA:
      - is_hedged           (pl.Boolean, default False — in LOAN_SCHEMA since p1_94a)
      - hedge_coverage_ratio (pl.Float64, value 0.95 — in LOAN_SCHEMA since p1_94b)
      - is_revolving        (pl.Boolean — FACILITY_SCHEMA field; extra column)
      - facility_limit      (pl.Float64 — FACILITY_SCHEMA.limit alias; extra column)
      - undrawn_amount      (pl.Float64 — hierarchy-derived; extra column)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p194d_counterparty()),
        ("loans", create_p194d_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.94d fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<20} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: P1.94d — Art. 123B(2A) revolving-instalment rule")
    print()
    print(f"  Base retail QRRE SA RW (Art. 123(1)):   {SA_RETAIL_QRRE_BASE_RW:.0%}")
    print(f"  Art. 123B multiplier:                   {CURRENCY_MISMATCH_MULTIPLIER:.2f}x")
    print(f"  Firm hedge_coverage_ratio (all arms):   {HEDGE_COVERAGE_RATIO:.2f}")
    print(f"  Art. 123B(2) threshold:                 {HEDGE_COVERAGE_THRESHOLD:.2f}")
    print()
    print("  Arm A (P194D_REVOLVING, is_revolving=True, partially drawn):")
    print(f"    full_draw_base                       = {FULL_DRAW_BASE_A:,.0f}")
    print(f"    covered_amount                       = {COVERED_AMOUNT_A:,.0f}")
    print(f"    effective_coverage                   = {EFFECTIVE_COVERAGE_A:.4f}  (<0.90)")
    print("    waiver                               = False")
    print(f"    risk_weight                          = {RW_REVOLVING:.4f}")
    print(f"    rwa                                  = {RWA_REVOLVING:,.2f}")
    print("    currency_mismatch_multiplier_applied = True")
    print()
    print("  Arm B (P194D_NON_REVOLVING, is_revolving=False, control):")
    print(f"    effective_coverage                   = {EFFECTIVE_COVERAGE_B:.4f}  (>=0.90)")
    print("    waiver                               = True  (no revolving rescale)")
    print(f"    risk_weight                          = {RW_NON_REVOLVING:.4f}")
    print(f"    rwa                                  = {RWA_NON_REVOLVING:,.2f}")
    print("    currency_mismatch_multiplier_applied = False")
    print()
    print("  Arm C (P194D_FULLY_DRAWN, is_revolving=True, no undrawn headroom):")
    print(f"    full_draw_base                       = {FULL_DRAW_BASE_C:,.0f}")
    print(f"    covered_amount                       = {COVERED_AMOUNT_C:,.0f}")
    print(f"    effective_coverage                   = {EFFECTIVE_COVERAGE_C:.4f}  (>=0.90)")
    print("    waiver                               = True  (full draw = current draw)")
    print(f"    risk_weight                          = {RW_FULLY_DRAWN:.4f}")
    print(f"    rwa                                  = {RWA_FULLY_DRAWN:,.2f}")
    print("    currency_mismatch_multiplier_applied = False")
    print()

    # Verify extra columns in loans parquet
    loans_df = pl.read_parquet(saved["loans"])
    for col_name, expected_dtype in [
        ("is_hedged", pl.Boolean),
        ("hedge_coverage_ratio", pl.Float64),
        ("is_revolving", pl.Boolean),
        ("facility_limit", pl.Float64),
        ("undrawn_amount", pl.Float64),
    ]:
        if col_name in loans_df.columns:
            actual_dtype = loans_df.schema[col_name]
            vals = loans_df[col_name].to_list()
            status = "OK" if actual_dtype == expected_dtype else f"WRONG dtype: {actual_dtype}"
            print(f"  [{status}] {col_name}: {vals}")
        else:
            print(f"  [WARNING] {col_name} column missing from loans parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p194d_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
