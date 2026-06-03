"""Unit tests for the hierarchy resolver module.

Tests cover:
- Parent and ultimate parent lookup building
- Rating inheritance from parents
- Exposure unification (loans + contingents)
- Lending group exposure aggregation
- Full hierarchy resolution pipeline
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    RawDataBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_DUPLICATE_KEY
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.hierarchy import HierarchyResolver

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def resolver() -> HierarchyResolver:
    """Return a HierarchyResolver instance."""
    return HierarchyResolver()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def simple_counterparties() -> pl.LazyFrame:
    """Simple counterparties LazyFrame for testing."""
    return pl.DataFrame(
        {
            "counterparty_reference": ["CP001", "CP002", "CP003", "CP004"],
            "counterparty_name": ["Parent Corp", "Child Corp 1", "Child Corp 2", "Standalone"],
            "entity_type": ["corporate", "corporate", "corporate", "corporate"],
            "country_code": ["GB", "GB", "GB", "GB"],
            "annual_revenue": [100000000.0, 20000000.0, 30000000.0, 5000000.0],
            "total_assets": [500000000.0, 100000000.0, 150000000.0, 25000000.0],
            "default_status": [False, False, False, False],
            "sector_code": ["MANU", "MANU", "MANU", "SERV"],
            "is_financial_institution": [False, False, False, False],
            "apply_fi_scalar": [True, True, True, True],
            "is_pse": [False, False, False, False],
            "is_mdb": [False, False, False, False],
            "is_international_org": [False, False, False, False],
            "is_central_counterparty": [False, False, False, False],
            "is_regional_govt_local_auth": [False, False, False, False],
            "is_managed_as_retail": [False, False, False, False],
        }
    ).lazy()


@pytest.fixture
def simple_org_mappings() -> pl.LazyFrame:
    """Simple org mappings for single-level hierarchy."""
    return pl.DataFrame(
        {
            "parent_counterparty_reference": ["CP001", "CP001"],
            "child_counterparty_reference": ["CP002", "CP003"],
        }
    ).lazy()


@pytest.fixture
def multi_level_org_mappings() -> pl.LazyFrame:
    """Multi-level org hierarchy for testing transitive resolution."""
    return pl.DataFrame(
        {
            "parent_counterparty_reference": ["ULTIMATE", "HOLDING", "HOLDING"],
            "child_counterparty_reference": ["HOLDING", "OPSUB1", "OPSUB2"],
        }
    ).lazy()


@pytest.fixture
def simple_ratings() -> pl.LazyFrame:
    """Simple ratings - parent has both internal and external ratings."""
    return pl.DataFrame(
        {
            "rating_reference": ["RAT001", "RAT002"],
            "counterparty_reference": ["CP001", "CP001"],
            "rating_type": ["external", "internal"],
            "rating_agency": ["MOODYS", "INT"],
            "rating_value": ["A2", "INT_A"],
            "cqs": [2, None],
            "pd": [None, 0.001],
            "rating_date": [date(2024, 6, 1), date(2024, 6, 1)],
            "is_solicited": [True, True],
        }
    ).lazy()


@pytest.fixture
def simple_loans() -> pl.LazyFrame:
    """Simple loans for testing."""
    return pl.DataFrame(
        {
            "loan_reference": ["LOAN001", "LOAN002", "LOAN003"],
            "product_type": ["TERM_LOAN", "TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP", "CORP"],
            "counterparty_reference": ["CP002", "CP003", "CP004"],
            "value_date": [date(2023, 1, 1)] * 3,
            "maturity_date": [date(2026, 1, 1)] * 3,
            "currency": ["GBP", "GBP", "GBP"],
            "drawn_amount": [1000000.0, 2000000.0, 500000.0],
            "lgd": [0.45, 0.45, 0.45],
            "beel": [0.01, 0.01, 0.01],
            "seniority": ["senior", "senior", "senior"],
            "risk_type": ["FR", "FR", "FR"],  # Full risk for drawn loans
            "ccf_modelled": [None, None, None],  # No modelled CCF
            "is_short_term_trade_lc": [None, None, None],  # N/A for loans
        }
    ).lazy()


@pytest.fixture
def simple_contingents() -> pl.LazyFrame:
    """Simple contingents for testing."""
    return pl.DataFrame(
        {
            "contingent_reference": ["CONT001", "CONT002"],
            "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP002", "CP004"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2025, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "nominal_amount": [250000.0, 100000.0],
            "lgd": [0.45, 0.45],
            "beel": [0.01, 0.01],
            "seniority": ["senior", "senior"],
            "risk_type": ["MR", "MR"],  # Medium risk
            "ccf_modelled": [None, None],  # No modelled CCF
            "is_short_term_trade_lc": [False, False],  # Not trade LCs
        }
    ).lazy()


@pytest.fixture
def simple_facility_mappings() -> pl.LazyFrame:
    """Simple facility mappings."""
    return pl.DataFrame(
        {
            "parent_facility_reference": ["FAC001", "FAC001", "FAC002"],
            "child_reference": ["LOAN001", "CONT001", "LOAN002"],
            "child_type": ["loan", "contingent", "loan"],
        }
    ).lazy()


@pytest.fixture
def lending_group_mappings() -> pl.LazyFrame:
    """Lending group mappings for retail threshold testing."""
    return pl.DataFrame(
        {
            "parent_counterparty_reference": ["LG_ANCHOR", "LG_ANCHOR"],
            "child_counterparty_reference": ["LG_MEMBER1", "LG_MEMBER2"],
        }
    ).lazy()


@pytest.fixture
def lending_group_counterparties() -> pl.LazyFrame:
    """Counterparties for lending group testing."""
    return pl.DataFrame(
        {
            "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2", "STANDALONE"],
            "counterparty_name": ["Anchor Person", "Member 1", "Member 2", "Standalone"],
            "entity_type": ["individual", "individual", "corporate", "individual"],
            "country_code": ["GB", "GB", "GB", "GB"],
            "annual_revenue": [0.0, 0.0, 500000.0, 0.0],
            "total_assets": [0.0, 0.0, 1000000.0, 0.0],
            "default_status": [False, False, False, False],
            "sector_code": ["RETAIL", "RETAIL", "RETAIL", "RETAIL"],
            "is_financial_institution": [False, False, False, False],
            "apply_fi_scalar": [True, True, True, True],
            "is_pse": [False, False, False, False],
            "is_mdb": [False, False, False, False],
            "is_international_org": [False, False, False, False],
            "is_central_counterparty": [False, False, False, False],
            "is_regional_govt_local_auth": [False, False, False, False],
            "is_managed_as_retail": [False, False, False, False],
        }
    ).lazy()


@pytest.fixture
def lending_group_loans() -> pl.LazyFrame:
    """Loans for lending group testing."""
    return pl.DataFrame(
        {
            "loan_reference": ["LG_LOAN1", "LG_LOAN2", "LG_LOAN3", "STANDALONE_LOAN"],
            "product_type": ["MORTGAGE", "PERSONAL", "BUSINESS", "PERSONAL"],
            "book_code": ["RETAIL", "RETAIL", "RETAIL", "RETAIL"],
            "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2", "STANDALONE"],
            "value_date": [date(2023, 1, 1)] * 4,
            "maturity_date": [date(2028, 1, 1)] * 4,
            "currency": ["GBP", "GBP", "GBP", "GBP"],
            "drawn_amount": [300000.0, 200000.0, 400000.0, 50000.0],
            "lgd": [0.15, 0.45, 0.45, 0.45],
            "beel": [0.01, 0.01, 0.01, 0.01],
            "seniority": ["senior", "senior", "senior", "senior"],
            "risk_type": ["FR", "FR", "FR", "FR"],  # Full risk for drawn loans
            "ccf_modelled": [None, None, None, None],  # No modelled CCF
            "is_short_term_trade_lc": [None, None, None, None],  # N/A for loans
        }
    ).lazy()


@pytest.fixture
def empty_lazyframe() -> pl.LazyFrame:
    """Empty LazyFrame for testing edge cases."""
    return pl.LazyFrame()


@pytest.fixture
def simple_raw_data_bundle(
    simple_counterparties: pl.LazyFrame,
    simple_org_mappings: pl.LazyFrame,
    simple_ratings: pl.LazyFrame,
    simple_loans: pl.LazyFrame,
    simple_contingents: pl.LazyFrame,
    simple_facility_mappings: pl.LazyFrame,
) -> RawDataBundle:
    """Simple raw data bundle for testing."""
    return RawDataBundle(
        facilities=pl.LazyFrame(),
        loans=simple_loans,
        contingents=simple_contingents,
        counterparties=simple_counterparties,
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        ratings=simple_ratings,
        facility_mappings=simple_facility_mappings,
        org_mappings=simple_org_mappings,
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
    )


# =============================================================================
# Ultimate Parent Lookup Tests (LazyFrame-based)
# =============================================================================


class TestBuildUltimateParentLazy:
    """Tests for _build_ultimate_parent_lazy method."""

    def test_single_level_hierarchy(
        self,
        resolver: HierarchyResolver,
        simple_org_mappings: pl.LazyFrame,
    ) -> None:
        """Single-level hierarchy should have correct ultimate parent."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(simple_org_mappings)
        df = ultimate_parents.collect()

        # CP002 -> CP001, CP003 -> CP001
        cp002 = df.filter(pl.col("counterparty_reference") == "CP002")
        cp003 = df.filter(pl.col("counterparty_reference") == "CP003")

        assert cp002["ultimate_parent_reference"][0] == "CP001"
        assert cp003["ultimate_parent_reference"][0] == "CP001"

    def test_multi_level_hierarchy(
        self,
        resolver: HierarchyResolver,
        multi_level_org_mappings: pl.LazyFrame,
    ) -> None:
        """Multi-level hierarchy should resolve ultimate parent correctly."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(multi_level_org_mappings)
        df = ultimate_parents.collect()

        # All should ultimately resolve to "ULTIMATE"
        holding = df.filter(pl.col("counterparty_reference") == "HOLDING")
        opsub1 = df.filter(pl.col("counterparty_reference") == "OPSUB1")
        opsub2 = df.filter(pl.col("counterparty_reference") == "OPSUB2")

        assert holding["ultimate_parent_reference"][0] == "ULTIMATE"
        assert opsub1["ultimate_parent_reference"][0] == "ULTIMATE"
        assert opsub2["ultimate_parent_reference"][0] == "ULTIMATE"

        # Verify hierarchy depths
        assert holding["hierarchy_depth"][0] == 1
        assert opsub1["hierarchy_depth"][0] == 2
        assert opsub2["hierarchy_depth"][0] == 2

    def test_empty_mappings(self, resolver: HierarchyResolver) -> None:
        """Empty mappings should return empty LazyFrame."""
        empty_mappings = pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        )

        ultimate_parents = resolver._build_ultimate_parent_lazy(empty_mappings)
        df = ultimate_parents.collect()

        assert df.height == 0


# =============================================================================
# Rating Inheritance Tests (LazyFrame-based)
# =============================================================================


class TestBuildRatingInheritanceLazy:
    """Tests for _build_rating_inheritance_lazy method."""

    def test_entity_with_own_rating(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
    ) -> None:
        """Entity with own rating should use its own ratings."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(simple_org_mappings)

        rating_inheritance = resolver._build_rating_inheritance_lazy(
            simple_counterparties,
            simple_ratings,
            ultimate_parents,
        )
        df = rating_inheritance.collect()

        # CP001 has own external and internal ratings
        cp001 = df.filter(pl.col("counterparty_reference") == "CP001")
        assert cp001["cqs"][0] == 2
        assert cp001["internal_pd"][0] == pytest.approx(0.001)

    def test_internal_rating_inherits_from_parent(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
    ) -> None:
        """Unrated child inherits parent's internal rating but not external."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(simple_org_mappings)

        rating_inheritance = resolver._build_rating_inheritance_lazy(
            simple_counterparties,
            simple_ratings,
            ultimate_parents,
        )
        df = rating_inheritance.collect()

        # CP002 inherits internal from CP001 but NOT external
        cp002 = df.filter(pl.col("counterparty_reference") == "CP002")
        assert cp002["internal_pd"][0] == pytest.approx(0.001)
        assert cp002["pd"][0] == pytest.approx(0.001)
        assert cp002["cqs"][0] is None
        assert cp002["external_cqs"][0] is None

    def test_standalone_unrated_entity(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Standalone unrated entity should be marked as unrated."""
        # Empty org mappings - no hierarchy
        empty_mappings = pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        )
        ultimate_parents = resolver._build_ultimate_parent_lazy(empty_mappings)

        rating_inheritance = resolver._build_rating_inheritance_lazy(
            simple_counterparties,
            simple_ratings,
            ultimate_parents,
        )
        df = rating_inheritance.collect()

        # CP004 is standalone and unrated
        cp004 = df.filter(pl.col("counterparty_reference") == "CP004")
        assert cp004["cqs"][0] is None


class TestInheritanceTruthTable:
    """Behavioural lock for the dual coalesce in _build_rating_inheritance_lazy.

    See REVIEWER NOTE on _build_rating_inheritance_lazy: rows 4, 6, 7 of this
    truth table are the load-bearing assertions. A refactor that simplifies
    the coalesce (e.g. fusing PD + model_id into a struct-coalesce, or
    collapsing the two own/parent joins into one) MUST update these rows;
    do not delete them.

    Row 7 (desync) is skipped pending a Risk decision on whether
    independent-coalesce or strict-pairing is the intended semantic for the
    case where own_pd is present but own_model_id is null. Replace RWA-XXXX
    with the real ticket and unskip with the agreed expected tuple before
    merge.
    """

    @staticmethod
    def _build_inheritance_inputs(
        own_pd: float | None,
        own_model_id: str | None,
        parent_pd: float | None,
        parent_model_id: str | None,
        *,
        own_cqs: int | None = None,
        parent_cqs: int | None = None,
        multi_level: bool = False,
    ) -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
        """Build (counterparties, ratings, org_mappings) for one truth-table row.

        Single-level: CHILD -> PARENT.
        Multi-level (depth 2): CHILD -> MID -> ULT, parent_* applied to ULT.
        """
        if multi_level:
            counterparty_refs = ["CHILD", "MID", "ULT"]
            org_mappings = pl.DataFrame(
                {
                    "child_counterparty_reference": ["CHILD", "MID"],
                    "parent_counterparty_reference": ["MID", "ULT"],
                }
            ).lazy()
            parent_ref = "ULT"
        else:
            counterparty_refs = ["CHILD", "PARENT"]
            org_mappings = pl.DataFrame(
                {
                    "child_counterparty_reference": ["CHILD"],
                    "parent_counterparty_reference": ["PARENT"],
                }
            ).lazy()
            parent_ref = "PARENT"

        counterparties = pl.DataFrame({"counterparty_reference": counterparty_refs}).lazy()

        rating_rows: dict[str, list[object]] = {
            "rating_reference": [],
            "counterparty_reference": [],
            "rating_type": [],
            "rating_agency": [],
            "rating_value": [],
            "cqs": [],
            "pd": [],
            "model_id": [],
            "rating_date": [],
        }

        def _add(
            rating_ref: str,
            cp_ref: str,
            rtype: str,
            agency: str,
            value: str,
            cqs: int | None,
            pd_value: float | None,
            model_id: str | None,
        ) -> None:
            rating_rows["rating_reference"].append(rating_ref)
            rating_rows["counterparty_reference"].append(cp_ref)
            rating_rows["rating_type"].append(rtype)
            rating_rows["rating_agency"].append(agency)
            rating_rows["rating_value"].append(value)
            rating_rows["cqs"].append(cqs)
            rating_rows["pd"].append(pd_value)
            rating_rows["model_id"].append(model_id)
            rating_rows["rating_date"].append(date(2024, 6, 1))

        if own_pd is not None or own_model_id is not None:
            _add("R_OWN_INT", "CHILD", "internal", "INTERNAL", "INT", None, own_pd, own_model_id)
        if own_cqs is not None:
            _add("R_OWN_EXT", "CHILD", "external", "MOODYS", "Aa1", own_cqs, None, None)
        if parent_pd is not None or parent_model_id is not None:
            _add(
                "R_PARENT_INT",
                parent_ref,
                "internal",
                "INTERNAL",
                "INT",
                None,
                parent_pd,
                parent_model_id,
            )
        if parent_cqs is not None:
            _add("R_PARENT_EXT", parent_ref, "external", "MOODYS", "Aa1", parent_cqs, None, None)

        if not rating_rows["rating_reference"]:
            ratings = pl.DataFrame(
                schema={
                    "rating_reference": pl.String,
                    "counterparty_reference": pl.String,
                    "rating_type": pl.String,
                    "rating_agency": pl.String,
                    "rating_value": pl.String,
                    "cqs": pl.Int64,
                    "pd": pl.Float64,
                    "model_id": pl.String,
                    "rating_date": pl.Date,
                }
            ).lazy()
        else:
            ratings = pl.DataFrame(rating_rows).lazy()

        return counterparties, ratings, org_mappings

    @pytest.mark.parametrize(
        (
            "scenario",
            "own_pd",
            "own_model",
            "parent_pd",
            "parent_model",
            "own_cqs",
            "parent_cqs",
            "multi",
            "exp_pd",
            "exp_model",
            "exp_cqs",
        ),
        [
            ("1_empty", None, None, None, None, None, None, False, None, None, None),
            ("2_inherit", None, None, 0.02, "M_PARENT", None, None, False, 0.02, "M_PARENT", None),
            ("3_own_only", 0.01, "M_OWN", None, None, None, None, False, 0.01, "M_OWN", None),
            (
                "4_gap_own_wins",
                0.01,
                "M_OWN",
                0.02,
                "M_PARENT",
                None,
                None,
                False,
                0.01,
                "M_OWN",
                None,
            ),
            ("5_tie", 0.02, "M_OWN", 0.02, "M_PARENT", None, None, False, 0.02, "M_OWN", None),
            ("6_multi_level", None, None, 0.01, "M_ULT", None, None, True, 0.01, "M_ULT", None),
            pytest.param(
                "7_desync_blocked",
                0.02,
                None,
                None,
                "M_PARENT",
                None,
                None,
                False,
                None,
                None,
                None,
                marks=pytest.mark.skip(
                    reason=(
                        "BLOCKED on Risk decision RWA-XXXX: Option A "
                        "(independent coalesce, current: pd=0.02, model=M_PARENT) "
                        "vs Option B (strict pairing: pd=0.02, model=null). "
                        "Replace RWA-XXXX with the real ticket and unskip with "
                        "the agreed expected tuple before merge."
                    )
                ),
            ),
            ("8_desync_mirror", None, "M_OWN", 0.02, None, None, None, False, 0.02, "M_OWN", None),
            ("9_external_fence", None, None, None, None, None, 2, False, None, None, None),
            ("10_full_rating", 0.005, "M_OWN", 0.02, "M_PARENT", 1, None, False, 0.005, "M_OWN", 1),
        ],
    )
    def test_inheritance_truth_table(
        self,
        resolver: HierarchyResolver,
        scenario: str,
        own_pd: float | None,
        own_model: str | None,
        parent_pd: float | None,
        parent_model: str | None,
        own_cqs: int | None,
        parent_cqs: int | None,
        multi: bool,
        exp_pd: float | None,
        exp_model: str | None,
        exp_cqs: int | None,
    ) -> None:
        """Behavioural truth table for the dual own->parent coalesce."""
        counterparties, ratings, org_mappings = self._build_inheritance_inputs(
            own_pd,
            own_model,
            parent_pd,
            parent_model,
            own_cqs=own_cqs,
            parent_cqs=parent_cqs,
            multi_level=multi,
        )

        ultimate_parents = resolver._build_ultimate_parent_lazy(org_mappings)

        if multi:
            # Pre-assert that ultimate-parent resolution actually walked 2 hops.
            ups = ultimate_parents.collect()
            child_row = ups.filter(pl.col("counterparty_reference") == "CHILD")
            assert len(child_row) == 1, f"missing CHILD in {scenario} ultimate_parents"
            assert child_row["ultimate_parent_reference"][0] == "ULT", scenario
            assert child_row["hierarchy_depth"][0] == 2, scenario

        result = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()

        child = result.filter(pl.col("counterparty_reference") == "CHILD")
        assert len(child) == 1, f"expected exactly one CHILD row in {scenario}"

        # Canonical column assertions.
        if exp_pd is None:
            assert child["internal_pd"][0] is None, scenario
        else:
            assert child["internal_pd"][0] == pytest.approx(exp_pd), scenario

        if exp_model is None:
            assert child["internal_model_id"][0] is None, scenario
        else:
            assert child["internal_model_id"][0] == exp_model, scenario

        if exp_cqs is None:
            assert child["external_cqs"][0] is None, scenario
        else:
            assert child["external_cqs"][0] == exp_cqs, scenario

        # Alias column assertions — pin the alias derivation at
        # hierarchy.py:434-439 so a refactor that drops the alias fails loudly.
        if exp_pd is None:
            assert child["pd"][0] is None, scenario
        else:
            assert child["pd"][0] == pytest.approx(exp_pd), scenario

        if exp_cqs is None:
            assert child["cqs"][0] is None, scenario
        else:
            assert child["cqs"][0] == exp_cqs, scenario


