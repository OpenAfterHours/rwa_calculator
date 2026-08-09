"""
Per-leg carrier allocation for the real-estate loan-splitter's child rows.

Pipeline position:
    CRMProcessor -> RealEstateSplitter (re_split/splitter.py) -> SA Calculator
    Pure expression-builder sub-module of the ``re_split`` stage package; its
    only callers are ``splitter._secured_columns`` and
    ``splitter._residual_columns``.

Why this module exists:
    ``engine/registry.py`` orders ``crm_processor`` BEFORE ``re_splitter``, so
    every per-exposure money carrier the CRM stage wrote is already on the
    parent row when the split happens. A carrier the splitter does not
    explicitly rewrite is inherited WHOLE by every emitted leg and then
    double-counts in every downstream sum: COREP C 07.00 col 0010 and
    Pillar 3 CR4 cols a/b are derived from ``drawn_amount`` / ``interest`` /
    ``nominal_amount`` / ``undrawn_amount``, so a split loan was filed at twice
    its book value. This module is the single auditable place where each
    carrier is classified.

Key responsibilities:
- ``alloc_share_expr`` — the ONE allocation basis: the leg's share of the
  parent EAD. ``scale_provision_expr`` is expressed in terms of it so the
  provision allocation and the carrier allocation cannot drift apart.
- ``secured_carrier_exprs`` / ``residual_carrier_exprs`` — the ``with_columns``
  fragment for one secured / residual child row.
- The membership constants below: the classification itself.

How the sets below were derived — the completeness criterion, so a future
editor extends them the same way rather than guessing: every ``Float64``
column on ``contracts/edges.py::RE_SPLIT_EXIT_EDGE`` (and its CCR twin
``RE_SPLIT_EXIT_CCR_EDGE``) was enumerated and classified explicitly into one
of the three classes below. Naming money columns from memory is how the first
pass missed fifteen of them. A new Float64 column on that contract must be
classified here.

The three classes of carrier:

- **Allocated pro-rata** (``_PRORATA_CARRIERS``) — extensive money amounts,
  multiplied by the leg's share of the parent EAD. Columns that participate in
  a common ratio, sum or difference are allocated TOGETHER so the relation is
  exactly invariant under the split; the constant's comments name each such
  group.
- **Real-estate collateral** (``_RE_COLLATERAL_CARRIERS`` /
  ``_RESIDENTIAL_ONLY_CARRIERS`` / ``_COMMERCIAL_ONLY_CARRIERS``) — attributed
  to the secured leg(s) only. The residual leg carries no property value: it
  sits at the counterparty risk weight *precisely because* it is the
  uncollateralised remainder, so attributing property value to it would
  contradict its own risk weight, and the Pillar 3 CR7a collateral column
  pairs the value against the exposure on the same row.
- **Inherited** — everything else, deliberately absent from every constant.
  Summing them is meaningless and scaling them would be a bug. Four kinds,
  with the judgement calls named so they read as decided rather than missed:

  * *Rates and per-unit fractions* — ``lgd`` / ``lgd_pre_crm`` /
    ``lgd_post_crm`` / ``lgd_secured`` / ``lgd_unsecured``, every ``ccf*``,
    ``pd`` / ``internal_pd`` / ``guarantor_pd`` / ``guarantor_internal_pd``,
    ``exposure_volatility_haircut``, ``guarantee_ratio``,
    ``guarantee_fx_haircut``, ``guarantee_restructuring_haircut``,
    ``collateral_coverage_pct``, ``securitisation_residual_pct``,
    ``fx_rate_applied``, ``supporting_factor``, the substitution risk weights
    (``fcsm_collateral_rw`` / ``life_ins_secured_rw`` /
    ``third_party_deposit_secured_rw``), the maturities
    (``effective_maturity``, ``original_maturity_years``,
    ``exposure_security_residual_maturity_years``) and, on a CCR row,
    ``pfe_multiplier`` / ``alpha_applied`` / ``ccr_effective_maturity`` /
    ``ccr_modelled_lgd`` / ``wwr_lgd_override``.
  * ``beel`` — a RATE despite the name: ``engine/irb/adjustments.py`` reads it
    as ``max(0, lgd_floored - beel)`` and ``beel * ead_final``, i.e. a fraction
    of EAD alongside LGD, not an amount.
  * ``el_estimate`` / ``el_dilution_estimate`` — also RATES, not amounts.
    CRR Art. 160(2) top-down: ``PD = EL / LGD`` for senior and ``PD = EL`` for
    subordinated claims, so EL here is a fraction of exposure. The derivation
    in ``engine/stages/classify/subtypes.py`` caps the quotient at 1.0 because
    an EL rate exceeding the supervisory LGD would otherwise yield a PD above
    one. Scaling them would move a PD. (No rate is quoted here on purpose —
    the LGD lives in the rulepack; engine prose must not restate a pack
    value.)
  * *Counterparty / lending-group aggregates* — ``e_star_group_drawn``,
    ``lending_group_total_exposure``, ``lending_group_adjusted_exposure``,
    ``total_cp_drawn``, plus the counterparty attributes
    ``cp_annual_revenue``, ``cp_total_assets`` and ``sme_size_metric_gbp``.
    These are already-summed group quantities (``.sum().over(...)`` at
    ``engine/stages/hierarchy/enrich.py:516-520``) or counterparty attributes,
    carried per row solely as THRESHOLD COMPARANDS (the CRR Art. 123 retail
    limit, the CRR Art. 501 E* test). Scaling a comparand by the leg's share
    breaks the test it feeds; the per-row duplication is inherent to the design
    and predates any split (three loans to one counterparty already carry
    three copies).
  * *Per-row drawn restatements, inherited only because nothing reads them
    after the split* — ``total_exposure_amount`` and
    ``exposure_for_retail_threshold``. These are NOT group aggregates, and it
    is worth being blunt about it because the earlier version of this
    docstring said they were: ``enrich.py:357`` sets
    ``total_exposure_amount = drawn_amount.clip(lower=0)``, so it is a copy of
    a column this module DOES allocate, and ``exposure_for_retail_threshold``
    is derived from it per row. Leaving them whole therefore makes a leg carry
    an allocated ``drawn_amount`` beside an unallocated restatement of it —
    the same inconsistency this module exists to remove. It is inert only
    because both are consumed upstream of the split (``enrich.py:424`` and the
    group sums at :516-520) and no post-split reader exists. If a post-split
    consumer is ever added, MOVE THEM TO ``_PRORATA_CARRIERS`` rather than
    reasoning about them as aggregates.
  * *Splitter decision provenance* — ``re_split_mode``,
    ``re_split_target_class``, ``re_split_property_type``,
    ``re_split_property_value``, ``re_split_residential_value``,
    ``re_split_commercial_value``, ``re_split_force_other_re``,
    ``prior_charge_ltv``. The classifier's finding ABOUT THE PARENT, retained
    as the audit trail for why the split happened. Nothing downstream sums
    them.

Nulls are propagated, never filled: ``null * share`` stays null, so an unknown
amount does not silently become a conservative-looking zero on every leg.

References:
- CRR Art. 124(1), first subparagraph, second sentence: "The part of the
  exposure that exceeds the mortgage value of the immovable property shall be
  assigned the risk weight applicable to the unsecured exposures of the
  counterparty involved." (Paragraph 1 has two subparagraphs and no third; the
  SECOND subparagraph is the separate pledged-amount cap.)
- PS1/26 Art. 124F(1)(b): the revised-regime equivalent — "the risk weight of
  the counterparty shall be applied to the residual part of the exposure, if
  any, in accordance with Article 124L". Art. 124L(e) in turn defines that as
  the weight for an "unsecured exposure to that counterparty". Both regimes
  therefore call the residual UNSECURED in the text, which is why it carries
  no property value.
- PS1/26 Art. 124L: PRA counterparty-type residual risk-weight table — the
  reason the residual leg is emitted at all under the revised regime.
- CRR Art. 125 / CRR Art. 126: the CRR-regime secured-leg treatments. Both are
  "[Note: Provision left blank]" in PS1/26, i.e. deleted under Basel 3.1 —
  which is why the revised regime needs its own pair below rather than sharing
  these.
- PS1/26 Art. 124F / PS1/26 Art. 124H: the Basel 3.1 secured-leg treatments,
  and the direct rule-level authority for splitting at all — Art. 124F(1)
  assigns one weight to "the part of the exposure up to 55% of the value of
  the property" and another to "the residual part". The split is in the rules,
  not an engine artefact.
- CRR Art. 123 / CRR Art. 501: the retail limit and the SME supporting-factor
  E* test, named above as the threshold comparands whose carriers stay whole.
  PS1/26 removes the Art. 501/501a factors, so that limb is CRR-only.
"""

