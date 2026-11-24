"""
Exposure subtype classification for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (engine/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    after ``attributes.derive_independent_flags`` has set the base
    exposure classes and flags.

Key responsibilities:
- SME / retail / QRRE class mutation (``classify_exposure_subtypes``):
  CORPORATE_SME, RETAIL_QRRE, the obligor-aggregate QRRE limit, is_sme,
  requires_fi_scalar, is_hvcre.
- Art. 147(5) corporate→retail reclassification
  (``reclassify_corporate_to_retail``).
- CRR Art. 160(2)/(6) top-down PD for purchased corporate receivables
  (``derive_purchased_receivables_pd``) — runs before the approach ladder
  because the IRB gate reads ``internal_pd``.
- Re-align ``exposure_class_irb`` with the mutated ``exposure_class``
  (``sync_irb_exposure_class``), excluding RGLA / PSE entity types.
- Derive the Basel 3.1 corporate ``exposure_subclass``
  (``derive_exposure_subclass``).

References:
- CRR Art. 147(5) / Basel CRE30.16-17: corporate→retail reclassification
- CRR Art. 154(4)(a)-(c) / PS1/26 Art. 147(5A)(a)-(c): QRRE assignment —
  individuals, unsecured + unconditionally-cancellable-when-undrawn, aggregate limit
- CRR Art. 4(1)(128D): SME size test (via ``attributes.is_sme_by_size_expr``)
- CRR Art. 147(3)/147(4)(b): RGLA / PSE IRB class exclusion
- CRR Art. 160(2)(a)/(b) + 160(6) / PS1/26 Art. 160(2)/(6): purchased-receivables
  top-down PD (senior EL/LGD, subordinated EL, dilution-risk EL)
- PS1/26, paragraph 147A.1: corporate exposure_subclass three-way split
- PRA PS1/26 Art. 124(3) / Art. 124K: ADC exclusion from CORPORATE_SME
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import RGLA_PSE_ENTITY_TYPES
from rwa_calc.domain.enums import ExposureClass, ExposureSubclass
from rwa_calc.engine.classify.attributes import is_sme_by_size_expr, natural_person_expr
from rwa_calc.engine.classify.re_evidence import RE_UNEVIDENCED_CLASS_COLUMN, re_evidence_expr
from rwa_calc.engine.irb.formulas import firb_supervisory_lgd_values
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.engine.utils import partition_by_nullable
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

#: Scratch column holding each leg's deduplicated contribution to its
#: obligor's Art. 154(4)(c) aggregate — one limit per (obligor, facility the
#: leg is keyed on). Materialised by ``qrre_obligor_aggregate_limit_expr`` and
#: dropped by ``classify_exposure_subtypes`` before it returns, so the classify
#: exit schema is unchanged. It exists because the per-(obligor, facility)
#: deduplication may not sit INSIDE the input of a later window: Polars
#: evaluates a window's input in the outer group-by context, so a nested
#: window re-runs once per outer group (arch_check check 21).
_QRRE_DEDUPED_LIMIT_COLUMN = "_qrre_deduped_limit"

#: Scratch column holding each row's position in the frame, so step 2 can
#: name the first QRRE-candidate leg of an umbrella with an aggregating window.
_QRRE_ROW_INDEX_COLUMN = "_qrre_row_index"

#: Scratch struct column holding step 2's per-(obligor, root facility) terms
#: (P1.355), one field each: ``counted`` (the step-1 limits counted under the
#: umbrella), ``drawn`` (the obligor's drawings under it), ``unmeasured`` (how
#: many of those drawings could not be measured) and ``first_leg`` (the row
#: index of the group's first QRRE-candidate leg, which carries the capped
#: value). ONE window of aggregations over plain inputs, materialised after
#: ``_QRRE_DEDUPED_LIMIT_COLUMN`` for the check-21 reason; one struct rather
#: than four windows because each window wrapped in ``partition_by_nullable``
#: computes its own grouping (measured: four such windows cost ~1.5x one).
_QRRE_UMBRELLA_TERMS_COLUMN = "_qrre_umbrella_terms"

#: Scratch column holding each leg's contribution once the deduplicated
#: limits under one root (umbrella) facility are capped at the root's own
#: limit — one value per (obligor, root facility), P1.355. Built from the
#: step-2 terms above and dropped with them.
_QRRE_UMBRELLA_LIMIT_COLUMN = "_qrre_umbrella_limit"

#: Every scratch column ``qrre_obligor_aggregate_limit_expr`` materialises.
_QRRE_SCRATCH_COLUMNS: tuple[str, ...] = (
    _QRRE_DEDUPED_LIMIT_COLUMN,
    _QRRE_ROW_INDEX_COLUMN,
    _QRRE_UMBRELLA_TERMS_COLUMN,
    _QRRE_UMBRELLA_LIMIT_COLUMN,
)


# =========================================================================
# Exposure subtype classification (4 .with_columns — three passes of QRRE
# aggregate helper columns, then the output expressions — plus a drop of the
# helpers)
# =========================================================================


@cites("CRR Art. 153(2)")
@cites("CRR Art. 142(1)(4)")
@cites("CRR Art. 154(4)")
@cites("CRR Art. 123")
@cites("PS1/26, paragraph 153")
@cites("PS1/26, paragraph 147")
@cites("PS1/26, paragraph 123")
def classify_exposure_subtypes(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Merge SME, retail, and QRRE classification into one output .with_columns().

    Preceded by three ``.with_columns`` that materialise the QRRE aggregate's
    per-leg helper columns (``_QRRE_SCRATCH_COLUMNS``: the per-facility
    deduplicated limit; the per-umbrella terms; the umbrella-capped limit),
    dropped again before this function returns (see
    ``qrre_obligor_aggregate_limit_expr`` for why those steps cannot be folded
    into the output expressions). The classify exit schema is unchanged.

    Works because they operate on non-overlapping initial exposure_class values:
    SME only touches "corporate", retail only touches "retail_other",
    QRRE specialises qualifying revolving retail.

    Also derives ``requires_fi_scalar`` — the gate for the 1.25x asset-value
    correlation multiplier (CRR Art. 153(2) / PS1/26 Art. 153(2)). This is a
    MANDATORY treatment for large financial sector entities, not a user
    election, so it is DERIVED from the entity-type flag and total assets:

        requires_fi_scalar = apply_fi_scalar
                             OR (is_financial_sector_entity
                                 AND total_assets >= threshold)

    The threshold is the LFSE size test (CRR Art. 142(1)(4): EUR 70bn on an
    individual/consolidated basis, converted GBP via the FX seam; PS1/26 IRB
    Part glossary: GBP 79bn native, at the highest level of consolidation).
    The assets basis is the pack Feature ``lfse_assets_at_highest_consolidation``:
    Basel 3.1 reads the group figure ``cp_group_total_assets`` (the glossary:
    "total assets, taken at the highest level of consolidation at which audited
    financial statements are available"); CRR keeps the entity's own
    ``cp_total_assets``, which Art. 142(1)(4)(a) ("calculated on an individual
    or consolidated basis") admits. Assets are GBP figures.
    The user-supplied ``apply_fi_scalar`` is retained as an authoritative
    True-OVERRIDE (a firm may know an entity is a large or UNREGULATED FSE
    even when size data says otherwise) — it can never SUPPRESS a derived
    True. A null ``total_assets`` on a flagged FSE leaves largeness
    undetermined: the scalar is NOT applied (the whole-FSE population mostly
    sits below the threshold), and ``audit.collect_input_warnings`` emits
    CLS009 so the data gap is never a silent under-statement. The unregulated
    FSE limb (Art. 142(1)(5), size-independent) needs a regulated-status input
    the schema does not carry and is deferred to a schema-enablement change;
    ``apply_fi_scalar`` is the interim override for known unregulated FSEs.

    A non-SME RETAIL_OTHER row failing ``qualifies_as_retail`` leaves the retail
    class for CORPORATE only where the pack Feature
    ``non_qualifying_retail_leaves_retail_class`` is on (CRR Art. 123, last
    sub-paragraph). Under Basel 3.1 it is off: PS1/26 Art. 123(1)(a) makes every
    non-SME natural-person exposure retail, and the row stays RETAIL_OTHER as a
    non-regulatory retail exposure (Art. 123(3)(c), 100%). The SME limb
    (``is_retail_sme`` -> CORPORATE_SME) is regime-invariant.

    A retail mortgage whose class rests on the product label alone (no linked
    property, no LTV — ``re_evidence.re_evidence_expr``) also records the class
    it would otherwise take in the scratch ``RE_UNEVIDENCED_CLASS_COLUMN``; the
    classifier applies it to Standardised-Approach rows (review CL-08).

    Sets: exposure_class (updated), is_sme, requires_fi_scalar, is_hvcre, and
    the scratch RE_UNEVIDENCED_CLASS_COLUMN
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    qrre_max_limit = float(
        regulatory_threshold(resolved_pack, "qrre_max_limit", config.eur_gbp_rate)
    )
    lfse_total_assets_threshold = float(
        regulatory_threshold(resolved_pack, "lfse_total_assets_threshold", config.eur_gbp_rate)
    )
    lfse_assets = pl.col(
        "cp_group_total_assets"
        if resolved_pack.feature("lfse_assets_at_highest_consolidation")
        else "cp_total_assets"
    )
    is_sme_by_size = is_sme_by_size_expr(config, pack=resolved_pack)

    # PRA PS1/26 Art. 124(3) / Art. 124K: ADC exposures retain the CORPORATE
    # class and route to the 150% Art. 124K(1) ADC RW — they must not be
    # reclassified to CORPORATE_SME. ``is_adc`` is always present after
    # ``_derive_independent_flags``.
    is_adc = pl.col("is_adc").fill_null(False)

    # Conditions reused across expressions. ``is_sme_by_size`` evaluates
    # CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC using turnover when
    # present and total assets as a fallback. Art. 501 supporting factor
    # eligibility is handled separately in sa/supporting_factors.py and
    # remains turnover-only per Art. 501(2)(c).
    is_corporate_sme = (
        (pl.col("exposure_class") == ExposureClass.CORPORATE.value) & is_sme_by_size & ~is_adc
    )
    is_retail_sme = (
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        & (pl.col("qualifies_as_retail") == False)  # noqa: E712
        & is_sme_by_size
    )
    # Where a non-SME retail row that fails ``qualifies_as_retail`` lands is a
    # regime difference (RE-03). CRR Art. 123 (last sub-paragraph) makes it
    # "not eligible for the retail exposures class" -> CORPORATE. PS1/26
    # Art. 123(1)(a) keeps every non-SME natural-person exposure retail, priced
    # at the Art. 123(3)(c) 100% non-regulatory weight downstream, so under
    # Basel 3.1 the row stays RETAIL_OTHER (and stays in reach of the Art. 123B
    # currency-mismatch multiplier, which is scoped by retail class).
    leaves_retail_class = (
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        & (pl.col("qualifies_as_retail") == False)  # noqa: E712
        & pl.lit(resolved_pack.feature("non_qualifying_retail_leaves_retail_class"))
    )
    # Specialised lending is a corporate sub-type (Art. 112(1)(g)) and is
    # flagged as SME when the counterparty meets the size test. The
    # exposure_class must remain SPECIALISED_LENDING so approach assignment
    # routes it to the slotting calculator; only the is_sme flag is set.
    # Art. 501 supporting-factor eligibility is gated separately on
    # turnover non-null in sa/supporting_factors.py.
    is_sl_sme = (
        pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value
    ) & is_sme_by_size

    # QRRE qualification (CRR Art. 154(4)(a)-(c) / PS1/26 Art. 147(5A)(a)-(c)):
    #   (a) the exposures are to individuals (natural persons);
    #   (b) they are revolving, UNSECURED, and — to the extent they are not
    #       drawn — immediately and unconditionally cancellable; and
    #   (c) the largest per-individual aggregate nominal exposure across the
    #       sub-portfolio is <= the limit (EUR 100k CRR / GBP 90k B31).
    # The same conditions apply under both regimes (only the (c) limit value
    # differs, resolved from the pack), so the gates are NOT regime-Featured.
    # Conditions (5A)(d) low loss-rate volatility and (5A)(e) consistency with
    # the sub-portfolio's underlying risk characteristics are supervisory,
    # portfolio-level attestations — not per-exposure inputs — and are out of
    # scope for row-level classification.
    #
    # (a) individuals; (b) unsecured + unconditionally-cancellable-when-undrawn.
    #     Each is a reusable module-level predicate (also read by the CLS010
    #     demotion-warning collector in ``audit.py``) — see the helpers below.
    is_qrre_individual = natural_person_expr()
    is_qrre_unsecured = qrre_unsecured_expr()
    is_qrre_cancellable = qrre_undrawn_cancellable_expr()

    # CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the *aggregate* nominal
    # exposure to any single individual across the QRRE sub-portfolio at the
    # limit (EUR 100k / GBP 90k), not each facility individually. Aggregate
    # ``facility_limit`` (the committed/nominal basis) per
    # ``counterparty_reference`` before comparing, counting each committed
    # facility ONCE rather than once per hierarchy leg, and never more under
    # one multi-option umbrella than the umbrella's own limit — see
    # ``qrre_obligor_aggregate_limit_expr``. The driver columns
    # (``is_revolving`` / ``facility_limit`` / ``parent_facility_reference`` /
    # ``root_facility_reference`` / ``is_secured`` / ``risk_type`` /
    # ``undrawn_amount``) are hierarchy_exit contract columns — always present,
    # null-gated by value; the umbrella's ``root_facility_limit`` /
    # ``root_facility_utilisation`` are optional ones (a sealed frame that never
    # ran the hierarchy producer carries typed nulls: no cap).
    #
    # The QRRE sub-portfolio is the qualifying revolving retail population.
    # Only those rows contribute to the per-individual aggregate; non-QRRE
    # facilities (e.g. a term loan to the same obligor) are masked to 0.
    is_qrre_candidate = (
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
        & (pl.col("is_revolving") == True)  # noqa: E712
        & is_qrre_individual
        & is_qrre_unsecured
        & is_qrre_cancellable
    )
    facility_limit = pl.col("facility_limit").fill_null(float("inf"))
    candidate_limit = pl.when(is_qrre_candidate).then(facility_limit).otherwise(pl.lit(0.0))
    exposures, obligor_aggregate_limit = qrre_obligor_aggregate_limit_expr(
        exposures, is_qrre_candidate, facility_limit, candidate_limit
    )
    is_qrre = is_qrre_candidate & (obligor_aggregate_limit <= qrre_max_limit)

    # FI scalar (1.25x correlation) — mandatory for large FSEs (Art. 153(2)).
    # An FSE is "large" when total assets meet the Art. 142(1)(4) / PS1/26
    # glossary threshold. Null total_assets -> the >= test is null -> False:
    # size undetermined, no scalar (CLS009 flags the gap in audit.py). The
    # user flag is OR-ed in as an authoritative override that can never
    # suppress a derived True.
    is_large_fse = pl.col("cp_is_financial_sector_entity").fill_null(False) & (
        lfse_assets >= lfse_total_assets_threshold
    ).fill_null(False)
    requires_fi_scalar = pl.col("cp_apply_fi_scalar").fill_null(False) | is_large_fse

    # Retail mortgage — stays RETAIL_MORTGAGE regardless of threshold.
    is_retail_mortgage = (pl.col("is_mortgage") == True) & (  # noqa: E712
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        | (pl.col("cp_entity_type") == "individual")
    )
    # The class the row takes when it is not a retail mortgage. Priority
    # order: QRRE, SME retail, non-qualifying retail (CRR only — Basel 3.1
    # keeps it retail), corporate SME, keep.
    non_mortgage_class = (
        pl.when(
            # QRRE: qualifying revolving retail under QRRE limit (Art. 147(5))
            is_qrre
        )
        .then(pl.lit(ExposureClass.RETAIL_QRRE.value))
        .when(
            # SME retail that doesn't qualify → CORPORATE_SME
            is_retail_sme
        )
        .then(pl.lit(ExposureClass.CORPORATE_SME.value))
        .when(
            # Other retail that doesn't qualify → CORPORATE (CRR only; see
            # ``leaves_retail_class``)
            leaves_retail_class
        )
        .then(pl.lit(ExposureClass.CORPORATE.value))
        .when(
            # Corporate with SME revenue → CORPORATE_SME
            is_corporate_sme
        )
        .then(pl.lit(ExposureClass.CORPORATE_SME.value))
        .otherwise(pl.col("exposure_class"))
    )

    return exposures.with_columns(
        [
            # --- exposure_class update (SME + retail + QRRE combined) ---
            pl.when(is_retail_mortgage)
            .then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .otherwise(non_mortgage_class)
            .alias("exposure_class"),
            # Review CL-08: a mortgage class resting on the product label alone
            # (no linked property, no LTV) records its non-mortgage class for
            # ``re_evidence.withhold_unevidenced_re_class`` to apply to
            # Standardised-Approach rows once the approach is known.
            pl.when(is_retail_mortgage & ~re_evidence_expr())
            .then(non_mortgage_class)
            .alias(RE_UNEVIDENCED_CLASS_COLUMN),
            # --- is_sme flag ---
            # True for: corporate SME, retail reclassified to CORPORATE_SME,
            # or specialised lending with SME counterparty (keeps SPECIALISED_LENDING class).
            (is_corporate_sme | is_retail_sme | is_sl_sme).alias("is_sme"),
            # --- FI scalar: derived (large FSE) OR user override (Art. 153(2)) ---
            requires_fi_scalar.alias("requires_fi_scalar"),
            # --- HVCRE flag (from specialised lending join, null → False) ---
            pl.col("is_hvcre").fill_null(False).alias("is_hvcre"),
        ]
    ).drop(_QRRE_SCRATCH_COLUMNS)


# =========================================================================
# QRRE (b)-gate predicates (shared with the CLS010 demotion-warning collector)
# =========================================================================


@cites("CRR Art. 154(4)")
@cites("PS1/26, paragraph 147")
def qrre_unsecured_expr() -> pl.Expr:
    """Return the Art. 147(5A)(b) / Art. 154(4)(b) "unsecured" QRRE predicate.

    A revolving retail facility flagged ``is_secured`` is NOT a QRRE. A null
    attestation resolves to unsecured (``fill_null(False)``) — consistent with
    how the pipeline treats absent collateral everywhere else, and with the
    reality that revolving retail credit is unsecured by nature. The classifier
    runs before CRMProcessor, so general (non-property) collateral is not yet
    allocated; this is a firm attestation rather than a pledge-presence join
    (which would replicate CRM's multi-level beneficiary cascade at classify
    time). The Art. 147(5A) second-sub-paragraph wage-account derogation is
    applied via input semantics — see ``FACILITY_SCHEMA.is_secured``.
    """
    return ~pl.col("is_secured").fill_null(False)


@cites("CRR Art. 154(4)")
@cites("PS1/26, paragraph 147")
def qrre_undrawn_cancellable_expr() -> pl.Expr:
    """Return the Art. 147(5A)(b) / Art. 154(4)(b) cancellability QRRE predicate.

    QRRE must be, "to the extent they are not drawn, immediately and
    unconditionally cancellable". A row carrying an undrawn commitment
    (``undrawn_amount > 0``) must have the CCF unconditionally-cancellable
    (LR / low-risk) ``risk_type``; a fully-drawn row has nothing undrawn to
    cancel and satisfies the limb trivially. Reuses the CCF machinery's UC
    signal (``risk_type`` == LR, engine/ccf.py) rather than minting a duplicate
    flag. A null/non-LR ``risk_type`` on an undrawn row -> not cancellable ->
    not QRRE, mirroring the CCF null convention (a null risk_type resolves to
    the MR-equivalent CCF, never the LR benefit — no divergence). A null
    ``undrawn_amount`` propagates (never QRRE), which is the conservative
    direction — no ``fill_null(0.0)`` on the Float column.
    """
    has_undrawn_commitment = pl.col("undrawn_amount") > 0.0
    is_uncond_cancellable = (
        pl.col("risk_type")
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.to_lowercase()
        .is_in(["lr", "low_risk"])
    )
    return ~has_undrawn_commitment | is_uncond_cancellable


@cites("CRR Art. 154(4)")
@cites("PS1/26, paragraph 147")
def qrre_obligor_aggregate_limit_expr(
    exposures: pl.LazyFrame,
    is_qrre_candidate: pl.Expr,
    facility_limit: pl.Expr,
    candidate_limit: pl.Expr,
) -> tuple[pl.LazyFrame, pl.Expr]:
    """Return the Art. 147(5A)(c) / Art. 154(4)(c) per-individual aggregate limit.

    Returns ``(exposures, obligor_aggregate_limit)``: the frame with the per-leg
    helper columns ``_QRRE_SCRATCH_COLUMNS`` materialised, and the expression
    that sums the last of them per obligor. The caller drops the helpers before
    returning, so the classify exit schema is unchanged.

    The limb caps the *aggregate* nominal exposure to any single individual
    across the QRRE sub-portfolio, not each facility individually. The nominal
    basis is the committed ``facility_limit``, aggregated in three steps:

    1. **One limit per facility** (P1.320). The hierarchy stage emits one row per
       *leg* of a facility — each drawn loan, each contingent, the synthetic
       ``_UNDRAWN`` headroom row, each MOF waterfall / ``_RESIDUAL`` sub-row —
       and every leg carries the ``facility_limit`` of the facility it is keyed
       on (``parent_facility_reference``, the exact functional determinant of
       that limit). Per (obligor, keyed facility) the first candidate leg
       carries the group's limit and every later leg zero.
    2. **Never more than the umbrella** (P1.355). Under a multi-option facility
       a drawn leg is keyed on its IMMEDIATE sub-facility and carries the
       sub-limit, while the root's waterfall / residual legs are keyed on the
       ROOT and carry the root's limit — so step 1 counts a sub-limit beside the
       umbrella that already contains it, and sums sibling sub-limits past a
       fully drawn umbrella that emits no root leg at all. An individual cannot
       draw more under an umbrella than the umbrella allows, so per (obligor,
       ``root_facility_reference``) the step-1 limits are summed and capped at
       ``root_facility_limit``: ``min(umbrella limit, sum of the distinct limits
       counted under it)`` — never the largest single sub-limit, which drops
       every other sub-limit and under-counts (nothing validates that the
       sub-limits sum to no more than the root). The first candidate leg of the
       group carries it, every later leg zero. The key holds the OBLIGOR as well
       as the root: the limb caps the exposure to "a single individual", so where
       sub-lines under one umbrella belong to different individuals each is
       capped separately. Keying on the root alone — headroom netting's grain,
       which nets per root across every obligor — would pool the owners'
       sub-limits, credit the capped pool to one owner and zero to the others,
       and wrongly admit them.
    3. **Per individual.** The step-2 values are summed per obligor.

    Today's conservative result is KEPT, by construction, in four cases (the
    first and last are the owner's P1.355 decision; each is pinned by a control
    in ``tests/unit/classifier/test_p1_355_qrre_umbrella_cap.py``):

    - **The umbrella has no limit.** A null ``root_facility_limit`` applies no
      cap; with headroom the root's own legs carry the null limit as unbounded,
      so the obligor stays out of QRRE. A sum-of-sub-limits rule would admit
      it — not adopted.
    - **A limit counted under the umbrella is null** (step 1 reads it as
      unbounded). The group stays unbounded rather than being capped at the
      umbrella.
    - **The individual has drawn more under the umbrella than its limit** —
      their drawings under the root exceed it, a zero limit included — **or a
      drawing under it cannot be measured.** The drawings are
      ``root_facility_utilisation``, which the hierarchy stage puts on every
      leg: a loan's drawn balance and a contingent's amount (on- or
      off-balance-sheet), floored at zero — the amounts it nets against the
      root's headroom — in the ROOT facility's currency at the run's FX rates,
      and null where the run holds no rate. Capping an overdrawn umbrella would
      count the individual below their own drawn balance, and an unmeasurable
      drawing cannot be shown to be within the limit, so in both the step-1
      sum is kept.
    - **A sibling sub-line fails the QRRE gate.** A waterfall leg is one sub's
      slice of the root's headroom but stays keyed on the root, so the root's
      limit is charged to the QRRE sub-portfolio in full (P1.320 leg (vi)).

    Intermediate umbrellas in a hierarchy deeper than two levels are not
    applied as caps — only the root is — which can only over-count. The
    overdrawn test is made in the root facility's currency, whatever the
    currency of each drawing and of the run. The cap itself compares limits as
    supplied: the root's limit with the step-1 limits, each in its own
    facility's currency — exact when the facilities under one umbrella share a
    currency. ``facility_limit`` is never FX-converted, so step 1 and the
    comparison with the (GBP) ceiling read every limit as stated; that is
    pre-existing and outside this cap.

    ⚠ The steps may NOT be folded into one expression, and this is a
    performance contract, not a style preference. Polars evaluates a window
    function's INPUT inside the outer group-by context, so putting one step's
    ``.over(...)`` inside the input of the next re-runs it once per outer group:
    cost becomes a function of row count times group count rather than of row
    count. That is what commit ``8ec7d302`` shipped — the classify stage went
    from 0.5 s to 5.6 s at 374k rows across v0.3.27-v0.3.32, with every
    correctness gate green. Reading each step's result back as a plain column
    makes the next window's input a ``pl.col()``, which Polars evaluates once
    per row. ``arch_check`` check 21 and
    ``tests/unit/classifier/test_p1_320_qrre_aggregate_scaling.py`` hold the
    shape.

    ⚠ Each step picks its carrying leg from the CANDIDATE MASK, not a row
    count: step 1 by a ``cum_sum`` of the mask, step 2 by the smallest row
    index among candidate legs (an aggregating window, cheaper than a second
    ``cum_sum``; the same leg, the first candidate in row order). This is the
    difference from the sibling obligor-deduplication in
    ``attributes.py`` (the optional 0.2% granularity test), which divides by
    ``pl.len().over(...)``: candidacy genuinely differs across legs of one
    facility (a MOF root with two committed subs of differing ``risk_type``
    emits one cancellable and one non-cancellable waterfall leg), and a line
    count would divide a facility's limit by legs that never contributed to it
    — halving the aggregate and wrongly admitting the obligor to QRRE.

    Null-key handling, each guarded by ``partition_by_nullable``:

    - Null ``parent_facility_reference`` — no dedupe; the row contributes its
      own ``facility_limit``. Polars would otherwise pool every null-parent row
      of the obligor into one partition and count only the largest,
      under-stating the aggregate (RWA-reducing).
    - Null ``root_facility_reference`` — no umbrella; the row passes its step-1
      value through unchanged. The hierarchy sets a root for every row with a
      parent, so this is the null-parent row again.
    - Null ``counterparty_reference`` — the row falls back to its own
      ``candidate_limit`` and never sees the pooled null partition, unchanged.
    """
    # Step 1 — one contribution per (obligor, keyed facility): the first
    # candidate leg of the group carries the group's limit, every later leg
    # zero. Materialised as its own column so step 2's window input is a plain
    # column read rather than a nested window (see the ⚠ note above).
    facility_keys = ["counterparty_reference", "parent_facility_reference"]
    deduped_limit = (
        pl.when(is_qrre_candidate)
        .then(
            partition_by_nullable(
                pl.when(is_qrre_candidate.cast(pl.UInt32).cum_sum().over(facility_keys) == 1)
                .then(candidate_limit.max().over(facility_keys))
                .otherwise(pl.lit(0.0)),
                "parent_facility_reference",
                facility_limit,
            )
        )
        .otherwise(pl.lit(0.0))
    )
    # Step 2a — the per-(obligor, umbrella) terms: one window of aggregations
    # over plain inputs, materialised (see the ⚠ notes). A null-root row (no
    # umbrella) gets a null struct; step 2b passes its step-1 value through.
    umbrella_keys = ["counterparty_reference", "root_facility_reference"]
    deduped = pl.col(_QRRE_DEDUPED_LIMIT_COLUMN)
    utilisation = pl.col("root_facility_utilisation")
    row_index = pl.col(_QRRE_ROW_INDEX_COLUMN)
    umbrella_terms = partition_by_nullable(
        pl.struct(
            deduped.sum().alias("counted"),
            utilisation.sum().alias("drawn"),
            utilisation.null_count().alias("unmeasured"),
            pl.when(is_qrre_candidate).then(row_index).min().alias("first_leg"),
        ).over(umbrella_keys),
        "root_facility_reference",
        pl.lit(None),
    )
    # Step 2b — one contribution per (obligor, umbrella), from column reads
    # only: the step-1 limits under the root, capped at the root's own limit
    # only where the cap can rely on it — the limit is present (a null compares
    # null: no cap), every drawing the obligor has under the root was
    # measurable in the root's currency and together they are within the
    # limit, and the counted sum is bounded. Otherwise the step-1 sum passes
    # through: today's count. The first candidate leg of the group carries it.
    terms = pl.col(_QRRE_UMBRELLA_TERMS_COLUMN).struct
    counted = terms.field("counted")
    root_limit = pl.col("root_facility_limit")
    umbrella_caps = (
        counted.is_finite()
        & (terms.field("unmeasured") == 0)
        & (root_limit >= terms.field("drawn"))
    )
    capped_at_umbrella = (
        pl.when(umbrella_caps).then(pl.min_horizontal(root_limit, counted)).otherwise(counted)
    )
    umbrella_limit = (
        pl.when(is_qrre_candidate)
        .then(
            pl.when(pl.col("root_facility_reference").is_null())
            .then(deduped)
            .when(terms.field("first_leg") == row_index)
            .then(capped_at_umbrella)
            .otherwise(pl.lit(0.0))
        )
        .otherwise(pl.lit(0.0))
    )
    # Step 3 — the per-obligor aggregate, reading the step-2 column back.
    obligor_aggregate_limit = partition_by_nullable(
        pl.col(_QRRE_UMBRELLA_LIMIT_COLUMN).sum().over("counterparty_reference"),
        "counterparty_reference",
        candidate_limit,
    )
    return (
        exposures.with_columns(deduped_limit.alias(_QRRE_DEDUPED_LIMIT_COLUMN))
        .with_row_index(_QRRE_ROW_INDEX_COLUMN)
        .with_columns(umbrella_terms.alias(_QRRE_UMBRELLA_TERMS_COLUMN))
        .with_columns(umbrella_limit.alias(_QRRE_UMBRELLA_LIMIT_COLUMN)),
        obligor_aggregate_limit,
    )


# =========================================================================
# Purchased-receivables top-down PD (CRR Art. 160(2)/(6); 1 .with_columns)
# =========================================================================


@cites("CRR Art. 160(2)")
@cites("CRR Art. 160(6)")
@cites("PS1/26, paragraph 160")
def derive_purchased_receivables_pd(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Derive the Art. 160(2)/(6) top-down PD for purchased corporate receivables.

    Where an institution "is not able to estimate PDs or an institution's PD
    estimates do not meet the requirements set out in Section 6", the PD is
    prescribed rather than modelled:

    - Art. 160(2)(a) — senior claims: ``PD = EL / LGD`` for those receivables.
    - Art. 160(2)(b) — subordinated claims: ``PD = EL`` (no division).
    - Art. 160(6) first sentence — dilution risk: ``PD = EL`` for dilution risk,
      taken from the separate ``el_dilution_estimate`` input.

    The (a) denominator is not a free choice. CRR Art. 161(1)(e)/(f)/(g) fix the
    supervisory purchased-receivables LGDs for exactly the population that cannot
    estimate PDs, and PS1/26 Art. 161(1)(e)-(g) with Art. 161(2)(a) bind the same
    values to "where PD is determined in accordance with point (a) of Article
    160(2)" for Foundation *and* Advanced IRB alike. So the denominator is the
    subtype's supervisory LGD read from the same pack table the LGD side uses —
    never a firm-supplied LGD, which removes any divide-by-null/zero surface.

    Runs before the approach ladder because the IRB gate is
    ``internal_pd.is_not_null()``: without this the pool has no PD at all and
    falls to the Standardised Approach.

    Null semantics (conservative): a null, zero or negative EL estimate derives
    nothing, leaving ``internal_pd`` / ``pd`` exactly as they were — an absent
    estimate must never become PD 0%. A firm-supplied PD always wins, because
    Art. 160(2) applies only where the institution cannot produce one.

    The derived PD is capped at 1.0 — ``EL / LGD`` is unbounded above (an EL rate
    of 60% over a 45% LGD gives 1.33) but a PD is a probability, and 100% is the
    Art. 160(3) value for a defaulted obligor. No floor is applied here: the
    Art. 160(1) 0.03% (PS1/26 0.05%) input floor is applied downstream by
    ``engine/irb/transforms.py::apply_pd_floor`` for every PD alike.

    Class scope: purchased *corporate* receivables only — CORPORATE /
    CORPORATE_SME on ``exposure_class_irb``. Art. 160(2) and Art. 160(6) both name
    the corporate population, and the (a) denominator is a corporate supervisory
    LGD (Art. 161(1)(e)); retail IRB is own-estimate only, with no supervisory LGD
    and no Art. 163 senior EL/LGD limb to authorise the division. A retail row
    carrying a subtype therefore derives nothing and keeps its existing route.

    Regime scope: both. PS1/26 Art. 160(2)(a)-(c) and 160(6) carry the CRR text
    over, so there is no regime Feature — only the pack's regime-keyed LGD values.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    lgd_table = firb_supervisory_lgd_values(resolved_pack)
    # Art. 161(1)(e): the senior supervisory LGD — a cited pack value, always
    # non-zero, so the Art. 160(2)(a) division is total.
    senior_lgd = float(lgd_table["purchased_receivables_senior"])

    subtype = pl.col("purchased_receivables_subtype")
    # Art. 160(2) and Art. 160(6) both read "purchased CORPORATE receivables", and
    # the Art. 161(1)(e)-(g) LGDs that supply the (a) denominator are likewise
    # corporate rates. Retail IRB is own-estimate only — Art. 163 has no senior
    # EL/LGD limb and no supervisory retail LGD exists — so without this gate a
    # retail row carrying a subtype would divide its EL by the CORPORATE senior
    # LGD and manufacture an unauthorised retail PD. Gating on the IRB class keeps
    # the derivation inside the population the article names (``exposure_class_irb``
    # is already synced by ``sync_irb_exposure_class``, which runs immediately
    # before this transform in the classifier).
    is_corporate = pl.col("exposure_class_irb").is_in(
        [ExposureClass.CORPORATE.value, ExposureClass.CORPORATE_SME.value]
    )
    # A usable estimate is strictly positive: 0.0 is "not supplied", not "no loss".
    default_risk_el = pl.when(pl.col("el_estimate") > 0.0).then(pl.col("el_estimate"))
    dilution_el = pl.when(pl.col("el_dilution_estimate") > 0.0).then(pl.col("el_dilution_estimate"))

    top_down_pd = (
        pl.when(~is_corporate)
        .then(pl.lit(None, dtype=pl.Float64))
        .when(subtype == "senior")
        .then(default_risk_el / pl.lit(senior_lgd))
        .when(subtype == "subordinated")
        .then(default_risk_el)
        .when(subtype == "dilution_risk")
        .then(dilution_el)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .clip(upper_bound=1.0)
    )

    # coalesce, not fill_null: the firm's own PD outranks the derivation, and a
    # null derivation leaves the column untouched (no Float null ever filled).
    derived_pd = pl.coalesce([pl.col("internal_pd"), top_down_pd])
    return exposures.with_columns(
        [derived_pd.alias("internal_pd"), pl.coalesce([pl.col("pd"), top_down_pd]).alias("pd")]
    )


# =========================================================================
# Corporate → retail reclassification (1 .with_columns)
# =========================================================================


def reclassify_corporate_to_retail(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    schema_names: set[str],
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Reclassify qualifying corporates to retail.

    Retail outranks corporate in the exposure class waterfall per
    CRR Art. 147(5) / Basel CRE30.16-17. Corporate exposures are
    reclassified to retail when all of:
    1. Managed as part of a retail pool (is_managed_as_retail=True)
    2. Aggregated exposure < EUR 1m (qualifies_as_retail=True)
    3. Has internally modelled LGD (lgd IS NOT NULL)
    4. Counterparty is SME-sized (CRR Art. 4(1)(128D) — turnover <
       EUR 50m OR balance-sheet total < EUR 43m when turnover null)

    Reclassification is an exposure-class decision, independent of
    approach permissions. The approach (AIRB/FIRB/SA) is determined
    later by _assign_approach using model_permissions.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    is_sme_by_size = is_sme_by_size_expr(config, pack=resolved_pack)

    # Reclassification eligibility expression (inlined — not a column ref)
    reclassification_expr = (
        (
            pl.col("exposure_class").is_in(
                [
                    ExposureClass.CORPORATE.value,
                    ExposureClass.CORPORATE_SME.value,
                ]
            )
        )
        & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
        & (pl.col("lgd").is_not_null())
        & is_sme_by_size
    )

    # Has property collateral expression (inlined)
    has_property_expr = _build_has_property_expr(schema_names)

    # Single .with_columns: reclassified_to_retail, has_property_collateral,
    # exposure_class update — all using inlined expressions (not column refs)
    return exposures.with_columns(
        [
            reclassification_expr.alias("reclassified_to_retail"),
            has_property_expr.alias("has_property_collateral"),
            pl.when(reclassification_expr & has_property_expr)
            .then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .when(reclassification_expr)
            .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),
        ]
    )


@cites("CRR Art. 147(5)")
@cites("CRR Art. 147(4)")
@cites("PS1/26, paragraph 147")
def sync_irb_exposure_class(
    exposures: pl.LazyFrame,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Sync exposure_class_irb with the (possibly mutated) exposure_class.

    Subtype classification and corporate→retail reclassification mutate
    ``exposure_class`` in place without touching ``exposure_class_irb``,
    which was set once in ``_add_counterparty_attributes``. Re-align them
    so downstream IRB permission lookups and approach filters see the
    reclassified class.

    rgla_* / pse_* entity types are excluded because their SA and IRB
    classes are definitionally different (CRR Art. 147(3)/147(4)(b)) —
    ``exposure_class_irb`` already carries the correct CGCB / INSTITUTION
    value from the pack's ``entity_type_to_irb_class`` and must not be overwritten.

    Non-named MDBs join that exclusion under CRR only (P1.276): CRR
    Art. 147(4)(c) assigns "exposures to multilateral development banks which
    are not assigned a 0 % risk weight under Article 117" to the INSTITUTIONS
    class while Art. 112 keeps them in their own SA class, so the two classes
    are definitionally different in exactly the rgla_* / pse_* sense and the
    derived ``exposure_class_irb`` must survive. Gated on the cited
    ``crr_non_named_mdb_institution_irb_class`` pack Feature — PS1/26
    Art. 147(3)(f) has no such split (all MDBs are quasi-sovereign there), so
    under Basel 3.1 the MDB rows keep syncing to their SA class as before.

    Natural-person IRB retail restoration (CRR Art. 147(5)(a)(i) / PS1/26
    Art. 147(5)(a)(i)): the SA regulatory-retail test (``qualifies_as_retail``,
    Art. 123 / 123A) applies the EUR 1,000,000 / GBP 880,000 monetary cap (and,
    where a firm elects it, the optional 0.2% granularity test) to natural
    persons; under CRR a failing individual is expelled to CORPORATE. Neither
    condition exists in the IRB retail class: Art. 147(5)(a) caps the SME limb
    (ii) only, and Art. 147(5) has no granularity limb. So a natural person
    expelled to CORPORATE keeps the IRB retail class, provided the
    Art. 147(5)(c) management-basis condition holds — i.e. the obligor is not
    managed individually as a corporate (``is_managed_as_retail`` not
    explicitly False; a null flag defaults to True, matching the
    Art. 123A(1)(b)(iii) backward-compatible KEEP). This leaves the SA
    ``exposure_class`` and ``qualifies_as_retail`` untouched — the SA/IRB
    divergence lives only in ``exposure_class_irb``.

    The mirror case under Basel 3.1 (RE-03): a natural person failing the SA
    regulatory-retail test now STAYS in the SA retail class (PS1/26
    Art. 123(1)(a)), so the divergence can run the other way. Where that row is
    managed individually (``is_managed_as_retail`` explicitly False) it fails
    Art. 147(5)(c) and its IRB class is CORPORATE — exactly the IRB class it had
    when the SA class itself was CORPORATE, so IRB permission lookup, approach
    routing and the IRB formula (via ``_align_irb_exposure_class``) are
    unchanged by RE-03. The predicate needs ``qualifies_as_retail`` False, a
    population that only exists in RETAIL_OTHER where the
    ``non_qualifying_retail_leaves_retail_class`` Feature is off, so CRR rows
    are untouched (a CRR natural person under the cap keeps its IRB retail class
    whatever the flag says, as before).
    """
    # Art. 147(5)(c): a natural person managed individually as corporate
    # (is_managed_as_retail explicitly False) is NOT IRB retail. Null → True
    # (documented KEEP, mirrors _build_qualifies_as_retail_expr).
    managed_as_retail = pl.col("cp_is_managed_as_retail").fill_null(True)
    restore_retail_irb = (
        natural_person_expr()
        & (pl.col("exposure_class") == ExposureClass.CORPORATE.value)
        & managed_as_retail
    )
    # RE-03 mirror: Basel 3.1 non-regulatory retail that is managed individually
    # keeps the IRB corporate class (Art. 147(5)(c)).
    individually_managed_retail_irb = (
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        & (pl.col("qualifies_as_retail") == False)  # noqa: E712
        & ~managed_as_retail
    )
    # Entity types whose derived IRB class is definitionally distinct from the
    # SA class and must not be overwritten by the sync.
    preserve_derived_irb_class = pl.col("cp_entity_type").is_in(list(RGLA_PSE_ENTITY_TYPES))
    if pack.feature("crr_non_named_mdb_institution_irb_class"):
        preserve_derived_irb_class = preserve_derived_irb_class | (
            pl.col("cp_entity_type") == "mdb"
        )

    return exposures.with_columns(
        pl.when(preserve_derived_irb_class)
        .then(pl.col("exposure_class_irb"))
        .when(restore_retail_irb)
        .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
        .when(individually_managed_retail_irb)
        .then(pl.lit(ExposureClass.CORPORATE.value))
        .otherwise(pl.col("exposure_class"))
        .alias("exposure_class_irb")
    )


