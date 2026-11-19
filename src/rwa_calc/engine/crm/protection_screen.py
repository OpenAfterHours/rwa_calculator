"""
Eligibility screen for unfunded credit protection, run on the raw guarantee rows.

Pipeline position:
    guarantees._prepare_guarantees:
        screen_unfunded_protection -> attach_shared_cap -> multi-level expansion
        -> value_unfunded_protection -> maturity mismatch -> split

Key responsibilities:
- Art. 213(1)(c)(i): drop protection the provider can unilaterally cancel (both
  regimes) or unilaterally change (Basel 3.1, ``ucp_unilateral_change_ineligible``
  Feature) — CRM012.
- Art. 234 / 235(2): drop tranched protection (an attachment above zero, or any
  detachment point) — CRM027. The securitisation framework Art. 234 requires is
  not run for such protection, so it is not recognised; the exposure keeps the
  obligor's own basis, the Art. 268(1) upper bound of that framework's result.
- Art. 213(1)(b)-(d) / 215(1)(b): drop letters of comfort and keepwells
  (``NON_ELIGIBLE_GUARANTEE_TYPES``) — CRM029.
- A ``guarantee_type`` naming a credit derivative makes the row a credit
  derivative whatever ``protection_type`` says — CRM030.
- One contract, one cap: warn where rows sharing a ``guarantee_reference``
  state different amounts or repeat a beneficiary — CRM028.

Every screen runs on the raw rows, before multi-level expansion, so each
message names one input row. The guarantee table is a small dimension frame
the CRM stage has already materialised, so it is collected once here to build
the messages.

References:
- CRR / PS1/26 Art. 213(1): requirements common to all credit protection.
- CRR / PS1/26 Art. 215(1)(b): a guarantee is an explicitly documented
  obligation assumed by the guarantor.
- CRR Art. 234 / PS1/26 Art. 234(1): tranched transfer of risk -> Chapter 5.
- CRR / PS1/26 Art. 235(2): substitution only where the protected and
  unprotected parts are of equal seniority.
- CRR / PS1/26 Art. 233(1): G is the amount the provider undertook to pay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_GUARANTEE_REFERENCE_INCONSISTENT,
    ERROR_INELIGIBLE_UNFUNDED_PROTECTION,
    ERROR_NOT_ELIGIBLE_PROTECTION_TYPE,
    ERROR_PROTECTION_TYPE_MISMATCH,
    ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED,
    crm_warning,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import (
    CREDIT_DERIVATIVE_GUARANTEE_TYPES,
    NON_ELIGIBLE_GUARANTEE_TYPES,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# Columns the screen reads that an input may legitimately omit. Every flag is
# null-PERMISSIVE: a null means "no known defect", so the row is kept.
_SCREEN_COLUMNS: dict[str, ColumnSpec] = {
    "protection_type": ColumnSpec(pl.String, default="guarantee", required=False),
    "guarantee_type": ColumnSpec(pl.String, required=False),
    "guarantee_reference": ColumnSpec(pl.String, required=False),
    "is_unilaterally_cancellable": ColumnSpec(pl.Boolean, required=False),
    "is_unilaterally_changeable": ColumnSpec(pl.Boolean, required=False),
    "attachment_amount": ColumnSpec(pl.Float64, required=False),
    "detachment_amount": ColumnSpec(pl.Float64, required=False),
}


@cites("CRR Art. 213")
@cites("PS1/26, paragraph 213")
@cites("CRR Art. 215")
@cites("PS1/26, paragraph 215")
@cites("CRR Art. 234")
@cites("PS1/26, paragraph 234")
def screen_unfunded_protection(
    guarantees: pl.LazyFrame,
    pack: ResolvedRulepack,
    errors: list[CalculationError] | None,
) -> pl.LazyFrame:
    """
    Drop ineligible unfunded protection and normalise ``protection_type``.

    Args:
        guarantees: Raw guarantee rows (one per input row).
        pack: The run's resolved rulepack (the Art. 213 change-limb Feature).
        errors: CRM error channel; when given, each screened row appends its
            warning(s) and each inconsistent shared reference one CRM028.

    Returns:
        The surviving rows, with ``protection_type`` set to
        ``credit_derivative`` where ``guarantee_type`` names one.
    """
    guarantees = ensure_columns(guarantees, _SCREEN_COLUMNS)
    change_gated = pack.feature("ucp_unilateral_change_ineligible")
    flagged = guarantees.with_columns(_flag_exprs(change_gated))
    if errors is not None:
        # The messages need concrete rows. Materialise the (small) guarantee
        # dimension once and continue from it, so the input plan is not
        # executed a second time downstream.
        materialised = flagged.collect()
        _record_screen_findings(materialised, change_gated, errors)
        flagged = materialised.lazy()

    return (
        flagged.filter(~_dropped())
        .with_columns(
            pl.when(pl.col("_cd_by_type"))
            .then(pl.lit("credit_derivative"))
            .otherwise(pl.col("protection_type"))
            .alias("protection_type"),
        )
        .drop("_ucp_ineligible", "_tranched", "_not_eligible_type", "_cd_by_type")
    )


def _dropped() -> pl.Expr:
    """True where any eligibility screen drops the row."""
    return pl.any_horizontal("_ucp_ineligible", "_tranched", "_not_eligible_type")


def _flag_exprs(change_gated: bool) -> list[pl.Expr]:
    """The four per-row screen flags, each null-free (null input -> False)."""
    ucp = pl.col("is_unilaterally_cancellable")
    if change_gated:
        ucp = ucp | pl.col("is_unilaterally_changeable")
    tranched = (pl.col("attachment_amount") > 0) | pl.col("detachment_amount").is_not_null()
    guarantee_type = (
        pl.col("guarantee_type")
        .fill_null("")
        .str.strip_chars()
        .str.to_lowercase()
        .str.replace_all(r"[\s\-]+", "_")
    )
    protection_type = pl.col("protection_type").fill_null("guarantee")
    return [
        ucp.fill_null(False).alias("_ucp_ineligible"),
        tranched.fill_null(False).alias("_tranched"),
        guarantee_type.is_in(NON_ELIGIBLE_GUARANTEE_TYPES).alias("_not_eligible_type"),
        (
            guarantee_type.is_in(CREDIT_DERIVATIVE_GUARANTEE_TYPES)
            & (protection_type != "credit_derivative")
        ).alias("_cd_by_type"),
        protection_type.alias("protection_type"),
    ]


def _record_screen_findings(
    flagged: pl.DataFrame,
    change_gated: bool,
    errors: list[CalculationError],
) -> None:
    """Append the per-row screen warnings, then the shared-reference ones."""
    for row in flagged.filter(_dropped() | pl.col("_cd_by_type")).iter_rows(named=True):
        errors.extend(_row_findings(row, change_gated))
    survivors = flagged.filter(~_dropped())
    errors.extend(_shared_reference_findings(survivors))


def _row_findings(row: dict[str, Any], change_gated: bool) -> list[CalculationError]:
    """The CRM029 / CRM027 / CRM012 / CRM030 warnings one raw row raises."""
    ref = row["guarantee_reference"]
    beneficiary = row.get("beneficiary_reference")
    found: list[CalculationError] = []
    if row["_not_eligible_type"]:
        found.append(
            crm_warning(
                ERROR_NOT_ELIGIBLE_PROTECTION_TYPE,
                f"Guarantee '{ref}' has guarantee_type '{row['guarantee_type']}': a letter "
                "of comfort or keepwell is not an explicitly documented obligation to pay "
                "on the obligor's default, so it is not eligible unfunded credit "
                "protection; not recognised — the exposure flows unguaranteed.",
                exposure_reference=beneficiary,
                regulatory_reference="CRR / PS1/26 Art. 213(1)(b)-(d), 215(1)(b)",
            )
        )
    if row["_tranched"]:
        found.append(
            crm_warning(
                ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED,
                f"Guarantee '{ref}' covers a tranche of the loss (attachment_amount "
                f"{row['attachment_amount']}, detachment_amount {row['detachment_amount']}). "
                "Art. 234 sends a tranched transfer of risk to the securitisation "
                "framework and Art. 235(2) allows substitution only where the protected "
                "and unprotected parts are of equal seniority; not recognised — the "
                "exposure keeps the obligor's own risk weight.",
                exposure_reference=beneficiary,
                regulatory_reference="CRR / PS1/26 Art. 234, 235(2)",
            )
        )
    if row["_ucp_ineligible"]:
        arm = "cancel or change" if change_gated else "cancel"
        found.append(
            crm_warning(
                ERROR_INELIGIBLE_UNFUNDED_PROTECTION,
                f"Guarantee '{ref}' is ineligible unfunded credit protection "
                f"under Art. 213(1)(c)(i) (the protection provider can unilaterally "
                f"{arm} it); dropped — the exposure flows unguaranteed.",
                exposure_reference=beneficiary,
                regulatory_reference=(
                    "PS1/26 Art. 213(1)(c)(i)" if change_gated else "CRR Art. 213(1)(c)(i)"
                ),
            )
        )
    kept = not (row["_not_eligible_type"] or row["_tranched"] or row["_ucp_ineligible"])
    if row["_cd_by_type"] and kept:
        found.append(
            crm_warning(
                ERROR_PROTECTION_TYPE_MISMATCH,
                f"Guarantee '{ref}' has guarantee_type '{row['guarantee_type']}' but "
                f"protection_type '{row['protection_type']}'; treated as a credit "
                "derivative, so Art. 233(2) applies when includes_restructuring is False.",
                exposure_reference=beneficiary,
                regulatory_reference="CRR / PS1/26 Art. 233(2)",
            )
        )
    return found


def _shared_reference_findings(survivors: pl.DataFrame) -> list[CalculationError]:
    """CRM028: a shared ``guarantee_reference`` whose rows disagree or repeat.

    Rows sharing a reference are one contract with one cap (the largest
    ``amount_covered``). Consistent sharing is the documented way to state a
    pooled cap and raises nothing.
    """
    keyed = survivors.filter(pl.col("guarantee_reference").is_not_null())
    by_reference = (
        keyed.group_by("guarantee_reference", maintain_order=True)
        .agg(
            pl.len().alias("rows"),
            pl.col("amount_covered").min().alias("low"),
            pl.col("amount_covered").max().alias("high"),
            pl.col("beneficiary_reference").n_unique().alias("beneficiaries"),
        )
        .with_columns(
            (pl.col("high") != pl.col("low")).fill_null(False).alias("amounts_differ"),
            (pl.col("beneficiaries") < pl.col("rows")).alias("beneficiary_repeated"),
        )
        .filter(pl.col("amounts_differ") | pl.col("beneficiary_repeated"))
    )
    found: list[CalculationError] = []
    for row in by_reference.iter_rows(named=True):
        ref = row["guarantee_reference"]
        if row["amounts_differ"]:
            found.append(
                crm_warning(
                    ERROR_GUARANTEE_REFERENCE_INCONSISTENT,
                    f"Guarantee '{ref}' appears on {row['rows']} rows with different "
                    f"amount_covered ({row['low']} to {row['high']}); its rows are one "
                    f"contract, so the total recognised is capped at {row['high']} and "
                    "shared pro-rata to each row's covered amount.",
                    regulatory_reference="CRR / PS1/26 Art. 213(1)(b), 233(1)",
                )
            )
        if row["beneficiary_repeated"]:
            found.append(
                crm_warning(
                    ERROR_GUARANTEE_REFERENCE_INCONSISTENT,
                    f"Guarantee '{ref}' is entered more than once for the same "
                    "beneficiary; its rows are one contract and share one cap, so the "
                    "repeated row adds no cover beyond it.",
                    regulatory_reference="CRR / PS1/26 Art. 213(1)(b), 233(1)",
                )
            )
    return found
