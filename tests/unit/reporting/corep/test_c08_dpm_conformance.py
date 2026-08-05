"""COREP C 08.0x conformance with the published DPM identities.

Pins the four supervisory-validation defects fixed in this slice, each against
the instruction text and the published rule that detects it:

- OF 08.02 is NOT reported for slotting exposures (PS1/26 Annex II §3.3.4
  paragraph 77A), so ``{OF08.01 r0070} = sum({OF08.02})`` holds — boe_b0752_*,
  boe_b0814_*, boe_b0763.
- OF 08.01/02 col 0251 (RWEA pre-adjustments) carries the slotting leg's RWEA
  rather than a null-filled 0.0, so ``{c0260} = sum({c0251;0252;0253;0254})``
  holds — boe_b0751, boe_b0763.
- OF 08.01/02 col 0104 (exposure after all CRM pre-CCF) is emitted, so
  ``{c0104} = sum({c0090;0101;0102})`` holds — boe_b1040.
- C 08.07 / OF 08.07 cols 0030/0040/0050 are DPM fractions, and OF 08.07's row
  axis is the eight Art. 147B(1) roll-out classes with the Total on row 0260 —
  EBA v09769_m/v09771_m/v09796_m, boe_b0778, boe_b0779.

References:
- PS1/26 Annex II §3.3.2 ¶76, §3.3.3.2 (cols 0090-0104, 0251-0260), §3.3.4 ¶77A,
  §3.3.10.2; COREP Annex II §3.3.2 ¶76, §3.3.6.2
- PS1/26 Art. 147B(1) (roll-out classes)
- docs/assets/boe-validation-rules-banking-reporting-v4.0.0.xlsx
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import (
    B31_C08_07_ROLLOUT_CLASSES,
    B31_C08_07_ROWS,
)
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

#: The C 08.01 rows the slotting book reports on: the Total (0010), its
#: on-balance-sheet split (0020) and the slotting total (0080). Row 0070
#: (obligor grades) is deliberately NOT among them.
_SLOTTING_ROWS = ("0010", "0020", "0080")


def _mixed_slotting_results() -> pl.LazyFrame:
    """Two formula-IRB corporate legs and two slotting specialised-lending legs.

    The slotting legs carry no ``cp_internal_rating_grade`` and no
    ``rwa_pre_adjustments`` — exactly the shape the engine produces, since
    ``apply_post_model_adjustments`` runs on the formula-IRB branch only.
    Every leg is on-balance-sheet and fully drawn, so gross == EAD and the CRM
    waterfall is a pass-through: corporate 8,000 / 5,300 RWEA, specialised
    lending 10,000 / 7,800 RWEA.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "SL_1", "SL_2"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "slotting",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "specialised_lending",
                "specialised_lending",
            ],
            "bs_type": ["ONB", "ONB", "ONB", "ONB"],
            "drawn_amount": [5000.0, 3000.0, 6000.0, 4000.0],
            "ead_final": [5000.0, 3000.0, 6000.0, 4000.0],
            "rwa_final": [3500.0, 1800.0, 4200.0, 3600.0],
            "risk_weight": [0.70, 0.60, 0.70, 0.90],
            "pd_floored": [0.005, 0.01, None, None],
            "lgd_floored": [0.45, 0.45, None, None],
            "expected_loss": [12.375, 13.5, 84.0, 56.0],
            "rwa_pre_adjustments": [3500.0, 1800.0, None, None],
            "post_model_adjustment_rwa": [0.0, 0.0, None, None],
            "mortgage_rw_floor_adjustment": [0.0, 0.0, None, None],
            "unrecognised_exposure_adjustment": [0.0, 0.0, None, None],
            "slotting_category": [None, None, "strong", "good"],
            "sl_type": [None, None, "project_finance", "project_finance"],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
        }
    )


