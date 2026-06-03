"""
Generate P1.197 fixtures: CRR slotting OBS EAD must use Art. 166(8)(d) F-IRB CCF (75%).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/ccf.py)

Key responsibilities:
- Produce one counterparty row: specialised_lending SPV, GB, project_finance, Strong.
- Produce one specialised-lending metadata row: sl_type=project_finance,
  slotting_category=strong, is_hvcre=False.
- Produce one facility row (parent commitment line):
    SL-FAC-001, limit=6,000,000, risk_type=MR, is_obs_commitment=True,
    maturity_date=2030-12-31, committed=True. Represents the full project-finance
    credit line (drawn + undrawn).
- Produce one loan row (drawn on-balance-sheet portion):
    SL-LOAN-001, drawn_amount=4,000,000, interest=0.
    Hierarchy resolver derives undrawn_amount = limit - drawn = 2,000,000.
- Produce one facility_mapping row linking loan SL-LOAN-001 to facility SL-FAC-001.

Scenario rationale (CRR-E.CCF1):
    Under CRR Art. 166(8)(d), F-IRB OBS items that are credit lines / NIFs / RUFs
    attract a 75% CCF (FIRB_CREDIT_LINE_CCF). Slotting is the IRB chapter for
    corporate specialised lending (Art. 147(8), 153(5)) — its EAD is therefore
    governed by Art. 166, not SA Art. 111.

    The pre-fix engine's _compute_ccf() branches only AIRB and FIRB; the SLOTTING
    approach falls to .otherwise() -> _sa_ccf_from_risk_type (SA CCF 50% for MR).
    Post-fix: SLOTTING under CRR routes to _firb_ccf_from_risk_type (75% for
    MR + is_obs_commitment=True).

    B31 must remain on SA CCFs via Art. 166C (CCF parity). Fix must be CRR-gated.

Hand-calculation (CRR, CalculationConfig.crr(reporting_date=date(2024, 12, 31))):

    Step 1 — CCF (the fix):
        risk_type=MR, is_obs_commitment=True, is_short_term_trade_lc=False
        → Art. 166(8)(d): FIRB_CREDIT_LINE_CCF = 0.75
        (Buggy: SA_CCF_CRR["MR"] = 0.50)

    Step 2 — on-BS EAD:
        on_bs_for_ead = max(0, drawn_amount) + max(0, interest)
                      = 4,000,000 + 0 = 4,000,000

    Step 3 — OBS EAD:
        ead_from_ccf = nominal_amount * ccf = 2,000,000 * 0.75 = 1,500,000

    Step 4 — total EAD (pre-CRM):
        ead_pre_crm = on_bs_for_ead + ead_from_ccf = 4,000,000 + 1,500,000 = 5,500,000
        No CRM -> ead_final = 5,500,000

    Step 5 — slotting RW (CRR Art. 153(5) Table 1):
        PF Strong, maturity >= 2.5yr (2030-12-31 from 2024-12-31 = 6yr), not HVCRE
        -> SLOTTING_RISK_WEIGHTS[STRONG] = 0.70

    Step 6 — RWA (slotting branch, pre-1.06x scaling):
        5,500,000 * 0.70 = 3,850,000

    Bug regression (pre-fix):
        ccf=0.50 -> ead_from_ccf=1,000,000 -> ead_pre_crm=5,000,000 -> rwa=3,500,000

Expected outputs (post-fix, slotting branch, pre portfolio scaling):
    ccf           = 0.75
    ead_from_ccf  = 1,500,000
    on_bs_for_ead = 4,000,000
    ead_pre_crm   = 5,500,000
    ead_final     = 5,500,000
    risk_weight   = 0.70
    rwa           = 3,850,000  (1.06x scaling applied at aggregator level only)

References:
    - CRR Art. 166(8)(d): F-IRB CCF 75% for credit lines / NIFs / RUFs
    - CRR Art. 147(8): specialised lending is a sub-class of corporate
    - CRR Art. 151(5)/(8): IRB EAD per Art. 166
    - CRR Art. 153(5) Table 1: slotting risk weights (PF Strong >=2.5yr = 70%)
    - src/rwa_calc/engine/ccf.py:438-446 (bug site: SLOTTING falls to SA CCF)
    - src/rwa_calc/data/tables/ccf.py:133 (FIRB_CREDIT_LINE_CCF = 0.75)
    - src/rwa_calc/data/tables/ccf.py:90 (SA_CCF_CRR["MR"] = 0.50)
    - src/rwa_calc/data/tables/crr_slotting.py (SLOTTING_RISK_WEIGHTS Strong=0.70)
    - src/rwa_calc/data/schemas.py:1292-1298 (VALID_SL_TYPES, "project_finance")
    - docs/specifications/crr/credit-conversion-factors.md line 53 (Art. 166(8)(d))
    - docs/specifications/crr/slotting-approach.md lines 36-47 (Art. 153(5) Table 1)

Usage:
    python tests/fixtures/p1_197/p1_197.py
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
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP-SL-PF-01"
FACILITY_REF: str = "SL-FAC-001"
LOAN_REF: str = "SL-LOAN-001"

# Dates
# reporting_date = 2024-12-31 (CalculationConfig.crr(reporting_date=date(2024, 12, 31)))
# maturity_date = 2030-12-31: residual 6yr >> 2.5yr threshold -> long maturity -> 70% RW
REPORTING_DATE: date = date(2024, 12, 31)
VALUE_DATE: date = date(2024, 1, 1)
MATURITY_DATE: date = date(2030, 12, 31)  # 6yr residual; ensures Strong >=2.5yr path

# Facility economics (CCF applies to the undrawn commitment headroom)
DRAWN_AMOUNT: float = 4_000_000.0  # On-balance-sheet drawn portion (loan row)
INTEREST: float = 0.0  # No accrued interest
UNDRAWN_AMOUNT: float = 2_000_000.0  # OBS commitment headroom = limit - drawn
FACILITY_LIMIT: float = DRAWN_AMOUNT + UNDRAWN_AMOUNT  # 6,000,000

# CCF inputs (for test-writer reference)
RISK_TYPE: str = "MR"  # Medium-risk commitment >1yr (CRR Annex I Row 3)
IS_OBS_COMMITMENT: bool = True  # Credit line -> Art. 166(8)(d) 75% F-IRB CCF
IS_SHORT_TERM_TRADE_LC: bool = False  # Not a trade LC (Art. 166(9) exception inapplicable)

# ---------------------------------------------------------------------------
# Expected outputs (post-fix) — anchors for test-writer assertions
# ---------------------------------------------------------------------------

# Art. 166(8)(d): credit-line CCF for slotting (CRR-only; B31 uses SA CCF via Art. 166C)
EXPECTED_CCF: float = 0.75  # F-IRB credit-line CCF (Art. 166(8)(d))
BUGGY_CCF: float = 0.50  # SA CCF for MR (pre-fix bug)

EXPECTED_ON_BS_FOR_EAD: float = DRAWN_AMOUNT + INTEREST  # 4,000,000
EXPECTED_EAD_FROM_CCF: float = UNDRAWN_AMOUNT * EXPECTED_CCF  # 1,500,000
EXPECTED_EAD_PRE_CRM: float = EXPECTED_ON_BS_FOR_EAD + EXPECTED_EAD_FROM_CCF  # 5,500,000
EXPECTED_EAD_FINAL: float = EXPECTED_EAD_PRE_CRM  # no CRM -> unchanged

# CRR Art. 153(5) Table 1: PF Strong, >=2.5yr maturity, non-HVCRE -> 70%
EXPECTED_RISK_WEIGHT: float = 0.70

# Pre-scaling RWA (1.06x IRB scaling factor is applied at aggregator, not slotting branch)
EXPECTED_RWA_PRE_SCALING: float = EXPECTED_EAD_FINAL * EXPECTED_RISK_WEIGHT  # 3,850,000

# Regression sentinels (pre-fix, buggy values)
BUGGY_EAD_FROM_CCF: float = UNDRAWN_AMOUNT * BUGGY_CCF  # 1,000,000
BUGGY_EAD_PRE_CRM: float = EXPECTED_ON_BS_FOR_EAD + BUGGY_EAD_FROM_CCF  # 5,000,000
BUGGY_RWA_PRE_SCALING: float = BUGGY_EAD_PRE_CRM * EXPECTED_RISK_WEIGHT  # 3,500,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.197 specialised-lending SPV counterparty.

    entity_type="specialised_lending" routes the classifier to the slotting
    approach for all exposures under this counterparty.
    country_code=GB: domestic GBP counterparty — no FX mismatch.
    annual_revenue=None: SL SPVs have no standalone revenue.
    apply_fi_scalar=False: not a financial institution.
    is_managed_as_retail=False: specialised lending is never retail.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _SLMetadata:
    """
    P1.197 specialised lending metadata row.

    sl_type="project_finance": load-bearing for the slotting RW table lookup.
    slotting_category="strong": maps to SLOTTING_RISK_WEIGHTS[STRONG] = 0.70
        under CRR Art. 153(5) Table 1 with maturity >= 2.5yr.
    is_hvcre=False: CRR has no separate HVCRE table; PF routes through Table 1.
    """

    counterparty_reference: str
    sl_type: str
    slotting_category: str
    is_hvcre: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "sl_type": self.sl_type,
            "slotting_category": self.slotting_category,
            "is_hvcre": self.is_hvcre,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.197 committed credit facility (the OBS commitment line).

    limit=6,000,000: total limit (drawn 4m + undrawn 2m).
    committed=True: unconditionally committed (not a UCC/LR line).
    risk_type="MR": medium-risk commitment >1yr; selects Art. 166(8)(d) CCF path.
    is_obs_commitment=True: credit-line / NIF / RUF bucket (Art. 166(8)(d) 75%)
        vs. issued OBS fallback (Art. 166(10) 50% MR).
    is_short_term_trade_lc=False: not a documentary credit (Art. 166(9) inapplicable).
    maturity_date=2030-12-31: 6yr from 2024-12-31 -> is_short_maturity=False -> 70% RW.
    seniority="senior": standard for project-finance debt.
    """

    facility_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    seniority: str
    risk_type: str
    is_obs_commitment: bool
    is_short_term_trade_lc: bool

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "is_obs_commitment": self.is_obs_commitment,
            "is_short_term_trade_lc": self.is_short_term_trade_lc,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.197 on-balance-sheet drawn loan.

    drawn_amount=4,000,000: the on-BS portion already drawn under the facility.
    interest=0: no accrued interest.
    EAD for this row: on_bs_for_ead = max(0, 4,000,000) + max(0, 0) = 4,000,000.
    The OBS (undrawn) commitment is represented by the parent facility row, not
    this loan. The hierarchy resolver sets undrawn_amount = limit - drawn =
    6,000,000 - 4,000,000 = 2,000,000, which becomes nominal_amount in the CCF
    exposure view.
    seniority="senior": senior secured (standard for PF).
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
    seniority: str
    is_payroll_loan: bool
    is_buy_to_let: bool
    is_under_construction: bool

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
            "seniority": self.seniority,
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


