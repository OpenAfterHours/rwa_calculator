"""
Two-layer protection look-through for credit risk mitigation.

Pipeline position:
    CRMProcessor.get_crm_unified_bundle (Step 0, before any other CRM step)

Key responsibilities:
- Honour the PRA Art. 191A(2)(e)(i) "funded-only" election: when an unfunded
  guarantee is itself collateralised by funded collateral posted by the
  guarantor, recognise ONLY the funded collateral. The guarantee row is
  suppressed (no Art. 235 RWSM substitution) and the collateral row is
  re-anchored from the guarantee onto the original obligor exposure.
- Emit an audit-trail CRM warning when the election is honoured so the
  operator can trace the regulatory decision.

References:
    PRA PS1/26 Art. 191A(2)(d)-(f): two-layer protection
    PRA PS1/26 Art. 191A(2)(e)(i): funded-only election
    PRA PS1/26 Art. 222 / Art. 197(1)(a): cash as eligible financial collateral
    PRA PS1/26 Art. 235: SA risk-weight substitution method (suppressed here)
"""

from __future__ import annotations

import logging

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_LOOK_THROUGH_APPLIED,
    ERROR_LOOK_THROUGH_NOT_IMPLEMENTED,
    CalculationError,
    crm_warning,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns

logger = logging.getLogger(__name__)


def apply_funded_only_look_through(
    guarantees: pl.LazyFrame | None,
    collateral: pl.LazyFrame | None,
) -> tuple[pl.LazyFrame | None, pl.LazyFrame | None, list[CalculationError]]:
    """
    Honour the Art. 191A(2)(e)(i) funded-only look-through election.

    For each guarantee row with ``look_through_election == "funded_only"``:
        1. Locate any collateral rows whose ``beneficiary_type == "guarantee"``
           and ``beneficiary_reference`` matches the guarantee's
           ``guarantee_reference``.
        2. Re-anchor those collateral rows onto the obligor exposure: rewrite
           ``beneficiary_type`` and ``beneficiary_reference`` to the
           guarantee's own ``beneficiary_type`` / ``beneficiary_reference``.
        3. Suppress the guarantee row (drop it from the guarantees frame so
           the downstream Art. 235 RWSM substitution does not run for it).

    Rows with ``look_through_election`` of ``"none"`` (the default) are left
    untouched, so existing behaviour is preserved when no caller opts in.
    A ``"both"`` election is currently treated as ``"none"`` and emits a
    CRM warning that the path is not implemented.

    Args:
        guarantees: Raw guarantee LazyFrame from the bundle (may be ``None``).
        collateral: Raw collateral LazyFrame from the bundle (may be ``None``).

    Returns:
        A tuple ``(guarantees, collateral, errors)`` where the frames have
        been transformed in line with the election and ``errors`` carries
        any audit-trail warnings emitted during processing.
    """
    errors: list[CalculationError] = []

    if guarantees is None:
        return guarantees, collateral, errors

    schema_names = guarantees.collect_schema().names()

    # Fast path: if the input never carried look_through_election, the caller
    # is on the default no-look-through track. Skip the materialise entirely
    # so legacy fixtures that omit the column behave exactly as before.
    if "look_through_election" not in schema_names:  # arch-exempt: early-exit guard
        return guarantees, collateral, errors

    # The caller opted into the field. We still need ``guarantee_reference``
    # plus the beneficiary columns to identify which rows to suppress and
    # re-anchor. Without them the election cannot be honoured — bail out lazily.
    required = {"guarantee_reference", "beneficiary_type", "beneficiary_reference"}
    if not required.issubset(schema_names):  # arch-exempt: early-exit guard
        return guarantees, collateral, errors

    guarantees = ensure_columns(
        guarantees,
        {
            "look_through_election": ColumnSpec(pl.String, default="none", required=False),
        },
    )

    election_col = pl.col("look_through_election").fill_null("none")
    election_df = (
        guarantees.select(
            pl.col("guarantee_reference"),
            pl.col("beneficiary_type"),
            pl.col("beneficiary_reference"),
            election_col.alias("_lt_election"),
        )
        .filter(pl.col("_lt_election").is_in(["funded_only", "both"]))
        .collect()
    )

    if election_df.height == 0:
        return guarantees, collateral, errors

    flagged_df = election_df.filter(pl.col("_lt_election") == "funded_only")
    both_df = election_df.filter(pl.col("_lt_election") == "both")

    # Re-anchor collateral rows whose beneficiary points at one of the
    # flagged guarantees.  We perform this transform on a small in-memory
    # dataframe so we can build per-row updates without complex joins; the
    # result is returned as a LazyFrame so the downstream pipeline stays lazy.
    if flagged_df.height > 0 and collateral is not None:
        collateral_df = collateral.collect()
        collateral_df = _re_anchor_collateral(collateral_df, flagged_df)
        collateral = collateral_df.lazy()

    # Suppress the flagged guarantee rows so the RWSM substitution path does
    # not run for them. The funded benefit now flows through FCCM/FCSM via
    # the re-anchored collateral.
    flagged_refs = flagged_df["guarantee_reference"].to_list()
    if flagged_refs:
        guarantees = guarantees.filter(
            ~((election_col == "funded_only") & pl.col("guarantee_reference").is_in(flagged_refs))
        )

    for guarantee_ref in flagged_refs:
        logger.info("art_191a_funded_only_look_through guarantee=%s", guarantee_ref)
        errors.append(
            crm_warning(
                ERROR_LOOK_THROUGH_APPLIED,
                f"Guarantee '{guarantee_ref}' honoured under Art. 191A(2)(e)(i) "
                "funded-only look-through: guarantee suppressed and guarantor-"
                "posted collateral re-anchored onto the obligor exposure.",
                regulatory_reference="PRA PS1/26 Art. 191A(2)(e)(i)",
            )
        )

    for guarantee_ref in both_df["guarantee_reference"].to_list():
        errors.append(
            crm_warning(
                ERROR_LOOK_THROUGH_NOT_IMPLEMENTED,
                f"Guarantee '{guarantee_ref}' requested look_through_election='both' "
                "which is not implemented; falling back to no look-through.",
                regulatory_reference="PRA PS1/26 Art. 191A(2)(e)(ii)",
            )
        )

    return guarantees, collateral, errors


