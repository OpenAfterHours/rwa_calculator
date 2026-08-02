"""COREP C 08.01/C 08.02 CRM substitution block (cols 0040-0090/0100).

Root cause these tests pin: col 0090 double-subtracted the substitution
outflow (``_crm_waterfall`` = ``0020 - 0040 - 0050 - 0060 - 0070 + 0080``, D1),
col 0070 was an INDEPENDENT sum gated on the guarantor's class differing from
the obligor's rather than the Annex II subtotal of cols 0040/0050/0060 (D2 —
so a same-class guarantee reported ``0070 = 0.0`` against a populated
``0040``, and col 0060 (Art. 232 other funded credit protection) never
contributed to the outflow at all), the off-BS memo col 0100 re-derived the
same double-subtraction component-for-component (D3), and the cross-sheet
inflow (col 0080) was gated on the SAME class-change flag while the outflow
side was not, so a same-class guarantee's covered amount left the class via
0070 with no equal-and-opposite inflow arriving back via 0080 (D4). This is
the C 08.01 twin of the C 07.00 fix already pinned in
``test_c07_crm_substitution.py`` (``_substitution_outflow`` /
``_net_after_substitution``).

Published identities pinned here (all four rules already shipped in this repo
at ``src/rwa_calc/reporting/validations/rules/crr-eba-v3.0-credit-risk.json``):
- ``v1663_m`` (live, C 08.01.a): ``{c0070} = {c0040} + {c0050} + {c0060}``.
- ``v1662_m`` (C 08.01.a): ``{c0090} = {c0020} + {c0070} + {c0080}`` — on the
  REPORTED (negative-outflow) signs, so the money is removed exactly once.
- Annex II, both templates/regimes: "Inflows and outflows within the same
  exposure classes ... shall also be considered" (the D4 same-class fix).

A further Basel 3.1-only gap (``TestB31OnBalanceSheetNettingInWaterfall``,
found via the published BoE rules — ``src/rwa_calc/reporting/validations/rules/basel31-boe-v4.0.0-credit-risk.json``):
col 0035 (the "(-)" on-balance-sheet netting adjustment, B31-only) is never
folded into the col 0090 waterfall at all today, on ANY row. The BoE rules are
ROW-SCOPED and disagree deliberately: ``boe_b0746`` / ``boe_b0746_1`` (C 08.01)
and ``boe_b0760`` / ``boe_b0761`` (C 08.02, uniform — "all" rows) —
    boe_b0746   (main rows incl. 0010/0020/0070/…): {c0090} = sum({c: 0020;0035;0070;0080})
    boe_b0746_1 (off-BS sub-rows 0030-0035):        {c0090} = sum({c: 0020;0070;0080})
    boe_b0760   (C 08.02, every row):                {c0090} = sum({c: 0020;0035;0070;0080})
On-balance-sheet netting is inherently an ON-balance-sheet concept, so it
correctly reduces col 0090 on the Total / on-BS / grades rows and on every
C 08.02 row, but must NOT reduce it on the off-BS breakdown row (0030) or its
CCF sub-splits (0031-0035) — those rows have no on-balance-sheet netting to
speak of.

References:
- COREP Annex II C 08.01 cols 0040-0090 (docs/assets/crr-annex-ii-reporting-instructins.pdf p.97-99)
- PRA PS1/26 Annex II OF 08.01 cols 0040-0090 (docs/assets/ps1-26-annex-ii-reporting-instructions.pdf p.102-103)
- CRR Art. 203/204 (unfunded protection), Art. 232 (other funded credit
  protection), Art. 235 (covered/uncovered split), Art. 161 (IRB parameter
  substitution)
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row

# The three C 08.01 substitution-block columns, in Annex II order.
_BLOCK_COLS = ("0040", "0050", "0060")


def _irb_results_different_class_guarantee() -> pl.LazyFrame:
    """One un-guaranteed corporate loan + one guaranteed by an institution.

    IRB_CORP_2's 800 guaranteed portion migrates from corporate into
    institution — the class-MIGRATING case (protection_type="guarantee",
    so the amount carries on col 0040).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": ["foundation_irb"] * 3,
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5_000.0, 3_000.0, 2_000.0],
            "undrawn_amount": [0.0, 0.0, 0.0],
            "ead_final": [5_000.0, 3_000.0, 2_000.0],
            "rwa_final": [3_500.0, 1_800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.002],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "expected_loss": [12.375, 13.5, 1.8],
            "scra_provision_amount": [0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
            "guaranteed_portion": [0.0, 800.0, 0.0],
            "protection_type": [None, "guarantee", None],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": ["corporate", "institution", "institution"],
        }
    )


