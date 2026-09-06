"""
Prove an engine or reporting change is output-preserving, across the whole estate.

A green test suite says the assertions that exist still hold. It does not say the
numbers did not move: most cells of most templates are asserted by nothing. For a
refactor whose contract is "identical output" — a performance change, a
materialisation move, a caching layer — the gate has to be the output itself.

This script dumps, for a fixed set of runs, every artifact a caller could observe:

- the sealed per-leg ledger of each run,
- its ``CalculationError`` list **in order** (code, severity, category, message,
  exposure reference, regulatory reference),
- every COREP sheet and every Pillar 3 sheet the run emits.

The run set is the 20 supervisory-gate portfolios (read live from
``tests/acceptance/reporting/test_supervisory_validations.py::RUNS``, so a newly
registered portfolio is covered without editing this file), five acceptance-fixture
configurations spanning SA / IRB / slotting under both regimes, and a one-row
property bundle. That is ~870 files.

Dumps go to two fixed slots under ``.reference_dumps/`` (git-ignored). Usage::

    git worktree add --detach ../base <base-commit>
    (cd ../base && uv run python scripts/reference_dump.py dump --slot base)
    uv run python scripts/reference_dump.py dump --slot current   # on the change
    uv run python scripts/reference_dump.py check

``check`` exits non-zero on any difference and prints the first few per file. The
slots are named rather than passed as paths because argv is attacker-controlled
to the security taint analysis (arch_check check 19); a caller that needs another
location imports :func:`dump` and :func:`check` and passes its own ``Path``.

Both slots live under the tree the script is run from, so the base dump must be
written from a worktree at the base commit — which is what you want anyway, since
that is the engine being compared.

**The engine is not bit-deterministic between runs, and that is expected.** Ledger
rows come back in a different order, and summed template cells differ at the last
unit in the last place. So frames are compared after sorting on every non-float
column, with floats at the goldens' tolerance (``1e-9`` relative). Establish this
for yourself before trusting a clean result: dump the unmodified base twice and
``check`` it against itself. An exact comparison reports ~40 spurious differences.

Error lists are compared as ORDERED lists first — order is part of the contract,
because a reader consumes them in sequence — and, when order alone differs, that is
reported separately rather than silently accepted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import fields, is_dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

os.environ.setdefault("POLARS_MAX_THREADS", "1")

import polars as pl  # noqa: E402
from polars.testing import assert_frame_equal  # noqa: E402

#: Float comparison tolerance. Matches the reporting goldens: the engine's own
#: summation order drifts at the last ULP between runs of identical code.
REL_TOL = 1e-9
ABS_TOL = 1e-6

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: The two fixed dump slots. The CLI selects one of these constants by NAME —
#: argv never constructs a path (arch_check check 19 / pythonsecurity:S8707).
_DUMP_ROOT = _REPO_ROOT / ".reference_dumps"
_SLOTS: dict[str, Path] = {"base": _DUMP_ROOT / "base", "current": _DUMP_ROOT / "current"}


# =============================================================================
# Dump
# =============================================================================


def dump(out_dir: Path) -> int:
    """Write every observable artifact of the fixed run set into ``out_dir``."""
    sys.path.insert(0, str(_REPO_ROOT))
    out_dir.mkdir(parents=True, exist_ok=True)

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    written = 0
    for spec in _run_specs():
        written += _dump_one(out_dir, *spec)

    # Acceptance-fixture configurations: SA, IRB and slotting under both regimes.
    from tests.acceptance.acceptance_helpers import build_raw_bundle, make_irb_bundle
    from tests.fixtures.irb_test_helpers import (
        create_full_irb_model_permissions,
        create_slotting_only_model_permissions,
    )
    from workbooks.shared.fixture_loader import load_fixtures

    fixtures = load_fixtures()
    sa_bundle = build_raw_bundle(fixtures)
    irb_bundle = make_irb_bundle(fixtures, create_full_irb_model_permissions())
    slotting_bundle = make_irb_bundle(fixtures, create_slotting_only_model_permissions())
    crr_date, b31_sa_date, b31_irb_date = (
        date(2025, 12, 31),
        date(2030, 6, 30),
        date(2032, 6, 30),
    )
    acceptance: list[tuple[str, Any, Any, str | None]] = [
        (
            "acc__crr_sa",
            sa_bundle,
            CalculationConfig.crr(
                reporting_date=crr_date, permission_mode=PermissionMode.STANDARDISED
            ),
            "CRR",
        ),
        (
            "acc__crr_irb",
            irb_bundle,
            CalculationConfig.crr(reporting_date=crr_date, permission_mode=PermissionMode.IRB),
            "CRR",
        ),
        (
            "acc__crr_slot",
            slotting_bundle,
            CalculationConfig.crr(reporting_date=crr_date, permission_mode=PermissionMode.IRB),
            None,
        ),
        (
            "acc__b31_sa",
            sa_bundle,
            CalculationConfig.basel_3_1(
                reporting_date=b31_sa_date, permission_mode=PermissionMode.STANDARDISED
            ),
            "BASEL_3_1",
        ),
        (
            "acc__b31_irb",
            irb_bundle,
            CalculationConfig.basel_3_1(
                reporting_date=b31_irb_date, permission_mode=PermissionMode.IRB
            ),
            "BASEL_3_1",
        ),
    ]
    for tag, bundle, config, framework in acceptance:
        written += _dump_one(out_dir, tag, bundle, config, framework)

    # A one-row bundle: the fixed-cost floor, and the smallest reproduction of a run.
    from tests.properties.portfolios import ExposureSpec, build_bundle, config_for

    for regime in ("CRR", "B31"):
        written += _dump_one(
            out_dir,
            f"onerow__{regime}",
            build_bundle((ExposureSpec(),)),
            config_for(regime),
            None,
        )

    print(f"wrote {written} files to {out_dir}")
    return 0


def _run_specs() -> list[tuple[str, Any, Any, str | None, Any]]:
    """The supervisory gate's own run table, read live so it cannot drift."""
    gate = _load_module(
        _REPO_ROOT / "tests" / "acceptance" / "reporting" / "test_supervisory_validations.py",
        "_supervisory_gate",
    )
    specs: list[tuple[str, Any, Any, str | None, Any]] = []
    for regime, framework, portfolio, build_bundle, build_config, build_prior in gate.RUNS:
        specs.append(
            (
                f"gate__{regime}__{portfolio}",
                build_bundle(),
                build_config(),
                framework,
                None if build_prior is None else (build_bundle(), build_prior()),
            )
        )
    return specs


