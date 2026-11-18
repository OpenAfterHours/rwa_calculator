"""Unit tests for SecuritisationAllocator.

Covers the five validation paths (SEC001-SEC005) and the resolved-lookup
schema. End-to-end pipeline behaviour is exercised in
``tests/integration/test_securitisation_pipeline.py``.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_SEC_DUPLICATE,
    ERROR_SEC_FULLY_SECURITISED,
    ERROR_SEC_INVALID_PCT,
    ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER,
    ERROR_SEC_OVER_ALLOCATED,
    ERROR_SEC_UNKNOWN_REFERENCE,
)
from rwa_calc.contracts.protocols import SecuritisationAllocatorProtocol
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.securitisation.allocator import (
    RESOLVED_SECURITISATION_SCHEMA,
    SecuritisationAllocator,
    attach_securitisation_lookup,
    empty_resolved_lookup,
)

_CONFIG = CalculationConfig.crr(reporting_date=date(2025, 12, 31))


def _bundle(allocs: pl.LazyFrame | None, *, loans: list[str] | None = None) -> RawDataBundle:
    """Build a minimal RawDataBundle with the listed loan_references known."""
    loan_refs = loans or ["L001", "L002", "L003"]
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.LazyFrame(
            {
                "loan_reference": loan_refs,
                "counterparty_reference": ["C001"] * len(loan_refs),
                "drawn_amount": [1_000_000.0] * len(loan_refs),
            }
        ),
        counterparties=pl.LazyFrame(),
        facility_mappings=pl.LazyFrame(),
        lending_mappings=pl.LazyFrame(),
        securitisation_allocations=allocs,
    )


class TestSecuritisationAllocatorProtocol:
    def test_implements_protocol(self) -> None:
        assert isinstance(SecuritisationAllocator(), SecuritisationAllocatorProtocol)


class TestEmptyAndNullInputs:
    def test_returns_none_when_no_allocations_supplied(self) -> None:
        allocator = SecuritisationAllocator()
        data = _bundle(allocs=None)
        _, lookup, errors = allocator.allocate(data, _CONFIG)
        assert lookup is None
        assert errors == []

    def test_returns_empty_lookup_for_empty_input_frame(self) -> None:
        allocator = SecuritisationAllocator()
        empty = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "exposure_type": pl.String,
                "pool_reference": pl.String,
                "allocation_pct": pl.Float64,
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(empty), _CONFIG)
        assert lookup is not None
        assert lookup.collect().height == 0
        assert errors == []


class TestHappyPath:
    def test_single_exposure_50pct_residual(self) -> None:
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "pool_reference": ["POOL_A"],
                "allocation_pct": [0.5],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        df = lookup.collect()
        assert df.height == 1
        row = df.row(0, named=True)
        assert row["exposure_reference"] == "L001"
        assert row["securitisation_residual_pct"] == pytest.approx(0.5)
        assert row["audit_status"] == "ok"
        assert errors == []

    def test_split_across_two_pools_with_residual(self) -> None:
        """SEC-03 hand-calc: 40% pool A + 30% pool B + 30% residual."""
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L001"],
                "exposure_type": ["loan", "loan"],
                "pool_reference": ["POOL_A", "POOL_B"],
                "allocation_pct": [0.4, 0.3],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        df = lookup.collect()
        row = df.row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(0.3)
        pools = {
            p["pool_reference"]: p["allocation_pct"] for p in row["securitisation_pool_allocations"]
        }
        assert pools == pytest.approx({"POOL_A": 0.4, "POOL_B": 0.3})
        assert row["audit_status"] == "ok"


class TestValidationSEC002InvalidPct:
    def test_negative_pct_dropped(self) -> None:
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L002"],
                "exposure_type": ["loan", "loan"],
                "pool_reference": ["POOL_A", "POOL_A"],
                "allocation_pct": [0.5, -0.2],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        df = lookup.collect()
        assert df.height == 1
        assert df.row(0, named=True)["exposure_reference"] == "L001"
        assert any(e.code == ERROR_SEC_INVALID_PCT for e in errors)

    def test_pct_greater_than_one_dropped(self) -> None:
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "pool_reference": ["POOL_A"],
                "allocation_pct": [1.2],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        assert lookup.collect().height == 0
        assert any(e.code == ERROR_SEC_INVALID_PCT for e in errors)


class TestValidationSEC003UnknownReference:
    def test_orphan_dropped(self) -> None:
        """SEC-08: allocation references unknown loan ref."""
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L_ORPHAN"],
                "exposure_type": ["loan", "loan"],
                "pool_reference": ["POOL_A", "POOL_A"],
                "allocation_pct": [0.5, 0.5],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        df = lookup.collect()
        assert df.height == 1
        assert df.row(0, named=True)["exposure_reference"] == "L001"
        assert any(e.code == ERROR_SEC_UNKNOWN_REFERENCE for e in errors)


class TestValidationSEC004Duplicate:
    def test_duplicate_dropped_first_kept(self) -> None:
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L001"],
                "exposure_type": ["loan", "loan"],
                "pool_reference": ["POOL_A", "POOL_A"],
                "allocation_pct": [0.5, 0.3],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        # First row kept: residual = 1 - 0.5 = 0.5
        assert row["securitisation_residual_pct"] == pytest.approx(0.5)
        assert any(e.code == ERROR_SEC_DUPLICATE for e in errors)


class TestValidationSEC001OverAllocated:
    def test_over_allocation_drops_pool_slices(self) -> None:
        """SEC-07: sum > 1.0 -> exposure fully on-balance-sheet."""
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L001"],
                "exposure_type": ["loan", "loan"],
                "pool_reference": ["POOL_A", "POOL_B"],
                "allocation_pct": [0.7, 0.5],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(1.0)
        assert row["securitisation_pool_allocations"] == []
        assert row["audit_status"] == "over_allocated"
        assert any(e.code == ERROR_SEC_OVER_ALLOCATED for e in errors)


class TestValidationSEC005FullySecuritised:
    def test_fully_securitised_residual_is_zero(self) -> None:
        """SEC-01: 100% securitised -> residual 0."""
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "pool_reference": ["POOL_A"],
                "allocation_pct": [1.0],
            }
        )
        _, lookup, errors = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(0.0)
        assert row["audit_status"] == "fully_securitised"
        assert any(e.code == ERROR_SEC_FULLY_SECURITISED for e in errors)


def _srt_allocs(pools: list[str], pcts: list[float], srt: list[bool | None]) -> pl.LazyFrame:
    """Allocation rows for L001 carrying an explicit ``significant_risk_transfer``."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["L001"] * len(pools),
            "exposure_type": ["loan"] * len(pools),
            "pool_reference": pools,
            "allocation_pct": pcts,
            "significant_risk_transfer": srt,
        },
        schema_overrides={"significant_risk_transfer": pl.Boolean},
    )


