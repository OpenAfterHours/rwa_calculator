"""
Unit tests for COREP reporting basis conditionality (P1.38(c)).

Tests cover:
- COREPGenerator accepts output_floor_config and threads it to templates
- OF 02.00 floor indicator rows (0034-0036) gated on is_floor_applicable()
- OF 02.01 output floor comparison skipped for exempt entities
- C 08.07 / OF 08.07 materiality columns (0160-0180) consolidated-only
- COREPTemplateBundle surfaces reporting_basis and institution_type
- ResultExporter.export_to_corep accepts output_floor_config
- Backward compatibility: None config preserves existing behaviour

Why these tests matter:
Art. 92 para 2A restricts the output floor to 3 entity-type/basis combinations.
Without reporting basis conditionality, COREP templates would show floor
indicators for exempt entities (international subsidiaries, ring-fenced bodies
on individual basis) — misleading regulators and auditors.

References:
- PRA PS1/26 Art. 92 para 2A(a)-(d)
- PRA PS1/26 Art. 150(1A): materiality columns consolidated-only
- Reporting (CRR) Part Rule 2.2A
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.config import OutputFloorConfig
from rwa_calc.domain.enums import InstitutionType, ReportingBasis
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle


# =============================================================================
# Fixtures
# =============================================================================


def _b31_irb_results() -> pl.LazyFrame:
    """B31 IRB results with floor columns — floor binds (50k < 72.5% × 100k)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["foundation_irb"],
            "ead_final": [100_000.0],
            "risk_weight": [0.5],
            "rwa_final": [60_000.0],
            "rwa_pre_floor": [50_000.0],
            "sa_rwa": [100_000.0],
        }
    )


def _b31_sa_results() -> pl.LazyFrame:
    """B31 SA-only results (no floor columns)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["standardised"],
            "ead_final": [100_000.0],
            "risk_weight": [1.0],
            "rwa_final": [100_000.0],
        }
    )


def _crr_results() -> pl.LazyFrame:
    """CRR results (no output floor)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["standardised"],
            "ead_final": [100_000.0],
            "risk_weight": [1.0],
            "rwa_final": [100_000.0],
        }
    )


def _exempt_floor_config() -> OutputFloorConfig:
    """International subsidiary on individual basis — exempt from floor."""
    return OutputFloorConfig.basel_3_1(
        institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )


def _applicable_floor_config() -> OutputFloorConfig:
    """Standalone UK on individual basis — floor applies."""
    return OutputFloorConfig.basel_3_1(
        institution_type=InstitutionType.STANDALONE_UK,
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )


def _rfb_sub_con_config() -> OutputFloorConfig:
    """Ring-fenced body on sub-consolidated basis — floor applies."""
    return OutputFloorConfig.basel_3_1(
        institution_type=InstitutionType.RING_FENCED_BODY,
        reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
    )


def _consolidated_config() -> OutputFloorConfig:
    """CRR consolidation entity on consolidated basis — floor applies."""
    return OutputFloorConfig.basel_3_1(
        institution_type=InstitutionType.CRR_CONSOLIDATION_ENTITY,
        reporting_basis=ReportingBasis.CONSOLIDATED,
    )


# =============================================================================
# COREPTemplateBundle metadata
# =============================================================================


