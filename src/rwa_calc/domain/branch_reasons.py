"""
Branch-reason vocabularies — why a row took the branch it took.

Pipeline position:
    Declared here, bound into ``pl.Enum`` dtypes by
    ``engine/branch_reason.py``, emitted beside the value by the instrumented
    stage (``engine/sa/risk_weights.py``, ``engine/irb/transforms.py``,
    ``engine/sa/guarantor_rw.py``), carried to the aggregator exit on
    ``contracts/edges.py``, and read back by
    ``contracts/validation.py::validate_branch_reasons`` and
    ``scripts/check_branch_census.py``.

Key responsibilities:
- Name every branch of an instrumented decision, so a run-level histogram can
  say which limbs the estate actually reaches.
- Give "I do not know" its own name (``UNKNOWN_FALLBACK``) in every vocabulary,
  distinct from every "the rule does not apply here" name.

Why the vocabulary is an enum rather than free strings
------------------------------------------------------
``docs/plans/test-space-correctness-proposal.md`` Phase 3 wants a census in
which **a branch reached by zero rows is a finding**. A ``String`` column
cannot express that: it carries the values that occurred and is silent about
the ones that did not, so a limb that never fires is indistinguishable from a
limb that does not exist. A ``pl.Enum`` carries its full category list in the
*dtype*, so the declared population comes off the schema and the reached
population off the data — and the set difference is the finding.

That also anchors the census to a source of truth that cannot drift with the
code under test (`.claude/LESSONS.md` B3): the categories are read from the
frame's own dtype, never from a hand-written list in the census script.

The one name every vocabulary must carry
----------------------------------------
``UNKNOWN_FALLBACK`` is the whole point of Phase 3. ``otherwise`` in this
engine does double duty — "the rule does not apply" and "I do not know" — and
separating them is what turns a silent fallback into a finding. Each
vocabulary below therefore declares:

- one name per limb the regulation actually defines ("the rule does not
  apply, and here is which limb priced the row"), and
- ``UNKNOWN_FALLBACK`` for the rows where the deciding predicate could not be
  evaluated, or where a value was substituted for data that was simply absent.

A row on ``UNKNOWN_FALLBACK`` must be accompanied by a ``CalculationError``
(``BR001``) — that invariant is enforced at the pipeline exit by
``validate_branch_reasons``, not merely asserted in a test.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 3
- .claude/LESSONS.md B3 (anchor to a source of truth that cannot drift), B8
  (ratchet the accumulator)
"""

from __future__ import annotations

from enum import StrEnum

import polars as pl

#: The name every vocabulary reserves for "I do not know". Kept as a module
#: constant as well as an enum member so ``engine/branch_reason.py`` can append
#: it to a vocabulary generically, and so the validator and the census script
#: test for it without importing four enums.
UNKNOWN_FALLBACK = "UNKNOWN_FALLBACK"

#: The instrumented columns. Named here rather than at each producer so the
#: edge contract, the exit validator and the census script cannot disagree
#: about what a branch-reason column is called.
SA_RISK_WEIGHT_BRANCH_REASON = "sa_risk_weight_branch_reason"
IRB_LGD_BRANCH_REASON = "irb_lgd_branch_reason"


class SovereignFloorReason(StrEnum):
    """Why the Art. 121(6) sovereign floor did or did not move an institution RW.

    The floor is the PS1/26 Art. 121(6) / CRE20.22 rule that an unrated
    institution exposure NOT denominated in the institution's domestic currency
    cannot be risk-weighted below its jurisdiction's sovereign risk weight.

    ``UNKNOWN_FALLBACK`` here means the FX test itself was indeterminate — the
    exposure carries no ``cp_local_currency`` and the counterparty's country is
    outside the UK/EU domestic-currency map, so ``is_domestic_currency``
    evaluates to null and the floor's ``pl.when`` silently takes ``otherwise``.
    That is a live anti-conservative defect (IMPLEMENTATION_PLAN.md P1.333),
    and naming it here is what makes it visible on every run rather than only
    to someone who instruments the expression by hand.
    """

    NOT_INSTITUTION = "not_institution"
    """Exposure is not to an institution — Art. 121(6) is out of scope."""

    RATED = "rated"
    """The institution carries its own ECAI assessment; the floor addresses unrated ones."""

    TRADE_EXEMPT = "trade_exempt"
    """Art. 121(6)(b) / CRE20.22 fn13: self-liquidating trade item, original maturity <= 1y."""

    DOMESTIC_CURRENCY = "domestic_currency"
    """Exposure IS in the institution's domestic currency — the floor's trigger is absent."""

    FLOOR_BOUND = "floor_bound"
    """The floor applied and RAISED the risk weight to the sovereign's."""

    FLOOR_NOT_BINDING = "floor_not_binding"
    """The floor applied and did not move the row — the base RW already exceeded it."""

    UNKNOWN_FALLBACK = UNKNOWN_FALLBACK
    """Domesticity could not be determined, so the floor was silently skipped (P1.333)."""


