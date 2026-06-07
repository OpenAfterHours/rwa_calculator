"""
Drift-guard: the app's vendored front-end assets must match their docs sources.

The brand design tokens, the landing-page design system, and the polar-bear
constellation script each live once under docs/ (loaded by the Zensical docs).
The packaged app cannot read docs/ at runtime, so it ships vendored copies under
src/rwa_calc/ui/app/static/. These tests fail if a copy drifts from its source —
re-copy the docs file into the app static dir to fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS = _REPO_ROOT / "docs"
_APP_STATIC = _REPO_ROOT / "src" / "rwa_calc" / "ui" / "app" / "static"

# (docs source, app vendored copy) pairs that must stay byte-identical
# (newline-normalised). Add a row here when vendoring another shared asset.
_VENDORED_ASSETS = [
    (
        _DOCS / "assets" / "stylesheets" / "tokens.css",
        _APP_STATIC / "tokens.css",
    ),
    (
        _DOCS / "assets" / "stylesheets" / "homepage.css",
        _APP_STATIC / "homepage.css",
    ),
    (
        _DOCS / "assets" / "javascripts" / "bear-constellation.js",
        _APP_STATIC / "bear-constellation.js",
    ),
]


@pytest.mark.parametrize(
    "docs_source, app_copy",
    _VENDORED_ASSETS,
    ids=lambda p: p.name,
)
def test_app_asset_matches_docs_source(docs_source: Path, app_copy: Path) -> None:
    # Arrange
    docs = docs_source.read_text(encoding="utf-8").replace("\r\n", "\n")
    app = app_copy.read_text(encoding="utf-8").replace("\r\n", "\n")

    # Assert — single source of truth; re-sync if this fails
    assert app == docs, (
        f"{app_copy.relative_to(_REPO_ROOT)} has drifted from "
        f"{docs_source.relative_to(_REPO_ROOT)}. Re-copy the docs file into the "
        f"app static dir so the shared asset stays defined once."
    )
