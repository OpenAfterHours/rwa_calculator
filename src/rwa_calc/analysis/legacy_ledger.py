"""
Project a legacy exposure extract into the sealed reporting-ledger vocabulary.

Pipeline position:
    api.reconciliation.LegacyOutputLoader.load()
        -> project_legacy_ledger()
        -> LegacyLedgerSource (a reporting.metadata.ResultsSource)
        -> COREPGenerator().generate(...) -> the firm's side of a return

Key responsibilities:
- Rename the mapped ``legacy_<component>`` / ``legacy_<carrier>`` columns of a
  loaded extract onto the sealed reporting-ledger column names the COREP
  generators read, applying nothing beyond a rename, a canonicalisation of
  categorical labels, and a type.
- Report what the mapping could NOT supply, per template and per column
  (``LedgerCoverage``), so an unpopulated cell reads as *unavailable* rather
  than as a legacy zero — and so an UNPRODUCIBLE template reads as absent
  rather than as a template of zeroes.

WHY THE MAPPING HAS TO CARRY EVERYTHING. ``LegacyOutputLoader.load()`` ends in a
``.select`` over the declared keys and the mapped ``legacy_*`` columns, so
nothing the mapping does not declare survives the load. Every ledger column the
templates need must therefore arrive as a component (an AMOUNT, with a delta and
a tolerance) or as a carrier (a NAME or a FLAG, passed through unreconciled) —
which is why ``recon_registry`` grew two registries rather than one.

EVERY TARGET IS A SEALED COLUMN. The generators resolve most quantities through
a ladder whose first rungs (``scra_provision_amount``, ``bs_type``, ``sa_cqs``,
``ccf_applied``, ``provision_held``, ``default_status``, ...) are not declared on
``AGGREGATOR_EXIT_EDGE`` and exist only on synthetic unit frames, so our own side
always traverses the sealed fallback. Writing a legacy value onto a synthetic
rung would put the two sides on DIFFERENT rungs of the same ladder — two
plausible numbers from different bases, which is the silent basis difference this
feature exists to expose, shipped inside the tool meant to find it.

WHY THERE IS NO SECOND REPORTING ENGINE. ``reporting.metadata.ResultsSource`` is
a two-member structural Protocol — a ``framework`` and a ``scan_results()``.
``LegacyLedgerSource`` satisfies it, so the firm's side of a return is produced
by ``COREPGenerator`` running the same ``TemplateSpec``s through the same
executor as ours. Every template added later gets a legacy side for free, and the
two sides cannot disagree about what a cell MEANS — only about the data behind
it. The cost is recorded in ``docs/plans/return-reconciliation.md`` under "Honest
limits": their side is aggregated OUR way (our weighting, our distinct-count
rule, our sign convention), which is the right default because it holds the
reporting rules constant so a difference means a DATA difference.

THE PROJECTION CALCULATES NO AMOUNTS. It renames and types. It does not derive a
CCF from a commitment, a floor from a PD, or a risk weight from an RWA. Where a
DERIVATION is wanted it is production's own that runs, on the production frame,
not a copy here — see the gross-exposure decision below. Where the mapping
supplies no source the column is simply ABSENT, which the generators tolerate —
``corep/c08.py::_prepare`` adds its derived discriminators "each only when its
sources exist — underived columns make their tolerant terms match nothing", and
``pick(cols, ...)`` resolves every metric by presence.

ABSENT, NOT NULL-FILLED — and the distinction is load-bearing. A typed null
COLUMN is present, and ``kernel/sums.py::col_sum`` sums a present all-null column
to **0.0** while returning ``None`` for an absent one. Injecting typed nulls for
unsupplied carriers would therefore manufacture exactly the false legacy zeros
this module exists to avoid. Nulls belong inside a column the mapping DID supply
(a row with no value keeps its null and is never filled to 0.0); an unsupplied
carrier is left out of the projection entirely. Two consequences are the
generators' own and are reported through ``LedgerCoverage`` rather than papered
over: ``kernel/columns.py::ensure_gross_side_carriers`` injects all-null
``reporting_gross_on_bs`` / ``_off_bs`` at generator entry when they are absent
(so those cells render 0.0, not null), and a ``SafeSum`` over a wholly absent
column group renders the template's empty policy (0.0 on COREP).

THE PD DECISION — one mapped PD lands on BOTH ``pd`` and ``pd_floored``.
C 08.03/C 08.05 allocate rows on ``pd_floored`` under CRR but on the
pre-input-floor ``pd`` under Basel 3.1 (``corep/c08.py::_pd_alloc_col``), while
the REPORTED PD column is always ``pick(cols, "pd_floored", "pd")`` and C 08.01
col 0010 binds ``pd_floored`` by name with no ladder at all. A legacy extract
carries ONE PD and says nothing about whether an input floor was applied to it,
so:

- writing it only to ``pd`` leaves C 08.01 col 0010 null and makes CRR allocate
  on a column present only through a fallback rung;
- writing it only to ``pd_floored`` works today but rests on Basel 3.1's
  allocation ladder falling THROUGH its preferred rung — an implementation
  detail of a module this one does not own;
- writing it to BOTH states exactly what is known (pre-floor and post-floor are
  the same as far as this extract is concerned), invents no value, and makes the
  row allocation identical under both frameworks — which is the honest answer
  when the extract carries no floor information.

The consequence to state on any compare surface: a RULE-driven banding
difference (their engine bands on the post-floor PD where ours bands pre-floor)
is invisible from an extract with a single PD. It becomes visible only when the
extract carries their own band/grade label, or when the filed return is supplied.

THE GROSS-EXPOSURE DECISION — map the RAW amounts, not the derived carriers.
``kernel/columns.py::ensure_gross_side_carriers`` runs at generator entry and
derives ``reporting_gross_on_bs`` / ``_off_bs`` from ``drawn_amount`` +
``interest`` and ``nominal_amount`` / ``undrawn_amount``, selected by
``exposure_type``, whenever the sealed columns are absent — the aggregator's own
rule, floor-at-0 and "a wholly unknown side stays null" included. So the default
route is the ``drawn`` / ``interest`` / ``undrawn`` / ``nominal`` components plus
the ``exposure_type`` carrier, and the derivation is production's. Three reasons
it beats mapping the derived carriers directly:

- it is what a firm's extract actually contains — a drawn balance and a
  commitment, not a "reporting gross on-balance-sheet";
- it reuses the derivation rather than trusting a firm to have applied the same
  one, so a floor-at-0 or a null-side convention cannot diverge silently;
- ``exposure_type`` has to be mapped anyway (it is the sealed rung of every
  balance-sheet ladder), so the raw route costs one extra mapped column, not five.

The ``gross_on_balance_sheet`` / ``gross_off_balance_sheet`` components remain as
an OVERRIDE for a firm that already reports a per-side gross and wants their
split rather than ours. Mapping them wins, because the derivation only fires on
an absent column. **The one thing the raw route must not become is a partial
one**: with neither the sealed column nor any raw source, the derivation still
runs and injects an ALL-NULL column, which sums to 0.0 rather than to null. That
is the generator's contract, not something this module can fix, so those cells
are reported through ``LedgerCoverage``.

THE PROVISIONS DECISION — the mapped provisions land on ``provision_deducted``
AND ``provision_allocated``, never on SCRA/GCRA. All four provisions cells in
scope read a ladder that checks ``scra_provision_amount`` / ``gcra_provision_amount``
first and falls through to a sealed carrier: ``provision_deducted`` for C 07.00
col 0030 (``c07.py::_prepare``) and ``provision_allocated`` for the C 08.01 col
0290 / C 08.03 col 0110 post-pass (``postpass.py::provisions_postfix``). Neither
SCRA carrier is sealed, so OUR side always takes the fallback rung. Landing a
firm's provisions on SCRA/GCRA would put the legacy side on the other rung, and
``c07_provision`` also feeds ``_block_cap_scale`` — the cap basis for the C 07.00
protection block — so the divergence would leak into cells well beyond the
provisions column.

One mapped column populates BOTH sealed names, and the safety of that is a
POPULATION property, not a value one. C 07.00 filters
``reporting_approach_origin == "standardised"``; C 08.01 and C 08.03 filter the
IRB set. A leg carries exactly one origin approach, so no leg can be read by both
``provision_deducted`` (C 07.00 col 0030) and ``provision_allocated`` (C 08.01
col 0290 / C 08.03 col 0110). Measured on the reference portfolio: 54,500 of
provisions splits into 1,500 on C 07.00 and 53,000 on C 08.01, nothing counted
twice and nothing lost. No cell in scope reads both columns, and no roll-up sums
the two templates.

THE ONE MECHANISM THAT WOULD BREAK THAT PARTITION IS UNREACHABLE, deliberately.
``c07_population`` admits the counterparty-credit-risk rows by ``risk_type`` with
NO approach filter, so an IRB-origin CCR leg would sit in both populations. No
component or carrier can supply ``risk_type``, so on a projected frame ``admit``
is ``None`` and the population is purely approach-based. Adding a ``risk_type``
carrier later would make the breach reachable and the dual write would then have
to be split per approach — which is why
``test_risk_type_is_not_projectable_so_the_populations_cannot_overlap`` guards it
rather than this paragraph.

REACHABLE AND POPULATED ARE DIFFERENT FACTS, reported separately. "Reachable"
is a statement about the MAPPING — the required columns are supplied and no
unrecognised approach label is standing in the way. "Populated" is a statement
about the BOOK — it actually contains rows of that population. An
all-standardised extract leaves C 08.01 REACHABLE and UNPOPULATED: the firm has
no IRB book, which is not a defect and has nothing to fix. Collapsing the two
produced an unreachable template with ``blocking_labels() == ()`` — unreachable
with nothing to fix, a state a user cannot act on, and the same conflation
``sheet_not_emitted`` already made between "no exposure" and "no bundle key".
The three states a compare surface must render differently: unreachable with
blocking COLUMNS (map these), unreachable with blocking LABELS (add these
value_map entries), reachable but unpopulated (nothing to fix).

AN UNMAPPED LABEL IS REPORTED, NOT PASSED THROUGH. Canonicalisation casefolds
and applies the ``value_map``; what it cannot do is INVENT a translation. A label
that survives it without matching the engine vocabulary used to reach the sheet
key unchanged, and the damage is asymmetric: an unmapped CLASS produces bogus
sheets, while an unmapped APPROACH empties the population of every template —
because ``population_flags`` admits by an ``is_in`` over the approach values, and
a label outside it matches nothing. A firm whose extract says ``"IRB"`` would have
been told all four templates were reachable and handed a blank return.

So the projection MEASURES the projected label columns against
``LEDGER_VOCABULARY`` (built from ``ExposureClass`` / ``ApproachType`` / the
input-domain constants, never a hand-written list) and reports what it finds:
``LedgerCoverage.unmapped_labels`` names the offending values, their row counts
and the TOML table to fix, and ``reachable_templates`` accounts for the
VOCABULARY as well as the columns — a template no row's approach admits is not
reachable, and ``blocking_labels`` says which values were seen instead. The
pre-flight ``ledger_coverage(...)`` form has no data to measure and is documented
as optimistic for exactly that reason.

THREE DEGRADATIONS THAT CHANGE A BASIS RATHER THAN EMPTY A CELL, so they are
recorded here rather than in ``LedgerCoverage`` (the cell IS populated — on a
different footing from ours):

- **No post-substitution twin.** Nothing maps ``reporting_class`` /
  ``reporting_approach``, and nothing should: an extract has no notion of a
  guarantor's sheet. ``kernel/bases.py`` degrades the POST basis to the ORIGIN
  basis when they are absent, which is number-neutral on a book that never
  substitutes and, on one that does, leaves the covered part's exposure value
  and RWEA on the obligor's sheet.
- **No ``is_guarantee_beneficial``.** C 07.00 ``_protection_exprs`` and
  ``crm_substitution.irb_protection_exprs`` gate the substitution block on it
  (CRR Art. 193(1)/(3): a guarantee the calculator declined has no substitution
  effect). Absent, EVERY mapped ``guaranteed_portion`` produces an outflow.
- **No ``post_crm_exposure_class_guaranteed``.** The col 0090 / col 0070 outflow
  is then reported with no matching col 0100 / col 0080 inflow anywhere in the
  estate. This one IS flagged, on the inflow cell.

References:
- docs/plans/return-reconciliation.md, Phase 2 (the legacy ledger projection)
- Reg (EU) 2021/451 Annex II: C 07.00, C 08.01, C 08.03, C 08.06
- PRA PS1/26 Annex I/II: OF 07.00, OF 08.01, OF 08.03, OF 08.06
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.analysis.recon_registry import (
    LEDGER_CARRIERS_BY_NAME,
    RECONCILABLE_COMPONENTS_BY_NAME,
)
from rwa_calc.data.schemas import (
    VALID_PROTECTION_TYPES,
    VALID_SL_TYPES,
    VALID_SLOTTING_CATEGORIES,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.reporting.corep.templates import (
    get_c07_columns,
    get_c08_03_columns,
    get_c08_06_columns,
    get_c08_06_rows,
    get_c08_columns,
    get_sa_row_sections,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from rwa_calc.analysis.recon_registry import (
        CarrierMapping,
        LedgerCarrier,
        LegacyColumnMapping,
        ReconcilableComponent,
    )

logger = logging.getLogger(__name__)

#: The frameworks the COREP generators accept (``reporting.metadata`` vocabulary).
FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")

#: The templates this projection is scoped to (plan Phase 2 / open question 1).
#: The projection itself is generic — anything the executor can run over the
#: sealed ledger it can run over this one — but the COVERAGE report is only as
#: honest as the enumeration behind it, so it is stated per template rather than
#: inferred.
LEDGER_TEMPLATE_IDS: tuple[str, ...] = ("c07_00", "c08_01", "c08_03", "c08_06")

#: A cell requirement, in DISJUNCTIVE NORMAL FORM: a tuple of ALTERNATIVES, each
#: a set of columns ALL of which are needed. The cell is populatable when any one
#: alternative is fully supplied. ``()`` = no carrier of its own (a constant, a
#: ``Formula`` over other cells, or a post-execute pass deriving from cells
#: already listed).
#:
#: IT WAS A CONJUNCTION OF OR-GROUPS, AND THAT SHAPE COULD NOT STATE THE TRUTH.
#: The on-balance-sheet gross is "the sealed carrier, OR drawn AND interest" —
#: an OR over a conjunction, which a conjunction of ORs cannot express. Written
#: as one OR-group ``(sealed, drawn, interest)`` it read ``interest`` as an
#: ALTERNATIVE source when ``ensure_gross_side_carriers`` treats it as an
#: ADDEND: a mapping supplying ``interest`` without ``drawn`` satisfied the
#: group, coverage reported the cell available, and the generator published a
#: present, non-null **0.0** — a 100% understatement of on-balance-sheet gross
#: reported as a confident zero. Measured across 3,078 (template, column) pairs,
#: two mappings did this: ``drawn`` silently zeroed 7 pairs and ``undrawn`` 9,
#: including C 07.00 cols 0010/0150, C 08.01 cols 0020/0040/0070/0090/0100 and
#: C 08.03 cols 0010/0020.
#:
#: The fix is the TYPE, not the two entries: a shape that cannot state the truth
#: produces this defect again the next time a derived carrier is added. Build
#: requirements with :func:`_needs` / :func:`_either` / :func:`_both` rather than
#: writing tuples by hand, so the boolean structure is explicit.
type CellRequirement = tuple[frozenset[str], ...]

#: The two components whose value lands on MORE THAN ONE sealed ledger column.
# Both are documented decisions, not conveniences — see the module docstring's
# "PD DECISION" and "PROVISIONS DECISION" sections. Everything else writes the
# single sealed name at the head of its ``our_columns`` preference order.
MULTI_TARGET_COMPONENTS: Mapping[str, tuple[str, ...]] = {
    "pd": ("pd_floored", "pd"),
    "provisions": ("provision_deducted", "provision_allocated"),
}

#: Every ledger column a mapping is CAPABLE of supplying — the union of the
#: component targets and the carrier targets. The coverage report narrows its
#: "needs ..." message to these, because naming a ladder rung nobody can map
#: (``scra_provision_amount``, ``bs_type``, ``ccf_applied``) sends an analyst
#: looking for a column that has no home in the grammar.
PROJECTABLE_LEDGER_COLUMNS: frozenset[str] = frozenset(
    target
    for spec in RECONCILABLE_COMPONENTS_BY_NAME.values()
    for target in MULTI_TARGET_COMPONENTS.get(spec.name, (spec.our_columns[0],))
) | frozenset(carrier.ledger_column for carrier in LEDGER_CARRIERS_BY_NAME.values())

#: The engine ``exposure_type`` values inside the credit-risk gross scope, plus
#: the legacy ``"facility"`` alias every discriminator still recognises. Kept as a
#: literal here and pinned in the tests against
#: ``kernel/columns.py::_CREDIT_BS_TYPES``, which is the source of truth a copy
#: could otherwise drift from.
_CREDIT_EXPOSURE_TYPES: frozenset[str] = frozenset(
    {"loan", "contingent", "facility_undrawn", "facility"}
)


@dataclass(frozen=True)
class LedgerVocabulary:
    """The closed set of values a projected LABEL column may legitimately hold.

    Attributes:
        mapping_name: The TOML key an analyst edits to fix an unmapped value —
            a ``[components.*]`` or ``[carriers.*]`` table name, never the ledger
            column, because the column is not what they can change.
        values: The canonical vocabulary, taken from the enum or the input-domain
            constant that DEFINES it, never a hand-written list (a hand-written
            one drifts, and the drift is invisible: an unrecognised label neither
            raises nor matches).
    """

    mapping_name: str
    values: frozenset[str]


#: The population discriminator, named once: reachability, the coverage warning
#: and ``blocking_labels`` all key it.
_APPROACH_COLUMN: str = "reporting_approach_origin"

#: Its TOML table key — what an analyst edits, and the key ``unmapped_labels``
#: reports it under.
_APPROACH_MAPPING: str = "approach"

# C 08.06 sheet/row mappings whose invalid DATA makes the template unsafe even
# when the columns exist. These names are the actionable TOML carrier keys.
_SLOTTING_PLACEMENT_MAPPINGS: frozenset[str] = frozenset(
    {"sl_type", "slotting_category", "is_short_maturity", "is_hvcre"}
)

#: Ledger column -> the vocabulary its values must fall inside. Only the columns
#: whose values DECIDE something appear: a sheet key, a population, a row axis, a
#: column split. ``counterparty_reference`` is deliberately absent — an obligor
#: reference is a free identifier with no vocabulary to violate.
LEDGER_VOCABULARY: Mapping[str, LedgerVocabulary] = {
    "reporting_class_origin": LedgerVocabulary(
        "exposure_class", frozenset(member.value for member in ExposureClass)
    ),
    "reporting_approach_origin": LedgerVocabulary(
        "approach", frozenset(member.value for member in ApproachType)
    ),
    "exposure_type": LedgerVocabulary("exposure_type", _CREDIT_EXPOSURE_TYPES),
    "protection_type": LedgerVocabulary("protection_type", frozenset(VALID_PROTECTION_TYPES)),
    "sl_type": LedgerVocabulary("sl_type", frozenset(VALID_SL_TYPES)),
    "slotting_category": LedgerVocabulary(
        "slotting_category", frozenset(VALID_SLOTTING_CATEGORIES)
    ),
}

#: The ``reporting_approach_origin`` values each scoped template's POPULATION
#: filter admits. Reachability has to test the vocabulary as well as the column:
#: a mapping that supplies an approach column every row of which says ``"IRB"``
#: has the column and an empty population, and reporting that as "reachable" is
#: the worst thing this module can say — the analyst gets a confident promise and
#: a blank return with nothing naming the cause.
TEMPLATE_POPULATION_LABELS: Mapping[str, frozenset[str]] = {
    # c07_population: population_flags(..., ("standardised",)).
    "c07_00": frozenset({ApproachType.SA.value}),
    # _irb_population: the whole IRB book, slotting included.
    "c08_01": frozenset(
        {
            ApproachType.FIRB.value,
            ApproachType.AIRB.value,
            ApproachType.SLOTTING.value,
        }
    ),
    # _non_slotting: the IRB book with slotting filtered out.
    "c08_03": frozenset({ApproachType.FIRB.value, ApproachType.AIRB.value}),
    # c08_06_plans: the specialised-lending slotting book only.
    "c08_06": frozenset({ApproachType.SLOTTING.value}),
}

# Flag tokens for a ``kind="boolean"`` carrier. Anything else is NULL, never
# False: "we do not know" and "not defaulted" are different statements, and the
# defaulted ladders in C 07.00 / C 08.01 read the difference.
_TRUE_TOKENS: frozenset[str] = frozenset({"true", "t", "y", "yes", "1"})
_FALSE_TOKENS: frozenset[str] = frozenset({"false", "f", "n", "no", "0"})


def _needs(*names: str) -> CellRequirement:
    """ONE alternative requiring ALL of *names*."""
    return (frozenset(names),)


def _either(*requirements: CellRequirement) -> CellRequirement:
    """Any one of *requirements* suffices (their alternatives, concatenated)."""
    return tuple(alternative for requirement in requirements for alternative in requirement)


def _both(*requirements: CellRequirement) -> CellRequirement:
    """Every one of *requirements* is needed (the cross product of alternatives).

    ``_both(_either(a, b), _either(c, d))`` is ``(a|b) AND (c|d)`` = the four
    alternatives ``ac``, ``ad``, ``bc``, ``bd`` — which is how a conjunction of
    disjunctions is stated in DNF. An empty requirement is the identity, so
    composing with a cell that has no carrier of its own changes nothing.
    """
    combined: CellRequirement = (frozenset(),)
    for requirement in requirements:
        if not requirement:
            continue
        combined = tuple(left | right for left in combined for right in requirement)
    return () if combined == (frozenset(),) else _minimal(combined)


def _minimal(requirement: CellRequirement) -> CellRequirement:
    """Drop duplicate alternatives and any that strictly contain another.

    A superset can never be the cheaper route to the same cell, so keeping it
    changes no answer and only lengthens the "needs ..." report. Matters because
    ``_both`` over a chain of formula cells multiplies alternatives out.
    """
    unique = {frozenset(alternative) for alternative in requirement}
    return tuple(
        sorted(
            (
                alternative
                for alternative in unique
                if not any(other < alternative for other in unique)
            ),
            key=lambda alternative: (len(alternative), sorted(alternative)),
        )
    )


def _any_of(*names: str) -> CellRequirement:
    """Any ONE of *names* suffices — one single-column alternative each."""
    return _either(*(_needs(name) for name in names))


# The two gross-exposure requirements — and the OR-over-a-conjunction the type
# was widened for. EITHER the sealed per-side carrier (mapped directly through
# the ``gross_*_balance_sheet`` override components) OR the raw amounts
# ``ensure_gross_side_carriers`` derives it from at generator entry.
#
# ON SIDE: ``clip0(drawn) + clip0(interest)``, both null-filled to 0. ``drawn``
# is the source; ``interest`` is an OPTIONAL ADDEND, not an alternative — a
# leave-one-out sweep confirms dropping ``interest`` while keeping ``drawn``
# changes no cell, while the reverse zeroes the whole on-balance-sheet gross.
_ON_BS_GROSS: CellRequirement = _any_of("reporting_gross_on_bs", "drawn_amount")

# OFF SIDE: the derivation routes by ``exposure_type`` — a contingent's nominal,
# a facility_undrawn's undrawn — so BOTH raw columns are required whenever the
# sealed carrier is absent. This DELIBERATELY OVER-DEMANDS: a book of pure
# ``loan`` rows needs neither, and one of pure revolvers needs only ``undrawn``.
# The alternative is to inspect the distinct ``exposure_type`` values at
# projection time, which would put a collect inside ``reconcile()`` and break the
# wiring slice's zero-collect contract. Over-reporting availability is the wrong
# way to be wrong, so the conservative requirement stands. A firm with no
# off-balance-sheet book maps the two columns as constant zeros, or maps
# ``gross_off_balance_sheet`` directly.
_OFF_BS_GROSS: CellRequirement = _either(
    _needs("reporting_gross_off_bs"), _needs("nominal_amount", "undrawn_amount")
)

# The provisions ladder, as the generators actually traverse it. The SCRA/GCRA
# rungs are listed because they are what the cell checks first, but nothing
# targets them: they are not sealed, so our side always lands on the fallback
# (``provision_deducted`` on C 07.00, ``provision_allocated`` on C 08.01/03).
_PROVISIONS_C07: CellRequirement = _any_of(
    "scra_provision_amount", "gcra_provision_amount", "provision_deducted"
)
_PROVISIONS_C08: CellRequirement = _any_of(
    "scra_provision_amount", "gcra_provision_amount", "provision_held", "provision_allocated"
)

# The two money ladders every template resolves by ``pick``, named once so a
# requirement cannot restate them differently from the generator.
_RWA: CellRequirement = _any_of("rwa_final", "rwa_post_factor", "rwa")
_PD: CellRequirement = _any_of("pd_floored", "pd")

# The balance-sheet side. ``bs_type`` is the first rung and is NOT sealed, so
# the real ledger always resolves to ``exposure_type`` — which is why that is
# the carrier the registry offers.
_BS_SIDE: CellRequirement = _any_of("bs_type", "exposure_type")

# The defaulted ladder, in the generators' own precedence order. ``is_defaulted``
# is the sealed rung; ``default_status`` is synthetic-frame-only; the class and
# PD rungs are last-resort proxies that state something DIFFERENT.
_DEFAULTED: CellRequirement = _any_of(
    "is_defaulted", "default_status", "exposure_class_applied", "exposure_class", "pd_floored"
)

# The C 07.00 CCF-bucket cells (0160-0190): the applied conversion factor picks
# the bucket, the off-balance-sheet gross is what the bucket sums.
# ``ccf_applied`` is the second rung of the C 07.00 carrier ladder (synthetic
# unit frames spell it that way); ``ccf`` is what the pipeline seals, and it is
# what C 08.03 col 0030 binds BY NAME with no ladder at all.
# The off-side NARROWING is part of what the bucket reads, not a nicety:
# ``_has_bs_side`` gates it, and without it a drawn loan (ccf = 0.0, a real CRR
# bucket) joins the 0% bucket and turns a null cell into a 0.0 one.
_CCF_BUCKET: CellRequirement = _both(_any_of("ccf", "ccf_applied"), _OFF_BS_GROSS, _BS_SIDE)

# The Annex II cap on the C 07.00 substitution block: the covered part is capped
# at the row's own contribution to col 0040, i.e. gross net of provisions
# (``c07.py::_block_cap_scale``). So cols 0050-0080 report a magnitude that
# depends on the GROSS and the PROVISIONS as well as on the covered carrier —
# found by the leave-one-out sweep, which caught cols 0050/0060 moving when the
# drawn amount was dropped and the cap basis collapsed.
_C07_BLOCK_CAP: CellRequirement = _both(_ON_BS_GROSS, _OFF_BS_GROSS, _PROVISIONS_C07)

# C 08.01 caps the same way but on its OWN basis: ``irb_block_cap_scale`` reads
# the two gross carriers and does NOT net provisions off it (the Art. 111(2)
# drawn-first deduction is SA-only), so the two caps are separate constants.
_C08_BLOCK_CAP: CellRequirement = _both(_ON_BS_GROSS, _OFF_BS_GROSS)

# The supporting-factor RWEA adjustments (C 07.00 cols 0216/0217, C 08.01 cols
# 0256/0257): sigma(rwa_pre_factor - rwa_final) over the rows the factor was
# applied to. ``_sf_adjustment_cell`` prefers the factor's own dedicated flag and
# falls back to the generic ``supporting_factor_applied`` ALONGSIDE the
# is_sme / is_infrastructure discriminator — a conjunction the old shape had to
# approximate and DNF states exactly.
_SF_SME_ADJUSTMENT: CellRequirement = _both(
    _needs("rwa_pre_factor"),
    _either(
        _needs("sme_supporting_factor_applied"),
        _needs("is_sme", "supporting_factor_applied"),
    ),
)
_SF_INFRA_ADJUSTMENT: CellRequirement = _both(
    _needs("rwa_pre_factor"),
    _either(
        _needs("infrastructure_factor_applied"),
        _needs("is_infrastructure", "supporting_factor_applied"),
    ),
)

# =============================================================================
# The enumeration — what each scoped template reads off the results frame
# =============================================================================
#
# Derived from the generators themselves (``reporting/corep/c07.py``,
# ``reporting/corep/c08.py`` and the helpers they call: ``kernel/bases.py``,
# ``kernel/columns.py``, ``corep/crm_substitution.py``, ``corep/pd_scale.py``,
# ``corep/postpass.py``). Module-derived discriminator columns (``c07_*`` /
# ``c08_*``) are resolved back to the LEDGER columns ``_prepare`` builds them
# from, because those are the only names a mapping can supply.

#: Columns without which a template produces nothing at all: the sheet key, the
#: population discriminator and the two money columns every plan builder resolves
#: before it does anything else. A mapping missing any of these makes the
#: template unreachable rather than sparse.
_SHEET_AND_MONEY: CellRequirement = _both(
    _needs("reporting_class_origin", "reporting_approach_origin", "ead_final"), _RWA
)

# C 08.06 is keyed by specialised-lending TYPE rather than exposure class. The
# generator can technically degrade without ``sl_type`` (one generic sheet) or
# ``is_short_maturity`` (everything assigned long), but either result fabricates
# placement differences in a reconciliation. Require the real sheet and row
# discriminators before declaring the template comparable.
_SLOTTING_SHEET_ROWS_AND_MONEY: CellRequirement = _both(
    _needs(
        "reporting_approach_origin",
        "ead_final",
        "sl_type",
        "slotting_category",
        "is_short_maturity",
    ),
    _RWA,
)

TEMPLATE_REQUIRED_COLUMNS: Mapping[str, CellRequirement] = {
    # c07_plans / c08_01_plans / c08_03_plans each pick() these three and append
    # an error when one is absent; population_flags() keys the approach column
    # and returns an EMPTY population when it is missing (never a pass-through).
    "c07_00": _SHEET_AND_MONEY,
    "c08_01": _SHEET_AND_MONEY,
    # C 08.03 additionally needs a PD: _pd_alloc_col() returning None records
    # "No PD column available — skipping PD range breakdown" and emits no sheets.
    "c08_03": _both(_SHEET_AND_MONEY, _PD),
    "c08_06": _SLOTTING_SHEET_ROWS_AND_MONEY,
}

#: Columns whose absence deletes a template's ROW AXIS — a categorically louder
#: failure than an empty cell, and the reason this is a table of its own.
#:
#: C 08.03 is the only member of the three. Its rows ARE the PD scale: without a
#: PD column ``pd_scale.banded_rows`` cannot run, ``c08_03_plans`` returns ``{}``
#: for every exposure class, and the whole template disappears from the
#: submission. C 07.00 and C 08.01 have static row axes and degrade to sparse
#: rows and empty cells instead. A compare surface must say "we cannot produce
#: this template at all", never render a template-wide zero delta.
LEDGER_ROW_AXIS_FATAL: Mapping[str, CellRequirement] = {
    "c08_03": _PD,
    "c08_06": _needs("slotting_category", "is_short_maturity"),
}


@dataclass(frozen=True)
class RowAxisRequirement:
    """What a set of template ROWS needs in order to be populated at all.

    The row-granular sibling of the cell requirements. A column requirement says
    "this figure cannot be computed"; a row requirement says "these rows cannot
    be selected", which silences EVERY column on them. Both are ways a cell can
    change without the delta meaning anything, so both have to be reportable —
    ``unavailable_refs`` for the first, ``unavailable_rows`` for the second.

    Attributes:
        rows: The affected row refs. Empty means either that the axis is
            regime-shaped (use ``rows_for``) or that it is DATA-driven and
            cannot be enumerated in advance — C 08.03's PD bands, which
            ``LEDGER_ROW_AXIS_FATAL`` covers instead.
        requirement: What those rows need.
        description: The Annex II sense of the rows, for the panel.
        rows_for: Resolver for a regime-shaped axis, taking the framework —
            C 07.00's risk-weight band section grows thirteen sub-bands under
            Basel 3.1, so its refs cannot be a literal. Wins over ``rows``.
    """

    rows: tuple[str, ...]
    requirement: CellRequirement
    description: str
    rows_for: Callable[[str], tuple[str, ...]] | None = None

    def refs(self, framework: str) -> tuple[str, ...]:
        """The affected row refs under *framework*."""
        if self.rows_for is not None:
            return self.rows_for(framework)
        return self.rows


def _sa_band_rows(framework: str) -> tuple[str, ...]:
    """C 07.00's risk-weight band rows — section 2 of its regime-shaped axis."""
    sections = get_sa_row_sections(framework)
    return tuple(row.ref for row in sections[_SA_BAND_SECTION].rows)


