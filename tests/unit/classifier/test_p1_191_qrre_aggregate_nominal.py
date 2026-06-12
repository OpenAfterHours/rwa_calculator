"""Unit tests for P1.191: QRRE per-individual aggregate nominal qualification.

Tests cover:
- Under CRR: two revolving facilities to one individual totalling GBP 100,000
  (> CRR limit GBP 87,320) must be declassified from QRRE to RETAIL_OTHER.
- Under Basel 3.1: same aggregate 100,000 > B31 limit GBP 90,000 → RETAIL_OTHER.
- Control obligor (single 50,000 facility, below both limits) stays RETAIL_QRRE.
- No CalculationError is raised (both QRRE columns present → CLS004 must not fire).

Anti-confound: under the current buggy per-row check, all three exposures classify as
RETAIL_QRRE because each facility_limit of 50,000 ≤ the per-row limit. The fix must
aggregate per counterparty_reference before comparing. Asserting EXP_A_UNDRAWN and
EXP_B_UNDRAWN == RETAIL_OTHER will therefore FAIL against the current (unpatched) engine.

References:
- CRR Art. 154(4)(c): QRRE; aggregate exposure to a single obligor ≤ EUR 100,000
- PRA PS1/26 Art. 147(5A)(c): QRRE sub-portfolio; largest per-individual aggregate
  nominal ≤ GBP 90,000
- engine/classifier.py:870-877: _combine_classifications is_qrre per-row defect
- tests/fixtures/p1_191/p1_191.py: fixture builder constants (limits, refs)
- tests/unit/test_classifier_qrre_warnings.py: analogous CLS004 pattern
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.hierarchy import HierarchyResolver

# =============================================================================
# Constants imported from the fixture builder (single source of truth)
# =============================================================================
from tests.fixtures.p1_191.p1_191 import (
    FAC_A,
    FAC_B,
    FAC_C,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# Exposure references after HierarchyResolver: committed, no-loan facilities
# become facility_undrawn rows with the suffix "_UNDRAWN".
_EXP_A = FAC_A + "_UNDRAWN"  # "EXP_A_UNDRAWN"
_EXP_B = FAC_B + "_UNDRAWN"  # "EXP_B_UNDRAWN"
_EXP_C = FAC_C + "_UNDRAWN"  # "EXP_C_UNDRAWN"

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_191"

# =============================================================================
# Module-level builders — shared across CRR and B31 test classes
# =============================================================================

_EMPTY_LOANS = pl.LazyFrame(
    schema={
        "loan_reference": pl.String,
        "product_type": pl.String,
        "book_code": pl.String,
        "counterparty_reference": pl.String,
        "value_date": pl.Date,
        "maturity_date": pl.Date,
        "currency": pl.String,
        "drawn_amount": pl.Float64,
        "lgd": pl.Float64,
        "seniority": pl.String,
        "risk_type": pl.String,
    }
)

_EMPTY_LENDING_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_counterparty_reference": pl.String,
        "child_counterparty_reference": pl.String,
    }
)

_EMPTY_FACILITY_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
)


def _build_raw_bundle() -> RawDataBundle:
    """Return the P1.191 RawDataBundle (parquet fixtures, no mapped loans)."""
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=_EMPTY_LOANS,
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=_EMPTY_FACILITY_MAPPINGS,
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


def _classify(config: CalculationConfig) -> pl.DataFrame:
    """Run HierarchyResolver → ExposureClassifier and return exposure_reference / exposure_class."""
    raw = _build_raw_bundle()
    resolved = HierarchyResolver().resolve(raw, config)
    result = ExposureClassifier().classify(resolved, config)
    return cast(
        pl.DataFrame,
        result.all_exposures.select("exposure_reference", "exposure_class").collect(),
    )


def _lookup(df: pl.DataFrame, ref: str) -> str:
    """Return the exposure_class string for the given exposure_reference."""
    row = df.filter(pl.col("exposure_reference") == ref)
    assert len(row) == 1, f"Expected 1 row for {ref!r}, got {len(row)}"
    return row["exposure_class"].item()


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2027, 1, 4))


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 4))


@pytest.fixture(scope="module")
def crr_classified(crr_config: CalculationConfig) -> pl.DataFrame:
    """Classify the P1.191 scenario under CRR (module-scoped for speed)."""
    return _classify(crr_config)


@pytest.fixture(scope="module")
def b31_classified(b31_config: CalculationConfig) -> pl.DataFrame:
    """Classify the P1.191 scenario under Basel 3.1 (module-scoped for speed)."""
    return _classify(b31_config)


# =============================================================================
# CRR: aggregate breach → RETAIL_OTHER; control → RETAIL_QRRE
# =============================================================================


class TestCRRQRREPerIndividualAggregateNominal:
    """CRR: per-individual aggregate nominal check declassifies breach obligor.

    QRRE limit under CRR = EUR 100,000 × 0.8732 = GBP 87,320.
    QRRE_AGG aggregate = EXP_A (50k) + EXP_B (50k) = 100,000 > 87,320 → NOT QRRE.
    QRRE_OK  aggregate = EXP_C (50k) = 50,000 ≤ 87,320 → QRRE.
    """

    def test_qrre_per_individual_aggregate_breach_declassifies_exp_a(
        self, crr_classified: pl.DataFrame
    ) -> None:
        """EXP_A belongs to QRRE_AGG whose aggregate 100k > CRR limit → RETAIL_OTHER."""
        # Arrange — crr_classified already computed

        # Act
        cls = _lookup(crr_classified, _EXP_A)

        # Assert — FAILS under buggy per-row engine (gives retail_qrre)
        assert cls == ExposureClass.RETAIL_OTHER.value, (
            f"EXP_A should be RETAIL_OTHER (aggregate 100k > CRR limit 87,320), got {cls!r}"
        )

    def test_qrre_per_individual_aggregate_breach_declassifies_exp_b(
        self, crr_classified: pl.DataFrame
    ) -> None:
        """EXP_B belongs to QRRE_AGG whose aggregate 100k > CRR limit → RETAIL_OTHER."""
        # Arrange — crr_classified already computed

        # Act
        cls = _lookup(crr_classified, _EXP_B)

        # Assert — FAILS under buggy per-row engine (gives retail_qrre)
        assert cls == ExposureClass.RETAIL_OTHER.value, (
            f"EXP_B should be RETAIL_OTHER (aggregate 100k > CRR limit 87,320), got {cls!r}"
        )

    def test_qrre_per_individual_aggregate_within_limit_stays_qrre(
        self, crr_classified: pl.DataFrame
    ) -> None:
        """EXP_C belongs to QRRE_OK whose aggregate 50k ≤ CRR limit → RETAIL_QRRE."""
        # Arrange — crr_classified already computed

        # Act
        cls = _lookup(crr_classified, _EXP_C)

        # Assert — control obligor must remain QRRE (passes under both buggy and fixed engine)
        assert cls == ExposureClass.RETAIL_QRRE.value, (
            f"EXP_C should be RETAIL_QRRE (aggregate 50k ≤ CRR limit 87,320), got {cls!r}"
        )


# =============================================================================
# Basel 3.1: same aggregate-breach logic with GBP 90,000 limit
# =============================================================================


class TestB31QRREPerIndividualAggregateNominal:
    """Basel 3.1: per-individual aggregate nominal check with GBP 90,000 limit.

    QRRE limit under B31 = GBP 90,000 (PRA PS1/26 Art. 147(5A)(c)).
    QRRE_AGG aggregate = 100,000 > 90,000 → NOT QRRE.
    QRRE_OK  aggregate = 50,000 ≤ 90,000 → QRRE.
    """

    def test_qrre_per_individual_aggregate_breach_declassifies_exp_a(
        self, b31_classified: pl.DataFrame
    ) -> None:
        """EXP_A belongs to QRRE_AGG whose aggregate 100k > B31 limit → RETAIL_OTHER."""
        # Arrange — b31_classified already computed

        # Act
        cls = _lookup(b31_classified, _EXP_A)

        # Assert — FAILS under buggy per-row engine (gives retail_qrre)
        assert cls == ExposureClass.RETAIL_OTHER.value, (
            f"EXP_A should be RETAIL_OTHER (aggregate 100k > B31 limit 90k), got {cls!r}"
        )

    def test_qrre_per_individual_aggregate_breach_declassifies_exp_b(
        self, b31_classified: pl.DataFrame
    ) -> None:
        """EXP_B belongs to QRRE_AGG whose aggregate 100k > B31 limit → RETAIL_OTHER."""
        # Arrange — b31_classified already computed

        # Act
        cls = _lookup(b31_classified, _EXP_B)

        # Assert — FAILS under buggy per-row engine (gives retail_qrre)
        assert cls == ExposureClass.RETAIL_OTHER.value, (
            f"EXP_B should be RETAIL_OTHER (aggregate 100k > B31 limit 90k), got {cls!r}"
        )

    def test_qrre_per_individual_aggregate_within_limit_stays_qrre(
        self, b31_classified: pl.DataFrame
    ) -> None:
        """EXP_C belongs to QRRE_OK whose aggregate 50k ≤ B31 limit → RETAIL_QRRE."""
        # Arrange — b31_classified already computed

        # Act
        cls = _lookup(b31_classified, _EXP_C)

        # Assert — control obligor must remain QRRE
        assert cls == ExposureClass.RETAIL_QRRE.value, (
            f"EXP_C should be RETAIL_QRRE (aggregate 50k ≤ B31 limit 90k), got {cls!r}"
        )


# =============================================================================
# No CLS004 error under either framework (both QRRE columns present)
# =============================================================================


class TestNoQRREColumnWarningFires:
    """CLS004 must NOT fire: both is_revolving and facility_limit are present."""

    def test_no_cls004_under_crr(self, crr_config: CalculationConfig) -> None:
        """Both QRRE columns present → no CLS004 warning under CRR."""
        # Arrange
        raw = _build_raw_bundle()
        resolved = HierarchyResolver().resolve(raw, crr_config)
        result = ExposureClassifier().classify(resolved, crr_config)

        # Act
        cls004_errors = [e for e in result.classification_errors if e.code == "CLS004"]

        # Assert
        assert cls004_errors == [], f"Unexpected CLS004 errors under CRR: {cls004_errors}"

    def test_no_cls004_under_b31(self, b31_config: CalculationConfig) -> None:
        """Both QRRE columns present → no CLS004 warning under Basel 3.1."""
        # Arrange
        raw = _build_raw_bundle()
        resolved = HierarchyResolver().resolve(raw, b31_config)
        result = ExposureClassifier().classify(resolved, b31_config)

        # Act
        cls004_errors = [e for e in result.classification_errors if e.code == "CLS004"]

        # Assert
        assert cls004_errors == [], f"Unexpected CLS004 errors under B31: {cls004_errors}"