class IrbLgdReason(StrEnum):
    """Which source supplied the LGD an IRB row was risk-weighted on.

    ``UNKNOWN_FALLBACK`` here is not a null predicate but a null *value*: a row
    with no own-estimate LGD, no modelled LGD and no purchased-receivables
    subtype reaches ``fill_null(default_lgd)`` and is priced on the senior
    unsecured supervisory rate — a defensible-looking number standing in for
    data that was simply absent. CRR Art. 143 requires an A-IRB institution to
    supply its own estimate; silently substituting the F-IRB supervisory value
    is the "plausible number instead of an error" failure Phase 2 measured.
    """

    SUPERVISORY_SUBTYPE = "supervisory_subtype"
    """Art. 161(1)(e)/(f)/(g): purchased-receivables subtype LGD, which overrides seniority."""

    SUPERVISORY_FIRB = "supervisory_firb"
    """Art. 161(1)(a): F-IRB supervisory LGD selected on seniority (and FSE status under B3.1)."""

    OWN_ESTIMATE = "own_estimate"
    """Art. 143: the institution's own A-IRB LGD estimate, as supplied."""

    CCR_MODELLED = "ccr_modelled"
    """The A-IRB own estimate arrived on the CCR/SFT carrier (``ccr_modelled_lgd``)."""

    UNKNOWN_FALLBACK = UNKNOWN_FALLBACK
    """No LGD from any source; the supervisory default was substituted for absent data."""


#: Every instrumented column, mapped to the vocabulary that types it. THE
#: registry — the edge contract builds its dtypes from this, the exit validator
#: iterates it to find the columns to scan, and the census enumerates it to
#: decide what to count. Adding a fifth instrumented path means adding one
#: entry here and nothing else; forgetting to is caught by
#: ``tests/contracts/test_branch_reason_contract.py``, which asserts the
#: registry and the sealed aggregator-exit edge agree.
BRANCH_REASON_VOCABULARIES: dict[str, type[StrEnum]] = {
    SA_RISK_WEIGHT_BRANCH_REASON: SovereignFloorReason,
    IRB_LGD_BRANCH_REASON: IrbLgdReason,
}


def declared_reasons(vocabulary: type[StrEnum]) -> list[str]:
    """The reason strings a vocabulary declares, in declaration order.

    The single derivation of "what this vocabulary declares". Both callers
    need it — ``reason_dtype`` to build the category list, ``decide`` to reject
    a reason that is not a member — and two copies of the same comprehension is
    the drift this module's own docstring argues against.

    Read off ``__members__`` rather than by iterating the class. The two are
    equivalent for values (an alias contributes the value it aliases, which
    ``dict.fromkeys`` collapses back to one category), but a bare
    ``for member in vocabulary`` reads to a static analyser as iteration over a
    class object — SonarCloud ``python:S5864`` flags exactly that, and the
    ``EnumType.__iter__`` that makes it work is invisible to it.
    """
    return list(dict.fromkeys(member.value for member in vocabulary.__members__.values()))


def reason_dtype(vocabulary: type[StrEnum]) -> pl.Enum:
    """The ``pl.Enum`` dtype for a vocabulary, in declaration order.

    Lives beside the vocabularies rather than in the engine because the edge
    contract needs it too, and ``contracts/`` may not import ``engine/``
    (arch_check check 13). One home means the producer, the edge and the
    census cannot disagree about the category list — which matters more here
    than usual, since the census reads its *declared* population straight off
    this dtype.
    """
    return pl.Enum(declared_reasons(vocabulary))
