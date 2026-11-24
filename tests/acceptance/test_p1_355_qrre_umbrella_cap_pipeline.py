"""P1.355 end-to-end: the capital consequence of capping the QRRE per-individual
aggregate at the multi-option umbrella, and the invariants the fix must NOT
disturb.

CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the aggregate nominal exposure
to a single individual. Under a multi-option facility a drawn leg carries its
sub-facility's limit, so the classifier summed the sub-limits of a fully drawn
umbrella past the umbrella that contains them. The unit sibling
(``tests/unit/classifier/test_p1_355_qrre_umbrella_cap.py``) pins the
classification; this file pins what the reclassification is worth.

The mover is the fixture's (NRL) leg: one individual, root 80,000, two
sub-lines of 60,000, 40,000 drawn under each. Counted as HEAD counts it the
aggregate is 120,000 (over both ceilings: ``retail_other``); capped at the
umbrella it is 80,000 (within both: ``retail_qrre``). Here the two loans are put
on the A-IRB branch at three (PD, own LGD) points chosen to show that the move
goes EITHER way, which is why the item was signed off as "either direction":

=========  =====  ======  =====================================================
scenario   PD     LGD     effect of admission to QRRE (per loan, EAD 40,000)
=========  =====  ======  =====================================================
LOW        1%     0.60    RWA falls in both regimes: R 0.1216 -> 0.04.
HIGH       15%    0.60    RWA rises in both regimes: above the PD ~ 7.3%
                          crossover the retail-other curve is below 0.04.
FLOORS     4%     0.30    CRR falls (no retail LGD floor); Basel 3.1 RISES —
                          the QRRE unsecured LGD floor (Art. 164(4)) binds and
                          outweighs the lower correlation.
=========  =====  ======  =====================================================

Three groups of assertions:

1. **The moving numbers, both regimes** (fail pre-fix). Each figure was derived
   offline from Art. 154(1)/(4) with the stdlib ``statistics.NormalDist`` — not
   the ``polars-normal-stats`` the engine uses, so expected value and engine do
   not share a source. The same derivation reproduces every PRE-fix
   ``retail_other`` figure below to <= 1.2e-10 relative (engine-measured on the
   unfixed tree), which is the evidence the method is sound before it is
   trusted for the post-fix figures.

       K   = LGD x [ N( (G(PD) + sqrt(R) G(0.999)) / sqrt(1 - R) ) - PD ]
       RWA = K x 12.5 x EAD x irb_scaling_factor (CRR 1.06; Basel 3.1 1.0)
       R   = 0.04 (QRRE, Art. 154(4)) | 0.03 f + 0.16 (1 - f),
             f = (1 - e^(-35 PD)) / (1 - e^(-35))  (other retail, Art. 154(1))

2. **EAD conservation, per regime separately** (green both sides): a
   classification fix can neither create nor destroy exposure (LESSONS C7).

3. **The Basel 3.1 output floor** (LESSONS D1), taken over the whole book
   (PS1/26 Art. 92 paras 2A / 3 / 3A). The SA-equivalent risk weight does not
   depend on the retail sub-class, so ``s_trea`` and ``sa_rwa_total`` are
   byte-identical across the fix in every scenario (green both sides). U-TREA
   is the SA-routed book plus the movers' modelled charge, so it moves with
   the movers (fails pre-fix). The floor is slack on both sides in every
   scenario — the SA-routed remainder keeps U-TREA far above
   ``x * S-TREA + OF-ADJ`` — so the post-floor total moves by the full
   modelled change (fails pre-fix).

4. **A duplicated facility reference** (DQ004; the run continues). The root
   join must copy no leg: the duplicated root's loans stay one row each, and
   the portfolio's rows and EAD equal those of the hierarchy without the root
   join (green on both sides of the fix; red on a plain join).

References:
- CRR Art. 153(1), 154(1)/(4); PS1/26 Art. 147(5A), 154(4), 163(1), 164(4).
- PS1/26 Art. 92 (2A) / (3) / (3A) / Art. 465: the Basel 3.1 output floor.
- ``tests/fixtures/p1_355/p1_355.py``: the portfolio and its leg inventory.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass, PermissionMode
from rwa_calc.engine.hierarchy import enrich as enrich_module
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.p1_355.p1_355 import (
    CP_NRL,
    DUP_DRAWN,
    LN_DUP_A,
    LN_DUP_B,
    LN_DUPS,
    LN_NRL_A,
    LN_NRL_B,
    NRL_DRAWN,
    VALUE_DATE,
    build_p1_355_duplicate_bundle,
    build_p1_355_raw_bundle,
)
from tests.fixtures.raw_bundle import seal_raw_table

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value

_REPORTING_DATE = date(2027, 1, 4)

#: The model_id ``create_full_irb_model_permissions`` grants every class.
_MODEL_ID: str = "TEST_FULL_IRB"

_RATINGS_SCHEMA: dict[str, pl.DataType] = {
    "rating_reference": pl.String,
    "counterparty_reference": pl.String,
    "rating_type": pl.String,
    "pd": pl.Float64,
    "model_id": pl.String,
    "rating_date": pl.Date,
}

_MOVERS: tuple[str, str] = (LN_NRL_A, LN_NRL_B)

#: Art. 154(4) QRRE correlation — flat, no PD term.
QRRE_CORRELATION: float = 0.04


@dataclass(frozen=True)
class _Scenario:
    """One (PD, own LGD) point and its per-loan figures, derived as above."""

    pd: float
    lgd: float
    crr_qrre_rwa: float
    crr_other_rwa: float
    b31_qrre_rwa: float
    b31_other_rwa: float


#: Per-loan modelled ``rwa`` (EAD 40,000). ``*_other_rwa`` is the pre-fix
#: ``retail_other`` basis, recorded for the anti-confound assertion only.
SCENARIOS: dict[str, _Scenario] = {
    "low": _Scenario(
        pd=0.01,
        lgd=0.60,
        crr_qrre_rwa=9_737.391767,
        crr_other_rwa=25_876.846970,
        b31_qrre_rwa=9_186.218648,
        b31_other_rwa=24_412.119783,
    ),
    "high": _Scenario(
        pd=0.15,
        lgd=0.60,
        crr_qrre_rwa=58_729.648861,
        crr_other_rwa=50_088.990880,
        b31_qrre_rwa=55_405.329114,
        b31_other_rwa=47_253.764981,
    ),
    # Basel 3.1 QRRE figure at LGD floored to the pack's retail_qrre_unsecured
    # (0.50 at the time of writing; asserted from the pack below, never typed
    # into an assertion), the other-retail one at the own LGD 0.30 — the
    # retail_other_unsecured floor does not bind at 0.30.
    "floors": _Scenario(
        pd=0.04,
        lgd=0.30,
        crr_qrre_rwa=13_330.799572,
        crr_other_rwa=18_377.022400,
        b31_qrre_rwa=20_960.376686,
        b31_other_rwa=17_336.813585,
    ),
}

#: Total EAD of the whole portfolio, per regime, measured pre-fix. The totals
#: differ because the unconditionally-cancellable CCF differs by regime — a
#: ``risk_type`` function, not a class function — so neither may move.
TOTAL_EAD_CRR: float = 540_000.0
TOTAL_EAD_B31: float = 573_000.0

#: The Basel 3.1 output-floor SA legs, measured pre-fix, identical in every
#: scenario. S-TREA is taken over the whole book: the movers' SA-equivalent
#: (2 x 40,000 x 75% = 60,000) plus the SA-routed remainder of the portfolio
#: (``sa_rwa_total``). Both must be byte-identical after the fix.
SA_RWA_TOTAL_B31: float = 369_750.0
S_TREA_B31: float = 429_750.0


# =============================================================================
# Bundles and runs
# =============================================================================


def _airb_bundle(pd_value: float, lgd: float) -> RawDataBundle:
    """The P1.355 bundle with the (NRL) mover's two loans on the A-IRB branch.

    Every other obligor stays unrated and routes standardised. Re-sealed through
    ``seal_raw_table`` so the frames carry the loader edge brands a production
    load produces.
    """
    raw = build_p1_355_raw_bundle()
    ratings = pl.LazyFrame(
        [
            {
                "rating_reference": "P1355-RTG-" + CP_NRL,
                "counterparty_reference": CP_NRL,
                "rating_type": "internal",
                "pd": pd_value,
                "model_id": _MODEL_ID,
                "rating_date": VALUE_DATE,
            }
        ],
        schema=_RATINGS_SCHEMA,
    )
    is_mover = pl.col("loan_reference").is_in(_MOVERS)
    loans = raw.loans.with_columns(
        pl.when(is_mover).then(pl.lit(lgd)).otherwise(pl.col("lgd")).alias("lgd"),
        # Retail is A-IRB-only; the own-estimate LGD is admitted only with the
        # collateral-data attestation beside it.
        pl.when(is_mover)
        .then(pl.lit(True))
        .otherwise(pl.col("has_sufficient_collateral_data"))
        .alias("has_sufficient_collateral_data"),
    )
    return replace(
        raw,
        loans=seal_raw_table(loans, "loans"),
        ratings=seal_raw_table(ratings, "ratings"),
        model_permissions=seal_raw_table(create_full_irb_model_permissions(), "model_permissions"),
    )


def _config(regime: str) -> CalculationConfig:
    """IRB permission mode; Basel 3.1 with the optional 0.2% granularity test off.

    The BCBS CRE20.66 granularity test (not a PS1/26 limb) would fail every
    retail row of a book this thin before the QRRE gate is reached — the same
    isolation switch the unit sibling and the P1.320 tests use.
    """
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


_RUNS: dict[tuple[str, str], AggregatedResultBundle] = {}


def _run(regime: str, scenario: str) -> AggregatedResultBundle:
    """Run (and memoise) the full pipeline for one regime and scenario."""
    key = (regime, scenario)
    if key not in _RUNS:
        point = SCENARIOS[scenario]
        _RUNS[key] = PipelineOrchestrator().run_with_data(
            _airb_bundle(point.pd, point.lgd), _config(regime)
        )
    return _RUNS[key]


def _rows(regime: str, scenario: str) -> pl.DataFrame:
    return _run(regime, scenario).results.collect()


def _mover(df: pl.DataFrame, ref: str) -> dict[str, object]:
    match = df.filter(pl.col("exposure_reference") == ref)
    assert len(match) == 1, f"expected exactly 1 row for {ref!r}, got {len(match)}"
    return match.row(0, named=True)


# =============================================================================
# 1. The moving numbers — both regimes, every scenario. FAIL PRE-FIX.
# =============================================================================


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("ref", _MOVERS)
class TestMoverCapital:
    """The (NRL) loans: ``retail_qrre`` at the flat Art. 154(4) correlation, at
    the derived modelled figure, on the A-IRB branch — in each regime."""

    def test_crr_mover_is_qrre_on_airb(self, scenario: str, ref: str) -> None:
        row = _mover(_rows("crr", scenario), ref)
        assert (row["exposure_class"], row["approach"]) == (_QRRE, "advanced_irb")

    def test_b31_mover_is_qrre_on_airb(self, scenario: str, ref: str) -> None:
        row = _mover(_rows("b31", scenario), ref)
        assert (row["exposure_class"], row["approach"]) == (_QRRE, "advanced_irb")

    def test_crr_mover_takes_the_flat_qrre_correlation(self, scenario: str, ref: str) -> None:
        row = _mover(_rows("crr", scenario), ref)
        assert row["correlation"] == pytest.approx(QRRE_CORRELATION, rel=1e-12)

    def test_b31_mover_takes_the_flat_qrre_correlation(self, scenario: str, ref: str) -> None:
        row = _mover(_rows("b31", scenario), ref)
        assert row["correlation"] == pytest.approx(QRRE_CORRELATION, rel=1e-12)

    def test_crr_mover_rwa(self, scenario: str, ref: str) -> None:
        row = _mover(_rows("crr", scenario), ref)
        assert row["rwa"] == pytest.approx(SCENARIOS[scenario].crr_qrre_rwa, rel=1e-8)

    def test_b31_mover_rwa(self, scenario: str, ref: str) -> None:
        row = _mover(_rows("b31", scenario), ref)
        assert row["rwa"] == pytest.approx(SCENARIOS[scenario].b31_qrre_rwa, rel=1e-8)

    def test_crr_mover_rwa_is_not_the_pre_fix_basis(self, scenario: str, ref: str) -> None:
        """Anti-confound: the two bases are at least 14% apart in every scenario."""
        row = _mover(_rows("crr", scenario), ref)
        assert row["rwa"] != pytest.approx(SCENARIOS[scenario].crr_other_rwa, rel=1e-3)

    def test_b31_mover_rwa_is_not_the_pre_fix_basis(self, scenario: str, ref: str) -> None:
        """Anti-confound: the two bases are at least 14% apart in every scenario."""
        row = _mover(_rows("b31", scenario), ref)
        assert row["rwa"] != pytest.approx(SCENARIOS[scenario].b31_other_rwa, rel=1e-3)


@pytest.mark.parametrize("ref", _MOVERS)
class TestBasel31QrreFloorsBind:
    """FLOORS, Basel 3.1: admission brings the QRRE unsecured LGD floor
    (Art. 164(4)), which binds at an own LGD of 0.30 and is why this scenario
    RAISES Basel 3.1 RWA while it lowers CRR's (CRR has no retail LGD floor)."""

    def test_b31_mover_lgd_is_floored_at_the_qrre_unsecured_floor(self, ref: str) -> None:
        pack = RulepackV0.from_config(_config("b31")).pack
        floor = float(pack.formula("lgd_floors").params["retail_qrre_unsecured"])
        assert floor > SCENARIOS["floors"].lgd, "the floor must bind or this proves nothing"
        assert _mover(_rows("b31", "floors"), ref)["lgd_floored"] == pytest.approx(floor, rel=1e-12)

    def test_crr_mover_keeps_its_own_lgd(self, ref: str) -> None:
        row = _mover(_rows("crr", "floors"), ref)
        assert row["lgd_floored"] == pytest.approx(SCENARIOS["floors"].lgd, rel=1e-12)