def _slotting_rows(framework: str) -> tuple[str, ...]:
    """C 08.06's framework-shaped category x maturity row axis."""
    return tuple(row_ref for row_ref, _label, _is_short, _rw in get_c08_06_rows(framework))


#: Section index of C 07.00's risk-weight band rows, mirroring the dispatch in
#: ``corep/c07.py::_terms_for_row`` (``section_index == 2``).
_SA_BAND_SECTION: int = 2

#: Row-axis dependencies: columns that decide WHICH ROWS a sheet emits rather
#: than what a column reports. A mapping can populate every column of C 07.00 and
#: still emit only its Total row, so these are reported alongside the cell
#: requirements rather than folded into them.
LEDGER_ROW_AXIS: Mapping[str, tuple[RowAxisRequirement, ...]] = {
    "c07_00": (
        RowAxisRequirement(("0015", "0300", "0320"), _DEFAULTED, "defaulted rows"),
        RowAxisRequirement(
            ("0020", "0341", "0343", "0344"),
            _any_of("sme_supporting_factor_eligible", "exposure_class"),
            "SME 'of which' rows",
        ),
        RowAxisRequirement(("0021", "0022", "0023"), _needs("sl_type"), "specialised lending"),
        RowAxisRequirement(
            ("0024", "0025", "0026"),
            _needs("sl_type", "sl_project_phase"),
            "project-finance phases",
        ),
        RowAxisRequirement(
            ("0030", "0035"),
            _any_of("is_sme", "is_infrastructure"),
            "supporting-factor rows",
        ),
        RowAxisRequirement(("0050", "0060"), _needs("ppu_reason"), "permanent partial use"),
        RowAxisRequirement(("0070", "0080"), _BS_SIDE, "on/off balance sheet"),
        RowAxisRequirement(("0090", "0110"), _needs("risk_type"), "counterparty credit risk"),
        RowAxisRequirement(
            ("0100", "0120"),
            _needs("risk_type", "cp_entity_type", "cp_is_qccp"),
            "QCCP-cleared 'of which'",
        ),
        RowAxisRequirement(
            (), _needs("risk_weight"), "risk-weight band rows", rows_for=_sa_band_rows
        ),
        RowAxisRequirement(("0281", "0282", "0283"), _needs("ciu_approach"), "CIU approach rows"),
        RowAxisRequirement(
            ("0290", "0310", "0330", "0331", "0332", "0340", "0341", "0342", "0343", "0344"),
            _both(
                _needs("property_type"),
                _any_of(
                    "materially_dependent_on_property", "has_income_cover", "is_income_producing"
                ),
            ),
            "real-estate rows",
        ),
        RowAxisRequirement(
            ("0350", "0351", "0352", "0353", "0354"),
            _needs("is_qualifying_re"),
            "non-qualifying real estate",
        ),
        RowAxisRequirement(("0360",), _needs("is_adc"), "ADC row"),
        RowAxisRequirement(
            ("0371", "0372", "0373", "0374"),
            _needs("equity_transitional_approach", "equity_higher_risk"),
            "equity transitional rows",
        ),
        RowAxisRequirement(
            ("0380",),
            _needs("currency_mismatch_multiplier_applied"),
            "currency-mismatch row",
        ),
    ),
    "c08_01": (
        RowAxisRequirement(("0020", "0030"), _BS_SIDE, "on/off balance sheet"),
        RowAxisRequirement(
            ("0070", "0080"),
            _needs("reporting_approach_origin"),
            "graded vs slotting",
        ),
        RowAxisRequirement(("0190",), _needs("exposure_class"), "unrated-corporate memo (B31)"),
        RowAxisRequirement(
            ("0200",),
            _both(_needs("exposure_class"), _any_of("cp_is_investment_grade", "pd_floored")),
            "unrated investment-grade memo (B31)",
        ),
    ),
    "c08_03": (
        # pd_scale.banded_rows keys the derived c08_pd_range / c08_pd_parent
        # labels off the framework's allocation PD, and the populated set is
        # DATA-driven — so the refs cannot be enumerated here. Losing the PD
        # deletes the whole axis, which LEDGER_ROW_AXIS_FATAL reports instead.
        RowAxisRequirement((), _PD, "PD-band rows"),
    ),
    "c08_06": (
        RowAxisRequirement(
            (),
            _needs("slotting_category", "is_short_maturity"),
            "slotting category and maturity rows",
            rows_for=_slotting_rows,
        ),
    ),
}

