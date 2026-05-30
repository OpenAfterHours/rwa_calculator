"""Unit tests for the changelog promotion helper used by scripts/deploy.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _deploy_changelog import (  # noqa: E402  # ty: ignore[unresolved-import]
    EMPTY_UNRELEASED_BLOCK,
    promote_unreleased,
    update_version_table,
)

TODAY = "2026-05-26"


def _wrap(unreleased_body: str) -> str:
    """Build a minimal changelog containing the given [Unreleased] body + one prior version."""
    return (
        "# Changelog\n"
        "\n"
        "## [Unreleased]\n"
        f"{unreleased_body}"
        "---\n"
        "\n"
        "## [0.2.14] - 2026-05-25\n"
        "\n"
        "### Added\n"
        "- Prior release bullet.\n"
        "\n"
        "---\n"
    )


class TestPromoteUnreleased:
    def test_placeholder_only_falls_back_to_version_bump_bullet(self):
        body = (
            "\n"
            "### Added\n"
            "- (Next release changes will go here)\n"
            "\n"
            "### Changed\n"
            "- (Next release changes will go here)\n"
            "\n"
        )
        content = _wrap(body)

        result = promote_unreleased(content, "0.2.15", today=TODAY)

        assert "## [0.2.15] - 2026-05-26" in result
        assert "Version bump for PyPI release" in result
        # [Unreleased] is reset to placeholder.
        assert EMPTY_UNRELEASED_BLOCK in result
        # Placeholder bullets do not survive into the new version section.
        new_section = result.split("## [0.2.15]")[1].split("## [0.2.14]")[0]
        assert "(Next release changes will go here)" not in new_section
        # Prior version is intact.
        assert "- Prior release bullet." in result

    def test_real_bullets_are_promoted_into_new_version(self):
        body = (
            "\n"
            "### Changed\n"
            "- Real change one.\n"
            "- Real change two.\n"
            "\n"
            "### Added\n"
            "- Real addition.\n"
            "\n"
        )
        content = _wrap(body)

        result = promote_unreleased(content, "0.2.15", today=TODAY)

        new_section = result.split("## [0.2.15]")[1].split("## [0.2.14]")[0]
        assert "- Real change one." in new_section
        assert "- Real change two." in new_section
        assert "- Real addition." in new_section
        assert "Version bump for PyPI release" not in new_section

        # [Unreleased] is reset cleanly.
        unreleased_section = result.split("## [Unreleased]")[1].split("## [0.2.15]")[0]
        assert "- Real change one." not in unreleased_section
        assert "(Next release changes will go here)" in unreleased_section

    def test_mixed_placeholder_and_real_keeps_only_real(self):
        body = (
            "\n"
            "### Added\n"
            "- (Next release changes will go here)\n"
            "- Real addition survives.\n"
            "\n"
            "### Changed\n"
            "- (Next release changes will go here)\n"
            "\n"
        )
        content = _wrap(body)

        result = promote_unreleased(content, "0.2.15", today=TODAY)

        new_section = result.split("## [0.2.15]")[1].split("## [0.2.14]")[0]
        assert "- Real addition survives." in new_section
        assert "(Next release changes will go here)" not in new_section
        # Changed had only a placeholder; the empty section is dropped from the new block.
        assert "### Changed" not in new_section

    def test_rerun_with_existing_version_returns_content_unchanged(self):
        content = _wrap("\n### Added\n- Some real bullet.\n\n")
        # Pretend the version is already there.
        content_with_version = (
            content + "\n## [0.2.15] - 2026-05-26\n\n### Changed\n- whatever\n\n---\n"
        )

        result = promote_unreleased(content_with_version, "0.2.15", today=TODAY)

        assert result == content_with_version

    def test_subsection_order_is_preserved(self):
        body = (
            "\n"
            "### Fixed\n"
            "- Fix bullet.\n"
            "\n"
            "### Added\n"
            "- Add bullet.\n"
            "\n"
            "### Changed\n"
            "- Change bullet.\n"
            "\n"
        )
        content = _wrap(body)

        result = promote_unreleased(content, "0.2.15", today=TODAY)
        new_section = result.split("## [0.2.15]")[1].split("## [0.2.14]")[0]

        fixed_pos = new_section.index("### Fixed")
        added_pos = new_section.index("### Added")
        changed_pos = new_section.index("### Changed")
        assert fixed_pos < added_pos < changed_pos


class TestUpdateVersionTable:
    def test_no_table_returns_content_unchanged(self):
        content = "no table here\n"
        assert update_version_table(content, "0.2.15", "0.2.14", TODAY) == content

    def test_table_row_is_updated(self):
        content = (
            "| Version | Date       | Status   |\n"
            "|---------|------------|----------|\n"
            "| 0.2.14 | 2026-05-25 | Current |\n"
            "| 0.2.13 | 2026-05-23 | Previous |\n"
        )

        result = update_version_table(content, "0.2.15", "0.2.14", TODAY)

        assert "| 0.2.15 | 2026-05-26 | Current |" in result
        assert "| 0.2.14 | 2026-05-26 | Previous |" in result


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
