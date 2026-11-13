"""Hand-built result frames for the C 02.00 / OF 02.00 published-layout tests.

One leg per figure the template can place, each with a DISTINCT amount, so a
figure landing in the wrong row changes a sum the tests state from the leg
list rather than from the generator's own grouping.

``own`` is the leg's RWEA under the approach it is actually on (``rwa_final``
under CRR, ``rwa_pre_floor`` under Basel 3.1); ``standardised`` is what the
standardised approach gives the same leg (``sa_rwa``), which only Basel 3.1
reports. The two differ on every modelled leg, so a column that copies one
where the other belongs cannot pass.
"""

from __future__ import annotations

from typing import NamedTuple

import polars as pl

#: The Basel 3.1 output floor multiplier the frames carry (Art. 92(5), 2027).
FLOOR_MULTIPLIER = 0.6


class Leg(NamedTuple):
    """One result row: where it sits and what it weighs."""

    reference: str
    approach: str
    exposure_class: str
    own: float
    standardised: float
    is_sme: bool | None = None
    subclass: str | None = None
    property_type: str | None = None
    sl_type: str | None = None
    equity_method: str | None = None


#: Standardised-approach legs: one per ``ExposureClass`` the SA rows key, plus a
#: SA-CCR derivative and the two SA-method equity classes.
SA_LEGS: tuple[Leg, ...] = (
    Leg("SA_CG", "standardised", "central_govt_central_bank", 10.0, 10.0),
    Leg("SA_RG", "standardised", "rgla", 11.0, 11.0),
    Leg("SA_PSE", "standardised", "pse", 12.0, 12.0),
    Leg("SA_MDB", "standardised", "mdb", 13.0, 13.0),
    Leg("SA_IO", "standardised", "international_organisation", 14.0, 14.0),
    Leg("SA_INST", "standardised", "institution", 15.0, 15.0),
    Leg("SA_CORP", "standardised", "corporate", 16.0, 16.0),
    Leg("SA_CSME", "standardised", "corporate_sme", 17.0, 17.0),
    Leg("SA_SL", "standardised", "specialised_lending", 18.0, 18.0),
    Leg("SA_RET", "standardised", "retail_other", 19.0, 19.0),
    Leg("SA_QRRE", "standardised", "retail_qrre", 20.0, 20.0),
    Leg("SA_RM", "standardised", "retail_mortgage", 21.0, 21.0),
    Leg("SA_RES", "standardised", "residential_mortgage", 22.0, 22.0),
    Leg("SA_COM", "standardised", "commercial_mortgage", 23.0, 23.0),
    Leg("SA_DEF", "standardised", "defaulted", 24.0, 24.0),
    Leg("SA_HR", "standardised", "high_risk", 25.0, 25.0),
    Leg("SA_CB", "standardised", "covered_bond", 26.0, 26.0),
    Leg("SA_OTH", "standardised", "other", 27.0, 27.0),
    Leg("SA_CCR", "standardised_ccr", "institution", 28.0, 28.0),
    Leg("SA_EQ", "equity", "equity", 29.0, 29.0, equity_method="sa"),
    Leg("SA_CIU", "equity", "ciu", 30.0, 30.0, equity_method="sa"),
)

#: Foundation-IRB legs both regimes have a row for.
FIRB_LEGS: tuple[Leg, ...] = (
    Leg("F_INST", "foundation_irb", "institution", 100.0, 150.0),
    Leg("F_SL", "foundation_irb", "specialised_lending", 110.0, 160.0),
    Leg("F_FSE", "foundation_irb", "corporate", 120.0, 170.0, subclass="corporate_financial_large"),
    Leg(
        "F_SME",
        "foundation_irb",
        "corporate_sme",
        130.0,
        180.0,
        is_sme=True,
        subclass="corporate_sme",
    ),
    Leg("F_OTH", "foundation_irb", "corporate", 140.0, 190.0, subclass="corporate_other"),
)

#: Advanced-IRB legs both regimes have a row for.
AIRB_LEGS: tuple[Leg, ...] = (
    Leg("A_SL", "advanced_irb", "specialised_lending", 200.0, 260.0),
    Leg(
        "A_SME",
        "advanced_irb",
        "corporate_sme",
        210.0,
        270.0,
        is_sme=True,
        subclass="corporate_sme",
    ),
    Leg("A_OTH", "advanced_irb", "corporate", 220.0, 280.0, subclass="corporate_other"),
    Leg(
        "A_RES_SME",
        "advanced_irb",
        "retail_mortgage",
        230.0,
        290.0,
        is_sme=True,
        property_type="residential",
    ),
    Leg(
        "A_RES",
        "advanced_irb",
        "retail_mortgage",
        240.0,
        300.0,
        is_sme=False,
        property_type="residential",
    ),
    Leg(
        "A_COM_SME",
        "advanced_irb",
        "retail_mortgage",
        250.0,
        310.0,
        is_sme=True,
        property_type="commercial",
    ),
    Leg(
        "A_COM",
        "advanced_irb",
        "retail_mortgage",
        255.0,
        315.0,
        is_sme=False,
        property_type="commercial",
    ),
    Leg("A_QRRE", "advanced_irb", "retail_qrre", 265.0, 320.0),
    Leg("A_OSME", "advanced_irb", "retail_other", 275.0, 330.0, is_sme=True),
    Leg("A_ONON", "advanced_irb", "retail_other", 285.0, 340.0, is_sme=False),
)

