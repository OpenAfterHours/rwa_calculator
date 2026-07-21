"""COREP C 08.02 / OF 08.02 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import (
    _get_total_row,
    _irb_results,
)


class TestC0802:
    """Tests for C 08.02 IRB PD grade breakdown template."""

    def test_c0802_produces_per_class_output(self) -> None:
        """C 08.02 produces a dict keyed by IRB exposure class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert isinstance(bundle.c08_02, dict)
        assert "corporate" in bundle.c08_02

    def test_c0802_pd_bands_assigned(self) -> None:
        """Exposures are assigned to correct PD bands."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_names = corp["row_name"].to_list()

        # PD=0.005 -> "0.25% - 0.50%" band (0.005 = 0.5%)
        assert any("0.50%" in b for b in band_names)

    def test_c0802_per_band_ead(self) -> None:
        """EAD aggregated per PD band."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]

        # Corp PD=0.005 (0.50%) -> "0.50% - 0.75%" band, EAD=5500
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        assert band_050["0110"][0] == pytest.approx(5500.0)

        # Corp PD=0.01 (1.00%) -> "0.75% - 2.50%" band, EAD=3000
        band_075 = corp.filter(pl.col("row_name") == "0.75% - 2.50%")
        assert band_075["0110"][0] == pytest.approx(3000.0)

    def test_c0802_weighted_pd_per_band(self) -> None:
        """Weighted PD within a single-exposure band equals the exposure PD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        assert band_050["0010"][0] == pytest.approx(0.005)

    def test_c0802_has_obligor_grade_identifier(self) -> None:
        """C 08.02 rows include obligor grade identifier (col 0005)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        assert "0005" in corp.columns

    def test_c0802_maturity_in_days(self) -> None:
        """C 08.02 maturity (col 0250) is also in days."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        # Single exposure: maturity = 2.5 years = 912.5 days
        assert band_050["0250"][0] == pytest.approx(2.5 * 365.0, rel=1e-4)


def _irb_results_sme_factor() -> pl.LazyFrame:
    """CRR IRB corporate_sme exposures (both PD=2%, one band) with the SME
    supporting factor applied — the shared C 08.01/02 value surface, so col
    0256 must negate on C 08.02 exactly as on C 08.01.

        0255 = Σ rwa_pre_factor = 16000; delta = 2400; 0256 = -2400; 0260 = 13600.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_SME_1", "IRB_SME_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate_sme", "corporate_sme"],
            "drawn_amount": [10000.0, 6000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [10000.0, 6000.0],
            "rwa_final": [8500.0, 5100.0],
            "rwa_pre_factor": [10000.0, 6000.0],
            "risk_weight": [0.85, 0.85],
            "pd_floored": [0.02, 0.02],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5],
            "expected_loss": [90.0, 54.0],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_S1", "CP_S2"],
            "sme_supporting_factor_applied": [True, True],
            "is_sme": [True, True],
        }
    )


class TestC0802SignConvention:
    """Annex II §1.3 "(-)" negation applies to C 08.02 the same as C 08.01 (item R2)."""

    def test_crr_0256_negated_per_pd_band(self) -> None:
        """CRR col 0256 (SME supporting-factor adjustment) is reported negative,
        and 0255 + 0256 foots to 0260 on the populated PD-band row."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_sme_factor(), framework="CRR")
        corp_sme = bundle.c08_02["corporate_sme"]
        band = corp_sme.filter(pl.col("0255").is_not_null() & (pl.col("0255") > 0.0))
        assert band.height == 1  # both SME rows fall in one PD band
        assert band["0256"][0] == pytest.approx(-2400.0)
        assert band["0256"][0] <= 0.0
        assert band["0255"][0] + band["0256"][0] == pytest.approx(band["0260"][0])


def _irb_results_on_off_bs() -> pl.LazyFrame:
    """One on-BS loan + one off-BS facility (with a guarantee), both PD=1%,
    in the corporate class — the shared C 08.01/02 value surface, so the two
    off-BS memo columns must compute on their recorded bases here too (R11).

    Both legs fall in one PD band. Hand-calc (mirroring _crm_waterfall):
        0100 = off-BS gross (2000) - off-BS guarantee (500) = 1500 (pre-CCF)
        0120 = off-BS ead 1000                              = 1000 (post-CCF)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_ON_1", "IRB_OFF_1"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "exposure_type": ["loan", "facility"],
            "drawn_amount": [5000.0, 0.0],
            "undrawn_amount": [0.0, 2000.0],
            "ead_final": [5000.0, 1000.0],
            "rwa_final": [3500.0, 700.0],
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
        }
    )


