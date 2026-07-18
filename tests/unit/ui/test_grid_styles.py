"""
Contract: the report-template grid's markup and its stylesheet must agree.

Regulatory templates are wide — up to 49 value columns — and are read on a
desktop. Three CSS behaviours make that usable, and each is invisible to the
HTML assertions elsewhere in the suite (they check classes, not rendering):

1. the report pages opt out of the 1100px reading measure (``container--wide``);
2. the grid is a BOUNDED scroll pane (``grid-wrap`` with a max-height), which is
   what gives ``position: sticky`` a scrollport — without the height cap the
   sticky header simply scrolls away with the page;
3. the row labels are frozen (``rowhead-*`` sticky left), so scrolling right
   does not lose which row you are on.

These tests fail if the stylesheet loses a rule the templates depend on (or vice
versa) — the failure mode being a grid that silently reverts to a narrow,
label-less, unscrollable slab.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATIC = _REPO_ROOT / "src" / "rwa_calc" / "ui" / "app" / "static"
_TEMPLATES = _REPO_ROOT / "src" / "rwa_calc" / "ui" / "app" / "templates"


@pytest.fixture(scope="module")
def css() -> str:
    return (_STATIC / "app.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def grid_html() -> str:
    return (_TEMPLATES / "report_templates.html").read_text(encoding="utf-8")


def test_report_pages_opt_out_of_the_reading_measure(css: str, grid_html: str) -> None:
    # Assert — prose keeps its measure; the return uses the whole desktop.
    assert "{% block container_mod %}container--wide{% endblock %}" in grid_html
    assert re.search(r"\.container--wide\s*\{[^}]*max-width:\s*none", css)


def test_the_grid_is_a_bounded_scroll_pane(css: str, grid_html: str) -> None:
    # Assert — the height cap is what makes `position: sticky` work at all.
    assert 'class="grid-wrap"' in grid_html
    rule = re.search(r"\.grid-wrap\s*\{([^}]*)\}", css)
    assert rule is not None
    body = rule.group(1)
    assert "overflow: auto" in body
    assert "max-height" in body


def test_the_row_labels_are_frozen(css: str, grid_html: str) -> None:
    # Assert — scrolling right must not lose which row you are on.
    assert 'class="mono rowhead-ref"' in grid_html
    assert 'class="rowhead-name"' in grid_html
    frozen = re.search(
        r"table\.data\.grid \.rowhead-ref,\s*table\.data\.grid \.rowhead-name\s*\{([^}]*)\}", css
    )
    assert frozen is not None
    assert "position: sticky" in frozen.group(1)
    assert re.search(r"\.rowhead-ref\s*\{[^}]*left:\s*0", css)


def test_the_two_header_rows_stack_instead_of_overlapping(css: str, grid_html: str) -> None:
    # Assert — the group band pins to the top and the ref row sits UNDER it; a
    # shared top:0 would stack them on the same line.
    assert '<tr class="band">' in grid_html
    assert 'class="refs' in grid_html
    assert re.search(r"thead tr\.band th\s*\{[^}]*top:\s*0", css)
    ref_row = re.search(r"thead tr\.refs th\s*\{([^}]*)\}", css)
    assert ref_row is not None
    assert re.search(r"top:\s*(?!0\b)\d", ref_row.group(1)), "the ref row must clear the band"
    # A template with no group band puts its ref row back at the top.
    assert re.search(r"thead tr\.refs--only th\s*\{[^}]*top:\s*0", css)


def test_numeric_cells_align_column_wise(css: str) -> None:
    # Assert — tabular numerals keep digits in columns when scanning a return.
    assert re.search(r"table\.data\.grid td\.num\s*\{[^}]*tabular-nums", css)
