"""
Unit tests for SA-CCR supervisory factor, correlation, and maturity-factor
constants (P8.7).

Verifies that ``rwa_calc.data.tables.sa_ccr_factors`` exposes the correct
Decimal scalars and Polars DataFrame builders required by the SA-CCR engine.

Regulatory references:
- PRA Rulebook CCR (CRR) Part Art. 280 Table 1: supervisory factors
- PRA Rulebook CCR (CRR) Part Art. 280a: credit class correlations
- PRA Rulebook CCR (CRR) Part Art. 280b: equity class correlations
- PRA Rulebook CCR (CRR) Part Art. 280c: commodity class correlations (0.40,
  NOT 0.80 — the plan-bullet's "80% commodities" is incorrect)
- PRA Rulebook CCR (CRR) Part Art. 279c: maturity factor formulae
- PRA Rulebook CCR (CRR) Part Art. 285(2)-(3): margined MPOR floors
- PRA Rulebook CCR (CRR) Part Art. 278(3): PFE multiplier floor F = 0.05

Import strategy: the module-under-test (``sa_ccr_factors``) is imported as a
whole at module scope.  Individual constants are fetched inside each test via
``getattr`` so that a missing constant surfaces as an ``AttributeError``
assertion failure rather than a collection-time ``ImportError``.
"""

from __future__ import annotations

from decimal import Decimal

import rwa_calc.data.tables.sa_ccr_factors as _mod

# =============================================================================
# TestSupervisoryFactors — Art. 280 Table 1
# =============================================================================