#: C 07.00: column ref -> the ledger columns its binding reads.
_C07_00_CELLS: Mapping[str, CellRequirement] = {
    # SafeSum(reporting_gross_on_bs, reporting_gross_off_bs, c07_ccr_gross). The
    # CCR limb (exposure_type + reporting_gross_drawn/_undrawn) is deliberately
    # NOT required: it carries only the counterparty-credit-risk / settlement
    # legs, which an SA credit-risk extract does not hold.
    "0010": _both(_ON_BS_GROSS, _OFF_BS_GROSS),
    "0020": _needs("own_funds_deduction_amount"),
    # Sum(c07_provision): the per-row SCRA+GCRA pick with the sealed Art. 111(2)
    # deducted provision as its fallback rung.
    "0030": _PROVISIONS_C07,
    "0035": _needs("on_bs_netting_amount"),  # Basel 3.1 only
    "0040": (),  # Formula 0010 - 0030 (- 0035)
    "0050": _both(_needs("guaranteed_portion", "protection_type"), _C07_BLOCK_CAP),
    # The 0050/0060 split is made by _protection_exprs off protection_type; with
    # no protection_type every covered part lands in 0050 and 0060 is a hard 0.0.
    "0060": _both(_needs("guaranteed_portion", "protection_type"), _C07_BLOCK_CAP),
    "0070": _both(_needs("fcsm_collateral_value"), _C07_BLOCK_CAP),
    "0080": _both(
        _any_of("life_ins_collateral_value", "third_party_deposit_value"), _C07_BLOCK_CAP
    ),
    "0090": (),  # Formula 0050 + 0060 + 0070 + 0080
    # SideContext: the cross-sheet inflow, routed by corep/crm_substitution.py on
    # the guarantor's class. Without it the outflow (0090) is reported with no
    # matching inflow anywhere in the estate.
    "0100": _needs("post_crm_exposure_class_guaranteed", "guaranteed_portion"),
    "0110": (),  # Formula 0040 - 0090 + 0100
    "0120": (),  # constant 0.0
    "0130": _needs("collateral_adjusted_value"),
    "0140": _needs("collateral_market_value"),  # market - collateral_adjusted_value
    "0150": (),  # Formula max(0, 0110 - 0130)
    # CCF buckets: Sum(reporting_gross_off_bs) narrowed on the applied CCF and
    # (when derivable) the off-balance-sheet side.
    "0160": _CCF_BUCKET,
    "0170": _CCF_BUCKET,
    "0171": _CCF_BUCKET,  # Basel 3.1 only
    "0180": _CCF_BUCKET,
    "0190": _CCF_BUCKET,
    "0200": _needs("ead_final"),
    "0210": _needs("ead_final", "risk_type"),
    "0211": _needs("ead_final", "risk_type", "cp_entity_type"),
    "0215": _any_of("rwa_pre_factor"),  # CRR only
    "0216": _SF_SME_ADJUSTMENT,  # CRR only
    "0217": _SF_INFRA_ADJUSTMENT,  # CRR only
    "0220": _RWA,
    "0230": _needs("sa_cqs"),
    "0235": _needs("sa_cqs"),  # Basel 3.1 only
    "0240": (),  # structural null
}