class TestDualRatingResolution:
    """Tests for dual per-type (internal/external) rating resolution."""

    def test_dual_rated_counterparty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Counterparty with both internal and external rating resolves both."""
        counterparties = pl.DataFrame({"counterparty_reference": ["CP001"]}).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["RAT_INT", "RAT_EXT"],
                "counterparty_reference": ["CP001", "CP001"],
                "rating_type": ["internal", "external"],
                "rating_agency": ["INTERNAL", "MOODYS"],
                "rating_value": ["INT_A", "A2"],
                "cqs": [None, 2],
                "pd": [0.0063, None],
                "rating_date": [date(2024, 6, 1), date(2024, 6, 1)],
            }
        ).lazy()
        ultimate_parents = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        )

        result = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()

        cp = result.filter(pl.col("counterparty_reference") == "CP001")
        assert cp["internal_pd"][0] == pytest.approx(0.0063)
        assert cp["external_cqs"][0] == 2
        # Derived: cqs = external-first, pd = internal only
        assert cp["cqs"][0] == 2
        assert cp["pd"][0] == pytest.approx(0.0063)

    def test_most_recent_per_type(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Multiple ratings of same type → most recent wins."""
        counterparties = pl.DataFrame({"counterparty_reference": ["CP001"]}).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["OLD_INT", "NEW_INT", "OLD_EXT", "NEW_EXT"],
                "counterparty_reference": ["CP001"] * 4,
                "rating_type": ["internal", "internal", "external", "external"],
                "rating_agency": ["INT", "INT", "MOODYS", "MOODYS"],
                "rating_value": ["OLD", "NEW", "Baa1", "A2"],
                "cqs": [None, None, 3, 2],
                "pd": [0.01, 0.005, None, None],
                "rating_date": [
                    date(2023, 1, 1),
                    date(2024, 6, 1),
                    date(2023, 1, 1),
                    date(2024, 6, 1),
                ],
            }
        ).lazy()
        ultimate_parents = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        )

        result = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()

        cp = result.filter(pl.col("counterparty_reference") == "CP001")
        assert cp["internal_pd"][0] == pytest.approx(0.005)  # Newer internal
        assert cp["external_cqs"][0] == 2  # Newer external

    def test_per_type_inheritance(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Child keeps own internal; parent's external does not inherit."""
        counterparties = pl.DataFrame({"counterparty_reference": ["PARENT", "CHILD"]}).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["CHILD_INT", "PARENT_EXT"],
                "counterparty_reference": ["CHILD", "PARENT"],
                "rating_type": ["internal", "external"],
                "rating_agency": ["INT", "SP"],
                "rating_value": ["INT_A", "A+"],
                "cqs": [None, 1],
                "pd": [0.003, None],
                "rating_date": [date(2024, 6, 1), date(2024, 6, 1)],
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["PARENT"],
                "child_counterparty_reference": ["CHILD"],
            }
        ).lazy()
        ultimate_parents = resolver._build_ultimate_parent_lazy(org_mappings)

        result = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()

        child = result.filter(pl.col("counterparty_reference") == "CHILD")
        # Own internal retained
        assert child["internal_pd"][0] == pytest.approx(0.003)
        assert child["pd"][0] == pytest.approx(0.003)
        # External does NOT inherit from parent
        assert child["external_cqs"][0] is None
        assert child["cqs"][0] is None

    def test_external_rating_does_not_inherit(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """External ratings must not inherit from parent to child.

        External ratings (from agencies like S&P, Fitch) are specific to
        the counterparty they were assigned to. Only internal ratings
        inherit down the org hierarchy.
        """
        counterparties = pl.DataFrame({"counterparty_reference": ["PARENT", "CHILD"]}).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["PARENT_EXT"],
                "counterparty_reference": ["PARENT"],
                "rating_type": ["external"],
                "rating_agency": ["SP"],
                "rating_value": ["A+"],
                "cqs": [1],
                "pd": [None],
                "rating_date": [date(2024, 6, 1)],
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["PARENT"],
                "child_counterparty_reference": ["CHILD"],
            }
        ).lazy()
        ultimate_parents = resolver._build_ultimate_parent_lazy(org_mappings)

        result = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()

        # Parent keeps own external rating
        parent = result.filter(pl.col("counterparty_reference") == "PARENT")
        assert parent["external_cqs"][0] == 1
        assert parent["cqs"][0] == 1

        # Child must NOT inherit parent's external rating
        child = result.filter(pl.col("counterparty_reference") == "CHILD")
        assert child["external_cqs"][0] is None
        assert child["cqs"][0] is None
        assert child["internal_pd"][0] is None
        assert child["pd"][0] is None

    def test_external_only_counterparty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Counterparty with only external rating has null internal_pd."""
        counterparties = pl.DataFrame({"counterparty_reference": ["CP001"]}).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["RAT_EXT"],
                "counterparty_reference": ["CP001"],
                "rating_type": ["external"],
                "rating_agency": ["MOODYS"],
                "rating_value": ["A2"],
                "cqs": [2],
                "pd": [None],
                "rating_date": [date(2024, 6, 1)],
            }
        ).lazy()
        ultimate_parents = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        )

        result = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()

        cp = result.filter(pl.col("counterparty_reference") == "CP001")
        assert cp["internal_pd"][0] is None
        assert cp["external_cqs"][0] == 2
        assert cp["cqs"][0] == 2
        assert cp["pd"][0] is None


class TestArt138ExternalRatingResolution:
    """CRR Art. 138 multi-rating resolution across nominated ECAIs.

    - 1 rating  -> use it
    - 2 ratings -> higher RW (worse CQS)
    - >=3       -> higher of the two lowest RWs (second-best CQS)

    Same-agency repeats first reduce to the most recent before Art. 138 runs.
    """

    @staticmethod
    def _run(resolver: HierarchyResolver, ratings: pl.LazyFrame) -> pl.DataFrame:
        counterparties = pl.DataFrame({"counterparty_reference": ["CP"]}).lazy()
        ultimate_parents = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        )
        df = resolver._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        ).collect()
        assert isinstance(df, pl.DataFrame)
        return df

    @staticmethod
    def _ratings(cqs_by_agency: list[tuple[str, int, date]]) -> pl.LazyFrame:
        return pl.DataFrame(
            {
                "rating_reference": [f"R{i}" for i in range(len(cqs_by_agency))],
                "counterparty_reference": ["CP"] * len(cqs_by_agency),
                "rating_type": ["external"] * len(cqs_by_agency),
                "rating_agency": [a for a, _, _ in cqs_by_agency],
                "rating_value": ["x"] * len(cqs_by_agency),
                "cqs": [c for _, c, _ in cqs_by_agency],
                "pd": [None] * len(cqs_by_agency),
                "rating_date": [d for _, _, d in cqs_by_agency],
            }
        ).lazy()

    def test_single_rating_used_as_is(self, resolver: HierarchyResolver) -> None:
        ratings = self._ratings([("MOODYS", 3, date(2024, 6, 1))])
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 3

    def test_two_ratings_picks_worse(self, resolver: HierarchyResolver) -> None:
        # CQS 2 (better, lower RW) vs CQS 4 (worse) -> worse wins
        ratings = self._ratings(
            [
                ("MOODYS", 2, date(2024, 6, 1)),
                ("SP", 4, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 4

    def test_two_ratings_same_cqs(self, resolver: HierarchyResolver) -> None:
        ratings = self._ratings(
            [
                ("MOODYS", 3, date(2024, 6, 1)),
                ("SP", 3, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 3

    def test_three_ratings_picks_second_best(self, resolver: HierarchyResolver) -> None:
        # CQS 1, 3, 5 -> two lowest are 1 and 3 -> higher = 3
        ratings = self._ratings(
            [
                ("MOODYS", 1, date(2024, 6, 1)),
                ("SP", 3, date(2024, 6, 1)),
                ("FITCH", 5, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 3

    def test_four_ratings_second_best(self, resolver: HierarchyResolver) -> None:
        # CQS 1, 3, 4, 6 -> second-best = 3
        ratings = self._ratings(
            [
                ("MOODYS", 1, date(2024, 6, 1)),
                ("SP", 3, date(2024, 6, 1)),
                ("FITCH", 4, date(2024, 6, 1)),
                ("DBRS", 6, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 3

    def test_ties_at_best_cqs(self, resolver: HierarchyResolver) -> None:
        # CQS 2, 2, 3, 5 -> two lowest are 2 and 2 -> second-best = 2
        ratings = self._ratings(
            [
                ("MOODYS", 2, date(2024, 6, 1)),
                ("SP", 2, date(2024, 6, 1)),
                ("FITCH", 3, date(2024, 6, 1)),
                ("DBRS", 5, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 2

    def test_ties_at_second_and_third(self, resolver: HierarchyResolver) -> None:
        # CQS 1, 3, 3, 5 -> second-best = 3
        ratings = self._ratings(
            [
                ("MOODYS", 1, date(2024, 6, 1)),
                ("SP", 3, date(2024, 6, 1)),
                ("FITCH", 3, date(2024, 6, 1)),
                ("DBRS", 5, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 3

    def test_same_agency_repeated_reduces_to_most_recent(self, resolver: HierarchyResolver) -> None:
        # Two agencies, each with two assessments. Moody's newest is CQS 2,
        # S&P newest is CQS 4. Art. 138 on [2, 4] -> worse = 4.
        ratings = self._ratings(
            [
                ("MOODYS", 5, date(2022, 1, 1)),
                ("MOODYS", 2, date(2024, 6, 1)),
                ("SP", 6, date(2022, 1, 1)),
                ("SP", 4, date(2024, 6, 1)),
            ]
        )
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 4

    def test_null_cqs_ignored(self, resolver: HierarchyResolver) -> None:
        # One valid rating (CQS 3) and one null-CQS row; null is dropped
        # so n==1 -> use the valid one.
        ratings = pl.DataFrame(
            {
                "rating_reference": ["R0", "R1"],
                "counterparty_reference": ["CP", "CP"],
                "rating_type": ["external", "external"],
                "rating_agency": ["MOODYS", "SP"],
                "rating_value": ["Baa1", "NR"],
                "cqs": [3, None],
                "pd": [None, None],
                "rating_date": [date(2024, 6, 1), date(2024, 6, 1)],
            }
        ).lazy()
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] == 3

    def test_no_external_ratings(self, resolver: HierarchyResolver) -> None:
        ratings = pl.DataFrame(
            {
                "rating_reference": ["R0"],
                "counterparty_reference": ["CP"],
                "rating_type": ["internal"],
                "rating_agency": ["INT"],
                "rating_value": ["INT_A"],
                "cqs": [None],
                "pd": [0.01],
                "rating_date": [date(2024, 6, 1)],
            }
        ).lazy()
        result = self._run(resolver, ratings)
        assert result["external_cqs"][0] is None


# =============================================================================
# Exposure Unification Tests
# =============================================================================


class TestUnifyExposures:
    """Tests for _unify_exposures method."""

    def test_loans_and_contingents_combined(
        self,
        resolver: HierarchyResolver,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_facility_mappings: pl.LazyFrame,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loans and contingents should be unified correctly."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            simple_loans,
            simple_contingents,
            None,  # No facilities for this test
            simple_facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Should have 3 loans + 2 contingents = 5 exposures
        assert len(df) == 5

        # Check exposure types
        loan_count = df.filter(pl.col("exposure_type") == "loan").height
        contingent_count = df.filter(pl.col("exposure_type") == "contingent").height
        assert loan_count == 3
        assert contingent_count == 2

    def test_exposure_references_preserved(
        self,
        resolver: HierarchyResolver,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_facility_mappings: pl.LazyFrame,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Exposure references should be preserved during unification."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, _ = resolver._unify_exposures(
            simple_loans,
            simple_contingents,
            None,  # No facilities for this test
            simple_facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()
        refs = df["exposure_reference"].to_list()

        assert "LOAN001" in refs
        assert "LOAN002" in refs
        assert "LOAN003" in refs
        assert "CONT001" in refs
        assert "CONT002" in refs

    def test_facility_hierarchy_added(
        self,
        resolver: HierarchyResolver,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_facility_mappings: pl.LazyFrame,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Facility hierarchy info should be added to exposures."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, _ = resolver._unify_exposures(
            simple_loans,
            simple_contingents,
            None,  # No facilities for this test
            simple_facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # LOAN001 is under FAC001
        loan001 = df.filter(pl.col("exposure_reference") == "LOAN001")
        assert loan001["exposure_has_parent"][0] is True
        assert loan001["parent_facility_reference"][0] == "FAC001"


# =============================================================================
# Lending Group Aggregation Tests
# =============================================================================


class TestLendingGroupAggregation:
    """Tests for lending group exposure aggregation."""

    def test_lending_group_totals_calculated(
        self,
        resolver: HierarchyResolver,
        lending_group_counterparties: pl.LazyFrame,
        lending_group_loans: pl.LazyFrame,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """Lending group totals should be correctly calculated."""
        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=lending_group_loans,
            contingents=pl.LazyFrame(
                schema={
                    "contingent_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "nominal_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            counterparties=lending_group_counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=lending_group_mappings,
        )
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        result = resolver.resolve(bundle, config)
        df = result.lending_group_totals.collect()

        # Should have one lending group
        assert len(df) == 1
        assert df["lending_group_reference"][0] == "LG_ANCHOR"

        # Total should be sum of anchor + members (300k + 200k + 400k = 900k)
        assert df["total_drawn"][0] == 900000.0
        # Adjusted exposure should equal total (no residential collateral)
        assert df["adjusted_exposure"][0] == 900000.0

    def test_standalone_not_in_lending_group(
        self,
        resolver: HierarchyResolver,
        lending_group_counterparties: pl.LazyFrame,
        lending_group_loans: pl.LazyFrame,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """Standalone counterparty with one exposure aggregates to its own drawn."""
        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=lending_group_loans,
            contingents=pl.LazyFrame(
                schema={
                    "contingent_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "nominal_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            counterparties=lending_group_counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=lending_group_mappings,
        )
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        result = resolver.resolve(bundle, config)
        df = result.exposures.collect()

        # Standalone loan has no lending group, so aggregation falls back to the
        # counterparty's own exposures — a single 50,000 drawn loan in this case
        # (CRR Art. 4(1)(39): a standalone obligor is a group-of-one).
        standalone = df.filter(pl.col("exposure_reference") == "STANDALONE_LOAN")
        assert standalone["lending_group_reference"][0] is None
        assert standalone["lending_group_total_exposure"][0] == pytest.approx(50000.0, abs=1e-10)
        assert standalone["lending_group_adjusted_exposure"][0] == pytest.approx(50000.0, abs=1e-10)

    def test_standalone_counterparty_aggregates_own_exposures(
        self,
        resolver: HierarchyResolver,
        lending_group_counterparties: pl.LazyFrame,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """A counterparty with multiple loans and no lending group aggregates across them.

        Regression for retail threshold bug: previously the threshold test used the
        per-row `exposure_for_retail_threshold`, incorrectly treating each line as
        an independent obligor.  CRR Art. 123(c) / Art. 4(1)(39) require aggregation
        across every exposure to the counterparty even when no explicit lending
        group exists.
        """
        loans = pl.DataFrame(
            {
                "loan_reference": ["SOLO_1", "SOLO_2", "SOLO_3"],
                "product_type": ["PERSONAL", "PERSONAL", "PERSONAL"],
                "book_code": ["RETAIL", "RETAIL", "RETAIL"],
                "counterparty_reference": ["STANDALONE"] * 3,
                "value_date": [date(2023, 1, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "drawn_amount": [400000.0, 400000.0, 400000.0],
                "lgd": [0.45] * 3,
                "beel": [0.01] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["FR"] * 3,
                "ccf_modelled": [None, None, None],
                "is_short_term_trade_lc": [None, None, None],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=loans,
            contingents=pl.LazyFrame(
                schema={
                    "contingent_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "nominal_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            counterparties=lending_group_counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=lending_group_mappings,
        )
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        result = resolver.resolve(bundle, config)
        df = result.exposures.collect()

        standalone_rows = df.filter(pl.col("counterparty_reference") == "STANDALONE")
        assert len(standalone_rows) == 3
        # Every row should see the full 1.2m counterparty aggregate, not its own 400k.
        assert standalone_rows["lending_group_reference"].to_list() == [None, None, None]
        for total in standalone_rows["lending_group_total_exposure"].to_list():
            assert total == pytest.approx(1_200_000.0, abs=1e-6)
        for adjusted in standalone_rows["lending_group_adjusted_exposure"].to_list():
            assert adjusted == pytest.approx(1_200_000.0, abs=1e-6)


# =============================================================================
# Full Resolution Tests
# =============================================================================


class TestFullResolution:
    """Tests for the complete resolve() method."""

    def test_resolve_returns_correct_bundle_type(
        self,
        resolver: HierarchyResolver,
        simple_raw_data_bundle: RawDataBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """resolve() should return a ResolvedHierarchyBundle."""
        result = resolver.resolve(simple_raw_data_bundle, crr_config)
        assert isinstance(result, ResolvedHierarchyBundle)

    def test_resolve_populates_all_fields(
        self,
        resolver: HierarchyResolver,
        simple_raw_data_bundle: RawDataBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """resolve() should populate all required fields."""
        result = resolver.resolve(simple_raw_data_bundle, crr_config)

        assert result.exposures is not None
        assert result.counterparty_lookup is not None
        assert result.collateral is not None
        assert result.guarantees is not None
        assert result.provisions is not None
        assert result.lending_group_totals is not None
        assert isinstance(result.hierarchy_errors, list)

    def test_resolve_with_real_fixtures(
        self,
        resolver: HierarchyResolver,
        fixtures_path: Path,
        crr_config: CalculationConfig,
    ) -> None:
        """resolve() should work with actual test fixtures."""
        if not fixtures_path.exists():
            pytest.skip("Fixtures path does not exist")

        from rwa_calc.engine.loader import ParquetLoader

        loader = ParquetLoader(fixtures_path)
        raw_data = loader.load()

        result = resolver.resolve(raw_data, crr_config)

        # Verify we can collect results
        exposures_df = result.exposures.collect()
        assert len(exposures_df) > 0

        # Verify counterparty lookup is populated
        assert isinstance(result.counterparty_lookup, CounterpartyLookup)


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_loans_and_contingents(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Should handle empty loans and contingents."""
        empty_bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=pl.LazyFrame(
                schema={
                    "loan_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "drawn_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            contingents=pl.LazyFrame(
                schema={
                    "contingent_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "nominal_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            counterparties=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                }
            ),
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=pl.LazyFrame(
                schema={
                    "rating_reference": pl.String,
                    "counterparty_reference": pl.String,
                    "rating_type": pl.String,
                    "rating_agency": pl.String,
                    "rating_value": pl.String,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                    "rating_date": pl.Date,
                    "is_solicited": pl.Boolean,
                }
            ),
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(empty_bundle, crr_config)

        # Should not raise and should return valid bundle
        assert isinstance(result, ResolvedHierarchyBundle)
        exposures_df = result.exposures.collect()
        assert len(exposures_df) == 0

    def test_no_org_hierarchy(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should handle case with no org hierarchy."""
        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=simple_loans,
            contingents=simple_contingents,
            counterparties=simple_counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=simple_ratings,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)

        # Should work without org hierarchy
        assert isinstance(result, ResolvedHierarchyBundle)
        assert result.counterparty_lookup.parent_mappings.collect().height == 0


# =============================================================================
# Facility Undrawn Calculation Tests
# =============================================================================


class TestFacilityUndrawnCalculation:
    """Tests for _calculate_facility_undrawn method."""

    @pytest.fixture
    def facilities_with_undrawn(self) -> pl.LazyFrame:
        """Facilities for testing undrawn calculation."""
        return pl.DataFrame(
            {
                "facility_reference": ["FAC001", "FAC002", "FAC003", "FAC004", "FAC005"],
                "product_type": ["RCF", "TERM", "OVERDRAFT", "RCF", "RCF"],
                "book_code": ["CORP", "CORP", "CORP", "CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005"],
                "value_date": [date(2023, 1, 1)] * 5,
                "maturity_date": [date(2028, 1, 1)] * 5,
                "currency": ["GBP"] * 5,
                "limit": [5000000.0, 1000000.0, 500000.0, 1000000.0, 1000000.0],
                "committed": [True, True, True, True, True],
                "lgd": [0.45] * 5,
                "beel": [0.01] * 5,
                "is_revolving": [True, False, True, True, True],
                "seniority": ["senior"] * 5,
                "risk_type": ["MR", "MR", "MR", "MR", "LR"],  # MR=50% CCF, LR=0% CCF
                "ccf_modelled": [None, None, None, 0.80, None],  # FAC004 has modelled CCF
                "is_short_term_trade_lc": [False, False, False, False, False],
            }
        ).lazy()

    @pytest.fixture
    def loans_for_facilities(self) -> pl.LazyFrame:
        """Loans linked to facilities."""
        return pl.DataFrame(
            {
                "loan_reference": ["LOAN001", "LOAN002", "LOAN003", "LOAN004"],
                "product_type": ["TERM_LOAN", "TERM_LOAN", "OVERDRAFT_DRAW", "TERM_LOAN"],
                "book_code": ["CORP"] * 4,
                "counterparty_reference": ["CP001", "CP001", "CP002", "CP003"],
                "value_date": [date(2023, 6, 1)] * 4,
                "maturity_date": [date(2028, 1, 1)] * 4,
                "currency": ["GBP"] * 4,
                "drawn_amount": [4000000.0, 500000.0, 1000000.0, 700000.0],
                "lgd": [0.45] * 4,
                "beel": [0.01] * 4,
                "seniority": ["senior"] * 4,
            }
        ).lazy()

    @pytest.fixture
    def facility_loan_mappings(self) -> pl.LazyFrame:
        """Mappings between facilities and loans."""
        return pl.DataFrame(
            {
                "parent_facility_reference": ["FAC001", "FAC001", "FAC002", "FAC003"],
                "child_reference": ["LOAN001", "LOAN002", "LOAN003", "LOAN004"],
                "child_type": ["loan", "loan", "loan", "loan"],
            }
        ).lazy()

    def test_normal_facility_undrawn_calculation(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Normal facility should have undrawn = limit - drawn."""
        # FAC001: limit=5M, drawn=4.5M (LOAN001 + LOAN002), undrawn=500k
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(500000.0)  # 5M - 4.5M = 500k
        assert fac001["nominal_amount"][0] == pytest.approx(500000.0)
        assert fac001["exposure_type"][0] == "facility_undrawn"
        assert fac001["risk_type"][0] == "MR"

    def test_fully_drawn_facility_not_included(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Fully drawn facility (undrawn=0) should not create exposure."""
        # FAC002: limit=1M, drawn=1M (LOAN003), undrawn=0
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        # FAC002 should NOT be in the output since undrawn = 0
        fac002 = df.filter(pl.col("exposure_reference") == "FAC002_UNDRAWN")
        assert len(fac002) == 0

    def test_facility_with_no_loans_100_percent_undrawn(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Facility with no linked loans should be 100% undrawn."""
        # FAC004: limit=1M, no linked loans, undrawn=1M
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        fac004 = df.filter(pl.col("exposure_reference") == "FAC004_UNDRAWN")
        assert len(fac004) == 1
        assert fac004["undrawn_amount"][0] == pytest.approx(1000000.0)
        # Should inherit ccf_modelled from facility
        assert fac004["ccf_modelled"][0] == pytest.approx(0.80)

    def test_overdrawn_facility_capped_at_zero(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Overdrawn facility (drawn > limit) should have undrawn capped at 0."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["OVERDRAWN_FAC"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["OVERDRAWN_LOAN"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [1200000.0],  # Drawn > limit
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["OVERDRAWN_FAC"],
                "child_reference": ["OVERDRAWN_LOAN"],
                "child_type": ["loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Should not create exposure since undrawn is capped at 0
        assert len(df) == 0

    def test_negative_drawn_amount_treated_as_zero(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Negative drawn amount should be treated as zero for undrawn calculation.

        If a loan has a negative drawn amount (e.g., credit balance), it should
        not increase the facility's undrawn headroom beyond the limit.
        Formula: undrawn = max(0, limit - max(0, drawn))
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_NEG"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_NEG"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [-50000.0],  # Negative drawn (credit balance)
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_NEG"],
                "child_reference": ["LOAN_NEG"],
                "child_type": ["loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Undrawn should be exactly the limit (1M), not limit + |negative| (1.05M)
        fac = df.filter(pl.col("exposure_reference") == "FAC_NEG_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(1000000.0)

    def test_mixed_positive_negative_drawn_amounts(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Mixed positive and negative drawn amounts - negatives treated as zero.

        When multiple loans are linked to a facility, only positive drawn amounts
        should count towards the total drawn. Negative amounts are floored at 0.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_MIX"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        # Two loans: one positive (400k), one negative (-100k)
        # Total drawn should be 400k (not 300k), undrawn = 600k
        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_POS", "LOAN_NEG"],
                "product_type": ["TERM_LOAN", "TERM_LOAN"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 6, 1), date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
                "currency": ["GBP", "GBP"],
                "drawn_amount": [400000.0, -100000.0],
                "lgd": [0.45, 0.45],
                "seniority": ["senior", "senior"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_MIX", "FAC_MIX"],
                "child_reference": ["LOAN_POS", "LOAN_NEG"],
                "child_type": ["loan", "loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Undrawn = 1M - 400k = 600k (NOT 1M - 300k = 700k)
        fac = df.filter(pl.col("exposure_reference") == "FAC_MIX_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(600000.0)

    def test_all_negative_drawn_amounts(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """All negative drawn amounts should result in full limit as undrawn."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_ALL_NEG"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [500000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_NEG1", "LOAN_NEG2"],
                "product_type": ["TERM_LOAN", "TERM_LOAN"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 6, 1), date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
                "currency": ["GBP", "GBP"],
                "drawn_amount": [-25000.0, -75000.0],  # Both negative
                "lgd": [0.45, 0.45],
                "seniority": ["senior", "senior"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ALL_NEG", "FAC_ALL_NEG"],
                "child_reference": ["LOAN_NEG1", "LOAN_NEG2"],
                "child_type": ["loan", "loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Both loans are negative, so total_drawn = 0, undrawn = full limit
        fac = df.filter(pl.col("exposure_reference") == "FAC_ALL_NEG_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(500000.0)

    def test_negative_drawn_with_interest_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Negative drawn with interest: interest doesn't reduce facility headroom.

        When a loan has drawn_amount=-100k and interest=100, the loan exposure
        should carry interest=100, but the facility undrawn should still equal
        the full limit (interest doesn't consume headroom).
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_INT"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_NEG_INT"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [-100000.0],
                "interest": [100.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_INT"],
                "child_reference": ["LOAN_NEG_INT"],
                "child_type": ["loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Facility undrawn should be full limit (interest doesn't reduce headroom)
        fac = df.filter(pl.col("exposure_reference") == "FAC_INT_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(1000000.0)

    def test_netting_negative_drawn_offsets_facility_utilisation(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Netting-flagged negative drawn balances reduce facility utilisation.

        Under an on-balance-sheet netting agreement (CRR Art. 195/219, PS1/26
        Art. 195/219), a deposit booked as a negative-drawn loan is treated as
        cash collateral against sibling positives. For facility-level
        utilisation that means total_drawn nets the negative, and the facility
        undrawn reflects the net headroom rather than the gross-positive sum.

        Scenario: Fac_01 limit 100m, three sibling loans 60m + 60m + (-40m
        netting deposit) → net drawn 80m → undrawn 20m.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_NETTING"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [100_000_000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_01", "LOAN_02", "LOAN_03"],
                "product_type": ["TERM_LOAN", "TERM_LOAN", "DEPOSIT"],
                "book_code": ["CORP", "CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001", "CP001"],
                "value_date": [date(2023, 6, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP", "GBP", "GBP"],
                "drawn_amount": [60_000_000.0, 60_000_000.0, -40_000_000.0],
                "lgd": [0.45, 0.45, 0.45],
                "seniority": ["senior", "senior", "senior"],
                "netting_agreement_reference": [None, None, "AGR01"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_NETTING"] * 3,
                "child_reference": ["LOAN_01", "LOAN_02", "LOAN_03"],
                "child_type": ["loan", "loan", "loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        fac = df.filter(pl.col("exposure_reference") == "FAC_NETTING_UNDRAWN")
        assert len(fac) == 1
        # Net drawn = 60 + 60 - 40 = 80m. Undrawn = 100m - 80m = 20m.
        assert fac["undrawn_amount"][0] == pytest.approx(20_000_000.0)

    def test_negative_drawn_without_netting_flag_still_clipped(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """A negative drawn without netting_agreement_reference is still clipped.

        Regression guard: the netting-aware aggregation must not change the
        historical treatment of accidental data-quality negatives. Without a
        netting agreement reference, the negative loan contributes 0 to the
        facility utilisation total and the undrawn reflects only the positive sum.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_NO_NET"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [100_000_000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_01", "LOAN_02", "LOAN_03"],
                "product_type": ["TERM_LOAN"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP001"] * 3,
                "value_date": [date(2023, 6, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "drawn_amount": [60_000_000.0, 60_000_000.0, -40_000_000.0],
                "lgd": [0.45, 0.45, 0.45],
                "seniority": ["senior", "senior", "senior"],
                "netting_agreement_reference": [None, None, None],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_NO_NET"] * 3,
                "child_reference": ["LOAN_01", "LOAN_02", "LOAN_03"],
                "child_type": ["loan", "loan", "loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # 60 + 60 = 120m drawn, undrawn = max(0, 100 - 120) = 0 → row suppressed
        # (the unify path filters out 0-amount undrawn rows).
        fac = df.filter(pl.col("exposure_reference") == "FAC_NO_NET_UNDRAWN")
        assert len(fac) == 0

    def test_facility_lr_risk_type(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Committed facility with LR risk type should create exposure with LR."""
        # FAC005: limit=1M, committed=True, no linked loans, risk_type=LR (0% CCF).
        # The LR-with-zero-CCF treatment under CRR is for the on-pipeline row;
        # genuine uncommitted (committed=False) suppression is covered by the
        # dedicated tests below.
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        fac005 = df.filter(pl.col("exposure_reference") == "FAC005_UNDRAWN")
        assert len(fac005) == 1
        assert fac005["undrawn_amount"][0] == pytest.approx(1000000.0)
        assert fac005["risk_type"][0] == "LR"  # Low risk = 0% CCF

    def test_facility_partial_draw_calculation(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Partially drawn facility should have correct undrawn amount."""
        # FAC003: limit=500k, drawn=700k (LOAN004), but loan is mapped to FAC003
        # Wait - looking at the test data, LOAN004 (700k) is mapped to FAC003 (limit 500k)
        # This would result in negative undrawn, which should be capped at 0
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        # FAC003 has limit 500k but drawn 700k, so undrawn is capped at 0
        fac003 = df.filter(pl.col("exposure_reference") == "FAC003_UNDRAWN")
        assert len(fac003) == 0

    def test_facility_undrawn_inherits_ccf_fields(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Facility undrawn should inherit CCF-related fields from facility."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_CCF"],
                "product_type": ["TRADE_LC"],
                "book_code": ["TRADE"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2024, 6, 1)],
                "currency": ["GBP"],
                "limit": [500000.0],
                "committed": [True],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MLR"],  # Medium-low risk (20% SA, 75% F-IRB, or 20% if trade LC)
                "ccf_modelled": [0.65],
                "is_short_term_trade_lc": [True],  # Art. 166(9) exception
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "drawn_amount": pl.Float64,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        mappings = pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        assert len(df) == 1
        assert df["exposure_reference"][0] == "FAC_CCF_UNDRAWN"
        assert df["risk_type"][0] == "MLR"
        assert df["ccf_modelled"][0] == pytest.approx(0.65)
        assert df["is_short_term_trade_lc"][0] is True
        assert df["nominal_amount"][0] == pytest.approx(500000.0)

    def test_empty_facilities_returns_empty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Empty facilities should return empty LazyFrame."""
        facilities = pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "limit": pl.Float64,
            }
        )

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "drawn_amount": pl.Float64,
            }
        )

        mappings = pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        assert len(df) == 0

    def test_uncommitted_facility_suppresses_undrawn_row(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Uncommitted facility (committed=False) generates no synthetic undrawn row.

        The bank can refuse to lend, so no commitment EAD/RWA is held against the
        unused headroom — even when limit > 0 and no loans are drawn.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_UNCOMMIT"],
                "product_type": ["UNCOMMITTED_RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [False],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["LR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "drawn_amount": pl.Float64,
            }
        )

        mappings = pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # No facility_undrawn row at all — undrawn headroom carries no commitment
        # EAD because the bank is not contractually obliged to lend.
        assert len(df) == 0

    def test_committed_null_treated_as_committed(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Null committed values default to True (committed) — defensive behaviour
        matching FACILITY_SCHEMA's default. Legacy callers that omit committed or
        pass null must keep generating undrawn rows as before.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_NULL_COMMIT"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [500000.0],
                "committed": pl.Series([None], dtype=pl.Boolean),
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "drawn_amount": pl.Float64,
            }
        )

        mappings = pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Null committed → treated as True → undrawn row IS generated.
        assert len(df) == 1
        assert df["exposure_reference"][0] == "FAC_NULL_COMMIT_UNDRAWN"
        assert df["undrawn_amount"][0] == pytest.approx(500000.0)


class TestFacilityUndrawnInUnifyExposures:
    """Tests for facility undrawn integration in _unify_exposures."""

    def test_unify_exposures_includes_facility_undrawn(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """_unify_exposures should include facility_undrawn exposure type."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_UNIFY"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_UNIFY"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [600000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_UNIFY"],
                "child_reference": ["LOAN_UNIFY"],
                "child_type": ["loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,  # No contingents
            facilities,
            facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Should have loan + facility_undrawn
        assert len(df) == 2

        # Check exposure types
        exposure_types = df["exposure_type"].to_list()
        assert "loan" in exposure_types
        assert "facility_undrawn" in exposure_types

        # Check facility_undrawn record
        facility_undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert facility_undrawn["exposure_reference"][0] == "FAC_UNIFY_UNDRAWN"
        assert facility_undrawn["undrawn_amount"][0] == pytest.approx(400000.0)  # 1M - 600k
        assert facility_undrawn["nominal_amount"][0] == pytest.approx(400000.0)
        assert facility_undrawn["risk_type"][0] == "MR"

    def test_uncommitted_facility_loans_still_flow(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Uncommitted facility suppresses its undrawn row, but the loan mapped to
        it is unaffected — the loan is already on-balance-sheet and still flows
        through the unified exposures with correct counterparty linkage.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_UNCOMMIT_FLOW"],
                "product_type": ["UNCOMMITTED_RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [False],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["LR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_ON_UNCOMMIT"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_UNCOMMIT_FLOW"],
                "child_reference": ["LOAN_ON_UNCOMMIT"],
                "child_type": ["loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, _ = resolver._unify_exposures(
            loans,
            None,
            facilities,
            facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Loan is still present, no facility_undrawn synthetic row.
        assert "facility_undrawn" not in df["exposure_type"].to_list()
        loan_rows = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_rows) == 1
        assert loan_rows["exposure_reference"][0] == "LOAN_ON_UNCOMMIT"
        assert loan_rows["counterparty_reference"][0] == "CP002"
        assert loan_rows["drawn_amount"][0] == pytest.approx(100000.0)

    def test_uncommitted_facility_contingents_still_flow(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Uncommitted facility suppresses its undrawn row, but a contingent mapped
        to it is unaffected — the contingent retains its own exposure row with
        nominal_amount intact for downstream CCF and reporting.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_UNCOMMIT_CONT"],
                "product_type": ["UNCOMMITTED_RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [False],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["LR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "drawn_amount": pl.Float64,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT_ON_UNCOMMIT"],
                "product_type": ["FINANCIAL_GUARANTEE"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [200000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "bs_type": ["OFB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_UNCOMMIT_CONT"],
                "child_reference": ["CONT_ON_UNCOMMIT"],
                "child_type": ["contingent"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, _ = resolver._unify_exposures(
            loans,
            contingents,
            facilities,
            facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        assert "facility_undrawn" not in df["exposure_type"].to_list()
        cont_rows = df.filter(pl.col("exposure_type") == "contingent")
        assert len(cont_rows) == 1
        assert cont_rows["exposure_reference"][0] == "CONT_ON_UNCOMMIT"
        assert cont_rows["counterparty_reference"][0] == "CP002"
        assert cont_rows["nominal_amount"][0] == pytest.approx(200000.0)

    def test_full_resolve_includes_facility_undrawn(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Full resolve() should include facility_undrawn exposures."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_RESOLVE"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_RESOLVE"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [2000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_RESOLVE"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_RESOLVE"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_RESOLVE"],
                "counterparty_name": ["Test Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [50000000.0],
                "total_assets": [100000000.0],
                "default_status": [False],
                "sector_code": ["MANU"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_RESOLVE"],
                "child_reference": ["LOAN_RESOLVE"],
                "child_type": ["loan"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have loan + facility_undrawn
        assert len(df) == 2

        # Check exposure types
        exposure_types = df["exposure_type"].unique().to_list()
        assert "loan" in exposure_types
        assert "facility_undrawn" in exposure_types

        # Check facility_undrawn amounts
        facility_undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert facility_undrawn["undrawn_amount"][0] == pytest.approx(1500000.0)  # 2M - 500k

    def test_facility_undrawn_excludes_interest_from_calculation(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn should be limit - drawn_amount (excluding interest).

        Per the plan:
        - Facility limit: 1000
        - Drawn loan: 500
        - Interest: 10
        - Undrawn = 1000 - 500 = 500 (interest excluded from undrawn calc)
        - On-balance-sheet = 500 + 10 = 510
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_INT"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_INT"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000.0],  # Limit = 1000
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_INT"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_INT"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500.0],  # Drawn = 500
                "interest": [10.0],  # Interest = 10 (should NOT reduce undrawn)
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_INT"],
                "counterparty_name": ["Interest Test Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [50000000.0],
                "total_assets": [100000000.0],
                "default_status": [False],
                "sector_code": ["MANU"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_INT"],
                "child_reference": ["LOAN_INT"],
                "child_type": ["loan"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have loan + facility_undrawn = 2 exposures
        assert len(df) == 2

        # Check the loan exposure has interest included
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert loan_exp["drawn_amount"][0] == pytest.approx(500.0)
        assert loan_exp["interest"][0] == pytest.approx(10.0)

        # Check facility_undrawn uses only drawn_amount (not interest)
        # Undrawn = limit (1000) - drawn (500) = 500
        facility_undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert facility_undrawn["undrawn_amount"][0] == pytest.approx(500.0)
        # Facility undrawn should have interest = 0
        assert facility_undrawn["interest"][0] == pytest.approx(0.0)


# =============================================================================
# Same Reference Tests (facility_reference = loan_reference)
# =============================================================================


class TestSameFacilityAndLoanReference:
    """Tests for scenarios where facility_reference equals loan_reference.

    In some source systems, the facility and loan share the same reference ID.
    This is a valid business scenario that must be supported. The system
    differentiates them by:
    - exposure_type: "loan" vs "facility_undrawn"
    - Facility undrawn gets "_UNDRAWN" suffix in exposure_reference
    - Different tables (facilities vs loans) with different schemas
    """

    @pytest.fixture
    def same_ref_facility(self) -> pl.LazyFrame:
        """Facility with reference that matches its loan."""
        return pl.DataFrame(
            {
                "facility_reference": ["REF001"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_SAME_REF"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "committed": [True],
                "lgd": [0.45],
                "beel": [0.01],
                "is_revolving": [True],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
            }
        ).lazy()

    @pytest.fixture
    def same_ref_loan(self) -> pl.LazyFrame:
        """Loan with reference that matches its parent facility."""
        return pl.DataFrame(
            {
                "loan_reference": ["REF001"],  # Same as facility_reference
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_SAME_REF"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [600000.0],
                "interest": [5000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
            }
        ).lazy()

    @pytest.fixture
    def same_ref_mapping(self) -> pl.LazyFrame:
        """Facility mapping linking facility REF001 to loan REF001."""
        return pl.DataFrame(
            {
                "parent_facility_reference": ["REF001"],
                "child_reference": ["REF001"],  # Same reference for both
                "child_type": ["loan"],
            }
        ).lazy()

    @pytest.fixture
    def same_ref_counterparty(self) -> pl.LazyFrame:
        """Counterparty for same-reference test."""
        return pl.DataFrame(
            {
                "counterparty_reference": ["CP_SAME_REF"],
                "counterparty_name": ["Same Reference Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [50000000.0],
                "total_assets": [100000000.0],
                "default_status": [False],
                "sector_code": ["MANU"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        ).lazy()

    def test_undrawn_calculation_with_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
    ) -> None:
        """Undrawn calculation should work when facility and loan share reference.

        Facility REF001: limit=1M
        Loan REF001: drawn=600k
        Expected undrawn = 1M - 600k = 400k
        """
        facility_undrawn = resolver._calculate_facility_undrawn(
            same_ref_facility,
            same_ref_loan,
            None,
            same_ref_mapping,
        )
        df = facility_undrawn.collect()

        # Should create one undrawn exposure with _UNDRAWN suffix
        assert len(df) == 1
        assert df["exposure_reference"][0] == "REF001_UNDRAWN"
        assert df["undrawn_amount"][0] == pytest.approx(400000.0)
        assert df["exposure_type"][0] == "facility_undrawn"

    def test_unify_exposures_differentiates_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
        same_ref_counterparty: pl.LazyFrame,
    ) -> None:
        """Unified exposures should correctly differentiate loan from facility_undrawn.

        Even though facility_reference = loan_reference = "REF001":
        - Loan exposure: exposure_reference = "REF001", exposure_type = "loan"
        - Facility undrawn: exposure_reference = "REF001_UNDRAWN", exposure_type = "facility_undrawn"
        """
        # Build counterparty lookup
        enriched_counterparties = same_ref_counterparty.with_columns(
            [
                pl.lit(False).alias("counterparty_has_parent"),
                pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
                pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
                pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
                pl.lit(None).cast(pl.Int8).alias("cqs"),
                pl.lit(None).cast(pl.Float64).alias("pd"),
            ]
        )

        counterparty_lookup = CounterpartyLookup(
            counterparties=enriched_counterparties,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        )

        exposures, errors = resolver._unify_exposures(
            same_ref_loan,
            None,  # No contingents
            same_ref_facility,
            same_ref_mapping,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Should have 2 exposures: loan + facility_undrawn
        assert len(df) == 2

        # Check loan exposure
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_exp) == 1
        assert loan_exp["exposure_reference"][0] == "REF001"
        assert loan_exp["drawn_amount"][0] == pytest.approx(600000.0)
        assert loan_exp["interest"][0] == pytest.approx(5000.0)

        # Check facility_undrawn exposure
        undrawn_exp = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert len(undrawn_exp) == 1
        assert undrawn_exp["exposure_reference"][0] == "REF001_UNDRAWN"
        assert undrawn_exp["undrawn_amount"][0] == pytest.approx(400000.0)

    def test_loan_correctly_linked_to_parent_facility_with_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
        same_ref_counterparty: pl.LazyFrame,
    ) -> None:
        """Loan should be correctly linked to parent facility even with same reference.

        The loan "REF001" should have parent_facility_reference = "REF001".
        This is not a circular reference - they are different entity types.
        """
        # Build counterparty lookup
        enriched_counterparties = same_ref_counterparty.with_columns(
            [
                pl.lit(False).alias("counterparty_has_parent"),
                pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
                pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
                pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
                pl.lit(None).cast(pl.Int8).alias("cqs"),
                pl.lit(None).cast(pl.Float64).alias("pd"),
            ]
        )

        counterparty_lookup = CounterpartyLookup(
            counterparties=enriched_counterparties,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        )

        exposures, errors = resolver._unify_exposures(
            same_ref_loan,
            None,
            same_ref_facility,
            same_ref_mapping,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Check loan has parent facility reference set
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert loan_exp["exposure_has_parent"][0] is True
        assert loan_exp["parent_facility_reference"][0] == "REF001"

        # Facility undrawn SHOULD have parent_facility_reference set to its source facility
        # This enables facility-level collateral to be allocated to undrawn amounts
        undrawn_exp = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_exp["exposure_has_parent"][0] is True
        assert undrawn_exp["parent_facility_reference"][0] == "REF001"

    def test_full_resolve_with_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
        same_ref_counterparty: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Full resolve() should work correctly with same facility/loan reference."""
        bundle = RawDataBundle(
            facilities=same_ref_facility,
            loans=same_ref_loan,
            contingents=None,
            counterparties=same_ref_counterparty,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=same_ref_mapping,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have 2 exposures
        assert len(df) == 2

        # Check both exposure types are present
        exposure_types = set(df["exposure_type"].to_list())
        assert exposure_types == {"loan", "facility_undrawn"}

        # Verify loan details
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert loan_exp["exposure_reference"][0] == "REF001"
        assert loan_exp["drawn_amount"][0] == pytest.approx(600000.0)
        assert loan_exp["parent_facility_reference"][0] == "REF001"
        assert loan_exp["exposure_has_parent"][0] is True

        # Verify facility_undrawn details
        undrawn_exp = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_exp["exposure_reference"][0] == "REF001_UNDRAWN"
        assert undrawn_exp["undrawn_amount"][0] == pytest.approx(400000.0)
        assert undrawn_exp["nominal_amount"][0] == pytest.approx(400000.0)

    def test_multiple_loans_with_same_reference_pattern(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple facilities can each have loans with matching references.

        This tests that the pattern works for multiple independent facility-loan pairs.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_A", "FAC_B"],
                "product_type": ["RCF", "TERM"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP_A", "CP_B"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP", "GBP"],
                "limit": [500000.0, 800000.0],
                "lgd": [0.45, 0.45],
                "seniority": ["senior", "senior"],
                "risk_type": ["MR", "MR"],
            }
        ).lazy()

        # Loans with SAME references as their parent facilities
        loans = pl.DataFrame(
            {
                "loan_reference": ["FAC_A", "FAC_B"],  # Same as facility references
                "product_type": ["TERM_LOAN", "TERM_LOAN"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP_A", "CP_B"],
                "value_date": [date(2023, 6, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP", "GBP"],
                "drawn_amount": [300000.0, 500000.0],
                "lgd": [0.45, 0.45],
                "seniority": ["senior", "senior"],
            }
        ).lazy()

        # Mappings where parent = child reference
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_A", "FAC_B"],
                "child_reference": ["FAC_A", "FAC_B"],
                "child_type": ["loan", "loan"],
            }
        ).lazy()

        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_A", "CP_B"],
                "counterparty_name": ["Corp A", "Corp B"],
                "entity_type": ["corporate", "corporate"],
                "country_code": ["GB", "GB"],
                "annual_revenue": [50000000.0, 60000000.0],
                "total_assets": [100000000.0, 120000000.0],
                "default_status": [False, False],
                "sector_code": ["MANU", "MANU"],
                "apply_fi_scalar": [True, True],
                "is_managed_as_retail": [False, False],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have 4 exposures: 2 loans + 2 facility_undrawn
        assert len(df) == 4

        # Check loan exposures
        loans_df = df.filter(pl.col("exposure_type") == "loan").sort("exposure_reference")
        assert loans_df["exposure_reference"].to_list() == ["FAC_A", "FAC_B"]
        assert loans_df["parent_facility_reference"].to_list() == ["FAC_A", "FAC_B"]

        # Check facility_undrawn exposures
        undrawn_df = df.filter(pl.col("exposure_type") == "facility_undrawn").sort(
            "exposure_reference"
        )
        assert undrawn_df["exposure_reference"].to_list() == ["FAC_A_UNDRAWN", "FAC_B_UNDRAWN"]

        # Verify undrawn amounts
        fac_a_undrawn = undrawn_df.filter(pl.col("exposure_reference") == "FAC_A_UNDRAWN")
        assert fac_a_undrawn["undrawn_amount"][0] == pytest.approx(200000.0)  # 500k - 300k

        fac_b_undrawn = undrawn_df.filter(pl.col("exposure_reference") == "FAC_B_UNDRAWN")
        assert fac_b_undrawn["undrawn_amount"][0] == pytest.approx(300000.0)  # 800k - 500k

    def test_same_ref_with_sub_facility_no_row_duplication(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Loan should not be duplicated when sub-facility shares the same reference.

        Scenario:
            FAC_PARENT (parent facility, limit=2M)
              |-- SUB001 (child_type="facility")   <- sub-facility
              |-- SUB001 (child_type="loan")       <- loan with same ref

        facility_mappings has TWO rows with child_reference="SUB001".
        Without the fix, the left join in _unify_exposures produces a cartesian
        product, duplicating the loan exposure row.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_PARENT"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_SUB"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [2000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["SUB001"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_SUB"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        # Two rows for SUB001: one as a sub-facility, one as a loan
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_PARENT", "FAC_PARENT"],
                "child_reference": ["SUB001", "SUB001"],
                "child_type": ["facility", "loan"],
            }
        ).lazy()

        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_SUB"],
                "counterparty_name": ["Sub-Facility Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [50000000.0],
                "total_assets": [100000000.0],
                "default_status": [False],
                "sector_code": ["MANU"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Loan SUB001 should appear exactly once (not duplicated by the facility mapping row)
        loan_rows = df.filter(
            (pl.col("exposure_type") == "loan") & (pl.col("exposure_reference") == "SUB001")
        )
        assert len(loan_rows) == 1, (
            f"Expected 1 loan row for SUB001, got {len(loan_rows)}. "
            f"Facility mapping join likely caused duplication."
        )

    def test_same_reference_fully_drawn_no_undrawn_exposure(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """When facility is fully drawn, only loan exposure should exist."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FULL_DRAW"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_FULL"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        # Loan with same reference, fully drawn
        loans = pl.DataFrame(
            {
                "loan_reference": ["FULL_DRAW"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_FULL"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],  # Fully drawn = limit
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FULL_DRAW"],
                "child_reference": ["FULL_DRAW"],
                "child_type": ["loan"],
            }
        ).lazy()

        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_FULL"],
                "counterparty_name": ["Fully Drawn Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [50000000.0],
                "total_assets": [100000000.0],
                "default_status": [False],
                "sector_code": ["MANU"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have only 1 exposure: the loan (no undrawn since fully drawn)
        assert len(df) == 1
        assert df["exposure_type"][0] == "loan"
        assert df["exposure_reference"][0] == "FULL_DRAW"
        assert df["drawn_amount"][0] == pytest.approx(500000.0)


# =============================================================================
# Lending Group Duplicate Membership Tests
# =============================================================================


class TestLendingGroupDuplicateMembership:
    """Tests for lending group duplication when counterparty appears in multiple groups.

    Bug 2: When a counterparty appears in multiple lending groups or as both
    a parent and child across groups, the pl.concat of lending_groups and
    parent_as_member can produce duplicate member_counterparty_reference entries,
    causing row duplication when joined to exposures.
    """

    def _build_counterparty_lookup(self, counterparties: pl.LazyFrame) -> CounterpartyLookup:
        """Helper to build a minimal counterparty lookup for lending group tests."""
        enriched = counterparties.with_columns(
            [
                pl.lit(False).alias("counterparty_has_parent"),
                pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
                pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
                pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
                pl.lit(None).cast(pl.Int8).alias("cqs"),
                pl.lit(None).cast(pl.Float64).alias("pd"),
            ]
        )
        return CounterpartyLookup(
            counterparties=enriched,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        )

    def test_counterparty_in_multiple_groups_no_row_duplication(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Counterparty in multiple lending groups should not duplicate exposure rows.

        Scenario:
            LG_A -> SHARED_CP (child)
            LG_B -> SHARED_CP (child)

        SHARED_CP appears in all_members twice (once per group). Without the fix,
        joining exposures to all_members duplicates the loan row.
        """
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["LG_A", "LG_B", "SHARED_CP"],
                "counterparty_name": ["Group A", "Group B", "Shared CP"],
                "entity_type": ["individual", "individual", "individual"],
                "country_code": ["GB", "GB", "GB"],
                "annual_revenue": [0.0, 0.0, 0.0],
                "total_assets": [0.0, 0.0, 0.0],
                "default_status": [False, False, False],
                "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
                "apply_fi_scalar": [True, True, True],
                "is_managed_as_retail": [False, False, False],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_SHARED"],
                "product_type": ["PERSONAL"],
                "book_code": ["RETAIL"],
                "counterparty_reference": ["SHARED_CP"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        lending_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["LG_A", "LG_B"],
                "child_counterparty_reference": ["SHARED_CP", "SHARED_CP"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=None,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=lending_mappings,
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # SHARED_CP's loan should appear exactly once
        loan_rows = df.filter(pl.col("exposure_reference") == "LOAN_SHARED")
        assert len(loan_rows) == 1, (
            f"Expected 1 row for LOAN_SHARED, got {len(loan_rows)}. "
            f"Lending group join likely caused duplication."
        )

    def test_counterparty_as_parent_and_child_in_different_group(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Counterparty that is both a child in one group and parent of another.

        Scenario:
            LG_A -> CP_DUAL (child)
            CP_DUAL -> CP_OTHER (parent of its own group)

        CP_DUAL appears in all_members twice: once from lending_groups (as child of
        LG_A) and once from parent_as_member (as parent of the CP_DUAL group).
        Without the fix, LOAN_DUAL is duplicated.
        """
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["LG_A", "CP_DUAL", "CP_OTHER"],
                "counterparty_name": ["Group A", "Dual Role CP", "Other CP"],
                "entity_type": ["individual", "individual", "individual"],
                "country_code": ["GB", "GB", "GB"],
                "annual_revenue": [0.0, 0.0, 0.0],
                "total_assets": [0.0, 0.0, 0.0],
                "default_status": [False, False, False],
                "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
                "apply_fi_scalar": [True, True, True],
                "is_managed_as_retail": [False, False, False],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_DUAL", "LOAN_OTHER"],
                "product_type": ["PERSONAL", "PERSONAL"],
                "book_code": ["RETAIL", "RETAIL"],
                "counterparty_reference": ["CP_DUAL", "CP_OTHER"],
                "value_date": [date(2023, 1, 1), date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
                "currency": ["GBP", "GBP"],
                "drawn_amount": [200000.0, 150000.0],
                "lgd": [0.45, 0.45],
                "seniority": ["senior", "senior"],
            }
        ).lazy()

        # CP_DUAL is a child of LG_A, AND CP_DUAL is a parent of CP_OTHER
        lending_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["LG_A", "CP_DUAL"],
                "child_counterparty_reference": ["CP_DUAL", "CP_OTHER"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=None,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=lending_mappings,
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # LOAN_DUAL should appear exactly once
        dual_rows = df.filter(pl.col("exposure_reference") == "LOAN_DUAL")
        assert len(dual_rows) == 1, (
            f"Expected 1 row for LOAN_DUAL, got {len(dual_rows)}. "
            f"Lending group parent_as_member caused duplication."
        )

        # Total should be 2 rows (LOAN_DUAL + LOAN_OTHER)
        assert len(df) == 2, f"Expected 2 total rows, got {len(df)}."


class TestNegativeDrawnAmountInHierarchy:
    """Tests for negative drawn amounts in hierarchy calculations.

    Credit balances (negative drawn) should not reduce exposure totals
    used in property coverage or lending group calculations.
    """

    def test_negative_drawn_property_coverage(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """total_exposure_amount in property coverage should floor at 0."""
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP001"],
                "counterparty_name": ["Test"],
                "entity_type": ["individual"],
                "country_code": ["GB"],
                "annual_revenue": [0.0],
                "total_assets": [0.0],
                "default_status": [False],
                "sector_code": ["RETAIL"],
                "is_financial_institution": [False],
                "apply_fi_scalar": [True],
                "is_pse": [False],
                "is_mdb": [False],
                "is_international_org": [False],
                "is_central_counterparty": [False],
                "is_regional_govt_local_auth": [False],
                "is_managed_as_retail": [False],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_NEG"],
                "product_type": ["MORTGAGE"],
                "book_code": ["RETAIL"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [-50000.0],
                "lgd": [0.15],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["FR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [None],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=loans,
            contingents=pl.LazyFrame(
                schema={
                    "contingent_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "nominal_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            counterparties=counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        result = resolver.resolve(bundle, config)
        df = result.exposures.collect()
        row = df.filter(pl.col("exposure_reference") == "LOAN_NEG")

        # total_exposure_amount should be 0, not -50000
        assert row["exposure_for_retail_threshold"][0] >= 0.0

    def test_negative_drawn_lending_group_totals(
        self,
        resolver: HierarchyResolver,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """Lending group totals should floor negative drawn amounts at 0."""
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2"],
                "counterparty_name": ["Anchor", "Member 1", "Member 2"],
                "entity_type": ["individual", "individual", "corporate"],
                "country_code": ["GB", "GB", "GB"],
                "annual_revenue": [0.0, 0.0, 500000.0],
                "total_assets": [0.0, 0.0, 1000000.0],
                "default_status": [False, False, False],
                "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
                "is_financial_institution": [False, False, False],
                "apply_fi_scalar": [True, True, True],
                "is_pse": [False, False, False],
                "is_mdb": [False, False, False],
                "is_international_org": [False, False, False],
                "is_central_counterparty": [False, False, False],
                "is_regional_govt_local_auth": [False, False, False],
                "is_managed_as_retail": [False, False, False],
            }
        ).lazy()

        # Member1 has negative drawn (credit balance on current account)
        loans = pl.DataFrame(
            {
                "loan_reference": ["LG_LOAN1", "LG_LOAN2", "LG_LOAN3"],
                "product_type": ["MORTGAGE", "PERSONAL", "BUSINESS"],
                "book_code": ["RETAIL", "RETAIL", "RETAIL"],
                "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2"],
                "value_date": [date(2023, 1, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP", "GBP", "GBP"],
                "drawn_amount": [300000.0, -50000.0, 400000.0],
                "lgd": [0.15, 0.45, 0.45],
                "beel": [0.01, 0.01, 0.01],
                "seniority": ["senior", "senior", "senior"],
                "risk_type": ["FR", "FR", "FR"],
                "ccf_modelled": [None, None, None],
                "is_short_term_trade_lc": [None, None, None],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=loans,
            contingents=pl.LazyFrame(
                schema={
                    "contingent_reference": pl.String,
                    "product_type": pl.String,
                    "book_code": pl.String,
                    "counterparty_reference": pl.String,
                    "value_date": pl.Date,
                    "maturity_date": pl.Date,
                    "currency": pl.String,
                    "nominal_amount": pl.Float64,
                    "lgd": pl.Float64,
                    "beel": pl.Float64,
                    "seniority": pl.String,
                    "risk_type": pl.String,
                    "ccf_modelled": pl.Float64,
                    "is_short_term_trade_lc": pl.Boolean,
                }
            ),
            counterparties=counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=None,
            lending_mappings=lending_group_mappings,
        )
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        result = resolver.resolve(bundle, config)
        df = result.lending_group_totals.collect()

        # total_drawn should floor the -50k at 0: 300k + 0 + 400k = 700k
        assert df["total_drawn"][0] == pytest.approx(700000.0)
        # total_exposure should also floor: (300k+0) + (0+0) + (400k+0) = 700k
        assert df["total_exposure"][0] == pytest.approx(700000.0)


# =============================================================================
# Duplicate Mapping Bug Fix Tests
# =============================================================================


class TestDuplicateMappingBugFixes:
    """Tests for bugs where duplicate facility_mappings rows cause:
    - Drawn total inflation (Bug 1) — silently drops facility_undrawn
    - Row duplication in _unify_exposures (Bug 2)
    - Missing type column fallback crash (Bug 3)
    """

    def test_duplicate_loan_mappings_do_not_inflate_drawn_total(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Duplicate (child_reference, parent_facility_reference) pairs in
        facility_mappings must not double-count drawn amounts.

        1 facility (limit=1M), 1 loan (drawn=600k), duplicate mapping row.
        Without the fix: total_drawn=1.2M, undrawn=0, facility silently dropped.
        With the fix: total_drawn=600k, undrawn=400k.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_DUP"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_DUP"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_DUP"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_DUP"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [600000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        # Duplicate mapping row for the same loan → facility link
        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_DUP", "FAC_DUP"],
                "child_reference": ["LOAN_DUP", "LOAN_DUP"],
                "child_type": ["loan", "loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        # Should produce 1 undrawn row with correct amount
        fac = df.filter(pl.col("exposure_reference") == "FAC_DUP_UNDRAWN")
        assert len(fac) == 1, (
            f"Expected 1 facility_undrawn row, got {len(fac)}. "
            f"Duplicate mappings likely inflated drawn total."
        )
        assert fac["undrawn_amount"][0] == pytest.approx(400000.0)  # 1M - 600k

    def test_duplicate_exposure_mappings_do_not_duplicate_rows(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Duplicate child_reference rows in facility_mappings must not
        duplicate exposure rows in _unify_exposures.

        1 facility, 1 loan, duplicate mapping row.
        Without the fix: loan appears twice, total rows = 3.
        With the fix: loan appears once, total rows = 2 (loan + facility_undrawn).
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_EXPDUP"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_EXPDUP"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [600000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        # Duplicate mapping: same child_reference appears twice
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_EXPDUP", "FAC_EXPDUP"],
                "child_reference": ["LOAN_EXPDUP", "LOAN_EXPDUP"],
                "child_type": ["loan", "loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,
            facilities,
            facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Loan should appear exactly once
        loan_rows = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_rows) == 1, (
            f"Expected 1 loan row, got {len(loan_rows)}. "
            f"Duplicate mapping rows caused row duplication in _unify_exposures."
        )

        # Total rows = loan + facility_undrawn
        assert len(df) == 2

    def test_facility_undrawn_with_no_type_column(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """facility_mappings with neither child_type nor node_type column.

        Post-normalisation contract: the resolver boundary synthesises a null
        ``child_type`` column for legacy mappings via ``_normalise_facility_mappings``.
        Null ``child_type`` is treated as "no children of any type", so loan
        aggregation does not run and the facility's undrawn equals its full limit.

        The right fix in production data is to emit ``child_type='loan'`` on
        loan mappings — once specified, aggregation works (covered by
        ``test_facility_undrawn_with_explicit_loan_type`` below).
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_NOTYPE"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_NOTYPE"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_NOTYPE"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_NOTYPE"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [300000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        # No child_type column at all — post-normalisation, synthesised null
        # blocks the loan aggregation path.
        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_NOTYPE"],
                "child_reference": ["LOAN_NOTYPE"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        fac = df.filter(pl.col("exposure_reference") == "FAC_NOTYPE_UNDRAWN")
        assert len(fac) == 1
        # Without explicit child_type='loan', loan is not aggregated; full limit is undrawn.
        assert fac["undrawn_amount"][0] == pytest.approx(1000000.0)

    def test_facility_undrawn_with_explicit_loan_type(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Same input as the no-type-column test, but with the canonical child_type='loan'.

        Confirms that once the input shape matches the post-normalisation contract,
        loan drawn amounts are aggregated against the facility's limit and the
        undrawn equals limit minus drawn.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_TYPED"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_TYPED"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_TYPED"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_TYPED"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [300000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_TYPED"],
                "child_reference": ["LOAN_TYPED"],
                "child_type": ["loan"],
            }
        ).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(facilities, loans, None, mappings)
        df = facility_undrawn.collect()

        fac = df.filter(pl.col("exposure_reference") == "FAC_TYPED_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(700000.0)  # 1M - 300k


class TestLargerDatasetFacilityUndrawn:
    """Integration test: facility_undrawn survives in a multi-group dataset
    with org hierarchy, lending groups, and duplicate mappings.
    """

    def test_facility_undrawn_survives_in_multi_group_dataset(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """All facility_undrawn rows should be present with correct amounts
        in a realistic dataset with:
        - 4 counterparties in org hierarchy
        - 3 facilities with undrawn headroom
        - 4 loans
        - Lending groups
        - Duplicate mapping rows
        """
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_PAR", "CP_CH1", "CP_CH2", "CP_CH3"],
                "counterparty_name": ["Parent Corp", "Child 1", "Child 2", "Child 3"],
                "entity_type": ["corporate", "corporate", "corporate", "corporate"],
                "country_code": ["GB", "GB", "GB", "GB"],
                "annual_revenue": [100e6, 20e6, 30e6, 15e6],
                "total_assets": [500e6, 100e6, 150e6, 75e6],
                "default_status": [False, False, False, False],
                "sector_code": ["MANU", "MANU", "MANU", "MANU"],
                "is_financial_institution": [False, False, False, False],
                "apply_fi_scalar": [True, True, True, True],
                "is_pse": [False, False, False, False],
                "is_mdb": [False, False, False, False],
                "is_international_org": [False, False, False, False],
                "is_central_counterparty": [False, False, False, False],
                "is_regional_govt_local_auth": [False, False, False, False],
                "is_managed_as_retail": [False, False, False, False],
            }
        ).lazy()

        org_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["CP_PAR", "CP_PAR", "CP_PAR"],
                "child_counterparty_reference": ["CP_CH1", "CP_CH2", "CP_CH3"],
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_A", "FAC_B", "FAC_C"],
                "product_type": ["RCF", "RCF", "TERM"],
                "book_code": ["CORP", "CORP", "CORP"],
                "counterparty_reference": ["CP_CH1", "CP_CH2", "CP_CH3"],
                "value_date": [date(2023, 1, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [2000000.0, 1500000.0, 800000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR", "MR", "MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LN_1", "LN_2", "LN_3", "LN_4"],
                "product_type": ["TERM_LOAN"] * 4,
                "book_code": ["CORP"] * 4,
                "counterparty_reference": ["CP_CH1", "CP_CH1", "CP_CH2", "CP_CH3"],
                "value_date": [date(2023, 6, 1)] * 4,
                "maturity_date": [date(2028, 1, 1)] * 4,
                "currency": ["GBP"] * 4,
                "drawn_amount": [800000.0, 400000.0, 1000000.0, 300000.0],
                "lgd": [0.45] * 4,
                "seniority": ["senior"] * 4,
            }
        ).lazy()

        # Duplicate mapping rows for LN_1 (simulating real-world data issue)
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": [
                    "FAC_A",
                    "FAC_A",
                    "FAC_A",  # LN_1 duplicate + LN_2
                    "FAC_B",  # LN_3
                    "FAC_C",  # LN_4
                ],
                "child_reference": [
                    "LN_1",
                    "LN_1",
                    "LN_2",  # LN_1 appears twice
                    "LN_3",
                    "LN_4",
                ],
                "child_type": ["loan", "loan", "loan", "loan", "loan"],
            }
        ).lazy()

        lending_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["LG_01", "LG_01"],
                "child_counterparty_reference": ["CP_CH1", "CP_CH2"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=org_mappings,
            lending_mappings=lending_mappings,
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # All 3 facility_undrawn rows must be present
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn").sort(
            "exposure_reference"
        )
        assert len(undrawn) == 3, (
            f"Expected 3 facility_undrawn rows, got {len(undrawn)}. "
            f"Refs present: {undrawn['exposure_reference'].to_list()}"
        )

        # FAC_A: limit=2M, drawn=800k+400k=1.2M, undrawn=800k
        fac_a = undrawn.filter(pl.col("exposure_reference") == "FAC_A_UNDRAWN")
        assert fac_a["undrawn_amount"][0] == pytest.approx(800000.0)

        # FAC_B: limit=1.5M, drawn=1M, undrawn=500k
        fac_b = undrawn.filter(pl.col("exposure_reference") == "FAC_B_UNDRAWN")
        assert fac_b["undrawn_amount"][0] == pytest.approx(500000.0)

        # FAC_C: limit=800k, drawn=300k, undrawn=500k
        fac_c = undrawn.filter(pl.col("exposure_reference") == "FAC_C_UNDRAWN")
        assert fac_c["undrawn_amount"][0] == pytest.approx(500000.0)

        # 4 loan rows should not be duplicated
        loan_rows = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_rows) == 4, (
            f"Expected 4 loan rows, got {len(loan_rows)}. "
            f"Duplicate mappings caused loan row duplication."
        )


# =============================================================================
# Facility Root Lookup Tests (multi-level facility hierarchy)
# =============================================================================


class TestBuildFacilityRootLookup:
    """Tests for _build_facility_root_lookup method."""

    def test_single_level_returns_parent_as_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Sub-facility → parent: root = parent, depth = 1."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_PARENT"],
                "child_reference": ["FAC_CHILD"],
                "child_type": ["facility"],
            }
        ).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["child_facility_reference"] == "FAC_CHILD"
        assert row["root_facility_reference"] == "FAC_PARENT"
        assert row["facility_hierarchy_depth"] == 1

    def test_two_level_hierarchy_resolves_to_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """sub2 → sub1 → root: root = root, depth = 2."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT", "FAC_SUB1"],
                "child_reference": ["FAC_SUB1", "FAC_SUB2"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        # Both sub1 and sub2 should be in lookup
        assert len(df) == 2

        sub1 = df.filter(pl.col("child_facility_reference") == "FAC_SUB1")
        assert sub1["root_facility_reference"][0] == "FAC_ROOT"
        assert sub1["facility_hierarchy_depth"][0] == 1

        sub2 = df.filter(pl.col("child_facility_reference") == "FAC_SUB2")
        assert sub2["root_facility_reference"][0] == "FAC_ROOT"
        assert sub2["facility_hierarchy_depth"][0] == 2

    def test_multiple_branches_same_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Two sub-facilities under one parent both resolve to same root."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT", "FAC_ROOT"],
                "child_reference": ["SUB_A", "SUB_B"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 2
        roots = df["root_facility_reference"].unique().to_list()
        assert roots == ["FAC_ROOT"]

    def test_no_facility_type_column_returns_empty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """No child_type column → cannot detect sub-facilities, return empty.

        Post-normalisation, ``_normalise_facility_mappings`` synthesises a null
        ``child_type``; the downstream filter (``== "facility"``) yields zero
        rows, ``facility_edges`` is empty, and the empty-result short-circuit
        fires.
        """
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT"],
                "child_reference": ["SUB_A"],
            }
        ).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 0

    def test_empty_mappings(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Empty facility mappings → empty lookup."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 0


class TestBuildFacilityAncestorClosure:
    """Tests for _build_facility_ancestor_closure (multi-level collateral cascade)."""

    def test_single_level_closure_includes_self_and_parent(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Sub-facility → parent: ancestors = [self, parent]."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_PARENT"],
                "child_reference": ["FAC_CHILD"],
                "child_type": ["facility"],
            }
        ).lazy()

        df = resolver._build_facility_ancestor_closure(facility_mappings).collect()

        row = df.filter(pl.col("child_facility_reference") == "FAC_CHILD")
        assert sorted(row["ancestor_facilities"][0].to_list()) == ["FAC_CHILD", "FAC_PARENT"]

    def test_two_level_closure_includes_all_ancestors(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """sub2 → sub1 → root: sub2 ancestors = [sub2, sub1, root]."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT", "FAC_SUB1"],
                "child_reference": ["FAC_SUB1", "FAC_SUB2"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        df = resolver._build_facility_ancestor_closure(facility_mappings).collect()

        sub2 = df.filter(pl.col("child_facility_reference") == "FAC_SUB2")
        assert sorted(sub2["ancestor_facilities"][0].to_list()) == [
            "FAC_ROOT",
            "FAC_SUB1",
            "FAC_SUB2",
        ]
        sub1 = df.filter(pl.col("child_facility_reference") == "FAC_SUB1")
        assert sorted(sub1["ancestor_facilities"][0].to_list()) == ["FAC_ROOT", "FAC_SUB1"]

    def test_no_facility_type_returns_empty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """No facility-typed children → empty closure (single-level fallback used)."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT"],
                "child_reference": ["SUB_A"],
            }
        ).lazy()

        df = resolver._build_facility_ancestor_closure(facility_mappings).collect()

        assert len(df) == 0

    def test_empty_mappings_returns_empty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Empty facility mappings → empty closure."""
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        df = resolver._build_facility_ancestor_closure(facility_mappings).collect()

        assert len(df) == 0


class TestMultiLevelFacilityUndrawn:
    """Tests for multi-level facility undrawn aggregation."""

    def test_multi_level_undrawn_aggregates_to_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """MOF parent (limit=2M) with two sub-facilities containing loans.

        FAC_PARENT (limit=2M, MR)
        ├── SUB001 (limit=1M, MR) → LOAN01 (drawn=0.5M)
        └── SUB002 (limit=0.5M, MR) → LOAN02 (drawn=0.25M)

        Waterfall split: SUB001 row £500k (sub headroom), SUB002 row £250k,
        residual £500k at parent's MR. Total off-balance = 1.25M.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_PARENT", "SUB001", "SUB002"],
                "product_type": ["RCF", "RCF", "RCF"],
                "book_code": ["CORP", "CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [2000000.0, 1000000.0, 500000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR"] * 3,
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01", "LOAN02"],
                "product_type": ["TERM_LOAN", "TERM_LOAN"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 6, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "drawn_amount": [500000.0, 250000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
            }
        ).lazy()

        # Mappings: sub-facilities under parent, loans under sub-facilities
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": [
                    "FAC_PARENT",
                    "FAC_PARENT",  # sub-facilities under parent
                    "SUB001",
                    "SUB002",  # loans under sub-facilities
                ],
                "child_reference": [
                    "SUB001",
                    "SUB002",
                    "LOAN01",
                    "LOAN02",
                ],
                "child_type": [
                    "facility",
                    "facility",
                    "loan",
                    "loan",
                ],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # Sub-facilities still don't emit standalone undrawn rows
        sub_refs = df["exposure_reference"].to_list()
        assert "SUB001_UNDRAWN" not in sub_refs
        assert "SUB002_UNDRAWN" not in sub_refs

        # MOF parent emits multiple split rows summing to parent headroom
        rows = df.filter(pl.col("source_facility_reference") == "FAC_PARENT")
        assert len(rows) == 3  # SUB001, SUB002, residual
        assert float(rows["undrawn_amount"].sum()) == pytest.approx(1_250_000.0)

    def test_sub_facilities_excluded_from_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Sub-facilities should NOT produce their own undrawn exposures."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_PARENT", "SUB001"],
                "product_type": ["RCF", "RCF"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "limit": [2000000.0, 1000000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
                "risk_type": ["MR"] * 2,
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_PARENT", "SUB001"],
                "child_reference": ["SUB001", "LOAN01"],
                "child_type": ["facility", "loan"],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # SUB001 should NOT have its own undrawn exposure
        sub_undrawn = df.filter(pl.col("exposure_reference") == "SUB001_UNDRAWN")
        assert len(sub_undrawn) == 0

        # MOF parent emits split rows under source_facility_reference = FAC_PARENT.
        # SUB001 (MR 50%, headroom £500k) fills first; residual £1m at parent's MR.
        rows = df.filter(pl.col("source_facility_reference") == "FAC_PARENT")
        assert float(rows["undrawn_amount"].sum()) == pytest.approx(1_500_000.0)

    def test_single_level_undrawn_unchanged(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """No regression: simple facility→loan (no sub-facilities) still works."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC001"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [600000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC001"],
                "child_reference": ["LOAN01"],
                "child_type": ["loan"],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        assert len(df) == 1
        assert df["exposure_reference"][0] == "FAC001_UNDRAWN"
        assert df["undrawn_amount"][0] == pytest.approx(400000.0)


class TestMultiLevelUnifyExposures:
    """Integration tests for multi-level facility hierarchy in _unify_exposures."""

    def test_multi_level_root_facility_reference_correct(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loan under sub-facility gets root = parent facility."""
        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_ROOT", "SUB001"],
                "product_type": ["RCF", "RCF"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "limit": [2000000.0, 1000000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
                "risk_type": ["MR"] * 2,
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT", "SUB001"],
                "child_reference": ["SUB001", "LOAN01"],
                "child_type": ["facility", "loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,
            facilities,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        # Loan's root_facility_reference should be the ultimate root
        loan_row = df.filter(pl.col("exposure_reference") == "LOAN01")
        assert loan_row["root_facility_reference"][0] == "FAC_ROOT"

    def test_multi_level_facility_hierarchy_depth_correct(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loan under sub-facility → depth=2 for two-level hierarchy."""
        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_ROOT", "SUB001"],
                "product_type": ["RCF", "RCF"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "limit": [2000000.0, 1000000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
                "risk_type": ["MR"] * 2,
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_ROOT", "SUB001"],
                "child_reference": ["SUB001", "LOAN01"],
                "child_type": ["facility", "loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,
            facilities,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        # Loan under sub-facility should have depth 2
        loan_row = df.filter(pl.col("exposure_reference") == "LOAN01")
        assert loan_row["facility_hierarchy_depth"][0] == 2

    def test_standalone_loan_depth_is_zero(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loan with no facility parent gets depth=0."""
        loans = pl.DataFrame(
            {
                "loan_reference": ["STANDALONE_LOAN"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,
            None,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        loan_row = df.filter(pl.col("exposure_reference") == "STANDALONE_LOAN")
        assert loan_row["facility_hierarchy_depth"][0] == 0
        assert loan_row["root_facility_reference"][0] is None


# =============================================================================
# Contingent in Facility Undrawn Calculation Tests
# =============================================================================


class TestContingentInFacilityUndrawn:
    """Tests for including contingents in facility undrawn calculations.

    Contingents mapped to a facility consume headroom and should reduce
    the facility's undrawn amount. Additionally, drawn contingents (ONB)
    should be treated as on-balance-sheet items in unified exposures.
    """

    def test_contingent_reduces_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """OFB contingent nominal_amount should reduce parent facility undrawn.

        FAC001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (OFB, nominal=0.1M)
        Expected undrawn: 1M - 0.5M - 0.1M = 0.4M
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC001"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01"],
                "product_type": ["FINANCIAL_GUARANTEE"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "bs_type": ["OFB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC001", "FAC001"],
                "child_reference": ["LOAN01", "CONT01"],
                "child_type": ["loan", "contingent"],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(400000.0)

    def test_drawn_contingent_reduces_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """ONB (drawn) contingent nominal_amount should also reduce facility undrawn.

        FAC001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (ONB, nominal=0.25M)
        Expected undrawn: 1M - 0.5M - 0.25M = 0.25M
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC001"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01"],
                "product_type": ["FINANCIAL_GUARANTEE"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [250000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "bs_type": ["ONB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC001", "FAC001"],
                "child_reference": ["LOAN01", "CONT01"],
                "child_type": ["loan", "contingent"],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(250000.0)

    def test_drawn_contingent_has_drawn_amount(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """ONB contingent in unified exposures should have drawn_amount = nominal, nominal = 0."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2026, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01"],
                "product_type": ["FINANCIAL_GUARANTEE"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [250000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "bs_type": ["ONB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        exposures, _ = resolver._unify_exposures(
            loans,
            contingents,
            None,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert len(cont) == 1
        assert cont["drawn_amount"][0] == pytest.approx(250000.0)
        assert cont["nominal_amount"][0] == pytest.approx(0.0)

    def test_undrawn_contingent_preserves_current_behaviour(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """OFB contingent retains current behaviour: drawn=0, nominal=X, CCF fields preserved."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2026, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01"],
                "product_type": ["LETTER_OF_CREDIT"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [0.75],
                "is_short_term_trade_lc": [True],
                "bs_type": ["OFB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        exposures, _ = resolver._unify_exposures(
            loans,
            contingents,
            None,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert len(cont) == 1
        assert cont["drawn_amount"][0] == pytest.approx(0.0)
        assert cont["nominal_amount"][0] == pytest.approx(100000.0)
        assert cont["risk_type"][0] == "MR"
        assert cont["ccf_modelled"][0] == pytest.approx(0.75)
        assert cont["is_short_term_trade_lc"][0] is True

    def test_drawn_contingent_nullifies_ccf_fields(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """ONB contingent should have null risk_type, ccf_modelled, is_short_term_trade_lc."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2026, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01"],
                "product_type": ["FINANCIAL_GUARANTEE"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [250000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [0.5],
                "is_short_term_trade_lc": [True],
                "bs_type": ["ONB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        exposures, _ = resolver._unify_exposures(
            loans,
            contingents,
            None,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert cont["risk_type"][0] is None
        assert cont["ccf_modelled"][0] is None
        assert cont["is_short_term_trade_lc"][0] is None

    def test_bs_type_defaults_to_ofb(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Contingent without bs_type should behave as OFB (current default behaviour)."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2026, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
            }
        ).lazy()

        # No bs_type column at all
        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01"],
                "product_type": ["FINANCIAL_GUARANTEE"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP002"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2025, 1, 1)],
                "currency": ["GBP"],
                "nominal_amount": [100000.0],
                "lgd": [0.45],
                "beel": [0.01],
                "seniority": ["senior"],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": pl.Series([], dtype=pl.String),
                "child_reference": pl.Series([], dtype=pl.String),
                "child_type": pl.Series([], dtype=pl.String),
            }
        ).lazy()

        exposures, _ = resolver._unify_exposures(
            loans,
            contingents,
            None,
            facility_mappings,
            counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert cont["drawn_amount"][0] == pytest.approx(0.0)
        assert cont["nominal_amount"][0] == pytest.approx(100000.0)
        assert cont["risk_type"][0] == "MR"

    def test_mixed_loans_and_contingents_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Full scenario: loans + drawn + undrawn contingents under facility.

        FAC001 (limit=1M)
        ├── LOAN01 (drawn=0.5M)
        ├── CONT01 (ONB, nominal=0.1M)  — drawn contingent
        └── CONT02 (OFB, nominal=0.2M)  — undrawn contingent

        Expected undrawn: 1M - 0.5M - 0.1M - 0.2M = 0.2M
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC001"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 1, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "limit": [1000000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01", "CONT02"],
                "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2025, 1, 1)] * 2,
                "currency": ["GBP", "GBP"],
                "nominal_amount": [100000.0, 200000.0],
                "lgd": [0.45, 0.45],
                "beel": [0.01, 0.01],
                "seniority": ["senior", "senior"],
                "risk_type": ["MR", "MR"],
                "ccf_modelled": [None, None],
                "is_short_term_trade_lc": [False, False],
                "bs_type": ["ONB", "OFB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC001", "FAC001", "FAC001"],
                "child_reference": ["LOAN01", "CONT01", "CONT02"],
                "child_type": ["loan", "contingent", "contingent"],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(200000.0)

    def test_multi_level_hierarchy_with_contingents(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Contingents under sub-facilities should roll up to root for undrawn calc.

        FAC_PARENT (limit=2M)
        ├── SUB001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (OFB, nominal=0.25M)
        └── SUB002 (limit=0.5M) → CONT02 (ONB, nominal=0.25M)

        Expected: FAC_PARENT undrawn = 2M - 0.5M - 0.25M - 0.25M = 1M
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_PARENT", "SUB001", "SUB002"],
                "product_type": ["RCF", "RCF", "RCF"],
                "book_code": ["CORP", "CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [2000000.0, 1000000.0, 500000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR"] * 3,
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP001"],
                "value_date": [date(2023, 6, 1)],
                "maturity_date": [date(2028, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [500000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01", "CONT02"],
                "product_type": ["LETTER_OF_CREDIT", "FINANCIAL_GUARANTEE"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2025, 1, 1)] * 2,
                "currency": ["GBP", "GBP"],
                "nominal_amount": [250000.0, 250000.0],
                "lgd": [0.45, 0.45],
                "beel": [0.01, 0.01],
                "seniority": ["senior", "senior"],
                "risk_type": ["MR", "MR"],
                "ccf_modelled": [None, None],
                "is_short_term_trade_lc": [False, False],
                "bs_type": ["OFB", "ONB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": [
                    "FAC_PARENT",
                    "FAC_PARENT",
                    "SUB001",
                    "SUB001",
                    "SUB002",
                ],
                "child_reference": [
                    "SUB001",
                    "SUB002",
                    "LOAN01",
                    "CONT01",
                    "CONT02",
                ],
                "child_type": [
                    "facility",
                    "facility",
                    "loan",
                    "contingent",
                    "contingent",
                ],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # MOF parent emits split rows summing to parent headroom
        rows = df.filter(pl.col("source_facility_reference") == "FAC_PARENT")
        assert float(rows["undrawn_amount"].sum()) == pytest.approx(1_000_000.0)

    def test_full_scenario_from_spec(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Full scenario from requirements.

        FAC_PARENT (limit=2M)
        ├── SUB001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (ONB, nominal=0.25M)
        └── SUB002 (limit=0.5M) → LOAN02 (drawn=0.25M) + CONT02 (OFB, nominal=0.25M)

        Total utilised: 0.5M + 0.25M + 0.25M + 0.25M = 1.25M
        Expected: FAC_PARENT undrawn = 2M - 1.25M = 0.75M
        Sub-facilities should not produce undrawn records.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_PARENT", "SUB001", "SUB002"],
                "product_type": ["RCF", "RCF", "RCF"],
                "book_code": ["CORP", "CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 3,
                "maturity_date": [date(2028, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [2000000.0, 1000000.0, 500000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR"] * 3,
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN01", "LOAN02"],
                "product_type": ["TERM_LOAN", "TERM_LOAN"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 6, 1)] * 2,
                "maturity_date": [date(2028, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "drawn_amount": [500000.0, 250000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
            }
        ).lazy()

        contingents = pl.DataFrame(
            {
                "contingent_reference": ["CONT01", "CONT02"],
                "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
                "book_code": ["CORP", "CORP"],
                "counterparty_reference": ["CP001", "CP001"],
                "value_date": [date(2023, 1, 1)] * 2,
                "maturity_date": [date(2025, 1, 1)] * 2,
                "currency": ["GBP", "GBP"],
                "nominal_amount": [250000.0, 250000.0],
                "lgd": [0.45, 0.45],
                "beel": [0.01, 0.01],
                "seniority": ["senior", "senior"],
                "risk_type": ["MR", "MR"],
                "ccf_modelled": [None, None],
                "is_short_term_trade_lc": [False, False],
                "bs_type": ["ONB", "OFB"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": [
                    "FAC_PARENT",
                    "FAC_PARENT",
                    "SUB001",
                    "SUB001",
                    "SUB002",
                    "SUB002",
                ],
                "child_reference": [
                    "SUB001",
                    "SUB002",
                    "LOAN01",
                    "CONT01",
                    "LOAN02",
                    "CONT02",
                ],
                "child_type": [
                    "facility",
                    "facility",
                    "loan",
                    "contingent",
                    "loan",
                    "contingent",
                ],
            }
        ).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # MOF parent emits split rows summing to parent headroom
        rows = df.filter(pl.col("source_facility_reference") == "FAC_PARENT")
        assert float(rows["undrawn_amount"].sum()) == pytest.approx(750_000.0)

        # Sub-facilities should NOT have undrawn records
        sub_refs = df["exposure_reference"].to_list()
        assert "SUB001_UNDRAWN" not in sub_refs


class TestMOFAndFacilityShare:
    """Tests for Multiple Option Facility (MOF) parent-CCF derivation and
    Facility Share riskiest-counterparty allocation."""

    def test_mof_waterfall_emits_one_row_per_sub(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """MOF parent emits one undrawn row per sub-facility, each with the sub's risk_type.

        Two sub-facilities, sub-limits sum equals parent limit, no draws → 2 rows
        with the sub's own risk_type and full sub-limit allocation. No residual.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["MOF", "SUB_FR", "SUB_MR"],
                "product_type": ["RCF", "RCF", "RCF"],
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_X"] * 3,
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [1_000_000.0, 600_000.0, 400_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                # Parent intentionally LR (0% CCF under CRR). The waterfall must
                # emit per-sub rows using the sub's own risk_type, not the parent's.
                "risk_type": ["LR", "FR", "MR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["MOF", "MOF"],
                "child_reference": ["SUB_FR", "SUB_MR"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        mof_rows = undrawn.filter(pl.col("source_facility_reference") == "MOF").sort(
            "exposure_reference"
        )
        assert len(mof_rows) == 2

        fr_row = mof_rows.filter(pl.col("mof_risk_type_source") == "SUB_FR")
        mr_row = mof_rows.filter(pl.col("mof_risk_type_source") == "SUB_MR")
        assert len(fr_row) == 1 and len(mr_row) == 1

        # FR sub fills first (100% > 50%), full sub-limit £600k
        assert fr_row["risk_type"][0] == "FR"
        assert fr_row["nominal_amount"][0] == pytest.approx(600_000.0)
        assert fr_row["exposure_reference"][0] == "MOF_UNDRAWN_SUB_FR"
        # MR sub fills second, remaining headroom £400k
        assert mr_row["risk_type"][0] == "MR"
        assert mr_row["nominal_amount"][0] == pytest.approx(400_000.0)
        assert mr_row["exposure_reference"][0] == "MOF_UNDRAWN_SUB_MR"

    def test_mof_waterfall_caps_at_parent_limit(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Sub-limits sum > parent limit — waterfall caps the lower-CCF row at residual headroom.

        User scenario: parent £100m, sub_01 £60m @ MR (50%) + sub_02 £60m @ MLR (20%).
        Sub-limits sum to £120m but parent caps at £100m → £60m @ MR + £40m @ MLR.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_01", "FAC_SUB_01", "FAC_SUB_02"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_X"] * 3,
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [100_000_000.0, 60_000_000.0, 60_000_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR", "MR", "MLR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_01", "FAC_01"],
                "child_reference": ["FAC_SUB_01", "FAC_SUB_02"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "FAC_01")
        assert len(rows) == 2

        sub01 = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_01")
        sub02 = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_02")

        # MR (50%) fills first up to its £60m limit
        assert sub01["risk_type"][0] == "MR"
        assert sub01["nominal_amount"][0] == pytest.approx(60_000_000.0)
        # MLR (20%) takes the remaining £40m of parent headroom (capped from £60m)
        assert sub02["risk_type"][0] == "MLR"
        assert sub02["nominal_amount"][0] == pytest.approx(40_000_000.0)
        # Total coverage = parent limit
        total_nominal = float(rows["nominal_amount"].sum())
        assert total_nominal == pytest.approx(100_000_000.0)

    def test_mof_waterfall_basel_3_1_ccf_table_used(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Under Basel 3.1, OC (40%) > LR (10%) — waterfall fills OC first."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["MOF_B31", "SUB_OC", "SUB_LR"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_X"] * 3,
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [1_000_000.0, 600_000.0, 400_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": [None, "OC", "LR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["MOF_B31", "MOF_B31"],
                "child_reference": ["SUB_OC", "SUB_LR"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        config_b31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
            config=config_b31,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "MOF_B31")
        assert len(rows) == 2
        oc_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_OC")
        lr_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_LR")
        # Basel 3.1: OC=40% beats LR=10% → OC fills first up to its £600k sub-limit
        assert oc_row["risk_type"][0] == "OC"
        assert oc_row["nominal_amount"][0] == pytest.approx(600_000.0)
        assert lr_row["risk_type"][0] == "LR"
        assert lr_row["nominal_amount"][0] == pytest.approx(400_000.0)

    def test_mof_waterfall_sub_drawn_nets_per_sub(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Drawn loans booked under a specific sub net only that sub's headroom.

        Parent £100m. Sub_01 £60m @ MR drawn £20m. Sub_02 £60m @ MLR drawn £10m.
        Per-sub headroom: sub_01 = £40m, sub_02 = £50m.
        Parent headroom = £70m. Waterfall: £40m @ MR, then £30m @ MLR.
        """
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_01", "FAC_SUB_01", "FAC_SUB_02"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_X"] * 3,
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [100_000_000.0, 60_000_000.0, 60_000_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR", "MR", "MLR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["L_A", "L_B"],
                "counterparty_reference": ["CP_X", "CP_X"],
                "drawn_amount": [20_000_000.0, 10_000_000.0],
                "currency": ["GBP"] * 2,
                "product_type": ["TERM_LOAN"] * 2,
                "book_code": ["CORP"] * 2,
                "value_date": [date(2024, 1, 1)] * 2,
                "maturity_date": [date(2027, 1, 1)] * 2,
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
            }
        ).lazy()

        # L_A under sub_01, L_B under sub_02
        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": [
                    "FAC_01",
                    "FAC_01",
                    "FAC_SUB_01",
                    "FAC_SUB_02",
                ],
                "child_reference": ["FAC_SUB_01", "FAC_SUB_02", "L_A", "L_B"],
                "child_type": ["facility", "facility", "loan", "loan"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "FAC_01")
        assert len(rows) == 2
        sub01 = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_01")
        sub02 = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_02")
        # MR fills first: sub_01 headroom £40m
        assert sub01["risk_type"][0] == "MR"
        assert sub01["nominal_amount"][0] == pytest.approx(40_000_000.0)
        # MLR fills second: parent headroom £70m - £40m = £30m
        assert sub02["risk_type"][0] == "MLR"
        assert sub02["nominal_amount"][0] == pytest.approx(30_000_000.0)

    def test_mof_waterfall_sub_fully_drawn_drops_out(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """A sub-facility fully drawn against its limit emits no undrawn row."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_01", "FAC_SUB_01", "FAC_SUB_02"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_X"] * 3,
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [100_000_000.0, 60_000_000.0, 40_000_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR", "MR", "MLR"],
            }
        ).lazy()

        # Sub_01 fully drawn (£60m drawn vs £60m limit). Sub_02 untouched.
        loans = pl.DataFrame(
            {
                "loan_reference": ["L_FULL"],
                "counterparty_reference": ["CP_X"],
                "drawn_amount": [60_000_000.0],
                "currency": ["GBP"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_01", "FAC_01", "FAC_SUB_01"],
                "child_reference": ["FAC_SUB_01", "FAC_SUB_02", "L_FULL"],
                "child_type": ["facility", "facility", "loan"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "FAC_01")
        # Only sub_02 emits a row — sub_01 has zero headroom.
        assert len(rows) == 1
        assert rows["mof_risk_type_source"][0] == "FAC_SUB_02"
        assert rows["risk_type"][0] == "MLR"
        # Parent headroom = £100m - £60m = £40m, fully absorbed by sub_02 (limit £40m)
        assert rows["nominal_amount"][0] == pytest.approx(40_000_000.0)

    def test_mof_waterfall_sub_limits_under_parent_emits_residual(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """When sub-limits sum below parent limit, residual headroom emits a parent-risk_type row."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_01", "FAC_SUB_01", "FAC_SUB_02"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_PARENT", "CP_X", "CP_X"],
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [100_000_000.0, 50_000_000.0, 30_000_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                # Parent's own risk_type FR (100%) drives the residual £20m row.
                "risk_type": ["FR", "MR", "MLR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_01", "FAC_01"],
                "child_reference": ["FAC_SUB_01", "FAC_SUB_02"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "FAC_01")
        # 2 sub rows + 1 residual row at parent's own risk_type.
        assert len(rows) == 3

        sub01 = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_01")
        sub02 = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_02")
        residual = rows.filter(pl.col("mof_risk_type_source").is_null())

        assert sub01["risk_type"][0] == "MR"
        assert sub01["nominal_amount"][0] == pytest.approx(50_000_000.0)
        assert sub02["risk_type"][0] == "MLR"
        assert sub02["nominal_amount"][0] == pytest.approx(30_000_000.0)
        # Residual £20m at parent's FR risk_type and parent's counterparty
        assert residual["risk_type"][0] == "FR"
        assert residual["nominal_amount"][0] == pytest.approx(20_000_000.0)
        assert residual["counterparty_reference"][0] == "CP_PARENT"

    def test_mof_waterfall_uncommitted_sub_skipped(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """An uncommitted (committed=False) sub-facility is skipped from the waterfall.

        The bank can refuse to lend on an unconditionally cancellable sub, so it
        carries no commitment EAD and must not consume parent headroom — the
        higher-CCF sub's limit is preserved for the still-committed sub.
        """
        # FAC_SUB_HIGH (committed=False, FR 100%) would otherwise win the waterfall
        # but is skipped. FAC_SUB_LOW (committed=True, MLR 20%) takes the full headroom.
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_TOP", "FAC_SUB_HIGH", "FAC_SUB_LOW"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_X"] * 3,
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [100_000_000.0, 60_000_000.0, 60_000_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR", "FR", "MLR"],
                "committed": [True, False, True],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_TOP", "FAC_TOP"],
                "child_reference": ["FAC_SUB_HIGH", "FAC_SUB_LOW"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "FAC_TOP")
        # Uncommitted FAC_SUB_HIGH (FR 100%) does NOT emit a row and does NOT
        # consume any parent headroom. FAC_SUB_LOW (MLR 20%) gets its full sub
        # headroom (£60m), with the remaining £40m falling to parent's MR residual.
        sub_high = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_HIGH")
        assert len(sub_high) == 0
        sub_low = rows.filter(pl.col("mof_risk_type_source") == "FAC_SUB_LOW")
        assert len(sub_low) == 1
        assert sub_low["risk_type"][0] == "MLR"
        assert sub_low["nominal_amount"][0] == pytest.approx(60_000_000.0)
        residual = rows.filter(pl.col("mof_risk_type_source").is_null())
        assert len(residual) == 1
        # Residual £40m at parent's own MR risk_type
        assert residual["risk_type"][0] == "MR"
        assert residual["nominal_amount"][0] == pytest.approx(40_000_000.0)

    def test_mof_waterfall_three_subs_mixed_ccf(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Three sub-facilities sort deterministically by descending CCF, then risk_type, then ref."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["MOF_3", "SUB_A", "SUB_B", "SUB_C"],
                "product_type": ["RCF"] * 4,
                "book_code": ["CORP"] * 4,
                "counterparty_reference": ["CP_X"] * 4,
                "value_date": [date(2024, 1, 1)] * 4,
                "maturity_date": [date(2027, 1, 1)] * 4,
                "currency": ["GBP"] * 4,
                "limit": [
                    1_000_000.0,
                    300_000.0,
                    300_000.0,
                    300_000.0,
                ],
                "lgd": [0.45] * 4,
                "seniority": ["senior"] * 4,
                # FR (100%) > MR (50%) > LR (0% under CRR)
                "risk_type": ["MR", "FR", "MR", "LR"],
            }
        ).lazy()

        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["MOF_3"] * 3,
                "child_reference": ["SUB_A", "SUB_B", "SUB_C"],
                "child_type": ["facility"] * 3,
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "MOF_3")
        # Parent headroom £1m. SUB_A (FR 100%) £300k → SUB_B (MR 50%) £300k →
        # SUB_C (LR 0%) £300k → residual £100k at parent's MR.
        assert len(rows) == 4

        a_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_A")
        b_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_B")
        c_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_C")
        residual = rows.filter(pl.col("mof_risk_type_source").is_null())

        assert a_row["risk_type"][0] == "FR"
        assert a_row["nominal_amount"][0] == pytest.approx(300_000.0)
        assert b_row["risk_type"][0] == "MR"
        assert b_row["nominal_amount"][0] == pytest.approx(300_000.0)
        assert c_row["risk_type"][0] == "LR"
        assert c_row["nominal_amount"][0] == pytest.approx(300_000.0)
        assert residual["risk_type"][0] == "MR"
        assert residual["nominal_amount"][0] == pytest.approx(100_000.0)

    def test_mof_with_no_facility_children_uses_own_risk_type(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """A plain hierarchy (only loan children) is not a MOF — parent risk_type unchanged."""
        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_PLAIN"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_X"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "currency": ["GBP"],
                "limit": [1_000_000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["L1"],
                "counterparty_reference": ["CP_X"],
                "drawn_amount": [100_000.0],
                "currency": ["GBP"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_PLAIN"],
                "child_reference": ["L1"],
                "child_type": ["loan"],
            }
        ).lazy()

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
        ).collect()

        row = undrawn.filter(pl.col("exposure_reference") == "FAC_PLAIN_UNDRAWN")
        assert len(row) == 1
        # No facility children → not a MOF → parent's own MR is preserved
        assert row["risk_type"][0] == "MR"
        assert row["mof_risk_type_source"][0] is None

    def test_facility_share_allocates_undrawn_to_riskiest_cp(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Facility with 3 distinct loan-counterparties allocates undrawn to the highest-RW one."""
        # CP_LOW: corporate CQS=1 (RW=20%); CP_MID: corporate CQS=3 (RW=100%);
        # CP_HIGH: corporate CQS=5 (RW=150%) — riskiest, should win.
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_LOW", "CP_MID", "CP_HIGH"],
                "counterparty_name": ["Low", "Mid", "High"],
                "entity_type": ["corporate"] * 3,
                "country_code": ["GB"] * 3,
                "default_status": [False] * 3,
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["R1", "R2", "R3"],
                "counterparty_reference": ["CP_LOW", "CP_MID", "CP_HIGH"],
                "rating_type": ["external"] * 3,
                "rating_agency": ["MOODYS"] * 3,
                "rating_value": ["AAA", "BBB", "B"],
                "cqs": [1, 3, 5],
                "pd": [None, None, None],
                "rating_date": [date(2024, 6, 1)] * 3,
                "is_solicited": [True] * 3,
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["SHARE_FAC"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                # Facility's own counterparty is CP_LOW — should be overridden to CP_HIGH.
                "counterparty_reference": ["CP_LOW"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "currency": ["GBP"],
                "limit": [1_000_000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["L_LOW", "L_MID", "L_HIGH"],
                "product_type": ["TERM_LOAN"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_LOW", "CP_MID", "CP_HIGH"],
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "drawn_amount": [50_000.0, 50_000.0, 50_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["SHARE_FAC"] * 3,
                "child_reference": ["L_LOW", "L_MID", "L_HIGH"],
                "child_type": ["loan"] * 3,
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            counterparties, org_mappings, ratings
        )

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
        ).collect()

        row = undrawn.filter(pl.col("exposure_reference") == "SHARE_FAC_UNDRAWN")
        assert len(row) == 1
        assert row["counterparty_reference"][0] == "CP_HIGH"
        assert row["original_counterparty_reference"][0] == "CP_LOW"

    def test_facility_share_single_member_unchanged(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """A facility with only one distinct loan-counterparty is not a share — no override."""
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_ONLY"],
                "counterparty_name": ["Only"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "default_status": [False],
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy()
        ratings = pl.DataFrame(
            schema={
                "rating_reference": pl.String,
                "counterparty_reference": pl.String,
                "rating_type": pl.String,
                "rating_agency": pl.String,
                "rating_value": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
                "rating_date": pl.Date,
                "is_solicited": pl.Boolean,
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["FAC_SOLO"],
                "product_type": ["RCF"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_ONLY"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "currency": ["GBP"],
                "limit": [500_000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["MR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["L1", "L2"],
                "product_type": ["TERM_LOAN"] * 2,
                "book_code": ["CORP"] * 2,
                "counterparty_reference": ["CP_ONLY"] * 2,
                "value_date": [date(2024, 1, 1)] * 2,
                "maturity_date": [date(2027, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "drawn_amount": [50_000.0, 50_000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_SOLO", "FAC_SOLO"],
                "child_reference": ["L1", "L2"],
                "child_type": ["loan", "loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            counterparties, org_mappings, ratings
        )

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
        ).collect()

        row = undrawn.filter(pl.col("exposure_reference") == "FAC_SOLO_UNDRAWN")
        assert len(row) == 1
        # Only one distinct member — no share override
        assert row["counterparty_reference"][0] == "CP_ONLY"

    def test_mof_waterfall_per_sub_counterparty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Each MOF undrawn split-row carries its own sub-facility's counterparty.

        With waterfall splitting, share-counterparty override is not needed for
        MOF parents — each row already names the sub it came from.
        """
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_A", "CP_B"],
                "counterparty_name": ["A", "B"],
                "entity_type": ["retail", "corporate"],
                "country_code": ["GB", "GB"],
                "default_status": [False, False],
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["R_B"],
                "counterparty_reference": ["CP_B"],
                "rating_type": ["external"],
                "rating_agency": ["MOODYS"],
                "rating_value": ["B"],
                "cqs": [5],
                "pd": [None],
                "rating_date": [date(2024, 6, 1)],
                "is_solicited": [True],
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["MOF_TOP", "SUB_A", "SUB_B"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_A", "CP_A", "CP_B"],
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [1_000_000.0, 500_000.0, 500_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["LR", "MLR", "FR"],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["L_A", "L_B"],
                "product_type": ["TERM_LOAN"] * 2,
                "book_code": ["CORP"] * 2,
                "counterparty_reference": ["CP_A", "CP_B"],
                "value_date": [date(2024, 1, 1)] * 2,
                "maturity_date": [date(2027, 1, 1)] * 2,
                "currency": ["GBP"] * 2,
                "drawn_amount": [50_000.0, 50_000.0],
                "lgd": [0.45] * 2,
                "seniority": ["senior"] * 2,
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["MOF_TOP", "MOF_TOP", "SUB_A", "SUB_B"],
                "child_reference": ["SUB_A", "SUB_B", "L_A", "L_B"],
                "child_type": ["facility", "facility", "loan", "loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            counterparties, org_mappings, ratings
        )

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "MOF_TOP")
        # Two sub-facility split rows, no residual (sub limits sum to parent limit).
        assert len(rows) == 2

        a_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_A")
        b_row = rows.filter(pl.col("mof_risk_type_source") == "SUB_B")

        # FR (100%) fills first — SUB_B with CP_B
        assert b_row["risk_type"][0] == "FR"
        assert b_row["counterparty_reference"][0] == "CP_B"
        # MLR (20%) fills second — SUB_A with CP_A
        assert a_row["risk_type"][0] == "MLR"
        assert a_row["counterparty_reference"][0] == "CP_A"

    def test_mof_waterfall_all_undrawn_per_sub_counterparties(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """All-undrawn MOF with multi-CP sub-facilities — each split row carries its sub's CP."""
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_PARENT", "CP_LIGHT", "CP_HEAVY"],
                "counterparty_name": ["Parent", "Light", "Heavy"],
                # CP_PARENT corporate CQS=2 (50%); CP_LIGHT retail (75%);
                # CP_HEAVY corporate CQS=5 (150%) — the worst credit, must win.
                "entity_type": ["corporate", "retail", "corporate"],
                "country_code": ["GB"] * 3,
                "default_status": [False] * 3,
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["R_P", "R_H"],
                "counterparty_reference": ["CP_PARENT", "CP_HEAVY"],
                "rating_type": ["external", "external"],
                "rating_agency": ["MOODYS", "MOODYS"],
                "rating_value": ["A2", "B"],
                "cqs": [2, 5],
                "pd": [None, None],
                "rating_date": [date(2024, 6, 1)] * 2,
                "is_solicited": [True, True],
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["MOF_DRY", "SUB_LIGHT", "SUB_HEAVY"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_PARENT", "CP_LIGHT", "CP_HEAVY"],
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [1_000_000.0, 600_000.0, 400_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR", "FR", "MR"],
            }
        ).lazy()

        # No loans, no contingents — the all-undrawn case.
        loans = pl.LazyFrame(
            schema={
                "loan_reference": pl.String,
                "counterparty_reference": pl.String,
                "drawn_amount": pl.Float64,
                "currency": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "lgd": pl.Float64,
                "seniority": pl.String,
            }
        )

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["MOF_DRY", "MOF_DRY"],
                "child_reference": ["SUB_LIGHT", "SUB_HEAVY"],
                "child_type": ["facility", "facility"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            counterparties, org_mappings, ratings
        )

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "MOF_DRY")
        # Two sub-facility split rows. SUB_LIGHT (FR 100%) fills first £600k,
        # SUB_HEAVY (MR 50%) fills remaining £400k.
        assert len(rows) == 2
        light = rows.filter(pl.col("mof_risk_type_source") == "SUB_LIGHT")
        heavy = rows.filter(pl.col("mof_risk_type_source") == "SUB_HEAVY")
        assert light["risk_type"][0] == "FR"
        assert light["counterparty_reference"][0] == "CP_LIGHT"
        assert light["nominal_amount"][0] == pytest.approx(600_000.0)
        assert heavy["risk_type"][0] == "MR"
        assert heavy["counterparty_reference"][0] == "CP_HEAVY"
        assert heavy["nominal_amount"][0] == pytest.approx(400_000.0)
        # Total = parent limit
        assert float(rows["nominal_amount"].sum()) == pytest.approx(1_000_000.0)

    def test_facility_share_mixed_drawn_and_undrawn_subs(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Mixed case: one sub-facility CP fully undrawn, another has a drawn loan.

        SUB_DRY is owned by CP_DRY and has no loans (fully undrawn). SUB_WET is
        owned by CP_WET and has a drawn loan to CP_WET. Both counterparties
        must be detected as share members so the riskiest still wins, even
        though one of them has zero current exposure.
        """
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CP_PARENT", "CP_DRY", "CP_WET"],
                "counterparty_name": ["Parent", "Dry", "Wet"],
                # CP_DRY is the riskiest (corporate CQS=5, RW=150%) but has no draws.
                # CP_WET (corporate CQS=2, RW=50%) has the drawn loan.
                # Pre-fix behaviour would have allocated to CP_WET (only loan-CP).
                # Post-fix: CP_DRY wins because it's a sub-facility share member.
                "entity_type": ["corporate", "corporate", "corporate"],
                "country_code": ["GB"] * 3,
                "default_status": [False] * 3,
            }
        ).lazy()
        org_mappings = pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy()
        ratings = pl.DataFrame(
            {
                "rating_reference": ["R_DRY", "R_WET", "R_PARENT"],
                "counterparty_reference": ["CP_DRY", "CP_WET", "CP_PARENT"],
                "rating_type": ["external"] * 3,
                "rating_agency": ["MOODYS"] * 3,
                "rating_value": ["B", "A2", "A2"],
                "cqs": [5, 2, 2],
                "pd": [None, None, None],
                "rating_date": [date(2024, 6, 1)] * 3,
                "is_solicited": [True] * 3,
            }
        ).lazy()

        facilities = pl.DataFrame(
            {
                "facility_reference": ["MOF_MIX", "SUB_DRY", "SUB_WET"],
                "product_type": ["RCF"] * 3,
                "book_code": ["CORP"] * 3,
                "counterparty_reference": ["CP_PARENT", "CP_DRY", "CP_WET"],
                "value_date": [date(2024, 1, 1)] * 3,
                "maturity_date": [date(2027, 1, 1)] * 3,
                "currency": ["GBP"] * 3,
                "limit": [1_000_000.0, 500_000.0, 500_000.0],
                "lgd": [0.45] * 3,
                "seniority": ["senior"] * 3,
                "risk_type": ["MR"] * 3,
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["L_WET"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["CORP"],
                "counterparty_reference": ["CP_WET"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [200_000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        facility_mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["MOF_MIX", "MOF_MIX", "SUB_WET"],
                "child_reference": ["SUB_DRY", "SUB_WET", "L_WET"],
                "child_type": ["facility", "facility", "loan"],
            }
        ).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            counterparties, org_mappings, ratings
        )

        root_lookup = resolver._build_facility_root_lookup(facility_mappings)
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        undrawn = resolver._calculate_facility_undrawn(
            facilities,
            loans,
            None,
            facility_mappings,
            root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
        ).collect()

        rows = undrawn.filter(pl.col("source_facility_reference") == "MOF_MIX")
        # Two split rows, both MR (50%). Tie-break: alphabetical risk_type then
        # facility_reference, so SUB_DRY fills first up to its £500k limit, then
        # SUB_WET fills its remaining headroom (£500k - £200k drawn = £300k).
        assert len(rows) == 2
        dry = rows.filter(pl.col("mof_risk_type_source") == "SUB_DRY")
        wet = rows.filter(pl.col("mof_risk_type_source") == "SUB_WET")
        # Each row carries its own sub's counterparty
        assert dry["counterparty_reference"][0] == "CP_DRY"
        assert dry["nominal_amount"][0] == pytest.approx(500_000.0)
        assert wet["counterparty_reference"][0] == "CP_WET"
        assert wet["nominal_amount"][0] == pytest.approx(300_000.0)
        # Total undrawn = parent headroom = £1m - £200k = £800k
        assert float(rows["nominal_amount"].sum()) == pytest.approx(800_000.0)


# =============================================================================
# Org Mappings Duplicate Child Tests (P2.24)
# =============================================================================


class TestOrgMappingDuplicateChild:
    """Tests for org_mappings dedup and DQ004 emission (P2.24).

    Bug: when two org_mappings rows share the same child_counterparty_reference
    but point to different parents, the join in
    _enrich_counterparties_with_hierarchy fans out — producing duplicate
    counterparty rows and duplicate exposure rows.

    Fix: the resolver must deduplicate org_mappings on child_counterparty_reference
    (first-row-wins), emit exactly one DQ004 WARNING per duplicated child, and
    store only the canonical single-row parent in parent_mappings.
    """

    def test_duplicate_child_in_org_mappings_emits_dq004_and_no_row_fanout(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Two org_mappings rows with the same child produce DQ004 and no fan-out.

        Arrange:
            - 3 counterparties: CHILD_CP (corporate), PARENT_A, PARENT_B
            - 1 loan on CHILD_CP: LOAN_DUP
            - 2 org_mappings rows: PARENT_A->CHILD_CP and PARENT_B->CHILD_CP
            - lending_mappings=None (not relevant to this scenario)
        Act:
            resolver.resolve(bundle, crr_config)
        Assert:
            1. result.exposures for LOAN_DUP has height == 1 (no row fan-out).
            2. result.counterparty_lookup.counterparties for CHILD_CP has height == 1.
            3. result.counterparty_lookup.parent_mappings for CHILD_CP has height == 1.
            4. Exactly one DQ004 error in result.hierarchy_errors for CHILD_CP.
            5. That DQ004 has severity=WARNING and category=DATA_QUALITY.
            6. The retained parent in parent_mappings for CHILD_CP is PARENT_A
               (deterministic first-row-wins).
        """
        # Arrange
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CHILD_CP", "PARENT_A", "PARENT_B"],
                "counterparty_name": ["Subsidiary Ltd", "Parent Alpha", "Parent Beta"],
                "entity_type": ["corporate", "corporate", "corporate"],
                "country_code": ["GB", "GB", "GB"],
                "annual_revenue": [100_000_000.0, 0.0, 0.0],
                "total_assets": [500_000_000.0, 0.0, 0.0],
                "default_status": [False, False, False],
                "sector_code": ["INDUSTRIAL", "INDUSTRIAL", "INDUSTRIAL"],
                "apply_fi_scalar": [False, False, False],
                "is_managed_as_retail": [False, False, False],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_DUP"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["BANKING"],
                "counterparty_reference": ["CHILD_CP"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [1_000_000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        # Duplicate child: CHILD_CP appears twice — trigger for DQ004
        org_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["PARENT_A", "PARENT_B"],
                "child_counterparty_reference": ["CHILD_CP", "CHILD_CP"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=None,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=org_mappings,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        # Act
        result = resolver.resolve(bundle, crr_config)

        # Assert 1: no row fan-out in exposures for LOAN_DUP
        exposure_rows = result.exposures.collect().filter(
            pl.col("exposure_reference") == "LOAN_DUP"
        )
        assert len(exposure_rows) == 1, (
            f"Expected 1 row for LOAN_DUP, got {len(exposure_rows)}. "
            f"org_mappings duplicate child likely caused fan-out."
        )

        # Assert 2: no fan-out in counterparties for CHILD_CP
        cp_rows = result.counterparty_lookup.counterparties.collect().filter(
            pl.col("counterparty_reference") == "CHILD_CP"
        )
        assert len(cp_rows) == 1, (
            f"Expected 1 counterparty row for CHILD_CP, got {len(cp_rows)}. "
            f"Duplicate org_mappings caused counterparty fan-out."
        )

        # Assert 3: no fan-out in parent_mappings for CHILD_CP
        pm_rows = result.counterparty_lookup.parent_mappings.collect().filter(
            pl.col("child_counterparty_reference") == "CHILD_CP"
        )
        assert len(pm_rows) == 1, (
            f"Expected 1 parent_mappings row for CHILD_CP, got {len(pm_rows)}. "
            f"Duplicate org_mappings not deduplicated before storing parent_mappings."
        )

        # Assert 4 & 5: exactly one DQ004 WARNING / DATA_QUALITY for CHILD_CP
        dq004_errors = [
            e
            for e in result.hierarchy_errors
            if e.code == ERROR_DUPLICATE_KEY and e.counterparty_reference == "CHILD_CP"
        ]
        assert len(dq004_errors) == 1, (
            f"Expected exactly 1 DQ004 error for CHILD_CP, got {len(dq004_errors)}. "
            f"All hierarchy_errors: {result.hierarchy_errors}"
        )
        err = dq004_errors[0]
        assert err.severity == ErrorSeverity.WARNING, (
            f"DQ004 must be WARNING severity, got {err.severity!r}"
        )
        assert err.category == ErrorCategory.DATA_QUALITY, (
            f"DQ004 must have DATA_QUALITY category, got {err.category!r}"
        )

        # Assert 6: deterministic first-row-wins — PARENT_A is retained
        assert pm_rows["parent_counterparty_reference"][0] == "PARENT_A", (
            f"Expected PARENT_A retained (first-row-wins), "
            f"got {pm_rows['parent_counterparty_reference'][0]!r}"
        )

    def test_single_row_org_mappings_emits_no_dq004(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Control arm: single-row org_mappings for CHILD_CP emits no DQ004.

        Arrange:
            - Same 3 counterparties and 1 loan as the duplicate test.
            - Only 1 org_mappings row: PARENT_A->CHILD_CP
        Act:
            resolver.resolve(bundle, crr_config)
        Assert:
            - Zero DQ004 errors in result.hierarchy_errors.
            - LOAN_DUP has height == 1 in exposures.
            - CHILD_CP has height == 1 in counterparties.
            - CHILD_CP has height == 1 in parent_mappings.
        """
        # Arrange
        counterparties = pl.DataFrame(
            {
                "counterparty_reference": ["CHILD_CP", "PARENT_A", "PARENT_B"],
                "counterparty_name": ["Subsidiary Ltd", "Parent Alpha", "Parent Beta"],
                "entity_type": ["corporate", "corporate", "corporate"],
                "country_code": ["GB", "GB", "GB"],
                "annual_revenue": [100_000_000.0, 0.0, 0.0],
                "total_assets": [500_000_000.0, 0.0, 0.0],
                "default_status": [False, False, False],
                "sector_code": ["INDUSTRIAL", "INDUSTRIAL", "INDUSTRIAL"],
                "apply_fi_scalar": [False, False, False],
                "is_managed_as_retail": [False, False, False],
            }
        ).lazy()

        loans = pl.DataFrame(
            {
                "loan_reference": ["LOAN_DUP"],
                "product_type": ["TERM_LOAN"],
                "book_code": ["BANKING"],
                "counterparty_reference": ["CHILD_CP"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2027, 1, 1)],
                "currency": ["GBP"],
                "drawn_amount": [1_000_000.0],
                "lgd": [0.45],
                "seniority": ["senior"],
            }
        ).lazy()

        # Single row — no duplicate
        org_mappings = pl.DataFrame(
            {
                "parent_counterparty_reference": ["PARENT_A"],
                "child_counterparty_reference": ["CHILD_CP"],
            }
        ).lazy()

        bundle = RawDataBundle(
            facilities=None,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            org_mappings=org_mappings,
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        # Act
        result = resolver.resolve(bundle, crr_config)

        # Assert: zero DQ004 errors
        dq004_errors = [e for e in result.hierarchy_errors if e.code == ERROR_DUPLICATE_KEY]
        assert len(dq004_errors) == 0, (
            f"Expected no DQ004 errors for clean single-row org_mappings, "
            f"got {len(dq004_errors)}: {dq004_errors}"
        )

        # Assert: shapes are correct (1 row each)
        assert (
            result.exposures.collect().filter(pl.col("exposure_reference") == "LOAN_DUP").height
            == 1
        ), "LOAN_DUP should appear exactly once in clean scenario."

        assert (
            result.counterparty_lookup.counterparties.collect()
            .filter(pl.col("counterparty_reference") == "CHILD_CP")
            .height
            == 1
        ), "CHILD_CP should appear exactly once in counterparties for clean scenario."

        assert (
            result.counterparty_lookup.parent_mappings.collect()
            .filter(pl.col("child_counterparty_reference") == "CHILD_CP")
            .height
            == 1
        ), "CHILD_CP should appear exactly once in parent_mappings for clean scenario."