from __future__ import annotations

import logging

import polars as pl

logger = logging.getLogger(__name__)

#: SET 1 -- extensive (money) carriers allocated PRO-RATA by the leg's share of
#: the parent EAD.
#:
#: Ratio-closure groups (members must move together or a downstream ratio
#: shifts):
#: - ``drawn_amount`` + ``facility_limit``: ``engine/sa/rw_adjustments.py``
#:   rescales the PS1/26 Art. 123B(2A) hedge coverage by
#:   ``drawn / max(drawn, facility_limit)``. Scaling both leaves it invariant;
#:   scaling only ``drawn_amount`` would shrink coverage by the leg share, stop
#:   the 90% waiver firing and apply the 1.5x currency-mismatch multiplier to
#:   legs it does not touch today. Note ``facility_limit`` IS therefore split
#:   pro-rata, and is deliberately kept OUT of
#:   ``data/schemas.py::ADDITIVE_OUTPUT_FIELDS``: the collapse takes
#:   ``.first()`` for it, so the collapsed parent shows one leg's share rather
#:   than the facility limit. That is acceptable ONLY because nothing reads it
#:   off the collapsed frame — verified: no reader in ``analysis/`` or
#:   ``reporting/``, the sole post-split consumer being the invariant ratio
#:   above. It is NOT justified by "a limit should not sum across legs"; that
#:   argument would tell against allocating it at all, and the ratio forbids
#:   that.
#: - ``guaranteed_portion`` + ``unguaranteed_portion``: the SA substitution
#:   blend is ``(unguaranteed * borrower_rw + guaranteed * guarantor_rw) /
#:   ead_final``. ``ead_final`` is the LEG EAD, so both portions must carry the
#:   same share for the blended risk weight to equal the parent's.
#: - ``total_collateral_for_lgd`` + every ``crm_alloc_*``: ``engine/irb/
#:   formulas.py`` relies on ``sum(crm_alloc_*) == total_collateral_for_lgd
#:   <= ead_for_crm`` for the LGD* convexity invariant, so ``ead_for_crm``
#:   belongs to the same group.
#: - ``ead_gross`` + ``provision_deducted`` (with ``provision_allocated``,
#:   allocated by ``scale_provision_expr``): the defaulted-exposure provision
#:   coverage test compares the allocated provision against
#:   ``ead_gross + provision_deducted``. All three share one basis.
#: - ``fcsm_collateral_value`` / ``life_ins_collateral_value`` /
#:   ``third_party_deposit_value``: each drives a substitution blend in
#:   ``engine/sa/rw_adjustments.py`` through
#:   ``secured_pct = clip(value / ead_final, 0, 1)``. ``ead_final`` is the LEG
#:   EAD, so an unallocated value inflates the ratio by 1/share and clips to
#:   1.0 — the leg would be treated as fully secured and take the collateral
#:   risk weight outright. Allocating the value restores ``V / E``.
#: - ``collateral_market_value`` + ``collateral_adjusted_value``: a DIFFERENCE
#:   closure. ``reporting/corep/c07.py`` derives the volatility / maturity
#:   adjustment as ``market - adjusted``; moving one and not the other
#:   manufactures a phantom adjustment.
#: - ``on_bs_for_ead`` + ``ead_from_ccf`` + ``ead_pre_crm``: a SUM closure.
#:   ``engine/ccf.py`` builds ``ead_pre_crm = on_bs_for_ead + ead_from_ccf``
#:   and ``ead_from_ccf = nominal_after_provision * ccf`` (``ccf`` is a rate,
#:   inherited), so all four money terms move together.
#: - ``drawn_amount`` / ``nominal_amount`` + ``provision_on_drawn`` /
#:   ``provision_on_nominal``: ``engine/crm/guarantees.py`` and COREP C 07.00
#:   col 0040 reconstruct the net basis as ``drawn - provision_on_drawn`` and
#:   ``nominal - provision_on_nominal``.
#: - Every ``collateral_*_value`` and its ``collateral_*_market_value`` twin:
#:   ``engine/aggregator/aggregator.py`` picks between the adjusted and the
#:   market basis per reporting view, so allocating one half of a pair would
#:   make the reported amount depend on which basis the template chose.
#:
#: Their risk-weight partners (``fcsm_collateral_rw``, ``life_ins_secured_rw``,
#: ``third_party_deposit_secured_rw``, ``guarantor_rw``,
#: ``pre_crm_risk_weight``) are RATES and are deliberately inherited.
_PRORATA_CARRIERS: tuple[str, ...] = (
    # Contractual / balance-sheet amounts (the reporting gross projection).
    "drawn_amount",
    "interest",
    "undrawn_amount",
    "nominal_amount",
    "original_amount",
    "on_bs_for_ead",
    "nominal_after_provision",
    "facility_limit",
    "on_bs_netting_amount",
    # EAD waterfall snapshots.
    "ead_from_ccf",
    "ead_modelled",
    "ead_gross",
    "ead_pre_crm",
    "ead_for_crm",
    "ead_after_collateral",
    "ead_after_guarantee",
    # Provisions (``provision_allocated`` is written by scale_provision_expr).
    "provision_deducted",
    "provision_on_drawn",
    "provision_on_nominal",
    # Own-funds deductions summed by engine/aggregator/_el_summary.py.
    "ava_amount",
    "other_own_funds_reductions",
    # Guarantee amounts -- ``guaranteed_portion`` / ``unguaranteed_portion``
    # are one ratio-closure group with ``ead_final``.
    "guarantee_amount",
    "original_guarantee_amount",
    "guaranteed_portion",
    "unguaranteed_portion",
    # Non-RE / aggregate CRM amounts. Every ``*_value`` is paired with its
    # ``*_market_value`` twin -- the reporting basis differs per view.
    "collateral_adjusted_value",
    "collateral_market_value",
    "collateral_allocated",
    "collateral_financial_value",
    "collateral_financial_market_value",
    "collateral_cash_value",
    "collateral_cash_market_value",
    "collateral_other_physical_value",
    "collateral_other_physical_market_value",
    "collateral_receivables_value",
    "collateral_receivables_market_value",
    "collateral_life_insurance_market_value",
    "total_collateral_for_lgd",
    "crm_alloc_financial",
    "crm_alloc_covered_bond",
    "crm_alloc_receivables",
    "crm_alloc_real_estate",
    "crm_alloc_other_physical",
    "crm_alloc_life_insurance",
    # Substitution collateral values -- each one half of a ``V / ead_final``
    # secured-percentage ratio in engine/sa/rw_adjustments.py.
    "fcsm_collateral_value",
    "life_ins_collateral_value",
    "third_party_deposit_value",
    # CRR Art. 200(1) other-funded-credit-protection AMOUNTS. The ``lgd`` in two of
    # the names is a misnomer -- engine/aggregator/aggregator.py aliases all
    # three straight to the ``reporting_ofcp_*`` money columns on C 08.01.
    "ofcp_lgd_cash_deposit",
    "ofcp_lgd_life_insurance",
    "ofcp_substitution_amount",
    # SA-CCR amounts, present only on a CCR run (schema-guarded, so a no-op
    # elsewhere). No CCR row currently reaches the split -- the classifier
    # flags candidates from property collateral -- but if one ever did, these
    # must move with ``ead_final`` for ``ead_ccr = alpha x (rc + pfe_addon)``
    # to survive. ``alpha_applied`` / ``pfe_multiplier`` are rates, inherited.
    "rc",
    "rc_margined",
    "rc_unmargined",
    "addon_aggregate",
    "pfe_addon",
    "transitional_add_on",
    "ead_ccr",
)

