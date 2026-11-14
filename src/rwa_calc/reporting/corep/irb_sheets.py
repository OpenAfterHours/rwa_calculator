"""
The IRB class-and-approach breakdown — one definition for OF 02.00 and OF 08.

Pipeline position:
    sealed aggregator-exit ledger
        -> here (which published sheet a leg belongs to)
        -> corep/c02.py (the OF 02.00 IRB class rows)
        -> corep/c08_sheets.py -> corep/c08.py (the OF 08.01 / 08.02 / 08.03 /
           08.05 sheets)
        -> filing/sheet_maps.py (published sheet code -> our sheet key)

Key responsibilities:
- Hold the ONE table that says which legs each published Basel 3.1 IRB sheet
  takes (``B31_CLASS_SHEETS``): the fifteen class-and-approach sheets of
  OF 08.01 / 08.02 / 08.03 / 08.05, each with its published code and label, the
  population it takes, the Total sheet it adds into and the OF 02.00 row whose
  figure it is.
- Compile that table into the per-leg sheet key (``sheet_key_expr``), which
  ``c02.py`` groups its IRB class rows by and ``c08_sheets.py`` keys the OF 08
  sheets by. One expression, so the two templates cannot disagree.
- Hold the leg classification both read (SME, financial or large corporate,
  commercial property, and the Art. 151(4) class revert).

Why one definition. The taxonomy makes each OF 02.00 IRB class row ONE data
point with the total of an OF 08.01 sheet — row 0271 column 0010 is sheet 0006
row 0010 column 0260, row 0295 is sheet 0022, and so on for fifteen rows, and
column 0020 is column 0276 likewise. A leg counted in one row and reported on
another sheet is one data point with two values, which a return cannot carry.
Until 2026-11-13 the OF 08 sheets were keyed by exposure class alone — coarser
than the published axis, so no figure on them could be filed at all — and
``c02.py`` held this classification privately.

Recorded decisions:

- THE FLAGS ARE THE OBLIGOR'S ON BOTH BASES. SME, financial-or-large and
  commercial-property are read off the leg, and the ledger seals them for the
  obligor only. A leg that moved to a guarantor's class by substitution is
  therefore placed among that class's sheets on its OBLIGOR's flags. Unknown is
  not a filter: the leg reports as non-SME, non-financial, residential.
- A-IRB FOLDS A FINANCIAL OR LARGE CORPORATE INTO "OTHER GENERAL CORPORATES -
  NON-SME" (sheet 0011), where F-IRB reports it on a sheet of its own (0022).
  Asymmetric, and preserved from ``c02.py``: PS1/26 Art. 147A permits no A-IRB
  for that sub-class and the published axis has no A-IRB sheet for it, so the
  engine should emit none.
- EVERY SLOTTING LEG IS ON SHEET 0010, whatever class the post-substitution key
  names. Slotting applies to specialised lending alone (Annex II row 0080;
  ``boe_b1041``), the template has the slotting row on that sheet and on the
  FIRB-and-slotting Total only, and OF 02.00 counts a slotting leg by its
  approach.
- A PAIR WITH NO SHEET IS NOT PLACED ON ONE. Art. 147A withdraws the IRB
  approach for sovereigns and A-IRB for institutions, and Art. 151(4) keeps
  retail off F-IRB. A leg carrying such a pair keys an OFF-AXIS sheet named for
  the pair (``institution_airb``): it is reported, it is counted in its
  approach's Total — as OF 02.00 counts it in the approach row — and
  ``c08_sheets.py`` records it as an error. It is never dropped and never added
  to a neighbouring sheet.

CRR is not described here. C 08.01 has its own published axis (class by own
estimates or not) and no EBA taxonomy is held to lay it out against; the CRR
sheets stay keyed by exposure class — see ``c08_sheets.py``.

References:
- PRA PS1/26 Art. 147(2), Art. 147A; Annex II §3.3.1-§3.3.2 (the OF CR IRB
  exposure and sub-exposure classes) and §1.3 (OF 02.00)
- CRR Art. 151(4) (retail exposures: own LGD estimates are mandatory)
- Bank of England Banking Taxonomy v4.1.1, module PRA001, tables
  ``OF08.01.01.01`` (the sheet axis) and ``OF02.00.01.01``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import polars as pl

from rwa_calc.reporting.corep import c02_rows as rows
from rwa_calc.reporting.corep.templates import IRB_EXPOSURE_CLASS_LABELS

# =============================================================================
# Constants
# =============================================================================

FIRB: Final = "foundation_irb"
AIRB: Final = "advanced_irb"
SLOTTING: Final = "slotting"

#: The IRB retail classes. CRR Art. 151(4) puts retail exposures under the
#: ADVANCED approach only (own LGD estimates are mandatory), which is why both
#: regimes' templates carry retail rows and sheets under A-IRB and none under
#: F-IRB — see ``placeable_irb_class`` for the pair this makes impossible.
RETAIL_CLASSES: Final[tuple[str, ...]] = ("retail_mortgage", "retail_qrre", "retail_other")

#: The Art. 147(2)(c) general-corporate classes the sub-class split reads.
CORPORATE_CLASSES: Final[tuple[str, ...]] = ("corporate", "corporate_sme")

#: ``property_type`` values that make a retail real-estate leg COMMERCIAL; every
#: other value, and none, is residential.
COMMERCIAL_PROPERTY_TYPES: Final[tuple[str, ...]] = ("commercial", "cre")

#: The Total sheets (published codes 0001 and 0002). Annex II §3.3.2: "The Total
#: template must be reported for the FIRB and the slotting approaches and,
#: separately for the AIRB approach."
TOTAL_AIRB_KEY: Final = "total_airb"
TOTAL_FIRB_SLOTTING_KEY: Final = "total_firb_slotting"

#: The sheet that carries the slotting row (published code 0010).
SLOTTING_SHEET_KEY: Final = "specialised_lending_firb_slotting"

# The suffix an off-axis sheet key takes, by approach. Slotting has none: every
# slotting leg is on ``SLOTTING_SHEET_KEY``.
_OFF_AXIS_SUFFIX: Final[dict[str, str]] = {FIRB: "_firb", AIRB: "_airb"}

_SPECIALISED_LENDING: Final[tuple[str, ...]] = ("specialised_lending",)
_RETAIL_REAL_ESTATE: Final[tuple[str, ...]] = ("retail_mortgage",)
_RETAIL_OTHER: Final[tuple[str, ...]] = ("retail_other",)


# =============================================================================
# The sheet table
# =============================================================================


@dataclass(frozen=True)
class Limb:
    """One population of legs, as an (approach, classes, flags) conjunction.

    ``None`` is "not a filter" — for ``classes``, any class at all.
    """

    approach: str
    classes: tuple[str, ...] | None
    sme: bool | None = None
    financial_large: bool | None = None
    commercial: bool | None = None


@dataclass(frozen=True)
class IrbSheet:
    """One published class-and-approach sheet and the legs it takes.

    Attributes:
        code: The published sheet (z-axis) code.
        key: Our sheet key — the bundle key the sheet is generated under.
        label: The publisher's label for the sheet.
        tab: A short name, for a workbook tab — at most 20 characters, which is
            what is left of Excel's 31 after the longest ``OF 08.05 - `` prefix.
        limbs: The populations the sheet takes. The FIRST is the sheet as
            published; any other is a recorded decision (module docstring).
        total: The key of the Total sheet this sheet adds into.
        slot: The OF 02.00 figure that is the legs of ``limbs[0].approach`` on
            this sheet. Its Basel 3.1 row is one data point with the sheet's
            total — except on the slotting sheet, whose total also counts the
            slotting legs OF 02.00 reports in rows of their own.
    """

    code: str
    key: str
    label: str
    tab: str
    limbs: tuple[Limb, ...]
    total: str
    slot: rows.Slot

    @property
    def approach(self) -> str:
        """The approach of the sheet as published (F-IRB or A-IRB)."""
        return self.limbs[0].approach


#: The fifteen class-and-approach sheets, in published code order. Codes and
#: labels are the taxonomy's (``tests/contracts/test_of08_published_sheets.py``
#: holds them to it, with each sheet's approach, class, SME and property
#: members and the OF 02.00 row it is one data point with).
B31_CLASS_SHEETS: Final[tuple[IrbSheet, ...]] = (
    IrbSheet(
        "0006",
        "institution_firb",
        "Institutions (FIRB approach)",
        "Institutions FIRB",
        (Limb(FIRB, ("institution",)),),
        TOTAL_FIRB_SLOTTING_KEY,
        rows.FIRB_INSTITUTIONS,
    ),
    IrbSheet(
        "0009",
        "specialised_lending_airb",
        "Corporates - Specialised Lending (AIRB approach)",
        "SL AIRB",
        (Limb(AIRB, _SPECIALISED_LENDING),),
        TOTAL_AIRB_KEY,
        rows.AIRB_SPECIALISED_LENDING,
    ),
    IrbSheet(
        "0010",
        SLOTTING_SHEET_KEY,
        "Corporates - Specialised Lending (FIRB approach or slotting approach)",
        "SL FIRB-slotting",
        (Limb(FIRB, _SPECIALISED_LENDING), Limb(SLOTTING, None)),
        TOTAL_FIRB_SLOTTING_KEY,
        rows.FIRB_SPECIALISED_LENDING,
    ),
    IrbSheet(
        "0011",
        "corporate_non_sme_airb",
        "Corporates - Other general corporates - non-SME (AIRB approach)",
        "Corp non-SME AIRB",
        (
            Limb(AIRB, CORPORATE_CLASSES, sme=False, financial_large=False),
            # The A-IRB fold of a financial or large corporate (module docstring).
            Limb(AIRB, CORPORATE_CLASSES, financial_large=True),
        ),
        TOTAL_AIRB_KEY,
        rows.AIRB_CORPORATES_OTHER,
    ),
    IrbSheet(
        "0012",
        "corporate_non_sme_firb",
        "Corporates - Other general corporates - non-SME (FIRB approach)",
        "Corp non-SME FIRB",
        (Limb(FIRB, CORPORATE_CLASSES, sme=False, financial_large=False),),
        TOTAL_FIRB_SLOTTING_KEY,
        rows.FIRB_CORPORATES_OTHER,
    ),
    IrbSheet(
        "0015",
        "retail_qrre_airb",
        "Retail - Qualifying revolving (AIRB approach)",
        "Retail QRRE",
        (Limb(AIRB, ("retail_qrre",)),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_QRRE,
    ),
    IrbSheet(
        "0016",
        "retail_other_sme_airb",
        "Retail - Other SME (AIRB approach)",
        "Retail other SME",
        (Limb(AIRB, _RETAIL_OTHER, sme=True),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_OTHER_SME,
    ),
    IrbSheet(
        "0017",
        "retail_other_non_sme_airb",
        "Retail - Other non-SME (AIRB approach)",
        "Retail other non-SME",
        (Limb(AIRB, _RETAIL_OTHER, sme=False),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_OTHER_NON_SME,
    ),
    IrbSheet(
        "0018",
        "retail_commercial_re_sme_airb",
        "Retail – Secured by commercial immovable property SME (AIRB approach)",
        "Retail CRE SME",
        (Limb(AIRB, _RETAIL_REAL_ESTATE, sme=True, commercial=True),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_COMMERCIAL_SME,
    ),
    IrbSheet(
        "0019",
        "retail_commercial_re_non_sme_airb",
        "Retail – Secured by commercial immovable property non-SME (AIRB approach)",
        "Retail CRE non-SME",
        (Limb(AIRB, _RETAIL_REAL_ESTATE, sme=False, commercial=True),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_COMMERCIAL_NON_SME,
    ),
    IrbSheet(
        "0020",
        "retail_residential_re_sme_airb",
        "Retail – Secured by residential immovable property - SME (AIRB approach)",
        "Retail RRE SME",
        (Limb(AIRB, _RETAIL_REAL_ESTATE, sme=True, commercial=False),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_RESIDENTIAL_SME,
    ),
    IrbSheet(
        "0021",
        "retail_residential_re_non_sme_airb",
        "Retail – Secured by residential immovable property non-SME (AIRB approach)",
        "Retail RRE non-SME",
        (Limb(AIRB, _RETAIL_REAL_ESTATE, sme=False, commercial=False),),
        TOTAL_AIRB_KEY,
        rows.AIRB_RETAIL_RESIDENTIAL_NON_SME,
    ),
    IrbSheet(
        "0022",
        "corporate_financial_large_firb",
        "Corporates - Financial corporates and large corporates (FIRB approach)",
        "Corp fin-large FIRB",
        (Limb(FIRB, CORPORATE_CLASSES, financial_large=True),),
        TOTAL_FIRB_SLOTTING_KEY,
        rows.FIRB_FINANCIAL_LARGE_CORPORATES,
    ),
    IrbSheet(
        "0023",
        "corporate_sme_airb",
        "Corporates - Other general corporates - SME (AIRB approach)",
        "Corp SME AIRB",
        (Limb(AIRB, CORPORATE_CLASSES, sme=True, financial_large=False),),
        TOTAL_AIRB_KEY,
        rows.AIRB_CORPORATES_SME,
    ),
    IrbSheet(
        "0024",
        "corporate_sme_firb",
        "Corporates - Other general corporates - SME (FIRB approach)",
        "Corp SME FIRB",
        (Limb(FIRB, CORPORATE_CLASSES, sme=True, financial_large=False),),
        TOTAL_FIRB_SLOTTING_KEY,
        rows.FIRB_CORPORATES_SME,
    ),
)

#: The two Total sheets: ``(published code, our key, published label, tab)``.
B31_TOTAL_SHEETS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("0001", TOTAL_AIRB_KEY, "Total (AIRB approach)", "Total AIRB"),
    (
        "0002",
        TOTAL_FIRB_SLOTTING_KEY,
        "Total (FIRB approach and slotting approach)",
        "Total FIRB-slotting",
    ),
)

#: Published sheet code -> our sheet key, for all seventeen published sheets.
B31_SHEET_KEYS: Final[dict[str, str]] = {
    **{code: key for code, key, _label, _tab in B31_TOTAL_SHEETS},
    **{sheet.code: sheet.key for sheet in B31_CLASS_SHEETS},
}

_TOTAL_KEYS: Final[frozenset[str]] = frozenset(key for _c, key, _l, _t in B31_TOTAL_SHEETS)
_CLASS_SHEET_BY_KEY: Final[dict[str, IrbSheet]] = {sheet.key: sheet for sheet in B31_CLASS_SHEETS}


# =============================================================================
# Public API — the sheet a leg belongs to
# =============================================================================


def sheet_key_expr(cols: set[str], approach: pl.Expr, exposure_class: pl.Expr) -> pl.Expr:
    """The Basel 3.1 sheet key of a leg treated under ``approach`` in ``exposure_class``.

    ``approach`` and ``exposure_class`` are whichever basis the caller is asking
    about — the obligor's own, or the post-substitution pair (with the class
    passed through ``placeable_irb_class``). The flags are read off the leg
    (module docstring).

    Returns a published sheet's key; an off-axis key (``<class>_firb`` /
    ``<class>_airb``) for an IRB pair the published axis has no sheet for; and
    null for a leg that is not under an IRB approach, or carries no class.
    """
    sme = is_sme_expr(cols) | (exposure_class == "corporate_sme").fill_null(value=False)
    flags = {
        "sme": sme,
        "financial_large": is_financial_large_expr(cols),
        "commercial": is_commercial_expr(cols),
    }
    suffix = pl.lit(None, dtype=pl.String)
    for irb_approach, text in _OFF_AXIS_SUFFIX.items():
        suffix = pl.when(approach == irb_approach).then(pl.lit(text)).otherwise(suffix)
    key = pl.concat_str([exposure_class, suffix])
    for sheet in reversed(B31_CLASS_SHEETS):
        taken = pl.lit(value=False)
        for limb in sheet.limbs:
            taken = taken | _limb_expr(limb, approach, exposure_class, flags)
        key = pl.when(taken).then(pl.lit(sheet.key)).otherwise(key)
    return key


@dataclass(frozen=True)
class SheetPlace:
    """Where one sheet key sits on the published axis.

    Attributes:
        total: The key of the Total sheet it adds into; ``None`` for a Total
            sheet itself and for a key that is not an IRB sheet key at all.
        published: Whether the key is one of the published class sheets.
        retail: Whether its legs are retail exposures.
    """

    total: str | None
    published: bool
    retail: bool


def place_of(key: str) -> SheetPlace:
    """Where ``key`` sits: its Total, and whether the published axis has it.

    Reads an off-axis key by its suffix, so a pair with no published sheet is
    still counted in its approach's Total.
    """
    sheet = _CLASS_SHEET_BY_KEY.get(key)
    if sheet is not None:
        return SheetPlace(
            sheet.total,
            published=True,
            retail=sheet.limbs[0].classes is not None
            and set(sheet.limbs[0].classes) <= set(RETAIL_CLASSES),
        )
    if key in _TOTAL_KEYS:
        return SheetPlace(None, published=True, retail=False)
    for approach, suffix in _OFF_AXIS_SUFFIX.items():
        if key.endswith(suffix):
            total = TOTAL_AIRB_KEY if approach == AIRB else TOTAL_FIRB_SLOTTING_KEY
            return SheetPlace(
                total, published=False, retail=key.removesuffix(suffix) in RETAIL_CLASSES
            )
    return SheetPlace(None, published=False, retail=key in RETAIL_CLASSES)


def get_irb_sheet_labels(framework: str = "CRR") -> dict[str, str]:
    """Readable name per Basel 3.1 IRB sheet key: the publisher's own label.

    For a sheet picker. Empty under CRR, whose sheets are keyed by exposure
    class and have always shown their key. A key not named here falls back to
    itself at the caller, so an off-axis sheet shows its key rather than
    disappearing.
    """
    if framework != rows.FRAMEWORK_BASEL_3_1:
        return {}
    return {
        **{key: label for _code, key, label, _tab in B31_TOTAL_SHEETS},
        **{sheet.key: sheet.label for sheet in B31_CLASS_SHEETS},
    }


def get_irb_sheet_tabs(framework: str = "CRR") -> dict[str, str]:
    """Short name per IRB sheet key, for a workbook tab.

    CRR: the Art. 147(2) class names. Basel 3.1: a short name per published
    sheet — the published labels differ only past the point a 31-character tab
    name is cut, so two sheets would otherwise claim one tab.
    """
    if framework != rows.FRAMEWORK_BASEL_3_1:
        return IRB_EXPOSURE_CLASS_LABELS
    return {
        **{key: tab for _code, key, _label, tab in B31_TOTAL_SHEETS},
        **{sheet.key: sheet.tab for sheet in B31_CLASS_SHEETS},
    }


# =============================================================================
# Public API — the leg classification
# =============================================================================


def placeable_irb_class(post_ec_col: str, origin_ec_col: str, approach_col: str) -> pl.Expr:
    """The post-substitution IRB class, REVERTED where that class cannot exist
    under the leg's approach.

    THE IMPOSSIBLE-PAIR TRAP, AND WHY IT IS HANDLED HERE RATHER THAN IGNORED.
    A post class key against the obligor's RETAINED approach can name a pair
    neither template has a row for: the aggregator moves the class to the
    guarantor's but keeps the obligor's approach whenever the guarantor is not
    SA, so an F-IRB corporate loan covered by a RETAIL guarantor emits
    ``(foundation_irb, retail_other)``. CRR Art. 151(4) makes that impossible —
    retail exposures are A-IRB only, so both layouts have retail rows under A-IRB
    and none under F-IRB. Its RWEA then fell out of the F-IRB class rows while the
    F-IRB total still counted it: 2,028,365.78 (CRR) / 1,700,935.66 (B31) on the
    CRM-substitution portfolio, INVISIBLE to every published rule, because the
    rules only check rows that exist. Reverting the class keeps the "of which"
    breakdown a true partition of the F-IRB total.

    THIS IS A REPORTING GUARD, NOT THE FIX. The engine should never have
    recognised the guarantee: CRR Art. 201(1) is an exhaustive list of eligible
    unfunded-protection providers — central governments/banks, RGLAs, MDBs,
    0%-RW international organisations, PSEs, institutions, other corporates,
    QCCPs — and has NO retail limb. Closing that gap is a separate, capital-
    affecting change with its own regulatory review. Until it lands, C 02.00
    must not silently drop RWEA it is required to break down, and reverting to
    the origin class puts the leg exactly where a declined guarantee would have
    left it. Deliberately narrow: only the Art. 151(4) pair is reverted, so a
    genuinely new impossible pair strands visibly rather than being absorbed —
    ``c02._warn_if_a_breakdown_strands`` is the net that catches it on OF 02.00,
    and on OF 08 it keys an off-axis sheet (``sheet_key_expr``).
    """
    retail_under_firb = (pl.col(approach_col) == FIRB) & pl.col(post_ec_col).is_in(
        list(RETAIL_CLASSES)
    )
    return pl.when(retail_under_firb).then(pl.col(origin_ec_col)).otherwise(pl.col(post_ec_col))


def is_sme_expr(cols: set[str]) -> pl.Expr:
    """Whether a leg is SME, from the classifier's sub-class and the ``is_sme`` flag.

    The classifier-derived ``exposure_subclass`` (PRA PS1/26 Art. 147A(1)(e)/(f))
    is the canonical corporate split signal; ``is_sme`` also carries the retail
    split. Unknown is False.
    """
    is_sme = pl.lit(value=False)
    if "exposure_subclass" in cols:
        is_sme = is_sme | (pl.col("exposure_subclass") == "corporate_sme").fill_null(value=False)
    if "is_sme" in cols:
        is_sme = is_sme | pl.col("is_sme").fill_null(value=False)
    return is_sme


def is_financial_large_expr(cols: set[str]) -> pl.Expr:
    """Whether a corporate leg is a "financial corporate or large corporate".

    ``exposure_subclass == "corporate_financial_large"`` (FSE OR revenue above
    the large-corporate threshold) where the classifier sealed it; otherwise the
    financial-sector flag alone. Unknown is False.
    """
    if "exposure_subclass" in cols:
        return (pl.col("exposure_subclass") == "corporate_financial_large").fill_null(value=False)
    if "cp_apply_fi_scalar" in cols:
        return pl.col("cp_apply_fi_scalar").fill_null(value=False)
    if "cp_is_financial_sector_entity" in cols:
        return pl.col("cp_is_financial_sector_entity").fill_null(value=False)
    return pl.lit(value=False)


def is_commercial_expr(cols: set[str]) -> pl.Expr:
    """Whether a retail real-estate leg is secured by COMMERCIAL property."""
    if "property_type" not in cols:
        return pl.lit(value=False)
    return pl.col("property_type").is_in(list(COMMERCIAL_PROPERTY_TYPES)).fill_null(value=False)


# =============================================================================
# Private helpers
# =============================================================================


def _limb_expr(
    limb: Limb, approach: pl.Expr, exposure_class: pl.Expr, flags: dict[str, pl.Expr]
) -> pl.Expr:
    """Whether a leg is in ``limb``. A null approach or class is in none."""
    taken = approach == limb.approach
    if limb.classes is not None:
        taken = taken & exposure_class.is_in(list(limb.classes))
    for name, flag in flags.items():
        wanted = getattr(limb, name)
        if wanted is not None:
            taken = taken & (flag if wanted else flag.not_())
    return taken.fill_null(value=False)
