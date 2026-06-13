"""
Aggregator constants and empty-frame schemas.

Internal module — not part of the public API.

References:
- CRR Art. 62(d): T2 credit cap (0.6% of IRB RWA)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

# Canonical IRB approach identifiers — union of ApproachType enum values and
# aggregator fallback labels. Used for EL summary and other IRB-specific logic.
IRB_APPROACHES: frozenset[str] = frozenset(
    {
        "foundation_irb",
        "advanced_irb",  # ApproachType enum values
        "FIRB",
        "AIRB",
        "IRB",  # Aggregator fallback labels
    }
)

# Floor-eligible approaches — IRB + slotting. The output floor compares
# "modelled" RWA (U-TREA) against SA-equivalent (S-TREA) at portfolio level.
# Slotting (Art. 153(5)) is an IRB-chapter sub-approach and is included per
# PRA PS1/26 Art. 92 para 2A which references all of Part Three, Title II.
FLOOR_ELIGIBLE_APPROACHES: frozenset[str] = IRB_APPROACHES | frozenset(
    {
        "slotting",  # ApproachType.SLOTTING.value
        "SLOTTING",  # Defensive: test fixtures may use uppercase
    }
)

# Standardised Approach (SA) approach identifiers — the ApproachType.SA enum
# value used by aggregator outputs.  Used by the portfolio-level summary to
# compute total SA RWA.
SA_APPROACHES: frozenset[str] = frozenset(
    {
        "standardised",  # ApproachType.SA.value
    }
)

# Equity approach identifiers — equity exposures are tagged with the
# ApproachType.EQUITY enum value by the equity-prep stage.
EQUITY_APPROACHES: frozenset[str] = frozenset(
    {
        "equity",  # ApproachType.EQUITY.value
    }
)

# T2 credit cap rate per CRR Art. 62(d): 0.6% of IRB credit-risk RWA.
T2_CREDIT_CAP_RATE = 0.006

# =============================================================================
# Empty-frame schemas
# =============================================================================

RESULT_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "approach_applied": pl.String,
    "exposure_class": pl.String,
    "ead_final": pl.Float64,
    "risk_weight": pl.Float64,
    "rwa_final": pl.Float64,
}

FLOOR_IMPACT_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "approach_applied": pl.String,
    "exposure_class": pl.String,
    "rwa_pre_floor": pl.Float64,
    "floor_rwa": pl.Float64,
    "is_floor_binding": pl.Boolean,
    "floor_impact_rwa": pl.Float64,
    "rwa_post_floor": pl.Float64,
    "output_floor_pct": pl.Float64,
}

POST_CRM_DETAILED_SCHEMA: dict[str, PolarsDataType] = {
    "reporting_counterparty": pl.String,
    "reporting_exposure_class": pl.String,
    "reporting_ead": pl.Float64,
    "reporting_rw": pl.Float64,
    "reporting_approach": pl.String,
    "crm_portion_type": pl.String,
}

POST_CRM_SUMMARY_SCHEMA: dict[str, PolarsDataType] = {
    "reporting_exposure_class": pl.String,
    "total_ead": pl.Float64,
    "total_rwa": pl.Float64,
    "exposure_count": pl.UInt32,
}

PRE_CRM_SUMMARY_SCHEMA: dict[str, PolarsDataType] = {
    "pre_crm_exposure_class": pl.String,
    "total_ead": pl.Float64,
    "total_rwa_blended": pl.Float64,
    "exposure_count": pl.UInt32,
}

SUPPORTING_FACTOR_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "supporting_factor": pl.Float64,
    "rwa_pre_factor": pl.Float64,
    "rwa_post_factor": pl.Float64,
    "supporting_factor_impact": pl.Float64,
    "supporting_factor_applied": pl.Boolean,
}
