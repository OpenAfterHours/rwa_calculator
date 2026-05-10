"""Tests for validate_aggregated_bundle — P2.34.

Validates the output-bounds checker on AggregatedResultBundle.results.

The function raises four categories of bound violations:
- OUT001: risk_weight > 12.5  (CRR Art. 92(3); CRE31.5)
- OUT002: risk_weight < 0     (CRR Art. 153; CRE31)
- OUT003: rwa_final < -1e-9   (CRR Art. 92(3))
- OUT004: ead_final is null   (data quality)

References:
- CRR Art. 92(3): minimum capital requirement
- CRR Art. 153: IRB risk weight function
- CRE31: Basel risk weight floors
"""

from __future__ import annotations

import polars as pl
import pytest

import rwa_calc.contracts.validation as _validation_module
from rwa_calc.contracts.bundles import AggregatedResultBundle

# Defer resolution of validate_aggregated_bundle so collection succeeds even
# before the engine-implementer adds the function.  Each test that calls it
# will get an AttributeError turned into a plain assertion failure, which
# satisfies the "assertion-style for C3.4" requirement.
_validate_aggregated_bundle = getattr(_validation_module, "validate_aggregated_bundle", None)


def validate_aggregated_bundle(*args, **kwargs):  # type: ignore[return]
    """Thin shim that defers the ImportError to assertion time."""
    assert _validate_aggregated_bundle is not None, (
        "validate_aggregated_bundle is not yet defined in rwa_calc.contracts.validation"
    )
    return _validate_aggregated_bundle(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_results_lf(
    exposure_references: list[str],
    risk_weights: list[float | None],
    rwa_finals: list[float | None],
    ead_finals: list[float | None],
) -> pl.LazyFrame:
    """Build a minimal results LazyFrame matching RESULT_SCHEMA."""
    n = len(exposure_references)
    return pl.LazyFrame(
        {
            "exposure_reference": exposure_references,
            "approach_applied": ["sa"] * n,
            "exposure_class": ["corporate"] * n,
            "ead_final": pl.Series(ead_finals, dtype=pl.Float64),
            "risk_weight": pl.Series(risk_weights, dtype=pl.Float64),
            "rwa_final": pl.Series(rwa_finals, dtype=pl.Float64),
        }
    )


def _make_bundle(results: pl.LazyFrame) -> AggregatedResultBundle:
    """Wrap a results LazyFrame in a minimal AggregatedResultBundle."""
    return AggregatedResultBundle(results=results)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateAggregatedBundle:
    """Contract tests for validate_aggregated_bundle."""

    def test_validate_aggregated_bundle_returns_four_errors_for_known_failure_modes(self):
        """Four distinct bound violations across four rows produce exactly four errors.

        Fixture (from scenario proposal):
          E001 — clean row: rw=0.20, rwa=200_000, ead=1_000_000
          E002 — OUT001: rw=13.0  (> 12.5)
          E003 — OUT002 + OUT003: rw=-0.5 (< 0), rwa=-500_000 (< -1e-9)
          E004 — OUT004: ead_final=None
        """
        # Arrange
        results = _make_results_lf(
            exposure_references=["E001", "E002", "E003", "E004"],
            risk_weights=[0.20, 13.0, -0.5, 1.00],
            rwa_finals=[200_000.0, 1_300_000.0, -500_000.0, 1_000_000.0],
            ead_finals=[1_000_000.0, 100_000.0, 1_000_000.0, None],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — exactly four errors
        assert len(errors) == 4, f"Expected 4 errors but got {len(errors)}: " + ", ".join(
            f"[{e.code}] {e.exposure_reference}" for e in errors
        )

        codes = [e.code for e in errors]
        assert codes.count("OUT001") == 1, f"Expected 1× OUT001, got {codes.count('OUT001')}"
        assert codes.count("OUT002") == 1, f"Expected 1× OUT002, got {codes.count('OUT002')}"
        assert codes.count("OUT003") == 1, f"Expected 1× OUT003, got {codes.count('OUT003')}"
        assert codes.count("OUT004") == 1, f"Expected 1× OUT004, got {codes.count('OUT004')}"

    def test_validate_aggregated_bundle_out001_error_references_correct_exposure(self):
        """OUT001 error must identify the violating exposure (E002)."""
        # Arrange
        results = _make_results_lf(
            exposure_references=["E001", "E002", "E003", "E004"],
            risk_weights=[0.20, 13.0, -0.5, 1.00],
            rwa_finals=[200_000.0, 1_300_000.0, -500_000.0, 1_000_000.0],
            ead_finals=[1_000_000.0, 100_000.0, 1_000_000.0, None],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — OUT001 points to E002
        out001 = [e for e in errors if e.code == "OUT001"]
        assert len(out001) == 1
        assert out001[0].exposure_reference == "E002"

    def test_validate_aggregated_bundle_out002_and_out003_share_same_exposure(self):
        """E003 produces both OUT002 (rw < 0) and OUT003 (rwa < -1e-9)."""
        # Arrange
        results = _make_results_lf(
            exposure_references=["E001", "E002", "E003", "E004"],
            risk_weights=[0.20, 13.0, -0.5, 1.00],
            rwa_finals=[200_000.0, 1_300_000.0, -500_000.0, 1_000_000.0],
            ead_finals=[1_000_000.0, 100_000.0, 1_000_000.0, None],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — both OUT002 and OUT003 reference E003
        e003_codes = {e.code for e in errors if e.exposure_reference == "E003"}
        assert "OUT002" in e003_codes
        assert "OUT003" in e003_codes

    def test_validate_aggregated_bundle_clean_bundle_returns_empty_list(self):
        """All-clean results produce no errors."""
        # Arrange — four rows identical to E001 shape (all within bounds, no nulls)
        results = _make_results_lf(
            exposure_references=["C001", "C002", "C003", "C004"],
            risk_weights=[0.20, 0.75, 1.50, 0.35],
            rwa_finals=[200_000.0, 750_000.0, 1_500_000.0, 350_000.0],
            ead_finals=[1_000_000.0, 1_000_000.0, 1_000_000.0, 1_000_000.0],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert
        assert errors == []

    def test_validate_aggregated_bundle_empty_results_returns_empty_list(self):
        """An empty results LazyFrame (zero rows) must return an empty list."""
        # Arrange — empty frame with the correct schema
        results = pl.LazyFrame(
            {
                "exposure_reference": pl.Series([], dtype=pl.String),
                "approach_applied": pl.Series([], dtype=pl.String),
                "exposure_class": pl.Series([], dtype=pl.String),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa_final": pl.Series([], dtype=pl.Float64),
            }
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert
        assert errors == []

    def test_validate_aggregated_bundle_sample_cap_limits_row_errors(self):
        """When more than sample_cap rows violate a bound, extra rows are summarised.

        Build 7 rows that all exceed risk_weight > 12.5 (OUT001).
        With sample_cap=5, expect exactly 5 per-row OUT001 errors plus 1 summary
        error for the 2 rows beyond the cap — total 6.
        """
        # Arrange
        n = 7
        results = _make_results_lf(
            exposure_references=[f"X{i:03d}" for i in range(n)],
            risk_weights=[14.0] * n,
            rwa_finals=[1_000_000.0] * n,
            ead_finals=[1_000_000.0] * n,
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle, sample_cap=5)

        # Assert — 5 per-row errors + 1 summary = 6 total; all coded OUT001
        out001_errors = [e for e in errors if e.code == "OUT001"]
        assert len(out001_errors) == 6, (
            f"Expected 6 OUT001 errors (5 row + 1 summary) but got {len(out001_errors)}"
        )

    def test_validate_aggregated_bundle_missing_column_silently_skipped(self):
        """If risk_weight is absent from results schema the bound is silently skipped."""
        # Arrange — omit risk_weight column entirely
        results = pl.LazyFrame(
            {
                "exposure_reference": ["M001", "M002"],
                "approach_applied": ["sa", "sa"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": pl.Series([500_000.0, 750_000.0], dtype=pl.Float64),
                "rwa_final": pl.Series([50_000.0, 75_000.0], dtype=pl.Float64),
                # risk_weight deliberately absent
            }
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — no OUT001/OUT002 errors (bounds rely on risk_weight)
        rw_error_codes = {e.code for e in errors if e.code in ("OUT001", "OUT002")}
        assert rw_error_codes == set()

    @pytest.mark.parametrize(
        "rw,expected_violation",
        [
            (12.5, False),  # exact boundary — not above cap, no error
            (12.500001, True),  # infinitesimally above — error
            (0.0, False),  # exact zero — not negative, no error
            (-1e-10, True),  # tiny negative — error
        ],
    )
    def test_validate_aggregated_bundle_boundary_values(self, rw: float, expected_violation: bool):
        """Boundary values for risk_weight are handled with strict inequality."""
        # Arrange
        results = _make_results_lf(
            exposure_references=["B001"],
            risk_weights=[rw],
            rwa_finals=[100_000.0],
            ead_finals=[1_000_000.0],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert
        rw_codes = {e.code for e in errors if e.code in ("OUT001", "OUT002")}
        if expected_violation:
            assert len(rw_codes) == 1, f"Expected 1 RW violation error for rw={rw}, got {rw_codes}"
        else:
            assert rw_codes == set(), f"Expected no RW violation for rw={rw}, got {rw_codes}"
