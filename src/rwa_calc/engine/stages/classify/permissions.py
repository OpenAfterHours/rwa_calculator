"""
Model-permission resolution for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    (optional — only when ``model_permissions`` is supplied) and by
    ``approach`` (permission expressions for the decision ladder).

Key responsibilities:
- Join exposures with ``model_permissions`` and resolve per-row permission
  flags (``resolve_model_permissions``): model_id match, exposure-class /
  geography / book-code filters, SA-precedence (PPU carve-out), and the
  ``_model_permission_diagnostic`` scratch column.
- Build the five permission expressions consumed by the approach ladder
  (``build_permission_exprs``) from model-level / IRB-mode / org-wide
  sources.
- Roll the diagnostic column up into CLS006 warnings
  (``emit_model_permission_diagnostics`` — eager, post-materialise).

References:
- CRR Art. 143: permission to use the IRB approach
- CRR Art. 148: sequential implementation (roll-out) across classes
- CRR Art. 150: permanent partial use (PPU) — SA-precedence carve-out
- CRR Art. 147(3)-(4): RGLA / PSE IRB-class keying for permission lookup
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_MODEL_PERMISSION_UNMATCHED,
    classification_warning,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


# =========================================================================
# Model-level permission resolution (optional)
# =========================================================================


@cites("CRR Art. 143")
@cites("CRR Art. 148")
@cites("CRR Art. 150")
def resolve_model_permissions(
    exposures: pl.LazyFrame,
    model_permissions: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Join exposures with model_permissions to produce per-row permission flags.

    model_id originates on internal ratings and is propagated to exposures by
    the rating inheritance pipeline. This method resolves which IRB approach each
    exposure is permitted to use based on:
    - model_id match (rating's model_id must exist in model_permissions)
    - exposure_class match
    - Geography filter: country_codes is null OR cp_country_code is in the list
    - Book code exclusion: excluded_book_codes is null OR book_code NOT in the list

    Priority: AIRB > FIRB. If a model has both, AIRB wins for exposures that
    also have modelled LGD; otherwise FIRB is used if the exposure has internal_pd.

    Sets: model_airb_permitted (bool), model_firb_permitted (bool),
          model_slotting_permitted (bool)

    Exposures without a model_id get all flags as False (→ SA fallback).

    Synthetic CCR rows reach this stage with ``model_id = null`` because the
    rating-inheritance attach that renames ``internal_model_id`` -> ``model_id``
    only runs over hierarchy-resolved lending rows. When the counterparty
    lookup carried an ``internal_model_id`` it was surfaced as
    ``cp_internal_model_id`` by ``_add_counterparty_attributes``; coalescing it
    into ``model_id`` here lets an IRB-permissioned counterparty's CCR
    derivative exposure resolve a model permission instead of falling back to
    SA. The coalesce is a no-op for lending rows whose ``model_id`` is already
    populated (CRR Art. 153(1); CRR Art. 162(2)(b)).
    """
    # Recover model_id for rows that carry only the counterparty's resolved
    # internal_model_id (synthetic CCR rows). No-op when model_id is already
    # set. Both columns are contract-guaranteed: model_id on hierarchy_exit,
    # cp_internal_model_id via the sealed counterparty lookup join.
    exposures = exposures.with_columns(
        pl.coalesce(pl.col("model_id"), pl.col("cp_internal_model_id")).alias("model_id")
    )

    # The model_permissions frame is sealed at the loader edge
    # (raw_model_permissions), so the optional columns country_codes /
    # excluded_book_codes / ppu_reason are always present — absent input
    # columns arrive as typed nulls (all geographies / no exclusions /
    # no PPU labelling).

    # Join exposures with model_permissions on model_id
    # Each exposure may match multiple permission rows (AIRB + FIRB for same model)
    joined = exposures.join(
        model_permissions.select(
            pl.col("model_id").alias("mp_model_id"),
            pl.col("exposure_class").alias("mp_exposure_class"),
            pl.col("approach").alias("mp_approach"),
            pl.col("country_codes").alias("mp_country_codes"),
            pl.col("excluded_book_codes").alias("mp_excluded_book_codes"),
            pl.col("ppu_reason").alias("mp_ppu_reason"),
        ),
        left_on="model_id",
        right_on="mp_model_id",
        how="left",
    )

    # Track whether the join produced any matching permission row for this
    # exposure (before filters are applied). Used downstream to distinguish
    # "model_id did not match any permission row" from "model_id matched
    # but filters rejected every row", so the diagnostic column can point
    # the user at the right remediation. Note: Polars drops the right
    # join key (mp_model_id) when left_on != right_on, so we probe via
    # mp_exposure_class which stays in the joined frame.
    joined = joined.with_columns(pl.col("mp_exposure_class").is_not_null().alias("_mp_row_joined"))

    # Apply filters: exposure_class match, geography, book code exclusion
    # A permission row is valid when:
    # 1. exposure_class_irb matches (use IRB class so rgla/pse entities typed
    #    as institution / sovereign match model permissions keyed on
    #    INSTITUTION / CGCB per CRR Art. 147(3)-(4))
    # 2. geography passes (country_codes is null OR cp_country_code in list)
    # 3. book code not excluded (excluded_book_codes is null OR book_code NOT in list)
    exposure_class_match = pl.col("exposure_class_irb") == pl.col("mp_exposure_class")

    # Null-safe filter logic (P1.114):
    # Polars `str.contains(<expr>)` propagates null when the needle is null,
    # producing kleene-3-valued OR results (null | null = null) that silently
    # block permission grants. Guard each branch:
    #   - geo: a null cp_country_code cannot prove scope-in, so it fails the
    #     filter when mp_country_codes is non-null (conservative).
    #   - book: a null book_code cannot be in any exclusion list, so the
    #     contains() result is coerced to False before negation.
    geo_passes = pl.col("mp_country_codes").is_null() | (
        pl.col("cp_country_code").is_not_null()
        & pl.col("mp_country_codes").str.contains(pl.col("cp_country_code"))
    )

    book_not_excluded = pl.col("mp_excluded_book_codes").is_null() | ~(
        pl.col("mp_excluded_book_codes").str.contains(pl.col("book_code")).fill_null(False)
    )

    permission_valid = exposure_class_match & geo_passes & book_not_excluded

    # Compute per-row permission flags
    airb_permitted = (permission_valid & (pl.col("mp_approach") == ApproachType.AIRB.value)).alias(
        "_airb_match"
    )
    firb_permitted = (permission_valid & (pl.col("mp_approach") == ApproachType.FIRB.value)).alias(
        "_firb_match"
    )
    slotting_permitted = (
        permission_valid & (pl.col("mp_approach") == ApproachType.SLOTTING.value)
    ).alias("_slotting_match")

    # SA-precedence (P1.145, CRR Art. 150(1) PPU carve-out): when the same
    # (model_id, exposure_class) yields both an IRB permission row and a
    # standardised row, the standardised row wins. AIRB-wins via .max()
    # would silently expand IRB scope beyond the firm's permission.
    sa_block = (permission_valid & (pl.col("mp_approach") == ApproachType.SA.value)).alias(
        "_sa_block_match"
    )

    # CRR Art. 150(1) PPU / Art. 148 roll-out provenance: capture the ppu_reason
    # from the surviving SA-precedence row only. Null on non-SA rows so the
    # max().over() roll-up below picks up the SA row's label (and stays null
    # when no SA-routing permission applied).
    sa_ppu_reason = (
        pl.when(sa_block).then(pl.col("mp_ppu_reason")).otherwise(None).alias("_sa_ppu_reason")
    )

    # Add match flags then aggregate: group by all original columns,
    # take max of the match flags (any valid AIRB/FIRB/slotting permission → True),
    # then AND-NOT the SA block to apply the SA-precedence rule.
    result = joined.with_columns(
        airb_permitted, firb_permitted, slotting_permitted, sa_block, sa_ppu_reason
    )

    # Aggregate back to one row per exposure using .over() to avoid group_by.
    # SA-precedence override is applied AFTER the .max() roll-up so any SA
    # row with permission_valid=True flips all IRB flags to False.
    result = result.with_columns(
        pl.col("_sa_block_match").max().over("exposure_reference").alias("_sa_block"),
        pl.col("_mp_row_joined").max().over("exposure_reference").alias("_mp_joined_any"),
        pl.col("_sa_ppu_reason").max().over("exposure_reference").alias("ppu_reason"),
    ).with_columns(
        (pl.col("_airb_match").max().over("exposure_reference") & ~pl.col("_sa_block")).alias(
            "model_airb_permitted"
        ),
        (pl.col("_firb_match").max().over("exposure_reference") & ~pl.col("_sa_block")).alias(
            "model_firb_permitted"
        ),
        (pl.col("_slotting_match").max().over("exposure_reference") & ~pl.col("_sa_block")).alias(
            "model_slotting_permitted"
        ),
    )

    # Diagnostic column: tag WHY a row did not get an IRB permission match.
    # Three causes with distinct remediations:
    #   null_model_id       → rating.model_id is null (fix ratings table)
    #   unmatched_model_id  → model_id absent from model_permissions (stale ref)
    #   filter_rejected     → matched but filtered by class/geo/book scope
    # Null when the exposure DID get a match (happy path).
    has_any_match = (
        pl.col("model_airb_permitted")
        | pl.col("model_firb_permitted")
        | pl.col("model_slotting_permitted")
    )
    result = result.with_columns(
        pl.when(has_any_match)
        .then(pl.lit(None, dtype=pl.String))
        .when(pl.col("model_id").is_null())
        .then(pl.lit("null_model_id"))
        .when(~pl.col("_mp_joined_any"))
        .then(pl.lit("unmatched_model_id"))
        .otherwise(pl.lit("filter_rejected"))
        .alias("_model_permission_diagnostic")
    )

    # Drop the join columns and keep one row per exposure deterministically
    # (P1.145, Step 3): sort by a total-order key so that whichever row of
    # the duplicate-permission join survives `unique(keep="first")` does
    # not depend on the physical row order of the input parquet. The
    # priority key keeps the most-informative diagnostic on the surviving
    # row (null > filter_rejected > unmatched_model_id > null_model_id).
    diagnostic_priority = (
        pl.when(pl.col("_model_permission_diagnostic").is_null())
        .then(pl.lit(0))
        .when(pl.col("_model_permission_diagnostic") == "filter_rejected")
        .then(pl.lit(1))
        .when(pl.col("_model_permission_diagnostic") == "unmatched_model_id")
        .then(pl.lit(2))
        .otherwise(pl.lit(3))
        .alias("_diagnostic_priority")
    )
    result = (
        result.with_columns(diagnostic_priority)
        .sort(
            [
                "exposure_reference",
                "_diagnostic_priority",
                "mp_approach",
                "mp_country_codes",
                "mp_excluded_book_codes",
            ],
            nulls_last=True,
            maintain_order=True,
        )
        .unique(subset=["exposure_reference"], keep="first", maintain_order=True)
        .select(
            pl.exclude(
                "mp_exposure_class",
                "mp_approach",
                "mp_country_codes",
                "mp_excluded_book_codes",
                "mp_ppu_reason",
                "_sa_ppu_reason",
                "_airb_match",
                "_firb_match",
                "_slotting_match",
                "_sa_block_match",
                "_sa_block",
                "_mp_row_joined",
                "_mp_joined_any",
                "_diagnostic_priority",
            )
        )
    )

    return result


