"""
Funded credit protection template coverage — the Simple Method column and the
Art. 199 IRB-collateral columns, end to end, in both regimes.

Pipeline position:
    build_reporting_fcsm_bundle()   -> PipelineOrchestrator -> COREPGenerator
    build_reporting_art199_bundle() -> PipelineOrchestrator
        -> COREPGenerator / Pillar3Generator

Why this exists. Five template cells reporting funded protection were measured
at ``0.00`` across all twelve registered golden runs, because no fixture in the
estate elected the Financial Collateral Simple Method and none pledged Art. 199
non-financial collateral:

    COREP C 07.00 col 0070        (-) Financial collateral: Simple method
    COREP C 08.01/02 col 0200     Other physical collateral, in LGD estimates
    COREP C 08.01/02 col 0210     Receivables, in LGD estimates
    Pillar 3 CR7-A col e          Receivables, % of exposure
    Pillar 3 CR7-A col f          Other physical collateral, % of exposure

A dead cell is a cell no gate can see: ``.claude/LESSONS.md`` B5's recurrence
records a supervisory ratchet passing green over a change it was structurally
incapable of observing, precisely because the cell it touched was ``0.00`` in
every golden portfolio. Every assertion below is therefore about a cell that had
never carried a value.

Two structural choices, both deliberate:

- **The Simple Method arm is run TWICE**, once with the Art. 191A election set
  to SIMPLE and once with the default COMPREHENSIVE. Col 0070 is non-zero in the
  first and zero in the second, on the SAME portfolio. Without the second arm a
  green test could not distinguish "the Simple Method populated the column" from
  "the column sums something every collateralised exposure has".
- **The Art. 199 arm keeps a LIVE sibling.** Col 0190 (immovable property) was
  already populated in the estate; cols 0200 / 0210 were not. Asserting all
  three together is what makes the assertions able to tell "the two dead members
  came alive" from "the whole family moved" — the two-leg pattern B5 prescribes.

References:
- CRR Art. 191A: firm-wide election between the Simple and Comprehensive methods
- CRR Art. 222(1): Simple Method — the collateral's own risk weight, floored
- CRR Art. 222(4): the same-currency 0% carve-out
- CRR Art. 199(a)/(b)/(c): IRB-only immovable property, receivables, other physical
- COREP Annex II, C 07.00 cols 0040-0110; C 08.01/02 cols 0180-0210
- Pillar 3 CR7-A cols d / e / f
- Published identities: ``v0305_m`` (C 07.00 0090 subtotal), ``v0306_m`` (0110)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl
import pytest
from tests.fixtures.reporting_funded_protection_portfolio import (
    A199_CARRIER_TO_C08_COLUMN,
    A199_CARRIER_TO_CR7A_COLUMN,
    A199_LIVE_SIBLING_CARRIER,
    A199_LN_ANCHOR,
    A199_LN_PHYSICAL,
    A199_LN_RE,
    A199_LN_RECV,
    A199_PREVIOUSLY_DEAD_CARRIERS,
    A199_TOTAL_DRAWN,
    FCSM_COLLATERAL_BOND,
    FCSM_COLLATERAL_CASH,
    FCSM_EXPECTED_COL_0070,
    FCSM_LN_ANCHOR,
    FCSM_LN_BOND,
    FCSM_LN_CASH,
    FCSM_TOTAL_DRAWN,
    build_reporting_art199_bundle,
    build_reporting_fcsm_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle
from rwa_calc.reporting.pillar3.templates import CR7A_FIRB_ROWS
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import scalar_value

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

#: The obligor class both portfolios book against — one sheet per template, so
#: the columns under test sit side by side and can be compared to each other.
_SHEET: str = "corporate"

#: The origin approach CR7-A keys its sheets on. Every Art. 199 leg is F-IRB.
_FIRB: str = "foundation_irb"

#: COREP renders the CRM deduction block with a negative sign (Annex II labels
#: cols 0050-0090 "(-) ..."), so an expected magnitude is compared against the
#: NEGATED cell. Stated once here rather than sprinkled as stray minus signs.
_DEDUCTION_SIGN: float = -1.0


def _sa_config(regime_key: str, method: CRMCollateralMethod) -> CalculationConfig:
    """SA configuration with an explicit Art. 191A collateral-method election."""
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            permission_mode=PermissionMode.STANDARDISED,
            crm_collateral_method=method,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.STANDARDISED,
        crm_collateral_method=method,
    )


def _irb_config(regime_key: str) -> CalculationConfig:
    """IRB configuration, matching the registered IRB golden runs' dates."""
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


