"""Integration contract: ``source_exposure_reference`` is an always-present,
always-non-null base reference on the real per-exposure output.

The engine mutates ``exposure_reference`` at several sites — guarantee splits
(``__G_``/``__REM``), real-estate splits (``_rre``/``_res`` ...), facility
undrawn (``<fac>_UNDRAWN[_<sub>|_RESIDUAL]``) and synthetic CCR/SFT rows
(``ccr__``/``ft__``/``dfc__``). Legacy/parallel-run data keys on the ORIGINAL
pre-concatenation reference, so reconciliation needs a stable base column to
join/collapse on. ``source_exposure_reference`` carries that base on every
result row.

This is the survival + population guard the pure-unit collapse tests cannot
give: it runs the full pipeline once and asserts the column reaches the sealed
``results`` frame non-null on 100% of rows, that facility-undrawn rows strip
their ``_UNDRAWN`` suffix back to the facility reference, and that guarantee
sub-rows strip their suffix back to the parent exposure reference.

References:
- src/rwa_calc/contracts/edges.py — _hierarchy_resolved_columns / _calc_output_common_columns
- src/rwa_calc/engine/stages/hierarchy/unify.py, facility_undrawn.py
- src/rwa_calc/data/schemas.py — RECON_PARENT_KEY_COLUMNS
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from workbooks.shared.fixture_loader import load_fixtures

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.acceptance_helpers import build_raw_bundle


@pytest.fixture(scope="module")
def crr_results() -> pl.DataFrame:
    """The real per-exposure output of a full CRR pipeline run over all fixtures.

    Module-scoped: the pipeline runs once and every assertion reads the same
    materialised frame.
    """
    bundle = build_raw_bundle(load_fixtures())
    config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


def test_source_exposure_reference_present_and_non_null(crr_results: pl.DataFrame) -> None:
    assert "source_exposure_reference" in crr_results.columns
    assert crr_results["source_exposure_reference"].null_count() == 0


def test_exposure_reference_always_extends_its_base(crr_results: pl.DataFrame) -> None:
    # Global invariant: every mutation is a suffix-append onto the base (or the
    # namespaced-equal case for synthetic rows), so exposure_reference must start
    # with source_exposure_reference on 100% of rows.
    starts_with = crr_results.select(
        pl.col("exposure_reference").str.starts_with(pl.col("source_exposure_reference"))
    ).to_series()
    assert starts_with.all()


def test_plain_loan_source_equals_own_reference(crr_results: pl.DataFrame) -> None:
    # A loan that has not been split (no guarantee/RE suffix) is base-grain, so
    # source == its own reference. (Guarantee-remainder rows keep exposure_type
    # "loan" but carry a __REM suffix, so exclude any split reference.)
    loans = crr_results.filter(
        (pl.col("exposure_type") == "loan")
        & ~pl.col("exposure_reference").str.contains("__G_")
        & ~pl.col("exposure_reference").str.contains("__REM")
    )
    assert loans.height > 0
    assert (loans["source_exposure_reference"] == loans["exposure_reference"]).all()


def test_facility_undrawn_source_strips_undrawn_suffix(crr_results: pl.DataFrame) -> None:
    undrawn = crr_results.filter(pl.col("exposure_type") == "facility_undrawn")
    assert undrawn.height > 0, "fixtures expected to produce facility_undrawn rows"
    # Base is the facility reference (== source_facility_reference), not the
    # suffixed synthetic reference.
    assert (undrawn["source_exposure_reference"] == undrawn["source_facility_reference"]).all()
    assert not undrawn["source_exposure_reference"].str.contains("_UNDRAWN").any()


def test_guarantee_split_source_strips_suffix(crr_results: pl.DataFrame) -> None:
    splits = crr_results.filter(
        pl.col("exposure_reference").str.contains("__G_")
        | pl.col("exposure_reference").str.contains("__REM")
    )
    if splits.height == 0:
        pytest.skip("no guarantee-split sub-rows in this fixture run")
    # The base strips the guarantee suffix entirely — and, for an undrawn
    # commitment that was then guaranteed (<fac>_UNDRAWN__G_...), strips the
    # _UNDRAWN suffix too, recovering a deeper base than parent_exposure_reference.
    assert not splits["source_exposure_reference"].str.contains("__G_").any()
    assert not splits["source_exposure_reference"].str.contains("__REM").any()
    assert not splits["source_exposure_reference"].str.contains("_UNDRAWN").any()
    assert (
        splits.select(
            pl.col("exposure_reference").str.starts_with(pl.col("source_exposure_reference"))
        )
        .to_series()
        .all()
    )
