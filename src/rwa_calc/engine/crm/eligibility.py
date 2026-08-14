"""
Eligibility of financial collateral — the Art. 197 closed list, shared by both methods.

Pipeline position:
    CRMProcessor -> {compute_fcsm_columns (Art. 222 Simple Method),
                     HaircutCalculator.apply_haircuts (Art. 223 Comprehensive)}

Key responsibilities:
- Hold ONE definition of each Art. 197 eligibility limb, so the Simple Method
  and the Comprehensive Method cannot recognise different collateral. The
  article's own heading is "Eligibility of collateral under **all approaches
  and methods**", and Art. 222(2) recognises only "eligible collateral".
- Parametrise the equity limb by CRM method — the ONE limb where the two
  methods legitimately differ. Art. 197(1)(f) admits "equities or convertible
  bonds that are included in a main index" under every method; Art. 198(1)(a)
  extends that to equity "not included in a main index but traded on a
  recognised exchange" only "where an institution uses the Financial Collateral
  Comprehensive Method set out in Article 223".
- Normalise ``collateral_type`` / ``issuer_type`` to the lookup vocabulary both
  the eligibility gate and the Art. 224 haircut table join key on.

Every attestation column is read conservatively: absent or null resolves to
False, because the absence of an attestation must never fabricate eligibility.

References:
- CRR / PS1-26 Art. 197: eligibility of collateral under all approaches and methods
- CRR / PS1-26 Art. 198: additional eligibility under the Comprehensive Method
- CRR / PS1-26 Art. 207(2): financial-collateral requirements — the obligor's own
  covered bonds qualify only when posted for a repurchase transaction
- CRR / PS1-26 Art. 218: credit-linked notes treated as cash collateral
- CRR / PS1-26 Art. 222: Financial Collateral Simple Method
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import (
    CREDIT_LINKED_NOTE_COLLATERAL_TYPES,
    EQUITY_COLLATERAL_TYPES,
    REAL_ESTATE_COLLATERAL_TYPES,
    RECEIVABLE_COLLATERAL_TYPES,
)
from rwa_calc.domain.enums import CRMCollateralMethod

logger = logging.getLogger(__name__)


@cites("CRR Art. 197")
def financial_collateral_ineligible_expr(
    schema_names: Iterable[str], *, method: CRMCollateralMethod
) -> pl.Expr:
    """True where a collateral row is NOT eligible financial collateral.

    The union of the three instrument-level gates below, evaluated against the
    RAW collateral columns (``collateral_type`` / ``issuer_type`` / ``issuer_cqs``
    plus the optional attestation flags), so it can be applied on either side of
    the Art. 224 haircut lookup.

    ``method`` selects the equity limb only — see ``equity_ineligible_expr``.
    Every other limb is Art. 197 / Art. 207, which bind under all approaches and
    methods, so they are method-invariant by construction.
    """
    names = list(schema_names)
    return (
        debt_security_ineligible_expr(names)
        | equity_ineligible_expr(names, method=method)
        | credit_linked_note_ineligible_expr(names)
    )


@cites("CRR Art. 197")
@cites("CRR Art. 207")
def debt_security_ineligible_expr(schema_names: Iterable[str]) -> pl.Expr:
    """Art. 197(1)(b)/(d)/(h) and Art. 207(2): the debt-security eligibility gate.

    - Art. 197(1)(b): a central-government / central-bank security is eligible
      only with an ECAI assessment at CQS 4 or above, so CQS 5-6 and unrated are
      out.
    - Art. 197(1)(d): a security issued by "other entities" (the engine's
      corporate / institution / PSE bucket) needs CQS 3 or above, so CQS 4-6 and
      unrated are out.
    - Art. 207(2): a covered bond is not in the Art. 197(1) closed list at all —
      it qualifies only when "posted as collateral for a repurchase
      transaction". A frame that does not carry the exposure's SFT flag cannot
      confirm the repo condition, so the row is ineligible (P1.96).
    - Art. 197(1)(h): a securitisation position is eligible only where it is not
      a resecuritisation AND carries a risk weight of 100% or lower. A null risk
      weight cannot confirm the <=100% condition, and a CQS outside 1-3 has no
      Art. 224 Table 1 securitisation haircut, so both are ineligible.

    Shared by ``HaircutCalculator.apply_haircuts`` (which additionally assigns a
    100% haircut to a gated row) and by the Art. 222 Simple Method's eligible-
    collateral filter.
    """
    names = set(schema_names)
    lookup_type = normalise_collateral_type_expr()
    cqs_val = pl.col("issuer_cqs")

    is_govt = lookup_type == "govt_bond"
    is_corp = lookup_type == "corp_bond"
    ineligible = (is_govt & ((cqs_val >= 5) | cqs_val.is_null())) | (
        is_corp & ((cqs_val >= 4) | cqs_val.is_null())
    )

    is_raw_covered_bond = pl.col("collateral_type").str.to_lowercase() == "covered_bond"
    ineligible = ineligible | (
        is_raw_covered_bond & _attestation_expr(names, "exposure_is_sft").not_()
    )

    sec_rw = _optional_float_expr(names, "securitisation_position_risk_weight")
    ineligible = ineligible | (
        (lookup_type == "securitisation")
        & (
            _attestation_expr(names, "is_resecuritisation")
            | sec_rw.is_null()
            | (sec_rw > 1.0)
            | cqs_val.is_null()
            | (cqs_val >= 4)
        )
    )
    return ineligible


@cites("CRR Art. 197")
@cites("CRR Art. 198")
def equity_ineligible_expr(schema_names: Iterable[str], *, method: CRMCollateralMethod) -> pl.Expr:
    """Art. 197(1)(f) / 198(1)(a): the equity eligibility gate, by CRM method.

    Under the **Simple Method** the gate is Art. 197(1)(f) ALONE — only equity
    "included in a main index" is eligible collateral. Art. 198(1)(a)'s
    extension to non-main-index equity "traded on a recognised exchange" opens
    with "where an institution uses the Financial Collateral Comprehensive
    Method set out in Article 223", so listing does not rescue an Art. 222
    pledge.

    Under the **Comprehensive Method** the gate is the Art. 197 ∪ Art. 198
    union: a non-main-index equity survives when it is attested listed.

    Null / absent ``is_main_index`` and ``is_listed`` resolve conservatively to
    False (unknown membership / listing must not fabricate eligibility). When
    neither signal column is present the expression is a no-op (``False``): that
    is the legacy backward-compatibility path where ``is_eligible_financial_
    collateral`` remains the eligibility proxy — production always carries both
    columns via ``COLLATERAL_SCHEMA``.

    Shared by the haircut-stage value gate (``HaircutCalculator``), the CRM018
    warning emission (``engine/crm/collateral.py``) and the Art. 222 Simple
    Method filter, so the predicate has a single definition. It reads the raw
    ``collateral_type`` (equivalent to the normalised ``_lookup_type ==
    "equity"``).
    """
    names = set(schema_names)
    if "is_main_index" not in names and "is_listed" not in names:  # arch-exempt: legacy no-op
        return pl.lit(False)

    is_equity = pl.col("collateral_type").str.to_lowercase().is_in(EQUITY_COLLATERAL_TYPES)
    gate = is_equity & _attestation_expr(names, "is_main_index").not_()
    if method is CRMCollateralMethod.COMPREHENSIVE:
        gate = gate & _attestation_expr(names, "is_listed").not_()
    return gate


@cites("CRR Art. 218")
def credit_linked_note_ineligible_expr(schema_names: Iterable[str]) -> pl.Expr:
    """Art. 218: a credit-linked note is cash collateral only if own-issued.

    A credit-linked note earns cash-collateral treatment (0% haircut, full
    EAD/LGD* offset) under CRR/PS1-26 Art. 218 only when it is ISSUED BY THE
    LENDING INSTITUTION itself — the note's cash proceeds fund the protection. A
    CLN issued by a THIRD PARTY is not within Art. 218: its value is materially
    correlated with the reference entity (typically the obligor — Art. 194(4)
    wrong-way risk), so it is ineligible funded protection.

    A ``credit_linked_note`` collateral row that is not attested own-issued
    (``is_own_issued_cln`` False or null) is therefore ineligible. Null / absent
    resolves conservatively to False (absence of attestation must not fabricate
    cash treatment). When the ``is_own_issued_cln`` column is not present the
    expression is a no-op (``False``): the legacy backward-compatibility path
    where every CLN retained cash treatment — production always carries the
    column via ``COLLATERAL_SCHEMA``.

    Shared by the haircut-stage value gate (``HaircutCalculator.apply_haircuts``),
    the CRM019 warning emission (``engine/crm/collateral.py``) and the Art. 222
    Simple Method filter, so the predicate has a single definition. It reads the
    raw ``collateral_type``.
    """
    names = set(schema_names)
    if "is_own_issued_cln" not in names:  # arch-exempt: legacy no-op
        return pl.lit(False)
    is_cln = pl.col("collateral_type").str.to_lowercase().is_in(CREDIT_LINKED_NOTE_COLLATERAL_TYPES)
    return is_cln & _attestation_expr(names, "is_own_issued_cln").not_()


def normalise_collateral_type_expr() -> pl.Expr:
    """Map collateral_type aliases to canonical types for eligibility / haircut lookup.

    ``issuer_type`` is read through ``fill_null("")`` so an all-null column
    (dtype ``Null`` on a synthetic frame) still resolves as String — the same
    idiom ``_derive_collateral_rw_expr`` uses. A null issuer matched no branch
    before and matches none now.
    """
    ct = pl.col("collateral_type").str.to_lowercase()
    issuer = pl.col("issuer_type").fill_null("").str.to_lowercase()
    return (
        pl.when(ct.is_in(["cash", "deposit", "credit_linked_note"]))
        .then(pl.lit("cash"))
        .when(ct == "gold")
        .then(pl.lit("gold"))
        .when(ct == "life_insurance")
        .then(pl.lit("life_insurance"))
        .when(
            ct.is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
            | ((ct == "bond") & (issuer == "sovereign"))
        )
        .then(pl.lit("govt_bond"))
        # CRR / PS1-26 Art. 197(1)(h): securitisation positions are a distinct
        # eligible-collateral class with the Art. 224 Table 1 securitisation
        # haircut (2x corporate). Keyed on collateral_type/issuer_type; the
        # RW<=100% + non-resecuritisation eligibility gate is applied above.
        .when((ct == "securitisation") | ((ct == "bond") & (issuer == "securitisation")))
        .then(pl.lit("securitisation"))
        .when(ct.is_in(["corp_bond", "corporate_bond", "covered_bond"]))
        .then(pl.lit("corp_bond"))
        .when((ct == "bond") & issuer.is_in(["corporate", "pse", "institution"]))
        .then(pl.lit("corp_bond"))
        .when(ct.is_in(["equity", "shares", "stock"]))
        .then(pl.lit("equity"))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit("receivables"))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit("real_estate"))
        .otherwise(pl.lit("other_physical"))
    )


def _attestation_expr(names: set[str], column: str) -> pl.Expr:
    """A boolean attestation, conservatively False when the column is absent or null."""
    return pl.col(column).fill_null(False) if column in names else pl.lit(False)


def _optional_float_expr(names: set[str], column: str) -> pl.Expr:
    """A float column, or a null literal when the frame does not carry it."""
    return pl.col(column) if column in names else pl.lit(None, dtype=pl.Float64)
