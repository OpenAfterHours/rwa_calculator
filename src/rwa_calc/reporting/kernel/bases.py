"""
The two-basis (origin / post-substitution) discriminators shared by C 07.00 and C 08.01.

Pipeline position:
    sealed aggregator-exit ledger -> {c07_plans, c08_01_plans} -> the derived
    flag columns every basis-split cell predicate reads -> cellspec.execute()

Key responsibilities:
- Derive the two POPULATION-membership flags for one template (the obligor's
  own approach book, and the same book measured on the sealed
  post-substitution approach).
- Derive the two SHEET keys (the obligor's class, and the guarantor's).
- Build the sheet AXIS as the union of both bases, and tag one sheet's frame
  with which basis each leg sits on.
- Say which risk weight the ORIGIN basis reports a substituted leg at.

WHY EVERY SHEET IS TWO POPULATIONS. Annex II makes the front of C 07.00 /
C 08.01 and the back of them answer different questions. The gross exposure and
the CRM substitution block belong to the OBLIGOR's book — that is where the
covered part is "deducted from the obligor's exposure class" — while the
exposure value and the RWEA are defined "after taking into account ... ALL
CREDIT RISK MITIGANTS", and substitution is a credit risk mitigant, so the
covered part must leave the obligor's sheet and land on the protection
provider's. One frame per sheet carrying both populations, each leg tagged,
lets one cell read the obligor's own book while its neighbour reads the
post-substitution one.

WHY DERIVED BOOLEAN COLUMNS AND NOT ``RowPredicate`` FIELDS. ``classes`` /
``classes_origin`` are per-CELL keys against the sealed ledger, while a basis is
a per-SHEET question ("is this leg on THIS sheet, on THIS basis?") answered
against a class that varies sheet by sheet. Expressing it as derived booleans
keeps ONE spec shared across every sheet, keeps the population definition in one
place, and — decisively — lets the post basis DEGRADE to the origin basis on a
frame that seals no post-substitution columns. A strict predicate term cannot
degrade: it would either raise on the missing column or (as a tolerant
``equals``) silently zero the exposure-value and RWEA columns of every synthetic
unit frame in the COREP / Pillar 3 estate.

THE RISK WEIGHT IS PER BASIS TOO. A leg Art. 235 substitution moved carries the
PROTECTOR's weight in ``risk_weight``, and the obligor's own weight before
substitution in ``pre_crm_risk_weight`` (``engine/sa/rw_adjustments.py::
apply_guarantee_substitution``). The origin basis reports the obligor's own book,
so a template that rows its origin cells by risk weight (C 07.00 rows 0140-0280)
reads the obligor's weight there and the protector's on the post basis:
``origin_risk_weight``. Gated on the protection having been APPLIED
(``is_guarantee_beneficial``, null-safe) rather than on the two weights merely
differing: ``pre_crm_risk_weight`` is captured before the Art. 123B currency
mismatch multiplier, so on an unprotected multiplied leg the two differ too.

References:
- Reg (EU) 2021/451 Annex II: C 07.00 cols 0090/0100/0200, C 08.01 cols
  0070/0080/0110/0260
- PRA PS1/26 Annex II: OF 07.00 / OF 08.01, same column blocks
- CRR Art. 235 (risk-weight substitution), Art. 161 (parameter substitution)
- PRA PS1/26 Annex II OF 07.00 cols 0010 / 0090-0100 and rows 0140-0280 (pp.81, 84, 94)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

if TYPE_CHECKING:
    from collections.abc import Callable

# The sealed post-substitution twins the post basis reads (``reporting_class`` =
# the guarantor's class on a beneficially-guaranteed leg, ``reporting_approach``
# = the approach that leg is treated under). Absent -> post degrades to origin.
POST_CLASS_SOURCE: str = "reporting_class"
POST_APPROACH_SOURCE: str = "reporting_approach"
ORIGIN_APPROACH_SOURCE: str = "reporting_approach_origin"

# The obligor's own risk weight before Art. 235 substitution, and the flag saying
# the substitution was applied. Both CONDITIONAL on the aggregator exit (present
# only where the guarantee step ran), so every read is presence-guarded.
PRE_SUBSTITUTION_RW_SOURCE: str = "pre_crm_risk_weight"
SUBSTITUTION_APPLIED_SOURCE: str = "is_guarantee_beneficial"


@dataclass(frozen=True)
class TwoBasis:
    """The six derived-column names carrying one template's two-basis split.

    ``prefix`` is the template's own column namespace (``"c07"`` / ``"c08"``), so
    two templates materialising both bases on the same frame cannot collide.
    """

    prefix: str

    @property
    def pop_origin(self) -> str:
        """Membership of the ORIGIN-approach population (frame-wide)."""
        return f"{self.prefix}_pop_origin"

    @property
    def pop_post(self) -> str:
        """Membership of the POST-substitution population (frame-wide)."""
        return f"{self.prefix}_pop_post"

    @property
    def class_origin(self) -> str:
        """The obligor's sheet key."""
        return f"{self.prefix}_class_origin"

    @property
    def class_post(self) -> str:
        """The guarantor's sheet key."""
        return f"{self.prefix}_class_post"

    @property
    def basis_origin(self) -> str:
        """Per-SHEET: in the origin population AND keyed to THIS sheet."""
        return f"{self.prefix}_basis_origin"

    @property
    def basis_post(self) -> str:
        """Per-SHEET: in the post population AND keyed to THIS sheet."""
        return f"{self.prefix}_basis_post"