#: SET 2a -- combined RRE+CRE real-estate collateral carriers. Secured leg(s)
#: only. A mixed split divides them by each component's share of the eligible
#: property value; a single-component split gives the whole value to its one
#: secured leg.
_RE_COLLATERAL_CARRIERS: tuple[str, ...] = (
    "collateral_re_value",
    "collateral_re_market_value",
)

#: SET 2b -- RESIDENTIAL-only real-estate collateral carriers. They may land on
#: a residential secured leg only: null on a commercial secured leg (they
#: describe a pledge that leg is not secured on) and null on the residual.
_RESIDENTIAL_ONLY_CARRIERS: tuple[str, ...] = (
    "residential_collateral_value",
    "residential_collateral_value_uncapped",
)

#: SET 2c -- COMMERCIAL-only real-estate collateral carriers: the exact mirror
#: of SET 2b, handled symmetrically. ``flagging.py`` reads the two ``*_uncapped``
#: columns as a pair on adjacent lines, so an asymmetry between them is a
#: defect on its face -- which is how the commercial half was missed once.
#:
#: CONSERVATION CAVEAT for SETS 2b/2c. "Sum over the legs recovers the parent"
#: holds only when the matching component actually emits a secured leg. A
#: single-component split nulls the OTHER component's carriers on the secured
#: leg it does emit and on the residual, so with no leg to receive them the
#: ledger sum is 0.0 rather than the parent value. Measured on a CRR mixed
#: RRE+CRE parent, where the CRE component fails the CRR Art. 126(2)(d) rental
#: gate and no CRE leg is emitted: ``commercial_collateral_value_uncapped``
#: sums to 0.0 against a parent 1,200,000 (pre-fix it summed to 2,400,000, so
#: neither state was right). Numerically inert today -- the only consumer,
#: ``flagging.py:150-151``, reads the PARENT before the split -- but do not
#: state the conservation invariant unconditionally for these two sets.
_COMMERCIAL_ONLY_CARRIERS: tuple[str, ...] = ("commercial_collateral_value_uncapped",)

