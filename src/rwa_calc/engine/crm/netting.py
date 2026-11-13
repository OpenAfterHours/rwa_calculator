"""
On-balance-sheet netting: synthetic cash collateral from netted deposits.

Pipeline position:
    EAD initialisation -> generate_netting_collateral -> apply_collateral

Key responsibilities:
- Turn negative-drawn loans (deposits) carrying a ``netting_agreement_reference``
  into synthetic ``NETTING_<loan>`` cash collateral rows (Art. 195 / 219)
- Pool deposits per set-off perimeter and allocate them pro-rata to the
  positive-drawn loans under the same agreement
- Carry the DEPOSIT's maturity onto each synthetic row so the Art. 237-239
  maturity-mismatch rules apply as for any other funded protection
- Record the Art. 195 / 205(a) CRM016 audit warning for agreements spanning
  more than one counterparty

References:
    CRR Art. 195: on-balance-sheet netting of reciprocal cash balances
    CRR Art. 205(a): legal enforceability of the netting agreement
    CRR Art. 219: netted loans and deposits treated as cash collateral
    CRR Art. 237-239: maturity mismatch on funded protection
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_CROSS_COUNTERPARTY_NETTING, crm_warning
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


@cites("CRR Art. 195")
@cites("CRR Art. 205")
@cites("CRR Art. 219")
@cites("CRR Art. 223")
@cites("CRR Art. 238")
def generate_netting_collateral(
    exposures: pl.LazyFrame,
    errors: list[CalculationError] | None = None,
    *,
    pack: ResolvedRulepack,
    reporting_date: date | None = None,
) -> pl.LazyFrame | None:
    """
    Generate synthetic cash collateral from negative-drawn netting-eligible loans.

    A negative drawn amount (credit balance / deposit) on a loan carrying a
    ``netting_agreement_reference`` (CRR Art. 195/219) becomes synthetic cash
    collateral for the other exposures under the SAME agreement.

    The agreement reference ALONE bounds the set-off (operator decision
    2026-09-04, reversing P1.238's (reference, counterparty) keying): pools key
    on (reference, currency), siblings match on the reference and the pro-rata
    denominator is the agreement's total drawn, so a deposit offsets every
    positive-drawn loan sibling under that agreement whichever party to it holds
    the leg. This is the cited pack Feature
    ``on_bs_netting_perimeter_is_agreement``; flipping it off restores the
    (reference, counterparty) keying exactly. An agreement spanning more than one
    counterparty — or carrying a null one — raises one CRM016 WARNING as an AUDIT
    record: the offset IS applied, and Art. 205(a) enforceability against every
    party to the agreement must be evidenced separately. Two exposures still do
    NOT net unless they share the reference, regardless of facility hierarchy.

    CRR Art. 219 limits on-balance-sheet netting to drawn loans and deposits
    (cash-on-cash). Synthetic cash collateral is allocated pro-rata by the drawn
    portion (`on_bs_for_ead`) to positive-drawn LOAN siblings carrying the same
    reference — contingents and synthetic facility_undrawn rows are
    off-balance-sheet and excluded from the beneficiary set.

    Currency: pools key on each deposit's DENOMINATION, and every synthetic row
    carries it as ``original_currency`` beside a ``currency`` that matches its
    already-converted ``market_value``. By the time CRM runs, ``FXConverter`` has
    rebased ``currency`` to the reporting currency on every row; the denomination
    survives only in ``original_currency`` (``currency`` itself for a direct caller
    that never ran conversion). That denomination is what the Art. 224 Table 4
    currency-mismatch test in ``HaircutCalculator.apply_haircuts`` compares with
    the loan's own (``exposure_currency``), so deposits in two currencies under one
    agreement stay two pools, and a synthetic row diagonal-concatenated onto an
    FX-converted user collateral frame does not arrive with a null there. Pooling
    on the rebased ``currency`` compared the REPORTING currency with the loan's
    denomination instead: a EUR deposit against a GBP loan took no haircut, a EUR
    deposit against a EUR loan took one, and with any collateral file present no
    netted deposit was haircut at all (escape log 2026-11-13).

    Art. 219 treats the netted deposit as cash collateral, so the funded-
    protection maturity-mismatch rules (Art. 237-239) apply exactly as for any
    other funded protection (P1.241). The synthetic row therefore carries the
    DEPOSIT's maturity — not the beneficiary loan's — as ``maturity_date``, the
    deposit residual (t) as ``residual_maturity_years`` (when ``reporting_date``
    is supplied) and the deposit ORIGINAL term as ``original_maturity_years``
    (when ``value_date`` is available). Downstream ``apply_maturity_mismatch``
    then, on a mismatch (t < T where T is the loan residual), zeroes the
    protection when t < 0.25 (Art. 237(1)) OR the original term < 1y
    (Art. 237(2)(a)), else applies (t-0.25)/(T-0.25) (Art. 238-239). The residual
    uses the /365.25 day-count of that function's exposure-side T (so equal
    deposit/loan maturities net in full, with NO phantom mismatch); the original
    term uses the /365 convention of the engine's other original-maturity
    derivations (risk_weights.py / enrich.py).

    Pooling convention (conservative): a pool of deposits of differing maturities
    carries the EARLIEST (minimum) deposit maturity AND the minimum deposit
    original term — the earliest maturity is when the pool's protection first
    begins to lapse and maximises the mismatch haircut (shortest t → smallest
    (t-0.25)/(T-0.25)), and the shortest original term is the one most likely to
    trip the Art. 237(2)(a) <1y gate. A null deposit maturity (or no
    ``reporting_date``) leaves the residual null, handled permissively downstream
    — absent maturity data cannot establish a mismatch, the convention ordinary
    financial collateral without a supplied residual follows, and the downstream
    10y default is unchanged (so this is NOT an anti-conservative fill); a null
    original term (no ``value_date``) likewise leaves the Art. 237(2)(a) gate
    permissive.

    Args:
        exposures: Exposures with ead_for_crm, on_bs_for_ead, exposure_type set
        errors: optional CRM error channel — receives the Art. 195 CRM016 audit
            warning for agreements spanning more than one counterparty.
        pack: resolved rulepack supplying the perimeter Feature. REQUIRED — a
            default would fail open to the wider, RWA-reducing perimeter, so
            every caller resolves a pack of its own.
        reporting_date: run reporting date, used to derive the deposit residual
            maturity (Art. 238) on the synthetic rows. When None (direct
            unit-test callers), residual_maturity_years stays null and the
            maturity mismatch is not applied — backward-compatible behaviour.

    Returns:
        LazyFrame of synthetic collateral rows, or None if no netting applies
    """
    schema = exposures.collect_schema()
    schema_names = set(schema.names())
    if "netting_agreement_reference" not in schema_names:
        return None

    # value_date lets the pool derive each deposit's ORIGINAL maturity for the
    # Art. 237(2)(a) gate. It is a core exposure column in production; injected as
    # a typed null for direct unit-test callers that omit it (→ original maturity
    # null → the gate stays permissive), via the schema-driven ensure_columns.
    exposures = ensure_columns(exposures, {"value_date": ColumnSpec(pl.Date, required=False)})

    # Graceful fallback for direct unit-test callers (production always
    # supplies ead_for_crm via _initialize_ead, on_bs_for_ead via _compute_ead,
    # and exposure_type via hierarchy).
    if "ead_for_crm" not in schema_names:
        exposures = exposures.with_columns(pl.col("ead_gross").alias("ead_for_crm"))
    if "on_bs_for_ead" not in schema_names:
        interest_expr = (
            pl.col("interest").fill_null(0.0).clip(lower_bound=0.0)
            if "interest" in schema_names
            else pl.lit(0.0)
        )
        exposures = exposures.with_columns(
            (pl.col("drawn_amount").clip(lower_bound=0.0) + interest_expr).alias("on_bs_for_ead")
        )
    if "exposure_type" not in schema_names:
        exposures = exposures.with_columns(pl.lit("loan").alias("exposure_type"))
    if "counterparty_reference" not in schema_names:
        # Test-caller fallback only (production always supplies it): one synthetic
        # counterparty, so the disabled perimeter is a no-op for legacy callers.
        exposures = exposures.with_columns(pl.lit("_UNKNOWN_CP").alias("counterparty_reference"))

    # Each leg's DENOMINATION (see the docstring): the pre-conversion currency,
    # falling back to ``currency`` per row where no conversion audit exists.
    denomination = (
        pl.coalesce("original_currency", "currency")
        if "original_currency" in schema_names
        else pl.col("currency")
    )
    exposures = exposures.with_columns(denomination.alias("_denomination"))

    # The Art. 195 set-off perimeter, from the cited pack Feature: the agreement
    # reference alone (enabled), or (reference, counterparty) when disabled.
    # Derived once so the two states differ in exactly one place — every pool,
    # sibling-join and pro-rata key below is built from these lists.
    perimeter_is_agreement = pack.feature("on_bs_netting_perimeter_is_agreement")
    perimeter_keys = ["netting_agreement_reference"]
    if not perimeter_is_agreement:
        perimeter_keys.append("counterparty_reference")
    allocation_keys = [*perimeter_keys, "_pool_original_currency", "_pool_currency"]

    # Negative-drawn loans carrying a netting agreement reference provide the pool
    negative_loans = exposures.filter(
        pl.col("netting_agreement_reference").is_not_null() & (pl.col("drawn_amount") < 0)
    )

    # Art. 195/205(a): CRM016 audit record for any agreement spanning more than
    # one counterparty (or carrying a null one) — the offset itself applies.
    if errors is not None:
        _record_cross_counterparty_netting(exposures, errors, perimeter_is_agreement)

    # Sum abs(drawn_amount) per (perimeter keys, denomination) → netting pool.
    # The rebased ``currency`` is a function of the denomination (one rate per
    # currency), so keying on it as well never splits a pool; it is kept so the
    # synthetic row's ``currency`` matches its converted market_value, exactly as
    # FXConverter leaves user collateral. Art. 219/238 (P1.241): the earliest
    # (min) deposit maturity per pool drives the mismatch t; the minimum deposit
    # ORIGINAL maturity rides alongside for the Art. 237(2)(a) >=1y gate (from
    # maturity_date - value_date, /365 as in engine/sa/risk_weights.py and
    # hierarchy/enrich.py). A null value_date leaves it null (gate permissive).
    deposit_original_years = (
        pl.col("maturity_date").cast(pl.Int32) - pl.col("value_date").cast(pl.Int32)
    ).cast(pl.Float64) / 365.0
    netting_pool = (
        negative_loans.group_by([*perimeter_keys, "_denomination", "currency"])
        .agg(
            pl.col("drawn_amount").abs().sum().alias("netting_pool"),
            pl.col("maturity_date").min().alias("_pool_deposit_maturity_date"),
            deposit_original_years.min().alias("_pool_deposit_orig_maturity"),
        )
        .rename({"_denomination": "_pool_original_currency", "currency": "_pool_currency"})
    )

    # CRR Art. 219: drawn-on-drawn cash netting. Synthetic cash collateral may
    # only benefit the drawn portion of loan exposures — contingents and
    # facility_undrawn synthetic rows are off-balance-sheet and ineligible. The
    # beneficiary loan's own maturity is NOT carried onto the synthetic row: it
    # feeds the mismatch as the EXPOSURE side (T) via the exposure lookup join
    # downstream, while the synthetic row carries the DEPOSIT maturity (t).
    positive_siblings = exposures.filter(
        (pl.col("exposure_type") == "loan")
        & (pl.col("on_bs_for_ead") > 0)
        & pl.col("netting_agreement_reference").is_not_null()
    ).select(
        "exposure_reference",
        "netting_agreement_reference",
        "counterparty_reference",
        "currency",
        "on_bs_for_ead",
    )

    # Match siblings to pools on the perimeter keys.
    matched = positive_siblings.join(netting_pool, on=perimeter_keys, how="inner")

    # Total drawn EAD per pool for pro-rata allocation. CRR Art. 219 nets cash
    # against drawn loans, so the basis is the on-BS (drawn) portion, NOT
    # ead_for_crm (which includes the off-BS nominal at CCF=100% per Art. 223(4)
    # — that override is for collateral valuation, not the OBS netting basis).
    facility_totals = matched.group_by(allocation_keys).agg(
        pl.col("on_bs_for_ead").sum().alias("_facility_total_drawn"),
    )

    # Join totals back for pro-rata
    allocated = matched.join(facility_totals, on=allocation_keys, how="left").filter(
        pl.col("_facility_total_drawn") > 0
    )

    # Pro-rata market_value per sibling by drawn portion (Art. 219).
    allocated = allocated.with_columns(
        (pl.col("netting_pool") * pl.col("on_bs_for_ead") / pl.col("_facility_total_drawn")).alias(
            "market_value"
        ),
    )

    # Deposit residual maturity (Art. 238 t). Derived from the pool's earliest
    # deposit maturity when a reporting_date is available; null (permissive)
    # otherwise. The /365.25 basis MATCHES the exposure-side T derivation in
    # HaircutCalculator.apply_maturity_mismatch, so a deposit and loan sharing a
    # maturity date net in full (t == T, no phantom mismatch). A null pool
    # maturity date yields a null residual either way.
    residual_expr = (
        (
            (pl.col("_pool_deposit_maturity_date").cast(pl.Date) - pl.lit(reporting_date))
            .dt.total_days()
            .cast(pl.Float64)
            / 365.25
        )
        if reporting_date is not None
        else pl.lit(None, dtype=pl.Float64)
    )
    # Deposit original maturity (Art. 237(2)(a) t_orig): the pool's minimum
    # deposit original term (null → permissive when value_date was absent). A
    # deposit with original maturity < 1y and a mismatch is zeroed downstream.
    original_expr = pl.col("_pool_deposit_orig_maturity")

    # Build synthetic collateral rows — currency and denomination from the pool
    # (source of funds). maturity_date / residual_maturity_years /
    # original_maturity_years are the DEPOSIT's (Art. 219/237-238), not the
    # beneficiary loan's.
    synthetic = allocated.select(
        (pl.lit("NETTING_") + pl.col("exposure_reference")).alias("collateral_reference"),
        pl.lit("cash").alias("collateral_type"),
        pl.col("_pool_currency").alias("currency"),
        pl.col("_pool_original_currency").alias("original_currency"),
        pl.col("_pool_deposit_maturity_date").alias("maturity_date"),
        pl.col("market_value"),
        pl.lit(None).cast(pl.Float64).alias("nominal_value"),
        pl.lit(None).cast(pl.Float64).alias("pledge_percentage"),
        pl.lit("loan").alias("beneficiary_type"),
        pl.col("exposure_reference").alias("beneficiary_reference"),
        pl.lit(None).cast(pl.Int8).alias("issuer_cqs"),
        pl.lit(None).cast(pl.String).alias("issuer_type"),
        residual_expr.alias("residual_maturity_years"),
        original_expr.alias("original_maturity_years"),
        pl.lit(True).alias("is_eligible_financial_collateral"),
        pl.lit(True).alias("is_eligible_irb_collateral"),
        pl.lit(None).cast(pl.Date).alias("valuation_date"),
        pl.lit(None).cast(pl.String).alias("valuation_type"),
        pl.lit(None).cast(pl.String).alias("property_type"),
        pl.lit(None).cast(pl.Float64).alias("property_ltv"),
        pl.lit(None).cast(pl.Boolean).alias("is_income_producing"),
        pl.lit(None).cast(pl.Boolean).alias("is_adc"),
        pl.lit(None).cast(pl.Boolean).alias("is_presold"),
    )

    return synthetic


def _record_cross_counterparty_netting(
    exposures: pl.LazyFrame,
    errors: list[CalculationError],
    perimeter_is_agreement: bool,
) -> None:
    """Emit one CRM016 warning per netting agreement that spans >1 counterparty.

    The trigger is the same in both perimeter states: an agreement carrying both
    a deposit and a positive loan whose counterparty cannot be positively
    confirmed — more than one distinct counterparty, OR any null counterparty.
    Only the WORDING varies. Under the agreement perimeter the offset IS applied
    and the warning is the audit record that Art. 205(a) enforceability against
    every party must be evidenced; with the Feature disabled the offset is
    refused and the message says so. Targeted collect of the offending
    agreements (the accepted DQ-emission idiom, P1.264).
    """
    is_deposit = pl.col("drawn_amount") < 0
    is_positive_loan = (pl.col("exposure_type") == "loan") & (pl.col("on_bs_for_ead") > 0)
    spanning = (
        exposures.filter(
            pl.col("netting_agreement_reference").is_not_null() & (is_deposit | is_positive_loan)
        )
        .group_by("netting_agreement_reference")
        .agg(
            pl.col("counterparty_reference").drop_nulls().n_unique().alias("_n_cp"),
            pl.col("counterparty_reference").is_null().any().alias("_has_null_cp"),
            is_deposit.sum().alias("_n_deposit"),
            is_positive_loan.sum().alias("_n_positive"),
        )
        .filter(
            ((pl.col("_n_cp") > 1) | pl.col("_has_null_cp"))
            & (pl.col("_n_deposit") > 0)
            & (pl.col("_n_positive") > 0)
        )
        .select("netting_agreement_reference", "_n_cp", "_has_null_cp")
        .collect()
    )
    refused_tail = (
        "could not be confined to a single confirmed counterparty (cross-counterparty "
        "or null-counterparty rows present); on-balance-sheet netting is limited to "
        "reciprocal balances with one counterparty (Art. 195), so those offsets are "
        "disallowed."
    )
    for row in spanning.iter_rows(named=True):
        agr = row.get("netting_agreement_reference")
        null_cp = " and an unconfirmed (null) counterparty" if row["_has_null_cp"] else ""
        tail = (
            f"nets reciprocal balances across {row['_n_cp']} counterparties{null_cp} on "
            "the agreement-perimeter basis (Art. 195, Feature "
            "on_bs_netting_perimeter_is_agreement); Art. 205(a) legal enforceability "
            "against every party under the agreement must be evidenced."
            if perimeter_is_agreement
            else refused_tail
        )
        errors.append(
            crm_warning(
                ERROR_CROSS_COUNTERPARTY_NETTING,
                f"Netting agreement '{agr}' {tail}",
                regulatory_reference="CRR Art. 195",
            )
        )
