"""
Unit tests for the facility-share resolver on synthetic frames.

Pipeline position:
    calculators -> OutputAggregator.aggregate
        -> engine/aggregator/_facility_share.py::resolve_facility_shares
        -> compute_el_portfolio_summary -> apply_floor_with_impact

Why synthetic frames rather than the FS-1 portfolio
---------------------------------------------------
Four properties of the resolver are UNREACHABLE from the acceptance portfolio,
and two of them are the ones an implementer is most likely to get wrong:

- **The tie-break chain.** Every metric on FS-1 is distinct by more than 10%, on
  purpose. A near-tie there would exercise the chain silently.
- **The all-non-finite group.** No FS-1 candidate produces a NaN.
- **``b_i`` on a slotting or CCR-via-SA candidate.** FS-1 has neither row, so a
  ``b_i`` predicate written as "not in ``IRB_APPROACHES``" instead of "in
  ``FLOOR_ELIGIBLE_APPROACHES``" passes every acceptance guard. That is the
  Attack-8 sibling shape: the repo offers ``is_in(list(FLOOR_ELIGIBLE_APPROACHES))``
  at ``aggregator.py`` (correct) and ``not in IRB_APPROACHES`` elsewhere (wrong
  here), and ``standardised_ccr`` is deliberately in the first set and NOT in
  ``SA_APPROACHES``.
- **``argmax b_i`` versus ``argmax s_i``.** They pick the same member on FS-1.

The resolver contract these tests assume
----------------------------------------
::

    resolution, summary = resolve_facility_shares(
        results,                 # pl.LazyFrame, the concatenated branch frames
        *,
        own_rwa_col: str,        # resolved by the CALLER via resolve_rwa_col
        evaluate_trea,           # Callable[[Sequence[str]], float]
        floor_applicable: bool,  # pack Feature AND config.output_floor scope
        floor_pct: float,        # x, from the Art. 92(5) Schedule
        metric: str,             # "floor_aware" | "own_approach"
    )

``resolution`` is the per-candidate audit LazyFrame; ``summary`` carries
``metric_used``, ``trea_alternative`` and ``errors``. The caller drives the drop
off ``resolution`` — ``is_winner`` and ``collapsed_exposure_reference`` say which
row survives and what it is renamed to — and applies it to ``combined``,
``sa_results``, ``irb_results`` AND ``slotting_results``, because
``compute_el_portfolio_summary`` reads the branch frames directly.

Two points where the proposal's signature is under-specified and this file
commits to an answer: ``floor_pct`` is a parameter (``b_i = x . s_i`` cannot be
computed without it, and the proposal's signature omits it), and ``summary`` is
an object with those three attributes rather than a tuple.

References:
- docs/plans/facility-share-riskiest-member.md Sections 5, 6.
- .claude/state/fs1-scenario-proposal.md Sections 6.2, 9 (mutations d, e, f).
- src/rwa_calc/engine/aggregator/_schemas.py::FLOOR_ELIGIBLE_APPROACHES.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import pytest

from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.aggregator._facility_share import resolve_facility_shares
from rwa_calc.engine.aggregator._schemas import (
    FLOOR_ELIGIBLE_APPROACHES,
    IRB_APPROACHES,
    SA_APPROACHES,
)

#: The Art. 92(5) transitional step the FS-1 scenario runs at. Stated here as a
#: TEST INPUT rather than read from the pack: these frames are synthetic, and the
#: point of each is the ordering the value produces, not the value itself.
X = 0.60

_OWN_RWA_COL = "rwa_post_factor"

_BASE_COLUMNS: dict[str, pl.DataType] = {
    "exposure_reference": pl.String,
    "facility_share_group": pl.String,
    "is_facility_share_candidate": pl.Boolean,
    "counterparty_reference": pl.String,
    "original_counterparty_reference": pl.String,
    "approach_applied": pl.String,
    "exposure_class": pl.String,
    "ead_final": pl.Float64,
    "risk_weight": pl.Float64,
    _OWN_RWA_COL: pl.Float64,
    "pd_floored": pl.Float64,
    "cqs": pl.Int8,
}


def candidate(
    member: str,
    *,
    group: str = "FAC",
    owner: str = "OWNER",
    approach: str = "standardised",
    u: float = 100_000.0,
    s: float | None = None,
    risk_weight: float = 0.5,
    pd_floored: float | None = None,
    cqs: int | None = None,
    ead: float = 200_000.0,
) -> dict[str, object]:
    """One candidate row as the calculators would leave it."""
    row: dict[str, object] = {
        "exposure_reference": f"{group}_UNDRAWN@{member}",
        "facility_share_group": group,
        "is_facility_share_candidate": True,
        "counterparty_reference": member,
        "original_counterparty_reference": owner,
        "approach_applied": approach,
        "exposure_class": "corporate",
        "ead_final": ead,
        "risk_weight": risk_weight,
        _OWN_RWA_COL: u,
        "pd_floored": pd_floored,
        "cqs": cqs,
    }
    if s is not None:
        row["sa_rwa"] = s
    return row


def ordinary(reference: str, *, u: float = 500_000.0, s: float | None = None) -> dict[str, object]:
    """One non-candidate row, so the resolver has a book to leave alone."""
    row: dict[str, object] = {
        "exposure_reference": reference,
        "facility_share_group": None,
        "is_facility_share_candidate": False,
        "counterparty_reference": "CP-OTHER",
        "original_counterparty_reference": None,
        "approach_applied": "foundation_irb",
        "exposure_class": "corporate",
        "ead_final": 1_000_000.0,
        "risk_weight": 0.5,
        _OWN_RWA_COL: u,
        "pd_floored": 0.01,
        "cqs": None,
    }
    if s is not None:
        row["sa_rwa"] = s
    return row


def frame(rows: list[dict[str, object]], *, with_sa_rwa: bool = True) -> pl.LazyFrame:
    """Build the results frame, with or without ``sa_rwa``.

    ``with_sa_rwa=False`` is the CRR shape and it OMITS the column entirely
    rather than nulling it — measured on a real CRR run, ``sa_rwa`` is absent
    from the results frame. A fixture that pinned it into the schema as a typed
    null could not reproduce the production absent-column path (LESSONS B1).
    """
    schema = dict(_BASE_COLUMNS)
    if with_sa_rwa:
        schema["sa_rwa"] = pl.Float64
    filled = [{name: row.get(name) for name in schema} for row in rows]
    return pl.DataFrame(filled, schema=schema).lazy()


class TreaSpy:
    """A stand-in for the aggregator's end-to-end TREA closure that counts calls."""

    def __init__(self, by_winner: dict[str, float]) -> None:
        self.by_winner = by_winner
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, surviving: Sequence[str]) -> float:
        surviving = tuple(surviving)
        self.calls.append(surviving)
        for member, value in self.by_winner.items():
            if any(reference.endswith(f"@{member}") for reference in surviving):
                return value
        raise AssertionError(f"no TREA supplied for {surviving}")


