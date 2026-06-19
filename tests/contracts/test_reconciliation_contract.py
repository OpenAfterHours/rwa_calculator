"""Contract tests for the parallel-run reconciliation surface.

Covers config-dataclass validation, the frozen ReconciliationBundle + empty
factory, REC error-code uniqueness, TOML config round-trip, and
ReconciliationResponse.from_bundle behaviour on an empty bundle.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.api.reconciliation import (
    ReconciliationSettings,
    dump_reconciliation_config,
    load_reconciliation_config,
)
from rwa_calc.contracts.bundles import (
    ReconciliationBundle,
    create_empty_reconciliation_bundle,
)
from rwa_calc.contracts.errors import (
    ERROR_RECON_DUPLICATE_LEGACY_KEY,
    ERROR_RECON_GRAIN_HETEROGENEOUS,
    ERROR_RECON_KEY_COLUMN_MISSING,
    ERROR_RECON_LEGACY_COLUMN_MISSING,
)


class TestConfigValidation:
    def test_valid_mapping_coerces_keys_to_tuples(self) -> None:
        mapping = LegacyColumnMapping(
            legacy_keys=["a"],  # ty: ignore[invalid-argument-type]
            our_keys=["exposure_reference"],  # ty: ignore[invalid-argument-type]
            components={"rwa": ComponentMapping("R")},
        )
        assert isinstance(mapping.legacy_keys, tuple)
        assert isinstance(mapping.our_keys, tuple)

    def test_key_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            LegacyColumnMapping(
                legacy_keys=("a", "b"),
                our_keys=("x",),
                components={"rwa": ComponentMapping("R")},
            )

    def test_empty_components_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one component"):
            LegacyColumnMapping(legacy_keys=("a",), components={})

    def test_unknown_component_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown reconciliation components"):
            LegacyColumnMapping(
                legacy_keys=("a",), components={"not_a_component": ComponentMapping("R")}
            )

    def test_bad_unit_raises(self) -> None:
        with pytest.raises(ValueError, match="unit must be one of"):
            ComponentMapping("R", unit="furlongs")  # ty: ignore[invalid-argument-type]

    def test_negative_tolerance_raises(self) -> None:
        with pytest.raises(ValueError, match="tol must be non-negative"):
            ComponentMapping("R", tol=-0.1)


class TestBundle:
    def test_bundle_is_frozen(self) -> None:
        bundle = create_empty_reconciliation_bundle()
        with pytest.raises(dataclasses.FrozenInstanceError):
            bundle.errors = []  # ty: ignore[invalid-assignment]

    def test_errors_defaults_to_empty_list(self) -> None:
        assert create_empty_reconciliation_bundle().errors == []

    def test_empty_factory_has_all_frames(self) -> None:
        bundle = create_empty_reconciliation_bundle()
        assert isinstance(bundle, ReconciliationBundle)
        # All seven frames present (collect_schema works on each).
        for frame in (
            bundle.component_reconciliation,
            bundle.summary_by_component,
            bundle.summary_by_bucket,
            bundle.summary_by_exposure_class,
            bundle.summary_by_approach,
            bundle.breaks_detail,
            bundle.totals_tie_out,
        ):
            assert frame.collect().height == 0


class TestErrorCodes:
    def test_rec_codes_unique(self) -> None:
        codes = [
            ERROR_RECON_LEGACY_COLUMN_MISSING,
            ERROR_RECON_DUPLICATE_LEGACY_KEY,
            ERROR_RECON_KEY_COLUMN_MISSING,
            ERROR_RECON_GRAIN_HETEROGENEOUS,
        ]
        assert len(set(codes)) == len(codes)
        assert all(c.startswith("REC") for c in codes)


class TestConfigRoundTrip:
    def test_toml_round_trip_is_identity(self, tmp_path: Path) -> None:
        # Arrange
        legacy_file = (tmp_path / "legacy.csv").resolve()
        settings = ReconciliationSettings(
            legacy_file=legacy_file,
            legacy_format="csv",
            top_n=25,
            mapping=LegacyColumnMapping(
                legacy_keys=("Obligor ID", "Facility ID"),
                our_keys=("counterparty_reference", "root_facility_reference"),
                components={
                    "rwa": ComponentMapping("RWA Amt", scale=1_000_000.0),
                    "pd": ComponentMapping("PD_pct", unit="percent", tol_kind="abs", tol=1e-4),
                    "exposure_class": ComponentMapping(
                        "Asset_Class", value_map={"CORP": "corporate", "RETAIL": "retail"}
                    ),
                },
            ),
        )

        # Act
        cfg_path = tmp_path / "reconciliation.toml"
        cfg_path.write_text(dump_reconciliation_config(settings))
        reloaded = load_reconciliation_config(cfg_path)

        # Assert
        assert reloaded == settings

    def test_missing_legacy_file_key_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "bad.toml"
        cfg.write_text('legacy_keys = ["a"]\n[components.rwa]\nlegacy_column = "R"\n')
        with pytest.raises(ValueError, match="legacy_file"):
            load_reconciliation_config(cfg)


class TestResponseFromBundle:
    def test_empty_bundle_is_not_successful(self) -> None:
        from rwa_calc.api.models import ReconciliationResponse

        resp = ReconciliationResponse.from_bundle(
            create_empty_reconciliation_bundle(), legacy_file=Path("legacy.csv")
        )
        assert resp.success is False
        assert resp.has_breaks is False
