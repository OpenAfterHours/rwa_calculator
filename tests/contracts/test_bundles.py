"""Tests for data transfer bundles.

Tests the bundle dataclasses and helper functions for creating
empty bundles for testing.
"""

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    CRMAdjustedBundle,
    IRBResultBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
    SAResultBundle,
    create_empty_classified_bundle,
    create_empty_counterparty_lookup,
    create_empty_crm_adjusted_bundle,
    create_empty_raw_data_bundle,
    create_empty_resolved_hierarchy_bundle,
)


class TestRawDataBundle:
    """Tests for RawDataBundle dataclass."""

    def test_create_with_lazyframes(self):
        """Should create bundle with LazyFrames."""
        bundle = RawDataBundle(
            facilities=pl.LazyFrame({"id": [1, 2]}),
            loans=pl.LazyFrame({"id": [3, 4]}),
            contingents=pl.LazyFrame({"id": [5]}),
            counterparties=pl.LazyFrame({"ref": ["A", "B"]}),
            collateral=pl.LazyFrame({"type": ["cash"]}),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=pl.LazyFrame(),
            facility_mappings=pl.LazyFrame(),
            org_mappings=pl.LazyFrame(),
            lending_mappings=pl.LazyFrame(),
        )

        assert bundle.facilities.collect().shape[0] == 2
        assert bundle.loans.collect().shape[0] == 2
        assert bundle.contingents.collect().shape[0] == 1

    def test_optional_specialised_lending(self):
        """Specialised lending should be optional."""
        bundle = create_empty_raw_data_bundle()

        assert bundle.specialised_lending is None

    def test_optional_equity_exposures(self):
        """Equity exposures should be optional."""
        bundle = create_empty_raw_data_bundle()

        assert bundle.equity_exposures is None

    def test_immutable(self):
        """Bundle should be immutable (frozen dataclass)."""
        bundle = create_empty_raw_data_bundle()

        with pytest.raises(AttributeError):
            bundle.facilities = pl.LazyFrame()