def resolve(
    results: pl.LazyFrame,
    *,
    evaluate_trea=None,  # noqa: ANN001 - a test double, deliberately untyped
    floor_applicable: bool = True,
    metric: str = "floor_aware",
    floor_pct: float = X,
):
    """Call the resolver with this file's defaults."""
    return resolve_facility_shares(
        results,
        own_rwa_col=_OWN_RWA_COL,
        evaluate_trea=evaluate_trea if evaluate_trea is not None else TreaSpy({}),
        floor_applicable=floor_applicable,
        floor_pct=floor_pct,
        metric=metric,
    )


def audit(resolution: pl.LazyFrame) -> list[dict]:
    """Collect the audit frame into plain dicts."""
    return resolution.collect().to_dicts()


def winner_of(resolution: pl.LazyFrame, group: str = "FAC") -> str:
    """The counterparty flagged ``is_winner`` for one group."""
    winners = [
        row["counterparty_reference"]
        for row in audit(resolution)
        if row["facility_share_group"] == group and row["is_winner"]
    ]
    assert len(winners) == 1, f"{group} has {len(winners)} winners, expected exactly 1"
    return winners[0]


# ---------------------------------------------------------------------------
# P0 — the own-approach metric
# ---------------------------------------------------------------------------


def test_resolver_ranks_candidates_by_own_approach_rwa() -> None:
    """
    P0 picks the largest own-approach RWA, not the largest risk weight or EAD.

    Arrange: three candidates whose own RWA ordering is the REVERSE of their
             risk-weight ordering, so a resolver ranking on the weight picks a
             different member.
    Act:     resolve with the floor inapplicable, which forces P0.
    Assert:  the winner is the largest-RWA member, and its rank is 1.

    Ranking on RWA rather than RW is decision D1: the conservative purpose is
    CAPITAL, and EAD can differ by member wherever the conversion factor or the
    credit risk mitigation depends on the obligor.
    """
    # Arrange — RWA descending is C, B, A; risk weight descending is A, B, C.
    results = frame(
        [
            candidate("M-A", u=40_000.0, risk_weight=0.90, ead=44_444.0),
            candidate("M-B", u=60_000.0, risk_weight=0.60),
            candidate("M-C", u=90_000.0, risk_weight=0.30, ead=300_000.0),
            ordinary("LOAN-1"),
        ]
    )

    # Act
    resolution, summary = resolve(results, floor_applicable=False)

    # Assert
    assert winner_of(resolution) == "M-C"
    assert summary.metric_used == "own_approach"
    ranks = {row["counterparty_reference"]: row["rank_own_approach"] for row in audit(resolution)}
    assert ranks == {"M-C": 1, "M-B": 2, "M-A": 3}


