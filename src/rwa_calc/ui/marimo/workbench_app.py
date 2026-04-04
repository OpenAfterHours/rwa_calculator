"""
Workbench Hub for RWA Calculator.

Manage user workbooks: create from templates, list existing notebooks,
and open them in the marimo editor.

Usage:
    Served at /workbench by the multi-app server.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import shutil
    from datetime import datetime
    from pathlib import Path

    import marimo as mo

    return Path, datetime, mo, shutil


@app.cell
def _(mo):
    import sys as _sys
    from pathlib import Path as _P

    _shared = str(_P(__file__).parent / "shared")
    if _shared not in _sys.path:
        _sys.path.insert(0, _shared)
    from sidebar import create_sidebar as _create_sidebar

    _create_sidebar(mo)
    return


@app.cell
def _(mo):
    return mo.md("""
# Workbench

Create and manage custom analysis workbooks. Each workbook opens in the
marimo editor with pre-configured imports and access to cached calculator results.
    """)


@app.cell
def _(mo):
    refresh_trigger, set_refresh = mo.state(0)
    return refresh_trigger, set_refresh


@app.cell
def _(Path, refresh_trigger, datetime, mo):
    refresh_trigger  # reactive dependency

    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _files = sorted(_ws_dir.glob("*.py")) if _ws_dir.exists() else []
    _files = [f for f in _files if f.stem != "__init__"]

    if _files:
        _cards = []
        for _f in _files:
            _mod_time = datetime.fromtimestamp(_f.stat().st_mtime)
            _cards.append(
                mo.md(
                    f"### {_f.stem}\n\n"
                    f"Last modified: {_mod_time:%Y-%m-%d %H:%M}\n\n"
                    f"[Open in Editor](http://localhost:8002/?file={_f.name})"
                )
            )
        _listing = mo.hstack(_cards, wrap=True, gap=1)
    else:
        _listing = mo.callout(
            mo.md(
                "No workbooks yet. Create one below to get started."
            ),
            kind="info",
        )
    mo.output.replace(_listing)
    return


@app.cell
def _(mo):
    new_name = mo.ui.text(
        label="Workbook name", placeholder="my_analysis"
    )
    create_btn = mo.ui.run_button(label="Create Workbook")
    mo.hstack([new_name, create_btn], gap=1)
    return create_btn, new_name


@app.cell
def _(Path, create_btn, mo, new_name, set_refresh, shutil):
    mo.stop(not create_btn.value)

    _name = new_name.value.strip() or "my_workbook"
    # Sanitise: only allow alphanumeric and underscores
    _name = "".join(c if c.isalnum() or c == "_" else "_" for c in _name)
    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _ws_dir.mkdir(parents=True, exist_ok=True)
    _template = Path(__file__).parent / "workspaces" / "templates" / "starter.py"
    _target = _ws_dir / f"{_name}.py"
    _counter = 1
    while _target.exists():
        _target = _ws_dir / f"{_name}_{_counter}.py"
        _counter += 1
    shutil.copy2(_template, _target)
    set_refresh(lambda n: n + 1)
    mo.callout(
        mo.md(
            f"Created **{_target.stem}**. "
            f"[Open in Editor](http://localhost:8002/?file={_target.name})"
        ),
        kind="success",
    )
    return


@app.cell
def _(Path, mo):
    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _files = sorted(
        f.stem for f in _ws_dir.glob("*.py") if f.stem != "__init__"
    ) if _ws_dir.exists() else []

    if _files:
        delete_dropdown = mo.ui.dropdown(
            options=_files, label="Select workbook to delete"
        )
        delete_btn = mo.ui.run_button(label="Delete", kind="danger")
        mo.hstack([delete_dropdown, delete_btn], gap=1)
    else:
        delete_dropdown = None
        delete_btn = None
    return delete_btn, delete_dropdown


@app.cell
def _(Path, delete_btn, delete_dropdown, mo, set_refresh):
    mo.stop(delete_btn is None or not delete_btn.value or not delete_dropdown.value)

    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _target = _ws_dir / f"{delete_dropdown.value}.py"
    if _target.exists():
        _target.unlink()
        set_refresh(lambda n: n + 1)
        mo.callout(
            mo.md(f"Deleted **{delete_dropdown.value}**."),
            kind="warn",
        )
    return


if __name__ == "__main__":
    app.run()
