"""
Fixtures for the referee's tests: a referee whose workers are a scripted stand-in.

References:
- packages/rwa-filer/tests/referee_builders.py — the stand-in and what it runs on
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from referee_builders import Referee, make_referee
from rwa_filer.referee import runner

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def trimmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Referee:
    """A referee that treats the (tiny) entry point as too large to load whole."""
    monkeypatch.setattr(runner, "AUTO_FULL_LIMIT_MB", 0.0)
    return make_referee(tmp_path, monkeypatch)


@pytest.fixture
def untrimmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Referee:
    """A referee on the same entry point, small enough to run against the official one."""
    return make_referee(tmp_path, monkeypatch)