# =============================================================================
# 2. EAD conservation — per regime, SEPARATELY. Green on both sides.
# =============================================================================


@pytest.mark.parametrize("scenario", list(SCENARIOS))
class TestEADConservation:
    """RWA moves; EAD does not (LESSONS C7). Absolute, pre-fix-measured totals."""

    def test_crr_total_ead_is_unchanged(self, scenario: str) -> None:
        assert _rows("crr", scenario)["ead_final"].sum() == pytest.approx(TOTAL_EAD_CRR, rel=1e-12)

    def test_b31_total_ead_is_unchanged(self, scenario: str) -> None:
        assert _rows("b31", scenario)["ead_final"].sum() == pytest.approx(TOTAL_EAD_B31, rel=1e-12)

    def test_crr_mover_ead_is_its_drawn_amount(self, scenario: str) -> None:
        rows = _rows("crr", scenario).filter(pl.col("exposure_reference").is_in(_MOVERS))
        assert rows["ead_final"].to_list() == pytest.approx([NRL_DRAWN, NRL_DRAWN], rel=1e-12)

    def test_b31_mover_ead_is_its_drawn_amount(self, scenario: str) -> None:
        rows = _rows("b31", scenario).filter(pl.col("exposure_reference").is_in(_MOVERS))
        assert rows["ead_final"].to_list() == pytest.approx([NRL_DRAWN, NRL_DRAWN], rel=1e-12)

    def test_crr_only_retail_classes_are_present(self, scenario: str) -> None:
        assert set(_rows("crr", scenario)["exposure_class"]) <= {_QRRE, _RETAIL_OTHER}

    def test_b31_only_retail_classes_are_present(self, scenario: str) -> None:
        assert set(_rows("b31", scenario)["exposure_class"]) <= {_QRRE, _RETAIL_OTHER}