@lru_cache(maxsize=8)
def _run_fcsm(
    regime_key: str, method: CRMCollateralMethod
) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_fcsm_bundle(), _sa_config(regime_key, method)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep


@lru_cache(maxsize=4)
def _run_art199(
    regime_key: str,
) -> tuple[pl.DataFrame, COREPTemplateBundle, Pillar3TemplateBundle]:
    framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_art199_bundle(), _irb_config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep, pillar3


def _total_row(frame: pl.DataFrame) -> dict[str, object]:
    matched = frame.filter(pl.col("row_ref") == "0010")
    assert matched.height == 1, "expected exactly one TOTAL row 0010"
    return matched.row(0, named=True)


def _by_reference(results: pl.DataFrame, column: str) -> dict[str, float]:
    return {
        row["exposure_reference"]: float(row[column] or 0.0)
        for row in results.iter_rows(named=True)
    }


def _fcsm_rw_floor(regime_key: str) -> float:
    """The Art. 222(1) collateral risk-weight floor, read from the RULEPACK.

    ``fcsm_rw_floor`` is the same pack entry ``engine/crm/simple_method.py``
    resolves, so the expected weight below cannot drift from the engine's
    without one of the two failing (LESSONS A4).
    """
    config = _sa_config(regime_key, CRMCollateralMethod.SIMPLE)
    return scalar_value(RulepackV0.from_config(config).pack.scalar_param("fcsm_rw_floor"))


def _cr7a_corporates_row() -> str:
    """The CR7-A F-IRB row carrying plain corporates, from the template definition.

    Resolved from ``CR7A_FIRB_ROWS`` rather than hardcoded: the row refs are a
    property of the layout, and a literal would keep pointing at whatever ends
    up in that position if the layout changes (LESSONS B3).
    """
    for row in CR7A_FIRB_ROWS:
        if "corporate" in row.exposure_classes:
            return row.ref
    raise AssertionError("CR7A_FIRB_ROWS has no row covering the corporate class")


# ---------------------------------------------------------------------------
# C 07.00 col 0070 — Financial Collateral Simple Method (CRR Art. 222)
# ---------------------------------------------------------------------------