class TestSignificantRiskTransferSEC006:
    """IV-04: an explicit ``significant_risk_transfer=False`` carves nothing out.

    CRR Art. 244(1) (traditional), verbatim: "The originator institution of a
    traditional securitisation may exclude underlying exposures from its
    calculation of risk-weighted exposure amounts and, where relevant, expected
    loss amounts if either of the following conditions is fulfilled: (a)
    significant credit risk associated with the underlying exposures has been
    transferred to third parties; (b) the originator institution applies a
    1 250 % risk weight to all securitisation positions it holds in the
    securitisation or deducts these securitisation positions from Common Equity
    Tier 1 items". Art. 245(1)(a)/(b) is the synthetic twin. PS1/26 does not
    replace that chapter (Table A2 row (1) points to Chapter 5 of Title II of
    Part Three of CRR). The engine has no securitisation-position route, so
    limb (b) cannot be evidenced either: a row asserting no SRT is retained.
    Pre-fix the flag was read nowhere: residual 0.0 and only SEC005.
    """

    def test_srt_false_keeps_exposure_fully_on_balance_sheet(self) -> None:
        # Arrange
        allocs = _srt_allocs(["POOL_A"], [1.0], [False])

        # Act
        _, lookup, errors = SecuritisationAllocator().allocate(_bundle(allocs), _CONFIG)

        # Assert
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(1.0)
        assert row["securitisation_pool_allocations"] == []
        assert row["audit_status"] == "no_significant_risk_transfer"
        codes = [e.code for e in errors]
        assert ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER in codes
        assert ERROR_SEC_FULLY_SECURITISED not in codes

    def test_srt_true_still_carves_out(self) -> None:
        # Arrange
        allocs = _srt_allocs(["POOL_A"], [1.0], [True])

        # Act
        _, lookup, errors = SecuritisationAllocator().allocate(_bundle(allocs), _CONFIG)

        # Assert
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(0.0)
        assert row["audit_status"] == "fully_securitised"
        codes = [e.code for e in errors]
        assert ERROR_SEC_FULLY_SECURITISED in codes
        assert ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER not in codes

    def test_null_srt_takes_the_documented_true_default(self) -> None:
        """Orchestrator decision: the null -> True schema default is kept (owner decision).

        Asserted end to end: the raw-table seal (``make_raw_bundle``, as the
        loader) fills a null Boolean with the schema default before the allocator
        runs, so this pins the user-visible contract, not the allocator's own
        ``ne_missing(False)`` null branch (unreachable through a sealed bundle).
        """
        # Arrange
        allocs = _srt_allocs(["POOL_A"], [1.0], [None])

        # Act
        _, lookup, errors = SecuritisationAllocator().allocate(_bundle(allocs), _CONFIG)

        # Assert
        assert lookup is not None
        assert lookup.collect().row(0, named=True)["securitisation_residual_pct"] == 0.0
        assert ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER not in [e.code for e in errors]

    def test_mixed_pools_carve_out_only_the_srt_slice(self) -> None:
        """Pool A 0.5 with SRT + pool B 0.3 without: residual 0.5, only A is a slice."""
        # Arrange
        allocs = _srt_allocs(["POOL_A", "POOL_B"], [0.5, 0.3], [True, False])

        # Act
        _, lookup, errors = SecuritisationAllocator().allocate(_bundle(allocs), _CONFIG)

        # Assert
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(0.5)
        assert row["securitisation_pool_allocations"] == [
            {"pool_reference": "POOL_A", "allocation_pct": 0.5}
        ]
        assert row["total_allocated_pct"] == pytest.approx(0.8)
        assert row["audit_status"] == "no_significant_risk_transfer"
        assert ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER in [e.code for e in errors]

    def test_over_allocation_still_counts_rows_without_srt(self) -> None:
        """SEC001 is a data error on the input sum, whatever the SRT assertion."""
        # Arrange
        allocs = _srt_allocs(["POOL_A", "POOL_B"], [0.7, 0.6], [True, False])

        # Act
        _, lookup, errors = SecuritisationAllocator().allocate(_bundle(allocs), _CONFIG)

        # Assert
        assert lookup is not None
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(1.0)
        assert row["audit_status"] == "over_allocated"
        assert ERROR_SEC_OVER_ALLOCATED in [e.code for e in errors]

    def test_sec006_names_the_retained_exposure(self) -> None:
        # Arrange
        allocs = _srt_allocs(["POOL_A"], [1.0], [False])

        # Act
        _, _, errors = SecuritisationAllocator().allocate(_bundle(allocs), _CONFIG)

        # Assert
        sec006 = next(e for e in errors if e.code == ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER)
        assert sec006.severity == ErrorSeverity.WARNING
        assert "L001" in sec006.message
        assert sec006.regulatory_reference is not None
        assert "244" in sec006.regulatory_reference


