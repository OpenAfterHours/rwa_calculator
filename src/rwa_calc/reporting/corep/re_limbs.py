"""
The Art. 124 limb (regulatory, other or ADC) the Basel 3.1 SA dispatcher's real-estate
route places a leg in, and its property side, as OF 07.00 rows 0330-0360 and OF 09.01
rows 0091-0094 report them.

Pipeline position:
    corep/c07.py::_prepare and corep/c09.py::_c09_01_derived_exprs -> re_limb_exprs()
        -> the {prefix}_re_limb / {prefix}_re_property discriminators
        -> the real-estate row terms (c07._re_terms over ``_RE_ROW_FILTERS``;
           c09._C09_01_RE_ROW_TERMS) -> re_limb_terms()

Key responsibilities:
- Place a leg in the limb the Basel 3.1 SA dispatcher routes its real-estate weight
  through, by evaluating the dispatcher's own predicates
  (``engine/sa/b31_risk_weight_tables.py::b31_real_estate_route``) on the sealed
  columns they read, and name its property side as that limb's weight reads it.
- Give C 07.00 and C 09.01 one derivation and one set of row terms, so an OF 09.01
  sub-row and the OF 07.00 row it is defined by read the same columns.

THE LIMBS. PS1/26 gives each its own weights (Art. 124(1)-(3): Articles 124F-124I for
regulatory real estate, 124J for other real estate, 124K for ADC) and defines them to
exclude one another. Art. 124A(1): a real estate exposure is regulatory "if it is not
an ADC exposure and all the following requirements are met", among them (d) "the value
of the property is determined in accordance with Article 124D". Glossary: "other real
estate exposure means a real estate exposure that is not a regulatory real estate
exposure or an ADC exposure". PS1/26 Annex II
(ps1-26-annex-ii-reporting-instructions.pdf PAGE_INDEX 89-91, 139) reports them on
OF 07.00 0330-0344 (Art. 124F / 124G / 124H / 124I), 0350-0354 (Art. 124J) and 0360
(Art. 124K). OF 09.01 row 0090 is the "Sum of rows 0091 to 0094", each with the "Same
definition as for row 0330 / 0340 / 0350 / 0360 of OF CR SA template", and the Bank
ties each pair (``boe_b0978``-``boe_b0989``).

WHY THE DISPATCHER'S PREDICATES. Until 2026-11 the rows read the input flags
directly: ``property_type`` for the side, ``is_qualifying_re`` for regulatory or other,
and no ADC exclusion at all. That disagreed with the weight on every shape the flags do
not decide, each measured through ``PipelineOrchestrator``
(``tests/integration/test_re_limb_partition_pipeline.py``):

- An ADC loan secured on commercial property was reported in 0340 AND 0360.
- A residential leg attested non-qualifying was reported in 0330 AND 0350.
- A leg secured on a property with no value (``property_type`` set, no LTV), which
  fails Art. 124A(1)(d) and is weighted under Art. 124J, was reported in 0330.
- A mortgage carrying its own LTV and no ``property_type`` was weighted under
  Art. 124F but reported in no limb row of either template.

Wherever the dispatcher reaches its real-estate branches, the route is what the weight
was computed from, so the reported limb is the one whose article set the weight. An
earlier dispatcher branch can pre-empt them (subordinated debt's flat 150%, for one);
the row then still names the limb the route places the leg in. A later step that
re-weights the leg (Art. 127, CRM substitution) does not move it either: that step
changes none of the route's inputs.

THE PROPERTY SIDE is the one the limb's weight reads:

- regulatory: commercial where the route's commercial branch matched
  (``is_commercial_re_class``: the class, or ``property_type`` "commercial"), else
  residential, which on a leg with no ``property_type`` is decided by its class;
- other: residential where ``property_type`` is residential, else commercial. This
  is the Art. 124J(2) / 124J(3) test of the weight (``is_residential_property``), so
  a null ``property_type`` reads as commercial here as it does there.

NOT IN A LIMB: a leg that matches no route predicate. That would be a real-estate class
with no ``is_adc``, no LTV, no ``property_type``, and no attested non-qualification.
The dispatcher prices it at its counterparty-class weight, and under the PS1/26
Glossary it is not a real estate exposure at all. If one reached the sheet it would
count in the class total (OF 07.00 row 0010, OF 09.01 row 0090) and in no limb row.
The one such shape measured (2026-11), a mortgage product with no property linked and
no LTV, is classified ``retail_other`` and never reaches the sheet. Whether any such
leg belongs in Art. 112(1)(i) is a classification question, not one for these rows.

Absent-strict. A frame missing any of ``RE_LIMB_SOURCES`` cannot evaluate the route,
so no limb is derived and the limb rows render empty rather than guess. C 07.00's
``_re_terms`` declares no terms, and C 09.01's terms on an underived column match
nothing (``cellspec.RowPredicate._compile``). Every source is sealed on the aggregator
exit (``contracts/edges.py``).

References:
- PRA PS1/26 Art. 124(1)-(3), Art. 124A(1), Art. 124J; Glossary "other real estate
  exposure", "real estate exposure"
- PRA PS1/26 Annex II OF 07.00 rows 0330-0360; OF 09.01 rows 0090-0094
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl
from watchfire import cites

from rwa_calc.engine.sa.b31_risk_weight_tables import b31_real_estate_route
from rwa_calc.engine.sa.re_class import is_residential_property

#: The Art. 124 limb a real-estate row reports.
type ReLimb = Literal["regulatory", "other", "adc"]
#: The property side of a regulatory or other real-estate row.
type ReProperty = Literal["residential", "commercial"]

#: The sealed columns ``b31_real_estate_route`` reads: the routing class, the
#: property and its LTV, Art. 124A, and ADC.
RE_LIMB_SOURCES: frozenset[str] = frozenset(
    {"exposure_class", "property_type", "ltv", "is_qualifying_re", "is_adc"}
)


@dataclass(frozen=True, slots=True)
class ReRow:
    """One OF 07.00 real-estate "of which" row: its Art. 124 limb, then the narrowing
    within it (``None`` = no narrowing on that axis).

    ``property_kind`` is the limb's property side (``re_limb_exprs``). ``md``
    ("materially dependent on the cash flows generated by the property") and ``sme``
    are read through C 07.00's own derived discriminators (``c07_md`` / ``c07_sme``).
    """

    limb: ReLimb
    property_kind: ReProperty | None = None
    md: bool | None = None
    sme: bool | None = None


@cites("PS1/26, paragraph 124")
def re_limb_exprs(cols: set[str], *, prefix: str) -> list[pl.Expr]:
    """The ``{prefix}_re_limb`` and ``{prefix}_re_property`` discriminators, derived
    only when every one of ``RE_LIMB_SOURCES`` is on the frame.

    ``{prefix}_re_limb`` is "adc", "other" or "regulatory", first match in the
    dispatcher's own order, and null where no route predicate matches.
    ``{prefix}_re_property`` is the property side of a regulatory or other leg, and
    null on ADC. One function serves both templates: OF 09.01's sub-rows are defined
    by OF 07.00's, so the two must derive these identically or the tie-out cannot hold.
    """
    if not RE_LIMB_SOURCES.issubset(cols):
        return []
    # The dispatcher's ``_upper_class`` (engine/sa/risk_weights.py), verbatim.
    route = b31_real_estate_route(pl.col("exposure_class").str.to_uppercase())
    other_side = pl.when(is_residential_property()).then(pl.lit("residential"))
    limb = (
        pl.when(route.adc)
        .then(pl.lit("adc"))
        .when(route.other_re)
        .then(pl.lit("other"))
        .when(route.commercial | route.residential)
        .then(pl.lit("regulatory"))
    )
    side = (
        pl.when(route.adc)
        .then(pl.lit(None, dtype=pl.String))
        .when(route.other_re)
        .then(other_side.otherwise(pl.lit("commercial")))
        .when(route.commercial)
        .then(pl.lit("commercial"))
        .when(route.residential)
        .then(pl.lit("residential"))
    )
    return [limb.alias(f"{prefix}_re_limb"), side.alias(f"{prefix}_re_property")]


def re_limb_terms(
    limb: ReLimb, property_kind: ReProperty | None = None, *, prefix: str
) -> tuple[tuple[str, str], ...]:
    """The membership terms of one limb, optionally narrowed to one property side,
    over ``re_limb_exprs``' discriminators. Over a leg with a derived limb, exactly
    one limb matches."""
    terms: tuple[tuple[str, str], ...] = ((f"{prefix}_re_limb", limb),)
    if property_kind is None:
        return terms
    return (*terms, (f"{prefix}_re_property", property_kind))
