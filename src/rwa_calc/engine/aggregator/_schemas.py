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

# CCR-routed SA approach tag. Counterparty-credit-risk exposures (synthetic
# netting-set rows) are risk-weighted via the Standardised Approach but, unlike
# ordinary SA exposures, MUST enter the output-floor S-TREA / U-TREA numerators
# (PRA PS1/26 Art. 92(3A): CCR exposures are NOT on the S-TREA exclusion list).
# Two families carry this tag, both set by the calculator stage:
#   - SA-CCR OTC derivatives (risk_type == "CCR_DERIVATIVE"), and
#   - FCCM SFTs (risk_type == "CCR_SFT").
# The label is method-neutral ("standardised, CCR-routed, floored") and the
# single ``approach_applied`` discriminator routes both into
# FLOOR_ELIGIBLE_APPROACHES while keeping them out of SA_APPROACHES — the RWA
# moves into the floor buckets rather than being double-counted in the
# plain-SA total.
SA_CCR_APPROACH: str = "standardised_ccr"

# Floor-eligible approaches — IRB + slotting + CCR-via-SA. The output floor
# compares "modelled" RWA (U-TREA) against SA-equivalent (S-TREA) at portfolio
# level. Slotting (Art. 153(5)) is an IRB-chapter sub-approach and is included
# per PRA PS1/26 Art. 92 para 2A which references all of Part Three, Title II.
# CCR exposures (SA-CCR derivatives + FCCM SFTs) are included per PS1/26
# Art. 92(3A) (not on the S-TREA exclusion list).
FLOOR_ELIGIBLE_APPROACHES: frozenset[str] = IRB_APPROACHES | frozenset(
    {
        "slotting",  # ApproachType.SLOTTING.value
        "SLOTTING",  # Defensive: test fixtures may use uppercase
        SA_CCR_APPROACH,  # CCR-via-SA rows (derivatives + SFTs) — PS1/26 Art. 92(3A)
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

# Mirrors SUPPORTING_FACTOR_IMPACT_EDGE (contracts/edges.py) column-for-column so
# the empty-frame fallback conforms cleanly if it ever fires. The populated path
# in _supporting_factors.py always emits all ten (col_or_default injects the four
# optional-source columns), so this fallback is dead today — but keeping it
# edge-shaped means a strict seal of the empty frame would not raise.
SUPPORTING_FACTOR_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "exposure_class": pl.String,
    "is_sme": pl.Boolean,
    "is_infrastructure": pl.Boolean,
    "ead_final": pl.Float64,
    "supporting_factor": pl.Float64,
    "rwa_pre_factor": pl.Float64,
    "rwa_post_factor": pl.Float64,
    "supporting_factor_impact": pl.Float64,
    "supporting_factor_applied": pl.Boolean,
}
