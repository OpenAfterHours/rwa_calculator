"""
COREP CRM substitution — the cross-template inflow router and the IRB waterfall.

Pipeline position:
    sealed aggregator-exit ledger -> substitution_inflows() ->
    ``ReportingContext.substitution_inflow`` -> C 07.00 col 0100
    (``corep/c07.py``) / C 08.01 col 0080 (``corep/c08.py``);
    crm_waterfall() / waterfall_refs() -> the C 08.01/02 col 0090 ``Formula``

Key responsibilities:
- Compute the per-destination-class CRM substitution INFLOW once over the WHOLE
  sealed population, and hand each inflow to the template that reports the
  approach the substituted leg is actually treated under.
- Own the C 08.01/02 col 0090 waterfall identity and its per-row-scope column
  selection, so the published rule and the code that satisfies it sit together.

WHY THIS IS NOT A PER-TEMPLATE HELPER (the defect it retires). C 07.00 and
C 08.01 each derived their own inflow map from their OWN approach-filtered
population, so a substitution that crossed the SA/IRB boundary was reported as
an outflow on one template and as an inflow on NEITHER: an IRB corporate loan
guaranteed by a sovereign (an SA-only class under PS1/26 Art. 147A(1)(a))
deducted the covered part on C 08.01 ``corporate`` and added it back nowhere,
because C 08.01 has no sovereign sheet and C 07.00's sovereign sheet is outside
the IRB leg's population. Annex II requires the opposite, for both templates and
both frameworks: "Exposures stemming from possible in- and outflows from and to
other templates shall be taken into account."

THE ROUTING KEY is the sealed ``reporting_approach`` — the aggregator's
``approach_post_crm`` (``engine/aggregator/aggregator.py``), which is exactly the
post-substitution approach: a guaranteed leg with an SA guarantor is a direct SA
exposure to the guarantor (CRR Art. 235 risk-weight substitution) and so its
inflow belongs on C 07.00, while a guaranteed leg with an IRB guarantor stays
under the obligor's IRB approach (CRR Art. 161 parameter substitution) and its
inflow belongs on C 08.01. The two destinations PARTITION the population — the
SA side is the complement of the IRB labels, so it also picks up the output
floor's ``standardised_ccr`` relabel — which is what makes an inflow impossible
to drop or to count twice.

A frame that does not seal the destination approach (synthetic unit frames; the
aggregator always seals it in production) routes NOTHING to the foreign template:
the cross-template half returns empty and each template keeps only what its own
population produced. An earlier draft offered the same unrouted map to both
callers on the theory that each would keep the destination classes it had sheets
for — that mitigation died the moment the sheet axis started unioning in the
inflow keys, because both templates would then materialise the sheet and BOTH
book the inflow. Under-reporting one cross-template inflow on a frame that cannot
express the routing beats double-counting it on every such frame.

SAME-CLASS MIGRATIONS ARE INCLUDED. Annex II, both templates and both
frameworks: "Inflows and outflows within the same exposure classes and, where
relevant, obligor grades or pools, shall also be considered." Gating the inflow
on a class CHANGE while the outflow subtotal counts every covered part makes a
same-class guarantee shrink the return by the covered amount — reproduced on
C 07.00 (``rgla`` guaranteed by an ``rgla`` counterparty lost 1,000,000 out of
col 0110) and, once col 0070 became the Annex II subtotal, on C 08.01 too.

RESIDUAL GAP (recorded, not papered over). The outflow subtotal counts every
route in the substitution block, but only the unfunded routes carry a
destination: the sealed ledger has ``post_crm_exposure_class_guaranteed`` for
guarantee / credit-derivative legs only. C 07.00's funded limbs (col 0070
financial collateral under the Simple Method, col 0080 Art. 232 other funded
protection) and C 08.01's col 0060 (Art. 232 other funded protection) therefore
produce an outflow with no matching inflow. The collateral issuer's exposure
class is not modelled, so the honest options are to under-report the outflow or
to under-report the inflow; the live rules ``v1663_m`` / ``v1665_m`` /
``v0305_m`` fix the outflow as the subtotal, so the gap lands on the inflow.
Sealing an issuer class per collateral leg is the follow-up that closes it.

References:
- Reg (EU) 2021/451 Annex II: C 07.00 cols 0090/0100 and C 08.01 cols 0070/0080
  ("SUBSTITUTION OF THE EXPOSURE DUE TO CRM"); PRA PS1/26 Annex II, OF 08.01
  cols 0070/0080
- CRR Art. 235 (risk-weight substitution), Art. 161 (IRB parameter substitution)
- Published rules: ``v0305_m`` / ``v0306_m`` (C 07.00), ``v1662_m`` / ``v1663_m``
  (C 08.01.a), ``v0347_m`` / ``v1665_m`` (C 08.02)

The two calling generators (``c07_plans`` / ``generate_c08_01``) carry the
``@cites`` annotations for this code path; a decorator pair here
(``CRR Art. 235`` + ``PS1/26, paragraph 1.3``) is a worthwhile addition but
needs ``uv run python scripts/generate_citation_matrix.py`` re-run to refresh
the docs matrix and the contract snapshot alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping

# The post-substitution approach labels whose inflow belongs on the IRB
# templates. Everything else is the SA destination — the complement, so the two
# sides partition the population (see the module docstring).
_IRB_DESTINATIONS: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# The sealed post-substitution approach (aggregator ``approach_post_crm``).
_DESTINATION_APPROACH_COL: str = "reporting_approach"
# The sealed ORIGIN approach (``approach_applied``) — which template reports the
# leg's outflow, and therefore whose Annex II block cap measures it.
_ORIGIN_APPROACH_COL: str = "reporting_approach_origin"
# The guarantor's exposure class — the destination sheet key.
_DESTINATION_CLASS_COL: str = "post_crm_exposure_class_guaranteed"
# The raw covered-part carrier. Its PRESENCE gates the whole mechanism; its VALUE
# is never summed directly — see :data:`IRB_UNFUNDED_COL`.
_COVERED_COL: str = "guaranteed_portion"
# The covered part of the original exposure pre-conversion factors, AS REPORTED —
# i.e. after the Annex II block cap. Reading the RAW ``guaranteed_portion`` here
# instead created money: the outflow sheds proportionally when the protection
# block over-runs the exposure, so a raw inflow booked more than ever left. The
# column is derived by :func:`irb_protection_exprs`, the SAME function that
# derives the cell bindings, so the two sides cannot drift.
IRB_UNFUNDED_COL: str = "c08_prot_unfunded"
IRB_BLOCK_COL: str = "c08_prot_block"

# C 08.01/02 col 0060 "OTHER FUNDED CREDIT PROTECTION" — the Art. 232(1) /
# Art. 200(1) list (third-party deposits, pledged life policies, instruments
# repurchased on request), i.e. protection treated AS A GUARANTEE and therefore
# acting on the OBLIGOR'S PD through substitution. This is the same carrier pair
# C 07.00 reads for its own Art. 232 column (``corep/c07.py::_OFCP_CARRIERS``).
#
# The Art. 199 collateral (immovable property, receivables, other physical) is
# DELIBERATELY NOT HERE: it is an LGD mitigant, not a PD one, and Annex II routes
# it by name to the CRM-in-LGD-estimates block at cols 0190/0200/0210 — see
# :func:`irb_protection_exprs` for the quoted instructions.
IRB_OFCP_CARRIERS: tuple[str, ...] = (
    "life_ins_collateral_value",
    "third_party_deposit_value",
)

# The per-leg pre-conversion-factor gross carriers that col 0020 sums — the cap
# basis for the substitution block (see :func:`irb_block_cap_scale`).
IRB_GROSS_CARRIERS: tuple[str, ...] = ("reporting_gross_on_bs", "reporting_gross_off_bs")

type Destination = Literal["standardised", "irb"]

# The kernel's off-balance-sheet ``exposure_type`` set (the ``bs_type`` fallback).
_OFF_BS_EXPOSURE_TYPES: list[str] = ["facility", "contingent", "facility_undrawn"]


@dataclass(frozen=True)
class InflowBreakdown:
    """One destination class's substitution inflow, on the axes C 08.01 publishes.

    ``total`` lands on the Total row 0010; ``on_bs`` / ``off_bs`` on rows 0020 /
    0030 (``boe_b0744``); ``graded`` / ``slotting`` on rows 0070 / 0080
    (``boe_b0745``, EBA ``v0338_m``). Each PAIR sums to ``total`` — they are the
    same money counted along two axes, exactly as a native exposure appears once
    in each decomposition. C 07.00 reads ``total`` only: its own row
    decomposition ``boe_b0717`` is scoped to cols 0200/0220, neither of which the
    inflow touches.
    """

    total: float
    on_bs: float
    off_bs: float
    graded: float
    slotting: float
    # C 07.00's third axis: the same money split by the RISK-WEIGHT BAND the
    # substituted amount is reported at on the destination sheet. Empty unless the
    # caller supplied a band expression (C 08.01 has no risk-weight row axis).
    by_rw_band: dict[str, float] = field(default_factory=dict)


# C 08.01 rows whose col 0090 waterfall EXCLUDES the B31 col 0035 on-balance-sheet
# netting term. The BoE splits the published waterfall in two by row scope:
# ``boe_b0746`` (live, ERROR) is ``{c0090} = sum({c0020; 0035; 0070; 0080})`` over
# r:0010;0017;0020;0070;0170;0175;0180;0190;0200, while ``boe_b0746_1`` drops the
# 0035 term over r:0001;0030;0031;0032;0033;0034;0035 — which is exactly the
# OFF-BALANCE-SHEET row family (row 0030 "Off balance sheet items subject to credit
# risk" plus its five CCF sub-rows). That split is not arbitrary: Art. 166(3)
# netting of loans and deposits is an on-balance-sheet effect, so it cannot reduce
# an off-balance-sheet row. Row 0080 (slotting total) and the inert CCR
# netting-set rows 0040/0050/0060 are in NEITHER scope; 0080 keeps the term so it
# stays consistent with its section sibling 0070 and the 0070 + 0080 = 0010
# approach partition still foots. C 08.02 has no such split — ``boe_b0760`` puts
# 0035 in the waterfall on every row of OF08.02.01.01. Under CRR there is no col
# 0035 at all, so the whole mechanism is a B31-only no-op there.
C08_01_NETTING_EXEMPT_ROWS: frozenset[str] = frozenset(
    {"0030", "0031", "0032", "0033", "0034", "0035"}
)


def waterfall_refs(column_refs: tuple[str, ...], *, netting: bool) -> tuple[str, ...]:
    """The ``Formula`` refs for one C 08.01/02 col 0090 cell.

    Selecting the col 0035 term by REF rather than by a branch inside
    :func:`crm_waterfall` is C 07.00's ``_net_of_adjustments`` precedent: the
    executor passes only the named refs, so an omitted one reads as zero. The
    presence guard keeps CRR — which has no col 0035 — on the three-ref form, and
    is load-bearing besides: a ref naming a column outside ``column_refs`` raises
    in the executor rather than degrading.
    """
    if netting and "0035" in column_refs:
        return ("0020", "0035", "0070", "0080")
    return ("0020", "0070", "0080")


def crm_waterfall(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0090 = 0020 - 0035 - 0070 + 0080 (positive magnitudes; 0035 by ref).

    The published identity, on the REPORTED signs where 0035/0070 are "(-)"
    deductions: ``{c0090} = sum({c0020; 0035; 0070; 0080})`` — EBA ``v1662_m`` /
    ``v0347_m`` and BoE ``boe_b0746`` (C 08.01) / ``boe_b0760`` (C 08.02). Col
    0070 IS the whole outflow; cols 0040/0050/0060 are the breakdown that MAKES
    it up, so subtracting both — as this did before — deducts every covered part
    twice. That is C 07.00's recorded ``_net_after_substitution`` defect on the
    IRB surface. The cell runs BEFORE the Annex II §1.3 negation pass, hence the
    positive magnitudes and the subtractions.
    """
    return (
        (cells["0020"] or 0.0)
        - (cells.get("0035") or 0.0)
        - (cells["0070"] or 0.0)
        + (cells["0080"] or 0.0)
    )