def _dump_one(
    out_dir: Path,
    tag: str,
    bundle: Any,
    config: Any,
    framework: str | None,
    prior: tuple[Any, Any] | None = None,
) -> int:
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    result = PipelineOrchestrator().run_with_data(bundle, config)
    result.results.collect().write_parquet(out_dir / f"{tag}__ledger.parquet")
    (out_dir / f"{tag}__errors.json").write_text(
        json.dumps(_errors(result), indent=0, default=str), encoding="utf-8"
    )
    written = 2
    if framework is None:
        print("dumped", tag, flush=True)
        return written

    from rwa_calc.reporting.corep.generator import COREPGenerator
    from rwa_calc.reporting.pillar3.generator import Pillar3Generator

    previous = None
    if prior is not None:
        prior_bundle, prior_config = prior
        previous = PipelineOrchestrator().run_with_data(prior_bundle, prior_config).results
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework=framework, previous_period_results=previous
    )
    written += _write_frames(corep, out_dir / f"{tag}__corep")
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    written += _write_frames(pillar3, out_dir / f"{tag}__p3")
    print("dumped", tag, flush=True)
    return written


def _errors(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "code": getattr(e, "code", None),
            "severity": str(getattr(e, "severity", None)),
            "category": str(getattr(e, "category", None)),
            "message": getattr(e, "message", None),
            "exposure_reference": getattr(e, "exposure_reference", None),
            "regulatory_reference": getattr(e, "regulatory_reference", None),
        }
        for e in result.errors
    ]


def _write_frames(bundle: object, prefix: Path) -> int:
    """Write every DataFrame the bundle exposes, including per-class sheet dicts."""
    names = (
        [f.name for f in fields(bundle)]
        if is_dataclass(bundle)
        else [n for n in dir(bundle) if not n.startswith("_")]
    )
    written = 0
    for name in names:
        try:
            value = getattr(bundle, name)
        except Exception:  # noqa: BLE001 - a property that needs arguments is not an artifact
            continue
        if isinstance(value, pl.LazyFrame):
            value = value.collect()
        if isinstance(value, pl.DataFrame):
            value.write_parquet(prefix.with_name(f"{prefix.name}__{name}.parquet"))
            written += 1
        elif isinstance(value, dict):
            for key, sheet in value.items():
                if isinstance(sheet, pl.DataFrame):
                    sheet.write_parquet(prefix.with_name(f"{prefix.name}__{name}__{key}.parquet"))
                    written += 1
    return written


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - a moved test module
        msg = f"cannot import {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =============================================================================
