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
from tests.unit.reporting.corep._builders import _get_total_row, _sa_results

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


def _sa_results_same_class_guarantee() -> pl.LazyFrame:
    """One un-guaranteed SA corporate loan + one guaranteed by ANOTHER SA
    corporate counterparty in the SAME class.

    Annex II C 07.00 cols 0090/0100: "Inflows and outflows within the same
    exposure classes shall also be reported" — a same-class guarantee must
    produce an equal-and-opposite inflow (col 0100) alongside its outflow
    (col 0090), netting col 0110 back to the un-guaranteed total.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2"],
            "counterparty_reference": ["CP_A", "CP_B"],
            "exposure_class": ["corporate", "corporate"],
            "approach_applied": ["standardised"] * 2,
            "exposure_type": ["loan", "loan"],
            "drawn_amount": [5_000.0, 3_000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [5_000.0, 3_000.0],
            "rwa_final": [5_000.0, 3_000.0],
            "risk_weight": [1.0, 1.0],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0],
            "protection_type": [None, "guarantee"],
            "pre_crm_exposure_class": ["corporate", "corporate"],
            "post_crm_exposure_class_guaranteed": ["corporate", "corporate"],
        }
    )


class TestSameClassInflowConservation:
    """Annex II: "Inflows and outflows within the same exposure classes ...
    shall also be reported" (C 07.00 cols 0090/0100) — a same-class guarantee
    must produce an equal inflow alongside its outflow. Pins ``v0305_m`` (the
    0090 subtotal, already correct) together with ``v0306_m`` (the 0110
    waterfall) and the same-class inflow gate this closes.
    """

    def test_same_class_guarantee_produces_an_inflow(self) -> None:
        """Col 0100 must equal the guaranteed amount, not 0.0 — the retired
        binding gated the inflow on ``pre_crm_exposure_class !=
        post_crm_exposure_class_guaranteed``, which a same-class migration
        never satisfies, so it excluded the inflow entirely."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_same_class_guarantee())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert
        assert total["0100"][0] == pytest.approx(500.0)

    def test_net_exposure_unchanged_by_a_same_class_guarantee(self) -> None:
        """``v0306_m``: 0110 = 0040 + 0090 + 0100. With the same-class inflow
        restored, a self-contained guarantee has no net effect on 0110 —
        today it reports 7,500 (the outflow with no matching inflow), not
        the correct 8,000."""
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_same_class_guarantee())
        total = _get_total_row(bundle.c07_00["corporate"])

        # Assert
        assert total["0110"][0] == pytest.approx(total["0040"][0])
        assert total["0110"][0] == pytest.approx(8_000.0)


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