@pytest.mark.parametrize(
    ("rows", "expected", "rung"),
    [
        (
            [
                candidate("M-A", u=100_000.0, risk_weight=0.50),
                candidate("M-B", u=100_000.0, risk_weight=0.60),
            ],
            "M-B",
            "risk_weight desc",
        ),
        (
            [
                candidate("M-A", u=100_000.0, risk_weight=0.50, pd_floored=0.01),
                candidate("M-B", u=100_000.0, risk_weight=0.50, pd_floored=0.03),
            ],
            "M-B",
            "pd_floored desc (worse credit)",
        ),
        (
            [
                candidate("M-A", u=100_000.0, risk_weight=0.50, cqs=2),
                candidate("M-B", u=100_000.0, risk_weight=0.50, cqs=5),
            ],
            "M-B",
            "cqs desc (worse credit)",
        ),
        (
            [
                candidate("M-B", u=100_000.0, risk_weight=0.50),
                candidate("M-A", u=100_000.0, risk_weight=0.50),
            ],
            "M-A",
            "counterparty_reference asc",
        ),
    ],
    ids=["risk_weight", "pd_floored", "cqs", "reference"],
)
def test_resolver_tie_break_chain_is_total(
    rows: list[dict[str, object]], expected: str, rung: str
) -> None:
    """
    Ties fall through risk weight, then PD, then CQS, then the reference.

    Arrange: two candidates identical up to one rung of the chain.
    Act:     resolve under P0.
    Assert:  the member the design of record's chain selects wins.

    The ``pd_floored`` / ``cqs`` rung has limited REACH and that is honest rather
    than accidental: ``pd_floored`` is populated on modelled rows and ``cqs`` on
    externally-rated ones, so on a mixed-approach group it discriminates only
    within an approach. It is harmless with ``nulls_last`` and the final
    reference rung guarantees a total order regardless — which is what stops the
    winner depending on input row order.
    """
    # Arrange / Act
    resolution, _summary = resolve(frame(rows), floor_applicable=False)

    # Assert
    assert winner_of(resolution) == expected, f"tie-break rung under test: {rung}"


def test_resolver_tie_break_puts_nulls_last() -> None:
    """
    A null tie-break value never outranks a populated one.

    Arrange: two candidates tied on own RWA, one with a null risk weight.
    Act:     resolve under P0.
    Assert:  the populated candidate wins.

    Without ``nulls_last=True`` a null sorts first under a descending sort in
    Polars, so the member the engine knows LEAST about would win every tie.
    """
    # Arrange
    rows = [
        candidate("M-A", u=100_000.0, risk_weight=None),
        candidate("M-B", u=100_000.0, risk_weight=0.20),
    ]

    # Act
    resolution, _summary = resolve(frame(rows), floor_applicable=False)

    # Assert
    assert winner_of(resolution) == "M-B"


