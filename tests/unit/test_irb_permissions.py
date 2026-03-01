"""Unit tests for IRBPermissions factory methods.

Tests cover:
- sa_only(): No IRB permissions
- firb_only(): Foundation IRB only (retail falls back to SA)
- airb_only(): Advanced IRB only (specialised lending uses slotting)
- full_irb(): Both FIRB and AIRB permitted
"""

from __future__ import annotations

from rwa_calc.contracts.config import IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass

# =============================================================================
# SA Only Tests
# =============================================================================


class TestSAOnlyPermissions:
    """Tests for IRBPermissions.sa_only() factory method."""

    def test_sa_only_returns_empty_permissions(self) -> None:
        """SA only should return empty permissions dict."""
        permissions = IRBPermissions.sa_only()
        assert permissions.permissions == {}

    def test_sa_only_allows_sa_for_all_classes(self) -> None:
        """SA only should allow SA approach for all exposure classes."""
        permissions = IRBPermissions.sa_only()

        for exposure_class in ExposureClass:
            # SA should be permitted (default when no permissions defined)
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            # IRB approaches should not be permitted
            assert not permissions.is_permitted(exposure_class, ApproachType.FIRB)
            assert not permissions.is_permitted(exposure_class, ApproachType.AIRB)

    def test_sa_only_get_permitted_approaches(self) -> None:
        """get_permitted_approaches should return only SA for SA-only config."""
        permissions = IRBPermissions.sa_only()

        for exposure_class in ExposureClass:
            permitted = permissions.get_permitted_approaches(exposure_class)
            assert permitted == {ApproachType.SA}


# =============================================================================
# FIRB Only Tests
# =============================================================================


class TestFIRBOnlyPermissions:
    """Tests for IRBPermissions.firb_only() factory method."""

    def test_firb_only_allows_firb_for_non_retail(self) -> None:
        """FIRB only should allow FIRB for non-retail classes."""
        permissions = IRBPermissions.firb_only()

        # Non-retail classes should have FIRB permitted
        non_retail_irb_classes = [
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK,
            ExposureClass.INSTITUTION,
            ExposureClass.CORPORATE,
            ExposureClass.CORPORATE_SME,
        ]

        for exposure_class in non_retail_irb_classes:
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            assert permissions.is_permitted(exposure_class, ApproachType.FIRB)
            assert not permissions.is_permitted(exposure_class, ApproachType.AIRB)

    def test_firb_only_retail_falls_back_to_sa(self) -> None:
        """FIRB only should have retail classes fall back to SA (FIRB not permitted)."""
        permissions = IRBPermissions.firb_only()

        retail_classes = [
            ExposureClass.RETAIL_MORTGAGE,
            ExposureClass.RETAIL_QRRE,
            ExposureClass.RETAIL_OTHER,
        ]

        for exposure_class in retail_classes:
            permitted = permissions.get_permitted_approaches(exposure_class)
            # Retail should only have SA (FIRB not permitted for retail per CRE30.1)
            assert permitted == {ApproachType.SA}
            assert not permissions.is_permitted(exposure_class, ApproachType.FIRB)
            assert not permissions.is_permitted(exposure_class, ApproachType.AIRB)

    def test_firb_only_specialised_lending_allows_firb_and_slotting(self) -> None:
        """FIRB only should allow FIRB and slotting for specialised lending."""
        permissions = IRBPermissions.firb_only()

        permitted = permissions.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)
        assert ApproachType.SA in permitted
        assert ApproachType.FIRB in permitted
        assert ApproachType.SLOTTING in permitted
        assert ApproachType.AIRB not in permitted

    def test_firb_only_equity_sa_only(self) -> None:
        """FIRB only should have equity using SA only (IRB removed under Basel 3.1)."""
        permissions = IRBPermissions.firb_only()

        permitted = permissions.get_permitted_approaches(ExposureClass.EQUITY)
        assert permitted == {ApproachType.SA}

    def test_firb_only_no_airb_anywhere(self) -> None:
        """FIRB only should not permit AIRB for any exposure class."""
        permissions = IRBPermissions.firb_only()

        for exposure_class in ExposureClass:
            assert not permissions.is_permitted(exposure_class, ApproachType.AIRB)


# =============================================================================
# AIRB Only Tests
# =============================================================================


