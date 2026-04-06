"""
Standardised Approach (SA) Calculator for RWA.

Implements CRR Art. 112-134 and Basel 3.1 CRE20 risk weight lookups and RWA
calculation. Supports both frameworks via config.is_basel_3_1 branching.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- CQS-based risk weight lookup (sovereign, institution, corporate)
- LTV-based weights for real estate (CRR split vs Basel 3.1 LTV bands)
- ADC exposure treatment (Basel 3.1: 150% / 100% pre-sold)
- Revised Basel 3.1 corporate CQS weights (CQS3: 75%, CQS5: 100%)
- SCRA-based institution risk weights for unrated exposures (Basel 3.1)
- Investment-grade corporate treatment (65%, Basel 3.1)
- SME corporate treatment (85%, Basel 3.1)
- Subordinated debt flat 150% (Basel 3.1)
- Defaulted exposure treatment (CRR Art. 127 / CRE20.88-90)
- Supporting factor application (CRR only — removed under Basel 3.1)
- RWA calculation (EAD × RW × supporting factor)

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 127: Defaulted exposure risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
- CRE20.16-21: Basel 3.1 institution ECRA/SCRA risk weights
- CRE20.22-26: Basel 3.1 revised corporate CQS risk weights
- CRE20.47-49: Basel 3.1 subordinated debt, investment-grade, SME corporate
- CRE20.88-90: Basel 3.1 defaulted exposure risk weights
- PRA Art. 124F: Basel 3.1 residential RE (general) loan-splitting
- CRE20.82: Basel 3.1 residential RE (income-producing) LTV bands
- CRE20.85: Basel 3.1 commercial RE (general) preferential treatment
- CRE20.86: Basel 3.1 commercial RE (income-producing) LTV bands
- CRE20.87-88: Basel 3.1 ADC exposures
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SAResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.tables.b31_risk_weights import (
    B31_CORPORATE_INVESTMENT_GRADE_RW,
    B31_CORPORATE_NON_INVESTMENT_GRADE_RW,
    B31_CORPORATE_SME_RW,
    B31_DEFAULTED_PROVISION_THRESHOLD,
    B31_DEFAULTED_RESI_RE_NON_INCOME_RW,
    B31_DEFAULTED_RW_HIGH_PROVISION,
    B31_DEFAULTED_RW_LOW_PROVISION,
    B31_ECRA_SHORT_TERM_RISK_WEIGHTS,
    B31_HIGH_RISK_RW,
    B31_SCRA_RISK_WEIGHTS,
    B31_SCRA_SHORT_TERM_RISK_WEIGHTS,
    B31_SUBORDINATED_DEBT_RW,
    b31_adc_rw_expr,
    b31_commercial_rw_expr,
    b31_residential_rw_expr,
    b31_sa_sl_rw_expr,
    get_b31_combined_cqs_risk_weights,
)
from rwa_calc.data.tables.crr_risk_weights import (
    COMMERCIAL_RE_PARAMS,
    CRR_DEFAULTED_PROVISION_THRESHOLD,
    CRR_DEFAULTED_RW_HIGH_PROVISION,
    CRR_DEFAULTED_RW_LOW_PROVISION,
    HIGH_RISK_RW,
    IO_ZERO_RW,
    MDB_NAMED_ZERO_RW,
    MDB_UNRATED_RW,
    OTHER_ITEMS_CASH_RW,
    OTHER_ITEMS_COLLECTION_RW,
    OTHER_ITEMS_DEFAULT_RW,
    PSE_SHORT_TERM_RW,
    PSE_UNRATED_DEFAULT_RW,
    QCCP_CLIENT_CLEARED_RW,
    QCCP_PROPRIETARY_RW,
    RESIDENTIAL_MORTGAGE_PARAMS,
    RETAIL_RISK_WEIGHT,
    RGLA_DOMESTIC_CURRENCY_RW,
    RGLA_UK_DEVOLVED_RW,
    RGLA_UNRATED_DEFAULT_RW,
    get_combined_cqs_risk_weights,
)
from rwa_calc.data.tables.eu_sovereign import build_eu_domestic_currency_expr
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class SACalculationError:
    """Error during SA calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