def _sa_results_with_substitution() -> pl.LazyFrame:
    """SA results with CRM substitution columns for Task 2H testing.

    Scenario: Corporate exposure SA_CORP_2 has a guarantee from an institution.
    The guaranteed portion (500) flows out of corporate class into institution class.

    Moved here from ``test_cross.py`` (arch_check ``max_reporting_test_file_loc``
    ratchet) — bodies verbatim.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_INST_1",
                "SA_RETAIL_1",
            ],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 200.0],
            "undrawn_amount": [500.0, 0.0, 0.0, 50.0],
            "ead_final": [1200.0, 2000.0, 3000.0, 225.0],
            "rwa_final": [1140.0, 1900.0, 600.0, 168.75],
            "risk_weight": [1.0, 1.0, 0.20, 0.75],
            "scra_provision_amount": [10.0, 20.0, 0.0, 2.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0, 1.0],
            "sa_cqs": [3, 0, 2, 0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D", "CP_E"],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0],
            # Pre-CRM: both corporates are in "corporate" class
            "pre_crm_exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            # Post-CRM: SA_CORP_2's guaranteed portion migrates to "institution"
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
                "retail_other",
            ],
        }
    )


class TestSubstitutionFlows:
    """Task 2H: CRM substitution flow columns (C 07.00: 0090/0100/0110).

    Why: COREP requires reporting how CRM guarantees cause exposure to
    'flow' between exposure classes. Outflows show guaranteed portions
    leaving the borrower's class; inflows show guaranteed portions
    arriving from other classes via the guarantor's class assignment.

    Moved here from ``test_cross.py`` (arch_check ``max_reporting_test_file_loc``
    ratchet) — bodies verbatim; the C 08.01 half of this class lives in
    ``test_c08_crm_substitution.py``.
    """

    def test_c07_outflow_populated(self) -> None:
        """Col 0090 shows guaranteed portion leaving the class — emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_2 has 500 guaranteed_portion migrating to institution; stored as negative deduction
        assert corp["0090"][0] == pytest.approx(-500.0)

    def test_c07_inflow_populated(self) -> None:
        """Col 0100 shows guaranteed portion arriving from other classes."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        inst = _get_total_row(bundle.c07_00["institution"])
        # SA_CORP_2's 500 guaranteed portion flows into institution class
        assert inst["0100"][0] == pytest.approx(500.0)

    def test_c07_no_flow_class_has_zero(self) -> None:
        """Class with no substitution has 0 outflow and 0 inflow."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        retail = _get_total_row(bundle.c07_00["retail_other"])
        assert retail["0090"][0] == pytest.approx(0.0)
        assert retail["0100"][0] == pytest.approx(0.0)

    def test_c07_net_exposure_after_substitution(self) -> None:
        """Col 0110 = 0040 + 0090 + 0100 — the outflow is removed exactly ONCE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Engine: 0040=3455, 0090=-500 (= col 0050), 0100=0 → 0110 = 2955
        assert corp["0110"][0] == pytest.approx(2955.0)

    def test_c07_outflow_reported_without_substitution_cols(self) -> None:
        """Outflow is the CRM block subtotal, not a detected class migration."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0090"][0] == pytest.approx(-500.0)
        assert corp["0100"][0] == pytest.approx(0.0)