def irb_origin_inflows(
    results: pl.LazyFrame,
    cols: set[str],
    *,
    destination: Destination,
    band_expr: pl.Expr | None = None,
) -> dict[str, InflowBreakdown]:
    """CRM substitution inflows arising from IRB-ORIGIN legs, per destination class.

    ``results`` is the WHOLE sealed population (not the calling template's own
    slice) — routing across the SA/IRB boundary is the entire point. ``cols`` is
    its column set. ``destination`` selects the half whose substituted legs are
    treated under the standardised approach (they land on C 07.00) or under an
    IRB approach (they land on C 08.01).

    WHY IRB-ORIGIN ONLY, and why that is COMPLETE rather than a simplification.
    The inflow must equal the outflow the SOURCE template actually reported, so
    it has to be measured with the SOURCE template's Annex II block cap — and the
    two templates cap on different bases (C 07.00's ``_block_cap_scale`` nets
    provisions off the basis under the Art. 111(2) drawn-first deduction; the IRB
    basis here does not). This function owns the IRB cap, so it can only speak
    for IRB-origin legs. It does not need to speak for SA-origin ones:
    ``engine/aggregator/aggregator.py::_post_crm_approach_expr`` sets the
    destination approach to the SA literal for an SA guarantor and to the
    obligor's own ``approach_applied`` otherwise, so an SA-ORIGIN leg lands on an
    SA destination under BOTH branches — it can never reach C 08.01. C 07.00
    therefore adds its own SA-origin half in-frame, off its own capped columns
    (``corep/c07.py::_sa_inflows``), and C 08.01 needs nothing further. If that
    aggregator rule ever grows a branch that maps an SA origin to an IRB
    destination, this docstring and ``_sa_inflows`` are the two places to revisit.

    Returns ``{guarantor exposure class: covered amount}`` as POSITIVE magnitudes
    measured on the CAPPED carrier (see :data:`IRB_UNFUNDED_COL`), empty when the
    frame carries no substitution carriers. Legs with no destination class are
    dropped rather than grouped under a null key: the sheet axis has no null
    member, so a null-keyed inflow could only be silently lost. Every leg with a
    positive covered part is counted — including one whose guarantor sits in the
    obligor's own class (Annex II "Inflows and outflows within the same exposure
    classes ... shall also be considered").
    """
    if not {_COVERED_COL, _DESTINATION_CLASS_COL} <= cols:
        return {}
    migrated = results.with_columns(irb_protection_exprs(cols)).filter(
        (pl.col(IRB_UNFUNDED_COL) > 0) & pl.col(_DESTINATION_CLASS_COL).is_not_null()
    )
    if _ORIGIN_APPROACH_COL in cols:
        migrated = migrated.filter(_is_irb(_ORIGIN_APPROACH_COL))
    if _DESTINATION_APPROACH_COL in cols:
        is_irb = _is_irb(_DESTINATION_APPROACH_COL)
        migrated = migrated.filter(is_irb if destination == "irb" else ~is_irb)
    elif destination == "standardised":
        # No sealed destination approach (synthetic unit frames): route nothing to
        # the FOREIGN template. Offering the same map to both callers would have
        # each materialise the destination sheet and book the inflow twice, now
        # that the sheet axis unions in the inflow keys — a double count is worse
        # than the pre-routing behaviour it would be imitating.
        return {}
    covered = pl.col(IRB_UNFUNDED_COL)
    bands = _band_split(migrated, covered, band_expr)
    grouped = (
        migrated.group_by(_DESTINATION_CLASS_COL)
        .agg(
            covered.sum().alias("total"),
            covered.filter(_off_bs(cols).not_()).sum().alias("on_bs"),
            covered.filter(_off_bs(cols)).sum().alias("off_bs"),
            covered.filter(_slotting(cols)).sum().alias("slotting"),
            covered.filter(_slotting(cols).not_()).sum().alias("graded"),
        )
        .collect()
    )
    return {
        row[_DESTINATION_CLASS_COL]: InflowBreakdown(
            total=float(row["total"] or 0.0),
            on_bs=float(row["on_bs"] or 0.0),
            off_bs=float(row["off_bs"] or 0.0),
            graded=float(row["graded"] or 0.0),
            slotting=float(row["slotting"] or 0.0),
            by_rw_band=bands.get(row[_DESTINATION_CLASS_COL], {}),
        )
        for row in grouped.iter_rows(named=True)
    }


