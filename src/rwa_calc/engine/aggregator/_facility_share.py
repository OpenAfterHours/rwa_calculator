"""
Facility-share candidate resolution — riskiest member by applied approach.

Pipeline position:
    SA / IRB / Slotting calculators -> OutputAggregator.aggregate (HEAD)
        -> resolve_facility_shares -> compute_el_portfolio_summary
        -> apply_floor_with_impact

Key responsibilities:
- Rank the priced undrawn CANDIDATES of one shared facility and keep exactly one
- Evaluate the two whole-book assignments the Basel 3.1 output floor makes
  possible, end to end, and keep the larger
- Record every candidate on an audit frame, so an attribution flip is visible
  rather than inferred from a moved COREP row

The hierarchy stage emits one synthetic undrawn row per member of a shared
facility (``<facility>_UNDRAWN@<member>``, carrying the full headroom), and each
flows through the classifier, CRM and the calculators as an ordinary row of its
own member. This module is where the "compute, then choose" half lands: it runs
at the HEAD of ``aggregate`` — before the applied-class overlay, the
securitisation views, the residual multiplier, the expected-loss summary and the
output floor — so the losers never reach S-TREA, U-TREA or the CET1 deduction.

**The allocation rule is FIRM POLICY, not regulation.** Neither UK CRR nor
PS1/26 defines a facility share or prescribes how to attribute a commitment that
several obligors may draw; capitalising it against the worst credit that could
draw it is a conservatism election. So nothing here carries a ``@cites`` of its
own — the EAD it selects cites the conversion-factor articles, and the
two-assignment comparison is a consequence of the floor cited on
``apply_floor_with_impact``.

Two metrics, and the floor is what separates them:

- **P0 — own approach.** ``argmax`` of the candidate's own pre-floor RWA. The
  rule under CRR (capital is additive there), and under Basel 3.1 whenever the
  floor is inapplicable or the firm has elected ``own_approach``.
- **P2 — floor-aware.** ``TREA = SA + EQ + max(U-TREA, x . S-TREA + OF-ADJ)`` is
  a portfolio ``max``, so "riskiest" is state-dependent. Assignment A picks every
  group by ``argmax u_i``; assignment B by ``argmax b_i``, where ``b_i`` is
  ``x . s_i`` for a floor-eligible member and ``u_i`` for every other. The two
  are evaluated END TO END through the caller's closure and the larger wins —
  exactly twice when the assignments name DIFFERENT members, and never when they
  coincide, because an identical survivor set yields an identical total by
  construction. That is a bound rather than an identity: OF-ADJ moves with the
  winners' expected loss, so the floored branch is not additive across groups and
  the two assignments cannot be compared on marginals alone.

References:
- docs/plans/facility-share-riskiest-member.md — the design of record (D1-D5)
- .claude/state/fs1-scenario-proposal.md Section 6.2 — the resolver contract
- PRA PS1/26 Art. 92(2A) — the output floor whose state makes P2 necessary

Internal module — not part of the public API.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import polars as pl
import polars.selectors as cs

from rwa_calc.contracts.errors import facility_share_fallback_warning
from rwa_calc.engine.aggregator._schemas import FLOOR_ELIGIBLE_APPROACHES
from rwa_calc.engine.aggregator._utils import collect_views

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from polars._typing import PolarsDataType

    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)

# --- Carriers the resolver reads off the concatenated branch frames ---------

#: The root facility a candidate row is competing for; null on every ordinary row.
GROUP_COL = "facility_share_group"
#: True on a priced candidate; False (never null — the branch edges fill it) elsewhere.
CANDIDATE_COL = "is_facility_share_candidate"
REFERENCE_COL = "exposure_reference"
COUNTERPARTY_COL = "counterparty_reference"
OWNER_COL = "original_counterparty_reference"
APPROACH_COL = "approach_applied"
CLASS_COL = "exposure_class"
EAD_COL = "ead_final"
SA_RWA_COL = "sa_rwa"
RISK_WEIGHT_COL = "risk_weight"
PD_COL = "pd_floored"
CQS_COL = "cqs"

#: The own-approach RWA is aliased to the design-of-record's name on the audit
#: frame. The SOURCE column is whatever the caller resolved (``rwa_final`` at
#: the aggregator's head); ``rwa_pre_floor`` itself does not exist yet, because
#: ``apply_floor_with_impact`` is what creates it.
OWN_RWA_COL = "rwa_pre_floor"
FLOORED_CONTRIBUTION_COL = "floored_branch_contribution"

# --- The three metric labels -----------------------------------------------

#: Also the value of the ``facility_share_metric`` election that pins P0.
METRIC_OWN_APPROACH = "own_approach"
METRIC_SA_EQUIVALENT = "sa_equivalent"
METRIC_FALLBACK = "fallback_deterministic"

#: One row per priced candidate. Emitted with these dtypes in BOTH regimes: the
#: floor-side columns are typed nulls under CRR (where ``sa_rwa`` is absent from
#: the results frame outright, not null) so a consumer sees one schema, not two.
RESOLUTION_SCHEMA: dict[str, PolarsDataType] = {
    GROUP_COL: pl.String,
    REFERENCE_COL: pl.String,
    COUNTERPARTY_COL: pl.String,
    OWNER_COL: pl.String,
    APPROACH_COL: pl.String,
    CLASS_COL: pl.String,
    EAD_COL: pl.Float64,
    OWN_RWA_COL: pl.Float64,
    SA_RWA_COL: pl.Float64,
    RISK_WEIGHT_COL: pl.Float64,
    FLOORED_CONTRIBUTION_COL: pl.Float64,
    "rank_own_approach": pl.UInt32,
    "rank_floored_branch": pl.UInt32,
    "is_winner": pl.Boolean,
    "metric_used": pl.String,
    "collapsed_exposure_reference": pl.String,
}


@dataclass(frozen=True)
class FacilityShareSummary:
    """What the resolver decided, and what the caller must do about it.

    Attributes:
        metric_used: ``own_approach`` when assignment A won (or P0 applied),
            ``sa_equivalent`` when the floored branch won. Mirrored onto
            ``OutputFloorSummary.facility_share_metric_used`` where a floor
            summary exists; under CRR there is none, so the per-row
            ``metric_used`` on the audit frame is the only observable.
        trea_alternative: the total the OTHER assignment came to, so the flip is
            auditable. ``None`` whenever only one assignment was evaluated.
        errors: one WARNING per group whose candidates all carried a non-finite
            own-approach RWA and fell back to the deterministic ordering.
        collapse: surviving candidate reference -> the reference it is renamed
            to on every frame it appears in (``<facility>_UNDRAWN``).
        dropped: the losing candidate references, to be filtered out of
            ``combined``, ``sa_results``, ``irb_results`` AND
            ``slotting_results`` — the expected-loss summary reads the branch
            frames directly, so a drop applied to the combined frame alone is
            green on ``rwa_final`` and wrong on OF-ADJ.
    """

    metric_used: str
    trea_alternative: float | None = None
    errors: list[CalculationError] = field(default_factory=list)
    collapse: dict[str, str] = field(default_factory=dict)
    dropped: tuple[str, ...] = ()


def resolve_facility_shares(
    results: pl.LazyFrame,
    *,
    own_rwa_col: str,
    evaluate_trea: Callable[[Sequence[str]], float],
    floor_applicable: bool,
    floor_pct: float,
    metric: str,
) -> tuple[pl.LazyFrame, FacilityShareSummary]:
    """Choose one member per facility share and say why.

    Args:
        results: the concatenated calculator branches (plus equity), as they
            stand at the head of ``aggregate`` — pre-floor, so ``own_rwa_col``
            still carries each row's own-approach RWA.
        own_rwa_col: the pre-floor own-approach RWA column, resolved by the
            CALLER (``_utils.resolve_own_approach_rwa_col``).
        evaluate_trea: ``(surviving_references) -> total_rwa_post_floor``. The
            caller supplies it because the end-to-end evaluation must use the
            aggregator's OWN expected-loss / OF-ADJ / floor arithmetic rather
            than a second copy of it. Called exactly twice under P2 when the two
            assignments name different members, and never otherwise — not under
            P0, and not when the assignments coincide (see
            :func:`_choose_assignment`).
        floor_applicable: ``pack.feature("output_floor")`` AND
            ``config.output_floor.is_entity_in_scope()``, composed by the
            caller. Not a regime boolean (arch_check check 17).
        floor_pct: ``x`` from the Art. 92(5) Schedule.
        metric: the ``facility_share_metric`` firm election.

    Returns:
        ``(resolution, summary)`` — the per-candidate audit frame (eager-backed,
        one row per candidate, exactly one ``is_winner`` per group) and the
        decision record. The CALLER drives the drop and the rename off
        ``summary``.
    """
    resolvable = resolvable_candidate()
    candidates = collect_views(
        {"candidates": results.filter(resolvable).select(_candidate_inputs(own_rwa_col))}
    )["candidates"]
    rows: list[dict[str, Any]] = candidates.to_dicts()
    if not rows:
        return empty_resolution(), FacilityShareSummary(metric_used=METRIC_OWN_APPROACH)

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[GROUP_COL]), []).append(row)

    use_floored_branch = floor_applicable and metric != METRIC_OWN_APPROACH
    if use_floored_branch:
        for row in rows:
            row[FLOORED_CONTRIBUTION_COL] = _floored_contribution(row, floor_pct)

    errors: list[CalculationError] = []
    order_a: dict[str, list[dict[str, Any]]] = {}
    order_b: dict[str, list[dict[str, Any]]] = {}
    fallback_groups: set[str] = set()
    for group, members in groups.items():
        if any(_is_usable(member[OWN_RWA_COL]) for member in members):
            order_a[group] = sorted(members, key=_own_approach_key)
            order_b[group] = sorted(members, key=_floored_branch_key)
            continue
        # Never drop the group: dropping every candidate deletes the facility's
        # undrawn commitment from the submission outright, which is this
        # project's dominant escape class. Fall back to a deterministic
        # ordering and SAY so — a fallback nobody is told about is a silent one.
        fallback_groups.add(group)
        deterministic = sorted(members, key=_fallback_key)
        order_a[group] = deterministic
        order_b[group] = deterministic
        errors.append(facility_share_fallback_warning(group=group, candidate_count=len(members)))
        logger.warning(
            "facility share %s: all %d candidates carry a non-finite own-approach RWA; "
            "falling back to the deterministic risk-weight ordering",
            group,
            len(members),
        )

    metric_used, trea_alternative, winners = _choose_assignment(
        order_a,
        order_b,
        results=results,
        resolvable=resolvable,
        evaluate_trea=evaluate_trea,
        use_floored_branch=use_floored_branch,
    )

    resolution = _build_resolution(
        order_a,
        order_b,
        winners=winners,
        fallback_groups=fallback_groups,
        metric_used=metric_used,
        use_floored_branch=use_floored_branch,
    )
    collapse = {
        winner[REFERENCE_COL]: _collapsed_reference(winner[REFERENCE_COL])
        for winner in winners.values()
    }
    dropped = tuple(row[REFERENCE_COL] for row in rows if row[REFERENCE_COL] not in collapse)
    logger.info(
        "facility share: resolved %d group(s) over %d candidate(s) on the %s metric",
        len(groups),
        len(rows),
        metric_used,
    )
    return resolution, FacilityShareSummary(
        metric_used=metric_used,
        trea_alternative=trea_alternative,
        errors=errors,
        collapse=collapse,
        dropped=dropped,
    )


def resolvable_candidate() -> pl.Expr:
    """A row this module will rank: flagged a candidate AND naming its group.

    The caller probes the book with this SAME expression before building the
    closure, so "is there anything to resolve?" and "what did the resolver
    resolve?" cannot answer differently. A flagged row with no group names no
    contest, so it is left alone rather than dropped — and it stays in the
    surviving set the trial evaluation is handed, which is what keeps its RWA in
    both assignments' totals.
    """
    return candidate_flag() & _optional(GROUP_COL, pl.String).is_not_null()


def candidate_flag() -> pl.Expr:
    """``is_facility_share_candidate`` as a null-free Boolean, absence included.

    Read through an absence-tolerant selector rather than a schema branch, for
    the reason ``aggregator._optional_country`` gives: the aggregator is also
    exercised on hand-built frames that never ran the facility-undrawn producer,
    and a bare ``pl.col`` would widen this module's input contract to a column
    most portfolios have no reason to carry. A null reads as False, which is the
    edge contract's own ``null_meaning`` ("False = ordinary row"), and it is what
    keeps ``~flag`` well-formed on a frame where the column is entirely null.
    """
    return pl.coalesce(cs.by_name(CANDIDATE_COL, require_all=False), pl.lit(False))


def drop_losing_candidates(lf: pl.LazyFrame, summary: FacilityShareSummary) -> pl.LazyFrame:
    """Remove the losing candidates and collapse the winner's reference.

    Applied to every frame a candidate row can appear on. The winner's
    ``is_facility_share_candidate`` is cleared at the same time: past this
    point the group has one row like any other, and the aggregator-exit edge
    treats a surviving True as a resolver defect.
    """
    reference = pl.col(REFERENCE_COL)
    return lf.filter(~reference.is_in(list(summary.dropped))).with_columns(
        reference.replace(summary.collapse).alias(REFERENCE_COL),
        pl.when(reference.is_in(list(summary.collapse)))
        .then(pl.lit(False))
        .otherwise(candidate_flag())
        .alias(CANDIDATE_COL),
    )


def empty_resolution() -> pl.LazyFrame:
    """The typed, zero-row audit frame — the no-share and no-candidate answer."""
    return pl.DataFrame(schema=RESOLUTION_SCHEMA).lazy()


def rekey_candidate_errors(
    errors: list[CalculationError], resolution: pl.LazyFrame | None
) -> list[CalculationError]:
    """Drop or re-key the errors raised against a facility-share candidate row.

    A losing candidate is a priced row that never reaches the ledger, so a
    classification or CRM warning raised against one is noise about an exposure
    the submission does not contain — and leaving it on the error channel makes
    a clean run look dirty in proportion to how many members the facility has.
    The WINNER's own warnings are kept and re-pointed at the collapsed
    reference, because that row IS in the submission, under its suffix-free
    name.

    Returns the list unchanged when the portfolio holds no facility share (most
    of them do not) or when the audit frame is empty.

    **The caller must apply the result unconditionally.** The two effects differ
    in what they touch: suppressing a loser's error SHORTENS the list, but
    re-keying the winner's REWRITES an element in place. A caller that guards on
    the length therefore discards the whole pass whenever only the winner raised
    anything — measured, ``['G_UNDRAWN@WIN'] -> ['G_UNDRAWN']`` at equal length
    — and the ``@<member>`` suffix leaks onto the error channel naming a row the
    results frame does not contain. Length is a valid measure of how many errors
    were DROPPED, and of nothing else.
    """
    if resolution is None or not errors:
        return errors
    audit = collect_views({"resolution": resolution})["resolution"]
    if not audit.height:
        return errors
    rows = audit.to_dicts()
    collapse = {
        row[REFERENCE_COL]: row["collapsed_exposure_reference"] for row in rows if row["is_winner"]
    }
    candidates = {row[REFERENCE_COL] for row in rows}
    kept: list[CalculationError] = []
    for error in errors:
        reference = error.exposure_reference
        if reference is None or reference not in candidates:
            kept.append(error)
        elif reference in collapse:
            kept.append(replace(error, exposure_reference=collapse[reference]))
    return kept


# =============================================================================
# Private helpers
# =============================================================================


def _candidate_inputs(own_rwa_col: str) -> list[pl.Expr]:
    """The columns the ranking and the audit frame need, absence tolerated.

    Only ``exposure_reference``, ``counterparty_reference``, ``approach_applied``
    and the caller-resolved own-RWA column are read hard — every branch exit
    seals all four. The rest go through the optional selector so a synthetic or
    partial frame ranks on what it has instead of raising.
    """
    return [
        pl.col(GROUP_COL),
        pl.col(REFERENCE_COL),
        pl.col(COUNTERPARTY_COL),
        _optional(OWNER_COL, pl.String),
        pl.col(APPROACH_COL),
        _optional(CLASS_COL, pl.String),
        _optional(EAD_COL, pl.Float64),
        pl.col(own_rwa_col).cast(pl.Float64).alias(OWN_RWA_COL),
        _optional(SA_RWA_COL, pl.Float64),
        _optional(RISK_WEIGHT_COL, pl.Float64),
        _optional(PD_COL, pl.Float64),
        _optional(CQS_COL, pl.Int16),
    ]


def _optional(column: str, dtype: PolarsDataType) -> pl.Expr:
    """``column`` where the frame has it, a typed null where it does not."""
    return pl.coalesce(cs.by_name(column, require_all=False), pl.lit(None, dtype=dtype)).alias(
        column
    )


def _floored_contribution(row: dict[str, Any], floor_pct: float) -> float | None:
    """``b_i`` — the member's marginal contribution to the FLOORED branch.

    ONE predicate, and the place an implementer goes wrong. A member on a
    floor-eligible approach contributes ``x . s_i`` (it sits inside the
    Art. 92(2A) max, scaled); every other member contributes its full ``u_i``
    (it sits OUTSIDE the max, unscaled). Keyed on
    ``FLOOR_ELIGIBLE_APPROACHES``, never on "not in ``IRB_APPROACHES``": the
    two do not partition the domain — slotting and CCR-via-SA are floor-eligible
    without being IRB, and ``standardised_ccr`` is deliberately kept out of
    ``SA_APPROACHES`` — so the negated form sends both down the ``u_i`` branch
    and understates the floored assignment wherever ``u_i > x . s_i``.
    """
    if row[APPROACH_COL] in FLOOR_ELIGIBLE_APPROACHES:
        sa_equivalent = row[SA_RWA_COL]
        return None if sa_equivalent is None else floor_pct * sa_equivalent
    return row[OWN_RWA_COL]


def _choose_assignment(
    order_a: dict[str, list[dict[str, Any]]],
    order_b: dict[str, list[dict[str, Any]]],
    *,
    results: pl.LazyFrame,
    resolvable: pl.Expr,
    evaluate_trea: Callable[[Sequence[str]], float],
    use_floored_branch: bool,
) -> tuple[str, float | None, dict[str, dict[str, Any]]]:
    """Pick the assignment, evaluating both end to end when they can differ.

    Under P0 the closure is never called at all, which is the observable that
    separates "P0 was computed" from "P2 was computed and happened to agree".

    Under P2 it is called exactly twice when the assignments DIFFER, and never
    when they coincide. Each call carries the WHOLE surviving book, because
    OF-ADJ's expected-loss channel makes the floored branch non-additive across
    groups and the two assignments cannot be compared on marginals. But when
    ``argmax u_i`` and ``argmax b_i`` name the same member in EVERY group, the
    two calls would be handed an identical survivor set, and ``TREA`` is a pure
    function of that set — so both totals are the same number by construction
    and there is nothing to compare. Skipping them is a saving, not a shortcut:
    it costs two whole-book expected-loss / OF-ADJ / floor evaluations plus the
    materialisation of every non-candidate reference, and on a share-dense
    all-standardised book (where ``b_i = u_i`` on every row, so the assignments
    can never differ) that measured as +233% on the aggregator stage.

    ``metric_used`` is then ``own_approach``: the own-approach ranking picked the
    winner, and no floored-branch comparison decided anything.
    ``trea_alternative`` is None for the same reason the P0 path reports None —
    only one assignment exists to report.

    Ties between two genuinely different assignments keep assignment A — an
    attribution that flipped on a tie would move obligor-level COREP rows for no
    capital reason at all.
    """
    winners_a = {group: members[0] for group, members in order_a.items()}
    if not use_floored_branch:
        return METRIC_OWN_APPROACH, None, winners_a

    winners_b = {group: members[0] for group, members in order_b.items()}
    if all(
        winner[REFERENCE_COL] == winners_b[group][REFERENCE_COL]
        for group, winner in winners_a.items()
    ):
        logger.debug(
            "facility share: assignments A and B name the same member in all %d group(s); "
            "the end-to-end totals are identical by construction and are not evaluated",
            len(winners_a),
        )
        return METRIC_OWN_APPROACH, None, winners_a

    others = collect_views({"others": results.filter(~resolvable).select(pl.col(REFERENCE_COL))})[
        "others"
    ]
    surviving = others[REFERENCE_COL].to_list()
    trea_a = evaluate_trea([*surviving, *(row[REFERENCE_COL] for row in winners_a.values())])
    trea_b = evaluate_trea([*surviving, *(row[REFERENCE_COL] for row in winners_b.values())])
    if trea_b > trea_a:
        return METRIC_SA_EQUIVALENT, trea_a, winners_b
    return METRIC_OWN_APPROACH, trea_b, winners_a


def _build_resolution(
    order_a: dict[str, list[dict[str, Any]]],
    order_b: dict[str, list[dict[str, Any]]],
    *,
    winners: dict[str, dict[str, Any]],
    fallback_groups: set[str],
    metric_used: str,
    use_floored_branch: bool,
) -> pl.LazyFrame:
    """One audit row per candidate, eager-backed like every other bundle frame."""
    out: list[dict[str, Any]] = []
    for group, members in order_a.items():
        is_fallback = group in fallback_groups
        rank_a = {row[REFERENCE_COL]: index for index, row in enumerate(members, start=1)}
        rank_b = {row[REFERENCE_COL]: index for index, row in enumerate(order_b[group], start=1)}
        winner_reference = winners[group][REFERENCE_COL]
        for row in members:
            reference = row[REFERENCE_COL]
            is_winner = reference == winner_reference
            scored = use_floored_branch and not is_fallback
            out.append(
                {
                    GROUP_COL: group,
                    REFERENCE_COL: reference,
                    COUNTERPARTY_COL: row[COUNTERPARTY_COL],
                    OWNER_COL: row[OWNER_COL],
                    APPROACH_COL: row[APPROACH_COL],
                    CLASS_COL: row[CLASS_COL],
                    EAD_COL: row[EAD_COL],
                    OWN_RWA_COL: row[OWN_RWA_COL],
                    SA_RWA_COL: row[SA_RWA_COL],
                    RISK_WEIGHT_COL: row[RISK_WEIGHT_COL],
                    FLOORED_CONTRIBUTION_COL: (
                        row.get(FLOORED_CONTRIBUTION_COL) if scored else None
                    ),
                    "rank_own_approach": None if is_fallback else rank_a[reference],
                    "rank_floored_branch": rank_b[reference] if scored else None,
                    "is_winner": is_winner,
                    "metric_used": METRIC_FALLBACK if is_fallback else metric_used,
                    "collapsed_exposure_reference": (
                        _collapsed_reference(reference) if is_winner else None
                    ),
                }
            )
    return pl.DataFrame(out, schema=RESOLUTION_SCHEMA).lazy()


def _collapsed_reference(reference: str) -> str:
    """``<facility>_UNDRAWN@<member>`` -> ``<facility>_UNDRAWN``.

    The inverse of the hierarchy's fan-out suffix, so the aggregator exit keeps
    today's invariant of one undrawn row per facility and no ``@`` grammar leaks
    into COREP, Pillar 3, the reconciliation or the supervisory register. A
    reference carrying no suffix is returned unchanged.
    """
    return reference.rsplit("@", 1)[0]


def _own_approach_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Assignment A / P0 order: own RWA desc, then the design-of-record chain.

    ``pd_floored`` is populated on modelled rows and ``cqs`` on externally-rated
    ones, so on a mixed-approach group that rung discriminates only within an
    approach — the final reference rungs are what make the order total, and what
    stop the winner depending on input row order.
    """
    return (
        _descending(row[OWN_RWA_COL]),
        *_tie_break_chain(row),
    )


