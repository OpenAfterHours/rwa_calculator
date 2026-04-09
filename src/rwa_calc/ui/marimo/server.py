"""
RWA Calculator Multi-App Server with Template Workbench.

Pipeline position:
    Standalone UI server — serves read-only templates and editable workbench.

Key responsibilities:
- Serve template apps in read-only run mode (existing behaviour)
- Manage user workspace (duplicate, list, delete workbooks)
- Manage team workspace (git-tracked shared workbooks)
- Launch marimo edit subprocess for interactive workbench on separate port

Usage (installed from PyPI):
    rwa-calc-ui

Usage (from source):
    uv run python src/rwa_calc/ui/marimo/server.py

Or with uvicorn directly (templates only, no workbench):
    uvicorn rwa_calc.ui.marimo.server:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import marimo
import uvicorn
from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
apps_dir = Path(__file__).parent

# ---------------------------------------------------------------------------
# Favicon — load custom icon at import time (replaces default marimo favicon)
# ---------------------------------------------------------------------------
_FAVICON_PATH = apps_dir.parents[3] / "docs" / "assets" / "openafterhours_icon_512.png"
_FAVICON_BYTES = _FAVICON_PATH.read_bytes() if _FAVICON_PATH.exists() else b""
workspaces_dir = apps_dir / "workspaces" / "local"
workspaces_dir.mkdir(parents=True, exist_ok=True)
team_dir = apps_dir / "workspaces" / "team"
team_dir.mkdir(parents=True, exist_ok=True)
(apps_dir / "workspaces" / "templates").mkdir(parents=True, exist_ok=True)

EDIT_SERVER_PORT = 8002

TEMPLATE_REGISTRY: dict[str, str] = {
    "landing": "landing_app.py",
    "calculator": "rwa_app.py",
    "results_explorer": "results_explorer.py",
    "comparison": "comparison_app.py",
    "workbench_starter": "workspaces/templates/starter.py",
}

# Directories to skip when scanning workspaces
_SKIP_DIRS = frozenset({"shared", "__marimo__", "__pycache__"})

# ---------------------------------------------------------------------------
# Read-only templates (run mode via create_asgi_app)
# ---------------------------------------------------------------------------
templates_asgi = (
    marimo.create_asgi_app()
    .with_app(path="", root=str(apps_dir / "landing_app.py"))
    .with_app(path="/calculator", root=str(apps_dir / "rwa_app.py"))
    .with_app(path="/results", root=str(apps_dir / "results_explorer.py"))
    .with_app(path="/comparison", root=str(apps_dir / "comparison_app.py"))
    .with_app(path="/workbench", root=str(apps_dir / "workbench_app.py"))
    .build()
)

# ---------------------------------------------------------------------------
# FastAPI gateway
# ---------------------------------------------------------------------------
gateway = FastAPI(title="RWA Calculator")


@gateway.middleware("http")
async def _favicon_middleware(request: Request, call_next: object) -> Response:
    """Serve custom favicon for all app paths (marimo uses relative ./favicon.ico)."""
    if request.url.path.endswith("/favicon.ico") and _FAVICON_BYTES:
        return Response(content=_FAVICON_BYTES, media_type="image/png")
    return await call_next(request)  # type: ignore[operator]


@gateway.on_event("startup")
async def _open_browser() -> None:
    """Open the landing page in the default browser on server start."""
    webbrowser.open("http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_workspace_path(base: Path, relative: str) -> Path:
    """Resolve *relative* within *base*, rejecting path traversal."""
    target = (base / relative).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


def _sanitise_name(raw: str) -> str:
    """Sanitise a user-supplied name to alphanumeric + underscores."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in raw)


def _list_items(base: Path, folder: str = "") -> list[dict[str, str]]:
    """List workbook files and subfolders within *base* / *folder*.

    Returns a list of dicts with keys: type, name, path, modified.
    """
    from datetime import datetime

    target = _validate_workspace_path(base, folder) if folder else base
    if not target.exists() or not target.is_dir():
        return []

    items: list[dict[str, str]] = []

    for entry in sorted(target.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".") or entry.name.startswith("__"):
            continue
        if entry.is_dir() and entry.name not in _SKIP_DIRS:
            py_count = len([f for f in entry.glob("*.py") if f.stem != "__init__"])
            rel = f"{folder}/{entry.name}" if folder else entry.name
            items.append(
                {
                    "type": "folder",
                    "name": entry.name,
                    "path": rel,
                    "count": str(py_count),
                }
            )
        elif entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__":
            mod = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC)
            rel = f"{folder}/{entry.name}" if folder else entry.name
            items.append(
                {
                    "type": "file",
                    "name": entry.stem,
                    "path": rel,
                    "modified": mod.isoformat(),
                }
            )

    return items


