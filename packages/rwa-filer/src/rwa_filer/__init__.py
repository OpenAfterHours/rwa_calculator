"""
rwa-filer — validate regulatory returns and write them for submission.

A standalone package: it depends on Polars alone and never imports ``rwa_calc``.
``rwa-calc`` reaches it through one adapter; any other source of template-level
figures reaches it through the same public API or the ``rwa-filer`` command.

References:
- Bank of England Banking Taxonomy (the returns and rules this package targets)
- docs/development/workspace.md — how the two packages share one repository
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
