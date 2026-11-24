"""
P1.368 — the PS1/26 Art. 110A due-diligence inputs reach the SA risk weight.

Pipeline position:
    Loader -> HierarchyResolver (unify + hierarchy_resolved seal) -> Classifier
    -> CRMProcessor -> RealEstateSplitter -> SACalculator -> Aggregator

What was wrong:
``due_diligence_performed`` and ``due_diligence_override_rw`` passed the loader
seal on loans and contingents, then were dropped by the explicit projections in
``engine/hierarchy/unify.py`` and (had they survived) stripped by the undeclared
``hierarchy_resolved`` edge. Two consequences under Basel 3.1:

- the override branch of ``apply_due_diligence_override`` was unreachable from any
  input, so a firm's "at least one credit quality step higher" weight
  (PS1/26 Art. 120(4) / 122(4) / 129(4A)) never reached ``risk_weight``;
- SA004 tested the column's PRESENCE, so it fired once on every Basel 3.1 run
  whatever the input said — an alarm with no discriminating power (LESSONS B9).

Why this file is end to end:
every pre-existing test called ``apply_due_diligence_override`` on a hand-built
frame, which bypasses unify and every edge (LESSONS G: helpers bypass the input
contract). That is how the dead path stayed green. Each assertion here goes through
``PipelineOrchestrator.run_with_data`` from raw input frames.

The SA004 assertions run on the case where nothing is wrong AND on the case the
alarm exists to catch, and check the outputs differ (LESSONS B9). The attested book
deliberately carries a facility-undrawn row and an SA-CCR row, the two row types
that have no attestation field: a census that counted their nulls would pass every
other leg here and saturate on every real facility or derivatives book.

Both carriers are exercised. Loans and contingents are unified by different
projections in ``engine/hierarchy/unify.py``, so dropping the two columns from either
one alone reopens the defect on that table only; the contingent legs below are the
guard for the contingent projection.

Hand calculation (corporate, external CQS 2, EAD 1,000,000, no CRM):
    base SA weight   = 50%   (Table 6, CQS 2 — CRR Art. 122(1); PS1/26 Art. 122(2))
    override 0.75    -> B31: max(0.75, 0.50) = 0.75, RWA 750,000 (Table 6 CQS 3,
                        one step higher — Art. 122(4)); CRR: no rule, 500,000
    override 0.20    -> max(0.20, 0.50) = 0.50 in both regimes (never reduces)
    contingent       -> OFB financial guarantee, credit substitute: CCF 100%
                        (CRR Art. 111(1), Annex I point 1(a); PS1/26 Art. 111(1)
                        Table A1 row 1(a)), so EAD 1,000,000 and the same 0.75 /
                        750,000 under Basel 3.1, 0.50 / 500,000 under CRR

Hand calculation (Basel 3.1 IRB book, output floor; the obligor is rated CQS 2 and
carries an internal PD 0.40%; two F-IRB term loans, EAD 1,000,000 each, M 3.0y):
    reported IRB weight  both loans, override or not: PS1/26 Art. 153(1)(c),
                         R(0.40%), supervisory LGD 40% (Art. 161(1)(aa)), M 3.0,
                         no 1.06 factor -> RW 0.606892, RWA 606,892.43
    SA-equivalent        PS1/26 Art. 92(3A)(b)(ii): S-TREA is calculated "as if
                         permission to use [the IRB Approach] has not been granted",
                         i.e. under the SA in full, Art. 122(4) included
      override 0.75      -> sa_rwa max(0.75, 0.50) x 1,000,000 =   750,000
      no override        -> sa_rwa 0.50 x 1,000,000            =   500,000
    S-TREA               = 750,000 + 500,000                   = 1,250,000
                         (1,000,000 if the override skipped IRB rows: an
                         RWA-reducing error under the output floor)

References:
- PRA PS1/26 Art. 110A(2), (5): the obligation and its exemptions
- PRA PS1/26 Art. 120(4), 122(4), 129(4A): the one-step-higher risk weight
- PRA PS1/26 Art. 92(3A)(b)(ii): S-TREA as if the IRB permission were not granted
- docs/specifications/basel31/sa-risk-weights.md, "Due Diligence Obligation"
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_DUE_DILIGENCE_NOT_PERFORMED, CalculationError
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_a1 import (
    CCR_A1_COUNTERPARTY_REF,
    build_raw_data_bundle_with_ccr_a1,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.oracle.derivations import formulas as oracle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_VALUE_DATE = date(2025, 1, 15)
_MATURITY_DATE = date(2030, 1, 15)
_EAD = 1_000_000.0

_CP_CORP = "P1368_CP_CORP"
_CP_SOV = "P1368_CP_SOV"

_LOAN_OVR = "P1368_L_OVR"  # override 0.75, above the 50% CQS 2 weight
_LOAN_LOW = "P1368_L_LOW"  # override 0.20, below it
_LOAN_NONE = "P1368_L_NONE"  # no override; drawn under the facility
_LOAN_SOV = "P1368_L_SOV"  # Art. 112(1)(a) central government, never attested
_FAC = "P1368_FAC"  # leaves 1,000,000 of undrawn headroom
_CONT_OVR = "P1368_C_OVR"  # OFB financial guarantee, override 0.75

_OVERRIDE_RW = 0.75
_LOW_OVERRIDE_RW = 0.20
#: Table 6 corporate CQS 2 — identical in both regimes (CRR Art. 122(1); PS1/26 Art. 122(2)).
_CQS2_CORPORATE_RW = 0.50

#: Rows of the attested book that are in scope of Art. 110A and carry the attestation
#: on the loans table: the three corporate loans. The corporate contingent is the
#: fourth in-scope row. The sovereign loan is exempt (Art. 110A(5)(a)); the
#: facility-undrawn and SA-CCR rows have no attestation field.
_IN_SCOPE_LOANS = (_LOAN_OVR, _LOAN_LOW, _LOAN_NONE)

_REGIMES = {
    "CRR": CalculationConfig.crr(
        reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.STANDARDISED
    ),
    "B31": CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.STANDARDISED
    ),
}

# The Basel 3.1 IRB book (output-floor legs). Maturity exactly 3.0y after reporting.
_IRB_REPORTING_DATE = date(2027, 6, 30)
_IRB_MATURITY_DATE = date(2030, 6, 30)
_IRB_MATURITY_YEARS = 3.0
_IRB_PD = 0.004
#: PS1/26 Art. 161(1)(aa): F-IRB senior unsecured LGD, non-financial-sector corporate.
_FIRB_SENIOR_LGD = 0.40
_IRB_LOAN_OVR = "P1368_IRB_L_OVR"  # override 0.75, above the 50% SA-equivalent weight
_IRB_LOAN_CTL = "P1368_IRB_L_CTL"  # no override, and unattested
_IRB_B31 = CalculationConfig.basel_3_1(
    reporting_date=_IRB_REPORTING_DATE, permission_mode=PermissionMode.IRB
)


# ---------------------------------------------------------------------------
# Bundle builders
# ---------------------------------------------------------------------------


def _counterparties(ccr_bundle: RawDataBundle) -> pl.LazyFrame:
    """The corporate and sovereign obligors, plus the SA-CCR institution CP_001."""
    rows = [
        {
            "counterparty_reference": _CP_CORP,
            "counterparty_name": "P1.368 corporate (CQS 2)",
            "entity_type": "corporate",
            "country_code": "GB",
            # Large corporate: keeps it off the SME supporting factor (CRR Art. 501).
            "annual_revenue": 1_000_000_000.0,
            "total_assets": 1_000_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
        {
            "counterparty_reference": _CP_SOV,
            "counterparty_name": "P1.368 UK central government",
            "entity_type": "sovereign",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
        },
    ]
    ours = pl.DataFrame(rows, schema=dtypes_of(COUNTERPARTY_SCHEMA))
    theirs = ccr_bundle.counterparties.collect().select(ours.columns)
    return pl.concat([ours, theirs]).lazy()


def _ratings(ccr_bundle: RawDataBundle) -> pl.LazyFrame:
    """External CQS 2 on the corporate, plus CP_001's own rating."""
    ours = pl.DataFrame(
        [
            {
                "rating_reference": "P1368_RTG_CORP",
                "counterparty_reference": _CP_CORP,
                "rating_type": "external",
                "rating_agency": "S&P",
                "rating_value": "A",
                "cqs": 2,
                "rating_date": _VALUE_DATE,
                "is_solicited": True,
            }
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )
    theirs = ccr_bundle.ratings.collect().select(ours.columns)
    return pl.concat([ours, theirs]).lazy()


def _loan(reference: str, counterparty: str, override: float | None, performed: bool) -> dict:
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty,
        "product_type": "term_loan",
        "drawn_amount": _EAD,
        "interest": 0.0,
        "currency": "GBP",
        "seniority": "senior",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
        "due_diligence_performed": performed,
        "due_diligence_override_rw": override,
    }