def _irb_results_same_class_guarantee() -> pl.LazyFrame:
    """One un-guaranteed corporate loan + one guaranteed by ANOTHER corporate
    counterparty in the SAME class — the same-class migration Annex II says
    "shall also be considered", both for the outflow and the inflow.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2"],
            "approach_applied": ["foundation_irb"] * 2,
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5_000.0, 3_000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [5_000.0, 3_000.0],
            "rwa_final": [3_500.0, 1_800.0],
            "risk_weight": [0.70, 0.60],
            "pd_floored": [0.005, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "expected_loss": [12.375, 13.5],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B"],
            "guaranteed_portion": [0.0, 800.0],
            "protection_type": [None, "guarantee"],
            "pre_crm_exposure_class": ["corporate", "corporate"],
            "post_crm_exposure_class_guaranteed": ["corporate", "corporate"],
        }
    )


def _irb_results_credit_derivative_different_class() -> pl.LazyFrame:
    """A credit-derivative protection (col 0050, not 0040) migrating class."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": ["foundation_irb"] * 3,
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5_000.0, 3_000.0, 2_000.0],
            "undrawn_amount": [0.0, 0.0, 0.0],
            "ead_final": [5_000.0, 3_000.0, 2_000.0],
            "rwa_final": [3_500.0, 1_800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.002],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "expected_loss": [12.375, 13.5, 1.8],
            "scra_provision_amount": [0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
            "guaranteed_portion": [0.0, 600.0, 0.0],
            "protection_type": [None, "credit_derivative", None],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": ["corporate", "institution", "institution"],
        }
    )


def _irb_results_other_funded_protection() -> pl.LazyFrame:
    """A single leg with Art. 232 other funded protection (col 0060) only —
    no ``guaranteed_portion`` column at all, so cols 0040/0050 are absent."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1"],
            "approach_applied": ["foundation_irb"],
            "exposure_class": ["corporate"],
            "drawn_amount": [5_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [5_000.0],
            "rwa_final": [3_500.0],
            "risk_weight": [0.70],
            "pd_floored": [0.01],
            "lgd_floored": [0.45],
            "irb_maturity_m": [2.5],
            "expected_loss": [10.0],
            "scra_provision_amount": [0.0],
            "gcra_provision_amount": [0.0],
            "counterparty_reference": ["CP_A"],
            "third_party_deposit_value": [400.0],
        }
    )


def _irb_results_multi_class_conservation() -> pl.LazyFrame:
    """A portfolio with a different-class guarantee, a same-class guarantee
    and a credit-derivative, all landing on sheets that already exist — so
    money conservation (``sum(0090) == sum(0020)``) can be checked end to end.

    IRB_CORP_2 (800, guarantee) migrates corporate -> institution.
    IRB_CORP_3 (500, guarantee) migrates corporate -> corporate (self).
    IRB_RETAIL_1 (200, credit_derivative) migrates retail_other -> institution.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_CORP_3",
                "IRB_INST_1",
                "IRB_RETAIL_1",
            ],
            "approach_applied": ["foundation_irb"] * 5,
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            "drawn_amount": [5_000.0, 3_000.0, 2_000.0, 2_000.0, 1_000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [5_000.0, 3_000.0, 2_000.0, 2_000.0, 1_000.0],
            "rwa_final": [3_500.0, 1_800.0, 1_200.0, 600.0, 300.0],
            "risk_weight": [0.70, 0.60, 0.60, 0.30, 0.30],
            "pd_floored": [0.005, 0.01, 0.01, 0.002, 0.003],
            "lgd_floored": [0.45, 0.45, 0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 3.0, 1.5, 1.5],
            "expected_loss": [12.375, 13.5, 9.0, 1.8, 1.35],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "guaranteed_portion": [0.0, 800.0, 500.0, 0.0, 200.0],
            "protection_type": [None, "guarantee", "guarantee", None, "credit_derivative"],
            "pre_crm_exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "corporate",
                "institution",
                "institution",
            ],
        }
    )


