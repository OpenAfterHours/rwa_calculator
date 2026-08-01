"""COREP C 07.00 CRM substitution block (cols 0050-0110).

Split into its own file rather than added to tests/unit/reporting/corep/test_c07.py
so the largest reporting test file does not accrete further (arch_check
``max_reporting_test_file_loc`` ratchet).

Root cause these tests pin: col 0080 carried the RAW Art. 199 real-estate /
receivables / other-physical collateral value — the IRB carriers — in a column
Annex II defines as "Other funded credit protection, Article 232 CRR". Under the
Standardised Approach none of that collateral is eligible funded credit
protection at all (Art. 199 is headed "Additional eligibility for collateral
under the IRB Approach"); the mortgage benefit arrives through the exposure class
and its Art. 124-126 risk weight instead, so reporting it as a substitution
effect double-counted it. A 60%-LTV mortgage therefore put 666,667 of property
against a 400,000 exposure, drove col 0110 to -266,667, tripped the ``max(0, …)``
E* floor on col 0150 and broke the whole Annex II waterfall — ~33 published
supervisory rules, headed by ``v10293_s`` / ``boe_b0667`` ({template} >= 0).

Two further Annex II identities are pinned here:
- ``v0305_m`` / ``boe_b0694``: 0090 = 0050 + 0060 + 0070 + 0080. Col 0090 used
  to carry ``guaranteed_portion`` for class-MIGRATING rows only.
- ``v0306_m`` / ``boe_b0697``: 0110 = 0040 + 0090 + 0100. The waterfall used to
  subtract the components AND 0090, removing every outflow twice.

References:
- COREP Annex II C 07.00 cols 0050-0110 (docs/assets/crr-annex-ii-reporting-instructins.pdf p.87-88)
- PRA PS1/26 Annex II OF 07.00 cols 0050-0110 (docs/assets/ps1-26-annex-ii-reporting-instructions.pdf p.82-84)
- CRR Art. 199 (IRB-only collateral), Art. 200/232 (other funded credit
  protection), Art. 222 (FCSM), Art. 235 (covered / uncovered split)
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row

# The four block columns, in Annex II order, and the outflow subtotal.
_BLOCK_COLS = ("0050", "0060", "0070", "0080")


def _sa_results_with_mortgage_collateral() -> pl.LazyFrame:
    """One SA mortgage, 60% LTV — property worth 1.67x the exposure.

    The shape that drove col 0110 negative: Art. 199 collateral (real estate)
    exceeding the exposure, on a Standardised-Approach row.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_RRE_1"],
            "counterparty_reference": ["CP_RRE"],
            "exposure_class": ["retail_mortgage"],
            "approach_applied": ["standardised"],
            "exposure_type": ["loan"],
            "drawn_amount": [400_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [400_000.0],
            "rwa_final": [140_000.0],
            "risk_weight": [0.35],
            "scra_provision_amount": [0.0],
            "gcra_provision_amount": [0.0],
            "guaranteed_portion": [0.0],
            "collateral_adjusted_value": [0.0],
            # Art. 199 IRB-only collateral — must not reach cols 0050-0080.
            "collateral_re_value": [666_667.0],
            "collateral_receivables_value": [0.0],
            "collateral_other_physical_value": [0.0],
        }
    )


def _sa_results_with_all_four_protections() -> pl.LazyFrame:
    """One SA corporate exposure carrying every limb of the Annex II block."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_P1"],
            "counterparty_reference": ["CP_P1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["standardised"],
            "exposure_type": ["loan"],
            "drawn_amount": [10_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [10_000.0],
            "rwa_final": [10_000.0],
            "risk_weight": [1.0],
            "scra_provision_amount": [1_000.0],
            "gcra_provision_amount": [0.0],
            # 0050 guarantee (Art. 203)
            "guaranteed_portion": [2_000.0],
            "protection_type": ["guarantee"],
            # 0070 financial collateral, Simple Method (Art. 222(1)-(2))
            "fcsm_collateral_value": [1_500.0],
            # 0080 Art. 232 other funded credit protection
            "life_ins_collateral_value": [800.0],
            "third_party_deposit_value": [200.0],
            # 0130 Cvam (Financial Collateral Comprehensive Method)
            "collateral_adjusted_value": [500.0],
            # Art. 199 IRB-only collateral — the negative control.
            "collateral_re_value": [50_000.0],
            "collateral_receivables_value": [7_000.0],
            "collateral_other_physical_value": [3_000.0],
        }
    )


def _sa_results_over_protected() -> pl.LazyFrame:
    """Protection worth more than the exposure — exercises the Annex II cap."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_OP1"],
            "counterparty_reference": ["CP_OP1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["standardised"],
            "exposure_type": ["loan"],
            "drawn_amount": [1_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [1_000.0],
            "rwa_final": [1_000.0],
            "risk_weight": [1.0],
            "scra_provision_amount": [0.0],
            "gcra_provision_amount": [0.0],
            "guaranteed_portion": [900.0],
            "protection_type": ["guarantee"],
            "fcsm_collateral_value": [900.0],
            "life_ins_collateral_value": [0.0],
            "third_party_deposit_value": [0.0],
            "collateral_adjusted_value": [0.0],
        }
    )


