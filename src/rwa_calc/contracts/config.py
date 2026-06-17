"""
Configuration contracts for RWA calculator.

Provides immutable configuration dataclasses for dual-framework support:
- OutputFloorConfig: 72.5% output floor (Basel 3.1 only)
- CalculationConfig: Master configuration with factory methods

Regulatory VALUES (PD/LGD floors, supporting factors, monetary thresholds, ...)
live in the rulepack (rwa_calc.rulebook), not here — RunConfig carries firm
inputs and elections only (Phase 5).

Factory methods .crr() and .basel_3_1() provide self-documenting
configuration that automatically sets correct values for each framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from watchfire import cites

from rwa_calc.domain.enums import (
    AIRBCollateralMethod,
    ApproachType,
    CRMCollateralMethod,
    ExposureClass,
    InstitutionType,
    PermissionMode,
    RegulatoryFramework,
    ReportingBasis,
)

# Type alias for Polars collection engine
PolarsEngine = Literal["cpu", "gpu", "streaming"]

# Regime identifier ("crr" | "b31") → the legacy RegulatoryFramework enum. The
# regime is carried on RunConfig as the ``regime_id`` string (Phase 5 S11e); the
# ``framework`` property derives the enum from it for the enum-typed read sites.
_REGIME_ID_TO_FRAMEWORK = {
    "crr": RegulatoryFramework.CRR,
    "b31": RegulatoryFramework.BASEL_3_1,
}


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

    # OF-ADJ capital-tier inputs (Art. 92 para 2A)
    # These are institution-level capital parameters that cannot be derived
    # from exposure-level data.  When all are zero (default), OF-ADJ = 0
    # and the floor formula simplifies to max(U-TREA, x * S-TREA).
    gcra_amount: float = 0.0
    """General credit risk adjustments, gross of tax effects.
    Capped internally at 1.25% of S-TREA per Art. 92 para 2A."""
    sa_t2_credit: float = 0.0
    """Art. 62(c) SA T2 credit for general credit risk adjustments."""
    art_40_deductions: float = 0.0
    """Art. 40 additional CET1 deductions (supervisory add-on beyond Art. 36(1)(d))."""

    # Firm election (Art. 92 para 5): voluntarily apply the full 72.5% floor from
    # day one rather than the transitional phase-in. Engine-read (Phase 5 S11e-v1)
    # alongside the pack output-floor percentages (output_floor_pct Schedule +
    # output_floor_pct_full scalar). The floor_percentage / transitional_* fields
    # below remain for the config-side get_floor_percentage method until the
    # S11e carve deletes them.
    skip_transitional: bool = False

    # Art. 92 para 2A(a): combinations where the output floor applies
    _FLOOR_APPLICABLE_COMBINATIONS: frozenset[tuple[InstitutionType, ReportingBasis]] = field(
        default=frozenset(
            {
                (InstitutionType.STANDALONE_UK, ReportingBasis.INDIVIDUAL),
                (InstitutionType.RING_FENCED_BODY, ReportingBasis.SUB_CONSOLIDATED),
                (InstitutionType.CRR_CONSOLIDATION_ENTITY, ReportingBasis.CONSOLIDATED),
            }
        ),
        init=False,
        repr=False,
    )

    def is_entity_in_scope(self) -> bool:
        """Art. 92 para 2A(a) entity-scope test, independent of the enabled gate.

        Returns True when the entity type / reporting basis bring the firm into
        output-floor scope — either because they are not set (backward compatible
        default: caller has already determined applicability) or because the
        ``(institution_type, reporting_basis)`` pair is in the Art. 92 para 2A(a)
        applicability set. Returns False for the para 2A(b)-(d) exempt entities.

        This is the firm-election half of :meth:`is_floor_applicable`: the regime
        on/off GATE is sourced from the ``output_floor`` rulepack Feature engine-
        side (Phase 5 S11d), so the engine composes
        ``pack.feature("output_floor") and config.output_floor.is_entity_in_scope()``.
        """
        # Backward compatible: when entity type not specified, default to applicable
        if self.institution_type is None or self.reporting_basis is None:
            return True
        return (self.institution_type, self.reporting_basis) in self._FLOOR_APPLICABLE_COMBINATIONS

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
        return self.enabled and self.is_entity_in_scope()

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
        gcra_amount: float = 0.0,
        sa_t2_credit: float = 0.0,
        art_40_deductions: float = 0.0,
        skip_transitional: bool = False,
    ) -> OutputFloorConfig:
        """Basel 3.1 output floor configuration with transitional period.

        Art. 92 para 5 optionality:
            The transitional floor rates (60%/65%/70%) are *permissive*, not
            mandatory. Institutions may voluntarily apply the full 72.5% floor
            from day one by passing ``skip_transitional=True``.  When skipped,
            ``get_floor_percentage()`` returns 72.5% regardless of reporting date.

        Args:
            institution_type: Entity type per Art. 92 para 2A. When set, floor
                applicability is checked against the regulatory carve-outs.
                When None, the floor is assumed applicable (backward compatible).
            reporting_basis: Basis of calculation per Rule 2.2A. Required with
                institution_type for floor applicability determination.
            gcra_amount: General credit risk adjustments for OF-ADJ (Art. 92 para 2A).
            sa_t2_credit: Art. 62(c) SA T2 credit for general CRAs (OF-ADJ input).
            art_40_deductions: Art. 40 additional CET1 deductions (OF-ADJ input).
            skip_transitional: When True, bypass the PRA transitional schedule
                and apply the full 72.5% floor immediately (Art. 92 para 5).
        """
        # PRA PS1/26 Art. 92(5) transitional schedule
        # NOTE: PRA compressed the BCBS 6-year phase-in to 4 years (2027-2030).
        # Art. 92 para 5: institutions "may apply" these rates — they are
        # permissive.  Firms can voluntarily use 72.5% from day one.
        if skip_transitional:
            transitional_schedule: dict[date, Decimal] = {}
        else:
            transitional_schedule = {
                date(2027, 1, 1): Decimal("0.60"),  # 60%
                date(2028, 1, 1): Decimal("0.65"),  # 65%
                date(2029, 1, 1): Decimal("0.70"),  # 70%
                date(2030, 1, 1): Decimal("0.725"),  # 72.5% (fully phased)
            }
        return cls(
            enabled=True,
            floor_percentage=Decimal("0.725"),
            transitional_start_date=None if skip_transitional else date(2027, 1, 1),
            transitional_end_date=None if skip_transitional else date(2030, 1, 1),
            transitional_floor_schedule=transitional_schedule,
            institution_type=institution_type,
            reporting_basis=reporting_basis,
            gcra_amount=gcra_amount,
            sa_t2_credit=sa_t2_credit,
            art_40_deductions=art_40_deductions,
            skip_transitional=skip_transitional,
        )


@dataclass(frozen=True)
class EquityTransitionalConfig:
    """
    Equity transitional configuration for Basel 3.1 (PRA Rules 4.1-4.10).

    Firms transitioning from CRR to Basel 3.1 equity weights use a phase-in
    schedule. Firms with prior IRB equity permission use the higher of the
    IRB model RW and the transitional SA RW (Rules 4.4-4.6).

    Per Rules 4.9-4.10 a firm may irrevocably opt out of the transitional
    regime. When ``opt_out`` is True the opt-out applies jointly to direct
    equity (the transitional floor is skipped) and to CIU underlyings (the
    Rule 4.8 higher-of is suppressed), so both end-state RWs apply directly.
    """

    enabled: bool = False
    schedule: dict[date, tuple[Decimal, Decimal]] = field(default_factory=dict)
    # (standard_rw, higher_risk_rw) keyed by effective date
    opt_out: bool = False
    # PRA Rules 4.9-4.10: irrevocable joint opt-out from the equity transitional regime.

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

    PRA PS1/26 Art. 153(5A), 154(4A), 158(6A) require firms to apply
    post-model adjustments (PMAs) to IRB model outputs for known deficiencies.
    These adjustments increase RWEA and EL to compensate for model limitations.

    Components:
    - General PMAs: Firm-level scalar applied to post-floor RWEA/EL (supervisory add-on)
    - Mortgage RW floor: Minimum risk weight for residential mortgage IRB exposures
    - Unrecognised exposure adjustment: Scalar for exposures not fully captured by model

    Adjustment sequencing per Art. 154(4A):
        (b) Mortgage RW floor applied first — establishes post-floor RWEA base
        (a) General PMA and unrecognised scalars applied to post-floor RWEA

    Art. 158(6A): PMA EL adjustments can only increase EL, never decrease.
    Negative scalars are rejected at construction time.

    CRR has no post-model adjustment framework.
    """

    enabled: bool = False
    pma_rwa_scalar: Decimal = Decimal("0.0")  # Additive % of post-floor RWEA (e.g., 0.05 = 5%)
    pma_el_scalar: Decimal = Decimal("0.0")  # Additive % of base EL (must be >= 0)
    mortgage_rw_floor: Decimal = Decimal("0.0")  # Min RW for residential mortgages (e.g., 0.10)
    unrecognised_exposure_scalar: Decimal = Decimal("0.0")  # Additive % of post-floor RWEA

    def __post_init__(self) -> None:
        """Validate PMA scalars per Art. 158(6A) — PMAs can only increase, not decrease."""
        if self.pma_rwa_scalar < 0:
            msg = f"pma_rwa_scalar must be >= 0 (got {self.pma_rwa_scalar})"
            raise ValueError(msg)
        if self.pma_el_scalar < 0:
            msg = (
                f"pma_el_scalar must be >= 0 per Art. 158(6A) — PMAs cannot decrease EL "
                f"(got {self.pma_el_scalar})"
            )
            raise ValueError(msg)
        if self.unrecognised_exposure_scalar < 0:
            msg = (
                f"unrecognised_exposure_scalar must be >= 0 "
                f"(got {self.unrecognised_exposure_scalar})"
            )
            raise ValueError(msg)
        if self.mortgage_rw_floor < 0:
            msg = f"mortgage_rw_floor must be >= 0 (got {self.mortgage_rw_floor})"
            raise ValueError(msg)

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
class IRBPermissions:
    """
    IRB approach permissions by exposure class.

    Tracks which approaches are permitted for each class.
    Must align with PRA permissions granted to the firm.
    """

    permissions: dict[ExposureClass, set[ApproachType]] = field(default_factory=dict)

    # Art. 236(1)(a)(i) (PRA PS1/26): PSM LGD source choice for IRB guarantee
    # parameter substitution. "option_ii" (default) uses the F-IRB supervisory
    # LGD keyed on the GUARANTOR's seniority/FSE status (i.e. the LGD that would
    # apply to a direct exposure to the guarantor). "option_i" uses the
    # borrower's own unprotected (pre-CRM) LGD. The "no better than direct"
    # floor (Art. 160(4)) continues to use the option_ii guarantor scalar so
    # the comparison stays meaningful regardless of this switch.
    psm_lgd_source: Literal["option_i", "option_ii"] = "option_ii"

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
        - Sovereign / quasi-sovereign with 0% SA risk weight (Art. 147(3):
          CGCB, sovereign-treated RGLAs/PSEs, MDBs, international orgs):
          SA only. Enforced at classifier level by entity-type check so that
          RGLAs/PSEs treated as institutions (Art. 147(4)(b)) are NOT
          captured here; they route to the INSTITUTION IRB class below.
        - Institution (including RGLAs/PSEs treated as institutions):
          F-IRB only (no A-IRB).
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

        The RGLA / PSE / MDB entries below are defensive defaults. Since
        permission lookup keys on exposure_class_irb, institution-typed
        RGLAs/PSEs will not hit these entries — they key on INSTITUTION.
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
class Pillar3CapitalRatioOverrides:
    """
    Optional capital-ratio overrides for the UKB OV1 pre-floor disclosure rows.

    Pillar III templates require pre-floor capital-ratio disclosures that are
    institution-level capital figures and cannot be derived from the credit-risk
    pipeline. Callers supply these values explicitly so that rows 5a/5b/6a/6b/
    7a/7b of UKB OV1 can be populated. Any field left as None causes the
    generator to emit None for the corresponding row's column 'a'/'b'/'c'.

    All ratios are expressed as decimal fractions (e.g., Decimal("0.135") for
    13.5%). The generator multiplies by 100 when emitting percentage points.

    References:
        PRA PS1/26 Disclosure (CRR) Part, Art. 456
        UKB OV1 template — pre-floor supplementary rows
    """

    cet1_ratio_pre_floor: Decimal | None = None
    cet1_ratio_pre_floor_transitional: Decimal | None = None
    tier1_ratio_pre_floor: Decimal | None = None
    tier1_ratio_pre_floor_transitional: Decimal | None = None
    total_ratio_pre_floor: Decimal | None = None
    total_ratio_pre_floor_transitional: Decimal | None = None


