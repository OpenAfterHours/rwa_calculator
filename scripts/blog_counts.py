"""
Canonical project counts for the blog and docs.

Pipeline position:
    Standalone reporting script (not part of the calculation pipeline).

Key responsibilities:
- Emit one authoritative set of "how big is the project" figures so that
  narrative prose (the blog under ``docs/blog/``, the docs site, READMEs) can
  cite a single source instead of hand-copying numbers that then drift.
- Count test functions per pyramid layer, source/test file counts, the number
  of architectural checks, role agents, pipeline stages, and the loop.sh size.

Why this exists:
    A blog audit (June 2026) found that the most common form of staleness was
    hand-typed figures: "~5,300 tests" long after the suite passed 7,000, "eight
    architectural checks" once there were seventeen, "four agents" once there
    were seven. None of those are judgement calls -- they are mechanical counts.
    This script makes them reproducible, so a correction is ``uv run python
    scripts/blog_counts.py`` rather than a fresh round of grepping.

Usage:
    uv run python scripts/blog_counts.py            # human-readable table
    uv run python scripts/blog_counts.py --json      # machine-readable JSON
    uv run python scripts/blog_counts.py --markdown   # a Markdown table for docs

Notes:
- Deliberately dependency-free (stdlib only) and fast: it walks the tree and
  greps with a regex; it does NOT import ``rwa_calc`` or invoke ``pytest``, so
  the figures are "definition counts" (``def test_``), not collected items.
  ``pytest --co`` collects a somewhat larger number (parametrised cases expand);
  when a blog post wants the "collected" figure, say "~N collected" and treat
  this script's total as the lower-bound function count.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_DEF_RE = re.compile(rb"^\s*(?:async\s+)?def\s+test_\w*", re.MULTILINE)
ARCH_CHECK_RE = re.compile(r"check\s+(\d+)")

# Ordered so the human-readable table reads top-of-pyramid first.
TEST_LAYERS: tuple[tuple[str, str], ...] = (
    ("unit", "tests/unit"),
    ("acceptance", "tests/acceptance"),
    ("acceptance_stress", "tests/acceptance/stress"),
    ("contracts", "tests/contracts"),
    ("integration", "tests/integration"),
    ("bdd", "tests/bdd"),
    ("benchmarks", "tests/benchmarks"),
    ("oracle", "tests/oracle"),
)


@dataclass(frozen=True)
class ProjectCounts:
    """An immutable snapshot of the project's headline figures."""

    test_functions_total: int
    test_functions_by_layer: dict[str, int]
    src_python_files: int
    test_files_with_tests: int
    test_python_files_total: int
    arch_checks: int
    role_agents: int
    pipeline_stages: int
    loop_sh_lines: int
    engine_subpackages: int
    head_commit: str


def collect_counts(root: Path = REPO_ROOT) -> ProjectCounts:
    """Walk the repository and compute the canonical counts."""
    by_layer = {name: _count_test_defs(root / path) for name, path in TEST_LAYERS}
    # The whole-suite total counts every test file once; layer counts may overlap
    # (acceptance_stress is nested under acceptance), so total is computed
    # independently rather than summed from the layers.
    total = _count_test_defs(root / "tests")

    return ProjectCounts(
        test_functions_total=total,
        test_functions_by_layer=by_layer,
        src_python_files=_count_files(root / "src", "*.py"),
        test_files_with_tests=_count_files_containing(root / "tests", TEST_DEF_RE),
        test_python_files_total=_count_files(root / "tests", "*.py"),
        arch_checks=_highest_arch_check(root / "scripts" / "arch_check.py"),
        role_agents=_count_role_agents(root / ".claude" / "agents"),
        pipeline_stages=_count_stage_specs(root / "src" / "rwa_calc" / "engine" / "registry.py"),
        loop_sh_lines=_count_lines(root / "loop.sh"),
        engine_subpackages=_count_subpackages(root / "src" / "rwa_calc" / "engine"),
        head_commit=_head_commit(root),
    )


def render_table(counts: ProjectCounts) -> str:
    """Render a human-readable, aligned text table."""
    layers = counts.test_functions_by_layer
    lines = [
        f"Project counts @ {counts.head_commit}",
        "=" * 48,
        f"  {'test functions (total)':<34}{counts.test_functions_total:>12,}",
    ]
    lines += [f"    - {name:<30}{n:>12,}" for name, n in layers.items()]
    lines += [
        f"  {'source .py files (src/)':<34}{counts.src_python_files:>12,}",
        f"  {'test files with tests':<34}{counts.test_files_with_tests:>12,}",
        f"  {'test .py files (total)':<34}{counts.test_python_files_total:>12,}",
        f"  {'architectural checks (arch_check)':<34}{counts.arch_checks:>12,}",
        f"  {'role agents (.claude/agents)':<34}{counts.role_agents:>12,}",
        f"  {'pipeline stages (registry)':<34}{counts.pipeline_stages:>12,}",
        f"  {'engine subpackages':<34}{counts.engine_subpackages:>12,}",
        f"  {'loop.sh lines':<34}{counts.loop_sh_lines:>12,}",
    ]
    return "\n".join(lines)


def render_markdown(counts: ProjectCounts) -> str:
    """Render a Markdown table for pasting into docs."""
    rows = [
        ("Test functions (total)", counts.test_functions_total),
        *((f"&nbsp;&nbsp;{name}", n) for name, n in counts.test_functions_by_layer.items()),
        ("Source `.py` files (`src/`)", counts.src_python_files),
        ("Test files with tests", counts.test_files_with_tests),
        ("Architectural checks", counts.arch_checks),
        ("Role agents", counts.role_agents),
        ("Pipeline stages", counts.pipeline_stages),
        ("Engine subpackages", counts.engine_subpackages),
        ("`loop.sh` lines", counts.loop_sh_lines),
    ]
    header = f"| Metric | Count (@ `{counts.head_commit}`) |\n| --- | ---: |"
    body = "\n".join(f"| {label} | {value:,} |" for label, value in rows)
    return f"{header}\n{body}"


def _count_test_defs(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(len(TEST_DEF_RE.findall(p.read_bytes())) for p in directory.rglob("*.py"))


def _count_files(directory: Path, pattern: str) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.rglob(pattern))


def _count_files_containing(directory: Path, pattern: re.Pattern[bytes]) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.rglob("*.py") if pattern.search(p.read_bytes()))


def _highest_arch_check(path: Path) -> int:
    if not path.is_file():
        return 0
    numbers = [int(m) for m in ARCH_CHECK_RE.findall(path.read_text(encoding="utf-8"))]
    return max(numbers, default=0)


def _count_role_agents(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    # The probe-child agent is a throwaway nesting probe, not a build-loop role.
    return sum(1 for p in directory.glob("*.md") if p.stem != "probe-child")


def _count_stage_specs(path: Path) -> int:
    if not path.is_file():
        return 0
    return path.read_text(encoding="utf-8").count("StageSpec(")


def _count_subpackages(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(
        1
        for p in directory.iterdir()
        if p.is_dir() and p.name != "__pycache__" and (p / "__init__.py").exists()
    )


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _head_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--markdown", action="store_true", help="emit a Markdown table")
    args = parser.parse_args()

    counts = collect_counts()
    if args.json:
        print(json.dumps(asdict(counts), indent=2))
    elif args.markdown:
        print(render_markdown(counts))
    else:
        print(render_table(counts))


if __name__ == "__main__":
    main()
