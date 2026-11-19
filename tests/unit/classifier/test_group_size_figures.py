"""
Group size figures: max over the entity and EVERY org ancestor (RC-05 / RC-06).

``hierarchy/graph.py::with_group_size_figures`` puts ``group_annual_revenue``
and ``group_total_assets`` on the counterparty lookup — the highest-consolidation
figures every size test reads (the SME definition, Art. 153(4), Art. 147(4C)(b)(ii),
the Basel 3.1 large-FSE asset test). The ancestors are the org walk's
``ancestor_references`` (``graph.build_ultimate_parent_lazy``, over the
de-duplicated org mappings). The classifier reads them through
``attributes.group_size_exprs`` — ``max(own, group)`` — so a hand-built lookup
without the group columns classifies on its own figures.

RC-06: the figure was max(own, ULTIMATE parent), so an apex with no figures (a
fund, a holding company) hid the consolidating parent beneath it. PS1/26
Art. 147(4C)(b)(ii) takes revenue "at the highest level of consolidation which
is performed and at which audited financial statements are available" — where
the apex has none, the next level that has one.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.classify.attributes import group_size_exprs
from rwa_calc.engine.hierarchy.graph import build_counterparty_lookup, build_ultimate_parent_lazy
from tests.fixtures.raw_bundle import seal_raw_table


def _group_figures(
    org: list[tuple[str, str]], figures: dict[str, tuple[float | None, float | None]]
) -> dict[str, tuple[float | None, float | None]]:
    """Run the hierarchy's counterparty-lookup build; return the group figures by reference."""
    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": list(figures),
            "entity_type": ["corporate"] * len(figures),
            "annual_revenue": [f[0] for f in figures.values()],
            "total_assets": [f[1] for f in figures.values()],
        },
        schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
        },
    )
    org_mappings = pl.LazyFrame(
        {
            "parent_counterparty_reference": [p for p, _c in org],
            "child_counterparty_reference": [c for _p, c in org],
        },
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        },
    )
    lookup, _errors = build_counterparty_lookup(
        seal_raw_table(counterparties, "counterparties"),
        seal_raw_table(org_mappings, "org_mappings"),
        None,
    )
    df = lookup.counterparties.collect()
    return {
        r["counterparty_reference"]: (r["group_annual_revenue"], r["group_total_assets"])
        for r in df.to_dicts()
    }


def test_walk_lists_every_ancestor_parent_first() -> None:
    edges = pl.LazyFrame(
        {
            "child_counterparty_reference": ["SUB", "MIDCO"],
            "parent_counterparty_reference": ["MIDCO", "TOPFUND"],
        }
    )

    walk = build_ultimate_parent_lazy(edges).collect()

    sub = walk.filter(pl.col("counterparty_reference") == "SUB").row(0, named=True)
    assert sub["ancestor_references"] == ["MIDCO", "TOPFUND"]
    assert sub["ultimate_parent_reference"] == "TOPFUND"


def test_null_revenue_apex_does_not_hide_the_mid_level_consolidator() -> None:
    """TOPFUND (no figures) -> MIDCO (1bn / 3bn) -> SUB (300m / 600m): SUB sizes at MIDCO."""
    groups = _group_figures(
        [("TOPFUND", "MIDCO"), ("MIDCO", "SUB")],
        {"TOPFUND": (None, None), "MIDCO": (1e9, 3e9), "SUB": (300e6, 600e6)},
    )

    assert groups["SUB"] == (1e9, 3e9)


def test_group_figure_is_the_max_over_the_chain() -> None:
    """A smaller (data-anomalous) parent figure never lowers the group figure."""
    groups = _group_figures([("P", "SUB")], {"P": (5e6, 10e6), "SUB": (40e6, 20e6)})

    assert groups["SUB"] == (40e6, 20e6)


@pytest.mark.parametrize(
    ("ref", "expected"),
    [("ROOT", (900e6, None)), ("LONE", (12e6, 4e6))],
    ids=["apex", "no-parent"],
)
def test_entity_without_ancestors_keeps_its_own_figures(
    ref: str, expected: tuple[float | None, float | None]
) -> None:
    groups = _group_figures(
        [("ROOT", "SUB")],
        {"ROOT": (900e6, None), "SUB": (10e6, 20e6), "LONE": (12e6, 4e6)},
    )

    assert groups[ref] == expected


def test_lookup_without_group_columns_classifies_on_own_figures() -> None:
    """A hand-built lookup (null group columns): group_size_exprs returns the own figures."""
    frame = pl.LazyFrame(
        {
            "annual_revenue": [50e6],
            "total_assets": [70e6],
            "group_annual_revenue": [None],
            "group_total_assets": [None],
        },
        schema={
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
            "group_annual_revenue": pl.Float64,
            "group_total_assets": pl.Float64,
        },
    )
    revenue, assets = group_size_exprs()

    row = frame.select(revenue.alias("r"), assets.alias("a")).collect().row(0)

    assert row == (50e6, 70e6)
