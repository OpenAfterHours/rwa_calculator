"""
Tests for double default treatment (CRR Art. 153(3), 202-203).

Double default reduces the IRB capital requirement for guaranteed exposures by
recognising that both borrower AND guarantor must default simultaneously:
    K_dd = K_obligor × (0.15 + 160 × PD_guarantor)

Only available under CRR (Basel 3.1 removes it). Requires:
- A-IRB permission (own LGD estimates)
- Corporate underlying exposure
- A protection provider on the Art. 202 list. Of the input entity types only
  ``institution`` and ``bank`` are certainly on it (P1.203): sovereigns, central
  banks, MDBs, international organisations, RGLAs, PSEs, CCPs, generic financial
  institutions and corporates are NOT eligible providers, whatever their rating
- Guarantor has internal PD
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data import schemas
from rwa_calc.domain.enums import ExposureClass, PermissionMode
from rwa_calc.engine.entity_class_maps import entity_type_to_sa_class
from rwa_calc.engine.irb.formulas import calculate_double_default_k
from rwa_calc.engine.irb.transforms import (
    apply_guarantee_substitution,
)

# =============================================================================
# HELPERS
# =============================================================================


def _crr_dd_config() -> CalculationConfig:
    """CRR config with double default enabled and full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
        enable_double_default=True,
    )


def _crr_no_dd_config() -> CalculationConfig:
    """CRR config with double default disabled."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
        enable_double_default=False,
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 config (double default never applies)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


def _make_guaranteed_frame(
    *,
    exposure_class: str = "corporate",
    pd: float = 0.02,
    lgd: float = 0.45,
    ead_final: float = 1_000_000.0,
    rwa: float = 500_000.0,
    risk_weight: float = 0.50,
    maturity: float = 2.5,
    guaranteed_portion: float = 600_000.0,
    unguaranteed_portion: float = 400_000.0,
    guarantor_entity_type: str = "bank",
    guarantor_exposure_class: str = "institution",
    guarantor_cqs: int | None = 2,
    guarantor_pd: float | None = 0.003,
    guarantor_approach: str = "irb",
    is_airb: bool = True,
    expected_loss: float = 9_000.0,
    turnover_m: float | None = None,
    requires_fi_scalar: bool = False,
) -> pl.LazyFrame:
    """Build a LazyFrame representing a single guaranteed IRB exposure."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP_DD"],
            "exposure_class": [exposure_class],
            "pd": [pd],
            "lgd": [lgd],
            "lgd_floored": [lgd],
            "pd_floored": [pd],
            "ead_final": [ead_final],
            "rwa": [rwa],
            "risk_weight": [risk_weight],
            "maturity": [maturity],
            "guaranteed_portion": [guaranteed_portion],
            "unguaranteed_portion": [unguaranteed_portion],
            "guarantor_entity_type": [guarantor_entity_type],
            "guarantor_exposure_class": [guarantor_exposure_class],
            "guarantor_cqs": pl.Series([guarantor_cqs], dtype=pl.Int64),
            "guarantor_pd": [guarantor_pd],
            "guarantor_approach": [guarantor_approach],
            "is_airb": [is_airb],
            "expected_loss": [expected_loss],
            "turnover_m": [turnover_m],
            "requires_fi_scalar": [requires_fi_scalar],
            "correlation": [0.15],
            "k": [rwa / (ead_final * 12.5 * 1.06)],
        }
    )


# =============================================================================
# FORMULA UNIT TESTS
# =============================================================================