#: C 08.01: column ref -> the ledger columns its binding reads.
_C08_01_CELLS: Mapping[str, CellRequirement] = {
    "0010": _needs("pd_floored", "ead_final"),  # CRR only; binds pd_floored by name
    "0020": _both(_ON_BS_GROSS, _OFF_BS_GROSS),
    "0030": _both(_ON_BS_GROSS, _OFF_BS_GROSS, _needs("cp_apply_fi_scalar")),
    "0035": _needs("on_bs_netting_amount"),  # Basel 3.1 only
    "0040": _both(_needs("guaranteed_portion", "protection_type"), _C08_BLOCK_CAP),
    "0050": _both(_needs("guaranteed_portion", "protection_type"), _C08_BLOCK_CAP),
    "0060": _both(_needs("reporting_ofcp_substitution"), _C08_BLOCK_CAP),
    # Sum(c08_prot_block) — the per-leg subtotal of 0040/0050/0060, so it is
    # populated by either limb; the guarantee limb is the one a legacy extract
    # realistically carries.
    "0070": _both(_any_of("guaranteed_portion", "reporting_ofcp_substitution"), _C08_BLOCK_CAP),
    "0080": _needs("post_crm_exposure_class_guaranteed", "guaranteed_portion"),
    "0090": (),  # Formula 0020 - 0035 - 0070 + 0080
    # postpass c08_off_bs_pre_ccf: the off-BS slice of the 0090 waterfall.
    "0100": _BS_SIDE,
    "0101": (),  # structural null
    "0102": (),  # structural null
    "0103": (),  # structural null
    "0104": (),  # postpass over 0090 / 0101 / 0102
    "0110": _needs("ead_final"),
    "0120": _both(_needs("ead_final"), _BS_SIDE),
    "0125": _both(_needs("ead_final"), _DEFAULTED),
    "0130": (),  # structural null
    "0140": _needs("ead_final", "cp_apply_fi_scalar"),
    "0150": (),  # constant 0.0 — the CRM-in-LGD twins are mutually exclusive
    "0160": (),  # constant 0.0 — with the substitution block above
    "0170": _any_of("reporting_ofcp_lgd_cash_deposit", "reporting_ofcp_lgd_life_insurance"),
    "0171": _needs("reporting_ofcp_lgd_cash_deposit"),
    "0172": _needs("reporting_ofcp_lgd_life_insurance"),
    "0173": (),  # constant 0.0 — no carrier for Art. 200(1)(c) instruments
    "0180": _needs("reporting_crm_lgd_financial"),
    "0190": _needs("reporting_crm_lgd_real_estate"),
    "0200": _needs("reporting_crm_lgd_other_physical"),
    "0210": _needs("reporting_crm_lgd_receivables"),
    "0220": _needs("double_default_unfunded_protection"),  # CRR only
    "0230": _both(_any_of("lgd_floored", "lgd_input"), _needs("ead_final")),
    "0240": _both(
        _any_of("lgd_floored", "lgd_input"),
        _needs("ead_final"),
        _needs("cp_apply_fi_scalar"),
    ),
    "0250": _needs("irb_maturity_m", "ead_final"),
    "0251": _needs("rwa_pre_adjustments"),  # Basel 3.1 only
    "0252": _needs("post_model_adjustment_rwa"),  # Basel 3.1 only
    "0253": _needs("mortgage_rw_floor_adjustment"),  # Basel 3.1 only
    "0254": _needs("unrecognised_exposure_adjustment"),  # Basel 3.1 only
    "0255": _needs("rwa_pre_factor"),  # CRR only
    "0256": _SF_SME_ADJUSTMENT,  # CRR only
    "0257": _SF_INFRA_ADJUSTMENT,  # CRR only
    "0260": _RWA,
    "0265": _both(_RWA, _DEFAULTED),  # Basel 3.1 only
    "0270": _both(_RWA, _needs("cp_apply_fi_scalar")),
    "0275": _needs("ead_final"),  # Basel 3.1 only
    "0276": _needs("sa_rwa"),  # Basel 3.1 only
    "0280": _any_of("el_pre_adjustment", "expected_loss"),
    "0281": _needs("post_model_adjustment_el"),  # Basel 3.1 only
    "0282": _any_of("el_after_adjustment", "expected_loss"),  # Basel 3.1 only
    # SafeSum(scra, gcra) with the provisions-ladder post-pass behind it.
    "0290": _PROVISIONS_C08,
    "0300": _needs("counterparty_reference"),  # DISTINCT count; falls back to a row count
    "0310": _RWA,
}

