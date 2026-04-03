"""Unit tests for IRBPermissions internal helper methods.

Tests cover:
- sa_only(): No IRB permissions
- full_irb(): Both FIRB and AIRB permitted

Note: firb_only(), airb_only(), and retail_airb_corporate_firb() have been
removed. IRB approach routing is now driven by model_permissions data, not
org-wide factory methods. The remaining sa_only() and full_irb() are internal
helpers used by PermissionMode resolution.
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
