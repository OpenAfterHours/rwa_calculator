"""
A carrier the RE splitter ALLOCATES must be SUMMED when its legs collapse back.

Pipeline position:
    RealEstateSplitter (fans one exposure into legs, allocating money carriers)
        -> ... -> aggregate_to_key_grain (collapses the legs back to one parent row)
        -> analysis/reconciliation.py (compares that parent row against the legacy run)

What this proves:
The splitter and the collapse helper hold two halves of one contract, in two
modules that do not import each other. ``engine/re_split/carriers.py``
decides which columns are EXTENSIVE — money that must be divided pro-rata across
the legs. ``data/schemas.py::ADDITIVE_OUTPUT_FIELDS`` decides which columns are
SUMMED when ``_collapse.py`` folds those legs back to one row per parent;
everything else takes ``.first()``.

If a column is allocated but not additive, the collapse keeps only the FIRST
leg's share and silently understates the parent. Nothing raises. The number is
simply smaller than it should be, on a frame a consumer reads.

Why this failure mode is invisible to the obvious tests: before the split legs
were allocated at all, every leg INHERITED the parent's full value, so
``.first()`` returned the correct total by accident. Correcting the leg-level
duplication removes the accident. A leg-level conservation identity — the shape
this project reached for first — sums the legs and sees nothing wrong, because
the legs ARE right; only the collapsed parent is wrong.

Scope, deliberately narrow (see the measured table below): this asserts the
contract only where a consumer actually reads the collapsed value, i.e. for
columns that are ALSO reconciliation components. 25 of the 33 allocated carriers
are non-additive, and demanding all 25 change would be a rule failing for a
reason that is not a defect (`.claude/LESSONS.md` C5) — nothing reads most of
them off the collapsed frame. The intersection is the part that bites today, and
the assertion keeps its value as both sets evolve.

References:
- CRR Art. 125 / 126, PS1/26 Art. 124F / 124H: the real-estate loan split
- `.claude/LESSONS.md` B1: a guard keyed on the wrong name fails silently forever
- `.claude/LESSONS.md` C5: a failing rule is not automatically our defect
"""

from __future__ import annotations

from rwa_calc.analysis.recon_registry import RECONCILABLE_COMPONENTS
from rwa_calc.data.schemas import ADDITIVE_OUTPUT_FIELDS
from rwa_calc.engine.re_split import carriers as re_split_carriers

#: Every column the reconciliation engine READS off the collapsed frame. Read off
#: the registry rather than hand-listed: a hand-written copy would drift out of
#: step with the registry and this test would then assert a contract nobody holds
#: (`.claude/LESSONS.md` B3).
#:
#: All THREE column families, and the reason is a refuted assumption. This started
#: as ``our_columns`` alone, on the argument that only the compared value matters.
#: But ``analysis/reconciliation.py:351`` selects
#: ``*spec.explain_columns, *spec.input_columns`` off the SAME collapsed frame, so
#: those are read too — and restricting to ``our_columns`` made five allocated,
#: non-additive, genuinely-read columns invisible to the assertion below:
#: ``collateral_financial_value``, ``collateral_re_value``,
#: ``collateral_receivables_value``, ``collateral_other_physical_value``,
#: ``guarantee_amount``. The narrower version passed while its own subject was
#: broken, which is the precise shape of a guard that cannot see the thing it
#: guards. Widen this set, never narrow it: a column read for EXPLANATION is still
#: a column a human reads a number off.
RECONCILED_COLUMNS: frozenset[str] = frozenset(
    column
    for component in RECONCILABLE_COMPONENTS
    for family in (component.our_columns, component.explain_columns, component.input_columns)
    for column in family or ()
)

#: How many allocated carriers are NOT summed on collapse. ASSERTED below, not
#: merely documented: the first version of this constant was written by hand, was
#: referenced by nothing, and said 25 when the answer was 45 — a dead number that
#: would have misled the next editor with more authority than a comment deserves.
#: If this figure moves, a carrier was added to the allocation sets without a
#: decision about its collapse behaviour, and that decision should be conscious.
KNOWN_LATENT_NON_ADDITIVE_COUNT = 45

#: Measured on a split parent (one corporate loan, drawn 1,000,000 / interest
#: 40,000, one 1,000,000 residential pledge, CRR). Each was allocated across the
#: legs, was NOT additive, and was therefore understated by the residual leg's
#: share — 23.1% here — when the parent row was rebuilt:
#:
#:     interest                  30,769.23 +  9,230.77 =    40,000.00 -> 30,769.23
#:     ead_gross                800,000.00 + 240,000.00 = 1,040,000.00 -> 800,000.00
#:     ead_for_crm              800,000.00 + 240,000.00 = 1,040,000.00 -> 800,000.00
#:     total_collateral_for_lgd 549,450.55 + 164,835.16 =   714,285.71 -> 549,450.55
#:
#: ``interest`` has since been made additive, along with
#: ``collateral_adjusted_value`` and the five columns the widened
#: :data:`RECONCILED_COLUMNS` exposed. The remaining 45 are LATENT: wrong on the
#: collapsed frame, read by no reconciliation path today. "Latent" is a claim
#: about today's consumers, not about correctness — the assertion below is what
#: keeps it honest as those consumers change.


