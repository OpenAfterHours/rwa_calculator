"""Unit tests for the CLI-input validators shared by the developer scripts.

These guard the ``subprocess`` argv interpolation points in deploy.py,
worktree.py, and profile_memory.py: a valid value is returned in sanitised form
(unchanged for the semver/git-ref/framework allowlists, canonicalised for the
ISO date), an invalid one fails fast via ``SystemExit`` before any command is
built.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _validate import (  # noqa: E402  # ty: ignore[unresolved-import]
    validate_framework,
    validate_git_ref,
    validate_iso_date,
    validate_semver,
)


class TestValidateSemver:
    @pytest.mark.parametrize("value", ["0.3.2", "1.0.0", "10.20.30"])
    def test_accepts_strict_semver(self, value: str) -> None:
        assert validate_semver(value) == value

    @pytest.mark.parametrize(
        "value",
        ["1.2", "0.3.2-rc1", "v0.3.2", "0.3.2 ", "0.3.2; rm -rf /", "--bump"],
    )
    def test_rejects_non_semver(self, value: str) -> None:
        with pytest.raises(SystemExit):
            validate_semver(value)


class TestValidateGitRef:
    @pytest.mark.parametrize(
        "value",
        ["HEAD", "master", "origin/main", "v0.3.1", "feature/x-1", "a1b2c3d"],
    )
    def test_accepts_safe_ref(self, value: str) -> None:
        assert validate_git_ref(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "--upload-pack=evil",  # leading dash → option injection
            "-evil",
            "a..b",  # range expression
            "HEAD@{1}",  # reflog selector
            "main.lock",  # trailing .lock
            "feature/",  # trailing slash
            "a b",  # whitespace
            "a~1",  # ancestry metachar
            "",  # empty
        ],
    )
    def test_rejects_unsafe_ref(self, value: str) -> None:
        with pytest.raises(SystemExit):
            validate_git_ref(value)


class TestValidateIsoDate:
    @pytest.mark.parametrize("value", ["2026-01-01", "2026-12-31"])
    def test_accepts_iso_date(self, value: str) -> None:
        assert validate_iso_date(value) == value

    def test_returns_canonical_form(self) -> None:
        # The value is reformatted from the parsed date (a derived value), not
        # echoed back; canonical input is therefore idempotent.
        assert validate_iso_date("2026-01-01") == "2026-01-01"

    @pytest.mark.parametrize(
        "value",
        ["2026-13-40", "01/01/2026", "not-a-date", "2026-01-01; rm -rf /", ""],
    )
    def test_rejects_non_iso_date(self, value: str) -> None:
        with pytest.raises(SystemExit):
            validate_iso_date(value)


class TestValidateFramework:
    @pytest.mark.parametrize("value", ["crr", "basel31"])
    def test_accepts_known_framework(self, value: str) -> None:
        assert validate_framework(value) == value

    @pytest.mark.parametrize(
        "value",
        ["ifrs9", "CRR", "basel31 ", "crr; rm -rf /", "--bump", ""],
    )
    def test_rejects_unknown_framework(self, value: str) -> None:
        with pytest.raises(SystemExit):
            validate_framework(value)
