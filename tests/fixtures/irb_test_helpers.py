"""
Helpers for creating IRB test data with model permissions.

Under PermissionMode.IRB, approach routing requires:
1. Internal ratings must have a model_id
2. A model_permissions table must grant the approach for that model_id + exposure class

These helpers enrich existing test fixtures with model_ids and create matching
model_permissions, enabling IRB pipeline testing without modifying parquet fixtures.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.domain.enums import ApproachType, ExposureClass

# A single model_id used for all enriched test ratings
_TEST_MODEL_ID = "TEST_FULL_IRB"

# All exposure classes that can receive IRB approaches
_IRB_EXPOSURE_CLASSES = [
    ExposureClass.CENTRAL_GOVT_CENTRAL_BANK,
    ExposureClass.INSTITUTION,
    ExposureClass.CORPORATE,
    ExposureClass.CORPORATE_SME,
    ExposureClass.RETAIL_MORTGAGE,
    ExposureClass.RETAIL_QRRE,
    ExposureClass.RETAIL_OTHER,
    ExposureClass.SPECIALISED_LENDING,
]


def create_full_irb_model_permissions() -> pl.LazyFrame:
    """Create model_permissions granting full IRB for all exposure classes.

    Returns a LazyFrame with FIRB, AIRB, and slotting permissions for
    a single test model_id covering all IRB-eligible exposure classes.
    """
    rows: list[dict] = []
    for ec in _IRB_EXPOSURE_CLASSES:
        # Grant FIRB (except retail — FIRB not permitted)
        if ec not in (
            ExposureClass.RETAIL_MORTGAGE,
            ExposureClass.RETAIL_QRRE,
            ExposureClass.RETAIL_OTHER,
        ):
            rows.append({
                "model_id": _TEST_MODEL_ID,
                "exposure_class": ec.value,
                "approach": ApproachType.FIRB.value,
            })
        # Grant AIRB
        rows.append({
            "model_id": _TEST_MODEL_ID,
            "exposure_class": ec.value,
            "approach": ApproachType.AIRB.value,
        })
    # Grant slotting for specialised lending
    rows.append({
        "model_id": _TEST_MODEL_ID,
        "exposure_class": ExposureClass.SPECIALISED_LENDING.value,
        "approach": ApproachType.SLOTTING.value,
    })

    return pl.LazyFrame(rows).cast({
        "model_id": pl.String,
        "exposure_class": pl.String,
        "approach": pl.String,
    })


def create_firb_only_model_permissions() -> pl.LazyFrame:
    """Create model_permissions granting FIRB only (no AIRB) for all eligible classes.

    Used for FIRB-specific acceptance tests where AIRB should NOT be available.
    Retail classes get no permissions (FIRB not permitted for retail).
    """
    rows: list[dict] = []
    for ec in _IRB_EXPOSURE_CLASSES:
        if ec in (
            ExposureClass.RETAIL_MORTGAGE,
            ExposureClass.RETAIL_QRRE,
            ExposureClass.RETAIL_OTHER,
        ):
            continue  # FIRB not permitted for retail
        rows.append({
            "model_id": _TEST_MODEL_ID,
            "exposure_class": ec.value,
            "approach": ApproachType.FIRB.value,
        })
    # Slotting for specialised lending
    rows.append({
        "model_id": _TEST_MODEL_ID,
        "exposure_class": ExposureClass.SPECIALISED_LENDING.value,
        "approach": ApproachType.SLOTTING.value,
    })

    return pl.LazyFrame(rows).cast({
        "model_id": pl.String,
        "exposure_class": pl.String,
        "approach": pl.String,
    })


def create_slotting_only_model_permissions() -> pl.LazyFrame:
    """Create model_permissions granting slotting only for specialised lending.

    Used for slotting-specific acceptance tests.
    """
    rows = [{
        "model_id": _TEST_MODEL_ID,
        "exposure_class": ExposureClass.SPECIALISED_LENDING.value,
        "approach": ApproachType.SLOTTING.value,
    }]
    return pl.LazyFrame(rows).cast({
        "model_id": pl.String,
        "exposure_class": pl.String,
        "approach": pl.String,
    })


def enrich_ratings_with_model_id(ratings: pl.LazyFrame) -> pl.LazyFrame:
    """Add model_id to all internal ratings that lack one.

    Internal ratings (rating_type='internal') get the test model_id
    so they can be matched against model_permissions.
    """
    return ratings.with_columns(
        pl.when(
            (pl.col("rating_type") == "internal") & pl.col("model_id").is_null()
        )
        .then(pl.lit(_TEST_MODEL_ID))
        .otherwise(pl.col("model_id"))
        .alias("model_id")
    )
