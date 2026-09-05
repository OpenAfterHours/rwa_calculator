"""
Unit tests for the hierarchy-stage facility-share candidate fan-out.

Pipeline position:
    Loader -> HierarchyResolver
        (engine/hierarchy/facility_undrawn.py::calculate_facility_undrawn)
        -> Classifier

What changes here
-----------------
Today a Facility Share emits ONE synthetic undrawn row, whose counterparty is
chosen by an SA-only preview risk weight. The design of record replaces that with
a fan-out: one candidate row per member, each carrying the FULL headroom (each is
"as if this member drew it all"), each keyed ``<facility>_UNDRAWN@<member>``, and
each flagged so the aggregator can find them again. The choice moves downstream
to a resolution step that can see every candidate's real, priced RWA.

Two decisions are pinned here because nothing else can see them:

- **D3, the owner is always a member.** Today the member set is the distinct
  counterparties on DESCENDANT exposures only, so a facility owned by A whose only
  loans belong to B and C has member set {B, C} and A — the legal borrower who can
  draw the whole line — is not ranked at all. That is not a row-count nicety: on
  the FS-1 portfolio the owner is the un-floored metric's winner.
- **D4, candidates count toward their own member's obligor aggregates**, with no
  window special-casing. The direction matters: a losing member's siblings GAIN
  the undrawn in their totals, so the partition-local thresholds can only be
  crossed upward, which is the conservative reading of "total amount owed" for a
  commitment any member may draw.

These tests drive ``calculate_facility_undrawn`` directly on hand-built frames and
``HierarchyResolver.resolve`` on the FS-1 bundle. They deliberately do NOT edit
``tests/unit/test_hierarchy.py``, whose ``TestP1307FacilityShareEntityPreview``
class pins the preview this change deletes; re-pointing those is the
implementation wave's job and is listed in the design of record's S5 row.

References:
- docs/plans/facility-share-riskiest-member.md Sections 4 (O2) and 7 (D3, D4).
- .claude/state/fs1-scenario-proposal.md Section 6.1.
- CRR Art. 147 — "total amount owed" is the drawn amount, which is why an
  undrawn row contributes zero to the retail-threshold aggregate.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.hierarchy.facility_undrawn import calculate_facility_undrawn
from tests.fixtures.facility_share_portfolio import (
    CP_ANCHOR,
    CP_IRB,
    CP_LOW,
    CP_SA,
    DRAWN_ANCHOR,
    DRAWN_IRB,
    DRAWN_LOW,
    DRAWN_SOLO,
    FAC_SOLO,
    HEADROOM_SHARE,
    HEADROOM_SOLO,
    build_facility_share_bundle,
    facility_share_config,
)
from tests.fixtures.raw_bundle import seal_raw_table

_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 1, 1)
_REPORTING_DATE = date(2024, 12, 31)

_OWNER = "CP-OWNER"
_MEMBER_A = "CP-MEM-A"
_MEMBER_B = "CP-MEM-B"
_FACILITY = "SHARE-FAC"
_LIMIT = 1_000_000.0
_DRAWN = 100_000.0
#: 1,000,000 limit less two 100,000 descendant loans.
_HEADROOM = _LIMIT - 2 * _DRAWN


# ---------------------------------------------------------------------------
# Frame builders — loader-sealed, as the hierarchy helpers assume
# ---------------------------------------------------------------------------


def _counterparties(references: tuple[str, ...], *, cqs: dict[str, int]) -> pl.LazyFrame:
    """Corporate obligors with external CQS ratings, so a preview COULD rank them."""
    return pl.DataFrame(
        {
            "counterparty_reference": list(references),
            "counterparty_name": list(references),
            "entity_type": ["corporate"] * len(references),
            "country_code": ["GB"] * len(references),
            "default_status": [False] * len(references),
        }
    ).lazy(), pl.DataFrame(
        {
            "rating_reference": [f"RTG-{ref}" for ref in references],
            "counterparty_reference": list(references),
            "rating_type": ["external"] * len(references),
            "rating_agency": ["MOODYS"] * len(references),
            "cqs": [cqs[ref] for ref in references],
            "pd": [None] * len(references),
            "rating_date": [_VALUE_DATE] * len(references),
            "is_solicited": [True] * len(references),
        }
    ).lazy()


def _facility(owner: str, *, reference: str = _FACILITY, limit: float = _LIMIT) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "facility_reference": [reference],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": [owner],
            "value_date": [_VALUE_DATE],
            "maturity_date": [_MATURITY_DATE],
            "currency": ["GBP"],
            "limit": [limit],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }
    ).lazy()


def _loans(members: tuple[str, ...], *, parent: str = _FACILITY) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "loan_reference": [f"L-{parent}-{member}" for member in members],
            "product_type": ["TERM_LOAN"] * len(members),
            "book_code": ["CORP"] * len(members),
            "counterparty_reference": list(members),
            "value_date": [_VALUE_DATE] * len(members),
            "maturity_date": [_MATURITY_DATE] * len(members),
            "currency": ["GBP"] * len(members),
            "drawn_amount": [_DRAWN] * len(members),
            "interest": [0.0] * len(members),
            "seniority": ["senior"] * len(members),
        }
    ).lazy()


def _mappings(
    members: tuple[str, ...], *, parent: str = _FACILITY, extra: list[dict] | None = None
) -> pl.LazyFrame:
    rows = [
        {
            "parent_facility_reference": parent,
            "child_reference": f"L-{parent}-{member}",
            "child_type": "loan",
        }
        for member in members
    ]
    return pl.DataFrame(
        rows + (extra or []),
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        },
    ).lazy()


def _assert_carriers_present(row: dict) -> None:
    """Both new columns are on the row at all.

    Checked before reading either, so a pre-change run fails on THIS assertion
    with its reason rather than raising ``KeyError`` from a dict lookup — an
    exception reports a broken test where a failure reports a missing feature.
    """
    for column in ("facility_share_group", "is_facility_share_candidate"):
        assert column in row, f"{column} is not produced by the hierarchy stage"


def _undrawn(
    *,
    owner: str,
    members: tuple[str, ...],
    cqs: dict[str, int],
    facilities: pl.LazyFrame | None = None,
    mappings: pl.LazyFrame | None = None,
    loans: pl.LazyFrame | None = None,
) -> list[dict]:
    """Run ``calculate_facility_undrawn`` on sealed frames and return its rows."""
    resolver = HierarchyResolver()
    references = tuple(dict.fromkeys((owner, *members)))
    counterparties, ratings = _counterparties(references, cqs=cqs)
    facilities = facilities if facilities is not None else _facility(owner)
    loans = loans if loans is not None else _loans(members)
    mappings = mappings if mappings is not None else _mappings(members)

    sealed_mappings = seal_raw_table(mappings, "facility_mappings")
    counterparty_lookup, _errors = resolver._build_counterparty_lookup(
        seal_raw_table(counterparties, "counterparties"),
        None,
        seal_raw_table(ratings, "ratings"),
    )
    return (
        calculate_facility_undrawn(
            seal_raw_table(facilities, "facilities"),
            seal_raw_table(loans, "loans"),
            None,
            sealed_mappings,
            resolver._build_facility_root_lookup(sealed_mappings),
            counterparty_lookup=counterparty_lookup,
            config=CalculationConfig.crr(reporting_date=_REPORTING_DATE),
        )
        .collect()
        .to_dicts()
    )


# ---------------------------------------------------------------------------
# The fan-out itself
# ---------------------------------------------------------------------------


def test_facility_share_emits_one_candidate_row_per_member() -> None:
    """
    A share emits one undrawn candidate per member, each with the FULL headroom.

    Arrange: a facility owned by CP-OWNER with two mapped loans belonging to
             CP-MEM-A and CP-MEM-B, and 800,000 of headroom.
    Act:     calculate the facility undrawn rows.
    Assert:  three rows, keyed ``SHARE-FAC_UNDRAWN@<member>``, each carrying the
             whole 800,000, the group, the candidate flag and the owner.

    Every candidate carries the whole headroom because each is "as if this member
    drew it all" — the undrawn AMOUNT never changes and nothing is drawn-weighted.
    Splitting it pro-rata would price a commitment any single member could draw in
    full against a fraction of itself.

    Red today: one row, ``SHARE-FAC_UNDRAWN``, whose counterparty is whichever
    member the SA preview ranked highest.
    """
    # Arrange / Act
    rows = _undrawn(
        owner=_OWNER,
        members=(_MEMBER_A, _MEMBER_B),
        cqs={_OWNER: 2, _MEMBER_A: 1, _MEMBER_B: 5},
    )

    # Assert — shape.
    by_reference = {row["exposure_reference"]: row for row in rows}
    assert set(by_reference) == {
        f"{_FACILITY}_UNDRAWN@{member}" for member in (_OWNER, _MEMBER_A, _MEMBER_B)
    }, sorted(by_reference)

    # Assert — every candidate row's carriers.
    for member in (_OWNER, _MEMBER_A, _MEMBER_B):
        row = by_reference[f"{_FACILITY}_UNDRAWN@{member}"]
        assert row["counterparty_reference"] == member
        assert row["original_counterparty_reference"] == _OWNER
        assert row["facility_share_group"] == _FACILITY
        assert row["is_facility_share_candidate"] is True
        assert row["undrawn_amount"] == pytest.approx(_HEADROOM), (
            "each candidate carries the FULL headroom; a pro-rata split would "
            "under-capitalise a line any single member can draw in full"
        )
        assert row["source_exposure_reference"] == _FACILITY, (
            "reconciliation keys on source_exposure_reference, so it must stay "
            "the bare facility reference through the fan-out"
        )


def test_hierarchy_owner_is_always_a_member() -> None:
    """
    D3: the facility OWNER is a candidate even with no descendant loan of its own.

    Arrange: a facility owned by CP-OWNER whose only mapped loans belong to
             CP-MEM-A and CP-MEM-B — the owner has no exposure under it.
    Act:     calculate the facility undrawn rows.
    Assert:  the owner appears as a candidate.

    Today's detection rule collects distinct counterparties on DESCENDANTS only,
    so this owner is not a member at all. Under D3 the owner is the legal borrower
    and can draw, so it is ranked with the rest.

    Mutation it detects (b): revert D3, i.e. build the member set from
    descendants alone. That reproduces today's behaviour exactly, drops the
    candidate count to two, and on the FS-1 portfolio moves the winner, the
    applied approach and the priced RWA.
    """
    # Arrange
    owner_has_no_loan = {_OWNER, _MEMBER_A, _MEMBER_B} - {_MEMBER_A, _MEMBER_B}
    assert owner_has_no_loan == {_OWNER}, (
        "the owner must hold no descendant loan, or this test passes under "
        "today's descendants-only rule and proves nothing about D3"
    )

    # Act
    rows = _undrawn(
        owner=_OWNER,
        members=(_MEMBER_A, _MEMBER_B),
        cqs={_OWNER: 2, _MEMBER_A: 1, _MEMBER_B: 5},
    )

    # Assert
    members = {row["counterparty_reference"] for row in rows}
    assert _OWNER in members, f"candidate members are {sorted(members)}"


def test_two_member_facility_where_the_owner_holds_no_loan_is_a_share() -> None:
    """
    D3 also changes DETECTION: owner + one descendant is two members, so a share.

    Arrange: a facility owned by CP-OWNER with a single mapped loan belonging to
             CP-MEM-A.
    Act:     calculate the facility undrawn rows.
    Assert:  two candidate rows, one per member.

    Today this facility has ONE member and is not a share at all; its undrawn
    stays with the owner through the ``coalesce`` fallback. This is the shape the
    estate already contains — ``tests/fixtures/exposures`` holds exactly one
    owner-mismatch facility — so the blast radius of D3 is measured with the FULL
    unit suite, not with grep.
    """
    # Arrange / Act
    rows = _undrawn(
        owner=_OWNER,
        members=(_MEMBER_A,),
        cqs={_OWNER: 2, _MEMBER_A: 5},
    )

    # Assert
    assert {row["counterparty_reference"] for row in rows} == {_OWNER, _MEMBER_A}
    assert all(row["is_facility_share_candidate"] for row in rows)


def test_single_member_facility_is_not_fanned_out() -> None:
    """
    A facility whose owner is its only member keeps one ordinary undrawn row.

    Arrange: a facility owned by CP-OWNER whose only mapped loan is also
             CP-OWNER's.
    Act:     calculate the facility undrawn rows.
    Assert:  one row, un-suffixed, with a null group and a False candidate flag.

    The control leg. A null group is what tells every downstream consumer this
    row was never allocated, and a False flag rather than a null keeps the column
    Boolean rather than tri-state.
    """
    # Arrange / Act
    rows = _undrawn(owner=_OWNER, members=(_OWNER,), cqs={_OWNER: 2})

    # Assert
    assert len(rows) == 1
    row = rows[0]
    assert row["exposure_reference"] == f"{_FACILITY}_UNDRAWN"
    assert row["counterparty_reference"] == _OWNER
    _assert_carriers_present(row)
    assert row["facility_share_group"] is None
    assert row["is_facility_share_candidate"] is False


def test_multiple_option_facility_parent_is_not_fanned_out() -> None:
    """
    A Multiple Option Facility parent keeps today's exclusion from the fan-out.

    Arrange: a parent facility with a ``child_type="facility"`` mapping, which is
             what makes it a MOF, plus loans under both parent and sub.
    Act:     calculate the facility undrawn rows.
    Assert:  no row of the MOF parent carries the candidate flag.

    A MOF's per-sub waterfall rows already carry each sub's own counterparty, so
    the allocation question does not arise there and the residual row is the
    parent's own risk type. Revisiting that needs a portfolio that has one; until
    then the exclusion is pinned so a fan-out cannot silently start splitting a
    waterfall.
    """
    # Arrange — a sub-facility under the parent makes the parent a MOF.
    sub = "SUB-FAC"
    facilities = pl.concat(
        [_facility(_OWNER), _facility(_MEMBER_A, reference=sub, limit=400_000.0)]
    )
    loans = pl.concat([_loans((_MEMBER_A,)), _loans((_MEMBER_B,), parent=sub)])
    mappings = _mappings(
        (_MEMBER_A,),
        extra=[
            {
                "parent_facility_reference": _FACILITY,
                "child_reference": sub,
                "child_type": "facility",
            },
            {
                "parent_facility_reference": sub,
                "child_reference": f"L-{sub}-{_MEMBER_B}",
                "child_type": "loan",
            },
        ],
    )

    # Act
    rows = _undrawn(
        owner=_OWNER,
        members=(_MEMBER_A, _MEMBER_B),
        cqs={_OWNER: 2, _MEMBER_A: 1, _MEMBER_B: 5},
        facilities=facilities,
        loans=loans,
        mappings=mappings,
    )

    # Assert
    parent_rows = [
        row
        for row in rows
        if row.get("source_exposure_reference") == _FACILITY
        or row["exposure_reference"].startswith(f"{_FACILITY}_UNDRAWN")
    ]
    assert parent_rows, "the MOF parent must still emit its undrawn rows"
    for row in parent_rows:
        _assert_carriers_present(row)
    assert not [row for row in parent_rows if row["is_facility_share_candidate"]], (
        "the MOF waterfall rows already carry each sub's counterparty, so the "
        "parent is excluded from the share fan-out"
    )
    assert not [row for row in parent_rows if "@" in row["exposure_reference"]], (
        "the @<member> grammar must not collide with the MOF _<sub> / _RESIDUAL forms"
    )


# ---------------------------------------------------------------------------
# D4 — obligor aggregates
# ---------------------------------------------------------------------------


def _resolved_rows(framework: str = "BASEL_3_1") -> list[dict]:
    """Resolve the FS-1 bundle through the whole hierarchy stage."""
    bundle = build_facility_share_bundle("binding")
    resolved = HierarchyResolver().resolve(bundle, facility_share_config(framework))
    return resolved.exposures.collect().to_dicts()


def test_each_candidate_counts_toward_its_own_members_obligor_total() -> None:
    """
    D4: a candidate row enters ITS OWN member's obligor total, upward only.

    Arrange: the FS-1 portfolio, whose share has 400,000 of headroom and three
             members with 400,000 / 200,000 / 100,000 of drawn exposure.
    Act:     resolve the hierarchy stage.
    Assert:  each member's ``lending_group_total_exposure`` is its own drawn
             exposure plus the full 400,000 headroom of its candidate row.

    "No special-casing" is the decision: every candidate counts toward its own
    member's aggregates exactly as any exposure of that member would. The
    direction is what makes it safe — the eventual WINNER's siblings are
    unchanged (the single undrawn row already counted for them) and a LOSING
    member's siblings gain the undrawn, so partition-local thresholds can only be
    crossed upward.

    Red today for FS-CP-LOW (200,000 rather than 600,000) and FS-CP-SA (300,000
    rather than 700,000); FS-CP-IRB is already 800,000 because it is today's
    preview winner, which is why the assertion covers all three rather than the
    one that happens to move most.
    """
    # Arrange / Act
    rows = _resolved_rows()
    totals = {row["counterparty_reference"]: row["lending_group_total_exposure"] for row in rows}

    # Assert — drawn plus the whole headroom, per member.
    expected = {
        CP_IRB: DRAWN_IRB + HEADROOM_SHARE,
        CP_LOW: DRAWN_LOW + HEADROOM_SHARE,
        # The owner also holds the solo facility's headroom and its own loan.
        CP_SA: DRAWN_SOLO + HEADROOM_SOLO + HEADROOM_SHARE,
        # The anchor is not a member and must not move at all.
        CP_ANCHOR: DRAWN_ANCHOR,
    }
    for member, want in expected.items():
        assert totals[member] == pytest.approx(want), (
            f"{member}'s obligor total is {totals[member]:,.2f}, expected "
            f"{want:,.2f} - a candidate must count toward its OWN member"
        )


def test_candidate_rows_do_not_move_the_retail_threshold_aggregate() -> None:
    """
    ``lending_group_adjusted_exposure`` is drawn-only, so candidates add nothing.

    Arrange: the FS-1 portfolio.
    Act:     resolve the hierarchy stage.
    Assert:  each member's retail-threshold aggregate is its DRAWN exposure only.

    CRR Art. 147 defines "total amount owed" as the drawn amount, and
    ``enrich.py`` implements that as ``total_exposure_amount = drawn_amount``, so
    an undrawn row contributes exactly 0.0 to ``exposure_for_retail_threshold``
    and therefore 0.0 to this aggregate. MEASURED on the pre-change engine, not
    inferred.

    That is worth an assertion of its own because the design of record predicted
    the opposite: it expected the fan-out to inflate this carrier and, through
    it, the Art. 123A(1)(b)(ii) granularity denominator. It cannot. Pinning the
    measurement here means a future change that starts counting undrawn amounts
    in the retail threshold reddens HERE, next to the reason, rather than
    surfacing as a moved COREP row.
    """
    # Arrange / Act
    rows = _resolved_rows()
    aggregates = {
        row["counterparty_reference"]: row["lending_group_adjusted_exposure"] for row in rows
    }

    # Assert
    expected = {
        CP_IRB: DRAWN_IRB,
        CP_LOW: DRAWN_LOW,
        CP_SA: DRAWN_SOLO,
        CP_ANCHOR: DRAWN_ANCHOR,
    }
    for member, want in expected.items():
        assert aggregates[member] == pytest.approx(want), (
            f"{member}'s retail-threshold aggregate is {aggregates[member]:,.2f}, "
            f"expected the drawn-only {want:,.2f} (CRR Art. 147)"
        )


def test_short_term_spill_over_windows_are_constant_within_an_obligor() -> None:
    """
    The obligor-keyed spill-over windows take one value per obligor, candidates included.

    Arrange: the FS-1 portfolio, resolved through the hierarchy stage.
    Act:     group the four Art. 120(3)(c) / Art. 140(2) spill-over carriers by
             obligor.
    Assert:  each obligor sees a single value across all its rows.

    Those four sites are ``max()`` / ``min()`` windows over
    ``counterparty_reference``. The fan-out adds rows to those partitions, and
    the claim the design makes is that it is VALUE-IDEMPOTENT because each
    candidate carries its own member's rating — the short-term rating lookup
    joins on ``(counterparty_reference, scope_id)``, so a facility-scoped rating
    held by the owner cannot spread to a member's candidate row.

    Scope, stated honestly rather than overstated: on THIS portfolio no obligor
    carries a short-term ECAI assessment, so the carriers are uniformly null or
    False and this test checks the partition SHAPE, not a live contamination
    path. A portfolio that fires those flags with a facility share in it does not
    exist in the estate, and building one is owed coverage rather than something
    this scenario can supply — the divergence chain it needs rules out the
    obligor types that carry short-term assessments.
    """
    # Arrange
    carriers = (
        "obligor_st_150_contamination",
        "obligor_st_50_floor",
        "has_own_short_term_ecai",
        "has_short_term_ecai",
    )

    # Act
    rows = _resolved_rows()

    # Assert
    for carrier in carriers:
        seen: dict[str, set] = {}
        for row in rows:
            seen.setdefault(row["counterparty_reference"], set()).add(row[carrier])
        for member, values in seen.items():
            assert len(values) == 1, (
                f"{carrier} takes {values} across {member}'s rows; an "
                "obligor-keyed window must resolve to one value per obligor, or "
                "a candidate row is contaminating its own member's partition"
            )


def test_candidate_rows_carry_their_own_members_inherited_rating() -> None:
    """
    Each candidate inherits ITS member's rating, not the owner's.

    Arrange: the FS-1 portfolio, whose owner is CQS 2, whose CQS-1 member is
             externally rated and whose F-IRB member carries an internal PD only.
    Act:     resolve the hierarchy stage and read the candidate rows.
    Assert:  each candidate's ``cqs`` / ``internal_pd`` are its own member's.

    This is the mechanism the whole design rests on: the rating join is on the
    row's ``counterparty_reference``, so a candidate carrying member M is priced
    with M's model permission, M's PD and M's external assessment. If it were
    not, every candidate would be a copy of the owner and the ranking would have
    nothing to rank.

    ``cqs`` is null on an internal-only obligor, measured — which is also why
    today's preview ranks the F-IRB member as an unrated 100% corporate.
    """
    # Arrange / Act
    rows = {
        row["exposure_reference"]: row
        for row in _resolved_rows()
        if row["exposure_type"] == "facility_undrawn"
    }
    candidates = {
        reference.split("@")[-1]: row for reference, row in rows.items() if "@" in reference
    }

    # Assert
    assert set(candidates) == {CP_SA, CP_LOW, CP_IRB}, sorted(candidates)
    assert candidates[CP_SA]["cqs"] == 2
    assert candidates[CP_LOW]["cqs"] == 1
    assert candidates[CP_IRB]["cqs"] is None
    assert candidates[CP_IRB]["internal_pd"] is not None
    assert candidates[CP_SA]["internal_pd"] is None


def test_solo_facility_row_is_untouched_by_the_fan_out() -> None:
    """
    The single-member control facility keeps its ordinary row through a full resolve.

    Arrange: the FS-1 portfolio, which holds a share AND a solo facility.
    Act:     resolve the hierarchy stage.
    Assert:  the solo facility emits exactly one un-suffixed row with a null
             group, carrying its own 200,000 of headroom.

    Green before and after. It is the leg that must SURVIVE while the share's
    rows move, which is what makes the pair distinguishable from a change that
    simply zeroed both.
    """
    # Arrange / Act
    rows = [
        row
        for row in _resolved_rows()
        if row.get("source_exposure_reference") == FAC_SOLO
        and row["exposure_type"] == "facility_undrawn"
    ]

    # Assert
    assert len(rows) == 1
    row = rows[0]
    assert row["exposure_reference"] == f"{FAC_SOLO}_UNDRAWN"
    assert row["counterparty_reference"] == CP_SA
    assert row["undrawn_amount"] == pytest.approx(HEADROOM_SOLO)
    _assert_carriers_present(row)
    assert row["facility_share_group"] is None
    assert row["is_facility_share_candidate"] is False
