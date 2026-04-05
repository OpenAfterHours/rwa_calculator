"""
Workbench Hub for RWA Calculator.

Manage user workbooks: create from templates, list existing notebooks,
and open them in the marimo editor.

Usage:
    Served at /workbench by the multi-app server.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium", css_file="shared/theme.css", html_head_file="shared/head.html")


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
def _():
    WB_STYLES = """<style>
/* Page wrapper — constrains width like landing page */
.wb-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

/* Page header */
.wb-header {
  padding: 2rem 0 1.5rem;
}
.wb-header h1 {
  font-size: 1.8rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
  color: var(--foreground, #1a1a2e);
}
.wb-header p {
  font-size: 1rem;
  opacity: 0.6;
  margin: 0;
  line-height: 1.6;
  max-width: 600px;
}

/* Card grid */
.wb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1.25rem;
}

/* Individual card */
.wb-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 1.75rem;
  border-radius: 12px;
  border: 1px solid var(--border, rgba(0,0,0,0.08));
  background: var(--card, #fff);
  color: var(--card-foreground, inherit);
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
}
.wb-card:hover {
  border-color: #ff9100;
  box-shadow: 0 4px 20px rgba(255, 145, 0, 0.12);
  transform: translateY(-2px);
}

/* Icon with circular accent background */
.wb-card-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 50%;
  background: rgba(255, 145, 0, 0.10);
  font-size: 1.4rem;
  margin-bottom: 0.75rem;
}

/* Title */
.wb-card h3 {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 0.25rem;
  word-break: break-word;
}

/* Descriptor subtitle */
.wb-card-desc {
  font-size: 0.85rem;
  opacity: 0.55;
  margin: 0 0 0.35rem;
  line-height: 1.4;
}

/* Modified date */
.wb-card-meta {
  font-size: 0.8rem;
  opacity: 0.45;
}

/* Footer action area */
.wb-card-actions {
  display: flex;
  align-items: center;
  margin-top: auto;
  padding-top: 1rem;
}

/* Open link styled like landing card-arrow */
.wb-card-action {
  font-size: 0.85rem;
  font-weight: 600;
  color: #ff9100;
  text-decoration: none;
  transition: opacity 0.2s;
}
.wb-card-action:hover {
  opacity: 0.8;
}

/* Delete button — positioned top-right corner */
.wb-card-delete {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  z-index: 2;
}
.wb-card-delete button {
  background: none !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0.25rem 0.4rem !important;
  font-size: 0.85rem;
  opacity: 0.3;
  cursor: pointer;
  transition: opacity 0.2s;
  min-width: unset !important;
  min-height: unset !important;
}
.wb-card-delete button:hover {
  opacity: 0.85;
}

/* Create section — dashed panel */
.wb-create {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem 1.75rem;
  border-radius: 12px;
  border: 1px dashed var(--border, rgba(0,0,0,0.12));
  transition: border-color 0.2s, background 0.2s;
  margin-bottom: 1.5rem;
}
.wb-create:hover,
.wb-create:focus-within {
  border-color: #ff9100;
  background: rgba(255, 145, 0, 0.04);
}

/* Empty state */
.wb-empty {
  text-align: center;
  padding: 3rem 1.5rem;
  border: 1px dashed var(--border, rgba(0,0,0,0.12));
  border-radius: 12px;
}
.wb-empty-icon {
  font-size: 2.5rem;
  margin-bottom: 0.75rem;
  opacity: 0.4;
}
.wb-empty h3 {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 0.5rem;
}
.wb-empty p {
  font-size: 0.9rem;
  opacity: 0.55;
  margin: 0;
  line-height: 1.5;
}

/* Dark mode adjustment for create panel hover */
@media (prefers-color-scheme: dark) {
  .wb-create:hover,
  .wb-create:focus-within {
    background: rgba(255, 145, 0, 0.06);
  }
}

/* Responsive */
@media (max-width: 640px) {
  .wb-grid { grid-template-columns: 1fr; }
  .wb-header h1 { font-size: 1.4rem; }
}
</style>"""
    return (WB_STYLES,)


@app.cell
def _(WB_STYLES, mo):
    mo.output.replace(
        mo.Html(
            WB_STYLES
            + """
<div class="wb-page">
  <div class="wb-header">
    <h1>\U0001f4bb Workbench</h1>
    <p>Create and manage custom analysis workbooks. Each workbook opens in the
    marimo editor with pre-configured imports and access to cached calculator results.</p>
  </div>
</div>
"""
        )
    )
    return


@app.cell
def _(mo):
    refresh_trigger, set_refresh = mo.state(0)
    pending_delete, set_pending_delete = mo.state(None)
    return pending_delete, refresh_trigger, set_pending_delete, set_refresh


@app.cell
def _(Path, WB_STYLES, refresh_trigger, datetime, mo, set_pending_delete):
    refresh_trigger  # noqa: B018 — reactive dependency for marimo

    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _files = sorted(_ws_dir.glob("*.py")) if _ws_dir.exists() else []
    _files = [f for f in _files if f.stem != "__init__"]

    if _files:
        _buttons = {}
        _card_html = []
        for _i, _f in enumerate(_files):
            _mod_time = datetime.fromtimestamp(_f.stat().st_mtime)
            _btn_key = f"btn_{_i}"
            _buttons[_btn_key] = mo.ui.button(
                label="\U0001f5d1\ufe0f",
                on_click=lambda _, n=_f.stem: set_pending_delete(n),
                kind="danger",
            )
            _card_html.append(
                f'<div class="wb-card">'
                f'  <div class="wb-card-delete">{{{_btn_key}}}</div>'
                f'  <div class="wb-card-icon">\U0001f4d3</div>'
                f"  <h3>{_f.stem}</h3>"
                f'  <span class="wb-card-desc">Python workbook</span>'
                f'  <span class="wb-card-meta">Modified {_mod_time:%Y-%m-%d %H:%M}</span>'
                f'  <div class="wb-card-actions">'
                f'    <a href="http://localhost:8002/?file={_f.name}"'
                f'       class="wb-card-action">Open in Editor \u2192</a>'
                f"  </div>"
                f"</div>"
            )
        # Escape CSS braces so .batch()'s str.format() ignores them
        _safe_styles = WB_STYLES.replace("{", "{{").replace("}", "}}")
        wb_card_grid = mo.Html(
            _safe_styles
            + '<div class="wb-page"><div class="wb-grid">\n'
            + "\n".join(_card_html)
            + "\n</div></div>"
        ).batch(**_buttons)
        _listing = wb_card_grid
    else:
        wb_card_grid = None
        _listing = mo.Html(
            WB_STYLES
            + """
<div class="wb-page">
  <div class="wb-empty">
    <div class="wb-empty-icon">\U0001f4d3</div>
    <h3>No workbooks yet</h3>
    <p>Create your first workbook below to start analysing results
    with custom Python notebooks.</p>
  </div>
</div>
"""
        )
    mo.output.replace(_listing)
    return (wb_card_grid,)


@app.cell
def _(WB_STYLES, mo):
    new_name = mo.ui.text(label="Workbook name", placeholder="my_analysis")
    create_btn = mo.ui.run_button(label="Create Workbook")
    _create_row = mo.hstack([new_name, create_btn], gap=1)
    mo.output.replace(mo.vstack([mo.Html(WB_STYLES), _create_row]))
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