def test_resolver_marks_exactly_one_winner_and_one_collapsed_reference_per_group() -> None:
    """
    ``is_winner`` sums to 1 per group and only the winner is collapsed.

    Arrange: two groups of three candidates each.
    Act:     resolve under P0.
    Assert:  one winner per group; ``collapsed_exposure_reference`` is the
             suffix-free undrawn reference on the winner and null on the losers.

    The collapse is what keeps the aggregator exit's invariant — one undrawn row
    per facility — so COREP, Pillar 3, reconciliation and the supervisory
    register see the shape they see today.
    """
    # Arrange
    rows = [
        candidate(f"M-{index}", group=group, u=float(index) * 10_000.0)
        for group in ("FAC-1", "FAC-2")
        for index in (1, 2, 3)
    ]

    # Act
    resolution, _summary = resolve(frame(rows), floor_applicable=False)

    # Assert
    entries = audit(resolution)
    for group in ("FAC-1", "FAC-2"):
        group_rows = [row for row in entries if row["facility_share_group"] == group]
        assert sum(1 for row in group_rows if row["is_winner"]) == 1
        for row in group_rows:
            if row["is_winner"]:
                assert row["collapsed_exposure_reference"] == f"{group}_UNDRAWN"
            else:
                assert row["collapsed_exposure_reference"] is None


# ---------------------------------------------------------------------------
# P2 — the two-assignment rule
# ---------------------------------------------------------------------------


def test_resolver_prefers_floored_branch_not_raw_sa_equivalent() -> None:
    """
    Assignment B is ``argmax b_i``, NOT ``argmax s_i``.

    Arrange: a standardised candidate at ``u = s = 100,000`` and a foundation-IRB
             candidate at ``s = 150,000`` with a smaller ``u``, at ``x = 0.60``.
    Act:     resolve under the floor-aware default with a TREA closure that makes
             assignment B the larger.
    Assert:  the winner is the STANDARDISED candidate.

    ``b_SA = u_SA = 100,000`` because a standardised row sits outside the
    Art. 92(2A) max at FULL weight; ``b_IRB = 0.60 x 150,000 = 90,000``. So
    ``argmax b`` picks the standardised member while ``argmax s`` picks the
    modelled one. ``b_SA = u_SA`` is precisely the discriminating property, which
    is why ``u_SA`` is pinned rather than left free.

    Mutation it detects (d): assignment B computed as ``argmax s_i``.
    """
    # Arrange
    rows = [
        candidate("M-SA", approach="standardised", u=100_000.0, s=100_000.0),
        candidate("M-IRB", approach="foundation_irb", u=60_000.0, s=150_000.0),
    ]
    assert X * 150_000.0 < 100_000.0, (
        "the floored contribution of the modelled candidate must sit BELOW the "
        "standardised candidate's full RWA, or argmax b and argmax s agree and "
        "this test cannot tell them apart"
    )
    # B must win the end-to-end comparison, or P2 falls back to A and the test
    # would pass for the wrong reason.
    spy = TreaSpy({"M-SA": 2_000_000.0, "M-IRB": 1_000_000.0})

    # Act
    resolution, summary = resolve(frame(rows), evaluate_trea=spy)

    # Assert
    assert winner_of(resolution) == "M-SA"
    entries = {row["counterparty_reference"]: row for row in audit(resolution)}
    assert entries["M-SA"]["floored_branch_contribution"] == pytest.approx(100_000.0)
    assert entries["M-IRB"]["floored_branch_contribution"] == pytest.approx(X * 150_000.0)