# ---------------------------------------------------------------------------
# Template API
# ---------------------------------------------------------------------------


@gateway.get("/api/templates")
async def list_templates() -> dict[str, list[str]]:
    """Return available template names."""
    return {"templates": list(TEMPLATE_REGISTRY.keys())}


# ---------------------------------------------------------------------------
# Local workspace API (with folder support)
# ---------------------------------------------------------------------------


@gateway.get("/api/workbooks")
async def list_workbooks(folder: str = "") -> dict[str, object]:
    """Return workbooks and subfolders in the local workspace."""
    items = _list_items(workspaces_dir, folder)
    breadcrumbs = folder.split("/") if folder else []
    return {"folder": folder, "items": items, "breadcrumbs": breadcrumbs}


@gateway.post("/api/workbooks/duplicate")
async def duplicate_template(
    template: str,
    name: str | None = None,
    folder: str = "",
) -> dict[str, str]:
    """Duplicate a template into the user workspace (optionally inside *folder*)."""
    if template not in TEMPLATE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template}")

    source = apps_dir / TEMPLATE_REGISTRY[template]
    target_name = name or template
    target_dir = _validate_workspace_path(workspaces_dir, folder) if folder else workspaces_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{target_name}.py"
    counter = 1
    while target.exists():
        target = target_dir / f"{target_name}_{counter}.py"
        counter += 1

    shutil.copy2(source, target)
    workbook_name = target.stem
    rel = f"local/{folder}/{workbook_name}.py" if folder else f"local/{workbook_name}.py"
    return {
        "workbook": workbook_name,
        "url": f"http://localhost:{EDIT_SERVER_PORT}/?file={rel}",
    }


@gateway.delete("/api/workbooks/{name:path}")
async def delete_workbook(name: str) -> dict[str, str]:
    """Delete a user workbook or an empty folder."""
    target = _validate_workspace_path(workspaces_dir, name)

    if target.is_dir():
        py_files = [f for f in target.glob("*.py") if f.stem != "__init__"]
        if py_files:
            raise HTTPException(
                status_code=409,
                detail=f"Folder contains {len(py_files)} workbook(s) — remove them first",
            )
        shutil.rmtree(target)
        return {"deleted": name, "type": "folder"}

    # File — append .py if not already present
    if not target.suffix:
        target = target.with_suffix(".py")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Workbook not found")
    target.unlink()
    return {"deleted": name, "type": "file"}


@gateway.post("/api/folders")
async def create_folder(name: str, workspace: str = "local") -> dict[str, str]:
    """Create a new folder in the specified workspace."""
    sanitised = _sanitise_name(name)
    if not sanitised:
        raise HTTPException(status_code=400, detail="Invalid folder name")
    base = team_dir if workspace == "team" else workspaces_dir
    target = base / sanitised
    if target.exists():
        raise HTTPException(status_code=409, detail="Folder already exists")
    target.mkdir()
    return {"folder": sanitised, "workspace": workspace}


@gateway.post("/api/workbooks/move")
async def move_workbook(source: str, dest_folder: str = "") -> dict[str, str]:
    """Move a workbook to a different folder (or to root if *dest_folder* is empty)."""
    src = _validate_workspace_path(workspaces_dir, source)
    if not src.suffix:
        src = src.with_suffix(".py")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source workbook not found")

    dest_dir = (
        _validate_workspace_path(workspaces_dir, dest_folder) if dest_folder else workspaces_dir
    )
    if not dest_dir.is_dir():
        raise HTTPException(status_code=404, detail="Destination folder not found")

    dest = dest_dir / src.name
    if dest.exists():
        raise HTTPException(status_code=409, detail="A workbook with that name already exists")

    src.rename(dest)
    return {"moved": source, "to": dest_folder or "(root)"}


# ---------------------------------------------------------------------------
# Team workspace API (git-tracked)
# ---------------------------------------------------------------------------


@gateway.get("/api/team/workbooks")
async def list_team_workbooks(folder: str = "") -> dict[str, object]:
    """Return team workbooks and subfolders (with git status)."""
    items = _list_items(team_dir, folder)
    breadcrumbs = folder.split("/") if folder else []
    return {"folder": folder, "items": items, "breadcrumbs": breadcrumbs}


