"""
Generate P5.15 fixtures: Art. 123A(1)(b)(ii) 0.2% retail portfolio granularity sub-condition.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/classifier.py
    _build_qualifies_as_retail_expr)

Key responsibilities:
- Produce a Basel-3.1 retail portfolio of natural-person obligors that makes the
  0.2% granularity limb of Art. 123A(1)(b)(ii) fire independently of the GBP 880k
  threshold limb.
- Counterparties: 10 control obligors (GBP 1,000 each) + 1 breaching obligor
  (RETAIL-BREACH, GBP 2,000) + 1 explicit pass obligor (RETAIL-CONTROL-PASS, GBP 1,000).
  Total = 12 obligors; portfolio total = 13,000 GBP; 0.2% limit = 26.00 GBP.
  The breach (2,000 > 26) fails; the pass (1,000 < 2,000, ratio 0.07692 > 0.002)
  would ALSO fail at this scale.

  REVISED DESIGN — see note below: to hit the proposal's numeric targets exactly
  (total 503,000; 0.2% = 1,006; breach 2,000 > 1,006; pass 1,000 < 1,006)
  the fixture uses:
    - 500 control obligors × GBP 1,000 = GBP 500,000
    - RETAIL-BREACH: GBP 2,000
    - RETAIL-CONTROL-PASS: GBP 1,000
    - portfolio_total = 503,000
    - granularity_limit = 0.002 × 503,000 = 1,006.00
    - breach ratio  = 2,000 / 503,000 = 0.003976...  > 0.002  → FAIL
    - pass ratio    = 1,000 / 503,000 = 0.001988...  < 0.002  → PASS

  To keep the fixture file small while preserving the portfolio total, the 500 control
  obligors are represented as individual rows in a single parquet. The loan file
  contains one loan per obligor (all personal_loan, drawn = counterparty's aggregate).

  All obligors:
    - cp_entity_type="individual" (natural person — Art. 123A(1)(b) path)
    - cp_is_managed_as_retail=True (pool-management limb already passes)
    - sme_size_metric_gbp=null / sme_size_source=null (no SME size data → non-SME path,
      so Art. 123A(1)(a) SME auto-qualify branch does NOT fire)
    - All exposures are well below GBP 880k (max = GBP 2,000) so the threshold limb
      alone cannot trip — any failure is attributable solely to the granularity limb.

Worked numbers (Basel 3.1, CalculationConfig.basel_3_1()):

    portfolio_total = 500 × 1,000 + 2,000 + 1,000 = 503,000 GBP

    granularity_limit = 0.002 × 503,000 = 1,006.00 GBP

    RETAIL-BREACH:
        ratio = 2,000 / 503,000 = 0.003976...  >  0.002  -> qualifies_as_retail = False
        re-routed to CORPORATE (Art. 122 unrated): RW = 100%, RWA = 2,000

    RETAIL-CONTROL-PASS:
        ratio = 1,000 / 503,000 = 0.001988...  <  0.002  -> qualifies_as_retail = True
        stays RETAIL_OTHER: RW = 75%, RWA = 750

Re-route consequence (risk-weight delta):
    RETAIL-BREACH:
        RWA as retail  (control comparison): 2,000 × 0.75 = 1,500
        RWA as corporate (actual, post re-route): 2,000 × 1.00 = 2,000
    RETAIL-CONTROL-PASS:
        RWA as retail: 1,000 × 0.75 = 750

References:
    - PRA PS1/26 Art. 123A(1)(b)(ii): retail granularity sub-condition (0.2%)
    - PRA PS1/26 Art. 123A(1)(b)(iii): pool-management attestation (cp_is_managed_as_retail)
    - PRA PS1/26 Art. 122 Table 6: unrated corporate SA RW = 100%
    - PRA PS1/26 Art. 123(3)(b): regulatory retail SA RW = 75%
    - BCBS CRE20.66: granularity criterion source
    - src/rwa_calc/engine/classifier.py L2044-2098: _build_qualifies_as_retail_expr
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_RETAIL_GRANULARITY_LIMIT = Decimal("0.002")

Usage:
    PYTHONPATH=<worktree>/src python tests/fixtures/p5_15/p5_15.py
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

# ---------------------------------------------------------------------------
# Scenario identity constants
# ---------------------------------------------------------------------------

#: Obligor reference for the granularity-breaching exposure
CP_BREACH: str = "RETAIL-BREACH"

#: Obligor reference for the explicit granularity-passing exposure
CP_CONTROL_PASS: str = "RETAIL-CONTROL-PASS"

#: Prefix for the 500 background control obligors: RETAIL-CTRL-001 … RETAIL-CTRL-500
CP_CTRL_PREFIX: str = "RETAIL-CTRL-"

#: Loan reference for the breaching obligor
LOAN_BREACH: str = "LOAN-RETAIL-BREACH"

#: Loan reference for the explicit pass obligor
LOAN_CONTROL_PASS: str = "LOAN-RETAIL-CTRL-PASS"

#: Number of background control obligors
NUM_CTRL_OBLIGORS: int = 500

# ---------------------------------------------------------------------------
# Scenario monetary constants (GBP)
# ---------------------------------------------------------------------------

#: Drawn balance for each control obligor (each one also = lending_group_adjusted_exposure)
CTRL_DRAWN: float = 1_000.0

#: Drawn balance for the breaching obligor
BREACH_DRAWN: float = 2_000.0

#: Drawn balance for the explicit pass obligor
PASS_DRAWN: float = 1_000.0

# ---------------------------------------------------------------------------
# Portfolio arithmetic (single source of truth for test-writer assertions)
# ---------------------------------------------------------------------------

#: Total portfolio = 500 × 1,000 + 2,000 + 1,000
PORTFOLIO_TOTAL: float = NUM_CTRL_OBLIGORS * CTRL_DRAWN + BREACH_DRAWN + PASS_DRAWN  # 503,000

#: 0.2% granularity limit
GRANULARITY_LIMIT: float = 0.002 * PORTFOLIO_TOTAL  # 1,006.00

#: Breach obligor ratio (>0.002 → FAIL)
BREACH_RATIO: float = BREACH_DRAWN / PORTFOLIO_TOTAL  # ≈ 0.003976

#: Pass obligor ratio (<0.002 → PASS)
PASS_RATIO: float = PASS_DRAWN / PORTFOLIO_TOTAL  # ≈ 0.001988

#: Control obligor ratio (same as pass, all pass)
CTRL_RATIO: float = CTRL_DRAWN / PORTFOLIO_TOTAL  # ≈ 0.001988

# ---------------------------------------------------------------------------
# Expected output scalars (single source of truth for test-writer assertions)
# ---------------------------------------------------------------------------

#: Basel 3.1 unrated corporate SA RW (Art. 122 Table 6) — applied after re-route
EXPECTED_RW_CORPORATE: float = 1.00

#: Basel 3.1 regulatory retail SA RW (Art. 123(3)(b))
EXPECTED_RW_RETAIL: float = 0.75

#: RWA for the breaching obligor after re-route to CORPORATE
EXPECTED_RWA_BREACH: float = BREACH_DRAWN * EXPECTED_RW_CORPORATE  # 2,000.00

#: RWA for the pass obligor (stays RETAIL_OTHER)
EXPECTED_RWA_PASS: float = PASS_DRAWN * EXPECTED_RW_RETAIL  # 750.00

#: Dates
VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2032, 1, 4)


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P5.15 retail counterparty (natural person, Basel 3.1, Art. 123A(1)(b) path).

    entity_type="individual": routes through the natural-person (b) branch of
    Art. 123A — NOT the SME auto-qualify (a) branch.
    is_managed_as_retail=True: pool-management attestation satisfies Art.
    123A(1)(b)(iii) so only the granularity limb can discriminate.
    annual_revenue=None, total_assets=None: natural persons have no revenue;
    null SME size metrics ensure _is_sme_by_size_expr evaluates False and
    the SME path is NOT taken.
    default_status=False: performing exposure.
    apply_fi_scalar=False: no FIRB 1.25x correlation multiplier.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_natural_person: bool

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
        }


@dataclass(frozen=True)
class _Loan:
    """
    P5.15 drawn personal loan.

    product_type="personal_loan": unsecured personal lending — EAD = drawn_amount.
    seniority="senior": standard senior claim.
    interest=0.0: no accrued interest — EAD = drawn_amount exactly.
    is_payroll_loan=False: not relevant to this scenario.
    is_buy_to_let=False: not a BTL mortgage.
    is_under_construction=False: no property under construction.
    """

    loan_reference: str
    product_type: str
    counterparty_reference: str
    currency: str
    drawn_amount: float
    interest: float
    value_date: date
    maturity_date: date
    seniority: str
    is_payroll_loan: bool
    is_buy_to_let: bool
    is_under_construction: bool

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "seniority": self.seniority,
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


# ---------------------------------------------------------------------------
# Private helper — build one counterparty row
# ---------------------------------------------------------------------------


def _make_cp(ref: str, name: str) -> _Counterparty:
    """Return a natural-person retail counterparty row for P5.15."""
    return _Counterparty(
        counterparty_reference=ref,
        counterparty_name=name,
        entity_type="individual",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=True,
        is_natural_person=True,
    )


def _make_loan(ref: str, cp_ref: str, drawn: float) -> _Loan:
    """Return a drawn personal loan row for P5.15."""
    return _Loan(
        loan_reference=ref,
        product_type="personal_loan",
        counterparty_reference=cp_ref,
        currency="GBP",
        drawn_amount=drawn,
        interest=0.0,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        seniority="senior",
        is_payroll_loan=False,
        is_buy_to_let=False,
        is_under_construction=False,
    )


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p515_counterparties() -> pl.DataFrame:
    """
    Return all P5.15 counterparties as a DataFrame (502 rows).

    Composition:
      - 500 control obligors: RETAIL-CTRL-001 … RETAIL-CTRL-500, each GBP 1,000
        (these form the background portfolio mass that sets the 0.2% limit)
      - RETAIL-BREACH: the obligor whose single exposure (GBP 2,000) exceeds
        the 0.2% granularity limit (limit = 1,006 GBP at this portfolio scale)
      - RETAIL-CONTROL-PASS: explicit assertion target, GBP 1,000, passes the
        granularity limb (1,000 < 1,006)

    All obligors are natural persons (entity_type="individual"), GB-domiciled,
    is_managed_as_retail=True, annual_revenue=None (null SME size), so:
      - Art. 123A(1)(a) SME auto-qualify branch does NOT fire (no SME size)
      - Art. 123A(1)(b)(iii) pool-management limb passes (is_managed_as_retail=True)
      - Only Art. 123A(1)(b)(ii) granularity discriminates
    """
    rows: list[dict] = []

    # 500 background control obligors
    for i in range(1, NUM_CTRL_OBLIGORS + 1):
        cp_ref = f"{CP_CTRL_PREFIX}{i:03d}"
        cp = _make_cp(cp_ref, f"Control Retail Obligor {i:03d}")
        rows.append(cp.to_dict())

    # Breaching obligor
    rows.append(_make_cp(CP_BREACH, "Granularity Breach Obligor").to_dict())

    # Explicit pass obligor
    rows.append(_make_cp(CP_CONTROL_PASS, "Granularity Control Pass Obligor").to_dict())

    return pl.DataFrame(rows, schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p515_loans() -> pl.DataFrame:
    """
    Return all P5.15 loan rows as a DataFrame (502 rows).

    One personal loan per counterparty.  Drawn amounts:
      - Control obligors (RETAIL-CTRL-001…500): GBP 1,000 each
      - RETAIL-BREACH:        GBP 2,000  (exceeds 0.2% limit of 1,006)
      - RETAIL-CONTROL-PASS:  GBP 1,000  (below 0.2% limit of 1,006)

    EAD = drawn_amount (interest = 0, no undrawn commitments).
    """
    rows: list[dict] = []

    # 500 background control loans
    for i in range(1, NUM_CTRL_OBLIGORS + 1):
        cp_ref = f"{CP_CTRL_PREFIX}{i:03d}"
        loan_ref = f"LOAN-{cp_ref}"
        rows.append(_make_loan(loan_ref, cp_ref, CTRL_DRAWN).to_dict())

    # Breaching loan
    rows.append(_make_loan(LOAN_BREACH, CP_BREACH, BREACH_DRAWN).to_dict())

    # Pass loan
    rows.append(_make_loan(LOAN_CONTROL_PASS, CP_CONTROL_PASS, PASS_DRAWN).to_dict())

    return pl.DataFrame(rows, schema=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Empty helpers (no CRM, collateral, guarantees, etc.)
# ---------------------------------------------------------------------------


def create_p515_empty_facilities() -> pl.DataFrame:
    """Return an empty facilities DataFrame (no facilities in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_SCHEMA))