@dataclass(frozen=True)
class _FacilityMapping:
    """
    P1.197 facility-mapping row: loan SL-LOAN-001 is a child of facility SL-FAC-001.

    child_type="loan": the hierarchy resolver uses this to distinguish loans from
    sub-facilities. The resolver subtracts the loan's drawn_amount from the
    parent facility's limit to compute undrawn_amount (the CCF subject amount).
    """

    parent_facility_reference: str
    child_reference: str
    child_type: str

    def to_dict(self) -> dict:
        return {
            "parent_facility_reference": self.parent_facility_reference,
            "child_reference": self.child_reference,
            "child_type": self.child_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1197_counterparty() -> pl.DataFrame:
    """
    Return the P1.197 SL counterparty as a DataFrame.

    CP-SL-PF-01: entity_type="specialised_lending" routes the classifier to the
    slotting approach. Country GB, currency GBP. Non-FSE, not retail.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P1.197 Project Finance SPV (Strong) — CRR-E.CCF1",
        entity_type="specialised_lending",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1197_sl_metadata() -> pl.DataFrame:
    """
    Return the P1.197 specialised-lending metadata row as a DataFrame.

    sl_type="project_finance": canonical VALID_SL_TYPES member (schemas.py:1293).
    slotting_category="strong": CRR Art. 153(5) Table 1 Strong >=2.5yr = 70% RW.
    is_hvcre=False: non-HVCRE project finance.
    """
    row = _SLMetadata(
        counterparty_reference=COUNTERPARTY_REF,
        sl_type="project_finance",
        slotting_category="strong",
        is_hvcre=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(SPECIALISED_LENDING_SCHEMA))


def create_p1197_facility() -> pl.DataFrame:
    """
    Return the P1.197 committed credit facility as a DataFrame.

    SL-FAC-001: GBP 6,000,000 limit (4m drawn + 2m undrawn headroom).
    risk_type="MR": medium-risk commitment; selects Art. 166(8)(d) 75% F-IRB CCF
        (or SA 50% for the pre-fix bug path).
    is_obs_commitment=True: credit line / NIF / RUF bucket (Art. 166(8)(d)).
    maturity_date=2030-12-31: 6yr residual from 2024-12-31 -> is_short_maturity=False.
    """
    row = _Facility(
        facility_reference=FACILITY_REF,
        product_type="PROJECT_FINANCE_FACILITY",
        book_code="SPECIALISED_LENDING",
        counterparty_reference=COUNTERPARTY_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        limit=FACILITY_LIMIT,
        committed=True,
        seniority="senior",
        risk_type=RISK_TYPE,
        is_obs_commitment=IS_OBS_COMMITMENT,
        is_short_term_trade_lc=IS_SHORT_TERM_TRADE_LC,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1197_loan() -> pl.DataFrame:
    """
    Return the P1.197 on-balance-sheet drawn loan as a DataFrame.

    SL-LOAN-001: GBP 4,000,000 drawn under facility SL-FAC-001.
    interest=0: no accrued interest outstanding.
    EAD = on_bs_for_ead = 4,000,000.

    The OBS commitment EAD (nominal_amount=2,000,000, CCF=0.75 post-fix) is
    computed by the hierarchy resolver from the parent facility's undrawn headroom:
        undrawn = FACILITY_LIMIT - DRAWN_AMOUNT = 6,000,000 - 4,000,000 = 2,000,000
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        product_type="PROJECT_FINANCE_LOAN",
        book_code="SPECIALISED_LENDING",
        counterparty_reference=COUNTERPARTY_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        drawn_amount=DRAWN_AMOUNT,
        interest=INTEREST,
        seniority="senior",
        is_payroll_loan=False,
        is_buy_to_let=False,
        is_under_construction=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1197_facility_mapping() -> pl.DataFrame:
    """
    Return the P1.197 facility-mapping row as a DataFrame.

    Maps loan SL-LOAN-001 (drawn_amount=4,000,000) as a child of facility
    SL-FAC-001 (limit=6,000,000). The hierarchy resolver uses this to compute:
        undrawn_amount = 6,000,000 - 4,000,000 = 2,000,000
    which becomes nominal_amount in the CCF exposure view.
    """
    row = _FacilityMapping(
        parent_facility_reference=FACILITY_REF,
        child_reference=LOAN_REF,
        child_type="loan",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1197_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.197 parquet files and return a mapping of name to path.

    Files produced:
        counterparty.parquet       — 1 row  (CP-SL-PF-01, specialised_lending, GB)
        sl_metadata.parquet        — 1 row  (project_finance, strong, is_hvcre=False)
        facility.parquet           — 1 row  (SL-FAC-001, limit=6m, MR, is_obs_commitment=True)
        loan.parquet               — 1 row  (SL-LOAN-001, drawn=4m, interest=0)
        facility_mapping.parquet   — 1 row  (SL-FAC-001 -> SL-LOAN-001)

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1197_counterparty()),
        ("sl_metadata", create_p1197_sl_metadata()),
        ("facility", create_p1197_facility()),
        ("loan", create_p1197_loan()),
        ("facility_mapping", create_p1197_facility_mapping()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.197 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR-E.CCF1 — Slotting OBS EAD must use Art. 166(8)(d) F-IRB CCF 75%")
    print(f"  Counterparty  : {COUNTERPARTY_REF} (specialised_lending, project_finance, Strong)")
    print(f"  Facility      : {FACILITY_REF}, limit=GBP {FACILITY_LIMIT:,.0f}")
    print(
        f"  Loan          : {LOAN_REF}, drawn=GBP {DRAWN_AMOUNT:,.0f}, interest=GBP {INTEREST:,.0f}"
    )
    print(f"  Undrawn (OBS) : GBP {UNDRAWN_AMOUNT:,.0f} (= limit - drawn)")
    print(f"  risk_type     : {RISK_TYPE}, is_obs_commitment={IS_OBS_COMMITMENT}")
    print(f"  maturity_date : {MATURITY_DATE} (>= 2.5yr from reporting_date={REPORTING_DATE})")
    print()
    print("  Expected outputs (post-fix, pre 1.06x IRB scaling):")
    print(f"    ccf            = {EXPECTED_CCF:.2f} (Art. 166(8)(d); buggy: {BUGGY_CCF:.2f} SA)")
    print(f"    on_bs_for_ead  = GBP {EXPECTED_ON_BS_FOR_EAD:,.0f}")
    print(
        f"    ead_from_ccf   = GBP {EXPECTED_EAD_FROM_CCF:,.0f} (buggy: GBP {BUGGY_EAD_FROM_CCF:,.0f})"
    )
    print(
        f"    ead_pre_crm    = GBP {EXPECTED_EAD_PRE_CRM:,.0f} (buggy: GBP {BUGGY_EAD_PRE_CRM:,.0f})"
    )
    print(
        f"    risk_weight    = {EXPECTED_RISK_WEIGHT:.2f} (CRR Art. 153(5) Table 1 PF Strong >=2.5yr)"
    )
    print(
        f"    rwa            = GBP {EXPECTED_RWA_PRE_SCALING:,.0f} (buggy: GBP {BUGGY_RWA_PRE_SCALING:,.0f})"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1197_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
