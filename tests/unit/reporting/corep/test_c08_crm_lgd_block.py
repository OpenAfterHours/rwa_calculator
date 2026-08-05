"""
Unit tests for the W6 COREP C 08.01/02 CRM-in-LGD block defect (cols
0060/0171/0172/0173/0180/0190/0200/0210).

``reporting/corep/c08.py::_value_cells`` (``:836-839``) binds cols
0180/0190/0200/0210 to the RAW ``collateral_*_value`` carriers, which report
the FIRB/Foundation-Collateral-Method (post-haircut, adjusted) basis on every
row -- including A-IRB rows, where PS1/26 Annex II / CRR Annex II require the
estimated MARKET value instead (D2). W5 seals the method-resolved value once,
in the engine, as four ``reporting_crm_lgd_*`` carriers; this file drives the
W6 fix that repoints ``_value_cells`` at them. C 08.01 and C 08.02 share
``_value_cells``, so both move together -- a live ERROR-rule family
(``boe_b0752_18..21``, ``boe_b0814_14..17``) ties
``{OF08.01 r0070, cNNNN} = sum({OF08.02, cNNNN})``.

Cols 0171/0172/0173 are today hardcoded ``_const(0.0)`` (D6). PS1/26 col 0060
(p.103), verbatim: "Other funded credit protection that is treated as a
guarantee in accordance with Article 232 ... shall be included [in 0060].
... Other funded credit protection recognised by firms applying the AIRB
approach and using the LGD Modelling Collateral Method shall be reported in
columns 0171, 0172 and 0173." The two routes are mutually exclusive per leg.

RD-8 (``docs/plans/irb-collateral-corep-reporting.md``): the routing
decision between the two routes depends on the run-level
``AIRBCollateralMethod`` election, which does not reach the COREP generator
(``generate_c08_01`` and siblings receive only
``(results, cols, framework, errors)`` -- no config, no resolved_pack, no
per-row method flag). Re-deriving the election in ``reporting/`` would put a
regulatory decision in the presentation layer, so ``engine/crm/`` -- which
already holds the config and pack -- makes the decision ONCE and seals three
carriers that are mutually exclusive BY CONSTRUCTION:

    engine carrier                sealed as                        cell
    ofcp_lgd_cash_deposit    ->   reporting_ofcp_lgd_cash_deposit   0171
    ofcp_lgd_life_insurance  ->   reporting_ofcp_lgd_life_insurance 0172
    ofcp_substitution_amount ->   reporting_ofcp_substitution       0060

Both LGD carriers are capped at the exposure value (PS1/26 p.107, "The value
of collateral reported shall be limited to the value of the exposure at the
level of an individual exposure") -- INSIDE engine/crm/, before the seal, so
COREP's binding is a plain ``Sum()`` with no cap logic of its own. Col 0173
(Art. 200(1)(c)) has no engine carrier and stays the recorded constant 0.0.

Test-frame convention: these fixtures pre-supply the sealed
``reporting_crm_lgd_*`` / ``reporting_ofcp_*`` carriers DIRECTLY (as the
module docstring's Pipeline position states -- "sealed aggregator-exit
ledger -> ... -> TemplateSpecs"), isolating the W6 binding fix from the
separate W5/RD-8 aggregator-seal fix (which
``tests/unit/engine/aggregator/test_crm_lgd_reporting_seal.py`` drives).
This mirrors the established convention elsewhere in this file's cluster
(e.g. ``post_crm_exposure_class_guaranteed`` pre-supplied directly in
``test_c08_crm_substitution.py``'s fixtures).

References:
    PRA PS1/26 Annex II, OF 08.01 cols 0150-0173/0180-0210
        (docs/assets/ps1-26-annex-ii-reporting-instructions.pdf p.102-109)
    CRR Annex II, C 08.01 cols 0150-0210
        (docs/assets/crr-annex-ii-reporting-instructins.pdf p.99-102)
    docs/plans/irb-collateral-corep-reporting.md, RD-1/RD-2/RD-3/RD-8, D2/D6, W6
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row

# =============================================================================
# Fixtures
# =============================================================================


def _airb_b31_row_with_lgd_collateral() -> pl.LazyFrame:
    """One A-IRB corporate leg on the LGD Modelling Collateral Method route
    (RD-8): its Art. 200(1)(a)/(b) amounts are ALREADY routed and capped by
    ``engine/crm/`` into the two LGD carriers; ``reporting_ofcp_substitution``
    is 0.0 -- proving 0060 does not pick up money that belongs on 0171/0172.

    reporting_crm_lgd_* values are distinct and nonzero per category so a
    "one column reads another's value" bug cannot pass by coincidence.
    reporting_crm_lgd_real_estate=500,000 vs ead_final=300,000 proves col
    0190 carries NO cap (RD-2) -- unrelated to the 0171/0172 block, which is
    already-capped-in-engine by the time it reaches this fixture.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["AIRB_1"],
            "approach_applied": ["advanced_irb"],
            "exposure_class": ["corporate"],
            "drawn_amount": [2_000_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [300_000.0],
            "rwa_final": [150_000.0],
            "risk_weight": [0.50],
            "pd_floored": [0.01],
            "lgd_floored": [0.12],
            "irb_maturity_m": [2.5],
            "expected_loss": [5.0],
            "scra_provision_amount": [0.0],
            "gcra_provision_amount": [0.0],
            "counterparty_reference": ["CP_A"],
            "reporting_crm_lgd_financial": [80_000.0],
            "reporting_crm_lgd_real_estate": [500_000.0],
            "reporting_crm_lgd_other_physical": [60_000.0],
            "reporting_crm_lgd_receivables": [40_000.0],
            # RD-8: engine/crm/ already resolved the Art. 200(1) route and
            # capped at the exposure -- COREP just reads these three plain.
            "reporting_ofcp_lgd_cash_deposit": [300_000.0],
            "reporting_ofcp_lgd_life_insurance": [100_000.0],
            "reporting_ofcp_substitution": [0.0],
        }
    )


