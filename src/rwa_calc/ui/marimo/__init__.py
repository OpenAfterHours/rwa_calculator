"""Marimo workbench for the RWA Calculator.

The polished read-only surface (landing, calculator, results, comparison) now
lives in the server-rendered app at ``rwa_calc.ui.app`` (the ``rwa-ui`` console
script). Marimo is retained only for the **editable workbench** — reactive,
reproducible, git-friendly notebooks against the engine.

The ``rwa-ui`` server launches the Marimo edit server on demand (port 8002),
pointed at ``workspaces/`` (``local/`` and ``team/``). New notebooks start from
``workspaces/templates/starter.py``; ``shared/sidebar.py`` provides the in-app
navigation back to the read-only surface.

Run the editor directly during development:
    uv run marimo edit src/rwa_calc/ui/marimo/workspaces
"""
