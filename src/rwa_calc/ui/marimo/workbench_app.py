"""
Workbench Hub for RWA Calculator.

Manage user workbooks: create from templates, list existing notebooks,
and open them in the marimo editor.

Usage:
    Served at /workbench by the multi-app server.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium", css_file="shared/theme.css")


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
    pending_delete, set_pending_delete = mo.state(None)
    return pending_delete, refresh_trigger, set_pending_delete, set_refresh


@app.cell
def _(Path, refresh_trigger, datetime, mo, set_pending_delete):
    refresh_trigger  # noqa: B018 — reactive dependency for marimo

    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _files = sorted(_ws_dir.glob("*.py")) if _ws_dir.exists() else []
    _files = [f for f in _files if f.stem != "__init__"]

    _css = mo.Html("""<style>
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
  border: 1px solid var(--border, rgba(0,0,0,0.08));
  background: var(--card, #fff);
  color: var(--card-foreground, inherit);
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
}
.wb-card:hover {
  border-color: #ff9100;
  box-shadow: 0 4px 16px rgba(255, 145, 0, 0.12);
  transform: translateY(-2px);
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
.wb-card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.75rem;
  gap: 0.5rem;
}
.wb-card-action {
  font-size: 0.85rem;
  font-weight: 600;
  color: #ff9100;
  text-decoration: none;
}
.wb-card-action:hover {
  text-decoration: underline;
}
</style>""")

    if _files:
        _buttons = {}
        _card_html = []
        for _i, _f in enumerate(_files):
            _mod_time = datetime.fromtimestamp(_f.stat().st_mtime)
            _btn_key = f"btn_{_i}"
            _buttons[_btn_key] = mo.ui.button(
                label="\U0001f5d1\ufe0f Delete",
                on_click=lambda _, n=_f.stem: set_pending_delete(n),
                kind="danger",
            )
            _card_html.append(
                f'<div class="wb-card">'
                f'  <div class="wb-card-icon">\U0001f4d3</div>'
                f"  <h3>{_f.stem}</h3>"
                f'  <span class="wb-card-meta">{_mod_time:%Y-%m-%d %H:%M}</span>'
                f'  <div class="wb-card-actions">'
                f'    <a href="http://localhost:8002/?file={_f.name}"'
                f'       class="wb-card-action">Open in Editor \u2192</a>'
                f"    {{{_btn_key}}}"
                f"  </div>"
                f"</div>"
            )
        # .batch() registers buttons with the frontend so on_click handlers fire
        wb_card_grid = mo.Html(
            '<div class="wb-grid">\n'
            + "\n".join(_card_html)
            + "\n</div>"
        ).batch(**_buttons)
        _listing = mo.vstack([_css, wb_card_grid])
    else:
        wb_card_grid = None
        _listing = mo.vstack([
            _css,
            mo.callout(
                mo.md("No workbooks yet. Create one below to get started."),
                kind="info",
            ),
        ])
    mo.output.replace(_listing)
    return (wb_card_grid,)


@app.cell
def _(mo):
    new_name = mo.ui.text(label="Workbook name", placeholder="my_analysis")
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
def _(mo, pending_delete):
    mo.stop(pending_delete() is None)

    confirm_btn = mo.ui.run_button(label="Confirm Delete", kind="danger")
    cancel_btn = mo.ui.run_button(label="Cancel")

    mo.callout(
        mo.vstack(
            [
                mo.md(
                    f"Are you sure you want to permanently delete "
                    f"**{pending_delete()}**? This cannot be undone."
                ),
                mo.hstack([confirm_btn, cancel_btn], gap=1),
            ]
        ),
        kind="warn",
    )
    return cancel_btn, confirm_btn


@app.cell
def _(Path, cancel_btn, confirm_btn, mo, pending_delete, set_pending_delete, set_refresh):
    mo.stop(pending_delete() is None)
    mo.stop(not confirm_btn.value and not cancel_btn.value)

    if cancel_btn.value:
        set_pending_delete(None)
        mo.callout(mo.md("Deletion cancelled."), kind="info")
    elif confirm_btn.value:
        _ws_dir = Path(__file__).parent / "workspaces" / "local"
        _target = _ws_dir / f"{pending_delete()}.py"
        _name = pending_delete()
        if _target.exists():
            _target.unlink()
        set_refresh(lambda n: n + 1)
        set_pending_delete(None)
        mo.callout(mo.md(f"Deleted **{_name}**."), kind="warn")
    return


if __name__ == "__main__":
    app.run()
