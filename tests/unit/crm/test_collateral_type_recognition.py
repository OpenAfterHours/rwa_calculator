"""
Unit tests for the D5 unrecognised-collateral-type defect.

``engine/crm/expressions.py::collateral_category_expr`` (``:223-242``) falls
through to category ``"other"`` for ANY ``collateral_type`` string that
matches none of the six known category sets, silently -- no data-quality
warning is raised. The collateral then reports in NO CRM column (the
Art. 231 waterfall, ``WATERFALL_ORDER``, keys on the SAME six sets), and RWA
changes: spelling real-estate collateral ``residential_real_estate`` (not a
member of ``REAL_ESTATE_COLLATERAL_TYPES``) on the retail-mortgage fixture
moves B3.1 RWA 39,848 -> 71,534 with no error, no warning, and no trace in
any published column.

This file drives a NEW warning, one per unrecognised row, naming the
collateral reference and the offending value. It does not exist in
``contracts/errors.py`` yet; the next free CRM code today is CRM021
(highest defined: CRM020, ``ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN``). This
file therefore asserts on the LITERAL STRING ``"CRM021"`` rather than
importing a not-yet-existing constant, and proposes the name
``ERROR_UNRECOGNISED_COLLATERAL_TYPE`` for the implementer, matching this
codebase's ``ERROR_<DESCRIPTION> = "CRMnnn"`` convention.

The trap (assertion #10, verified against the actual category sets, not
assumed): ``"other"`` and ``"other_physical"`` are BOTH already explicit,
legitimate members of ``OTHER_PHYSICAL_COLLATERAL_TYPES`` --
``["other_physical", "equipment", "inventory", "other"]``
(``data/schemas.py``) -- distinct from the FALLBACK CATEGORY LABEL
``collateral_category_expr`` also happens to call ``"other"``. A row whose
own ``collateral_type`` literally reads ``"other"`` is therefore a
RECOGNISED type (routed to the ``other_physical`` category on purpose, one
step before the ``.otherwise()`` branch), not an unrecognised one, and must
NOT warn.

References:
    docs/plans/irb-collateral-corep-reporting.md, D5
    CRR/PS1-26 Art. 230-231: collateral category -> LGDS waterfall
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import (
    empty_counterparty_lookup,
    normalise_collateral,
    with_ancestor_facilities,
)

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle, CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ErrorCategory, ErrorSeverity
from rwa_calc.data.schemas import (
    COVERED_BOND_COLLATERAL_TYPES,
    FINANCIAL_COLLATERAL_TYPES,
    LIFE_INSURANCE_COLLATERAL_TYPES,
    OTHER_PHYSICAL_COLLATERAL_TYPES,
    REAL_ESTATE_COLLATERAL_TYPES,
    RECEIVABLE_COLLATERAL_TYPES,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# The proposed new error code -- not yet declared in contracts/errors.py.
# See the module docstring for why this file asserts on the literal string.
_ERROR_UNRECOGNISED_COLLATERAL_TYPE = "CRM021"

# The six category sets collateral_category_expr checks, imported directly
# from data/schemas.py (not hand-copied) so this list cannot drift from the
# source. "cash"/"deposit" (the seventh, inline-literal branch in
# collateral_category_expr, not a named schemas.py constant) are already
# members of FINANCIAL_COLLATERAL_TYPES, so they are covered too.
_ALL_KNOWN_TYPES: list[str] = [
    *LIFE_INSURANCE_COLLATERAL_TYPES,
    *COVERED_BOND_COLLATERAL_TYPES,
    *FINANCIAL_COLLATERAL_TYPES,
    *RECEIVABLE_COLLATERAL_TYPES,
    *REAL_ESTATE_COLLATERAL_TYPES,
    *OTHER_PHYSICAL_COLLATERAL_TYPES,
]

# =============================================================================
# Fixtures / helpers
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


def _exposure_row(ref: str = "EXP1", ead: float = 1_000_000.0) -> pl.LazyFrame:
    """One senior corporate F-IRB loan (mirrors test_p1_235's proven shape)."""
    return (
        pl.DataFrame(
            {
                "exposure_reference": [ref],
                "counterparty_reference": ["CP1"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [ead],
                "ead_gross": [ead],
                "lgd": [None],
                "pd": [0.02],
                "maturity_date": [date(2029, 12, 31)],
                "currency": ["GBP"],
                "seniority": ["senior"],
                "exposure_type": ["loan"],
                "nominal_amount": [0.0],
                "interest": [0.0],
                "undrawn_amount": [0.0],
                "risk_type": [None],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "book_code": ["BOOK1"],
                "is_sft": [False],
            }
        )
        .lazy()
        .with_columns(pl.col("parent_facility_reference").cast(pl.String))
    )


def _collateral_row(
    collateral_type: str | None,
    ref: str = "COLL1",
    beneficiary_ref: str = "EXP1",
    market_value: float = 500_000.0,
) -> dict:
    return {
        "collateral_reference": ref,
        "collateral_type": collateral_type,
        "currency": "GBP",
        "market_value": market_value,
        "value_after_maturity_adj": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_ref,
        "maturity_date": date(2035, 12, 31),
        "issuer_type": "",
        "issuer_cqs": 1,
        "is_main_index": False,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 10.0,
        "liquidation_period_days": 10,
    }


def _make_bundle(exposures: pl.LazyFrame, collateral_rows: list[dict]) -> ClassifiedExposuresBundle:
    exposures = with_ancestor_facilities(exposures)
    collateral = normalise_collateral(pl.DataFrame(collateral_rows).lazy())
    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> CRMAdjustedBundle:
    return processor.get_crm_unified_bundle(bundle, config)


def _crm021_warnings(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == _ERROR_UNRECOGNISED_COLLATERAL_TYPE]


# =============================================================================
# 8. An unrecognised collateral_type emits the new warning
# =============================================================================


class TestUnrecognisedTypeWarns:
    """D5 assertion #8: naming the reference and the unrecognised value.

    Uses the exact probe from the plan's evidence: "residential_real_estate"
    is not a member of REAL_ESTATE_COLLATERAL_TYPES (which holds
    "real_estate"/"property"/"rre"/"cre"/"residential"/"commercial" and four
    more), and moves B3.1 RWA 39,848 -> 71,534 on the retail-mortgage
    fixture with no warning today.
    """

    def test_unrecognised_type_raises_new_warning(self, processor: CRMProcessor) -> None:
        # Arrange
        exposures = _exposure_row()
        collateral = [_collateral_row("residential_real_estate", ref="COLL_BAD")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        warnings = _crm021_warnings(result)
        assert len(warnings) == 1
        assert "COLL_BAD" in warnings[0].message
        assert "residential_real_estate" in warnings[0].message


# =============================================================================
# 9. The new warning is a WARNING, not an error; the pipeline continues
# =============================================================================


class TestWarningNotError:
    """D5 assertion #9: this project never raises for data-quality issues."""

    def test_warning_severity_is_warning_not_error(self, processor: CRMProcessor) -> None:
        # Arrange
        exposures = _exposure_row()
        collateral = [_collateral_row("residential_real_estate", ref="COLL_BAD")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        warnings = _crm021_warnings(result)
        assert len(warnings) == 1
        assert warnings[0].severity == ErrorSeverity.WARNING
        assert warnings[0].category == ErrorCategory.CRM

    def test_pipeline_continues_and_exposure_still_reports(self, processor: CRMProcessor) -> None:
        # Arrange
        exposures = _exposure_row()
        collateral = [_collateral_row("residential_real_estate", ref="COLL_BAD")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)
        df = result.exposures.collect()

        # Assert: no exception was raised getting here, and the exposure
        # the collateral secures still reports (not dropped).
        assert df.filter(pl.col("exposure_reference") == "EXP1").height == 1


# =============================================================================
# 10. "other" / "other_physical" are legitimate members and must NOT warn
# =============================================================================


class TestLegitimateOtherPhysicalMembersDoNotWarn:
    """D5 assertion #10: the trap. "other" and "other_physical" are already
    explicit members of OTHER_PHYSICAL_COLLATERAL_TYPES -- distinct from the
    identically-named FALLBACK category collateral_category_expr assigns an
    unrecognised type to."""

    @pytest.mark.parametrize("collateral_type", ["other", "other_physical"])
    def test_type_does_not_warn(self, processor: CRMProcessor, collateral_type: str) -> None:
        # Arrange
        exposures = _exposure_row()
        collateral = [_collateral_row(collateral_type, ref="COLL_OP")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        assert _crm021_warnings(result) == []


# =============================================================================
# 11. Every recognised type across all six sets stays silent
# =============================================================================


class TestRecognisedTypesStaySilent:
    """D5 assertion #11: parametrized over the actual data/schemas.py
    constants collateral_category_expr reads, so this test cannot drift
    from the source."""

    @pytest.mark.parametrize("collateral_type", _ALL_KNOWN_TYPES)
    def test_recognised_type_does_not_warn(
        self, processor: CRMProcessor, collateral_type: str
    ) -> None:
        # Arrange
        exposures = _exposure_row()
        collateral = [_collateral_row(collateral_type, ref="COLL_OK")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        assert _crm021_warnings(result) == []


# =============================================================================
# 12. Case-insensitivity preserved; null collateral_type behaviour pinned
# =============================================================================


class TestCaseInsensitivityAndNullBehaviour:
    """D5 assertion #12: collateral_category_expr matches via
    _coll_type_lower() (case-insensitive); a null collateral_type's
    behaviour is CHECKED first (below) and pinned as-is, not changed by
    this fix."""

    def test_uppercase_recognised_type_does_not_warn(self, processor: CRMProcessor) -> None:
        # Arrange: REAL_ESTATE_COLLATERAL_TYPES holds "real_estate"
        # lower-case; the expression lower-cases collateral_type before
        # matching, so upper-case input must still be recognised.
        exposures = _exposure_row()
        collateral = [_collateral_row("REAL_ESTATE", ref="COLL_UPPER")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        assert _crm021_warnings(result) == []

    def test_mixed_case_unrecognised_type_still_warns(self, processor: CRMProcessor) -> None:
        # Arrange: case-insensitivity must not accidentally suppress a
        # genuinely unrecognised type either.
        exposures = _exposure_row()
        collateral = [_collateral_row("Residential_Real_Estate", ref="COLL_MIXED")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        assert len(_crm021_warnings(result)) == 1

    def test_null_collateral_type_does_not_warn(self, processor: CRMProcessor) -> None:
        """A null collateral_type ALSO falls through collateral_category_expr's
        when-chain to the "other" category today (Kleene null: every
        ``is_in`` test on a null value is null, not True, so no branch
        fires) -- exactly like a genuinely unrecognised string, but this is
        the project's established null-permissive convention (a missing
        value is not asserted to be a data-quality defect), not the D5
        defect itself. Checked empirically before writing this assertion,
        per team-lead's instruction to pin the existing behaviour rather
        than changing it: a null-typed collateral row runs through the full
        CRM pipeline today without error and without any CRM warning.
        """
        # Arrange
        exposures = _exposure_row()
        collateral = [_collateral_row(None, ref="COLL_NULL")]
        bundle = _make_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, _crr_config(), bundle)

        # Assert
        assert _crm021_warnings(result) == []
