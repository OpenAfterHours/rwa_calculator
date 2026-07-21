"""Unit tests: reporting-scope config / API plumbing (multi-entity reporting W1-A).

Pins the config-and-API half of run-per-scope submissions:
- ``reporting_entity`` requires a ``reporting_basis`` (a config error, raised);
- both factories accept and set the top-level scope, and ``.basel_3_1()`` still
  propagates the basis into the OutputFloorConfig (Art. 92 para 2A);
- ``CreditRiskCalc`` forwards the scope into the config and stamps it onto the
  response (enum rendered as its string value);
- the run-index fingerprint distinguishes two scopes over identical data, and a
  run_index.json written before these fields existed still loads (None scope).

The hard invariant across all of this: with no scope configured everything
behaves exactly as before multi-entity reporting existed.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api import run_index
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import InstitutionType, ReportingBasis

# =============================================================================
# Config validation rule
# =============================================================================


class TestScopeValidation:
    def test_entity_without_basis_raises(self) -> None:
        # Arrange / Act / Assert
        with pytest.raises(ValueError, match="reporting_basis"):
            CalculationConfig.crr(
                reporting_date=date(2025, 1, 1),
                reporting_entity="ENTITY_A",
            )

    def test_entity_without_basis_raises_on_basel(self) -> None:
        with pytest.raises(ValueError, match="reporting_basis"):
            CalculationConfig.basel_3_1(
                reporting_date=date(2027, 1, 1),
                reporting_entity="ENTITY_A",
            )

    def test_entity_without_basis_raises_on_direct_construction(self) -> None:
        with pytest.raises(ValueError, match="reporting_basis"):
            CalculationConfig(
                regime_id="crr",
                reporting_date=date(2025, 1, 1),
                reporting_entity="ENTITY_A",
            )

    def test_basis_alone_is_valid(self) -> None:
        # reporting_basis without reporting_entity keeps existing floor semantics.
        config = CalculationConfig.crr(
            reporting_date=date(2025, 1, 1),
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )

        assert config.reporting_basis is ReportingBasis.CONSOLIDATED
        assert config.reporting_entity is None

    def test_entity_with_basis_is_valid(self) -> None:
        config = CalculationConfig.crr(
            reporting_date=date(2025, 1, 1),
            reporting_entity="ENTITY_A",
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )

        assert config.reporting_entity == "ENTITY_A"
        assert config.reporting_basis is ReportingBasis.INDIVIDUAL

    def test_unscoped_config_has_none_scope(self) -> None:
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        assert config.reporting_entity is None
        assert config.reporting_basis is None


# =============================================================================
# Factory propagation (incl. floor-config interplay)
# =============================================================================


class TestFactoryPropagation:
    def test_basel_propagates_basis_into_floor(self) -> None:
        # Arrange / Act
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1),
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )

        # Assert — top-level scope AND the floor config both carry the basis.
        assert config.reporting_basis is ReportingBasis.INDIVIDUAL
        assert config.output_floor.reporting_basis is ReportingBasis.INDIVIDUAL
        assert config.output_floor.institution_type is InstitutionType.STANDALONE_UK

    def test_basel_floor_applicability_still_works(self) -> None:
        # STANDALONE_UK on individual basis is in scope (Art. 92 para 2A(a)(i)).
        applicable = CalculationConfig.basel_3_1(
            reporting_date=date(2032, 1, 1),
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        # RFB at individual level is exempt (para 2A(c)).
        exempt = CalculationConfig.basel_3_1(
            reporting_date=date(2032, 1, 1),
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )

        assert applicable.output_floor.is_floor_applicable() is True
        assert exempt.output_floor.is_floor_applicable() is False

    def test_basel_without_scope_leaves_floor_fields_none(self) -> None:
        # Backward compatible: no scope args -> floor assumes applicable.
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

        assert config.reporting_basis is None
        assert config.output_floor.reporting_basis is None
        assert config.output_floor.institution_type is None
        assert config.output_floor.is_entity_in_scope() is True

    def test_basel_sets_top_level_entity(self) -> None:
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1),
            reporting_entity="GROUP_APEX",
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )

        assert config.reporting_entity == "GROUP_APEX"

    def test_crr_scope_does_not_enable_floor(self) -> None:
        config = CalculationConfig.crr(
            reporting_date=date(2025, 1, 1),
            reporting_entity="ENTITY_A",
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )

        assert config.output_floor.enabled is False


# =============================================================================
# CreditRiskCalc forwarding + response stamping
# =============================================================================


class TestServiceForwarding:
    def test_create_config_forwards_scope_crr(self, tmp_path: Path) -> None:
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            cache_dir=tmp_path / "cache",
            reporting_entity="ENTITY_A",
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )

        config = calc._create_config()

        assert config.reporting_entity == "ENTITY_A"
        assert config.reporting_basis is ReportingBasis.INDIVIDUAL

    def test_create_config_forwards_scope_basel(self, tmp_path: Path) -> None:
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
            cache_dir=tmp_path / "cache",
            reporting_entity="GROUP_APEX",
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )

        config = calc._create_config()

        assert config.reporting_entity == "GROUP_APEX"
        assert config.reporting_basis is ReportingBasis.CONSOLIDATED
        # Basis reached the floor config too.
        assert config.output_floor.reporting_basis is ReportingBasis.CONSOLIDATED

    def test_stamp_scope_renders_enum_as_string(self, tmp_path: Path) -> None:
        # Arrange — a bare formatter-style response with no scope set.
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
            cache_dir=tmp_path / "cache",
            reporting_entity="GROUP_APEX",
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        response = _bare_response()

        # Act
        stamped = calc._stamp_scope(response)

        # Assert — entity kept, basis is the enum's string value.
        assert stamped.reporting_entity == "GROUP_APEX"
        assert stamped.reporting_basis == "consolidated"

    def test_stamp_scope_is_noop_when_unscoped(self, tmp_path: Path) -> None:
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            cache_dir=tmp_path / "cache",
        )
        response = _bare_response()

        stamped = calc._stamp_scope(response)

        assert stamped == response
        assert stamped.reporting_entity is None
        assert stamped.reporting_basis is None


class TestCalculateStampsScope:
    """End-to-end: calculate()'s RETURNED response carries the stamped scope.

    Drives the cheap error path (a data_path that fails validation ->
    format_error_response -> _stamp_scope) so the actual return-wrapping is
    exercised, not _stamp_scope in isolation.
    """

    def test_error_response_carries_scope(self, tmp_path: Path) -> None:
        # Arrange — a nonexistent data_path fails validation without a pipeline run.
        calc = CreditRiskCalc(
            data_path=tmp_path / "nonexistent",
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
            cache_dir=tmp_path / "cache",
            reporting_entity="GROUP_APEX",
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )

        # Act
        response = calc.calculate()

        # Assert — a failed run, but the scope is stamped on the returned object.
        assert response.success is False
        assert response.reporting_entity == "GROUP_APEX"
        assert response.reporting_basis == "consolidated"

    def test_error_response_unscoped_stays_none(self, tmp_path: Path) -> None:
        calc = CreditRiskCalc(
            data_path=tmp_path / "nonexistent",
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            cache_dir=tmp_path / "cache",
        )

        response = calc.calculate()

        assert response.success is False
        assert response.reporting_entity is None
        assert response.reporting_basis is None


# =============================================================================
# CalculationResponse fields
# =============================================================================


class TestResponseFields:
    def test_defaults_are_none(self) -> None:
        response = _bare_response()

        assert response.reporting_entity is None
        assert response.reporting_basis is None

    def test_fields_are_carried(self) -> None:
        response = dataclasses.replace(
            _bare_response(),
            reporting_entity="ENTITY_A",
            reporting_basis="individual",
        )

        assert response.reporting_entity == "ENTITY_A"
        assert response.reporting_basis == "individual"


# =============================================================================
# Fingerprint — scope is part of run identity
# =============================================================================


@pytest.fixture(autouse=True)
def clean_index() -> None:
    """Each test starts from an empty in-process index."""
    run_index.clear()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir(parents=True)
    pl.DataFrame({"id": ["1"]}).write_parquet(root / "exposures.parquet")
    return root


def _fingerprint(data_dir: Path, **overrides: object) -> run_index.CalculationFingerprint:
    params: dict = {
        "data_path": data_dir,
        "framework": "CRR",
        "reporting_date": date(2025, 1, 1),
        "permission_mode": "standardised",
        "data_format": "parquet",
    }
    params.update(overrides)
    return run_index.compute_fingerprint(**params)


class TestFingerprintScope:
    def test_unscoped_fingerprint_matches_the_old_default(self, data_dir: Path) -> None:
        # No scope args -> both fields None, and identical requests still match.
        fp = _fingerprint(data_dir)
        assert fp.reporting_entity is None
        assert fp.reporting_basis is None
        assert fp == _fingerprint(data_dir)

    def test_distinct_entities_differ(self, data_dir: Path) -> None:
        a = _fingerprint(data_dir, reporting_entity="A", reporting_basis="consolidated")
        b = _fingerprint(data_dir, reporting_entity="B", reporting_basis="consolidated")

        assert a != b

    def test_distinct_bases_differ(self, data_dir: Path) -> None:
        indiv = _fingerprint(data_dir, reporting_entity="A", reporting_basis="individual")
        consol = _fingerprint(data_dir, reporting_entity="A", reporting_basis="consolidated")

        assert indiv != consol

    def test_scope_miss_over_identical_data(self, data_dir: Path) -> None:
        # Arrange — register a run for scope A over this exact data.
        response = _response_backed_by(data_dir / "cache")
        fp_a = _fingerprint(data_dir, reporting_entity="A", reporting_basis="consolidated")
        run_index.register_calculation(fp_a, "run-a", response)

        # Act — a different scope over the SAME data must not reuse it.
        fp_b = _fingerprint(data_dir, reporting_entity="B", reporting_basis="consolidated")

        assert run_index.find_reusable(fp_b) is None
        assert run_index.find_latest_for_params(fp_b) is None
        assert run_index.find_reusable(fp_a) is not None


# =============================================================================
# Persistence backward compatibility
# =============================================================================


class TestPersistenceScope:
    def test_scope_survives_restart(self, tmp_path: Path, data_dir: Path) -> None:
        # Arrange
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        response = dataclasses.replace(
            _response_backed_by(state / "runs" / "run-a"),
            reporting_entity="A",
            reporting_basis="consolidated",
        )
        fp = _fingerprint(data_dir, reporting_entity="A", reporting_basis="consolidated")
        run_index.register_calculation(fp, "run-a", response)

        # Act — restart.
        run_index.clear()
        run_index.configure_persistence(state)

        # Assert — the fingerprint and the response both carry the scope back.
        hit = run_index.find_reusable(fp)
        assert hit is not None
        assert hit.response.reporting_entity == "A"
        assert hit.response.reporting_basis == "consolidated"

    def test_old_json_without_scope_keys_loads_as_none(
        self, tmp_path: Path, data_dir: Path
    ) -> None:
        # Arrange — persist normally, then strip the new keys to mimic an old file.
        state = tmp_path / "state"
        run_index.configure_persistence(state)
        response = _response_backed_by(state / "runs" / "run-a")
        run_index.register_calculation(_fingerprint(data_dir), "run-a", response)
        persist_path = state / "run_index.json"
        raw = json.loads(persist_path.read_text(encoding="utf-8"))
        for entry in raw["entries"]:
            del entry["fingerprint"]["reporting_entity"]
            del entry["fingerprint"]["reporting_basis"]
            del entry["response"]["reporting_entity"]
            del entry["response"]["reporting_basis"]
        persist_path.write_text(json.dumps(raw), encoding="utf-8")

        # Act — restart against the old-shaped file.
        run_index.clear()
        run_index.configure_persistence(state)

        # Assert — loads fine, scope is None on both fingerprint and response.
        hit = run_index.find_reusable(_fingerprint(data_dir))
        assert hit is not None
        assert hit.response.reporting_entity is None
        assert hit.response.reporting_basis is None


# =============================================================================
# Helpers
# =============================================================================


def _bare_response() -> CalculationResponse:
    """A minimal CalculationResponse with no scope set (results_path unused here)."""
    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("100"),
            total_rwa=Decimal("50"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=Path("unused.parquet"),
    )


def _response_backed_by(cache_dir: Path) -> CalculationResponse:
    """A successful response backed by a real results parquet under *cache_dir*."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    results = cache_dir / "last_results.parquet"
    pl.DataFrame({"exposure_reference": ["LN-1"], "rwa_final": [1.0]}).write_parquet(results)
    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("100"),
            total_rwa=Decimal("50"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=results,
    )
