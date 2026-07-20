"""COREP C 08.04 / OF 08.04 RWEA-flow tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator


def _irb_flow_results() -> pl.LazyFrame:
    """Synthetic IRB results for C 08.04 flow statement tests.

    3 corporate exposures + 1 institution + 1 retail mortgage.
    Corporate total RWEA: 2750 + 1800 + 780 = 5330.
    Institution RWEA: 600. Retail mortgage RWEA: 1200.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
            ],
            "ead_final": [5500.0, 3000.0, 1200.0, 2000.0, 4000.0],
            "rwa_final": [2750.0, 1800.0, 780.0, 600.0, 1200.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
        }
    )


def _irb_flow_with_slotting() -> pl.LazyFrame:
    """IRB results including slotting exposures for exclusion testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3"],
            "approach_applied": ["foundation_irb", "slotting", "advanced_irb"],
            "exposure_class": ["corporate", "specialised_lending", "corporate"],
            "ead_final": [5000.0, 3000.0, 2000.0],
            "rwa_final": [3500.0, 2100.0, 1400.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
        }
    )


def _irb_flow_prior() -> pl.LazyFrame:
    """Prior-period snapshot, same classes as ``_irb_flow_results`` (lower RWEA).

    Corporate prior RWEA: 2500 + 1500 = 4000. Corporate-SME: 700.
    Institution: 500. Retail mortgage: 1000. A slotting row is included to
    prove it is excluded from the opening exactly as it is from the closing.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["P1", "P2", "P3", "P4", "P5", "P6"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
                "corporate",
            ],
            "ead_final": [5000.0, 2800.0, 1100.0, 1800.0, 3500.0, 2000.0],
            "rwa_final": [2500.0, 1500.0, 700.0, 500.0, 1000.0, 9999.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E", "CP_F"],
        }
    )


