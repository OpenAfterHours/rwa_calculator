"""
Membership contract for the RE loan-splitter's carrier classification.

Pipeline position:
    CRMProcessor -> RealEstateSplitter (engine/re_split/carriers.py)

Why this file exists — and why it is a MEMBERSHIP test rather than a
behavioural one:

``carriers.py`` classifies 62 ledger columns into allocated and inherited
sets. Mutation testing showed that 51 of the 57 ``_PRORATA_CARRIERS`` members
could be silently deleted from the tuple without reddening any end-to-end
test in the estate: no golden portfolio combines a real-estate split with
life-insurance collateral, an FCSM pledge, a third-party deposit or a
guarantee, so most members have no live cell to assert against. Two of them
are worse than untested — ``undrawn_amount`` and ``nominal_amount`` appear to
be structurally unreachable on a split leg, because an undrawn commitment
materialises as its own non-splitting row.

An end-to-end assertion therefore cannot gate this classification. This file
gates it directly: it pins membership against the sealed edge contract (a
source of truth that cannot drift with the code under test — LESSONS B3) and
pins the specific members whose omission is known to move capital or to
corrupt a regulatory return.

References:
- CRR Art. 124(1), first subparagraph, second sentence: the part of the
  exposure exceeding the mortgage value takes the counterparty's unsecured
  risk weight — the residual leg carries no property value.
- PS1/26 Art. 124F(1)(b), Art. 124L: the same rule under the revised regime.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import RE_SPLIT_EXIT_CCR_EDGE, RE_SPLIT_EXIT_EDGE
from rwa_calc.engine.re_split.carriers import (
    _COMMERCIAL_ONLY_CARRIERS,
    _PRORATA_CARRIERS,
    _RE_COLLATERAL_CARRIERS,
    _RESIDENTIAL_ONLY_CARRIERS,
)

_ALL_SETS: dict[str, tuple[str, ...]] = {
    "_PRORATA_CARRIERS": _PRORATA_CARRIERS,
    "_RE_COLLATERAL_CARRIERS": _RE_COLLATERAL_CARRIERS,
    "_RESIDENTIAL_ONLY_CARRIERS": _RESIDENTIAL_ONLY_CARRIERS,
    "_COMMERCIAL_ONLY_CARRIERS": _COMMERCIAL_ONLY_CARRIERS,
}


def _contract_floats() -> dict[str, pl.DataType]:
    """Float64 columns on either splitter exit contract, keyed by name."""
    merged = {**RE_SPLIT_EXIT_EDGE.columns, **RE_SPLIT_EXIT_CCR_EDGE.columns}
    return {
        name: spec.dtype
        for name, spec in merged.items()
        if getattr(spec, "dtype", None) is not None
    }


# ---------------------------------------------------------------------------
# Structural: the sets are well-formed against the sealed contract.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", sorted(_ALL_SETS))
def test_every_allocated_carrier_exists_on_the_exit_contract(set_name: str) -> None:
    """A carrier absent from the contract is presence-guarded into a no-op.

    Such a member is dead configuration: it can never match ``schema_names``,
    so it silently allocates nothing. Catching it here is the only way it
    surfaces, since a no-op produces no failure downstream.
    """
    contract = _contract_floats()
    unknown = [c for c in _ALL_SETS[set_name] if c not in contract]
    assert unknown == []


@pytest.mark.parametrize("set_name", sorted(_ALL_SETS))
def test_every_allocated_carrier_is_float(set_name: str) -> None:
    """Allocation multiplies by a fractional share, so the column must be Float64.

    Scaling an integer or boolean column would either truncate or raise.
    """
    contract = _contract_floats()
    non_float = [c for c in _ALL_SETS[set_name] if c in contract and contract[c] != pl.Float64]
    assert non_float == []


def test_the_four_sets_are_pairwise_disjoint() -> None:
    """A column in two sets would emit two expressions aliasing one name.

    Two expressions with the same output name inside a single
    ``with_columns`` is a Polars error, so an overlap is a hard failure at
    run time rather than a wrong number.
    """
    seen: dict[str, str] = {}
    collisions: list[str] = []
    for set_name, members in _ALL_SETS.items():
        for column in members:
            if column in seen:
                collisions.append(f"{column} in {seen[column]} and {set_name}")
            seen[column] = set_name
    assert collisions == []


@pytest.mark.parametrize("set_name", sorted(_ALL_SETS))
def test_no_duplicate_members_within_a_set(set_name: str) -> None:
    """A repeated member emits the same alias twice — same Polars error."""
    members = _ALL_SETS[set_name]
    assert len(members) == len(set(members))


# ---------------------------------------------------------------------------
# Intensive columns must NEVER be allocated. Scaling a rate is a capital bug.
# ---------------------------------------------------------------------------

#: Rates, ratios and per-unit attributes. Each is meaningless when summed and
#: WRONG when scaled: a leg carrying 55% of a 45% LGD would understate loss
#: given default, and a scaled supporting factor would understate RWA.
_MUST_STAY_INHERITED_INTENSIVE: tuple[str, ...] = (
    "lgd",
    "lgd_pre_crm",
    "lgd_post_crm",
    "lgd_secured",
    "lgd_unsecured",
    "pd",
    "internal_pd",
    "ccf",
    "effective_ccf",
    "supporting_factor",
    "collateral_coverage_pct",
    "original_maturity_years",
    "effective_maturity",
    "securitisation_residual_pct",
    "risk_weight",
    "pre_crm_risk_weight",
    "guarantor_rw",
    "fcsm_collateral_rw",
    "life_ins_secured_rw",
    "third_party_deposit_secured_rw",
    "exposure_volatility_haircut",
    "fx_rate_applied",
    "prior_charge_ltv",
    "ltv",
)

#: Counterparty attributes and genuine lending-group aggregates. These are
#: per-row THRESHOLD comparands (Art. 501 E*, the Art. 123 retail limit);
#: scaling one by the leg share corrupts the comparison it feeds.
_MUST_STAY_INHERITED_COMPARANDS: tuple[str, ...] = (
    "cp_annual_revenue",
    "cp_total_assets",
    "sme_size_metric_gbp",
    "e_star_group_drawn",
    "lending_group_total_exposure",
    "lending_group_adjusted_exposure",
    "total_cp_drawn",
)


@pytest.mark.parametrize("column", _MUST_STAY_INHERITED_INTENSIVE)
def test_intensive_column_is_never_allocated(column: str) -> None:
    """Scaling a rate or ratio by the leg's EAD share is a capital defect."""
    allocated = {c for members in _ALL_SETS.values() for c in members}
    assert column not in allocated


