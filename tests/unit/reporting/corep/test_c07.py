"""COREP C 07.00 / OF 07.00 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import (
    B31_C07_COLUMNS,
    CRR_C07_COLUMNS,
)
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import (
    _combined_results,
    _get_total_row,
    _sa_results,
    _sa_results_with_currency_mismatch,
    _sa_results_with_phase2_cols,
)


def _sa_results_with_ccf() -> pl.LazyFrame:
    """SA results with off-BS exposures and CCF values for Phase 2C testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_ON_1",
                "SA_OFF_0",
                "SA_OFF_20",
                "SA_OFF_50",
                "SA_OFF_100",
            ],
            "approach_applied": ["standardised"] * 5,
            "exposure_class": ["corporate"] * 5,
            "drawn_amount": [5000.0, 0.0, 0.0, 0.0, 0.0],
            "undrawn_amount": [0.0, 1000.0, 2000.0, 3000.0, 500.0],
            "ead_final": [5000.0, 0.0, 400.0, 1500.0, 500.0],
            "rwa_final": [5000.0, 0.0, 400.0, 1500.0, 500.0],
            "risk_weight": [1.0, 1.0, 1.0, 1.0, 1.0],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 3, 3, 3, 3],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "bs_type": ["ONB", "OFB", "OFB", "OFB", "OFB"],
            "ccf_applied": [None, 0.0, 0.2, 0.5, 1.0],
        }
    )


def _get_rw_row(df: pl.DataFrame, rw_label: str) -> pl.DataFrame:
    """Get a risk weight breakdown row by its label (e.g., '100%')."""
    return df.filter(pl.col("row_name") == rw_label)


def _sa_results_with_own_funds_deduction() -> pl.LazyFrame:
    """SA results with own_funds_deduction_amount for P2.12 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_OFD_1"],
            "approach_applied": ["standardised"],
            "exposure_class": ["corporate"],
            "drawn_amount": [1000.0],
            "undrawn_amount": [0.0],
            "ead_final": [1000.0],
            "rwa_final": [1000.0],
            "rwa_pre_factor": [1000.0],
            "risk_weight": [1.0],
            "scra_provision_amount": [30.0],
            "gcra_provision_amount": [0.0],
            "collateral_adjusted_value": [0.0],
            "guaranteed_portion": [0.0],
            "sa_cqs": [None],
            "bs_type": ["OB"],
            "ccf_applied": [None],
            "own_funds_deduction_amount": [200.0],
        }
    )


def _sa_results_without_own_funds_deduction() -> pl.LazyFrame:
    """SA results WITHOUT own_funds_deduction_amount for P2.12 absent-column test."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_NO_OFD_1"],
            "approach_applied": ["standardised"],
            "exposure_class": ["corporate"],
            "drawn_amount": [1000.0],
            "undrawn_amount": [0.0],
            "ead_final": [1000.0],
            "rwa_final": [1000.0],
            "risk_weight": [1.0],
            "scra_provision_amount": [30.0],
            "gcra_provision_amount": [0.0],
            "collateral_adjusted_value": [0.0],
            "guaranteed_portion": [0.0],
            "sa_cqs": [None],
        }
    )


def _sa_results_with_sl() -> pl.LazyFrame:
    """SA results with specialised lending types and project phases for Task 3G."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_SL_OF_1",
                "SA_SL_CF_1",
                "SA_SL_PF_PRE_1",
                "SA_SL_PF_OP_1",
                "SA_SL_PF_HQ_1",
            ],
            "approach_applied": ["standardised"] * 6,
            "exposure_class": ["corporate"] * 6,
            "drawn_amount": [1000.0, 500.0, 300.0, 200.0, 400.0, 600.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 500.0, 300.0, 200.0, 400.0, 600.0],
            "rwa_final": [1000.0, 500.0, 300.0, 260.0, 400.0, 360.0],
            "risk_weight": [1.00, 1.00, 1.00, 1.30, 1.00, 0.60],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "collateral_adjusted_value": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, None, None, None, None, None],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E", "CP_F"],
            # SL type: None for non-SL, specific type for SL exposures
            "sl_type": [
                None,
                "object_finance",
                "commodities_finance",
                "project_finance",
                "project_finance",
                "project_finance",
            ],
            # Project phase: only for project_finance exposures
            "sl_project_phase": [
                None,
                None,
                None,
                "pre_operational",
                "operational",
                "high_quality_operational",
            ],
        }
    )


def _sa_results_with_re() -> pl.LazyFrame:
    """SA results with real estate columns for Task 3H testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_RE_RES_1",
                "SA_RE_RES_2",
                "SA_RE_COMM_1",
                "SA_RE_COMM_2",
                "SA_RE_COMM_3",
                "SA_RE_ADC_1",
                "SA_CORP_1",
            ],
            "approach_applied": ["standardised"] * 7,
            "exposure_class": [
                "secured_by_re_residential",
                "secured_by_re_residential",
                "secured_by_re_commercial",
                "secured_by_re_commercial",
                "secured_by_re_commercial",
                "secured_by_re_commercial",
                "corporate",
            ],
            "drawn_amount": [200.0, 300.0, 500.0, 400.0, 150.0, 100.0, 1000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [200.0, 300.0, 500.0, 400.0, 150.0, 100.0, 1000.0],
            "rwa_final": [40.0, 105.0, 300.0, 240.0, 112.5, 150.0, 1000.0],
            "risk_weight": [0.20, 0.35, 0.60, 0.60, 0.75, 1.50, 1.00],
            "scra_provision_amount": [0.0] * 7,
            "gcra_provision_amount": [0.0] * 7,
            "collateral_adjusted_value": [0.0] * 7,
            "guaranteed_portion": [0.0] * 7,
            "sa_cqs": [None] * 7,
            "counterparty_reference": [
                "CP_R1",
                "CP_R2",
                "CP_C1",
                "CP_C2",
                "CP_C3",
                "CP_ADC",
                "CP_CORP",
            ],
            "property_type": [
                "residential",
                "residential",
                "commercial",
                "commercial",
                "commercial",
                "commercial",
                None,
            ],
            "materially_dependent_on_property": [
                False,
                True,
                False,
                True,
                False,
                None,
                None,
            ],
            "is_adc": [False, False, False, False, False, True, False],
            # SME flag for commercial sub-split
            "sme_supporting_factor_eligible": [
                False,
                False,
                False,
                False,
                True,
                False,
                False,
            ],
        }
    )


