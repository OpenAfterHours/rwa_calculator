"""Declarative C 08.03 cell bindings.

Kept separate from the wider C 08 family module so the explicit origin/post-CRM
column matrix remains reviewable without growing that already-large module.

THE ROW AXIS IS PART OF THAT MATRIX, AND IT IS A DELIBERATE DEPARTURE FROM THE
PUBLISHED ROW INSTRUCTION. MUST NOT BE "FIXED" BACK.

Both rulebooks say the opposite in as many words. Reg (EU) 2021/451 Annex II,
C 08.03 rows: "Exposures shall be allocated to an appropriate bucket of the
fixed PD range based on the PD estimated for each obligor assigned to this
exposure class (WITHOUT CONSIDERING ANY SUBSTITUTION EFFECTS DUE TO CRM)".
PS1/26 Annex II section 3.3.5.2 repeats it with an added pre-input-floor
carve-out.

Read literally, that clause holds the WHOLE template on the obligor basis. That
is not what this template does, and not what C 07.00 / C 08.01 / C 08.02 do:
cols 0040-0100 already follow the resultant obligor to the GUARANTOR's sheet
(EBA Q&A 2023_6718), so honouring the clause on the row axis alone reports a
guarantor's exposure value, PD, LGD, RWEA and EL against a BORROWER's PD band.
Measured on the CRM-substitution portfolio under CRR before the change:

- ``institution`` row 0060 ("0.50 to <0.75") reported ``0050 = 0.30%``;
- ``retail_other`` row 0060 reported ``0050 = 2.00%``;
- ``corporate`` row 0080 ("0.75 to <1.75") reported ``0050 = 0.69%``.

Three bands whose reported average PD sat outside the band's own range. And
where a guarantee changes the PD WITHOUT changing the exposure class (fixture
S5: 0.90% obligor, 0.45% guarantor, both corporate) the row axis was the only
place the benefit could have shown, so honouring the clause made a real,
capital-reducing guarantee invisible in the PD breakdown entirely.

THE ELECTION: the row axis is part of the post-CRM column block's own basis and
travels with it. A band is only ever asserted about the PD that produced the
numbers reported against it. What the clause still governs is kept — the origin
columns band on the obligor's own pre-substitution PD, unchanged — and so is the
part of it that is orthogonal to substitution: BOTH bases band on the
PRE-INPUT-FLOOR PD under Basel 3.1, which is why the engine seals
``reporting_pd_post_crm_pre_floor`` alongside ``reporting_pd_post_crm`` instead
of banding the post limb on a floored value.

C 08.02 DOES NOT MOVE WITH THIS AND CANNOT. Its axis is the obligor GRADE
string, and the ledger carries no guarantor grade (R12), so an arrived leg stays
on that template's "Unassigned" residual row. C 08.03's axis is a PD, and the
guarantor's PD is sealed per leg — which is the whole reason the treatment is
available here and not there.
"""

from __future__ import annotations

from collections.abc import Mapping

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Formula,
    RowPredicate,
    SafeSum,
    Sum,
    WeightedAvg,
)

_IRB_RETAIL_CLASSES: frozenset[str] = frozenset({"retail_mortgage", "retail_qrre", "retail_other"})


def _null(_cells: Mapping[str, float | None], _prior_available: bool) -> None:
    return None


def build_c08_03_cells(  # noqa: PLR0913 - the complete C 08.03 column surface
    band_rows: list[tuple[str, str, str, str]],
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    pd_report_col: str,
    lgd_col: str | None,
    exposure_class: str,
    basis_origin: str,
    basis_post: str,
) -> dict[tuple[str, str], CellSpec]:
    """Build every C 08.03 cell on its prescribed origin or post-CRM basis.

    Each row carries TWO term columns, not one: ``origin_col`` bands a leg on
    its obligor's own PD and ``post_col`` on the PD that actually risk-weighted
    it (``pd_scale.banded_rows_by_basis``). A cell reads whichever pairs with
    its basis, so a beneficial guarantee that changes only the PD — leaving the
    exposure class alone — still moves its exposure value and RWEA to the
    guarantor's band while the obligor's gross stays put.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, label, origin_col, post_col in band_rows:
        origin_member = RowPredicate(equals=((basis_origin, True), (origin_col, label)))
        post_member = RowPredicate(equals=((basis_post, True), (post_col, label)))
        cells[(ref, "0010")] = CellSpec(Sum("reporting_gross_on_bs"), predicate=origin_member)
        cells[(ref, "0020")] = CellSpec(Sum("reporting_gross_off_bs"), predicate=origin_member)
        cells[(ref, "0030")] = CellSpec(
            WeightedAvg("ccf", weight="reporting_gross_off_bs"),
            predicate=origin_member,
            empty_cell="null",
        )
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=post_member)
        cells[(ref, "0050")] = CellSpec(
            WeightedAvg(pd_report_col, weight=ead_col),
            predicate=post_member,
            empty_cell="null",
        )
        # The obligor COUNT is reported against the PRE-CRM counterparty and is
        # the one column of EBA Q&A 2023_6718's list (0040, 0050, 0060, 0070,
        # 0080) that deliberately does NOT move to the post basis. Recorded
        # decision — see the C 08.03 bullet in ``corep/c08.py``'s module
        # docstring before changing this predicate.
        cells[(ref, "0060")] = (
            CellSpec(Count("counterparty_reference", distinct=True), predicate=origin_member)
            if "counterparty_reference" in cols
            else CellSpec(Count("exposure_reference"), predicate=origin_member)
        )
        cells[(ref, "0070")] = (
            CellSpec(
                WeightedAvg(lgd_col, weight=ead_col),
                predicate=post_member,
                empty_cell="null",
            )
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_null))
        )
        cells[(ref, "0080")] = (
            CellSpec(Formula(refs=(), fn=_null))
            if exposure_class in _IRB_RETAIL_CLASSES
            else CellSpec(
                WeightedAvg("irb_maturity_m", weight=ead_col),
                predicate=post_member,
                empty_cell="null",
            )
        )
        cells[(ref, "0090")] = CellSpec(Sum(rwa_col), predicate=post_member)
        # Expected loss is calculated after CRM substitution and therefore
        # follows the resultant obligor, alongside EAD and RWEA.  Keeping it on
        # the origin predicate reports the covered leg against the borrower
        # instead of the protection provider (EBA Q&A 2023_6718).
        cells[(ref, "0100")] = CellSpec(Sum("expected_loss"), predicate=post_member)
        cells[(ref, "0110")] = CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")),
            predicate=origin_member,
        )
    return cells