def test_resolver_floored_branch_covers_every_floor_eligible_approach() -> None:
    """
    ``b_i`` keys on ``FLOOR_ELIGIBLE_APPROACHES``, not on ``IRB_APPROACHES``.

    Arrange: four candidates in one group — standardised, foundation IRB,
             slotting and standardised CCR — sized so the two predicates pick
             DIFFERENT winners.
    Act:     resolve under the floor-aware default.
    Assert:  the slotting candidate wins on the correct predicate.

    The two conditions do not partition the domain. ``FLOOR_ELIGIBLE_APPROACHES``
    is ``IRB_APPROACHES | {slotting, SLOTTING, standardised_ccr}``, and
    ``standardised_ccr`` is deliberately kept OUT of ``SA_APPROACHES``. Writing
    the standardised limb as "not in ``IRB_APPROACHES``" sends both the slotting
    and the CCR-via-SA candidate down the ``u_i`` branch and OVERSTATES the
    floored assignment wherever ``u_i > x . s_i``.

    A slotting candidate is production-reachable: a specialised-lending
    facility's undrawn row takes the slotting branch, and the F-IRB-only
    permission helper grants slotting for specialised lending.

    Mutation it detects (f). Note that under the mutation the slotting candidate
    scores ``b = 200,000`` rather than ``120,000`` and beats the standardised
    candidate's ``150,000``, so the winner MOVES — a mutation that merely
    perturbed a losing row would prove nothing.
    """
    # Arrange — the predicate the code must use, asserted against the module's
    # own sets rather than a hand-written list.
    assert "slotting" in FLOOR_ELIGIBLE_APPROACHES
    assert "standardised_ccr" in FLOOR_ELIGIBLE_APPROACHES
    assert "slotting" not in IRB_APPROACHES
    assert "standardised_ccr" not in IRB_APPROACHES
    assert "standardised_ccr" not in SA_APPROACHES

    rows = [
        candidate("M-STD", approach="standardised", u=150_000.0, s=150_000.0),
        candidate("M-IRB", approach="foundation_irb", u=50_000.0, s=100_000.0),
        candidate("M-SLOT", approach="slotting", u=200_000.0, s=200_000.0),
        candidate("M-CCR", approach="standardised_ccr", u=60_000.0, s=100_000.0),
    ]
    correct_b = {"M-STD": 150_000.0, "M-IRB": X * 100_000.0, "M-SLOT": X * 200_000.0}
    assert max(correct_b, key=lambda key: correct_b[key]) == "M-STD", (
        "sized so the CORRECT predicate picks the standardised candidate and "
        "the mutated one picks the slotting candidate at its unscaled 200,000"
    )
    spy = TreaSpy({"M-STD": 9_000_000.0, "M-SLOT": 1_000_000.0, "M-IRB": 1_000_000.0})

    # Act
    resolution, _summary = resolve(frame(rows), evaluate_trea=spy)

    # Assert — the winner, and the per-row contribution that decided it.
    entries = {row["counterparty_reference"]: row for row in audit(resolution)}
    assert entries["M-SLOT"]["floored_branch_contribution"] == pytest.approx(X * 200_000.0)
    assert entries["M-CCR"]["floored_branch_contribution"] == pytest.approx(X * 100_000.0)
    assert entries["M-STD"]["floored_branch_contribution"] == pytest.approx(150_000.0)
    assert winner_of(resolution) == "M-STD"


def test_resolver_evaluates_the_trea_closure_exactly_twice_under_p2() -> None:
    """
    P2 evaluates both assignments end to end — twice, never more.

    Arrange: a group whose two assignments name different winners.
    Act:     resolve under the floor-aware default.
    Assert:  the closure was called exactly twice, once per assignment, each time
             with the full surviving reference set.

    P2 is NOT a closed form. The OF-ADJ expected-loss channel makes the floored
    branch non-additive across groups, so the resolver must recompute the EL
    summary per assignment rather than compare marginals — "the better of A and
    B, evaluated exactly", a bound rather than an identity. Counting the calls is
    what distinguishes that from a marginal comparison dressed up as one.
    """
    # Arrange
    rows = [
        candidate("M-SA", approach="standardised", u=100_000.0, s=100_000.0),
        candidate("M-IRB", approach="foundation_irb", u=40_000.0, s=200_000.0),
        ordinary("LOAN-1", s=500_000.0),
    ]
    spy = TreaSpy({"M-SA": 1_000_000.0, "M-IRB": 1_100_000.0})

    # Act
    resolution, summary = resolve(frame(rows), evaluate_trea=spy)

    # Assert
    assert len(spy.calls) == 2, f"closure called {len(spy.calls)} times"
    for surviving in spy.calls:
        assert "LOAN-1" in surviving, "the closure evaluates the WHOLE book, not just the share"
        assert sum(1 for reference in surviving if reference.startswith("FAC_UNDRAWN@")) == 1
    assert winner_of(resolution) == "M-IRB"
    assert summary.metric_used == "sa_equivalent"
    assert summary.trea_alternative == pytest.approx(1_000_000.0)