def _sa_results_with_defaulted() -> pl.LazyFrame:
    """SA results with defaulted exposures at different risk weights.

    Contains:
    - 2 defaulted corporate exposures: one at RW 100%, one at RW 150%
    - 1 non-defaulted corporate (RW 100%) to verify filtering
    - 1 defaulted retail at RW 150%
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_DEF_100",
                "SA_DEF_150",
                "SA_CORP_LIVE",
                "SA_RET_DEF",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "retail_other",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 500.0],
            "undrawn_amount": [0.0, 0.0, 500.0, 0.0],
            "ead_final": [1000.0, 2000.0, 3200.0, 500.0],
            "rwa_final": [1000.0, 3000.0, 3200.0, 750.0],
            "risk_weight": [1.00, 1.50, 1.00, 1.50],
            "default_status": [True, True, False, True],
            "scra_provision_amount": [50.0, 100.0, 10.0, 25.0],
            "gcra_provision_amount": [0.0, 0.0, 5.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [None, None, 3, None],
        }
    )


def _sa_results_with_re_memorandum() -> pl.LazyFrame:
    """SA results with RE-secured exposures for CRR memorandum rows 0290/0310.

    Contains:
    - 2 commercial RE-secured exposures (EAD 1000 + 2000)
    - 1 residential RE-secured exposure (EAD 3000)
    - 1 non-RE exposure
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CRE_1",
                "SA_CRE_2",
                "SA_RRE_1",
                "SA_PLAIN",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "secured_by_re_property",
                "secured_by_re_property",
                "secured_by_re_property",
                "corporate",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 4000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 3000.0, 4000.0],
            "rwa_final": [500.0, 1000.0, 1050.0, 4000.0],
            "risk_weight": [0.50, 0.50, 0.35, 1.00],
            "property_type": ["commercial", "commercial", "residential", None],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [None, None, None, 3],
        }
    )