#: SET 2 members ``splitter._residual_columns`` already nulls in its own
#: override list, unconditionally, so an older fixture that lacks the column
#: still receives it as a typed null. Excluded from the generated residual
#: nulls: two expressions aliasing the same name inside one ``with_columns``
#: is a Polars error.
_RESIDUAL_PRE_NULLED: frozenset[str] = frozenset({"residential_collateral_value"})

#: Splitter temp column flagging a parent whose split emitted BOTH a
#: ``secured_rre`` and a ``secured_cre`` leg.
_IS_MIXED_COL = "_re_is_mixed"


def secured_carrier_exprs(
    *,
    schema_names: set[str],
    parent_ead_col: str,
    secured_ead_col: str,
    component_value_col: str,
    other_component_value_col: str,
    is_residential_component: bool,
) -> list[pl.Expr]:
    """Carrier-allocation fragment for ONE secured child row.

    Args:
        schema_names: Columns present on the frame entering the splitter. A
            carrier absent from it produces no expression — the splitter is
            also exercised by pre-classifier unit fixtures and by CCR runs
            with a different column set.
        parent_ead_col: The parent EAD column (the allocation denominator).
        secured_ead_col: This component's secured-EAD temp column.
        component_value_col: This component's eligible property-value temp.
        other_component_value_col: The other component's property-value temp.
        is_residential_component: True for the RRE leg. Selects which
            single-type collateral family this leg keeps and which it nulls.

    Returns:
        The ``with_columns`` expression list. Disjoint from the splitter's own
        override list, so the two can be concatenated.
    """
    share = alloc_share_expr(numerator=secured_ead_col, parent_ead_col=parent_ead_col)
    exprs = [(pl.col(col) * share).alias(col) for col in _PRORATA_CARRIERS if col in schema_names]

    re_share = _re_value_share_expr(
        component_value_col=component_value_col,
        other_component_value_col=other_component_value_col,
    )
    exprs.extend(
        (pl.col(col) * re_share).alias(col)
        for col in _RE_COLLATERAL_CARRIERS
        if col in schema_names
    )

    # This leg keeps its own single-type carriers whole and nulls the other
    # component's: they describe a pledge this leg is not secured on.
    other_component_only = (
        _COMMERCIAL_ONLY_CARRIERS if is_residential_component else _RESIDENTIAL_ONLY_CARRIERS
    )
    exprs.extend(_null_float(col) for col in other_component_only if col in schema_names)
    return exprs