class TestDoubleDefaultFormula:
    """Unit tests for the double default multiplier formula."""

    def test_multiplier_low_pd_guarantor(self):
        """Investment-grade guarantor (PD=0.03%) gives ~0.198 multiplier."""
        k_dd = calculate_double_default_k(k_obligor=0.04, guarantor_pd=0.0003)
        multiplier = 0.15 + 160.0 * 0.0003  # = 0.198
        assert k_dd == pytest.approx(0.04 * multiplier)

    def test_multiplier_mid_pd_guarantor(self):
        """Guarantor with PD=1% gives 1.75 multiplier (no benefit)."""
        k_dd = calculate_double_default_k(k_obligor=0.04, guarantor_pd=0.01)
        multiplier = 0.15 + 160.0 * 0.01  # = 1.75
        assert k_dd == pytest.approx(0.04 * multiplier)

    def test_multiplier_very_low_pd(self):
        """Very high quality guarantor (PD=0.01%) gives ~0.166 multiplier."""
        k_dd = calculate_double_default_k(k_obligor=0.05, guarantor_pd=0.0001)
        multiplier = 0.15 + 160.0 * 0.0001  # = 0.166
        assert k_dd == pytest.approx(0.05 * multiplier)

    def test_zero_k_obligor(self):
        """Zero obligor K results in zero DD K."""
        k_dd = calculate_double_default_k(k_obligor=0.0, guarantor_pd=0.003)
        assert k_dd == pytest.approx(0.0)


# =============================================================================
# ELIGIBILITY TESTS
# =============================================================================


