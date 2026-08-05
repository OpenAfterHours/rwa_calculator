"""
Unit tests for the D8 Pillar 3 CR7-A collateral-ratio cap defect.

``reporting/pillar3/cr7a.py:111-112`` binds every collateral column (b
financial, d immovable property, e receivables, f other physical) as a bare
``Ratio(source, "reporting_ead", scale=100.0)`` -- ``sum(numerator) /
sum(denominator) x100`` over the row's whole exposure subset, with no cap.

PS1/26 Annex XXII col d (``ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf``
p.11), verbatim: "For the FIRB approach, immovable property collateral ...
calculated as Ci, after the application of volatility adjustments and a
maturity mismatch adjustment if relevant ... and shall be capped at the
individual exposure value. For the AIRB approach: immovable property
collateral recognised under the LGD modelling collateral method. The amount
to be included in the numerator shall be the estimated market value of the
collateral, capped at the individual exposure value." The same clause repeats
for cols b, e, f. The CRR Pillar 3 IRB instructions
(``crr-pillar3-irb-credit-risk-instructions.pdf`` pp.9-11) state it as "The
value of collateral disclosed shall be limited to the value of the exposure
at the level of an individual exposure."

The cap is per INDIVIDUAL EXPOSURE, applied before the numerator is summed --
capping the aggregate numerator against the aggregate denominator is a
different (and wrong) computation, since it lets one over-collateralised
exposure subsidise an under-collateralised one on the same row. That
per-exposure-vs-aggregate distinction is the substance of this defect, and is
what ``TestCapIsPerExposureNotAggregate`` below pins.

Live evidence: the committed golden
``tests/expected_outputs/reporting/irb_classes_crr/pillar3__cr7a__advanced_irb.ndjson``
publishes col d = 166.67% (500,000 collateral / 300,000 EAD) on the
retail_mortgage row -- a breach of the "capped at the individual exposure
value" instruction.

References:
    PRA PS1/26 Annex XXII (CR7-A instructions), cols b/c/d/e/f
    CRR Pillar 3 IRB credit risk instructions, cols b/c/d/e/f
    docs/plans/irb-collateral-corep-reporting.md, RD-2 (revised) / D8
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# =============================================================================
# Helpers
# =============================================================================


def _airb_row(
    ref: str,
    ead: float,
    *,
    exposure_class: str = "retail_mortgage",
    approach: str = "advanced_irb",
    collateral_financial_value: float = 0.0,
    collateral_re_value: float = 0.0,
    collateral_receivables_value: float = 0.0,
    collateral_other_physical_value: float = 0.0,
    rwa: float = 0.0,
) -> dict:
    """One CR7-A-shaped exposure row (mirrors test_cr6_cr7.py's minimal shape,
    extended with the four collateral disclosure carriers)."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": f"CP_{ref}",
        "approach_applied": approach,
        "exposure_class": exposure_class,
        "ead_final": ead,
        "rwa_final": rwa,
        "drawn_amount": ead,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "undrawn_amount": 0.0,
        "exposure_type": "loan",
        "collateral_financial_value": collateral_financial_value,
        "collateral_re_value": collateral_re_value,
        "collateral_receivables_value": collateral_receivables_value,
        "collateral_other_physical_value": collateral_other_physical_value,
    }


def _make_frame(rows: list[dict]) -> pl.LazyFrame:
    return pl.LazyFrame(rows)


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


# =============================================================================
# 1. Single over-collateralised exposure must cap at 100%
# =============================================================================


class TestSingleExposureCap:
    """D8 assertion #1: an over-collateralised A-IRB exposure caps col d at 100%."""

    def test_re_ratio_capped_at_100_not_166_67(self, generator: Pillar3Generator) -> None:
        """Retail mortgage, EAD=300,000, RE collateral=500,000 -- exactly the
        committed golden's 166.67% figure, uncapped today."""
        # Arrange
        data = _make_frame([_airb_row("EXP1", ead=300_000.0, collateral_re_value=500_000.0)])

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="CRR")

        # Assert
        airb = bundle.cr7a["advanced_irb"]
        row = airb.filter(pl.col("row_ref") == "3")  # retail_mortgage
        assert row["d"][0] == pytest.approx(100.0, rel=1e-6)


# =============================================================================
# 2. The cap is per-exposure, not aggregate
# =============================================================================


class TestCapIsPerExposureNotAggregate:
    """D8 assertion #2: capping the summed numerator against the summed
    denominator is NOT the same computation as capping each exposure before
    summation -- this is the test that distinguishes a correct fix from a
    lazy one."""

    def test_mixed_over_and_under_collateralised_yields_50_pct_not_75_pct(
        self, generator: Pillar3Generator
    ) -> None:
        """EXP_OVER: 500k RE collateral / 300k EAD (over-collateralised).
        EXP_UNDER: 100k RE collateral / 500k EAD (under-collateralised).
        Both retail_mortgage, same row.

        Correct (per-exposure cap): (min(500k,300k) + min(100k,500k)) /
        (300k + 500k) x100 = (300k + 100k) / 800k x100 = 50.0%.

        A naive AGGREGATE cap -- min(sum(num), sum(den)) / sum(den) -- gives
        min(600k, 800k) / 800k x100 = 75.0%, identical to today's fully
        uncapped result (600k < 800k, so the aggregate cap never even binds).
        Both the uncapped and the aggregate-capped computation are wrong;
        only the per-exposure cap yields 50.0%.
        """
        # Arrange
        data = _make_frame(
            [
                _airb_row("EXP_OVER", ead=300_000.0, collateral_re_value=500_000.0),
                _airb_row("EXP_UNDER", ead=500_000.0, collateral_re_value=100_000.0),
            ]
        )

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="CRR")

        # Assert
        airb = bundle.cr7a["advanced_irb"]
        row = airb.filter(pl.col("row_ref") == "3")
        assert row["d"][0] == pytest.approx(50.0, rel=1e-6)