def _irb_results_off_bs_with_substitution() -> pl.LazyFrame:
    """One on-BS loan + one off-BS facility carrying a class-migrating
    guarantee, so the off-BS pre-CCF memo (col 0100) is non-trivial.

    Leg A (on-BS loan):      drawn 5,000, no CRM.
    Leg B (off-BS facility): undrawn 2,000, ead 1,000 (CCF 0.5), guaranteed
                              500 (protection_type="guarantee") migrating to
                              institution.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_ON_1", "IRB_OFF_1"],
            "approach_applied": ["foundation_irb"] * 2,
            "exposure_class": ["corporate", "corporate"],
            "exposure_type": ["loan", "facility"],
            "drawn_amount": [5_000.0, 0.0],
            "undrawn_amount": [0.0, 2_000.0],
            "ead_final": [5_000.0, 1_000.0],
            "rwa_final": [3_500.0, 700.0],
            "risk_weight": [0.70, 0.70],
            "pd_floored": [0.01, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5],
            "expected_loss": [10.0, 2.0],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_ON", "CP_OFF"],
            "guaranteed_portion": [0.0, 500.0],
            "protection_type": [None, "guarantee"],
            "pre_crm_exposure_class": ["corporate", "corporate"],
            "post_crm_exposure_class_guaranteed": ["corporate", "institution"],
        }
    )


class TestC0801DifferentClassGuarantee:
    """A class-migrating guarantee: outflow leaves the obligor's sheet exactly
    once and the equal inflow arrives on the guarantor's sheet."""

    def test_outflow_is_the_block_subtotal(self) -> None:
        """``v1663_m``: 0070 = 0040 + 0050 + 0060."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_different_class_guarantee())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(sum(corp[col][0] for col in _BLOCK_COLS))

    def test_money_removed_exactly_once_not_twice(self) -> None:
        """``v1662_m``: 0090 = 0020 + 0070 + 0080 (0070 stored negative).

        800 covered out of an 8,000 corporate book leaves 7,200 — not the
        6,400 the double-subtracted waterfall gave.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_different_class_guarantee())

        corp = _get_total_row(bundle.c08_01["corporate"])
        expected = corp["0020"][0] + corp["0070"][0] + corp["0080"][0]
        assert corp["0090"][0] == pytest.approx(expected)
        assert corp["0090"][0] == pytest.approx(7_200.0)

    def test_institution_receives_the_matching_inflow(self) -> None:
        """The guarantor's sheet gains an equal-and-opposite inflow (col 0080)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_different_class_guarantee())

        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0080"][0] == pytest.approx(800.0)
        assert inst["0090"][0] == pytest.approx(2_800.0)


class TestC0801SameClassGuarantee:
    """Annex II: "Inflows and outflows within the same exposure classes ...
    shall also be considered" — a same-class guarantee must still populate
    the outflow AND its matching inflow, netting col 0090 back to the
    un-guaranteed total."""

    def test_outflow_reports_the_guarantee_not_zero(self) -> None:
        """``v1663_m`` live-rule violation today: col 0070 reports 0.0 against
        a populated col 0040 when the guarantor sits in the SAME class as the
        obligor, because the retired binding gated 0070 on a class CHANGE.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_same_class_guarantee())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(corp["0040"][0])
        assert corp["0070"][0] == pytest.approx(-800.0)

    def test_net_exposure_unchanged_by_a_same_class_guarantee(self) -> None:
        """The equal inflow lands in the SAME class, so col 0090 == col 0020."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_same_class_guarantee())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0090"][0] == pytest.approx(corp["0020"][0])
        assert corp["0090"][0] == pytest.approx(8_000.0)


class TestC0801CreditDerivativeProtection:
    """Col 0050 (credit derivatives, Art. 204) rather than 0040 carries the
    amount, and the outflow subtotal still reads it."""

    def test_credit_derivative_carries_col_0050_not_0040(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_credit_derivative_different_class())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0040"][0] == pytest.approx(0.0)
        assert corp["0050"][0] == pytest.approx(-600.0)

    def test_outflow_subtotal_reads_col_0050(self) -> None:
        """``v1663_m``: 0070 = 0040 + 0050 + 0060, so 0070 == 0050 here."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_credit_derivative_different_class())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(corp["0050"][0])
        assert corp["0070"][0] == pytest.approx(sum(corp[col][0] for col in _BLOCK_COLS))

    def test_money_removed_exactly_once(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_credit_derivative_different_class())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0090"][0] == pytest.approx(7_400.0)