def _firb_row_with_lgd_collateral() -> pl.LazyFrame:
    """The mirror leg: ``engine/crm/`` routed its Art. 200(1) amount
    entirely into the Art. 232 substitution carrier. Narrated as a FIRB leg
    for realism, but under RD-8 COREP does not need to know WHY the engine
    chose this route (FIRB, or an A-IRB leg on the FOUNDATION election, or
    any CRR leg) -- only that it did, via which of the three sealed
    carriers is nonzero."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["FIRB_1"],
            "approach_applied": ["foundation_irb"],
            "exposure_class": ["corporate"],
            "drawn_amount": [2_000_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [300_000.0],
            "rwa_final": [150_000.0],
            "risk_weight": [0.50],
            "pd_floored": [0.01],
            "lgd_floored": [0.45],
            "irb_maturity_m": [2.5],
            "expected_loss": [5.0],
            "scra_provision_amount": [0.0],
            "gcra_provision_amount": [0.0],
            "counterparty_reference": ["CP_B"],
            "reporting_crm_lgd_financial": [80_000.0],
            "reporting_crm_lgd_real_estate": [300_000.0],
            "reporting_crm_lgd_other_physical": [60_000.0],
            "reporting_crm_lgd_receivables": [40_000.0],
            "reporting_ofcp_lgd_cash_deposit": [0.0],
            "reporting_ofcp_lgd_life_insurance": [0.0],
            "reporting_ofcp_substitution": [600_000.0],
        }
    )


# =============================================================================
# 1. Cols 0180/0190/0200/0210 read the sealed carriers, no cap
# =============================================================================


class TestSealedCarriersDriveColumns0180To0210:
    """W6 assertions #5/#6/#7: cols 0180/0190/0200/0210 read the sealed
    ``reporting_crm_lgd_*`` carriers, reproduce the AIRB market basis end to
    end, and carry NO cap (RD-2 -- contrast Pillar 3 CR7-A, which another
    agent IS capping; the two templates must stay divergent by instruction)."""

    def test_all_four_columns_read_the_sealed_carriers(self) -> None:
        """0180=financial, 0190=real estate, 0200=other physical, 0210=receivables."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0180"][0] == pytest.approx(80_000.0)
        assert total["0190"][0] == pytest.approx(500_000.0)
        assert total["0200"][0] == pytest.approx(60_000.0)
        assert total["0210"][0] == pytest.approx(40_000.0)

    def test_re_column_reproduces_airb_market_basis_under_both_regimes(self) -> None:
        """A 500,000 property publishes 500,000 under BOTH regimes once the
        AIRB market basis is sealed once at the aggregator -- the
        disappearance of the CRR-vs-B3.1 divergence (previously 500,000 vs
        300,000, the D2 golden evidence) is the proof the basis fix is right.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        crr_bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="CRR"
        )
        b31_bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )

        # Assert
        crr_total = _get_total_row(crr_bundle.c08_01["corporate"])
        b31_total = _get_total_row(b31_bundle.c08_01["corporate"])
        assert crr_total["0190"][0] == pytest.approx(500_000.0)
        assert b31_total["0190"][0] == pytest.approx(500_000.0)

    def test_re_column_is_not_capped_at_the_exposure_value(self) -> None:
        """RD-2: a 500,000 pledge against a 300,000 EAD publishes 500,000,
        NOT 300,000 -- no cap exists on 0180-0210 in either instruction PDF."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0190"][0] == pytest.approx(500_000.0)


# =============================================================================
# 2. Cols 0060/0171/0172/0173 -- structural exclusivity (RD-8)
# =============================================================================


