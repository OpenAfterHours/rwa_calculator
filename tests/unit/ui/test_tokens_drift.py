"""
Drift-guard: the app's vendored tokens.css must match the docs source of truth.

The brand design tokens live once in docs/assets/stylesheets/tokens.css (loaded
by the Zensical docs). The packaged app cannot read docs/ at runtime, so it ships
a vendored copy under src/rwa_calc/ui/app/static/tokens.css. This test fails if
the two drift apart — re-copy the docs file into the app static dir to fix.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS_TOKENS = _REPO_ROOT / "docs" / "assets" / "stylesheets" / "tokens.css"
_APP_TOKENS = _REPO_ROOT / "src" / "rwa_calc" / "ui" / "app" / "static" / "tokens.css"


def test_app_tokens_match_docs_source() -> None:
    # Arrange
    docs = _DOCS_TOKENS.read_text(encoding="utf-8").replace("\r\n", "\n")
    app = _APP_TOKENS.read_text(encoding="utf-8").replace("\r\n", "\n")

    # Assert — single source of truth; re-sync if this fails
    assert app == docs, (
        "src/rwa_calc/ui/app/static/tokens.css has drifted from "
        "docs/assets/stylesheets/tokens.css. Re-copy the docs file into the app "
        "static dir so the brand tokens stay defined once."
    )
