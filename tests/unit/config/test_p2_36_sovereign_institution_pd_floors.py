"""
Unit tests for P2.36 — sovereign/institution PD floors as first-class PDFloors fields.

Asserts that ``PDFloors`` exposes explicit ``sovereign`` and ``institution`` fields
(in addition to the existing corporate/retail fields), and that ``get_floor`` dispatches
to these fields rather than falling back to the corporate floor.

The load-bearing override regression tests (``test_*_override_drives_dispatch_not_fallback``)
run exposures through the full pipeline with an overridden floor value and verify that
the engine consumes the new field — proving dispatch goes through the new path,
not through the corporate fallback.

Pipeline position:
    PDFloors (config) -> engine/irb/formulas.py (_pd_floor_expression)
    -> IRBCalculator -> irb_results

Engine gap (P2.36):
    ``PDFloors`` dataclass has no ``sovereign`` or ``institution`` fields (both default to the
    corporate fallback in ``get_floor``). Adding them as explicit ``Decimal`` fields and updating
    ``_pd_floor_expression`` to dispatch to them is the minimal engine change required.

References:
    - PRA PS1/26 Art. 160(1): Basel 3.1 PD floor for sovereign and institution = 0.05%.
    - PRA PS1/26 Art. 147A(1)(a): sovereign restricted to SA under Basel 3.1.
    - PRA PS1/26 Art. 147A(1)(b): institution restricted to F-IRB under Basel 3.1.
    - PRA PS1/26 Art. 161(1)(aa): Basel 3.1 senior non-FSE F-IRB LGD = 40%.
    - CRR Art. 160(1): uniform 0.03% PD floor for all IRB classes.
    - tests/fixtures/p2_36/p2_36.py: fixture constants and parquet generators.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p2_36.p2_36 import (
    EXPECTED_RW_B31_FLOORED,
    EXPECTED_RW_B31_SOV_OVERRIDE,
    EXPECTED_RWA_B31_FLOORED,
    EXPECTED_RWA_B31_SOV_OVERRIDE,
    INSTITUTION_LOAN_REF,
    SOVEREIGN_LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PDFloors
from rwa_calc.domain.enums import ExposureClass, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook import RulepackV0

# =============================================================================
# Fixture directory
# =============================================================================

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_36"

# Reporting date for all tests — within Basel 3.1 era so transitional floor applies
_REPORTING_DATE = date(2027, 6, 30)

# Override floor values for the dispatch regression tests
_SOV_OVERRIDE_FLOOR = Decimal("0.001")  # 0.10% — lifts sovereign PD above default 0.05%
_INST_OVERRIDE_FLOOR = Decimal("0.001")  # 0.10% — lifts institution PD above default 0.05%


# =============================================================================
# Pipeline fixture helpers
# =============================================================================


def _build_p236_bundle() -> RawDataBundle:
    """
    Load P2.36 parquet fixtures and assemble a RawDataBundle.

    Contains two exposures:
      - EXP_P236_SOV: GBP 1,000,000 sovereign loan (input PD=0.0001)
      - EXP_P236_INST: GBP 1,000,000 institution loan (input PD=0.0003)

    Both input PDs are below the Basel 3.1 floor (0.0005) so the floor always
    binds when the engine uses the new sovereign/institution fields.
    """
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
    )


def _run_pipeline(bundle: RawDataBundle, config: CalculationConfig) -> object:
    """Run the pipeline and return the AggregatedResultBundle."""
    return PipelineOrchestrator().run_with_data(bundle, config)


def _pd_floor_override_rulepack(
    config: CalculationConfig, floor_field: str, value: Decimal
) -> RulepackV0:
    """Resolve the config's standard rulepack, override one ``pd_floors`` param, rewrap.

    Phase 5 reads PD floors from the resolved rulepack, so a single-floor override
    is expressed as a ``pd_floors`` pack override (hash recomputed) injected via
    ``run_with_data(rulepack=...)`` — the successor to mutating ``config.pd_floors``.
    """
    base = RulepackV0.from_config(config).pack
    pd_floors = base.formula("pd_floors")
    overridden = base.with_overrides(
        pd_floors=dataclasses.replace(pd_floors, params={**pd_floors.params, floor_field: value})
    )
    return RulepackV0.from_resolved(config, overridden)


def _get_irb_row(results: object, loan_ref: str) -> dict | None:
    """
    Return the IRB result row for *loan_ref*, or None if not on IRB branch.

    Looks for a direct exposure_reference match first. Returns None if the
    exposure landed on the SA branch (e.g., sovereign forced to SA under B31).
    """
    if results.irb_results is None:
        return None
    irb_df = results.irb_results.collect()
    rows = irb_df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    if len(rows) == 1:
        return rows[0]
    return None


# =============================================================================
# 1. Config field tests — fail with AttributeError on master
# =============================================================================


class TestPDFloorFieldExistence:
    """
    P2.36: PDFloors must expose explicit ``sovereign`` and ``institution`` fields.

    All four tests below will fail on master with:
        AttributeError: 'PDFloors' object has no attribute 'sovereign'
        AttributeError: 'PDFloors' object has no attribute 'institution'

    After the engine-implementer adds the fields to the ``PDFloors`` dataclass
    and updates the factory methods, these tests will pass.
    """

    def test_pd_floors_basel_3_1_exposes_sovereign_field(self) -> None:
        """
        P2.36-1a: PDFloors.basel_3_1() must have a ``sovereign`` field equal to Decimal('0.0005').

        PRA PS1/26 Art. 160(1): the Basel 3.1 PD floor for sovereign IRB exposures
        is 0.05% (same as corporate). Today ``PDFloors`` has no ``sovereign`` field;
        this test fails with ``AttributeError`` until the field is added.
        """
        # Arrange
        floors = PDFloors.basel_3_1()

        # Act / Assert
        assert floors.sovereign == Decimal("0.0005"), (  # type: ignore[attr-defined]
            f"PDFloors.basel_3_1().sovereign should be Decimal('0.0005') "
            f"(PRA PS1/26 Art. 160(1): 0.05% PD floor). "
            f"Got {floors.sovereign!r}"  # type: ignore[attr-defined]
        )

    def test_pd_floors_basel_3_1_exposes_institution_field(self) -> None:
        """
        P2.36-1b: PDFloors.basel_3_1() must have an ``institution`` field equal to Decimal('0.0005').

        PRA PS1/26 Art. 160(1): the Basel 3.1 PD floor for institution IRB exposures
        is 0.05% (same as corporate). Today ``PDFloors`` has no ``institution`` field;
        this test fails with ``AttributeError`` until the field is added.
        """
        # Arrange
        floors = PDFloors.basel_3_1()

        # Act / Assert
        assert floors.institution == Decimal("0.0005"), (  # type: ignore[attr-defined]
            f"PDFloors.basel_3_1().institution should be Decimal('0.0005') "
            f"(PRA PS1/26 Art. 160(1): 0.05% PD floor). "
            f"Got {floors.institution!r}"  # type: ignore[attr-defined]
        )

    def test_pd_floors_crr_sovereign_field(self) -> None:
        """
        P2.36-2a: PDFloors.crr() must have a ``sovereign`` field equal to Decimal('0.0003').

        CRR Art. 160(1): uniform 0.03% PD floor for all IRB exposure classes,
        including sovereign. Today ``PDFloors.crr()`` has no ``sovereign`` field;
        this test fails with ``AttributeError`` until the field is added.
        """
        # Arrange
        floors = PDFloors.crr()

        # Act / Assert
        assert floors.sovereign == Decimal("0.0003"), (  # type: ignore[attr-defined]
            f"PDFloors.crr().sovereign should be Decimal('0.0003') "
            f"(CRR Art. 160(1): uniform 0.03% floor). "
            f"Got {floors.sovereign!r}"  # type: ignore[attr-defined]
        )

    def test_pd_floors_crr_institution_field(self) -> None:
        """
        P2.36-2b: PDFloors.crr() must have an ``institution`` field equal to Decimal('0.0003').

        CRR Art. 160(1): uniform 0.03% PD floor for all IRB exposure classes,
        including institution. Today ``PDFloors.crr()`` has no ``institution`` field;
        this test fails with ``AttributeError`` until the field is added.
        """
        # Arrange
        floors = PDFloors.crr()

        # Act / Assert
        assert floors.institution == Decimal("0.0003"), (  # type: ignore[attr-defined]
            f"PDFloors.crr().institution should be Decimal('0.0003') "
            f"(CRR Art. 160(1): uniform 0.03% floor). "
            f"Got {floors.institution!r}"  # type: ignore[attr-defined]
        )


# =============================================================================
# 2. get_floor dispatch tests
# =============================================================================


class TestGetFloorDispatch:
    """
    P2.36: PDFloors.get_floor() must dispatch to the explicit sovereign/institution fields.

    Note: On master today, get_floor falls through to the corporate fallback.
    Under Basel 3.1 the corporate fallback is also 0.0005, so these two tests
    may PASS on master (returning the correct value via the wrong path).

    The override regression tests below are the load-bearing discriminators —
    they prove the engine uses the new fields rather than the corporate fallback.
    """

    def test_get_floor_dispatches_sovereign_b31(self) -> None:
        """
        P2.36-3a: get_floor(CENTRAL_GOVT_CENTRAL_BANK) should return PDFloors.sovereign.

        Under Basel 3.1, PDFloors.basel_3_1().sovereign == 0.0005 (Art. 160(1)).
        Today this returns 0.0005 via the corporate fallback. The test still passes on
        master because the value happens to be the same; the override regression
        test below is the one that will fail on master.
        """
        # Arrange
        floors = PDFloors.basel_3_1()

        # Act
        result = floors.get_floor(ExposureClass.CENTRAL_GOVT_CENTRAL_BANK)

        # Assert
        assert result == Decimal("0.0005"), (
            f"get_floor(CENTRAL_GOVT_CENTRAL_BANK) should return 0.0005 "
            f"(PRA PS1/26 Art. 160(1): sovereign floor 0.05%). Got {result!r}"
        )

    def test_get_floor_dispatches_institution_b31(self) -> None:
        """
        P2.36-3b: get_floor(INSTITUTION) should return PDFloors.institution.

        Under Basel 3.1, PDFloors.basel_3_1().institution == 0.0005 (Art. 160(1)).
        Today this returns 0.0005 via the corporate fallback. The test still passes on
        master. The override regression test below is the load-bearing discriminator.
        """
        # Arrange
        floors = PDFloors.basel_3_1()

        # Act
        result = floors.get_floor(ExposureClass.INSTITUTION)

        # Assert
        assert result == Decimal("0.0005"), (
            f"get_floor(INSTITUTION) should return 0.0005 "
            f"(PRA PS1/26 Art. 160(1): institution floor 0.05%). Got {result!r}"
        )

    def test_get_floor_dispatches_sovereign_crr(self) -> None:
        """
        P2.36-3c: get_floor(CENTRAL_GOVT_CENTRAL_BANK) on CRR floors should return 0.0003.

        Under CRR, PDFloors.crr().sovereign == 0.0003 (uniform 0.03% floor).
        Today this returns 0.0003 via the corporate fallback (same value). Test passes
        on master; the override regression test is the load-bearing discriminator.
        """
        # Arrange
        floors = PDFloors.crr()

        # Act
        result = floors.get_floor(ExposureClass.CENTRAL_GOVT_CENTRAL_BANK)

        # Assert
        assert result == Decimal("0.0003"), (
            f"get_floor(CENTRAL_GOVT_CENTRAL_BANK) CRR should return 0.0003 "
            f"(CRR Art. 160(1): uniform 0.03% floor). Got {result!r}"
        )

    def test_get_floor_dispatches_institution_crr(self) -> None:
        """
        P2.36-3d: get_floor(INSTITUTION) on CRR floors should return 0.0003.

        Under CRR, PDFloors.crr().institution == 0.0003 (uniform 0.03% floor).
        Today this returns 0.0003 via the corporate fallback (same value). Test passes
        on master; the override regression test is the load-bearing discriminator.
        """
        # Arrange
        floors = PDFloors.crr()

        # Act
        result = floors.get_floor(ExposureClass.INSTITUTION)

        # Assert
        assert result == Decimal("0.0003"), (
            f"get_floor(INSTITUTION) CRR should return 0.0003 "
            f"(CRR Art. 160(1): uniform 0.03% floor). Got {result!r}"
        )


# =============================================================================
# 3. Override regression tests — load-bearing, must FAIL on master
# =============================================================================


class TestOverrideRegressionDispatch:
    """
    P2.36 load-bearing override regression tests.

    These tests verify that the IRB engine CONSUMES the new sovereign/institution
    fields from PDFloors rather than ignoring them and falling back to corporate.

    FAILURE MODE ON MASTER:
        The ``dataclasses.replace(cfg.pd_floors, institution=...)`` call (and the
        equivalent for sovereign) raises:
            TypeError: __init__() got an unexpected keyword argument 'institution'
        (or AttributeError when accessing the field for replace).

        This is the expected pre-fix failure. Once the engine-implementer adds the
        ``institution`` and ``sovereign`` fields to ``PDFloors``, the replace succeeds
        and the engine must also route _pd_floor_expression through the new branches
        for the RWA assertions to pass.

    INSTITUTION TEST (Basel 3.1 F-IRB):
        The institution exposure (INST_P236, PD=0.0003) is allowed through F-IRB under
        Basel 3.1 (Art. 147A(1)(b): F-IRB only, not SA-only). This is the primary
        load-bearing test because it exercises the full pipeline under the intended
        Basel 3.1 framework.

        Default: institution floor = 0.0005 → PD floored to 0.0005 → RW ≈ 0.174504
        Override: institution floor = 0.001  → PD floored to 0.001  → RW ≈ 0.263930
        Delta:    RWA_override − RWA_default ≈ 89,426 (≈51%)

    SOVEREIGN TEST (CRR F-IRB):
        The sovereign exposure (SOV_P236, PD=0.0001) is SA-only under Basel 3.1
        (Art. 147A(1)(a)), so the CRR pipeline (no Art. 147A restriction) is used here.
        Under CRR with full_irb() permissions, the sovereign model permission routes
        the exposure to F-IRB. Overriding the sovereign floor changes the PD floor and
        therefore the IRB RWA, proving the engine reads the sovereign field.

        Default: sovereign floor = 0.0003 → PD floored to 0.0003 → some RWA_default
        Override: sovereign floor = 0.001  → PD floored to 0.001  → RWA_override > RWA_default
    """

    def test_institution_floor_override_drives_dispatch_not_fallback(self) -> None:
        """
        P2.36-4: Institution floor override changes IRB RWA, proving the engine
        reads the institution PD floor (not the corporate fallback).

        Phase 5 S5c: the engine sources PD floors from the resolved rulepack, so
        the floor override is expressed as a ``pd_floors`` pack override injected
        via ``run_with_data(rulepack=...)`` — the successor to mutating
        ``config.pd_floors``.

        Arrange:
            One Basel 3.1 config; two rulepacks:
            - default: pack institution PD floor == 0.0005
            - override: pack institution PD floor == 0.001 (injected)
        Act:
            Run the P2.36 institution exposure (INST_P236) through both rulepacks.
        Assert:
            default → RW ≈ 0.174504, RWA ≈ 174,504 (PD floored to 0.0005)
            override → RW ≈ 0.263930, RWA ≈ 263,930 (PD floored to 0.001)
        """
        # Arrange — default Basel 3.1 config
        cfg_default = CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        )

        # Override: lift the institution PD floor to 0.001 (2× the default 0.0005)
        # on the resolved rulepack, injected via run_with_data. Phase 5 reads PD
        # floors from the pack, so a floor override is a pack override.
        override_rulepack = _pd_floor_override_rulepack(
            cfg_default, "institution", _INST_OVERRIDE_FLOOR
        )

        bundle_default = _build_p236_bundle()
        bundle_override = _build_p236_bundle()

        # Act
        results_default = _run_pipeline(bundle_default, cfg_default)
        results_override = PipelineOrchestrator().run_with_data(
            bundle_override, cfg_default, rulepack=override_rulepack
        )

        row_default = _get_irb_row(results_default, INSTITUTION_LOAN_REF)
        row_override = _get_irb_row(results_override, INSTITUTION_LOAN_REF)

        assert row_default is not None, (
            f"P2.36-4: {INSTITUTION_LOAN_REF!r} must appear in IRB results under Basel 3.1 "
            f"F-IRB (institution is F-IRB-eligible per Art. 147A(1)(b)). "
            f"Got None — check model_permission.parquet and classifier."
        )
        assert row_override is not None, (
            f"P2.36-4: {INSTITUTION_LOAN_REF!r} must appear in IRB results with override config."
        )

        # Assert — default: RW ≈ 0.174504 (PD floor 0.0005, LGD=0.40, M=2.5, scaling=1.0)
        actual_rw_default = row_default["risk_weight"]
        assert actual_rw_default == pytest.approx(EXPECTED_RW_B31_FLOORED, rel=1e-4), (
            f"P2.36-4 default: risk_weight should be ≈{EXPECTED_RW_B31_FLOORED:.6f} "
            f"(PD=0.0005, LGD=0.40, M=2.5, B31 no scaling). "
            f"Got {actual_rw_default:.6f}."
        )

        actual_rwa_default = row_default["rwa"]
        assert actual_rwa_default == pytest.approx(EXPECTED_RWA_B31_FLOORED, rel=1e-4), (
            f"P2.36-4 default: rwa should be ≈{EXPECTED_RWA_B31_FLOORED:,.0f}. "
            f"Got {actual_rwa_default:,.0f}."
        )

        # Assert — override: RW ≈ 0.263930 (PD floor 0.001, LGD=0.40, M=2.5, scaling=1.0)
        actual_rw_override = row_override["risk_weight"]
        assert actual_rw_override == pytest.approx(EXPECTED_RW_B31_SOV_OVERRIDE, rel=1e-4), (
            f"P2.36-4 override: risk_weight should be ≈{EXPECTED_RW_B31_SOV_OVERRIDE:.6f} "
            f"(PD=0.001, LGD=0.40, M=2.5, B31 no scaling — institution floor=0.001). "
            f"Got {actual_rw_override:.6f}. "
            f"If equal to the default ({EXPECTED_RW_B31_FLOORED:.6f}), the engine is NOT "
            f"consuming the new institution field — it is still using the corporate fallback."
        )

        actual_rwa_override = row_override["rwa"]
        assert actual_rwa_override == pytest.approx(EXPECTED_RWA_B31_SOV_OVERRIDE, rel=1e-4), (
            f"P2.36-4 override: rwa should be ≈{EXPECTED_RWA_B31_SOV_OVERRIDE:,.0f}. "
            f"Got {actual_rwa_override:,.0f}."
        )

        # Anti-regression: the two arms must produce materially different RWA
        assert actual_rwa_override > actual_rwa_default * 1.3, (
            f"P2.36-4 anti-regression: rwa_override ({actual_rwa_override:,.0f}) must exceed "
            f"rwa_default ({actual_rwa_default:,.0f}) by >30%. "
            f"If they are equal, the engine ignores the institution field override."
        )

    def test_sovereign_floor_override_drives_dispatch_not_fallback(self) -> None:
        """
        P2.36-5: Sovereign floor override changes CRR IRB RWA, proving the engine
        reads the sovereign PD floor (not the corporate fallback).

        Note: Sovereign is SA-only under Basel 3.1 (Art. 147A(1)(a)), so CRR is used
        here to allow the exposure through the F-IRB path.

        Phase 5 S5c: the engine sources PD floors from the resolved rulepack, so
        the floor override is a ``pd_floors`` pack override injected via
        ``run_with_data(rulepack=...)``.

        Arrange:
            One CRR config with IRB permissions; two rulepacks:
            - default: pack sovereign PD floor == 0.0003
            - override: pack sovereign PD floor == 0.001 (injected)
        Act:
            Run the P2.36 sovereign exposure (SOV_P236, input PD=0.0001) through both rulepacks.
        Assert:
            override → IRB RWA materially higher than default (floor lifted from 0.0003 to 0.001).
            Anti-regression: rwa_override != rwa_default (proves engine reads sovereign floor).
        """
        # Arrange — default CRR config with full IRB permissions
        cfg_default = CalculationConfig.crr(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        )

        # Override: lift the sovereign PD floor to 0.001 (3.3× the CRR default 0.0003)
        # on the resolved rulepack, injected via run_with_data. Phase 5 reads PD
        # floors from the pack, so a floor override is a pack override.
        override_rulepack = _pd_floor_override_rulepack(
            cfg_default, "sovereign", _SOV_OVERRIDE_FLOOR
        )

        bundle_default = _build_p236_bundle()
        bundle_override = _build_p236_bundle()

        # Act
        results_default = _run_pipeline(bundle_default, cfg_default)
        results_override = PipelineOrchestrator().run_with_data(
            bundle_override, cfg_default, rulepack=override_rulepack
        )

        row_default = _get_irb_row(results_default, SOVEREIGN_LOAN_REF)
        row_override = _get_irb_row(results_override, SOVEREIGN_LOAN_REF)

        assert row_default is not None, (
            f"P2.36-5: {SOVEREIGN_LOAN_REF!r} must appear in IRB results under CRR "
            f"with full_irb() permissions. "
            f"Got None — check model_permission.parquet ('central_govt_central_bank', "
            f"'foundation_irb') and classifier."
        )
        assert row_override is not None, (
            f"P2.36-5: {SOVEREIGN_LOAN_REF!r} must appear in IRB results with override config."
        )

        rwa_default = row_default["rwa"]
        rwa_override = row_override["rwa"]

        # Anti-regression: the two arms must produce different RWA
        assert rwa_override != pytest.approx(rwa_default, rel=1e-3), (
            f"P2.36-5 anti-regression: rwa_override ({rwa_override:,.0f}) must differ from "
            f"rwa_default ({rwa_default:,.0f}). "
            f"If equal, the engine is NOT consuming the new sovereign field — "
            f"it still falls back to the corporate floor (which is unchanged)."
        )

        # The override floor (0.001) is higher than the default (0.0003), so the floored PD
        # is higher, and therefore the IRB RWA must be higher.
        assert rwa_override > rwa_default, (
            f"P2.36-5: rwa_override ({rwa_override:,.0f}) must exceed rwa_default "
            f"({rwa_default:,.0f}) because the override sovereign floor "
            f"({_SOV_OVERRIDE_FLOOR}) > default floor (0.0003). "
            f"A higher floor → higher floored PD → higher IRB risk weight."
        )

        # The override floor is 3.3× the default: expect a substantial (>30%) RWA increase.
        assert rwa_override > rwa_default * 1.3, (
            f"P2.36-5: rwa_override ({rwa_override:,.0f}) should exceed rwa_default "
            f"({rwa_default:,.0f}) by >30%. Override floor 0.001 vs default 0.0003 should "
            f"produce a material RWA lift."
        )


# =============================================================================
# 4. Fixture sanity guards (fast, no pipeline invocation)
# =============================================================================


class TestP236FixtureSanity:
    """Fixture constant and file sanity checks — no pipeline invocation."""

    def test_p236_fixture_parquet_files_exist(self) -> None:
        """P2.36: all required parquet fixture files must be present on disk."""
        for name in ("counterparty", "facility", "loan", "rating", "model_permission"):
            path = _FIXTURES_DIR / f"{name}.parquet"
            assert path.exists(), (
                f"P2.36 fixture file missing: {path}. "
                f"Run: uv run python tests/fixtures/p2_36/p2_36.py"
            )

    def test_p236_sovereign_pd_below_b31_floor(self) -> None:
        """P2.36: sovereign input PD (0.0001) is below Basel 3.1 floor (0.0005) — floor binds."""
        from tests.fixtures.p2_36.p2_36 import EXPECTED_PD_FLOORED_B31, PD_SOVEREIGN

        assert PD_SOVEREIGN < EXPECTED_PD_FLOORED_B31, (
            f"Fixture: PD_SOVEREIGN ({PD_SOVEREIGN}) must be below B31 floor "
            f"({EXPECTED_PD_FLOORED_B31}) so the floor is always binding."
        )

    def test_p236_institution_pd_below_b31_floor(self) -> None:
        """P2.36: institution input PD (0.0003) is below Basel 3.1 floor (0.0005) — floor binds."""
        from tests.fixtures.p2_36.p2_36 import EXPECTED_PD_FLOORED_B31, PD_INSTITUTION

        assert PD_INSTITUTION < EXPECTED_PD_FLOORED_B31, (
            f"Fixture: PD_INSTITUTION ({PD_INSTITUTION}) must be below B31 floor "
            f"({EXPECTED_PD_FLOORED_B31}) so the floor is always binding."
        )

    def test_p236_expected_rw_override_greater_than_default(self) -> None:
        """P2.36: EXPECTED_RW_B31_SOV_OVERRIDE > EXPECTED_RW_B31_FLOORED (higher floor → higher RW)."""
        assert EXPECTED_RW_B31_SOV_OVERRIDE > EXPECTED_RW_B31_FLOORED, (
            f"Fixture: override RW ({EXPECTED_RW_B31_SOV_OVERRIDE}) should exceed "
            f"default RW ({EXPECTED_RW_B31_FLOORED}) — floor 0.001 > 0.0005."
        )