def _band_split(
    migrated: pl.LazyFrame, covered: pl.Expr, band_expr: pl.Expr | None
) -> dict[str, dict[str, float]]:
    """Per destination class, the inflow split by risk-weight band label.

    ``band_expr`` is supplied by the CALLER because the band ladder is that
    template's own regime-shaped axis (``corep/c07.py::_rw_band_expr`` over
    ``get_sa_risk_weight_bands``) — the same expression its own rows key on, so a
    banded inflow lands on a row that exists. It is measured on the SOURCE leg's
    ``risk_weight``, which on a guaranteed leg IS the guarantor's substituted
    weight (CRR Art. 235 risk-weight substitution), i.e. the weight the
    destination sheet should report the inflow at. The ladder ends in an "Other
    risk weights" catch-all, so no leg can be silently dropped.
    """
    if band_expr is None:
        return {}
    grouped = (
        migrated.with_columns(band_expr.alias("_rw_band"))
        .group_by(_DESTINATION_CLASS_COL, "_rw_band")
        .agg(covered.sum().alias("inflow"))
        .collect()
    )
    out: dict[str, dict[str, float]] = {}
    for row in grouped.iter_rows(named=True):
        amount = float(row["inflow"] or 0.0)
        if amount:
            out.setdefault(row[_DESTINATION_CLASS_COL], {})[row["_rw_band"]] = amount
    return out


