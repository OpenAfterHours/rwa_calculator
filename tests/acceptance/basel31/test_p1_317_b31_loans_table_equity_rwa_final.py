"""
P1.317 — a Basel 3.1 equity leg from the LOANS table is risk-weighted, then dropped.

Acceptance scenario: one obligor whose ``entity_type`` is ``equity`` holds a single
GBP 1,500,000 drawn position booked on the **loans** table (not the dedicated
``equity_exposures`` table), alongside an ordinary CQS 3 corporate loan that acts as
the survives-the-change control leg.

The defect under test:
    ``engine/stages/calc.py:106`` splits the portfolio with
    ``~is_irb & ~is_slotting``, which admits BOTH ``standardised`` and ``equity``
    onto the SA branch. Under Basel 3.1 the ``output_floor`` feature is on, so that
    branch is served by ``engine/sa/calculator.py::calculate_unified``, whose
    ``is_sa = pl.col("approach") == ApproachType.SA.value`` gate (``:106``, used at
    ``:141``) is FALSE for the equity row. ``rwa_pre_factor`` lands on the
    ``.otherwise(...)`` arm and is null, and the null then rides
    ``rwa_post_factor`` -> ``calc.py:151`` ``rwa_final`` -> ``_floor.py:151``
    ``rwa_pre_floor`` -> ``_floor.py:265`` ``rwa_final``.

    The engine has already RESOLVED the weight — ``risk_weight`` / ``reporting_rw``
    read 2.50 and ``sa_rwa`` reads 3,750,000 — so the RWEA is computed and then
    silently discarded. ``rwa_final`` is the carrier every COREP / Pillar 3 credit
    risk row and OV1 line sums, so 3,750,000 of RWEA and 300,000 of own funds
    requirement (CRR Art. 92(1), 8% of RWEA) leave the submission with no error, no
    null cell and no failing published rule: the row simply is not there.

    CRR is unaffected: ``output_floor`` is ``enabled=False`` in the CRR pack, so
    ``calc.py:154`` takes ``calculate_branch``, which computes RWA unconditionally.
    The CRR leg below is therefore a genuine control — a fix that repairs Basel 3.1
    by disturbing the CRR path reddens it.

Population, measured rather than assumed: this is the loans/contingents-table
equity shape ONLY. A leg arriving through the dedicated ``equity_exposures`` table
is already correct in both regimes.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> calculators
    -> OutputAggregator (the sealed ledger these assertions read)

Headline fail-first assertion:
    B31 equity leg: ``risk_weight == 2.50`` AND ``rwa_final == 3,750,000``.
    Pre-fix the engine returns ``risk_weight == 2.50`` and ``rwa_final is None``.
    Both are pinned together deliberately: the load-bearing risk is a fix that
    makes ``rwa_final`` non-null by routing equity through the wrong arm and
    picking up a different weight, which an ``is not None`` assertion would pass.

Hand calculation (steady state, so no transitional schedule is in play):
    Basel 3.1, reporting_date 2030-06-30:
        equity    EAD 1,500,000 x RW 2.50 = RWA 3,750,000   (currently None)
        corporate EAD 4,000,000 x RW 0.75 = RWA 3,000,000   (correct today)
        portfolio total rwa_final                6,750,000  (currently 3,000,000)
    CRR, reporting_date 2025-12-31:
        equity    EAD 1,500,000 x RW 1.00 = RWA 1,500,000   (correct today)
        corporate EAD 4,000,000 x RW 1.00 = RWA 4,000,000   (correct today)
        portfolio total rwa_final                5,500,000

    No IRB or slotting leg exists in this portfolio, so U-TREA == S-TREA and the
    output floor cannot bind — every ``rwa_final`` below is its own unfloored RWA.

Regulatory references:
    - PRA PS1/26 Art. 133(3): "An equity exposure shall be assigned a risk weight
      of 250%..." (verbatim, ``docs/assets/ps126app1.pdf`` page index 67).
      Rulepack ``equity_sa_risk_weights`` (b31), default ``2.50``.
    - CRR Art. 133(2): 100% flat equity SA risk weight. Rulepack
      ``equity_sa_risk_weights`` (crr), default ``1.00``.
    - CRR Art. 92(1): own funds requirement is 8% of RWEA.
    - src/rwa_calc/engine/stages/calc.py:106,141,151 (the branch split).
    - src/rwa_calc/engine/sa/calculator.py:106,141 (the ``is_sa`` gate; fix target).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

#: Steady state under both regimes: the PRA Rules 4.2/4.3 equity transitional
#: schedule has completed (its last step is 2030-01-01) and the output-floor
#: phase-in is irrelevant here because nothing routes IRB. A 2030 date therefore
#: makes 250% unambiguously the Art. 133(3) steady-state weight.
_B31_REPORTING_DATE = date(2030, 6, 30)
_CRR_REPORTING_DATE = date(2025, 12, 31)

_VALUE_DATE = date(2015, 1, 1)
_MATURITY_DATE = date(2035, 6, 30)

EQUITY_REF = "LN-P1317-EQ"
CORPORATE_REF = "LN-P1317-CORP"

EQUITY_EAD = 1_500_000.0
CORPORATE_EAD = 4_000_000.0

#: PS1/26 Art. 133(3) — rulepack ``equity_sa_risk_weights`` (b31), default 2.50.
B31_EQUITY_RW = 2.50
B31_EQUITY_RWA = 3_750_000.0

#: PS1/26 Art. 122(2) Table 6 — CQS 3 corporate. The control leg, correct today.
B31_CORPORATE_RW = 0.75
B31_CORPORATE_RWA = 3_000_000.0

#: CRR Art. 133(2) — rulepack ``equity_sa_risk_weights`` (crr), default 1.00.
CRR_EQUITY_RW = 1.00
CRR_EQUITY_RWA = 1_500_000.0

#: CRR Art. 122(1) Table 6 — CQS 3 corporate.
CRR_CORPORATE_RW = 1.00
CRR_CORPORATE_RWA = 4_000_000.0

B31_PORTFOLIO_RWA = B31_EQUITY_RWA + B31_CORPORATE_RWA
CRR_PORTFOLIO_RWA = CRR_EQUITY_RWA + CRR_CORPORATE_RWA

_MONEY_TOLERANCE = 0.005


# ---------------------------------------------------------------------------
# Portfolio (module-local; no tests/fixtures/ edit)
# ---------------------------------------------------------------------------


def _build_bundle():
    """Seal the two-leg portfolio through the production loader edge contracts.

    Both legs are booked on the LOANS table, which is the whole point: the
    ``equity_exposures`` table reaches ``EquityCalculator`` and is already correct,
    while a loans-table row whose obligor is ``entity_type='equity'`` classifies to
    the equity class and routes ``approach='equity'`` onto the SA branch.
    """
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP-P1317-EQ",
                "counterparty_name": "CP-P1317-EQ",
                "entity_type": "equity",
                "country_code": "GB",
                "is_natural_person": False,
                "is_managed_as_retail": False,
                "default_status": False,
            },
            {
                "counterparty_reference": "CP-P1317-CORP",
                "counterparty_name": "CP-P1317-CORP",
                "entity_type": "corporate",
                "country_code": "GB",
                "is_natural_person": False,
                "is_managed_as_retail": False,
                "default_status": False,
            },
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": EQUITY_REF,
                "counterparty_reference": "CP-P1317-EQ",
                "product_type": "term_loan",
                "drawn_amount": EQUITY_EAD,
                "currency": "GBP",
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY_DATE,
                "seniority": "senior",
                "is_defaulted": False,
            },
            {
                "loan_reference": CORPORATE_REF,
                "counterparty_reference": "CP-P1317-CORP",
                "product_type": "term_loan",
                "drawn_amount": CORPORATE_EAD,
                "currency": "GBP",
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY_DATE,
                "seniority": "senior",
                "is_defaulted": False,
            },
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": "RT-P1317-CORP",
                "counterparty_reference": "CP-P1317-CORP",
                "rating_type": "external",
                "rating_agency": "TEST_AGENCY",
                "cqs": 3,
                "rating_date": _VALUE_DATE,
            }
        ],
        schema_overrides=dtypes_of(RATINGS_SCHEMA),
    )
    return make_raw_bundle(counterparties=counterparties, loans=loans, ratings=ratings)


def _run(config: CalculationConfig) -> pl.DataFrame:
    """The collected sealed aggregator-exit ledger — the frame templates sum."""
    return PipelineOrchestrator().run_with_data(_build_bundle(), config).results.collect()


def _leg(ledger: pl.DataFrame, reference: str) -> dict:
    """The single ledger row for ``reference``, asserting it was emitted at all."""
    rows = ledger.filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, (
        f"expected exactly one ledger row for {reference!r}, got {len(rows)}. "
        f"References present: {sorted(ledger['exposure_reference'].to_list())}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_ledger() -> pl.DataFrame:
    """Basel 3.1 sealed ledger — the regime carrying the defect."""
    return _run(
        CalculationConfig.basel_3_1(
            reporting_date=_B31_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    )


@pytest.fixture(scope="module")
def crr_ledger() -> pl.DataFrame:
    """CRR sealed ledger — the control regime, correct today."""
    return _run(
        CalculationConfig.crr(
            reporting_date=_CRR_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    )


# ---------------------------------------------------------------------------
# P1.317 — PRIMARY ASSERTION (FAILS today)
# ---------------------------------------------------------------------------


def test_b31_loans_table_equity_leg_carries_its_rwea_to_rwa_final(
    b31_ledger: pl.DataFrame,
) -> None:
    """The Basel 3.1 equity leg reaches ``rwa_final`` at the weight it was given.

    Arrange: the sealed Basel 3.1 ledger for the two-leg loans-table portfolio.
    Act: read the equity leg's resolved weight and its final RWEA.
    Assert: ``risk_weight == 2.50`` AND ``rwa_final == 3,750,000``, together.

    The two are pinned in one assertion on purpose. ``rwa_final is not None`` would
    be satisfied by any fix that routes equity through a different arm and picks up
    a different weight, and the absolute value alone would be satisfied by a weight
    that happened to multiply out. Pinning both makes the ONLY passing state
    "Art. 133(3) 250% applied, and carried through".

    Failure mode before fix: ``rwa_final is None`` while ``risk_weight`` already
    reads 2.50 — the engine resolved the weight and discarded the product.
    """
    # Arrange / Act
    leg = _leg(b31_ledger, EQUITY_REF)

    # Assert
    assert (leg["risk_weight"], leg["rwa_final"]) == (
        pytest.approx(B31_EQUITY_RW, abs=1e-9),
        pytest.approx(B31_EQUITY_RWA, abs=_MONEY_TOLERANCE),
    ), (
        f"P1.317: the Basel 3.1 loans-table equity leg {EQUITY_REF!r} should carry "
        f"risk_weight={B31_EQUITY_RW} (PS1/26 Art. 133(3) 250%) and "
        f"rwa_final={B31_EQUITY_RWA:,.2f} (EAD {EQUITY_EAD:,.2f} x 250%); got "
        f"risk_weight={leg['risk_weight']} rwa_final={leg['rwa_final']}. "
        f"The engine already resolved the weight — sa_rwa={leg.get('sa_rwa')} — so a "
        f"null rwa_final is RWEA computed and then dropped, not RWEA not computed."
    )


def test_b31_loans_table_equity_leg_is_emitted_with_its_exposure_value(
    b31_ledger: pl.DataFrame,
) -> None:
    """The equity leg is present in the ledger, on the equity approach, with its EAD.

    Arrange: the sealed Basel 3.1 ledger.
    Act: locate the equity leg and read the columns that place it.
    Assert: exactly one row exists, its origin approach is ``ApproachType.EQUITY``
    and ``ead_final`` is the full 1,500,000.

    Negative-space guard (``.claude/LESSONS.md`` B4). Without it the primary
    assertion could be satisfied by DELETING the row — an equity leg that never
    reaches the ledger also never publishes a wrong number. The approach label is
    read off the enum, not a literal, so it cannot drift with the engine.
    """
    # Arrange / Act
    leg = _leg(b31_ledger, EQUITY_REF)

    # Assert
    assert leg["reporting_approach_origin"] == ApproachType.EQUITY.value, (
        f"P1.317: {EQUITY_REF!r} should still route the equity approach, got "
        f"{leg['reporting_approach_origin']!r} — a fix that repairs rwa_final by "
        f"reclassifying the leg out of equity is not this fix."
    )
    assert leg["ead_final"] == pytest.approx(EQUITY_EAD, abs=_MONEY_TOLERANCE), (
        f"P1.317: {EQUITY_REF!r} ead_final should be {EQUITY_EAD:,.2f}, got {leg['ead_final']}"
    )


def test_b31_no_leg_carries_a_null_rwa_final(b31_ledger: pl.DataFrame) -> None:
    """Every Basel 3.1 ledger row with exposure carries a non-null ``rwa_final``.

    Arrange: the sealed Basel 3.1 ledger.
    Act: select every row whose ``rwa_final`` is null.
    Assert: there are none. Stated over the WHOLE frame rather than over a named
    list of references, so it cannot drift with the portfolio: a null and a
    legitimate zero are different claims, and only the null is unpublishable.
    """
    # Arrange / Act
    dropped = b31_ledger.filter(pl.col("rwa_final").is_null())

    # Assert
    assert dropped.height == 0, (
        "P1.317: Basel 3.1 legs whose RWEA never reaches rwa_final:\n  "
        + "\n  ".join(
            f"{row['exposure_reference']}: approach={row['reporting_approach_origin']!r} "
            f"ead_final={row['ead_final']} risk_weight={row['risk_weight']} "
            f"sa_rwa={row.get('sa_rwa')} rwa_final=None"
            for row in dropped.to_dicts()
        )
    )


def test_b31_portfolio_total_rwa_final_foots_both_legs(b31_ledger: pl.DataFrame) -> None:
    """The Basel 3.1 portfolio total is the sum of both legs' RWEA.

    Arrange: the sealed Basel 3.1 ledger.
    Act: sum ``rwa_final`` across the portfolio.
    Assert: 6,750,000 — 3,750,000 equity plus 3,000,000 corporate. Asserted as an
    ABSOLUTE figure, not as "greater than the corporate leg": a breakdown that
    silently drops a row still foots against itself, and the dropped-row total
    (3,000,000) is exactly what the engine publishes today.
    """
    # Arrange / Act
    total = float(b31_ledger["rwa_final"].fill_null(0.0).sum())

    # Assert
    assert total == pytest.approx(B31_PORTFOLIO_RWA, abs=_MONEY_TOLERANCE), (
        f"P1.317: Basel 3.1 portfolio rwa_final should total "
        f"{B31_PORTFOLIO_RWA:,.2f} ({B31_EQUITY_RWA:,.2f} equity + "
        f"{B31_CORPORATE_RWA:,.2f} corporate), got {total:,.2f}. A shortfall of "
        f"{B31_EQUITY_RWA:,.2f} is the equity leg missing from every template that "
        f"sums this carrier."
    )


def test_b31_standardised_control_leg_is_undisturbed(b31_ledger: pl.DataFrame) -> None:
    """The plain-SA corporate leg keeps the number it already has.

    Arrange: the sealed Basel 3.1 ledger.
    Act: read the CQS 3 corporate leg.
    Assert: ``risk_weight == 0.75`` and ``rwa_final == 3,000,000``.

    The survives-the-change half of the two-leg pattern (``.claude/LESSONS.md``
    B5): the fix widens the arm that serves the SA branch, and a test whose only
    live leg MOVES cannot tell "the fix worked" from "the fix disturbed everything
    on that branch".
    """
    # Arrange / Act
    leg = _leg(b31_ledger, CORPORATE_REF)

    # Assert
    assert (leg["risk_weight"], leg["rwa_final"]) == (
        pytest.approx(B31_CORPORATE_RW, abs=1e-9),
        pytest.approx(B31_CORPORATE_RWA, abs=_MONEY_TOLERANCE),
    ), (
        f"P1.317 control: the Basel 3.1 CQS 3 corporate leg {CORPORATE_REF!r} should "
        f"be unchanged at risk_weight={B31_CORPORATE_RW} / "
        f"rwa_final={B31_CORPORATE_RWA:,.2f}, got risk_weight={leg['risk_weight']} "
        f"rwa_final={leg['rwa_final']}"
    )


# ---------------------------------------------------------------------------
# CRR control — passes today, and must keep passing
# ---------------------------------------------------------------------------


def test_crr_loans_table_equity_leg_still_carries_its_rwea_to_rwa_final(
    crr_ledger: pl.DataFrame,
) -> None:
    """The same input shape under CRR keeps its 100% RWEA.

    Arrange: the sealed CRR ledger for the identical portfolio.
    Act: read the equity leg.
    Assert: ``risk_weight == 1.00`` and ``rwa_final == 1,500,000``.

    CRR takes ``calculate_branch`` (``output_floor`` is disabled in the CRR pack),
    which computes RWA unconditionally, so this passes today. It is here because
    the fix touches the shared branch split: a repair that reroutes equity under
    Basel 3.1 and changes what CRR does to the same row reddens this test rather
    than shipping.
    """
    # Arrange / Act
    leg = _leg(crr_ledger, EQUITY_REF)

    # Assert
    assert (leg["risk_weight"], leg["rwa_final"]) == (
        pytest.approx(CRR_EQUITY_RW, abs=1e-9),
        pytest.approx(CRR_EQUITY_RWA, abs=_MONEY_TOLERANCE),
    ), (
        f"P1.317 CRR control: the loans-table equity leg {EQUITY_REF!r} should stay at "
        f"risk_weight={CRR_EQUITY_RW} (CRR Art. 133(2) 100%) and "
        f"rwa_final={CRR_EQUITY_RWA:,.2f}, got risk_weight={leg['risk_weight']} "
        f"rwa_final={leg['rwa_final']}"
    )


def test_crr_portfolio_total_rwa_final_foots_both_legs(crr_ledger: pl.DataFrame) -> None:
    """The CRR portfolio total is unchanged at 5,500,000.

    Arrange: the sealed CRR ledger.
    Act: sum ``rwa_final``.
    Assert: 5,500,000 — 1,500,000 equity plus 4,000,000 corporate. Absolute, so a
    fix that moves the CRR equity leg to 250% (the wrong regime's weight) is caught
    here rather than passing as "still non-null".
    """
    # Arrange / Act
    total = float(crr_ledger["rwa_final"].fill_null(0.0).sum())

    # Assert
    assert total == pytest.approx(CRR_PORTFOLIO_RWA, abs=_MONEY_TOLERANCE), (
        f"P1.317 CRR control: portfolio rwa_final should total "
        f"{CRR_PORTFOLIO_RWA:,.2f}, got {total:,.2f}"
    )


def test_crr_no_leg_carries_a_null_rwa_final(crr_ledger: pl.DataFrame) -> None:
    """No CRR ledger row carries a null ``rwa_final``.

    Arrange: the sealed CRR ledger.
    Act: select the rows whose ``rwa_final`` is null.
    Assert: there are none. The regime-symmetric half of the absence guard —
    ``.claude/LESSONS.md`` C7: one regime being green is not evidence about the
    other, so the guard is stated separately per regime rather than once over a
    parametrisation whose red half would mask the green one.
    """
    # Arrange / Act
    dropped = crr_ledger.filter(pl.col("rwa_final").is_null())

    # Assert
    assert dropped.height == 0, (
        "P1.317 CRR control: legs whose RWEA never reaches rwa_final:\n  "
        + "\n  ".join(
            f"{row['exposure_reference']}: approach={row['reporting_approach_origin']!r} "
            f"ead_final={row['ead_final']} risk_weight={row['risk_weight']} rwa_final=None"
            for row in dropped.to_dicts()
        )
    )