def residual_carrier_exprs(
    *,
    schema_names: set[str],
    parent_ead_col: str,
    residual_ead_col: str,
) -> list[pl.Expr]:
    """Carrier-allocation fragment for the residual child row.

    The residual takes its pro-rata share of every extensive carrier and NO
    real-estate collateral value: it carries the counterparty risk weight
    exactly because it is the uncollateralised remainder.
    """
    share = alloc_share_expr(numerator=residual_ead_col, parent_ead_col=parent_ead_col)
    exprs = [(pl.col(col) * share).alias(col) for col in _PRORATA_CARRIERS if col in schema_names]
    exprs.extend(
        _null_float(col)
        for col in _RE_COLLATERAL_CARRIERS + _RESIDENTIAL_ONLY_CARRIERS + _COMMERCIAL_ONLY_CARRIERS
        if col in schema_names and col not in _RESIDUAL_PRE_NULLED
    )
    return exprs


def alloc_share_expr(*, numerator: str, parent_ead_col: str) -> pl.Expr:
    """The leg's share of the parent EAD — the single allocation basis.

    Zero when the parent carries no EAD, so a zero-EAD parent allocates
    nothing rather than dividing by zero. Every allocated carrier and the
    provision allocation read this one expression.
    """
    parent_ead = pl.col(parent_ead_col).fill_null(0.0)
    return (
        pl.when(parent_ead > 0.0)
        .then(pl.col(numerator).fill_null(0.0) / parent_ead)
        .otherwise(pl.lit(0.0))
    )


