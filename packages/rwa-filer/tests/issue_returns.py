"""
The minimal correct return of each publisher issue, for Arelle and the engine.

Each issue in a release's register (``rwa_filer/boe/data/issues/<release>.json``)
carries the smallest return that follows the reporting instructions and shows
the issue: its ``example``. This module builds that return from the PACKAGED
register, so the return the Bank reads in the shared write-up
(``docs/rwa-filer/publisher-issues.md``) is exactly the one Arelle evaluated.

Arelle's verdict on each example — ``[satisfied, unsatisfied]`` for every rule
the example is measured on — is kept in
``tests/releases/<release>/oracles/publisher_issues_oracle.json``, and
``boe/test_publisher_issues_oracle.py`` holds the engine to it in CI. Measured
once, with the real referee, never typed::

    uv run python packages/rwa-filer/tests/issue_returns.py \\
        --taxonomy-package .taxonomy/boe-banking-v411.zip \\
        --arelle-python .arelle-venv/bin/python

One Arelle process at a time (about 12 s and 1 GB each). Re-measure whenever an
example changes: ``facts_sha256`` pins each one, and the test says which.

References:
- rwa_filer.boe.issues — the register and its examples
- docs/rwa-filer/publisher-issues.md — the register, rendered for sharing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Final

import polars as pl

from rwa_filer.boe.issues import load_issues
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.release import shipped_releases
from rwa_filer.taxonomy.pack import load_packaged
from rwa_filer.validate.identity import facts_sha256

LEI: Final = "5493001KJTIIGC8Y1R12"
REFERENCE_DATE: Final = date(2027, 3, 31)
ORACLE_FILE: Final = "publisher_issues_oracle.json"

#: The canonical return's columns, in the order an example's facts list them.
COLUMNS: Final = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
_SCHEMA: Final = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
    "decimals": pl.Int64,
}


def build_returns(version: str) -> dict[str, tuple[str, CanonicalReturn]]:
    """Each issue's example return, by issue id, with its module."""
    out: dict[str, tuple[str, CanonicalReturn]] = {}
    for issue in load_issues(version).issues:
        if issue.example is None:
            continue
        module = issue.rules[0].module.upper()
        header = ReturnHeader(entity_identifier=LEI, reference_date=REFERENCE_DATE, module=module)
        frame = pl.DataFrame(
            [list(fact) for fact in issue.example.facts],
            schema=_SCHEMA,
            orient="row",
        )
        out[issue.id] = (module, CanonicalReturn.from_frame(header, frame))
    return out


def pack_key(module: str, version: str) -> str:
    """The packaged taxonomy pack of ``module`` in ``version``."""
    return f"{module}-{version}".lower()


def oracle_path(version: str) -> Path:
    """Where Arelle's counts on release ``version``'s examples are kept."""
    return Path(__file__).parent / "releases" / version / "oracles" / ORACLE_FILE


# =============================================================================
# Re-measuring the oracle — needs Arelle and the Bank's taxonomy package
# =============================================================================


def _measure(version: str, taxonomy_package: Path, arelle_python: Path | None) -> dict[str, Any]:
    from rwa_filer.referee.runner import run_referee
    from rwa_filer.xbrl.writer import write_instance

    register = load_issues(version)
    measured: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for issue_id, (module, ret) in build_returns(version).items():
            example = register.issue(issue_id).example  # type: ignore[union-attr]
            assert example is not None
            instance = write_instance(ret, load_packaged(pack_key(module, version)))
            path = Path(scratch) / f"{issue_id}.xbrl"
            content = instance.content
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            result = run_referee(
                path,
                taxonomy_package,
                python=arelle_python,
                rules=example.rules,
                filing_rules=False,
            )
            if not result.complete or result.errors:
                raise SystemExit(f"{issue_id}: Arelle did not finish cleanly: {result.errors}")
            measured[issue_id] = {
                "module": module,
                "facts": instance.facts,
                "facts_sha256": facts_sha256(ret),
                "rules": {
                    rule_id: [verdict.satisfied, verdict.unsatisfied]
                    for rule_id, verdict in sorted(result.rules.items())
                },
            }
            sys.stdout.write(f"{issue_id}: {len(result.rules)} rule(s) measured\n")
    return measured


def _arelle_version(arelle_python: Path | None) -> str:
    from rwa_filer.referee.runner import find_arelle_python

    interpreter = find_arelle_python(arelle_python)
    probe = "from importlib.metadata import version; print(version('arelle-release'))"
    found = subprocess.run(  # noqa: S603 - the interpreter the referee itself runs
        [str(interpreter), "-I", "-c", probe], capture_output=True, text=True, check=True
    )
    return f"arelle-release {found.stdout.strip()}"


def main(argv: list[str] | None = None) -> int:
    """Re-measure every shipped release's oracle with Arelle and write it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--taxonomy-package", type=Path, required=True)
    parser.add_argument("--arelle-python", type=Path)
    parser.add_argument("--release", choices=shipped_releases(), default=shipped_releases()[0])
    args = parser.parse_args(argv)
    oracle = {
        "_comment": (
            "Arelle's verdict, as [satisfied, unsatisfied] evaluation counts, on the minimal "
            "correct return each publisher issue of this release carries (its example in "
            "rwa_filer/boe/data/issues/<release>.json), for the rules the example is measured "
            "on. Regenerate with tests/issue_returns.py, never by hand."
        ),
        "processor": _arelle_version(args.arelle_python),
        "taxonomy": f"Bank of England Banking Taxonomy v{args.release}",
        "returns": _measure(args.release, args.taxonomy_package, args.arelle_python),
    }
    path = oracle_path(args.release)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(oracle, indent=1, sort_keys=True) + "\n")
    sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
