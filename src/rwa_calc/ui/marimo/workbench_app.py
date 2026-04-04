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
        _card_html = []
        for _f in _files:
            _mod_time = datetime.fromtimestamp(_f.stat().st_mtime)
            _card_html.append(
                f'<a class="wb-card" href="http://localhost:8002/?file={_f.name}">'
                f"  <div class=\"wb-card-icon\">\U0001f4d3</div>"
                f"  <h3>{_f.stem}</h3>"
                f'  <span class="wb-card-meta">{_mod_time:%Y-%m-%d %H:%M}</span>'
                f'  <div class="wb-card-action">Open in Editor \u2192</div>'
                f"</a>"
            )
        _listing = mo.md(
            """
<style>
.wb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}
.wb-card {
  display: flex;
  flex-direction: column;
  padding: 1.25rem;
  border-radius: 10px;
  border: 1px solid var(--border-color, rgba(0,0,0,0.08));
  background: var(--surface-color, rgba(255,255,255,0.6));
  backdrop-filter: blur(8px);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
}
.wb-card:hover {
  border-color: #ff9100;
  box-shadow: 0 4px 16px rgba(255, 145, 0, 0.12);
  transform: translateY(-2px);
}
@media (prefers-color-scheme: dark) {
  .wb-card {
    background: rgba(30, 30, 50, 0.6);
    border-color: rgba(255,255,255,0.08);
  }
  .wb-card:hover {
    border-color: #ff9100;
    box-shadow: 0 4px 20px rgba(255, 145, 0, 0.18);
  }
}
.wb-card-icon { font-size: 1.6rem; margin-bottom: 0.5rem; }
.wb-card h3 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 0.35rem;
  word-break: break-word;
}
.wb-card-meta {
  font-size: 0.8rem;
  opacity: 0.5;
  margin-bottom: auto;
}
.wb-card-action {
  margin-top: 0.75rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: #ff9100;
}
</style>
<div class="wb-grid">
"""
            + "\n".join(_card_html)
            + "\n</div>"
        )
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