def _is_irb(col: str) -> pl.Expr:
    return pl.col(col).is_in(list(_IRB_DESTINATIONS)).fill_null(value=False)


def _off_bs(cols: set[str]) -> pl.Expr:
    """Is the SOURCE leg off-balance-sheet? (C 08.01 row 0030 vs row 0020.)

    The balance-sheet side is a property of the underlying asset and substitution
    does not change it, so the inflow inherits the side of the leg it came from.
    The kernel ladder is ``bs_type`` then ``exposure_type``; a leg the frame
    cannot place falls to the ON-balance-sheet side rather than vanishing, which
    is what keeps ``on_bs + off_bs == total`` and therefore keeps ``boe_b0744``
    footing on a frame with a thin schema.
    """
    if "bs_type" in cols:
        return pl.col("bs_type") == "OFB"
    if "exposure_type" in cols:
        return pl.col("exposure_type").is_in(_OFF_BS_EXPOSURE_TYPES).fill_null(value=False)
    return pl.lit(value=False)


def _slotting(cols: set[str]) -> pl.Expr:
    """Is the SOURCE leg slotted post-substitution? (row 0080 vs row 0070.)

    Read off the POST-substitution approach, so the split matches the treatment
    the substituted amount is actually reported under. Everything that is not
    slotting is an exposure assigned to an obligor grade or pool (row 0070), which
    is where a parameter-substituted amount belongs — it takes the guarantor's
    grade. With no sealed approach the whole inflow is graded, so
    ``graded + slotting == total`` regardless.
    """
    if _DESTINATION_APPROACH_COL not in cols:
        return pl.lit(value=False)
    return (pl.col(_DESTINATION_APPROACH_COL) == "slotting").fill_null(value=False)