@cites("CRR Art. 274(2)")
@dataclass(frozen=True)
class CCRConfig:
    """
    Counterparty Credit Risk configuration.

    References:
    - CRR Art. 271(2) — SFT EAD routing (FCCM, not SA-CCR Art. 274)
    - CRR Art. 274(2) — α = 1.4 default for SA-CCR EAD formula
    - CRR Art. 285(2)(b) — 10 business day MPOR floor for non-SFT netting sets
    - CRR Art. 285(1)(b)(ii) — initial margin recognition
    - CRR Art. 273a — small/non-complex derivatives portfolio carve-out

    ``sft_method`` selects the EAD method for SFT trades per CRR Art. 271(2).
    Only the Financial Collateral Comprehensive Method ("fccm", Art. 220-223)
    is implemented today; the ``"var"`` (Art. 221) and ``"imm"`` (Art. 283)
    method literals are reserved for future expansion.
    """

    method: Literal["sa_ccr"] = "sa_ccr"
    sft_method: Literal["fccm", "var", "imm"] = "fccm"
    alpha: Decimal = Decimal("1.4")
    enable_ccp_exposures: bool = True
    mpor_floor_days: int = 10
    recognise_im: bool = True


@dataclass(frozen=True)
class CalculationConfig:
    """
    Master configuration for RWA calculations.

    Immutable configuration container that bundles all framework-specific
    settings. Use factory methods .crr() and .basel_3_1() to create
    correctly configured instances.

    Attributes:
        regime_id: Regime identifier ("crr" | "b31") — the regime carrier
        reporting_date: As-of date for the calculation
        base_currency: Currency for reporting (default GBP)
        apply_fx_conversion: Whether to convert exposures to base_currency
        output_floor: Output floor configuration
        post_model_adjustments: Post-model adjustments (Basel 3.1 only)
        permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing)
        use_investment_grade_assessment: Art. 122(6) election — IG=65% / non-IG=135%
        collect_engine: Polars engine for .collect() - 'cpu' (default) for
            in-memory processing, 'streaming' for batched lower-memory execution.
        spill_dir: Directory for temp parquet files during streaming materialization.
            None uses system temp directory.
    """

    regime_id: str  # "crr" | "b31" — the regime carrier (Phase 5 S11e)
    reporting_date: date
    base_currency: str = "GBP"
    apply_fx_conversion: bool = True  # Convert exposures to base_currency using fx_rates
    output_floor: OutputFloorConfig = field(default_factory=OutputFloorConfig.crr)
    post_model_adjustments: PostModelAdjustmentConfig = field(
        default_factory=PostModelAdjustmentConfig.crr
    )
    ccr: CCRConfig = field(default_factory=CCRConfig)
    permission_mode: PermissionMode = PermissionMode.STANDARDISED
    # Optional explicit IRBPermissions override. When None (default) the value
    # is derived in __post_init__ from permission_mode and regime_id. Passing a
    # non-None value (or replacing via ``dataclasses.replace``) lets callers
    # customise IRB-permission flags such as ``psm_lgd_source`` without having
    # to reconstruct the master config from scratch.
    irb_permissions: IRBPermissions | None = None
    equity_transitional: EquityTransitionalConfig = field(default_factory=EquityTransitionalConfig)
    eur_gbp_rate: Decimal = Decimal("0.8732")  # FX rate for EUR threshold conversion
    # When True, the pipeline replaces eur_gbp_rate (and rebuilds thresholds)
    # with the (EUR, GBP) row from the loaded fx_rates table, if present.
    # Set False to force the passed-in / default rate regardless of input data.
    sync_eur_gbp_rate_from_fx_table: bool = True
    enable_double_default: bool = False  # CRR Art. 153(3) double default treatment
    # CRR Art. 155(3): when True and the firm has IRB permissions under CRR,
    # equity exposures use the PD/LGD approach (Art. 165 supervisory parameters)
    # instead of the Art. 155(2) IRB Simple risk weights. Ignored under Basel 3.1
    # (Art. 147A removes IRB equity — all equity uses SA).
    equity_pd_lgd: bool = False
    # PRA PS1/26 Art. 123A(1)(b)(ii) / BCBS CRE20.66: the 0.2%-of-portfolio
    # granularity sub-condition for regulatory-retail qualification (Basel 3.1
    # only). When True (default) an obligor whose aggregate exceeds 0.2% of the
    # total candidate-retail portfolio is re-routed to CORPORATE. Set False to
    # suppress the limb — e.g. when granularity is assessed by another method
    # under CRE20.66's national-discretion clause, or to isolate the other
    # Art. 123A limbs in tests. No effect under CRR (the limb is Basel-3.1 only).
    enforce_retail_granularity: bool = True
    use_investment_grade_assessment: bool = False  # Art. 122(6)/(8): IG=65% / non-IG=135%
    # Art. 122(8): IRB institutions must choose between para 2 (100% flat)
    # or para 6 (65%/135% IG assessment) for unrated corporates. This choice
    # applies to both regular SA calculations and the output floor S-TREA
    # computation (Art. 92 para 2A). The choice must be declared to the PRA.
    crm_collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE
    # Art. 191A: Firm-wide election for financial collateral recognition.
    # COMPREHENSIVE (default): EAD reduction via supervisory haircuts (Art. 223-224).
    # SIMPLE: SA-only risk weight substitution (Art. 222), 20% RW floor on secured portion.
    # IRB exposures always use Foundation Collateral Method regardless of this election.
    airb_collateral_method: AIRBCollateralMethod | None = None
    # Art. 169A/169B: A-IRB collateral recognition method (Basel 3.1 only).
    # LGD_MODELLING (default under B31): own LGD captures collateral effects;
    #   Art. 169B fallback uses Foundation formula with own unsecured LGD.
    # FOUNDATION: uses supervisory LGDS/LGDU, same as F-IRB.
    # None: not applicable under CRR (A-IRB is free-form).
    # Enable splitting one finite collateral item across multiple beneficiaries
    # via the optional collateral_links table (CRR Art. 230-231). When True
    # (default) and a collateral_links table is supplied, the CRM stage splits
    # each finite value across the linked beneficiaries for the most beneficial
    # RWA impact. No-op when no collateral_links table is present; acts as an
    # A/B kill-switch against the single-beneficiary path.
    enable_collateral_link_splitting: bool = True
    # DEPRECATED: collect_engine="streaming" is the legacy spelling of
    # spill_edges=True (accept-and-warn for one release; see
    # docs/plans/target-architecture-migration.md Phase 1). There is one
    # execution semantics: stages exchange materialised frames, in-memory by
    # default, spilled to parquet when spill_edges is set.
    collect_engine: PolarsEngine = "cpu"
    # Spill stage-edge materialisations to parquet instead of holding them
    # in memory (out-of-core mode for very large datasets). A sink failure
    # raises SpillError — never a silent in-memory fallback.
    spill_edges: bool = False
    spill_dir: Path | None = None  # Directory for disk-spill temp files (None = system temp)
    log_level: str = "INFO"  # stdlib logging level for the rwa_calc namespace
    log_format: Literal["text", "json"] = "text"  # "text" for humans, "json" for audit ingestion
    # Opt-in audit cache (see docs/specifications/audit-cache.md). When set, the
    # pipeline persists intermediate CRM frames as parquet under
    # ``<audit_cache_dir>/<run_id>/`` so users can diff or grep ``fx_haircut``,
    # ``collateral_haircut`` and the per-row ``value_after_haircut`` without
    # re-running ``HaircutCalculator`` manually. Default ``None`` = feature off,
    # zero overhead. ``audit_cache_max_runs`` (optional) retains only the N most
    # recent run subdirectories, deleting older ones at the start of each run.
    audit_cache_dir: Path | None = None
    audit_cache_max_runs: int | None = None

    def __post_init__(self) -> None:
        """Derive internal irb_permissions from permission_mode and regime_id.

        Skips derivation when an explicit ``irb_permissions`` was supplied so
        callers can override flags like ``psm_lgd_source`` without losing the
        permission map.
        """
        if self.irb_permissions is not None:
            return
        if self.permission_mode == PermissionMode.IRB:
            if self.regime_id == "b31":
                object.__setattr__(self, "irb_permissions", IRBPermissions.full_irb_b31())
            else:
                object.__setattr__(self, "irb_permissions", IRBPermissions.full_irb())
        else:
            object.__setattr__(self, "irb_permissions", IRBPermissions.sa_only())

    @property
    def framework(self) -> RegulatoryFramework:
        """The RegulatoryFramework enum derived from ``regime_id`` (back-compat).

        ``regime_id`` is the stored regime carrier (Phase 5 S11e); this property
        keeps the enum-typed read sites (logging, COREP, comparison) unchanged.
        """
        return _REGIME_ID_TO_FRAMEWORK[self.regime_id]

    @property
    def is_crr(self) -> bool:
        """Check if using CRR framework."""
        return self.regime_id == "crr"

    @property
    def is_basel_3_1(self) -> bool:
        """Check if using Basel 3.1 framework."""
        return self.regime_id == "b31"

    def get_output_floor_percentage(self) -> Decimal:
        """Get the applicable output floor percentage."""
        return self.output_floor.get_floor_percentage(self.reporting_date)

    def with_fx_rate(self, eur_gbp_rate: Decimal) -> CalculationConfig:
        """Return a new CRR config with ``eur_gbp_rate`` updated.

        Only the rate is carried: the engine derives GBP thresholds from the pack
        EUR bases × ``eur_gbp_rate`` at read time (engine/thresholds.py), so there
        is no config-side threshold to rebuild. No-op for Basel 3.1 (GBP-native
        thresholds; eur_gbp_rate is unused by the B3.1 SME correlation branch per
        PRA PS1/26 Art. 153(4)).
        """
        if self.regime_id != "crr":
            return self
        if eur_gbp_rate == self.eur_gbp_rate:
            return self
        return replace(self, eur_gbp_rate=eur_gbp_rate)

    @classmethod
    def crr(
        cls,
        reporting_date: date,
        permission_mode: PermissionMode = PermissionMode.STANDARDISED,
        base_currency: str = "GBP",
        eur_gbp_rate: Decimal = Decimal("0.8732"),
        enable_double_default: bool = False,
        crm_collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE,
        airb_collateral_method: AIRBCollateralMethod = AIRBCollateralMethod.LGD_MODELLING,
        enable_collateral_link_splitting: bool = True,
        collect_engine: PolarsEngine = "cpu",
        spill_dir: Path | None = None,
        log_level: str = "INFO",
        log_format: Literal["text", "json"] = "text",
        audit_cache_dir: Path | None = None,
        audit_cache_max_runs: int | None = None,
        ccr_alpha: Decimal = Decimal("1.4"),
        enable_ccp_exposures: bool = True,
        mpor_floor_days: int = 10,
        recognise_im: bool = True,
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
            collect_engine: Polars engine for .collect() - 'cpu' (default) for
                in-memory processing, 'streaming' for batched lower-memory execution.

        Returns:
            Configured CalculationConfig for CRR
        """
        return cls(
            regime_id="crr",
            reporting_date=reporting_date,
            base_currency=base_currency,
            output_floor=OutputFloorConfig.crr(),
            post_model_adjustments=PostModelAdjustmentConfig.crr(),
            ccr=CCRConfig(
                method="sa_ccr",
                alpha=ccr_alpha,
                enable_ccp_exposures=enable_ccp_exposures,
                mpor_floor_days=mpor_floor_days,
                recognise_im=recognise_im,
            ),
            permission_mode=permission_mode,
            eur_gbp_rate=eur_gbp_rate,
            enable_double_default=enable_double_default,
            crm_collateral_method=crm_collateral_method,
            airb_collateral_method=airb_collateral_method,
            enable_collateral_link_splitting=enable_collateral_link_splitting,
            collect_engine=collect_engine,
            spill_dir=spill_dir,
            log_level=log_level,
            log_format=log_format,
            audit_cache_dir=audit_cache_dir,
            audit_cache_max_runs=audit_cache_max_runs,
        )

    @classmethod
    def basel_3_1(
        cls,
        reporting_date: date,
        permission_mode: PermissionMode = PermissionMode.STANDARDISED,
        base_currency: str = "GBP",
        post_model_adjustments: PostModelAdjustmentConfig | None = None,
        use_investment_grade_assessment: bool = False,
        institution_type: InstitutionType | None = None,
        reporting_basis: ReportingBasis | None = None,
        gcra_amount: float = 0.0,
        sa_t2_credit: float = 0.0,
        art_40_deductions: float = 0.0,
        skip_transitional_floor: bool = False,
        crm_collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE,
        airb_collateral_method: AIRBCollateralMethod = AIRBCollateralMethod.LGD_MODELLING,
        enforce_retail_granularity: bool = True,
        enable_collateral_link_splitting: bool = True,
        collect_engine: PolarsEngine = "cpu",
        spill_dir: Path | None = None,
        log_level: str = "INFO",
        log_format: Literal["text", "json"] = "text",
        audit_cache_dir: Path | None = None,
        audit_cache_max_runs: int | None = None,
        ccr_alpha: Decimal = Decimal("1.4"),
        enable_ccp_exposures: bool = True,
        mpor_floor_days: int = 10,
        recognise_im: bool = True,
    ) -> CalculationConfig:
        """
        Create Basel 3.1 (PRA PS1/26) configuration.

        Basel 3.1 characteristics:
        - Differentiated PD floors by exposure class
        - LGD floors for A-IRB by collateral type
        - No supporting factors (SME/infrastructure)
        - Output floor (72.5%, transitional) with OF-ADJ
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
            gcra_amount: General credit risk adjustments for OF-ADJ (Art. 92 para 2A).
                Capped at 1.25% of S-TREA.
            sa_t2_credit: Art. 62(c) SA T2 credit for general CRAs (OF-ADJ input).
            art_40_deductions: Art. 40 additional CET1 deductions (OF-ADJ input).
            skip_transitional_floor: When True, bypass the PRA 4-year transitional
                schedule (60%/65%/70%/72.5%) and apply the full 72.5% floor from
                day one. Art. 92 para 5 says institutions "may apply" the transitional
                rates — they are permissive, not mandatory.
            enforce_retail_granularity: Art. 123A(1)(b)(ii) / CRE20.66 — when True
                (default) the 0.2%-of-portfolio retail granularity limb is applied
                and concentrated obligors are re-routed to CORPORATE. Set False to
                suppress the limb (granularity assessed by another method, or to
                isolate the other Art. 123A limbs in tests).
            collect_engine: Polars engine for .collect() - 'cpu' (default) for
                in-memory processing, 'streaming' for batched lower-memory execution.

        Returns:
            Configured CalculationConfig for Basel 3.1
        """
        return cls(
            regime_id="b31",
            reporting_date=reporting_date,
            base_currency=base_currency,
            output_floor=OutputFloorConfig.basel_3_1(
                institution_type=institution_type,
                reporting_basis=reporting_basis,
                gcra_amount=gcra_amount,
                sa_t2_credit=sa_t2_credit,
                art_40_deductions=art_40_deductions,
                skip_transitional=skip_transitional_floor,
            ),
            post_model_adjustments=(
                post_model_adjustments or PostModelAdjustmentConfig.basel_3_1()
            ),
            ccr=CCRConfig(
                method="sa_ccr",
                alpha=ccr_alpha,
                enable_ccp_exposures=enable_ccp_exposures,
                mpor_floor_days=mpor_floor_days,
                recognise_im=recognise_im,
            ),
            permission_mode=permission_mode,
            equity_transitional=EquityTransitionalConfig.basel_3_1(),
            eur_gbp_rate=Decimal("0.8732"),  # Used only to derive sme_balance_sheet_threshold
            use_investment_grade_assessment=use_investment_grade_assessment,
            crm_collateral_method=crm_collateral_method,
            airb_collateral_method=airb_collateral_method,
            enable_collateral_link_splitting=enable_collateral_link_splitting,
            enforce_retail_granularity=enforce_retail_granularity,
            collect_engine=collect_engine,
            spill_dir=spill_dir,
            log_level=log_level,
            log_format=log_format,
            audit_cache_dir=audit_cache_dir,
            audit_cache_max_runs=audit_cache_max_runs,
        )


# =============================================================================
# RunConfig (Phase 5 S11) — the canonical name for the per-run configuration.
# Currently a transparent alias of CalculationConfig (zero behaviour change); in
# S11e the dataclass is carved into a regime-agnostic RunConfig (zero regulatory
# values) and the alias direction flips (CalculationConfig = RunConfig back-compat).
# See .claude/state/phase5-s11-plan.md.
# =============================================================================
RunConfig = CalculationConfig

# Parallel-run reconciliation configuration (ComponentMapping / LegacyColumnMapping)
# moved to rwa_calc.analysis.recon_registry (migration Phase 6 - analysis layer).