def _sa_results_with_supporting_factors() -> pl.LazyFrame:
    """SA results with supporting factor data for CRR rows 0030/0035.

    All exposures are "corporate" class. The is_sme/is_infrastructure flags
    indicate which supporting factor applies. In a real pipeline, the
    classifier sets these flags while keeping exposure_class as "corporate".

    Contains:
    - 2 SME corporate exposures with supporting factor applied
    - 1 infrastructure corporate exposure with supporting factor applied
    - 1 plain corporate (no factor)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_SME_1",
                "SA_SME_2",
                "SA_INFRA_1",
                "SA_CORP_1",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
            ],
            "drawn_amount": [1000.0, 2000.0, 5000.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 500.0],
            "ead_final": [1000.0, 2000.0, 5000.0, 3200.0],
            "rwa_final": [700.0, 1400.0, 3750.0, 3200.0],
            "risk_weight": [1.00, 1.00, 1.00, 1.00],
            "rwa_pre_factor": [1000.0, 2000.0, 5000.0, 3200.0],
            "supporting_factor_applied": [True, True, True, False],
            "is_sme": [True, True, False, False],
            "is_infrastructure": [False, False, True, False],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [3, 3, 3, 3],
        }
    )


class TestC0700:
    """Tests for C 07.00 SA credit risk template generation.

    The generator now produces one DataFrame per exposure class, each with
    5 row sections and 4-digit COREP column references.
    """

    def test_c07_produces_per_class_output(self) -> None:
        """C 07.00 produces a dict keyed by exposure class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert isinstance(bundle.c07_00, dict)
        assert "corporate" in bundle.c07_00
        assert "institution" in bundle.c07_00
        assert "retail_other" in bundle.c07_00
        assert "central_govt_central_bank" in bundle.c07_00

    def test_c07_each_class_has_row_sections(self) -> None:
        """Each per-class DataFrame has rows from all 5 sections."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        row_refs = corp["row_ref"].to_list()

        # Section 1: Total row (0010) must be present
        assert "0010" in row_refs
        # Section 2: Exposure type rows
        assert "0070" in row_refs  # On-BS
        assert "0080" in row_refs  # Off-BS
        # Section 3: Risk weight rows
        assert "0230" in row_refs  # 100% RW
        # Section 4: CIU approach
        assert "0281" in row_refs
        # Section 5: Memorandum
        assert "0290" in row_refs or "0300" in row_refs

    def test_c07_uses_4_digit_column_refs(self) -> None:
        """DataFrame columns use 4-digit COREP refs."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        cols = set(corp.columns)

        # Key COREP columns should be present
        assert "0010" in cols  # Original exposure
        assert "0030" in cols  # Provisions
        assert "0040" in cols  # Net exposure
        assert "0200" in cols  # Exposure value
        assert "0220" in cols  # RWEA

    def test_c07_total_row_original_exposure(self) -> None:
        """Total row (0010) aggregates original exposure correctly."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # 2 corporate exposures: drawn 1000+2000=3000, undrawn 500+0=500
        assert corp["0010"][0] == pytest.approx(3500.0)

    def test_c07_total_row_provisions(self) -> None:
        """Provisions (col 0030) sum SCRA + GCRA amounts — emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Corp provisions: (10+5) + (20+10) = 45; stored as negative deduction
        assert corp["0030"][0] == pytest.approx(-45.0)

    def test_c07_total_row_net_exposure(self) -> None:
        """Net exposure (col 0040) = original - provisions."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # 3500 - 45 = 3455
        assert corp["0040"][0] == pytest.approx(3455.0)

    def test_c07_total_row_guarantees(self) -> None:
        """Guarantees (col 0050) are aggregated correctly — emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Corp guarantees: 0 + 500 = 500; stored as negative deduction
        assert corp["0050"][0] == pytest.approx(-500.0)

    def test_c07_total_row_collateral(self) -> None:
        """Collateral (col 0130) is aggregated correctly — emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Corp collateral: 100 + 0 = 100; stored as negative deduction
        assert corp["0130"][0] == pytest.approx(-100.0)

    def test_c07_total_row_ead(self) -> None:
        """Exposure value (col 0200) matches EAD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # EAD: 1200 + 2000 = 3200
        assert corp["0200"][0] == pytest.approx(3200.0)

    def test_c07_total_row_rwea(self) -> None:
        """RWEA (col 0220) matches RWA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # RWA: 1200 + 2000 = 3200
        assert corp["0220"][0] == pytest.approx(3200.0)

    def test_c07_zero_rw_for_sovereign(self) -> None:
        """Central government with CQS 1 gets 0% RW, hence 0 RWEA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        sovn = _get_total_row(bundle.c07_00["central_govt_central_bank"])
        assert sovn["0220"][0] == pytest.approx(0.0)
        assert sovn["0200"][0] == pytest.approx(5000.0)

    def test_c07_ecai_assessment(self) -> None:
        """ECAI column (0230) only includes rated exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # All corp exposures have sa_cqs not null -> all RWA is rated
        assert corp["0230"][0] == pytest.approx(3200.0)

    def test_c07_no_irb_in_sa_output(self) -> None:
        """C 07.00 dict must not include IRB-only exposure classes."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # retail_mortgage is IRB-only in test data
        assert "retail_mortgage" not in bundle.c07_00

    def test_c07_empty_results(self) -> None:
        """C 07.00 handles empty results gracefully."""
        gen = LedgerShimCorepGenerator()
        empty = pl.LazyFrame(
            schema={
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(empty)
        assert bundle.c07_00 == {}


class TestC0700RiskWeightSection:
    """Tests for C 07.00 Section 3: Risk weight band breakdown.

    Risk weight breakdown is now integrated as Section 3 of each
    per-class DataFrame (no longer a separate template).
    """

    def test_rw_section_100pct_for_corporates(self) -> None:
        """Corporates with RW=1.00 appear in the 100% row."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        rw_100 = _get_rw_row(corp, "100%")

        # EAD: 1200 + 2000 = 3200 (both corps are 100% RW)
        assert len(rw_100) == 1
        assert rw_100["0200"][0] == pytest.approx(3200.0)

    def test_rw_section_0pct_for_sovereign(self) -> None:
        """Sovereign with 0% RW appears in the 0% row."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        sovn = bundle.c07_00["central_govt_central_bank"]
        rw_0 = _get_rw_row(sovn, "0%")

        assert len(rw_0) == 1
        assert rw_0["0200"][0] == pytest.approx(5000.0)

    def test_rw_section_75pct_for_retail(self) -> None:
        """Retail exposures with 75% RW appear in the 75% row."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        retail = bundle.c07_00["retail_other"]
        rw_75 = _get_rw_row(retail, "75%")

        # EAD: 225 + 300 = 525
        assert len(rw_75) == 1
        assert rw_75["0200"][0] == pytest.approx(525.0)

    def test_rw_section_empty_bands_are_null(self) -> None:
        """RW bands with no exposures have null values."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        # Corporates are all 100% RW, so 0% band should be null
        rw_0 = _get_rw_row(corp, "0%")
        assert len(rw_0) == 1
        assert rw_0["0200"][0] is None

    def test_rw_section_rwea_populated(self) -> None:
        """RW section rows have RWEA values populated."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        retail = bundle.c07_00["retail_other"]
        rw_75 = _get_rw_row(retail, "75%")
        # RWA: 168.75 + 225.0 = 393.75
        assert rw_75["0220"][0] == pytest.approx(393.75)


class TestSupportingFactors:
    """Tests for CRR supporting factor columns 0215-0217 (C 07.00) and 0255-0257 (C 08.01)."""

    def test_c07_supporting_factor_pre_rwea(self) -> None:
        """Col 0215 (RWEA pre factors) is populated from rwa_before_sme_factor."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # corporate has 3 exposures: rwa_before_sme_factor = 1200+2000+1200 = 4400
        assert corp["0215"][0] == pytest.approx(4400.0)

    def test_c07_sme_factor_benefit(self) -> None:
        """Col 0216 (SME factor benefit) = pre - post, emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        sme = _get_total_row(bundle.c07_00["corporate_sme"])
        # rwa_before_sme_factor=550, rwa_final=467.5, benefit=82.5; negative deduction.
        assert sme["0216"][0] == pytest.approx(-82.5)

    def test_c07_infra_factor_benefit(self) -> None:
        """Col 0217 (infra factor benefit) computed, emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_1 infra_factor_applied=True: pre=1200, post=1140, benefit=60; negative.
        assert corp["0217"][0] == pytest.approx(-60.0)

    def test_c07_supporting_factors_not_in_b31(self) -> None:
        """Supporting factor columns (0215-0217) absent from Basel 3.1 output."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = next(iter(bundle.c07_00.values()))
        assert "0215" not in corp.columns
        assert "0216" not in corp.columns
        assert "0217" not in corp.columns

    def test_c07_rwea_relationship(self) -> None:
        """Col 0220 = 0215 + 0216 + 0217 under the "(-)" display convention."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        sme = _get_total_row(bundle.c07_00["corporate_sme"])
        pre = sme["0215"][0]
        sme_benefit = sme["0216"][0]  # negative per Annex II §1.3
        post = sme["0220"][0]
        # pre + sme_benefit = post (no infra for SME class; 0216 already signed)
        assert post == pytest.approx(pre + sme_benefit)


class TestECAIUnratedSplit:
    """Tests for Basel 3.1 ECAI unrated split column 0235."""

    def test_b31_ecai_unrated_column_present(self) -> None:
        """Col 0235 (without ECAI) present in Basel 3.1 output."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = next(iter(bundle.c07_00.values()))
        assert "0235" in corp.columns

    def test_b31_unrated_exposure_in_0235(self) -> None:
        """Unrated exposure (sa_cqs=null) RWA goes to col 0235."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_DEF_1 has sa_cqs=None, rwa_final=1200 -> goes to 0235
        assert corp["0235"][0] == pytest.approx(1200.0)

    def test_b31_rated_plus_unrated_equals_total(self) -> None:
        """Col 0230 (rated) + col 0235 (unrated) = col 0220 (total RWEA)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c07_00["corporate"])
        rated = corp["0230"][0]
        unrated = corp["0235"][0]
        total = corp["0220"][0]
        assert rated + unrated == pytest.approx(total)


class TestCCFBreakdown:
    """Tests for off-BS CCF breakdown columns 0160-0190."""

    def test_c07_ccf_columns_populated(self) -> None:
        """CCF breakdown columns are populated when ccf_applied is available."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # 0% CCF: EAD=0, 20% CCF: EAD=400, 50% CCF: EAD=1500, 100% CCF: EAD=500
        assert corp["0160"][0] == pytest.approx(0.0)  # 0% bucket
        assert corp["0170"][0] == pytest.approx(400.0)  # 20% bucket
        assert corp["0180"][0] == pytest.approx(1500.0)  # 50% bucket
        assert corp["0190"][0] == pytest.approx(500.0)  # 100% bucket

    def test_c07_ccf_sum_equals_off_bs_ead(self) -> None:
        """Sum of CCF columns = total off-BS EAD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        corp = _get_total_row(bundle.c07_00["corporate"])
        ccf_sum = (
            (corp["0160"][0] or 0.0)
            + (corp["0170"][0] or 0.0)
            + (corp["0180"][0] or 0.0)
            + (corp["0190"][0] or 0.0)
        )
        # Off-BS EAD: 0+400+1500+500=2400
        assert ccf_sum == pytest.approx(2400.0)

    def test_c07_ccf_null_without_column(self) -> None:
        """CCF columns are null when ccf_applied not in data."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0160"][0] is None
        assert corp["0170"][0] is None

    def test_b31_ccf_includes_40pct_bucket(self) -> None:
        """Basel 3.1 has 0171 (40% CCF) column; 0160 maps to 10% CCF."""
        # Create B3.1 data with 10% and 40% CCF values
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SA_OFF_10", "SA_OFF_40"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "drawn_amount": [0.0, 0.0],
                "undrawn_amount": [1000.0, 2000.0],
                "ead_final": [100.0, 800.0],
                "rwa_final": [100.0, 800.0],
                "risk_weight": [1.0, 1.0],
                "sa_cqs": [3, 3],
                "counterparty_reference": ["CP_A", "CP_B"],
                "bs_type": ["OFB", "OFB"],
                "ccf_applied": [0.1, 0.4],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert "0171" in corp.columns
        assert corp["0160"][0] == pytest.approx(100.0)  # 10% bucket
        assert corp["0171"][0] == pytest.approx(800.0)  # 40% bucket

    def test_c07_ccf_on_rw_section_rows(self) -> None:
        """CCF breakdown also works within risk weight section rows."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        corp = bundle.c07_00["corporate"]
        rw_100 = corp.filter(pl.col("row_name") == "100%")
        if len(rw_100) > 0:
            # All exposures are RW=100%, so RW section should match total CCF
            assert rw_100["0170"][0] == pytest.approx(400.0)


class TestC0700Col0020:
    """P2.12: COREP C 07.00 col 0020 — Exposures deducted from own funds.

    Why: CRR Art. 111(1)(b) and Basel 3.1 SA rules require that exposures
    deducted from own funds are reported separately in the C 07.00 waterfall
    (between col 0010 Original exposure and col 0030 Provisions). Without col
    0020, the deduction is invisible in COREP reporting and auditors cannot
    reconcile the EAD waterfall.
    """

    def test_crr_c0700_has_col_0020_with_value(self) -> None:
        """CRR C 07.00 corporate row reports own_funds_deduction_amount in col 0020."""
        # Arrange
        gen = LedgerShimCorepGenerator()
        lf = _sa_results_with_own_funds_deduction()

        # Act
        bundle = gen.generate_from_lazyframe(lf, framework="CRR")
        corp = _get_total_row(bundle.c07_00["corporate"])

        # Assert: col 0020 present and carries the expected deduction value
        cols = corp.columns
        assert "0020" in cols, f"Col 0020 missing from CRR C 07.00 output; got: {cols}"
        idx_0020 = cols.index("0020")
        idx_0010 = cols.index("0010")
        idx_0030 = cols.index("0030")
        assert idx_0010 < idx_0020 < idx_0030
        assert corp["0020"][0] == pytest.approx(200.0)

    def test_b31_of0700_has_col_0020_with_value(self) -> None:
        """Basel 3.1 OF 07.00 corporate row reports own_funds_deduction_amount in col 0020."""
        # Arrange
        gen = LedgerShimCorepGenerator()
        lf = _sa_results_with_own_funds_deduction()

        # Act
        bundle = gen.generate_from_lazyframe(lf, framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])

        # Assert: col 0020 present and carries the expected deduction value
        cols = corp.columns
        assert "0020" in cols, f"Col 0020 missing from B3.1 OF 07.00 output; got: {cols}"
        idx_0020 = cols.index("0020")
        idx_0010 = cols.index("0010")
        idx_0030 = cols.index("0030")
        assert idx_0010 < idx_0020 < idx_0030
        assert corp["0020"][0] == pytest.approx(200.0)

    def test_c0700_col_0020_is_none_when_field_absent(self) -> None:
        """Without own_funds_deduction_amount in data, col 0020 is None."""
        # Arrange
        gen = LedgerShimCorepGenerator()
        lf = _sa_results_without_own_funds_deduction()

        # Act
        bundle = gen.generate_from_lazyframe(lf, framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])

        # Assert: column is present but value is None (same pattern as col 0035 test)
        assert "0020" in corp.columns, (
            f"Col 0020 missing from B3.1 OF 07.00 output; got: {corp.columns}"
        )
        assert corp["0020"][0] is None

    def test_col_0020_in_template_definition_between_0010_and_0030(self) -> None:
        """CRR_C07_COLUMNS and B31_C07_COLUMNS both contain a col 0020 between 0010 and 0030."""
        # Arrange / Act — use the imported column definitions directly
        for col_list in (CRR_C07_COLUMNS, B31_C07_COLUMNS):
            refs = [c.ref for c in col_list]

            # Assert presence
            assert "0020" in refs, f"Column 0020 missing from {col_list!r}"

            # Assert ordering
            idx_0020 = refs.index("0020")
            idx_0010 = refs.index("0010")
            idx_0030 = refs.index("0030")
            assert idx_0010 < idx_0020 < idx_0030, (
                f"Col 0020 not between 0010 and 0030 in column list: "
                f"0010@{idx_0010}, 0020@{idx_0020}, 0030@{idx_0030}"
            )

            # Assert name
            col_0020 = next(c for c in col_list if c.ref == "0020")
            assert col_0020.name == "Exposures deducted from own funds", (
                f"Expected 'Exposures deducted from own funds', got {col_0020.name!r}"
            )


class TestSpecialisedLendingRows:
    """Task 3G: Specialised lending detail rows (B3.1 OF 07.00 rows 0021-0026).

    Why: Basel 3.1 requires separate reporting of object finance, commodities
    finance, and project finance (with phase breakdown) within each exposure
    class. These "of which" rows enable supervisors to monitor concentration
    in specialised lending sub-types.
    """

    def test_object_finance_row_populated(self) -> None:
        """Row 0021 shows object finance exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0021 = corp.filter(pl.col("row_ref") == "0021")
        assert len(row_0021) == 1
        # SA_SL_OF_1: ead_final=500
        assert row_0021["0200"][0] == pytest.approx(500.0)

    def test_commodities_finance_row_populated(self) -> None:
        """Row 0022 shows commodities finance exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0022 = corp.filter(pl.col("row_ref") == "0022")
        assert len(row_0022) == 1
        # SA_SL_CF_1: ead_final=300
        assert row_0022["0200"][0] == pytest.approx(300.0)

    def test_project_finance_row_is_total(self) -> None:
        """Row 0023 shows total project finance (all phases)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0023 = corp.filter(pl.col("row_ref") == "0023")
        assert len(row_0023) == 1
        # 3 PF exposures: 200 + 400 + 600 = 1200
        assert row_0023["0200"][0] == pytest.approx(1200.0)

    def test_project_finance_pre_operational(self) -> None:
        """Row 0024 shows pre-operational project finance."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0024 = corp.filter(pl.col("row_ref") == "0024")
        assert len(row_0024) == 1
        assert row_0024["0200"][0] == pytest.approx(200.0)

    def test_project_finance_operational(self) -> None:
        """Row 0025 shows operational project finance."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0025 = corp.filter(pl.col("row_ref") == "0025")
        assert len(row_0025) == 1
        assert row_0025["0200"][0] == pytest.approx(400.0)

    def test_project_finance_hq_operational(self) -> None:
        """Row 0026 shows high quality operational project finance."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0026 = corp.filter(pl.col("row_ref") == "0026")
        assert len(row_0026) == 1
        assert row_0026["0200"][0] == pytest.approx(600.0)

    def test_sl_rows_absent_crr(self) -> None:
        """SL detail rows don't exist under CRR (no rows 0021-0026)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        sl_rows = corp.filter(
            pl.col("row_ref").is_in(["0021", "0022", "0023", "0024", "0025", "0026"])
        )
        assert len(sl_rows) == 0

    def test_sl_rows_null_without_sl_data(self) -> None:
        """Without sl_type column, SL rows are null."""
        gen = LedgerShimCorepGenerator()
        # _sa_results() has no sl_type column
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0021 = corp.filter(pl.col("row_ref") == "0021")
        assert len(row_0021) == 1
        assert row_0021["0200"][0] is None

    def test_phase_sum_equals_total_pf(self) -> None:
        """Sum of phase rows (0024-0026) equals total project finance row (0023)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        total_pf = corp.filter(pl.col("row_ref") == "0023")["0200"][0]
        pre_op = corp.filter(pl.col("row_ref") == "0024")["0200"][0]
        op = corp.filter(pl.col("row_ref") == "0025")["0200"][0]
        hq_op = corp.filter(pl.col("row_ref") == "0026")["0200"][0]
        assert total_pf == pytest.approx(pre_op + op + hq_op)


class TestRealEstateRows:
    """Task 3H: Real estate detail rows (B3.1 OF 07.00 rows 0330-0360).

    Why: Basel 3.1 requires granular reporting of RE exposures by property
    type, cash-flow dependency, and SME status. This enables supervisors to
    assess concentration risk in property-secured lending.
    """

    def test_residential_re_total(self) -> None:
        """Row 0330 shows total regulatory residential RE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        # RE exposures are in "secured_by_re_residential" class
        re_res = bundle.c07_00.get("secured_by_re_residential")
        assert re_res is not None
        row = re_res.filter(pl.col("row_ref") == "0330")
        assert len(row) == 1
        # SA_RE_RES_1 + SA_RE_RES_2: 200 + 300 = 500
        assert row["0200"][0] == pytest.approx(500.0)

    def test_residential_not_dependent(self) -> None:
        """Row 0331: residential, not materially dependent."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        row = re_res.filter(pl.col("row_ref") == "0331")
        assert len(row) == 1
        # SA_RE_RES_1: 200 (not dependent)
        assert row["0200"][0] == pytest.approx(200.0)

    def test_residential_dependent(self) -> None:
        """Row 0332: residential, materially dependent."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        row = re_res.filter(pl.col("row_ref") == "0332")
        assert len(row) == 1
        # SA_RE_RES_2: 300 (dependent)
        assert row["0200"][0] == pytest.approx(300.0)

    def test_commercial_re_total(self) -> None:
        """Row 0340 shows total regulatory commercial RE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00.get("secured_by_re_commercial")
        assert re_comm is not None
        row = re_comm.filter(pl.col("row_ref") == "0340")
        assert len(row) == 1
        # All commercial (excl ADC): 500 + 400 + 150 + 100 = 1150
        # But property_type = commercial for all, including ADC
        assert row["0200"][0] == pytest.approx(1150.0)

    def test_commercial_not_dependent_non_sme(self) -> None:
        """Row 0341: commercial, not dependent, non-SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["secured_by_re_commercial"]
        row = re_comm.filter(pl.col("row_ref") == "0341")
        assert len(row) == 1
        # SA_RE_COMM_1: 500 (not dependent, not SME)
        assert row["0200"][0] == pytest.approx(500.0)

    def test_commercial_sme_not_dependent(self) -> None:
        """Row 0343: commercial, not dependent, SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["secured_by_re_commercial"]
        row = re_comm.filter(pl.col("row_ref") == "0343")
        assert len(row) == 1
        # SA_RE_COMM_3: 150 (not dependent, SME)
        assert row["0200"][0] == pytest.approx(150.0)

    def test_adc_row(self) -> None:
        """Row 0360 shows ADC exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["secured_by_re_commercial"]
        row = re_comm.filter(pl.col("row_ref") == "0360")
        assert len(row) == 1
        # SA_RE_ADC_1: 100
        assert row["0200"][0] == pytest.approx(100.0)

    def test_re_rows_absent_crr(self) -> None:
        """RE detail rows don't exist under CRR."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="CRR")
        re_res = bundle.c07_00.get("secured_by_re_residential")
        if re_res is not None:
            re_rows = re_res.filter(
                pl.col("row_ref").is_in(["0330", "0331", "0332", "0340", "0341", "0342", "0360"])
            )
            assert len(re_rows) == 0

    def test_dependent_splits_sum_to_total(self) -> None:
        """Rows 0331 + 0332 = 0330 for residential RE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        total = re_res.filter(pl.col("row_ref") == "0330")["0200"][0]
        not_dep = re_res.filter(pl.col("row_ref") == "0331")["0200"][0]
        dep = re_res.filter(pl.col("row_ref") == "0332")["0200"][0]
        assert total == pytest.approx(not_dep + dep)


