"""
Configuration contracts for RWA calculator.

Provides immutable configuration dataclasses for dual-framework support:
- PDFloors: PD floor values by exposure class
- LGDFloors: LGD floor values by collateral type (Basel 3.1 A-IRB only)
- SupportingFactors: SME/infrastructure factors (CRR only)
- OutputFloorConfig: 72.5% output floor (Basel 3.1 only)
- CalculationConfig: Master configuration with factory methods

Factory methods .crr() and .basel_3_1() provide self-documenting
configuration that automatically sets correct values for each framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rwa_calc.domain.enums import (
    ApproachType,
    CollateralType,
    ExposureClass,
    InstitutionType,
    PermissionMode,
    RegulatoryFramework,
    ReportingBasis,
)

if TYPE_CHECKING:
    pass

# Type alias for Polars collection engine
PolarsEngine = Literal["cpu", "gpu", "streaming"]


@dataclass(frozen=True)
class PDFloors:
    """
    PD floor values by exposure class.

    Under CRR: Single floor of 0.03% for all exposures (Art. 163)
    Under Basel 3.1: Differentiated floors (CRE30.55, PS1/26 Ch.5)
        - Corporate: 0.05%
        - Retail non-QRRE: 0.05%
        - Retail QRRE transactors: 0.03%
        - Retail QRRE revolvers: 0.10%

    All values expressed as decimals (e.g., 0.0003 = 0.03%)
    """

    corporate: Decimal = Decimal("0.0003")  # 0.03%
    corporate_sme: Decimal = Decimal("0.0003")
    retail_mortgage: Decimal = Decimal("0.0003")
    retail_other: Decimal = Decimal("0.0003")
    retail_qrre_transactor: Decimal = Decimal("0.0003")
    retail_qrre_revolver: Decimal = Decimal("0.0003")

    def get_floor(self, exposure_class: ExposureClass, is_qrre_transactor: bool = False) -> Decimal:
        """Get the PD floor for a given exposure class."""
        if exposure_class == ExposureClass.CORPORATE:
            return self.corporate
        elif exposure_class == ExposureClass.CORPORATE_SME:
            return self.corporate_sme
        elif exposure_class == ExposureClass.RETAIL_MORTGAGE:
            return self.retail_mortgage
        elif exposure_class == ExposureClass.RETAIL_QRRE:
            return self.retail_qrre_transactor if is_qrre_transactor else self.retail_qrre_revolver
        elif exposure_class == ExposureClass.RETAIL_OTHER:
            return self.retail_other
        else:
            # Default to corporate floor for other classes
            return self.corporate

    @classmethod
    def crr(cls) -> PDFloors:
        """CRR PD floors: single 0.03% floor for all classes."""
        return cls(
            corporate=Decimal("0.0003"),
            corporate_sme=Decimal("0.0003"),
            retail_mortgage=Decimal("0.0003"),
            retail_other=Decimal("0.0003"),
            retail_qrre_transactor=Decimal("0.0003"),
            retail_qrre_revolver=Decimal("0.0003"),
        )

    @classmethod
    def basel_3_1(cls) -> PDFloors:
        """Basel 3.1 PD floors: differentiated by class (PRA PS1/26 Art. 160/163)."""
        return cls(
            corporate=Decimal("0.0005"),  # 0.05% Art. 160(1)
            corporate_sme=Decimal("0.0005"),  # 0.05% Art. 160(1)
            retail_mortgage=Decimal("0.0010"),  # 0.10% Art. 163(1)(b) secured by UK RRE
            retail_other=Decimal("0.0005"),  # 0.05% Art. 163(1)(c) all other retail
            retail_qrre_transactor=Decimal("0.0005"),  # 0.05% Art. 163(1)(c) all other retail
            retail_qrre_revolver=Decimal("0.0010"),  # 0.10% Art. 163(1)(a) QRRE revolvers
        )


@dataclass(frozen=True)
class LGDFloors:
    """
    LGD floor values by collateral type and exposure class for A-IRB.

    Only applicable under Basel 3.1 (CRE30.41, PS1/26 Ch.5).
    CRR has no LGD floors for A-IRB.

    Corporate floors (Art. 161(5)):
        - Unsecured (senior & subordinated): 25%
        - Financial collateral: 0%, Receivables: 10%, CRE: 10%, RRE: 10%, Other: 15%

    Retail floors (Art. 164(4)):
        - (a) RRE-secured retail: 5%
        - (b)(i) QRRE unsecured: 50%
        - (b)(ii) Other retail unsecured: 30%
        - (c) Other secured retail: blended formula with LGDU=30%, LGDS per collateral type

    All values expressed as decimals (e.g., 0.25 = 25%)
    """

    # Corporate LGD floors — Art. 161(5)
    unsecured: Decimal = Decimal("0.25")  # 25%
    subordinated_unsecured: Decimal = Decimal("0.50")  # 50% conservative fallback
    financial_collateral: Decimal = Decimal("0.0")  # 0%
    receivables: Decimal = Decimal("0.10")  # 10%
    commercial_real_estate: Decimal = Decimal("0.10")  # 10%
    residential_real_estate: Decimal = Decimal("0.10")  # 10% (PRA Art. 161(5))
    other_physical: Decimal = Decimal("0.15")  # 15%

    # Retail LGD floors — Art. 164(4)
    retail_rre: Decimal = Decimal("0.05")  # 5% Art. 164(4)(a) RRE-secured retail
    retail_qrre_unsecured: Decimal = Decimal("0.50")  # 50% Art. 164(4)(b)(i)
    retail_other_unsecured: Decimal = Decimal("0.30")  # 30% Art. 164(4)(b)(ii)
    retail_lgdu: Decimal = Decimal("0.30")  # 30% Art. 164(4)(c) LGDU for blended formula

    def get_floor(
        self,
        collateral_type: CollateralType,
        exposure_class: str | None = None,
    ) -> Decimal:
        """Get the LGD floor for a given collateral type and optional exposure class.

        When exposure_class is a retail class, returns Art. 164(4) retail floors.
        Otherwise returns Art. 161(5) corporate floors.
        """
        is_retail_mortgage = exposure_class in ("retail_mortgage", "RETAIL_MORTGAGE")
        is_retail_qrre = exposure_class in ("retail_qrre", "RETAIL_QRRE")
        is_retail_other = exposure_class in ("retail_other", "RETAIL_OTHER")
        is_retail = is_retail_mortgage or is_retail_qrre or is_retail_other

        if is_retail and collateral_type == CollateralType.OTHER:
            # Unsecured retail — return exposure-class-specific floor
            if is_retail_qrre:
                return self.retail_qrre_unsecured
            if is_retail_other:
                return self.retail_other_unsecured
            # Retail mortgage unsecured (unusual) — use other retail floor
            return self.retail_other_unsecured

        if is_retail_mortgage and collateral_type == CollateralType.IMMOVABLE:
            return self.retail_rre

        # Collateral-type-based floor (same LGDS for corporate and retail)
        mapping = {
            CollateralType.FINANCIAL: self.financial_collateral,
            CollateralType.RECEIVABLES: self.receivables,
            CollateralType.IMMOVABLE: self.commercial_real_estate,
            CollateralType.OTHER_PHYSICAL: self.other_physical,
            CollateralType.OTHER: self.unsecured,
        }
        return mapping.get(collateral_type, self.unsecured)

    @classmethod
    def crr(cls) -> LGDFloors:
        """CRR: No LGD floors (all zero)."""
        return cls(
            unsecured=Decimal("0.0"),
            subordinated_unsecured=Decimal("0.0"),
            financial_collateral=Decimal("0.0"),
            receivables=Decimal("0.0"),
            commercial_real_estate=Decimal("0.0"),
            residential_real_estate=Decimal("0.0"),
            other_physical=Decimal("0.0"),
            retail_rre=Decimal("0.0"),
            retail_qrre_unsecured=Decimal("0.0"),
            retail_other_unsecured=Decimal("0.0"),
            retail_lgdu=Decimal("0.0"),
        )

    @classmethod
    def basel_3_1(cls) -> LGDFloors:
        """
        Basel 3.1 LGD floors (CRE30.41).

        Corporate floors: PRA PS1/26 Art. 161(5).
        Retail floors: PRA PS1/26 Art. 164(4).
        Note: BCBS CRE30.41 RRE = 5% for retail; PRA Art. 161(5) sets corporate
        RRE at 10%. Both are now correctly distinguished.
        """
        return cls(
            # Corporate — Art. 161(5)
            unsecured=Decimal("0.25"),  # 25%
            subordinated_unsecured=Decimal("0.50"),  # 50% conservative fallback
            financial_collateral=Decimal("0.0"),  # 0%
            receivables=Decimal("0.10"),  # 10%
            commercial_real_estate=Decimal("0.10"),  # 10%
            residential_real_estate=Decimal("0.10"),  # 10% (PRA Art. 161(5))
            other_physical=Decimal("0.15"),  # 15%
            # Retail — Art. 164(4)
            retail_rre=Decimal("0.05"),  # 5% Art. 164(4)(a)
            retail_qrre_unsecured=Decimal("0.50"),  # 50% Art. 164(4)(b)(i)
            retail_other_unsecured=Decimal("0.30"),  # 30% Art. 164(4)(b)(ii)
            retail_lgdu=Decimal("0.30"),  # 30% Art. 164(4)(c) LGDU
        )


@dataclass(frozen=True)
class SupportingFactors:
    """
    Supporting factors for CRR (SME and infrastructure).

    Only applicable under CRR. Basel 3.1 removes these factors.

    SME Supporting Factor (CRR Art. 501):
        - Applies to SME exposures (turnover < EUR 50m)
        - Factor 1: 0.7619 for exposure up to EUR 2.5m
        - Factor 2: 0.85 for exposure above EUR 2.5m

    Infrastructure Supporting Factor (CRR Art. 501a):
        - Applies to qualifying infrastructure exposures
        - Factor: 0.75
    """

    sme_factor_under_threshold: Decimal = Decimal("0.7619")
    sme_factor_above_threshold: Decimal = Decimal("0.85")
    sme_exposure_threshold_eur: Decimal = Decimal("2500000")  # EUR 2.5m
    sme_turnover_threshold_eur: Decimal = Decimal("50000000")  # EUR 50m
    infrastructure_factor: Decimal = Decimal("0.75")
    enabled: bool = True

    @classmethod
    def crr(cls) -> SupportingFactors:
        """CRR supporting factors enabled."""
        return cls(
            sme_factor_under_threshold=Decimal("0.7619"),
            sme_factor_above_threshold=Decimal("0.85"),
            sme_exposure_threshold_eur=Decimal("2500000"),
            sme_turnover_threshold_eur=Decimal("50000000"),
            infrastructure_factor=Decimal("0.75"),
            enabled=True,
        )

    @classmethod
    def basel_3_1(cls) -> SupportingFactors:
        """Basel 3.1: Supporting factors disabled (all 1.0)."""
        return cls(
            sme_factor_under_threshold=Decimal("1.0"),
            sme_factor_above_threshold=Decimal("1.0"),
            sme_exposure_threshold_eur=Decimal("2500000"),
            sme_turnover_threshold_eur=Decimal("50000000"),
            infrastructure_factor=Decimal("1.0"),
            enabled=False,
        )


@dataclass(frozen=True)
class OutputFloorConfig:
    """
    Output floor configuration for Basel 3.1.

    The output floor (CRE99.1-8, PS1/26 Ch.12) requires IRB RWAs
    to be at least 72.5% of the equivalent SA RWAs.

    Not applicable under CRR.

    Entity-type carve-outs (Art. 92 para 2A):
        The floor applies only to specific (institution_type, reporting_basis)
        combinations. When institution_type and reporting_basis are set, the
        ``is_floor_applicable()`` method checks Art. 92 para 2A rules. When
        not set (None), the floor defaults to applicable if enabled — backward
        compatible with existing configurations.

    Art. 92 para 2A applicability:
        (a)(i)   stand-alone UK institution on individual basis → FLOOR
        (a)(ii)  ring-fenced body on sub-consolidated basis → FLOOR
        (a)(iii) non-international-subsidiary CRR consolidation entity
                 on consolidated basis → FLOOR
        (b)      non-ring-fenced on sub-consolidated basis → EXEMPT
        (c)      ring-fenced body at individual level / non-stand-alone → EXEMPT
        (d)      international subsidiary → EXEMPT

    Art. 92 para 5 optionality:
        Transitional floor rates (60/65/70%) are permissive — institutions
        may voluntarily apply the full 72.5% from day one.

    Art. 122(8) corporate SA treatment for S-TREA:
        IRB institutions must choose between 100% flat (Art. 122(2)) or
        65%/135% IG assessment (Art. 122(6)) for unrated corporate exposures
        in the output floor S-TREA computation. This choice is configured via
        ``CalculationConfig.use_investment_grade_assessment`` and flows to the
        SA calculator's unified path, which produces ``sa_rwa`` for the floor.
    """

    enabled: bool = False
    floor_percentage: Decimal = Decimal("0.725")  # 72.5%
    transitional_start_date: date | None = None
    transitional_end_date: date | None = None
    transitional_floor_schedule: dict[date, Decimal] = field(default_factory=dict)
    institution_type: InstitutionType | None = None
    reporting_basis: ReportingBasis | None = None

    # Art. 92 para 2A(a): combinations where the output floor applies
    _FLOOR_APPLICABLE_COMBINATIONS: frozenset[tuple[InstitutionType, ReportingBasis]] = field(
        default=frozenset({
            (InstitutionType.STANDALONE_UK, ReportingBasis.INDIVIDUAL),
            (InstitutionType.RING_FENCED_BODY, ReportingBasis.SUB_CONSOLIDATED),
            (InstitutionType.CRR_CONSOLIDATION_ENTITY, ReportingBasis.CONSOLIDATED),
        }),
        init=False,
        repr=False,
    )

    def is_floor_applicable(self) -> bool:
        """Determine if the output floor applies per Art. 92 para 2A.

        Returns True when:
        - Floor is enabled, AND
        - Either institution_type/reporting_basis are not set (backward compatible
          default: assumes user has already determined applicability), OR
        - The (institution_type, reporting_basis) pair is in the Art. 92 para 2A(a)
          applicability set.

        Returns False when:
        - Floor is disabled (CRR), OR
        - The entity is exempt under Art. 92 para 2A(b)-(d): non-ring-fenced
          institutions on sub-consolidated basis, ring-fenced bodies at individual
          level, international subsidiaries.
        """
        if not self.enabled:
            return False
        # Backward compatible: when entity type not specified, default to applicable
        if self.institution_type is None or self.reporting_basis is None:
            return True
        return (self.institution_type, self.reporting_basis) in self._FLOOR_APPLICABLE_COMBINATIONS

    def get_floor_percentage(self, calculation_date: date) -> Decimal:
        """Get the applicable floor percentage for a given date.

        Returns 0% if floor is disabled or the calculation date precedes the
        transitional start date (PS1/26: 1 Jan 2027 for UK firms).
        """
        if not self.enabled:
            return Decimal("0.0")

        # Before the transitional period starts, no floor applies
        if self.transitional_start_date and calculation_date < self.transitional_start_date:
            return Decimal("0.0")

        # Check transitional schedule
        if self.transitional_floor_schedule:
            applicable_floor = Decimal("0.0")
            for schedule_date, floor in sorted(self.transitional_floor_schedule.items()):
                if calculation_date >= schedule_date:
                    applicable_floor = floor
            if applicable_floor > Decimal("0.0"):
                return applicable_floor

        return self.floor_percentage

    @classmethod
    def crr(cls) -> OutputFloorConfig:
        """CRR: No output floor."""
        return cls(enabled=False)

    @classmethod
    def basel_3_1(
        cls,
        institution_type: InstitutionType | None = None,
        reporting_basis: ReportingBasis | None = None,
    ) -> OutputFloorConfig:
        """Basel 3.1 output floor configuration with transitional period.

        Args:
            institution_type: Entity type per Art. 92 para 2A. When set, floor
                applicability is checked against the regulatory carve-outs.
                When None, the floor is assumed applicable (backward compatible).
            reporting_basis: Basis of calculation per Rule 2.2A. Required with
                institution_type for floor applicability determination.
        """
        # PRA PS1/26 Art. 92(5) transitional schedule
        # NOTE: PRA compressed the BCBS 6-year phase-in to 4 years (2027-2030).
        transitional_schedule = {
            date(2027, 1, 1): Decimal("0.60"),  # 60%
            date(2028, 1, 1): Decimal("0.65"),  # 65%
            date(2029, 1, 1): Decimal("0.70"),  # 70%
            date(2030, 1, 1): Decimal("0.725"),  # 72.5% (fully phased)
        }
        return cls(
            enabled=True,
            floor_percentage=Decimal("0.725"),
            transitional_start_date=date(2027, 1, 1),
            transitional_end_date=date(2030, 1, 1),
            transitional_floor_schedule=transitional_schedule,
            institution_type=institution_type,
            reporting_basis=reporting_basis,
        )


@dataclass(frozen=True)
class EquityTransitionalConfig:
    """
    Equity transitional configuration for Basel 3.1 (PRA Rules 4.1-4.10).

    Firms transitioning from CRR to Basel 3.1 equity weights use a phase-in
    schedule. Firms with prior IRB equity permission use the higher of the
    IRB model RW and the transitional SA RW (Rules 4.4-4.6).
    """

    enabled: bool = False
    schedule: dict[date, tuple[Decimal, Decimal]] = field(default_factory=dict)
    # (standard_rw, higher_risk_rw) keyed by effective date

    def get_transitional_rw(
        self,
        reporting_date: date,
        is_higher_risk: bool = False,
    ) -> Decimal | None:
        """Get the transitional RW for a given date, or None if not in transition."""
        if not self.enabled or not self.schedule:
            return None

        applicable: tuple[Decimal, Decimal] | None = None
        for schedule_date, rws in sorted(self.schedule.items()):
            if reporting_date >= schedule_date:
                applicable = rws

        if applicable is None:
            return None

        return applicable[1] if is_higher_risk else applicable[0]

    @classmethod
    def basel_3_1(cls) -> EquityTransitionalConfig:
        """PRA Rules 4.1-4.3: SA transitional equity risk weights (2027-2029)."""
        return cls(
            enabled=True,
            schedule={
                date(2027, 1, 1): (Decimal("1.60"), Decimal("2.20")),
                date(2028, 1, 1): (Decimal("1.90"), Decimal("2.80")),
                date(2029, 1, 1): (Decimal("2.20"), Decimal("3.40")),
                date(2030, 1, 1): (Decimal("2.50"), Decimal("4.00")),
            },
        )


@dataclass(frozen=True)
class PostModelAdjustmentConfig:
    """
    Post-model adjustment configuration for Basel 3.1 IRB.

    PRA PS9/24 Art. 153(5A), 154(4A), 158(6A) require firms to apply
    post-model adjustments (PMAs) to IRB model outputs for known deficiencies.
    These adjustments increase RWEA and EL to compensate for model limitations.

    Components:
    - General PMAs: Firm-level scalar applied to modelled RWEA/EL (supervisory add-on)
    - Mortgage RW floor: Minimum risk weight for residential mortgage IRB exposures
    - Unrecognised exposure adjustment: Scalar for exposures not fully captured by model

    CRR has no post-model adjustment framework.
    """

    enabled: bool = False
    pma_rwa_scalar: Decimal = Decimal("0.0")  # Additive % of base RWEA (e.g., 0.05 = 5%)
    pma_el_scalar: Decimal = Decimal("0.0")  # Additive % of base EL
    mortgage_rw_floor: Decimal = Decimal("0.0")  # Min RW for residential mortgages (e.g., 0.15)
    unrecognised_exposure_scalar: Decimal = Decimal("0.0")  # Additive % of base RWEA

    @classmethod
    def crr(cls) -> PostModelAdjustmentConfig:
        """CRR: No post-model adjustments."""
        return cls(enabled=False)

    @classmethod
    def basel_3_1(
        cls,
        pma_rwa_scalar: Decimal = Decimal("0.0"),
        pma_el_scalar: Decimal = Decimal("0.0"),
        mortgage_rw_floor: Decimal = Decimal("0.10"),
        unrecognised_exposure_scalar: Decimal = Decimal("0.0"),
    ) -> PostModelAdjustmentConfig:
        """
        Basel 3.1 post-model adjustment configuration.

        Args:
            pma_rwa_scalar: General PMA as fraction of base RWEA (default 0%)
            pma_el_scalar: General PMA as fraction of base EL (default 0%)
            mortgage_rw_floor: Minimum RW for residential mortgages (default 10%, Art. 154(4A)(b))
            unrecognised_exposure_scalar: Unrecognised exposure add-on (default 0%)
        """
        return cls(
            enabled=True,
            pma_rwa_scalar=pma_rwa_scalar,
            pma_el_scalar=pma_el_scalar,
            mortgage_rw_floor=mortgage_rw_floor,
            unrecognised_exposure_scalar=unrecognised_exposure_scalar,
        )


@dataclass(frozen=True)
class RetailThresholds:
    """
    Thresholds for retail exposure classification.

    Different thresholds apply under CRR vs Basel 3.1.
    """

    # Maximum aggregated exposure to qualify as retail
    max_exposure_threshold: Decimal = Decimal("1000000")  # GBP 1m (CRR)

    # QRRE specific limits
    qrre_max_limit: Decimal = Decimal("100000")  # GBP 100k limit per exposure

    @classmethod
    def crr(cls, eur_gbp_rate: Decimal = Decimal("0.8732")) -> RetailThresholds:
        """
        CRR retail thresholds (converted from EUR dynamically).

        Args:
            eur_gbp_rate: EUR/GBP exchange rate for threshold conversion
        """
        return cls(
            max_exposure_threshold=Decimal("1000000") * eur_gbp_rate,  # EUR 1m
            qrre_max_limit=Decimal("100000") * eur_gbp_rate,  # EUR 100k
        )

    @classmethod
    def basel_3_1(cls) -> RetailThresholds:
        """Basel 3.1 retail thresholds (GBP)."""
        return cls(
            max_exposure_threshold=Decimal("880000"),  # GBP 880k
            qrre_max_limit=Decimal("90000"),  # GBP 90k per Art. 147(5A)(c)
        )


@dataclass(frozen=True)
class IRBPermissions:
    """
    IRB approach permissions by exposure class.

    Tracks which approaches are permitted for each class.
    Must align with PRA permissions granted to the firm.
    """

    permissions: dict[ExposureClass, set[ApproachType]] = field(default_factory=dict)

    def is_permitted(self, exposure_class: ExposureClass, approach: ApproachType) -> bool:
        """Check if an approach is permitted for an exposure class."""
        if exposure_class not in self.permissions:
            # Default to SA only if no permissions defined
            return approach == ApproachType.SA
        return approach in self.permissions[exposure_class]

    def get_permitted_approaches(self, exposure_class: ExposureClass) -> set[ApproachType]:
        """Get all permitted approaches for an exposure class."""
        return self.permissions.get(exposure_class, {ApproachType.SA})

    @classmethod
    def sa_only(cls) -> IRBPermissions:
        """SA only - no IRB permissions."""
        return cls(permissions={})

    @classmethod
    def full_irb(cls) -> IRBPermissions:
        """Full IRB permissions for all applicable classes."""
        return cls(
            permissions={
                ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: {
                    ApproachType.SA,
                    ApproachType.FIRB,
                    ApproachType.AIRB,
                },
                ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
                ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
                ExposureClass.CORPORATE_SME: {
                    ApproachType.SA,
                    ApproachType.FIRB,
                    ApproachType.AIRB,
                },
                ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.SPECIALISED_LENDING: {
                    ApproachType.SA,
                    ApproachType.SLOTTING,
                    ApproachType.FIRB,
                    ApproachType.AIRB,
                },
                ExposureClass.EQUITY: {ApproachType.SA},  # IRB for equity removed under Basel 3.1
                ExposureClass.COVERED_BOND: {ApproachType.SA},  # SA-only (Art. 129)
            }
        )

    @classmethod
    def full_irb_b31(cls) -> IRBPermissions:
        """Full IRB permissions with Basel 3.1 Art. 147A approach restrictions.

        Art. 147A mandates:
        - Sovereign/quasi-sovereign (RGLA, PSE, MDB): SA only
        - Institution: F-IRB only (no A-IRB)
        - IPRE/HVCRE: Slotting only (enforced at classifier level)
        - FSE corporate: F-IRB only (enforced at classifier level)
        - Large corporate (>GBP 440m): F-IRB only (enforced at classifier level)
        - Equity: SA only
        - Other SL (PF/OF/CF): Slotting default, F-IRB/A-IRB with permission
        - Other corporate: F-IRB default, A-IRB with explicit permission
        - Retail: A-IRB (if approved)

        Note: FSE and large corporate AIRB restrictions are enforced at
        classifier level using counterparty attributes, not here, because
        they depend on per-exposure data (revenue, entity flags).
        """
        return cls(
            permissions={
                # SA only — Art. 147A(1)(a): sovereign and quasi-sovereigns
                ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: {ApproachType.SA},
                ExposureClass.PSE: {ApproachType.SA},
                ExposureClass.MDB: {ApproachType.SA},
                ExposureClass.RGLA: {ApproachType.SA},
                # F-IRB only — Art. 147A(1)(b): institutions
                ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB},
                # Corporate — Art. 147A(1)(f): F-IRB default, A-IRB with permission
                # (FSE/large corp AIRB restriction enforced at classifier level)
                ExposureClass.CORPORATE: {
                    ApproachType.SA,
                    ApproachType.FIRB,
                    ApproachType.AIRB,
                },
                ExposureClass.CORPORATE_SME: {
                    ApproachType.SA,
                    ApproachType.FIRB,
                    ApproachType.AIRB,
                },
                # Retail — Art. 147A(3): A-IRB (if approved)
                ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
                # SL — Art. 147A(1)(c)/(d): IPRE/HVCRE slotting-only at classifier
                # Other SL (PF/OF/CF) may use F-IRB/A-IRB with explicit permission
                ExposureClass.SPECIALISED_LENDING: {
                    ApproachType.SA,
                    ApproachType.SLOTTING,
                    ApproachType.FIRB,
                    ApproachType.AIRB,
                },
                # SA only
                ExposureClass.EQUITY: {ApproachType.SA},
                ExposureClass.COVERED_BOND: {ApproachType.SA},
            }
        )


@dataclass(frozen=True)
class CalculationConfig:
    """
    Master configuration for RWA calculations.

    Immutable configuration container that bundles all framework-specific
    settings. Use factory methods .crr() and .basel_3_1() to create
    correctly configured instances.

    Attributes:
        framework: Regulatory framework (CRR or BASEL_3_1)
        reporting_date: As-of date for the calculation
        base_currency: Currency for reporting (default GBP)
        apply_fx_conversion: Whether to convert exposures to base_currency
        pd_floors: PD floor configuration
        lgd_floors: LGD floor configuration (A-IRB)
        supporting_factors: SME/infrastructure factors
        output_floor: Output floor configuration
        post_model_adjustments: Post-model adjustments (Basel 3.1 only)
        retail_thresholds: Retail classification thresholds
        permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing)
        scaling_factor: 1.06 scaling factor for IRB (CRR Art. 153), 1.0 for Basel 3.1
        use_investment_grade_assessment: Art. 122(6) election — IG=65% / non-IG=135%
        collect_engine: Polars engine for .collect() - 'cpu' (default)
            processes in batches for lower memory usage, 'cpu' for in-memory
        spill_dir: Directory for temp parquet files during streaming materialization.
            None uses system temp directory.
    """

    framework: RegulatoryFramework
    reporting_date: date
    base_currency: str = "GBP"
    apply_fx_conversion: bool = True  # Convert exposures to base_currency using fx_rates
    pd_floors: PDFloors = field(default_factory=PDFloors.crr)
    lgd_floors: LGDFloors = field(default_factory=LGDFloors.crr)
    supporting_factors: SupportingFactors = field(default_factory=SupportingFactors.crr)
    output_floor: OutputFloorConfig = field(default_factory=OutputFloorConfig.crr)
    post_model_adjustments: PostModelAdjustmentConfig = field(
        default_factory=PostModelAdjustmentConfig.crr
    )
    retail_thresholds: RetailThresholds = field(default_factory=RetailThresholds.crr)
    permission_mode: PermissionMode = PermissionMode.STANDARDISED
    irb_permissions: IRBPermissions = field(init=False)
    equity_transitional: EquityTransitionalConfig = field(default_factory=EquityTransitionalConfig)
    scaling_factor: Decimal = Decimal("1.06")  # IRB K scaling (CRR Art. 153)
    eur_gbp_rate: Decimal = Decimal("0.8732")  # FX rate for EUR threshold conversion
    enable_double_default: bool = False  # CRR Art. 153(3) double default treatment
    use_investment_grade_assessment: bool = False  # Art. 122(6)/(8): IG=65% / non-IG=135%
    # Art. 122(8): IRB institutions must choose between para 2 (100% flat)
    # or para 6 (65%/135% IG assessment) for unrated corporates. This choice
    # applies to both regular SA calculations and the output floor S-TREA
    # computation (Art. 92 para 2A). The choice must be declared to the PRA.
    collect_engine: PolarsEngine = "cpu"  # Default to in-memory; use "streaming" for large datasets
    spill_dir: Path | None = None  # Directory for disk-spill temp files (None = system temp)

    def __post_init__(self) -> None:
        """Derive internal irb_permissions from permission_mode and framework."""
        if self.permission_mode == PermissionMode.IRB:
            if self.framework == RegulatoryFramework.BASEL_3_1:
                object.__setattr__(self, "irb_permissions", IRBPermissions.full_irb_b31())
            else:
                object.__setattr__(self, "irb_permissions", IRBPermissions.full_irb())
        else:
            object.__setattr__(self, "irb_permissions", IRBPermissions.sa_only())

    @property
    def is_crr(self) -> bool:
        """Check if using CRR framework."""
        return self.framework == RegulatoryFramework.CRR

    @property
    def is_basel_3_1(self) -> bool:
        """Check if using Basel 3.1 framework."""
        return self.framework == RegulatoryFramework.BASEL_3_1

    def get_output_floor_percentage(self) -> Decimal:
        """Get the applicable output floor percentage."""
        return self.output_floor.get_floor_percentage(self.reporting_date)

    @classmethod
    def crr(
        cls,
        reporting_date: date,
        permission_mode: PermissionMode = PermissionMode.STANDARDISED,
        eur_gbp_rate: Decimal = Decimal("0.8732"),
        enable_double_default: bool = False,
        collect_engine: PolarsEngine = "cpu",
        spill_dir: Path | None = None,
    ) -> CalculationConfig:
        """
        Create CRR (Basel 3.0) configuration.

        CRR characteristics:
        - Single PD floor (0.03%) for all classes
        - No LGD floors for A-IRB
        - SME supporting factor (0.7619/0.85)
        - Infrastructure supporting factor (0.75)
        - No output floor
        - No post-model adjustments
        - 1.06 scaling factor for IRB K
        - Optional double default treatment (Art. 153(3), 202-203)

        Args:
            reporting_date: As-of date for calculation
            permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing)
            eur_gbp_rate: EUR/GBP exchange rate for threshold conversion
            enable_double_default: Enable double default treatment for eligible guarantees
            collect_engine: Polars engine for .collect() - 'cpu' (default)
                for memory efficiency, 'cpu' for in-memory processing

        Returns:
            Configured CalculationConfig for CRR
        """
        return cls(
            framework=RegulatoryFramework.CRR,
            reporting_date=reporting_date,
            base_currency="GBP",
            pd_floors=PDFloors.crr(),
            lgd_floors=LGDFloors.crr(),
            supporting_factors=SupportingFactors.crr(),
            output_floor=OutputFloorConfig.crr(),
            post_model_adjustments=PostModelAdjustmentConfig.crr(),
            retail_thresholds=RetailThresholds.crr(eur_gbp_rate=eur_gbp_rate),
            permission_mode=permission_mode,
            scaling_factor=Decimal("1.06"),
            eur_gbp_rate=eur_gbp_rate,
            enable_double_default=enable_double_default,
            collect_engine=collect_engine,
            spill_dir=spill_dir,
        )

    @classmethod
    def basel_3_1(
        cls,
        reporting_date: date,
        permission_mode: PermissionMode = PermissionMode.STANDARDISED,
        post_model_adjustments: PostModelAdjustmentConfig | None = None,
        use_investment_grade_assessment: bool = False,
        institution_type: InstitutionType | None = None,
        reporting_basis: ReportingBasis | None = None,
        collect_engine: PolarsEngine = "cpu",
        spill_dir: Path | None = None,
    ) -> CalculationConfig:
        """
        Create Basel 3.1 (PRA PS1/26) configuration.

        Basel 3.1 characteristics:
        - Differentiated PD floors by exposure class
        - LGD floors for A-IRB by collateral type
        - No supporting factors (SME/infrastructure)
        - Output floor (72.5%, transitional)
        - 1.06 scaling factor removed (PRA PS1/26 confirms)
        - Post-model adjustments (mortgage RW floor, PMAs)

        Args:
            reporting_date: As-of date for calculation
            permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing)
            post_model_adjustments: PMA configuration (optional, defaults to B3.1)
            use_investment_grade_assessment: Art. 122(6)/(8) election — when True,
                unrated IG corporates get 65% and non-IG get 135%. When False
                (default), all unrated corporates get 100%. Under Art. 122(8),
                this choice also determines the SA-equivalent risk weight used
                for the output floor S-TREA computation (Art. 92 para 2A).
                Must be declared to the PRA.
            institution_type: Entity type per Art. 92 para 2A for output floor
                applicability. When None, floor is assumed applicable.
            reporting_basis: Calculation basis per Rule 2.2A. Required with
                institution_type for floor applicability check.
            collect_engine: Polars engine for .collect() - 'cpu' (default)
                for memory efficiency, 'cpu' for in-memory processing

        Returns:
            Configured CalculationConfig for Basel 3.1
        """
        return cls(
            framework=RegulatoryFramework.BASEL_3_1,
            reporting_date=reporting_date,
            base_currency="GBP",
            pd_floors=PDFloors.basel_3_1(),
            lgd_floors=LGDFloors.basel_3_1(),
            supporting_factors=SupportingFactors.basel_3_1(),
            output_floor=OutputFloorConfig.basel_3_1(
                institution_type=institution_type,
                reporting_basis=reporting_basis,
            ),
            post_model_adjustments=(
                post_model_adjustments or PostModelAdjustmentConfig.basel_3_1()
            ),
            retail_thresholds=RetailThresholds.basel_3_1(),
            permission_mode=permission_mode,
            equity_transitional=EquityTransitionalConfig.basel_3_1(),
            scaling_factor=Decimal("1.0"),  # Removed under Basel 3.1 (PRA PS1/26)
            eur_gbp_rate=Decimal("0.8732"),  # Not used for Basel 3.1 (GBP thresholds)
            use_investment_grade_assessment=use_investment_grade_assessment,
            collect_engine=collect_engine,
            spill_dir=spill_dir,
        )
