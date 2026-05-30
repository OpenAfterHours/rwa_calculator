"""
P2.41 fixture builder: IRB corporate COREP C 02.00 exposure_subclass split.

Pipeline position (reporting path):
    CreditRiskCalc.calculate() -> Pillar3Generator._c02_00 -> rows 0295/0296/0297

Scenario design (P2.41 — PRA PS1/26 Art. 147A(1)(e)/(f), Basel 3.1):

    COREP C 02.00 F-IRB corporate sub-rows require three-way discrimination:
        0295  Financial and large corporates (Art. 147A(1)(e) FSE limb OR
              large-corp-by-revenue, annual_revenue > GBP 440m)
        0296  Other general corporates — SME
        0297  Other general corporates — non-SME

    Four counterparties / four loans (one loan per counterparty):

        CP1 (CP-P241-FSE):
            entity_type="corporate", is_financial_sector_entity=True
            annual_revenue=200_000_000 (< 440m, but FSE limb applies)
            → subclass: corporate_financial_large (row 0295 via FSE Art. 147A(1)(e))
            Approach: F-IRB (A-IRB blocked by FSE, per Art. 147A(1)(e))

        CP2 (CP-P241-LRGCORP):
            entity_type="corporate", is_financial_sector_entity=False
            annual_revenue=500_000_000 (> GBP 440m)
            → subclass: corporate_financial_large (row 0295 via large-corp limb)
            Approach: F-IRB (A-IRB blocked by large-corp, per Art. 147A(1)(d))
            ANTI-DEGENERATE: CP2 is NOT an FSE, so the large-corp revenue limb
            is the only route into 0295. This is the load-bearing test case.

        CP3 (CP-P241-CORPOTHER):
            entity_type="corporate", is_financial_sector_entity=False
            annual_revenue=100_000_000 (>= SME threshold, < 440m)
            → subclass: corporate_other / non-SME (row 0297)
            Approach: A-IRB eligible (neither FSE nor large-corp restriction)

        CP4 (CP-P241-SME):
            entity_type="corporate", is_financial_sector_entity=False
            annual_revenue=30_000_000 (< GBP 44m SME turnover threshold)
            → subclass: corporate_sme (row 0296)
            Approach: A-IRB eligible (SME, not FSE)

    Loans (one per counterparty, all GBP senior term loans):
        LN-P241-FSE:      EAD=50_000_000, PD=0.0050, LGD=0.40, M=2.5 (F-IRB)
        LN-P241-LRGCORP:  EAD=80_000_000, PD=0.0080, LGD=0.40, M=2.5 (F-IRB)
        LN-P241-CORPOTHER:EAD=60_000_000, PD=0.0050, LGD=0.30, M=2.5 (A-IRB)
        LN-P241-SME:      EAD=20_000_000, PD=0.0100, LGD=0.30, M=2.5 (A-IRB)

    Model permissions:
        MODEL-P241-FIRB  → foundation_irb, exposure_class=corporate (CP1, CP2)
        MODEL-P241-AIRB  → advanced_irb,   exposure_class=corporate (CP3, CP4)
        (Two separate models so CP1/CP2 get F-IRB and CP3/CP4 get A-IRB.)

    Ratings:
        RTG-P241-FSE:      CP1, model=MODEL-P241-FIRB, PD=0.0050
        RTG-P241-LRGCORP:  CP2, model=MODEL-P241-FIRB, PD=0.0080
        RTG-P241-CORPOTHER:CP3, model=MODEL-P241-AIRB, PD=0.0050
        RTG-P241-SME:      CP4, model=MODEL-P241-AIRB, PD=0.0100

    Config: CalculationConfig.basel_3_1(permission_mode=IRB)
    Reporting date: 2027-06-01 (fully in Basel 3.1 window)

Load-bearing assertion (row 0295 sum):
    Both CP1 (FSE) and CP2 (large-corp-by-revenue, NOT FSE) must appear in 0295.
    Under the current engine, CP2 would fall into 0297 (is_fse=False, is_sme=False).
    P2.41 engine fix: COREP _c02_00_irb_sub_agg must additionally derive _fse=True
    when annual_revenue > 440m, regardless of is_financial_sector_entity.

Expected COREP sums (row 0010 = EAD × RWA_density, approximate — test-writer
computes exact values from the IRB K formula):
    Row 0295: CP1 RWA + CP2 RWA  (both land in financial_large)
    Row 0296: CP4 RWA             (SME)
    Row 0297: CP3 RWA             (corporate_other non-SME)

References:
    - PRA PS1/26 Art. 147A(1)(d): large-corporate F-IRB restriction (> GBP 440m)
    - PRA PS1/26 Art. 147A(1)(e): FSE F-IRB restriction
    - PRA PS1/26 Art. 147A(1)(f): other corporate (non-FSE, non-large, non-SME)
    - COREP templates.py rows 0295/0296/0297
    - generator.py _c02_00_irb_sub_agg / _irb_sub_split

Usage (clean-import check):
    cd /home/philm/projects/rwa_calculator/tmp/worktrees/P2.41
    PYTHONPATH=src /home/philm/projects/rwa_calculator/.venv/bin/python \\
        tests/fixtures/p2_41/p2_41.py
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

SCENARIO_ID: str = "P2.41"
FRAMEWORK: str = "BASEL_3_1"

# Counterparty references
CP_FSE: str = "CP-P241-FSE"
CP_LRGCORP: str = "CP-P241-LRGCORP"
CP_CORPOTHER: str = "CP-P241-CORPOTHER"
CP_SME: str = "CP-P241-SME"

# Loan references
LOAN_FSE: str = "LN-P241-FSE"
LOAN_LRGCORP: str = "LN-P241-LRGCORP"
LOAN_CORPOTHER: str = "LN-P241-CORPOTHER"
LOAN_SME: str = "LN-P241-SME"

# Rating references
RATING_FSE: str = "RTG-P241-FSE"
RATING_LRGCORP: str = "RTG-P241-LRGCORP"
RATING_CORPOTHER: str = "RTG-P241-CORPOTHER"
RATING_SME: str = "RTG-P241-SME"

# Model IDs (unique to this scenario — avoid cross-test interference)
MODEL_FIRB: str = "CORP-FIRB-P241"
MODEL_AIRB: str = "CORP-AIRB-P241"

# Revenue thresholds (PRA PS1/26 Art. 147A(1)(d)):
#   GBP 44m  = SME turnover ceiling
#   GBP 440m = large-corporate threshold
REVENUE_FSE: float = 200_000_000.0  # FSE; below 440m; FSE limb fires
REVENUE_LRGCORP: float = 500_000_000.0  # NOT FSE; above 440m; large-corp limb fires
REVENUE_CORPOTHER: float = 100_000_000.0  # not FSE; in [44m, 440m]; corporate_other
REVENUE_SME: float = 30_000_000.0  # < 44m GBP SME threshold

# EADs (round numbers for easy hand-calculation)
EAD_FSE: float = 50_000_000.0
EAD_LRGCORP: float = 80_000_000.0
EAD_CORPOTHER: float = 60_000_000.0
EAD_SME: float = 20_000_000.0

# IRB parameters
# F-IRB rows (CP1, CP2): PD from rating; LGD = 0.40 (B3.1 F-IRB senior unsecured,
# PRA PS1/26 Art. 161(1)(aa))
PD_FSE: float = 0.0050  # 0.50%
PD_LRGCORP: float = 0.0080  # 0.80%
LGD_FIRB: float = 0.40

# A-IRB rows (CP3, CP4): PD from rating; LGD populated (A-IRB own estimate)
PD_CORPOTHER: float = 0.0050  # 0.50%
PD_SME: float = 0.0100  # 1.00%
LGD_AIRB: float = 0.30  # A-IRB own LGD estimate (above 25% AIRB floor for corp)

EFFECTIVE_MATURITY: float = 2.5  # years

# Dates
VALUE_DATE: date = date(2027, 1, 1)
MATURITY_DATE: date = date(2029, 7, 1)  # ~2.5y from value date
RATING_DATE: date = date(2027, 1, 2)
REPORTING_DATE: date = date(2027, 6, 1)

# COREP row references for the load-bearing assertions
COREP_ROW_FINANCIAL_LARGE: str = "0295"  # F-IRB — Financial and large corporates
COREP_ROW_CORPORATE_SME: str = "0296"  # F-IRB — Other general corporates (SME)
COREP_ROW_CORPORATE_OTHER: str = "0297"  # F-IRB — Other general corporates (non-SME)


# ---------------------------------------------------------------------------
# Internal dataclasses (thin wrappers for type-safety)
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
    is_financial_sector_entity: bool

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
            "is_financial_sector_entity": self.is_financial_sector_entity,
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


def create_p241_counterparties() -> pl.DataFrame:
    """Return the 4 P2.41 counterparties as a DataFrame.

    Load-bearing shape:
        CP_FSE:        is_financial_sector_entity=True,  annual_revenue=200m  → 0295 (FSE limb)
        CP_LRGCORP:    is_financial_sector_entity=False, annual_revenue=500m  → 0295 (large-corp limb)
        CP_CORPOTHER:  is_financial_sector_entity=False, annual_revenue=100m  → 0297 (non-SME other)
        CP_SME:        is_financial_sector_entity=False, annual_revenue=30m   → 0296 (SME)

    CP2 being NOT an FSE but ABOVE 440m revenue is the anti-degenerate test: the
    large-corp-by-revenue path into row 0295 must work independently of the FSE flag.
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_FSE,
            counterparty_name="P2.41 FSE Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=REVENUE_FSE,
            total_assets=500_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=True,
        ),
        _Counterparty(
            counterparty_reference=CP_LRGCORP,
            counterparty_name="P2.41 Large Corp Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=REVENUE_LRGCORP,
            total_assets=900_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,  # NOT FSE — only revenue limb applies
        ),
        _Counterparty(
            counterparty_reference=CP_CORPOTHER,
            counterparty_name="P2.41 Corp Other Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=REVENUE_CORPOTHER,
            total_assets=200_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        _Counterparty(
            counterparty_reference=CP_SME,
            counterparty_name="P2.41 SME Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=REVENUE_SME,
            total_assets=15_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p241_loans() -> pl.DataFrame:
    """Return the 4 P2.41 loan rows as a DataFrame.

    All loans are senior unsecured GBP term loans:
        LOAN_FSE:       CP_FSE,        EAD=50m,  LGD=0.40 (F-IRB supervisory, Art. 161(1)(aa))
        LOAN_LRGCORP:   CP_LRGCORP,    EAD=80m,  LGD=0.40 (F-IRB supervisory)
        LOAN_CORPOTHER: CP_CORPOTHER,  EAD=60m,  LGD=0.30 (A-IRB own estimate)
        LOAN_SME:       CP_SME,        EAD=20m,  LGD=0.30 (A-IRB own estimate)

    Effective maturity=2.5y on all rows produces well-defined non-degenerate IRB K
    (maturity adjustment b(PD) applies, PD above B3.1 corporate floor of 0.03%).
    beel=0.0 means no best-estimate-of-expected-loss adjustment.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_FSE,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_FSE,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_FSE,
            interest=0.0,
            lgd=LGD_FIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
        _Loan(
            loan_reference=LOAN_LRGCORP,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_LRGCORP,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_LRGCORP,
            interest=0.0,
            lgd=LGD_FIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
        _Loan(
            loan_reference=LOAN_CORPOTHER,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_CORPOTHER,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_CORPOTHER,
            interest=0.0,
            lgd=LGD_AIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
        _Loan(
            loan_reference=LOAN_SME,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_SME,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=EAD_SME,
            interest=0.0,
            lgd=LGD_AIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p241_ratings() -> pl.DataFrame:
    """Return the 4 P2.41 internal rating rows as a DataFrame.

    Each counterparty has one internal rating row referencing its model:
        CP_FSE       → MODEL_FIRB (F-IRB), PD=0.0050
        CP_LRGCORP   → MODEL_FIRB (F-IRB), PD=0.0080
        CP_CORPOTHER → MODEL_AIRB (A-IRB), PD=0.0050
        CP_SME       → MODEL_AIRB (A-IRB), PD=0.0100

    No external CQS is set — all counterparties are unrated externally.
    Internal PDs are above the B3.1 corporate PD floor (0.03%) so floors do
    not interfere with the approach-routing signal.
    """
    rows = [
        _Rating(
            rating_reference=RATING_FSE,
            counterparty_reference=CP_FSE,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BB",
            pd=PD_FSE,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_FIRB,
        ),
        _Rating(
            rating_reference=RATING_LRGCORP,
            counterparty_reference=CP_LRGCORP,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BB",
            pd=PD_LRGCORP,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_FIRB,
        ),
        _Rating(
            rating_reference=RATING_CORPOTHER,
            counterparty_reference=CP_CORPOTHER,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BB",
            pd=PD_CORPOTHER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_AIRB,
        ),
        _Rating(
            rating_reference=RATING_SME,
            counterparty_reference=CP_SME,
            rating_type="internal",
            rating_agency="internal",
            rating_value="B",
            pd=PD_SME,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_AIRB,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p241_model_permissions() -> pl.DataFrame:
    """Return the 2 P2.41 model permission rows as a DataFrame.

    MODEL_FIRB (CORP-FIRB-P241):  grants foundation_irb for corporate
        → CP1 (FSE) and CP2 (large-corp) will route F-IRB; their A-IRB is
          blocked by Art. 147A(1)(d)/(e) at the classifier level regardless
          of this permission.

    MODEL_AIRB (CORP-AIRB-P241):  grants advanced_irb for corporate
        → CP3 (corporate_other) and CP4 (SME) will route A-IRB; neither
          the FSE nor the large-corp restriction applies to them.

    Separate model IDs for F-IRB and A-IRB here because:
        - Using a single model with both FIRB + AIRB would mean CP1/CP2 could
          "attempt" A-IRB and be blocked by the classifier; that's also valid
          but adds a dependency on the classifier gate to the test.
        - Using distinct models makes the routing explicit in the fixture:
          the test-writer need only assert that the model_id-to-approach
          assignment drives the CP1/CP2 → F-IRB and CP3/CP4 → A-IRB split,
          and that the COREP 0295 sum includes BOTH approaches' corporate
          financial-large / large-corp-by-revenue rows.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_FIRB,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_AIRB,
            exposure_class="corporate",
            approach="advanced_irb",
            country_codes=None,
            excluded_book_codes=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p241_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all P2.41 parquet files and return a name-to-path mapping.

    Args:
        output_dir: Target directory.  Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p241_counterparties()),
        ("loan", create_p241_loans()),
        ("rating", create_p241_ratings()),
        ("model_permission", create_p241_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.41 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>2} row(s)  ->  {path.name}")
    print("-" * 70)
    print("Scenario: COREP C 02.00 corporate sub-row split (Basel 3.1)")
    print(f"  CP1 FSE (row 0295):       EAD={EAD_FSE:,.0f}, PD={PD_FSE:.2%}, LGD={LGD_FIRB:.0%}")
    print(
        f"  CP2 large-corp (row 0295):EAD={EAD_LRGCORP:,.0f}, PD={PD_LRGCORP:.2%}, LGD={LGD_FIRB:.0%}"
    )
    print(
        f"  CP3 corp-other (row 0297):EAD={EAD_CORPOTHER:,.0f}, PD={PD_CORPOTHER:.2%}, LGD={LGD_AIRB:.0%}"
    )
    print(f"  CP4 SME (row 0296):       EAD={EAD_SME:,.0f}, PD={PD_SME:.2%}, LGD={LGD_AIRB:.0%}")
    print(
        f"  Anti-degenerate: CP2 is_financial_sector_entity=False, "
        f"annual_revenue={REVENUE_LRGCORP:,.0f} > 440m"
    )


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_fixtures() -> None:
    """Smoke-check all DataFrames: shapes, schema invariants, and scenario constants."""
    cp_df = create_p241_counterparties()
    ln_df = create_p241_loans()
    rt_df = create_p241_ratings()
    mp_df = create_p241_model_permissions()

    # Shape
    assert cp_df.height == 4, f"Expected 4 counterparties, got {cp_df.height}"
    assert ln_df.height == 4, f"Expected 4 loans, got {ln_df.height}"
    assert rt_df.height == 4, f"Expected 4 ratings, got {rt_df.height}"
    assert mp_df.height == 2, f"Expected 2 model_permissions, got {mp_df.height}"

    # CP1: FSE=True, revenue < 440m
    cp1 = cp_df.filter(pl.col("counterparty_reference") == CP_FSE)
    assert cp1.height == 1
    assert cp1["is_financial_sector_entity"][0] is True, "CP1 must be FSE"
    assert cp1["annual_revenue"][0] < 440_000_000.0, "CP1 revenue must be < 440m"

    # CP2: FSE=False, revenue > 440m (anti-degenerate)
    cp2 = cp_df.filter(pl.col("counterparty_reference") == CP_LRGCORP)
    assert cp2.height == 1
    assert cp2["is_financial_sector_entity"][0] is False, "CP2 must NOT be FSE"
    assert cp2["annual_revenue"][0] > 440_000_000.0, "CP2 revenue must exceed GBP 440m"

    # CP3: FSE=False, revenue in [44m, 440m]
    cp3 = cp_df.filter(pl.col("counterparty_reference") == CP_CORPOTHER)
    assert cp3.height == 1
    assert cp3["is_financial_sector_entity"][0] is False, "CP3 must not be FSE"
    assert 44_000_000.0 <= cp3["annual_revenue"][0] <= 440_000_000.0, (
        f"CP3 revenue must be in SME-to-440m range, got {cp3['annual_revenue'][0]}"
    )

    # CP4: FSE=False, revenue < 44m SME threshold
    cp4 = cp_df.filter(pl.col("counterparty_reference") == CP_SME)
    assert cp4.height == 1
    assert cp4["is_financial_sector_entity"][0] is False, "CP4 must not be FSE"
    assert cp4["annual_revenue"][0] < 44_000_000.0, (
        f"CP4 revenue must be < GBP 44m SME threshold, got {cp4['annual_revenue'][0]}"
    )

    # Ratings reference the correct models
    assert rt_df.filter(pl.col("counterparty_reference") == CP_FSE)["model_id"][0] == MODEL_FIRB
    assert rt_df.filter(pl.col("counterparty_reference") == CP_LRGCORP)["model_id"][0] == MODEL_FIRB
    assert (
        rt_df.filter(pl.col("counterparty_reference") == CP_CORPOTHER)["model_id"][0] == MODEL_AIRB
    )
    assert rt_df.filter(pl.col("counterparty_reference") == CP_SME)["model_id"][0] == MODEL_AIRB

    # Model permissions: one FIRB, one AIRB
    firb_perm = mp_df.filter(pl.col("approach") == "foundation_irb")
    airb_perm = mp_df.filter(pl.col("approach") == "advanced_irb")
    assert firb_perm.height == 1, f"Expected 1 FIRB permission, got {firb_perm.height}"
    assert airb_perm.height == 1, f"Expected 1 AIRB permission, got {airb_perm.height}"
    assert firb_perm["model_id"][0] == MODEL_FIRB
    assert airb_perm["model_id"][0] == MODEL_AIRB

    # All PDs are above the B3.1 corporate floor (0.03% = 0.0003)
    for pd_val in (PD_FSE, PD_LRGCORP, PD_CORPOTHER, PD_SME):
        assert pd_val >= 0.0003, f"PD {pd_val} is below the B3.1 corporate floor 0.03%"

    # LGD values satisfy A-IRB floor (>= 25% = 0.25 for unsecured corporate)
    for lgd_val in (LGD_FIRB, LGD_AIRB):
        assert lgd_val >= 0.25, f"LGD {lgd_val} is below the 25% A-IRB floor for corporate"

    # Revenue thresholds are internally consistent
    assert REVENUE_LRGCORP > 440_000_000.0, "REVENUE_LRGCORP must exceed GBP 440m"
    assert 44_000_000.0 <= REVENUE_CORPOTHER <= 440_000_000.0, (
        "REVENUE_CORPOTHER must be in [44m, 440m]"
    )
    assert REVENUE_SME < 44_000_000.0, "REVENUE_SME must be < GBP 44m"

    # EADs are positive
    for ead in (EAD_FSE, EAD_LRGCORP, EAD_CORPOTHER, EAD_SME):
        assert ead > 0.0, f"EAD {ead} must be positive"


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p241_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    _verify_fixtures()
    saved = save_p241_fixtures()
    print_summary(saved)
    print("\nP2.41 fixture self-check passed.")
    print(f"  4 counterparties: {CP_FSE}, {CP_LRGCORP}, {CP_CORPOTHER}, {CP_SME}")
    print("  4 loans, 4 ratings, 2 model_permissions")
    print(f"  Anti-degenerate: {CP_LRGCORP} is NOT FSE but revenue={REVENUE_LRGCORP:,.0f} > 440m")
    print("  Expected COREP rows: 0295 (CP1+CP2), 0296 (CP4), 0297 (CP3)")
