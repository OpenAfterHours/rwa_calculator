"""
Emit the reason beside the value — one primitive, shared by every instrumented branch.

Pipeline position:
    (not a pipeline stage) — an expression builder called by the instrumented
    decision points: ``engine/sa/risk_weights.py`` (Art. 121(6) sovereign
    floor), ``engine/irb/transforms.py`` (IRB LGD source) and
    ``engine/sa/guarantor_rw.py`` (Art. 235 substitution chain).

Key responsibilities:
- Build a ``pl.when``/``then`` value chain and its reason chain **from the same
  predicate objects**, so the two cannot drift.
- Detect the Polars behaviour this whole phase exists for: a predicate that
  evaluates to NULL does not take its branch — it silently falls through to
  ``otherwise``. That row is labelled ``UNKNOWN_FALLBACK``.

The mechanism, stated precisely
-------------------------------
``pl.when(p).then(a).otherwise(b)`` yields ``b`` when ``p`` is False **and when
``p`` is null**. Polars offers no way to distinguish the two after the fact:
the output carries ``b`` either way. So ``otherwise`` is doing double duty —
"the rule does not apply" and "I could not tell" — and every rule in this
engine whose predicate touches a nullable column has a silent third state.

:func:`decide` splits them. For cases ``(p1, v1, r1), (p2, v2, r2), ...``:

- the **value** chain is exactly ``when(p1).then(v1).when(p2).then(v2)…
  .otherwise(v0)`` — the expression the engine had before instrumentation;
- the **reason** chain interleaves a nullity test before each predicate::

      when(p1.is_null()).then(UNKNOWN_FALLBACK)
      .when(p1).then(r1)
      .when(p2.is_null()).then(UNKNOWN_FALLBACK)
      .when(p2).then(r2)
      …
      .otherwise(r0)

  so the first predicate that is *indeterminate* rather than False names the
  row, whatever a later predicate happens to say. That is the honest reading:
  once ``p1`` is unknown, the branch this row belongs in is unknown too, even
  if ``p2`` matched.

Why the caller must keep the value chain equivalent
---------------------------------------------------
This function is an instrument, not a fix. Restructuring a live chain into
cases can silently change capital: a predicate that was null inside a single
composite ``_floor_applies`` term may become a *matching* case once the term is
split. The obligation on every call site is that the new value chain is
**provably identical** to the one it replaced — the usual way to discharge it
is to give every non-firing case the untouched incumbent value, so only the one
case that genuinely computes something new can move a number. Each call site
records that argument in its own comment, and
``tests/unit/engine/test_branch_reason.py`` pins the equivalence directly.

Fixing the defects the census exposes is separate work with its own review and
its own output-floor evidence (`.claude/LESSONS.md` D1).

Why the reason column is a ``pl.Enum``
--------------------------------------
A branch reached by zero rows is a finding, and a ``String`` column cannot
report one — it carries what occurred and is silent about what did not. An
``Enum`` carries its categories in the dtype, so the census reads the
*declared* population off the schema and the *reached* population off the
data. It also costs ~1 byte per row against ~12 for the equivalent String.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 3
- rwa_calc.domain.branch_reasons — the vocabularies
- .claude/LESSONS.md B3 (anchor to a source that cannot drift with the code),
  D1 (an RWA-moving change needs its own review)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.branch_reasons import UNKNOWN_FALLBACK, reason_dtype

if TYPE_CHECKING:
    from collections.abc import Sequence
    from enum import StrEnum

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BranchCase:
    """One limb of an instrumented decision: its predicate, its value, its name.

    Attributes:
        reason: The vocabulary member naming this limb. Must belong to the
            vocabulary passed to :func:`decide`.
        predicate: The Boolean expression selecting this limb. A null here is
            what :func:`decide` reports as ``UNKNOWN_FALLBACK``.
        value: The expression this limb yields.
    """

    reason: StrEnum
    predicate: pl.Expr
    value: pl.Expr


def decide(
    cases: Sequence[BranchCase],
    *,
    otherwise: pl.Expr,
    otherwise_reason: StrEnum,
    vocabulary: type[StrEnum],
) -> tuple[pl.Expr, pl.Expr]:
    """Build a value chain and the reason chain that explains it.

    Args:
        cases: The limbs, in the order the regulation resolves them. First
            match wins, exactly as in a hand-written ``pl.when`` chain.
        otherwise: The value for a row no case matched.
        otherwise_reason: The name for a row no case matched. Pass the
            vocabulary's ``UNKNOWN_FALLBACK`` when falling through genuinely
            means "no source supplied this value"; pass a named limb when it
            means "the rule does not apply".
        vocabulary: The ``StrEnum`` whose members name this decision's limbs.
            Becomes the reason column's ``Enum`` categories, so it must contain
            every reason used — including ``otherwise_reason``.

    Returns:
        ``(value_expr, reason_expr)``. The reason expression is typed
        ``reason_dtype(vocabulary)``.

    Raises:
        ValueError: A reason is not a member of ``vocabulary``, the vocabulary
            declares no ``UNKNOWN_FALLBACK``, or ``cases`` is empty. All three
            are programming errors, so they raise rather than accumulate.
    """
    if not cases:
        raise ValueError("decide() needs at least one case")

    declared = {member.value for member in vocabulary}
    if UNKNOWN_FALLBACK not in declared:
        raise ValueError(
            f"{vocabulary.__name__} declares no {UNKNOWN_FALLBACK} member — every "
            "branch vocabulary must be able to say 'I do not know' "
            "(rwa_calc.domain.branch_reasons)"
        )
    used = [case.reason for case in cases] + [otherwise_reason]
    unknown = sorted({reason.value for reason in used} - declared)
    if unknown:
        raise ValueError(f"reason(s) {unknown} are not members of {vocabulary.__name__}")

    dtype = reason_dtype(vocabulary)
    unknown_lit = pl.lit(UNKNOWN_FALLBACK, dtype=dtype)

    value_chain = pl.when(cases[0].predicate).then(cases[0].value)
    # The nullity test precedes its own predicate so an indeterminate case
    # names the row before any later case can claim it.
    reason_chain = (
        pl.when(cases[0].predicate.is_null())
        .then(unknown_lit)
        .when(cases[0].predicate)
        .then(pl.lit(cases[0].reason.value, dtype=dtype))
    )
    for case in cases[1:]:
        value_chain = value_chain.when(case.predicate).then(case.value)
        reason_chain = (
            reason_chain.when(case.predicate.is_null())
            .then(unknown_lit)
            .when(case.predicate)
            .then(pl.lit(case.reason.value, dtype=dtype))
        )

    return (
        value_chain.otherwise(otherwise),
        reason_chain.otherwise(pl.lit(otherwise_reason.value, dtype=dtype)),
    )
