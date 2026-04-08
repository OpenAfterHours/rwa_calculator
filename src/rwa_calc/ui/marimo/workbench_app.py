"""
Workbench Hub for RWA Calculator.

Manage user workbooks: create from templates, list existing notebooks,
organise into folders, publish to the git-tracked team workspace, and
open them in the marimo editor.

Usage:
    Served at /workbench by the multi-app server.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium", css_file="shared/theme.css", html_head_file="shared/head.html")


@app.cell
def _():
    import shutil
    import subprocess
    from datetime import datetime
    from pathlib import Path

    import marimo as mo

    return Path, datetime, mo, shutil, subprocess


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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@app.cell
def _():
    EDIT_PORT = 8002
    SKIP_DIRS = frozenset({"shared", "__marimo__", "__pycache__"})
    return EDIT_PORT, SKIP_DIRS


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


@app.cell
def _():
    WB_STYLES = """<style>
/* Page wrapper */
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

/* Section header */
.wb-section {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1.5rem 0 1rem;
}
.wb-section h2 {
  font-size: 1.3rem;
  font-weight: 600;
  margin: 0;
}
.wb-section-actions {
  display: flex;
  gap: 0.5rem;
  margin-left: auto;
}

/* Breadcrumb bar */
.wb-breadcrumbs {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0 1rem;
  font-size: 0.9rem;
}
.wb-breadcrumbs-label {
  font-weight: 600;
  opacity: 0.7;
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

/* Folder card */
.wb-card-folder {
  border-style: dashed;
}
.wb-card-folder:hover {
  border-color: #6495ed;
  box-shadow: 0 4px 20px rgba(100, 149, 237, 0.12);
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
.wb-card-folder .wb-card-icon {
  background: rgba(100, 149, 237, 0.10);
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

/* Git status badge */
.wb-status {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 0.4rem;
  vertical-align: middle;
}
.wb-status-unmodified { background: #22c55e; }
.wb-status-modified { background: #f59e0b; }
.wb-status-new { background: #3b82f6; }
.wb-status-conflict { background: #ef4444; }

/* Footer action area */
.wb-card-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
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


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@app.cell
def _(mo):
    refresh_trigger, set_refresh = mo.state(0)
    pending_delete, set_pending_delete = mo.state(None)
    current_folder, set_current_folder = mo.state("")
    pending_move, set_pending_move = mo.state(None)
    return (
        current_folder,
        pending_delete,
        pending_move,
        refresh_trigger,
        set_current_folder,
        set_pending_delete,
        set_pending_move,
        set_refresh,
    )


# ---------------------------------------------------------------------------
# My Workbooks — Section header + breadcrumbs
# ---------------------------------------------------------------------------


@app.cell
def _(WB_STYLES, current_folder, mo):
    _safe = WB_STYLES.replace("{", "{{").replace("}", "}}")

    _header = mo.Html(
        _safe
        + '<div class="wb-page"><div class="wb-section">'
        + "<h2>\U0001f4c1 My Workbooks</h2>"
        + "</div></div>"
    )

    if current_folder():
        breadcrumb_back = mo.ui.run_button(label="\u2190 All workbooks")
        mo.output.replace(
            mo.vstack(
                [
                    _header,
                    mo.hstack(
                        [breadcrumb_back, mo.md(f"/ **{current_folder()}**")],
                        align="center",
                    ),
                ]
            )
        )
    else:
        breadcrumb_back = None
        mo.output.replace(_header)
    return (breadcrumb_back,)


# ---------------------------------------------------------------------------
# My Workbooks — Card grid (folders + files)
# ---------------------------------------------------------------------------


@app.cell
def _(
    EDIT_PORT,
    Path,
    SKIP_DIRS,
    WB_STYLES,
    current_folder,
    datetime,
    mo,
    refresh_trigger,
):
    refresh_trigger  # noqa: B018 — reactive dependency

    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _browse_dir = _ws_dir / current_folder() if current_folder() else _ws_dir

    # Discover subfolders (only when at root)
    _folders = []
    if not current_folder() and _browse_dir.exists():
        _folders = sorted(
            d
            for d in _browse_dir.iterdir()
            if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
        )

    # Discover files
    _files = (
        sorted(f for f in _browse_dir.glob("*.py") if f.stem != "__init__")
        if _browse_dir.exists()
        else []
    )

    if _folders or _files:
        # Build buttons in a mo.ui.dictionary for reliable reactivity
        # (.batch() does not propagate interactions to downstream cells)
        _btn_elements: dict[str, object] = {}
        _btn_meta: dict[str, tuple[str, object]] = {}
        _cards: list[object] = []

        # Folder cards
        for _di, _d in enumerate(_folders):
            _py_count = len([f for f in _d.glob("*.py") if f.stem != "__init__"])
            _open_key = f"folder_open_{_di}"
            _del_key = f"folder_del_{_di}"
            _btn_elements[_open_key] = mo.ui.button(
                label="Open \u2192", on_click=lambda v: (v or 0) + 1
            )
            _btn_elements[_del_key] = mo.ui.button(
                label="\U0001f5d1\ufe0f", on_click=lambda v: (v or 0) + 1, kind="danger"
            )
            _btn_meta[_open_key] = ("open_folder", _d.name)
            _btn_meta[_del_key] = ("delete_folder", _d.name)

        for _i, _f in enumerate(_files):
            _del_key = f"btn_{_i}"
            _move_key = f"move_{_i}"
            _pub_key = f"pub_{_i}"
            _cf = current_folder()
            _btn_elements[_del_key] = mo.ui.button(
                label="\U0001f5d1\ufe0f", on_click=lambda v: (v or 0) + 1, kind="danger"
            )
            _btn_elements[_move_key] = mo.ui.button(label="Move", on_click=lambda v: (v or 0) + 1)
            _btn_elements[_pub_key] = mo.ui.button(label="Publish", on_click=lambda v: (v or 0) + 1)
            _btn_meta[_del_key] = (
                "delete_file",
                f"{_cf}/{_f.stem}" if _cf else _f.stem,
            )
            _btn_meta[_move_key] = (
                "move_file",
                (f"{_cf}/{_f.stem}.py" if _cf else f"{_f.stem}.py", _f.stem),
            )
            _btn_meta[_pub_key] = (
                "publish_file",
                (
                    f"__publish__:{_cf}/{_f.stem}" if _cf else f"__publish__:{_f.stem}",
                    _f.stem,
                ),
            )

        wb_actions = mo.ui.dictionary(_btn_elements)
        wb_action_meta = _btn_meta

        # Build card display using dictionary buttons
        for _di, _d in enumerate(_folders):
            _py_count = len([f for f in _d.glob("*.py") if f.stem != "__init__"])
            _cards.append(
                mo.callout(
                    mo.vstack(
                        [
                            mo.md(f"\U0001f4c1 **{_d.name}**"),
                            mo.md(f"_{_py_count} workbook(s)_"),
                            mo.hstack(
                                [
                                    wb_actions[f"folder_open_{_di}"],
                                    wb_actions[f"folder_del_{_di}"],
                                ]
                            ),
                        ]
                    ),
                    kind="info",
                )
            )

        _cf = current_folder()
        for _i, _f in enumerate(_files):
            _mod_time = datetime.fromtimestamp(_f.stat().st_mtime)
            _rel = f"local/{_cf}/{_f.name}" if _cf else f"local/{_f.name}"
            _edit_link = mo.md(
                f"[Open in Editor \u2192](http://localhost:{EDIT_PORT}/?file={_rel})"
            )
            _cards.append(
                mo.callout(
                    mo.vstack(
                        [
                            mo.md(f"\U0001f4d3 **{_f.stem}**"),
                            mo.md(f"_Modified {_mod_time:%Y-%m-%d %H:%M}_"),
                            mo.hstack(
                                [
                                    _edit_link,
                                    wb_actions[f"move_{_i}"],
                                    wb_actions[f"pub_{_i}"],
                                    wb_actions[f"btn_{_i}"],
                                ]
                            ),
                        ]
                    ),
                    kind="neutral",
                )
            )

        # Arrange cards in rows of 3
        _rows = []
        for _start in range(0, len(_cards), 3):
            _rows.append(mo.hstack(_cards[_start : _start + 3], widths="equal"))
        mo.output.replace(mo.Html(WB_STYLES) if not _rows else mo.vstack(_rows))
    else:
        wb_actions = mo.ui.dictionary({})
        wb_action_meta = {}
        mo.output.replace(
            mo.Html(
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
        )
    return wb_action_meta, wb_actions


# ---------------------------------------------------------------------------
# Card grid + breadcrumb button handler
# ---------------------------------------------------------------------------
# .batch() does not propagate interactions to downstream cells (marimo #6435).
# We use mo.ui.dictionary instead — interacting with any child element
# automatically re-executes cells that reference the dictionary.


@app.cell
def _(
    breadcrumb_back,
    mo,
    set_current_folder,
    set_pending_delete,
    set_pending_move,
    wb_action_meta,
    wb_actions,
):
    # Handle back button in breadcrumb (plain mo.ui.button, not in batch)
    if breadcrumb_back is not None and breadcrumb_back.value:
        set_current_folder("")
        mo.stop(True)

    # Handle card grid buttons from mo.ui.dictionary
    _vals = wb_actions.value
    for _key, _count in _vals.items():
        if _count and _key in wb_action_meta:
            _action, _data = wb_action_meta[_key]
            if _action == "open_folder":
                set_current_folder(_data)
            elif _action == "delete_folder":
                set_pending_delete(f"__folder__:{_data}")
            elif _action == "delete_file":
                set_pending_delete(_data)
            elif _action in ("move_file", "publish_file"):
                set_pending_move(_data)
            break
    return


# ---------------------------------------------------------------------------
# Create workbook + Create folder
# ---------------------------------------------------------------------------


@app.cell
def _(WB_STYLES, mo):
    new_name = mo.ui.text(label="Workbook name", placeholder="my_analysis")
    create_btn = mo.ui.run_button(label="Create Workbook")
    folder_name = mo.ui.text(label="Folder name", placeholder="my_project")
    create_folder_btn = mo.ui.run_button(label="New Folder")
    _create_row = mo.hstack(
        [new_name, create_btn, mo.md("|"), folder_name, create_folder_btn], gap=1
    )
    mo.output.replace(mo.vstack([mo.Html(WB_STYLES), _create_row]))
    return create_btn, create_folder_btn, folder_name, new_name


@app.cell
def _(Path, create_btn, current_folder, mo, new_name, set_refresh, shutil):
    mo.stop(not create_btn.value)

    _name = new_name.value.strip() or "my_workbook"
    _name = "".join(c if c.isalnum() or c == "_" else "_" for c in _name)
    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _target_dir = _ws_dir / current_folder() if current_folder() else _ws_dir
    _target_dir.mkdir(parents=True, exist_ok=True)
    _template = Path(__file__).parent / "workspaces" / "templates" / "starter.py"
    _target = _target_dir / f"{_name}.py"
    _counter = 1
    while _target.exists():
        _target = _target_dir / f"{_name}_{_counter}.py"
        _counter += 1
    shutil.copy2(_template, _target)
    set_refresh(lambda n: n + 1)
    _rel = (
        f"local/{current_folder()}/{_target.name}" if current_folder() else f"local/{_target.name}"
    )
    mo.callout(
        mo.md(f"Created **{_target.stem}**. [Open in Editor](http://localhost:8002/?file={_rel})"),
        kind="success",
    )
    return


@app.cell
def _(Path, create_folder_btn, folder_name, mo, set_refresh, shutil):
    mo.stop(not create_folder_btn.value)

    _name = folder_name.value.strip() or "new_folder"
    _name = "".join(c if c.isalnum() or c == "_" else "_" for c in _name)
    _ws_dir = Path(__file__).parent / "workspaces" / "local"
    _target = _ws_dir / _name
    if _target.exists():
        mo.callout(mo.md(f"Folder **{_name}** already exists."), kind="warn")
    else:
        _target.mkdir(parents=True, exist_ok=True)
        # Copy shared assets into the new folder
        _shared_src = Path(__file__).parent / "shared"
        if _shared_src.exists():
            shutil.copytree(_shared_src, _target / "shared", dirs_exist_ok=True)
        set_refresh(lambda n: n + 1)
        mo.callout(mo.md(f"Created folder **{_name}**."), kind="success")
    return


# ---------------------------------------------------------------------------
# Delete confirmation (workbooks and folders)
# ---------------------------------------------------------------------------


@app.cell
def _(mo, pending_delete):
    mo.stop(pending_delete() is None)

    confirm_btn = mo.ui.run_button(label="Confirm Delete", kind="danger")
    cancel_btn = mo.ui.run_button(label="Cancel")

    _label = pending_delete()
    if _label.startswith("__folder__:"):
        _display = f"folder **{_label[len('__folder__:') :]}"
    else:
        _display = f"**{_label}**"

    mo.callout(
        mo.vstack(
            [
                mo.md(
                    f"Are you sure you want to permanently delete "
                    f"{_display}? This cannot be undone."
                ),
                mo.hstack([confirm_btn, cancel_btn], gap=1),
            ]
        ),
        kind="warn",
    )
    return cancel_btn, confirm_btn


@app.cell
def _(Path, cancel_btn, confirm_btn, mo, pending_delete, set_pending_delete, set_refresh, shutil):
    mo.stop(pending_delete() is None)
    mo.stop(not confirm_btn.value and not cancel_btn.value)

    if cancel_btn.value:
        set_pending_delete(None)
        mo.callout(mo.md("Deletion cancelled."), kind="info")
    elif confirm_btn.value:
        _ws_dir = Path(__file__).parent / "workspaces" / "local"
        _label = pending_delete()

        if _label.startswith("__folder__:"):
            # Folder delete
            _folder_name = _label[len("__folder__:") :]
            _folder_path = _ws_dir / _folder_name
            _py_files = (
                [f for f in _folder_path.glob("*.py") if f.stem != "__init__"]
                if _folder_path.exists()
                else []
            )
            if _py_files:
                set_pending_delete(None)
                mo.callout(
                    mo.md(
                        f"Cannot delete **{_folder_name}** — it contains "
                        f"{len(_py_files)} workbook(s). Move or delete them first."
                    ),
                    kind="danger",
                )
            elif _folder_path.exists():
                shutil.rmtree(_folder_path)
                set_refresh(lambda n: n + 1)
                set_pending_delete(None)
                mo.callout(mo.md(f"Deleted folder **{_folder_name}**."), kind="warn")
        else:
            # File delete — _label may be "folder/name" or just "name"
            _target = _ws_dir / f"{_label}.py"
            _display_name = _label.split("/")[-1] if "/" in _label else _label
            if _target.exists():
                _target.unlink()
            set_refresh(lambda n: n + 1)
            set_pending_delete(None)
            mo.callout(mo.md(f"Deleted **{_display_name}**."), kind="warn")
    return


# ---------------------------------------------------------------------------
# Move workbook dialog
# ---------------------------------------------------------------------------


@app.cell
def _(Path, SKIP_DIRS, mo, pending_move, set_pending_move, set_refresh):
    move_cancel_btn = None
    move_confirm_btn = None
    move_dropdown = None

    mo.stop(pending_move() is None)

    _source_path, _source_name = pending_move()

    # Handle publish action
    if _source_path.startswith("__publish__:"):
        _pub_rel = _source_path[len("__publish__:") :]
        _ws_dir = Path(__file__).parent / "workspaces" / "local"
        _team_dir = Path(__file__).parent / "workspaces" / "team"
        _src = _ws_dir / f"{_pub_rel}.py"
        if _src.exists():
            import shutil as _shutil

            _dest = _team_dir / _src.name
            _team_dir.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(_src, _dest)
            set_refresh(lambda n: n + 1)
            set_pending_move(None)
            _rel = f"team/{_dest.name}"
            mo.output.replace(
                mo.callout(
                    mo.md(
                        f"Published **{_source_name}** to team workspace. "
                        f"[Open in Editor](http://localhost:8002/?file={_rel})"
                    ),
                    kind="success",
                )
            )
        else:
            set_pending_move(None)
            mo.output.replace(mo.callout(mo.md(f"Source not found: {_pub_rel}"), kind="danger"))
    else:
        # Move dialog — show folder dropdown
        _ws_dir = Path(__file__).parent / "workspaces" / "local"
        _available_folders = ["(root)"] + sorted(
            d.name
            for d in _ws_dir.iterdir()
            if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
        )
        move_dropdown = mo.ui.dropdown(
            options=_available_folders,
            label="Move to",
            value="(root)",
        )
        move_confirm_btn = mo.ui.run_button(label="Move")
        move_cancel_btn = mo.ui.run_button(label="Cancel")
        mo.output.replace(
            mo.callout(
                mo.vstack(
                    [
                        mo.md(f"Move **{_source_name}** to:"),
                        mo.hstack([move_dropdown, move_confirm_btn, move_cancel_btn], gap=1),
                    ]
                ),
                kind="info",
            )
        )
    return move_cancel_btn, move_confirm_btn, move_dropdown


@app.cell
def _(
    Path,
    mo,
    move_cancel_btn,
    move_confirm_btn,
    move_dropdown,
    pending_move,
    set_pending_move,
    set_refresh,
):
    mo.stop(pending_move() is None)
    mo.stop(move_confirm_btn is None)

    _source_path, _source_name = pending_move()
    # Skip publish actions (handled above)
    mo.stop(_source_path.startswith("__publish__:"))

    mo.stop(not move_confirm_btn.value and not move_cancel_btn.value)

    if move_cancel_btn.value:
        set_pending_move(None)
        mo.callout(mo.md("Move cancelled."), kind="info")
    elif move_confirm_btn.value:
        _ws_dir = Path(__file__).parent / "workspaces" / "local"
        _src = _ws_dir / _source_path
        _dest_folder = move_dropdown.value
        _dest_dir = _ws_dir if _dest_folder == "(root)" else _ws_dir / _dest_folder
        _dest = _dest_dir / _src.name
        if _dest.exists():
            mo.callout(
                mo.md(f"A workbook named **{_src.stem}** already exists in {_dest_folder}."),
                kind="danger",
            )
        elif _src.exists():
            _src.rename(_dest)
            set_refresh(lambda n: n + 1)
            set_pending_move(None)
            mo.callout(
                mo.md(f"Moved **{_source_name}** to **{_dest_folder}**."),
                kind="success",
            )
    return


# ---------------------------------------------------------------------------
# Team Workbooks — Section header
# ---------------------------------------------------------------------------


@app.cell
def _(WB_STYLES, mo):
    pull_btn = mo.ui.run_button(label="Pull Latest")
    commit_btn = mo.ui.run_button(label="Commit & Push")

    _safe = WB_STYLES.replace("{", "{{").replace("}", "}}")
    mo.output.replace(
        mo.Html(
            _safe
            + '<div class="wb-page"><div class="wb-section">'
            + "<h2>\U0001f91d Team Workbooks</h2>"
            + '<div class="wb-section-actions">{pull} {commit}</div>'
            + "</div></div>"
        ).batch(pull=pull_btn, commit=commit_btn)
    )
    return commit_btn, pull_btn


# ---------------------------------------------------------------------------
# Team Workbooks — Card grid
# ---------------------------------------------------------------------------


@app.cell
def _(EDIT_PORT, Path, SKIP_DIRS, WB_STYLES, datetime, mo, refresh_trigger):
    refresh_trigger  # noqa: B018

    _team_dir = Path(__file__).parent / "workspaces" / "team"

    # Get git status for team files
    _git_statuses: dict[str, str] = {}
    try:
        from rwa_calc.ui.marimo.git_ops import find_repo_root as _find_repo_root
        from rwa_calc.ui.marimo.git_ops import get_status as _get_status

        _repo_root = _find_repo_root(_team_dir)
        for _s in _get_status(_team_dir, _repo_root):
            _key = f"{_s.folder}/{_s.name}" if _s.folder else _s.name
            _git_statuses[_key] = _s.status
    except Exception:
        pass

    # Discover team files
    _files = []
    if _team_dir.exists():
        _files = sorted(
            f
            for f in _team_dir.rglob("*.py")
            if f.stem != "__init__"
            and not any(p in SKIP_DIRS for p in f.relative_to(_team_dir).parts)
        )

    if _files:
        _buttons = {}
        _card_html = []
        for _i, _f in enumerate(_files):
            _rel_to_team = _f.relative_to(_team_dir)
            _status_key = (
                f"{_rel_to_team.parent}/{_rel_to_team.stem}"
                if len(_rel_to_team.parts) > 1
                else _rel_to_team.stem
            )
            _status = _git_statuses.get(_status_key, "unmodified")
            _status_dot = f'<span class="wb-status wb-status-{_status}"></span>'
            _mod_time = datetime.fromtimestamp(_f.stat().st_mtime)
            _rel = f"team/{_rel_to_team.as_posix()}"
            _folder_prefix = f"{_rel_to_team.parent}/" if len(_rel_to_team.parts) > 1 else ""

            _card_html.append(
                f'<div class="wb-card">'
                f'  <div class="wb-card-icon">\U0001f4d3</div>'
                f"  <h3>{_status_dot}{_f.stem}</h3>"
                f'  <span class="wb-card-desc">{_folder_prefix}Team workbook</span>'
                f'  <span class="wb-card-meta">Modified {_mod_time:%Y-%m-%d %H:%M}</span>'
                f'  <div class="wb-card-actions">'
                f'    <a href="http://localhost:{EDIT_PORT}/?file={_rel}"'
                f'       class="wb-card-action">Open in Editor \u2192</a>'
                f"  </div>"
                f"</div>"
            )

        _safe_styles = WB_STYLES.replace("{", "{{").replace("}", "}}")
        team_card_grid = mo.Html(
            _safe_styles
            + '<div class="wb-page"><div class="wb-grid">\n'
            + "\n".join(_card_html)
            + "\n</div></div>"
        )
        mo.output.replace(team_card_grid)
    else:
        team_card_grid = None
        mo.output.replace(
            mo.Html(
                WB_STYLES
                + """
<div class="wb-page">
  <div class="wb-empty">
    <div class="wb-empty-icon">\U0001f91d</div>
    <h3>No team workbooks yet</h3>
    <p>Publish a workbook from your local workspace to share it with
    your team via git.</p>
  </div>
</div>
"""
            )
        )
    return (team_card_grid,)


# ---------------------------------------------------------------------------
# Team — Commit & Push handler
# ---------------------------------------------------------------------------


@app.cell
def _(Path, commit_btn, mo):
    mo.stop(not commit_btn.value)

    _team_dir = Path(__file__).parent / "workspaces" / "team"
    try:
        from rwa_calc.ui.marimo.git_ops import commit_and_push as _commit_and_push
        from rwa_calc.ui.marimo.git_ops import find_repo_root as _find_repo_root

        _repo_root = _find_repo_root(_team_dir)
        _files = [f for f in _team_dir.rglob("*.py") if f.stem != "__init__"]
        if not _files:
            mo.callout(mo.md("No workbooks to commit."), kind="info")
        else:
            _names = sorted({f.stem for f in _files})
            _message = f"workbench: update {', '.join(_names)}"
            _result = _commit_and_push(_team_dir, _repo_root, _files, _message)
            if _result.success:
                mo.callout(mo.md(f"**{_result.message}**"), kind="success")
            else:
                mo.callout(mo.md(f"**{_result.message}**"), kind="danger")
    except Exception as _e:
        mo.callout(mo.md(f"Git error: {_e}"), kind="danger")
    return


# ---------------------------------------------------------------------------
# Team — Pull handler
# ---------------------------------------------------------------------------


@app.cell
def _(Path, mo, pull_btn, set_refresh):
    mo.stop(not pull_btn.value)

    _team_dir = Path(__file__).parent / "workspaces" / "team"
    try:
        from rwa_calc.ui.marimo.git_ops import find_repo_root as _find_repo_root
        from rwa_calc.ui.marimo.git_ops import pull as _pull

        _repo_root = _find_repo_root(_team_dir)
        _result = _pull(_repo_root)
        set_refresh(lambda n: n + 1)
        if _result.success:
            mo.callout(mo.md(f"**{_result.message}**"), kind="success")
        else:
            mo.callout(mo.md(f"**{_result.message}**"), kind="danger")
    except Exception as _e:
        mo.callout(mo.md(f"Git error: {_e}"), kind="danger")
    return


if __name__ == "__main__":
    app.run()
