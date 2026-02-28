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
from typing import TYPE_CHECKING, Literal

from rwa_calc.domain.enums import (
    ApproachType,
    CollateralType,
    ExposureClass,
    RegulatoryFramework,
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
    Under Basel 3.1: Differentiated floors (CRE30.55, PS9/24 Ch.5)
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
        """Basel 3.1 PD floors: differentiated by class (CRE30.55)."""
        return cls(
            corporate=Decimal("0.0005"),  # 0.05%
            corporate_sme=Decimal("0.0005"),  # 0.05%
            retail_mortgage=Decimal("0.0005"),  # 0.05%
            retail_other=Decimal("0.0005"),  # 0.05%
            retail_qrre_transactor=Decimal("0.0003"),  # 0.03%
            retail_qrre_revolver=Decimal("0.0010"),  # 0.10%
        )


@dataclass(frozen=True)
class LGDFloors:
    """
    LGD floor values by collateral type for A-IRB.

    Only applicable under Basel 3.1 (CRE30.41, PS9/24 Ch.5).
    CRR has no LGD floors for A-IRB.

    All values expressed as decimals (e.g., 0.25 = 25%)
    """

    unsecured: Decimal = Decimal("0.25")  # 25%
    subordinated_unsecured: Decimal = Decimal("0.50")  # 50%
    financial_collateral: Decimal = Decimal("0.0")  # 0%
    receivables: Decimal = Decimal("0.10")  # 10%
    commercial_real_estate: Decimal = Decimal("0.10")  # 10%
    residential_real_estate: Decimal = Decimal("0.05")  # 5%
    other_physical: Decimal = Decimal("0.15")  # 15%

    def get_floor(self, collateral_type: CollateralType) -> Decimal:
        """Get the LGD floor for a given collateral type."""
        mapping = {
            CollateralType.FINANCIAL: self.financial_collateral,
            CollateralType.RECEIVABLES: self.receivables,
            CollateralType.IMMOVABLE: self.commercial_real_estate,  # Default to CRE
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
        )

    @classmethod
    def basel_3_1(cls) -> LGDFloors:
        """
        Basel 3.1 LGD floors (CRE30.41).

        Note: Values reflect PRA implementation. BCBS standard values differ
        for some collateral types (Receivables: 15%, RRE: 10%, Other Physical: 20%).
        TODO: Verify against PRA PS1/26 final rules when published.
        """
        return cls(
            unsecured=Decimal("0.25"),  # 25%
            subordinated_unsecured=Decimal("0.50"),  # 50%
            financial_collateral=Decimal("0.0"),  # 0%
            receivables=Decimal("0.10"),  # 10%
            commercial_real_estate=Decimal("0.10"),  # 10%
            residential_real_estate=Decimal("0.05"),  # 5%
            other_physical=Decimal("0.15"),  # 15%
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

    The output floor (CRE99.1-8, PS9/24 Ch.12) requires IRB RWAs
    to be at least 72.5% of the equivalent SA RWAs.

    Not applicable under CRR.
    """

    enabled: bool = False
    floor_percentage: Decimal = Decimal("0.725")  # 72.5%
    transitional_start_date: date | None = None
    transitional_end_date: date | None = None
    transitional_floor_schedule: dict[date, Decimal] = field(default_factory=dict)

    def get_floor_percentage(self, calculation_date: date) -> Decimal:
        """Get the applicable floor percentage for a given date.

        Returns 0% if floor is disabled or the calculation date precedes the
        transitional start date (PS9/24: 1 Jan 2027 for UK firms).
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
    def basel_3_1(cls) -> OutputFloorConfig:
        """Basel 3.1 output floor configuration with transitional period."""
        # PRA PS9/24 transitional schedule
        transitional_schedule = {
            date(2027, 1, 1): Decimal("0.50"),  # 50%
            date(2028, 1, 1): Decimal("0.55"),  # 55%
            date(2029, 1, 1): Decimal("0.60"),  # 60%
            date(2030, 1, 1): Decimal("0.65"),  # 65%
            date(2031, 1, 1): Decimal("0.70"),  # 70%
            date(2032, 1, 1): Decimal("0.725"),  # 72.5% (fully phased)
        }
        return cls(
            enabled=True,
            floor_percentage=Decimal("0.725"),
            transitional_start_date=date(2027, 1, 1),
            transitional_end_date=date(2032, 1, 1),
            transitional_floor_schedule=transitional_schedule,
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
            qrre_max_limit=Decimal("100000"),  # GBP 100k
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
            }
        )

    @classmethod
    def firb_only(cls) -> IRBPermissions:
        """
        Foundation IRB only - no AIRB permissions.

        Regulatory constraints per exposure class:
        - FIRB not permitted for retail (CRE30.1) - falls back to SA
        - Specialised lending can use FIRB or slotting (CRE33)
        - Equity uses SA only (IRB removed under Basel 3.1)
        """
        return cls(
            permissions={
                ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA},  # FIRB not permitted for retail
                ExposureClass.RETAIL_QRRE: {ApproachType.SA},  # FIRB not permitted for retail
                ExposureClass.RETAIL_OTHER: {ApproachType.SA},  # FIRB not permitted for retail
                ExposureClass.SPECIALISED_LENDING: {
                    ApproachType.SA,
                    ApproachType.SLOTTING,
                    ApproachType.FIRB,
                },
                ExposureClass.EQUITY: {ApproachType.SA},
            }
        )

    @classmethod
    def airb_only(cls) -> IRBPermissions:
        """
        Advanced IRB only - no FIRB permissions.

        Regulatory constraints per exposure class:
        - AIRB permitted for all non-equity classes except specialised lending
        - Specialised lending uses slotting (no AIRB - CRE33.5)
        - Equity uses SA only (IRB removed under Basel 3.1)
        """
        return cls(
            permissions={
                ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.SPECIALISED_LENDING: {
                    ApproachType.SA,
                    ApproachType.SLOTTING,
                },  # No AIRB for SL
                ExposureClass.EQUITY: {ApproachType.SA},
            }
        )

    @classmethod
    def retail_airb_corporate_firb(cls) -> IRBPermissions:
        """
        AIRB for retail, FIRB for corporate - hybrid approach.

        Use when firm has:
        - AIRB approval for retail exposures
        - FIRB approval for corporate exposures
        - Ability to reclassify qualifying corporates as regulatory retail

        Corporates can be treated as retail (per CRR Art. 147(5)) if:
        - Managed as part of retail pool (is_managed_as_retail=True)
        - Aggregated exposure < EUR 1m
        - Has internally modelled LGD

        Reclassification target:
        - With property collateral → RETAIL_MORTGAGE
        - Without property collateral → RETAIL_OTHER
        - NOT eligible for QRRE
        """
        return cls(
            permissions={
                ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.FIRB},
                ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.SPECIALISED_LENDING: {
                    ApproachType.SA,
                    ApproachType.SLOTTING,
                    ApproachType.FIRB,
                },
                ExposureClass.EQUITY: {ApproachType.SA},
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
        retail_thresholds: Retail classification thresholds
        irb_permissions: IRB approach permissions
        scaling_factor: 1.06 scaling factor for IRB (CRR Art. 153), 1.0 for Basel 3.1
        correlation_multiplier: SME correlation adjustment multiplier
        collect_engine: Polars engine for .collect() - 'streaming' (default)
            processes in batches for lower memory usage, 'cpu' for in-memory
    """

    framework: RegulatoryFramework
    reporting_date: date
    base_currency: str = "GBP"
    apply_fx_conversion: bool = True  # Convert exposures to base_currency using fx_rates
    pd_floors: PDFloors = field(default_factory=PDFloors.crr)
    lgd_floors: LGDFloors = field(default_factory=LGDFloors.crr)
    supporting_factors: SupportingFactors = field(default_factory=SupportingFactors.crr)
    output_floor: OutputFloorConfig = field(default_factory=OutputFloorConfig.crr)
    retail_thresholds: RetailThresholds = field(default_factory=RetailThresholds.crr)
    irb_permissions: IRBPermissions = field(default_factory=IRBPermissions.sa_only)
    scaling_factor: Decimal = Decimal("1.06")  # IRB K scaling (CRR Art. 153)
    eur_gbp_rate: Decimal = Decimal("0.8732")  # FX rate for EUR threshold conversion
    collect_engine: PolarsEngine = "streaming"  # Default to streaming for memory efficiency

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
        irb_permissions: IRBPermissions | None = None,
        eur_gbp_rate: Decimal = Decimal("0.8732"),
        collect_engine: PolarsEngine = "streaming",
    ) -> CalculationConfig:
        """
        Create CRR (Basel 3.0) configuration.

        CRR characteristics:
        - Single PD floor (0.03%) for all classes
        - No LGD floors for A-IRB
        - SME supporting factor (0.7619/0.85)
        - Infrastructure supporting factor (0.75)
        - No output floor
        - 1.06 scaling factor for IRB K

        Args:
            reporting_date: As-of date for calculation
            irb_permissions: IRB approach permissions (optional)
            eur_gbp_rate: EUR/GBP exchange rate for threshold conversion
            collect_engine: Polars engine for .collect() - 'streaming' (default)
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
            retail_thresholds=RetailThresholds.crr(eur_gbp_rate=eur_gbp_rate),
            irb_permissions=irb_permissions or IRBPermissions.sa_only(),
            scaling_factor=Decimal("1.06"),
            eur_gbp_rate=eur_gbp_rate,
            collect_engine=collect_engine,
        )

    @classmethod
    def basel_3_1(
        cls,
        reporting_date: date,
        irb_permissions: IRBPermissions | None = None,
        collect_engine: PolarsEngine = "streaming",
    ) -> CalculationConfig:
        """
        Create Basel 3.1 (PRA PS9/24) configuration.

        Basel 3.1 characteristics:
        - Differentiated PD floors by exposure class
        - LGD floors for A-IRB by collateral type
        - No supporting factors (SME/infrastructure)
        - Output floor (72.5%, transitional)
        - 1.06 scaling factor removed (PRA CP16/22 confirms)

        Args:
            reporting_date: As-of date for calculation
            irb_permissions: IRB approach permissions (optional)
            collect_engine: Polars engine for .collect() - 'streaming' (default)
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
            output_floor=OutputFloorConfig.basel_3_1(),
            retail_thresholds=RetailThresholds.basel_3_1(),
            irb_permissions=irb_permissions or IRBPermissions.sa_only(),
            scaling_factor=Decimal("1.0"),  # Removed under Basel 3.1 (PRA CP16/22)
            eur_gbp_rate=Decimal("0.8732"),  # Not used for Basel 3.1 (GBP thresholds)
            collect_engine=collect_engine,
        )
