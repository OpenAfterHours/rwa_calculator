"""
Changelog promotion helper for scripts/deploy.py.

Engineers append bullets under `## [Unreleased]` as work lands. When deploy.py
runs, this module:

1. Extracts those bullets,
2. Drops placeholder lines ("(Next release changes will go here)"),
3. Writes the real bullets under a new `## [version] - YYYY-MM-DD` section,
4. Resets `[Unreleased]` to the canonical empty placeholder.

The two public entry points are pure string transforms so they can be unit-tested
without touching the filesystem.
"""

from __future__ import annotations

import re
from datetime import date

PLACEHOLDER_BULLET = "- (Next release changes will go here)"

EMPTY_UNRELEASED_BLOCK = (
    "## [Unreleased]\n"
    "\n"
    "### Added\n"
    f"{PLACEHOLDER_BULLET}\n"
    "\n"
    "### Changed\n"
    f"{PLACEHOLDER_BULLET}\n"
    "\n"
    "---\n"
)

FALLBACK_SUBSECTIONS = "### Changed\n- Version bump for PyPI release\n\n"


def promote_unreleased(content: str, new_version: str, *, today: str | None = None) -> str:
    """
    Promote the `[Unreleased]` block into a new `## [version] - today` section.

    Returns the rewritten content. If `new_version` already has a section in the
    file, content is returned unchanged.
    """
    today = today or date.today().strftime("%Y-%m-%d")

    if f"## [{new_version}]" in content:
        return content

    header = "## [Unreleased]"
    terminator = "\n---\n"
    start = content.find(header)
    body_start = content.find("\n", start) if start != -1 else -1
    term_idx = content.find(terminator, body_start) if body_start != -1 else -1

    if start == -1 or term_idx == -1:
        return _insert_fallback_version(content, new_version, today)

    body = content[body_start + 1 : term_idx]
    end = term_idx + len(terminator)

    sections = _parse_subsections(body)
    real_sections = _drop_placeholders(sections)
    new_version_body = _format_subsections(real_sections) or FALLBACK_SUBSECTIONS

    new_block = f"## [{new_version}] - {today}\n\n{new_version_body}---\n"
    replacement = f"{EMPTY_UNRELEASED_BLOCK}\n{new_block}"

    return content[:start] + replacement + content[end:]


def update_version_table(
    content: str,
    new_version: str,
    old_version: str,
    today: str,
) -> str:
    """Update the optional version table near the bottom of the changelog."""
    table_pattern = rf"\| {re.escape(old_version)} \| [\d-]+ \| Current \|"
    if not re.search(table_pattern, content):
        return content

    content = re.sub(r"\| Previous \|$", "| - |", content, flags=re.MULTILINE)
    table_replacement = (
        f"| {new_version} | {today} | Current |\n| {old_version} | {today} | Previous |"
    )
    return re.sub(table_pattern, table_replacement, content)


def _parse_subsections(body: str) -> dict[str, list[str]]:
    """Split an [Unreleased] body into `{section_name: [bullet_line, ...]}`."""
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in body.split("\n"):
        if line.startswith("###") and line[3:4].isspace():
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        if line.startswith("- "):
            sections[current].append(line)

    return sections


def _drop_placeholders(sections: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drop placeholder bullets and any sections that become empty."""
    cleaned: dict[str, list[str]] = {}
    for name, bullets in sections.items():
        real = [b for b in bullets if b.strip() != PLACEHOLDER_BULLET]
        if real:
            cleaned[name] = real
    return cleaned


def _format_subsections(sections: dict[str, list[str]]) -> str:
    if not sections:
        return ""
    parts = [f"### {name}\n" + "\n".join(bullets) for name, bullets in sections.items()]
    return "\n\n".join(parts) + "\n\n"


def _insert_fallback_version(content: str, new_version: str, today: str) -> str:
    """Insert a stub version section when [Unreleased] is missing."""
    new_section = f"## [{new_version}] - {today}\n\n{FALLBACK_SUBSECTIONS}---\n\n"
    match = re.search(r"^## \[\d", content, re.MULTILINE)
    if match is None:
        return content.rstrip() + f"\n\n{new_section}"
    return content[: match.start()] + new_section + content[match.start() :]