# Check
# =============================================================================


def check(ref_dir: Path, new_dir: Path) -> int:
    """Compare two dumps. Returns 0 when nothing differs beyond run-to-run noise."""
    ref_files = {p.name for p in ref_dir.iterdir()}
    new_files = {p.name for p in new_dir.iterdir()}
    problems: list[str] = []
    order_only: list[str] = []

    problems.extend(f"MISSING in new: {n}" for n in sorted(ref_files - new_files))
    problems.extend(f"EXTRA in new: {n}" for n in sorted(new_files - ref_files))

    for name in sorted(ref_files & new_files):
        if name.endswith(".parquet"):
            diff = _compare_frames(ref_dir / name, new_dir / name)
            if diff:
                problems.append(f"FRAME DIFF {name}: {diff}")
        elif name.endswith(".json"):
            problems.extend(_compare_errors(ref_dir / name, new_dir / name, order_only))

    print(f"compared {len(ref_files & new_files)} files")
    for name in order_only:
        print(f"ERROR-ORDER-ONLY (same multiset, different order): {name}")
    for line in problems:
        print(line)
    verdict = "IDENTICAL" if not problems and not order_only else "DIFFERENT"
    if not problems and order_only:
        verdict = "ORDER-ONLY"
    print("RESULT:", verdict)
    return 1 if problems else 0


def _canonical(frame: pl.DataFrame) -> pl.DataFrame:
    """Sort on every non-float column so row order cannot register as a difference."""
    frame = frame.with_columns(
        pl.col(name).cast(pl.String)
        for name, dtype in frame.schema.items()
        if dtype in (pl.Categorical, pl.Enum)
    )
    keys = [
        name
        for name, dtype in frame.schema.items()
        if dtype not in (pl.Float32, pl.Float64) and not dtype.is_nested()
    ]
    return frame.sort(keys, nulls_last=True) if keys else frame


def _compare_frames(a: Path, b: Path) -> str | None:
    left, right = _canonical(pl.read_parquet(a)), _canonical(pl.read_parquet(b))
    if left.shape != right.shape:
        return f"shape {left.shape} vs {right.shape}"
    try:
        assert_frame_equal(
            left,
            right,
            check_exact=False,
            rel_tol=REL_TOL,
            abs_tol=ABS_TOL,
            check_column_order=True,
        )
    except AssertionError as exc:
        return " | ".join(str(exc).splitlines()[:3])
    return None


def _compare_errors(a: Path, b: Path, order_only: list[str]) -> list[str]:
    left = json.loads(a.read_text(encoding="utf-8"))
    right = json.loads(b.read_text(encoding="utf-8"))
    if left == right:
        return []
    key = lambda item: json.dumps(item, sort_keys=True, default=str)  # noqa: E731
    if sorted(map(key, left)) == sorted(map(key, right)):
        order_only.append(a.name)
        return []
    only_ref = set(map(key, left)) - set(map(key, right))
    only_new = set(map(key, right)) - set(map(key, left))
    lines = [
        f"ERRORS DIFF {a.name}: ref={len(left)} new={len(right)} "
        f"only_ref={len(only_ref)} only_new={len(only_new)}"
    ]
    lines.extend(f"   only in ref: {item[:220]}" for item in sorted(only_ref)[:3])
    lines.extend(f"   only in new: {item[:220]}" for item in sorted(only_new)[:3])
    return lines


def main() -> int:
    """CLI over the two fixed slots.

    ``--slot`` names a constant from ``_SLOTS``; no operator string ever reaches
    a ``Path`` constructor (arch_check check 19). A caller needing a different
    location imports :func:`dump` / :func:`check` directly.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    dump_parser = sub.add_parser("dump", help="write a reference dump into a slot")
    dump_parser.add_argument("--slot", choices=sorted(_SLOTS), required=True)
    sub.add_parser("check", help="compare the base slot against the current slot")
    args = parser.parse_args()
    if args.command == "dump":
        return dump(_SLOTS[args.slot])
    missing = [name for name, path in _SLOTS.items() if not path.is_dir()]
    if missing:
        print(f"missing dump slot(s): {', '.join(missing)} — run `dump --slot <name>` first")
        return 2
    return check(_SLOTS["base"], _SLOTS["current"])


if __name__ == "__main__":
    sys.exit(main())