class TestC0802ExcludesSlotting:
    """PS1/26 Annex II ¶77A: OF 08.02 covers the AIRB and FIRB approaches "but
    not ... exposures subject to the slotting approach"."""

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_slotting_only_class_emits_no_c0802_sheet(self, framework: str) -> None:
        """A class whose whole book is slotting has no obligor grades to break down.

        Arrange: two formula-IRB corporate legs, two slotting SL legs.
        Act:     generate the COREP bundle.
        Assert:  C 08.02 keys corporate but not specialised_lending — the same
                 treatment C 08.03/05 already give the slotting book.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework=framework)

        assert "corporate" in bundle.c08_02
        assert "specialised_lending" not in bundle.c08_02

    def test_c0801_still_reports_slotting_on_row_0080(self) -> None:
        """OF 08.01 keeps the slotting book — it reports on row 0080, not 0070.

        Arrange: the mixed slotting fixture.
        Act:     generate OF 08.01 for the specialised-lending sheet.
        Assert:  row 0080 ("Specialised lending slotting approach: Total") carries
                 the full 10,000 EAD and row 0070 (obligor grades) is null.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="BASEL_3_1")

        sheet = bundle.c08_01["specialised_lending"]
        assert sheet.filter(pl.col("row_ref") == "0080")["0110"][0] == pytest.approx(10000.0)
        assert sheet.filter(pl.col("row_ref") == "0070")["0110"][0] is None

    def test_row_0070_foots_the_c0802_sheet(self) -> None:
        """boe_b0752_* / boe_b0814_*: {OF08.01 r0070, c0110} = sum({OF08.02 c0110}).

        Arrange: the mixed slotting fixture.
        Act:     generate both templates for the corporate sheet.
        Assert:  row 0070's exposure value equals the sum over every C 08.02 grade
                 row — the cross-template identity the slotting rows used to break.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="BASEL_3_1")

        grades_total = bundle.c08_01["corporate"].filter(pl.col("row_ref") == "0070")["0110"][0]
        assert grades_total == pytest.approx(bundle.c08_02["corporate"]["0110"].sum())


class TestC0801RweaAdjustmentIdentity:
    """boe_b0751 / boe_b0763: {c0260} = sum({c0251; 0252; 0253; 0254})."""

    def test_slotting_rows_report_rwea_pre_adjustments(self) -> None:
        """Col 0251 falls back to the leg's own RWEA where the formula-IRB
        pre-adjustment carrier is null.

        Arrange: two slotting legs with a null ``rwa_pre_adjustments``.
        Act:     generate OF 08.01 for the specialised-lending sheet.
        Assert:  every slotting row reports 0251 == 0260 == 7,800.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="BASEL_3_1")

        sheet = bundle.c08_01["specialised_lending"]
        for ref in _SLOTTING_ROWS:
            row = sheet.filter(pl.col("row_ref") == ref)
            assert row["0251"][0] == pytest.approx(7800.0), ref
            assert row["0260"][0] == pytest.approx(7800.0), ref

    def test_adjustment_components_foot_to_the_total(self) -> None:
        """The published identity holds on every populated row of both sheets.

        Arrange: the mixed slotting fixture.
        Act:     generate OF 08.01 for both sheets.
        Assert:  0260 == 0251 + 0252 + 0253 + 0254 wherever 0260 is populated.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="BASEL_3_1")

        for sheet in bundle.c08_01.values():
            for row in sheet.iter_rows(named=True):
                if row["0260"] is None:
                    continue
                components = sum(row[ref] or 0.0 for ref in ("0251", "0252", "0253", "0254"))
                assert row["0260"] == pytest.approx(components), row["row_ref"]


class TestC0801ExposureAfterAllCrm:
    """boe_b1040: {c0104} = sum({c0090; 0101; 0102}) — "exposure after all CRM
    pre-conversion factors" is column 0090 adjusted for the slotting FCCM."""

    def test_col_0104_is_emitted(self) -> None:
        """0104 equals 0090 while the FCCM-under-slotting carriers are unwired.

        Arrange: the mixed slotting fixture.
        Act:     generate OF 08.01 for the corporate sheet.
        Assert:  the total row's 0104 equals its 0090 (8,000) rather than null.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="BASEL_3_1")

        total = bundle.c08_01["corporate"].filter(pl.col("row_ref") == "0010")
        assert total["0104"][0] == pytest.approx(8000.0)
        assert total["0104"][0] == pytest.approx(total["0090"][0])

    def test_col_0104_holds_across_both_templates(self) -> None:
        """The identity holds on every populated OF 08.01 and OF 08.02 row.

        Arrange: the mixed slotting fixture.
        Act:     generate both templates.
        Assert:  0104 == 0090 + 0101 + 0102 on the reported (signed) cells.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="BASEL_3_1")

        sheets = [*bundle.c08_01.values(), *bundle.c08_02.values()]
        for sheet in sheets:
            for row in sheet.iter_rows(named=True):
                if row["0090"] is None:
                    continue
                signed = sum(row[ref] or 0.0 for ref in ("0090", "0101", "0102"))
                assert row["0104"] == pytest.approx(signed), row["row_ref"]

    def test_crr_has_no_0104_column(self) -> None:
        """The FCCM column block is a Basel 3.1 addition — CRR C 08.01 has none.

        Arrange: the mixed slotting fixture.
        Act:     generate C 08.01 under CRR.
        Assert:  cols 0101-0104 are absent from the frame.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_slotting_results(), framework="CRR")

        columns = set(bundle.c08_01["corporate"].columns)
        assert columns.isdisjoint({"0101", "0102", "0103", "0104"})


def _over_collateralised_results() -> pl.LazyFrame:
    """One over-collateralised A-IRB mortgage plus a normally-secured control.

    RM_OVER carries 500,000 of real estate against a 300,000 exposure — the shape
    that drove col 0090 to -200,000 before the Annex II cap. RM_OK carries 100,000
    against 400,000 and must be left completely untouched, so the test can tell a
    cap from a blanket rescale.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["RM_OVER", "RM_OK"],
            "approach_applied": ["advanced_irb", "advanced_irb"],
            "exposure_class": ["retail_mortgage", "retail_mortgage"],
            "bs_type": ["ONB", "ONB"],
            "drawn_amount": [300000.0, 400000.0],
            "ead_final": [300000.0, 400000.0],
            "rwa_final": [90000.0, 140000.0],
            "pd_floored": [0.006, 0.006],
            "lgd_floored": [0.15, 0.15],
            # RD-8/W5: col 0190 reads the sealed reporting_crm_lgd_real_estate
            # twin directly, and col 0060 reads reporting_ofcp_substitution — no
            # Art. 200(1) protection here, so it is sealed 0.0, not absent.
            "reporting_crm_lgd_real_estate": [500000.0, 100000.0],
            "reporting_ofcp_substitution": [0.0, 0.0],
            "counterparty_reference": ["CP_1", "CP_2"],
        }
    )