# =============================================================================
# 3. Cols b, e, f carry the same cap
# =============================================================================


class TestOtherCollateralColumnsAlsoCapped:
    """D8 assertion #3: cols b (financial), e (receivables) and f (other
    physical) carry the identical per-exposure cap as col d."""

    @pytest.mark.parametrize(
        ("column_ref", "collateral_field"),
        [
            ("b", "collateral_financial_value"),
            ("e", "collateral_receivables_value"),
            ("f", "collateral_other_physical_value"),
        ],
    )
    def test_column_capped_at_100_pct(
        self, generator: Pillar3Generator, column_ref: str, collateral_field: str
    ) -> None:
        # Arrange
        # Dict-merge rather than ``**kwargs`` unpacking: a dynamically-keyed
        # mapping cannot be matched against named parameters by the checker.
        row = _airb_row("EXP1", ead=300_000.0) | {collateral_field: 500_000.0}
        data = _make_frame([row])

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="CRR")

        # Assert
        airb = bundle.cr7a["advanced_irb"]
        row = airb.filter(pl.col("row_ref") == "3")
        assert row[column_ref][0] == pytest.approx(100.0, rel=1e-6)


# =============================================================================
# 4. Col c = d + e + f continues to hold on the capped values
# =============================================================================


class TestColumnCIsSumOfCappedComponents:
    """D8 assertion #4: col c (= d + e + f) must hold on the CAPPED values.

    Structural note: c is wired as ``Formula(refs=("d", "e", "f"))``, so it
    always reads whatever d/e/f already resolved to -- this identity holds
    regardless of whether a cap exists. This test is therefore expected to
    PASS both before and after the fix; it is included as the invariant the
    fix must not break, per the proposal's requirement.
    """

    def test_c_equals_capped_d_plus_e_plus_f(self, generator: Pillar3Generator) -> None:
        """All three components over-collateralised -> each caps to 100% ->
        c = 100 + 100 + 100 = 300%."""
        # Arrange
        data = _make_frame(
            [
                _airb_row(
                    "EXP1",
                    ead=300_000.0,
                    collateral_re_value=500_000.0,
                    collateral_receivables_value=400_000.0,
                    collateral_other_physical_value=350_000.0,
                )
            ]
        )

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="CRR")

        # Assert
        airb = bundle.cr7a["advanced_irb"]
        row = airb.filter(pl.col("row_ref") == "3")
        d, e, f, c = row["d"][0], row["e"][0], row["f"][0], row["c"][0]
        assert c == pytest.approx(d + e + f, rel=1e-6)


# =============================================================================
# 5. The FIRB limb carries the same cap (the instruction repeats identically
#    for both approaches)
# =============================================================================


class TestCapAppliesOnBothApproachLimbs:
    """PS1/26 Annex XXII col d states the cap for BOTH the FIRB and the AIRB
    limb; cr7a.py binds both sub-templates through the identical
    ``_row_cells``/``_PCT_SOURCES`` code path, so the defect (and the fix)
    apply uniformly -- pinned here on the FIRB sheet specifically."""

    def test_firb_re_ratio_capped_at_100(self, generator: Pillar3Generator) -> None:
        # Arrange
        data = _make_frame(
            [
                _airb_row(
                    "EXP1",
                    ead=300_000.0,
                    collateral_re_value=500_000.0,
                    exposure_class="corporate",
                    approach="foundation_irb",
                )
            ]
        )

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="CRR")

        # Assert
        firb = bundle.cr7a["foundation_irb"]
        row = firb.filter(pl.col("row_ref") == "4")  # Corporates — Other
        assert row["d"][0] == pytest.approx(100.0, rel=1e-6)


# =============================================================================
# 6. Regression: an under-collateralised exposure is unaffected by the cap
# =============================================================================


class TestUnderCollateralisedExposureUnaffected:
    """D8 assertion #6: an under-collateralised exposure's ratio is unchanged
    by the cap (regression guard -- passes both before and after the fix)."""

    def test_under_collateralised_ratio_unchanged(self, generator: Pillar3Generator) -> None:
        # Arrange
        data = _make_frame([_airb_row("EXP1", ead=500_000.0, collateral_re_value=100_000.0)])

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="CRR")

        # Assert
        airb = bundle.cr7a["advanced_irb"]
        row = airb.filter(pl.col("row_ref") == "3")
        assert row["d"][0] == pytest.approx(20.0, rel=1e-6)
