"""
RWA Calculator Multi-App Server with Template Workbench.

Pipeline position:
    Standalone UI server — serves read-only templates and editable workbench.

Key responsibilities:
- Serve template apps in read-only run mode (existing behaviour)
- Manage user workspace (duplicate, list, delete workbooks)
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
from pathlib import Path
from typing import TYPE_CHECKING

import marimo
import uvicorn
from fastapi import FastAPI, HTTPException

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
apps_dir = Path(__file__).parent
workspaces_dir = apps_dir / "workspaces" / "local"
workspaces_dir.mkdir(parents=True, exist_ok=True)

EDIT_SERVER_PORT = 8002

TEMPLATE_REGISTRY: dict[str, str] = {
    "landing": "landing_app.py",
    "calculator": "rwa_app.py",
    "results_explorer": "results_explorer.py",
    "comparison": "comparison_app.py",
    "reference": "framework_reference.py",
}

# ---------------------------------------------------------------------------
# Read-only templates (run mode via create_asgi_app)
# ---------------------------------------------------------------------------
templates_asgi = (
    marimo.create_asgi_app()
    .with_app(path="", root=str(apps_dir / "landing_app.py"))
    .with_app(path="/calculator", root=str(apps_dir / "rwa_app.py"))
    .with_app(path="/results", root=str(apps_dir / "results_explorer.py"))
    .with_app(path="/comparison", root=str(apps_dir / "comparison_app.py"))
    .with_app(path="/reference", root=str(apps_dir / "framework_reference.py"))
    .build()
)

# ---------------------------------------------------------------------------
# FastAPI gateway
# ---------------------------------------------------------------------------
gateway = FastAPI(title="RWA Calculator")


@gateway.on_event("startup")
async def _open_browser() -> None:
    """Open the landing page in the default browser on server start."""
    webbrowser.open("http://localhost:8000")


@gateway.get("/api/templates")
async def list_templates() -> dict[str, list[str]]:
    """Return available template names."""
    return {"templates": list(TEMPLATE_REGISTRY.keys())}


@gateway.get("/api/workbooks")
async def list_workbooks() -> dict[str, list[str]]:
    """Return user workbooks in the local workspace."""
    workbooks = [f.stem for f in workspaces_dir.glob("*.py") if f.stem != "__init__"]
    return {"workbooks": sorted(workbooks)}


@gateway.post("/api/workbooks/duplicate")
async def duplicate_template(template: str, name: str | None = None) -> dict[str, str]:
    """Duplicate a template into the user workspace."""
    if template not in TEMPLATE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template}")

    source = apps_dir / TEMPLATE_REGISTRY[template]
    target_name = name or template
    target = workspaces_dir / f"{target_name}.py"
    counter = 1
    while target.exists():
        target = workspaces_dir / f"{target_name}_{counter}.py"
        counter += 1

    shutil.copy2(source, target)
    workbook_name = target.stem
    return {
        "workbook": workbook_name,
        "url": f"http://localhost:{EDIT_SERVER_PORT}/?file={workbook_name}.py",
    }


@gateway.delete("/api/workbooks/{name}")
async def delete_workbook(name: str) -> dict[str, str]:
    """Delete a user workbook."""
    target = workspaces_dir / f"{name}.py"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Workbook not found")
    target.unlink()
    return {"deleted": name}


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
            str(workspaces_dir),
        ],
    )

    print("Templates (read-only):")
    print("  http://localhost:8000/            (Landing Page)")
    print("  http://localhost:8000/calculator  (Calculator)")
    print("  http://localhost:8000/results     (Results Explorer)")
    print("  http://localhost:8000/comparison  (Impact Analysis)")
    print("  http://localhost:8000/reference   (Framework Reference)")
    print()
    print(f"Workbench (editable):  http://localhost:{EDIT_SERVER_PORT}/")
    print()
    print("API:")
    print("  GET    /api/templates             List available templates")
    print("  GET    /api/workbooks             List your workbooks")
    print("  POST   /api/workbooks/duplicate   Duplicate a template")
    print("  DELETE /api/workbooks/{name}      Delete a workbook")
    print()

    try:
        uvicorn.run(gateway, host="127.0.0.1", port=8000)
    finally:
        if _edit_process:
            _edit_process.terminate()


if __name__ == "__main__":
    main()