class TestCOREPTemplateBundleMetadata:
    """Test that COREPTemplateBundle surfaces reporting_basis and institution_type."""

    def test_bundle_has_reporting_basis_field(self) -> None:
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.reporting_basis is None

    def test_bundle_has_institution_type_field(self) -> None:
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.institution_type is None

    def test_bundle_reporting_basis_from_config(self) -> None:
        gen = COREPGenerator()
        config = _applicable_floor_config()
        bundle = gen.generate_from_lazyframe(
            _b31_sa_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        assert bundle.reporting_basis == "individual"

    def test_bundle_institution_type_from_config(self) -> None:
        gen = COREPGenerator()
        config = _applicable_floor_config()
        bundle = gen.generate_from_lazyframe(
            _b31_sa_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        assert bundle.institution_type == "standalone_uk"

    def test_bundle_rfb_sub_consolidated(self) -> None:
        gen = COREPGenerator()
        config = _rfb_sub_con_config()
        bundle = gen.generate_from_lazyframe(
            _b31_sa_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        assert bundle.reporting_basis == "sub_consolidated"
        assert bundle.institution_type == "ring_fenced_body"

    def test_bundle_none_config_preserves_none_metadata(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_sa_results(), framework="BASEL_3_1",
        )
        assert bundle.reporting_basis is None
        assert bundle.institution_type is None

    def test_bundle_crr_no_metadata(self) -> None:
        gen = COREPGenerator()
        config = _applicable_floor_config()
        bundle = gen.generate_from_lazyframe(
            _crr_results(),
            framework="CRR",
            output_floor_config=config,
        )
        # Config is passed but CRR framework still records the metadata
        assert bundle.reporting_basis == "individual"


# =============================================================================
# OF 02.01 — Output Floor Comparison gating
# =============================================================================


class TestOF0201FloorApplicability:
    """Test that OF 02.01 is gated on entity-type floor applicability."""

    def test_of_02_01_none_for_crr(self) -> None:
        """CRR: OF 02.01 is always None."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_crr_results(), framework="CRR")
        assert bundle.of_02_01 is None

    def test_of_02_01_present_for_applicable_entity(self) -> None:
        """Applicable B31 entity with floor columns → OF 02.01 generated."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_applicable_floor_config(),
        )
        assert bundle.of_02_01 is not None

    def test_of_02_01_none_for_exempt_entity(self) -> None:
        """Exempt entity (international subsidiary) → OF 02.01 skipped."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_exempt_floor_config(),
        )
        assert bundle.of_02_01 is None

    def test_of_02_01_present_when_no_config(self) -> None:
        """No config → backward compatible, OF 02.01 generated."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
        )
        assert bundle.of_02_01 is not None

    def test_of_02_01_rfb_sub_consolidated_applicable(self) -> None:
        """RFB on sub-consolidated basis → floor applicable → OF 02.01 generated."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_rfb_sub_con_config(),
        )
        assert bundle.of_02_01 is not None

    def test_of_02_01_rfb_individual_exempt(self) -> None:
        """RFB on individual basis → floor not applicable → OF 02.01 skipped."""
        gen = COREPGenerator()
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        assert bundle.of_02_01 is None


# =============================================================================
# OF 02.00 — Floor Indicator Rows
# =============================================================================


def _get_c02_row(bundle: COREPTemplateBundle, row_ref: str) -> dict[str, object] | None:
    """Extract a row from the C 02.00 / OF 02.00 template by row_ref."""
    if bundle.c_02_00 is None:
        return None
    df = bundle.c_02_00
    filtered = df.filter(pl.col("row_ref") == row_ref)
    if len(filtered) == 0:
        return None
    return filtered.row(0, named=True)


class TestOF0200FloorIndicatorRows:
    """Test that OF 02.00 rows 0034-0036 are gated on is_floor_applicable()."""

    def test_exempt_entity_floor_not_activated(self) -> None:
        """Exempt entity: row 0034 (floor activated) = 0.0."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_exempt_floor_config(),
        )
        row = _get_c02_row(bundle, "0034")
        assert row is not None
        assert row["0010"] == 0.0

    def test_exempt_entity_multiplier_zero(self) -> None:
        """Exempt entity: row 0035 (multiplier) = 0.0."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_exempt_floor_config(),
        )
        row = _get_c02_row(bundle, "0035")
        assert row is not None
        assert row["0010"] == 0.0

    def test_exempt_entity_of_adj_zero(self) -> None:
        """Exempt entity: row 0036 (OF-ADJ) = 0.0."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_exempt_floor_config(),
        )
        row = _get_c02_row(bundle, "0036")
        assert row is not None
        assert row["0010"] == 0.0

    def test_applicable_entity_floor_activated(self) -> None:
        """Applicable entity with binding floor: row 0034 = 1.0."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_applicable_floor_config(),
        )
        row = _get_c02_row(bundle, "0034")
        assert row is not None
        # rwa_final (60k) > rwa_pre_floor (50k) → floor activated
        assert row["0010"] == 1.0

    def test_no_config_backward_compat(self) -> None:
        """No config → floor is assumed applicable (backward compat)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
        )
        row = _get_c02_row(bundle, "0034")
        assert row is not None
        # rwa_final (60k) > rwa_pre_floor (50k) → floor activated
        assert row["0010"] == 1.0

    def test_crr_no_floor_indicator_rows(self) -> None:
        """CRR: rows 0034-0036 not present in C 02.00."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _crr_results(), framework="CRR",
        )
        for ref in ("0034", "0035", "0036"):
            row = _get_c02_row(bundle, ref)
            assert row is None, f"Row {ref} should not exist under CRR"

    def test_exempt_all_three_indicator_rows_zero(self) -> None:
        """Exempt entity: all three indicator rows consistently zero."""
        gen = COREPGenerator()
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.NON_RING_FENCED,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        for ref in ("0034", "0035", "0036"):
            row = _get_c02_row(bundle, ref)
            assert row is not None
            assert row["0010"] == 0.0, f"Row {ref} should be 0.0 for exempt entity"


# =============================================================================
# C 08.07 / OF 08.07 — Materiality Columns
# =============================================================================


class TestC0807MaterialityColumns:
    """Test that C 08.07 materiality columns (0160-0180) reflect reporting basis."""

    def test_materiality_null_without_config(self) -> None:
        """No config: materiality columns are None (backward compat)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
        )
        assert bundle.c08_07 is not None
        total = bundle.c08_07.filter(pl.col("row_name") == "Total")
        assert len(total) == 1
        row = total.row(0, named=True)
        for ref in ("0160", "0170", "0180"):
            assert row[ref] is None, f"Col {ref} should be None without config"

    def test_materiality_null_for_non_consolidated(self) -> None:
        """Individual basis: materiality columns are None."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_applicable_floor_config(),
        )
        assert bundle.c08_07 is not None
        total = bundle.c08_07.filter(pl.col("row_name") == "Total")
        row = total.row(0, named=True)
        for ref in ("0160", "0170", "0180"):
            assert row[ref] is None

    def test_materiality_null_for_consolidated(self) -> None:
        """Consolidated basis: materiality columns still None (data not available).

        When the institutional config provides materiality data, these would
        be populated. For now, they are in scope but not computable.
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=_consolidated_config(),
        )
        assert bundle.c08_07 is not None
        total = bundle.c08_07.filter(pl.col("row_name") == "Total")
        row = total.row(0, named=True)
        # Even for consolidated basis, values are None until institutional
        # materiality data is provided — but the is_consolidated flag is
        # threaded through for future population.
        for ref in ("0160", "0170", "0180"):
            assert row[ref] is None

    def test_crr_no_materiality_columns(self) -> None:
        """CRR: C 08.07 has 5 columns, no materiality."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),  # using IRB data for CRR too
            framework="CRR",
        )
        if bundle.c08_07 is not None:
            cols = bundle.c08_07.columns
            for ref in ("0160", "0170", "0180"):
                assert ref not in cols


# =============================================================================
# Backward Compatibility
# =============================================================================


class TestBackwardCompatibility:
    """Test that None output_floor_config preserves existing behaviour."""

    def test_generate_from_lazyframe_no_config(self) -> None:
        """No config: bundle generated without errors."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(), framework="BASEL_3_1",
        )
        assert bundle.framework == "BASEL_3_1"
        assert bundle.reporting_basis is None
        assert bundle.institution_type is None

    def test_of_02_01_present_without_config(self) -> None:
        """No config: OF 02.01 still generated (backward compat)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(), framework="BASEL_3_1",
        )
        assert bundle.of_02_01 is not None

    def test_c_02_00_floor_rows_present_without_config(self) -> None:
        """No config: floor indicator rows still present."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(), framework="BASEL_3_1",
        )
        for ref in ("0034", "0035", "0036"):
            row = _get_c02_row(bundle, ref)
            assert row is not None


