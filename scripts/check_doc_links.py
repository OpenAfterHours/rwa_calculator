"""Dead-link and dead-anchor census for ``docs/``, with a two-way ratchet.

The docs site has accumulated dead intra-page anchors (plan item P1.309: the
site generator collapses an em-dash gap in a heading to a *single* hyphen,
while many links guessed a double), and nothing failed when a page rename
orphaned its inbound links. This script counts both defects across every
``docs/**/*.md`` page: a relative link whose target file does not exist, or
whose ``#anchor`` matches no heading slug / explicit id in the target page.

The count is ratcheted **both ways** against ``scripts/docs_link_baseline.json``
(house style — cf. the supervisory validation register): an increase is a
regression and fails; a decrease is an improvement that must be banked with
``--update-baseline`` so it cannot silently regress back. Drive the number to
zero (plan item P4.56), then delete the baseline file — a missing baseline
means the gate is hard-zero.

Slugs are computed the way python-markdown's ``toc`` extension does (strip
non-word punctuation, collapse whitespace runs to one hyphen, ``_N`` suffixes
for duplicates), which reproduces the single-hyphen em-dash behaviour. The
approximation does not follow ``--8<--`` snippet includes; the ratchet absorbs
that.

Usage:
    uv run python scripts/check_doc_links.py                     # list + count
    uv run python scripts/check_doc_links.py --check             # ratchet gate
    uv run python scripts/check_doc_links.py --update-baseline   # bank the count

Exit codes:
    0 = listed (default), or --check matched the baseline
    1 = --check found a regression or an unbanked improvement
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = REPO_ROOT / "docs"
BASELINE_PATH = REPO_ROOT / "scripts" / "docs_link_baseline.json"

#: Directories under docs/ that are not site pages.
EXCLUDED_DIRS = {"assets", "overrides"}

_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+?)(?:\s+\"[^\"]*\")?\s*\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_ATTR_ID_RE = re.compile(r"\{[:#][^}]*\}\s*$")
_ATTR_ID_CAPTURE_RE = re.compile(r"#([\w-]+)")
_HTML_ID_RE = re.compile(r"<a\s+(?:id|name)=[\"']([^\"']+)[\"']")
_INLINE_ANCHOR_RE = re.compile(r"\[\]\(\)\{\s*#([\w-]+)")
_CODE_SPAN_RE = re.compile(r"`[^`]*`")
_EXTERNAL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class BrokenLink(NamedTuple):
    """One dead reference: the page, its line, the target, and why it is dead."""

    page: str
    line: int
    target: str
    reason: str


def census() -> list[BrokenLink]:
    """Every broken relative link/anchor across the docs tree, sorted."""
    pages = sorted(
        page
        for page in DOCS_ROOT.rglob("*.md")
        if not (set(page.relative_to(DOCS_ROOT).parts[:-1]) & EXCLUDED_DIRS)
    )
    anchors = {page: _page_anchors(page) for page in pages}
    broken: list[BrokenLink] = []
    for page in pages:
        broken.extend(_check_page(page, anchors))
    return broken


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dead-link and dead-anchor census for docs/, with a two-way ratchet."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="two-way ratchet against the baseline")
    mode.add_argument("--update-baseline", action="store_true", help="bank the current count")
    args = parser.parse_args()

    broken = census()
    count = len(broken)

    if args.update_baseline:
        BASELINE_PATH.write_text(
            json.dumps(
                {
                    "_comment": (
                        "Docs dead-link ratchet (scripts/check_doc_links.py --check). "
                        "The count may not INCREASE; a decrease must be banked here. "
                        "Drive to zero (P4.56) then delete this file for a hard-zero gate."
                    ),
                    "broken_links": count,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        sys.stderr.write(f"baseline banked at {count}\n")
        return 0

    if args.check:
        baseline = 0
        if BASELINE_PATH.exists():
            baseline = int(json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["broken_links"])
        if count > baseline:
            _report(broken)
            sys.stderr.write(
                f"\nREGRESSION: {count} broken links vs baseline {baseline}. "
                "Fix the new dead links (do not raise the baseline to clear a red gate).\n"
            )
            return 1
        if count < baseline:
            sys.stderr.write(
                f"IMPROVED: {count} broken links vs baseline {baseline}. Bank it:\n"
                "  uv run python scripts/check_doc_links.py --update-baseline\n"
            )
            return 1
        sys.stderr.write(f"[OK] {count} broken links == baseline\n")
        return 0

    _report(broken)
    sys.stderr.write(f"\n{count} broken links\n")
    return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _report(broken: list[BrokenLink]) -> None:
    for item in broken:
        sys.stdout.write(f"{item.page}:{item.line}: {item.target} ({item.reason})\n")


def _check_page(page: Path, anchors: dict[Path, set[str]]) -> list[BrokenLink]:
    broken: list[BrokenLink] = []
    rel = str(page.relative_to(REPO_ROOT)).replace("\\", "/")
    for line_no, line in enumerate(_content_lines(page), start=1):
        for match in _LINK_RE.finditer(_CODE_SPAN_RE.sub("", line)):
            target = match.group(1)
            problem = _check_target(page, target, anchors)
            if problem is not None:
                broken.append(BrokenLink(rel, line_no, target, problem))
    return broken


def _check_target(page: Path, target: str, anchors: dict[Path, set[str]]) -> str | None:
    if _EXTERNAL_RE.match(target) or target.startswith("//"):
        return None
    path_part, _, anchor = target.partition("#")

    if not path_part:
        dest = page
    else:
        base = DOCS_ROOT if path_part.startswith("/") else page.parent
        dest = (base / path_part.lstrip("/")).resolve()
        if not dest.exists():
            return "missing file"
        if dest.is_dir():
            dest = dest / "index.md"
            if not dest.exists():
                return "directory without index.md"

    if not anchor or dest.suffix != ".md":
        return None
    dest_anchors = anchors.get(dest)
    if dest_anchors is None:
        dest_anchors = _page_anchors(dest) if dest.exists() else set()
        anchors[dest] = dest_anchors
    if anchor not in dest_anchors:
        return "missing anchor"
    return None


def _content_lines(page: Path) -> list[str]:
    """The page's lines with fenced code blocks blanked out."""
    lines: list[str] = []
    in_fence = False
    for line in page.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            lines.append("")
            continue
        lines.append("" if in_fence else line)
    return lines


def _page_anchors(page: Path) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in _content_lines(page):
        heading = _HEADING_RE.match(line)
        if heading:
            text = heading.group(2)
            attr = _ATTR_ID_RE.search(text)
            if attr:
                explicit = _ATTR_ID_CAPTURE_RE.search(attr.group(0))
                text = text[: attr.start()].rstrip()
                if explicit:
                    anchors.add(explicit.group(1))
                    continue
            slug = _slugify(_strip_markup(text))
            if slug in seen:
                seen[slug] += 1
                slug = f"{slug}_{seen[slug]}"
            else:
                seen[slug] = 0
            anchors.add(slug)
        for html_id in _HTML_ID_RE.finditer(line):
            anchors.add(html_id.group(1))
        for inline in _INLINE_ANCHOR_RE.finditer(line):
            anchors.add(inline.group(1))
    return anchors


def _strip_markup(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("*", "").replace("__", "")


def _slugify(text: str) -> str:
    """python-markdown ``toc`` default slug: strip punctuation, hyphenate runs."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


if __name__ == "__main__":
    raise SystemExit(main())