def test_allocated_reconciliation_components_are_additive() -> None:
    """A column that is both split-allocated and reconciled must be summed on collapse.

    The intersection is what a consumer can actually observe: the reconciliation
    engine collapses our results to one row per key and compares these columns
    against the legacy system. An allocated-but-not-additive column arrives at
    that comparison holding one leg's share of the parent's value, so the run
    reports a break that is not real — or nets against a real one.
    """
    # Arrange
    allocated = _all_allocated_carriers()

    # Act
    offenders = sorted((allocated & RECONCILED_COLUMNS) - ADDITIVE_OUTPUT_FIELDS)

    # Assert
    assert offenders == [], (
        f"{offenders} are allocated pro-rata across real-estate split legs "
        f"(engine/re_split/carriers.py::_PRORATA_CARRIERS) and are compared by the "
        f"reconciliation engine (analysis/recon_registry.py), but are absent from "
        f"ADDITIVE_OUTPUT_FIELDS (data/schemas.py). engine/aggregator/_collapse.py takes "
        f".first() for every non-additive column, so on a split parent each of these "
        f"collapses to the first leg's share instead of the parent total. Fix by adding "
        f"them to ADDITIVE_OUTPUT_FIELDS."
    )


def test_the_contract_is_not_vacuous() -> None:
    """Both sides of the intersection are non-empty and hold their known members.

    Without this, a rename on either side — ``_PRORATA_CARRIERS`` emptied, the
    registry's ``our_columns`` restructured — would make the intersection empty
    and the assertion above pass forever while asserting nothing. That is the
    exact shape of `.claude/LESSONS.md` B1, whose measured instance published
    nothing into a COREP column for the template's entire life.
    """
    # Arrange
    allocated = _all_allocated_carriers()

    # Act / Assert
    assert allocated, "the splitter's allocated-carrier list is empty"
    assert RECONCILED_COLUMNS, "no reconciliation component exposes a column name"
    assert ADDITIVE_OUTPUT_FIELDS, "the additive-field set is empty"
    # THE load-bearing line, and the one this guard originally lacked. Both sets
    # being non-empty is not enough: an adversarial reviewer renamed the two
    # members of the then 2-wide intersection, both sets stayed populated, the
    # intersection emptied, the contract above passed over nothing — and this
    # guard passed too, because not one of its anchors sat on BOTH sides. A
    # vacuity guard that checks the operands instead of the OPERATION is itself
    # vacuous, which is the failure mode it exists to prevent, one level up.
    assert allocated & RECONCILED_COLUMNS, (
        "no allocated carrier is read by the reconciliation engine, so the contract "
        "above is asserting over an empty set and cannot fail. Either the splitter's "
        "carrier tuples or the registry's column names have been renamed."
    )
    # Anchors whose membership is structural rather than incidental.
    assert "ead_final" in RECONCILED_COLUMNS
    assert "ead_final" in ADDITIVE_OUTPUT_FIELDS
    assert "drawn_amount" in allocated


def test_the_latent_non_additive_count_is_unchanged() -> None:
    """The number of allocated-but-not-summed carriers matches the recorded figure.

    This is the disclosure the PR makes ("45 of 62 allocated carriers remain
    non-additive, all latent"), so it has to be a checked number rather than a
    remembered one. A change here means a carrier joined the allocation sets
    without anyone deciding how it should collapse — which is exactly the decision
    that was missed the first time and cost us a defect.
    """
    # Arrange
    allocated = _all_allocated_carriers()

    # Act
    latent = sorted(allocated - ADDITIVE_OUTPUT_FIELDS)

    # Assert
    assert len(latent) == KNOWN_LATENT_NON_ADDITIVE_COUNT, (
        f"{len(latent)} allocated carriers are non-additive, but "
        f"KNOWN_LATENT_NON_ADDITIVE_COUNT records {KNOWN_LATENT_NON_ADDITIVE_COUNT}. "
        f"If a carrier was added to the allocation sets, decide whether it must be "
        f"summed on collapse and either add it to ADDITIVE_OUTPUT_FIELDS or update "
        f"this figure deliberately. Current set: {latent}"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _all_allocated_carriers() -> frozenset[str]:
    """Every column any of the splitter's carrier tuples allocates across legs.

    Discovered by scanning ``engine/re_split/carriers`` for module-level
    names ending in ``CARRIERS`` rather than importing a fixed list, for one
    reason: the allocation sets GREW mid-batch (``_PRORATA_CARRIERS`` 33 -> 57,
    plus ``_COMMERCIAL_ONLY_CARRIERS`` appearing entirely), and a hand-listed
    import would have kept asserting over the old, smaller subject while looking
    healthy. A NEW allocation tuple is now covered the moment it is added.

    The count assertion below is what stops the introspection failing open: if a
    rename made this return an empty or truncated set, the recorded figure stops
    matching and the suite says so.
    """
    tuples = [
        value
        for name, value in vars(re_split_carriers).items()
        if name.endswith("CARRIERS") and isinstance(value, tuple)
    ]
    assert tuples, (
        "no *CARRIERS tuple found in engine/re_split/carriers — the module was "
        "renamed or restructured, and every assertion in this file is now vacuous"
    )
    return frozenset(column for group in tuples for column in group)