# =============================================================================
# 3. The Basel 3.1 output floor (LESSONS D1).
# =============================================================================


@pytest.mark.parametrize("scenario", list(SCENARIOS))
class TestOutputFloorSAEquivalentDoesNotMove:
    """Green on both sides: the SA-equivalent risk weight reads neither retail
    sub-class (the SA ladder gates on the ``RETAIL`` substring and the 45%
    transactor limb on ``is_qrre_transactor``, False throughout), so the floor's
    SA legs cannot fall with the modelled charge."""

    def test_b31_s_trea_is_unchanged(self, scenario: str) -> None:
        summary = _run("b31", scenario).output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(S_TREA_B31, rel=1e-12)

    def test_b31_sa_routed_total_is_unchanged(self, scenario: str) -> None:
        summary = _run("b31", scenario).output_floor_summary
        assert summary is not None
        assert summary.sa_rwa_total == pytest.approx(SA_RWA_TOTAL_B31, rel=1e-12)

    def test_b31_u_trea_is_the_sa_book_plus_the_movers_modelled_rwa(self, scenario: str) -> None:
        """U-TREA is the whole book's own RWEA: the SA-routed rows' plus the
        movers', the portfolio's only IRB rows. FAILS PRE-FIX."""
        summary = _run("b31", scenario).output_floor_summary
        assert summary is not None
        expected = SA_RWA_TOTAL_B31 + 2 * SCENARIOS[scenario].b31_qrre_rwa
        assert summary.u_trea == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
