"""
Render ``AGENTS.md`` from ``CLAUDE.md`` plus the Codex-runtime appendix.

Pipeline position:
    CLAUDE.md + .agents/codex-appendix.md -> sync_agent_instructions.py -> AGENTS.md

Key responsibilities:
- Strip ``CLAUDE-ONLY`` fenced blocks out of the shared body
- Append the Codex-sandbox-only notes from ``.agents/codex-appendix.md``
- ``--check``: fail on drift, with a diff a reader can act on

**The two-reader problem.** Two agent CLIs work this repo and neither reads the
other's instruction file: Claude Code injects ``CLAUDE.md`` and never looks at
``AGENTS.md``; OpenAI Codex CLI injects the repo-root ``AGENTS.md`` and never
looks at ``CLAUDE.md`` (confirmed against Codex 0.151.0 with
``codex debug prompt-input``, which renders the model-visible prompt without
calling the model). While ``AGENTS.md`` was a hand-written subset it drifted,
and drift here is not cosmetic — it instructs a coding agent. The last
hand-written revision told Codex to write domain logic as
``@pl.api.register_lazyframe_namespace``, a pattern ``scripts/arch_check.py``
check 14 rejects with no allowlist, and described a pre-fold six-stage pipeline
that the ``engine/registry.py`` + ``engine/orchestrator.py::run_stages`` fold
had already replaced.

So ``CLAUDE.md`` is the single canonical body and ``AGENTS.md`` is generated
from it, in the same shape as the other generated pages named in CLAUDE.md's
Documentation section.

**Fence grammar.** Content that is meaningless to a non-Claude reader — the
``.claude/agents/`` roster, the Agent tool, worktree provisioning, slash
commands — is wrapped in the project's existing ``<!-- ... -->`` marker idiom::

    <!-- CLAUDE-ONLY:START -->
    ... stripped from AGENTS.md, kept in CLAUDE.md ...
    <!-- CLAUDE-ONLY:END -->

Markers must sit alone on their own line, spelled exactly as above. Fences do
not nest, and an unclosed, unopened, or malformed marker is a hard error rather
than a silent pass-through: a fence that fails open does not merely fail to
hide a block, it renders the marker as ordinary text and publishes the whole
body the marker was written to withhold.

"Malformed" covers the **sentinel** as well as the kind. Guarding only the kind
left ``<!-- claude-only:start -->``, ``<!-- CLAUDE_ONLY:START -->``,
``<!-- CLAUDE ONLY:START -->``, ``<!-- Claude-Only:START -->`` and
``<!-- CLUADE-ONLY:START -->`` all leaking silently, so ``_is_near_miss_marker``
now rejects any whole-line HTML comment that is *close to* a marker without
being one — by named spelling and, for the variants no character class can
express, by similarity ratio.

**The near-miss predicate is deliberately biased toward false positives, and
widening it back is the wrong fix.** It over-triggers on whole-line HTML
comments that merely resemble a marker. Two known, entirely reasonable
comments hard-error today::

    <!-- this section is Claude only, for now -->
    <!-- ONLY:START of the appendix -->

That asymmetry is the point. A false positive is a loud, immediate hard error
naming the offending line, and it costs one reworded comment. A false negative
is silent and total: the unrecognised marker renders as ordinary text and the
whole block it was meant to withhold is published into ``AGENTS.md``, where
nothing downstream will ever notice. The five sentinel misspellings that leaked
through the first version of this guard are what that failure looks like in
practice.

So when this predicate rejects a comment you believe is innocent: **reword the
comment.** Do not loosen the regex, lower ``_NEAR_MISS_RATIO``, or add an
escape hatch — every one of those reopens the fail-open leak this exists to
close, and reopens it for the whole category rather than the one comment in
front of you. If the comment must survive verbatim, put it inside a fenced code
block, where markers are inert by design.

Markers inside a fenced code block (``` or ~~~) are inert and pass through
verbatim, so this grammar can be shown in a code block without the
documentation stripping itself.

The reverse direction never uses a fence. Codex-only notes must NOT live inside
``CLAUDE.md`` at all — Claude Code reads that file literally, so an HTML
comment hides nothing from it. They live in ``.agents/codex-appendix.md``,
which this script concatenates after the shared body.

``--check`` compares the committed target against a fresh render through
``Path.read_text``, which applies universal-newline translation — so the
comparison is **line-ending insensitive by design, not byte-exact**. The repo
carries no ``.gitattributes`` and CLAUDE.md is CRLF in a Windows checkout, so a
byte comparison would fail the gate on platform alone. Content drift is what it
detects; CRLF-vs-LF is not drift.

Usage:
    uv run python scripts/sync_agent_instructions.py            # write AGENTS.md
    uv run python scripts/sync_agent_instructions.py --check    # drift gate

Exit codes:
    0 = written (default), or --check found no drift
    1 = --check found drift, or a source fence is malformed

References:
- CLAUDE.md "Documentation" — generated pages are never hand-edited
- tests/contracts/test_agent_instructions_freshness.py — the committed gate
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_SOURCE = REPO_ROOT / "CLAUDE.md"
APPENDIX_SOURCE = REPO_ROOT / ".agents" / "codex-appendix.md"
TARGET = REPO_ROOT / "AGENTS.md"

REGEN_COMMAND = "uv run python scripts/sync_agent_instructions.py"

START_MARKER = "<!-- CLAUDE-ONLY:START -->"
END_MARKER = "<!-- CLAUDE-ONLY:END -->"

#: A marker line, which must be the whole line apart from leading whitespace.
#: Canonical uppercase-and-hyphen ``CLAUDE-ONLY`` is the only ACCEPTED spelling;
#: everything near it is a hard error, so there is exactly one way to write one.
_MARKER_RE = re.compile(r"^\s*<!--\s*CLAUDE-ONLY:(?P<kind>START|END)\s*-->\s*$")

#: Any whole-line HTML comment. Anchored at the start of the line on purpose:
#: CLAUDE.md's own Documentation section quotes both markers mid-sentence while
#: explaining this file, and prose about a marker is not a marker.
_COMMENT_LINE_RE = re.compile(r"^\s*<!--")

#: Near-miss spellings anyone actually types. The sentinel is matched
#: case-insensitively and across ``-``/``_``/space; the second alternative
#: catches a misspelt sentinel that still carries the ``ONLY:<kind>`` tail
#: (``CLUADE-ONLY:START``), which no character class over ``CLAUDE`` can reach.
_LOOSE_MARKER_RE = re.compile(
    r"^\s*<!--.*(?:CLAUDE[-_ ]?ONLY|ONLY[-_ :]{0,2}(?:START|END))",
    re.IGNORECASE,
)

#: How close a whole-line HTML comment must be to a canonical marker before it
#: is treated as a botched one. Measured on this repo, the gap is wide and the
#: threshold sits in the middle of it: every near-miss spelling scores >= 0.941
#: (including ``CLUADE-ONLY:STRT``, which misspells both halves), while the
#: unrelated whole-line comments in play — ``<!-- BEGIN GENERATED: id -->`` and
#: friends — score <= 0.542.
_NEAR_MISS_RATIO = 0.75

#: Fenced code block delimiters. Markers inside one are documentation, not
#: directives, and pass through untouched.
_CODE_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

#: Prepended to AGENTS.md. Deliberately visible prose and not only an HTML
#: comment: the reader is a model that is handed the rendered text, and a
#: comment is the one thing it may skim past.
BANNER = f"""\
<!-- GENERATED FILE. DO NOT EDIT BY HAND. -->

