"""Ensure the starter workbook template parses cleanly through marimo's AST
parser so that marimo.App() kwargs (css_file, html_head_file, etc.) are
actually respected at render time.

Marimo's _eval_kwargs only accepts ast.Constant / ast.List values.
Non-literal expressions (e.g. str(path / "theme.css")) are silently
dropped, breaking theme injection.  This test guards against that
regression.
"""

from __future__ import annotations

from pathlib import Path

from marimo._ast.parse import parse_notebook

STARTER = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "rwa_calc"
    / "ui"
    / "marimo"
    / "workspaces"
    / "templates"
    / "starter.py"
)


def test_starter_template_has_no_parse_violations() -> None:
    nb = parse_notebook(STARTER.read_text(), filepath=str(STARTER))
    bad = [
        v
        for v in nb.violations
        if "Unexpected value for keyword argument" in v.description
        or "Unexpected statement" in v.description
    ]
    assert not bad, f"starter.py has parse violations: {[v.description for v in bad]}"
