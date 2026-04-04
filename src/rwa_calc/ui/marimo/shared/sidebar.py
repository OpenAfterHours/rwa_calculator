"""
Shared sidebar for all RWA Calculator marimo apps.

Provides a single definition of the navigation sidebar so that changes
(new links, styling, workbook listing logic) only need to be made once.
"""

from __future__ import annotations

from pathlib import Path

_MARIMO_DIR = Path(__file__).parent.parent
_WORKSPACES_DIR = _MARIMO_DIR / "workspaces" / "local"


def create_sidebar(mo: object, *, version: str = "v1.0") -> object:
    """Build the standard RWA Calculator sidebar.

    Must be used as the last expression in a marimo cell, e.g.::

        @app.cell
        def _(mo):
            create_sidebar(mo)

    Args:
        mo: The marimo module (passed from the calling cell).
        version: Version string shown in the footer.

    Returns:
        The ``mo.sidebar`` element (must be the cell's last expression).
    """
    workbooks = (
        sorted(f.stem for f in _WORKSPACES_DIR.glob("*.py") if f.stem != "__init__")
        if _WORKSPACES_DIR.exists()
        else []
    )
    wb_links = "\n".join(
        f"- [{n}](http://localhost:8002/?file={n}.py)" for n in workbooks
    )

    items = [
        mo.md("# 🕵️🤖 RWA Calculator"),
        mo.nav_menu(
            {
                "/": f"{mo.icon('home')} Home",
                "/calculator": f"{mo.icon('calculator')} Calculator",
                "/results": f"{mo.icon('table')} Results Explorer",
                "/comparison": f"{mo.icon('git-compare')} Impact Analysis",
                "/reference": f"{mo.icon('book')} Framework Reference",
                "/workbench": f"{mo.icon('code')} Workbench",
            },
            orientation="vertical",
        ),
        mo.md("---"),
        mo.md(
            "**Quick Links**\n"
            "- [PRA PS1/26](https://www.bankofengland.co.uk/"
            "prudential-regulation/publication/2026/january/"
            "implementation-of-the-basel-3-1-final-rules-"
            "policy-statement)\n"
            "- [UK CRR](https://www.legislation.gov.uk/"
            "eur/2013/575/contents)\n"
            "- [BCBS Framework](https://www.bis.org/"
            "basel_framework/)"
        ),
    ]
    if workbooks:
        items.append(mo.md(f"**Workbooks**\n{wb_links}"))

    return mo.sidebar(items, footer=mo.md(f"*RWA Calculator {version}*"))