class TestSupervisoryFactors:
    """Supervisory factor constants per CRR / PRA Rulebook CCR Part Art. 280 Table 1.

    Each test covers exactly one constant — one-assertion-per-concept.
    """

    # -------------------------------------------------------------------------
    # Scalar asset classes: IR and FX
    # -------------------------------------------------------------------------

    def test_supervisory_factor_ir_is_0_5pct(self) -> None:
        """Art. 280 Table 1: interest-rate supervisory factor = 0.5%.

        Arrange: fetch SA_CCR_SUPERVISORY_FACTOR_IR from module.
        Act:     compare to Decimal("0.005").
        Assert:  equals 0.005.
        """
        # Arrange
        sf = _mod.SA_CCR_SUPERVISORY_FACTOR_IR

        # Assert
        assert sf == Decimal("0.005"), (
            f"IR supervisory factor must be Decimal('0.005') per Art. 280 Table 1, got {sf!r}"
        )

    def test_supervisory_factor_fx_is_4pct(self) -> None:
        """Art. 280 Table 1: FX supervisory factor = 4%.

        Arrange: fetch SA_CCR_SUPERVISORY_FACTOR_FX from module.
        Act:     compare to Decimal("0.04").
        Assert:  equals 0.04.
        """
        # Arrange
        sf = _mod.SA_CCR_SUPERVISORY_FACTOR_FX

        # Assert
        assert sf == Decimal("0.04"), (
            f"FX supervisory factor must be Decimal('0.04') per Art. 280 Table 1, got {sf!r}"
        )

    # -------------------------------------------------------------------------
    # Credit single-name
    # -------------------------------------------------------------------------

    def test_supervisory_factor_credit_sn_ig_is_0_46pct(self) -> None:
        """Art. 280 Table 1: credit SN IG supervisory factor = 0.46%."""
        # Arrange
        sn = _mod.SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN

        # Assert
        assert sn["IG"] == Decimal("0.0046"), (
            f"Credit SN IG SF must be Decimal('0.0046') per Art. 280 Table 1, got {sn['IG']!r}"
        )

    def test_supervisory_factor_credit_sn_hy_is_1_3pct(self) -> None:
        """Art. 280 Table 1: credit SN HY supervisory factor = 1.3%."""
        # Arrange
        sn = _mod.SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN

        # Assert
        assert sn["HY"] == Decimal("0.013"), (
            f"Credit SN HY SF must be Decimal('0.013') per Art. 280 Table 1, got {sn['HY']!r}"
        )

    def test_supervisory_factor_credit_sn_non_rated_is_6pct(self) -> None:
        """Art. 280 Table 1: credit SN non-rated supervisory factor = 6%."""
        # Arrange
        sn = _mod.SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN

        # Assert
        assert sn["NON_RATED"] == Decimal("0.06"), (
            f"Credit SN NON_RATED SF must be Decimal('0.06') per Art. 280 Table 1, "
            f"got {sn['NON_RATED']!r}"
        )

    # -------------------------------------------------------------------------
    # Credit index
    # -------------------------------------------------------------------------

    def test_supervisory_factor_credit_idx_ig_is_0_38pct(self) -> None:
        """Art. 280 Table 1: credit index IG supervisory factor = 0.38%."""
        # Arrange
        idx = _mod.SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX

        # Assert
        assert idx["IG"] == Decimal("0.0038"), (
            f"Credit IDX IG SF must be Decimal('0.0038') per Art. 280 Table 1, got {idx['IG']!r}"
        )

    def test_supervisory_factor_credit_idx_hy_is_1_06pct(self) -> None:
        """Art. 280 Table 1: credit index HY supervisory factor = 1.06%."""
        # Arrange
        idx = _mod.SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX

        # Assert
        assert idx["HY"] == Decimal("0.0106"), (
            f"Credit IDX HY SF must be Decimal('0.0106') per Art. 280 Table 1, got {idx['HY']!r}"
        )

    # -------------------------------------------------------------------------
    # Equity
    # -------------------------------------------------------------------------

    def test_supervisory_factor_equity_sn_is_32pct(self) -> None:
        """Art. 280 Table 1: equity single-name supervisory factor = 32%."""
        # Arrange
        sf = _mod.SA_CCR_SUPERVISORY_FACTOR_EQUITY_SN

        # Assert
        assert sf == Decimal("0.32"), (
            f"Equity SN SF must be Decimal('0.32') per Art. 280 Table 1, got {sf!r}"
        )

    def test_supervisory_factor_equity_idx_is_20pct(self) -> None:
        """Art. 280 Table 1: equity index supervisory factor = 20%."""
        # Arrange
        sf = _mod.SA_CCR_SUPERVISORY_FACTOR_EQUITY_IDX

        # Assert
        assert sf == Decimal("0.20"), (
            f"Equity IDX SF must be Decimal('0.20') per Art. 280 Table 1, got {sf!r}"
        )

    # -------------------------------------------------------------------------
    # Commodity sub-classes
    # -------------------------------------------------------------------------

    def test_supervisory_factor_commodity_electricity_is_40pct(self) -> None:
        """Art. 280 Table 1: electricity commodity supervisory factor = 40%."""
        # Arrange
        commodity = _mod.SA_CCR_SUPERVISORY_FACTORS_COMMODITY

        # Assert
        assert commodity["ELECTRICITY"] == Decimal("0.40"), (
            f"Commodity ELECTRICITY SF must be Decimal('0.40') per Art. 280 Table 1, "
            f"got {commodity['ELECTRICITY']!r}"
        )

    def test_supervisory_factor_commodity_oil_gas_is_18pct(self) -> None:
        """Art. 280 Table 1: oil/gas commodity supervisory factor = 18%."""
        # Arrange
        commodity = _mod.SA_CCR_SUPERVISORY_FACTORS_COMMODITY

        # Assert
        assert commodity["OIL_GAS"] == Decimal("0.18"), (
            f"Commodity OIL_GAS SF must be Decimal('0.18') per Art. 280 Table 1, "
            f"got {commodity['OIL_GAS']!r}"
        )

    def test_supervisory_factor_commodity_metals_is_18pct(self) -> None:
        """Art. 280 Table 1: metals commodity supervisory factor = 18%."""
        # Arrange
        commodity = _mod.SA_CCR_SUPERVISORY_FACTORS_COMMODITY

        # Assert
        assert commodity["METALS"] == Decimal("0.18"), (
            f"Commodity METALS SF must be Decimal('0.18') per Art. 280 Table 1, "
            f"got {commodity['METALS']!r}"
        )

    def test_supervisory_factor_commodity_agricultural_is_18pct(self) -> None:
        """Art. 280 Table 1: agricultural commodity supervisory factor = 18%."""
        # Arrange
        commodity = _mod.SA_CCR_SUPERVISORY_FACTORS_COMMODITY

        # Assert
        assert commodity["AGRICULTURAL"] == Decimal("0.18"), (
            f"Commodity AGRICULTURAL SF must be Decimal('0.18') per Art. 280 Table 1, "
            f"got {commodity['AGRICULTURAL']!r}"
        )

    def test_supervisory_factor_commodity_other_is_18pct(self) -> None:
        """Art. 280 Table 1: other commodity supervisory factor = 18%."""
        # Arrange
        commodity = _mod.SA_CCR_SUPERVISORY_FACTORS_COMMODITY

        # Assert
        assert commodity["OTHER"] == Decimal("0.18"), (
            f"Commodity OTHER SF must be Decimal('0.18') per Art. 280 Table 1, "
            f"got {commodity['OTHER']!r}"
        )