def _loans(*, attested: bool) -> pl.DataFrame:
    """Three corporate loans and one sovereign loan.

    ``attested=False`` withdraws the attestation from ONE corporate loan only, so
    the alarm's two states differ by exactly one in-scope row.
    """
    rows = [
        _loan(_LOAN_OVR, _CP_CORP, _OVERRIDE_RW, performed=True),
        _loan(_LOAN_LOW, _CP_CORP, _LOW_OVERRIDE_RW, performed=True),
        _loan(_LOAN_NONE, _CP_CORP, None, performed=attested),
        _loan(_LOAN_SOV, _CP_SOV, None, performed=False),
    ]
    return pl.DataFrame(rows, schema=dtypes_of(LOAN_SCHEMA))


def _contingents(*, attested: bool) -> pl.DataFrame:
    """One OFB financial guarantee to the corporate, carrying the 0.75 override.

    ``attested=False`` withdraws its attestation and leaves the override in place:
    the override does not depend on the attestation, the SA004 count does.
    """
    row = {
        "contingent_reference": _CONT_OVR,
        "counterparty_reference": _CP_CORP,
        "product_type": "guarantee_given",
        "nominal_amount": _EAD,
        "currency": "GBP",
        "seniority": "senior",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
        "bs_type": "OFB",
        # Full risk: a guarantee with the character of a credit substitute, CCF 100%.
        "risk_type": "FR",
        "due_diligence_performed": attested,
        "due_diligence_override_rw": _OVERRIDE_RW,
    }
    return pl.DataFrame([row], schema=dtypes_of(CONTINGENTS_SCHEMA))