class TestSimpleMethodReachesC0700Column0070:
    """Col 0070 was ``0.00`` in every registered golden run. These are the first
    assertions in the estate that it carries anything at all."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_sheet_is_emitted_and_column_0070_is_non_null(self, regime_key: str) -> None:
        """B4: the sheet exists AND the cell in scope is non-null where the
        portfolio has protection. A missing sheet and a null cell read the same
        on the error channel, so both are asserted."""
        _results, corep = _run_fcsm(regime_key, CRMCollateralMethod.SIMPLE)

        assert _SHEET in corep.c07_00, f"{regime_key}: no C 07.00 {_SHEET} sheet"
        total = _total_row(corep.c07_00[_SHEET])
        assert total["0070"] is not None, f"{regime_key}: col 0070 is NULL"
        assert float(total["0070"]) != 0.0, f"{regime_key}: col 0070 is still dead"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_column_0070_reports_the_recognised_collateral(self, regime_key: str) -> None:
        """Annex II col 0070 is the financial collateral incorporated under the
        Simple Method — its raw market value, since Art. 222 applies no haircut
        and does not reduce the exposure value."""
        _results, corep = _run_fcsm(regime_key, CRMCollateralMethod.SIMPLE)

        total = _total_row(corep.c07_00[_SHEET])
        assert float(total["0070"]) == pytest.approx(_DEDUCTION_SIGN * FCSM_EXPECTED_COL_0070)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_comprehensive_election_leaves_column_0070_empty(self, regime_key: str) -> None:
        """The control arm. Same portfolio, Art. 191A election flipped: the
        collateral now reduces the exposure VALUE (col 0200) instead of
        substituting a risk weight, so col 0070 must be zero. Without this the
        test above could pass on a column that summed all collateral."""
        _results, corep = _run_fcsm(regime_key, CRMCollateralMethod.COMPREHENSIVE)

        total = _total_row(corep.c07_00[_SHEET])
        assert float(total["0070"] or 0.0) == pytest.approx(0.0)
        assert float(total["0200"]) < FCSM_TOTAL_DRAWN, (
            "the comprehensive method must reduce the exposure value; if it did "
            "not, the two arms differ by nothing and the contrast proves nothing"
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_simple_method_does_not_reduce_the_exposure_value(self, regime_key: str) -> None:
        """Art. 222: the Simple Method substitutes a risk weight and leaves the
        exposure value alone. Col 0200 must therefore still be the whole book —
        this is the half of the mechanism col 0070 alone cannot show."""
        _results, corep = _run_fcsm(regime_key, CRMCollateralMethod.SIMPLE)

        total = _total_row(corep.c07_00[_SHEET])
        assert float(total["0200"]) == pytest.approx(FCSM_TOTAL_DRAWN)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_annex_ii_outflow_identities_still_close(self, regime_key: str) -> None:
        """``v0305_m`` (0090 = 0050 + 0060 + 0070 + 0080) and ``v0306_m``
        (0110 = 0040 + 0090 + 0100, the components removed exactly once through
        the subtotal). Newly evaluable: with col 0070 at zero both identities
        held vacuously on every golden portfolio."""
        _results, corep = _run_fcsm(regime_key, CRMCollateralMethod.SIMPLE)

        total = _total_row(corep.c07_00[_SHEET])
        subtotal = sum(float(total[ref] or 0.0) for ref in ("0050", "0060", "0070", "0080"))
        assert float(total["0090"]) == pytest.approx(subtotal)
        assert float(total["0110"]) == pytest.approx(
            float(total["0040"]) + float(total["0090"]) + float(total["0100"] or 0.0)
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_each_article_222_limb_substitutes_its_own_weight(self, regime_key: str) -> None:
        """Both limbs, distinguished. Art. 222(1) floors the collateral weight at
        ``fcsm_rw_floor``; Art. 222(4)'s carve-out takes a same-currency 0%-RW
        item to zero. A portfolio with only one of them could not tell a missing
        floor from a missing carve-out."""
        results, _corep = _run_fcsm(regime_key, CRMCollateralMethod.SIMPLE)

        collateral_rw = _by_reference(results, "fcsm_collateral_rw")
        assert collateral_rw[FCSM_LN_BOND] == pytest.approx(_fcsm_rw_floor(regime_key))
        assert collateral_rw[FCSM_LN_CASH] == pytest.approx(0.0)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_uncollateralised_anchor_is_untouched(self, regime_key: str) -> None:
        """The survivor leg. It shares the sheet with both substituted rows, so
        a substitution that leaked across exposures would show here as a moved
        weight on a loan that has no collateral at all."""
        results, _corep = _run_fcsm(regime_key, CRMCollateralMethod.SIMPLE)

        values = _by_reference(results, "fcsm_collateral_value")
        assert values[FCSM_LN_ANCHOR] == pytest.approx(0.0)
        assert values[FCSM_LN_BOND] == pytest.approx(FCSM_COLLATERAL_BOND)
        assert values[FCSM_LN_CASH] == pytest.approx(FCSM_COLLATERAL_CASH)


# ---------------------------------------------------------------------------
# C 08.01 cols 0200 / 0210 and CR7-A cols e / f — CRR Art. 199
# ---------------------------------------------------------------------------


class TestArticle199ReachesTheIrbCrmColumns:
    """C 08.01/02 cols 0200 / 0210 and CR7-A cols e / f were ``0.00`` in every
    registered golden run, so any conservation or coverage rule stated over the
    (real estate, other physical, receivables) family was vacuous on two of its
    three members."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_sheet_is_emitted_with_every_crm_column_non_null(self, regime_key: str) -> None:
        _results, corep, _p3 = _run_art199(regime_key)

        assert _SHEET in corep.c08_01, f"{regime_key}: no C 08.01 {_SHEET} sheet"
        total = _total_row(corep.c08_01[_SHEET])
        for carrier, column in A199_CARRIER_TO_C08_COLUMN.items():
            assert total[column] is not None, f"{regime_key}: col {column} ({carrier}) is NULL"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_previously_dead_columns_now_carry_value(self, regime_key: str) -> None:
        """The two members that were identically zero. Asserted strictly greater
        than zero, not merely non-null: a null-to-zero regression would satisfy
        a non-null check and leave the family just as vacuous."""
        _results, corep, _p3 = _run_art199(regime_key)

        total = _total_row(corep.c08_01[_SHEET])
        for carrier in A199_PREVIOUSLY_DEAD_CARRIERS:
            column = A199_CARRIER_TO_C08_COLUMN[carrier]
            assert float(total[column]) > 0.0, f"{regime_key}: col {column} ({carrier}) is dead"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_live_sibling_survives_beside_them(self, regime_key: str) -> None:
        """Col 0190 was already live in the estate and must STAY live. This is
        the leg of the two-leg pattern that makes a moved number attributable:
        without it, "the family came alive" and "the family moved wholesale"
        look identical."""
        _results, corep, _p3 = _run_art199(regime_key)

        total = _total_row(corep.c08_01[_SHEET])
        column = A199_CARRIER_TO_C08_COLUMN[A199_LIVE_SIBLING_CARRIER]
        assert float(total[column]) > 0.0, f"{regime_key}: col {column} went dark"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_each_column_sums_the_carrier_it_reports(self, regime_key: str) -> None:
        """E2: a breakdown cell must sum the carrier its definition names, not a
        plausible neighbour. Checked against the sealed ledger rather than
        against a literal, so the tie holds whatever the LGD* maths produces."""
        results, corep, _p3 = _run_art199(regime_key)

        total = _total_row(corep.c08_01[_SHEET])
        for carrier, column in A199_CARRIER_TO_C08_COLUMN.items():
            expected = float(results[carrier].fill_null(0.0).sum())
            assert float(total[column]) == pytest.approx(expected), (
                f"{regime_key}: col {column} does not sum {carrier}"
            )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_each_article_199_category_lands_on_its_own_exposure(self, regime_key: str) -> None:
        """Attribution, not just totals. Each pledge is on exactly one loan, so
        each carrier must be non-zero on that loan and zero on the other three —
        a category routed to the wrong carrier leaves the portfolio total
        unchanged and would pass every assertion above."""
        results, _corep, _p3 = _run_art199(regime_key)

        owner = {
            "reporting_crm_lgd_real_estate": A199_LN_RE,
            "reporting_crm_lgd_receivables": A199_LN_RECV,
            "reporting_crm_lgd_other_physical": A199_LN_PHYSICAL,
        }
        for carrier, expected_owner in owner.items():
            per_loan = _by_reference(results, carrier)
            non_zero = {ref for ref, value in per_loan.items() if value > 0.0}
            assert non_zero == {expected_owner}, f"{regime_key}: {carrier} on {non_zero}"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_unsecured_anchor_carries_no_collateral(self, regime_key: str) -> None:
        results, _corep, _p3 = _run_art199(regime_key)

        for carrier in A199_CARRIER_TO_C08_COLUMN:
            assert _by_reference(results, carrier)[A199_LN_ANCHOR] == pytest.approx(0.0)