def scale_provision_expr(*, numerator: str, parent_ead_col: str) -> pl.Expr:
    """Allocate provisions pro-rata to the child row's EAD share.

    Shares ``alloc_share_expr``'s basis. A null parent ``provision_allocated``
    deliberately becomes ``0.0`` (long-standing behaviour, preserved
    verbatim): the provision columns are a deduction, where a null means "no
    provision" rather than "unknown". The allocated carriers propagate their
    nulls instead — see the module docstring.
    """
    return pl.col("provision_allocated").fill_null(0.0) * alloc_share_expr(
        numerator=numerator, parent_ead_col=parent_ead_col
    )


def _re_value_share_expr(*, component_value_col: str, other_component_value_col: str) -> pl.Expr:
    """This component's share of the eligible property value.

    Only a MIXED split (both components emitted a secured leg) divides the
    combined RRE+CRE collateral carriers; a single-component split attributes
    the whole pledged value to its one secured leg. Guards the zero-total case.
    """
    component_v = pl.col(component_value_col)
    total_v = component_v + pl.col(other_component_value_col)
    mixed_share = pl.when(total_v > 0.0).then(component_v / total_v).otherwise(pl.lit(0.0))
    return pl.when(pl.col(_IS_MIXED_COL)).then(mixed_share).otherwise(pl.lit(1.0))


def _null_float(column: str) -> pl.Expr:
    """A typed Float64 null for ``column`` — the leg carries no such value."""
    return pl.lit(None, dtype=pl.Float64).alias(column)