@pytest.mark.parametrize("column", _MUST_STAY_INHERITED_COMPARANDS)
def test_threshold_comparand_is_never_allocated(column: str) -> None:
    """Scaling a threshold comparand corrupts the test that reads it."""
    allocated = {c for members in _ALL_SETS.values() for c in members}
    assert column not in allocated


# ---------------------------------------------------------------------------
# Named members whose omission is KNOWN to move capital or corrupt a return.
# Each entry records the consumer, so a future editor removing one sees why.
# ---------------------------------------------------------------------------

#: Substitution collateral values. Each is the numerator of
#: ``secured_pct = clip(V / ead_final, 0, 1)`` in engine/sa/rw_adjustments.py
#: (lines 103, 145, 182) where ``ead_final`` is the LEG EAD. Left unallocated,
#: the ratio inflates by 1/share and clips to 1.0 — the leg is treated as
#: FULLY secured and takes the collateral risk weight outright, which
#: UNDER-capitalises it. Measured on the life-insurance limb: a corporate
#: residual leg reported 20% instead of 60%, total RWA 200,000 against a
#: correct 380,000 under Basel 3.1.
_CAPITAL_CRITICAL_SUBSTITUTION: tuple[str, ...] = (
    "fcsm_collateral_value",
    "life_ins_collateral_value",
    "third_party_deposit_value",
)

#: The Art. 123B(2A) hedge-coverage rescale is
#: ``raw_coverage * drawn_amount / max(drawn_amount, facility_limit)``
#: (engine/sa/rw_adjustments.py:530-545). Both members must be allocated or
#: the ratio shifts by the leg share, stopping the 90% waiver firing and
#: applying the 1.5x currency-mismatch multiplier to legs it should not touch.
_CAPITAL_CRITICAL_HEDGE_RATIO: tuple[str, ...] = ("drawn_amount", "facility_limit")

#: The SA guarantee substitution blend is
#: ``(unguaranteed * borrower_rw + guaranteed * guarantor_rw) / ead_final``
#: (engine/sa/rw_adjustments.py:412-415). ``ead_final`` is the leg EAD, so
#: both portions must carry the same share for the blend to equal the parent's.
_CAPITAL_CRITICAL_GUARANTEE: tuple[str, ...] = ("guaranteed_portion", "unguaranteed_portion")

#: Art. 501 E* is a windowed group sum of ``drawn_amount + interest`` computed
#: AFTER the split (engine/supporting_factors.py, dispatched from
#: engine/stages/calc.py). Unallocated, a split exposure contributes once per
#: leg, overstating the amount owed by the client group and denying the SME
#: supporting factor above the EUR 2.5m threshold.
_CAPITAL_CRITICAL_E_STAR: tuple[str, ...] = ("drawn_amount", "interest")

#: The gross-exposure carriers COREP C 07.00 col 0010 and Pillar 3 CR4 cols
#: a/b are derived from, via ``reporting_gross_on_bs`` / ``_off_bs`` in
#: engine/aggregator/aggregator.py. Unallocated, a firm files twice its book.
_RETURN_CRITICAL_GROSS: tuple[str, ...] = (
    "drawn_amount",
    "interest",
    "nominal_amount",
    "undrawn_amount",
)

