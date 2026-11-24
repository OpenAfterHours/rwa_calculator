"""
P1.210: Art. 159 pool composition ('B' vs 'D') and the 'all other cases' net.

PS1/26 Art. 159(1) (UK CRR Art. 159 states the same ring-fence in one paragraph):

    'B' = (i) general credit risk adjustments; (ii) specific credit risk
          adjustments for non-defaulted exposures; (iii) additional value
          adjustments; (iv) other own funds reductions.
    'D' = specific credit risk adjustments for defaulted exposures.

PS1/26 Art. 159(3): "Where 'A' > 'B' and 'D' > 'C'" the institution reports
'B' - 'A' (negative) and 'D' - 'C' (positive) separately. "In all other cases"
it reports ONE figure, ('B' + 'D') - ('A' + 'C'): negative under (c), positive
under (d).

So 'D' holds defaulted SPECIFIC credit risk adjustments only. A general credit
risk adjustment allocated to a defaulted exposure, and the AVAs and other own
funds reductions on a defaulted exposure, all belong in 'B'. The carrier that
separates the two kinds of provision is ``provision_specific_allocated``
(``engine/crm/provisions.py``, P1.208): ``provision_type`` ``scra`` in any case,
or NULL. ``provision_allocated`` is every provision row. A frame that does not
carry the specific carrier at all (or carries a null on a row) counts the
row's whole ``provision_allocated`` as specific — the documented default for an
untyped book.

The unit under test is regime-agnostic (no config); both regimes are exercised
end to end in ``tests/acceptance/test_p1_210_art_159_pool_d_gcra_pipeline.py``.

References:
- PS1/26 Art. 159(1), (3); UK CRR Art. 159
- CRR Art. 36(1)(d): CET1 deduction of the shortfall
- CRR Art. 62(d): T2 credit for the excess, capped at 0.6% of IRB RWA
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary


def _two_row_frame(
    *,
    el: tuple[float, float],
    provision_allocated: tuple[float, float],
    provision_specific_allocated: tuple[float | None, float | None] | None,
    ava: tuple[float, float] = (0.0, 0.0),
    other_ofr: tuple[float, float] = (0.0, 0.0),
) -> pl.LazyFrame:
    """One non-defaulted row and one defaulted row, 10m of IRB RWA in total.

    The per-row ``el_shortfall`` / ``el_excess`` audit columns are written as
    ``max(0, EL - pool_b)`` / ``max(0, pool_b - EL)`` over the row's own
    provisions + AVA + other own funds reductions, as ``irb/adjustments.py``
    writes them; the summary recomputes from the pool aggregates.
    """
    pool_b = [p + a + o for p, a, o in zip(provision_allocated, ava, other_ofr, strict=True)]
    data: dict[str, object] = {
        "exposure_reference": ["ND_001", "DEF_001"],
        "approach_applied": ["AIRB", "AIRB"],
        "rwa_post_factor": [5_000_000.0, 5_000_000.0],
        "expected_loss": list(el),
        "provision_allocated": list(provision_allocated),
        "ava_amount": list(ava),
        "other_own_funds_reductions": list(other_ofr),
        "el_shortfall": [max(0.0, e - b) for e, b in zip(el, pool_b, strict=True)],
        "el_excess": [max(0.0, b - e) for e, b in zip(el, pool_b, strict=True)],
        "is_defaulted": [False, True],
    }
    schema: dict[str, pl.DataType] = {}
    if provision_specific_allocated is not None:
        data["provision_specific_allocated"] = list(provision_specific_allocated)
        schema["provision_specific_allocated"] = pl.Float64()
    return pl.LazyFrame(data, schema_overrides=schema)


class TestPoolDHoldsDefaultedSpecificOnly:
    """'D' = defaulted SPECIFIC CRA; defaulted GCRA, AVA and OFR go to 'B'."""

    def test_defaulted_gcra_moves_to_pool_b_and_nets(self) -> None:
        """A GCRA on a defaulted exposure is 'B'(i), so the books net to zero.

        Arrange:
            Non-defaulted: A = 100,000; specific CRA 95,000.
            Defaulted:     C = 50,000; specific CRA 45,000 plus a 10,000
                           general CRA on the same exposure
                           (provision_allocated 55,000, specific 45,000).
        Rule:
            B = 95,000 + 10,000 = 105,000; D = 45,000.
            A > B is false, so "all other cases": (B + D) - (A + C)
            = 150,000 - 150,000 = 0 -> no shortfall, no excess.
        HEAD (D = 55,000, B = 95,000): two-branch, shortfall 5,000 and
        excess 5,000.
        """
        # Arrange
        frame = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(95_000.0, 55_000.0),
            provision_specific_allocated=(95_000.0, 45_000.0),
        )

        # Act
        result = compute_el_portfolio_summary(frame)

        # Assert
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(0.0, abs=1e-6)
        assert float(result.total_el_excess) == pytest.approx(0.0, abs=1e-6)
        assert float(result.cet1_deduction) == pytest.approx(0.0, abs=1e-6)
        assert float(result.t2_credit) == pytest.approx(0.0, abs=1e-6)

    def test_ring_fence_survives_the_type_split(self) -> None:
        """Defaulted SPECIFIC CRA stays in 'D' and still cannot cover 'A'.

        Arrange:
            Non-defaulted: A = 100,000; specific CRA 80,000.
            Defaulted:     C = 50,000; specific CRA 70,000 plus a 10,000
                           general CRA on the same exposure.
        Rule:
            B = 80,000 + 10,000 = 90,000; D = 70,000.
            A > B and D > C -> Art. 159(3)(a)/(b):
                shortfall = A - B = 10,000; excess = D - C = 20,000.
        HEAD (B = 80,000, D = 80,000): shortfall 20,000, excess 30,000.
        An implementation that sent every defaulted provision to 'B' would
        net to an excess of 10,000 and no shortfall — removing the ring-fence.
        """
        # Arrange
        frame = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(80_000.0, 80_000.0),
            provision_specific_allocated=(80_000.0, 70_000.0),
        )

        # Act
        result = compute_el_portfolio_summary(frame)

        # Assert
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(10_000.0)
        assert float(result.defaulted_el_excess) == pytest.approx(20_000.0)
        assert float(result.total_el_shortfall) == pytest.approx(10_000.0)
        assert float(result.total_el_excess) == pytest.approx(20_000.0)
        assert float(result.cet1_deduction) == pytest.approx(10_000.0)
        assert float(result.t2_credit) == pytest.approx(20_000.0)

    def test_defaulted_ava_and_other_ofr_belong_to_pool_b(self) -> None:
        """'B'(iii) AVAs and 'B'(iv) other own funds reductions are never 'D'.

        Arrange (all provisions specific):
            Non-defaulted: A = 50,000; specific CRA 20,000; AVA 10,000.
            Defaulted:     C = 10,000; specific CRA 30,000; AVA 5,000;
                           other own funds reductions 2,000.
        Rule:
            B = 20,000 + 10,000 + 5,000 + 2,000 = 37,000; D = 30,000.
            A > B and D > C -> shortfall = 13,000; excess = 20,000.
        HEAD (D = 37,000, B = 30,000): shortfall 20,000, excess 27,000.
        """
        # Arrange
        frame = _two_row_frame(
            el=(50_000.0, 10_000.0),
            provision_allocated=(20_000.0, 30_000.0),
            provision_specific_allocated=(20_000.0, 30_000.0),
            ava=(10_000.0, 5_000.0),
            other_ofr=(0.0, 2_000.0),
        )

        # Act
        result = compute_el_portfolio_summary(frame)

        # Assert
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.total_el_shortfall) == pytest.approx(13_000.0)
        assert float(result.total_el_excess) == pytest.approx(20_000.0)
        assert float(result.total_pool_b) == pytest.approx(67_000.0)

    def test_untyped_provisions_on_a_defaulted_exposure_stay_in_pool_d(self) -> None:
        """No specific carrier (or a null on the row) -> the whole provision is 'D'.

        The owner-visible default for an untyped book: a provision with no
        stated type is specific (P1.208, ``provisions.py::_specific_amount``),
        so it is ring-fenced. Same inputs as the ring-fence case, without the
        split: B = 80,000, D = 80,000 -> A > B and D > C ->
        shortfall 20,000, excess 30,000.
        """
        # Arrange
        absent = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(80_000.0, 80_000.0),
            provision_specific_allocated=None,
        )
        null_on_row = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(80_000.0, 80_000.0),
            provision_specific_allocated=(80_000.0, None),
        )

        # Act
        results = [compute_el_portfolio_summary(absent), compute_el_portfolio_summary(null_on_row)]

        # Assert
        for result in results:
            assert result is not None
            assert result.art_159_3_applies is True
            assert float(result.total_el_shortfall) == pytest.approx(20_000.0)
            assert float(result.total_el_excess) == pytest.approx(30_000.0)


class TestAllOtherCasesNet:
    """Outside A > B and D > C, Art. 159(3)(c)/(d) report ONE net figure."""

    def test_non_defaulted_surplus_covers_defaulted_gap(self) -> None:
        """A <= B and D <= C: one net excess, never a shortfall and an excess.

        Arrange: A = 100,000 / B = 130,000; C = 50,000 / D = 40,000.
        Rule: (B + D) - (A + C) = 170,000 - 150,000 = +20,000 -> (d) excess.
        HEAD: shortfall 10,000 (C - D) AND excess 30,000 (B - A).
        """
        # Arrange
        frame = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(130_000.0, 40_000.0),
            provision_specific_allocated=(130_000.0, 40_000.0),
        )

        # Act
        result = compute_el_portfolio_summary(frame)

        # Assert
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(0.0, abs=1e-6)
        assert float(result.total_el_excess) == pytest.approx(20_000.0)
        assert float(result.cet1_deduction) == pytest.approx(0.0, abs=1e-6)
        assert float(result.t2_credit) == pytest.approx(20_000.0)

    def test_defaulted_gap_larger_than_non_defaulted_surplus(self) -> None:
        """A <= B and D <= C with a net gap: one net shortfall, no excess.

        Arrange: A = 100,000 / B = 110,000; C = 50,000 / D = 20,000.
        Rule: (B + D) - (A + C) = 130,000 - 150,000 = -20,000 -> (c) shortfall.
        HEAD: shortfall 30,000 (C - D) AND excess 10,000 (B - A).
        """
        # Arrange
        frame = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(110_000.0, 20_000.0),
            provision_specific_allocated=(110_000.0, 20_000.0),
        )

        # Act
        result = compute_el_portfolio_summary(frame)

        # Assert
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.total_el_excess) == pytest.approx(0.0, abs=1e-6)
        assert float(result.cet1_deduction) == pytest.approx(20_000.0)
        assert float(result.t2_credit) == pytest.approx(0.0, abs=1e-6)

    def test_per_pool_figures_stay_gross(self) -> None:
        """The four pool-level fields report each pool's own comparison.

        Only the effective totals are netted; ``non_defaulted_el_excess`` and
        ``defaulted_el_shortfall`` still say B - A = 30,000 and C - D = 10,000
        for the A <= B, D <= C case above, so the pools stay auditable.
        """
        # Arrange
        frame = _two_row_frame(
            el=(100_000.0, 50_000.0),
            provision_allocated=(130_000.0, 40_000.0),
            provision_specific_allocated=(130_000.0, 40_000.0),
        )

        # Act
        result = compute_el_portfolio_summary(frame)

        # Assert
        assert result is not None
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(0.0, abs=1e-6)
        assert float(result.non_defaulted_el_excess) == pytest.approx(30_000.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(10_000.0)
        assert float(result.defaulted_el_excess) == pytest.approx(0.0, abs=1e-6)