class TestCurrencyMismatchRow:
    """Task 3J: Currency mismatch multiplier memorandum row 0380.

    Why: Basel 3.1 Art. 123B requires reporting of retail and RE exposures
    subject to the 1.5x currency mismatch RW multiplier. Row 0380 in the
    OF 07.00 memorandum section aggregates these exposures for supervisory
    transparency.
    """

    def test_b31_row_0380_populated(self) -> None:
        """Row 0380 aggregates exposures with currency mismatch applied."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        # Retail class — SA_RET_1 has mismatch, SA_RET_2 does not
        ret = bundle.c07_00["retail_other"]
        row = ret.filter(pl.col("row_ref") == "0380")
        assert len(row) == 1
        # Only SA_RET_1 (EAD=100, RWA=112.5) has mismatch
        assert row["0200"][0] == pytest.approx(100.0)
        assert row["0220"][0] == pytest.approx(112.5)

    def test_b31_mortgage_row_0380(self) -> None:
        """Row 0380 works for retail_mortgage class too."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        mort = bundle.c07_00["retail_mortgage"]
        row = mort.filter(pl.col("row_ref") == "0380")
        assert len(row) == 1
        # SA_MORT_1 has mismatch (EAD=500, RWA=375)
        assert row["0200"][0] == pytest.approx(500.0)
        assert row["0220"][0] == pytest.approx(375.0)

    def test_b31_corporate_row_0380_null(self) -> None:
        """Corporate class — no mismatch exposures → row 0380 is null."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0380")
        assert len(row) == 1
        assert row["0200"][0] is None

    def test_crr_no_row_0380(self) -> None:
        """CRR framework does not have row 0380 — it's a B3.1-only memorandum."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_currency_mismatch(), framework="CRR")
        ret = bundle.c07_00.get("retail_other")
        if ret is not None:
            row = ret.filter(pl.col("row_ref") == "0380")
            assert len(row) == 0

    def test_no_mismatch_column_row_0380_null(self) -> None:
        """Without currency_mismatch_multiplier_applied column, row 0380 is null."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = bundle.c07_00.get("corporate")
        if corp is not None:
            row = corp.filter(pl.col("row_ref") == "0380")
            if len(row) > 0:
                assert row["0200"][0] is None


class TestC0700MemorandumRows:
    """Tests for C 07.00 / OF 07.00 Section 5 memorandum rows.

    Memorandum items provide supplementary breakdowns:
    - Row 0290 (CRR): Exposures secured by mortgages on commercial immovable property
    - Row 0300: Exposures in default subject to RW of 100%
    - Row 0310 (CRR): Exposures secured by mortgages on residential immovable property
    - Row 0320: Exposures in default subject to RW of 150%

    Why: These rows are mandatory COREP fields. Previously they were
    always null, misrepresenting the institution's defaulted exposure
    distribution and RE-secured positions.

    References:
        CRR Art. 127: Defaulted exposure risk weights
        CRR Art. 124-126: Exposures secured by immovable property
    """

    def test_row_0300_defaulted_rw_100(self) -> None:
        """Row 0300 filters defaulted exposures with RW = 100%."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0300")
        assert len(row) == 1
        # SA_DEF_100 has EAD 1000, RW 100%, defaulted
        assert row["0200"][0] == pytest.approx(1000.0)
        assert row["0220"][0] == pytest.approx(1000.0)

    def test_row_0320_defaulted_rw_150(self) -> None:
        """Row 0320 filters defaulted exposures with RW = 150%."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0320")
        assert len(row) == 1
        # SA_DEF_150 has EAD 2000, RW 150%, defaulted
        assert row["0200"][0] == pytest.approx(2000.0)
        assert row["0220"][0] == pytest.approx(3000.0)

    def test_row_0300_excludes_non_defaulted(self) -> None:
        """Row 0300 must not include non-defaulted exposures even at RW 100%."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0300 = corp.filter(pl.col("row_ref") == "0300")
        # SA_CORP_LIVE is RW 100% but NOT defaulted; should be excluded
        # Only SA_DEF_100 (EAD 1000) qualifies
        assert row_0300["0200"][0] == pytest.approx(1000.0)

    def test_row_0320_retail_class(self) -> None:
        """Row 0320 applies within each exposure class independently."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        retail = bundle.c07_00["retail_other"]
        row = retail.filter(pl.col("row_ref") == "0320")
        # SA_RET_DEF has EAD 500, RW 150%, defaulted
        assert row["0200"][0] == pytest.approx(500.0)
        assert row["0220"][0] == pytest.approx(750.0)

    def test_row_0300_null_when_no_defaults_at_100(self) -> None:
        """Row 0300 is null when no defaulted exposures have RW = 100%."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        retail = bundle.c07_00["retail_other"]
        row = retail.filter(pl.col("row_ref") == "0300")
        # No defaulted retail exposures at RW 100%
        assert row["0200"][0] is None

    def test_b31_rows_0300_0320_present(self) -> None:
        """Basel 3.1 OF 07.00 also has rows 0300 and 0320."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0300" in row_refs
        assert "0320" in row_refs

    def test_b31_row_0300_populated(self) -> None:
        """B31 row 0300 is populated from defaulted exposures at RW 100%."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0300")
        assert row["0200"][0] == pytest.approx(1000.0)

    def test_row_0290_crr_commercial_re(self) -> None:
        """CRR row 0290: commercial immovable property secured exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re_memorandum(), framework="CRR")
        re = bundle.c07_00["secured_by_re_property"]
        row = re.filter(pl.col("row_ref") == "0290")
        assert len(row) == 1
        # Two commercial RE: EAD 1000 + 2000 = 3000
        assert row["0200"][0] == pytest.approx(3000.0)
        # RWA 500 + 1000 = 1500
        assert row["0220"][0] == pytest.approx(1500.0)

    def test_row_0310_crr_residential_re(self) -> None:
        """CRR row 0310: residential immovable property secured exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re_memorandum(), framework="CRR")
        re = bundle.c07_00["secured_by_re_property"]
        row = re.filter(pl.col("row_ref") == "0310")
        assert len(row) == 1
        # One residential RE: EAD 3000
        assert row["0200"][0] == pytest.approx(3000.0)
        assert row["0220"][0] == pytest.approx(1050.0)

    def test_row_0290_null_for_non_re_class(self) -> None:
        """Row 0290 is null for classes without RE-secured exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re_memorandum(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0290")
        assert row["0200"][0] is None

    def test_b31_no_rows_0290_0310(self) -> None:
        """B31 OF 07.00 does not have rows 0290/0310 (replaced by Section 1 RE breakdown)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_re_memorandum(), framework="BASEL_3_1"
        )
        re = bundle.c07_00["secured_by_re_property"]
        row_refs = re["row_ref"].to_list()
        # B31 memorandum doesn't include 0290/0310 (removed in template defs)
        assert "0290" not in row_refs
        assert "0310" not in row_refs

    def test_defaulted_rw_matching_uses_rounding(self) -> None:
        """RW comparison uses 4-decimal rounding to handle float imprecision."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "drawn_amount": [1000.0],
                "undrawn_amount": [0.0],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
                # Slightly imprecise 100% due to float arithmetic
                "risk_weight": [0.99999999],
                "default_status": [True],
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "counterparty_reference": ["CP_A"],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0300")
        # Should match despite float imprecision
        assert row["0200"][0] == pytest.approx(1000.0)

    def test_memorandum_columns_complete(self) -> None:
        """Memorandum rows have the full set of COREP columns."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0300 = corp.filter(pl.col("row_ref") == "0300")
        # Should have all CRR C07 columns
        crr_col_refs = [c.ref for c in CRR_C07_COLUMNS]
        for ref in crr_col_refs:
            assert ref in row_0300.columns