#: C 08.03: column ref -> the ledger columns its binding reads.
_C08_03_CELLS: Mapping[str, CellRequirement] = {
    "0010": _ON_BS_GROSS,
    "0020": _OFF_BS_GROSS,
    "0030": _both(_needs("ccf"), _OFF_BS_GROSS),  # the off-BS gross is the WEIGHT
    "0040": _needs("ead_final"),
    "0050": _both(_PD, _needs("ead_final")),
    "0060": _needs("counterparty_reference"),  # DISTINCT count; falls back to a row count
    "0070": _both(_any_of("lgd_floored", "lgd_input"), _needs("ead_final")),
    "0080": _needs("irb_maturity_m", "ead_final"),
    "0090": _RWA,
    "0100": _needs("expected_loss"),
    "0110": _PROVISIONS_C08,
}

# C 08.06: the bindings in ``corep.c08::_c08_06_spec``. Its predicates use the
# blocking sheet/row discriminators above; these requirements enumerate only the
# measure-specific inputs each published column reads.
_C08_06_CELLS: Mapping[str, CellRequirement] = {
    "0010": _both(_ON_BS_GROSS, _OFF_BS_GROSS),
    "0020": _both(_ON_BS_GROSS, _OFF_BS_GROSS),
    "0030": _OFF_BS_GROSS,
    "0031": (),  # Basel 3.1 structural null
    "0040": _needs("ead_final"),
    "0050": _both(_needs("ead_final"), _BS_SIDE),
    "0060": (),  # structural null
    "0070": _both(_needs("risk_weight"), _needs("ead_final")),
    "0080": _RWA,
    "0090": _needs("expected_loss"),
    "0100": _PROVISIONS_C08,
}

TEMPLATE_CELL_REQUIREMENTS: Mapping[str, Mapping[str, CellRequirement]] = {
    "c07_00": _C07_00_CELLS,
    "c08_01": _C08_01_CELLS,
    "c08_03": _C08_03_CELLS,
    "c08_06": _C08_06_CELLS,
}

#: Column ref -> the refs its value is DERIVED from: the ``Formula`` cells and the
#: post-execute passes that stand in for them.
#:
#: A formula cell has no carrier of its own, and treating that as "nothing to
#: report" was an under-report the leave-one-out sweep caught: dropping the
#: undrawn amount moved C 07.00 cols 0040 / 0110 / 0150 while coverage named col
#: 0010 alone, because those three are ``0010 - 0030``, ``0040 - 0090 + 0100`` and
#: ``max(0, 0110 - 0130)``. A formula is exactly as available as its inputs — and
#: an absent input reads as ZERO in the waterfall rather than as a null, so the
#: derived cell comes out confidently wrong rather than empty. The expansion is
#: transitive and framework-aware: a ref outside the regime column axis (CRR has
#: no col 0035) contributes nothing, because the formula never reads it.
TEMPLATE_FORMULA_INPUTS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "c07_00": {
        "0040": ("0010", "0030", "0035"),
        "0090": ("0050", "0060", "0070", "0080"),
        "0110": ("0040", "0090", "0100"),
        "0150": ("0110", "0130"),
    },
    "c08_01": {
        "0090": ("0020", "0035", "0070", "0080"),
        "0100": ("0090",),
        "0104": ("0090", "0101", "0102"),
    },
    "c08_03": {},
    "c08_06": {},
}

# The published column axis per template, so the coverage report walks the
# generator's own refs rather than a second copy of them that could drift.
_TEMPLATE_COLUMN_AXIS: Mapping[str, Callable[[str], tuple[str, ...]]] = {
    "c07_00": lambda framework: tuple(col.ref for col in get_c07_columns(framework)),
    "c08_01": lambda framework: tuple(col.ref for col in get_c08_columns(framework)),
    "c08_03": lambda framework: tuple(col.ref for col in get_c08_03_columns(framework)),
    "c08_06": lambda framework: tuple(col.ref for col in get_c08_06_columns(framework)),
}