class TestAIRBOnlyPermissions:
    """Tests for IRBPermissions.airb_only() factory method."""

    def test_airb_only_allows_airb_for_applicable_classes(self) -> None:
        """AIRB only should allow AIRB for applicable classes."""
        permissions = IRBPermissions.airb_only()

        airb_classes = [
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK,
            ExposureClass.INSTITUTION,
            ExposureClass.CORPORATE,
            ExposureClass.CORPORATE_SME,
            ExposureClass.RETAIL_MORTGAGE,
            ExposureClass.RETAIL_QRRE,
            ExposureClass.RETAIL_OTHER,
        ]

        for exposure_class in airb_classes:
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            assert permissions.is_permitted(exposure_class, ApproachType.AIRB)
            assert not permissions.is_permitted(exposure_class, ApproachType.FIRB)

    def test_airb_only_specialised_lending_uses_slotting(self) -> None:
        """AIRB only should have specialised lending use slotting (no AIRB per CRE33.5)."""
        permissions = IRBPermissions.airb_only()

        permitted = permissions.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)
        assert ApproachType.SA in permitted
        assert ApproachType.SLOTTING in permitted
        # AIRB not permitted for specialised lending
        assert ApproachType.AIRB not in permitted
        assert ApproachType.FIRB not in permitted

    def test_airb_only_equity_sa_only(self) -> None:
        """AIRB only should have equity using SA only."""
        permissions = IRBPermissions.airb_only()

        permitted = permissions.get_permitted_approaches(ExposureClass.EQUITY)
        assert permitted == {ApproachType.SA}

    def test_airb_only_no_firb_anywhere(self) -> None:
        """AIRB only should not permit FIRB for any exposure class."""
        permissions = IRBPermissions.airb_only()

        for exposure_class in ExposureClass:
            assert not permissions.is_permitted(exposure_class, ApproachType.FIRB)


# =============================================================================
# Full IRB Tests
# =============================================================================


class TestFullIRBPermissions:
    """Tests for IRBPermissions.full_irb() factory method."""

    def test_full_irb_allows_both_firb_and_airb_for_corporates(self) -> None:
        """Full IRB should allow both FIRB and AIRB for corporate classes."""
        permissions = IRBPermissions.full_irb()

        corporate_classes = [
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK,
            ExposureClass.INSTITUTION,
            ExposureClass.CORPORATE,
            ExposureClass.CORPORATE_SME,
        ]

        for exposure_class in corporate_classes:
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            assert permissions.is_permitted(exposure_class, ApproachType.FIRB)
            assert permissions.is_permitted(exposure_class, ApproachType.AIRB)

    def test_full_irb_retail_has_airb_only(self) -> None:
        """Full IRB should have retail classes with AIRB only (no FIRB)."""
        permissions = IRBPermissions.full_irb()

        retail_classes = [
            ExposureClass.RETAIL_MORTGAGE,
            ExposureClass.RETAIL_QRRE,
            ExposureClass.RETAIL_OTHER,
        ]

        for exposure_class in retail_classes:
            permitted = permissions.get_permitted_approaches(exposure_class)
            assert ApproachType.SA in permitted
            assert ApproachType.AIRB in permitted
            # FIRB not permitted for retail
            assert ApproachType.FIRB not in permitted

    def test_full_irb_specialised_lending_has_all_approaches(self) -> None:
        """Full IRB should have specialised lending with FIRB, slotting, and AIRB.

        Under CRR Art. 153(5), firms can use A-IRB for specialised lending if they
        can reliably estimate PD. Only when PD cannot be estimated must firms fall back
        to the slotting approach. full_irb() represents maximum regulatory approval.
        """
        permissions = IRBPermissions.full_irb()

        permitted = permissions.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)
        assert ApproachType.SA in permitted
        assert ApproachType.FIRB in permitted
        assert ApproachType.SLOTTING in permitted
        assert ApproachType.AIRB in permitted

    def test_full_irb_equity_sa_only(self) -> None:
        """Full IRB should have equity using SA only."""
        permissions = IRBPermissions.full_irb()

        permitted = permissions.get_permitted_approaches(ExposureClass.EQUITY)
        assert permitted == {ApproachType.SA}


# =============================================================================
# Comparison Tests
# =============================================================================


class TestPermissionsComparison:
    """Tests comparing different IRBPermissions configurations."""

    def test_firb_vs_full_irb_corporate_difference(self) -> None:
        """FIRB only should not have AIRB while full_irb does for corporates."""
        firb = IRBPermissions.firb_only()
        full = IRBPermissions.full_irb()

        assert not firb.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)
        assert full.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

        # Both should have FIRB for corporate
        assert firb.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert full.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)

    def test_airb_vs_full_irb_corporate_difference(self) -> None:
        """AIRB only should not have FIRB while full_irb does for corporates."""
        airb = IRBPermissions.airb_only()
        full = IRBPermissions.full_irb()

        assert not airb.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert full.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)

        # Both should have AIRB for corporate
        assert airb.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)
        assert full.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_firb_vs_airb_retail_difference(self) -> None:
        """FIRB only should have SA for retail while AIRB has AIRB."""
        firb = IRBPermissions.firb_only()
        airb = IRBPermissions.airb_only()

        # FIRB: retail only has SA
        assert firb.get_permitted_approaches(ExposureClass.RETAIL_MORTGAGE) == {ApproachType.SA}

        # AIRB: retail has SA and AIRB
        assert airb.get_permitted_approaches(ExposureClass.RETAIL_MORTGAGE) == {
            ApproachType.SA,
            ApproachType.AIRB,
        }

    def test_firb_vs_airb_specialised_lending_difference(self) -> None:
        """FIRB and AIRB should have different permissions for specialised lending."""
        firb = IRBPermissions.firb_only()
        airb = IRBPermissions.airb_only()

        firb_sl = firb.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)
        airb_sl = airb.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)

        # FIRB: SA, FIRB, SLOTTING
        assert ApproachType.FIRB in firb_sl
        assert ApproachType.AIRB not in firb_sl

        # AIRB: SA, SLOTTING (no AIRB for SL, no FIRB)
        assert ApproachType.FIRB not in airb_sl
        assert ApproachType.AIRB not in airb_sl


