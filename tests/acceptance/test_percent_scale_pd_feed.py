"""
Acceptance — a risk feed that expresses PD in percent must not silently ship.

The failure this pins is the highest-probability real defect in the estate and the
one measured in docs/plans/test-space-correctness-proposal.md: a firm's feed sends
``pd = 1.5`` meaning 1.5%, and the engine consumes it as 150%.

Measured on ``fix/distribution-gate-and-escapes``, end to end from parquet files
through ``ParquetLoader`` -> ``PipelineOrchestrator.run()`` on a single GBP 1,000,000
senior unsecured corporate F-IRB exposure (CRR, effective maturity 2.5y,
supervisory LGD 45% per the ``firb_supervisory_lgd`` pack entry, CRR Art. 161(1)(a)):

===================  =====================  ===================
PD as supplied       ``rwa_final``          Signal raised
===================  =====================  ===================
``1.5``  (percent)   GBP        603.665912  none
``0.015`` (fraction) GBP  1,119,286.688648  none
===================  =====================  ===================

A **99.9461%** understatement — GBP 1,118,683 of capital per GBP 1m of exposure —
with no exception, no null and no ``CalculationError``. The number is not merely
wrong, it is plausible: a reviewer reading a populated results frame has nothing to
notice. ``1.5`` is outside the PD domain of ``(0, 1]``, and
``contracts/validation.py::validate_pd_range`` has been written and unit-tested
since before this branch — it is simply unreachable from ``src/``
(``.venv/bin/python scripts/validator_reachability.py``).

Validation is non-blocking, so the contract asserted here is the triage invariant,
not a refusal to compute: the out-of-domain row still produces a number AND an
error names it. Exactly one of "trust this figure" and "this figure is flagged"
must be true of every row, and today neither is.

Pipeline position:
    parquet feed -> ParquetLoader (``_run_bundle_validation`` ->
    ``validate_bundle_values``) -> PipelineOrchestrator.run -> AggregatedResultBundle

References:
- docs/plans/test-space-correctness-proposal.md — Phase 0 and the measured table
- CRR Art. 160(1)/163(1): PD is a probability — the domain is (0, 1]
- CRR Art. 161(1)(a): F-IRB supervisory LGD, senior unsecured corporate
- CRR Art. 153: the IRB risk-weight function this feeds
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_PD_OUT_OF_RANGE
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.loader import DataSourceConfig, ParquetLoader
from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_calc.contracts.bundles import AggregatedResultBundle

VALUE_DATE = date(2025, 1, 2)
MATURITY_DATE = date(2030, 1, 2)
REPORTING_DATE = date(2025, 12, 31)

LOAN_REF = "LN_ACME_1"
RATING_REF = "RT_ACME_PD"
COUNTERPARTY_REF = "CP_ACME"

#: The row references a triage-able error may legitimately name.
ROW_IDENTIFIERS = (RATING_REF, COUNTERPARTY_REF, LOAN_REF)

#: PD supplied as a percentage (1.5 meaning 1.5%) — outside the (0, 1] domain.
PERCENT_SCALE_PD = 1.5
#: The same credit quality supplied correctly, as a fraction.
FRACTION_SCALE_PD = 0.015

#: Measured on this branch — the answer the correctly-scaled feed produces.
EXPECTED_RWA_FRACTION_SCALE = 1_119_286.688647647
#: Measured on this branch — what the percent-scale feed silently returns instead.
MEASURED_RWA_PERCENT_SCALE = 603.665912249


def _write_feed(base_dir: Path, pd_value: float) -> DataSourceConfig:
    """Write a one-exposure CRR F-IRB parquet feed carrying *pd_value*."""
    base_dir.mkdir(parents=True, exist_ok=True)

    tables = {
        "counterparties": pl.DataFrame(
            [
                {
                    "counterparty_reference": COUNTERPARTY_REF,
                    "counterparty_name": "Acme Plc",
                    "entity_type": "company",
                    "country_code": "GB",
                    "annual_revenue": 500_000_000.0,
                    "default_status": False,
                }
            ],
            schema=dtypes_of(COUNTERPARTY_SCHEMA),
        ),
        "loans": pl.DataFrame(
            [
                {
                    "loan_reference": LOAN_REF,
                    "product_type": "term_loan",
                    "book_code": "BOOK",
                    "counterparty_reference": COUNTERPARTY_REF,
                    "value_date": VALUE_DATE,
                    "maturity_date": MATURITY_DATE,
                    "currency": "GBP",
                    "drawn_amount": 1_000_000.0,
                    "interest": 0.0,
                    "seniority": "senior",
                    "effective_maturity": 2.5,
                }
            ],
            schema=dtypes_of(LOAN_SCHEMA),
        ),
        "ratings": pl.DataFrame(
            [
                {
                    "rating_reference": RATING_REF,
                    "counterparty_reference": COUNTERPARTY_REF,
                    "rating_type": "internal",
                    "rating_agency": "internal",
                    "rating_value": "BB",
                    "cqs": None,
                    "pd": pd_value,
                    "rating_date": VALUE_DATE,
                    "is_solicited": False,
                    "model_id": "MODEL_CORP_FIRB",
                }
            ],
            schema=dtypes_of(RATINGS_SCHEMA),
        ),
        "model_permissions": pl.DataFrame(
            [
                {
                    "model_id": "MODEL_CORP_FIRB",
                    "exposure_class": "corporate",
                    "approach": "foundation_irb",
                    "country_codes": None,
                    "excluded_book_codes": None,
                }
            ],
            schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
        ),
        "facilities": pl.DataFrame([], schema=dtypes_of(FACILITY_SCHEMA)),
        "facility_mappings": pl.DataFrame([], schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        "lending_mappings": pl.DataFrame([], schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
    }

    paths: dict[str, Path] = {}
    for name, frame in tables.items():
        path = base_dir / f"{name}.parquet"
        frame.write_parquet(path)
        paths[name] = path

    return DataSourceConfig(
        counterparties_file=paths["counterparties"],
        facilities_file=paths["facilities"],
        loans_file=paths["loans"],
        facility_mappings_file=paths["facility_mappings"],
        lending_mappings_file=paths["lending_mappings"],
        ratings_file=paths["ratings"],
        model_permissions_file=paths["model_permissions"],
    )


def _run_feed(base_dir: Path, pd_value: float) -> AggregatedResultBundle:
    """Run the full production path — files on disk, loader, orchestrator."""
    source = _write_feed(base_dir, pd_value)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    return PipelineOrchestrator(loader=ParquetLoader(base_dir, source)).run(config)


@pytest.fixture(scope="module")
def percent_scale_result(tmp_path_factory: pytest.TempPathFactory) -> AggregatedResultBundle:
    return _run_feed(tmp_path_factory.mktemp("pd_percent"), PERCENT_SCALE_PD)


@pytest.fixture(scope="module")
def fraction_scale_result(tmp_path_factory: pytest.TempPathFactory) -> AggregatedResultBundle:
    return _run_feed(tmp_path_factory.mktemp("pd_fraction"), FRACTION_SCALE_PD)


def _exposure_row(result: AggregatedResultBundle) -> dict:
    """The single result row, asserting the frame was emitted at all."""
    df = result.results.collect()
    assert df.height == 1, f"expected exactly one result row, got {df.height}"
    row = df.to_dicts()[0]
    assert row["exposure_reference"] == LOAN_REF
    return row


class TestPercentScalePdFeed:
    """The feed sends 1.5 meaning 1.5%. Something must say so."""

    def test_percent_scale_pd_is_flagged_as_out_of_domain(
        self, percent_scale_result: AggregatedResultBundle
    ) -> None:
        """A PD of 1.5 must produce a CalculationError against the ``pd`` field."""
        # Arrange / Act
        pd_errors = [
            e
            for e in percent_scale_result.errors
            if e.code == ERROR_PD_OUT_OF_RANGE and e.field_name == "pd"
        ]

        # Assert
        assert pd_errors, (
            "pd=1.5 understates RWA by 99.9461% "
            f"(GBP {MEASURED_RWA_PERCENT_SCALE:,.2f} against GBP "
            f"{EXPECTED_RWA_FRACTION_SCALE:,.2f}) and nothing in the run says so. "
            "Accumulated codes: "
            f"{sorted({e.code for e in percent_scale_result.errors}) or '<none>'}"
        )

    def test_the_out_of_domain_error_names_the_offending_row(
        self, percent_scale_result: AggregatedResultBundle
    ) -> None:
        """An error a firm cannot trace to a row cannot be actioned on a real feed."""
        # Arrange / Act
        pd_errors = [
            e
            for e in percent_scale_result.errors
            if e.code == ERROR_PD_OUT_OF_RANGE and e.field_name == "pd"
        ]
        assert pd_errors, "no PD-domain error to inspect — see the sibling test"
        rendered = " ".join(
            f"{e.message} {e.exposure_reference} {e.counterparty_reference} {e.actual_value}"
            for e in pd_errors
        )

        # Assert
        assert any(identifier in rendered for identifier in ROW_IDENTIFIERS), (
            f"the PD-domain error names none of {list(ROW_IDENTIFIERS)}: {rendered}"
        )

    def test_the_flagged_exposure_still_produces_a_result_row(
        self, percent_scale_result: AggregatedResultBundle
    ) -> None:
        """Validation is non-blocking — the row is flagged, not dropped or nulled.

        This is the other half of the triage invariant, and the guard against a
        fix that turns a silent wrong number into a silent missing row.
        """
        # Arrange / Act
        row = _exposure_row(percent_scale_result)

        # Assert
        assert row["ead_final"] is not None
        assert row["risk_weight"] is not None
        assert row["rwa_final"] is not None
        assert row["approach_applied"] == "foundation_irb"

    def test_correctly_scaled_feed_is_unflagged_and_gives_the_expected_rwa(
        self, fraction_scale_result: AggregatedResultBundle
    ) -> None:
        """Control — the same credit, supplied as a fraction, must be clean.

        Pinned to the absolute measured RWA rather than to a comparison against
        the percent-scale run: a relative assertion would have been satisfied by
        both the correct and the understated answer.
        """
        # Arrange / Act
        row = _exposure_row(fraction_scale_result)
        pd_errors = [e for e in fraction_scale_result.errors if e.field_name == "pd"]

        # Assert
        assert row["pd"] == pytest.approx(FRACTION_SCALE_PD)
        assert row["lgd"] == pytest.approx(0.45)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_FRACTION_SCALE, rel=1e-9)
        assert not pd_errors, (
            f"an in-domain PD must not be flagged: {[f'[{e.code}] {e.message}' for e in pd_errors]}"
        )
