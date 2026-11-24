"""
Eligibility screen for unfunded credit protection, run on the raw guarantee rows.

Pipeline position:
    guarantees._prepare_guarantees:
        screen_unfunded_protection -> attach_shared_cap -> multi-level expansion
        -> value_unfunded_protection -> maturity mismatch -> split

Key responsibilities:
- Art. 213(1)(c)(i): drop protection the provider can unilaterally cancel (both
  regimes) or unilaterally change in a way that would adversely impact the
  institution (Basel 3.1, ``ucp_unilateral_change_ineligible`` Feature) — CRM012.
  Basel 3.1 Art. 183(1A)(b) carries the same words for IRB; the screen runs on
  every row before the approach split, so it serves both.
- PS1/26 rule 4.11: on a reporting date from 1 January 2027 to 30 June 2028
  (both included) the change limb is omitted for protection entered into before
  1 January 2027 (``protection_inception_date``). The cancel limb is never
  omitted, and a null inception date is not grandfathered.
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
- PS1/26 Art. 183(1A)(b): the IRB twin of the Art. 213(1)(c)(i) change limb.
- PS1/26 Credit Risk: General Provisions (CRR) Part rule 4.11: Unfunded Credit
  Protection Transitional ("or change" omitted for pre-2027 protection to
  30 June 2028).
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
    from datetime import date

    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# Columns the screen reads that an input may legitimately omit. Every flag is
# null-PERMISSIVE: a null means "no known defect", so the row is kept. The rule
# 4.11 inception date is the opposite, deliberately: it RELAXES the screen, so a
# null (or absent) date is not grandfathered.
_SCREEN_COLUMNS: dict[str, ColumnSpec] = {
    "protection_type": ColumnSpec(pl.String, default="guarantee", required=False),
    "guarantee_type": ColumnSpec(pl.String, required=False),
    "guarantee_reference": ColumnSpec(pl.String, required=False),
    "is_unilaterally_cancellable": ColumnSpec(pl.Boolean, required=False),
    "is_unilaterally_changeable": ColumnSpec(pl.Boolean, required=False),
    "protection_inception_date": ColumnSpec(pl.Date, required=False),
    "attachment_amount": ColumnSpec(pl.Float64, required=False),
    "detachment_amount": ColumnSpec(pl.Float64, required=False),
}


@cites("CRR Art. 213")
@cites("PS1/26, paragraph 213")
@cites("PS1/26, paragraph 4.11")
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
        pack: The run's resolved rulepack: the Art. 213 change-limb Feature,
            and — where that is on — the rule 4.11 window and inception cut-off,
            tested against ``pack.reporting_date`` (the run's reporting date).
        errors: CRM error channel; when given, each screened row appends its
            warning(s) and each inconsistent shared reference one CRM028.

    Returns:
        The surviving rows, with ``protection_type`` set to
        ``credit_derivative`` where ``guarantee_type`` names one.
    """
    guarantees = ensure_columns(guarantees, _SCREEN_COLUMNS)
    change_gated = pack.feature("ucp_unilateral_change_ineligible")
    # Only a gated change limb has "or change" words for rule 4.11 to omit.
    cutoff = _rule_4_11_inception_cutoff(pack) if change_gated else None
    flagged = guarantees.with_columns(_flag_exprs(change_gated, cutoff))
    if errors is not None:
        # The messages need concrete rows. Materialise the (small) guarantee
        # dimension once and continue from it, so the input plan is not
        # executed a second time downstream.
        materialised = flagged.collect()
        _record_screen_findings(materialised, change_gated, cutoff, errors)
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


def _rule_4_11_inception_cutoff(pack: ResolvedRulepack) -> date | None:
    """The rule 4.11 inception cut-off where the reporting date is in the window.

    Rule 4.11: "During the period beginning with 1 January 2027 and ending with
    30 June 2028 ... [Art. 213(1)(c)(i)] shall apply to unfunded credit
    protection entered into prior to 1 January 2027 with the words 'or change'
    wherever they appear omitted." Both window days are included. Returns None
    outside the window, where no protection is grandfathered.
    """
    start = pack.date_param("ucp_change_limb_transitional_start").value
    end = pack.date_param("ucp_change_limb_transitional_end").value
    if not start <= pack.reporting_date <= end:
        return None
    return pack.date_param("ucp_change_limb_grandfather_inception_cutoff").value