# =============================================================================
# Results
# =============================================================================


@dataclass(frozen=True)
class LedgerCoverage:
    """Which ledger columns the mapping could supply, and what that costs.

    Attributes:
        supplied: Sealed reporting-ledger column names the projection emitted.
        missing: Ledger columns the scoped templates read that the mapping could
            NOT supply. Scoped to what the templates actually ask for — a column
            no template reads is neither supplied nor missing.
        unavailable_cells: Template id -> the column refs that cannot be
            populated from this mapping, each as ``"<ref>: needs <columns>"``.
            The reason is carried in the string so a reachability panel can show
            "map ``specific_provisions`` to unlock C 08.03 column 0110" without a
            second lookup; ``unavailable_refs`` returns the bare refs.
        reachable_templates: The scoped templates THE MAPPING can produce —
            required columns supplied, and no unmapped approach label standing in
            the way. Reachable is a statement about the MAPPING, never about the
            book: an all-standardised extract leaves C 08.01 reachable, because
            nothing about the mapping prevents it. A template outside this set
            emits nothing and the cause is always actionable — see
            ``blocking_columns`` and ``blocking_labels``.
        populated_templates: The scoped templates THIS BOOK actually contains
            rows for. ``None`` when the vocabulary was not measured. Reachable
            and populated are INDEPENDENT facts and conflating them is a known
            trap in this codebase — ``sheet_not_emitted`` conflated "no exposure"
            (not fixable, not a defect) with "no bundle key" (a real gap), and
            the give-away is an unreachable template with nothing named to fix.
            The three user-facing states are: unreachable with blocking COLUMNS
            (map these columns); unreachable with blocking LABELS (add these
            value_map entries); reachable but unpopulated (your book has no such
            exposures — nothing to fix).
        unmapped_labels: Mapping name (a ``[components.*]`` / ``[carriers.*]``
            table key) -> the distinct values that survived canonicalisation
            without matching the engine vocabulary, as ``"<value> (<n> rows)"``,
            commonest first. A label that decides a sheet, a population or a
            column split cannot be allowed to pass through silently: an unmapped
            CLASS produces bogus sheets, and an unmapped APPROACH empties every
            template. Empty when every label matched, and when no vocabulary
            column was supplied.
        present_approaches: The distinct ``reporting_approach_origin`` values the
            extract actually carries, or ``None`` when the vocabulary was not
            measured (the pre-flight ``ledger_coverage`` form, which has no data).
            ``None`` makes reachability column-only and therefore OPTIMISTIC —
            the projection always measures it.
    """

    supplied: frozenset[str]
    missing: frozenset[str]
    unavailable_cells: Mapping[str, tuple[str, ...]]
    reachable_templates: frozenset[str]
    unmapped_labels: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    present_approaches: frozenset[str] | None = None
    populated_templates: frozenset[str] | None = None

    def unavailable_refs(self, template_id: str) -> tuple[str, ...]:
        """The bare column refs of ``template_id`` that cannot be populated."""
        return tuple(
            entry.split(":", 1)[0] for entry in self.unavailable_cells.get(template_id, ())
        )

    def blocking_columns(self, template_id: str) -> tuple[str, ...]:
        """The unmet columns that stop ``template_id`` being produced AT ALL.

        Empty exactly when the template is reachable. This is not the same
        question as ``unavailable_refs``: an unavailable COLUMN leaves a cell
        blank on a template that still generates, whereas a blocking column
        means no sheet is emitted for any exposure class — and for C 08.03 the
        blocking column is its PD, which is the ROW AXIS itself
        (``LEDGER_ROW_AXIS_FATAL``). A compare surface must render the two
        differently: a missing template is not a template of zeroes.
        """
        return tuple(sorted(_unmet_columns(TEMPLATE_REQUIRED_COLUMNS[template_id], self.supplied)))

    def row_axis_deleted(self, template_id: str) -> bool:
        """Is ``template_id`` unproducible because its ROW AXIS has no source?"""
        requirement = LEDGER_ROW_AXIS_FATAL.get(template_id)
        return requirement is not None and not _satisfied(requirement, self.supplied)

    def unavailable_rows(self, template_id: str, framework: str) -> tuple[str, ...]:
        """The row refs of ``template_id`` whose ROW AXIS this mapping cannot key.

        Silencing a row silences every column on it, which is a way a cell can
        change without the change meaning anything — so it has to be reportable
        alongside ``unavailable_refs``. A data-driven axis contributes nothing
        here and is covered by ``row_axis_deleted`` instead.
        """
        refs: set[str] = set()
        for axis in LEDGER_ROW_AXIS[template_id]:
            if not _satisfied(axis.requirement, self.supplied):
                refs |= set(axis.refs(framework))
        return tuple(sorted(refs))

    def blocking_labels(self, template_id: str) -> tuple[str, ...]:
        """The approach labels the extract carries that ``template_id`` refuses.

        The vocabulary twin of ``blocking_columns``, and the actionable half of
        the answer: the column is there, the values in it are not the ones this
        template's population filter admits. Empty when the template is
        reachable, when it is blocked by a missing COLUMN instead (a different
        fix), or when the vocabulary was not measured.
        """
        if self.present_approaches is None or template_id in self.reachable_templates:
            return ()
        if not _satisfied(TEMPLATE_REQUIRED_COLUMNS[template_id], self.supplied):
            return ()
        return tuple(sorted(self.present_approaches - TEMPLATE_POPULATION_LABELS[template_id]))


@dataclass(frozen=True)
class LegacyLedgerSource:
    """The firm's exposure extract in our sealed reporting-ledger vocabulary.

    Structurally a ``reporting.metadata.ResultsSource``, so it is a valid
    argument to ``COREPGenerator().generate(...)`` and to anything else that
    takes a results source — which is the whole point: their templates are
    generated by the identical code path as ours.

    Attributes:
        framework: ``"CRR"`` or ``"BASEL_3_1"`` — the regime whose template
            variants their return is being compared on.
        ledger: The projected frame. Carries ONLY the columns the mapping
            supplied; an unsupplied carrier is absent, never a null column
            (see the module docstring).
    """

    framework: str
    ledger: pl.LazyFrame

    def scan_results(self) -> pl.LazyFrame:
        """The projected ledger frame (the ``ResultsSource`` contract)."""
        return self.ledger


# =============================================================================
# Main entry point
# =============================================================================


def project_legacy_ledger(
    legacy: pl.LazyFrame,
    mapping: LegacyColumnMapping,
    *,
    framework: str,
) -> tuple[LegacyLedgerSource, LedgerCoverage]:
    """Project a loaded legacy extract onto the sealed reporting-ledger columns.

    ``legacy`` is what ``api.reconciliation.LegacyOutputLoader.load()`` returns:
    the declared join keys under their LEGACY names, plus one
    ``legacy_<component>`` column per mapped component and one
    ``legacy_<carrier>`` column per mapped carrier. Columns the file did not
    carry are already absent from it, so an unmapped and an unfound column are
    the same thing here — both simply do not reach the ledger.

    Args:
        legacy: The loaded extract (see above).
        mapping: The same mapping the loader was given. Read for its key
            alignment, its components' ledger targets and value maps, and its
            optional carriers.
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    ONE MATERIALISATION PASS, AND IT IS DELIBERATE. The projection itself is
    lazy — ``scan_results()`` returns an unexecuted ``LazyFrame`` — but the label
    measurement cannot be: whether a value matches the engine vocabulary is a
    question about DATA, and reporting an unmapped label (or a reachability that
    accounts for one) is impossible without reading it. The cost is a single
    ``pl.collect_all`` over one ``group_by`` per vocabulary column — four
    single-column plans, projection-pushed, so it reads four String columns and
    nothing else.

    Note for anyone auditing laziness: ``tests/unit/api/test_service_reconcile_ledger.py``
    spies ``pl.LazyFrame.collect`` and so does NOT observe this pass. It is
    counted here rather than hidden.

    Returns:
        The projected source and its coverage report.

    Raises:
        ValueError: If ``framework`` is not one of ``FRAMEWORKS`` (a programming
            error — the caller chose the regime, it is not data).
    """
    if framework not in FRAMEWORKS:
        raise ValueError(f"framework must be one of {FRAMEWORKS}, got {framework!r}")

    cols = set(legacy.collect_schema().names())
    exprs, supplied = _projection_exprs(mapping, cols)
    ledger = legacy.select(exprs) if exprs else pl.LazyFrame()
    # The vocabulary is measured on the PROJECTED frame, after canonicalisation,
    # because that is the only place the question can be asked: a value that
    # survives casefolding and the value_map without matching the engine's
    # vocabulary is one nothing downstream will ever match either.
    unmapped_labels, present_approaches = _label_facts(ledger, supplied)
    coverage = ledger_coverage(
        supplied,
        framework=framework,
        present_approaches=present_approaches,
        unmapped_labels=unmapped_labels,
    )
    logger.info(
        "legacy ledger projection: %d ledger columns supplied, %d missing, "
        "%d of %d scoped templates reachable, %d label(s) unmapped",
        len(coverage.supplied),
        len(coverage.missing),
        len(coverage.reachable_templates),
        len(LEDGER_TEMPLATE_IDS),
        len(coverage.unmapped_labels),
    )
    return LegacyLedgerSource(framework=framework, ledger=ledger), coverage


