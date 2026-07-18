"""
Third-Party Deposit Method (Art. 200(a)/232(2) with Art. 212(1)).

Pipeline position:
    CRMProcessor (pre-collateral split + Step 4c compute)
        -> SACalculator.apply_third_party_deposit_rw_mapping

Key responsibilities:
- Identify cash on deposit held at a THIRD-PARTY institution (the collateral row
  carries ``held_by_counterparty_reference``); such deposits are "other funded
  credit protection" treated as a GUARANTEE by the holder institution (Art.
  232(2)) — the holder's own SA risk weight substitutes on the covered part —
  NOT own-bank cash at a 0% haircut.
- Partition them out of the ordinary collateral frame so they contribute to NO
  cash-collateral value channel (SA E*, FIRB LGD*), then aggregate per exposure
  into ``third_party_deposit_value`` + ``third_party_deposit_secured_rw`` for the
  SA calculator's risk-weight blend.
- Under F-IRB the substitution analogue is deferred: a third-party deposit gives
  NO benefit (conservative) and raises CRM017.

The holder institution's risk weight is derived from the deposit row's
``issuer_cqs`` (a cash deposit is a claim on the institution holding it, so its
issuer IS the holder) via the same Art. 120/121 (CRR) / Art. 120A ECRA (Basel
3.1) institution tables the SA calculator and FCSM use — no invented values.

References:
- CRR Art. 200(a): eligibility of third-party deposits as other funded protection
- CRR Art. 232(2): third-party deposit treated as a guarantee by the holder
- CRR Art. 212(1): operational requirements
- PS1/26 Art. 200(1)(a)/232: retained equivalents
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED, crm_warning
from rwa_calc.data.schemas import (
    INSTITUTION_DEPOSIT_HOLDER_TYPES,
    THIRD_PARTY_DEPOSIT_COLLATERAL_TYPES,
)
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.sa.guarantor_rw import build_institution_guarantor_rw_expr

if TYPE_CHECKING:
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


def _is_third_party_deposit_expr() -> pl.Expr:
    """A cash/deposit collateral row that carries a third-party holder reference."""
    return (
        pl.col("collateral_type").str.to_lowercase().is_in(THIRD_PARTY_DEPOSIT_COLLATERAL_TYPES)
        & pl.col("held_by_counterparty_reference").is_not_null()
    )


def split_third_party_deposits(
    collateral: pl.LazyFrame | None,
) -> tuple[pl.LazyFrame | None, pl.LazyFrame | None]:
    """Partition third-party deposits out of the ordinary collateral frame.

    Returns ``(collateral_without_third_party_deposits, third_party_deposits)``.
    The first feeds the normal haircut / EAD / LGD* machinery (so third-party
    deposits contribute to no cash-collateral value channel); the second feeds
    ``compute_third_party_deposit_columns``. Either may be None.
    """
    if collateral is None:
        return None, None
    names = collateral.collect_schema().names()
    if "held_by_counterparty_reference" not in names or "collateral_type" not in names:
        return collateral, None
    is_tpd = _is_third_party_deposit_expr()
    return collateral.filter(~is_tpd), collateral.filter(is_tpd)


@cites("CRR Art. 232")
def compute_third_party_deposit_columns(
    exposures: pl.LazyFrame,
    third_party_deposits: pl.LazyFrame | None,
    *,
    is_basel_3_1: bool,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Set SA third-party-deposit CRM columns on the exposure frame.

    Aggregates the third-party deposits per beneficiary exposure and sets:
    - third_party_deposit_value: total INSTITUTION-held deposit value (capped at EAD)
    - third_party_deposit_secured_rw: value-weighted holder institution RW

    Only deposits held by an INSTITUTION (Art. 232(2)) drive the substitution; the
    holder RW is looked up via the shared ``build_institution_guarantor_rw_expr``
    (CRR Art. 120 / PS1/26 Art. 120A ECRA, with the CRE20.21 SCRA Grade-C 150%
    fallback for an unrated Basel 3.1 holder — the deposit carries no SCRA grade,
    so the conservative fallback binds). A populated NON-institution holder is out
    of scope: no benefit (it is already excluded from the 0% cash path) + CRM017.
    Under F-IRB the substitution is deferred: no benefit + CRM017.
    """
    if third_party_deposits is None:
        return _add_default_columns(exposures)

    is_inst = pl.col("issuer_type").str.to_lowercase().is_in(INSTITUTION_DEPOSIT_HOLDER_TYPES)
    tpd = third_party_deposits.with_columns(
        is_inst.alias("_tpd_is_inst"),
        # A null SCRA-grade column so build_institution_guarantor_rw_expr routes an
        # unrated B31 holder to the CRE20.21 Grade-C conservative fallback.
        pl.lit(None).cast(pl.String).alias("_tpd_scra_grade"),
    ).with_columns(
        build_institution_guarantor_rw_expr(
            "issuer_cqs", is_basel_3_1, scra_grade_col="_tpd_scra_grade"
        ).alias("_tpd_item_rw"),
    )
    val = pl.col("market_value").fill_null(0.0)
    inst_val = val.filter(pl.col("_tpd_is_inst"))
    agg = tpd.group_by("beneficiary_reference").agg(
        inst_val.sum().alias("_tpd_inst_value"),
        (inst_val * pl.col("_tpd_item_rw").filter(pl.col("_tpd_is_inst")))
        .sum()
        .alias("_tpd_weighted_rw"),
        (~pl.col("_tpd_is_inst")).any().alias("_tpd_has_non_inst"),
    )

    exp_names = exposures.collect_schema().names()
    exp_ref = "exposure_reference" if "exposure_reference" in exp_names else "loan_reference"
    ead_col = "ead_gross" if "ead_gross" in exp_names else "ead"

    exposures = exposures.join(agg, left_on=exp_ref, right_on="beneficiary_reference", how="left")

    ead = pl.col(ead_col).fill_null(0.0)
    inst_value = pl.col("_tpd_inst_value").fill_null(0.0)
    wrw = pl.col("_tpd_weighted_rw").fill_null(0.0)
    has_non_inst = pl.col("_tpd_has_non_inst").fill_null(value=False)
    avg_rw = pl.when(inst_value > 0).then(wrw / inst_value).otherwise(pl.lit(0.0))

    is_firb = pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
    if errors is not None:
        _record_third_party_deposit_warnings(
            exposures, inst_value, has_non_inst, is_firb, exp_ref, errors
        )

    exposures = exposures.with_columns(
        pl.when(is_firb)
        .then(pl.lit(0.0))
        .otherwise(pl.min_horizontal(inst_value, ead))
        .alias("third_party_deposit_value"),
        avg_rw.alias("third_party_deposit_secured_rw"),
    ).drop(["_tpd_inst_value", "_tpd_weighted_rw", "_tpd_has_non_inst"])

    return exposures