def create_p515_empty_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame (no contingents in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p515_empty_collateral() -> pl.DataFrame:
    """Return an empty collateral DataFrame (no CRM in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p515_empty_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame (no guarantees in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p515_empty_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame (no provisions in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p515_empty_ratings() -> pl.DataFrame:
    """Return an empty ratings DataFrame (no external ratings in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


def create_p515_empty_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory (matches test-writer expected API)
# ---------------------------------------------------------------------------


def build_p5_15_bundle(*, fixtures_dir: Path) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P5.15 scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module.  The ``fixtures_dir`` argument is accepted for
    interface symmetry with other bundle builders (it is not used here).

    Returns:
        RawDataBundle with:
        - 502 counterparties (500 control + RETAIL-BREACH + RETAIL-CONTROL-PASS)
        - 502 loans (one per counterparty, personal loans, GBP)
        - All other LazyFrames: empty, schema-conformant

    Args:
        fixtures_dir: Path to the fixtures directory (unused; accepted for
            interface compatibility with other bundle builders).
    """
    return RawDataBundle(
        facilities=create_p515_empty_facilities().lazy(),
        loans=create_p515_loans().lazy(),
        counterparties=create_p515_counterparties().lazy(),
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
        contingents=create_p515_empty_contingents().lazy(),
        collateral=create_p515_empty_collateral().lazy(),
        guarantees=create_p515_empty_guarantees().lazy(),
        provisions=create_p515_empty_provisions().lazy(),
        ratings=create_p515_empty_ratings().lazy(),
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p515_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P5.15 parquet files and return a mapping of name to path.

    Two parquet files are written:
    - counterparties.parquet  (502 rows: 500 control + RETAIL-BREACH + RETAIL-CONTROL-PASS)
    - loans.parquet           (502 rows: one loan per counterparty)

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
        ("counterparties", create_p515_counterparties()),
        ("loans", create_p515_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P5.15 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<25} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: Art. 123A(1)(b)(ii) — 0.2% retail portfolio granularity sub-condition")
    print()
    print(f"  Portfolio total:         {PORTFOLIO_TOTAL:>12,.0f} GBP")
    print(f"  0.2% granularity limit:  {GRANULARITY_LIMIT:>12,.2f} GBP")
    print()
    print(f"  RETAIL-BREACH        drawn={BREACH_DRAWN:>8,.0f}  ratio={BREACH_RATIO:.6f}  > 0.002  -> FAIL")
    print(f"  RETAIL-CONTROL-PASS  drawn={PASS_DRAWN:>8,.0f}  ratio={PASS_RATIO:.6f}  < 0.002  -> PASS")
    print(f"  Control obligors (×{NUM_CTRL_OBLIGORS})  drawn={CTRL_DRAWN:>8,.0f}  ratio={CTRL_RATIO:.6f}  < 0.002  -> PASS")
    print()
    print("  Expected classifier output:")
    print(f"    RETAIL-BREACH:       qualifies_as_retail=False  -> CORPORATE  RW={EXPECTED_RW_CORPORATE:.0%}  RWA={EXPECTED_RWA_BREACH:,.0f}")
    print(f"    RETAIL-CONTROL-PASS: qualifies_as_retail=True   -> RETAIL_OTHER RW={EXPECTED_RW_RETAIL:.0%}  RWA={EXPECTED_RWA_PASS:,.0f}")
    print()
    # Verify no drawn amounts exceed GBP 880k (threshold limb must NOT fire)
    loans_df = pl.read_parquet(saved["loans"])
    max_drawn = loans_df["drawn_amount"].max()
    print(f"  Max drawn across all loans: {max_drawn:,.0f} GBP (must be << 880,000 — threshold limb must not fire)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p515_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
