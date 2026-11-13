"""
``ResultExporter.export_filing_package`` — a completed run as the file the PRA accepts.

Pipeline position:
    CalculationResponse -> ResultExporter.export_filing_package
        -> COREPGenerator -> reporting.filing.build_filing_package -> .xbrl + manifest

The run here is a minimal one cached to parquet, with no pipeline involved: what
is pinned is the entry point's own behaviour — which runs it accepts, that it
generates the estate and hands it to the filing adapter, that nothing it finds
raises, and that the written file reads back as the estate. The adapter's own
decisions are pinned in ``tests/unit/reporting/filing/test_package.py``.

References:
- src/rwa_calc/api/export.py::ResultExporter.export_filing_package
- Bank of England Banking Taxonomy v4.1.1 (PRA001)
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.api.export import ResultExporter
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.results_cache import ResultsCache
from rwa_filer.taxonomy.pack import PackNotFoundError
from rwa_filer.xbrl.reader import read_instance

if TYPE_CHECKING:
    from pathlib import Path

LEI = "5493001KJTIIGC8Y1R12"
REFERENCE_DATE = date(2027, 3, 31)


def _response(tmp_path: Path, framework: str) -> CalculationResponse:
    """A minimal completed run, cached to parquet — no pipeline involved."""
    cache = ResultsCache(tmp_path / "cache")
    results = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002"],
            "approach_applied": ["standardised", "standardised"],
            "exposure_class": ["corporate", "retail_other"],
            "ead_final": [1_000_000.0, 500_000.0],
            "risk_weight": [1.0, 0.75],
            "rwa_final": [1_000_000.0, 375_000.0],
        }
    )
    cached = cache.sink_results(results=with_reporting_ledger(results))
    return CalculationResponse(
        success=True,
        framework=framework,
        reporting_date=REFERENCE_DATE,
        summary=SummaryStatistics(
            total_ead=Decimal("1500000"),
            total_rwa=Decimal("1375000"),
            exposure_count=2,
            average_risk_weight=Decimal("0.9167"),
        ),
        results_path=cached.results_path,
    )


@pytest.fixture
def basel_run(tmp_path: Path) -> CalculationResponse:
    return _response(tmp_path, "BASEL_3_1")


def test_a_run_is_re_addressed_validated_and_reported_without_raising(
    basel_run: CalculationResponse, tmp_path: Path
) -> None:
    """Whatever stands in the way is data on the outcome — the caller decides."""
    # Act
    outcome = ResultExporter().export_filing_package(
        basel_run, tmp_path / "filing", entity_identifier=LEI, reference_date=REFERENCE_DATE
    )

    # Assert — the estate was generated and placed; the verdict is stated.
    assert outcome.mapping.placed_cells > 0
    assert outcome.mapping.canonical.header.module == "PRA001"
    assert outcome.written == (outcome.blocked_by is None)
    assert outcome.blocked_by in (None, "unplaced_figures", "structure", "rules")


def test_the_written_file_is_the_estate_that_was_placed(
    basel_run: CalculationResponse, tmp_path: Path
) -> None:
    # Act — written whatever the completeness and rule verdicts, to read it back.
    outcome = ResultExporter().export_filing_package(
        basel_run,
        tmp_path / "filing",
        entity_identifier=LEI,
        reference_date=REFERENCE_DATE,
        monetary_decimals=2,
        allow_incomplete=True,
        allow_rule_breaks=True,
    )
    if outcome.blocked_by == "structure":
        pytest.skip("the minimal estate has a structure finding; nothing can be written")
    assert outcome.package is not None and outcome.package.instance_path is not None
    assert outcome.package.manifest_path is not None
    back = read_instance(outcome.package.instance_path)
    manifest = json.loads(outcome.package.manifest_path.read_text())

    # Assert
    coordinates = ["table", "sheet", "open_key", "row", "column"]
    placed = outcome.mapping.canonical.facts.select(coordinates).unique()
    assert back.findings == ()
    assert placed.join(back.ret.facts, on=coordinates, how="anti", nulls_equal=True).is_empty()
    assert manifest["instance"]["monetary_decimals"] == 2
    assert manifest["header"]["Entity identifier"] == LEI


def test_a_crr_run_has_no_filing_package(tmp_path: Path) -> None:
    """PRA001 is the Basel 3.1 return. A usage error, so it raises."""
    # Arrange
    crr_run = _response(tmp_path, "CRR")

    # Act / Assert
    with pytest.raises(ValueError, match="Basel 3.1 run"):
        ResultExporter().export_filing_package(
            crr_run, tmp_path / "filing", entity_identifier=LEI, reference_date=REFERENCE_DATE
        )


def test_a_reference_date_before_the_taxonomy_applies_has_no_pack(
    basel_run: CalculationResponse, tmp_path: Path
) -> None:
    with pytest.raises(PackNotFoundError):
        ResultExporter().export_filing_package(
            basel_run, tmp_path / "filing", entity_identifier=LEI, reference_date=date(2026, 12, 31)
        )