def _facilities() -> pl.LazyFrame:
    """One committed facility over _LOAN_NONE with 1,000,000 undrawn headroom."""
    row = {
        "facility_reference": _FAC,
        "counterparty_reference": _CP_CORP,
        "product_type": "rcf",
        "limit": 2 * _EAD,
        "risk_type": "MR",
        "committed": True,
        "is_revolving": False,
        "currency": "GBP",
        "seniority": "senior",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
    }
    return pl.DataFrame([row], schema=dtypes_of(FACILITY_SCHEMA)).lazy()


def _facility_mappings() -> pl.LazyFrame:
    row = {"parent_facility_reference": _FAC, "child_reference": _LOAN_NONE, "child_type": "loan"}
    return pl.DataFrame([row], schema=dtypes_of(FACILITY_MAPPING_SCHEMA)).lazy()


def _bundle(loans: pl.DataFrame, contingents: pl.DataFrame) -> RawDataBundle:
    """Loans + contingent + facility + the SA-CCR A1 netting set, sealed as the loader
    seals them."""
    ccr_bundle = build_raw_data_bundle_with_ccr_a1()
    return make_raw_bundle(
        facilities=_facilities(),
        loans=loans.lazy(),
        contingents=contingents.lazy(),
        counterparties=_counterparties(ccr_bundle),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(ccr_bundle),
        ccr=ccr_bundle.ccr,
    )


def _run(regime: str, loans: pl.DataFrame, contingents: pl.DataFrame | None = None):
    """One pipeline run; the contingent is attested unless a frame is passed."""
    if contingents is None:
        contingents = _contingents(attested=True)
    return PipelineOrchestrator().run_with_data(_bundle(loans, contingents), _REGIMES[regime])