def _irb_book_with_sa_guarantor() -> pl.LazyFrame:
    """An all-IRB-origin book whose only guarantee has an SA guarantor.

    IRB_CORP_1 is unguaranteed (5,000). IRB_CORP_2 (3,000) is guaranteed 1,500
    by an institution treated under the STANDARDISED approach post-CRM (the
    CRR Art. 235 risk-weight substitution route), while every row's ORIGIN
    approach is ``foundation_irb``. So the origin-approach population sees NO
    row from this book at all — the SA guarantor never has its own exposure
    here — yet the inflow the guarantee generates is destined for C 07.00's
    ``institution`` sheet by the guarantor's POST-crm approach
    (``corep/crm_substitution.py``).

    TWO THINGS HERE ARE LOAD-BEARING AND WERE BOTH WRONG BEFORE.

    1. THE POST-CRM TWINS ARE SET AS A PAIR. This frame used to set
       ``approach_post_crm="standardised"`` with NO ``exposure_class_post_crm``,
       so the shim sealed ``reporting_approach="standardised"`` alongside
       ``reporting_class="corporate"`` — a leg simultaneously claiming to be an
       SA exposure and to sit in the obligor's own class. PRODUCTION CANNOT EMIT
       THAT: ``aggregator.py::_add_post_crm_reporting_class`` and
       ``_post_crm_approach_expr`` carry the SAME is_guaranteed-and-beneficial
       gate precisely so the two partition the same money the same way, and the
       latter's docstring says an approach that migrates while the class does not
       "would key a leg onto a sheet/template pair that never existed". Once
       C 07.00's exposure-value and RWEA columns moved to the post-substitution
       basis they read that pair, and the impossible state materialised a
       phantom ``corporate`` sheet carrying the leg's whole EAD. If this test
       ever fails again, FIX THE FRAME, NOT THE ASSERTION — a divergent pair is
       the bug, not the thing under test.

    2. THE GUARANTEED EXPOSURE IS SPLIT INTO ITS TWO LEGS, as CRM does
       (``engine/crm/guarantees.py`` emits ``__G_<guarantor>`` and ``__REM``).
       The single-row form is what made (1) impossible to express correctly: a
       post-CRM class is a per-LEG attribute, so one row cannot say "only the
       covered 1,500 migrated" — the whole 3,000 would land on the guarantor's
       sheet. With the split, col 0200 on the institution sheet is the covered
       1,500 and agrees with the col 0100 inflow instead of contradicting it.
       Book totals are preserved (8,000 EAD / 5,300 RWEA); the retained and
       covered halves keep the borrower's 0.60 weight because no assertion here
       concerns risk weights and inventing a guarantor weight would pin a number
       nothing tests.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2__REM", "IRB_CORP_2__G_INST_GTOR"],
            "approach_applied": ["foundation_irb"] * 3,
            # The two post-CRM twins, always set together — see the docstring.
            "approach_post_crm": ["foundation_irb", "foundation_irb", "standardised"],
            "exposure_class": ["corporate"] * 3,
            "exposure_class_post_crm": ["corporate", "corporate", "institution"],
            "drawn_amount": [5_000.0, 1_500.0, 1_500.0],
            "undrawn_amount": [0.0, 0.0, 0.0],
            "ead_final": [5_000.0, 1_500.0, 1_500.0],
            "rwa_final": [3_500.0, 900.0, 900.0],
            "risk_weight": [0.70, 0.60, 0.60],
            "pd_floored": [0.005, 0.01, 0.01],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 3.0],
            "expected_loss": [12.375, 6.75, 6.75],
            "scra_provision_amount": [0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_B"],
            "guaranteed_portion": [0.0, 0.0, 1_500.0],
            "protection_type": [None, None, "guarantee"],
            # Art. 235 substitution ACTUALLY applied on the covered leg. Stated
            # explicitly rather than left absent: absence makes the decline gate
            # a no-op, which happens to give the same answer here but says
            # "the CRM sub-step never ran" rather than "the guarantee was
            # recognised", and only the latter entitles the covered part to the
            # guarantor's sheet.
            "is_guarantee_beneficial": [None, None, True],
            "pre_crm_exposure_class": ["corporate"] * 3,
            "post_crm_exposure_class_guaranteed": ["corporate", "corporate", "institution"],
        }
    )


class TestEmptyPopulationStillEmitsInflowOnlySheet:
    """D6: a destination template with NO native population of its own must
    still emit the inflow-only sheet — the empty-population early exit used to
    run BEFORE the inflow map was computed, so an all-IRB book guaranteed by
    an SA counterparty dropped the inflow a second time (on top of D5)."""

    def test_c07_gets_an_institution_sheet_despite_an_empty_sa_population(self) -> None:
        """C 07.00's own population (SA-origin rows) is empty here — both
        loans are IRB-origin, so ``corporate`` never gets a native C 07.00
        sheet — but ``institution`` must still be emitted to carry the inflow."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_book_with_sa_guarantor())

        assert "institution" in bundle.c07_00
        assert "corporate" not in bundle.c07_00

    def test_inflow_only_sheet_reports_the_guaranteed_amount(self) -> None:
        """The inflow-only sheet has zero native exposure (0010) but the full
        covered amount on col 0100, and 0110 = 0100 (nothing else on the sheet)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_book_with_sa_guarantor())

        inst = _get_total_row(bundle.c07_00["institution"])
        assert inst["0010"][0] == pytest.approx(0.0)
        assert inst["0100"][0] == pytest.approx(1_500.0)
        assert inst["0110"][0] == pytest.approx(1_500.0)

    def test_c08_01_does_not_also_claim_the_sa_routed_inflow(self) -> None:
        """The SA/IRB routing partitions the population — C 08.01's institution
        sheet (if it exists at all) must NOT also carry this inflow, or the
        same covered amount would be double-counted across templates."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_book_with_sa_guarantor())

        if "institution" in bundle.c08_01:
            inst = _get_total_row(bundle.c08_01["institution"])
            assert inst["0080"][0] == pytest.approx(0.0)
