"""
Generate P1.316 fixtures: CRR Art. 121(1) Table 5 sovereign-derived RW for
unrated institutions.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/sa/risk_weights.py: ``_crr_append_institution_maturity_branches``
    — the Art. 121(1) Table 5 branch behind the Art. 121(3) <=3m branch;
    engine/sa/sovereign_derived.py: ``sovereign_derived_rw_expr`` /
    ``crr_art_121_4_trade_finance_expr``)

Why this fixture had to be built at all
---------------------------------------
No fixture in the estate exercised Table 5. All 16 registered reporting runs
carry zero unrated-institution rows with a non-null ``sovereign_cqs``, and a
scan of all 494 fixture parquets found exactly one candidate — whose loan is
~85 days, so Art. 121(3) short-circuits it at 20% before Table 5 is reached.
So the defect and its repair were BOTH invisible to the estate: no golden, no
register entry and no baseline moved either way. See LESSONS B5.

Two-leg shape (LESSONS B5)
--------------------------
A single moving row cannot distinguish "the fix works" from "the branch is now
unconditional", so every leg that MOVES is paired with one that SURVIVES:

    leg           sov_cqs  orig / residual  trade LC  pre-fix  post-fix  role
    LN-SOV1       1        5y / 4.9y        no         100%      20%    MOVES (largest, reducing)
    LN-SOV4       4        5y / 4.9y        no         100%     100%    SURVIVES (mis-keyed table)
    LN-SOV6       6        5y / 4.9y        no         100%     150%    MOVES (capital shortfall)
    LN-SOVNULL    null     5y / 4.9y        no         100%     100%    SURVIVES (Art. 121(2))
    LN-SHORT      6        73d / 43d        no          20%      20%    SURVIVES (Art. 121(3))
    LN-TRADE5Y    1        5y / 4.9y        YES        100%      20%    MOVES (outside 121(4))
    LN-TRADE5Y6   6        5y / 4.9y        YES        100%     150%    MOVES (outside 121(4))
    LN-TRADE1Y    1        1.08y / 1.0y     YES        100%     100%    SURVIVES (121(4) boundary)
    LN-TRADESEAS  1        2.5y / 0.5y      YES        100%     100%    SURVIVES (121(4), residual)
    LN-RATED      6 (own 2) 5y / 4.9y       no          50%      50%    SURVIVES (Art. 120 Table 3)

"pre-fix" is the engine before P1.316 (a flat 100% for every unrated
institution). The trade legs were also 100% at the intermediate state, when
Art. 121(4) was held out at every maturity; only LN-TRADE5Y and LN-TRADE5Y6
moved in the second change, and in opposite directions.

``LN-SOVNULL`` is the discriminator that no other leg supplies: an
implementation that fires the sovereign-derived lookup unconditionally, instead
of falling through to the Art. 121(2) 100% residual, moves this row and nothing
else. ``LN-SOV4`` is the mirror discriminator for a mis-keyed table — Table 5's
CQS 4 cell is 100%, the same as the pre-fix flat fallback, so it can only move
if the lookup reads the wrong row.

Art. 121(4) scope — residual maturity, up to and including one year
-------------------------------------------------------------------
Art. 121(4) reaches only "trade finance exposures referred to in point (b) of
the second subparagraph of Article 162(3)", and point (b) is "self-liquidating
short-term trade finance transactions connected to the exchange of goods or
services with a residual maturity of up to one year" (legislation.gov.uk, CRR
as at 2026-01-01). A trade LC with more than a year to run is outside
Art. 121(4) and Table 5 governs it like any other unrated-institution exposure.
The engine implements neither Art. 121(4) rate (P1.326 / P1.338 / P7.8), so the
rows INSIDE the scope stay on the 100% interim; the four trade legs pin both
sides of the scope:

- ``LN-TRADE5Y`` / ``LN-TRADE5Y6`` are outside it and take Table 5. The first
  fix held every flagged row out at 100% on the belief that the 50% limb had no
  maturity condition. It does — through the Art. 162(3)(b) cross-reference — so
  both moved: CQS 1 from 100% to 20%, and CQS 6 from 100% to 150%. The old
  100% at CQS 6 was a 50pp understatement under every reading of Art. 121(4),
  because no reading of paragraph (4) reaches a row outside point (b).
- ``LN-TRADE1Y`` sits exactly on the bound (residual 1.0y by the
  ``exact_fractional_years_expr`` day count) and stays in scope: "up to one
  year" is inclusive.
- ``LN-TRADESEAS`` is the discriminator against keying on ORIGINAL maturity
  (the shape of the sibling PS1/26 Art. 121(6)(b) floor exemption, a different
  rule): 2.5 years original, half a year residual. An original-maturity gate
  leaks it into Table 5 at 20%.

Every pipeline exposure row carries ``residual_maturity_years`` as NULL — it is
a collateral-schema column — so the residual is derived from ``maturity_date``
and the reporting date. A gate on the column alone would hold every pipeline
row in scope and these legs could not move.

Fixture shape is load-bearing
-----------------------------
Every counterparty is GB-incorporated with ``local_currency="GBP"`` and every
loan is in GBP, so ``cp_local_currency == currency`` and the Art. 121(6) FX
sovereign floor (``_apply_sovereign_floor_for_institutions``) is OFF for a
STRUCTURAL reason rather than an incidental one. That matters twice over:

- With the floor armed, a CQS-6 row already returns 150% pre-fix (measured), so
  LN-SOV6 would be green before the fix and prove nothing.
- The floor's FX fallback for a counterparty with a null ``local_currency`` is a
  Kleene null for non-UK/non-EU countries, i.e. currently dead. Relying on that
  deadness to keep the floor off would make these legs silently vacuous the day
  that separate defect is fixed. Matching the currencies does not.

For the same reason the acceptance bundle must be built with ``fx_rates=None``:
a rate row rewrites ``currency`` in the converter and silently re-arms the floor.

Each leg gets its OWN counterparty, because ``sovereign_cqs`` is a
counterparty column. (When this fixture was written a counterparty-level
broadcast of ``is_short_term_trade_lc`` also made sharing a counterparty
unsafe; review TR-01 removed it — a loan now inherits the flag only from its
own parent facility via ``facility_mappings``.)

Hand-calculation (CRR, EAD = drawn_amount = GBP 1,000,000 per leg)
-----------------------------------------------------------------
Art. 121(1) Table 5 (crr.pdf PAGE_INDEX 119, verbatim):

    CQS of central government   1     2     3     4     5     6
    Risk weight                20%   50%  100%  100%  100%  150%

    LN-SOV1     RW 0.20 -> RWA   200,000   (pre-fix 1,000,000)
    LN-SOV4     RW 1.00 -> RWA 1,000,000   (unchanged)
    LN-SOV6     RW 1.50 -> RWA 1,500,000   (pre-fix 1,000,000)
    LN-SOVNULL  RW 1.00 -> RWA 1,000,000   (unchanged, Art. 121(2))
    LN-SHORT    RW 0.20 -> RWA   200,000   (unchanged, Art. 121(3))
    LN-TRADE5Y    RW 0.20 -> RWA   200,000   (Table 5 CQS 1; residual 4.9y > 1y)
    LN-TRADE5Y6   RW 1.50 -> RWA 1,500,000   (Table 5 CQS 6; residual 4.9y > 1y)
    LN-TRADE1Y    RW 1.00 -> RWA 1,000,000   (Art. 121(4) interim; residual = 1.0y)
    LN-TRADESEAS  RW 1.00 -> RWA 1,000,000   (Art. 121(4) interim; residual 0.5y)
    LN-RATED      RW 0.50 -> RWA   500,000   (unchanged, Art. 120(1) Table 3 CQS 2)

    Portfolio RWA: 8,100,000 post-fix vs 8,700,000 pre-fix — NET REDUCING by
    600,000. Two reducing steps (LN-SOV1 and LN-TRADE5Y, -800,000 each)
    outweigh two increasing steps (LN-SOV6 and LN-TRADE5Y6, +500,000 each).
    The Art. 121(4) scope change alone, from the intermediate state, is
    8,400,000 -> 8,100,000: also net reducing (-800,000 at CQS 1, +500,000 at
    CQS 6). Both totals are asserted, so the direction claim is measured
    rather than narrated.

CRR ONLY. PS1/26 replaced Art. 121 with the Grade A/B/C SCRA, which routes
through ``cp_scra_grade`` and has no sovereign-derived institution table, so
these parquets are not exercised under ``CalculationConfig.basel_3_1()``.

References:
    - CRR Art. 121(1) Table 5; Art. 121(2); Art. 121(3); Art. 121(4)
      (crr.pdf PAGE_INDEX 119).
    - CRR Art. 120(1) Table 3 (LN-RATED control).
    - CRR Art. 162(3) second subparagraph point (b) (Art. 121(4) scope:
      residual maturity of up to one year).
    - src/rwa_calc/rulebook/packs/crr.py: ``institution_rw_sovereign_derived``,
      ``sa_unrated_institution_trade_finance_max_residual_maturity_years``.
    - IMPLEMENTATION_PLAN.md: P1.316; P1.326 / P1.338 / P7.8 (the
      unimplemented Art. 121(4) rates); P5.22 (``cp_sovereign_cqs`` dead in
      the register).
    - tests/oracle/ORACLE_DERIVATIONS.md: ORC-105/020/106/107/108/109/021.
    - LESSONS.md B5 (two-leg fixture), B7 (strict xfail), D1 (output floor).

Usage:
    uv run python tests/fixtures/p1_316/p1_316.py
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
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

DRAWN_AMOUNT: float = 1_000_000.00

# Long-dated: 5 years, comfortably outside the Art. 121(3) <=3m window.
VALUE_DATE = date(2024, 1, 1)
MATURITY_DATE_LONG = date(2029, 1, 1)
# Short-dated: 73 days -> 73/365 ~= 0.1999y <= 0.25y (Art. 121(3)).
MATURITY_DATE_SHORT = date(2024, 3, 14)

# Art. 121(4) boundary leg: one calendar year after REPORTING_DATE_GUIDANCE, so
# the residual is exactly 1.0y by ``exact_fractional_years_expr``.
MATURITY_DATE_ONE_YEAR_RESIDUAL = date(2025, 1, 31)
# Seasoned trade leg: 2.5 years original, half a year residual at the
# reporting date — inside Art. 121(4) by residual, outside it by original.
VALUE_DATE_SEASONED = date(2022, 1, 31)
MATURITY_DATE_SEASONED = date(2024, 7, 31)

# Reporting-date guidance for the acceptance test (not a parquet column): must
# sit at or before MATURITY_DATE_SHORT so LN-SHORT is still live.
REPORTING_DATE_GUIDANCE = date(2024, 1, 31)

# Own-rating CQS for the LN-RATED control (Art. 120(1) Table 3 CQS 2 -> 50%).
RATED_OWN_CQS = 2

# Every leg is GBP against a GB counterparty with local_currency="GBP", so the
# Art. 121(6) FX floor is structurally off. See the module docstring.
CURRENCY = "GBP"
COUNTRY_CODE = "GB"


@dataclass(frozen=True)
class Leg:
    """One P1.316 exposure leg: a counterparty, a loan, and its expected RW."""

    label: str
    sovereign_cqs: int | None
    expected_rw: float
    pre_fix_rw: float
    role: str
    long_dated: bool = True
    is_trade_lc: bool = False
    own_cqs: int | None = None
    #: (value_date, maturity_date) for a leg off the 5-year / 73-day shapes.
    #: Such legs are not ``long_dated``: they mature before the Basel 3.1 run.
    dates: tuple[date, date] | None = None

    @property
    def cp_ref(self) -> str:
        return f"P1316-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1316-LN-{self.label}"

    @property
    def facility_ref(self) -> str:
        return f"P1316-FAC-{self.label}"

    @property
    def value_date(self) -> date:
        return self.dates[0] if self.dates is not None else VALUE_DATE

    @property
    def maturity_date(self) -> date:
        if self.dates is not None:
            return self.dates[1]
        return MATURITY_DATE_LONG if self.long_dated else MATURITY_DATE_SHORT

    @property
    def expected_rwa(self) -> float:
        return DRAWN_AMOUNT * self.expected_rw

    @property
    def moves(self) -> bool:
        return self.expected_rw != self.pre_fix_rw


#: The ten legs, keyed by label. MOVE-or-SURVIVE pairs plus the rated control
#: — see the table in the module docstring.
LEGS: dict[str, Leg] = {
    leg.label: leg
    for leg in (
        Leg("SOV1", 1, 0.20, 1.00, "MOVES — Table 5 CQS 1, the largest and reducing step"),
        Leg(
            "SOV4", 4, 1.00, 1.00, "SURVIVES — Table 5 CQS 4 is 100%, so a mis-keyed table moves it"
        ),
        Leg("SOV6", 6, 1.50, 1.00, "MOVES — Table 5 CQS 6, the capital-shortfall limb"),
        Leg("SOVNULL", None, 1.00, 1.00, "SURVIVES — Art. 121(2), catches an unconditional branch"),
        Leg("SHORT", 6, 0.20, 0.20, "SURVIVES — Art. 121(3) <=3m flat 20%", long_dated=False),
        Leg(
            "TRADE5Y",
            1,
            0.20,
            1.00,
            "MOVES — trade LC, residual > 1y is outside Art. 121(4): Table 5 CQS 1",
            is_trade_lc=True,
        ),
        Leg(
            "TRADE5Y6",
            6,
            1.50,
            1.00,
            "MOVES — trade LC, residual > 1y is outside Art. 121(4): Table 5 CQS 6",
            is_trade_lc=True,
        ),
        Leg(
            "TRADE1Y",
            1,
            1.00,
            1.00,
            "SURVIVES — trade LC, residual exactly 1y is inside Art. 121(4) (inclusive)",
            long_dated=False,
            is_trade_lc=True,
            dates=(VALUE_DATE, MATURITY_DATE_ONE_YEAR_RESIDUAL),
        ),
        Leg(
            "TRADESEAS",
            1,
            1.00,
            1.00,
            "SURVIVES — trade LC, 2.5y original / 0.5y residual: Art. 121(4) keys on residual",
            long_dated=False,
            is_trade_lc=True,
            dates=(VALUE_DATE_SEASONED, MATURITY_DATE_SEASONED),
        ),
        Leg("RATED", 6, 0.50, 0.50, "SURVIVES — rated, Art. 120(1) Table 3", own_cqs=RATED_OWN_CQS),
    )
}

EXPECTED_PORTFOLIO_RWA: float = sum(leg.expected_rwa for leg in LEGS.values())
PRE_FIX_PORTFOLIO_RWA: float = sum(DRAWN_AMOUNT * leg.pre_fix_rw for leg in LEGS.values())


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1316_counterparties() -> pl.DataFrame:
    """Return one unrated GB institution counterparty per leg.

    ``sovereign_cqs`` is the column under test. ``local_currency="GBP"`` against
    GBP loans is what keeps the Art. 121(6) FX floor off structurally.
    """
    rows = [
        {
            "counterparty_reference": leg.cp_ref,
            "counterparty_name": f"P1.316 Unrated Bank ({leg.label})",
            "entity_type": "bank",
            "country_code": COUNTRY_CODE,
            "local_currency": CURRENCY,
            "sovereign_cqs": leg.sovereign_cqs,
            "default_status": False,
            "is_financial_sector_entity": True,
            "apply_fi_scalar": False,
        }
        for leg in LEGS.values()
    ]
    return pl.DataFrame(rows, schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1316_facilities() -> pl.DataFrame:
    """Return one facility per leg — the only carrier of ``is_short_term_trade_lc``.

    The flag is a FACILITY column (``unify.py`` sets it null for drawn loans and
    ``enrich.propagate_facility_qrre_columns`` inherits it from the loan's own
    parent facility), so the Art. 121(4) leg can only be built through a
    parent facility.
    """
    rows = [
        {
            "facility_reference": leg.facility_ref,
            "product_type": "term_loan",
            "book_code": "FI_LENDING",
            "counterparty_reference": leg.cp_ref,
            "value_date": leg.value_date,
            "maturity_date": leg.maturity_date,
            "currency": CURRENCY,
            "limit": DRAWN_AMOUNT,
            "committed": True,
            "lgd": 0.45,
            "beel": 0.0,
            "is_revolving": False,
            "seniority": "senior",
            "risk_type": "MR",
            "is_short_term_trade_lc": leg.is_trade_lc,
        }
        for leg in LEGS.values()
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FACILITY_SCHEMA))


def create_p1316_loans() -> pl.DataFrame:
    """Return one fully-drawn GBP 1,000,000 loan per leg."""
    rows = [
        {
            "loan_reference": leg.loan_ref,
            "counterparty_reference": leg.cp_ref,
            "currency": CURRENCY,
            "value_date": leg.value_date,
            "maturity_date": leg.maturity_date,
            "drawn_amount": DRAWN_AMOUNT,
            "interest": 0.0,
            "seniority": "senior",
        }
        for leg in LEGS.values()
    ]
    return pl.DataFrame(rows, schema=dtypes_of(LOAN_SCHEMA))


def create_p1316_facility_mappings() -> pl.DataFrame:
    """Return the loan-to-facility mapping rows."""
    rows = [
        {
            "parent_facility_reference": leg.facility_ref,
            "child_reference": leg.loan_ref,
            "child_type": "loan",
        }
        for leg in LEGS.values()
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1316_ratings() -> pl.DataFrame:
    """Return the single own-rating row for the LN-RATED control leg.

    Every other leg is deliberately unrated — that is the Art. 121 precondition.
    """
    rows = [
        {
            "rating_reference": f"P1316-RTG-{leg.label}",
            "counterparty_reference": leg.cp_ref,
            "rating_type": "external",
            "cqs": leg.own_cqs,
            "is_solicited": True,
            "is_short_term": False,
        }
        for leg in LEGS.values()
        if leg.own_cqs is not None
    ]
    return pl.DataFrame(rows, schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1316_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all P1.316 parquet files and return a mapping of name -> path."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1316_counterparties()),
        ("facility", create_p1316_facilities()),
        ("loan", create_p1316_loans()),
        ("facility_mapping", create_p1316_facility_mappings()),
        ("rating", create_p1316_ratings()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path
    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.316 fixture generation complete")
    print("-" * 78)
    for name, path in saved.items():
        print(f"  {name:<20} {pl.read_parquet(path).height:>3} row(s)  ->  {path}")
    print("-" * 78)
    print(f"{'leg':<10} {'sov_cqs':>8} {'pre':>7} {'post':>7}  role")
    for leg in LEGS.values():
        print(
            f"{leg.label:<10} {str(leg.sovereign_cqs):>8} "
            f"{leg.pre_fix_rw:>7.0%} {leg.expected_rw:>7.0%}  {leg.role}"
        )
    print("-" * 78)
    print(
        f"Portfolio RWA: {PRE_FIX_PORTFOLIO_RWA:,.0f} pre-fix -> "
        f"{EXPECTED_PORTFOLIO_RWA:,.0f} post-fix (NET REDUCING)"
    )
    print(f"Reporting-date guidance for the acceptance test: {REPORTING_DATE_GUIDANCE}")


def main() -> None:
    """Entry point for standalone generation."""
    print_summary(save_p1316_fixtures())


if __name__ == "__main__":
    main()
