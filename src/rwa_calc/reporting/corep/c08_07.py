"""
COREP C 08.07 / OF 08.07 — IRB scope of use, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> _c08_07_prepared() -> one TemplateSpec over
    the FULL population -> cellspec.execute() -> one DataFrame | None

Cell semantics (recorded decisions):

- The population is the FULL results frame — SA enters every denominator, a null
  approach falls to SA, and slotting counts as IRB (the pinned
  ``C08_07_IRB_APPROACHES``). The sheet key is the RAW ``exposure_class``: this is
  the one COREP sheet deliberately NOT retargeted to the applied ladder, because
  the Art. 147 origination taxonomy has no "defaulted" class.
- The ROW AXIS differs by framework. CRR keys the Art. 147(2) exposure classes
  with a whole-population Total on row 0170. OF 08.07 keys the EIGHT
  Art. 147B(1) ROLL-OUT CLASSES on rows 0180-0250, with the Total on row 0260 and
  the aggregate permanent-partial-use materiality percentage on row 0270 — and
  that Total is the SUM OF THOSE EIGHT ROWS, not the whole population, so
  sovereigns (which have no roll-out class at all under PS1/26), equity and other
  non-credit obligation assets sit outside it. Rows 0200/0240 (purchased
  receivables) are roll-out classes with no counterpart in our Art. 147(2)
  taxonomy and render structurally null, as do CRR's 0060/0100/0130.
  PS1/26 Annex II §3.3.10.2 rows: "0260 TOTAL — Institutions shall report the sum
  of the values reported in rows 0180-0250 for each of columns 0060-0150";
  boe_b0779 states the same identity.
- Cols 0030/0040/0050 are DPM FRACTIONS, not 0-100 percentages — see
  ``_pct_ppu`` for the instruction text and the published bounds.
- Col 0040 ("% subject to a roll-out plan", CRR Art. 148) carves the roll-out
  slice out of the SA coverage: the SA-treated legs (``~c0807_irb``) flagged by
  the optional ``is_under_irb_rollout`` INPUT column go to 0040 and col 0030 drops
  to permanent-partial-use only (Art. 150), preserving 0030 + 0040 == the whole SA
  share. Absent the input column the slice is empty, 0040 = 0.0 and 0030 keeps the
  whole SA share. Col 0040 first carries the roll-out EAD Sum and is rescaled to a
  fraction post-execute (``_c08_07_rollout_pct``).
- Empty real-class rows stay 0.0 — the opposite of C 07.00's empty-subset rule;
  only the FIXED structural-null set is nulled (``_null_fixed_rows``). The B31
  materiality columns 0160-0180 are always null (the retired
  ``output_floor_config`` gate was dead code, recorded).
- Lineage-instrumented (R22, single frame): ``c08_07_plans`` exposes the one
  full-population plan; the two post-execute passes (the col-0040 rescale and
  ``_null_fixed_rows``) live on the REPORTED frame (``c08_07_frames``), which the
  drill-down reads a cell's ``cell_value`` from — so col 0040 shows its rescaled
  fraction and the fixed-null rows read null, never contradicting the sheet.

Extracted from ``corep/c08.py`` (which hosts C 08.01-06) — the per-template split
that module's docstring records as the honest long-term answer, taken here first
because C 08.07 shares none of the C 08.01/02 value surface.

References:
- CRR Art. 143/148/150 (IRB permission, roll-out, permanent partial use);
  PS1/26 Art. 147B (roll-out classes), Art. 150(1A) (materiality)
- COREP Annex II §3.3.6 (C 08.07); PRA PS1/26 Annex II §3.3.10 (OF 08.07)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.corep.templates import (
    C08_07_IRB_APPROACHES,
    get_c08_07_columns,
    get_c08_07_row_unions,
    get_c08_07_rows,
)
from rwa_calc.reporting.kernel import pick
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

# Single-frame lineage key: C 08.07 has no sheet axis, so its one plan keys
# under a canonical name (see reporting.plans / _resolve_sheet_key single_frame).
_C08_07_SHEET_KEY = "c08_07"

_Terms = tuple[tuple[str, str | bool], ...]


class _Row:
    """Minimal TemplateRow for the framework-specific row axis."""

    __slots__ = ("name", "ref")

    def __init__(self, ref: str, name: str) -> None:
        self.ref = ref
        self.name = name


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


@cites("CRR Art. 148")
@cites("PS1/26, paragraph 1.3")
def generate_c08_07(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute C 08.07 / OF 08.07 over the FULL results population.

    SA and IRB both enter (the IRB side is ``approach_applied`` membership
    in the pinned ``C08_07_IRB_APPROACHES`` — slotting counts as IRB; a
    null approach falls to SA); the coverage shares (cols 0030/0040/0050) are
    intra-row formulas guarding a zero denominator to 0.0 and are reported as DPM
    FRACTIONS, not 0-100 percentages (``_pct_ppu``). Col 0040 ("% subject to a
    roll-out plan", CRR Art. 148) is the SA-treated slice flagged by the
    optional ``is_under_irb_rollout`` INPUT column, carved out of col 0030
    (permanent partial use, Art. 150) so 0030 + 0040 == the whole SA coverage;
    with no roll-out input col 0040 is 0.0 and 0030 keeps the whole SA share.
    Rows with no exposure class binding (and no aggregate rule) render ALL-NULL;
    empty real-class rows stay 0.0 — the opposite split from C 07.00. The B31
    materiality columns 0160-0180 are structurally null regardless of reporting
    basis (the retired ``output_floor_config`` gate was dead code).
    """
    prepared = _c08_07_prepared(results, cols, framework, errors)
    if prepared is None:
        return None
    spec, data, null_rows = prepared
    frame = execute(spec, data)
    frame = _c08_07_rollout_pct(frame)
    return _null_fixed_rows(frame, null_rows)