# =============================================================================
# TestCorrelations — Art. 280a/b/c
# =============================================================================


class TestCorrelations:
    """Correlation constants per PRA Rulebook CCR Part Art. 280a/b/c.

    CRITICAL: Commodity correlation is 0.40 per Art. 280c, NOT 0.80.
    The plan-bullet's mention of '80% commodities' is incorrect; this test
    class locks the engine-implementer to 0.40.
    """

    def test_correlation_credit_sn_is_50pct(self) -> None:
        """Art. 280a: credit single-name correlation = 50%.

        Arrange: fetch SA_CCR_CORRELATION_CREDIT_SN from module.
        Act:     compare to Decimal("0.50").
        Assert:  equals 0.50.
        """
        # Arrange
        corr = _mod.SA_CCR_CORRELATION_CREDIT_SN

        # Assert
        assert corr == Decimal("0.50"), (
            f"Credit SN correlation must be Decimal('0.50') per Art. 280a, got {corr!r}"
        )

    def test_correlation_credit_idx_is_80pct(self) -> None:
        """Art. 280a: credit index correlation = 80%."""
        # Arrange
        corr = _mod.SA_CCR_CORRELATION_CREDIT_IDX

        # Assert
        assert corr == Decimal("0.80"), (
            f"Credit IDX correlation must be Decimal('0.80') per Art. 280a, got {corr!r}"
        )

    def test_correlation_equity_sn_is_50pct(self) -> None:
        """Art. 280b: equity single-name correlation = 50%."""
        # Arrange
        corr = _mod.SA_CCR_CORRELATION_EQUITY_SN

        # Assert
        assert corr == Decimal("0.50"), (
            f"Equity SN correlation must be Decimal('0.50') per Art. 280b, got {corr!r}"
        )

    def test_correlation_equity_idx_is_80pct(self) -> None:
        """Art. 280b: equity index correlation = 80%."""
        # Arrange
        corr = _mod.SA_CCR_CORRELATION_EQUITY_IDX

        # Assert
        assert corr == Decimal("0.80"), (
            f"Equity IDX correlation must be Decimal('0.80') per Art. 280b, got {corr!r}"
        )

    def test_correlation_commodity_is_40pct_not_80pct(self) -> None:
        """Art. 280c: commodity correlation = 40%.

        CRITICAL: The plan-bullet incorrectly states '80% commodities'.
        CRR / PRA Rulebook CCR Part Art. 280c mandates 0.40 for all
        commodity sub-classes. This test guards against the 0.80 mistake.
        """
        # Arrange
        corr = _mod.SA_CCR_CORRELATION_COMMODITY

        # Assert — must be 0.40, NOT 0.80
        assert corr == Decimal("0.40"), (
            f"Commodity correlation must be Decimal('0.40') per Art. 280c (NOT 0.80), got {corr!r}"
        )
        assert corr != Decimal("0.80"), (
            "Commodity correlation must NOT be 0.80 — the plan-bullet contained an error; "
            "Art. 280c mandates 0.40 for all commodity sub-classes."
        )


# =============================================================================
# TestMaturityFactorConstants — Art. 279c, Art. 285(2)-(3)
# =============================================================================


