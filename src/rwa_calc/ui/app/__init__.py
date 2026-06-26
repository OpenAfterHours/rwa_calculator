"""
RWA Calculator — server-rendered read-only UI package.

A FastAPI + Jinja application that renders the polished read-only surface
(landing, calculator, results explorer, CRR vs Basel 3.1 comparison) using the
shared --oah-* design tokens so it matches the Zensical docs, and mounts the REST
API in the same process.

Entry point: ``rwa_calc.ui.app.main:main`` (the ``rwa-ui`` console script).
"""

from __future__ import annotations
