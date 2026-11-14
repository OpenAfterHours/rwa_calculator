"""
Contract gate: an ``index.md`` page in the docs nav is either its section's
first child or its own one-page section.

Why this exists
---------------
``zensical.toml`` enables the ``navigation.indexes`` theme feature, under which
Zensical makes the **first** ``index.md`` page directly inside a section that
section's index page -- wherever it sits in the section's list. A section
whose own index is not at position 0 therefore gets a later child promoted in
its place, and two things go wrong silently: that child disappears from the
sidebar, and clicking the section heading opens it. ``zensical build`` exits 0
and no link breaks, so nothing else in the estate notices.

Measured twice, not hypothetical:

- ``reconciliation/index.md`` became the index of the whole "RWA Calculator"
  tab when the nav was split into tabs (fixed by making Reconciliation a
  one-page section; see the comment above it in ``zensical.toml``);
- ``specifications/crr/ccr/index.md``, the 10th child of the "CRR Framework"
  section, had been that section's index since before the tab split: the
  "SA-CCR (Counterparty Credit Risk)" entry was missing from the sidebar and
  the "CRR Framework" heading opened the SA-CCR page.

The first was fixed as prose; the second is why this is now a check.

What this checks, and what it does not
--------------------------------------
Checked, from ``zensical.toml`` alone, with no rendered site: in every nav
section, the first child whose page is named ``index.md`` (bare or titled) is
at position 0. A section with no ``index.md`` child passes -- its heading is a
plain toggle, which is a legitimate choice. The two fixes are a real index
page at position 0, or wrapping the page in a one-page section of its own.

**Not** checked: whether the page at position 0 is a *good* index for the
section, or whether every docs page is in the nav at all. Deliberately
source-based so it runs in the dev loop; the defect is decided entirely by
the nav's shape, so the rendered HTML adds nothing.

References:
- zensical.toml (``nav`` and the ``navigation.indexes`` theme feature)
- docs/specifications/crr/index.md (the index page that closed the CRR case)
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
ZENSICAL_TOML = REPO_ROOT / "zensical.toml"

type NavItem = str | dict[str, str | list[NavItem]]


def test_every_section_index_page_is_first_or_alone() -> None:
    # Arrange
    nav = _load_nav()

    # Act
    misplaced = list(_misplaced_section_indexes(nav))

    # Assert
    assert not misplaced, (
        "Zensical makes the first index.md directly inside a section that "
        "section's index, so each page below is hidden from the sidebar and "
        "opened by its section heading instead. Put a real index page at "
        "position 0 of the section, or wrap the page in a one-page section "
        '(`{ "Title" = [ "path/index.md" ] }`):\n'
        + "\n".join(
            f"  {section}: child {position} is {page}" for section, position, page in misplaced
        )
    )


def test_gate_sees_the_real_nav_sections() -> None:
    # Arrange / Act
    sections = list(_sections(_load_nav(), ()))

    # Assert -- guards against a vacuous pass if the nav moves or is renamed.
    titles = {trail[-1] for trail, _ in sections}
    assert {"RWA Calculator", "Specifications", "CRR Framework", "Basel 3.1 Framework"} <= titles


def test_gate_flags_an_index_page_after_position_zero() -> None:
    # Arrange -- the CRR Framework shape before it had an index page.
    nav: list[NavItem] = [
        {
            "Framework": [
                {"SA Risk Weights": "crr/sa-risk-weights.md"},
                {"SA-CCR": "crr/ccr/index.md"},
                {"SFT": "crr/sft/index.md"},
            ]
        },
        {"Fixed": ["fixed/index.md", {"Other": "fixed/sub/index.md"}]},
        {"One-page": [{"SA-CCR": [{"SA-CCR": "crr/ccr/index.md"}]}]},
    ]

    # Act
    misplaced = list(_misplaced_section_indexes(nav))

    # Assert -- only the first index.md counts, and a one-page section is fine.
    assert misplaced == [("Framework", 1, "crr/ccr/index.md")]


def _load_nav() -> list[NavItem]:
    with ZENSICAL_TOML.open("rb") as fh:
        return tomllib.load(fh)["project"]["nav"]


def _misplaced_section_indexes(nav: list[NavItem]) -> Iterator[tuple[str, int, str]]:
    """Yield (section path, position, page) where a section's first index.md is not first."""
    for trail, children in _sections(nav, ()):
        pages = [_page(child) for child in children]
        position = next(
            (i for i, page in enumerate(pages) if page and PurePosixPath(page).name == "index.md"),
            None,
        )
        if position:
            yield " > ".join(trail), position, str(pages[position])


def _sections(
    items: list[NavItem], trail: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], list[NavItem]]]:
    for item in items:
        if not isinstance(item, dict):
            continue
        for title, value in item.items():
            if isinstance(value, list):
                yield (*trail, title), value
                yield from _sections(value, (*trail, title))


def _page(item: NavItem) -> str | None:
    if isinstance(item, str):
        return item
    values = list(item.values())
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None
