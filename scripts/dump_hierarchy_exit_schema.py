"""
Dump the observed hierarchy-exit schema under minimal and rich inputs.

Phase 3 working tool: the hierarchy_exit EdgeContract is seeded from the
UNION of observed schemas — a minimal bundle (no optional tables, the
stress shape) and a rich bundle (every optional table populated) — so the
contract pins what the stage must emit even when optional inputs are
absent (typed defaults), and what only appears when they are present.

Usage:
    uv run python scripts/dump_hierarchy_exit_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import polars as pl  # noqa: E402
from tests.acceptance.stress.conftest import (  # noqa: E402
    build_stress_dataset,
    create_raw_bundle,
)
from tests.fixtures.raw_bundle import make_raw_bundle  # noqa: E402

from rwa_calc.engine.hierarchy import HierarchyResolver  # noqa: E402


def _rich_bundle():
    """One-row-per-table bundle with every optional table populated."""
    return make_raw_bundle(
        counterparties=pl.LazyFrame(
            {
                "counterparty_reference": ["CP1", "GUAR1"],
                "entity_type": ["corporate", "institution"],
            }
        ),
        facilities=pl.LazyFrame(
            {
                "facility_reference": ["F1"],
                "counterparty_reference": ["CP1"],
                "limit": [1000.0],
            }
        ),
        loans=pl.LazyFrame(
            {
                "loan_reference": ["L1"],
                "counterparty_reference": ["CP1"],
                "drawn_amount": [500.0],
            }
        ),
        contingents=pl.LazyFrame(
            {
                "contingent_reference": ["CT1"],
                "counterparty_reference": ["CP1"],
                "nominal_amount": [100.0],
            }
        ),
        facility_mappings=pl.LazyFrame(
            {
                "parent_facility_reference": ["F1", "F1"],
                "child_reference": ["L1", "CT1"],
                "child_type": ["loan", "contingent"],
            }
        ),
        collateral=pl.LazyFrame(
            {
                "collateral_reference": ["COL1"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["L1"],
                "collateral_type": ["residential_property"],
                "market_value": [800.0],
            }
        ),
        collateral_links=pl.LazyFrame(
            {
                "collateral_reference": ["COL1"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["L1"],
            }
        ),
        guarantees=pl.LazyFrame(
            {
                "guarantee_reference": ["G1"],
                "guarantor_reference": ["GUAR1"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["L1"],
                "amount_covered": [200.0],
            }
        ),
        provisions=pl.LazyFrame(
            {
                "provision_reference": ["P1"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["L1"],
                "amount": [10.0],
            }
        ),
        ratings=pl.LazyFrame(
            {
                "rating_reference": ["R1"],
                "counterparty_reference": ["CP1"],
                "rating_type": ["external"],
                "cqs": [2],
            }
        ),
        org_mappings=pl.LazyFrame(
            {
                "child_counterparty_reference": ["CP1"],
                "parent_counterparty_reference": ["GUAR1"],
            }
        ),
        lending_mappings=pl.LazyFrame(
            {
                "parent_counterparty_reference": ["GUAR1"],
                "child_counterparty_reference": ["CP1"],
            }
        ),
        equity_exposures=pl.LazyFrame(
            {
                "equity_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "market_value": [50.0],
            }
        ),
        specialised_lending=pl.LazyFrame(
            {
                "exposure_reference": ["L1"],
                "sl_type": ["project_finance"],
            }
        ),
        model_permissions=pl.LazyFrame(
            {
                "model_id": ["M1"],
                "exposure_class": ["corporate"],
                "approach": ["foundation_irb"],
            }
        ),
    )


def main() -> None:
    from datetime import date

    from rwa_calc.contracts.config import CalculationConfig

    resolver = HierarchyResolver()
    configs = {
        "crr": CalculationConfig.crr(reporting_date=date(2026, 12, 31)),
        "b31": CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 31)),
    }

    minimal = create_raw_bundle(build_stress_dataset(50, seed=42), irb=True)
    rich = _rich_bundle()

    schemas: dict[str, dict[str, pl.DataType]] = {}
    for cfg_name, config in configs.items():
        for name, bundle in (("minimal", minimal), ("rich", rich)):
            resolved = resolver.resolve(bundle, config)
            key = f"{name}/{cfg_name}"
            schemas[key] = dict(resolved.exposures.collect_schema())
            print(f"[{key}] exposures: {len(schemas[key])} columns")
    schemas = {
        "minimal": schemas["minimal/crr"] | schemas["minimal/b31"],
        "rich": schemas["rich/crr"] | schemas["rich/b31"],
    }

    all_cols = sorted(set(schemas["minimal"]) | set(schemas["rich"]))
    print(f"\nUNION: {len(all_cols)} columns")
    print(f"{'column':45} {'minimal':18} {'rich':18}")
    for col in all_cols:
        m = str(schemas["minimal"].get(col, "—"))
        r = str(schemas["rich"].get(col, "—"))
        flag = "" if m == r else "   <-- VARIES"
        print(f"{col:45} {m:18} {r:18}{flag}")


if __name__ == "__main__":
    main()
