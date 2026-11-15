"""
Each shipped release's measured numbers, for the tests that hold its packaged data to them.

``tests/releases/<version>/measurements.json`` is written by
``scripts/build_filer_release.py`` (``rwa_filer.release_build.measure_release``)
when a release is built, checked or re-measured — never by hand. The tests read
it, so a second shipped release is tested with no test edits, and a number that
moves is re-measured rather than typed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rwa_filer.release import shipped_releases

RELEASES_DIR = Path(__file__).parent / "releases"


def measurements_path(version: str) -> Path:
    """Where release ``version``'s measurement file lives."""
    return RELEASES_DIR / version / "measurements.json"


def measurements(version: str) -> dict[str, Any]:
    """Release ``version``'s measured numbers."""
    return json.loads(measurements_path(version).read_text(encoding="utf-8"))


def shipped_measurements() -> dict[str, dict[str, Any]]:
    """Every shipped release's measured numbers, by version."""
    return {version: measurements(version) for version in shipped_releases()}


def oracle_path(version: str, name: str) -> Path:
    """An Arelle oracle file of release ``version`` (``releases/<version>/oracles/``)."""
    return RELEASES_DIR / version / "oracles" / name