class TestOutputFloorStaysSlack:
    """Basel 3.1: the SA-routed remainder keeps U-TREA above the floor threshold
    on both sides of the fix, in every scenario, so the post-floor total moves
    by the full modelled change — LOW 418,574.24 -> 388,122.44, HIGH
    464,257.53 -> 480,560.66, FLOORS 404,423.63 -> 411,670.75 (measured)."""

    def test_b31_portfolio_floor_does_not_bind(self, scenario: str) -> None:
        summary = _run("b31", scenario).output_floor_summary
        assert summary is not None
        assert summary.portfolio_floor_binding is False

    def test_b31_post_floor_total_is_the_sa_book_plus_the_movers(self, scenario: str) -> None:
        """FAILS PRE-FIX: the movers are priced as other retail there."""
        summary = _run("b31", scenario).output_floor_summary
        assert summary is not None
        expected = SA_RWA_TOTAL_B31 + 2 * SCENARIOS[scenario].b31_qrre_rwa
        assert summary.total_rwa_post_floor == pytest.approx(expected, rel=1e-9)


# =============================================================================
# 4. A duplicated facility reference (DQ004) — the root join copies no leg.
#    Review objection to the first attempt: a plain join on a repeated root
#    copied every leg under it and doubled the portfolio's EAD.
# =============================================================================