class TestC0801OtherFundedProtection:
    """Col 0060 (Art. 232 other funded credit protection) must contribute to
    the outflow subtotal — the retired binding ignored it entirely."""

    def test_col_0060_contributes_to_the_outflow(self) -> None:
        """``v1663_m``: 0070 = 0040 + 0050 + 0060 == 0060 here (0040 = 0050 = 0)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_other_funded_protection())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0060"][0] == pytest.approx(-400.0)
        assert corp["0070"][0] == pytest.approx(corp["0060"][0])


class TestC0801MoneyConservation:
    """Every guarantee stays inside the IRB book (no cross-template leak),
    so the total exposure after substitution must equal the total gross
    exposure — outflows and inflows are the same money, counted once."""

    def test_sum_of_0090_equals_sum_of_0020_across_sheets(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_multi_class_conservation())

        total_0090 = sum(_get_total_row(frame)["0090"][0] for frame in bundle.c08_01.values())
        total_0020 = sum(_get_total_row(frame)["0020"][0] for frame in bundle.c08_01.values())
        assert total_0090 == pytest.approx(total_0020)
        assert total_0090 == pytest.approx(13_000.0)


class TestC0801OffBalanceSheetMemoNoDoubleSubtraction:
    """Col 0100 (off-BS pre-CCF memo) mirrors the corrected 0090 waterfall —
    it must not re-subtract the substituted portion a second time."""

    def test_col_0100_is_the_off_bs_gross_less_the_off_bs_outflow(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_off_bs_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0100"][0] == pytest.approx(1_500.0)

    def test_off_bs_breakdown_row_0100_equals_its_own_0090(self) -> None:
        """On the off-BS breakdown row (0030), the whole subset IS off-BS, so
        the off-BS memo equals that row's own CRM waterfall."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_off_bs_with_substitution())

        off_row = bundle.c08_01["corporate"].filter(pl.col("row_ref") == "0030")
        assert off_row["0100"][0] == pytest.approx(off_row["0090"][0])
        assert off_row["0100"][0] == pytest.approx(1_500.0)


