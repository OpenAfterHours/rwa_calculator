"""
Integration tests: multi-entity solo-vs-consolidated scope resolution end-to-end.

Pipeline position:
    ParquetLoader -> resolve_scope -> (full pipeline) -> CalculationResponse

Proves the ``reporting_entity`` / ``reporting_basis`` scope feature over the
purpose-built ``tests/fixtures/multi_entity/`` dataset by running the FULL
calculation via ``CreditRiskCalc`` for four scopes (unscoped, GRP consolidated,
BANK_A individual, BANK_B individual) and checking every number against the
fixture's documented hand-calc (see ``tests/fixtures/multi_entity/multi_entity.py``
docstring and ``docs/plans/multi-entity-reporting.md``).

Hand-calc basis (all derived, none snapshotted):
- Every exposure is a GBP 1,000,000 drawn term loan whose facility limit equals
  the drawn amount, so there is no undrawn leg and EAD == drawn == 1,000,000.
- Every counterparty is unrated, so under CRR SA the risk weight is 100%
  (unrated corporate Art. 122; unrated institution Art. 120/121). Each full loan
  therefore contributes EAD 1,000,000 x 100% = 1,000,000 RWA.
- Scope populations (membership + booking filter + intragroup elimination):
    unscoped          : all 5 loans                       -> 5,000,000 RWA
    GRP consolidated  : 3 externals (both intragroup      -> 3,000,000 RWA
                        loans eliminated)
    BANK_A individual : LOAN_A1_EXT, LOAN_A2_EXT,          -> 3,000,000 RWA
                        LOAN_A1_IG_TO_BANK_B (kept)
    BANK_B individual : LOAN_B1_EXT, LOAN_B1_IG_TO_BANK_A  -> 2,000,000 RWA
  BANK_A + BANK_B solo (3,000,000 + 2,000,000 = 5,000,000) deliberately does NOT
  equal GRP consolidated (3,000,000): the two intragroup loans are counted once
  each solo but eliminated at group level. That 2,000,000 asymmetry is the point
  of the fixture.

References:
- CRR Part One Title II (Art. 6, 11-18): individual / sub-consolidated /
  consolidated levels; consolidation eliminates intragroup exposures.
- docs/plans/multi-entity-reporting.md: scope-resolver specification, run-per-scope
  execution model, submission-identity fingerprint.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

import tests.fixtures.multi_entity.multi_entity as multi_entity_fixture
from rwa_calc.api import CreditRiskCalc
from rwa_calc.api.run_index import compute_fingerprint
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.loader import ParquetLoader

if TYPE_CHECKING:
    from rwa_calc.api.models import CalculationResponse

# =============================================================================
# Hand-calc constants (derived from the fixture docstring — see module docstring)
# =============================================================================

_REPORTING_DATE = date(2024, 12, 31)  # CRR era (< 2027-01-01)
_RWA_PER_FULL_LOAN = 1_000_000.0  # EAD 1,000,000 x unrated SA RW 100%

# The single external loan on each book, plus the two intragroup loans.
_LOAN_A1_EXT = "LOAN_A1_EXT"
_LOAN_A2_EXT = "LOAN_A2_EXT"
_LOAN_B1_EXT = "LOAN_B1_EXT"
_LOAN_A1_IG = "LOAN_A1_IG_TO_BANK_B"  # BANK_A book, borrower = group entity BANK_B
_LOAN_B1_IG = "LOAN_B1_IG_TO_BANK_A"  # BANK_B book, borrower = group entity BANK_A

# Expected surviving *source* exposures (distinct underlying loans, before the
# guarantee split fans some into two legs) per scope.
_EXPECTED_LOANS: dict[str, frozenset[str]] = {
    "unscoped": frozenset({_LOAN_A1_EXT, _LOAN_A2_EXT, _LOAN_B1_EXT, _LOAN_A1_IG, _LOAN_B1_IG}),
    "consolidated": frozenset({_LOAN_A1_EXT, _LOAN_A2_EXT, _LOAN_B1_EXT}),
    "bank_a": frozenset({_LOAN_A1_EXT, _LOAN_A2_EXT, _LOAN_A1_IG}),
    "bank_b": frozenset({_LOAN_B1_EXT, _LOAN_B1_IG}),
}
_EXPECTED_TOTAL_RWA: dict[str, float] = {
    "unscoped": 5_000_000.0,
    "consolidated": 3_000_000.0,
    "bank_a": 3_000_000.0,
    "bank_b": 2_000_000.0,
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def multi_entity_data_path() -> Path:
    """Path to the multi-entity fixture directory, regenerated if absent.

    The ``*.parquet`` files under ``tests/fixtures/multi_entity/`` are
    git-ignored build artifacts, so a clean checkout may not have them. Rebuild
    them (deterministically) when the last-written file is missing; this only
    touches ignored artifacts, never the tracked builder.
    """
    fixture_dir = Path(multi_entity_fixture.__file__).parent
    sentinel = fixture_dir / "config" / "reporting_entities.parquet"
    if not sentinel.exists():
        multi_entity_fixture.save_multi_entity_fixtures(fixture_dir)
    return fixture_dir


def _run_scope(
    data_path: Path, entity: str | None, basis: ReportingBasis | None
) -> tuple[CalculationResponse, pl.DataFrame]:
    """Run the full CRR SA calculation for one reporting scope."""
    response = CreditRiskCalc(
        data_path=data_path,
        framework="CRR",
        reporting_date=_REPORTING_DATE,
        permission_mode="standardised",
        reporting_entity=entity,
        reporting_basis=basis,
    ).calculate()
    return response, response.collect_results()


@pytest.fixture(scope="module")
def unscoped_run(multi_entity_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    """Full run with no scope configured (byte-identical-to-today path)."""
    return _run_scope(multi_entity_data_path, None, None)


@pytest.fixture(scope="module")
def consolidated_run(multi_entity_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    """Full run for the GRP consolidated submission (intragroup eliminated)."""
    return _run_scope(multi_entity_data_path, "GRP", ReportingBasis.CONSOLIDATED)


@pytest.fixture(scope="module")
def bank_a_run(multi_entity_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    """Full run for the BANK_A individual submission (intragroup kept)."""
    return _run_scope(multi_entity_data_path, "BANK_A", ReportingBasis.INDIVIDUAL)


@pytest.fixture(scope="module")
def bank_b_run(multi_entity_data_path: Path) -> tuple[CalculationResponse, pl.DataFrame]:
    """Full run for the BANK_B individual submission (intragroup kept)."""
    return _run_scope(multi_entity_data_path, "BANK_B", ReportingBasis.INDIVIDUAL)


# =============================================================================
# Helpers
# =============================================================================


def _source_loans(df: pl.DataFrame) -> set[str]:
    """Distinct underlying source exposures (loans, pre guarantee-split)."""
    return set(df["source_exposure_reference"].unique().to_list())


def _rwa_for_loan(df: pl.DataFrame, source_ref: str) -> float:
    """Total ``rwa_final`` across every result leg of one source loan."""
    legs = df.filter(pl.col("source_exposure_reference") == source_ref)
    return float(legs["rwa_final"].sum())


def _scp_errors(response: CalculationResponse) -> list:
    """SCP-coded reporting-scope errors (SCP001-SCP006) on a response."""
    return [e for e in response.errors if e.code.startswith("SCP")]


def _cls009_errors(response: CalculationResponse) -> list:
    """CLS009 large-FSE-size-undetermined warnings on a response."""
    return [e for e in response.errors if e.code == "CLS009"]


def _row_count(lf: pl.LazyFrame | None) -> int:
    """Eagerly count the rows of a lazy frame."""
    assert lf is not None
    return lf.select(pl.len()).collect().item()


# =============================================================================
# 1. Fixture smoke guard (Wave-1 reviewer tripwire)
# =============================================================================


class TestMultiEntityFixtureLoads:
    """The fixture dataset loads cleanly through the production loader."""

    def test_loader_reports_no_errors(self, multi_entity_data_path: Path) -> None:
        """Loading the clean fixture must accumulate zero CalculationErrors."""
        # Arrange / Act
        bundle = ParquetLoader(base_path=multi_entity_data_path).load()

        # Assert
        assert bundle.errors == [], f"loader accumulated errors: {bundle.errors}"

    def test_expected_frames_present_with_row_counts(self, multi_entity_data_path: Path) -> None:
        """The eight fixture files resolve to seven populated bundle frames.

        The eighth file, ``mapping/lending_mapping.parquet``, is written with
        zero rows (corporate-only dataset, no retail connected-party rollup), so
        the loader's optional-empty rule collapses it to ``None`` — asserted
        explicitly so all eight files are accounted for.
        """
        # Arrange / Act
        bundle = ParquetLoader(base_path=multi_entity_data_path).load()

        # Assert — the seven populated frames, including the two multi-entity
        # registry tables that this feature adds.
        assert _row_count(bundle.counterparties) == 6
        assert _row_count(bundle.facilities) == 5
        assert _row_count(bundle.loans) == 5
        assert _row_count(bundle.facility_mappings) == 5
        assert _row_count(bundle.guarantees) == 2
        assert _row_count(bundle.reporting_entities) == 3
        assert _row_count(bundle.book_entity_mappings) == 3
        # The zero-row mandatory file collapses to None (loader optional-empty rule).
        assert bundle.lending_mappings is None


# =============================================================================
# 2a. Scope population (row counts)
# =============================================================================


class TestScopeRowCounts:
    """Each scope resolves to the loan population the fixture hand-calc predicts."""

    def test_unscoped_includes_all_five_loans(
        self, unscoped_run: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """No scope configured -> all 5 loans survive (identity path)."""
        response, df = unscoped_run
        assert response.success
        assert _source_loans(df) == _EXPECTED_LOANS["unscoped"]

    def test_consolidated_eliminates_both_intragroup_loans(
        self, consolidated_run: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """GRP consolidated -> 3 external loans; both intragroup loans eliminated."""
        response, df = consolidated_run
        assert response.success
        assert _source_loans(df) == _EXPECTED_LOANS["consolidated"]

    def test_bank_a_individual_keeps_its_intragroup_loan(
        self, bank_a_run: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """BANK_A individual -> its 2 externals + its intragroup loan (kept solo)."""
        response, df = bank_a_run
        assert response.success
        assert _source_loans(df) == _EXPECTED_LOANS["bank_a"]

    def test_bank_b_individual_keeps_its_intragroup_loan(
        self, bank_b_run: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """BANK_B individual -> its 1 external + its intragroup loan (kept solo)."""
        response, df = bank_b_run
        assert response.success
        assert _source_loans(df) == _EXPECTED_LOANS["bank_b"]

    def test_intragroup_loans_absent_from_group_present_in_solo(
        self,
        consolidated_run: tuple[CalculationResponse, pl.DataFrame],
        bank_a_run: tuple[CalculationResponse, pl.DataFrame],
        bank_b_run: tuple[CalculationResponse, pl.DataFrame],
    ) -> None:
        """Both intragroup loans vanish at group level but appear in their solo runs.

        LOAN_A1_IG_TO_BANK_B sits on a BANK_A book; LOAN_B1_IG_TO_BANK_A on a
        BANK_B book — so each is present in exactly its own solo run and absent
        from the consolidated run (elimination).
        """
        group_loans = _source_loans(consolidated_run[1])
        assert _LOAN_A1_IG not in group_loans
        assert _LOAN_B1_IG not in group_loans
        assert _LOAN_A1_IG in _source_loans(bank_a_run[1])
        assert _LOAN_B1_IG in _source_loans(bank_b_run[1])


# =============================================================================
# 2b. Intragroup guarantee — CRM substitution vs elimination
# =============================================================================


class TestIntragroupGuaranteeSubstitution:
    """The intragroup guarantee substitutes on the solo run and is eliminated at group.

    GUAR_IG_BANK_B_TO_A1EXT: guarantor BANK_B (a group entity) covers 50% of
    LOAN_A1_EXT (an external corporate loan booked in BANK_A). Hand-calc:
    - LOAN_A1_EXT is EAD 1,000,000; the guarantee covers 50% -> a 500,000
      guaranteed leg + a 500,000 remainder leg.
    - On BANK_A individual the guarantee is kept: the loan splits into two legs
      and the guaranteed leg is attributed to guarantor BANK_B (substitution).
    - On GRP consolidated the guarantee is eliminated (guarantor BANK_B is in
      the consolidated subtree), so the loan stays a single unsubstituted row.
    - RWA is invariant at 1,000,000 either way: guarantor BANK_B is an unrated
      institution (SA RW 100%) and obligor CORP_EXT_A1 an unrated corporate
      (SA RW 100%), so the substitution moves attribution, not capital. The
      effect is therefore asserted on the *split structure*, not an RWA delta.
    """

    def test_solo_run_splits_loan_and_tags_guarantor(
        self, bank_a_run: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """BANK_A individual: LOAN_A1_EXT splits into a guaranteed leg + remainder."""
        _, df = bank_a_run
        legs = df.filter(pl.col("source_exposure_reference") == _LOAN_A1_EXT)

        # Two legs: one guaranteed (tagged to BANK_B, 500,000 covered), one remainder.
        assert legs.height == 2
        guaranteed = legs.filter(pl.col("is_guaranteed"))
        assert guaranteed.height == 1
        guaranteed_row = guaranteed.row(0, named=True)
        assert guaranteed_row["guarantor_reference"] == "BANK_B"
        assert guaranteed_row["guaranteed_portion"] == pytest.approx(500_000.0)

    def test_group_run_leaves_loan_unsubstituted(
        self, consolidated_run: tuple[CalculationResponse, pl.DataFrame]
    ) -> None:
        """GRP consolidated: LOAN_A1_EXT is a single row with no guarantor tag."""
        _, df = consolidated_run
        legs = df.filter(pl.col("source_exposure_reference") == _LOAN_A1_EXT)

        # Single unsplit row — the intragroup guarantee was eliminated pre-CRM.
        assert legs.height == 1
        row = legs.row(0, named=True)
        assert row["is_guaranteed"] is False
        assert row["guarantor_reference"] is None
        assert row["guaranteed_portion"] == pytest.approx(0.0)

    def test_substitution_is_rwa_neutral_across_the_two_runs(
        self,
        bank_a_run: tuple[CalculationResponse, pl.DataFrame],
        consolidated_run: tuple[CalculationResponse, pl.DataFrame],
    ) -> None:
        """LOAN_A1_EXT totals 1,000,000 RWA in both runs (100% guarantor == 100% obligor).

        The guarantee changes attribution (a leg tagged to BANK_B on the solo
        run) but not capital, because both parties carry a 100% SA risk weight.
        Asserting the equality guards against a spurious RWA move being read as a
        substitution benefit — the substitution here is structural only.
        """
        solo_rwa = _rwa_for_loan(bank_a_run[1], _LOAN_A1_EXT)
        group_rwa = _rwa_for_loan(consolidated_run[1], _LOAN_A1_EXT)
        assert solo_rwa == pytest.approx(_RWA_PER_FULL_LOAN)
        assert group_rwa == pytest.approx(_RWA_PER_FULL_LOAN)
        assert solo_rwa == pytest.approx(group_rwa)


# =============================================================================
# 2c. Scope data-quality errors
# =============================================================================


class TestScopeErrors:
    """The clean dataset raises no SCP errors and exactly one CLS009 per run."""

    @pytest.mark.parametrize(
        "run_fixture",
        ["unscoped_run", "consolidated_run", "bank_a_run", "bank_b_run"],
    )
    def test_no_scp_errors_on_clean_dataset(
        self, run_fixture: str, request: pytest.FixtureRequest
    ) -> None:
        """Every book is mapped and every intragroup tag is known -> no SCP001-006."""
        response, _ = request.getfixturevalue(run_fixture)
        assert _scp_errors(response) == [], (
            f"unexpected SCP errors on {run_fixture}: "
            f"{[(e.code, e.message) for e in _scp_errors(response)]}"
        )

    @pytest.mark.parametrize(
        "run_fixture",
        ["unscoped_run", "consolidated_run", "bank_a_run", "bank_b_run"],
    )
    def test_exactly_one_cls009_warning_per_run(
        self, run_fixture: str, request: pytest.FixtureRequest
    ) -> None:
        """Exactly one CLS009 fires in every run — driven by the reference table, not scope.

        CLS009 (Art. 153(2) large-FSE size undetermined) is a single aggregate
        warning raised over the *counterparty reference table*, which the scope
        resolver does NOT filter (reference frames are never scope-filtered —
        dropped exposures simply stop joining to them). That table always carries
        the three financial-sector counterparties with null total_assets
        (BANK_A, BANK_B, EXT_BANK_1), so the one aggregate warning fires in all
        four scopes — including GRP consolidated, where BANK_A / BANK_B have no
        surviving exposures. The count therefore tracks the reference-frame
        population, not which counterparties have in-scope exposures.
        """
        response, _ = request.getfixturevalue(run_fixture)
        cls009 = _cls009_errors(response)
        assert len(cls009) == 1, (
            f"expected exactly one CLS009 on {run_fixture}; got {len(cls009)}. "
            "CLS009 is raised over the unfiltered counterparty reference table "
            "(all three null-total_assets FSEs), not the scoped exposure population."
        )


# =============================================================================
# 2d. Scope totals
# =============================================================================


class TestScopeTotals:
    """Portfolio RWA totals match the hand-calc and are internally consistent."""

    @pytest.mark.parametrize(
        ("run_fixture", "scope_key"),
        [
            ("unscoped_run", "unscoped"),
            ("consolidated_run", "consolidated"),
            ("bank_a_run", "bank_a"),
            ("bank_b_run", "bank_b"),
        ],
    )
    def test_total_rwa_matches_hand_calc(
        self, run_fixture: str, scope_key: str, request: pytest.FixtureRequest
    ) -> None:
        """Each run's total RWA equals its hand-derived value (100% RW x EAD)."""
        response, _ = request.getfixturevalue(run_fixture)
        assert float(response.summary.total_rwa) == pytest.approx(_EXPECTED_TOTAL_RWA[scope_key])

    @pytest.mark.parametrize(
        "run_fixture",
        ["unscoped_run", "consolidated_run", "bank_a_run", "bank_b_run"],
    )
    def test_summary_total_equals_sum_over_result_rows(
        self, run_fixture: str, request: pytest.FixtureRequest
    ) -> None:
        """The summary total is exactly the sum of ``rwa_final`` over the run's rows."""
        response, df = request.getfixturevalue(run_fixture)
        assert float(response.summary.total_rwa) == pytest.approx(float(df["rwa_final"].sum()))

    def test_consolidated_total_differs_from_solo_sum_by_intragroup(
        self,
        consolidated_run: tuple[CalculationResponse, pl.DataFrame],
        bank_a_run: tuple[CalculationResponse, pl.DataFrame],
        bank_b_run: tuple[CalculationResponse, pl.DataFrame],
    ) -> None:
        """GRP consolidated != BANK_A solo + BANK_B solo — asymmetric by construction.

        Solo sum (3,000,000 + 2,000,000 = 5,000,000) exceeds GRP consolidated
        (3,000,000) by exactly 2,000,000: the two intragroup loans (1,000,000
        each) are counted once each solo but eliminated at the group level.
        """
        group = float(consolidated_run[0].summary.total_rwa)
        solo_sum = float(bank_a_run[0].summary.total_rwa) + float(bank_b_run[0].summary.total_rwa)

        assert group != pytest.approx(solo_sum)
        assert solo_sum - group == pytest.approx(2 * _RWA_PER_FULL_LOAN)