class TestC0801OtherFundedCreditProtection:
    """Col 0060 is the Art. 232(1) substitution route (protection treated as a
    guarantee, acting on PD). The Art. 199 collateral belongs to the
    CRM-in-LGD-estimates block at cols 0190/0200/0210, which Annex II names by
    article — reporting it in both places was a double count that drove col 0090
    negative."""

    def test_art_199_collateral_is_not_in_col_0060(self) -> None:
        """Real-estate collateral does not reduce the exposure.

        Arrange: 500,000 of real estate against a 300,000 mortgage.
        Act:     generate OF 08.01.
        Assert:  col 0060 is 0.0 — the property is an LGD mitigant and has no
                 place in a substitution-effect column under either approach.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_over_collateralised_results(), framework="BASEL_3_1")

        row = bundle.c08_01["retail_mortgage"].filter(pl.col("row_ref") == "0010")
        assert row["0060"][0] == pytest.approx(0.0)

    def test_waterfall_closes_at_the_full_exposure(self) -> None:
        """Col 0090 was -200,000 on a supervisory return; it is now the exposure.

        Arrange: the over-collateralised book (700,000 gross across two legs).
        Act:     generate OF 08.01.
        Assert:  col 0090 == col 0020 — nothing in the substitution block reduces
                 it, which is the point: the collateral acts through LGD.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_over_collateralised_results(), framework="BASEL_3_1")

        row = bundle.c08_01["retail_mortgage"].filter(pl.col("row_ref") == "0010")
        assert row["0090"][0] == pytest.approx(700000.0)
        assert row["0090"][0] == pytest.approx(row["0020"][0])

    def test_no_row_reports_a_negative_exposure_after_crm(self) -> None:
        """The defect this closes, stated as the invariant.

        Arrange: the over-collateralised book.
        Act:     generate OF 08.01.
        Assert:  every populated col 0090 is >= 0.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_over_collateralised_results(), framework="BASEL_3_1")

        populated = bundle.c08_01["retail_mortgage"].filter(pl.col("0090").is_not_null())
        assert populated.height > 0
        assert (populated["0090"] >= -1e-9).all()

    def test_collateral_is_still_reported_in_the_lgd_block(self) -> None:
        """Nothing is lost: cols 0190/0200/0210 carry the Art. 199 collateral.

        Arrange: real estate on both legs (500,000 + 100,000).
        Act:     generate OF 08.01.
        Assert:  col 0190 reports the full 600,000 — Annex II cites "Article
                 199(2), (3) and (4)" for that column by name.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_over_collateralised_results(), framework="BASEL_3_1")

        row = bundle.c08_01["retail_mortgage"].filter(pl.col("row_ref") == "0010")
        assert row["0190"][0] == pytest.approx(600000.0)

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_holds_under_both_frameworks(self, framework: str) -> None:
        """CRR Annex II p.99-100 and PS1/26 Annex II say the same thing.

        Arrange: the over-collateralised book.
        Act:     generate C 08.01 / OF 08.01.
        Assert:  col 0060 empty, col 0090 the full exposure, under both.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_over_collateralised_results(), framework=framework)

        row = bundle.c08_01["retail_mortgage"].filter(pl.col("row_ref") == "0010")
        assert row["0060"][0] == pytest.approx(0.0)
        assert row["0090"][0] == pytest.approx(700000.0)

    def test_c0802_shares_the_surface(self) -> None:
        """C 08.02 reads the same value surface, so it inherits the fix.

        Arrange: the over-collateralised book.
        Act:     generate OF 08.02.
        Assert:  no grade row reports a negative col 0090.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_over_collateralised_results(), framework="BASEL_3_1")

        sheet = bundle.c08_02["retail_mortgage"]
        assert sheet.height > 0
        assert (sheet["0090"].fill_null(0.0) >= -1e-9).all()
        assert (sheet["0060"].fill_null(0.0) == 0.0).all()