> **Generated file — do not hand-edit.** `AGENTS.md` is rendered from
> `CLAUDE.md` (the shared body, with `CLAUDE-ONLY` fenced blocks removed) plus
> `.agents/codex-appendix.md` (notes true only of the sandboxed Codex runtime).
> An edit made here is lost at the next render. Edit the source, then run:
>
> ```
> {REGEN_COMMAND}
> ```
>
> Freshness is gated by `tests/contracts/test_agent_instructions_freshness.py`.\
"""


class FenceError(ValueError):
    """A ``CLAUDE-ONLY`` fence in the shared body is malformed or unbalanced."""


def render() -> str:
    """The exact text ``AGENTS.md`` must hold, given the current sources."""
    shared = strip_claude_only(SHARED_SOURCE.read_text(encoding="utf-8"))
    appendix = APPENDIX_SOURCE.read_text(encoding="utf-8").strip("\n")
    return f"{BANNER}\n\n{shared}\n\n{appendix}\n"


def strip_claude_only(text: str) -> str:
    """``text`` with every ``CLAUDE-ONLY`` block, and its fence lines, removed.

    Raises ``FenceError`` on a malformed, nested, unopened or unclosed marker —
    the failure mode worth refusing is a fence that silently passes its content
    through to the generated file.

    Markers inside a fenced code block are inert, so the grammar can be
    documented in a code block without that documentation stripping itself.

    Blank lines that followed a stripped block are dropped while the preceding
    kept line is already blank, so removing a section leaves one blank-line
    separator rather than a double-blank scar.
    """
    kept: list[str] = []
    opened_at = 0
    healing = False
    in_code_block = False

    for number, line in enumerate(text.splitlines(), start=1):
        if _CODE_FENCE_RE.match(line):
            in_code_block = not in_code_block

        marker = None if in_code_block else _MARKER_RE.match(line)
        if marker is None and not in_code_block and _is_near_miss_marker(line):
            raise FenceError(
                f"{SHARED_SOURCE.name}:{number}: malformed CLAUDE-ONLY marker. A marker is "
                f"exactly {START_MARKER!r} or {END_MARKER!r} on a line of its own — an "
                f"unrecognised one is emitted as text and publishes the block it meant to "
                f"withhold:\n  {line}"
            )

        if marker is not None:
            if marker["kind"] == "START":
                if opened_at:
                    raise FenceError(
                        f"{SHARED_SOURCE.name}:{number}: CLAUDE-ONLY block opened again while "
                        f"the one at line {opened_at} is still open. Fences do not nest."
                    )
                opened_at = number
            else:
                if not opened_at:
                    raise FenceError(
                        f"{SHARED_SOURCE.name}:{number}: CLAUDE-ONLY end marker with no "
                        f"matching start."
                    )
                opened_at = 0
                healing = True
            continue

        if opened_at:
            continue

        if healing:
            if not line.strip() and kept and not kept[-1].strip():
                continue
            healing = False

        kept.append(line)

    if opened_at:
        raise FenceError(
            f"{SHARED_SOURCE.name}:{opened_at}: CLAUDE-ONLY block is never closed. Add "
            f"{END_MARKER!r} on its own line."
        )

    return "\n".join(kept).strip("\n")


def _is_near_miss_marker(line: str) -> bool:
    """True when a whole-line HTML comment is trying, and failing, to be a marker.

    Two independent signals, because what this guards is silent and total: an
    unrecognised marker is emitted as ordinary text and the block it opened is
    published in full. The regex catches the near-miss spellings people actually
    type; the similarity ratio catches the ones nobody predicted — transposed
    letters included, which no character class over ``CLAUDE`` can express.

    Deliberately biased toward false positives: it rejects innocent comments
    such as ``<!-- this section is Claude only, for now -->``. Reword the
    comment; do not loosen this. See the module docstring for why the asymmetry
    is the correct one, and ``tests/contracts/`` for the cases pinning both
    directions.
    """
    if not _COMMENT_LINE_RE.match(line):
        return False
    if _LOOSE_MARKER_RE.match(line):
        return True

    candidate = " ".join(line.split()).lower()
    return any(
        difflib.SequenceMatcher(None, candidate, canonical.lower()).ratio() >= _NEAR_MISS_RATIO
        for canonical in (START_MARKER, END_MARKER)
    )


def drift_diff(committed: str, rendered: str) -> str:
    """A unified diff of the committed target against a fresh render."""
    return "".join(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile="AGENTS.md (committed)",
            tofile="AGENTS.md (fresh render)",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render AGENTS.md from CLAUDE.md (CLAUDE-ONLY blocks stripped) plus "
            ".agents/codex-appendix.md."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if the committed AGENTS.md differs from a fresh render",
    )
    args = parser.parse_args()

    try:
        rendered = render()
    except FenceError as error:
        sys.stderr.write(f"{error}\n")
        return 1

    committed = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""

    if args.check:
        if committed != rendered:
            sys.stderr.write(
                "AGENTS.md no longer matches a fresh render of CLAUDE.md + "
                ".agents/codex-appendix.md. It is generated — edit the source, never the "
                f"target, then regenerate:\n  {REGEN_COMMAND}\n\n"
                f"{drift_diff(committed, rendered)}"
            )
            return 1
        return 0

    if committed == rendered:
        sys.stdout.write("AGENTS.md already matches its sources; nothing written.\n")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    sys.stdout.write(f"Wrote {TARGET.relative_to(REPO_ROOT).as_posix()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
