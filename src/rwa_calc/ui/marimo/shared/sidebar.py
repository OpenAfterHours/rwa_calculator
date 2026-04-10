"""
Shared sidebar for all RWA Calculator marimo apps.

Provides a single definition of the navigation sidebar so that changes
(new links, styling, workbook listing logic) only need to be made once.

Theme is applied project-wide via [tool.marimo.display.custom_css] in
pyproject.toml, which marimo injects into <head> at render time.
"""

from __future__ import annotations

from pathlib import Path

_MARIMO_DIR = Path(__file__).parent.parent
_WORKSPACES_DIR = _MARIMO_DIR / "workspaces" / "local"
_TEAM_DIR = _MARIMO_DIR / "workspaces" / "team"
_SKIP_DIRS = frozenset({"shared", "__marimo__", "__pycache__"})


# Read logo at import time from project docs/assets
def _load_logo_base64() -> str:
    import base64

    logo_path = (
        _MARIMO_DIR.parent.parent.parent.parent / "docs" / "assets" / "openafterhours_icon_512.png"
    )
    if logo_path.exists():
        return "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode()
    return ""


_LOGO_URI = _load_logo_base64()


def _get_version() -> str:
    """Read version from rwa_calc package, falling back to 'dev'."""
    try:
        from rwa_calc import __version__

        return __version__
    except ImportError:
        return "dev"


def _discover_workbooks(base_dir: Path, url_prefix: str) -> list[str]:
    """Build markdown list entries for workbooks in *base_dir*.

    Returns a list of markdown lines. Root-level workbooks are top-level
    items; subfolders appear as bold headers with their contents indented.
    """
    if not base_dir.exists():
        return []

    lines: list[str] = []

    # Root-level workbooks
    root_books = sorted(f.stem for f in base_dir.glob("*.py") if f.stem != "__init__")
    for name in root_books:
        lines.append(f"- [{name}](http://localhost:8002/?file={url_prefix}/{name}.py)")

    # Folder workbooks
    for d in sorted(base_dir.iterdir()):
        if not d.is_dir() or d.name in _SKIP_DIRS or d.name.startswith("."):
            continue
        folder_books = sorted(f.stem for f in d.glob("*.py") if f.stem != "__init__")
        if folder_books:
            lines.append(f"- **{d.name}/**")
            for name in folder_books:
                lines.append(
                    f"  - [{name}](http://localhost:8002/?file={url_prefix}/{d.name}/{name}.py)"
                )

    return lines


def create_sidebar(mo: object, *, version: str = "", base_url: str = "") -> object:
    """Build the standard RWA Calculator sidebar.

    Must be used as the last expression in a marimo cell, e.g.::

        @app.cell
        def _(mo):
            create_sidebar(mo)

    Args:
        mo: The marimo module (passed from the calling cell).
        version: Version string shown in the footer. Defaults to the
            installed rwa_calc package version prefixed with "v".
        base_url: URL prefix for nav links. Use ``"http://localhost:8000"``
            when rendering from the workbench edit server (port 8002) so
            that sidebar links navigate back to the main template apps.

    Returns:
        The ``mo.sidebar`` element.
    """
    if not version:
        version = f"v{_get_version()}"

    _header = (
        mo.Html(
            f'<div style="display:flex;align-items:center;gap:0.6rem">'
            f'<img src="{_LOGO_URI}" alt="Logo" '
            f'style="width:36px;height:36px;border-radius:6px">'
            f'<strong style="font-size:1.15rem">RWA Calculator</strong>'
            f"</div>"
        )
        if _LOGO_URI
        else mo.md("# RWA Calculator")
    )

    items = [
        _header,
        mo.nav_menu(
            {
                f"{base_url}/": f"{mo.icon('home')} Home",
                f"{base_url}/calculator": f"{mo.icon('calculator')} Calculator",
                f"{base_url}/results": f"{mo.icon('table')} Results Explorer",
                f"{base_url}/comparison": f"{mo.icon('git-compare')} Impact Analysis",
                "https://openafterhours.github.io/rwa_calculator/": f"{mo.icon('book')} Documentation",
                f"{base_url}/workbench": f"{mo.icon('code')} Workbench",
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

    # Local workbooks
    local_lines = _discover_workbooks(_WORKSPACES_DIR, "local")
    if local_lines:
        items.append(mo.md("**Workbooks**\n" + "\n".join(local_lines)))

    # Team workbooks
    team_lines = _discover_workbooks(_TEAM_DIR, "team")
    if team_lines:
        items.append(mo.md("**Team Workbooks**\n" + "\n".join(team_lines)))

    return mo.sidebar(items, footer=mo.md(f"*RWA Calculator {version}*"))
