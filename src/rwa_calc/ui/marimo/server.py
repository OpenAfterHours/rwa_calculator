"""
RWA Calculator Multi-App Server.

Serves all Marimo applications with proper navigation between them.

Usage:
    uv run python src/rwa_calc/ui/marimo/server.py

    Or with uvicorn directly:
    uv run uvicorn rwa_calc.ui.marimo.server:app --host 0.0.0.0 --port 8000
"""

import marimo
from pathlib import Path

# Get the directory containing the apps
apps_dir = Path(__file__).parent

# Create marimo ASGI app with all notebooks and build it
app = (
    marimo.create_asgi_app()
    .with_app(path="", root=str(apps_dir / "rwa_app.py"))
    .with_app(path="/calculator", root=str(apps_dir / "rwa_app.py"))
    .with_app(path="/results", root=str(apps_dir / "results_explorer.py"))
    .with_app(path="/reference", root=str(apps_dir / "framework_reference.py"))
    .build()
)

if __name__ == "__main__":
    import uvicorn
    print("Starting RWA Calculator server...")
    print("Apps available at:")
    print("  - http://localhost:8000/           (Calculator)")
    print("  - http://localhost:8000/calculator (Calculator)")
    print("  - http://localhost:8000/results    (Results Explorer)")
    print("  - http://localhost:8000/reference  (Framework Reference)")
    uvicorn.run(app, host="0.0.0.0", port=8000)
