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

THE PROJECTION CALCULATES NOTHING. It renames and types. It does not derive a
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
AND ``provision_allocated``, never on SCRA/GCRA. All three provisions cells in
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
- Reg (EU) 2021/451 Annex II: C 07.00, C 08.01, C 08.03
- PRA PS1/26 Annex I/II: OF 07.00, OF 08.01, OF 08.03
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.analysis.recon_registry import (
    LEDGER_CARRIERS_BY_NAME,
    RECONCILABLE_COMPONENTS_BY_NAME,
)
from rwa_calc.reporting.corep.templates import (
    get_c07_columns,
    get_c08_03_columns,
    get_c08_columns,
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
LEDGER_TEMPLATE_IDS: tuple[str, ...] = ("c07_00", "c08_01", "c08_03")

#: A cell requirement: a CONJUNCTION of OR-groups. The cell is populatable when
#: every group has at least one supplied member. ``()`` = no carrier of its own
#: (a constant, a ``Formula`` over other cells, or a post-execute pass that
#: derives from cells already listed).
type CellRequirement = tuple[tuple[str, ...], ...]

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

# Flag tokens for a ``kind="boolean"`` carrier. Anything else is NULL, never
# False: "we do not know" and "not defaulted" are different statements, and the
# defaulted ladders in C 07.00 / C 08.01 read the difference.
_TRUE_TOKENS: frozenset[str] = frozenset({"true", "t", "y", "yes", "1"})
_FALSE_TOKENS: frozenset[str] = frozenset({"false", "f", "n", "no", "0"})


def _all(*names: str) -> CellRequirement:
    """Every named column is needed (a conjunction of single-member groups)."""
    return tuple((name,) for name in names)


def _any_of(*names: str) -> CellRequirement:
    """Any one of the named columns is enough (one OR-group)."""
    return ((names),)


# The two gross-exposure OR-groups. EITHER the sealed per-side carrier (mapped
# directly through the ``gross_*_balance_sheet`` override components) OR a raw
# amount the generator can derive it from — ``ensure_gross_side_carriers`` runs
# at generator entry whenever the sealed column is absent and applies the
# aggregator's own rule to drawn/interest (on-side) and nominal/undrawn (off).
_ON_BS_GROSS: CellRequirement = (("reporting_gross_on_bs", "drawn_amount", "interest"),)
_OFF_BS_GROSS: CellRequirement = (("reporting_gross_off_bs", "nominal_amount", "undrawn_amount"),)

# The provisions ladder, as the generators actually traverse it. The SCRA/GCRA
# rungs are listed because they are what the cell checks first, but nothing
# targets them: they are not sealed, so our side always lands on the fallback
# (``provision_deducted`` on C 07.00, ``provision_allocated`` on C 08.01/03).
_PROVISIONS_C07: CellRequirement = (
    ("scra_provision_amount", "gcra_provision_amount", "provision_deducted"),
)
_PROVISIONS_C08: CellRequirement = (
    (
        "scra_provision_amount",
        "gcra_provision_amount",
        "provision_held",
        "provision_allocated",
    ),
)

# The balance-sheet side. ``bs_type`` is the first rung and is NOT sealed, so
# the real ledger always resolves to ``exposure_type`` — which is why that is
# the carrier the registry offers.
_BS_SIDE: CellRequirement = (("bs_type", "exposure_type"),)

# The defaulted ladder, in the generators' own precedence order. ``is_defaulted``
# is the sealed rung; ``default_status`` is synthetic-frame-only; the class and
# PD rungs are last-resort proxies that state something DIFFERENT.
_DEFAULTED: CellRequirement = (
    ("is_defaulted", "default_status", "exposure_class_applied", "exposure_class", "pd_floored"),
)

# The C 07.00 CCF-bucket cells (0160-0190): the applied conversion factor picks
# the bucket, the off-balance-sheet gross is what the bucket sums.
# ``ccf_applied`` is the second rung of the C 07.00 carrier ladder (synthetic
# unit frames spell it that way); ``ccf`` is what the pipeline seals, and it is
# what C 08.03 col 0030 binds BY NAME with no ladder at all.
_CCF_BUCKET: CellRequirement = (("ccf", "ccf_applied"), _OFF_BS_GROSS[0])

# The supporting-factor RWEA adjustments (C 07.00 cols 0216/0217, C 08.01 cols
# 0256/0257): sigma(rwa_pre_factor - rwa_final) over the rows the factor was
# applied to. ``_sf_adjustment_cell`` prefers the factor's own dedicated flag
# and falls back to the generic ``supporting_factor_applied`` alongside the
# is_sme / is_infrastructure discriminator — approximated here as the OR of the
# two flags, because the fallback rung is a conjunction the group form cannot
# express and over-reporting availability is the wrong way to be wrong.
_SF_SME_ADJUSTMENT: CellRequirement = (
    ("rwa_pre_factor",),
    ("sme_supporting_factor_applied", "supporting_factor_applied"),
)
_SF_INFRA_ADJUSTMENT: CellRequirement = (
    ("rwa_pre_factor",),
    ("infrastructure_factor_applied", "supporting_factor_applied"),
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
TEMPLATE_REQUIRED_COLUMNS: Mapping[str, CellRequirement] = {
    # c07_plans / c08_01_plans / c08_03_plans each pick() these three and append
    # an error when one is absent; population_flags() keys the approach column
    # and returns an EMPTY population when it is missing (never a pass-through).
    "c07_00": (
        ("reporting_class_origin",),
        ("reporting_approach_origin",),
        ("ead_final",),
        ("rwa_final", "rwa_post_factor", "rwa"),
    ),
    "c08_01": (
        ("reporting_class_origin",),
        ("reporting_approach_origin",),
        ("ead_final",),
        ("rwa_final", "rwa_post_factor", "rwa"),
    ),
    # C 08.03 additionally needs a PD: _pd_alloc_col() returning None records
    # "No PD column available — skipping PD range breakdown" and emits no sheets.
    "c08_03": (
        ("reporting_class_origin",),
        ("reporting_approach_origin",),
        ("ead_final",),
        ("rwa_final", "rwa_post_factor", "rwa"),
        ("pd_floored", "pd"),
    ),
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
    "c08_03": (("pd_floored", "pd"),),
}

#: Row-axis dependencies: columns that decide WHICH ROWS a sheet emits rather
#: than what a column reports. Published for the reachability panel — a mapping
#: can populate every column of C 07.00 and still emit only its Total row.
LEDGER_ROW_AXIS_COLUMNS: Mapping[str, Mapping[str, CellRequirement]] = {
    "c07_00": {
        "0015 / 0290-0320 defaulted rows": _DEFAULTED,
        "0020 / RE SME 'of which' rows": _any_of(
            "sme_supporting_factor_eligible", "exposure_class"
        ),
        "0021-0023 specialised lending": _all("sl_type"),
        "0024-0026 project-finance phases": _all("sl_type", "sl_project_phase"),
        "0030 / 0035 supporting-factor rows": _any_of("is_sme", "is_infrastructure"),
        "0050 / 0060 permanent partial use": _all("ppu_reason"),
        "0070 / 0080 on/off balance sheet": _BS_SIDE,
        "0090 / 0110 counterparty credit risk": _all("risk_type"),
        "0100 / 0120 QCCP-cleared 'of which'": _all("risk_type", "cp_entity_type", "cp_is_qccp"),
        "risk-weight band rows (section 2)": _all("risk_weight"),
        "0281-0283 CIU rows": _all("ciu_approach"),
        "0330-0344 real-estate rows": (
            ("property_type",),
            ("materially_dependent_on_property", "has_income_cover", "is_income_producing"),
        ),
        "0350-0354 non-qualifying real estate": _all("is_qualifying_re"),
        "0360 ADC row": _all("is_adc"),
        "0371-0374 equity transitional rows": _all(
            "equity_transitional_approach", "equity_higher_risk"
        ),
        "0380 currency-mismatch row": _all("currency_mismatch_multiplier_applied"),
    },
    "c08_01": {
        "0020 / 0030 on/off balance sheet": _BS_SIDE,
        "0070 / 0080 graded vs slotting": _all("reporting_approach_origin"),
        "0190 unrated-corporate memo (B31)": _all("exposure_class"),
        "0200 unrated investment-grade memo (B31)": (
            ("exposure_class",),
            ("cp_is_investment_grade", "pd_floored"),
        ),
    },
    "c08_03": {
        # pd_scale.banded_rows keys the derived c08_pd_range / c08_pd_parent
        # labels off the framework's allocation PD (see the PD decision above).
        "PD-band rows": _any_of("pd_floored", "pd"),
    },
}

#: C 07.00: column ref -> the ledger columns its binding reads.
_C07_00_CELLS: Mapping[str, CellRequirement] = {
    # SafeSum(reporting_gross_on_bs, reporting_gross_off_bs, c07_ccr_gross). The
    # CCR limb (exposure_type + reporting_gross_drawn/_undrawn) is deliberately
    # NOT required: it carries only the counterparty-credit-risk / settlement
    # legs, which an SA credit-risk extract does not hold.
    "0010": (*_ON_BS_GROSS, *_OFF_BS_GROSS),
    "0020": _all("own_funds_deduction_amount"),
    # Sum(c07_provision): the per-row SCRA+GCRA pick with the sealed Art. 111(2)
    # deducted provision as its fallback rung.
    "0030": _PROVISIONS_C07,
    "0035": _all("on_bs_netting_amount"),  # Basel 3.1 only
    "0040": (),  # Formula 0010 - 0030 (- 0035)
    "0050": _all("guaranteed_portion"),
    # The 0050/0060 split is made by _protection_exprs off protection_type; with
    # no protection_type every covered part lands in 0050 and 0060 is a hard 0.0.
    "0060": _all("guaranteed_portion", "protection_type"),
    "0070": _all("fcsm_collateral_value"),
    "0080": _any_of("life_ins_collateral_value", "third_party_deposit_value"),
    "0090": (),  # Formula 0050 + 0060 + 0070 + 0080
    # SideContext: the cross-sheet inflow, routed by corep/crm_substitution.py on
    # the guarantor's class. Without it the outflow (0090) is reported with no
    # matching inflow anywhere in the estate.
    "0100": _all("post_crm_exposure_class_guaranteed", "guaranteed_portion"),
    "0110": (),  # Formula 0040 - 0090 + 0100
    "0120": (),  # constant 0.0
    "0130": _all("collateral_adjusted_value"),
    "0140": _all("collateral_market_value"),  # market - collateral_adjusted_value
    "0150": (),  # Formula max(0, 0110 - 0130)
    # CCF buckets: Sum(reporting_gross_off_bs) narrowed on the applied CCF and
    # (when derivable) the off-balance-sheet side.
    "0160": _CCF_BUCKET,
    "0170": _CCF_BUCKET,
    "0171": _CCF_BUCKET,  # Basel 3.1 only
    "0180": _CCF_BUCKET,
    "0190": _CCF_BUCKET,
    "0200": _all("ead_final"),
    "0210": _all("ead_final", "risk_type"),
    "0211": _all("ead_final", "risk_type", "cp_entity_type"),
    "0215": _any_of("rwa_pre_factor"),  # CRR only
    "0216": _SF_SME_ADJUSTMENT,  # CRR only
    "0217": _SF_INFRA_ADJUSTMENT,  # CRR only
    "0220": _any_of("rwa_final", "rwa_post_factor", "rwa"),
    "0230": _all("sa_cqs"),
    "0235": _all("sa_cqs"),  # Basel 3.1 only
    "0240": (),  # structural null
}

#: C 08.01: column ref -> the ledger columns its binding reads.
_C08_01_CELLS: Mapping[str, CellRequirement] = {
    "0010": _all("pd_floored", "ead_final"),  # CRR only; binds pd_floored by name
    "0020": (*_ON_BS_GROSS, *_OFF_BS_GROSS),
    "0030": (*_ON_BS_GROSS, *_OFF_BS_GROSS, ("cp_apply_fi_scalar",)),
    "0035": _all("on_bs_netting_amount"),  # Basel 3.1 only
    "0040": _all("guaranteed_portion"),
    "0050": _all("guaranteed_portion", "protection_type"),
    "0060": _all("reporting_ofcp_substitution"),
    # Sum(c08_prot_block) — the per-leg subtotal of 0040/0050/0060, so it is
    # populated by either limb; the guarantee limb is the one a legacy extract
    # realistically carries.
    "0070": _any_of("guaranteed_portion", "reporting_ofcp_substitution"),
    "0080": _all("post_crm_exposure_class_guaranteed", "guaranteed_portion"),
    "0090": (),  # Formula 0020 - 0035 - 0070 + 0080
    # postpass c08_off_bs_pre_ccf: the off-BS slice of the 0090 waterfall.
    "0100": _BS_SIDE,
    "0101": (),  # structural null
    "0102": (),  # structural null
    "0103": (),  # structural null
    "0104": (),  # postpass over 0090 / 0101 / 0102
    "0110": _all("ead_final"),
    "0120": (("ead_final",), *_BS_SIDE),
    "0125": (("ead_final",), *_DEFAULTED),
    "0130": (),  # structural null
    "0140": _all("ead_final", "cp_apply_fi_scalar"),
    "0150": (),  # constant 0.0 — the CRM-in-LGD twins are mutually exclusive
    "0160": (),  # constant 0.0 — with the substitution block above
    "0170": _any_of("reporting_ofcp_lgd_cash_deposit", "reporting_ofcp_lgd_life_insurance"),
    "0171": _all("reporting_ofcp_lgd_cash_deposit"),
    "0172": _all("reporting_ofcp_lgd_life_insurance"),
    "0173": (),  # constant 0.0 — no carrier for Art. 200(1)(c) instruments
    "0180": _all("reporting_crm_lgd_financial"),
    "0190": _all("reporting_crm_lgd_real_estate"),
    "0200": _all("reporting_crm_lgd_other_physical"),
    "0210": _all("reporting_crm_lgd_receivables"),
    "0220": _all("double_default_unfunded_protection"),  # CRR only
    "0230": (("lgd_floored", "lgd_input"), ("ead_final",)),
    "0240": (("lgd_floored", "lgd_input"), ("ead_final",), ("cp_apply_fi_scalar",)),
    "0250": _all("irb_maturity_m", "ead_final"),
    "0251": _all("rwa_pre_adjustments"),  # Basel 3.1 only
    "0252": _all("post_model_adjustment_rwa"),  # Basel 3.1 only
    "0253": _all("mortgage_rw_floor_adjustment"),  # Basel 3.1 only
    "0254": _all("unrecognised_exposure_adjustment"),  # Basel 3.1 only
    "0255": _all("rwa_pre_factor"),  # CRR only
    "0256": _SF_SME_ADJUSTMENT,  # CRR only
    "0257": _SF_INFRA_ADJUSTMENT,  # CRR only
    "0260": _any_of("rwa_final", "rwa_post_factor", "rwa"),
    "0265": (("rwa_final", "rwa_post_factor", "rwa"), *_DEFAULTED),  # Basel 3.1 only
    "0270": (("rwa_final", "rwa_post_factor", "rwa"), ("cp_apply_fi_scalar",)),
    "0275": _all("ead_final"),  # Basel 3.1 only
    "0276": _all("sa_rwa"),  # Basel 3.1 only
    "0280": _any_of("el_pre_adjustment", "expected_loss"),
    "0281": _all("post_model_adjustment_el"),  # Basel 3.1 only
    "0282": _any_of("el_after_adjustment", "expected_loss"),  # Basel 3.1 only
    # SafeSum(scra, gcra) with the provisions-ladder post-pass behind it.
    "0290": _PROVISIONS_C08,
    "0300": _all("counterparty_reference"),  # DISTINCT count; falls back to a row count
    "0310": _any_of("rwa_final", "rwa_post_factor", "rwa"),
}

#: C 08.03: column ref -> the ledger columns its binding reads.
_C08_03_CELLS: Mapping[str, CellRequirement] = {
    "0010": _ON_BS_GROSS,
    "0020": _OFF_BS_GROSS,
    "0030": (("ccf",), *_OFF_BS_GROSS),  # the off-BS gross is the WEIGHT
    "0040": _all("ead_final"),
    "0050": (("pd_floored", "pd"), ("ead_final",)),
    "0060": _all("counterparty_reference"),  # DISTINCT count; falls back to a row count
    "0070": (("lgd_floored", "lgd_input"), ("ead_final",)),
    "0080": _all("irb_maturity_m", "ead_final"),
    "0090": _any_of("rwa_final", "rwa_post_factor", "rwa"),
    "0100": _all("expected_loss"),
    "0110": _PROVISIONS_C08,
}

TEMPLATE_CELL_REQUIREMENTS: Mapping[str, Mapping[str, CellRequirement]] = {
    "c07_00": _C07_00_CELLS,
    "c08_01": _C08_01_CELLS,
    "c08_03": _C08_03_CELLS,
}

# The published column axis per template, so the coverage report walks the
# generator's own refs rather than a second copy of them that could drift.
_TEMPLATE_COLUMN_AXIS: Mapping[str, Callable[[str], tuple[str, ...]]] = {
    "c07_00": lambda framework: tuple(col.ref for col in get_c07_columns(framework)),
    "c08_01": lambda framework: tuple(col.ref for col in get_c08_columns(framework)),
    "c08_03": lambda framework: tuple(col.ref for col in get_c08_03_columns(framework)),
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
        reachable_templates: The scoped templates the projection can produce at
            all — the ones whose ``TEMPLATE_REQUIRED_COLUMNS`` are satisfied. A
            template outside this set emits nothing, which is a different failure
            from a sparse one and must not be shown as a portfolio-wide delta.
    """

    supplied: frozenset[str]
    missing: frozenset[str]
    unavailable_cells: Mapping[str, tuple[str, ...]]
    reachable_templates: frozenset[str]

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
    coverage = ledger_coverage(supplied, framework=framework)
    logger.info(
        "legacy ledger projection: %d ledger columns supplied, %d missing, "
        "%d of %d scoped templates reachable",
        len(coverage.supplied),
        len(coverage.missing),
        len(coverage.reachable_templates),
        len(LEDGER_TEMPLATE_IDS),
    )
    return LegacyLedgerSource(framework=framework, ledger=ledger), coverage


def ledger_coverage(supplied: set[str] | frozenset[str], *, framework: str) -> LedgerCoverage:
    """Score a set of supplied ledger columns against the scoped templates.

    Split out from ``project_legacy_ledger`` so a UI can answer "what would this
    mapping unlock?" before any file is read — the reachability panel the plan
    asks to show BEFORE the compare runs.
    """
    supplied = frozenset(supplied)
    unavailable: dict[str, tuple[str, ...]] = {}
    missing: set[str] = set()
    reachable: set[str] = set()

    for template_id in LEDGER_TEMPLATE_IDS:
        required = TEMPLATE_REQUIRED_COLUMNS[template_id]
        if _satisfied(required, supplied):
            reachable.add(template_id)
        missing |= _unmet_columns(required, supplied)

        cells = TEMPLATE_CELL_REQUIREMENTS[template_id]
        entries: list[str] = []
        for ref in _TEMPLATE_COLUMN_AXIS[template_id](framework):
            requirement = cells.get(ref, ())
            if not requirement or _satisfied(requirement, supplied):
                continue
            unmet = _unmet_columns(requirement, supplied)
            missing |= unmet
            entries.append(f"{ref}: needs {', '.join(sorted(unmet))}")
        if entries:
            unavailable[template_id] = tuple(entries)

        for requirement in LEDGER_ROW_AXIS_COLUMNS[template_id].values():
            missing |= _unmet_columns(requirement, supplied)

    coverage = LedgerCoverage(
        supplied=supplied,
        missing=frozenset(missing),
        unavailable_cells=unavailable,
        reachable_templates=frozenset(reachable),
    )
    _warn_unreachable(coverage)
    return coverage


def _warn_unreachable(coverage: LedgerCoverage) -> None:
    """Log every unproducible template, separating the two failure modes.

    A missing template is not a template of zeroes, and the row-axis case is
    louder still: on C 08.03 an unmapped PD deletes the sheet rather than
    emptying a cell (``LEDGER_ROW_AXIS_FATAL``).
    """
    for template_id in LEDGER_TEMPLATE_IDS:
        if template_id in coverage.reachable_templates:
            continue
        blocking = coverage.blocking_columns(template_id)
        if coverage.row_axis_deleted(template_id):
            logger.warning(
                "legacy ledger projection: %s cannot be produced — its ROW AXIS has no "
                "source (needs one of %s). No sheet will be emitted for any exposure "
                "class; this is not a template of zeroes",
                template_id,
                ", ".join(sorted(LEDGER_ROW_AXIS_FATAL[template_id][0])),
            )
            continue
        logger.warning(
            "legacy ledger projection: %s cannot be produced — missing %s",
            template_id,
            ", ".join(blocking),
        )


# =============================================================================
# Private helpers
# =============================================================================


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
    """Is every OR-group of ``requirement`` met by ``supplied``?"""
    return all(bool(set(group) & supplied) for group in requirement)


def _unmet_columns(requirement: CellRequirement, supplied: frozenset[str]) -> set[str]:
    """The unmet OR-groups' columns, narrowed to what a mapping could supply.

    An OR-group lists every rung the GENERATOR reads, synthetic-frame-only rungs
    included, because documenting the ladder is what the table is for. The report
    has a different job — telling an analyst what to map — so each unmet group is
    reported by its PROJECTABLE members. A group with no projectable rung at all
    falls back to naming the whole group, because "this cell cannot be supplied
    through the grammar" is itself the finding (C 07.00 col 0020's
    ``own_funds_deduction_amount`` is the standing example).
    """
    unmet: set[str] = set()
    for group in requirement:
        if set(group) & supplied:
            continue
        unmet |= set(group) & PROJECTABLE_LEDGER_COLUMNS or set(group)
    return unmet