@cites("PS1/26, paragraph 147A.1")
def derive_exposure_subclass(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Derive the Basel 3.1 corporate ``exposure_subclass`` (PRA PS1/26 Art. 147A(1)).

    Basel 3.1 only — under CRR the column is null. For rows whose
    ``exposure_class`` is corporate / corporate_sme, the three-way split is:

      - ``corporate_financial_large`` — FSE (``cp_is_financial_sector_entity``)
        OR large corporate (``cp_annual_revenue`` > the Art. 147(4C)(b)(ii) GBP 440m
        threshold). Art. 147A(1)(e).
      - ``corporate_sme`` — ``is_sme`` (turnover <= GBP 44m). Art. 147A(1)(f).
      - ``corporate_other`` — otherwise. Art. 147A(1)(f).

    Reuses the FSE predicate and the large-corporate revenue threshold
    (``regulatory_threshold(pack, "large_corporate_revenue_threshold", …)``) shared
    with ``_apply_b31_approach_restrictions``; non-corporate rows stay null.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    null_subclass = pl.lit(None, dtype=pl.String).alias("exposure_subclass")
    if not resolved_pack.feature("b31_exposure_subclass_reporting_applies"):
        return exposures.with_columns(null_subclass)

    is_corporate = pl.col("exposure_class").is_in(
        [ExposureClass.CORPORATE.value, ExposureClass.CORPORATE_SME.value]
    )

    is_fse = (pl.col("cp_is_financial_sector_entity") == True).fill_null(False)  # noqa: E712

    is_large_by_revenue = (
        pl.col("cp_annual_revenue")
        > float(
            regulatory_threshold(
                resolved_pack, "large_corporate_revenue_threshold", config.eur_gbp_rate
            )
        )
    ).fill_null(False)

    is_sme = pl.col("is_sme").fill_null(False)

    subclass = (
        pl.when(~is_corporate)
        .then(pl.lit(None, dtype=pl.String))
        .when(is_fse | is_large_by_revenue)
        .then(pl.lit(ExposureSubclass.CORPORATE_FINANCIAL_LARGE.value))
        .when(is_sme)
        .then(pl.lit(ExposureSubclass.CORPORATE_SME.value))
        .otherwise(pl.lit(ExposureSubclass.CORPORATE_OTHER.value))
        .alias("exposure_subclass")
    )
    return exposures.with_columns(subclass)


# =========================================================================
# Private helpers
# =========================================================================


def _build_has_property_expr(schema_names: set[str]) -> pl.Expr:
    """Build has_property_collateral expression.

    The property aggregates are hierarchy_exit contract columns —
    always present, null/False = no property collateral.
    """
    expr = (pl.col("property_collateral_value") > 0) | (
        pl.col("has_facility_property_collateral") == True  # noqa: E712
    )

    # KEEP (presence guard on a non-contract column): ``collateral_type``
    # is a collateral-table column, not declared on hierarchy_exit — a
    # sealed classifier input never carries it, so this branch only
    # contributes for direct expression-level use on hand-rolled frames.
    if "collateral_type" in schema_names:
        expr = expr | pl.col("collateral_type").is_in(
            ["immovable", "residential", "commercial"],
        )

    return expr