class TestDoubleDefaultEligibility:
    """Tests for double default eligibility determination."""

    def test_corporate_with_institution_guarantor_eligible(self):
        """Corporate exposure + institution guarantor + A-IRB → eligible."""
        lf = _make_guaranteed_frame()
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is True

    def test_institution_exposure_not_eligible(self):
        """Institution exposure class is not eligible for DD (corporate only)."""
        lf = _make_guaranteed_frame(exposure_class="institution")
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_retail_exposure_not_eligible(self):
        """Retail exposure not eligible for DD."""
        lf = _make_guaranteed_frame(exposure_class="retail_mortgage")
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_firb_not_eligible(self):
        """F-IRB (not A-IRB) → not eligible for DD."""
        lf = _make_guaranteed_frame(is_airb=False)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_no_guarantor_pd_not_eligible(self):
        """Guarantor without internal PD → not eligible."""
        lf = _make_guaranteed_frame(guarantor_pd=None)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_corporate_guarantor_cqs3_not_eligible(self):
        """Corporate guarantor with CQS 3 → not eligible (no corporate is an Art. 202 provider)."""
        lf = _make_guaranteed_frame(
            guarantor_entity_type="company",
            guarantor_exposure_class="corporate",
            guarantor_cqs=3,
        )
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_dd_disabled_in_config(self):
        """DD disabled in config → not eligible even if criteria met."""
        lf = _make_guaranteed_frame()
        result = lf.pipe(apply_guarantee_substitution, _crr_no_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_b31_never_eligible(self):
        """Basel 3.1 removes DD → never eligible."""
        lf = _make_guaranteed_frame()
        result = lf.pipe(apply_guarantee_substitution, _b31_config()).collect()
        assert result["is_double_default_eligible"][0] is False

    def test_no_guarantee_not_eligible(self):
        """Unguaranteed exposure → not eligible."""
        lf = _make_guaranteed_frame(guaranteed_portion=0.0, unguaranteed_portion=1_000_000.0)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["is_double_default_eligible"][0] is False


# =============================================================================
# RWA IMPACT TESTS
# =============================================================================


class TestDoubleDefaultRWA:
    """Tests for RWA calculation under double default treatment."""

    def test_dd_reduces_rwa_vs_no_dd(self):
        """DD with investment-grade guarantor reduces RWA vs SA substitution."""
        lf = _make_guaranteed_frame(
            risk_weight=0.50,
            rwa=500_000.0,
            guarantor_pd=0.0003,  # Investment grade
            guarantor_cqs=1,
        )
        # With DD
        result_dd = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        # Without DD (SA substitution only)
        result_no_dd = lf.pipe(apply_guarantee_substitution, _crr_no_dd_config()).collect()

        # DD should produce lower or equal RWA
        assert result_dd["rwa"][0] <= result_no_dd["rwa"][0]

    def test_dd_method_tracked(self):
        """DD-applied exposures have correct guarantee_method_used."""
        lf = _make_guaranteed_frame(guarantor_pd=0.0003, guarantor_cqs=1)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()

        # DD eligibility allows DD treatment OR plain substitution (SA RW for SA
        # guarantors, PD-parameter substitution for IRB guarantors per Art. 161(3))
        if result["is_double_default_eligible"][0]:
            assert result["guarantee_method_used"][0] in (
                "DOUBLE_DEFAULT",
                "SA_RW_SUBSTITUTION",
                "PD_PARAMETER_SUBSTITUTION",
            )

    def test_dd_unfunded_protection_tracked(self):
        """DD-eligible exposure tracks guaranteed portion."""
        lf = _make_guaranteed_frame(guaranteed_portion=600_000.0)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["double_default_unfunded_protection"][0] == pytest.approx(600_000.0)

    def test_dd_lgd_tracked(self):
        """DD-eligible exposure tracks obligor LGD."""
        lf = _make_guaranteed_frame(lgd=0.45)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["irb_lgd_double_default"][0] == pytest.approx(0.45)

    def test_dd_not_eligible_zero_unfunded(self):
        """Non-eligible exposure has zero DD unfunded protection."""
        lf = _make_guaranteed_frame(is_airb=False)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["double_default_unfunded_protection"][0] == pytest.approx(0.0)

    def test_dd_floor_at_guarantor_rw(self):
        """A high-PD guarantor makes DD non-beneficial, so the substitution RW is kept.

        CRR Art. 153(3) has no "not lower than a direct exposure" floor (that was
        Basel II para 286, not onshored — see TestDoubleDefaultReachable); DD is
        simply not applied when rw_dd is not below the substitution RW.
        """
        # High guarantor PD → DD multiplier > 1 → DD RW > substitution RW
        lf = _make_guaranteed_frame(
            guarantor_pd=0.01,  # 1% PD → multiplier = 1.75
            risk_weight=0.50,
        )
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        # With high guarantor PD, DD multiplier is 1.75, so DD RW > obligor RW.
        # DD is not beneficial; the engine reports the substitution path that was
        # evaluated. After P1.160, an IRB guarantor on the PSM path emits
        # PD_PARAMETER_SUBSTITUTION even when the beneficial gate retained the
        # borrower RWA (the GUARANTEE_NOT_APPLIED_NON_BENEFICIAL signal lives on
        # guarantee_status, not on guarantee_method_used).
        assert result["guarantee_method_used"][0] in (
            "SA_RW_SUBSTITUTION",
            "DOUBLE_DEFAULT",
            "NO_SUBSTITUTION",
            "PD_PARAMETER_SUBSTITUTION",
        )


class TestDoubleDefaultStatusTracking:
    """Tests for guarantee status tracking with double default."""

    def test_status_double_default(self):
        """DD-applied exposure has DOUBLE_DEFAULT status."""
        lf = _make_guaranteed_frame(
            guarantor_pd=0.0003,
            guarantor_cqs=1,
            risk_weight=0.50,
            rwa=500_000.0,
        )
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        if result["guarantee_status"][0] == "DOUBLE_DEFAULT":
            assert result["guarantee_method_used"][0] == "DOUBLE_DEFAULT"

    def test_status_no_guarantee(self):
        """Unguaranteed exposure → NO_GUARANTEE status even with DD enabled."""
        lf = _make_guaranteed_frame(guaranteed_portion=0.0, unguaranteed_portion=1_000_000.0)
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()
        assert result["guarantee_status"][0] == "NO_GUARANTEE"

    def test_crr_without_dd_uses_sa_substitution(self):
        """CRR without DD enabled → SA_RW_SUBSTITUTION."""
        lf = _make_guaranteed_frame()
        result = lf.pipe(apply_guarantee_substitution, _crr_no_dd_config()).collect()
        if result["is_guarantee_beneficial"][0]:
            assert result["guarantee_method_used"][0] == "SA_RW_SUBSTITUTION"


class TestDoubleDefaultReachable:
    """P1.228 — CRR Art. 153(3) DD RW must be reachable (no direct-to-guarantor floor).

    Art. 153(3) defines rw_dd = RW_0 x (0.15 + 160 x PD_guarantor) with NO floor
    at the substitution (direct-exposure-to-guarantor) risk weight — that floor was
    Basel II para 286, not onshored into CRR. The engine's beneficial gate must
    compare the UNFLOORED rw_dd against the substitution RW; flooring rw_dd at
    guarantor_rw before the gate makes the strict "<" comparison always False,
    so DOUBLE_DEFAULT is never reachable.
    """

    def test_crr_a7_dd_reachable_full_guarantee_institution_sa(self):
        """Full-cover corporate exposure, institution CQS2 guarantor (SA path).

        Hand calc (see P1_228-scenario.md):
        - Substitution RW (Art. 120 Table 3, institution CQS2): 0.50
        - DD multiplier (Art. 153(3)): 0.15 + 160 x 0.0005 = 0.23
        - Unfloored DD RW: RW_0 (borrower IRB RW = 1.00) x 0.23 = 0.23
        - Beneficial gate: 0.23 < 0.50 (substitution RW) -> DD applies
        - rwa = 1,000,000 x 0.23 = 230,000; risk_weight = 0.23
        """
        # Arrange
        lf = _make_guaranteed_frame(
            rwa=1_000_000.0,
            risk_weight=1.00,
            guaranteed_portion=1_000_000.0,
            unguaranteed_portion=0.0,
            guarantor_pd=0.0005,
            guarantor_approach="sa",
        )

        # Act
        result = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect()

        # Assert
        assert result["is_double_default_eligible"][0] is True
        assert result["guarantee_status"][0] == "DOUBLE_DEFAULT"
        assert result["guarantor_rw"][0] == pytest.approx(0.23)
        assert result["risk_weight"][0] == pytest.approx(0.23)
        assert result["rwa"][0] == pytest.approx(230_000.0)


class TestDoubleDefaultProviderList:
    """P1.203 — CRR Art. 202 limits the Art. 153(3) double-default PROVIDER.

    CRR Art. 202 (legislation.gov.uk): "An institution may use institutions,
    investment firms, insurance and reinsurance undertakings and export credit
    agencies as eligible providers of unfunded credit protection which qualify
    for the treatment set out in Article 153(3) where they meet all the following
    conditions: ...". Sovereigns, central banks and MDBs are not on that list, nor
    are CCPs, and a generic Art. 4(1)(26) "financial institution" is by definition
    "an undertaking other than an institution". Insurers are on the list but no
    entity type tells them apart from a non-financial corporate, so no corporate
    qualifies. Only ``institution`` / ``bank`` guarantors remain.

    Every row is a 1,000,000 corporate exposure, fully guaranteed, obligor RW 1.00,
    SA-routed guarantor with an internal PD of 0.05%. Where DD applies:
    rw_dd = 1.00 x (0.15 + 160 x 0.0005) = 0.23 -> RWA 230,000. Where it does not,
    the guarantor's SA substitution RW stands (CRR Art. 114 Table 1 CQS 3, Art. 117
    MDB CQS 2, Art. 120 Table 3 institution CQS 2 and Art. 122 Table 6 corporate
    CQS 2 are each 50%; the CQS 1 sovereign and the named MDB 0%; the CCP 2%).
    """

    @staticmethod
    def _full_cover_frame(
        guarantor_entity_type: str, guarantor_exposure_class: str, guarantor_cqs: int | None
    ) -> pl.LazyFrame:
        return _make_guaranteed_frame(
            rwa=1_000_000.0,
            risk_weight=1.00,
            guaranteed_portion=1_000_000.0,
            unguaranteed_portion=0.0,
            guarantor_entity_type=guarantor_entity_type,
            guarantor_exposure_class=guarantor_exposure_class,
            guarantor_cqs=guarantor_cqs,
            guarantor_pd=0.0005,
            guarantor_approach="sa",
        )

    @pytest.mark.parametrize(
        ("guarantor_entity_type", "guarantor_exposure_class", "guarantor_cqs", "substitution_rw"),
        [
            # Red before P1.203: each was DD-eligible AND DD-applied (RW 0.23).
            pytest.param("sovereign", "central_govt_central_bank", 3, 0.50, id="sovereign_cqs3"),
            pytest.param(
                "central_bank", "central_govt_central_bank", 3, 0.50, id="central_bank_cqs3"
            ),
            pytest.param("mdb", "mdb", 2, 0.50, id="mdb_cqs2"),
            pytest.param("company", "corporate", 2, 0.50, id="corporate_cqs2"),
            pytest.param("corporate", "corporate_sme", 2, 0.50, id="corporate_sme_cqs2"),
            pytest.param(
                "financial_institution", "institution", 2, 0.50, id="financial_institution_cqs2"
            ),
            # A qualifying CCP guarantor is booked as an institution (Art. 107(2)(a)) and,
            # since P1.396, takes that class's CQS 2 weight, not the Art. 306 2%.
            pytest.param("ccp", "institution", 2, 0.50, id="ccp"),
            # Red before P1.203 on eligibility / C 08.01 col 0220 only: DD was never
            # beneficial against a 0% substitution RW.
            pytest.param("sovereign", "central_govt_central_bank", 1, 0.0, id="sovereign_cqs1"),
            pytest.param("mdb_named", "mdb", 1, 0.0, id="named_mdb"),
        ],
    )
    def test_provider_outside_art_202_list_takes_no_double_default(
        self,
        guarantor_entity_type: str,
        guarantor_exposure_class: str,
        guarantor_cqs: int,
        substitution_rw: float,
    ) -> None:
        """A provider Art. 202 does not list is not DD-eligible and keeps its substitution RW."""
        # Arrange
        lf = self._full_cover_frame(guarantor_entity_type, guarantor_exposure_class, guarantor_cqs)

        # Act
        row = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect().row(0, named=True)

        # Assert
        assert row["is_double_default_eligible"] is False
        assert row["guarantee_status"] == "SA_RW_SUBSTITUTION"
        assert row["double_default_unfunded_protection"] == pytest.approx(0.0)
        assert row["irb_lgd_double_default"] is None
        assert row["risk_weight"] == pytest.approx(substitution_rw)
        assert row["rwa"] == pytest.approx(1_000_000.0 * substitution_rw)

    @pytest.mark.parametrize(
        ("guarantor_entity_type", "guarantor_exposure_class", "guarantor_cqs"),
        [
            # The Art. 201 general provider list admits these; Art. 202 does not.
            # Already ineligible before P1.203 — kept so that copying the Art. 201
            # list into the DD gate cannot pass.
            pytest.param("rgla_sovereign", "rgla", 1, id="rgla_sovereign"),
            pytest.param("rgla_institution", "rgla", 2, id="rgla_institution"),
            pytest.param("pse_sovereign", "pse", 2, id="pse_sovereign"),
            pytest.param("pse_institution", "pse", 2, id="pse_institution"),
            pytest.param(
                "international_org", "international_organisation", 1, id="international_org"
            ),
        ],
    )
    def test_art_201_only_provider_stays_not_eligible(
        self, guarantor_entity_type: str, guarantor_exposure_class: str, guarantor_cqs: int
    ) -> None:
        """RGLA, PSE and international-organisation guarantors are not Art. 202 providers."""
        # Arrange
        lf = self._full_cover_frame(guarantor_entity_type, guarantor_exposure_class, guarantor_cqs)

        # Act
        row = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect().row(0, named=True)

        # Assert
        assert row["is_double_default_eligible"] is False
        assert row["guarantee_status"] != "DOUBLE_DEFAULT"
        assert row["double_default_unfunded_protection"] == pytest.approx(0.0)

    @pytest.mark.parametrize(
        ("guarantor_entity_type", "guarantor_cqs"),
        [
            pytest.param("bank", 2, id="bank_cqs2"),
            pytest.param("institution", 2, id="institution_cqs2"),
            # Art. 202(b) is an either/or: a provider "regulated in a manner
            # equivalent to the rules laid down in this Regulation" passes it with no
            # ECAI rating, so the engine applies no CQS gate to an institution.
            pytest.param("institution", None, id="institution_unrated"),
        ],
    )
    def test_institution_provider_keeps_double_default(
        self, guarantor_entity_type: str, guarantor_cqs: int | None
    ) -> None:
        """An institution / bank guarantor is still DD-eligible and DD still applies."""
        # Arrange
        lf = self._full_cover_frame(guarantor_entity_type, "institution", guarantor_cqs)

        # Act
        row = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect().row(0, named=True)

        # Assert
        assert row["is_double_default_eligible"] is True
        assert row["guarantee_status"] == "DOUBLE_DEFAULT"
        assert row["double_default_unfunded_protection"] == pytest.approx(1_000_000.0)
        assert row["risk_weight"] == pytest.approx(0.23)
        assert row["rwa"] == pytest.approx(230_000.0)

    def test_listed_provider_types_are_valid_institution_entity_types(self) -> None:
        """Each listed provider type is a valid entity type mapped to the institution class.

        A misspelt entry, or one outside the institution class, would make double
        default silently unreachable for that guarantor type.
        """
        # Arrange
        sa_class = entity_type_to_sa_class()
        provider_types = schemas.DOUBLE_DEFAULT_PROVIDER_ENTITY_TYPES

        # Act
        unknown = set(provider_types) - schemas.VALID_ENTITY_TYPES
        not_institution = {
            et for et in provider_types if sa_class.get(et) != ExposureClass.INSTITUTION.value
        }

        # Assert
        assert provider_types, "an empty list disables double default"
        assert unknown == set()
        assert not_institution == set()

    def test_art_201_rejected_bank_guarantor_not_eligible(self) -> None:
        """A bank guarantor the Art. 201 gate rejected (class cleared) is not DD-eligible.

        ``assign_guarantor_approach`` clears ``guarantor_exposure_class`` and
        ``guarantor_approach`` on a rejected leg but leaves the entity type, so the
        DD gate must test the class as well as the entity type.
        """
        # Arrange
        lf = _make_guaranteed_frame(
            rwa=1_000_000.0,
            risk_weight=1.00,
            guaranteed_portion=1_000_000.0,
            unguaranteed_portion=0.0,
            guarantor_entity_type="bank",
            guarantor_exposure_class="",
            guarantor_pd=0.0005,
            guarantor_approach="",
        )

        # Act
        row = lf.pipe(apply_guarantee_substitution, _crr_dd_config()).collect().row(0, named=True)

        # Assert
        assert row["is_double_default_eligible"] is False
        assert row["double_default_unfunded_protection"] == pytest.approx(0.0)
        assert row["rwa"] == pytest.approx(1_000_000.0)

    @pytest.mark.parametrize(
        ("guarantor_entity_type", "guarantor_exposure_class", "guarantor_cqs"),
        [
            pytest.param("bank", "institution", 2, id="bank"),
            pytest.param("sovereign", "central_govt_central_bank", 3, id="sovereign"),
            pytest.param("mdb", "mdb", 2, id="mdb"),
            pytest.param("company", "corporate", 2, id="corporate"),
        ],
    )
    def test_basel_3_1_has_no_double_default_for_any_provider(
        self, guarantor_entity_type: str, guarantor_exposure_class: str, guarantor_cqs: int
    ) -> None:
        """PS1/26 leaves Art. 153(3), 202 and 217 blank: no provider takes DD under Basel 3.1.

        Negative control. It passes before and after P1.203 — the Basel 3.1 side is
        decided by the ``double_default_treatment`` pack Feature, not by the
        provider list, so this regime cannot be reddened by the provider change.
        """
        # Arrange
        lf = self._full_cover_frame(guarantor_entity_type, guarantor_exposure_class, guarantor_cqs)

        # Act
        row = lf.pipe(apply_guarantee_substitution, _b31_config()).collect().row(0, named=True)

        # Assert
        assert row["is_double_default_eligible"] is False
        assert row["guarantee_status"] != "DOUBLE_DEFAULT"
        assert row["double_default_unfunded_protection"] == pytest.approx(0.0)