def ledger_coverage(
    supplied: set[str] | frozenset[str],
    *,
    framework: str,
    present_approaches: frozenset[str] | None = None,
    unmapped_labels: Mapping[str, tuple[str, ...]] | None = None,
) -> LedgerCoverage:
    """Score a set of supplied ledger columns against the scoped templates.

    Split out from ``project_legacy_ledger`` so a UI can answer "what would this
    mapping unlock?" before any file is read — the reachability panel the plan
    asks to show BEFORE the compare runs.

    ``present_approaches`` is the vocabulary half of that question and can only be
    answered against data. Passing ``None`` (the pre-flight form) scores
    reachability on column presence ALONE, which is optimistic: a mapping can
    supply every required column and still produce nothing, because every row's
    approach label falls outside the population filter. ``project_legacy_ledger``
    always measures it, so the reported reachability there is the truth.
    """
    supplied = frozenset(supplied)
    unavailable: dict[str, tuple[str, ...]] = {}
    missing: set[str] = set()
    reachable: set[str] = set()

    for template_id in LEDGER_TEMPLATE_IDS:
        required = TEMPLATE_REQUIRED_COLUMNS[template_id]
        if _satisfied(required, supplied) and _vocabulary_permits(
            template_id, present_approaches, unmapped_labels or {}
        ):
            reachable.add(template_id)
        missing |= _unmet_columns(required, supplied)

        column_refs = _TEMPLATE_COLUMN_AXIS[template_id](framework)
        cells = _effective_requirements(template_id, column_refs)
        entries: list[str] = []
        for ref in column_refs:
            requirement = cells[ref]
            if not requirement or _satisfied(requirement, supplied):
                continue
            unmet = _unmet_columns(requirement, supplied)
            missing |= unmet
            entries.append(f"{ref}: needs {', '.join(sorted(unmet))}")
        if entries:
            unavailable[template_id] = tuple(entries)

        for axis in LEDGER_ROW_AXIS[template_id]:
            missing |= _unmet_columns(axis.requirement, supplied)

    coverage = LedgerCoverage(
        supplied=supplied,
        missing=frozenset(missing),
        unavailable_cells=unavailable,
        reachable_templates=frozenset(reachable),
        unmapped_labels=dict(unmapped_labels or {}),
        present_approaches=present_approaches,
        populated_templates=_populated(present_approaches),
    )
    _warn_unmapped_labels(coverage)
    _warn_unreachable(coverage)
    return coverage


def _effective_requirements(
    template_id: str, column_refs: tuple[str, ...]
) -> dict[str, CellRequirement]:
    """Each column's requirement with its FORMULA inputs folded in, transitively.

    A ``Formula`` cell is as available as the cells it derives from, and an
    unavailable input reads as ZERO in the waterfall rather than as a null — so
    the derived cell comes out confidently wrong, not empty. Inputs outside this
    framework's column axis are skipped: the formula never reads them (CRR has no
    C 07.00 col 0035, so its col 0040 does not depend on the netting amount).
    """
    base = TEMPLATE_CELL_REQUIREMENTS[template_id]
    inputs = TEMPLATE_FORMULA_INPUTS.get(template_id, {})
    present = set(column_refs)
    resolved: dict[str, CellRequirement] = {}

    def resolve(ref: str, seen: frozenset[str]) -> CellRequirement:
        if ref in resolved:
            return resolved[ref]
        if ref in seen:  # a cycle would be a table bug; degrade rather than hang
            return ()
        parts = [base.get(ref, ())]
        parts.extend(
            resolve(source, seen | {ref}) for source in inputs.get(ref, ()) if source in present
        )
        requirement = _both(*parts)
        resolved[ref] = requirement
        return requirement

    return {ref: resolve(ref, frozenset()) for ref in column_refs}


def _vocabulary_permits(
    template_id: str,
    present_approaches: frozenset[str] | None,
    unmapped_labels: Mapping[str, tuple[str, ...]],
) -> bool:
    """Is the MAPPING capable of producing this template's population?

    Not "does the book contain it" — that is ``_populated``, and conflating the
    two produces an unreachable template with nothing to fix, which a user cannot
    act on. A recognised approach that admits the template settles it. Where none
    does, the answer turns on WHY: if every label was recognised, the book simply
    has no such exposures and the mapping is fine; if some label was NOT
    recognised, one of them might have been the missing population, and that is a
    mapping defect the analyst can fix.
    """
    if template_id == "c08_06" and _SLOTTING_PLACEMENT_MAPPINGS & unmapped_labels.keys():
        return False
    if present_approaches is None:
        return True
    if present_approaches & TEMPLATE_POPULATION_LABELS[template_id]:
        return True
    return _APPROACH_MAPPING not in unmapped_labels


def _populated(present_approaches: frozenset[str] | None) -> frozenset[str] | None:
    """The templates whose population this BOOK actually carries rows for."""
    if present_approaches is None:
        return None
    return frozenset(
        template_id
        for template_id in LEDGER_TEMPLATE_IDS
        if present_approaches & TEMPLATE_POPULATION_LABELS[template_id]
    )


def _warn_unmapped_labels(coverage: LedgerCoverage) -> None:
    """Log every label that matched no engine vocabulary, naming the TOML key.

    Silence here is the failure mode this exists to remove: an unrecognised label
    neither raises nor matches, so it partitions into a sheet no template has, or
    empties a population, with nothing to read.
    """
    for mapping_name, values in coverage.unmapped_labels.items():
        logger.warning(
            "legacy ledger projection: [%s] carries %d value(s) that match no engine "
            "vocabulary and will be silently dropped by every predicate that reads them: "
            "%s. Add them to that mapping's value_map",
            mapping_name,
            len(values),
            ", ".join(values),
        )


def _warn_unreachable(coverage: LedgerCoverage) -> None:
    """Log every unproducible template, separating the THREE failure modes.

    A missing template is not a template of zeroes. The row-axis case is louder
    still — on C 08.03 an unmapped PD deletes the sheet rather than emptying a
    cell (``LEDGER_ROW_AXIS_FATAL``) — and the vocabulary case is the one that
    used to be invisible: every required column present, and not one row whose
    approach label the population filter admits.
    """
    for template_id in LEDGER_TEMPLATE_IDS:
        if template_id in coverage.reachable_templates:
            continue
        if coverage.row_axis_deleted(template_id):
            logger.warning(
                "legacy ledger projection: %s cannot be produced — its ROW AXIS has no "
                "source (needs one of %s). No sheet will be emitted for any exposure "
                "class; this is not a template of zeroes",
                template_id,
                ", ".join(sorted(LEDGER_ROW_AXIS_FATAL[template_id][0])),
            )
            continue
        blocking = coverage.blocking_columns(template_id)
        if blocking:
            logger.warning(
                "legacy ledger projection: %s cannot be produced — missing %s",
                template_id,
                ", ".join(blocking),
            )
            continue
        placement = sorted(_SLOTTING_PLACEMENT_MAPPINGS & coverage.unmapped_labels.keys())
        if template_id == "c08_06" and placement:
            logger.warning(
                "legacy ledger projection: %s cannot be produced safely — invalid or null "
                "slotting placement values in %s. Fix those [carriers.*] mappings or source "
                "values; otherwise sheets or category/maturity rows can silently disappear",
                template_id,
                ", ".join(placement),
            )
            continue
        logger.warning(
            "legacy ledger projection: %s cannot be produced — every required column is "
            "present, but no row carries an approach its population admits and some "
            "approach labels were not recognised. Seen: %s; needs one of: %s. Map those "
            "values in [components.approach] value_map",
            template_id,
            ", ".join(coverage.blocking_labels(template_id)) or "(no approach labels at all)",
            ", ".join(sorted(TEMPLATE_POPULATION_LABELS[template_id])),
        )
    # The third state, and the one that is NOT a defect: the mapping is complete
    # and this book simply has no exposures of that population. Logged at INFO,
    # not WARNING, because there is nothing for anyone to fix.
    if coverage.populated_templates is None:
        return
    for template_id in sorted(coverage.reachable_templates - coverage.populated_templates):
        logger.info(
            "legacy ledger projection: %s is reachable but the extract carries no %s "
            "exposures, so it emits no sheet. Nothing to map",
            template_id,
            " / ".join(sorted(TEMPLATE_POPULATION_LABELS[template_id])),
        )


# =============================================================================
# Private helpers
# =============================================================================


def _label_facts(
    ledger: pl.LazyFrame, supplied: set[str]
) -> tuple[dict[str, tuple[str, ...]], frozenset[str]]:
    """Measure the projected LABEL columns: what is unmapped, what approaches exist.

    One scan per vocabulary column, batched through ``collect_all`` so the whole
    measurement is a single pass over the extract rather than one per column.
    Nulls are excluded — an absent value is a coverage question, not a vocabulary
    one, and it is already answered by the missing-column report.
    """
    columns = [column for column in LEDGER_VOCABULARY if column in supplied]
    if not columns:
        return {}, frozenset()
    value_plans = [
        ledger.select(pl.col(column).alias("value")).drop_nulls().group_by("value").len()
        for column in columns
    ]
    slotting_discriminators = [
        column
        for column in ("sl_type", "slotting_category", "is_short_maturity", "is_hvcre")
        if column in supplied
        and _APPROACH_COLUMN in supplied
        and (column != "is_hvcre" or "sl_type" in supplied)
    ]
    null_plans: list[pl.LazyFrame] = []
    for column in slotting_discriminators:
        relevant = pl.col(_APPROACH_COLUMN) == ApproachType.SLOTTING.value
        if column == "is_hvcre":
            # The optional flag only refines IPRE/HVCRE routing. A blank flag on
            # project/object/commodities finance cannot change its sheet, while
            # a bad explicit token on IPRE could silently hide HVCRE exposure.
            relevant &= pl.col("sl_type").is_in(["ipre", "hvcre"])
        null_plans.append(
            ledger.filter(relevant).select(pl.col(column).is_null().sum().alias("null_count"))
        )
    frames = pl.collect_all([*value_plans, *null_plans])
    counts = frames[: len(value_plans)]
    unmapped: dict[str, tuple[str, ...]] = {}
    present_approaches: frozenset[str] = frozenset()
    for column, frame in zip(columns, counts, strict=True):
        vocabulary = LEDGER_VOCABULARY[column]
        if column == _APPROACH_COLUMN:
            present_approaches = frozenset(frame["value"].to_list())
        outside = [row for row in frame.iter_rows() if row[0] not in vocabulary.values]
        if not outside:
            continue
        # Commonest first: the value costing the most rows is the one to map.
        outside.sort(key=lambda row: (-row[1], row[0]))
        unmapped[vocabulary.mapping_name] = tuple(
            f"{value} ({count} rows)" for value, count in outside
        )
    for column, frame in zip(slotting_discriminators, frames[len(value_plans) :], strict=True):
        null_count = int(frame["null_count"][0])
        if null_count == 0:
            continue
        mapping_name = (
            LEDGER_VOCABULARY[column].mapping_name if column in LEDGER_VOCABULARY else column
        )
        unmapped[mapping_name] = (
            *unmapped.get(mapping_name, ()),
            f"<null or invalid> ({null_count} rows)",
        )
    return unmapped, present_approaches