def _irb_flow_prior_corporate_only() -> pl.LazyFrame:
    """Prior period carrying only a corporate class (institution etc. absent).

    Used to prove a class present ONLY in the current period gets a null
    opening while its whole closing lands in the Other residual (opening
    coerces to zero WITH a prior period — the CR8 convention)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["P1", "P2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "ead_final": [5000.0, 2800.0],
            "rwa_final": [2500.0, 1500.0],
            "counterparty_reference": ["CP_A", "CP_B"],
        }
    )


def _flow_value(df: pl.DataFrame, row_ref: str) -> float | None:
    """Read the single col-0010 value of a C 08.04 row."""
    return df.filter(pl.col("row_ref") == row_ref)["0010"][0]


class TestC0804TemplateDefinitions:
    """Test C 08.04 / OF 08.04 template structure definitions."""

    def test_crr_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_04_COLUMNS

        assert len(CRR_C08_04_COLUMNS) == 1

    def test_b31_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_04_COLUMNS

        assert len(B31_C08_04_COLUMNS) == 1

    def test_crr_column_ref(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_04_COLUMNS

        assert CRR_C08_04_COLUMNS[0].ref == "0010"

    def test_crr_column_includes_supporting_factors(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_04_COLUMNS

        assert "supporting factors" in CRR_C08_04_COLUMNS[0].name.lower()

    def test_b31_column_excludes_supporting_factors(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_04_COLUMNS

        assert "supporting factors" not in B31_C08_04_COLUMNS[0].name.lower()

    def test_column_refs_list(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_COLUMN_REFS

        assert C08_04_COLUMN_REFS == ["0010"]

    def test_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        assert len(C08_04_ROWS) == 9

    def test_rows_refs_sequential(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        expected_refs = [f"00{i}0" for i in range(1, 10)]
        assert [r.ref for r in C08_04_ROWS] == expected_refs

    def test_first_row_is_opening(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        assert "previous" in C08_04_ROWS[0].name.lower()

    def test_last_row_is_closing(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        assert "end of the reporting period" in C08_04_ROWS[8].name.lower()

    def test_movement_driver_rows(self) -> None:
        """7 movement driver rows between opening and closing."""
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        drivers = C08_04_ROWS[1:8]
        assert len(drivers) == 7
        expected_names = [
            "Asset size",
            "Asset quality",
            "Model updates",
            "Methodology and policy",
            "Acquisitions and disposals",
            "Foreign exchange movements",
            "Other",
        ]
        for row, expected in zip(drivers, expected_names, strict=True):
            assert expected.lower() in row.name.lower()

    def test_get_columns_crr(self) -> None:
        from rwa_calc.reporting.corep.templates import (
            CRR_C08_04_COLUMNS,
            get_c08_04_columns,
        )

        assert get_c08_04_columns("CRR") is CRR_C08_04_COLUMNS

    def test_get_columns_b31(self) -> None:
        from rwa_calc.reporting.corep.templates import (
            B31_C08_04_COLUMNS,
            get_c08_04_columns,
        )

        assert get_c08_04_columns("BASEL_3_1") is B31_C08_04_COLUMNS


class TestC0804Generation:
    """Test C 08.04 generation — per-class DataFrames with correct structure."""

    def test_generates_per_class(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        assert isinstance(bundle.c08_04, dict)
        assert len(bundle.c08_04) > 0

    def test_multiple_classes(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        # corporate, corporate_sme, institution, retail_mortgage
        assert len(bundle.c08_04) == 4

    def test_each_class_has_9_rows(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        for ec, df in bundle.c08_04.items():
            assert len(df) == 9, f"{ec} has {len(df)} rows instead of 9"

    def test_each_class_has_correct_columns(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        for _ec, df in bundle.c08_04.items():
            assert "row_ref" in df.columns
            assert "row_name" in df.columns
            assert "0010" in df.columns

    def test_empty_irb_returns_empty_dict(self) -> None:
        """No IRB data produces empty dict."""
        gen = LedgerShimCorepGenerator()
        sa_only = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
            }
        )
        bundle = gen.generate_from_lazyframe(sa_only)
        assert bundle.c08_04 == {}


class TestC0804ClosingRWEA:
    """Test row 0090 (closing RWEA) population from pipeline data."""

    def test_closing_rwea_corporate(self) -> None:
        """Corporate closing RWEA = sum of corporate+corporate_sme RWEA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        # E1=2750 + E2=1800 corporate
        assert closing["0010"][0] == pytest.approx(4550.0, rel=1e-4)

    def test_closing_rwea_institution(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        inst = bundle.c08_04["institution"]
        closing = inst.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(600.0, rel=1e-4)

    def test_closing_rwea_retail(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        retail = bundle.c08_04["retail_mortgage"]
        closing = retail.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(1200.0, rel=1e-4)

    def test_closing_rwea_sme(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        sme = bundle.c08_04["corporate_sme"]
        closing = sme.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(780.0, rel=1e-4)


class TestC0804NullDriverRows:
    """Test that opening and driver rows are null (require prior-period data)."""

    def test_opening_rwea_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        opening = corp.filter(pl.col("row_ref") == "0010")
        assert opening["0010"][0] is None

    def test_asset_size_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0020")
        assert row["0010"][0] is None

    def test_asset_quality_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        assert row["0010"][0] is None

    def test_model_updates_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0040")
        assert row["0010"][0] is None

    def test_methodology_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0050")
        assert row["0010"][0] is None

    def test_acquisitions_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        assert row["0010"][0] is None

    def test_fx_movements_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0070")
        assert row["0010"][0] is None

    def test_other_is_null(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0010"][0] is None

    def test_all_drivers_null(self) -> None:
        """All 7 driver rows + opening are null."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        for ref in ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]:
            row = corp.filter(pl.col("row_ref") == ref)
            assert row["0010"][0] is None, f"Row {ref} should be null"


class TestC0804B31Features:
    """Test Basel 3.1 specific features for C 08.04."""

    def test_b31_generates_same_row_count(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results(), framework="BASEL_3_1")
        for ec, df in bundle.c08_04.items():
            assert len(df) == 9, f"B31 {ec} has {len(df)} rows"

    def test_b31_closing_rwea_matches_crr(self) -> None:
        """Closing RWEA values are framework-independent."""
        gen = LedgerShimCorepGenerator()
        crr = gen.generate_from_lazyframe(_irb_flow_results(), framework="CRR")
        b31 = gen.generate_from_lazyframe(_irb_flow_results(), framework="BASEL_3_1")
        for ec in crr.c08_04:
            crr_closing = crr.c08_04[ec].filter(pl.col("row_ref") == "0090")["0010"][0]
            b31_closing = b31.c08_04[ec].filter(pl.col("row_ref") == "0090")["0010"][0]
            assert crr_closing == pytest.approx(b31_closing, rel=1e-4)

    def test_b31_framework_stored(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results(), framework="BASEL_3_1")
        assert bundle.framework == "BASEL_3_1"


class TestC0804EdgeCases:
    """Test edge cases for C 08.04 generation."""

    def test_excludes_slotting(self) -> None:
        """Slotting exposures excluded from C 08.04."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_with_slotting())
        # Only corporate class, slotting excluded
        assert "corporate" in bundle.c08_04
        assert "specialised_lending" not in bundle.c08_04

    def test_slotting_rwea_not_in_closing(self) -> None:
        """Closing RWEA excludes slotting RWEA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_with_slotting())
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        # E1=3500 + E3=1400 corporate only
        assert closing["0010"][0] == pytest.approx(4900.0, rel=1e-4)

    def test_missing_exposure_class_returns_empty(self) -> None:
        gen = LedgerShimCorepGenerator()
        no_ec = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(no_ec)
        assert bundle.c08_04 == {}

    def test_missing_rwa_column(self) -> None:
        """Missing rwa_final still generates template with null closing."""
        gen = LedgerShimCorepGenerator()
        no_rwa = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
            }
        )
        bundle = gen.generate_from_lazyframe(no_rwa)
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] is None

    def test_zero_rwa(self) -> None:
        """Zero RWEA is reported as 0.0, not null."""
        gen = LedgerShimCorepGenerator()
        zero_rwa = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [0.0],
            }
        )
        bundle = gen.generate_from_lazyframe(zero_rwa)
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(0.0)

    def test_row_refs_are_correct(self) -> None:
        """All 9 row refs are the expected 4-digit codes."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        expected = ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080", "0090"]
        assert corp["row_ref"].to_list() == expected

    def test_bundle_has_c08_04_field(self) -> None:
        """COREPTemplateBundle has c08_04 field."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        assert hasattr(bundle, "c08_04")
        assert isinstance(bundle.c08_04, dict)


class TestC0804PriorPeriod:
    """C 08.04 with a prior period: opening, signed residual, and footing."""

    def test_opening_equals_prior_closing_corporate(self) -> None:
        """Row 0010 (opening) == prior period's corporate closing = 2500 + 1500."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        corp = bundle.c08_04["corporate"]
        assert _flow_value(corp, "0010") == pytest.approx(4000.0, rel=1e-4)

    def test_opening_equals_prior_closing_institution(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        inst = bundle.c08_04["institution"]
        assert _flow_value(inst, "0010") == pytest.approx(500.0, rel=1e-4)

    def test_closing_unchanged_with_prior(self) -> None:
        """Row 0090 (closing) is the current period's sum regardless of prior."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        corp = bundle.c08_04["corporate"]
        assert _flow_value(corp, "0090") == pytest.approx(4550.0, rel=1e-4)

    def test_other_residual_is_signed_delta(self) -> None:
        """Row 0080 (Other) == closing − opening = 4550 − 4000 = +550."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        corp = bundle.c08_04["corporate"]
        assert _flow_value(corp, "0080") == pytest.approx(550.0, rel=1e-4)

    def test_statement_foots_for_every_class(self) -> None:
        """closing == opening + Σ(flow rows 0020-0080), nulls treated as zero."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        for ec, df in bundle.c08_04.items():
            opening = _flow_value(df, "0010") or 0.0
            flows = sum(
                _flow_value(df, ref) or 0.0
                for ref in ("0020", "0030", "0040", "0050", "0060", "0070", "0080")
            )
            closing = _flow_value(df, "0090") or 0.0
            assert opening + flows == pytest.approx(closing, rel=1e-4), f"{ec} does not foot"

    def test_driver_rows_stay_null_with_prior(self) -> None:
        """The 6 attributable driver rows (0020-0070) remain null even with a prior."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        corp = bundle.c08_04["corporate"]
        for ref in ("0020", "0030", "0040", "0050", "0060", "0070"):
            assert _flow_value(corp, ref) is None, f"Row {ref} should stay null"

    def test_slotting_excluded_from_opening(self) -> None:
        """The prior slotting row (rwa 9999) must not inflate the corporate opening."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior()
        )
        corp = bundle.c08_04["corporate"]
        # Opening excludes slotting: 2500 + 1500 only, not + 9999.
        assert _flow_value(corp, "0010") == pytest.approx(4000.0, rel=1e-4)

    def test_current_only_class_gets_null_opening(self) -> None:
        """A class absent from the prior period gets a null opening and its whole
        closing as the Other residual (opening coerces to zero WITH a prior)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(), previous_period_results=_irb_flow_prior_corporate_only()
        )
        inst = bundle.c08_04["institution"]
        assert _flow_value(inst, "0010") is None
        assert _flow_value(inst, "0080") == pytest.approx(600.0, rel=1e-4)
        # Still foots: 0 opening + 600 Other == 600 closing.
        assert _flow_value(inst, "0090") == pytest.approx(600.0, rel=1e-4)

    def test_decrease_control_negative_residual(self) -> None:
        """Snapshots swapped (RWEA falls): Other is negative = 4000 − 4550 = −550."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_prior(), previous_period_results=_irb_flow_results()
        )
        corp = bundle.c08_04["corporate"]
        assert _flow_value(corp, "0080") == pytest.approx(-550.0, rel=1e-4)

    def test_b31_prior_period_foots(self) -> None:
        """The opening/residual wiring is framework-independent (OF 08.04)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_flow_results(),
            framework="BASEL_3_1",
            previous_period_results=_irb_flow_prior(),
        )
        corp = bundle.c08_04["corporate"]
        assert _flow_value(corp, "0010") == pytest.approx(4000.0, rel=1e-4)
        assert _flow_value(corp, "0080") == pytest.approx(550.0, rel=1e-4)


class TestC0804NoPriorUnchanged:
    """Number-neutrality: passing no prior (or None) is byte-identical to today."""

    def test_none_prior_matches_default(self) -> None:
        """Explicit previous_period_results=None equals the no-arg output frame."""
        gen = LedgerShimCorepGenerator()
        default = gen.generate_from_lazyframe(_irb_flow_results())
        gen2 = LedgerShimCorepGenerator()
        with_none = gen2.generate_from_lazyframe(_irb_flow_results(), previous_period_results=None)
        for ec, df in default.c08_04.items():
            assert df.equals(with_none.c08_04[ec]), f"{ec} differs when prior=None"

    def test_no_prior_opening_and_other_null(self) -> None:
        """Without a prior period, opening (0010) and Other (0080) stay null."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        assert _flow_value(corp, "0010") is None
        assert _flow_value(corp, "0080") is None