class TestC0801SubstitutionBlockCap:
    """Annex II caps what legitimately remains in the block: cols 0040-0050
    "shall be capped at the exposure value", col 0060 "shall be capped at the
    value of the original exposure pre conversion factors"."""

    def test_art_232_protection_is_capped_at_the_exposure(self) -> None:
        """A third-party deposit exceeding its exposure is bounded, not dropped.

        Arrange: 400,000 of Art. 232(1) third-party deposit against a 300,000
                 exposure — the carrier col 0060 legitimately reports.
        Act:     generate OF 08.01.
        Assert:  col 0060 is -300,000 (the 400,000 raw amount capped at the
                 300,000 exposure), col 0090 lands on exactly 0, and the
                 published ``v1663_m`` identity {c0070} = {c0040}+{c0050}+{c0060}
                 holds on the SAME capped magnitude — proving the cap reaches
                 col 0060 itself rather than only the col 0070 subtotal.
        """
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["DEP_OVER"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "bs_type": ["ONB"],
                "drawn_amount": [300000.0],
                "ead_final": [300000.0],
                "rwa_final": [150000.0],
                "pd_floored": [0.01],
                "lgd_floored": [0.45],
                "third_party_deposit_value": [400000.0],
                # RD-8: col 0060 reads this sealed, routed carrier — the raw,
                # uncapped 400,000 the engine emits before the block cap is
                # applied downstream (crm_substitution.irb_protection_exprs).
                "reporting_ofcp_substitution": [400000.0],
                # No guarantee on this leg — sealed 0.0, not absent, so col
                # 0040 reads a real (capped) 0.0 rather than nulling out the
                # v1663_m identity check below.
                "guaranteed_portion": [0.0],
                "counterparty_reference": ["CP_D"],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")

        row = bundle.c08_01["corporate"].filter(pl.col("row_ref") == "0010")
        assert row["0060"][0] == pytest.approx(-300000.0)
        assert row["0090"][0] == pytest.approx(0.0)
        # v1663_m: the cap must land on col 0060 itself, not just on the col
        # 0070 subtotal — a defect that broke this identity by exactly the
        # 100,000 shed by the cap (0070 == -300,000 while an uncapped 0060
        # would report -400,000).
        assert row["0070"][0] == pytest.approx(row["0040"][0] + row["0050"][0] + row["0060"][0])
        assert row["0070"][0] == pytest.approx(-300000.0)


def _scope_of_use_results() -> pl.LazyFrame:
    """A book spanning six exposure classes, two of them outside every roll-out class.

    Corporate 5,000 IRB + 3,000 SA; corporate SME 2,000 IRB; institution 1,000 SA;
    specialised lending 4,000 slotting; retail other 1,000 IRB; equity 500 SA.
    Roll-out-class total EAD = 16,000; grand total = 16,500.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
            "approach_applied": [
                "foundation_irb",
                "standardised",
                "advanced_irb",
                "standardised",
                "slotting",
                "advanced_irb",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "specialised_lending",
                "retail_other",
                "equity",
            ],
            "ead_final": [5000.0, 3000.0, 2000.0, 1000.0, 4000.0, 1000.0, 500.0],
            "rwa_final": [3500.0, 1500.0, 1400.0, 200.0, 2800.0, 750.0, 1250.0],
        }
    )


class TestC0807CoverageAreFractions:
    """EBA v09769_m/v09771_m/v09796_m and boe_b0778 bound cols 0030/0040/0050 at
    1, not 100: the DPM datapoint carries the ratio the instructions define."""

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_coverage_shares_sum_to_one_on_populated_rows(self, framework: str) -> None:
        """0030 + 0040 + 0050 == 1 on every row that has exposure.

        Arrange: a mixed SA/IRB book.
        Act:     generate C 08.07 / OF 08.07.
        Assert:  the three shares partition each populated row exactly.

        Rows with a zero denominator are excluded: 0/0 admits no partition, and
        the published rule has no emptiness guard (a recorded residual break).
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework=framework).c08_07
        assert df is not None

        populated = df.filter(pl.col("0020").fill_null(0.0) > 0.0)
        assert populated.height > 0
        for row in populated.iter_rows(named=True):
            shares = sum(row[ref] or 0.0 for ref in ("0030", "0040", "0050"))
            assert shares == pytest.approx(1.0), row["row_ref"]

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_no_coverage_share_exceeds_one(self, framework: str) -> None:
        """v09769_m ``{c0030} <= 1`` and v09771_m ``{c0050} <= 1``.

        Arrange: a mixed SA/IRB book.
        Act:     generate C 08.07 / OF 08.07.
        Assert:  no coverage cell exceeds 1 anywhere on the sheet.
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework=framework).c08_07
        assert df is not None

        for ref in ("0030", "0040", "0050"):
            assert (df[ref].fill_null(0.0) <= 1.0).all(), ref


class TestOf0807RolloutClassAxis:
    """PS1/26 Art. 147B(1) gives eight roll-out classes; Annex II §3.3.10.2 puts
    them on rows 0180-0250 with the Total on 0260 and the aggregate
    permanent-partial-use materiality percentage on 0270."""

    def test_row_axis_matches_article_147b(self) -> None:
        """Eight class rows 0180-0250, then 0260 Total and 0270 materiality.

        Arrange: the published row list.
        Act:     read the row refs.
        Assert:  they are exactly 0180..0270 in steps of 10, with no 0280 (a row
                 the DPM does not have).
        """
        refs = [row[0] for row in B31_C08_07_ROWS]
        assert refs == ["0180", "0190", "0200", "0210", "0220", "0230", "0240", "0250"] + [
            "0260",
            "0270",
        ]

    def test_no_sovereign_roll_out_class(self) -> None:
        """PS1/26 withdraws the IRB approach for sovereigns, so they have no row.

        Arrange: the published row list and the roll-out class set.
        Act:     look for a central-government binding.
        Assert:  neither carries one.
        """
        assert "central_govt_central_bank" not in B31_C08_07_ROLLOUT_CLASSES
        assert all(row[2] != "central_govt_central_bank" for row in B31_C08_07_ROWS)

    def test_total_row_foots_the_roll_out_class_rows(self) -> None:
        """boe_b0779: {r0260} = sum({r0180 .. r0250}) on the amount columns.

        Arrange: a book with equity, which is outside every roll-out class.
        Act:     generate OF 08.07.
        Assert:  the Total row foots rows 0180-0250 in cols 0010/0020/0060/0150 —
                 so equity's 500 EAD and 1,250 RWEA are correctly outside it.
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework="BASEL_3_1").c08_07
        assert df is not None

        class_rows = df.filter(
            pl.col("row_ref").is_in(
                ["0180", "0190", "0200", "0210", "0220", "0230", "0240", "0250"]
            )
        )
        total = df.filter(pl.col("row_ref") == "0260")
        for ref in ("0010", "0020", "0060", "0150"):
            assert total[ref][0] == pytest.approx(class_rows[ref].sum()), ref

    def test_total_row_excludes_non_roll_out_classes(self) -> None:
        """Equity is reported nowhere on OF 08.07, so the Total is 16,000 not 16,500.

        Arrange: a book carrying 500 equity EAD and 1,250 equity RWEA.
        Act:     generate OF 08.07.
        Assert:  the Total row's exposure and RWEA exclude both.
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework="BASEL_3_1").c08_07
        assert df is not None

        total = df.filter(pl.col("row_ref") == "0260")
        assert total["0020"][0] == pytest.approx(16000.0)
        assert total["0060"][0] == pytest.approx(10150.0)

    def test_combined_corporates_row_unions_sme_and_non_sme(self) -> None:
        """Art. 147B(1)(d) is ONE roll-out class over 147(2)(c)(ii) and (c)(iii).

        Arrange: 8,000 corporate EAD and 2,000 corporate-SME EAD.
        Act:     generate OF 08.07.
        Assert:  row 0210 reports their union, 10,000.
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework="BASEL_3_1").c08_07
        assert df is not None

        row = df.filter(pl.col("row_ref") == "0210")
        assert row["0020"][0] == pytest.approx(10000.0)
        assert row["0010"][0] == pytest.approx(7000.0)

    def test_purchased_receivable_rows_are_structurally_null(self) -> None:
        """Rows 0200/0240 are roll-out classes with no Art. 147(2) counterpart.

        Arrange: a book with no purchased receivables.
        Act:     generate OF 08.07.
        Assert:  both rows render all-null rather than a misleading 0.0.
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework="BASEL_3_1").c08_07
        assert df is not None

        for ref in ("0200", "0240"):
            row = df.filter(pl.col("row_ref") == ref)
            assert row["0020"][0] is None, ref
            assert row["0060"][0] is None, ref

    def test_slotting_reports_on_the_specialised_lending_row(self) -> None:
        """Col 0050 counts slotting as IRB (PS1/26 Annex II §3.3.10.2 col 0050).

        Arrange: 4,000 EAD of slotting specialised lending.
        Act:     generate OF 08.07.
        Assert:  row 0190 is fully IRB.
        """
        gen = LedgerShimCorepGenerator()
        df = gen.generate_from_lazyframe(_scope_of_use_results(), framework="BASEL_3_1").c08_07
        assert df is not None

        row = df.filter(pl.col("row_ref") == "0190")
        assert row["0010"][0] == pytest.approx(4000.0)
        assert row["0050"][0] == pytest.approx(1.0)
