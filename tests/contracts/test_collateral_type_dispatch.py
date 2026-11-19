"""
Every collateral type the INPUT CONTRACT accepts must reach a CRM dispatch branch.

Pipeline position:
    RawDataBundle (validate_bundle_values gates collateral_type against
        VALID_COLLATERAL_TYPES) -> CRMProcessor (engine/crm/expressions.py
        dispatches on the category lists) -> collateral value carriers

What this proves:
Two sets decide the fate of a pledge, in two layers that do not check each other.
``data/schemas.py::VALID_COLLATERAL_TYPES`` is the canonical INPUT set — a
``collateral_type`` outside it is rejected as a data-quality error.
``RECOGNISED_COLLATERAL_TYPES``, derived from the category lists
``engine/crm/expressions.py`` actually branches on, is what the ENGINE dispatches.

A type in the first set but not the second lands in a split state: it is excluded
from the per-CATEGORY carriers that the CRM disclosure columns are built from,
while still receiving an Art. 223 adjusted value and full EAD relief. The
exposure is mitigated; the disclosure says it is not.

Measured instance (2026-08-09), which is why this file exists. ``"bond"`` is a
member of ``VALID_COLLATERAL_TYPES`` and of no category list. On a 1,000,000
corporate exposure with a 500,000 pledge, CRR:

    collateral_type    errors     financial      adjusted   RWA relief
    cash               -              0.00     500,000.00    -500,000.00
    government_bond    -        485,857.86     485,857.86    -485,857.86
    bond               CRM021         0.00     485,857.86    -485,857.86
    banana             CRM021         0.00     217,157.29    -217,157.29

Three things that table settles, each of which contradicts the obvious guess:

- ``bond`` is NOT silently worth zero. It receives the SAME RWA relief as
  ``government_bond`` and raises ``CRM021``, so the drop is neither total nor
  silent. Only the per-category carrier is empty.
- The mismatch is therefore a REPORTING one: the ``collateral_*_value`` family
  and the C 08.01/02 and CR7-A columns fed from it omit a pledge that the EAD
  path already recognised, so two published surfaces disagree about one pledge.
- ``banana`` — an arbitrary string in NO set — still earns 217,157.29 of relief
  behind a single ``CRM021`` warning. That direction is ANTI-CONSERVATIVE and is
  the more serious half; it is filed as its own Tier 1 item, because it is about
  what an UNRECOGNISED type is granted rather than about which list it is on.

The conservative reading of the first bullet matters for the sibling
conservation identities: an inequality of the form ``collateral <= pledged`` is
satisfied by an UNDER-reported mitigant, so it cannot see this defect at all.
That is why the contract below is stated over the SETS and not over amounts.

Note the schemas comment above the category lists asserts they are "broader than
VALID_COLLATERAL_TYPES because the engine accepts synonyms". That is the
invariant this file makes executable — and it is FALSE in both directions:
``bond`` is accepted and undispatched, while ``government_bond`` is dispatched
and is not in ``VALID_COLLATERAL_TYPES`` at all (yet raises no validation error,
so that set is not enforced on this path the way its docstring implies).

Note the schemas comment above the category lists asserts they are "broader than
VALID_COLLATERAL_TYPES because the engine accepts synonyms". That is the
invariant this file makes executable — and it was FALSE for ``bond`` when
written. A documented invariant nobody checks is how the gap survived.

References:
- CRR Art. 197: eligible financial collateral (issuer and rating conditions)
- CRR Art. 199: eligible non-financial collateral under IRB
- CRR Art. 161 / 230, CRE22.40-78: the CRM category mapping
- `.claude/LESSONS.md` B2: an unmatched dict/list key zero-fills silently
"""

from __future__ import annotations

from rwa_calc.data.schemas import (
    BOND_COLLATERAL_TYPES,
    COVERED_BOND_COLLATERAL_TYPES,
    FINANCIAL_COLLATERAL_TYPES,
    LIFE_INSURANCE_COLLATERAL_TYPES,
    OTHER_PHYSICAL_COLLATERAL_TYPES,
    REAL_ESTATE_COLLATERAL_TYPES,
    RECEIVABLE_COLLATERAL_TYPES,
    RECOGNISED_COLLATERAL_TYPES,
    VALID_COLLATERAL_TYPES,
)

#: Accepted by validation, dispatched by nothing — deliberately tolerated, one
#: entry per outstanding decision. This is an ALLOWLIST, not a baseline: it exists
#: so a NEW gap fails immediately while a known one is tracked rather than
#: invisible.
#:
#: The set is only ever SUBTRACTED from a difference computed live from the two
#: schemas constants, never used as the list of things to check. So a member can
#: only shrink this gate for a type someone deliberately recorded — it can never
#: hide a NEW undispatched type, which would still appear in the difference and
#: fail. An allowlist whose members are merely enumerated has the opposite
#: property; this one is safe in the direction that matters.
#:
#: EMPTY since review CL-11. Its one entry was ``bond``, accepted by validation and
#: absent from every category list, so a sovereign ``bond`` pledge was "other" on
#: the F-IRB path (CRM014-gated, or the other-physical LGDS) and raised CRM021 on
#: every path, while ``government_bond`` took the 0% financial LGDS. ``bond`` is
#: now dispatched by its ISSUER (``BOND_COLLATERAL_TYPES`` /
#: ``engine/crm/expressions.py::issued_bond_expr``): financial where the issuer
#: resolves it to an Art. 197 debt security, other physical otherwise — the class
#: the Art. 224 haircut lookup already gave it. The stale-entry ratchet below
#: forced the entry out, which is what it is for.
KNOWN_UNDISPATCHED_TYPES: frozenset[str] = frozenset()

