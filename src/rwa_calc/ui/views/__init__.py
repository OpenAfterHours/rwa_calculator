"""
Framework-agnostic UI view helpers.

These modules transform engine bundles into presentation-ready data structures
(plain dicts and Polars DataFrames) with no UI-framework imports, so the
Zensical docs site, the FastAPI/Jinja app, and Marimo can all render the same
numbers from one source.
"""

from __future__ import annotations