def _irb_bundle() -> RawDataBundle:
    """The Basel 3.1 IRB book: one large corporate, rated CQS 2 externally and PD
    0.40% internally, with two F-IRB term loans — one carrying the 0.75 override
    (attested), one with no override and no attestation."""
    counterparty = {
        "counterparty_reference": _CP_CORP,
        "counterparty_name": "P1.368 IRB corporate (CQS 2, PD 0.40%)",
        "entity_type": "corporate",
        "country_code": "GB",
        # Large corporate: no SME correlation adjustment (PS1/26 Art. 153(4)).
        "annual_revenue": 1_000_000_000.0,
        "total_assets": 1_000_000_000.0,
        "default_status": False,
        "apply_fi_scalar": False,
    }
    ratings = [
        {
            "rating_reference": "P1368_IRB_RTG_EXT",
            "counterparty_reference": _CP_CORP,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "A",
            "cqs": 2,
            "rating_date": _IRB_REPORTING_DATE,
            "is_solicited": True,
        },
        {
            "rating_reference": "P1368_IRB_RTG_INT",
            "counterparty_reference": _CP_CORP,
            "rating_type": "internal",
            "pd": _IRB_PD,
            "rating_date": _IRB_REPORTING_DATE,
            "model_id": "TEST_FULL_IRB",
        },
    ]
    loans = [
        _loan(_IRB_LOAN_OVR, _CP_CORP, _OVERRIDE_RW, performed=True),
        _loan(_IRB_LOAN_CTL, _CP_CORP, None, performed=False),
    ]
    for loan in loans:
        loan["maturity_date"] = _IRB_MATURITY_DATE
    return make_raw_bundle(
        counterparties=pl.DataFrame([counterparty], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy(),
        loans=pl.DataFrame(loans, schema=dtypes_of(LOAN_SCHEMA)).lazy(),
        ratings=pl.DataFrame(ratings, schema=dtypes_of(RATINGS_SCHEMA)).lazy(),
        model_permissions=create_full_irb_model_permissions(),
    )


def _sa004(errors: list[CalculationError]) -> list[CalculationError]:
    return [e for e in errors if e.code == ERROR_DUE_DILIGENCE_NOT_PERFORMED]


def _sa_row(result, reference: str) -> dict:
    """The single SA result row for a loan or contingent, keyed by its source reference."""
    assert result.sa_results is not None, "no SA branch emitted: nothing below means anything"
    rows = (
        result.sa_results.collect()
        .filter(pl.col("source_exposure_reference") == reference)
        .to_dicts()
    )
    assert len(rows) == 1, f"{reference}: expected one SA row, got {len(rows)}"
    return rows[0]


@pytest.fixture(scope="module")
def attested_runs() -> dict:
    """One run per regime of the attested book."""
    return {regime: _run(regime, _loans(attested=True)) for regime in _REGIMES}


@pytest.fixture(scope="module")
def irb_run():
    """One Basel 3.1 run of the IRB book under the output floor."""
    return PipelineOrchestrator().run_with_data(_irb_bundle(), _IRB_B31)


def _irb_row(result, reference: str) -> dict:
    """The single aggregated result row for an IRB loan."""
    rows = result.results.collect().filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, f"{reference}: expected one result row, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# The override reaches risk_weight (Basel 3.1) and nothing moves under CRR
# ---------------------------------------------------------------------------


class TestDueDiligenceOverrideReachesRiskWeight:
    """A populated ``due_diligence_override_rw`` lifts the SA weight end to end."""

    def test_b31_override_above_the_rated_weight_is_applied(self, attested_runs: dict) -> None:
        """Basel 3.1: the 0.75 override replaces the 50% CQS 2 weight (Art. 122(4))."""
        # Arrange
        row = _sa_row(attested_runs["B31"], _LOAN_OVR)

        # Act / Assert
        assert row["ead_final"] == pytest.approx(_EAD)
        assert row["risk_weight"] == pytest.approx(_OVERRIDE_RW)
        assert row["rwa_final"] == pytest.approx(_EAD * _OVERRIDE_RW)
        assert row["due_diligence_override_applied"] is True

    def test_b31_override_below_the_rated_weight_never_reduces_it(
        self, attested_runs: dict
    ) -> None:
        """The override is max-only: 0.20 against a 50% weight leaves 50%."""
        # Arrange
        row = _sa_row(attested_runs["B31"], _LOAN_LOW)

        # Act / Assert
        assert row["risk_weight"] == pytest.approx(_CQS2_CORPORATE_RW)
        assert row["rwa_final"] == pytest.approx(_EAD * _CQS2_CORPORATE_RW)
        assert row["due_diligence_override_applied"] is False

    def test_b31_contingent_override_is_applied(self, attested_runs: dict) -> None:
        """Basel 3.1: the contingent carrier reaches the SA weight too (Art. 122(4)).

        Loans and contingents are unified by separate projections, so this leg is the
        only thing that fails if the contingent projection drops the two columns.
        """
        # Arrange
        row = _sa_row(attested_runs["B31"], _CONT_OVR)

        # Act / Assert
        assert row["exposure_type"] == "contingent"
        assert row["ead_final"] == pytest.approx(_EAD)
        assert row["risk_weight"] == pytest.approx(_OVERRIDE_RW)
        assert row["rwa_final"] == pytest.approx(_EAD * _OVERRIDE_RW)
        assert row["due_diligence_override_applied"] is True

    @pytest.mark.parametrize("reference", [_LOAN_OVR, _LOAN_LOW, _LOAN_NONE, _CONT_OVR])
    def test_crr_ignores_the_override(self, attested_runs: dict, reference: str) -> None:
        """CRR has no Art. 110A: every corporate loan and the contingent keep their
        Table 6 CQS 2 weight."""
        # Arrange
        row = _sa_row(attested_runs["CRR"], reference)

        # Act / Assert
        assert row["risk_weight"] == pytest.approx(_CQS2_CORPORATE_RW)
        assert row["rwa_final"] == pytest.approx(_EAD * _CQS2_CORPORATE_RW)
        assert row.get("due_diligence_override_applied") is None


# ---------------------------------------------------------------------------
# SA004 reads the value, scoped to the rows Art. 110A covers
# ---------------------------------------------------------------------------


class TestDueDiligenceWarningDiscriminates:
    """SA004 must differ between a book that attests and one that does not (B9)."""

    def test_b31_attested_book_raises_no_sa004(self, attested_runs: dict) -> None:
        """Every in-scope row (three loans, one contingent) attests; the exempt
        sovereign, the facility-undrawn row and the SA-CCR row do not, and none of them
        may trip the alarm."""
        # Arrange
        result = attested_runs["B31"]
        sa = result.sa_results.collect()
        assert "facility_undrawn" in sa["exposure_type"].to_list(), (
            "no facility-undrawn row reached the SA branch: this leg would be vacuous"
        )
        assert CCR_A1_COUNTERPARTY_REF in sa["counterparty_reference"].to_list(), (
            "no SA-CCR row reached the SA branch: this leg would be vacuous"
        )
        assert "central_govt_central_bank" in sa["exposure_class"].to_list(), (
            "no Art. 110A(5) exempt row: this leg would be vacuous"
        )

        # Act
        warnings = _sa004(result.errors)

        # Assert
        assert warnings == [], [w.message for w in warnings]

    def test_b31_one_unattested_in_scope_row_raises_one_sa004(self) -> None:
        """Withdraw the attestation from one corporate loan: one warning, counting one."""
        # Arrange
        result = _run("B31", _loans(attested=False))

        # Act
        warnings = _sa004(result.errors)

        # Assert
        assert len(warnings) == 1, [w.message for w in warnings]
        assert warnings[0].actual_value == "False on 1 exposure row(s)"
        assert warnings[0].message.startswith("1 Standardised Approach exposure row(s)")

    def test_b31_unattested_contingent_is_counted(self) -> None:
        """Withdraw the contingent's attestation as well: the same one warning, now
        counting two. The step from 1 to 2 is the contingent alone, so a contingent
        projection that dropped ``due_diligence_performed`` (leaving it null, which
        the census never counts) fails here."""
        # Arrange
        result = _run("B31", _loans(attested=False), _contingents(attested=False))

        # Act
        warnings = _sa004(result.errors)

        # Assert
        assert len(warnings) == 1, [w.message for w in warnings]
        assert warnings[0].actual_value == "False on 2 exposure row(s)"

    def test_b31_feed_without_the_column_warns_on_every_in_scope_row(self) -> None:
        """A loans feed that genuinely omits both columns (not pinned as typed nulls).

        The loader defaults ``due_diligence_performed`` to False, so each of the three
        corporate loans is unattested; the sovereign stays exempt.
        """
        # Arrange
        loans = _loans(attested=True).drop("due_diligence_performed", "due_diligence_override_rw")
        assert "due_diligence_performed" not in loans.columns

        # Act
        warnings = _sa004(_run("B31", loans).errors)

        # Assert
        assert len(warnings) == 1, [w.message for w in warnings]
        assert warnings[0].actual_value == f"False on {len(_IN_SCOPE_LOANS)} exposure row(s)"

    def test_crr_never_raises_sa004(self) -> None:
        """No Art. 110A under CRR: an unattested book raises nothing."""
        # Arrange / Act
        warnings = _sa004(_run("CRR", _loans(attested=False), _contingents(attested=False)).errors)

        # Assert
        assert warnings == []


# ---------------------------------------------------------------------------
# Under the output floor the override lifts the SA-equivalent, never the IRB weight
# ---------------------------------------------------------------------------


class TestDueDiligenceOverrideOutputFloor:
    """Basel 3.1 IRB book: the override reaches S-TREA and leaves U-TREA alone.

    PS1/26 Art. 92(3A)(b)(ii) computes S-TREA "as if permission to use [the IRB
    Approach] has not been granted", so the SA-equivalent weight of an IRB row is the
    SA weight in full, Art. 122(4) included. Copying the SA004 census's
    ``is_sa_branch_approach()`` scope into the override would skip IRB rows and lower
    S-TREA — an RWA-reducing change under the output floor. These legs pin it.
    """

    @pytest.mark.parametrize("reference", [_IRB_LOAN_OVR, _IRB_LOAN_CTL])
    def test_b31_rows_are_foundation_irb(self, irb_run, reference: str) -> None:
        """Guard: the book only means something on F-IRB rows at EAD 1,000,000, M 3.0."""
        # Arrange / Act
        row = _irb_row(irb_run, reference)

        # Assert
        assert row["approach_applied"] == "foundation_irb"
        assert row["ead_final"] == pytest.approx(_EAD)
        assert row["lgd_floored"] == pytest.approx(_FIRB_SENIOR_LGD)
        assert row["irb_maturity_m"] == pytest.approx(_IRB_MATURITY_YEARS)

    def test_b31_override_lifts_the_sa_equivalent_of_an_irb_row(self, irb_run) -> None:
        """The overridden loan's SA-equivalent RWA is EAD x 0.75, not EAD x 0.50."""
        # Arrange / Act
        row = _irb_row(irb_run, _IRB_LOAN_OVR)

        # Assert
        assert row["sa_rwa"] == pytest.approx(row["ead_final"] * _OVERRIDE_RW)
        assert row["sa_rwa"] == pytest.approx(_EAD * _OVERRIDE_RW)

    def test_b31_irb_row_without_an_override_keeps_its_sa_equivalent(self, irb_run) -> None:
        """Control: the twin with no override stays at the CQS 2 weight, EAD x 0.50."""
        # Arrange / Act
        row = _irb_row(irb_run, _IRB_LOAN_CTL)

        # Assert
        assert row["sa_rwa"] == pytest.approx(_EAD * _CQS2_CORPORATE_RW)

    def test_b31_s_trea_carries_the_override(self, irb_run) -> None:
        """S-TREA = 750,000 + 500,000 = 1,250,000 (1,000,000 without the override)."""
        # Arrange
        summary = irb_run.output_floor_summary
        assert summary is not None, "no output-floor summary: Basel 3.1 IRB run expected one"

        # Act / Assert
        assert summary.s_trea == pytest.approx(_EAD * (_OVERRIDE_RW + _CQS2_CORPORATE_RW))

    @pytest.mark.parametrize("reference", [_IRB_LOAN_OVR, _IRB_LOAN_CTL])
    def test_b31_override_never_moves_the_reported_irb_weight(
        self, irb_run, reference: str
    ) -> None:
        """Both loans keep the Art. 153(1)(c) F-IRB weight, 0.606892: the override is
        an SA rule and only reaches the SA-equivalent."""
        # Arrange
        expected_rw = oracle.irb_risk_weight_corporate(
            pd_value=_IRB_PD,
            lgd=_FIRB_SENIOR_LGD,
            maturity=_IRB_MATURITY_YEARS,
            correlation=oracle.correlation_corporate(_IRB_PD),
            scaling_factor=1.0,  # PS1/26 Art. 153(1)(c): no 1.06 factor
        )

        # Act
        row = _irb_row(irb_run, reference)

        # Assert
        assert expected_rw == pytest.approx(0.606892, abs=1e-6)
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(_EAD * expected_rw)

    @pytest.mark.parametrize("reference", [_IRB_LOAN_OVR, _IRB_LOAN_CTL])
    def test_b31_irb_row_carries_no_override_audit_flag(self, irb_run, reference: str) -> None:
        """``due_diligence_override_applied`` is an SA-branch flag: null on IRB rows,
        including the one whose SA-equivalent the override lifted."""
        # Arrange / Act
        row = _irb_row(irb_run, reference)

        # Assert
        assert "due_diligence_override_applied" in row, "the aggregator edge declares it"
        assert row["due_diligence_override_applied"] is None

    def test_b31_unattested_irb_row_raises_no_sa004(self, irb_run) -> None:
        """The control loan is unattested, but Art. 110A(1) is an SA obligation: an
        IRB-only book raises no SA004 even though ``calculate_unified`` weights it."""
        # Arrange / Act
        warnings = _sa004(irb_run.errors)

        # Assert
        assert warnings == [], [w.message for w in warnings]