def _floored_branch_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Assignment B order: ``b_i`` desc, then the same chain as assignment A."""
    return (
        _descending(row.get(FLOORED_CONTRIBUTION_COL)),
        _descending(row[OWN_RWA_COL]),
        *_tie_break_chain(row),
    )


def _fallback_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Deterministic order for a group with no usable own-approach RWA.

    Risk weight descending, then the reference — the last rung has to be a value
    the engine always has, or the fallback is itself undefined and the winner
    depends on input row order.
    """
    return (_descending(row[RISK_WEIGHT_COL]), *_reference_rungs(row))


def _tie_break_chain(row: dict[str, Any]) -> tuple[Any, ...]:
    """risk weight desc -> PD desc -> CQS desc -> reference asc (worse credit first)."""
    return (
        _descending(row[RISK_WEIGHT_COL]),
        _descending(row[PD_COL]),
        _descending(row[CQS_COL]),
        *_reference_rungs(row),
    )


def _reference_rungs(row: dict[str, Any]) -> tuple[Any, ...]:
    """The total-order backstop: counterparty ascending, then the row reference."""
    counterparty = row[COUNTERPARTY_COL]
    return ((counterparty is None, counterparty or ""), row[REFERENCE_COL])


def _descending(value: float | int | None) -> tuple[bool, float]:
    """Sort key placing larger values first and unusable ones LAST.

    ``nulls_last`` in expression form. Without it a null sorts first under a
    descending order in Polars, so the member the engine knows LEAST about would
    win every tie. A NaN is treated as unusable rather than compared, because a
    NaN in a sort key makes the whole ordering non-deterministic.
    """
    if value is None or not _is_usable(value):
        return (True, 0.0)
    return (False, -float(value))


def _is_usable(value: float | int | None) -> bool:
    """A metric the ranking can act on: present and finite."""
    return value is not None and math.isfinite(value)