def population_flags(
    basis: TwoBasis,
    cols: set[str],
    approaches: tuple[str, ...],
    *,
    admit: pl.Expr | None = None,
) -> list[pl.Expr]:
    """The two population-membership flags for a template keyed on *approaches*.

    Mirrors ``filter_by_approach``'s missing-column rule — no approach
    discriminator means an EMPTY population, never a silent pass-through. The
    post limb falls back to the ORIGIN approach when no post-substitution
    approach is sealed, so a synthetic frame reports the same figures under both
    bases instead of zeroing its exposure-value columns.

    ``admit`` is an optional extra limb admitted to BOTH bases regardless of
    approach (C 07.00's counterparty-credit-risk rows: substitution does not
    move them, so they belong to both populations).
    """
    origin = _in_approaches(cols, ORIGIN_APPROACH_SOURCE, approaches)
    post = (
        _in_approaches(cols, POST_APPROACH_SOURCE, approaches)
        if POST_APPROACH_SOURCE in cols
        else origin
    )
    if admit is not None:
        origin, post = origin | admit, post | admit
    return [origin.alias(basis.pop_origin), post.alias(basis.pop_post)]


def class_keys(
    basis: TwoBasis,
    cols: set[str],
    origin_class_col: str,
    *,
    key: Callable[[str], pl.Expr] | None = None,
) -> list[pl.Expr]:
    """The two sheet keys, degrading the post key to the origin key.

    ``key`` is the template's own sheet-key transform applied to BOTH keys (C
    07.00 merges specialised lending into corporate under Art. 112 Table A2, so
    an SL guarantor keys a sheet that template actually has); ``None`` keys the
    raw class. Degrading the post key on a frame sealing no ``reporting_class``
    is what makes the split number-neutral wherever nothing substitutes.
    """
    post_col = POST_CLASS_SOURCE if POST_CLASS_SOURCE in cols else origin_class_col
    shape = key if key is not None else pl.col
    return [
        shape(origin_class_col).alias(basis.class_origin),
        shape(post_col).alias(basis.class_post),
    ]


def sheet_axis(basis: TwoBasis, data: pl.DataFrame) -> set[str]:
    """The sheet keys BOTH bases contribute (a null key partitions into NO sheet).

    The post-basis limb is belt-and-braces where the caller also unions in the
    substitution inflow keys — a beneficially-substituted leg's guarantor class
    is an inflow key too. Without it, a leg whose inflow the Annex II block cap
    shed to zero would drop its exposure value and RWEA out of the template
    silently.
    """
    keys: set[str] = set()
    for population, class_col in (
        (basis.pop_origin, basis.class_origin),
        (basis.pop_post, basis.class_post),
    ):
        keys |= set(data.filter(pl.col(population))[class_col].drop_nulls().unique().to_list())
    return keys


def sheet_frame(
    basis: TwoBasis, data: pl.DataFrame, exposure_class: str, *, keep: str | None = None
) -> pl.DataFrame:
    """One sheet's frame: the legs on it under EITHER basis, each tagged with which.

    A leg on neither basis is dropped, so the frame is never wider than the
    sheet, and every cell predicate carries its own basis flag — an unflagged
    predicate would silently sum both populations.

    ``keep`` names a boolean column of ``data`` whose legs the sheet also keeps
    although neither basis puts them on it: C 07.00's memorandum legs
    (``corep/c07_sheet_scope.py``), read only by the cells whose predicate names
    their own flag. Both basis flags are False on such a leg.
    """
    tagged = data.with_columns(
        (pl.col(basis.pop_origin) & (pl.col(basis.class_origin) == exposure_class))
        .fill_null(value=False)
        .alias(basis.basis_origin),
        (pl.col(basis.pop_post) & (pl.col(basis.class_post) == exposure_class))
        .fill_null(value=False)
        .alias(basis.basis_post),
    )
    on_sheet = pl.col(basis.basis_origin) | pl.col(basis.basis_post)
    if keep is not None:
        on_sheet = on_sheet | pl.col(keep)
    return tagged.filter(on_sheet)


@cites("CRR Art. 235")
def substituted_leg(cols: set[str]) -> pl.Expr | None:
    """True on a leg Art. 235 substitution was applied to, with its own weight recorded.

    ``None`` on a frame that seals either column (a run with no guarantee, a
    synthetic unit frame): nothing on it was substituted. Null-safe: an unknown
    benefit is not a substitution, and a leg with no recorded own weight has no
    other weight to report at.
    """
    if not {SUBSTITUTION_APPLIED_SOURCE, PRE_SUBSTITUTION_RW_SOURCE} <= cols:
        return None
    applied = pl.col(SUBSTITUTION_APPLIED_SOURCE).fill_null(value=False)
    return (applied & pl.col(PRE_SUBSTITUTION_RW_SOURCE).is_not_null()).fill_null(value=False)


@cites("CRR Art. 235")
def origin_risk_weight(cols: set[str], post_weight: pl.Expr) -> pl.Expr:
    """The risk weight the ORIGIN basis reports a leg at (module docstring).

    The obligor's own pre-substitution weight on a ``substituted_leg``;
    ``post_weight`` — the weight the post basis reports it at — on every other.
    """
    substituted = substituted_leg(cols)
    if substituted is None:
        return post_weight
    return pl.when(substituted).then(pl.col(PRE_SUBSTITUTION_RW_SOURCE)).otherwise(post_weight)


def _in_approaches(cols: set[str], approach_col: str, approaches: tuple[str, ...]) -> pl.Expr:
    """Is this leg in *approaches* under ``approach_col``? (Absent column = no.)"""
    if approach_col not in cols:
        return pl.lit(value=False)
    return pl.col(approach_col).is_in(list(approaches)).fill_null(value=False)