def irb_block_cap_scale(cols: set[str], block_total: pl.Expr) -> pl.Expr:
    """The 0-1 factor that caps the substitution block at the leg's own exposure.

    ``1.0`` unless the block over-runs the cap basis, in which case
    ``basis / block_total`` (well-defined: an over-run implies a positive total).
    Degrades to ``1.0`` — uncapped — only on a frame carrying neither a gross
    carrier nor ``ead_final``, which the sealed ledger never is. This is C 07.00's
    ``_block_cap_scale`` (``corep/c07.py``) on the IRB surface; the basis differs
    (see ``irb_protection_exprs``) and there is no provisions term, because the
    Art. 111(2) drawn-first deduction is SA-only.
    """
    gross = [pl.col(col).fill_null(0.0) for col in IRB_GROSS_CARRIERS if col in cols]
    if not gross and "ead_final" in cols:
        gross = [pl.col("ead_final").fill_null(0.0)]
    if not gross:
        return pl.lit(1.0)
    basis = pl.sum_horizontal(gross).clip(lower_bound=0.0)
    return pl.when(block_total > basis).then(basis / block_total).otherwise(1.0)


def irb_protection_exprs(cols: set[str]) -> list[pl.Expr]:
    """Per-leg capped twins of the C 08.01/02 substitution-block carriers.

    WHAT THE BLOCK CONTAINS — cols 0040/0050/0060 sit under "CREDIT RISK
    MITIGATION (CRM) TECHNIQUES WITH SUBSTITUTION EFFECTS ON THE EXPOSURE", the
    route where the protection provider's risk replaces the obligor's, i.e. an
    effect on PD. Annex II says so of col 0060 in three ways: "Collateral that
    has an effect on the **PD** of the exposure shall be capped ..."; "Where own
    estimates of LGD are not used, **Article 232(1)** CRR applies" (the
    Art. 200(1) list — third-party deposits, pledged life policies, instruments
    repurchased on request — treated AS A GUARANTEE); and, decisively, the
    routing sentence "**Where an adjustment is made in the LGD, that amount shall
    be reported in column 170**". PS1/26 is blunter still: "Other funded credit
    protection that is treated as a guarantee in accordance with Article 232 ...
    shall be included. Other funded credit protection that is not treated as a
    guarantee ... shall be reported in 0172."

    WHY THE ART. 199 COLLATERAL IS NOT HERE (recorded — this column previously
    summed it, and that was a DOUBLE COUNT, not a magnitude problem). Immovable
    property, receivables and other physical collateral are LGD mitigants under
    both IRB variants — recognised through Art. 230 where own LGD estimates are
    not used, and through Art. 181(1)(e)-(f) where they are — never through
    substitution, so they never touch PD. Annex II routes them BY NAME to the
    "CRM TECHNIQUES TAKEN INTO ACCOUNT IN LGD ESTIMATES" block, whose heading
    excludes substitution effects outright ("CRM techniques that have an impact on
    LGD estimates as a result of the application of the substitution effect of CRM
    techniques shall not be included in these columns") and whose columns cite the
    exact paragraphs: 0190 REAL ESTATE "Article 199(2), (3) and (4)"; 0200 OTHER
    PHYSICAL COLLATERAL "Article 199(6) and (8)"; 0210 RECEIVABLES "Articles
    199(5) and 229(2)". ``_value_cells`` already binds all three there, so the
    same 500,000 of property was being reported twice on one sheet — once
    correctly at col 0190 and once as a -500,000 exposure reduction at col 0060,
    driving col 0090 ("exposure after CRM substitution effects pre-conversion
    factors") to -200,000 on a supervisory return. Removing it from col 0060
    loses nothing: col 0190 is untouched. Same defect and same remedy as C 07.00
    col 0080 (``corep/c07.py``); the SA/IRB difference is only WHERE the
    collateral does belong — SA: the exposure class; IRB: this LGD block.

    THE CAP ITSELF still applies to what legitimately remains in the block, and
    Annex II mandates it twice: cols 0040-0050 "shall be capped at the exposure
    value", col 0060 "shall be capped at the value of the original exposure pre
    conversion factors". It is inert on every committed portfolio now that the
    Art. 199 collateral is gone, and is kept because the requirement is real —
    an Art. 232 deposit or a guarantee CAN exceed the exposure it covers.

    THE BLOCK, NOT THE COLUMN (C 07.00's recorded reasoning): capping each column
    at the exposure separately still lets the columns SUM past it, so the cap is
    applied to the block total and the excess shed PROPORTIONALLY across the
    components — Annex II prescribes no priority between the protection routes,
    so no route may be preferred.

    THE PRE-CCF BASIS: the two cap sentences name nominally different bases ("the
    exposure value" for 0040-0050, "the original exposure pre conversion factors"
    for 0060). The PRE-conversion-factor basis (what col 0020 sums) is the one
    adopted for the whole block, because the block feeds the PRE-CCF waterfall at
    col 0090; capping against the post-CCF exposure value inside a pre-CCF
    waterfall would leave 0090 able to go negative.

    COL 0070 IS THE BLOCK'S SUBTOTAL, NOT A FIFTH COMPONENT OF IT. Annex II
    defines the substitution outflow as "the covered part of the original
    exposure pre-conversion factors that is deducted from the obligor's exposure
    class", and the live rules ``v1663_m`` (C 08.01.a) / ``v1665_m`` (C 08.02)
    write that out: ``{c0070} = {c0040} + {c0050} + {c0060}``. So it is the
    already-capped block total (``c08_prot_block``, returned here so the identity
    holds BY CONSTRUCTION on every frame rather than by two bindings agreeing),
    it needs no cap of its own, and it must not be capped a second time. The
    docstring here previously recorded the double-subtraction that reads the same
    covered part out of both col 0040 and col 0070 as "currently inert (no leg in
    any committed portfolio sits in both)": that claim was FALSE — every guarantee
    lands in both columns by construction, it was reproduced against the real
    pipeline (a 1,500,000 guarantee deducted twice from a 51,100,000 corporate
    sheet), and it is now fixed in ``_crm_waterfall``, not deferred.

    Returns the ``c08_prot_*`` twins for whichever raw carriers the frame has,
    plus the ``c08_prot_block`` subtotal — a constant 0.0 on a frame with no
    protection carrier at all, so col 0070 reports the same zero deduction as the
    breakdown cells it subtotals instead of a structural null the published
    identity cannot be evaluated against.
    """
    parts = [pl.col(col).fill_null(0.0) for col in IRB_OFCP_CARRIERS if col in cols]
    unfunded: pl.Expr | None = None
    if "guaranteed_portion" in cols:
        gp = pl.col("guaranteed_portion").fill_null(0.0)
        # Cols 0040/0050 split the same carrier by protection type, so a leg
        # contributes to the block only through the type it actually carries;
        # with no ``protection_type`` column col 0040 takes the whole amount.
        unfunded = (
            pl.when(pl.col("protection_type").is_in(["guarantee", "credit_derivative"]))
            .then(gp)
            .otherwise(pl.lit(0.0))
            if "protection_type" in cols
            else gp
        )
        parts.append(unfunded)
    if not parts:
        return [pl.lit(0.0).alias(IRB_BLOCK_COL), pl.lit(0.0).alias(IRB_UNFUNDED_COL)]
    scale = irb_block_cap_scale(cols, pl.sum_horizontal(parts))
    exprs = [
        (pl.col(col).fill_null(0.0) * scale).alias(f"c08_prot_{col}")
        for col in IRB_OFCP_CARRIERS
        if col in cols
    ]
    if unfunded is not None:
        exprs.append(
            (pl.col("guaranteed_portion").fill_null(0.0) * scale).alias("c08_prot_guaranteed")
        )
    # The col 0070 subtotal: the SAME capped magnitudes cols 0040/0050/0060 sum,
    # added up once per leg. ``unfunded`` already carries the protection_type
    # split those two cells make by predicate, so the identity
    # ``0070 == 0040 + 0050 + 0060`` holds however the frame degrades.
    exprs.append((pl.sum_horizontal(parts) * scale).alias(IRB_BLOCK_COL))
    # The UNFUNDED half of that subtotal — cols 0040 + 0050 per leg, i.e. the only
    # part of the outflow that carries a destination class. The substitution INFLOW
    # binds this column so it is the SAME capped magnitude the outflow reports;
    # reading the raw ``guaranteed_portion`` instead booked more on the way in than
    # ever left, creating money whenever the cap bit. ``unfunded`` is already
    # protection_type-gated, so a leg carrying an out-of-vocabulary protection type
    # (non-blocking validation lets one through) contributes zero to BOTH sides
    # rather than zero out and a full amount in.
    exprs.append(
        ((unfunded if unfunded is not None else pl.lit(0.0)) * scale).alias(IRB_UNFUNDED_COL)
    )
    return exprs