class TestCounterpartyLookup:
    """Tests for CounterpartyLookup dataclass."""

    def test_create_with_lookups(self):
        """Should create lookup with hierarchy mappings as LazyFrames."""
        lookup = CounterpartyLookup(
            counterparties=pl.LazyFrame({"counterparty_reference": ["A", "B", "C"]}),
            parent_mappings=pl.LazyFrame(
                {
                    "child_counterparty_reference": ["B", "C"],
                    "parent_counterparty_reference": ["A", "A"],
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                {
                    "counterparty_reference": ["A", "B", "C"],
                    "ultimate_parent_reference": ["A", "A", "A"],
                    "hierarchy_depth": [0, 1, 1],
                }
            ),
            rating_inheritance=pl.LazyFrame(
                {
                    "counterparty_reference": ["A"],
                    "cqs": [1],
                    "pd": [0.001],
                    "rating_value": ["A2"],
                    "inherited": [False],
                    "source_counterparty": ["A"],
                    "inheritance_reason": ["own_rating"],
                }
            ),
        )

        # Verify parent mappings
        parents = lookup.parent_mappings.collect()
        b_parent = parents.filter(pl.col("child_counterparty_reference") == "B")[
            "parent_counterparty_reference"
        ][0]
        assert b_parent == "A"

        # Verify ultimate parent mappings
        ult = lookup.ultimate_parent_mappings.collect()
        c_ult = ult.filter(pl.col("counterparty_reference") == "C")["ultimate_parent_reference"][0]
        assert c_ult == "A"

        # Verify rating inheritance
        ratings = lookup.rating_inheritance.collect()
        a_cqs = ratings.filter(pl.col("counterparty_reference") == "A")["cqs"][0]
        assert a_cqs == 1

    def test_empty_lookups_default(self):
        """Lookups should default to empty LazyFrames."""
        lookup = create_empty_counterparty_lookup()

        assert lookup.parent_mappings.collect().height == 0
        assert lookup.ultimate_parent_mappings.collect().height == 0
        assert lookup.rating_inheritance.collect().height == 0


class TestResolvedHierarchyBundle:
    """Tests for ResolvedHierarchyBundle dataclass."""

    def test_create_with_resolved_data(self):
        """Should create bundle with resolved hierarchy data."""
        bundle = ResolvedHierarchyBundle(
            exposures=pl.LazyFrame({"exposure_ref": ["E1", "E2"]}),
            counterparty_lookup=create_empty_counterparty_lookup(),
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            lending_group_totals=pl.LazyFrame(),
        )

        assert bundle.exposures.collect().shape[0] == 2

    def test_hierarchy_errors_default_empty(self):
        """Hierarchy errors should default to empty list."""
        bundle = create_empty_resolved_hierarchy_bundle()

        assert bundle.hierarchy_errors == []


class TestClassifiedExposuresBundle:
    """Tests for ClassifiedExposuresBundle dataclass."""

    def test_create_with_split_exposures(self):
        """Should create bundle with SA and IRB splits."""
        bundle = ClassifiedExposuresBundle(
            all_exposures=pl.LazyFrame({"ref": ["E1", "E2", "E3"]}),
            sa_exposures=pl.LazyFrame({"ref": ["E1"]}),
            irb_exposures=pl.LazyFrame({"ref": ["E2", "E3"]}),
        )

        assert bundle.all_exposures.collect().shape[0] == 3
        assert bundle.sa_exposures.collect().shape[0] == 1
        assert bundle.irb_exposures.collect().shape[0] == 2

    def test_optional_slotting_exposures(self):
        """Slotting exposures should be optional."""
        bundle = create_empty_classified_bundle()

        assert bundle.slotting_exposures is None

    def test_optional_audit_trail(self):
        """Classification audit should be optional."""
        bundle = create_empty_classified_bundle()

        assert bundle.classification_audit is None


class TestCRMAdjustedBundle:
    """Tests for CRMAdjustedBundle dataclass."""

    def test_create_with_crm_data(self):
        """Should create bundle with CRM-adjusted data."""
        bundle = CRMAdjustedBundle(
            exposures=pl.LazyFrame({"ref": ["E1"], "final_ead": [1000.0]}),
            sa_exposures=pl.LazyFrame({"ref": ["E1"]}),
            irb_exposures=pl.LazyFrame(),
        )

        assert bundle.exposures.collect().shape[0] == 1

    def test_optional_audit_trail(self):
        """CRM audit should be optional."""
        bundle = create_empty_crm_adjusted_bundle()

        assert bundle.crm_audit is None
        assert bundle.collateral_allocation is None


class TestSAResultBundle:
    """Tests for SAResultBundle dataclass."""

    def test_create_sa_results(self):
        """Should create bundle with SA results."""
        bundle = SAResultBundle(
            results=pl.LazyFrame(
                {
                    "ref": ["E1"],
                    "sa_rwa": [100.0],
                }
            )
        )

        assert bundle.results.collect().shape[0] == 1

    def test_errors_default_empty(self):
        """Errors should default to empty list."""
        bundle = SAResultBundle(results=pl.LazyFrame())

        assert bundle.errors == []


class TestIRBResultBundle:
    """Tests for IRBResultBundle dataclass."""

    def test_create_irb_results(self):
        """Should create bundle with IRB results."""
        bundle = IRBResultBundle(
            results=pl.LazyFrame(
                {
                    "ref": ["E1"],
                    "irb_rwa": [150.0],
                }
            ),
            expected_loss=pl.LazyFrame(
                {
                    "ref": ["E1"],
                    "el": [5.0],
                }
            ),
        )

        assert bundle.results.collect().shape[0] == 1
        assert bundle.expected_loss.collect().shape[0] == 1

    def test_optional_expected_loss(self):
        """Expected loss should be optional."""
        bundle = IRBResultBundle(results=pl.LazyFrame())

        assert bundle.expected_loss is None


class TestAggregatedResultBundle:
    """Tests for AggregatedResultBundle dataclass."""

    def test_create_aggregated_results(self):
        """Should create bundle with aggregated results."""
        bundle = AggregatedResultBundle(
            results=pl.LazyFrame({"final_rwa": [100.0, 150.0]}),
            sa_results=pl.LazyFrame({"sa_rwa": [100.0]}),
            irb_results=pl.LazyFrame({"irb_rwa": [150.0]}),
        )

        assert bundle.results.collect().shape[0] == 2

    def test_optional_impact_analysis(self):
        """Impact analysis frames should be optional."""
        bundle = AggregatedResultBundle(results=pl.LazyFrame())

        assert bundle.floor_impact is None
        assert bundle.supporting_factor_impact is None
        assert bundle.summary_by_class is None


class TestEmptyBundleFactories:
    """Tests for empty bundle factory functions."""

    def test_create_empty_raw_data_bundle(self):
        """Should create valid empty RawDataBundle."""
        bundle = create_empty_raw_data_bundle()

        assert isinstance(bundle, RawDataBundle)
        assert bundle.facilities.collect().shape[0] == 0
        assert bundle.loans.collect().shape[0] == 0

    def test_create_empty_counterparty_lookup(self):
        """Should create valid empty CounterpartyLookup."""
        lookup = create_empty_counterparty_lookup()

        assert isinstance(lookup, CounterpartyLookup)
        assert lookup.counterparties.collect().shape[0] == 0

    def test_create_empty_resolved_hierarchy_bundle(self):
        """Should create valid empty ResolvedHierarchyBundle."""
        bundle = create_empty_resolved_hierarchy_bundle()

        assert isinstance(bundle, ResolvedHierarchyBundle)
        assert bundle.exposures.collect().shape[0] == 0

    def test_create_empty_classified_bundle(self):
        """Should create valid empty ClassifiedExposuresBundle."""
        bundle = create_empty_classified_bundle()

        assert isinstance(bundle, ClassifiedExposuresBundle)
        assert bundle.all_exposures.collect().shape[0] == 0

    def test_create_empty_crm_adjusted_bundle(self):
        """Should create valid empty CRMAdjustedBundle."""
        bundle = create_empty_crm_adjusted_bundle()

        assert isinstance(bundle, CRMAdjustedBundle)
        assert bundle.exposures.collect().shape[0] == 0