class TestResolvedSchema:
    def test_empty_lookup_schema_matches_canonical(self) -> None:
        empty = empty_resolved_lookup().collect()
        assert set(empty.columns) == set(RESOLVED_SECURITISATION_SCHEMA.keys())

    def test_resolved_lookup_carries_canonical_columns(self) -> None:
        allocator = SecuritisationAllocator()
        allocs = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "pool_reference": ["POOL_A"],
                "allocation_pct": [0.5],
            }
        )
        _, lookup, _ = allocator.allocate(_bundle(allocs), _CONFIG)
        assert lookup is not None
        assert set(lookup.collect_schema().names()) == set(RESOLVED_SECURITISATION_SCHEMA.keys())


class TestAttachSecuritisationLookup:
    def test_no_lookup_defaults_to_one_and_empty(self) -> None:
        """When no allocations supplied, every row gets residual_pct=1.0 and []."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L002"],
                "exposure_type": ["loan", "contingent"],
                "ead_final": [1000.0, 500.0],
            }
        )
        attached = attach_securitisation_lookup(exposures, None).collect()
        assert attached["securitisation_residual_pct"].to_list() == [1.0, 1.0]
        for pools in attached["securitisation_pool_allocations"].to_list():
            assert pools == []

    def test_attaches_loan_allocation(self) -> None:
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["L001", "L002"],
                "exposure_type": ["loan", "loan"],
                "ead_final": [1000.0, 500.0],
            }
        )
        lookup = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "securitisation_residual_pct": [0.5],
                "securitisation_pool_allocations": [
                    [{"pool_reference": "POOL_A", "allocation_pct": 0.5}]
                ],
            }
        )
        attached = attach_securitisation_lookup(exposures, lookup).collect()
        row_l001 = attached.filter(pl.col("exposure_reference") == "L001").row(0, named=True)
        row_l002 = attached.filter(pl.col("exposure_reference") == "L002").row(0, named=True)
        assert row_l001["securitisation_residual_pct"] == pytest.approx(0.5)
        assert row_l002["securitisation_residual_pct"] == pytest.approx(1.0)
        assert row_l002["securitisation_pool_allocations"] == []

    def test_facility_undrawn_inherits_via_source_facility_reference(self) -> None:
        """SEC-05: facility_undrawn row keys on the parent facility's allocation."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["F001_UNDRAWN", "L001"],
                "exposure_type": ["facility_undrawn", "loan"],
                "source_facility_reference": ["F001", None],
                "ead_final": [600_000.0, 1_000_000.0],
            }
        )
        lookup = pl.LazyFrame(
            {
                "exposure_reference": ["F001"],
                "exposure_type": ["facility"],
                "securitisation_residual_pct": [0.5],
                "securitisation_pool_allocations": [
                    [{"pool_reference": "POOL_A", "allocation_pct": 0.5}]
                ],
            }
        )
        attached = attach_securitisation_lookup(exposures, lookup).collect()
        undrawn = attached.filter(pl.col("exposure_type") == "facility_undrawn").row(0, named=True)
        assert undrawn["securitisation_residual_pct"] == pytest.approx(0.5)
        loan = attached.filter(pl.col("exposure_type") == "loan").row(0, named=True)
        # Loan L001 is NOT in the lookup -> default residual_pct=1.0
        assert loan["securitisation_residual_pct"] == pytest.approx(1.0)