#: Supervisory-slotting legs, one per specialised-lending type.
SLOTTING_LEGS: tuple[Leg, ...] = (
    Leg("SL_PF", "slotting", "specialised_lending", 400.0, 500.0, sl_type="project_finance"),
    Leg("SL_OF", "slotting", "specialised_lending", 410.0, 510.0, sl_type="object_finance"),
    Leg("SL_CF", "slotting", "specialised_lending", 420.0, 520.0, sl_type="commodities_finance"),
    Leg("SL_IPRE", "slotting", "specialised_lending", 430.0, 530.0, sl_type="ipre"),
    Leg("SL_HVCRE", "slotting", "specialised_lending", 440.0, 540.0, sl_type="hvcre"),
)

#: Legs only the CRR template has a row for: IRB sovereigns, A-IRB institutions
#: and Art. 155 IRB equity. PS1/26 Art. 147A withdraws all four.
CRR_ONLY_LEGS: tuple[Leg, ...] = (
    Leg("F_CG", "foundation_irb", "central_govt_central_bank", 600.0, 0.0),
    Leg("A_CG", "advanced_irb", "central_govt_central_bank", 610.0, 0.0),
    Leg("A_INST", "advanced_irb", "institution", 620.0, 0.0),
    Leg("EQ_IRB", "equity", "equity", 630.0, 0.0, equity_method="irb_simple"),
)

COMMON_LEGS: tuple[Leg, ...] = SA_LEGS + FIRB_LEGS + AIRB_LEGS + SLOTTING_LEGS
MODELLED_LEGS: tuple[Leg, ...] = FIRB_LEGS + AIRB_LEGS + SLOTTING_LEGS


def own(legs: tuple[Leg, ...], *references: str) -> float:
    """Sum of ``own`` over ``legs`` — all of them, or the named references."""
    return sum(leg.own for leg in legs if not references or leg.reference in references)


def standardised(legs: tuple[Leg, ...], *references: str) -> float:
    """Sum of ``standardised`` over ``legs`` — all of them, or the named references."""
    return sum(leg.standardised for leg in legs if not references or leg.reference in references)


def crr_frame(legs: tuple[Leg, ...] = COMMON_LEGS + CRR_ONLY_LEGS) -> pl.LazyFrame:
    """A CRR result frame: ``rwa_final`` only, no output-floor carriers."""
    return _frame(legs).drop("rwa_pre_floor", "sa_rwa", "output_floor_pct")


def b31_frame(
    legs: tuple[Leg, ...] = COMMON_LEGS, *, floor_add_on: float = 0.0, carry_multiplier: bool = True
) -> pl.LazyFrame:
    """A Basel 3.1 result frame, with the carriers the output floor seals.

    ``floor_add_on`` is added to ``rwa_final`` on every modelled leg, as the
    engine distributes a binding floor's shortfall; ``rwa_pre_floor`` keeps the
    un-floored figure. ``carry_multiplier=False`` omits ``output_floor_pct``, the
    shape of a frame the floor never ran on.
    """
    frame = _frame(legs).with_columns(
        pl.when(pl.col("approach_applied").is_in(["foundation_irb", "advanced_irb", "slotting"]))
        .then(pl.col("rwa_final") + floor_add_on)
        .otherwise(pl.col("rwa_final"))
        .alias("rwa_final")
    )
    return frame if carry_multiplier else frame.drop("output_floor_pct")


def _frame(legs: tuple[Leg, ...]) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": [leg.reference for leg in legs],
            "approach_applied": [leg.approach for leg in legs],
            "exposure_class": [leg.exposure_class for leg in legs],
            "ead_final": [leg.own * 2.0 for leg in legs],
            "rwa_final": [leg.own for leg in legs],
            "rwa_pre_floor": [leg.own for leg in legs],
            "sa_rwa": [leg.standardised for leg in legs],
            "output_floor_pct": [FLOOR_MULTIPLIER for _ in legs],
            "is_sme": [leg.is_sme for leg in legs],
            "exposure_subclass": [leg.subclass for leg in legs],
            "property_type": [leg.property_type for leg in legs],
            "sl_type": [leg.sl_type for leg in legs],
            "equity_method": [leg.equity_method for leg in legs],
        },
        schema_overrides={
            "is_sme": pl.Boolean,
            "exposure_subclass": pl.String,
            "property_type": pl.String,
            "sl_type": pl.String,
            "equity_method": pl.String,
        },
    )