class TestMaturityFactorConstants:
    """Maturity-factor scalar constants per PRA Rulebook CCR Part Art. 279c and Art. 285."""

    def test_mf_unmargined_cap_years_is_1(self) -> None:
        """Art. 279c(1)(a): unmargined MF cap = 1 year.

        Arrange: fetch MF_UNMARGINED_CAP_YEARS from module.
        Act:     compare to Decimal("1.0").
        Assert:  equals 1.0.
        """
        # Arrange
        val = _mod.MF_UNMARGINED_CAP_YEARS

        # Assert
        assert val == Decimal("1.0"), (
            f"MF_UNMARGINED_CAP_YEARS must be Decimal('1.0') per Art. 279c, got {val!r}"
        )

    def test_mf_unmargined_denom_years_is_1(self) -> None:
        """Art. 279c(1)(a): unmargined MF denominator = 1 year."""
        # Arrange
        val = _mod.MF_UNMARGINED_DENOM_YEARS

        # Assert
        assert val == Decimal("1.0"), (
            f"MF_UNMARGINED_DENOM_YEARS must be Decimal('1.0') per Art. 279c, got {val!r}"
        )

    def test_mf_margined_scalar_is_1_5(self) -> None:
        """Art. 279c(1)(b): margined MF scalar = 1.5 (the 3/2 factor)."""
        # Arrange
        val = _mod.MF_MARGINED_SCALAR

        # Assert
        assert val == Decimal("1.5"), (
            f"MF_MARGINED_SCALAR must be Decimal('1.5') per Art. 279c, got {val!r}"
        )

    def test_mf_margined_floor_days_repo_sft_is_5(self) -> None:
        """Art. 285(2): MPOR floor for repo / SFT = 5 business days."""
        # Arrange
        val = _mod.MF_MARGINED_FLOOR_DAYS_REPO_SFT

        # Assert
        assert val == 5, f"MF_MARGINED_FLOOR_DAYS_REPO_SFT must be 5 per Art. 285(2), got {val!r}"

    def test_mf_margined_floor_days_otc_is_10(self) -> None:
        """Art. 285(2): MPOR floor for standard OTC derivatives = 10 business days."""
        # Arrange
        val = _mod.MF_MARGINED_FLOOR_DAYS_OTC

        # Assert
        assert val == 10, f"MF_MARGINED_FLOOR_DAYS_OTC must be 10 per Art. 285(2), got {val!r}"

    def test_mf_margined_floor_days_large_or_illiquid_is_20(self) -> None:
        """Art. 285(3): MPOR floor for large or illiquid netting sets = 20 business days."""
        # Arrange
        val = _mod.MF_MARGINED_FLOOR_DAYS_LARGE_OR_ILLIQUID

        # Assert
        assert val == 20, (
            f"MF_MARGINED_FLOOR_DAYS_LARGE_OR_ILLIQUID must be 20 per Art. 285(3), got {val!r}"
        )

    def test_pfe_multiplier_floor_f_is_0_05(self) -> None:
        """Art. 278(3): PFE multiplier floor F = 5%."""
        # Arrange
        val = _mod.PFE_MULTIPLIER_FLOOR_F

        # Assert
        assert val == Decimal("0.05"), (
            f"PFE_MULTIPLIER_FLOOR_F must be Decimal('0.05') per Art. 278(3), got {val!r}"
        )


# =============================================================================
# TestBuilderDataFrames — _build_sa_ccr_supervisory_factors_df and
#                          _build_sa_ccr_correlations_df
# =============================================================================