def _neutral_root_join(
    exposures: pl.LazyFrame, facilities: pl.LazyFrame | None, fx: object
) -> pl.LazyFrame:
    """The hierarchy as it was before the root join existed: typed nulls, no join."""
    return exposures.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("root_facility_limit"),
        pl.lit(None, dtype=pl.Float64).alias("root_facility_utilisation"),
    )


def _sa_config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, enforce_retail_granularity=False
    )


def _duplicate_rows(regime: str) -> pl.DataFrame:
    return (
        PipelineOrchestrator()
        .run_with_data(build_p1_355_duplicate_bundle(), _sa_config(regime))
        .results.collect()
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
class TestDuplicateFacilityReferenceConservesEAD:
    """Through the whole pipeline, per regime: the duplicated root's loans are
    one row each at their drawn amount (absolute), and the portfolio has the
    same rows and the same EAD as with the root join replaced by typed nulls —
    the duplicated single-level facility's rows included, which the
    IMMEDIATE-parent join already copies (pre-existing; not this item's)."""

    def test_each_loan_under_the_duplicated_root_is_one_row_at_its_drawn_amount(
        self, regime: str
    ) -> None:
        rows = _duplicate_rows(regime).filter(
            pl.col("exposure_reference").is_in([LN_DUP_A, LN_DUP_B])
        )
        assert sorted(rows["exposure_reference"]) == [LN_DUP_A, LN_DUP_B]
        assert rows["ead_final"].to_list() == pytest.approx([DUP_DRAWN, DUP_DRAWN], rel=1e-12)

    def test_rows_and_ead_match_the_hierarchy_without_the_root_join(
        self, regime: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live = _duplicate_rows(regime)
        monkeypatch.setattr(enrich_module, "_join_root_facility_limit", _neutral_root_join)
        neutral = _duplicate_rows(regime)
        assert Counter(live["exposure_reference"]) == Counter(neutral["exposure_reference"])
        assert live["ead_final"].sum() == pytest.approx(neutral["ead_final"].sum(), rel=1e-12)

    def test_the_duplicated_single_level_facility_is_in_the_portfolio(self, regime: str) -> None:
        """Adequacy: the comparison above covers the single-level shape too."""
        assert LN_DUPS in set(_duplicate_rows(regime)["exposure_reference"])
