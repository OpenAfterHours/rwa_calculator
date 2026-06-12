"""
Pins for the Phase 3 silent-skip fix on engine/utils.py.

``has_required_columns`` / ``has_rows`` no longer swallow exceptions: a
plan that cannot resolve its schema is a programming error and raises,
so "firm has no guarantees" and "refactor broke the key column" are
distinguishable again. The one legitimate data-quality case — a supplied
collateral table with incompatible dtypes — is handled at the CRM
boundary with a precise warning (and on-BS netting still applies).

References:
- docs/plans/target-architecture-migration.md (Phase 3: silent-skip layer)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.utils import has_required_columns, has_rows
from tests.fixtures.resolved_bundle import make_classified_bundle


def _broken_plan() -> pl.LazyFrame:
    """A plan whose schema resolution fails (dtype-conflicting concat)."""
    a = pl.LazyFrame({"market_value": [1.0]})
    b = pl.LazyFrame({"market_value": ["not-a-number"]})
    return pl.concat([a, b], how="diagonal")


class TestHasRequiredColumns:
    def test_none_input_is_false(self):
        assert has_required_columns(None, {"x"}) is False

    def test_missing_column_is_false(self):
        assert has_required_columns(pl.LazyFrame({"a": [1]}), {"a", "b"}) is False

    def test_present_columns_is_true(self):
        assert has_required_columns(pl.LazyFrame({"a": [1], "b": [2]}), {"a", "b"}) is True

    def test_schema_resolution_failure_raises(self):
        # Previously the bare except returned False — the calling stage
        # silently skipped its sub-step on a broken plan.
        with pytest.raises(Exception, match="[Ss]chema|dtype|supertype|type"):
            has_required_columns(_broken_plan(), {"market_value"})


class TestHasRows:
    def test_empty_frame_is_false(self):
        assert has_rows(pl.LazyFrame({"a": pl.Series([], dtype=pl.Int64)})) is False

    def test_nonempty_frame_is_true(self):
        assert has_rows(pl.LazyFrame({"a": [1]})) is True

    def test_schema_resolution_failure_raises(self):
        with pytest.raises(Exception, match="[Ss]chema|dtype|supertype|type"):
            has_rows(_broken_plan())


class TestMalformedCollateralBoundary:
    """The CRM boundary owns the leniency, with an accurate message."""

    def test_incompatible_dtypes_warn_precisely_and_netting_survives(self):
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "exposure_class": ["corporate"],
                "approach": ["standardised"],
                "exposure_type": ["loan"],
                "drawn_amount": [1000.0],
                "currency": ["GBP"],
                "original_currency": ["GBP"],
            }
        )
        bad_collateral = pl.LazyFrame(
            {
                "collateral_reference": ["C1"],
                "beneficiary_reference": ["E1"],
                "beneficiary_type": ["loan"],
                "market_value": ["lots"],  # String — incompatible dtype
                "collateral_type": ["cash"],
            }
        )
        bundle = make_classified_bundle(all_exposures=exposures, collateral=bad_collateral)
        config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

        result = CRMProcessor().get_crm_unified_bundle(bundle, config)

        dtype_warnings = [e for e in result.crm_errors if "incompatible column dtypes" in e.message]
        assert len(dtype_warnings) == 1
        assert "market_value" in dtype_warnings[0].message
        # The run still completes with the malformed table dropped.
        assert result.exposures.collect().height == 1