# =============================================================================
# Retail AIRB / Corporate FIRB (Hybrid) Tests
# =============================================================================


class TestRetailAIRBCorporateFIRBPermissions:
    """Tests for IRBPermissions.retail_airb_corporate_firb() factory method."""

    def test_airb_permitted_for_retail_classes(self) -> None:
        """Hybrid should allow AIRB for all retail classes."""
        permissions = IRBPermissions.retail_airb_corporate_firb()

        retail_classes = [
            ExposureClass.RETAIL_MORTGAGE,
            ExposureClass.RETAIL_QRRE,
            ExposureClass.RETAIL_OTHER,
        ]

        for exposure_class in retail_classes:
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            assert permissions.is_permitted(exposure_class, ApproachType.AIRB)
            # FIRB not permitted for retail
            assert not permissions.is_permitted(exposure_class, ApproachType.FIRB)

    def test_firb_permitted_for_corporate_classes(self) -> None:
        """Hybrid should allow FIRB (not AIRB) for corporate classes."""
        permissions = IRBPermissions.retail_airb_corporate_firb()

        corporate_classes = [
            ExposureClass.CORPORATE,
            ExposureClass.CORPORATE_SME,
        ]

        for exposure_class in corporate_classes:
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            assert permissions.is_permitted(exposure_class, ApproachType.FIRB)
            # AIRB not permitted for corporate in hybrid mode
            assert not permissions.is_permitted(exposure_class, ApproachType.AIRB)

    def test_firb_permitted_for_sovereign_and_institution(self) -> None:
        """Hybrid should allow FIRB for sovereign and institution."""
        permissions = IRBPermissions.retail_airb_corporate_firb()

        for exposure_class in [ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ExposureClass.INSTITUTION]:
            assert permissions.is_permitted(exposure_class, ApproachType.SA)
            assert permissions.is_permitted(exposure_class, ApproachType.FIRB)
            assert not permissions.is_permitted(exposure_class, ApproachType.AIRB)

    def test_specialised_lending_has_firb_and_slotting(self) -> None:
        """Hybrid should allow FIRB and slotting for specialised lending."""
        permissions = IRBPermissions.retail_airb_corporate_firb()

        permitted = permissions.get_permitted_approaches(ExposureClass.SPECIALISED_LENDING)
        assert ApproachType.SA in permitted
        assert ApproachType.FIRB in permitted
        assert ApproachType.SLOTTING in permitted
        assert ApproachType.AIRB not in permitted

    def test_equity_sa_only(self) -> None:
        """Hybrid should have equity using SA only."""
        permissions = IRBPermissions.retail_airb_corporate_firb()

        permitted = permissions.get_permitted_approaches(ExposureClass.EQUITY)
        assert permitted == {ApproachType.SA}

    def test_hybrid_vs_full_irb_corporate_difference(self) -> None:
        """Hybrid should NOT have AIRB for corporate while full_irb does."""
        hybrid = IRBPermissions.retail_airb_corporate_firb()
        full = IRBPermissions.full_irb()

        # Hybrid: corporate has FIRB only
        assert hybrid.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert not hybrid.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

        # Full: corporate has both
        assert full.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert full.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_hybrid_vs_firb_only_retail_difference(self) -> None:
        """Hybrid should have AIRB for retail while FIRB-only has SA only."""
        hybrid = IRBPermissions.retail_airb_corporate_firb()
        firb = IRBPermissions.firb_only()

        # Hybrid: retail has AIRB
        assert hybrid.is_permitted(ExposureClass.RETAIL_OTHER, ApproachType.AIRB)

        # FIRB-only: retail has SA only
        assert not firb.is_permitted(ExposureClass.RETAIL_OTHER, ApproachType.AIRB)
        assert firb.get_permitted_approaches(ExposureClass.RETAIL_OTHER) == {ApproachType.SA}