# =============================================================================
# 3. Submission identity (run-reuse fingerprint distinguishes scopes)
# =============================================================================


class TestSubmissionIdentity:
    """Two runs over identical data but different scopes are distinct submissions."""

    def test_scopes_produce_distinct_fingerprints_over_identical_data(
        self, multi_entity_data_path: Path
    ) -> None:
        """Four scopes over one on-disk dataset yield four distinct fingerprints.

        The fingerprint keys the run-reuse index; distinct scopes must never
        collide there (a consolidated run must not be reused for a solo request).
        The data signature is identical across all four — proving the distinction
        comes from the scope parameters, not any input-file difference.
        """

        def fingerprint(entity: str | None, basis: ReportingBasis | None):
            return compute_fingerprint(
                data_path=multi_entity_data_path,
                framework="CRR",
                reporting_date=_REPORTING_DATE,
                permission_mode="standardised",
                data_format="parquet",
                reporting_entity=entity,
                reporting_basis=basis.value if basis is not None else None,
            )

        fingerprints = [
            fingerprint(None, None),
            fingerprint("GRP", ReportingBasis.CONSOLIDATED),
            fingerprint("BANK_A", ReportingBasis.INDIVIDUAL),
            fingerprint("BANK_B", ReportingBasis.INDIVIDUAL),
        ]

        # All four distinct as index keys.
        assert len(set(fingerprints)) == 4
        # ...over one identical on-disk data state.
        signatures = {fp.data_signature for fp in fingerprints}
        assert len(signatures) == 1

    def test_response_carries_the_requested_scope(
        self,
        unscoped_run: tuple[CalculationResponse, pl.DataFrame],
        consolidated_run: tuple[CalculationResponse, pl.DataFrame],
        bank_a_run: tuple[CalculationResponse, pl.DataFrame],
    ) -> None:
        """The response echoes the scope it was calculated for (None when unscoped)."""
        assert unscoped_run[0].reporting_entity is None
        assert unscoped_run[0].reporting_basis is None
        assert consolidated_run[0].reporting_entity == "GRP"
        assert consolidated_run[0].reporting_basis == "consolidated"
        assert bank_a_run[0].reporting_entity == "BANK_A"
        assert bank_a_run[0].reporting_basis == "individual"
