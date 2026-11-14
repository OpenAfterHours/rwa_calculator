"""
``rwa-filer dash`` — a local web dashboard over the package's own public API.

Pipeline position:
    browser  ->  dash.app (Starlette)  ->  readers / validate / workflow
        ->  Jinja templates  ->  HTML

Why a dashboard: the command line answers "does this return pass?" well and
"why not, and where?" badly. The dashboard shows the same validation the
``validate`` command prints, and lets a person walk from the verdict to a
broken rule to the cells on the template grid that broke it.

It holds no validation or filing logic of its own: every figure on every page
comes from the functions the command line calls, and every file it writes is
written by them — a build from the dashboard is byte for byte the command's.
It runs on this machine, answers only the browser holding the session's token,
and sends nothing anywhere.

Module map:
- ``app``       — the Starlette application: routes, middleware, static files
- ``context``   — what every page shares: the workspace, templates, layout
- ``pages``     — the read-only pages: open, overview, rules, templates
- ``filing_pages`` — the write actions: overrides, build, sign-off, verify
- ``filing``    — what those actions do, and the Build & sign off page model
- ``compare_pages`` / ``compare`` — this return beside another version of it
- ``referee_pages`` / ``referee_jobs`` — Arelle's verdict, run in the background
- ``reference_pages`` — the packaged taxonomy packs and rule books
- ``forms``     — opening a return from a form, for every page that takes one
- ``views``     — page models for the overview and the rules
- ``grid``      — the page model of the template viewer
- ``workspace`` — the returns opened in one session
- ``security``  — the session token and the same-origin check
- ``server``    — ``serve``: port, address, browser, uvicorn

References:
- docs/rwa-filer/dash.md — the user guide
"""

from __future__ import annotations

from rwa_filer.dash.app import create_app
from rwa_filer.dash.server import serve
from rwa_filer.dash.workspace import OpenedReturn, Workspace

__all__ = ["OpenedReturn", "Workspace", "create_app", "serve"]