# =============================================================================
# Exhaustive Entity Type Combinations
# =============================================================================


class TestEntityTypeCombinations:
    """Test floor indicator behaviour across all entity-type/basis combinations."""

    @pytest.mark.parametrize(
        "inst_type,basis,expect_applicable",
        [
            (InstitutionType.STANDALONE_UK, ReportingBasis.INDIVIDUAL, True),
            (InstitutionType.RING_FENCED_BODY, ReportingBasis.SUB_CONSOLIDATED, True),
            (InstitutionType.CRR_CONSOLIDATION_ENTITY, ReportingBasis.CONSOLIDATED, True),
            (InstitutionType.INTERNATIONAL_SUBSIDIARY, ReportingBasis.INDIVIDUAL, False),
            (InstitutionType.NON_RING_FENCED, ReportingBasis.SUB_CONSOLIDATED, False),
            (InstitutionType.RING_FENCED_BODY, ReportingBasis.INDIVIDUAL, False),
            (InstitutionType.STANDALONE_UK, ReportingBasis.CONSOLIDATED, False),
        ],
    )
    def test_of_02_01_gating(
        self,
        inst_type: InstitutionType,
        basis: ReportingBasis,
        expect_applicable: bool,
    ) -> None:
        """OF 02.01 presence matches floor applicability."""
        gen = COREPGenerator()
        config = OutputFloorConfig.basel_3_1(
            institution_type=inst_type, reporting_basis=basis,
        )
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        if expect_applicable:
            assert bundle.of_02_01 is not None, (
                f"{inst_type.value}/{basis.value} should produce OF 02.01"
            )
        else:
            assert bundle.of_02_01 is None, (
                f"{inst_type.value}/{basis.value} should NOT produce OF 02.01"
            )

    @pytest.mark.parametrize(
        "inst_type,basis,expect_applicable",
        [
            (InstitutionType.STANDALONE_UK, ReportingBasis.INDIVIDUAL, True),
            (InstitutionType.INTERNATIONAL_SUBSIDIARY, ReportingBasis.INDIVIDUAL, False),
        ],
    )
    def test_floor_activated_row(
        self,
        inst_type: InstitutionType,
        basis: ReportingBasis,
        expect_applicable: bool,
    ) -> None:
        """Row 0034 reflects floor activation only for applicable entities."""
        gen = COREPGenerator()
        config = OutputFloorConfig.basel_3_1(
            institution_type=inst_type, reporting_basis=basis,
        )
        bundle = gen.generate_from_lazyframe(
            _b31_irb_results(),
            framework="BASEL_3_1",
            output_floor_config=config,
        )
        row = _get_c02_row(bundle, "0034")
        assert row is not None
        if expect_applicable:
            # Floor binds: rwa_final (60k) > rwa_pre_floor (50k)
            assert row["0010"] == 1.0
        else:
            assert row["0010"] == 0.0


# =============================================================================
# Protocol compliance
# =============================================================================


class TestExporterProtocolCompliance:
    """Test that the updated protocol and exporter accept output_floor_config."""

    def test_result_exporter_accepts_output_floor_config(self) -> None:
        """ResultExporter.export_to_corep has output_floor_config kwarg."""
        from rwa_calc.api.export import ResultExporter

        exporter = ResultExporter()
        # Just verify the method exists and accepts the kwarg
        import inspect

        sig = inspect.signature(exporter.export_to_corep)
        assert "output_floor_config" in sig.parameters

    def test_protocol_has_output_floor_config(self) -> None:
        """ResultExporterProtocol.export_to_corep has output_floor_config kwarg."""
        from rwa_calc.contracts.protocols import ResultExporterProtocol

        import inspect

        # Get the method from the protocol class itself
        sig = inspect.signature(ResultExporterProtocol.export_to_corep)
        assert "output_floor_config" in sig.parameters