class TestC0802OffBalanceSheetMemo:
    """R11: C 08.02 shares the C 08.01 value surface, so its per-PD-band rows
    carry the same off-BS memos — 0100 (pre-CCF waterfall slice) and 0120
    (post-CCF off-BS exposure value)."""

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_off_bs_memos_on_populated_band(self, framework: str) -> None:
        """The single populated PD band reports 0100 = 1500 (pre-CCF) and
        0120 = 1000 (post-CCF off-BS ead)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_on_off_bs(), framework=framework)
        corp = bundle.c08_02["corporate"]
        # Both legs (PD 1%) fall in one band -> a single populated row.
        assert corp.height == 1
        band = corp.row(0, named=True)
        assert band["0110"] == pytest.approx(6000.0)
        assert band["0100"] == pytest.approx(1500.0)
        assert band["0120"] == pytest.approx(1000.0)


def _irb_results_cross_class_substitution() -> pl.LazyFrame:
    """IRB corporate exposure guaranteed INTO the institution class.

    IRB_CORP_2's guaranteed portion (800) is substituted from corporate
    (pre) into institution (post) — a cross-class inflow into institution.
    IRB_INST_1 is the sole institution-origin leg. So on C 08.01 the
    institution sheet's Total row carries an 800 substitution inflow (col
    0080), while the corporate sheet carries the matching 800 outflow (col
    0070). Mirrors the shape of ``test_cross.py::_irb_results_with_substitution``.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
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
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            "bs_type": ["ONB", "ONB", "ONB"],
            "guaranteed_portion": [0.0, 800.0, 0.0],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": ["corporate", "institution", "institution"],
        }
    )


class TestC0802SubstitutionInflowDisposition:
    """R12 — recorded decision: C 08.02 (the by-PD-grade breakdown) deliberately
    does NOT receive the cross-class substitution INFLOW (col 0080), so the
    inflow is a MONITORED, documented divergence from C 08.01 — not silent drift.

    Basis (see ``corep/c08.py`` module docstring): C 08 keys every sheet on the
    obligor-basis ``reporting_class_origin``. A guaranteed leg substituted from
    class X into class Y sits in X's ORIGIN sheet (reported as an OUTFLOW, col
    0070, at the OBLIGOR's grade) and carries the obligor's PD grade, never the
    guarantor's — so the inflow into Y is composed of legs that never appear in
    Y's partition. C 08.01 lands that per-destination-class scalar on its Total
    row; C 08.02 has no Total row and no origin-basis grade home for it, so 0080
    stays 0.0 on every grade row. Attributing it per grade would require the
    guarantor's rating grade sealed per-leg (a deferred engine enhancement).

    Fixture: IRB_CORP_2 (corporate, PD 1%, guaranteed_portion 800) migrates into
    institution; IRB_INST_1 (institution, PD 0.2%) is the sole institution-origin
    leg. Inflow into institution = 800.
    """

    _INFLOW = 800.0

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_destination_sheet_has_zero_inflow(self, framework: str) -> None:
        """C 08.02[institution] carries NO substitution inflow under either
        framework: col 0080 sums to 0.0 across its grade rows (the inflow legs
        are not in this origin partition)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_cross_class_substitution(), framework=framework
        )
        inst = bundle.c08_02["institution"]
        assert inst["0080"].fill_null(0.0).sum() == pytest.approx(0.0)

    def test_inflow_diverges_from_c0801_total(self) -> None:
        """The monitored divergence: the sum of C 08.02[institution] col 0080 is
        0.0, while C 08.01's Total row carries the full inflow (800) — the two
        differ by exactly the inbound amount."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_cross_class_substitution())
        c0802_inflow = bundle.c08_02["institution"]["0080"].fill_null(0.0).sum()
        c0801_inflow = _get_total_row(bundle.c08_01["institution"])["0080"][0]
        assert c0801_inflow == pytest.approx(self._INFLOW)
        assert c0802_inflow == pytest.approx(0.0)
        assert c0801_inflow - c0802_inflow == pytest.approx(self._INFLOW)

    def test_exposure_after_substitution_short_by_inflow(self) -> None:
        """Correspondingly, C 08.02[institution] col 0090 (exposure after CRM
        substitution) is short of C 08.01's Total 0090 by the inflow: the grade
        breakdown foots the origin book (0020 only), while the C 08.01 total adds
        the inbound 800 on top."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_cross_class_substitution())
        c0802_0090 = bundle.c08_02["institution"]["0090"].fill_null(0.0).sum()
        c0801_0090 = _get_total_row(bundle.c08_01["institution"])["0090"][0]
        assert c0801_0090 - c0802_0090 == pytest.approx(self._INFLOW)

    def test_outflow_side_reconciles(self) -> None:
        """Positive control — the divergence is inflow-only: on the ORIGIN sheet
        the substitution OUTFLOW (col 0070) reconciles between C 08.02 and
        C 08.01 (both -800 after the Annex II §1.3 negation)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_cross_class_substitution())
        c0802_outflow = bundle.c08_02["corporate"]["0070"].fill_null(0.0).sum()
        c0801_outflow = _get_total_row(bundle.c08_01["corporate"])["0070"][0]
        assert c0801_outflow == pytest.approx(-self._INFLOW)
        assert c0802_outflow == pytest.approx(c0801_outflow)