class TestArticle199ReachesPillar3Cr7a:
    """CR7-A reports each funded-protection category as a percentage of the
    row's exposure. Cols e / f had no source of data in the estate."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_firb_sheet_is_emitted(self, regime_key: str) -> None:
        _results, _corep, pillar3 = _run_art199(regime_key)

        assert _FIRB in pillar3.cr7a, f"{regime_key}: no CR7-A {_FIRB} sheet"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_funded_protection_column_is_non_null_and_positive(self, regime_key: str) -> None:
        _results, _corep, pillar3 = _run_art199(regime_key)

        sheet = pillar3.cr7a[_FIRB]
        row = sheet.filter(pl.col("row_ref") == _cr7a_corporates_row()).row(0, named=True)
        for carrier, column in A199_CARRIER_TO_CR7A_COLUMN.items():
            assert row[column] is not None, f"{regime_key}: CR7-A col {column} ({carrier}) NULL"
            assert float(row[column]) > 0.0, f"{regime_key}: CR7-A col {column} ({carrier}) zero"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_each_percentage_is_its_carrier_over_the_row_exposure(self, regime_key: str) -> None:
        """The percentages are ratios over the row's own exposure, so the row's
        col a must be the portfolio's exposure and each of d / e / f must be its
        carrier's share of it. Anchoring on the ledger keeps the check honest if
        the LGD* maths moves an adjusted value."""
        results, _corep, pillar3 = _run_art199(regime_key)

        sheet = pillar3.cr7a[_FIRB]
        row = sheet.filter(pl.col("row_ref") == _cr7a_corporates_row()).row(0, named=True)
        exposure = float(row["a"])
        assert exposure == pytest.approx(A199_TOTAL_DRAWN)

        for carrier, column in A199_CARRIER_TO_CR7A_COLUMN.items():
            expected = 100.0 * float(results[carrier].fill_null(0.0).sum()) / exposure
            assert float(row[column]) == pytest.approx(expected), (
                f"{regime_key}: CR7-A col {column} is not {carrier} / exposure"
            )
