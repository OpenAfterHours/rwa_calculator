"""
Contract gate: every ``--8<--`` snippet include in docs/ resolves to real content.

Why this exists
---------------
``zensical.toml`` sets ``[project.markdown_extensions.pymdownx.snippets]
check_paths = false``. A snippet whose path does not exist therefore emits
**nothing** and raises **nothing**: the published page silently loses the
content and ``zensical build`` still exits 0. Nothing else in the estate gates
this, so the failure is invisible to every tier of the test suite *and* to the
docs CI job.

Measured, not hypothetical. The S1 stage/domain move (2026-08-29) repointed
``engine/stages/{hierarchy,classify}/`` to ``engine/{hierarchy,classify}/`` and
left four includes behind. The full suite stayed green, ``zensical build``
exited 0, and two published pages had lost 52,102 characters between them --
including the entire worked example on the retail exposure-class page. It was
found by reading the build output, not by any check. Reverting a single path
and rebuilding reproduces it exactly: build still exits 0, the page silently
drops 27,563 characters.

What this checks, and what it does not
--------------------------------------
Checked, from source, with no rendered site required:

- the included file exists;
- a declared ``:start:end`` range lies inside the file (this is the drift case
  -- when code is deleted above a snippet, or the file shrinks, the range runs
  off the end and the include silently truncates);
- the selected lines are not all blank.

**Not** checked: whether an in-bounds range still frames the *intended* code.
A range that has slid by a few lines but still lands on valid source will pass
here; catching that needs a golden of the rendered excerpt, which is a heavier
gate than this one. Stated plainly so nobody reads this as stronger than it is.

Deliberately source-based rather than rendered-HTML based: it keeps the test in
the dev loop (file reads, no ``zensical`` invocation and no built ``site/``),
and a missing include renders as nothing *because* the source does not resolve,
so checking at the source catches the same defect strictly earlier. The only
thing the HTML form would add is "zensical failed to include a file that does
exist", which is a toolchain bug rather than our defect class.

References:
- zensical.toml (``check_paths = false`` -- the reason this is silent)
- docs/plans/architecture-review-2026-08-29.md §2 (the move that exposed it)
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"

# Real directives sit on their own line (optionally indented). Anchoring to the
# line start excludes prose that merely *describes* the syntax -- e.g.
# docs/development/citation-tracking.md explains the generator by writing
# ``--8<-- "path:start:end"`` mid-sentence, which is documentation, not an
# include.
SNIPPET = re.compile(r'^[ \t]*--8<--[ \t]+"([^"]+)"', re.MULTILINE)

# The population is ~220 includes across the docs tree. The floor guards against
# this test passing because the scan found nothing (a moved docs/ root, a
# changed directive syntax, a regex that stopped matching) -- an empty scan and
# a clean estate are otherwise indistinguishable. Well below the real count so
# ordinary docs churn does not trip it.
MINIMUM_EXPECTED_SNIPPETS = 150


def _snippet_sites() -> list[tuple[Path, int, str]]:
    """Every snippet directive in docs/ as (markdown file, line number, spec)."""
    sites: list[tuple[Path, int, str]] = []
    for md in sorted(DOCS_ROOT.rglob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        for match in SNIPPET.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            sites.append((md, line_no, match.group(1)))
    return sites


def _parse(spec: str) -> tuple[str, int | None, int | None]:
    """Split ``path`` or ``path:start:end`` into its parts.

    Only the numeric-range form is treated as a range; anything else is a
    whole-file include, so an unrecognised pymdownx selector is checked for
    existence rather than mis-parsed into a bogus range.
    """
    head, _, tail = spec.rpartition(":")
    path, _, mid = head.rpartition(":")
    if path and mid.isdigit() and tail.isdigit():
        return path, int(mid), int(tail)
    return spec, None, None


def _describe(md: Path, line_no: int, spec: str, problem: str) -> str:
    return f"{md.relative_to(REPO_ROOT).as_posix()}:{line_no}: --8<-- {spec!r} -- {problem}"


def test_every_doc_snippet_resolves_to_content() -> None:
    """No snippet include may silently publish nothing."""
    # Arrange
    sites = _snippet_sites()
    cache: dict[str, list[str] | None] = {}
    problems: list[str] = []

    # Act
    for md, line_no, spec in sites:
        path, start, end = _parse(spec)
        if path not in cache:
            target = REPO_ROOT / path
            cache[path] = (
                target.read_text(encoding="utf-8", errors="replace").splitlines()
                if target.is_file()
                else None
            )
        lines = cache[path]

        if lines is None:
            problems.append(_describe(md, line_no, spec, f"no such file: {path}"))
            continue
        if start is None or end is None:
            if not any(line.strip() for line in lines):
                problems.append(_describe(md, line_no, spec, "file is empty"))
            continue
        if start < 1 or end < start or end > len(lines):
            problems.append(
                _describe(md, line_no, spec, f"range {start}:{end} outside 1:{len(lines)}")
            )
            continue
        if not any(line.strip() for line in lines[start - 1 : end]):
            problems.append(_describe(md, line_no, spec, f"lines {start}:{end} are blank"))

    # Assert
    assert not problems, (
        f"{len(problems)} of {len(sites)} doc snippet include(s) resolve to nothing. "
        "pymdownx renders these as SILENT EMPTY -- the page loses the content and "
        "`zensical build` still exits 0, so nothing else will tell you:\n  " + "\n  ".join(problems)
    )


def test_snippet_scan_is_not_vacuous() -> None:
    """The scan must find the real population, or the gate above proves nothing."""
    # Arrange / Act
    sites = _snippet_sites()

    # Assert
    assert len(sites) >= MINIMUM_EXPECTED_SNIPPETS, (
        f"found only {len(sites)} snippet directives under {DOCS_ROOT.name}/, expected at "
        f"least {MINIMUM_EXPECTED_SNIPPETS}. Either the docs tree moved, the directive "
        "syntax changed, or SNIPPET stopped matching -- in any of those cases "
        "test_every_doc_snippet_resolves_to_content is passing over an empty scan."
    )