def _re_anchor_collateral(collateral_df: pl.DataFrame, flagged_df: pl.DataFrame) -> pl.DataFrame:
    """
    Rewrite collateral rows that point at a flagged guarantee.

    For each flagged guarantee, any collateral row with
    ``beneficiary_type == "guarantee"`` and ``beneficiary_reference == <guarantee_ref>``
    has those two columns rewritten to the guarantee's own
    ``beneficiary_type`` / ``beneficiary_reference``. Rows that do not match
    are left untouched.
    """
    if "beneficiary_type" not in collateral_df.columns:  # arch-exempt: early-exit guard
        return collateral_df
    if "beneficiary_reference" not in collateral_df.columns:  # arch-exempt: early-exit guard
        return collateral_df

    # Build a per-guarantee mapping: guarantee_ref -> (target_type, target_ref).
    target_type_lookup = dict(
        zip(
            flagged_df["guarantee_reference"].to_list(),
            flagged_df["beneficiary_type"].to_list(),
            strict=True,
        )
    )
    target_ref_lookup = dict(
        zip(
            flagged_df["guarantee_reference"].to_list(),
            flagged_df["beneficiary_reference"].to_list(),
            strict=True,
        )
    )

    new_types: list[str] = []
    new_refs: list[str] = []
    for bt, br in zip(
        collateral_df["beneficiary_type"].to_list(),
        collateral_df["beneficiary_reference"].to_list(),
        strict=True,
    ):
        if isinstance(bt, str) and bt.lower() == "guarantee" and br in target_ref_lookup:
            new_types.append(target_type_lookup[br])
            new_refs.append(target_ref_lookup[br])
        else:
            new_types.append(bt)
            new_refs.append(br)

    return collateral_df.with_columns(
        pl.Series("beneficiary_type", new_types, dtype=pl.String),
        pl.Series("beneficiary_reference", new_refs, dtype=pl.String),
    )