class SACalculator:
    """
    Calculate RWA using Standardised Approach.

    Implements SACalculatorProtocol for:
    - CQS-based risk weight lookup (sovereign, institution, corporate)
    - Fixed retail risk weight (75%)
    - LTV-based real estate risk weights
    - Supporting factor application (CRR only)

    Usage:
        calculator = SACalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def __init__(self) -> None:
        """Initialize SA calculator with sub-components."""
        self._supporting_factor_calc = SupportingFactorCalculator()
        self._risk_weight_tables: dict[str, pl.DataFrame] | None = None

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using Standardised Approach.

        Args:
            data: CRM-adjusted exposures (uses sa_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with SA RWA calculations
        """
        bundle = self.get_sa_result_bundle(data, config)

        # Convert bundle errors to CalculationErrors
        calc_errors = [
            CalculationError(
                code="SA001",
                message=str(err),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CALCULATION,
            )
            for err in bundle.errors
        ]

        return LazyFrameResult(
            frame=bundle.results,
            errors=calc_errors,
        )

    def get_sa_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """
        Calculate SA RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            SAResultBundle with results and audit trail
        """
        errors: list[SACalculationError] = []

        # Get SA exposures
        exposures = data.sa_exposures

        # Step 1: Look up risk weights
        exposures = self._apply_risk_weights(exposures, config)

        # Step 2: Apply guarantee substitution (blended risk weight)
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 2b: Apply currency mismatch multiplier (Basel 3.1 Art. 123B)
        exposures = self._apply_currency_mismatch_multiplier(exposures, config)

        # Step 3: Calculate pre-factor RWA
        exposures = self._calculate_rwa(exposures)

        # Step 4: Apply supporting factors (CRR only)
        exposures = self._apply_supporting_factors(exposures, config)

        # Step 5: Build audit trail
        audit = self._build_audit(exposures)

        return SAResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=errors,
        )

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SA risk weights to SA rows on a unified frame.

        Operates on the full unified frame (SA + IRB + slotting rows together).
        Only modifies columns for rows where approach == 'standardised'.

        Steps:
        1. Join risk weight table (unconditional — SA-equivalent RW for output floor)
        2. Apply SA-specific RW overrides (mortgage LTV, retail fixed, etc.)
        3. Apply SA guarantee substitution
        4. Calculate RWA = EAD x RW (SA rows only)
        5. Apply supporting factors (SA rows only)

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with SA columns populated for SA rows
        """
        is_sa = pl.col("approach") == ApproachType.SA.value

        # Step 1-2: Apply risk weights (runs unconditionally — also provides
        # SA-equivalent RW for IRB output floor)
        exposures = self._apply_risk_weights(exposures, config)

        # Step 3: Guarantee substitution (already conditional on guaranteed_portion > 0)
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 3a: Currency mismatch multiplier (Basel 3.1 Art. 123B)
        exposures = self._apply_currency_mismatch_multiplier(exposures, config)

        # Step 3b: Store SA-equivalent RWA for ALL rows before IRB calculator
        # overwrites risk_weight. The output floor needs: floor_rwa = floor_pct × sa_rwa.
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        if config.output_floor.enabled:
            exposures = exposures.with_columns(
                (pl.col(ead_col) * pl.col("risk_weight")).alias("sa_rwa"),
            )

        # Step 4: Calculate pre-factor RWA (SA rows only)
        exposures = exposures.with_columns(
            [
                pl.when(is_sa)
                .then(pl.col(ead_col) * pl.col("risk_weight"))
                .otherwise(
                    pl.col("rwa_pre_factor")
                    if "rwa_pre_factor" in schema.names()
                    else pl.lit(None).cast(pl.Float64)
                )
                .alias("rwa_pre_factor"),
            ]
        )

        # Step 5: Apply supporting factors (SA rows only)
        exposures = self._apply_supporting_factors(exposures, config)

        return exposures

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate SA RWA on pre-filtered SA-only rows.

        Unlike calculate_unified(), expects only SA rows — no approach guards
        needed for RWA calculation. Risk weight join runs on ~55K SA rows
        instead of the full 100K unified frame.

        Args:
            exposures: Pre-filtered SA rows only
            config: Calculation configuration

        Returns:
            LazyFrame with SA RWA columns populated
        """
        # Step 1-2: Apply risk weights
        exposures = self._apply_risk_weights(exposures, config)

        # Step 3: Guarantee substitution
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 3b: Currency mismatch multiplier (Basel 3.1 Art. 123B)
        exposures = self._apply_currency_mismatch_multiplier(exposures, config)

        # Step 4: Calculate pre-factor RWA (all rows are SA — no guard needed)
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        exposures = exposures.with_columns(
            (pl.col(ead_col) * pl.col("risk_weight")).alias("rwa_pre_factor"),
        )

        # Step 5: Apply supporting factors
        exposures = self._apply_supporting_factors(exposures, config)

        return exposures

    def _apply_risk_weights(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Look up and apply risk weights based on exposure class.

        Handles:
        - CQS-based lookups (sovereign, institution, corporate)
        - Fixed retail (75%)
        - LTV-based real estate (split treatment)

        Args:
            exposures: SA exposures with classification
            config: Calculation configuration

        Returns:
            Exposures with risk_weight column added
        """
        # Get CQS-based risk weight table — Basel 3.1 uses revised corporate weights
        use_uk_deviation = config.base_currency == "GBP"
        if config.is_basel_3_1:
            rw_table = get_b31_combined_cqs_risk_weights(use_uk_deviation).lazy()
        else:
            rw_table = get_combined_cqs_risk_weights(use_uk_deviation).lazy()

        # Ensure required columns exist (single with_columns call)
        schema = exposures.collect_schema()
        missing_cols = []
        if "ltv" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Float64).alias("ltv"))
        if "has_income_cover" not in schema.names():
            missing_cols.append(pl.lit(False).alias("has_income_cover"))
        if "book_code" not in schema.names():
            missing_cols.append(pl.lit("").alias("book_code"))
        if "cp_is_managed_as_retail" not in schema.names():
            missing_cols.append(pl.lit(False).alias("cp_is_managed_as_retail"))
        if "qualifies_as_retail" not in schema.names():
            missing_cols.append(pl.lit(True).alias("qualifies_as_retail"))
        if "property_type" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("property_type"))
        if "is_adc" not in schema.names():
            missing_cols.append(pl.lit(False).alias("is_adc"))
        if "is_presold" not in schema.names():
            missing_cols.append(pl.lit(False).alias("is_presold"))
        if "seniority" not in schema.names():
            missing_cols.append(pl.lit("senior").alias("seniority"))
        if "cp_scra_grade" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("cp_scra_grade"))
        if "cp_is_investment_grade" not in schema.names():
            missing_cols.append(pl.lit(False).alias("cp_is_investment_grade"))
        if "is_defaulted" not in schema.names():
            missing_cols.append(pl.lit(False).alias("is_defaulted"))
        if "provision_allocated" not in schema.names():
            missing_cols.append(pl.lit(0.0).alias("provision_allocated"))
        if "provision_deducted" not in schema.names():
            missing_cols.append(pl.lit(0.0).alias("provision_deducted"))
        if "currency" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("currency"))
        if "cp_country_code" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("cp_country_code"))
        if "cp_entity_type" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("cp_entity_type"))
        if "cp_is_ccp_client_cleared" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Boolean).alias("cp_is_ccp_client_cleared"))
        if "sl_type" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("sl_type"))
        if "sl_project_phase" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Utf8).alias("sl_project_phase"))
        if "is_qrre_transactor" not in schema.names():
            missing_cols.append(pl.lit(False).alias("is_qrre_transactor"))
        if "residual_maturity_years" not in schema.names():
            missing_cols.append(pl.lit(None).cast(pl.Float64).alias("residual_maturity_years"))
        if "is_short_term_trade_lc" not in schema.names():
            missing_cols.append(pl.lit(False).alias("is_short_term_trade_lc"))
        if missing_cols:
            exposures = exposures.with_columns(missing_cols)

        # CRR Art. 114(3)/(4): Domestic CGCB exposures → 0% RW
        # UK sovereign in GBP, or EU sovereign in that member state's domestic currency
        _is_uk_domestic_currency = (pl.col("cp_country_code") == "GB") & (
            pl.col("currency") == "GBP"
        )
        _is_eu_domestic_currency = build_eu_domestic_currency_expr("cp_country_code", "currency")
        _is_domestic_currency = _is_uk_domestic_currency | _is_eu_domestic_currency

        # Prepare exposures for join
        # Compute uppercase once for all comparisons (avoids repeated regex)
        # Use sentinel value -1 for null CQS to allow join (null != null in joins)
        _upper = pl.col("exposure_class").str.to_uppercase()
        exposures = exposures.with_columns(
            [
                # Map detailed classes to lookup classes
                pl.when(_upper.str.contains("CENTRAL_GOVT", literal=True))
                .then(pl.lit("CENTRAL_GOVT_CENTRAL_BANK"))
                .when(_upper == "RGLA")
                .then(pl.lit("RGLA"))
                .when(_upper == "PSE")
                .then(pl.lit("PSE"))
                .when(_upper == "MDB")
                .then(pl.lit("MDB"))
                .when(_upper.str.contains("INSTITUTION", literal=True))
                .then(pl.lit("INSTITUTION"))
                .when(_upper.str.contains("CORPORATE", literal=True))
                .then(pl.lit("CORPORATE"))
                # Rated SL uses corporate CQS table (Art. 122A(3))
                .when(_upper.str.contains("SPECIALISED", literal=True))
                .then(pl.lit("CORPORATE"))
                .when(_upper.str.contains("COVERED_BOND", literal=True))
                .then(pl.lit("COVERED_BOND"))
                .otherwise(_upper)
                .alias("_lookup_class"),
                # Use -1 as sentinel for null CQS (for join matching)
                pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("_lookup_cqs"),
                # Cache uppercase for risk weight override chain
                _upper.alias("_upper_class"),
            ]
        )

        # Prepare risk weight table with same sentinel for null CQS
        rw_table = rw_table.with_columns(
            [
                pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("cqs"),
            ]
        )

        # Join risk weight table
        exposures = exposures.join(
            rw_table.select(["exposure_class", "cqs", "risk_weight"]),
            left_on=["_lookup_class", "_lookup_cqs"],
            right_on=["exposure_class", "cqs"],
            how="left",
            suffix="_rw",
        )

        # Apply class-specific risk weights (framework-dependent)
        retail_rw = float(RETAIL_RISK_WEIGHT)
        _uc = pl.col("_upper_class")

        if config.is_basel_3_1:
            # Save CQS-based risk weight before override — needed for
            # Basel 3.1 general CRE min(60%, counterparty_rw) logic (CRE20.85)
            exposures = exposures.with_columns(
                pl.col("risk_weight").fill_null(1.0).alias("_cqs_risk_weight")
            )

            # Basel 3.1 ECRA short-term risk weights for rated institutions (Table 4)
            ecra_st_low_rw = float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[1])  # CQS 1-5: 20%
            ecra_st_high_rw = float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[6])  # CQS 6: 150%
            # Basel 3.1 SCRA risk weights for unrated institutions (CRE20.16-21)
            # Long-term (>3m)
            scra_a_rw = float(B31_SCRA_RISK_WEIGHTS["A"])
            scra_ae_rw = float(B31_SCRA_RISK_WEIGHTS["A_ENHANCED"])
            scra_b_rw = float(B31_SCRA_RISK_WEIGHTS["B"])
            scra_c_rw = float(B31_SCRA_RISK_WEIGHTS["C"])
            # Short-term (≤3m)
            scra_st_a_rw = float(B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"])
            scra_st_b_rw = float(B31_SCRA_SHORT_TERM_RISK_WEIGHTS["B"])
            scra_st_c_rw = float(B31_SCRA_SHORT_TERM_RISK_WEIGHTS["C"])
            inv_grade_rw = float(B31_CORPORATE_INVESTMENT_GRADE_RW)
            non_inv_grade_rw = float(B31_CORPORATE_NON_INVESTMENT_GRADE_RW)
            sme_corp_rw = float(B31_CORPORATE_SME_RW)
            sub_debt_rw = float(B31_SUBORDINATED_DEBT_RW)
            b31_def_threshold = float(B31_DEFAULTED_PROVISION_THRESHOLD)
            b31_def_high_rw = float(B31_DEFAULTED_RW_HIGH_PROVISION)
            b31_def_low_rw = float(B31_DEFAULTED_RW_LOW_PROVISION)

            # EAD column for provision ratio denominator
            schema_for_ead = exposures.collect_schema()
            _ead_col = "ead_final" if "ead_final" in schema_for_ead.names() else "ead"

            exposures = exposures.with_columns(
                [
                    # 0. Art. 114(3)/(4): Domestic CGCB → 0% RW (overrides all CQS)
                    pl.when(_uc.str.contains("CENTRAL_GOVT", literal=True) & _is_domestic_currency)
                    .then(pl.lit(0.0))
                    # 1. Defaulted exposures: 150% or 100% (PRA PS1/26 Art. 127)
                    # HIGH_RISK excluded: Art. 128 (150%) takes priority over
                    # Art. 127 per Art. 112 Table A2 classification ordering.
                    # B31 provision ratio = provision_allocated / ead (exposure value)
                    # NOT (ead + provision_deducted) — that is the CRR denominator.
                    # Exception: general RESI RE (non-income-dependent) always 100%
                    # per CRE20.88 / Art. 127 — Basel 3.1 simplification.
                    .when(pl.col("is_defaulted").fill_null(False) & (_uc != "HIGH_RISK"))
                    .then(
                        # RESI RE non-income-dependent: 100% flat (CRE20.88)
                        pl.when(
                            (
                                _uc.str.contains("MORTGAGE", literal=True)
                                | _uc.str.contains("RESIDENTIAL", literal=True)
                            )
                            & ~pl.col("has_income_cover").fill_null(False)
                        )
                        .then(pl.lit(float(B31_DEFAULTED_RESI_RE_NON_INCOME_RW)))
                        # All other defaulted: provision-based (Art. 127)
                        .when(pl.col("provision_allocated") >= b31_def_threshold * pl.col(_ead_col))
                        .then(pl.lit(b31_def_high_rw))
                        .otherwise(pl.lit(b31_def_low_rw))
                    )
                    # 2. QCCP trade exposures: 2% proprietary / 4% client-cleared
                    # (CRR Art. 306, CRE54.14-15)
                    .when(pl.col("cp_entity_type") == "ccp")
                    .then(
                        pl.when(pl.col("cp_is_ccp_client_cleared").fill_null(False))
                        .then(pl.lit(float(QCCP_CLIENT_CLEARED_RW)))
                        .otherwise(pl.lit(float(QCCP_PROPRIETARY_RW)))
                    )
                    # 3. Subordinated debt: flat 150% (CRE20.47)
                    # Overrides all CQS-based weights for institution + corporate
                    .when(
                        (pl.col("seniority").fill_null("senior") == "subordinated")
                        & (
                            _uc.str.contains("INSTITUTION", literal=True)
                            | _uc.str.contains("CORPORATE", literal=True)
                        )
                    )
                    .then(pl.lit(sub_debt_rw))
                    # 4. ADC: 150% or 100% pre-sold (CRE20.87-88)
                    .when(pl.col("is_adc").fill_null(False))
                    .then(b31_adc_rw_expr())
                    # 2. Residential mortgage: loan-split (Art. 124F) / LTV-band (Art. 124G)
                    .when(
                        _uc.str.contains("MORTGAGE", literal=True)
                        | _uc.str.contains("RESIDENTIAL", literal=True)
                    )
                    .then(b31_residential_rw_expr("_cqs_risk_weight"))
                    # 3. Commercial RE: LTV-band or min() (CRE20.85/86)
                    .when(
                        _uc.str.contains("COMMERCIAL", literal=True)
                        | _uc.str.contains("CRE", literal=True)
                        | (pl.col("property_type").fill_null("") == "commercial")
                    )
                    .then(b31_commercial_rw_expr("_cqs_risk_weight"))
                    # 4a. PSE short-term (Art. 116(3)): ≤3m → 20% flat
                    # No domestic currency condition. Overrides all CQS-based weights.
                    .when(
                        (_uc == "PSE")
                        & pl.col("residual_maturity_years").is_not_null()
                        & (pl.col("residual_maturity_years") <= 0.25)
                    )
                    .then(pl.lit(float(PSE_SHORT_TERM_RW)))
                    # 4b. PSE unrated: sovereign-derived (Art. 116(1), Table 2)
                    # Rated PSEs use Table 2A from CQS join; unrated need sovereign CQS.
                    # UK sovereign CQS=1 → 20%. Non-UK: conservative 100%.
                    .when((_uc == "PSE") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
                    .then(
                        pl.when(pl.col("cp_country_code") == "GB")
                        .then(pl.lit(0.20))  # UK sovereign CQS 1 → Table 2 row 1
                        .otherwise(pl.lit(float(PSE_UNRATED_DEFAULT_RW)))
                    )
                    # 4c-rgla. RGLA UK devolved govt → 0% (PRA designation)
                    # Overrides all other RGLA treatments for devolved administrations.
                    .when(
                        (_uc == "RGLA")
                        & (pl.col("cp_entity_type").fill_null("") == "rgla_sovereign")
                        & (pl.col("cp_country_code") == "GB")
                    )
                    .then(pl.lit(float(RGLA_UK_DEVOLVED_RW)))
                    # 4d-rgla. RGLA domestic currency → 20% (Art. 115(5))
                    # UK+GBP or EU+domestic currency → 20% regardless of CQS.
                    .when((_uc == "RGLA") & _is_domestic_currency)
                    .then(pl.lit(float(RGLA_DOMESTIC_CURRENCY_RW)))
                    # 4e-rgla. RGLA unrated non-domestic: sovereign-derived (Table 1A)
                    # UK sovereign CQS=1 → 20%. Non-UK: conservative 100%.
                    .when((_uc == "RGLA") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
                    .then(
                        pl.when(pl.col("cp_country_code") == "GB")
                        .then(pl.lit(0.20))  # UK sovereign CQS 1 → Table 1A row 1
                        .otherwise(pl.lit(float(RGLA_UNRATED_DEFAULT_RW)))
                    )
                    # Rated RGLA: falls through to CQS join (Table 1B) via default
                    # 4f-mdb. Named MDB → 0% (Art. 117(2))
                    # 16 named MDBs get 0% unconditionally, identified by mdb_named entity_type.
                    .when((_uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "mdb_named"))
                    .then(pl.lit(float(MDB_NAMED_ZERO_RW)))
                    # 4g-io. International Organisation → 0% (Art. 118)
                    # EU, IMF, BIS, EFSF, ESM — always 0%.
                    .when(
                        (_uc == "MDB")
                        & (pl.col("cp_entity_type").fill_null("") == "international_org")
                    )
                    .then(pl.lit(float(IO_ZERO_RW)))
                    # 4h-mdb. Unrated non-named MDB → 50% (Art. 117(1), Table 2B)
                    .when((_uc == "MDB") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
                    .then(pl.lit(float(MDB_UNRATED_RW)))
                    # Rated non-named MDB: falls through to CQS join (Table 2B) via default
                    # 4b-ecra. ECRA short-term rated institutions (Table 4, Art. 120)
                    # Rated institutions with residual maturity ≤ 3m get preferential
                    # weights: CQS 1-5 = 20%, CQS 6 = 150%. Also applies to trade
                    # finance exposures with residual maturity ≤ 6m (Art. 121(5)).
                    .when(
                        _uc.str.contains("INSTITUTION", literal=True)
                        & (pl.col("cqs").is_not_null() & (pl.col("cqs") > 0))
                        & (
                            (pl.col("residual_maturity_years").fill_null(1.0) <= 0.25)
                            | (
                                pl.col("is_short_term_trade_lc").fill_null(False)
                                & (pl.col("residual_maturity_years").fill_null(1.0) <= 0.5)
                            )
                        )
                    )
                    .then(
                        pl.when(pl.col("cqs") <= 5)
                        .then(pl.lit(ecra_st_low_rw))
                        .otherwise(pl.lit(ecra_st_high_rw))
                    )
                    # 4c. SCRA-based unrated institutions (CRE20.16-21)
                    # Only for unrated (CQS is null/-1) — rated use ECRA from CQS join
                    # Null SCRA grade defaults to Grade C (150%) — conservative treatment
                    # per PRA PS1/26 Art. 120A (missing data must not produce favourable RW)
                    # Short-term (≤3m): Grade A/A_ENHANCED → 20%, Grade B → 50%, C → 150%
                    .when(
                        _uc.str.contains("INSTITUTION", literal=True)
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                        & (pl.col("residual_maturity_years").fill_null(1.0) <= 0.25)
                    )
                    .then(
                        pl.when(pl.col("cp_scra_grade").is_in(["A", "A_ENHANCED"]))
                        .then(pl.lit(scra_st_a_rw))
                        .when(pl.col("cp_scra_grade") == "B")
                        .then(pl.lit(scra_st_b_rw))
                        .otherwise(pl.lit(scra_st_c_rw))
                    )
                    # 4d. SCRA long-term unrated institutions (>3m) (CRE20.16-21)
                    .when(
                        _uc.str.contains("INSTITUTION", literal=True)
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                    )
                    .then(
                        pl.when(pl.col("cp_scra_grade") == "A_ENHANCED")
                        .then(pl.lit(scra_ae_rw))
                        .when(pl.col("cp_scra_grade") == "A")
                        .then(pl.lit(scra_a_rw))
                        .when(pl.col("cp_scra_grade") == "B")
                        .then(pl.lit(scra_b_rw))
                        .otherwise(pl.lit(scra_c_rw))
                    )
                    # 5. Investment-grade assessment (Art. 122(6))
                    # Only active when use_investment_grade_assessment=True.
                    # IG corporates → 65% (Art. 122(6)(a)), non-IG → 135% (Art. 122(6)(b))
                    # Without this election, all unrated corporates get 100%.
                    .when(
                        pl.lit(config.use_investment_grade_assessment)
                        & _uc.str.contains("CORPORATE", literal=True)
                        & ~_uc.str.contains("SME", literal=True)
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                        & (pl.col("cp_is_investment_grade").fill_null(False) == True)  # noqa: E712
                    )
                    .then(pl.lit(inv_grade_rw))
                    # 5b. Non-investment-grade unrated corporate: 135% (Art. 122(6)(b))
                    .when(
                        pl.lit(config.use_investment_grade_assessment)
                        & _uc.str.contains("CORPORATE", literal=True)
                        & ~_uc.str.contains("SME", literal=True)
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                        & (pl.col("cp_is_investment_grade").fill_null(False) != True)  # noqa: E712
                    )
                    .then(pl.lit(non_inv_grade_rw))
                    # 6. SME managed as retail: 75% (same both frameworks)
                    # Art. 123 requires aggregated exposure ≤ EUR 1m threshold.
                    .when(
                        _uc.str.contains("SME", literal=True)
                        & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
                        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
                    )
                    .then(pl.lit(retail_rw))
                    # 7. SA Specialised Lending (unrated only): Art. 122A-122B
                    # Rated SL exposures use the corporate CQS table (Art. 122A(3))
                    .when(
                        (
                            _uc.str.contains("SPECIALISED", literal=True)
                            | (pl.col("sl_type").fill_null("").str.len_chars() > 0)
                        )
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                    )
                    .then(b31_sa_sl_rw_expr())
                    # 8. Corporate SME: 85% (CRE20.47-49, Basel 3.1)
                    .when(
                        _uc.str.contains("CORPORATE", literal=True)
                        & _uc.str.contains("SME", literal=True)
                    )
                    .then(pl.lit(sme_corp_rw))
                    # 9. QRRE transactor: 45% (Art. 123)
                    .when(
                        _uc.str.contains("RETAIL", literal=True)
                        & pl.col("is_qrre_transactor").fill_null(False)
                    )
                    .then(pl.lit(0.45))
                    # 9a. Non-regulatory retail: 100% (Art. 123(3)(c))
                    # Retail exposures failing Art. 123A qualifying criteria
                    .when(
                        _uc.str.contains("RETAIL", literal=True)
                        & (pl.col("qualifies_as_retail").fill_null(True) == False)  # noqa: E712
                    )
                    .then(pl.lit(1.0))
                    # 10. Regulatory retail (non-mortgage): 75% flat
                    .when(_uc.str.contains("RETAIL", literal=True))
                    .then(pl.lit(retail_rw))
                    # 11. Unrated covered bonds: derive from issuer institution RW
                    # (Art. 129(5)) — SCRA grade → institution RW → CB RW via
                    # COVERED_BOND_UNRATED_DERIVATION table:
                    #   A_ENHANCED (inst 30%) → CB 15%
                    #   A (inst 40%) → CB 20%
                    #   B (inst 75%) → CB 35%
                    #   C (inst 150%) → CB 100%
                    .when(
                        _uc.str.contains("COVERED_BOND", literal=True)
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                    )
                    .then(
                        pl.when(pl.col("cp_scra_grade") == "A_ENHANCED")
                        .then(pl.lit(0.15))
                        .when(pl.col("cp_scra_grade") == "A")
                        .then(pl.lit(0.20))
                        .when(pl.col("cp_scra_grade") == "B")
                        .then(pl.lit(0.35))
                        .when(pl.col("cp_scra_grade") == "C")
                        .then(pl.lit(1.00))
                        .otherwise(pl.lit(1.00))  # Default: assume Grade C (conservative)
                    )
                    # 11a. High-risk items → 150% (Art. 128)
                    # Venture capital, private equity, speculative RE financing,
                    # and other PRA-designated high-risk items.
                    .when(_uc == "HIGH_RISK")
                    .then(pl.lit(float(B31_HIGH_RISK_RW)))
                    # 12. Other Items (Art. 134): sub-type-specific risk weights
                    # 12a. Cash/gold → 0% (Art. 134(1)/(4))
                    .when(
                        (_uc == "OTHER")
                        & (
                            pl.col("cp_entity_type")
                            .fill_null("")
                            .is_in(["other_cash", "other_gold"])
                        )
                    )
                    .then(pl.lit(float(OTHER_ITEMS_CASH_RW)))
                    # 12b. Items in course of collection → 20% (Art. 134(3))
                    .when(
                        (_uc == "OTHER")
                        & (pl.col("cp_entity_type").fill_null("") == "other_items_in_collection")
                    )
                    .then(pl.lit(float(OTHER_ITEMS_COLLECTION_RW)))
                    # 12c. Residual lease value → 1/t × 100% (Art. 134(6))
                    .when(
                        (_uc == "OTHER")
                        & (pl.col("cp_entity_type").fill_null("") == "other_residual_lease")
                    )
                    .then(
                        pl.lit(1.0)
                        / pl.col("residual_maturity_years").fill_null(1.0).clip(lower_bound=1.0)
                    )
                    # 12d. Tangible assets and all other → 100% (Art. 134(2))
                    .when(_uc == "OTHER")
                    .then(pl.lit(float(OTHER_ITEMS_DEFAULT_RW)))
                    # Default: CQS-based or 100%
                    .otherwise(pl.col("risk_weight").fill_null(1.0))
                    .alias("risk_weight"),
                ]
            )
        else:
            # CRR risk weight overrides (Art. 112-134)
            resi_threshold = float(RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"])
            resi_rw_low = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"])
            resi_rw_high = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_high_ltv"])
            cre_threshold = float(COMMERCIAL_RE_PARAMS["ltv_threshold"])
            cre_rw_low = float(COMMERCIAL_RE_PARAMS["rw_low_ltv"])
            cre_rw_standard = float(COMMERCIAL_RE_PARAMS["rw_standard"])
            crr_def_threshold = float(CRR_DEFAULTED_PROVISION_THRESHOLD)
            crr_def_high_rw = float(CRR_DEFAULTED_RW_HIGH_PROVISION)
            crr_def_low_rw = float(CRR_DEFAULTED_RW_LOW_PROVISION)

            # EAD column for provision ratio denominator
            schema_for_ead = exposures.collect_schema()
            _ead_col = "ead_final" if "ead_final" in schema_for_ead.names() else "ead"

            exposures = exposures.with_columns(
                [
                    # 0. Art. 114(3)/(4): Domestic CGCB → 0% RW (overrides all CQS)
                    pl.when(_uc.str.contains("CENTRAL_GOVT", literal=True) & _is_domestic_currency)
                    .then(pl.lit(0.0))
                    # 1. Defaulted exposures: 100% or 150% (CRR Art. 127)
                    # HIGH_RISK excluded: Art. 128 (150%) takes priority over
                    # Art. 127 per Art. 112 Table A2 classification ordering.
                    # Provision ratio = provision_allocated / (ead + provision_deducted)
                    # where denominator reconstructs pre-provision unsecured EAD
                    .when(pl.col("is_defaulted").fill_null(False) & (_uc != "HIGH_RISK"))
                    .then(
                        pl.when(
                            pl.col("provision_allocated")
                            >= crr_def_threshold * (pl.col(_ead_col) + pl.col("provision_deducted"))
                        )
                        .then(pl.lit(crr_def_high_rw))
                        .otherwise(pl.lit(crr_def_low_rw))
                    )
                    # 2. QCCP trade exposures: 2% proprietary / 4% client-cleared
                    # (CRR Art. 306, CRE54.14-15)
                    .when(pl.col("cp_entity_type") == "ccp")
                    .then(
                        pl.when(pl.col("cp_is_ccp_client_cleared").fill_null(False))
                        .then(pl.lit(float(QCCP_CLIENT_CLEARED_RW)))
                        .otherwise(pl.lit(float(QCCP_PROPRIETARY_RW)))
                    )
                    # 3. Residential mortgage: LTV split (CRR Art. 125)
                    .when(
                        _uc.str.contains("MORTGAGE", literal=True)
                        | _uc.str.contains("RESIDENTIAL", literal=True)
                    )
                    .then(
                        pl.when(pl.col("ltv").fill_null(0.0) <= resi_threshold)
                        .then(pl.lit(resi_rw_low))
                        .otherwise(
                            resi_rw_low * resi_threshold / pl.col("ltv").fill_null(1.0)
                            + resi_rw_high
                            * (pl.col("ltv").fill_null(1.0) - resi_threshold)
                            / pl.col("ltv").fill_null(1.0)
                        )
                    )
                    # 2. Commercial RE: LTV + income cover (CRR Art. 126)
                    .when(
                        _uc.str.contains("COMMERCIAL", literal=True)
                        | _uc.str.contains("CRE", literal=True)
                        | (pl.col("property_type").fill_null("") == "commercial")
                    )
                    .then(
                        pl.when(
                            (pl.col("ltv").fill_null(1.0) <= cre_threshold)
                            & pl.col("has_income_cover").fill_null(False)
                        )
                        .then(pl.lit(cre_rw_low))
                        .otherwise(pl.lit(cre_rw_standard))
                    )
                    # 3. SME managed as retail: 75% (CRR Art. 123)
                    # Art. 123 requires aggregated exposure ≤ EUR 1m threshold.
                    .when(
                        _uc.str.contains("SME", literal=True)
                        & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
                        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
                    )
                    .then(pl.lit(retail_rw))
                    # 4. Corporate SME: 100%
                    .when(
                        _uc.str.contains("CORPORATE", literal=True)
                        & _uc.str.contains("SME", literal=True)
                    )
                    .then(pl.lit(1.0))
                    # 5. Non-regulatory retail: 100% (Art. 123(c))
                    # Retail exposures failing qualifying criteria
                    .when(
                        _uc.str.contains("RETAIL", literal=True)
                        & (pl.col("qualifies_as_retail").fill_null(True) == False)  # noqa: E712
                    )
                    .then(pl.lit(1.0))
                    # 5a. Regulatory retail (non-mortgage): 75% flat
                    .when(_uc.str.contains("RETAIL", literal=True))
                    .then(pl.lit(retail_rw))
                    # 6a. PSE short-term (Art. 116(3)): ≤3m → 20% flat
                    .when(
                        (_uc == "PSE")
                        & pl.col("residual_maturity_years").is_not_null()
                        & (pl.col("residual_maturity_years") <= 0.25)
                    )
                    .then(pl.lit(float(PSE_SHORT_TERM_RW)))
                    # 6b. PSE unrated: sovereign-derived (Art. 116(1), Table 2)
                    .when((_uc == "PSE") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
                    .then(
                        pl.when(pl.col("cp_country_code") == "GB")
                        .then(pl.lit(0.20))  # UK sovereign CQS 1 → Table 2 row 1
                        .otherwise(pl.lit(float(PSE_UNRATED_DEFAULT_RW)))
                    )
                    # 6c-rgla. RGLA UK devolved govt → 0% (PRA designation)
                    .when(
                        (_uc == "RGLA")
                        & (pl.col("cp_entity_type").fill_null("") == "rgla_sovereign")
                        & (pl.col("cp_country_code") == "GB")
                    )
                    .then(pl.lit(float(RGLA_UK_DEVOLVED_RW)))
                    # 6d-rgla. RGLA domestic currency → 20% (Art. 115(5))
                    .when((_uc == "RGLA") & _is_domestic_currency)
                    .then(pl.lit(float(RGLA_DOMESTIC_CURRENCY_RW)))
                    # 6e-rgla. RGLA unrated non-domestic: sovereign-derived (Table 1A)
                    .when((_uc == "RGLA") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
                    .then(
                        pl.when(pl.col("cp_country_code") == "GB")
                        .then(pl.lit(0.20))  # UK sovereign CQS 1 → Table 1A row 1
                        .otherwise(pl.lit(float(RGLA_UNRATED_DEFAULT_RW)))
                    )
                    # Rated RGLA: falls through to CQS join (Table 1B) via default
                    # 6f-mdb. Named MDB → 0% (Art. 117(2))
                    .when((_uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "mdb_named"))
                    .then(pl.lit(float(MDB_NAMED_ZERO_RW)))
                    # 6g-io. International Organisation → 0% (Art. 118)
                    .when(
                        (_uc == "MDB")
                        & (pl.col("cp_entity_type").fill_null("") == "international_org")
                    )
                    .then(pl.lit(float(IO_ZERO_RW)))
                    # 6h-mdb. Unrated non-named MDB �� 50% (Art. 117(1), Table 2B)
                    .when((_uc == "MDB") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
                    .then(pl.lit(float(MDB_UNRATED_RW)))
                    # Rated non-named MDB: falls through to CQS join (Table 2B) via default
                    # 7. Unrated covered bonds: derive from issuer institution RW
                    # (CRR Art. 129(5)) — unrated institution = 40% → covered bond = 20%
                    .when(
                        _uc.str.contains("COVERED_BOND", literal=True)
                        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
                    )
                    .then(pl.lit(0.20))
                    # 7a. High-risk items → 150% (Art. 128)
                    # Venture capital, private equity, speculative RE financing,
                    # and other PRA-designated high-risk items.
                    .when(_uc == "HIGH_RISK")
                    .then(pl.lit(float(HIGH_RISK_RW)))
                    # 8. Other Items (Art. 134): sub-type-specific risk weights
                    # 8a. Cash/gold → 0% (Art. 134(1)/(4))
                    .when(
                        (_uc == "OTHER")
                        & (
                            pl.col("cp_entity_type")
                            .fill_null("")
                            .is_in(["other_cash", "other_gold"])
                        )
                    )
                    .then(pl.lit(float(OTHER_ITEMS_CASH_RW)))
                    # 8b. Items in course of collection → 20% (Art. 134(3))
                    .when(
                        (_uc == "OTHER")
                        & (pl.col("cp_entity_type").fill_null("") == "other_items_in_collection")
                    )
                    .then(pl.lit(float(OTHER_ITEMS_COLLECTION_RW)))
                    # 8c. Residual lease value → 1/t × 100% (Art. 134(6))
                    .when(
                        (_uc == "OTHER")
                        & (pl.col("cp_entity_type").fill_null("") == "other_residual_lease")
                    )
                    .then(
                        pl.lit(1.0)
                        / pl.col("residual_maturity_years").fill_null(1.0).clip(lower_bound=1.0)
                    )
                    # 8d. Tangible assets and all other → 100% (Art. 134(2))
                    .when(_uc == "OTHER")
                    .then(pl.lit(float(OTHER_ITEMS_DEFAULT_RW)))
                    # 9. Default: CQS-based or 100%
                    .otherwise(pl.col("risk_weight").fill_null(1.0))
                    .alias("risk_weight"),
                ]
            )

        # Clean up temporary columns
        exposures = exposures.drop(
            [
                col
                for col in [
                    "_lookup_class",
                    "_lookup_cqs",
                    "_upper_class",
                    "_cqs_risk_weight",
                    "risk_weight_rw",
                ]
                if col in exposures.collect_schema().names()
            ]
        )

        return exposures

    def _apply_guarantee_substitution(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution for unfunded credit protection.

        For guaranteed portions, the risk weight is substituted with the
        guarantor's risk weight. The final RWA is calculated using blended
        risk weight based on guaranteed vs unguaranteed portions.

        CRR Art. 213-217: Unfunded credit protection

        Args:
            exposures: Exposures with risk_weight and guarantee columns
            config: Calculation configuration

        Returns:
            Exposures with guarantee substitution applied
        """
        schema = exposures.collect_schema()
        cols = schema.names()

        # Check if guarantee columns exist
        if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
            # No guarantee data, return as-is
            return exposures

        # Ensure guarantor_exposure_class is available (set by CRM processor;
        # fallback for unit tests that construct LazyFrames directly)
        if "guarantor_exposure_class" not in cols:
            from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS

            exposures = exposures.with_columns(
                pl.col("guarantor_entity_type")
                .fill_null("")
                .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
                .alias("guarantor_exposure_class"),
            )

        # Ensure optional guarantor columns exist
        if "guarantor_country_code" not in cols:
            exposures = exposures.with_columns(
                pl.lit(None).cast(pl.String).alias("guarantor_country_code"),
            )
        if "guarantor_is_ccp_client_cleared" not in cols:
            exposures = exposures.with_columns(
                pl.lit(None).cast(pl.Boolean).alias("guarantor_is_ccp_client_cleared"),
            )

        # Preserve pre-CRM risk weight before any guarantee substitution
        # This is needed for regulatory reporting (pre-CRM vs post-CRM views)
        exposures = exposures.with_columns(
            [
                pl.col("risk_weight").alias("pre_crm_risk_weight"),
            ]
        )

        # Calculate guarantor's risk weight based on exposure class and CQS.
        # Uses guarantor_exposure_class (derived from ENTITY_TYPE_TO_SA_CLASS dict)
        # instead of regex on entity_type, ensuring all valid entity types are covered.
        # UK deviation for institutions (30% for CQS 2 instead of 50%).
        use_uk_deviation = config.base_currency == "GBP"

        # Art. 114(3)/(4): Domestic CGCB guarantors → 0% RW regardless of CQS
        # UK guarantor in GBP, or EU guarantor in that member state's domestic currency
        schema_now = exposures.collect_schema()
        _has_country = "guarantor_country_code" in schema_now.names()
        _has_currency = "currency" in schema_now.names()
        _is_uk_domestic_guarantor = (
            (pl.col("guarantor_country_code").fill_null("") == "GB") & (pl.col("currency") == "GBP")
            if (_has_country and _has_currency)
            else pl.lit(False)
        )
        _is_eu_domestic_guarantor = (
            build_eu_domestic_currency_expr("guarantor_country_code", "currency")
            if (_has_country and _has_currency)
            else pl.lit(False)
        )
        _is_domestic_guarantor = _is_uk_domestic_guarantor | _is_eu_domestic_guarantor

        # Guarantor exposure class (set by CRM processor from ENTITY_TYPE_TO_SA_CLASS)
        _gec = pl.col("guarantor_exposure_class").fill_null("")

        # Guarantor risk weights by exposure class and CQS
        # CGCB: 0%, 20%, 50%, 100%, 100%, 150% (unrated 100%)
        # Institution: 20%, 30%/50%, 50%, 100%, 100%, 150% (unrated 40%)
        # MDB named/IO: 0% unconditional
        # MDB rated (Table 2B): 20%, 30%, 50%, 100%, 100%, 150% (unrated 50%)
        # Corporate: 20%, 50%, 100%, 100%, 150%, 150% (unrated 100%)
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("guaranteed_portion") <= 0)
                .then(pl.lit(None).cast(pl.Float64))
                # Art. 114(3)/(4): Domestic sovereign → 0% regardless of CQS
                .when((_gec == "central_govt_central_bank") & _is_domestic_guarantor)
                .then(pl.lit(0.0))
                # CGCB guarantors (sovereign, central_bank)
                .when(_gec == "central_govt_central_bank")
                .then(
                    pl.when(pl.col("guarantor_cqs") == 1)
                    .then(pl.lit(0.0))
                    .when(pl.col("guarantor_cqs") == 2)
                    .then(pl.lit(0.20))
                    .when(pl.col("guarantor_cqs") == 3)
                    .then(pl.lit(0.50))
                    .when(pl.col("guarantor_cqs").is_in([4, 5]))
                    .then(pl.lit(1.0))
                    .when(pl.col("guarantor_cqs") == 6)
                    .then(pl.lit(1.50))
                    .otherwise(pl.lit(1.0))  # Unrated
                )
                # CCP guarantors: 2% proprietary / 4% client-cleared
                # (CRR Art. 306, CRE54.14-15) — overrides institution CQS weights
                .when(pl.col("guarantor_entity_type") == "ccp")
                .then(
                    pl.when(pl.col("guarantor_is_ccp_client_cleared").fill_null(False))
                    .then(pl.lit(float(QCCP_CLIENT_CLEARED_RW)))
                    .otherwise(pl.lit(float(QCCP_PROPRIETARY_RW)))
                )
                # Named MDB guarantors (Art. 117(2)): 0% unconditional
                .when(
                    (_gec == "mdb") & (pl.col("guarantor_entity_type").fill_null("") == "mdb_named")
                )
                .then(pl.lit(0.0))
                # International Organisation guarantors (Art. 118): 0% unconditional
                .when(
                    (_gec == "mdb")
                    & (pl.col("guarantor_entity_type").fill_null("") == "international_org")
                )
                .then(pl.lit(0.0))
                # MDB guarantors — Table 2B (Art. 117(1))
                .when(_gec == "mdb")
                .then(
                    pl.when(pl.col("guarantor_cqs") == 1)
                    .then(pl.lit(0.20))
                    .when(pl.col("guarantor_cqs") == 2)
                    .then(pl.lit(0.30))  # Table 2B: CQS 2 = 30%
                    .when(pl.col("guarantor_cqs") == 3)
                    .then(pl.lit(0.50))
                    .when(pl.col("guarantor_cqs").is_in([4, 5]))
                    .then(pl.lit(1.0))
                    .when(pl.col("guarantor_cqs") == 6)
                    .then(pl.lit(1.50))
                    .otherwise(pl.lit(0.50))  # Unrated MDB = 50% (Table 2B)
                )
                # Institution guarantors (institution, bank, etc.)
                .when(_gec == "institution")
                .then(
                    pl.when(pl.col("guarantor_cqs") == 1)
                    .then(pl.lit(0.20))
                    .when(pl.col("guarantor_cqs") == 2)
                    .then(pl.lit(0.30) if use_uk_deviation else pl.lit(0.50))
                    .when(pl.col("guarantor_cqs") == 3)
                    .then(pl.lit(0.50))
                    .when(pl.col("guarantor_cqs").is_in([4, 5]))
                    .then(pl.lit(1.0))
                    .when(pl.col("guarantor_cqs") == 6)
                    .then(pl.lit(1.50))
                    .otherwise(pl.lit(0.40))  # Unrated institution = 40%
                )
                # PSE guarantors (Art. 116(2) Table 2A for rated; sovereign-derived for unrated)
                .when(_gec == "pse")
                .then(
                    pl.when(pl.col("guarantor_cqs") == 1)
                    .then(pl.lit(0.20))
                    .when(pl.col("guarantor_cqs") == 2)
                    .then(pl.lit(0.50))
                    .when(pl.col("guarantor_cqs") == 3)
                    .then(pl.lit(0.50))  # Table 2A: CQS 3 = 50% (differs from institutions)
                    .when(pl.col("guarantor_cqs").is_in([4, 5]))
                    .then(pl.lit(1.0))
                    .when(pl.col("guarantor_cqs") == 6)
                    .then(pl.lit(1.50))
                    # Unrated: sovereign-derived; UK → 20%, otherwise 100%
                    .otherwise(
                        pl.when(pl.col("guarantor_country_code").fill_null("") == "GB")
                        .then(pl.lit(0.20))
                        .otherwise(pl.lit(1.0))
                    )
                )
                # RGLA guarantors (Art. 115(1)(b) Table 1B for rated; sovereign-derived for unrated)
                .when(_gec == "rgla")
                .then(
                    pl.when(pl.col("guarantor_cqs") == 1)
                    .then(pl.lit(0.20))
                    .when(pl.col("guarantor_cqs") == 2)
                    .then(pl.lit(0.50))
                    .when(pl.col("guarantor_cqs") == 3)
                    .then(pl.lit(0.50))  # Table 1B: CQS 3 = 50%
                    .when(pl.col("guarantor_cqs").is_in([4, 5]))
                    .then(pl.lit(1.0))
                    .when(pl.col("guarantor_cqs") == 6)
                    .then(pl.lit(1.50))
                    # Unrated: sovereign-derived; UK → 20%, otherwise 100%
                    .otherwise(
                        pl.when(pl.col("guarantor_country_code").fill_null("") == "GB")
                        .then(pl.lit(0.20))
                        .otherwise(pl.lit(1.0))
                    )
                )
                # Corporate guarantors (corporate, company)
                .when(_gec.is_in(["corporate", "corporate_sme"]))
                .then(
                    pl.when(pl.col("guarantor_cqs") == 1)
                    .then(pl.lit(0.20))
                    .when(pl.col("guarantor_cqs") == 2)
                    .then(pl.lit(0.50))
                    .when(pl.col("guarantor_cqs").is_in([3, 4]))
                    .then(pl.lit(1.0))
                    .when(pl.col("guarantor_cqs").is_in([5, 6]))
                    .then(pl.lit(1.50))
                    .otherwise(pl.lit(1.0))  # Unrated
                )
                # Unknown exposure class - no substitution
                .otherwise(pl.lit(None).cast(pl.Float64))
                .alias("guarantor_rw"),
            ]
        )

        # Check if guarantee is beneficial (guarantor RW < borrower RW)
        # Non-beneficial guarantees should NOT be applied per CRR Art. 213
        exposures = exposures.with_columns(
            [
                pl.when(
                    (pl.col("guaranteed_portion") > 0)
                    & (pl.col("guarantor_rw").is_not_null())
                    & (pl.col("guarantor_rw") < pl.col("pre_crm_risk_weight"))
                )
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("is_guarantee_beneficial"),
            ]
        )

        # Calculate blended risk weight using substitution approach
        # Only apply if guarantee is beneficial
        # RWA = (unguaranteed_portion * borrower_rw + guaranteed_portion * guarantor_rw) / ead_final
        ead_col = "ead_final" if "ead_final" in cols else "ead"

        exposures = exposures.with_columns(
            [
                # Blended risk weight when guarantee exists AND is beneficial
                pl.when(
                    (pl.col("guaranteed_portion") > 0)
                    & (pl.col("guarantor_rw").is_not_null())
                    & (pl.col("is_guarantee_beneficial"))
                )
                .then(
                    # weighted average of borrower and guarantor risk weights
                    (
                        pl.col("unguaranteed_portion") * pl.col("pre_crm_risk_weight")
                        + pl.col("guaranteed_portion") * pl.col("guarantor_rw")
                    )
                    / pl.col(ead_col)
                )
                # No guarantee, no guarantor RW, or non-beneficial - use original risk weight
                .otherwise(pl.col("pre_crm_risk_weight"))
                .alias("risk_weight"),
            ]
        )

        # Track guarantee status for reporting
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("guaranteed_portion") <= 0)
                .then(pl.lit("NO_GUARANTEE"))
                .when(~pl.col("is_guarantee_beneficial"))
                .then(pl.lit("GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"))
                .otherwise(pl.lit("SA_RW_SUBSTITUTION"))
                .alias("guarantee_status"),
                # Calculate RW benefit from guarantee (positive = RW reduced)
                pl.when(pl.col("is_guarantee_beneficial"))
                .then(pl.col("pre_crm_risk_weight") - pl.col("risk_weight"))
                .otherwise(pl.lit(0.0))
                .alias("guarantee_benefit_rw"),
            ]
        )

        return exposures

    def _apply_currency_mismatch_multiplier(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply 1.5x RW multiplier for retail/RE currency mismatch (Basel 3.1 only).

        When the exposure currency differs from the borrower's income currency,
        a 1.5x multiplier is applied to the risk weight for retail and real estate
        exposure classes.

        Basel 3.1 Art. 123B / CRE20.93.

        Args:
            exposures: Exposures with risk_weight and currency columns
            config: Calculation configuration

        Returns:
            Exposures with currency mismatch multiplier applied where applicable
        """
        if not config.is_basel_3_1:
            return exposures

        schema = exposures.collect_schema()
        cols = schema.names()

        # Need both exposure currency and borrower income currency
        income_col = (
            "cp_borrower_income_currency"
            if "cp_borrower_income_currency" in cols
            else "borrower_income_currency"
            if "borrower_income_currency" in cols
            else None
        )
        if income_col is None or "currency" not in cols:
            return exposures

        _uc = (
            pl.col("_upper_class")
            if "_upper_class" in cols
            else (pl.col("exposure_class").fill_null("").str.to_uppercase())
        )

        is_retail_or_re = (
            _uc.str.contains("RETAIL", literal=True)
            | _uc.str.contains("MORTGAGE", literal=True)
            | _uc.str.contains("RESIDENTIAL", literal=True)
            | _uc.str.contains("COMMERCIAL", literal=True)
            | _uc.str.contains("CRE", literal=True)
        )

        has_mismatch = pl.col(income_col).is_not_null() & (pl.col(income_col) != pl.col("currency"))

        mismatch_applies = is_retail_or_re & has_mismatch

        exposures = exposures.with_columns(
            [
                pl.when(mismatch_applies)
                .then(pl.col("risk_weight") * 1.5)
                .otherwise(pl.col("risk_weight"))
                .alias("risk_weight"),
                mismatch_applies.alias("currency_mismatch_multiplier_applied"),
            ]
        )

        return exposures

    def _calculate_rwa(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Calculate RWA = EAD × Risk Weight.

        Args:
            exposures: Exposures with ead_final and risk_weight

        Returns:
            Exposures with rwa_pre_factor column
        """
        # Determine EAD column (ead_final preferred, fallback to ead)
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"

        return exposures.with_columns(
            [
                (pl.col(ead_col) * pl.col("risk_weight")).alias("rwa_pre_factor"),
            ]
        )

    def _apply_supporting_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SME and infrastructure supporting factors.

        Args:
            exposures: Exposures with rwa_pre_factor
            config: Calculation configuration

        Returns:
            Exposures with supporting factors applied
        """
        # Ensure required columns exist for supporting factor calculation
        schema = exposures.collect_schema()

        if "is_sme" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_sme"),
                ]
            )

        if "is_infrastructure" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_infrastructure"),
                ]
            )

        if "ead_final" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.col("ead").alias("ead_final"),
                ]
            )

        return self._supporting_factor_calc.apply_factors(exposures, config)

    def _build_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Build SA calculation audit trail.

        Args:
            exposures: Calculated exposures

        Returns:
            Audit trail LazyFrame
        """
        schema = exposures.collect_schema()
        available_cols = schema.names()

        # Select available audit columns
        select_cols = ["exposure_reference"]
        optional_cols = [
            "counterparty_reference",
            "exposure_class",
            "cqs",
            "ltv",
            "ead_final",
            "risk_weight",
            "rwa_pre_factor",
            "supporting_factor",
            "rwa_post_factor",
            "supporting_factor_applied",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = exposures.select(select_cols)

        # Add calculation string
        audit = audit.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("SA: EAD="),
                        pl.col("ead_final").round(0).cast(pl.String),
                        pl.lit(" × RW="),
                        (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                        pl.lit("% × SF="),
                        (pl.col("supporting_factor") * 100).round(2).cast(pl.String),
                        pl.lit("% → RWA="),
                        pl.col("rwa_post_factor").round(0).cast(pl.String),
                    ]
                ).alias("sa_calculation"),
            ]
        )

        return audit


def create_sa_calculator() -> SACalculator:
    """
    Create an SA calculator instance.

    Returns:
        SACalculator ready for use
    """
    return SACalculator()