class TestC0700SupportingFactorRows:
    """Tests for CRR C 07.00 Section 1 supporting factor rows.

    Row 0030: of which: Exposures subject to SME-supporting factor
    Row 0035: of which: Exposures subject to infrastructure supporting factor

    Why: These rows report the regulatory benefit from supporting factors.
    Previously they were always null despite the pipeline computing
    supporting factors. Now populated using is_sme/is_infrastructure
    flags and supporting_factor_applied status.

    References:
        CRR Art. 501: SME supporting factor
        CRR Art. 501a: Infrastructure supporting factor
    """

    def test_row_0030_sme_exposures(self) -> None:
        """Row 0030 filters SME exposures with supporting factor applied."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        # corporate_sme merges into corporate for C 07.00
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        assert len(row) == 1
        # SA_SME_1 (EAD 1000) + SA_SME_2 (EAD 2000) = 3000
        assert row["0200"][0] == pytest.approx(3000.0)
        assert row["0220"][0] == pytest.approx(2100.0)  # 700 + 1400

    def test_row_0035_infrastructure_exposures(self) -> None:
        """Row 0035 filters infrastructure exposures with factor applied."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0035")
        assert len(row) == 1
        # SA_INFRA_1: EAD 5000, RWA 3750
        assert row["0200"][0] == pytest.approx(5000.0)
        assert row["0220"][0] == pytest.approx(3750.0)

    def test_row_0030_excludes_non_sme(self) -> None:
        """Row 0030 excludes non-SME exposures even with factor applied."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0030 = corp.filter(pl.col("row_ref") == "0030")
        # Only SME exposures (3000), not infra (5000) or plain (3200)
        assert row_0030["0200"][0] == pytest.approx(3000.0)

    def test_row_0035_excludes_non_infrastructure(self) -> None:
        """Row 0035 excludes non-infrastructure exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0035 = corp.filter(pl.col("row_ref") == "0035")
        # Only infra (5000), not SME (3000) or plain (3200)
        assert row_0035["0200"][0] == pytest.approx(5000.0)

    def test_row_0030_null_when_no_sme(self) -> None:
        """Row 0030 is null when no SME exposures exist."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        assert row["0200"][0] is None

    def test_b31_no_supporting_factor_rows(self) -> None:
        """B31 has no supporting factor rows (removed under Basel 3.1)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_supporting_factors(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        row_refs = corp["row_ref"].to_list()
        # B31 removes rows 0030 and 0035
        assert "0030" not in row_refs
        assert "0035" not in row_refs

    def test_supporting_factor_without_flag_column(self) -> None:
        """Rows 0030/0035 are null when is_sme/is_infrastructure absent."""
        gen = LedgerShimCorepGenerator()
        # _sa_results() has no is_sme or is_infrastructure columns
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0030 = corp.filter(pl.col("row_ref") == "0030")
        row_0035 = corp.filter(pl.col("row_ref") == "0035")
        assert row_0030["0200"][0] is None
        assert row_0035["0200"][0] is None

    def test_original_exposure_correct_for_sme(self) -> None:
        """Row 0030 original exposure (col 0010) = drawn + undrawn for SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        # SME_1: 1000+0=1000, SME_2: 2000+0=2000, total 3000
        assert row["0010"][0] == pytest.approx(3000.0)


class TestC0700SupportingFactorRWEA:
    """Tests for CRR C 07.00 RWEA columns 0215-0217 with pipeline columns.

    The pipeline produces rwa_pre_factor and supporting_factor_applied,
    while the COREP spec expects per-type breakdown (SME vs infrastructure).
    The generator now uses fallback logic: tries legacy column names first,
    then pipeline columns (is_sme/is_infrastructure + supporting_factor_applied).

    Why: These columns quantify the SME/infrastructure capital relief. Without
    the fallback, they were always null despite the pipeline computing factors.

    References:
        CRR Art. 501: SME supporting factor
        CRR Art. 501a: Infrastructure supporting factor
    """

    def test_col_0215_pre_factor_rwa(self) -> None:
        """Col 0215 uses rwa_pre_factor when rwa_before_sme_factor absent."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Total rwa_pre_factor: 1000+2000+5000+3200 = 11200
        assert total["0215"][0] == pytest.approx(11200.0)

    def test_col_0216_sme_adjustment(self) -> None:
        """Col 0216 computes SME factor adjustment, emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # SME adjustment = pre - post for SME rows, reported as a negative deduction
        # SME_1: 1000 - 700 = 300, SME_2: 2000 - 1400 = 600 -> -(300 + 600)
        assert total["0216"][0] == pytest.approx(-900.0)

    def test_col_0217_infra_adjustment(self) -> None:
        """Col 0217 infra factor adjustment, emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Infrastructure adjustment = pre - post for infra rows, reported negative
        # INFRA_1: 5000 - 3750 = 1250 -> -1250
        assert total["0217"][0] == pytest.approx(-1250.0)

    def test_col_0220_post_factor_rwa(self) -> None:
        """Col 0220 (post-factor RWEA) is the sum of rwa_final."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Total rwa_final: 700+1400+3750+3200 = 9050
        assert total["0220"][0] == pytest.approx(9050.0)

    def test_pre_minus_adjustments_equals_post(self) -> None:
        """RWEA integrity: 0215 + 0216 + 0217 ≈ 0220 under the "(-)" convention."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        pre = total["0215"][0]
        sme_adj = total["0216"][0]  # negative per Annex II §1.3
        infra_adj = total["0217"][0]  # negative per Annex II §1.3
        post = total["0220"][0]
        # 11200 + (-900) + (-1250) = 9050
        assert pre + sme_adj + infra_adj == pytest.approx(post)

    def test_col_0216_null_without_pipeline_columns(self) -> None:
        """Col 0216 is null when neither legacy nor pipeline columns exist."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0216"][0] is None

    def test_b31_no_supporting_factor_columns(self) -> None:
        """B31 does not have cols 0215-0217 (supporting factors removed)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_supporting_factors(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        assert "0215" not in corp.columns
        assert "0216" not in corp.columns
        assert "0217" not in corp.columns


class TestOF0700RESubRowFallback:
    """Tests for OF 07.00 RE sub-row filtering with has_income_cover fallback.

    Why: The generator previously required materially_dependent_on_property
    to populate RE sub-rows (0331-0354). The SA calculator produces
    has_income_cover instead. The fallback allows these rows to be populated
    from existing pipeline data.
    """

    def test_re_rows_with_has_income_cover(self) -> None:
        """RE sub-rows populate using has_income_cover as fallback."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1", "RE_2", "RE_3"],
                "approach_applied": ["standardised"] * 3,
                "exposure_class": ["secured_by_re_residential"] * 3,
                "drawn_amount": [100.0, 200.0, 300.0],
                "undrawn_amount": [0.0, 0.0, 0.0],
                "ead_final": [100.0, 200.0, 300.0],
                "rwa_final": [20.0, 70.0, 105.0],
                "risk_weight": [0.20, 0.35, 0.35],
                "property_type": ["residential", "residential", "residential"],
                "has_income_cover": [False, True, False],
                "scra_provision_amount": [0.0] * 3,
                "gcra_provision_amount": [0.0] * 3,
                "counterparty_reference": ["CP1", "CP2", "CP3"],
                "sa_cqs": [None] * 3,
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        # 0331: residential, NOT dependent → RE_1 + RE_3 (EAD 100+300=400)
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        assert len(r0331) == 1
        ead_col = "0200" if "0200" in r0331.columns else "0010"
        val = float(r0331[ead_col][0] or 0)
        assert val == pytest.approx(400.0)
        # 0332: residential, dependent → RE_2 (EAD 200)
        r0332 = re_res.filter(pl.col("row_ref") == "0332")
        val2 = float(r0332[ead_col][0] or 0)
        assert val2 == pytest.approx(200.0)

    def test_re_rows_with_is_income_producing(self) -> None:
        """RE sub-rows populate using is_income_producing as second fallback."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1", "RE_2"],
                "approach_applied": ["standardised"] * 2,
                "exposure_class": ["secured_by_re_residential"] * 2,
                "drawn_amount": [100.0, 200.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [100.0, 200.0],
                "rwa_final": [20.0, 70.0],
                "risk_weight": [0.20, 0.35],
                "property_type": ["residential", "residential"],
                "is_income_producing": [False, True],
                "scra_provision_amount": [0.0] * 2,
                "gcra_provision_amount": [0.0] * 2,
                "counterparty_reference": ["CP1", "CP2"],
                "sa_cqs": [None] * 2,
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        ead_col = "0200" if "0200" in r0331.columns else "0010"
        assert float(r0331[ead_col][0] or 0) == pytest.approx(100.0)

    def test_re_rows_empty_without_any_dependency_column(self) -> None:
        """Without any dependency column, sub-rows remain null."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["secured_by_re_residential"],
                "drawn_amount": [100.0],
                "undrawn_amount": [0.0],
                "ead_final": [100.0],
                "rwa_final": [20.0],
                "risk_weight": [0.20],
                "property_type": ["residential"],
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "counterparty_reference": ["CP1"],
                "sa_cqs": [None],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        ead_col = "0200" if "0200" in r0331.columns else "0010"
        # Should be null (no data to split on)
        assert r0331[ead_col][0] is None

    def test_materially_dependent_preferred_over_has_income_cover(self) -> None:
        """When both columns exist, materially_dependent_on_property wins."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["secured_by_re_residential"],
                "drawn_amount": [100.0],
                "undrawn_amount": [0.0],
                "ead_final": [100.0],
                "rwa_final": [20.0],
                "risk_weight": [0.20],
                "property_type": ["residential"],
                "materially_dependent_on_property": [True],
                "has_income_cover": [False],  # Different value — should be ignored
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "counterparty_reference": ["CP1"],
                "sa_cqs": [None],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        ead_col = "0200" if "0200" in re_res.columns else "0010"
        # RE_1 has materially_dependent=True, so should appear in row 0332
        r0332 = re_res.filter(pl.col("row_ref") == "0332")
        assert float(r0332[ead_col][0] or 0) == pytest.approx(100.0)
        # And NOT in row 0331
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        assert r0331[ead_col][0] is None