def emit_model_permission_diagnostics(
    classified: pl.LazyFrame,
) -> list[CalculationError]:
    """Emit CLS006 warnings for IRB-eligible exposures that failed model match.

    Reads ``_model_permission_diagnostic`` (added by
    ``resolve_model_permissions``) and rolls up the failure causes
    (``null_model_id`` / ``unmatched_model_id`` / ``filter_rejected``)
    into one warning per cause. The caller must drop the diagnostic
    column from the frame after this returns.

    This runs **after** the classifier's single materialise barrier so
    the underlying ``.collect()`` reads in-memory data rather than
    re-executing the upstream join plan. See ``classify()``.
    """
    diagnostic_counts = (
        classified.filter(pl.col("internal_pd").is_not_null())
        .filter(pl.col("_model_permission_diagnostic").is_not_null())
        .group_by("_model_permission_diagnostic")
        .agg(pl.len().alias("n"))
        .collect()
    )
    return [
        _build_model_permission_warning(row["_model_permission_diagnostic"], row["n"])
        for row in diagnostic_counts.iter_rows(named=True)
    ]


def build_permission_exprs(
    config: CalculationConfig,
    *,
    has_internal_rating: pl.Expr,
    has_modelled_lgd: pl.Expr,
    has_model_permissions: bool,
) -> tuple[pl.Expr, pl.Expr, pl.Expr, pl.Expr, pl.Expr]:
    """Build the five permission expressions consumed by the approach ladder.

    Returns ``(airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting)``.

    Three permission sources:
    - **Model-level** (``has_model_permissions=True``): per-row flags set
      by ``resolve_model_permissions``, already filtered by exposure_class,
      geography, and book code. AIRB additionally requires modelled LGD.
    - **IRB mode without model_permissions**: no exposure can be granted
      IRB — every flag is ``pl.lit(False)``, falling back to SA.
    - **Org-wide** (default): booleans pre-computed from
      ``config.irb_permissions``, lifted via ``pl.lit``.

    ``firb_clear_expr`` identifies rows whose LGD should be cleared (FIRB
    uses supervisory LGD). Under model-level permissions, this excludes
    rows that also qualify for AIRB.
    """
    if has_model_permissions:
        sl_airb = pl.col("model_airb_permitted")
        sl_slotting = pl.col("model_slotting_permitted")
        airb_expr = pl.col("model_airb_permitted") & has_internal_rating & has_modelled_lgd
        firb_expr = pl.col("model_firb_permitted") & has_internal_rating
        firb_clear_expr = (
            pl.col("model_firb_permitted")
            & has_internal_rating
            & ~(pl.col("model_airb_permitted") & has_modelled_lgd)
        )
        return airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting

    if config.permission_mode == PermissionMode.IRB:
        # IRB mode requires model_permissions to gate per-model approval.
        # Without it, no exposure can be granted IRB — fall back to SA.
        false_expr = pl.lit(False)
        return false_expr, false_expr, false_expr, false_expr, false_expr

    # Org-wide SL permissions from config
    sl_airb = pl.lit(
        config.irb_permissions.is_permitted(
            ExposureClass.SPECIALISED_LENDING,
            ApproachType.AIRB,
        )
    )
    sl_slotting = pl.lit(
        config.irb_permissions.is_permitted(
            ExposureClass.SPECIALISED_LENDING,
            ApproachType.SLOTTING,
        )
    )
    airb_expr, firb_expr, firb_clear_expr = _build_orgwide_permission_exprs(
        config, has_internal_rating
    )
    return airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting


def _build_orgwide_permission_exprs(
    config: CalculationConfig,
    has_internal_rating: pl.Expr,
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """Build org-wide permission expressions (backward compat when no model_permissions).

    Returns (airb_permitted_expr, firb_permitted_expr, firb_clear_expr).
    """
    perms = config.irb_permissions.permissions
    airb_classes = [ec.value for ec, approaches in perms.items() if ApproachType.AIRB in approaches]
    firb_classes = [ec.value for ec, approaches in perms.items() if ApproachType.FIRB in approaches]
    firb_only_classes = [
        ec.value
        for ec, approaches in perms.items()
        if ApproachType.FIRB in approaches and ApproachType.AIRB not in approaches
    ]

    # Key IRB permission lookup on exposure_class_irb (not exposure_class) so
    # rgla_institution / pse_institution route via the INSTITUTION IRB class
    # (CRR Art. 147(4)(b)) and rgla_sovereign / pse_sovereign via CGCB
    # (CRR Art. 147(3)). exposure_class is the SA class and would otherwise
    # exclude these rows from IRB permission entries keyed on INSTITUTION / CGCB.
    airb_expr = pl.col("exposure_class_irb").is_in(airb_classes) & has_internal_rating
    firb_expr = pl.col("exposure_class_irb").is_in(firb_classes) & has_internal_rating
    firb_clear = pl.col("exposure_class_irb").is_in(firb_only_classes) & has_internal_rating

    return airb_expr, firb_expr, firb_clear


def _build_model_permission_warning(cause: str, n: int) -> CalculationError:
    """Build a CLS006 classification warning for a model permission miss.

    Three distinct causes, each with a specific remediation:
    - ``null_model_id``: ratings table lacks model_id → fix the ratings input
    - ``unmatched_model_id``: stale reference → fix the model_permissions table
    - ``filter_rejected``: scope mismatch → check exposure_class / country_codes
      / excluded_book_codes filters on the permission row
    """
    messages = {
        "null_model_id": (
            f"{n} exposure(s) with internal ratings were routed to Standardised "
            f"Approach because their rating has no model_id. Check the ratings "
            f"table (model_id column) and rating inheritance."
        ),
        "unmatched_model_id": (
            f"{n} exposure(s) with internal ratings were routed to Standardised "
            f"Approach because their model_id does not appear in the "
            f"model_permissions table. Check for stale model references."
        ),
        "filter_rejected": (
            f"{n} exposure(s) with internal ratings were routed to Standardised "
            f"Approach because all matching model_permissions rows were filtered "
            f"out by exposure_class / country_codes / excluded_book_codes. "
            f"Check permission scope."
        ),
    }
    return classification_warning(
        code=ERROR_MODEL_PERMISSION_UNMATCHED,
        message=messages[cause],
        regulatory_reference="PRA PS1/26 / CRR Art. 143",
    )