@gateway.get("/api/team/status")
async def team_status() -> dict[str, object]:
    """Return git status for all files in the team workspace."""
    from rwa_calc.ui.marimo.git_ops import find_repo_root, get_status

    try:
        repo_root = find_repo_root(team_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    statuses = get_status(team_dir, repo_root)
    return {"files": [{"name": s.name, "folder": s.folder, "status": s.status} for s in statuses]}


@gateway.post("/api/team/publish")
async def publish_to_team(name: str, folder: str = "") -> dict[str, str]:
    """Copy a workbook from local/ to team/ and stage it."""
    from rwa_calc.ui.marimo.git_ops import publish

    src_dir = _validate_workspace_path(workspaces_dir, folder) if folder else workspaces_dir
    src = src_dir / f"{name}.py"
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source workbook not found")

    dest_parent = _validate_workspace_path(team_dir, folder) if folder else team_dir
    dest_parent.mkdir(parents=True, exist_ok=True)

    dest = publish(src, dest_parent)
    rel = f"team/{folder}/{dest.name}" if folder else f"team/{dest.name}"
    return {
        "published": name,
        "url": f"http://localhost:{EDIT_SERVER_PORT}/?file={rel}",
    }


@gateway.post("/api/team/commit")
async def commit_team(message: str = "") -> dict[str, object]:
    """Stage all changes in team/, commit, and push."""
    from rwa_calc.ui.marimo.git_ops import commit_and_push, find_repo_root

    try:
        repo_root = find_repo_root(team_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Collect all .py files in team/
    files = [f for f in team_dir.rglob("*.py") if f.stem != "__init__"]
    if not files:
        return {"success": False, "message": "No workbooks in team workspace"}

    if not message:
        names = sorted({f.stem for f in files})
        message = f"workbench: update {', '.join(names)}"

    result = commit_and_push(team_dir, repo_root, files, message)
    return {
        "success": result.success,
        "message": result.message,
        "commit_hash": result.commit_hash,
    }


@gateway.post("/api/team/pull")
async def pull_team() -> dict[str, object]:
    """Pull latest team changes from remote."""
    from rwa_calc.ui.marimo.git_ops import find_repo_root, pull

    try:
        repo_root = find_repo_root(team_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = pull(repo_root)
    return {"success": result.success, "message": result.message}


# Mount read-only templates at root (catch-all — must be registered last)
gateway.mount("/", templates_asgi)

# Expose for `uvicorn rwa_calc.ui.marimo.server:app`
app = gateway

# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------
_edit_process: subprocess.Popen[bytes] | None = None


def main() -> None:
    """Start the RWA Calculator UI server and marimo edit workbench."""
    global _edit_process  # noqa: PLW0603

    print("Starting RWA Calculator server...")
    print()

    # Launch marimo edit server for workbench (separate process/port)
    # Points at workspaces/ parent so both local/ and team/ are accessible
    _edit_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "marimo",
            "edit",
            "--host",
            "127.0.0.1",
            "--port",
            str(EDIT_SERVER_PORT),
            "--no-token",
            "--headless",
            str(apps_dir / "workspaces"),
        ],
        cwd=str(apps_dir / "workspaces"),
    )

    print("Templates (read-only):")
    print("  http://localhost:8000/            (Landing Page)")
    print("  http://localhost:8000/calculator  (Calculator)")
    print("  http://localhost:8000/results     (Results Explorer)")
    print("  http://localhost:8000/comparison  (Impact Analysis)")
    print("  http://localhost:8000/workbench  (Workbench Hub)")
    print()
    print(f"Workbench editor:      http://localhost:{EDIT_SERVER_PORT}/")
    print()
    print("API:")
    print("  GET    /api/templates             List available templates")
    print("  GET    /api/workbooks             List your workbooks")
    print("  POST   /api/workbooks/duplicate   Duplicate a template")
    print("  DELETE /api/workbooks/{{name}}      Delete a workbook")
    print("  POST   /api/folders               Create a folder")
    print("  POST   /api/workbooks/move        Move a workbook")
    print()
    print("  GET    /api/team/workbooks        List team workbooks")
    print("  GET    /api/team/status           Git status for team")
    print("  POST   /api/team/publish          Publish to team")
    print("  POST   /api/team/commit           Commit & push team changes")
    print("  POST   /api/team/pull             Pull latest team changes")
    print()

    try:
        uvicorn.run(gateway, host="127.0.0.1", port=8000)
    finally:
        if _edit_process:
            _edit_process.terminate()


if __name__ == "__main__":
    main()