def _irb_results_with_substitution() -> pl.LazyFrame:
    """IRB results with CRM substitution columns for Task 2H testing.

    Scenario: Corporate IRB exposure IRB_CORP_2 guaranteed by institution.
    The guaranteed portion (800) flows out of corporate class into institution class.

    Moved here from ``test_cross.py`` (arch_check ``max_reporting_test_file_loc``
    ratchet) — bodies verbatim; the C 07.00 half of this class lives in
    ``test_c07_crm_substitution.py``.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5000.0, 3000.0, 2000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0],
            "rwa_final": [3850.0, 1800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.002],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "provision_held": [15.0, 10.0, 3.0],
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            "bs_type": ["ONB", "ONB", "ONB"],
            "guaranteed_portion": [0.0, 800.0, 0.0],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
            ],
        }
    )


class TestSubstitutionFlows:
    """Task 2H: CRM substitution flow columns (C 08.01: 0040/0070/0080/0090).

    Moved here from ``test_cross.py`` (arch_check ``max_reporting_test_file_loc``
    ratchet) — bodies verbatim.
    """

    def test_c08_guarantee_col_populated(self) -> None:
        """C 08.01 col 0040 shows guaranteed_portion sum — negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_CORP_2 has 800 guaranteed_portion; stored as a negative deduction.
        assert corp["0040"][0] == pytest.approx(-800.0)

    def test_c08_outflow_populated(self) -> None:
        """C 08.01 col 0070 shows guaranteed portion leaving the class — negative
        per Annex II. ``v1663_m`` now governs: 0070 = 0040 + 0050 + 0060 (here
        0050 = 0060 = 0, so 0070 == 0040)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(-800.0)

    def test_c08_inflow_populated(self) -> None:
        """C 08.01 col 0080 shows guaranteed portion arriving from other classes."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0080"][0] == pytest.approx(800.0)

    def test_c08_net_after_substitution(self) -> None:
        """C 08.01 col 0090 foots the CRM waterfall — ``v1662_m`` now governs.

        The waterfall runs on positive magnitudes BEFORE the display negation:
        0090 = 0020 + 0070 + 0080 (0070 stored negative, 0080 the positive
        inflow). Cols 0040/0050/0060 are the breakdown that MAKES UP 0070
        (``v1663_m``) and must not be subtracted a second time — the retired
        formula (0090 = 0020 + 0040 + 0070 + 0080) double-counted the outflow,
        the same defect C 07.00's ``_net_after_substitution`` already fixed.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        v_0020 = corp["0020"][0]
        v_0070 = corp["0070"][0]  # negative (deduction) — already the subtotal
        v_0080 = corp["0080"][0]  # positive (inflow)
        v_0090 = corp["0090"][0]

        expected = v_0020 + v_0070 + v_0080
        assert v_0090 == pytest.approx(expected)
        assert v_0090 == pytest.approx(8_200.0)


def _irb_results_b31_on_off_bs_netting() -> pl.LazyFrame:
    """One on-BS loan + one off-BS facility, both carrying on-balance-sheet
    netting (Basel 3.1 col 0035) — no guarantee, so this fixture is isolated
    from D1-D4 and tests only the col 0035 waterfall term.

    Leg A (on-BS loan):      drawn 5,000, on_bs_netting_amount 500.
    Leg B (off-BS facility): undrawn 2,000, on_bs_netting_amount 100 (an
        unrealistic value on an off-BS leg, deliberately, so the row-scoped
        EXCLUSION on row 0030 is observable rather than coincidentally zero).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_ON_1", "IRB_OFF_1"],
            "approach_applied": ["foundation_irb"] * 2,
            "exposure_class": ["corporate", "corporate"],
            "exposure_type": ["loan", "facility"],
            "drawn_amount": [5_000.0, 0.0],
            "undrawn_amount": [0.0, 2_000.0],
            "ead_final": [5_000.0, 1_000.0],
            "rwa_final": [3_500.0, 700.0],
            "risk_weight": [0.70, 0.70],
            "pd_floored": [0.01, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5],
            "expected_loss": [10.0, 2.0],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_ON", "CP_OFF"],
            "on_bs_netting_amount": [500.0, 100.0],
        }
    )