class TestBuilderDataFrames:
    """DataFrame builder helpers must return well-formed Polars DataFrames.

    ``_build_sa_ccr_supervisory_factors_df()`` — 14 rows covering all
    asset-class / sub-class combinations in Art. 280 Table 1.

    ``_build_sa_ccr_correlations_df()`` — 5 rows covering
    CREDIT_SN, CREDIT_IDX, EQUITY_SN, EQUITY_IDX, COMMODITY.
    """

    # -------------------------------------------------------------------------
    # _build_sa_ccr_supervisory_factors_df
    # -------------------------------------------------------------------------

    def test_supervisory_factors_df_has_14_rows(self) -> None:
        """Builder must produce exactly 14 rows (one per Art. 280 Table 1 entry).

        14 = IR(1) + FX(1) + CREDIT_SN(3) + CREDIT_IDX(2) + EQUITY(2) + COMMODITY(5).

        Arrange: call _build_sa_ccr_supervisory_factors_df().
        Act:     inspect .height.
        Assert:  equals 14.
        """
        # Arrange
        builder = _mod._build_sa_ccr_supervisory_factors_df
        df = builder()

        # Assert
        assert df.height == 14, f"Supervisory factors DataFrame must have 14 rows, got {df.height}"

    def test_supervisory_factors_df_column_set(self) -> None:
        """Builder DataFrame must have exactly columns ['asset_class', 'sub_class', 'supervisory_factor']."""
        # Arrange
        builder = _mod._build_sa_ccr_supervisory_factors_df
        df = builder()

        # Assert
        assert set(df.columns) == {"asset_class", "sub_class", "supervisory_factor"}, (
            f"Unexpected columns: {df.columns!r}"
        )

    def test_supervisory_factors_df_ir_row_value(self) -> None:
        """IR row in supervisory factors DataFrame must have supervisory_factor ≈ 0.005."""
        # Arrange
        builder = _mod._build_sa_ccr_supervisory_factors_df
        df = builder()

        # Act
        ir_rows = df.filter(df["asset_class"] == "IR")

        # Assert
        assert ir_rows.height == 1, f"Expected 1 IR row, got {ir_rows.height}"
        actual = ir_rows["supervisory_factor"][0]
        assert abs(actual - 0.005) < 1e-9, (
            f"IR supervisory_factor in DataFrame must be ~0.005, got {actual}"
        )

    def test_supervisory_factors_df_electricity_row_value(self) -> None:
        """COMMODITY/ELECTRICITY row must have supervisory_factor ≈ 0.40."""
        # Arrange
        builder = _mod._build_sa_ccr_supervisory_factors_df
        df = builder()

        # Act
        rows = df.filter((df["asset_class"] == "COMMODITY") & (df["sub_class"] == "ELECTRICITY"))

        # Assert
        assert rows.height == 1, f"Expected 1 ELECTRICITY row, got {rows.height}"
        actual = rows["supervisory_factor"][0]
        assert abs(actual - 0.40) < 1e-9, (
            f"COMMODITY/ELECTRICITY supervisory_factor must be ~0.40, got {actual}"
        )

    def test_supervisory_factors_df_credit_sn_non_rated_row_value(self) -> None:
        """CREDIT_SN/NON_RATED row must have supervisory_factor ≈ 0.06."""
        # Arrange
        builder = _mod._build_sa_ccr_supervisory_factors_df
        df = builder()

        # Act
        rows = df.filter((df["asset_class"] == "CREDIT_SN") & (df["sub_class"] == "NON_RATED"))

        # Assert
        assert rows.height == 1, f"Expected 1 CREDIT_SN/NON_RATED row, got {rows.height}"
        actual = rows["supervisory_factor"][0]
        assert abs(actual - 0.06) < 1e-9, (
            f"CREDIT_SN/NON_RATED supervisory_factor must be ~0.06, got {actual}"
        )

    # -------------------------------------------------------------------------
    # _build_sa_ccr_correlations_df
    # -------------------------------------------------------------------------

    def test_correlations_df_has_5_rows(self) -> None:
        """Builder must produce exactly 5 rows (CREDIT_SN, CREDIT_IDX, EQUITY_SN, EQUITY_IDX, COMMODITY).

        Arrange: call _build_sa_ccr_correlations_df().
        Act:     inspect .height.
        Assert:  equals 5.
        """
        # Arrange
        builder = _mod._build_sa_ccr_correlations_df
        df = builder()

        # Assert
        assert df.height == 5, f"Correlations DataFrame must have 5 rows, got {df.height}"

    def test_correlations_df_has_required_columns(self) -> None:
        """Builder DataFrame must include columns 'asset_class' and 'correlation'."""
        # Arrange
        builder = _mod._build_sa_ccr_correlations_df
        df = builder()

        # Assert
        assert "asset_class" in df.columns, f"'asset_class' column missing. Columns: {df.columns!r}"
        assert "correlation" in df.columns, f"'correlation' column missing. Columns: {df.columns!r}"

    def test_correlations_df_commodity_row_is_40pct(self) -> None:
        """COMMODITY row in correlations DataFrame must have correlation ≈ 0.40 (Art. 280c)."""
        # Arrange
        builder = _mod._build_sa_ccr_correlations_df
        df = builder()

        # Act
        rows = df.filter(df["asset_class"] == "COMMODITY")

        # Assert
        assert rows.height == 1, f"Expected 1 COMMODITY correlation row, got {rows.height}"
        actual = rows["correlation"][0]
        assert abs(actual - 0.40) < 1e-9, (
            f"COMMODITY correlation in DataFrame must be ~0.40 per Art. 280c, got {actual}. "
            "NOT 0.80 — the plan-bullet contained an error."
        )
