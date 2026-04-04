"""
Shared sidebar for all RWA Calculator marimo apps.

Provides a single definition of the navigation sidebar so that changes
(new links, styling, workbook listing logic) only need to be made once.

Theme is applied via css_file="shared/theme.css" in each app's marimo.App()
config, which injects the CSS into <head> where it properly overrides
marimo's default variables.
"""

from __future__ import annotations

from pathlib import Path

_MARIMO_DIR = Path(__file__).parent.parent
_WORKSPACES_DIR = _MARIMO_DIR / "workspaces" / "local"

# Read logo at import time from project docs/assets
def _load_logo_base64() -> str:
    import base64
    logo_path = _MARIMO_DIR.parent.parent.parent.parent / "docs" / "assets" / "openafterhours_icon_512.png"
    if logo_path.exists():
        return "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode()
    return ""

_LOGO_URI = _load_logo_base64()


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
        The ``mo.sidebar`` element.
    """
    workbooks = (
        sorted(f.stem for f in _WORKSPACES_DIR.glob("*.py") if f.stem != "__init__")
        if _WORKSPACES_DIR.exists()
        else []
    )
    wb_links = "\n".join(
        f"- [{n}](http://localhost:8002/?file={n}.py)" for n in workbooks
    )

    _header = (
        mo.Html(
            f'<div style="display:flex;align-items:center;gap:0.6rem">'
            f'<img src="{_LOGO_URI}" alt="Logo" '
            f'style="width:36px;height:36px;border-radius:6px">'
            f"<strong style=\"font-size:1.15rem\">RWA Calculator</strong>"
            f"</div>"
        )
        if _LOGO_URI
        else mo.md("# RWA Calculator")
    )

    items = [
        _header,
        mo.nav_menu(
            {
                "/": f"{mo.icon('home')} Home",
                "/calculator": f"{mo.icon('calculator')} Calculator",
                "/results": f"{mo.icon('table')} Results Explorer",
                "/comparison": f"{mo.icon('git-compare')} Impact Analysis",
                "https://openafterhours.github.io/rwa_calculator/": f"{mo.icon('book')} Documentation",
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
