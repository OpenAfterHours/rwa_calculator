"""
Ratchet the DECLARED input domains — the population of columns that state one.

Pipeline position:
    (not a pipeline stage) — a gate. Run by
    ``tests/contracts/test_input_domain_ratchet.py`` on every dev-loop pytest
    run, and available standalone:

        uv run python scripts/check_input_domains.py            # census
        uv run python scripts/check_input_domains.py --check    # the gate
        uv run python scripts/check_input_domains.py --update-baseline

Key responsibilities:
- Census every ``ColumnSpec.domain`` declared in ``rwa_calc.data.schemas``,
  keyed ``<SCHEMA>::<column>``.
- Two-way ratchet that set against ``scripts/input_domain_baseline.json``
  through the shared set-diff in ``scripts/tolerated_findings.py``.
- **Reachability**: prove that every schema carrying a declared domain is
  actually visited by the input gate, so a declaration cannot be dead.

Why a SET, not a count
----------------------
`.claude/LESSONS.md` B8: ratchet the accumulator, never a ratio nor a bare
count. A count ratchet on this population is satisfiable by declaring a
trivial domain on an easy column while a hard one silently loses its own —
75 stays 75 and the gate reports success. The id set cannot do that: dropping
``RATINGS_SCHEMA::pd`` is a named removal whatever else is added in the same
change.

The two directions, and why BOTH are gated
------------------------------------------
This register is the mirror image of the parked-findings registers that
``scripts/tolerated_findings.py`` was extracted for. There, the population is
findings we tolerate, so GROWTH is the failure and shrinkage is free. Here the
population is coverage, so the directions invert:

- **Removals are a HARD FAILURE.** A column that had a declared domain and no
  longer does is coverage going backwards, which is exactly what happens when
  a red gate is cleared by deleting the bound instead of fixing the data. That
  is the move this file exists to catch, so ``--update-baseline`` will not
  silently absorb one: it refuses to drop an id.
- **Additions must be BANKED.** Adding a domain is the outcome we want, and the
  gate still fails until the baseline records it. That is not bureaucracy —
  banking is what makes the *next* removal visible, and it puts the new bound
  in a reviewable diff in a file whose whole purpose is to be reviewed.

Reachability, and why it lives here rather than in arch_check
-------------------------------------------------------------
``arch_check`` check 20 stops a guard FUNCTION from being unreachable from
production. Phase 1 moves the guard one level down, from functions to
declarations, and re-opens the same hole in a new shape: a ``NumericDomain``
on a table the gate never visits is guard-shaped data that reads as coverage
while validating nothing. The check is here rather than in ``arch_check``
because answering it means importing ``rwa_calc`` and reading
``validation.bundle_frames`` — ``arch_check`` is a static AST pass over source
and structurally cannot.

References:
- ``docs/plans/test-space-correctness-proposal.md`` — Phase 1
- `.claude/LESSONS.md` B8 (ratchet the accumulator, not a ratio)
- ``scripts/tolerated_findings.py`` — the shared set-diff
- ``scripts/check_doc_links.py`` — the ``--check`` / ``--update-baseline`` shape
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tolerated_findings import diff  # noqa: E402

if TYPE_CHECKING:
    from rwa_calc.data.column_spec import ColumnDomain

BASELINE_PATH = REPO_ROOT / "scripts" / "input_domain_baseline.json"

_BASELINE_COMMENT = (
    "Declared input-domain ratchet (scripts/check_input_domains.py --check). "
    "One id per column carrying a ColumnSpec.domain, as <SCHEMA>::<column>. "
    "REMOVALS ARE A HARD FAILURE and --update-baseline refuses to make one: "
    "a domain that disappears is coverage going backwards, which is what "
    "clearing a red gate by deleting the bound looks like. Additions are the "
    "outcome we want and must still be banked here so the next removal is "
    "visible. docs/plans/test-space-correctness-proposal.md Phase 1."
)


def census() -> dict[str, ColumnDomain]:
    """Every declared input domain in ``rwa_calc.data.schemas``, keyed by id.

    Discovers schemas the same way the numeric census does — an UPPER_CASE
    module-level dict whose values are ``ColumnSpec`` — so a schema added
    later is picked up without touching this file.
    """
    from rwa_calc.data import schemas
    from rwa_calc.data.column_spec import ColumnSpec

    declared: dict[str, ColumnDomain] = {}
    for schema_name in dir(schemas):
        if not schema_name.isupper():
            continue
        schema = getattr(schemas, schema_name)
        if not isinstance(schema, dict) or not schema:
            continue
        if not isinstance(next(iter(schema.values())), ColumnSpec):
            continue
        for column, spec in schema.items():
            if spec.domain is not None:
                declared[f"{schema_name}::{column}"] = spec.domain
    return declared


def unreachable_declarations() -> list[str]:
    """Ids whose schema no input-gate table maps to — a declaration nothing reads.

    Resolves the gate's own coverage rather than a restatement of it: the
    tables come from ``validation.bundle_frames`` (built against an empty
    bundle carrying both CCR and SFT composites, so the nested leaves appear)
    and the schemas from ``TABLE_SCHEMAS``.
    """
    from rwa_calc.contracts.validation import bundle_frames
    from rwa_calc.data import schemas
    from rwa_calc.data.schemas import TABLE_SCHEMAS

    visited = set(bundle_frames(_probe_bundle()))
    reachable_schemas = {id(TABLE_SCHEMAS[table]) for table in visited if table in TABLE_SCHEMAS}
    unreachable = [
        declared_id
        for declared_id in census()
        if id(getattr(schemas, declared_id.split("::", 1)[0])) not in reachable_schemas
    ]
    return sorted(unreachable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Declared input-domain census for data/schemas.py, with a two-way ratchet."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="two-way ratchet against the baseline")
    mode.add_argument("--update-baseline", action="store_true", help="bank added declarations")
    args = parser.parse_args(argv)

    declared = census()
    ids = sorted(declared)

    if args.update_baseline:
        return _update_baseline(ids)
    if args.check:
        return _check(ids)

    for declared_id in ids:
        sys.stdout.write(f"{declared_id}  {declared[declared_id].describe()}\n")
    sys.stderr.write(f"\n{len(ids)} declared input domains\n")
    return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _probe_bundle():
    """An empty RawDataBundle carrying both CCR and SFT composites.

    ``bundle_frames`` reaches the nested CCR / SFT leaves only when those
    composites are present, so a bare empty bundle would under-report the
    gate's coverage and wrongly mark every CCR / SFT declaration unreachable.
    """
    import polars as pl

    from rwa_calc.contracts.bundles import (
        CCRCollateralBundle,
        MarginAgreementBundle,
        NettingSetBundle,
        RawCCRBundle,
        RawSFTBundle,
        SftCollateralBundle,
        SftTradeBundle,
        TradeBundle,
        create_empty_raw_data_bundle,
    )
    from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
    from rwa_calc.data.column_spec import dtypes_of
    from rwa_calc.data.schemas import TABLE_SCHEMAS

    def _empty(table: str) -> pl.LazyFrame:
        return pl.DataFrame(schema=dtypes_of(TABLE_SCHEMAS[table])).lazy()

    def _sealed(table: str, edge_key: str) -> pl.LazyFrame:
        # The SFT leaves validate their brand in __post_init__; the CCR leaves
        # do not (CCR frames bypass the loader seal), so only these two go
        # through seal_lenient.
        return seal_lenient(_empty(table), SFT_TABLE_EDGES[edge_key])[0]

    ccr = RawCCRBundle(
        trades=TradeBundle(trades=_empty("ccr.trades")),
        netting_sets=NettingSetBundle(netting_sets=_empty("ccr.netting_sets")),
        margin_agreements=MarginAgreementBundle(margin_agreements=_empty("ccr.margin_agreements")),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_empty("ccr.ccr_collateral")),
    )
    sft = RawSFTBundle(
        trades=SftTradeBundle(sft_trades=_sealed("sft.trades", "sft_trades")),
        collateral=SftCollateralBundle(sft_collateral=_sealed("sft.collateral", "sft_collateral")),
    )
    base = create_empty_raw_data_bundle()
    return type(base)(
        **{
            field: getattr(base, field)
            for field in base.__dataclass_fields__
            if field not in {"ccr", "sft"}
        },
        ccr=ccr,
        sft=sft,
    )


def _load_baseline() -> list[str]:
    if not BASELINE_PATH.exists():
        return []
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return list(payload["declared_domains"])


def _write_baseline(ids: list[str]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {"_comment": _BASELINE_COMMENT, "count": len(ids), "declared_domains": ids},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _update_baseline(ids: list[str]) -> int:
    moved = diff(ids, _load_baseline())
    if moved.removed:
        sys.stderr.write(
            "REFUSED: --update-baseline will not drop a declared domain.\n"
            + "".join(f"  gone: {i}\n" for i in moved.removed)
            + "Restore the declaration, or hand-edit the baseline so the removal "
            "is a reviewable diff in its own right.\n"
        )
        return 1
    _write_baseline(ids)
    sys.stderr.write(f"baseline banked at {len(ids)} declared domains (+{len(moved.added)})\n")
    return 0


def _check(ids: list[str]) -> int:
    failed = False

    dead = unreachable_declarations()
    if dead:
        sys.stderr.write(
            "UNREACHABLE: these columns declare a domain no input-gate table reads, "
            "so the declaration validates nothing.\n"
            + "".join(f"  {i}\n" for i in dead)
            + "Add the table to data/schemas.py TABLE_SCHEMAS and to "
            "contracts/validation.py bundle_frames, or drop the declaration.\n\n"
        )
        failed = True

    moved = diff(ids, _load_baseline())
    if moved.removed:
        sys.stderr.write(
            f"REGRESSION: {len(moved.removed)} declared input domain(s) removed.\n"
            + "".join(f"  gone: {i}\n" for i in moved.removed)
            + "A domain that disappears is coverage going backwards. Fix the data "
            "or the bound — do not delete the declaration to clear a red gate.\n\n"
        )
        failed = True
    if moved.added:
        sys.stderr.write(
            f"UNBANKED: {len(moved.added)} new declared input domain(s). Bank them:\n"
            + "".join(f"  new: {i}\n" for i in moved.added)
            + "  uv run python scripts/check_input_domains.py --update-baseline\n\n"
        )
        failed = True

    if failed:
        return 1
    sys.stderr.write(f"[OK] {len(ids)} declared input domains == baseline, all reachable\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
