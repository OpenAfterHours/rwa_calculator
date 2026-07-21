"""
Integration tests: CRR Art. 113(6) core-UK-group 0% RW end-to-end (solo runs).

Runs the FULL calculation via ``CreditRiskCalc`` over the ``multi_entity_cug``
fixture (identical exposures to ``multi_entity`` but with ``core_uk_group=True``
on GRP / BANK_A / BANK_B) and checks every number against the fixture's
documented hand-calc. The base ``multi_entity`` dataset is run alongside to prove
the permission GATE: with ``core_uk_group=False`` no row is eligible and the
solo totals are unchanged.

Hand-calc (see tests/fixtures/multi_entity/multi_entity.py + Wave 4 of
docs/plans/multi-entity-reporting.md):
    unscoped          : base 5m + LOAN_A1_IG_UNDRAWN (1m @ 100%)   -> 6,500,000 RWA
                        + FAC_A1_IG_UNDRAWN undrawn (0.5m @ 100%)
    GRP consolidated  : 3 externals, intragroup eliminated BEFORE  -> 3,000,000 RWA
                        weighting so the 0% never bites            (unchanged)
    BANK_A individual : 2 externals (2m) + LOAN_A1_IG_TO_BANK_B    -> 2,000,000 RWA
                        + LOAN_A1_IG_UNDRAWN + FAC_A1_IG_UNDRAWN
                        undrawn, all at 0% (CUG)                   (base: 3m)
    BANK_B individual : 1 external (1m) + LOAN_B1_IG_TO_BANK_A      -> 1,000,000 RWA
                        at 0% (CUG)                                (base: 2m)
The guaranteed external loan LOAN_A1_EXT (guarantor BANK_B, a CUG member) stays
at 100% on both legs — the permission is keyed on a row's OWN intragroup tag,
not on who guarantees it. The CUG variant also adds an intragroup FACILITY with
undrawn headroom so a synthetic facility_undrawn row exercises the 0% override.

References:
- CRR Art. 113(6): core-UK-group 0% risk weight (individual basis).
- docs/plans/multi-entity-reporting.md: Wave 4 design record.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

import tests.fixtures.multi_entity.multi_entity as multi_entity_fixture
from rwa_calc.api import CreditRiskCalc
from rwa_calc.domain.enums import ReportingBasis

if TYPE_CHECKING:
    from rwa_calc.api.models import CalculationResponse

_REPORTING_DATE = date(2024, 12, 31)  # CRR era (< 2027-01-01)
_RWA_PER_FULL_LOAN = 1_000_000.0

_LOAN_A2_EXT = "LOAN_A2_EXT"
_LOAN_A1_IG = "LOAN_A1_IG_TO_BANK_B"  # BANK_A book, borrower = group entity BANK_B
_LOAN_B1_IG = "LOAN_B1_IG_TO_BANK_A"  # BANK_B book, borrower = group entity BANK_A
_LOAN_A1_EXT = "LOAN_A1_EXT"  # external corporate loan guaranteed BY BANK_B (a CUG member)

_FAC_IG_UNDRAWN = "FAC_A1_IG_UNDRAWN"  # CUG-only intragroup facility with 0.5m undrawn headroom

# The CUG variant adds one intragroup facility with undrawn headroom on BANK_A's
# book (LOAN_A1_IG_UNDRAWN 1m drawn under a 1.5m limit -> 0.5m undrawn at 100% CCF).
# Solo BANK_A / consolidated stay 2m / 3m (0% / eliminated); the unscoped total
# gains the drawn 1m + the 0.5m undrawn commitment, both at 100% -> 6.5m.
_EXPECTED_CUG_TOTAL: dict[str, float] = {
    "unscoped": 6_500_000.0,
    "consolidated": 3_000_000.0,
    "bank_a": 2_000_000.0,
    "bank_b": 1_000_000.0,
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def cug_data_path() -> Path:
    """Path to the core-UK-group fixture, regenerated if the artifacts are absent."""
    cug_dir = Path(multi_entity_fixture.__file__).parent.parent / "multi_entity_cug"
    sentinel = cug_dir / "config" / "reporting_entities.parquet"
    if not sentinel.exists():
        multi_entity_fixture.save_multi_entity_fixtures(cug_dir, core_uk_group=True)
    return cug_dir


@pytest.fixture(scope="module")
def base_data_path() -> Path:
    """Path to the base (non-CUG) fixture, regenerated if the artifacts are absent."""
    fixture_dir = Path(multi_entity_fixture.__file__).parent
    sentinel = fixture_dir / "config" / "reporting_entities.parquet"
    if not sentinel.exists():
        multi_entity_fixture.save_multi_entity_fixtures(fixture_dir)
    return fixture_dir


def _run(
    data_path: Path, entity: str | None, basis: ReportingBasis | None
) -> tuple[CalculationResponse, pl.DataFrame]:
    """Run the full CRR SA calculation for one reporting scope."""
    response = CreditRiskCalc(
        data_path=data_path,
        framework="CRR",
        reporting_date=_REPORTING_DATE,
        permission_mode="standardised",
        reporting_entity=entity,
        reporting_basis=basis,
    ).calculate()
    return response, response.collect_results()


@pytest.fixture(scope="module")
def cug_unscoped(cug_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    return _run(cug_data_path, None, None)


@pytest.fixture(scope="module")
def cug_consolidated(cug_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    return _run(cug_data_path, "GRP", ReportingBasis.CONSOLIDATED)


@pytest.fixture(scope="module")
def cug_bank_a(cug_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    return _run(cug_data_path, "BANK_A", ReportingBasis.INDIVIDUAL)


@pytest.fixture(scope="module")
def cug_bank_b(cug_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    return _run(cug_data_path, "BANK_B", ReportingBasis.INDIVIDUAL)


# =============================================================================
# Helpers
# =============================================================================


def _legs(df: pl.DataFrame, source_ref: str) -> pl.DataFrame:
    return df.filter(pl.col("source_exposure_reference") == source_ref)


def _rwa_for_loan(df: pl.DataFrame, source_ref: str) -> float:
    return float(_legs(df, source_ref)["rwa_final"].sum())


def _total(response: CalculationResponse) -> float:
    return float(response.summary.total_rwa)


# =============================================================================
# 1. Scope totals — the core hand-calc
# =============================================================================


class TestCugScopeTotals:
    """Each CUG scope's total RWA equals its hand-derived value."""

    @pytest.mark.parametrize(
        ("run_fixture", "scope_key"),
        [
            ("cug_unscoped", "unscoped"),
            ("cug_consolidated", "consolidated"),
            ("cug_bank_a", "bank_a"),
            ("cug_bank_b", "bank_b"),
        ],
    )
    def test_total_rwa_matches_hand_calc(
        self, run_fixture: str, scope_key: str, request: pytest.FixtureRequest
    ) -> None:
        response, _ = request.getfixturevalue(run_fixture)
        assert _total(response) == pytest.approx(_EXPECTED_CUG_TOTAL[scope_key])

    def test_summary_total_equals_sum_over_result_rows(
        self, cug_bank_a: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        response, df = cug_bank_a
        assert _total(response) == pytest.approx(float(df["rwa_final"].sum()))


# =============================================================================
# 2. Intragroup rows carry the 0% weight on their own solo run
# =============================================================================


class TestIntragroupRowsZeroWeighted:
    """The intragroup loan on each solo run is risk-weighted at 0% (Art. 113(6))."""

    def test_bank_a_intragroup_loan_is_zero_weighted(
        self, cug_bank_a: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        _, df = cug_bank_a
        legs = _legs(df, _LOAN_A1_IG)
        assert legs.height >= 1
        assert legs["risk_weight"].to_list() == [pytest.approx(0.0)] * legs.height
        assert _rwa_for_loan(df, _LOAN_A1_IG) == pytest.approx(0.0)

    def test_bank_b_intragroup_loan_is_zero_weighted(
        self, cug_bank_b: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        _, df = cug_bank_b
        legs = _legs(df, _LOAN_B1_IG)
        assert legs.height >= 1
        assert legs["risk_weight"].to_list() == [pytest.approx(0.0)] * legs.height
        assert _rwa_for_loan(df, _LOAN_B1_IG) == pytest.approx(0.0)

    def test_external_loan_unaffected(
        self, cug_bank_a: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """A plain external corporate loan keeps its 100% weight."""
        _, df = cug_bank_a
        assert _rwa_for_loan(df, _LOAN_A2_EXT) == pytest.approx(_RWA_PER_FULL_LOAN)

    def test_intragroup_facility_undrawn_row_is_zero_weighted(
        self, cug_bank_a: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """The synthetic facility_undrawn row of an eligible intragroup facility gets 0%.

        FAC_A1_IG_UNDRAWN (intragroup to BANK_B, 0.5m undrawn headroom) proves the
        carrier reaches the SA override on a facility_undrawn row, not just on drawn
        loan / guarantee-split legs. Its 0.5m EAD would be 0.5m RWA at 100%.
        """
        _, df = cug_bank_a
        undrawn = df.filter(
            (pl.col("source_exposure_reference") == _FAC_IG_UNDRAWN)
            & (pl.col("exposure_type") == "facility_undrawn")
        )
        assert undrawn.height == 1
        row = undrawn.row(0, named=True)
        assert row["ead_final"] == pytest.approx(500_000.0)
        assert row["risk_weight"] == pytest.approx(0.0)
        assert row["rwa_final"] == pytest.approx(0.0)


# =============================================================================
# 3. Permission does not leak via a guarantor that is a CUG member
# =============================================================================


class TestPermissionDoesNotLeakViaGuarantor:
    """LOAN_A1_EXT is guaranteed BY BANK_B (a CUG member) but stays at 100%."""

    def test_guaranteed_external_loan_legs_stay_full_weight(
        self, cug_bank_a: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        _, df = cug_bank_a
        legs = _legs(df, _LOAN_A1_EXT)

        # Split into a guaranteed leg + remainder — both at 100% (guarantor BANK_B
        # unrated institution == obligor unrated corporate == 100%), NOT 0%.
        assert legs.height == 2
        assert legs["risk_weight"].to_list() == [pytest.approx(1.0)] * 2
        assert _rwa_for_loan(df, _LOAN_A1_EXT) == pytest.approx(_RWA_PER_FULL_LOAN)


# =============================================================================
# 4. The permission gate — base (non-CUG) dataset is unchanged
# =============================================================================


class TestPermissionGate:
    """With core_uk_group=False no row is eligible, so the base solo totals hold."""

    def test_base_bank_a_unchanged_at_three_million(self, base_data_path: Path) -> None:
        response, _ = _run(base_data_path, "BANK_A", ReportingBasis.INDIVIDUAL)
        assert _total(response) == pytest.approx(3 * _RWA_PER_FULL_LOAN)

    def test_base_bank_b_unchanged_at_two_million(self, base_data_path: Path) -> None:
        response, _ = _run(base_data_path, "BANK_B", ReportingBasis.INDIVIDUAL)
        assert _total(response) == pytest.approx(2 * _RWA_PER_FULL_LOAN)

    def test_consolidated_unchanged_because_elimination_precedes_weighting(
        self, cug_consolidated: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """Even with CUG on, the consolidated run is 3m: intragroup rows are eliminated."""
        response, _ = cug_consolidated
        assert _total(response) == pytest.approx(3 * _RWA_PER_FULL_LOAN)