def test_resolver_ties_between_assignments_go_to_assignment_a() -> None:
    """
    An exact TREA tie keeps assignment A, for attribution stability.

    Arrange: a group where the two assignments produce the SAME total.
    Act:     resolve under the floor-aware default.
    Assert:  the own-approach winner survives and the metric is ``own_approach``.

    An attribution that flipped on a tie would move obligor-level COREP rows for
    no capital reason at all.
    """
    # Arrange
    rows = [
        candidate("M-SA", approach="standardised", u=100_000.0, s=100_000.0),
        candidate("M-IRB", approach="foundation_irb", u=40_000.0, s=200_000.0),
    ]
    spy = TreaSpy({"M-SA": 1_000_000.0, "M-IRB": 1_000_000.0})

    # Act
    resolution, summary = resolve(frame(rows), evaluate_trea=spy)

    # Assert
    assert winner_of(resolution) == "M-SA"
    assert summary.metric_used == "own_approach"


@pytest.mark.parametrize(
    ("metric", "floor_applicable"),
    [("own_approach", True), ("floor_aware", False)],
    ids=["election_pins_p0", "floor_inapplicable"],
)
def test_resolver_forces_p0_and_never_evaluates_trea(metric: str, floor_applicable: bool) -> None:
    """
    Either the election or an inapplicable floor reduces the resolver to P0.

    Arrange: a group where P0 and P2 pick different members.
    Act:     resolve with the election set, then with the floor inapplicable.
    Assert:  the own-approach winner survives and the TREA closure is never
             called.

    The gate is ``pack.feature("output_floor") AND
    config.output_floor.is_entity_in_scope()`` — composed by the caller and
    passed in as ``floor_applicable``. Not calling the closure is the observable
    that separates "P0 was computed" from "P2 was computed and happened to agree".
    """
    # Arrange
    rows = [
        candidate("M-SA", approach="standardised", u=100_000.0, s=100_000.0),
        candidate("M-IRB", approach="foundation_irb", u=40_000.0, s=300_000.0),
    ]
    spy = TreaSpy({"M-SA": 1.0, "M-IRB": 9_999_999.0})

    # Act
    resolution, summary = resolve(
        frame(rows), evaluate_trea=spy, metric=metric, floor_applicable=floor_applicable
    )

    # Assert
    assert spy.calls == [], "P0 must not evaluate the end-to-end TREA at all"
    assert winner_of(resolution) == "M-SA"
    assert summary.metric_used == "own_approach"


# ---------------------------------------------------------------------------
# The CRR shape: sa_rwa is ABSENT, not null
# ---------------------------------------------------------------------------


def test_resolver_computes_p0_when_sa_rwa_is_absent() -> None:
    """
    Under CRR the results frame has no ``sa_rwa`` column at all.

    Arrange: a frame built WITHOUT the column, and the floor inapplicable.
    Act:     resolve.
    Assert:  the own-approach winner survives, and the audit frame's floor-side
             columns are TYPED nulls rather than missing.

    Branch on PRESENCE, not on a null test: measured on a real CRR run,
    ``sa_rwa`` and ``rwa_pre_floor`` are absent from the results frame.
    A resolver that reads ``sa_rwa`` unconditionally raises
    ``ColumnNotFoundError`` on every CRR run — mutation (e). A presence guard
    written from the Basel 3.1 side alone is the LESSONS B1 shape.

    The audit columns stay typed so a downstream consumer sees one schema in both
    regimes rather than two.
    """
    # Arrange
    rows = [
        candidate("M-SA", approach="standardised", u=100_000.0),
        candidate("M-IRB", approach="foundation_irb", u=82_000.0),
        candidate("M-LOW", approach="standardised", u=40_000.0),
    ]
    results = frame(rows, with_sa_rwa=False)
    assert "sa_rwa" not in results.collect_schema().names(), (
        "the CRR shape must OMIT the column; pinning it as a typed null cannot "
        "reproduce the production absent-column path"
    )

    # Act
    resolution, summary = resolve(results, floor_applicable=False)

    # Assert
    assert winner_of(resolution) == "M-SA"
    assert summary.metric_used == "own_approach"
    assert summary.trea_alternative is None

    schema = resolution.collect_schema()
    assert schema["sa_rwa"] == pl.Float64
    assert schema["floored_branch_contribution"] == pl.Float64
    assert schema["rank_floored_branch"] == pl.UInt32
    for row in audit(resolution):
        assert row["sa_rwa"] is None
        assert row["floored_branch_contribution"] is None
        assert row["rank_floored_branch"] is None
        assert row["rank_own_approach"] is not None