class TestArt199CollateralIsNotAnSaSubstitutionEffect:
    """Art. 199 collateral is eligible under the IRB Approach only, so it can
    produce no Standardised-Approach substitution effect (cols 0050-0080)."""

    def test_mortgage_property_value_does_not_reach_col_0080(self) -> None:
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_mortgage_collateral())
        total = _get_total_row(bundle.c07_00["retail_mortgage"])

        # Assert — 666,667 of property against a 400,000 exposure is not an
        # Art. 232 protection; col 0080 stays empty.
        assert total["0080"][0] == pytest.approx(0.0)

    def test_net_exposure_after_substitution_stays_non_negative(self) -> None:
        """``v10293_s`` / ``boe_b0667``: no C 07.00 cell may be negative."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_mortgage_collateral())
        total = _get_total_row(bundle.c07_00["retail_mortgage"])

        # Assert — 0110 is the untouched net exposure, not -266,667.
        assert total["0110"][0] == pytest.approx(400_000.0)

    def test_fully_adjusted_exposure_is_not_floored_to_zero(self) -> None:
        """The Art. 223(3) ``max(0, …)`` E* floor must stop firing spuriously."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_mortgage_collateral())
        total = _get_total_row(bundle.c07_00["retail_mortgage"])

        # Assert
        assert total["0150"][0] == pytest.approx(400_000.0)

    def test_irb_collateral_is_excluded_from_every_block_column(self) -> None:
        """Not just 0080 — no limb of the block may absorb Art. 199 collateral."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_all_four_protections())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert — 60,000 of RE + receivables + other physical is nowhere in the
        # block; only the guarantee / FCSM / Art. 232 amounts are.
        assert [total[col][0] for col in _BLOCK_COLS] == [
            pytest.approx(-2_000.0),
            pytest.approx(0.0),
            pytest.approx(-1_500.0),
            pytest.approx(-1_000.0),
        ]


class TestSubstitutionOutflowSubtotal:
    """Annex II cols 0090/0100 and the col 0110 waterfall."""

    def test_outflow_is_the_block_subtotal(self) -> None:
        """``v0305_m`` / ``boe_b0694``: 0090 = 0050 + 0060 + 0070 + 0080."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_all_four_protections())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert
        assert total["0090"][0] == pytest.approx(sum(total[col][0] for col in _BLOCK_COLS))

    def test_net_exposure_removes_the_outflow_once(self) -> None:
        """``v0306_m`` / ``boe_b0697``: 0110 = 0040 + 0090 + 0100.

        With 0090 emitted negative, 4,500 of protection against a 9,000 net
        exposure leaves 4,500 — not 0 as the double-counting waterfall gave.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_all_four_protections())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert
        expected = total["0040"][0] + total["0090"][0] + total["0100"][0]
        assert total["0110"][0] == pytest.approx(expected)
        assert total["0110"][0] == pytest.approx(4_500.0)

    def test_fully_adjusted_exposure_foots_the_waterfall(self) -> None:
        """``v0307_m`` / ``boe_b0699``: 0150 = 0110 + 0120 + 0130."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_all_four_protections())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert — 0130 is emitted negative, so the identity is a plain sum.
        expected = total["0110"][0] + total["0120"][0] + total["0130"][0]
        assert total["0150"][0] == pytest.approx(expected)
        assert total["0150"][0] == pytest.approx(4_000.0)


class TestBlockCappedAtExposureValue:
    """Annex II cols 0050-0100: "Collateral that has an effect on the exposure
    value … shall be capped at the exposure value"."""

    def test_over_protection_is_capped_at_the_exposure(self) -> None:
        # Arrange — 1,800 of protection against a 1,000 exposure.
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_over_protected())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert — the outflow is the exposure, not the protection.
        assert total["0090"][0] == pytest.approx(-1_000.0)
        assert total["0110"][0] == pytest.approx(0.0)

    def test_the_cap_is_shed_proportionally_across_the_block(self) -> None:
        # Arrange — two equal limbs, so each keeps half the capped total.
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_over_protected())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert
        assert total["0050"][0] == pytest.approx(-500.0)
        assert total["0070"][0] == pytest.approx(-500.0)
