"""
Evidence of real-estate security for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (engine/classify) -> CRMProcessor
    Sub-module of the classify stage package. ``subtypes`` reads
    ``re_evidence_expr`` when it builds the mortgage class; ``classifier``
    calls ``withhold_unevidenced_re_class`` once the approach is known.

Key responsibilities:
- ``re_evidence_expr``: is there anything that shows the exposure is secured
  by immovable property — a linked property with a value at any level, or an
  LTV (supplied on the collateral or the loan row, or derived by the hierarchy
  stage from the property value)?
- ``withhold_unevidenced_re_class``: a Standardised-Approach exposure whose
  real-estate class came from a mortgage product label alone takes its
  counterparty's class instead (review CL-08). IRB rows keep their class: the
  IRB retail-mortgage class carries its own parameters (correlation, LGD
  floors), and re-classifying it is a different question; their
  Standardised-equivalent weight (the Basel 3.1 output floor) is held by the
  SA dispatchers' own LTV gate.

Why: the product label is not security. The PS1/26 glossary defines a real
estate exposure as "an ADC exposure or an exposure secured by a charge on
immovable property", and Art. 124A(1)(a)(i) requires a regulatory one to be
"secured by immovable property"; CRR Art. 125(1) reaches only "exposures fully
and completely secured by mortgages on residential property". A
``product_type`` of ``MORTGAGE`` with no property and no LTV took CRR 35% and
Basel 3.1 44.75% (an assumed 100% LTV) with no warning; it now takes the
counterparty-class weight and the run reports ``RE005``.

References:
- PS1/26 Glossary ("real estate exposure"), Art. 124, Art. 124A(1)(a)
- CRR Art. 124(1), Art. 125(1)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import ApproachType

logger = logging.getLogger(__name__)

#: Scratch column: the class a mortgage-labelled row would have without the
#: label, set only where the row has no evidence of security. Lives from
#: ``classify_exposure_subtypes`` to the classifier's exit seal, which strips it
#: after the RE005 count has read it.
RE_UNEVIDENCED_CLASS_COLUMN = "_re_unevidenced_class"


@cites("CRR Art. 125")
@cites("PS1/26, paragraph 124A")
def re_evidence_expr() -> pl.Expr:
    """True where something shows the exposure is secured by immovable property.

    The property aggregates and ``ltv`` are hierarchy_exit contract columns:
    ``property_collateral_value`` is the linked real-estate market value at the
    direct level or allocated from a facility / counterparty pledge,
    ``has_facility_property_collateral`` catches a pledge whose allocation to
    this row is zero (an undrawn commitment), and ``ltv`` is supplied or derived.
    """
    return (
        (pl.col("property_collateral_value") > 0.0)
        | (pl.col("has_facility_property_collateral") == True)  # noqa: E712
        | pl.col("ltv").is_not_null()
    )


@cites("CRR Art. 124")
@cites("PS1/26, paragraph 124")
def withhold_unevidenced_re_class(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Give a Standardised-Approach row with no evidence of security its non-mortgage class.

    Reads ``RE_UNEVIDENCED_CLASS_COLUMN`` (set by ``classify_exposure_subtypes``)
    and ``approach`` (set by ``assign_approach``), so it must run after both and
    before ``derive_exposure_subclass``. The scratch column is left in place for
    the RE005 count.
    """
    fallback = pl.col(RE_UNEVIDENCED_CLASS_COLUMN)
    is_standardised = pl.col("approach") == ApproachType.SA.value
    return exposures.with_columns(
        pl.when(is_standardised & fallback.is_not_null())
        .then(fallback)
        .otherwise(pl.col("exposure_class"))
        .alias("exposure_class")
    )


def re_evidence_count_exprs() -> dict[str, pl.Expr]:
    """Row counts behind the RE005 / RE006 warnings, for one shared collect.

    ``re005_standardised`` / ``re005_other``: mortgage-labelled rows with no
    evidence of security, by approach. ``re006``: rows whose LTV the hierarchy
    derived from the property value.
    """
    unevidenced = pl.col(RE_UNEVIDENCED_CLASS_COLUMN).is_not_null()
    is_standardised = pl.col("approach") == ApproachType.SA.value
    return {
        "re005_standardised": (unevidenced & is_standardised).sum(),
        "re005_other": (unevidenced & ~is_standardised).sum(),
        "re006": pl.col("ltv_derived").sum(),
    }
