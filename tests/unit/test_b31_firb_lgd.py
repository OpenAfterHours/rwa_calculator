"""
Unit tests for Basel 3.1 F-IRB supervisory LGD data tables.

Tests verify:
- B31 FIRB LGD constants match PRA PS1/26 Art. 161(1) values
- DataFrame generator produces correct schema and values
- FSE vs non-FSE senior unsecured distinction (45% vs 40%)
- Covered bond LGD (11.25%) is included
- Reduced LGDS values for non-financial collateral (CRE32.9-12)
- Scalar lookup function returns correct values for all collateral types
- Comparison DataFrame shows CRR-to-B31 changes correctly
- Consistency between B31 constants, DataFrame, and lookup function
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from rwa_calc.data.tables.b31_firb_lgd import (
    B31_FIRB_LGD_COMMERCIAL_RE,
    B31_FIRB_LGD_COVERED_BOND,
    B31_FIRB_LGD_FINANCIAL_COLLATERAL,
    B31_FIRB_LGD_OTHER_PHYSICAL,
    B31_FIRB_LGD_RECEIVABLES,
    B31_FIRB_LGD_RESIDENTIAL_RE,
    B31_FIRB_LGD_SUBORDINATED,
    B31_FIRB_LGD_UNSECURED_SENIOR,
    B31_FIRB_LGD_UNSECURED_SENIOR_FSE,
    get_b31_firb_lgd_table,
    get_b31_vs_crr_lgd_comparison,
    lookup_b31_firb_lgd,
)
from rwa_calc.data.tables.crr_firb_lgd import (
    BASEL31_FIRB_SUPERVISORY_LGD,
    FIRB_SUPERVISORY_LGD,
)


# =============================================================================
# CONSTANT VALUE TESTS — PRA PS1/26 Art. 161(1) values
# =============================================================================


class TestB31FIRBLGDConstants:
    """Tests for Basel 3.1 FIRB LGD constant values per PRA PS1/26 Art. 161."""

    def test_non_fse_senior_unsecured_forty_percent(self) -> None:
        """Non-FSE senior unsecured is 40% under B31 (Art. 161(1)(aa))."""
        assert B31_FIRB_LGD_UNSECURED_SENIOR == Decimal("0.40")

    def test_fse_senior_unsecured_forty_five_percent(self) -> None:
        """FSE senior unsecured remains 45% under B31 (Art. 161(1)(a))."""
        assert B31_FIRB_LGD_UNSECURED_SENIOR_FSE == Decimal("0.45")

    def test_subordinated_seventy_five_percent(self) -> None:
        """Subordinated is 75%, unchanged from CRR (Art. 161(1)(b))."""
        assert B31_FIRB_LGD_SUBORDINATED == Decimal("0.75")

    def test_covered_bond_eleven_point_two_five_percent(self) -> None:
        """Covered bonds get 11.25% LGD (Art. 161(1B))."""
        assert B31_FIRB_LGD_COVERED_BOND == Decimal("0.1125")

    def test_financial_collateral_zero_percent(self) -> None:
        """Financial collateral is 0%, unchanged from CRR."""
        assert B31_FIRB_LGD_FINANCIAL_COLLATERAL == Decimal("0.00")

    def test_receivables_twenty_percent(self) -> None:
        """Receivables LGDS is 20% under B31 (CRR: 35%, CRE32.9)."""
        assert B31_FIRB_LGD_RECEIVABLES == Decimal("0.20")

    def test_residential_re_twenty_percent(self) -> None:
        """Residential RE LGDS is 20% under B31 (CRR: 35%, CRE32.10)."""
        assert B31_FIRB_LGD_RESIDENTIAL_RE == Decimal("0.20")

    def test_commercial_re_twenty_percent(self) -> None:
        """Commercial RE LGDS is 20% under B31 (CRR: 35%, CRE32.11)."""
        assert B31_FIRB_LGD_COMMERCIAL_RE == Decimal("0.20")

    def test_other_physical_twenty_five_percent(self) -> None:
        """Other physical LGDS is 25% under B31 (CRR: 40%, CRE32.12)."""
        assert B31_FIRB_LGD_OTHER_PHYSICAL == Decimal("0.25")

    def test_constants_match_dict(self) -> None:
        """Named constants are consistent with the BASEL31_FIRB_SUPERVISORY_LGD dict."""
        assert B31_FIRB_LGD_UNSECURED_SENIOR == BASEL31_FIRB_SUPERVISORY_LGD["unsecured_senior"]
        assert (
            B31_FIRB_LGD_UNSECURED_SENIOR_FSE
            == BASEL31_FIRB_SUPERVISORY_LGD["unsecured_senior_fse"]
        )
        assert B31_FIRB_LGD_SUBORDINATED == BASEL31_FIRB_SUPERVISORY_LGD["subordinated"]
        assert B31_FIRB_LGD_COVERED_BOND == BASEL31_FIRB_SUPERVISORY_LGD["covered_bond"]
        assert (
            B31_FIRB_LGD_FINANCIAL_COLLATERAL
            == BASEL31_FIRB_SUPERVISORY_LGD["financial_collateral"]
        )
        assert B31_FIRB_LGD_RECEIVABLES == BASEL31_FIRB_SUPERVISORY_LGD["receivables"]
        assert B31_FIRB_LGD_RESIDENTIAL_RE == BASEL31_FIRB_SUPERVISORY_LGD["residential_re"]
        assert B31_FIRB_LGD_COMMERCIAL_RE == BASEL31_FIRB_SUPERVISORY_LGD["commercial_re"]
        assert B31_FIRB_LGD_OTHER_PHYSICAL == BASEL31_FIRB_SUPERVISORY_LGD["other_physical"]


class TestB31VsCRRChanges:
    """Tests verifying Basel 3.1 LGD changes from CRR are correctly captured."""

    def test_non_fse_senior_reduced_from_crr(self) -> None:
        """Non-FSE senior unsecured reduced from 45% (CRR) to 40% (B31)."""
        assert FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.45")
        assert B31_FIRB_LGD_UNSECURED_SENIOR == Decimal("0.40")

    def test_fse_senior_unchanged_from_crr(self) -> None:
        """FSE senior unsecured unchanged at 45%."""
        assert FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.45")
        assert B31_FIRB_LGD_UNSECURED_SENIOR_FSE == Decimal("0.45")

    def test_receivables_reduced_from_crr(self) -> None:
        """Receivables reduced from 35% (CRR) to 20% (B31)."""
        assert FIRB_SUPERVISORY_LGD["receivables"] == Decimal("0.35")
        assert B31_FIRB_LGD_RECEIVABLES == Decimal("0.20")

    def test_residential_re_reduced_from_crr(self) -> None:
        """Residential RE reduced from 35% (CRR) to 20% (B31)."""
        assert FIRB_SUPERVISORY_LGD["residential_re"] == Decimal("0.35")
        assert B31_FIRB_LGD_RESIDENTIAL_RE == Decimal("0.20")

    def test_commercial_re_reduced_from_crr(self) -> None:
        """Commercial RE reduced from 35% (CRR) to 20% (B31)."""
        assert FIRB_SUPERVISORY_LGD["commercial_re"] == Decimal("0.35")
        assert B31_FIRB_LGD_COMMERCIAL_RE == Decimal("0.20")

    def test_other_physical_reduced_from_crr(self) -> None:
        """Other physical reduced from 40% (CRR) to 25% (B31)."""
        assert FIRB_SUPERVISORY_LGD["other_physical"] == Decimal("0.40")
        assert B31_FIRB_LGD_OTHER_PHYSICAL == Decimal("0.25")

    def test_subordinated_unchanged(self) -> None:
        """Subordinated unchanged at 75%."""
        assert FIRB_SUPERVISORY_LGD["subordinated"] == Decimal("0.75")
        assert B31_FIRB_LGD_SUBORDINATED == Decimal("0.75")

    def test_financial_collateral_unchanged(self) -> None:
        """Financial collateral unchanged at 0%."""
        assert FIRB_SUPERVISORY_LGD["financial_collateral"] == Decimal("0.00")
        assert B31_FIRB_LGD_FINANCIAL_COLLATERAL == Decimal("0.00")


# =============================================================================
# DATAFRAME GENERATOR TESTS
# =============================================================================


class TestB31FIRBLGDDataFrame:
    """Tests for the Basel 3.1 FIRB LGD DataFrame generator."""

    def test_dataframe_has_expected_columns(self) -> None:
        """DataFrame has all required columns."""
        df = get_b31_firb_lgd_table()
        expected_cols = {
            "collateral_type",
            "seniority",
            "is_fse",
            "lgd",
            "overcollateralisation_ratio",
            "min_threshold",
            "description",
        }
        assert set(df.columns) == expected_cols

    def test_dataframe_has_eleven_rows(self) -> None:
        """DataFrame has 11 rows: 3 unsecured + covered_bond + financial + cash + receivables
        + 3 real_estate + other_physical."""
        df = get_b31_firb_lgd_table()
        assert len(df) == 11

    def test_dataframe_lgd_column_float64(self) -> None:
        """LGD column is Float64 type for Polars arithmetic."""
        df = get_b31_firb_lgd_table()
        assert df.schema["lgd"] == pl.Float64

    def test_dataframe_overcoll_ratio_float64(self) -> None:
        """Overcollateralisation ratio column is Float64."""
        df = get_b31_firb_lgd_table()
        assert df.schema["overcollateralisation_ratio"] == pl.Float64

    def test_dataframe_non_fse_senior_unsecured_value(self) -> None:
        """Non-FSE senior unsecured row has LGD = 0.40."""
        df = get_b31_firb_lgd_table()
        non_fse = df.filter(
            (pl.col("collateral_type") == "unsecured")
            & (pl.col("seniority") == "senior")
            & (pl.col("is_fse") == False)  # noqa: E712
        )
        assert len(non_fse) == 1
        assert non_fse["lgd"][0] == 0.40

    def test_dataframe_fse_senior_unsecured_value(self) -> None:
        """FSE senior unsecured row has LGD = 0.45."""
        df = get_b31_firb_lgd_table()
        fse = df.filter(
            (pl.col("collateral_type") == "unsecured")
            & (pl.col("seniority") == "senior")
            & (pl.col("is_fse") == True)  # noqa: E712
        )
        assert len(fse) == 1
        assert fse["lgd"][0] == 0.45

    def test_dataframe_subordinated_value(self) -> None:
        """Subordinated row has LGD = 0.75."""
        df = get_b31_firb_lgd_table()
        sub = df.filter(pl.col("seniority") == "subordinated")
        assert len(sub) == 1
        assert sub["lgd"][0] == 0.75

    def test_dataframe_covered_bond_value(self) -> None:
        """Covered bond row has LGD = 0.1125."""
        df = get_b31_firb_lgd_table()
        cb = df.filter(pl.col("collateral_type") == "covered_bond")
        assert len(cb) == 1
        assert cb["lgd"][0] == 0.1125

    def test_dataframe_receivables_value(self) -> None:
        """Receivables row has LGD = 0.20 (CRR: 0.35)."""
        df = get_b31_firb_lgd_table()
        recv = df.filter(pl.col("collateral_type") == "receivables")
        assert len(recv) == 1
        assert recv["lgd"][0] == 0.20

    def test_dataframe_residential_re_value(self) -> None:
        """Residential RE row has LGD = 0.20 (CRR: 0.35)."""
        df = get_b31_firb_lgd_table()
        rre = df.filter(pl.col("collateral_type") == "residential_re")
        assert len(rre) == 1
        assert rre["lgd"][0] == 0.20

    def test_dataframe_commercial_re_value(self) -> None:
        """Commercial RE row has LGD = 0.20 (CRR: 0.35)."""
        df = get_b31_firb_lgd_table()
        cre = df.filter(pl.col("collateral_type") == "commercial_re")
        assert len(cre) == 1
        assert cre["lgd"][0] == 0.20

    def test_dataframe_other_physical_value(self) -> None:
        """Other physical row has LGD = 0.25 (CRR: 0.40)."""
        df = get_b31_firb_lgd_table()
        op = df.filter(pl.col("collateral_type") == "other_physical")
        assert len(op) == 1
        assert op["lgd"][0] == 0.25

    def test_dataframe_re_overcoll_ratio_one_forty(self) -> None:
        """Real estate rows have 140% overcollateralisation ratio."""
        df = get_b31_firb_lgd_table()
        re_rows = df.filter(
            pl.col("collateral_type").is_in(["residential_re", "commercial_re", "real_estate"])
        )
        assert all(r == 1.40 for r in re_rows["overcollateralisation_ratio"].to_list())

    def test_dataframe_receivables_overcoll_ratio_one_twenty_five(self) -> None:
        """Receivables have 125% overcollateralisation ratio."""
        df = get_b31_firb_lgd_table()
        recv = df.filter(pl.col("collateral_type") == "receivables")
        assert recv["overcollateralisation_ratio"][0] == 1.25

    def test_dataframe_re_min_threshold_thirty_percent(self) -> None:
        """Real estate and other physical have 30% minimum threshold."""
        df = get_b31_firb_lgd_table()
        rows = df.filter(
            pl.col("collateral_type").is_in(
                ["residential_re", "commercial_re", "real_estate", "other_physical"]
            )
        )
        assert all(t == 0.30 for t in rows["min_threshold"].to_list())

    def test_dataframe_financial_no_overcoll(self) -> None:
        """Financial collateral has no overcollateralisation requirement."""
        df = get_b31_firb_lgd_table()
        fin = df.filter(
            pl.col("collateral_type").is_in(["financial_collateral", "cash"])
        )
        assert all(r == 1.0 for r in fin["overcollateralisation_ratio"].to_list())
        assert all(t == 0.0 for t in fin["min_threshold"].to_list())


# =============================================================================
# SCALAR LOOKUP TESTS
# =============================================================================


class TestB31FIRBLGDLookup:
    """Tests for the Basel 3.1 FIRB LGD scalar lookup function."""

    def test_unsecured_non_fse_returns_forty_percent(self) -> None:
        """Unsecured non-FSE returns 40%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type=None, is_financial_sector_entity=False)
        assert lgd == Decimal("0.40")
        assert "non-FSE" in desc

    def test_unsecured_fse_returns_forty_five_percent(self) -> None:
        """Unsecured FSE returns 45%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type=None, is_financial_sector_entity=True)
        assert lgd == Decimal("0.45")
        assert "FSE" in desc

    def test_subordinated_returns_seventy_five_percent(self) -> None:
        """Subordinated returns 75%."""
        lgd, desc = lookup_b31_firb_lgd(is_subordinated=True)
        assert lgd == Decimal("0.75")
        assert "Subordinated" in desc

    def test_subordinated_ignores_collateral_type(self) -> None:
        """Subordinated always returns 75% regardless of collateral."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="financial_collateral", is_subordinated=True)
        assert lgd == Decimal("0.75")

    def test_subordinated_ignores_fse_flag(self) -> None:
        """Subordinated always returns 75% regardless of FSE flag."""
        lgd, _ = lookup_b31_firb_lgd(is_subordinated=True, is_financial_sector_entity=True)
        assert lgd == Decimal("0.75")

    def test_covered_bond_returns_eleven_point_two_five(self) -> None:
        """Covered bond returns 11.25%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type="covered_bond")
        assert lgd == Decimal("0.1125")
        assert "Covered bond" in desc

    def test_covered_bonds_plural_alias(self) -> None:
        """Plural 'covered_bonds' alias also works."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="covered_bonds")
        assert lgd == Decimal("0.1125")

    def test_financial_collateral_returns_zero(self) -> None:
        """Financial collateral returns 0%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="financial_collateral")
        assert lgd == Decimal("0.00")

    def test_cash_alias_returns_zero(self) -> None:
        """Cash alias returns 0%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="cash")
        assert lgd == Decimal("0.00")

    def test_gold_alias_returns_zero(self) -> None:
        """Gold alias returns 0%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="gold")
        assert lgd == Decimal("0.00")

    def test_receivables_returns_twenty_percent(self) -> None:
        """Receivables returns 20%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type="receivables")
        assert lgd == Decimal("0.20")
        assert "Receivables" in desc

    def test_trade_receivables_alias(self) -> None:
        """Trade receivables alias returns 20%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="trade_receivables")
        assert lgd == Decimal("0.20")

    def test_residential_re_returns_twenty_percent(self) -> None:
        """Residential RE returns 20%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type="residential_re")
        assert lgd == Decimal("0.20")
        assert "Residential" in desc

    def test_rre_alias(self) -> None:
        """RRE alias returns 20%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="rre")
        assert lgd == Decimal("0.20")

    def test_commercial_re_returns_twenty_percent(self) -> None:
        """Commercial RE returns 20%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type="commercial_re")
        assert lgd == Decimal("0.20")
        assert "Commercial" in desc

    def test_cre_alias(self) -> None:
        """CRE alias returns 20%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="cre")
        assert lgd == Decimal("0.20")

    def test_real_estate_general_defaults_to_rre(self) -> None:
        """Generic 'real_estate' defaults to residential RE (20%)."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="real_estate")
        assert lgd == Decimal("0.20")

    def test_property_alias_defaults_to_rre(self) -> None:
        """'property' alias defaults to residential RE (20%)."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="property")
        assert lgd == Decimal("0.20")

    def test_other_physical_returns_twenty_five_percent(self) -> None:
        """Other physical returns 25%."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type="other_physical")
        assert lgd == Decimal("0.25")
        assert "Other physical" in desc

    def test_equipment_alias(self) -> None:
        """Equipment alias returns 25%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="equipment")
        assert lgd == Decimal("0.25")

    def test_inventory_alias(self) -> None:
        """Inventory alias returns 25%."""
        lgd, _ = lookup_b31_firb_lgd(collateral_type="inventory")
        assert lgd == Decimal("0.25")

    def test_unknown_collateral_defaults_to_unsecured_non_fse(self) -> None:
        """Unknown collateral type defaults to unsecured non-FSE (40%)."""
        lgd, desc = lookup_b31_firb_lgd(collateral_type="unknown_widget")
        assert lgd == Decimal("0.40")
        assert "unsecured" in desc.lower()

    def test_unknown_collateral_fse_defaults_to_unsecured_fse(self) -> None:
        """Unknown collateral type with FSE flag defaults to unsecured FSE (45%)."""
        lgd, desc = lookup_b31_firb_lgd(
            collateral_type="unknown_widget", is_financial_sector_entity=True
        )
        assert lgd == Decimal("0.45")
        assert "FSE" in desc

    def test_case_insensitive(self) -> None:
        """Lookup is case insensitive."""
        lgd1, _ = lookup_b31_firb_lgd(collateral_type="Residential_RE")
        lgd2, _ = lookup_b31_firb_lgd(collateral_type="RESIDENTIAL_RE")
        lgd3, _ = lookup_b31_firb_lgd(collateral_type="residential_re")
        assert lgd1 == lgd2 == lgd3 == Decimal("0.20")


# =============================================================================
# COMPARISON TABLE TESTS
# =============================================================================


class TestB31VsCRRComparisonTable:
    """Tests for the CRR vs B31 comparison DataFrame."""

    def test_comparison_has_expected_columns(self) -> None:
        """Comparison table has required columns."""
        df = get_b31_vs_crr_lgd_comparison()
        assert set(df.columns) == {"collateral_type", "crr_lgd", "b31_lgd", "change_bps"}

    def test_comparison_non_fse_senior_minus_500bps(self) -> None:
        """Non-FSE senior unsecured shows -500bps change (45% -> 40%)."""
        df = get_b31_vs_crr_lgd_comparison()
        row = df.filter(pl.col("collateral_type") == "unsecured_senior")
        assert row["change_bps"][0] == -500

    def test_comparison_receivables_minus_1500bps(self) -> None:
        """Receivables shows -1500bps change (35% -> 20%)."""
        df = get_b31_vs_crr_lgd_comparison()
        row = df.filter(pl.col("collateral_type") == "receivables")
        assert row["change_bps"][0] == -1500

    def test_comparison_other_physical_minus_1500bps(self) -> None:
        """Other physical shows -1500bps change (40% -> 25%)."""
        df = get_b31_vs_crr_lgd_comparison()
        row = df.filter(pl.col("collateral_type") == "other_physical")
        assert row["change_bps"][0] == -1500

    def test_comparison_fse_zero_change(self) -> None:
        """FSE senior unsecured shows 0bps change (both 45%)."""
        df = get_b31_vs_crr_lgd_comparison()
        row = df.filter(pl.col("collateral_type") == "unsecured_senior_fse")
        assert row["change_bps"][0] == 0

    def test_comparison_subordinated_zero_change(self) -> None:
        """Subordinated shows 0bps change (both 75%)."""
        df = get_b31_vs_crr_lgd_comparison()
        row = df.filter(pl.col("collateral_type") == "subordinated")
        assert row["change_bps"][0] == 0

    def test_comparison_re_minus_1500bps(self) -> None:
        """Real estate types show -1500bps change (35% -> 20%)."""
        df = get_b31_vs_crr_lgd_comparison()
        rre = df.filter(pl.col("collateral_type") == "residential_re")
        cre = df.filter(pl.col("collateral_type") == "commercial_re")
        assert rre["change_bps"][0] == -1500
        assert cre["change_bps"][0] == -1500

    def test_comparison_includes_fse_entry(self) -> None:
        """Comparison table includes FSE-specific entry even though it only exists in B31."""
        df = get_b31_vs_crr_lgd_comparison()
        fse = df.filter(pl.col("collateral_type") == "unsecured_senior_fse")
        assert len(fse) == 1
        assert fse["crr_lgd"][0] == 0.45  # CRR has no FSE split — uses senior unsecured
        assert fse["b31_lgd"][0] == 0.45


# =============================================================================
# CONSISTENCY TESTS — constants, DataFrame, and dict must agree
# =============================================================================


class TestB31FIRBLGDConsistency:
    """Tests ensuring consistency between all three LGD representations."""

    def test_dataframe_matches_constants_non_fse_senior(self) -> None:
        """DataFrame non-FSE senior LGD matches named constant."""
        df = get_b31_firb_lgd_table()
        row = df.filter(
            (pl.col("collateral_type") == "unsecured")
            & (pl.col("seniority") == "senior")
            & (pl.col("is_fse") == False)  # noqa: E712
        )
        assert row["lgd"][0] == float(B31_FIRB_LGD_UNSECURED_SENIOR)

    def test_dataframe_matches_constants_fse_senior(self) -> None:
        """DataFrame FSE senior LGD matches named constant."""
        df = get_b31_firb_lgd_table()
        row = df.filter(
            (pl.col("collateral_type") == "unsecured")
            & (pl.col("seniority") == "senior")
            & (pl.col("is_fse") == True)  # noqa: E712
        )
        assert row["lgd"][0] == float(B31_FIRB_LGD_UNSECURED_SENIOR_FSE)

    def test_dataframe_matches_constants_receivables(self) -> None:
        """DataFrame receivables LGD matches named constant."""
        df = get_b31_firb_lgd_table()
        row = df.filter(pl.col("collateral_type") == "receivables")
        assert row["lgd"][0] == float(B31_FIRB_LGD_RECEIVABLES)

    def test_dataframe_matches_constants_other_physical(self) -> None:
        """DataFrame other physical LGD matches named constant."""
        df = get_b31_firb_lgd_table()
        row = df.filter(pl.col("collateral_type") == "other_physical")
        assert row["lgd"][0] == float(B31_FIRB_LGD_OTHER_PHYSICAL)

    def test_lookup_matches_constants_all_types(self) -> None:
        """Scalar lookup returns values consistent with named constants."""
        assert lookup_b31_firb_lgd(None, False, False)[0] == B31_FIRB_LGD_UNSECURED_SENIOR
        assert lookup_b31_firb_lgd(None, False, True)[0] == B31_FIRB_LGD_UNSECURED_SENIOR_FSE
        assert lookup_b31_firb_lgd(None, True, False)[0] == B31_FIRB_LGD_SUBORDINATED
        assert lookup_b31_firb_lgd("covered_bond")[0] == B31_FIRB_LGD_COVERED_BOND
        assert lookup_b31_firb_lgd("financial_collateral")[0] == B31_FIRB_LGD_FINANCIAL_COLLATERAL
        assert lookup_b31_firb_lgd("receivables")[0] == B31_FIRB_LGD_RECEIVABLES
        assert lookup_b31_firb_lgd("residential_re")[0] == B31_FIRB_LGD_RESIDENTIAL_RE
        assert lookup_b31_firb_lgd("commercial_re")[0] == B31_FIRB_LGD_COMMERCIAL_RE
        assert lookup_b31_firb_lgd("other_physical")[0] == B31_FIRB_LGD_OTHER_PHYSICAL

    def test_all_lgd_values_non_negative(self) -> None:
        """All LGD values in the DataFrame are non-negative."""
        df = get_b31_firb_lgd_table()
        assert df.filter(pl.col("lgd") < 0).height == 0

    def test_all_lgd_values_at_most_one(self) -> None:
        """All LGD values are at most 100% (1.0)."""
        df = get_b31_firb_lgd_table()
        assert df.filter(pl.col("lgd") > 1.0).height == 0

    def test_all_overcoll_ratios_at_least_one(self) -> None:
        """All overcollateralisation ratios are >= 1.0."""
        df = get_b31_firb_lgd_table()
        assert df.filter(pl.col("overcollateralisation_ratio") < 1.0).height == 0
