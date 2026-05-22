"""Unit tests for SecuritisationAllocator.

Covers the five validation paths (SEC001-SEC005) and the resolved-lookup
schema. End-to-end pipeline behaviour is exercised in
``tests/integration/test_securitisation_pipeline.py``.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_SEC_DUPLICATE,
    ERROR_SEC_FULLY_SECURITISED,
    ERROR_SEC_INVALID_PCT,
    ERROR_SEC_OVER_ALLOCATED,
    ERROR_SEC_UNKNOWN_REFERENCE,
)
from rwa_calc.contracts.protocols import SecuritisationAllocatorProtocol
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
    return RawDataBundle(
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
        row = lookup.collect().row(0, named=True)
        assert row["securitisation_residual_pct"] == pytest.approx(0.0)
        assert row["audit_status"] == "fully_securitised"
        assert any(e.code == ERROR_SEC_FULLY_SECURITISED for e in errors)


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
