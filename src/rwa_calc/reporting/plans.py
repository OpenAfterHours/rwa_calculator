"""
Sheet execution plans — the shared container a template is executed FROM.

Pipeline position:
    sealed aggregator-exit ledger -> <template>_plans() -> SheetPlan
        -> {execute() in the generator, drill-down in reporting.lineage}

Key responsibilities:
- Bundle the three things a template sheet is executed from — its
  ``TemplateSpec``, its prepared+partitioned frame, and its ``ReportingContext``
  side inputs — with the post-``execute`` metadata a consumer needs to read a
  rendered cell WITHOUT re-deciding it (the Annex II §1.3 "(-)" negation set,
  and the tolerant-equals terms of any inert/empty rows).

Why this lives OUTSIDE any one template module: a ``SheetPlan`` is the seam
between a template's generator and the lineage drill-down. It was born inside
``corep/c07.py`` (the first instrumented template), but every other template's
``<t>_plans()`` must return the SAME type — otherwise each template's plans
would be typed against C 07.00's dataclass. Hosting it here lets a template
module import it back and lets ``reporting.lineage`` read it, so a cell's spec
has exactly one home.

Two deliberate fail-safe choices (a template silently inheriting the wrong one
is a mis-sign / mis-null defect, so neither is guessed):
- ``negative_cols`` is REQUIRED — no default. A template with no "(-)"-labelled
  deduction columns passes ``frozenset()`` explicitly; nothing inherits
  C 07.00's Annex II deduction set by omission.
- ``row_terms`` defaults to ``{}`` — the safe "null no inert rows" behaviour for
  a template that renders no all-null rows.

References:
- docs/plans/report-cell-lineage.md §4.1 (the SheetPlan extraction)
- Regulation (EU) 2021/451, Annex II §1.3 (the "(-)" sign convention)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.reporting.cellspec import TemplateSpec
    from rwa_calc.reporting.metadata import ReportingContext

# A tolerant-equals membership spec: the ``(column, literal)`` equality pairs a
# row's subset must ALL match. A template that nulls inert/empty rows carries
# these per row ref on the plan; ``None`` marks a structurally inert row (one
# rendered all-null regardless of the data).
type RowTerms = tuple[tuple[str, str | bool], ...]


@dataclass(frozen=True)
class SheetPlan:
    """Everything one template sheet is executed from, plus its post-pass signs.

    ``spec`` + ``frame`` + ``ctx`` ARE the definition of every cell on the
    sheet: ``execute(spec, frame, ctx)`` produces it. Exposing the plan (rather
    than only the rendered frame) lets a consumer that must EXPLAIN a cell — the
    lineage drill-down — read the very same ``CellSpec`` and run the very same
    ``RowPredicate`` over the very same rows the generator used, instead of
    re-deriving the population (a copy that could silently drift from the
    reported figure).

    ``negative_cols`` and ``row_terms`` carry the two post-``execute`` passes
    (the Annex II §1.3 "(-)" negation; the all-null inert rows), so a consumer
    knows a rendered cell's sign and emptiness policy without re-deciding either.
    """

    spec: TemplateSpec
    frame: pl.DataFrame
    ctx: ReportingContext
    negative_cols: frozenset[str]
    row_terms: dict[str, RowTerms | None] = field(default_factory=dict)