#: Provisions reported at COREP C 07.00 col 0030, whose real-submission
#: carrier is ``provision_deducted`` (reporting/corep/c07.py:840-849).
_RETURN_CRITICAL_PROVISIONS: tuple[str, ...] = ("provision_deducted",)

#: Summed into the own-funds EL shortfall/excess by
#: engine/aggregator/_el_summary.py:117-120 and :221-246.
_RETURN_CRITICAL_OWN_FUNDS: tuple[str, ...] = ("ava_amount", "other_own_funds_reductions")

#: Bound by a literal ``Sum(...)`` cell spec at COREP C 07.00 / C 08.01
#: col 0035 (reporting/corep/c07.py:1530, c08.py:763).
_RETURN_CRITICAL_NETTING: tuple[str, ...] = ("on_bs_netting_amount",)

#: The EAD waterfall. Pinned for UNIFORMITY, not because a consumer is known to
#: break: ``ead_gross`` feeds the Art. 127(1) coverage test, which split legs
#: cannot reach (``flagging.py`` excludes defaulted rows from split candidacy),
#: and ``ead_for_crm`` feeds the LGD* convexity invariant, which is IRB-only
#: while split legs are SA-bound. So the case for omitting them was "no
#: consequence to pin".
#:
#: That argument is from TODAY'S consumer set, and this entire change exists
#: because a consumer set was read too narrowly — the substitution family above
#: was believed inconsequential until it was measured at +90% RWA. An
#: allocated carrier is pinned here on the strength of being allocated, not on
#: the strength of a consumer we can currently name.
_WATERFALL_FOR_UNIFORMITY: tuple[str, ...] = (
    "ead_from_ccf",
    "ead_modelled",
    "ead_gross",
    "ead_pre_crm",
    "ead_for_crm",
    "ead_after_collateral",
    "ead_after_guarantee",
)

_MUST_BE_PRORATA: dict[str, tuple[str, ...]] = {
    "EAD waterfall (uniformity)": _WATERFALL_FOR_UNIFORMITY,
    "substitution secured_pct (capital)": _CAPITAL_CRITICAL_SUBSTITUTION,
    "Art. 123B hedge ratio (capital)": _CAPITAL_CRITICAL_HEDGE_RATIO,
    "guarantee blend (capital)": _CAPITAL_CRITICAL_GUARANTEE,
    "Art. 501 E* (capital)": _CAPITAL_CRITICAL_E_STAR,
    "gross exposure returns": _RETURN_CRITICAL_GROSS,
    "C 07.00 provisions": _RETURN_CRITICAL_PROVISIONS,
    "own-funds deductions": _RETURN_CRITICAL_OWN_FUNDS,
    "on-balance netting": _RETURN_CRITICAL_NETTING,
}


@pytest.mark.parametrize(("reason", "columns"), sorted(_MUST_BE_PRORATA.items()))
def test_capital_and_return_critical_carriers_are_prorata(
    reason: str, columns: tuple[str, ...]
) -> None:
    """Named members whose omission moves capital or corrupts a return."""
    missing = [c for c in columns if c not in _PRORATA_CARRIERS]
    assert missing == [], f"{reason}: {missing} must be pro-rata allocated"


# ---------------------------------------------------------------------------
# The real-estate families are structurally symmetric.
# ---------------------------------------------------------------------------


def test_residential_and_commercial_uncapped_carriers_are_symmetric() -> None:
    """``flagging.py:150-151`` reads the two ``*_uncapped`` columns as a pair.

    The commercial half was omitted once precisely because the two are
    handled in mirrored branches; an asymmetry between them is a defect on
    its face, so pin that both are classified.
    """
    assert "residential_collateral_value_uncapped" in _RESIDENTIAL_ONLY_CARRIERS
    assert "commercial_collateral_value_uncapped" in _COMMERCIAL_ONLY_CARRIERS


def test_combined_re_carriers_are_not_in_a_single_component_set() -> None:
    """``collateral_re_*`` span both components, so they split by value share.

    Putting either in a single-component set would null it on the other
    secured leg and lose the pledge.
    """
    single_component = set(_RESIDENTIAL_ONLY_CARRIERS) | set(_COMMERCIAL_ONLY_CARRIERS)
    assert set(_RE_COLLATERAL_CARRIERS).isdisjoint(single_component)


def test_property_collateral_value_is_not_generated() -> None:
    """``_secured_columns`` / ``_residual_columns`` override it by hand.

    A generated expression for it would collide with the hand-written
    override and raise a duplicate-alias error.
    """
    allocated = {c for members in _ALL_SETS.values() for c in members}
    assert "property_collateral_value" not in allocated
    assert "ead_final" not in allocated
    assert "provision_allocated" not in allocated