def _dropped() -> pl.Expr:
    """True where any eligibility screen drops the row."""
    return pl.any_horizontal("_ucp_ineligible", "_tranched", "_not_eligible_type")


def _flag_exprs(change_gated: bool, cutoff: date | None) -> list[pl.Expr]:
    """The four per-row screen flags, each null-free (null input -> False).

    ``cutoff`` is the rule 4.11 inception cut-off on an in-window reporting
    date (else None): the change limb then does not apply to protection entered
    into strictly before it. A null inception date is not before it.
    """
    ucp = pl.col("is_unilaterally_cancellable")
    if change_gated:
        change = pl.col("is_unilaterally_changeable")
        if cutoff is not None:
            change = change & ~_grandfathered(cutoff)
        ucp = ucp | change
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


def _grandfathered(cutoff: date) -> pl.Expr:
    """True where the protection was entered into strictly before ``cutoff``; never null.

    The null test comes first on purpose. ``~null`` is null, which the final
    ``fill_null(False)`` would read as eligible — so a bare ``date < cutoff``
    would grandfather every row with no inception date. ``False & null`` is
    False, so this expression is False for a null date.
    """
    inception = pl.col("protection_inception_date")
    return inception.is_not_null() & (inception < cutoff)


def _record_screen_findings(
    flagged: pl.DataFrame,
    change_gated: bool,
    cutoff: date | None,
    errors: list[CalculationError],
) -> None:
    """Append the per-row screen warnings, then the shared-reference ones."""
    for row in flagged.filter(_dropped() | pl.col("_cd_by_type")).iter_rows(named=True):
        errors.extend(_row_findings(row, change_gated, cutoff))
    survivors = flagged.filter(~_dropped())
    errors.extend(_shared_reference_findings(survivors))


def _row_findings(
    row: dict[str, Any], change_gated: bool, cutoff: date | None
) -> list[CalculationError]:
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
        found.append(_ucp_finding(row, change_gated, cutoff))
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


def _ucp_finding(row: dict[str, Any], change_gated: bool, cutoff: date | None) -> CalculationError:
    """CRM012: the Art. 213(1)(c)(i) clause the row has, and why rule 4.11 did not help.

    A row dropped on the change limb inside the rule 4.11 window says why it was
    not grandfathered (its inception date is null, or not before the cut-off).
    """
    on_change_limb = not row["is_unilaterally_cancellable"]
    clause = (
        "change it in a way that would adversely impact the institution"
        if on_change_limb
        else "cancel it"
    )
    message = (
        f"Guarantee '{row['guarantee_reference']}' is ineligible unfunded credit "
        f"protection under Art. 213(1)(c)(i) (the protection provider can unilaterally "
        f"{clause}); dropped — the exposure flows unguaranteed."
    )
    reference = "PS1/26 Art. 213(1)(c)(i)" if change_gated else "CRR Art. 213(1)(c)(i)"
    if on_change_limb and cutoff is not None:
        inception = row["protection_inception_date"]
        reason = "is null" if inception is None else f"is not before {cutoff.isoformat()}"
        message += (
            f" PS1/26 rule 4.11 omits 'or change' only for protection entered into "
            f"before {cutoff.isoformat()}; protection_inception_date {reason}."
        )
        reference += ", rule 4.11"
    return crm_warning(
        ERROR_INELIGIBLE_UNFUNDED_PROTECTION,
        message,
        exposure_reference=row.get("beneficiary_reference"),
        regulatory_reference=reference,
    )


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
                    "beneficiary; its rows are one contract: a repeat from the same "
                    "guarantor adds no cover (the largest row is used), and rows from "
                    "different guarantors share the contract's cap.",
                    regulatory_reference="CRR / PS1/26 Art. 213(1)(b), 233(1)",
                )
            )
    return found