def _irb_results_b31_netting_single_leg() -> pl.LazyFrame:
    """A single on-BS C 08.02 leg carrying on-balance-sheet netting."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_ON_1"],
            "approach_applied": ["foundation_irb"],
            "exposure_class": ["corporate"],
            "exposure_type": ["loan"],
            "drawn_amount": [5_000.0],
            "undrawn_amount": [0.0],
            "ead_final": [5_000.0],
            "rwa_final": [3_500.0],
            "risk_weight": [0.70],
            "pd_floored": [0.01],
            "lgd_floored": [0.45],
            "irb_maturity_m": [2.5],
            "expected_loss": [10.0],
            "scra_provision_amount": [0.0],
            "gcra_provision_amount": [0.0],
            "counterparty_reference": ["CP_ON"],
            "on_bs_netting_amount": [500.0],
        }
    )


class TestB31OnBalanceSheetNettingInWaterfall:
    """Basel 3.1 col 0035 (on-balance-sheet netting) must be folded into the
    col 0090 waterfall on the rows the published BoE rules name, and ONLY
    those rows — see the module docstring for the row-scope table."""

    def test_total_row_waterfall_includes_col_0035(self) -> None:
        """``boe_b0746`` (row 0010 in scope): 0090 = 0020 + 0035 + 0070 + 0080.

        7,000 gross less 600 of on-balance netting (500 + 100) leaves 6,400 —
        not the 7,000 the netting-blind waterfall gives today.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_on_off_bs_netting(), framework="BASEL_3_1"
        )

        total = _get_total_row(bundle.c08_01["corporate"])
        expected = total["0020"][0] + total["0035"][0] + total["0070"][0] + total["0080"][0]
        assert total["0090"][0] == pytest.approx(expected)
        assert total["0090"][0] == pytest.approx(6_400.0)

    def test_on_bs_breakdown_row_waterfall_includes_col_0035(self) -> None:
        """``boe_b0746`` (row 0020 in scope): the on-BS row's own netting
        (500) reduces its own 0090 to 4,500."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_on_off_bs_netting(), framework="BASEL_3_1"
        )

        on_row = bundle.c08_01["corporate"].filter(pl.col("row_ref") == "0020")
        assert on_row["0090"][0] == pytest.approx(4_500.0)

    def test_off_bs_breakdown_row_waterfall_excludes_col_0035(self) -> None:
        """``boe_b0746_1`` (row 0030 in scope): the off-BS row's col 0035 is
        NOT a waterfall term, so its own 100 of (economically nonsensical,
        deliberately provocative) netting must NOT reduce its 0090 — a
        positive control against an overzealous "always add 0035" fix."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_on_off_bs_netting(), framework="BASEL_3_1"
        )

        off_row = bundle.c08_01["corporate"].filter(pl.col("row_ref") == "0030")
        assert off_row["0035"][0] == pytest.approx(-100.0)
        assert off_row["0090"][0] == pytest.approx(2_000.0)

    def test_c08_02_waterfall_includes_col_0035_on_every_row(self) -> None:
        """``boe_b0760`` (C 08.02, "all" rows — no on/off-BS row split exists
        here, so every row includes col 0035): 0090 = 0020 + 0035 + 0070 + 0080."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_netting_single_leg(), framework="BASEL_3_1"
        )

        band = bundle.c08_02["corporate"]
        expected = band["0020"][0] + band["0035"][0] + band["0070"][0] + band["0080"][0]
        assert band["0090"][0] == pytest.approx(expected)
        assert band["0090"][0] == pytest.approx(4_500.0)


class TestC0802OutflowSubtotal:
    """C 08.02 shares ``_value_cells`` with C 08.01, so its per-grade-row col
    0070 moved from the ``c08_substituted``-gated sum to the
    0040+0050+0060 subtotal too — TWO LIVE published rules govern it,
    distinct from C 08.01's ``v1662_m``/``v1663_m``:
    - ``v1665_m`` (live, C 08.02): {c0070} = {c0040} + {c0050} + {c0060}
    - ``v0347_m`` (live, C 08.02): {c0090} = {c0020} + {c0070} + {c0080}

    R12 (recorded decision) makes col 0080 a constant 0.0 on every C 08.02
    grade row — the cross-class inflow is deliberately excluded from the
    by-grade breakdown — so ``v0347_m`` REDUCES to ``0090 = 0020 + 0070``
    there. That reduced identity is asserted explicitly below: it is exactly
    the shape where a regression would hide behind a plain "0090 changed"
    check, since 0080 already being 0 means only col 0070 is doing any work.

    Uses ``_irb_results_different_class_guarantee()``: IRB_CORP_2 (pd=0.01,
    guaranteed 800) falls in a DIFFERENT PD band from IRB_CORP_1 (pd=0.005),
    so its own grade row is a clean single-leg check.
    """

    _CORP_2_ROW_REF = "0.75% - 2.50%"

    def test_outflow_is_the_block_subtotal(self) -> None:
        """``v1665_m``: 0070 = 0040 + 0050 + 0060."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_different_class_guarantee())

        row = bundle.c08_02["corporate"].filter(pl.col("row_ref") == self._CORP_2_ROW_REF)
        assert row.height == 1
        assert row["0070"][0] == pytest.approx(row["0040"][0] + row["0050"][0] + row["0060"][0])
        assert row["0070"][0] == pytest.approx(-800.0)

    def test_reduced_waterfall_with_zero_inflow(self) -> None:
        """``v0347_m`` reduced form: 0090 = 0020 + 0070 (0080 == 0.0, R12)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_different_class_guarantee())

        row = bundle.c08_02["corporate"].filter(pl.col("row_ref") == self._CORP_2_ROW_REF)
        assert row["0080"][0] == pytest.approx(0.0)
        expected = row["0020"][0] + row["0070"][0]
        assert row["0090"][0] == pytest.approx(expected)
        assert row["0090"][0] == pytest.approx(2_200.0)
