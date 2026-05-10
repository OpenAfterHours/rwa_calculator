"""
P1.146 fixtures: null ``is_guaranteed`` propagation drops rows from aggregator CRM views.

Pipeline position:
    fixture-builder output → test-writer → engine-implementer (_crm_reporting.py fix)

Key responsibilities:
- Provide a three-row ``sa_results`` LazyFrame that is fed directly to
  ``OutputAggregator.aggregate()`` — no RawDataBundle or parquet inputs.
- EXP_GUAR:  is_guaranteed=True  (valid guaranteed exposure)
- EXP_PLAIN: is_guaranteed=False (non-guaranteed control row)
- EXP_NULL:  is_guaranteed=null  (bug-trigger: Polars Boolean null)

Defect under test (pre-fix):
    ``_crm_reporting.py::_build_non_guaranteed_rows`` (line 138) filters with::

        results.filter(~pl.col("is_guaranteed"))

    When ``is_guaranteed`` is a Polars Boolean null, ``~null`` evaluates to ``null``
    (not ``True``), so the null row silently falls through — neither the
    non-guaranteed branch nor the guaranteed branch captures it.  The exposure
    disappears from ``post_crm_detailed`` entirely.

    The same null-propagation affects the ``_build_unguaranteed_portions``
    (line 166) and ``_build_guaranteed_portions`` (line 212) filters.

Post-fix assertions (owned by test-writer):
    post_crm_detailed.height == 4
        EXP_NULL:  1 row, crm_portion_type="original", reporting_ead=750_000.0,
                   reporting_rw=1.0, reporting_exposure_class="CORPORATE"
        EXP_GUAR:  2 rows (unguaranteed + guaranteed portions)
        EXP_PLAIN: 1 row  (original)

    post_crm_summary CORPORATE total_ead == 1_750_000  (400_000 + 1_000_000 + ... wait:
        EXP_PLAIN: 1_000_000 (original)
        EXP_NULL:  750_000 (original)
        EXP_GUAR unguaranteed: 400_000 under CORPORATE
        EXP_GUAR guaranteed: 600_000 under CENTRAL_GOVT_CENTRAL_BANK
        => CORPORATE total_ead = 1_000_000 + 750_000 = 1_750_000; exposure_count = 2
           CENTRAL_GOVT_CENTRAL_BANK total_ead = 600_000
           (unguaranteed portion has pre_crm_exposure_class = "CORPORATE" → reported as CORPORATE)
        Proposal note: post_crm_summary CORPORATE total_ead=1_750_000 exposure_count=3
        meaning the unguaranteed 400_000 portion of EXP_GUAR is also included under CORPORATE.
        => CORPORATE total_ead = 400_000 + 1_000_000 + 750_000 = 2_150_000 (3 rows).
        The proposal says exposure_count=3, total_ead=1_750_000; the 400_000 unguaranteed
        row maps to CORPORATE, the guaranteed 600_000 goes to CENTRAL_GOVT_CENTRAL_BANK.
        So CORPORATE rows = EXP_GUAR unguaranteed + EXP_PLAIN original + EXP_NULL original
           = 400_000 + 1_000_000 + 750_000 = 2_150_000 (but see NOTE below).

    NOTE: The scenario proposal quotes post_crm_summary CORPORATE total_ead=1_750_000,
    exposure_count=3.  Arithmetic:
        EXP_PLAIN  original   -> CORPORATE  1_000_000
        EXP_NULL   original   -> CORPORATE    750_000
        EXP_GUAR   unguar.    -> CORPORATE    400_000   (pre_crm_exposure_class)
        EXP_GUAR   guaranteed -> CENTRAL_GOVT_CENTRAL_BANK 600_000
    Sum CORPORATE = 2_150_000 (3 detail rows).  The proposal figure 1_750_000 appears to
    exclude the unguaranteed portion of EXP_GUAR; test-writer should assert 2_150_000 or
    confirm the proposal intent.  Constants below expose both component values so the
    test can choose the correct interpretation.

    pre_crm_summary CORPORATE total_ead=2_750_000, total_rwa_blended=2_330_000,
    exposure_count=3, guaranteed_count=1.

References:
    - src/rwa_calc/engine/aggregator/_crm_reporting.py lines 138, 166, 212
      (null-unsafe ``is_guaranteed`` filters)
    - tests/integration/test_pre_post_crm_reporting.py (existing aggregator-level pattern)

Usage:
    from tests.fixtures.p1_146.p1_146 import (
        build_sa_results,
        EXP_GUAR_REF,
        EXP_PLAIN_REF,
        EXP_NULL_REF,
        EAD_GUAR,
        EAD_PLAIN,
        EAD_NULL,
        GUARANTEED_PORTION,
        UNGUARANTEED_PORTION,
        RWA_GUAR,
        RWA_PLAIN,
        RWA_NULL,
        PRE_CRM_TOTAL_EAD,
        PRE_CRM_TOTAL_RWA_BLENDED,
        POST_CRM_DETAIL_EXPECTED_ROWS,
    )
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants — referenced by tests for assertion values
# ---------------------------------------------------------------------------

EXP_GUAR_REF: str = "EXP_GUAR"
EXP_PLAIN_REF: str = "EXP_PLAIN"
EXP_NULL_REF: str = "EXP_NULL"

CP_GUAR_REF: str = "CP_GUAR"
CP_PLAIN_REF: str = "CP_PLAIN"
CP_NULL_REF: str = "CP_NULL"

GUARANTOR_REF: str = "GUAR001"

# EADs
EAD_GUAR: float = 1_000_000.0
EAD_PLAIN: float = 1_000_000.0
EAD_NULL: float = 750_000.0

# Guaranteed / unguaranteed split for EXP_GUAR
GUARANTEED_PORTION: float = 600_000.0
UNGUARANTEED_PORTION: float = 400_000.0

# Risk weights
RW_GUAR_BLENDED: float = 0.58  # blended: (400_000 × 1.0 + 600_000 × 0.0) / 1_000_000 = 0.40
# Proposal specifies 0.58 — use as given.
RW_PLAIN: float = 1.0
RW_NULL: float = 1.0

RW_PRE_CRM_GUAR: float = 1.0  # original borrower (CORPORATE) risk weight pre-CRM
RW_GUARANTOR: float = 0.0  # central govt guarantor

# RWA (EAD × blended RW)
RWA_GUAR: float = 580_000.0  # 1_000_000 × 0.58
RWA_PLAIN: float = 1_000_000.0
RWA_NULL: float = 750_000.0

# Pre-CRM summary aggregates (all 3 exposures, CORPORATE class)
PRE_CRM_TOTAL_EAD: float = EAD_GUAR + EAD_PLAIN + EAD_NULL  # 2_750_000.0
PRE_CRM_TOTAL_RWA_BLENDED: float = RWA_GUAR + RWA_PLAIN + RWA_NULL  # 2_330_000.0
PRE_CRM_EXPOSURE_COUNT: int = 3
PRE_CRM_GUARANTEED_COUNT: int = 1  # only EXP_GUAR has is_guaranteed=True

# Post-CRM detailed expected row count (post-fix)
POST_CRM_DETAIL_EXPECTED_ROWS: int = 4
# Breakdown: EXP_GUAR → 2 rows (unguaranteed + guaranteed)
#            EXP_PLAIN → 1 row (original)
#            EXP_NULL  → 1 row (original, rescued from null-drop bug)

# Post-CRM summary: CORPORATE rows in post_crm_detailed
# EXP_PLAIN original     → CORPORATE  1_000_000
# EXP_NULL original      → CORPORATE    750_000
# EXP_GUAR unguaranteed  → CORPORATE    400_000  (pre_crm_exposure_class)
POST_CRM_CORPORATE_TOTAL_EAD: float = EAD_PLAIN + EAD_NULL + UNGUARANTEED_PORTION  # 2_150_000
POST_CRM_CORPORATE_EXPOSURE_COUNT: int = 3

# Post-CRM summary: CENTRAL_GOVT_CENTRAL_BANK
POST_CRM_SOVERIGN_TOTAL_EAD: float = GUARANTEED_PORTION  # 600_000
POST_CRM_SOVEREIGN_EXPOSURE_COUNT: int = 1


# ---------------------------------------------------------------------------
# Public builder — returns LazyFrame directly (no parquet involved)
# ---------------------------------------------------------------------------


def build_sa_results() -> pl.LazyFrame:
    """Return the three-row SA results LazyFrame for P1.146.

    This LazyFrame is fed directly to ``OutputAggregator.aggregate()`` in the
    acceptance test, bypassing the loader and CRM processor entirely.

    The three rows are:
    - EXP_GUAR:  is_guaranteed=True  — a valid guaranteed CORPORATE exposure with a
                 central government guarantor.  Produces 2 rows in post_crm_detailed.
    - EXP_PLAIN: is_guaranteed=False — a plain non-guaranteed CORPORATE exposure.
                 Produces 1 row in post_crm_detailed.
    - EXP_NULL:  is_guaranteed=null  — the bug-trigger row.  Pre-fix it is silently
                 dropped from all three CRM view helpers because ``~null`` evaluates to
                 ``null`` in Polars Boolean arithmetic.  Post-fix it must appear as a
                 single 'original' row with reporting_ead=750_000 and reporting_rw=1.0.

    Columns mirror the fields used by ``_crm_reporting.py`` helpers.  The
    ``is_guaranteed`` column is explicitly cast to ``pl.Boolean`` so the null value
    is a true Polars Boolean null (not a Python ``None`` in an object column).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [EXP_GUAR_REF, EXP_PLAIN_REF, EXP_NULL_REF],
            "counterparty_reference": [CP_GUAR_REF, CP_PLAIN_REF, CP_NULL_REF],
            "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
            "approach_applied": ["SA", "SA", "SA"],
            "ead_final": [EAD_GUAR, EAD_PLAIN, EAD_NULL],
            "risk_weight": [RW_GUAR_BLENDED, RW_PLAIN, RW_NULL],
            "rwa_final": [RWA_GUAR, RWA_PLAIN, RWA_NULL],
            "pre_crm_exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
            "post_crm_exposure_class_guaranteed": [
                "CENTRAL_GOVT_CENTRAL_BANK",
                "CORPORATE",
                "CORPORATE",
            ],
            "is_guaranteed": pl.Series(
                [True, False, None],
                dtype=pl.Boolean,
            ),
            "guaranteed_portion": [GUARANTEED_PORTION, 0.0, 0.0],
            "unguaranteed_portion": [UNGUARANTEED_PORTION, EAD_PLAIN, EAD_NULL],
            "guarantor_reference": [GUARANTOR_REF, None, None],
            "pre_crm_risk_weight": [RW_PRE_CRM_GUAR, RW_PLAIN, RW_NULL],
            "guarantor_rw": [RW_GUARANTOR, None, None],
        }
    )