#: The category lists ``engine/crm/expressions.py`` branches on, in the order
#: its ``pl.when(...).when(...)`` ladders test them. Named explicitly rather than
#: discovered by module introspection so that ADDING a seventh category without
#: wiring it in here is visible in review.
DISPATCHED_CATEGORY_LISTS: tuple[tuple[str, list[str]], ...] = (
    ("life_insurance", LIFE_INSURANCE_COLLATERAL_TYPES),
    ("covered_bond", COVERED_BOND_COLLATERAL_TYPES),
    ("financial", FINANCIAL_COLLATERAL_TYPES),
    # Issuer-dispatched: financial or other physical by ``issuer_type`` (CL-11).
    ("bond (by issuer)", BOND_COLLATERAL_TYPES),
    ("receivables", RECEIVABLE_COLLATERAL_TYPES),
    ("real_estate", REAL_ESTATE_COLLATERAL_TYPES),
    ("other_physical", OTHER_PHYSICAL_COLLATERAL_TYPES),
)


def test_every_accepted_collateral_type_reaches_a_dispatch_branch() -> None:
    """A type validation accepts must be dispatched, or be a tracked exception.

    The failure mode this prevents is not a crash but a silent zero: an accepted
    type that matches no branch contributes no collateral value, and every
    conservative downstream check passes because less mitigation only raises RWA.
    """
    # Arrange
    dispatched = {value for _name, values in DISPATCHED_CATEGORY_LISTS for value in values}

    # Act
    undispatched = (VALID_COLLATERAL_TYPES - dispatched) - KNOWN_UNDISPATCHED_TYPES

    # Assert
    assert undispatched == set(), (
        f"{sorted(undispatched)} are accepted by validate_bundle_values "
        f"(data/schemas.py::VALID_COLLATERAL_TYPES) but match no CRM category list, so a "
        f"pledge of that type is silently worth zero — neither rejected nor recognised. "
        f"Either dispatch it (add to the right *_COLLATERAL_TYPES list, checking Art. 197 "
        f"/ 199 eligibility first) or reject it at validation. If it must be tolerated for "
        f"now, add it to KNOWN_UNDISPATCHED_TYPES with the reason and a plan-item reference."
    )


def test_the_undispatched_allowlist_has_not_gone_stale() -> None:
    """Every tolerated exception is still accepted AND still undispatched.

    A two-way ratchet, in the house style of the dead-link baseline: once a
    tolerated type is either dispatched or rejected, its allowlist entry becomes
    a lie and this fails, forcing the entry out. Without this, the allowlist
    would quietly outlive the problem and start concealing the next one.

    Note the limit of that guarantee, spelled out at
    :data:`KNOWN_UNDISPATCHED_TYPES`: it catches the DISPATCHED and the REJECTED
    resolutions, not the data-quality-error resolution, which leaves both
    conditions true. This ratchet is necessary and not sufficient.
    """
    # Arrange
    dispatched = {value for _name, values in DISPATCHED_CATEGORY_LISTS for value in values}

    # Act
    resolved = {
        entry
        for entry in KNOWN_UNDISPATCHED_TYPES
        if entry not in VALID_COLLATERAL_TYPES or entry in dispatched
    }

    # Assert
    assert resolved == set(), (
        f"{sorted(resolved)} no longer describe a gap — each is now either dispatched or no "
        f"longer accepted by validation. Delete the entry from KNOWN_UNDISPATCHED_TYPES: a "
        f"stale allowlist entry silences the check for a type that is fine, and would hide a "
        f"regression that reintroduced the gap."
    )


def test_the_recognised_set_is_exactly_the_dispatched_categories() -> None:
    """``RECOGNISED_COLLATERAL_TYPES`` must equal the union of the branch lists.

    It is consumed as "everything the CRM engine understands", including by
    ``engine/crm/expressions.py`` itself. Pinning it to the same lists the
    dispatch ladders test keeps it from drifting into a third, subtly different
    opinion — and makes this file's other two assertions sound, since both are
    stated over that union.
    """
    # Arrange
    dispatched = {value for _name, values in DISPATCHED_CATEGORY_LISTS for value in values}

    # Act / Assert
    assert set(RECOGNISED_COLLATERAL_TYPES) == dispatched, (
        f"RECOGNISED_COLLATERAL_TYPES disagrees with the dispatched category lists. "
        f"Only in RECOGNISED: {sorted(set(RECOGNISED_COLLATERAL_TYPES) - dispatched)}; "
        f"only in the category lists: {sorted(dispatched - set(RECOGNISED_COLLATERAL_TYPES))}."
    )


def test_the_contract_is_not_vacuous() -> None:
    """Both sets are populated and hold their structural members.

    Without this, a rename that emptied either side would make the difference
    empty and the first assertion would pass forever while checking nothing —
    `.claude/LESSONS.md` B1, whose measured instance published nothing into a
    COREP column for the template's entire life.
    """
    # Arrange / Act / Assert
    assert VALID_COLLATERAL_TYPES, "the input-contract collateral set is empty"
    assert all(values for _name, values in DISPATCHED_CATEGORY_LISTS), (
        "a CRM category list is empty, so its dispatch branch can never match"
    )
    # Anchors: cash is the canonical financial pledge and real_estate the
    # canonical non-financial one. Both must be accepted AND dispatched.
    for anchor in ("cash", "real_estate"):
        assert anchor in VALID_COLLATERAL_TYPES
        assert anchor in set(RECOGNISED_COLLATERAL_TYPES)