def _projection_exprs(
    mapping: LegacyColumnMapping, cols: set[str]
) -> tuple[list[pl.Expr], set[str]]:
    """The rename/cast expressions, and the ledger columns they supply."""
    exprs: list[pl.Expr] = []
    supplied: set[str] = set()

    def emit(expr: pl.Expr, target: str, source: str) -> None:
        if target in supplied:
            logger.warning(
                "legacy ledger projection: %r already supplied; %r ignored", target, source
            )
            return
        exprs.append(expr)
        supplied.add(target)

    # The join keys, positionally aligned: ``our_keys`` names OUR frame's
    # columns, which ARE ledger columns, so the existing grammar already says
    # where a key belongs. ``exposure_reference`` (the default) is what
    # ``c07_population`` dedupes on and what the obligor-count cells fall back to.
    for legacy_key, our_key in zip(mapping.legacy_keys, mapping.our_keys, strict=False):
        if legacy_key not in cols:
            logger.warning("legacy ledger projection: join key %r absent from extract", legacy_key)
            continue
        emit(pl.col(legacy_key).alias(our_key), our_key, legacy_key)

    for name, component_mapping in mapping.components.items():
        source = f"legacy_{name}"
        if source not in cols:
            logger.debug("legacy ledger projection: component %r absent from extract", name)
            continue
        spec = RECONCILABLE_COMPONENTS_BY_NAME[name]
        value = _component_value(source, spec, component_mapping.value_map)
        for target in _ledger_targets(spec):
            emit(value.alias(target), target, source)

    for name, carrier_mapping in mapping.carriers.items():
        source = f"legacy_{name}"
        if source not in cols:
            logger.debug("legacy ledger projection: carrier %r absent from extract", name)
            continue
        carrier = LEDGER_CARRIERS_BY_NAME[name]
        emit(
            _carrier_value(source, carrier, carrier_mapping),
            carrier.ledger_column,
            source,
        )

    # HVCRE is a distinct C 08.06 sheet under Basel 3.1 and folds into IPRE
    # under CRR. A canonical sl_type contains enough information to derive the
    # flag when the extract does not carry one. An explicit mapping has already
    # supplied the target above and therefore wins.
    sl_mapping = mapping.carriers.get("sl_type")
    sl_source = "legacy_sl_type"
    if sl_mapping is not None and sl_source in cols and "is_hvcre" not in supplied:
        sl_carrier = LEDGER_CARRIERS_BY_NAME["sl_type"]
        canonical_sl_type = _carrier_value(sl_source, sl_carrier, sl_mapping)
        emit((canonical_sl_type == "hvcre").alias("is_hvcre"), "is_hvcre", sl_source)

    # A numeric maturity is an optional alternative to the direct band flag.
    # Direct mapping wins; otherwise the regulatory boundary is strict: <2.5
    # years is short, exactly 2.5 is long. Invalid numeric tokens cast to null
    # and the data-aware coverage check below blocks the template.
    maturity_mapping = mapping.carriers.get("remaining_maturity_years")
    maturity_source = "legacy_remaining_maturity_years"
    if (
        maturity_mapping is not None
        and maturity_source in cols
        and "is_short_maturity" not in supplied
    ):
        maturity_carrier = LEDGER_CARRIERS_BY_NAME["remaining_maturity_years"]
        maturity = _carrier_value(maturity_source, maturity_carrier, maturity_mapping)
        emit((maturity < 2.5).alias("is_short_maturity"), "is_short_maturity", maturity_source)
    return exprs, supplied


def _ledger_targets(spec: ReconcilableComponent) -> tuple[str, ...]:
    """The sealed ledger column(s) one component's value is written to.

    One target per component — the head of its ``our_columns`` preference order,
    which is the SEALED name our own side resolves to — except for the two
    entries of ``MULTI_TARGET_COMPONENTS``, each of which is a recorded decision
    in the module docstring.
    """
    targets = MULTI_TARGET_COMPONENTS.get(spec.name)
    if targets is not None:
        return targets
    return (spec.our_columns[0],)


def _component_value(
    source: str, spec: ReconcilableComponent, value_map: dict[str, str]
) -> pl.Expr:
    """One component's ledger value: the loaded column, canonicalised if a label.

    Numeric components arrive already scaled and unit-converted by the loader, so
    there is nothing left to do to them. Categorical ones arrive RAW — the loader
    is mechanical and ``analysis.reconciliation`` applies the ``value_map`` at
    comparison time — so the canonicalisation happens here instead, in the same
    casefold-strip-then-replace form that module uses. It has to: a sheet key of
    ``"CORP"`` partitions into a sheet no template has.
    """
    if spec.kind != "categorical":
        return pl.col(source)
    return _canonical_label(pl.col(source), value_map)


def _carrier_value(source: str, carrier: LedgerCarrier, carrier_mapping: CarrierMapping) -> pl.Expr:
    """One carrier's ledger value — a canonical label, or a parsed flag.

    An unrecognised flag token is NULL, never False. The C 07.00 / C 08.01
    defaulted ladders read ``is_defaulted`` with ``fill_null(False)``, so a null
    behaves as "not defaulted" for row membership — but it stays visibly unknown
    to everything that inspects the frame, and filling it here would make the
    guess indistinguishable from a supplied value.

    Unlike a categorical COMPONENT, a carrier label is NOT casefolded. The
    component targets (``reporting_class_origin`` / ``reporting_approach_origin``)
    are lowercase-canonical, but a carrier targets whatever vocabulary the engine
    column already speaks, and a casefold that happened not to match would fail
    silently rather than loudly.
    """
    label = _carrier_label(pl.col(source), carrier_mapping.value_map)
    if carrier.kind == "numeric":
        return label.cast(pl.Float64, strict=False).alias(carrier.ledger_column)
    if carrier.kind != "boolean":
        return label.alias(carrier.ledger_column)
    token = label.str.to_lowercase()
    return (
        pl.when(token.is_in(list(_TRUE_TOKENS)))
        .then(pl.lit(value=True))
        .when(token.is_in(list(_FALSE_TOKENS)))
        .then(pl.lit(value=False))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
        .alias(carrier.ledger_column)
    )


def _canonical_label(expr: pl.Expr, value_map: dict[str, str]) -> pl.Expr:
    """Casefold + strip, then apply legacy→canonical synonyms.

    Mirrors ``analysis.reconciliation``'s ``_normalise`` / ``_apply_value_map``
    pair term for term, so a label that reconciles as equal on the exposure-grain
    view keys the same sheet on the template view.
    """
    normalised = expr.cast(pl.String).str.strip_chars().str.to_lowercase()
    if not value_map:
        return normalised
    return normalised.replace({k.strip().lower(): v.strip().lower() for k, v in value_map.items()})


def _carrier_label(expr: pl.Expr, value_map: dict[str, str]) -> pl.Expr:
    """Strip, then apply legacy→canonical synonyms with the VALUE kept verbatim.

    Keys still match case-insensitively (a firm writing ``"Off"`` and ``"OFF"``
    should not need two entries), but an unmapped value passes through with its
    own case intact and a mapped one lands exactly as written — because the
    target vocabularies here are the engine's, and they are case-sensitive.
    """
    stripped = expr.cast(pl.String).str.strip_chars()
    if not value_map:
        return stripped
    norm_map = {key.strip().lower(): value for key, value in value_map.items()}
    lowered = stripped.str.to_lowercase()
    return (
        pl.when(lowered.is_in(list(norm_map))).then(lowered.replace(norm_map)).otherwise(stripped)
    )


def _satisfied(requirement: CellRequirement, supplied: frozenset[str]) -> bool:
    """Is ANY alternative of ``requirement`` fully supplied? (Empty = yes.)"""
    return not requirement or any(alternative <= supplied for alternative in requirement)


def _unmet_columns(requirement: CellRequirement, supplied: frozenset[str]) -> set[str]:
    """The unmet OR-groups' columns, narrowed to what a mapping could supply.

    Every alternative is reported, not just the cheapest one: each is a genuine
    way to unlock the cell, and naming only one would hide the route an analyst
    can actually take (the off-balance-sheet gross is reachable through the
    sealed carrier OR through ``nominal_amount`` + ``undrawn_amount``).

    An alternative lists every rung the GENERATOR reads, synthetic-frame-only
    rungs included, because documenting the ladder is what the table is for. The
    report has a different job — telling an analyst what to map — so each
    shortfall is narrowed to its PROJECTABLE members, falling back to the whole
    shortfall when none of it can be mapped, because "this cell cannot be
    supplied through the grammar" is itself the finding (C 07.00 col 0020's
    ``own_funds_deduction_amount`` is the standing example).
    """
    if _satisfied(requirement, supplied):
        return set()
    shortfall: set[str] = set()
    for alternative in requirement:
        shortfall |= alternative - supplied
    # Narrow ACROSS the alternatives, not within each: the provisions ladder has
    # one unsealed rung per alternative, so a per-alternative narrowing would
    # find nothing projectable in any of them and fall back to naming all four.
    return shortfall & PROJECTABLE_LEDGER_COLUMNS or shortfall