class TestOtherFundedProtectionMethodRouting:
    """W6 assertions #8-11, revised under RD-8: ``engine/crm/`` makes the
    Art. 200(1) routing decision ONCE, sealing three carriers that are
    mutually exclusive BY CONSTRUCTION (``reporting_ofcp_lgd_cash_deposit``,
    ``reporting_ofcp_lgd_life_insurance``, ``reporting_ofcp_substitution``).
    COREP binds each with a plain ``Sum()`` -- no framework/approach gate
    lives in ``reporting/`` at all.

    This resolves the gap the previous revision of this file flagged (the
    AIRB-FOUNDATION-election sub-case, previously untestable at COREP): the
    election is now irrelevant to COREP by design -- whichever route
    ``engine/crm/`` chose, exactly one of the three sealed carriers is
    nonzero on a given leg, and COREP just reads it. The FOUNDATION-election
    case itself is tested at the seal, not here --
    ``tests/unit/engine/aggregator/test_crm_lgd_reporting_seal.py``.
    """

    def test_lgd_modelling_shaped_leg_reports_0171_and_0172(self) -> None:
        """reporting_ofcp_lgd_cash_deposit=300,000 -> 0171=300,000;
        reporting_ofcp_lgd_life_insurance=100,000 -> 0172=100,000."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0171"][0] == pytest.approx(300_000.0)
        assert total["0172"][0] == pytest.approx(100_000.0)

    def test_lgd_modelling_shaped_leg_col_0060_reads_zero(self) -> None:
        """Structural exclusivity: col 0060 binds ``reporting_ofcp_substitution``
        alone, which is 0.0 on this leg -- the nonzero 0171/0172 amounts
        alongside it must not leak into 0060 (the double count RD-3 forbids)."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0060"][0] == pytest.approx(0.0)

    def test_substitution_shaped_leg_col_0060_reports_the_guarantee_route(self) -> None:
        """reporting_ofcp_substitution=600,000 -> 0060=-600,000 (negated
        deduction column, unchanged mechanism -- regression pin)."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_firb_row_with_lgd_collateral(), framework="BASEL_3_1")
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0060"][0] == pytest.approx(-600_000.0)

    def test_substitution_shaped_leg_0171_0172_read_zero(self) -> None:
        """Structural exclusivity, mirrored: 0171/0172 bind their own LGD
        carriers alone, both 0.0 on this leg -- the nonzero substitution
        amount alongside them must not leak into 0171/0172."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_firb_row_with_lgd_collateral(), framework="BASEL_3_1")
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0171"][0] == pytest.approx(0.0)
        assert total["0172"][0] == pytest.approx(0.0)

    def test_binding_is_framework_invariant(self) -> None:
        """RD-8: the routing decision was already made in ``engine/crm/``
        before the ledger was sealed, so COREP's binding needs no framework
        check at all -- the substitution-shaped leg reports identically
        under CRR and Basel 3.1 (contrast the earlier, withdrawn design,
        where COREP itself had to gate on ``framework == BASEL_3_1``)."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        crr_bundle = gen.generate_from_lazyframe(_firb_row_with_lgd_collateral(), framework="CRR")
        b31_bundle = gen.generate_from_lazyframe(
            _firb_row_with_lgd_collateral(), framework="BASEL_3_1"
        )

        # Assert
        crr_total = _get_total_row(crr_bundle.c08_01["corporate"])
        b31_total = _get_total_row(b31_bundle.c08_01["corporate"])
        assert crr_total["0060"][0] == pytest.approx(-600_000.0)
        assert b31_total["0060"][0] == pytest.approx(crr_total["0060"][0])

    def test_c0170_equals_sum_of_c0171_to_c0173_on_the_lgd_modelling_leg(self) -> None:
        """boe_b0750 / v09752_m / v09751_m: c0170 = c0171 + c0172 + c0173.

        Passes VACUOUSLY today (0170/0171/0172/0173 are all the hardcoded
        0.0 constant) -- RD-8 records that this identity then holds BY
        CONSTRUCTION once 0170 is wired as their sum; pinned per the
        proposal's explicit requirement so it cannot regress once real
        values appear.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0170"][0] == pytest.approx(
            total["0171"][0] + total["0172"][0] + total["0173"][0]
        )

    def test_c017x_never_exceeds_c0170_on_the_lgd_modelling_leg(self) -> None:
        """boe_b0375/6/7: c017x <= c0170. Also passes vacuously today (see
        the note on the sibling test above)."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        for col in ("0171", "0172", "0173"):
            assert total[col][0] <= total["0170"][0] + 1e-9

    def test_col_0173_always_zero(self) -> None:
        """Art. 200(1)(c) (instruments repurchased on request) has no engine
        carrier -- no data source exists to populate it, so it stays the
        recorded constant 0.0 on every leg, including one that populates
        0171/0172."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _airb_b31_row_with_lgd_collateral(), framework="BASEL_3_1"
        )
        total = _get_total_row(bundle.c08_01["corporate"])

        # Assert
        assert total["0173"][0] == pytest.approx(0.0)
