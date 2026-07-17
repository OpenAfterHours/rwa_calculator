"""
P1.270 — Art. 194(4): own-issue / connected-issuer collateral is ineligible.

CRR/PS1-26 Art. 194(4) admits funded credit protection only where its value is
not materially positively correlated with the obligor's credit quality. The
canonical ineligible case (BCBS CRE22) is a security ISSUED by the obligor — or
by a member of the obligor's group — pledged back as collateral: if the obligor
defaults the security is worthless exactly when the protection is needed.

The new optional `issuer_counterparty_reference` field identifies the collateral
security's issuer. When it resolves to the obligor, or to a counterparty sharing
the obligor's ultimate parent, the CRM engine zeroes the collateral (no benefit)
and raises a CRM015 data-quality warning. Null issuer is PERMISSIVE.

Pipeline position:
    tests/unit — direct CRMProcessor.get_crm_unified_bundle drive.

References:
    - CRR/PS1-26 Art. 194(4): correlation / connected-issuer ineligibility.
    - BCBS CRE22: own-issued securities expressly ineligible.
    - IMPLEMENTATION_PLAN.md: P1.270.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle, make_counterparty_lookup
from tests.unit.crm._crm_bundles import normalise_collateral, with_ancestor_facilities

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    CRMAdjustedBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_OWN_ISSUE_COLLATERAL
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def firb_crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


def _create_bundle(
    issuer_counterparty_reference: str | None,
    *,
    counterparty_lookup: CounterpartyLookup | None = None,
    obligor_ref: str = "CP1",
    parent_facility_ref: str | None = None,
    beneficiary_type: str = "loan",
    beneficiary_reference: str = "EXP1",
) -> ClassifiedExposuresBundle:
    """FIRB corporate exposure secured by a CQS1 corporate bond.

    ``issuer_counterparty_reference`` drives the Art. 194(4) gate. A recognised
    bond carries a positive post-haircut ``collateral_adjusted_value``; when the
    gate zeroes the bond, that value collapses to 0 (no CRM benefit).

    ``beneficiary_type`` / ``beneficiary_reference`` set the pledge level so the
    obligor-map union (exposure / facility / counterparty keys) can be exercised;
    ``parent_facility_ref`` gives the exposure a facility ancestor for the
    facility-level case.
    """
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": [obligor_ref],
            "parent_facility_reference": [parent_facility_ref],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "approach": [ApproachType.FIRB.value],
            "drawn_amount": [10_000_000.0],
            "ead_gross": [10_000_000.0],
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
    ).lazy()
    exposures = exposures.with_columns(pl.col("parent_facility_reference").cast(pl.String))
    exposures = with_ancestor_facilities(exposures)

    collateral = normalise_collateral(
        pl.DataFrame(
            {
                "collateral_reference": ["BOND1"],
                "collateral_type": ["bond"],
                "currency": ["GBP"],
                "market_value": [20_000_000.0],
                "value_after_maturity_adj": [None],
                "beneficiary_type": [beneficiary_type],
                "beneficiary_reference": [beneficiary_reference],
                "issuer_type": ["corporate"],
                "issuer_cqs": [1],
                "is_main_index": [False],
                "is_eligible_financial_collateral": [True],
                "is_eligible_irb_collateral": [True],
                "issuer_counterparty_reference": [issuer_counterparty_reference],
                "residual_maturity_years": [10.0],
                "liquidation_period_days": [10],
            },
            schema_overrides={"issuer_counterparty_reference": pl.String},
        ).lazy()
    )

    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=counterparty_lookup or create_empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> CRMAdjustedBundle:
    return processor.get_crm_unified_bundle(bundle, config)


def _collateral_adjusted_value(result: CRMAdjustedBundle) -> float:
    """The post-haircut collateral value attributed to the exposure.

    The Art. 194(4) gate zeroes the collateral's market_value, which cascades to
    this value — so it is 0 for a gated (own-issue) row and > 0 for a recognised
    one, independent of the downstream LGD/EAD categorisation.
    """
    row = result.exposures.collect().filter(pl.col("exposure_reference") == "EXP1")
    return row["collateral_adjusted_value"][0]


def _crm015_errors(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == ERROR_OWN_ISSUE_COLLATERAL]


class TestOwnIssueGate:
    """Art. 194(4): collateral issued by the obligor is ineligible."""

    def test_third_party_bond_recognised(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Control: a bond issued by an unrelated third party is recognised (value > 0)."""
        bundle = _create_bundle("BANK_X")

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) > 0.0
        assert _crm015_errors(result) == []

    def test_null_issuer_permissive(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Null issuer is permissive — the bond is recognised (no gate fires)."""
        bundle = _create_bundle(None)

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) > 0.0
        assert _crm015_errors(result) == []

    def test_own_issue_bond_zeroed(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: a bond issued by the obligor itself is zeroed (no CRM benefit)."""
        bundle = _create_bundle("CP1")  # issuer == obligor

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) == pytest.approx(0.0, abs=1e-6)

    def test_own_issue_bond_emits_crm015(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Own-issue collateral accumulates exactly one CRM015 warning (never raised)."""
        bundle = _create_bundle("CP1")

        result = _run_crm(processor, firb_crr_config, bundle)

        warnings = _crm015_errors(result)
        assert len(warnings) == 1
        assert warnings[0].exposure_reference == "EXP1"
        assert warnings[0].regulatory_reference == "CRR Art. 194(4)"


class TestConnectedIssuerGroupGate:
    """Art. 194(4): collateral issued by a group member (shared ultimate parent)."""

    @staticmethod
    def _group_lookup() -> CounterpartyLookup:
        # CP1 (obligor) and CP1_SISTER (issuer) share ultimate parent GROUP1.
        upm = pl.DataFrame(
            {
                "counterparty_reference": ["CP1", "CP1_SISTER"],
                "ultimate_parent_reference": ["GROUP1", "GROUP1"],
                "hierarchy_depth": [1, 1],
            }
        )
        return make_counterparty_lookup(ultimate_parent_mappings=upm)

    def test_group_member_bond_zeroed(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: a bond issued by a sister company (shared parent) is zeroed."""
        bundle = _create_bundle("CP1_SISTER", counterparty_lookup=self._group_lookup())

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) == pytest.approx(0.0, abs=1e-6)

    def test_group_member_bond_emits_crm015(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """The group-member case raises the same CRM015 warning."""
        bundle = _create_bundle("CP1_SISTER", counterparty_lookup=self._group_lookup())

        result = _run_crm(processor, firb_crr_config, bundle)

        assert len(_crm015_errors(result)) == 1

    def test_unrelated_issuer_with_group_lookup_recognised(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Control: an issuer outside the obligor's group is still recognised."""
        bundle = _create_bundle("BANK_X", counterparty_lookup=self._group_lookup())

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) > 0.0
        assert _crm015_errors(result) == []


class TestMultiLevelPledgeResolution:
    """The obligor-map union resolves the obligor at every pledge level (Art. 194(4)).

    ``_build_beneficiary_obligor_map`` unions exposure / facility / counterparty
    key spaces, so an own-issue match must fire whether the collateral is pledged
    against the loan, its parent facility, or the counterparty — not just the
    exposure-level case the earlier tests exercise.
    """

    def test_facility_level_own_issue_filtered(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: facility-level collateral issued by the obligor is filtered.

        The bond's beneficiary is the parent FACILITY (not the exposure), so the
        obligor is resolved via the map's ``parent_facility_reference`` key space.
        """
        bundle = _create_bundle(
            "CP1",
            parent_facility_ref="FAC1",
            beneficiary_type="facility",
            beneficiary_reference="FAC1",
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) == pytest.approx(0.0, abs=1e-6)
        assert len(_crm015_errors(result)) == 1

    def test_facility_level_third_party_recognised(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Control: facility-level collateral from a third party is still recognised."""
        bundle = _create_bundle(
            "BANK_X",
            parent_facility_ref="FAC1",
            beneficiary_type="facility",
            beneficiary_reference="FAC1",
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) > 0.0
        assert _crm015_errors(result) == []

    def test_counterparty_level_own_issue_filtered(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: counterparty-level collateral issued by the obligor is filtered.

        The bond's beneficiary is the obligor COUNTERPARTY directly, so the obligor
        is resolved via the map's identity (``counterparty_reference``) key space.
        """
        bundle = _create_bundle(
            "CP1",
            beneficiary_type="counterparty",
            beneficiary_reference="CP1",
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _collateral_adjusted_value(result) == pytest.approx(0.0, abs=1e-6)
        assert len(_crm015_errors(result)) == 1
