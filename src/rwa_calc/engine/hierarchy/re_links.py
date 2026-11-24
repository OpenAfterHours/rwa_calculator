"""
Real-estate collateral links for the hierarchy stage's property enrichment.

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; called by ``resolver`` after the
    FX conversion and before ``enrich.add_collateral_ltv`` /
    ``enrich.enrich_with_property_coverage``, which read the view it returns.

Key responsibilities:
- Build the collateral VIEW the property enrichment reads: each real-estate
  item named in ``collateral_links`` is replaced by one row per link, the
  beneficiary taken from the link. The collateral row's own beneficiary is
  dropped, not kept beside the links (the CRM link allocator's anti-join does
  the same). Every other collateral row passes through unchanged.
- Give every linked beneficiary - a loan, a contingent, a facility's
  exposures or a counterparty's - every property attribute (type, Art. 124A
  qualifying flag, ADC / pre-sold flags, income dependence, prior charges and a
  supplied ``property_ltv``) and a share of the property value. Each link row is
  labelled with its resolved level, so every reader of the view places it at
  the level its share was measured at. The share is pro rata to the PS1/26
  Art. 124C(2) amount of the loans each link names
  (``re_ltv.art_124c_loan_amount_expr``), capped by the link's
  ``max_pledge_amount``, so the shares never sum above the value.
- Leave the bundle's collateral frame alone: the CRM stage expands the same
  links for credit risk mitigation itself (``engine/crm/link_allocation.py``),
  and a frame expanded here would be expanded twice.

Before this, the hierarchy read only the collateral row's own beneficiary, so
one property spread over several loans gave that loan the whole value and an
LTV on its own loan alone, and every other linked loan no property at all
(review CL-13, P1.450). A linked mortgage then lost its class and took its
counterparty's weight (RE005), while a linked loan of an ADC or a
non-qualifying property escaped the higher real-estate weight. The same value
sets the IRB class (``classify.attributes._build_is_mortgage_expr`` reads
``property_collateral_value``), so a linked retail loan whose product names no
mortgage is now an IRB retail mortgage in both regimes, and each linked IRB
row's Basel 3.1 output-floor SA-equivalent takes the real-estate weight.

The LTV follows from the share. Because the share is pro rata to the Art.
124C(2) amount, ``re_ltv.derive_missing_ltv`` reads each linked loan's LTV as
(every loan the item secures + the prior charges) / the property value, which
is what Art. 124C(3) asks: "The amount of the loan which is used for the
calculation of the LTV shall include all other loans secured with charges
ranking in priority ahead of or pari passu with the charge that the exposure is
secured by. If there is insufficient information to determine the ranking of
other charges the institution shall rank the other charges pari passu with the
charge that the exposure is secured by."

The firm's own charges on a property, as this module measures them, are the
exposures one item secures: its link set (and, on the unlinked path, the
exposures a facility- or counterparty-level pledge secures). They are measured
from those exposures' Art. 124C(2) amounts, so they must not also be reported in
``prior_charge_ltv``, which carries the OTHER charges on the property (ranking
ahead or pari passu) as a share of its value and is broadcast to every linked
loan unchanged; a loan's prior amount is that share of its own part of the
value, so the shares again sum to the item's figure. A link carries no ranking,
so the whole link set is one pari passu pool: a junior loan of the firm's own
enters a senior one's LTV too, which Art. 124C(3) does not require and which is
conservative for the senior loan. Whether P1.449's proposed own-prior and
own-pari-passu input amounts should replace or refine this measured definition
is left open to that item's premise audit; nothing here settles it.

The Art. 124F(1)(a) / 124H(1)(a) band ("the part of the exposure up to 55% of
the value of the property") is shared the same way, pro rata. Paragraph (2) of
each reduces the band only for charges NOT held by the institution, so the text
does not itself say how the firm's own exposures on one property share it; the
pro-rata, never-double-counted reading is the owner-approved convention
(sign-off brief P1.450). Under CRR the same share is the "pledged amount of the
market value" of Art. 124(1), against which Art. 125(2)(d) / 126(2)(d) measure
the 80% / 50% limits.

Precedence: a beneficiary secured by two items (say a residential and a
commercial property) takes its single-valued attributes - ``property_type``,
``is_qualifying_re``, income dependence, ``prior_charge_ltv`` and a supplied
``property_ltv`` - from one of them, by the rule the unlinked path already
applies to two collateral rows naming one beneficiary: within a level, the
first row carrying a ``property_ltv`` wins, else the first row, in the
collateral table's row order (``enrich.add_collateral_ltv``). The view keeps
that order - each linked item's rows stand where the item's row stood, in the
links table's order - so the first-listed item wins, whichever of its links
names the beneficiary. Before the order was fixed the joins returned the link
rows in a different order on each run, and so did the RWA. The values and the
any-True flags (non-qualifying, ADC, pre-sold) sum or OR over every item, so
they do not depend on the order.

Effects beyond the linked loans themselves:
- A linked loan's share of a residential value now counts as residential
  security, so it leaves the obligor's retail-threshold aggregate
  (``exposure_for_retail_threshold``; CRR Art. 123(c), PS1/26 Art. 123A(1)(b)(ii)).
  An obligor's OTHER loans - ones no link names - can then fall within the
  threshold and move from the corporate to the retail class.
- The CRM stage ranks the collateral co-linked to an exposure by the
  exposure's SA risk weight, which now reflects the property, so financial
  collateral linked alongside a property may be allocated differently.

Scope:
- Only when ``enable_collateral_link_splitting`` is set, mirroring the CRM
  stage (``CRMProcessor._apply_collateral_links``); off, or with no links
  table, the collateral is returned as it came.
- A link's beneficiary resolves at its own level - an exposure, the immediate
  parent facility, or the counterparty, an unknown type as an exposure (the
  property-coverage step's levels). A link naming no exposure gets no value.
- A capped share is not redistributed to the item's other links: the stranded
  value secures nothing, which raises the capped loan's LTV.

References:
- PS1/26 Art. 124C(2)-(3): LTV over all pari passu and prior-ranking loans
- PS1/26 Art. 124, 124F(1)-(2), 124H(1)-(2), 124J, 124K(1)
- CRR Art. 124(1): secured part capped at the pledged amount of market value
- CRR Art. 125(2)(d) / 126(2)(d): the 80% / 50% of market value limits
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.engine.hierarchy.re_ltv import art_124c_loan_amount_expr
from rwa_calc.engine.kernels.allocation import beneficiary_level_expr
from rwa_calc.engine.materialise import materialise_frame

logger = logging.getLogger(__name__)

# Scratch column names (dropped before the view is returned).
_LEVEL = "_rel_level"
_REF = "_rel_ref"
_BASIS = "_rel_basis"
_TOTAL = "_rel_total"
_ITEM_ORDER = "_rel_item_order"
_LINK_ORDER = "_rel_link_order"


@cites("CRR Art. 124")
@cites("PS1/26, paragraph 124C")
def expand_real_estate_links(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
    collateral_links: pl.LazyFrame | None,
    *,
    enabled: bool,
) -> pl.LazyFrame | None:
    """The collateral view with every linked real-estate item expanded to its links.

    Args:
        exposures: Unified exposures in the reporting currency, carrying
            ``exposure_reference``, ``parent_facility_reference``,
            ``counterparty_reference`` and the Art. 124C(2) amounts
            (``drawn_amount`` / ``interest`` / ``nominal_amount``).
        collateral: The FX-converted collateral table, or ``None``.
        collateral_links: The sealed (and namespace-qualified) M:N links table,
            or ``None``.
        enabled: ``config.enable_collateral_link_splitting``.

    Returns:
        ``collateral`` unchanged when there is nothing to expand; otherwise the
        collateral in its input row order, each linked real-estate item replaced
        where it stood by one row per link (in the links table's order), in the
        same columns, with ``market_value`` the link's share. The order is
        fixed, so every run on the same input resolves the same attributes.
    """
    if collateral is None or collateral_links is None or not enabled:
        return collateral

    is_real_estate = pl.col("collateral_type").str.to_lowercase() == "real_estate"
    # The input row order of each collateral row and each link, carried to the
    # final sort: the joins below do not keep row order, and a beneficiary named
    # by two items takes its attributes from the first row it meets (see the
    # "Precedence" section of the module docstring).
    collateral = collateral.with_row_index(_ITEM_ORDER)
    # One row per (item, beneficiary type, beneficiary): a repeated link shares nothing twice.
    link_key = ["collateral_reference", "beneficiary_type", "beneficiary_reference"]
    links = (
        collateral_links.select(*link_key, "max_pledge_amount")
        .unique(subset=link_key, keep="first", maintain_order=True)
        .with_row_index(_LINK_ORDER)
    )
    items = collateral.filter(is_real_estate).join(
        links.select("collateral_reference").unique(), on="collateral_reference", how="semi"
    )
    unlinked = collateral.join(
        items.select("collateral_reference"), on="collateral_reference", how="anti"
    )
    # The links of linked real-estate items only: their beneficiaries are the only
    # exposures whose amounts are read, so the collect below keeps a handful of
    # rows however large the book (measured on 50,000 loans: resolve about +0.25s,
    # against +0.6s when every exposure's amount was read).
    item_links = links.join(
        items.select("collateral_reference"), on="collateral_reference", how="semi"
    )
    # Collected once (``materialise_frame``): the shares read the exposure
    # amounts, and the property enrichment reads this view seven times (three
    # attribute levels, three LTV levels, one coverage aggregate), so a lazy view
    # would embed the whole upstream exposure plan in every read. Measured on a
    # 30-loan book: the unoptimised hierarchy plan is 0.48m characters with no
    # links, 12.8m with a lazy view and 0.54m with this one collected;
    # resolve-to-collect 0.4s, 9.2s and 0.7s. The frame holds one row per link
    # edge of a linked real-estate item.
    linked = materialise_frame(
        item_links.join(
            items.drop("beneficiary_type", "beneficiary_reference"),
            on="collateral_reference",
            how="inner",
        )
        .with_columns(beneficiary_level_expr(unknown="direct").alias(_LEVEL))
        .join(
            _link_basis_lookup(exposures, item_links),
            left_on=[_LEVEL, "beneficiary_reference"],
            right_on=[_LEVEL, _REF],
            how="left",
        )
        .with_columns(pl.col(_BASIS).sum().over("collateral_reference").alias(_TOTAL))
        .with_columns(
            _link_share_expr().alias("market_value"),
            _view_beneficiary_type_expr().alias("beneficiary_type"),
        )
        .drop(_LEVEL, _BASIS, _TOTAL, "max_pledge_amount")
        .sort(_ITEM_ORDER, _LINK_ORDER)
    )
    # Each linked item's rows stand where the item stood, in link order; an
    # unlinked row's own index is unique, so its null link ordinal never ties.
    return (
        pl.concat([unlinked, linked], how="diagonal_relaxed")
        .sort(_ITEM_ORDER, _LINK_ORDER)
        .drop(_ITEM_ORDER, _LINK_ORDER)
    )


def _link_basis_lookup(exposures: pl.LazyFrame, item_links: pl.LazyFrame) -> pl.LazyFrame:
    """Art. 124C(2) loan amount per (level, beneficiary reference) a link names.

    An exposure's own amount at the direct level; the sum over the exposures
    sharing the key at the facility (immediate parent) and counterparty levels.
    Only the exposures some link reference names at one of those keys are read.
    """
    named = item_links.select("beneficiary_reference").unique()
    amounts = exposures.select(
        "exposure_reference",
        "parent_facility_reference",
        "counterparty_reference",
        art_124c_loan_amount_expr().alias(_BASIS),
    )
    lookups = [
        amounts.join(named, left_on=key, right_on="beneficiary_reference", how="semi")
        .group_by(key)
        .agg(pl.col(_BASIS).sum())
        .select(pl.lit(level).alias(_LEVEL), pl.col(key).alias(_REF), _BASIS)
        for level, key in (
            ("direct", "exposure_reference"),
            ("facility", "parent_facility_reference"),
            ("counterparty", "counterparty_reference"),
        )
    ]
    return pl.concat(lookups, how="vertical")


def _view_beneficiary_type_expr() -> pl.Expr:
    """The link's beneficiary type in the view: its resolved level, ``exposure`` if direct.

    The view's readers do not agree on which labels are direct.
    ``enrich.add_collateral_ltv`` looks a property's attributes up at the direct
    level for ``exposure`` / ``loan`` only, while the property-coverage and
    LTV-derivation steps (and the share above) also take ``contingent``, and an
    unknown label, as direct. A link to a contingent must say ``contingent`` (the
    CRM stage raises CRM010 on any other label), so without this its contingent
    took a share of the value and a derived LTV but none of the property's
    attributes, and was weighted as qualifying residential. Naming the level here
    makes all three readers place every link row where the share was measured.
    The unlinked rows keep their own labels: a contingent named by a collateral
    row's own ``beneficiary_type`` is the attribute lookup's own, pre-existing gap.
    """
    return pl.when(pl.col(_LEVEL) == "direct").then(pl.lit("exposure")).otherwise(pl.col(_LEVEL))


def _link_share_expr() -> pl.Expr:
    """The link's share of the item's value: pro rata to its basis, capped by the link.

    A link whose beneficiary matched nothing has a null basis and so a null
    share, which the cap must not turn into a value (``min_horizontal`` skips
    nulls). An item whose links carry no amount at all shares nothing.
    """
    pro_rata = (
        pl.when(pl.col(_TOTAL) > 0.0)
        .then(pl.col("market_value") * pl.col(_BASIS) / pl.col(_TOTAL))
        .otherwise(pl.lit(0.0))
    )
    return (
        pl.when(pro_rata.is_null())
        .then(pro_rata)
        .otherwise(pl.min_horizontal(pro_rata, pl.col("max_pledge_amount")))
    )
