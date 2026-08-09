"""Root test fixtures shared across the whole ``tests/`` tree.

Currently provides:
- ``write_minimal_crr_dataset`` — a factory fixture that writes the minimum
  mandatory CRR parquet files (counterparties, facilities, loans,
  facility_mappings, lending_mappings) into a directory and returns a
  ``DataSourceConfig`` pointing at them. Used by CCR loader / fixture-builder
  tests that need a valid base CRR dataset before wiring optional CCR files.
- The Polars thread-pool cap for the whole test session (see below).
"""

from __future__ import annotations

import os

# Polars sizes its thread pool from the core count the first time it is
# imported, and pytest-xdist sizes its worker fleet the same way. Left alone on
# a 16-core box that is 16 workers each holding a 16-thread pool — 256 threads
# contending for 16 cores, each pool carrying its own buffers. Practically every
# test here pushes a handful of rows through the pipeline, so that parallelism
# buys nothing and costs both wall time and resident memory: capping it to one
# thread took the dev-loop suite from 8m43s / 7.3 GB peak to 3m38s / 4.35 GB on
# the reference box, with identical results.
#
# This must run before the first ``import polars`` anywhere in the process,
# which is why it sits above the imports rather than in a fixture — conftest is
# imported before any test module, in the controller and in every xdist worker.
#
# ``setdefault`` leaves an explicit outer value in charge: the CI benchmark job
# exports the real core count so it still measures production-like throughput.
# Never set this to 0 — Polars accepts it at import and then panics at compute
# time with "Worker threads cannot be set to 0".
os.environ.setdefault("POLARS_MAX_THREADS", "1")

from typing import TYPE_CHECKING  # noqa: E402

import polars as pl  # noqa: E402
import pytest  # noqa: E402

from rwa_calc.engine.loader import DataSourceConfig  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def write_minimal_crr_dataset() -> Callable[[Path], DataSourceConfig]:
    """Return a factory that writes the minimum mandatory CRR files.

    The returned callable writes counterparties, facilities, loans,
    facility_mappings and lending_mappings parquets into ``base_dir`` so that
    ``ParquetLoader`` does not fail on missing required files, then returns a
    ``DataSourceConfig`` pointing at the written files.
    """

    def _write(base_dir: Path) -> DataSourceConfig:
        # Minimal counterparties
        cp_df = pl.DataFrame(
            {
                "counterparty_reference": ["CP_001"],
                "counterparty_name": ["Test Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [100_000_000.0],
                "total_assets": [500_000_000.0],
                "default_status": [False],
            }
        )
        # Minimal facilities
        fac_df = pl.DataFrame(
            {
                "facility_reference": ["FAC_001"],
                "counterparty_reference": ["CP_001"],
            }
        )
        # Minimal loans
        loan_df = pl.DataFrame(
            {
                "loan_reference": ["LN_001"],
                "counterparty_reference": ["CP_001"],
                "drawn_amount": [0.0],
            }
        )
        # Minimal facility_mappings
        fm_df = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_001"],
                "child_reference": ["LN_001"],
            }
        )
        # Minimal lending_mappings (empty)
        lm_df = pl.DataFrame({"member_counterparty_reference": pl.Series([], dtype=pl.String)})

        base_dir.mkdir(parents=True, exist_ok=True)
        cp_path = base_dir / "counterparties.parquet"
        fac_path = base_dir / "facilities.parquet"
        loan_path = base_dir / "loans.parquet"
        fm_path = base_dir / "facility_mappings.parquet"
        lm_path = base_dir / "lending_mappings.parquet"

        cp_df.write_parquet(cp_path)
        fac_df.write_parquet(fac_path)
        loan_df.write_parquet(loan_path)
        fm_df.write_parquet(fm_path)
        lm_df.write_parquet(lm_path)

        return DataSourceConfig(
            counterparties_file=cp_path,
            facilities_file=fac_path,
            loans_file=loan_path,
            facility_mappings_file=fm_path,
            lending_mappings_file=lm_path,
        )

    return _write
