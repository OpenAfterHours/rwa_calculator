"""
Generate P1.233 fixtures: corporate/PSE ``bond`` collateral routes to ``corp_bond``.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/crm/haircuts.py::_normalize_collateral_type_expr)

Key responsibilities:
- Produce one counterparty row: CP-CORP-233, entity_type="corporate",
  country_code="GB", no external rating (own cqs stays null after ratings
  resolution -> Art. 122 unrated-corporate 100% SA risk weight).
- Produce three drawn term loan rows (LN-A/LN-B/LN-C): GBP 1,000,000 drawn
  each, value_date 2026-01-01, maturity_date 2029-01-01 (residual 3.0y).
- Produce three collateral rows, one per loan, all ``collateral_type="bond"``
  with GBP market values, each testing a different Art. 197 issuer/CQS limb:
    - Coll A (LN-A): issuer_type="corporate", issuer_cqs=3 (Art. 197(1)(d)
      eligible -- CQS 1-3) -> Art. 224 Table 1 corp_bond haircut applies.
    - Coll B (LN-B): issuer_type="corporate", issuer_cqs=5 (Art. 197(1)(d)
      INELIGIBLE -- CQS 4-6/unrated corporate debt securities are excluded)
      -> the ineligible-bond zeroing branch fires, collateral contributes
      no CRM benefit.
    - Coll C (LN-C): issuer_type="pse", issuer_cqs=2 (Art. 197(1)(c)
      eligible -- institution/PSE debt securities CQS 1-3) -> same Table 1
      corp_bond haircut band as Coll A (Table 1 groups CQS 2-3 together).
- No facility, guarantee, or provision rows -- clean single-factor SA CRM
  boundary test isolating the collateral-type normalisation routing bug.
- Framework: CalculationConfig.crr() (reporting_date 2026-01-01).

Scenario rationale:
    Today ``_normalize_collateral_type_expr`` sends any non-sovereign
    ``collateral_type="bond"`` row to ``.otherwise("other_physical")``,
    which has two compounding effects:
      (a) the Art. 197 CQS-eligibility gate (issuer-type + CQS threshold)
          never fires for bond collateral, so an *ineligible* CQS 5
          corporate bond (Coll B) is incorrectly treated as eligible and
          given CRM benefit it should not receive (Art. 197(1)(d) excludes
          CQS 4-6/unrated corporate debt securities entirely).
      (b) an *eligible* bond (Coll A, Coll C) takes the flat Art. 230(2)
          "other" 40% haircut instead of the graduated Art. 224 Table 1
          corp-bond haircut (6% at CQS 2-3, 1-5y residual), understating
          the CRM benefit and overstating RWA.
    The fix routes ``collateral_type="bond"`` with
    ``issuer_type in {corporate, pse, institution}`` to the ``corp_bond``
    branch ahead of the ``other_physical`` fallback.

Hand-calculation (CRR, CalculationConfig.crr(), identical for all three
loans up to the collateral haircut / eligibility step):
    E  = drawn_amount = 1,000,000 (on-B/S EAD, CCF=1.0)
    HE = 0 (Art. 223(5); no exposure volatility haircut asserted here)
    HFX = 0 (collateral currency GBP == exposure currency GBP)
    Liquidation-period scaling: sqrt(10/10) = 1.0 (base 10-day period,
        Art. 226(2); no scaling adjustment)
    No maturity mismatch (Art. 237/238): collateral maturity 2030-01-01 is
        after loan maturity 2029-01-01.
    SA EAD after CRM = E* x CCF (CCF=1.0 for a drawn on-B/S exposure)
    RW = 1.00 (unrated corporate, CRR Art. 122)
    RWA = EAD x RW; K = RWA x 8%

    Loan A (Coll A -- eligible corporate bond, Art. 197(1)(d), CQS 3):
        normalize bond + issuer_type="corporate" -> corp_bond (post-fix;
            today misroutes to other_physical)
        residual_maturity_years=4.0 -> CRR 1-5y band
        base haircut: corp_bond, CQS 3, 1-5y = 0.06 (Art. 224 Table 1)
        value_after_haircut = 500,000 x (1 - 0.06) = 470,000
        E* = max(0, 1,000,000 - 470,000) = 530,000
        EAD = RWA = 530,000; K = 42,400
        (pre-fix bug: other_physical 40% -> 500,000 x 0.60 = 300,000 ->
         E* = 700,000 -> RWA = 700,000)

    Loan B (Coll B -- ineligible corporate bond, Art. 197(1)(d) gate,
             CQS 5):
        normalize bond + issuer_type="corporate" -> corp_bond (post-fix)
        Art. 197(1)(d) gate: CQS 5 >= 4 -> corporate debt security
            INELIGIBLE -> ineligible-bond zeroing fires:
            value_after_haircut = 0, is_eligible_financial_collateral
            overridden to False, collateral_adjusted_value = 0
        E* = max(0, 1,000,000 - 0) = 1,000,000
        EAD = RWA = 1,000,000; K = 80,000
        (pre-fix bug: routed to other_physical with
         is_eligible_financial_collateral left True (gate never fires)
         -> 800,000 x (1 - 0.60) = 320,000 ->
         wait: other_physical 40% haircut -> value_after_haircut =
         800,000 x 0.60 = 480,000 -> E* = 520,000 -> RWA = 520,000;
         a GBP 480,000 capital UNDERSTATEMENT relative to the correct
         RWA of 1,000,000)

    Loan C (Coll C -- eligible PSE bond, Art. 197(1)(c), CQS 2):
        normalize bond + issuer_type="pse" -> corp_bond (post-fix)
        Art. 197(1)(c) gate: CQS 2 <= 3 -> institution/PSE debt security
            ELIGIBLE
        base haircut: corp_bond, CQS 2, 1-5y = 0.06 (Table 1 groups
            CQS 2-3 together)
        value_after_haircut = 500,000 x (1 - 0.06) = 470,000
        E* = max(0, 1,000,000 - 470,000) = 530,000
        EAD = RWA = 530,000; K = 42,400
        (pre-fix bug: other_physical 40% -> 500,000 x 0.60 = 300,000 ->
         E* = 700,000 -> RWA = 700,000)

Deviation from the scenario proposal:
    The proposal text specifies ``beneficiary_type="exposure"`` for all
    three collateral rows. ``"exposure"`` is not a member of
    ``VALID_BENEFICIARY_TYPES`` (schemas.py) -- the valid set is
    ``{"counterparty", "loan", "facility", "contingent", "guarantee"}``.
    Since each collateral row protects a specific LOAN_SCHEMA row (not a
    facility or the counterparty as a whole), this builder uses
    ``beneficiary_type="loan"`` with ``beneficiary_reference`` set to the
    matching loan_reference (LN-A/LN-B/LN-C), which is the schema-correct
    encoding of the proposal's intent and matches the established pattern
    in tests/fixtures/p1_96/p1_96.py and tests/fixtures/collateral/collateral.py.

References:
    - CRR Art. 197(1)(c): institution/PSE debt securities eligible at
      CQS 1-3.
    - CRR Art. 197(1)(d): corporate debt securities eligible at CQS 1-3;
      CQS 4-6/unrated INELIGIBLE.
    - CRR Art. 224 Table 1: corp/institution bond haircuts by CQS x
      residual maturity (CQS 2-3, 1-5y = 6%).
    - CRR Art. 223(5) / Art. 228(1): FCCM E* reduction, SA EAD after CRM.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - src/rwa_calc/rulebook/packs/crr.py::collateral_haircuts (Art. 224;
      corp_bond CQS 2-3, 1-5y = 0.06).
    - Fix site: engine/crm/haircuts.py::_normalize_collateral_type_expr
      (bond + issuer_type routing), eligibility gate ~L570-578,
      ineligible-bond zeroing + is_eligible override ~L268-284.
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5
      WS3 (P1.233 L182-186, P1.236 L197-201).

Usage:
    uv run python tests/fixtures/p1_233/p1_233.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, LOAN_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP-CORP-233"

LOAN_REF_A = "LN-A"
LOAN_REF_B = "LN-B"
LOAN_REF_C = "LN-C"

COLLATERAL_REF_A = "COLL-P233-A"
COLLATERAL_REF_B = "COLL-P233-B"
COLLATERAL_REF_C = "COLL-P233-C"

REPORTING_DATE = date(2026, 1, 1)
VALUE_DATE = date(2026, 1, 1)
LOAN_MATURITY_DATE = date(2029, 1, 1)  # residual 3.0y from reporting date
COLLATERAL_MATURITY_DATE = date(2030, 1, 1)  # residual 4.0y from reporting date

DRAWN_AMOUNT: float = 1_000_000.0  # GBP, each loan

# Coll A / Coll C: eligible bonds -> Art. 224 Table 1 corp_bond, CQS 2-3,
# 1-5y band = 6% base 10-day haircut. liquidation_period_days=10 -> no
# scaling adjustment (sqrt(10/10) = 1.0).
CORP_BOND_HAIRCUT_CQS2_3_1_5Y: float = 0.06

MARKET_VALUE_A: float = 500_000.0
MARKET_VALUE_B: float = 800_000.0
MARKET_VALUE_C: float = 500_000.0

LIQUIDATION_PERIOD_DAYS: int = 10
RESIDUAL_MATURITY_YEARS: float = 4.0

# ---------------------------------------------------------------------------
# Expected post-fix outputs (CRR, CalculationConfig.crr())
# ---------------------------------------------------------------------------

# Loan A: eligible CQS-3 corporate bond.
VALUE_AFTER_HAIRCUT_A: float = MARKET_VALUE_A * (1.0 - CORP_BOND_HAIRCUT_CQS2_3_1_5Y)  # 470,000
EAD_A: float = max(0.0, DRAWN_AMOUNT - VALUE_AFTER_HAIRCUT_A)  # 530,000
RWA_A: float = EAD_A  # RW = 1.00
CAPITAL_A: float = RWA_A * 0.08  # 42,400

# Loan B: ineligible CQS-5 corporate bond -- zeroed by the Art. 197(1)(d) gate.
VALUE_AFTER_HAIRCUT_B: float = 0.0
EAD_B: float = DRAWN_AMOUNT  # 1,000,000 (no CRM benefit)
RWA_B: float = EAD_B
CAPITAL_B: float = RWA_B * 0.08  # 80,000

# Loan C: eligible CQS-2 PSE bond (same Table 1 band as CQS 2-3).
VALUE_AFTER_HAIRCUT_C: float = MARKET_VALUE_C * (1.0 - CORP_BOND_HAIRCUT_CQS2_3_1_5Y)  # 470,000
EAD_C: float = max(0.0, DRAWN_AMOUNT - VALUE_AFTER_HAIRCUT_C)  # 530,000
RWA_C: float = EAD_C
CAPITAL_C: float = RWA_C * 0.08  # 42,400

# Pre-fix illustrative figures (other_physical 40% flat haircut, no Art. 197
# eligibility gate) -- for acceptance-test regression documentation only.
OTHER_PHYSICAL_HAIRCUT: float = 0.40
PRE_FIX_EAD_A: float = max(0.0, DRAWN_AMOUNT - MARKET_VALUE_A * (1.0 - OTHER_PHYSICAL_HAIRCUT))
PRE_FIX_EAD_B: float = max(0.0, DRAWN_AMOUNT - MARKET_VALUE_B * (1.0 - OTHER_PHYSICAL_HAIRCUT))
PRE_FIX_EAD_C: float = max(0.0, DRAWN_AMOUNT - MARKET_VALUE_C * (1.0 - OTHER_PHYSICAL_HAIRCUT))


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.233 corporate counterparty: unrated, GB, not defaulted."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.233 drawn term loan: GBP 1,000,000, value_date 2026-01-01, maturity 2029-01-01."""

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str

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
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P1.233 bond collateral row.

    ``collateral_type="bond"`` with ``issuer_type`` in {corporate, pse} is
    the routing limb this scenario exercises: today it falls through to
    ``other_physical`` (flat 40% haircut, no Art. 197 CQS-eligibility gate);
    post-fix it must route to ``corp_bond`` (Art. 224 Table 1 graduated
    haircut + the Art. 197(1)(c)/(d) CQS-eligibility gate).

    ``beneficiary_type="loan"`` / ``beneficiary_reference=<loan_reference>``
    anchors each collateral row to exactly one of LN-A/LN-B/LN-C (schema
    deviation from the proposal's "exposure" wording -- see module
    docstring "Deviation from the scenario proposal").
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    maturity_date: date
    market_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_cqs: int
    issuer_type: str
    residual_maturity_years: float
    is_eligible_financial_collateral: bool
    liquidation_period_days: int
    valuation_date: date
    valuation_type: str

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "market_value": self.market_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "issuer_cqs": self.issuer_cqs,
            "issuer_type": self.issuer_type,
            "residual_maturity_years": self.residual_maturity_years,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "liquidation_period_days": self.liquidation_period_days,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1233_counterparty() -> pl.DataFrame:
    """Return the P1.233 counterparty as a single-row DataFrame."""
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Bond Collateral Routing Corporate Ltd",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_financial_sector_entity=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1233_loans() -> pl.DataFrame:
    """Return the three P1.233 drawn term loans (LN-A/LN-B/LN-C) as a DataFrame."""
    rows = [
        _Loan(
            loan_reference=loan_ref,
            counterparty_reference=COUNTERPARTY_REF,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=LOAN_MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        )
        for loan_ref in (LOAN_REF_A, LOAN_REF_B, LOAN_REF_C)
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1233_collateral() -> pl.DataFrame:
    """
    Return the three P1.233 collateral rows (Coll A/B/C) as a DataFrame.

    Coll A (LN-A): corporate issuer, CQS 3 -- Art. 197(1)(d) eligible.
    Coll B (LN-B): corporate issuer, CQS 5 -- Art. 197(1)(d) ineligible.
    Coll C (LN-C): PSE issuer, CQS 2 -- Art. 197(1)(c) eligible.
    """
    rows = [
        _Collateral(
            collateral_reference=COLLATERAL_REF_A,
            collateral_type="bond",
            currency="GBP",
            maturity_date=COLLATERAL_MATURITY_DATE,
            market_value=MARKET_VALUE_A,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_A,
            issuer_cqs=3,
            issuer_type="corporate",
            residual_maturity_years=RESIDUAL_MATURITY_YEARS,
            is_eligible_financial_collateral=True,
            liquidation_period_days=LIQUIDATION_PERIOD_DAYS,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
        ),
        _Collateral(
            collateral_reference=COLLATERAL_REF_B,
            collateral_type="bond",
            currency="GBP",
            maturity_date=COLLATERAL_MATURITY_DATE,
            market_value=MARKET_VALUE_B,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_B,
            issuer_cqs=5,
            issuer_type="corporate",
            residual_maturity_years=RESIDUAL_MATURITY_YEARS,
            is_eligible_financial_collateral=True,
            liquidation_period_days=LIQUIDATION_PERIOD_DAYS,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
        ),
        _Collateral(
            collateral_reference=COLLATERAL_REF_C,
            collateral_type="bond",
            currency="GBP",
            maturity_date=COLLATERAL_MATURITY_DATE,
            market_value=MARKET_VALUE_C,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_C,
            issuer_cqs=2,
            issuer_type="pse",
            residual_maturity_years=RESIDUAL_MATURITY_YEARS,
            is_eligible_financial_collateral=True,
            liquidation_period_days=LIQUIDATION_PERIOD_DAYS,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1233_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.233 parquet files and return a mapping of name -> path.

    Three parquet files are written:
    - counterparty.parquet  (1 row: CP-CORP-233)
    - loan.parquet          (3 rows: LN-A, LN-B, LN-C)
    - collateral.parquet    (3 rows: COLL-P233-A/B/C)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1233_counterparty()),
        ("loan", create_p1233_loans()),
        ("collateral", create_p1233_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.233 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR corporate/PSE 'bond' collateral routes to corp_bond")
    print("          (Art. 197(1)(c)/(d) eligibility gate + Art. 224 Table 1 haircut)")
    print("")
    print("  Loan  Issuer     CQS  Eligible  Haircut  ValueAfterHC   EAD/RWA      K(8%)")
    print(
        f"  A     corporate  3    True      "
        f"{CORP_BOND_HAIRCUT_CQS2_3_1_5Y:.0%}      {VALUE_AFTER_HAIRCUT_A:>10,.0f}   "
        f"{RWA_A:>10,.0f}   {CAPITAL_A:>9,.0f}"
    )
    print(
        f"  B     corporate  5    False     "
        f"n/a      {VALUE_AFTER_HAIRCUT_B:>10,.0f}   {RWA_B:>10,.0f}   {CAPITAL_B:>9,.0f}"
    )
    print(
        f"  C     pse        2    True      "
        f"{CORP_BOND_HAIRCUT_CQS2_3_1_5Y:.0%}      {VALUE_AFTER_HAIRCUT_C:>10,.0f}   "
        f"{RWA_C:>10,.0f}   {CAPITAL_C:>9,.0f}"
    )
    print("")
    print("  Pre-fix (other_physical 40%, no eligibility gate) illustrative RWA:")
    print(f"    A: {PRE_FIX_EAD_A:,.0f}   B: {PRE_FIX_EAD_B:,.0f}   C: {PRE_FIX_EAD_C:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1233_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