def _c08_07_prepared(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> tuple[TemplateSpec, pl.DataFrame, list[str]] | None:
    """Collect + derive the C 08.07 discriminators and build its spec.

    Shared by ``generate_c08_07`` (the reported frame, which re-applies the two
    post-execute passes) and ``c08_07_plans`` (the lineage plan). Returns
    ``None`` on the imperative generator's early exits (missing columns / empty
    population), recording the same error string.
    """
    ead_col = pick(cols, "ead_final")
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    # Recorded basis: C 08.07 keys the RAW class over the FULL population
    # (Art. 147 origination taxonomy has no "defaulted" class) — the one
    # COREP sheet key deliberately NOT retargeted to the applied ladder.
    ec_col = pick(cols, "exposure_class")
    if ead_col is None or approach_col is None or ec_col is None:
        missing = [
            name
            for name, value in (("ead", ead_col), ("approach", approach_col), ("class", ec_col))
            if value is None
        ]
        errors.append(f"C 08.07: missing columns: {', '.join(missing)}")
        return None
    data = results.collect()
    if data.height == 0:
        return None
    data = data.with_columns(
        pl.col(approach_col).is_in(sorted(C08_07_IRB_APPROACHES)).alias("c0807_irb")
    )
    # CRR Art. 148/150 roll-out-plan discriminator (col 0040): an SA-treated leg
    # (``~c0807_irb``) that the firm's approved sequential-implementation plan
    # schedules to move to IRB. Derived ONLY when the optional input flag is
    # present — an absent flag leaves ``c0807_rollout`` off the frame, so the
    # tolerant col-0040 predicate matches nothing (0.0) and col 0030 keeps the
    # whole SA share, byte-identical to the pre-R14 output.
    rollout_col = pick(cols, "is_under_irb_rollout")
    if rollout_col is not None:
        data = data.with_columns(
            (~pl.col("c0807_irb") & pl.col(rollout_col).fill_null(value=False)).alias(
                "c0807_rollout"
            )
        )
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    row_defs = get_c08_07_rows(framework)
    spec, null_rows = _c08_07_spec(row_defs, ec_col, ead_col, rwa_col, framework)
    return spec, data, null_rows


def c08_07_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single C 08.07 execution plan for lineage (single frame).

    C 08.07 has no sheet axis, so its one plan keys under the canonical
    single-frame key. The plan frame is the FULL prepared population (carrying
    the derived ``c0807_irb`` / ``c0807_rollout`` discriminators) and each cell's
    own predicate narrows it. C 08.07 has no "(-)"-labelled deduction column, so
    ``negative_cols`` is empty. The two post-execute passes
    (``_c08_07_rollout_pct`` rescaling col 0040 to a percentage,
    ``_null_fixed_rows`` on the structural-null rows) live on the REPORTED frame
    (``c08_07_frames`` / ``generate_c08_07``): the drill-down reads a cell's
    ``cell_value`` from there, so col 0040 shows its rescaled percentage and the
    fixed-null rows read null (they carry no cell binding — an ``unbound`` cell),
    never contradicting the sheet. Preserves the generator's error contract via
    ``_c08_07_prepared``.
    """
    prepared = _c08_07_prepared(results, cols, framework, errors)
    if prepared is None:
        return {}
    spec, data, _null_rows = prepared
    return {
        _C08_07_SHEET_KEY: SheetPlan(
            spec=spec, frame=data, ctx=ReportingContext(), negative_cols=frozenset()
        )
    }


def c08_07_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single C 08.07 frame for lineage (keyed like ``c08_07_plans``).

    Wraps ``generate_c08_07`` under the single-frame key so a cell's reported
    value carries the two post-execute passes the plan does not — the lineage
    drill-down reads ``cell_value`` from HERE, so it honours the rescaled col
    0040 and the nulled structural rows."""
    frame = generate_c08_07(results, cols, framework, errors)
    return {_C08_07_SHEET_KEY: frame} if frame is not None else {}


def _c08_07_spec(
    row_defs: list[tuple[str, str, str | None]],
    ec_col: str,
    ead_col: str,
    rwa_col: str | None,
    framework: str,
) -> tuple[TemplateSpec, list[str]]:
    """The C 08.07 spec + the fixed structural-null row set (CRR 0060/0100/
    0130; B31 0200/0240/0270 — rows with neither a class binding nor an
    aggregate rule).

    Row bindings resolve in three steps: a row definition's own exposure class;
    else a display aggregate from ``get_c08_07_row_unions`` (CRR's "Retail" row,
    B31's combined-corporates roll-out class and its Total); else — only under
    CRR — the whole-population Total row. CRR's Total (0170) spans every exposure
    class; B31's Total (0260) is the SUM of the eight Art. 147B(1) roll-out class
    rows and therefore excludes sovereigns, equity and other non-credit
    obligation assets, which have no roll-out class (PS1/26 Annex II §3.3.10.2:
    "0260 TOTAL — Institutions shall report the sum of the values reported in
    rows 0180-0250 for each of columns 0060-0150")."""
    is_b31 = framework == "BASEL_3_1"
    column_refs = tuple(col.ref for col in get_c08_07_columns(framework))
    rows = tuple(_Row(row_def[0], row_def[1]) for row_def in row_defs)
    row_unions = get_c08_07_row_unions(framework)
    cells: dict[tuple[str, str], CellSpec] = {}
    null_rows: list[str] = []
    for row_ref, row_name, ec_value in row_defs:
        union: tuple[RowPredicate, ...] = ()
        if ec_value is not None:
            class_terms: _Terms = ((ec_col, ec_value),)
        elif row_ref in row_unions:
            class_terms = ()
            union = tuple(
                RowPredicate(equals=((ec_col, ec),)) for ec in sorted(row_unions[row_ref])
            )
        elif row_name == "Total":
            class_terms = ()
        else:
            null_rows.append(row_ref)
            continue
        total_pred = RowPredicate(equals=class_terms, any_of=union)
        irb_pred = RowPredicate(equals=(*class_terms, ("c0807_irb", True)), any_of=union)
        rollout_pred = RowPredicate(equals=(*class_terms, ("c0807_rollout", True)), any_of=union)
        cells[(row_ref, "0010")] = CellSpec(Sum(ead_col), predicate=irb_pred)
        cells[(row_ref, "0020")] = CellSpec(Sum(ead_col), predicate=total_pred)
        # Col 0040 first carries the roll-out-plan EAD (SA-treated AND under an
        # Art. 148 plan); ``_c08_07_rollout_pct`` rescales it to a percentage of
        # the row total post-execute. A frame without ``c0807_rollout`` makes the
        # tolerant predicate match nothing -> 0.0 (permanent-partial-use only).
        cells[(row_ref, "0040")] = CellSpec(Sum(ead_col), predicate=rollout_pred)
        cells[(row_ref, "0030")] = CellSpec(Formula(refs=("0010", "0020", "0040"), fn=_pct_ppu))
        cells[(row_ref, "0050")] = CellSpec(Formula(refs=("0010", "0020"), fn=_pct_irb))
        if is_b31:
            if rwa_col is not None:
                cells[(row_ref, "0060")] = CellSpec(Sum(rwa_col), predicate=total_pred)
                cells[(row_ref, "0150")] = CellSpec(Sum(rwa_col), predicate=irb_pred)
                cells[(row_ref, "0140")] = CellSpec(Formula(refs=("0060", "0150"), fn=_sa_rwea))
            for ref in ("0160", "0170", "0180"):
                cells[(row_ref, ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
    spec = TemplateSpec(
        name="c08_07", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, null_rows


def _pct_ppu(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0030 = SA share subject to PERMANENT PARTIAL USE, as a DPM FRACTION (0.0
    on a zero denominator): the SA EAD (row total 0020 minus IRB 0010) EXCLUDING
    the roll-out-plan slice (col 0040, still the raw EAD Sum when this formula
    runs). 0030 + 0040 == the total SA coverage, so the aggregate the pre-R14 col
    0030 reported is preserved; with no roll-out data col 0040 is 0.0 and 0030
    reduces to the whole SA share (``x - 0.0 == x``).
    Art. 148 (roll-out plans) vs Art. 150 (permanent partial use).

    UNITS (recorded): the column label carries "(%)" but the DPM datapoint is a
    percent-typed fact carrying the RATIO, not a 0-100 figure — both instruction
    sets say to report the quotient itself ("Institutions shall calculate this
    percentage by dividing (1) by (2)", PS1/26 Annex II §3.3.10.2 col 0030; "the
    exposure subject to the Standardised approach before CRM OVER the total
    exposure in that exposure class in column 0020", COREP Annex II §3.3.6.2 col
    0030), and the published rules bound the cell at 1, not 100 (EBA v09769_m
    ``{c0030} <= 1``, v09771_m ``{c0050} <= 1``, v09796_m and boe_b0778
    ``{c0030} + {c0040} + {c0050} = 1``). The retired ``* 100.0`` reported
    100.0/27.54/72.46 where the DPM wanted 1.0/0.2754/0.7246."""
    total = cells["0020"] or 0.0
    if total <= 0:
        return 0.0
    return (total - (cells["0010"] or 0.0) - (cells["0040"] or 0.0)) / total


def _pct_irb(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0050 = IRB share of the row's EAD, as a DPM fraction (0.0 on a zero
    denominator — see ``_pct_ppu`` for the units basis)."""
    total = cells["0020"] or 0.0
    if total <= 0:
        return 0.0
    return (cells["0010"] or 0.0) / total


def _c08_07_rollout_pct(frame: pl.DataFrame) -> pl.DataFrame:
    """Rescale C 08.07 col 0040 from the roll-out-plan EAD (the Sum bound in the
    spec) to its DPM fraction of the row total (col 0020), guarding a zero
    denominator to 0.0 — the executor has no verb for "share of another
    cell", so it is derived here post-execute. Col 0030 already excludes this
    slice (``_pct_ppu``), so 0030 + 0040 == the row's total SA coverage. A
    no-op when no roll-out data is present (col 0040 EAD is 0.0). The units are
    the ratio, not 0-100 — see ``_pct_ppu``."""
    if "0040" not in frame.columns or "0020" not in frame.columns:
        return frame
    total = pl.col("0020")
    pct = pl.when(total > 0).then(pl.col("0040") / total).otherwise(0.0)
    return frame.with_columns(pct.alias("0040"))


def _sa_rwea(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """B31 0140 = SA RWEA lumped as "other" (total 0060 minus IRB 0150 —
    no ``sa_use_reason`` carrier exists, so 0070-0130 stay 0.0 and the
    additive identity 0060 = Σ(0070..0140) + 0150 holds by construction)."""
    return (cells["0060"] or 0.0) - (cells["0150"] or 0.0)


def _null_fixed_rows(frame: pl.DataFrame, row_refs: list[str]) -> pl.DataFrame:
    """Render a FIXED row set all-null (the C 08.07 structural rows — NOT
    empty-subset detection: empty real-class rows must stay 0.0)."""
    if not row_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(row_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )
