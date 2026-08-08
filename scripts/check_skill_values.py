"""Ban hand-written regulatory values in the `.claude/skills` prose.

The regulatory skills are read by every role-agent before it designs a scenario,
writes a test, or implements an engine change. When a skill restates a value the
rulepack already holds, the copy drifts and agents design against a number the
engine never used. This has happened repeatedly:

- corporate CQS5 under Basel 3.1 was stated as 100% in **three** skill files
  while the pack, the engine and PS1/26 Art. 122(2) Table 6 all said 150%;
- the QRRE limit was stated as GBP 100k against a pack value of GBP 90k.

`scripts/generate_regulatory_tables.py` fixes the supply side by rendering pack
values into marked regions of the skill files. This script fixes the demand
side: outside those regions, a percentage token in a skill file is an error.

Percentages — not every number — because that is the demonstrated defect class.
Formula coefficients (`R = 0.12`, `G(0.999) = 3.0902323`), article numbers,
CQS grades and dates are all legitimate skill prose and are left alone.

Genuine exceptions exist and are listed in ``ALLOWANCES`` below, each with a
justification. Two kinds qualify: a **verbatim quotation** of article text, and
a number whose authority is something other than the rulepack (a published EBA
validation-rule expression, say). "It is more readable inline" does not qualify
— that is exactly the argument that produced the CQS5 defect.

Usage:
    uv run python scripts/check_skill_values.py            # report and exit 1 on findings
    uv run python scripts/check_skill_values.py --check    # identical; for symmetry

Exit codes:
    0 = no hand-written regulatory values outside generated regions
    1 = findings (or a stale allowance that no longer matches anything)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"

BEGIN_MARKER = re.compile(r"^<!-- BEGIN GENERATED: ([a-z0-9-]+) -->$")
END_MARKER = re.compile(r"^<!-- END GENERATED: ([a-z0-9-]+) -->$")

#: A percentage written out: `20%`, `72.5 %`, `0,03 %`.
PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s*%")

#: Stripped before scanning: `%20`/`%29` inside a percent-encoded URL are not
#: regulatory values, and no skill states a value only inside a link.
URL = re.compile(r"https?://\S+")

#: Sentinel for "every percentage in this file is exempt".
ALL = "*"


@dataclass(frozen=True)
class Allowance:
    """One justified exception to the no-values-in-prose rule."""

    path: str  # repo-relative, POSIX separators
    tokens: tuple[str, ...]  # matched text, or (ALL,)
    reason: str


ALLOWANCES: tuple[Allowance, ...] = (
    Allowance(
        ".claude/skills/basel31/SKILL.md",
        ("100%", "150%"),
        "Narrates the CQS5 defect this machinery exists to prevent. The two "
        "numbers are the wrong value and the right one; stating them is the "
        "point of the passage, not a lookup.",
    ),
    Allowance(
        ".claude/skills/crr/references/irb-parameters.md",
        ("0,03 %",),
        "Verbatim quotation of CRR Art. 160(1) and 163(1). The quotation is "
        "load-bearing: the surrounding prose turns on the articles' exact "
        "wording and their missing CGCB limb.",
    ),
    Allowance(
        ".claude/skills/crr/references/reporting-validation-rules.md",
        (ALL,),
        "Transcribes published EBA validation-rule expressions verbatim (e.g. "
        "`{r0270, c0215} = {r0270, c0200} * 1250%`). Their authority is the "
        "rules JSON under src/rwa_calc/reporting/validations/rules/, not the "
        "rulepack, and a rule expression is meaningless with its factor "
        "removed.",
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ban hand-written regulatory values in .claude/skills prose."
    )
    parser.add_argument("--check", action="store_true", help="accepted for symmetry; the default")
    parser.parse_args()

    findings, used = _scan()
    stale = [a for a in ALLOWANCES if a not in used]

    for path, line_no, token, context in findings:
        sys.stderr.write(f"{path}:{line_no}: hand-written regulatory value {token!r}\n")
        sys.stderr.write(f"    {context}\n")
    if findings:
        sys.stderr.write(
            f"\n{len(findings)} hand-written regulatory value(s) in skill prose.\n"
            "Skill files must not restate rulepack values. Either:\n"
            "  - move the value into a generated fragment "
            "(add it to FRAGMENTS in scripts/generate_regulatory_tables.py, then\n"
            "    re-run: uv run python scripts/generate_regulatory_tables.py), or\n"
            "  - rewrite the prose to name the pack entry instead of its value, or\n"
            "  - if it is genuinely not a rulepack value, add a justified entry to\n"
            "    ALLOWANCES in scripts/check_skill_values.py.\n"
        )
    for allowance in stale:
        sys.stderr.write(
            f"stale allowance: {allowance.path} {allowance.tokens} matches nothing — remove it\n"
        )

    if findings or stale:
        return 1
    sys.stderr.write("skill prose is free of hand-written regulatory values\n")
    return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _scan() -> tuple[list[tuple[str, int, str, str]], set[Allowance]]:
    findings: list[tuple[str, int, str, str]] = []
    used: set[Allowance] = set()

    for path in sorted(SKILLS_ROOT.rglob("*.md")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        allowances = [a for a in ALLOWANCES if a.path == rel]
        for line_no, line in _prose_lines(path):
            for match in PERCENT.finditer(URL.sub("", line)):
                token = match.group(0)
                allowed = next(
                    (a for a in allowances if ALL in a.tokens or token in a.tokens), None
                )
                if allowed is not None:
                    used.add(allowed)
                    continue
                findings.append((rel, line_no, token, line.strip()))
    return findings, used


def _prose_lines(path: Path) -> list[tuple[int, str]]:
    """Every line outside a `<!-- BEGIN/END GENERATED -->` region."""
    out: list[tuple[int, str]] = []
    inside = False
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if BEGIN_MARKER.match(stripped):
            inside = True
            continue
        if END_MARKER.match(stripped):
            inside = False
            continue
        if not inside:
            out.append((line_no, line))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
