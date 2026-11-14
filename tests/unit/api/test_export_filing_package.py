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
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest
from fastapi import HTTPException
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.api import rest
from rwa_calc.api.export import ResultExporter
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.results_cache import ResultsCache
from rwa_filer.taxonomy.pack import PackNotFoundError
from rwa_filer.xbrl.reader import read_instance

if TYPE_CHECKING:
    from collections.abc import Iterator

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


# =============================================================================
# GET /api/filing/status and /api/filing/package
# =============================================================================


@pytest.fixture
def registered(basel_run: CalculationResponse) -> Iterator[str]:
    """The Basel 3.1 run in the REST in-process registry, cleaned up after."""
    run_id = rest.register_run(basel_run)
    yield run_id
    rest._RUNS.pop(run_id, None)
    rest._TEMPLATE_BUNDLES.pop((run_id, None), None)


class TestFilingStatusEndpoint:
    """The route answering whether a run can be filed, and if not, why not."""

    def test_a_run_that_cannot_be_filed_is_a_200_that_says_why(self, registered: str) -> None:
        """Whatever stands in the way is data about the filing, not a fault in the request."""
        # Act
        payload = rest.filing_status(registered, entity_identifier=LEI)

        # Assert
        assert payload["module"] == "PRA001"
        assert payload["placed_cells"] > 0
        assert isinstance(payload["is_submittable"], bool)
        assert payload["blocked_by"] in (None, "unplaced_figures", "structure", "rules")
        assert payload["written"] is (payload["blocked_by"] is None)
        assert payload["unplaced_figures"] == sum(
            item["figures"] for item in payload["unplaced_by_reason"]
        )

    def test_the_verdict_keeps_no_file(self, registered: str, tmp_path: Path) -> None:
        # Act
        rest.filing_status(registered, entity_identifier=LEI)

        # Assert — nothing was written where the caller could find it later.
        assert list(tmp_path.glob("**/*.xbrl")) == []

    def test_with_the_overrides_the_answer_is_what_would_still_stand_in_the_way(
        self, registered: str
    ) -> None:
        """How a caller learns whether a file for review can be written at all."""
        # Act
        strict = rest.filing_status(registered, entity_identifier=LEI)
        overridden = rest.filing_status(
            registered, entity_identifier=LEI, allow_incomplete=True, allow_rule_breaks=True
        )

        # Assert — the minimal run is stopped by rule breaks and nothing else an
        # override cannot lift; overridden, it is validated and written.
        # Was "unplaced_figures" with no validation: every unplaced figure of this run
        # was an OF 02.00 cell the published template lacks (taxonomy OF02.00.01.01).
        # With none left, the return is validated and the Error rules stand in the way.
        assert strict["blocked_by"] == "rules"
        assert strict["unplaced_figures"] == 0
        assert strict["validation"] is not None
        assert overridden["blocked_by"] is None and overridden["written"] is True
        assert overridden["validation"] is not None
        # ... and a return written with an override is never called submittable.
        assert overridden["is_submittable"] is False

    def test_unknown_run_id_is_a_404(self) -> None:
        with pytest.raises(HTTPException) as raised:
            rest.filing_status("no-such-run", entity_identifier=LEI)
        assert raised.value.status_code == 404

    def test_a_crr_run_is_a_422(self, tmp_path: Path) -> None:
        """PRA001 is the Basel 3.1 return: there is no such return to file."""
        # Arrange
        run_id = rest.register_run(_response(tmp_path, "CRR"))

        # Act / Assert
        try:
            with pytest.raises(HTTPException) as raised:
                rest.filing_status(run_id, entity_identifier=LEI)
            assert raised.value.status_code == 422
        finally:
            rest._RUNS.pop(run_id, None)


class TestFilingPackageEndpoint:
    """The route that downloads the instance and its manifest."""

    def test_the_package_holds_the_instance_and_its_manifest(self, registered: str) -> None:
        # Act — everything that may be allowed is allowed, so there is a file.
        download = rest.filing_package(
            registered, entity_identifier=LEI, allow_incomplete=True, allow_rule_breaks=True
        )

        # Assert — names come from run data, never from the caller's identifier.
        with zipfile.ZipFile(download.path) as archive:
            names = sorted(archive.namelist())
            instance = archive.read(next(name for name in names if name.endswith(".xbrl")))
        assert "rwa_filing_BASEL_3_1_2027-03-31.xbrl" in names
        assert "rwa_filing_BASEL_3_1_2027-03-31.manifest.json" in names
        assert LEI not in "".join(names) and LEI.encode() in instance
        assert read_instance(instance).findings == ()

    def test_a_blocked_run_is_a_409_carrying_the_verdict(self, registered: str) -> None:
        """The caller asked for a file and there is none to give."""
        # Arrange — is the run blocked at all without the allowances?
        status = rest.filing_status(registered, entity_identifier=LEI)
        if status["blocked_by"] is None:
            pytest.skip("the minimal run is fileable as it stands")

        # Act
        with pytest.raises(HTTPException) as raised:
            rest.filing_package(registered, entity_identifier=LEI)

        # Assert
        assert raised.value.status_code == 409
        assert raised.value.detail["blocked_by"] == status["blocked_by"]  # type: ignore[index]

    def test_an_identifier_that_is_not_an_lei_is_refused_not_used_as_a_path(
        self, registered: str
    ) -> None:
        """The identifier goes into the instance, never into a file name."""
        # Act
        with pytest.raises(HTTPException) as raised:
            rest.filing_package(
                registered,
                entity_identifier="../../etc/passwd",
                allow_incomplete=True,
                allow_rule_breaks=True,
            )

        # Assert — a structure finding about the identifier; nothing was written.
        assert raised.value.status_code == 409
        detail = raised.value.detail
        assert isinstance(detail, dict)
        assert detail["blocked_by"] == "structure"
        assert detail["written"] is False