# ---------------------------------------------------------------------------
# The all-non-finite group
# ---------------------------------------------------------------------------


def test_resolver_never_drops_a_group_whose_metrics_are_all_non_finite() -> None:
    """
    A group with no usable metric falls back deterministically — it is never dropped.

    Arrange: a group whose three candidates all carry a NaN own RWA but usable
             risk weights.
    Act:     resolve under P0.
    Assert:  a winner is still chosen, by risk weight descending; the audit frame
             keeps every candidate with a null rank and
             ``metric_used == "fallback_deterministic"``; and one AGG-family
             WARNING names the group.

    Dropping every candidate would silently delete the facility's undrawn
    exposure from the submission, which is this project's dominant escape class.
    The warning is what makes the fallback attributable rather than merely
    survivable — a log line is not a gate.
    """
    # Arrange
    nan = float("nan")
    rows = [
        candidate("M-A", u=nan, risk_weight=0.20),
        candidate("M-B", u=nan, risk_weight=0.90),
        candidate("M-C", u=nan, risk_weight=0.50),
    ]

    # Act
    resolution, summary = resolve(frame(rows), floor_applicable=False)

    # Assert — the group survives, and the fallback is the risk-weight rung.
    entries = audit(resolution)
    assert len(entries) == 3, "every candidate stays on the audit frame"
    assert winner_of(resolution) == "M-B"
    for row in entries:
        assert row["rank_own_approach"] is None
        assert row["metric_used"] == "fallback_deterministic"

    # Assert — and it is reported, once, naming the group.
    warnings = [error for error in summary.errors if error.code.startswith("AGG")]
    assert len(warnings) == 1, [error.code for error in summary.errors]
    assert warnings[0].severity == ErrorSeverity.WARNING
    assert "FAC" in warnings[0].message
    assert "3" in warnings[0].message, "the message states the candidate count"


def test_resolver_falls_back_to_the_reference_when_every_metric_is_non_finite() -> None:
    """
    With the risk weight non-finite too, the winner is the first reference.

    Arrange: a group whose own RWA AND risk weight are both NaN throughout.
    Act:     resolve under P0.
    Assert:  the alphabetically first member wins and the group survives.

    The last rung has to be a value the engine always has, or the fallback is
    itself undefined and the winner depends on input row order.
    """
    # Arrange
    nan = float("nan")
    rows = [
        candidate("M-C", u=nan, risk_weight=nan),
        candidate("M-A", u=nan, risk_weight=nan),
        candidate("M-B", u=nan, risk_weight=nan),
    ]

    # Act
    resolution, _summary = resolve(frame(rows), floor_applicable=False)

    # Assert
    assert winner_of(resolution) == "M-A"
    assert len(audit(resolution)) == 3


def test_resolver_leaves_non_candidate_rows_alone() -> None:
    """
    Only flagged candidate rows enter the audit frame.

    Arrange: one share plus two ordinary rows.
    Act:     resolve under P0.
    Assert:  the audit frame holds the candidates and nothing else.

    A resolver that keyed on ``facility_share_group`` being non-null without also
    reading the candidate flag would behave identically here; the flag matters on
    the aggregator exit, where the winner keeps its group but is no longer a
    candidate.
    """
    # Arrange
    rows = [
        candidate("M-A", u=100_000.0),
        candidate("M-B", u=50_000.0),
        ordinary("LOAN-1"),
        ordinary("LOAN-2"),
    ]

    # Act
    resolution, _summary = resolve(frame(rows), floor_applicable=False)

    # Assert
    references = {row["exposure_reference"] for row in audit(resolution)}
    assert references == {"FAC_UNDRAWN@M-A", "FAC_UNDRAWN@M-B"}