def _add_default_columns(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Zero-valued third-party-deposit columns when no such deposit exists."""
    return exposures.with_columns(
        pl.lit(0.0).alias("third_party_deposit_value"),
        pl.lit(0.0).alias("third_party_deposit_secured_rw"),
    )


def _record_third_party_deposit_warnings(
    exposures: pl.LazyFrame,
    inst_value: pl.Expr,
    has_non_inst: pl.Expr,
    is_firb: pl.Expr,
    exp_ref: str,
    errors: list[CalculationError],
) -> None:
    """Append CRM017 warnings for third-party deposits that yield no benefit.

    Two distinct reasons (one collect over the gated rows, P1.264 idiom):
    - F-IRB exposure with an institution-held deposit: substitution deferred.
    - a NON-institution holder: out of Art. 232(2) scope (institution only).
    """
    firb_flag = (is_firb & (inst_value > 0)).alias("_firb")
    gated = (
        exposures.filter((is_firb & (inst_value > 0)) | has_non_inst)
        .select(pl.col(exp_ref).alias("_ref"), firb_flag, has_non_inst.alias("_non_inst"))
        .collect()
    )
    for row in gated.iter_rows(named=True):
        ref = row.get("_ref")
        if row.get("_non_inst"):
            errors.append(
                crm_warning(
                    ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED,
                    f"Exposure '{ref}' carries a third-party deposit whose holder is "
                    f"not an institution; Art. 232(2) other-funded-protection treatment "
                    f"applies only to deposits held by an institution, so the deposit "
                    f"receives no CRM benefit (it is not own-bank cash either).",
                    exposure_reference=ref,
                    regulatory_reference="CRR Art. 200(a)/232(2)",
                )
            )
        if row.get("_firb"):
            errors.append(
                crm_warning(
                    ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED,
                    f"Exposure '{ref}' is secured by a third-party deposit (Art. 232(2) "
                    f"other funded protection). The F-IRB holder-RW substitution is a "
                    f"deferred follow-up, so the deposit is conservatively given no CRM "
                    f"benefit under F-IRB (excluded from LGD*) pending that treatment.",
                    exposure_reference=ref,
                    regulatory_reference="CRR Art. 200(a)/232(2)",
                )
            )
