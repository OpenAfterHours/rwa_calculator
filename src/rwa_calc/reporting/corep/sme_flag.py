"""
The SA "of which: SME" discriminator — one definition for C 07.00 and C 09.

Pipeline position:
    sealed aggregator-exit ledger
        -> here (is this leg an exposure to an SME?)
        -> corep/c07.py (``c07_sme``: row 0020 on every sheet; Basel 3.1 rows
           0343 / 0344 on the real-estate sheet)
        -> corep/c09.py (``c09_sme``: the C 09.01 "of which: SME" rows, which
           Annex II defines as "Same definition as for row 0020" of C 07.00, and
           the CRR C 09.02 SME / non-SME rows)

Key responsibilities:
- Read the SME flag off the obligor's SEALED carrier — ``is_sme`` and the
  Basel 3.1 ``exposure_subclass`` (``irb_sheets.is_sme_expr``) — not off the
  exposure-class name.
- Keep the two synthetic-frame rungs (``sme_supporting_factor_eligible``, then
  the class name) for frames that seal neither carrier.

Why not the class name. Row 0020 is "All exposures to SMEs as defined in the
Glossary Part" (PS1/26 Annex II p.88; CRR Annex II C 07.00: "All exposures to
SME"), and rows 0343 / 0344 are "Exposures to SMEs ... within Article 124H" /
"... 124I" (PS1/26 Annex II p.91). The loan-splitter renames an SME obligor's
secured leg ``residential_mortgage`` / ``commercial_mortgage``
(``engine/re_split/splitter.py``) and keeps ``is_sme`` True, and an SME's
specialised-lending exposure keeps the ``specialised_lending`` class with
``is_sme`` True (``engine/classify/subtypes.py``). Reading the class name left
all of those legs out of every SME row; ``sme_supporting_factor_eligible`` — the
old first rung — is never sealed, so on the production ledger the class name
was the only rung that ever fired. The class name stays OR-ed into the sealed
rung, so no leg the old reading counted leaves the rows.

Not covered (a residual of the classifier's ``is_sme``, not of this reading):
``is_sme`` is False for an SME's ADC exposure (Art. 124K keeps the corporate
class) and for a retail-qualifying SME (kept in ``retail_other``), so neither
reaches row 0020.

References:
- PRA PS1/26 Annex II, OF 07.00 row 0020 (p.88), rows 0343 / 0344 (p.91)
- CRR Annex II (COREP), C 07.00 row 0020; C 09.01 rows 0075 / 0085 / 0095
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting.corep import irb_sheets

#: The sealed SME carriers (``contracts/edges.py`` seals both on the aggregator
#: exit). Either one present selects the sealed rung.
_SEALED_SME_CARRIERS: tuple[str, ...] = ("is_sme", "exposure_subclass")

#: The synthetic-frame rung: a supporting-factor eligibility flag no pipeline run
#: produces (``data/schemas.py`` declares it, nothing seals it).
_SYNTHETIC_SME_COL: str = "sme_supporting_factor_eligible"


def sme_exposure_expr(cols: set[str]) -> pl.Expr | None:
    """Whether a leg is an exposure to an SME, as C 07.00 row 0020 reads it.

    The ladder, first rung whose source is present:

    1. ``is_sme`` / ``exposure_subclass`` (sealed): ``irb_sheets.is_sme_expr``,
       OR-ed with the class name when ``exposure_class`` is present.
    2. ``sme_supporting_factor_eligible`` (synthetic unit frames only).
    3. ``exposure_class`` containing ``"sme"`` (synthetic unit frames only).

    Nulls fold to False, so the flag is a non-null Boolean an ``equals`` term can
    match. Returns ``None`` when the frame carries no source at all — the caller
    then derives no column and its presence-tolerant terms match nothing.
    """
    class_name = (
        pl.col("exposure_class").str.contains("sme").fill_null(value=False)
        if "exposure_class" in cols
        else None
    )
    if any(carrier in cols for carrier in _SEALED_SME_CARRIERS):
        sealed = irb_sheets.is_sme_expr(cols)
        return sealed if class_name is None else sealed | class_name
    if _SYNTHETIC_SME_COL in cols:
        return (pl.col(_SYNTHETIC_SME_COL) == True).fill_null(value=False)  # noqa: E712
    return class_name
