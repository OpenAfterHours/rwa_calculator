"""
Unit tests — P1.179: FIRB LGD naming regression guard.

Six assertion groups that pin the full naming and value contract for
``get_firb_lgd_table`` and ``get_firb_lgd_table_for_framework`` across both
CRR and Basel 3.1 frameworks. These tests complement the existing dispatch
test (``test_p1_179_firb_lgd_table_dispatch.py``) with more granular
value-level assertions, schema-delta checks, cross-helper consistency, and
re-export object-identity verification.

References:
    CRR Art. 161 / Art. 230 Table 5: CRR supervisory LGD values
    PRA PS1/26 Art. 161 / BCBS CRE32.9-12: Basel 3.1 revised supervisory LGDs
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.data.tables.firb_lgd import (
    get_firb_lgd_table,
    get_firb_lgd_table_for_framework,
)


class TestP1179FirbLgdNamingRegression:
    """Regression guard: naming and value contract for FIRB LGD helpers.

    Covers six orthogonal aspects not pinned by the existing dispatch test:
    1. CRR default DataFrame values (unsecured senior and receivables senior)
    2. B31 DataFrame values including FSE/non-FSE split
    3. Schema delta: is_fse column present only in B31 DataFrame
    4. Dict-helper values for unsecured_senior and receivables in both frameworks
    5. Cross-helper consistency: DataFrame lgd floats must match dict Decimal values
    6. Re-export object identity: symbols in rwa_calc.data.tables are the same
       objects as in rwa_calc.data.tables.firb_lgd
    """

    # -------------------------------------------------------------------------
    # 1. CRR DataFrame default values
    # -------------------------------------------------------------------------

    def test_crr_dataframe_default_values(self) -> None:
        """get_firb_lgd_table() with no args returns CRR Art. 161 / Art. 230 Table 5 values.

        Pins two rows:
        - (unsecured, senior): lgd == 0.45  (CRR Art. 161(1)(a))
        - (receivables, senior): lgd == 0.35  (CRR Art. 230 Table 5)

        Arrange: call get_firb_lgd_table() — no kwargs, CRR default.
        Act:     filter to each target row, extract lgd scalar.
        Assert:  lgd matches regulatory value.
        """
        # Arrange / Act
        df = get_firb_lgd_table()

        # Assert — unsecured senior
        unsecured_lgd = (
            df.filter(
                (pl.col("collateral_type") == "unsecured") & (pl.col("seniority") == "senior")
            )
            .select("lgd")
            .item()
        )
        assert unsecured_lgd == pytest.approx(0.45), (
            f"CRR Art. 161(1)(a): expected unsecured senior LGD = 0.45, got {unsecured_lgd}"
        )

        # Assert — receivables senior
        receivables_lgd = (
            df.filter(
                (pl.col("collateral_type") == "receivables") & (pl.col("seniority") == "senior")
            )
            .select("lgd")
            .item()
        )
        assert receivables_lgd == pytest.approx(0.35), (
            f"CRR Art. 230 Table 5: expected receivables senior LGD = 0.35, got {receivables_lgd}"
        )

    # -------------------------------------------------------------------------
    # 2. B31 DataFrame values including FSE/non-FSE split
    # -------------------------------------------------------------------------

    def test_b31_dataframe_values_with_fse_split(self) -> None:
        """get_firb_lgd_table(is_basel_3_1=True) returns PS1/26 / CRE32.9 values with FSE split.

        Pins three rows:
        - (unsecured, senior, is_fse=False): lgd == 0.40  (CRE32.9 / Art. 161(1)(aa))
        - (unsecured, senior, is_fse=True):  lgd == 0.45  (Art. 161(1)(a) — FSE unchanged)
        - (receivables, senior, is_fse=False): lgd == 0.20  (CRE32.9)

        Arrange: call get_firb_lgd_table(is_basel_3_1=True).
        Act:     filter each target row, extract lgd scalar.
        Assert:  lgd matches regulatory value.
        """
        # Arrange / Act
        df = get_firb_lgd_table(is_basel_3_1=True)

        # Assert — unsecured senior non-FSE (40% under B31)
        non_fse_lgd = (
            df.filter(
                (pl.col("collateral_type") == "unsecured")
                & (pl.col("seniority") == "senior")
                & (pl.col("is_fse") == False)  # noqa: E712
            )
            .select("lgd")
            .item()
        )
        assert non_fse_lgd == pytest.approx(0.40), (
            f"PRA PS1/26 Art. 161(1)(aa): expected non-FSE unsecured senior LGD = 0.40, "
            f"got {non_fse_lgd}"
        )

        # Assert — unsecured senior FSE (45% unchanged)
        fse_lgd = (
            df.filter(
                (pl.col("collateral_type") == "unsecured")
                & (pl.col("seniority") == "senior")
                & (pl.col("is_fse") == True)  # noqa: E712
            )
            .select("lgd")
            .item()
        )
        assert fse_lgd == pytest.approx(0.45), (
            f"PRA PS1/26 Art. 161(1)(a): expected FSE unsecured senior LGD = 0.45, got {fse_lgd}"
        )

        # Assert — receivables senior (20% under B31)
        receivables_lgd = (
            df.filter(
                (pl.col("collateral_type") == "receivables")
                & (pl.col("seniority") == "senior")
                & (pl.col("is_fse") == False)  # noqa: E712
            )
            .select("lgd")
            .item()
        )
        assert receivables_lgd == pytest.approx(0.20), (
            f"BCBS CRE32.9: expected receivables senior LGD = 0.20, got {receivables_lgd}"
        )

    # -------------------------------------------------------------------------
    # 3. Schema delta: is_fse only in B31 DataFrame
    # -------------------------------------------------------------------------

    def test_schema_delta_is_fse_only_on_b31(self) -> None:
        """CRR DataFrame must not have 'is_fse'; B31 DataFrame must have 'is_fse'.

        The FSE/non-FSE distinction is introduced in Basel 3.1 Art. 161(1)(a)/(aa).
        The CRR table has no such split, so the column should be absent.

        Arrange: call both variants of get_firb_lgd_table.
        Act:     inspect .columns list.
        Assert:  'is_fse' absent in CRR; 'is_fse' present in B31.
        """
        # Arrange
        df_crr = get_firb_lgd_table()
        df_b31 = get_firb_lgd_table(is_basel_3_1=True)

        # Assert
        assert "is_fse" not in df_crr.columns, (
            "CRR table must not contain 'is_fse' column — FSE split is B31-only "
            "(Art. 161(1)(a)/(aa) introduced in PS1/26)."
        )
        assert "is_fse" in df_b31.columns, (
            "B31 table must contain 'is_fse' column — required to distinguish "
            "FSE (45%) from non-FSE (40%) unsecured senior LGD."
        )

    # -------------------------------------------------------------------------
    # 4. Dict-helper values
    # -------------------------------------------------------------------------

    def test_dict_helper_values(self) -> None:
        """get_firb_lgd_table_for_framework returns correct Decimal values.

        Pins four key-value pairs across both framework variants:
        - CRR unsecured_senior: Decimal("0.45")
        - B31 unsecured_senior: Decimal("0.40")
        - B31 unsecured_senior_fse: Decimal("0.45")
        - B31 receivables: Decimal("0.20")

        Arrange: call get_firb_lgd_table_for_framework for both frameworks.
        Act:     index the returned dict by key.
        Assert:  value == expected Decimal.
        """
        # Arrange
        crr_dict = get_firb_lgd_table_for_framework(False)
        b31_dict = get_firb_lgd_table_for_framework(True)

        # Assert — CRR
        assert crr_dict["unsecured_senior"] == Decimal("0.45"), (
            f"CRR Art. 161(1)(a): expected unsecured_senior = Decimal('0.45'), "
            f"got {crr_dict['unsecured_senior']!r}"
        )

        # Assert — B31
        assert b31_dict["unsecured_senior"] == Decimal("0.40"), (
            f"PS1/26 Art. 161(1)(aa): expected unsecured_senior = Decimal('0.40'), "
            f"got {b31_dict['unsecured_senior']!r}"
        )
        assert b31_dict["unsecured_senior_fse"] == Decimal("0.45"), (
            f"PS1/26 Art. 161(1)(a): expected unsecured_senior_fse = Decimal('0.45'), "
            f"got {b31_dict['unsecured_senior_fse']!r}"
        )
        assert b31_dict["receivables"] == Decimal("0.20"), (
            f"BCBS CRE32.9: expected receivables = Decimal('0.20'), got {b31_dict['receivables']!r}"
        )

    # -------------------------------------------------------------------------
    # 5. Cross-helper consistency
    # -------------------------------------------------------------------------

    def test_cross_helper_consistency(self) -> None:
        """DataFrame lgd floats and dict Decimal values must agree for both frameworks.

        Guards against a divergence where the DataFrame-builder and the dict
        helper are updated independently and drift out of sync.

        For each framework, checks:
        - (unsecured, senior) row lgd  ==  dict["unsecured_senior"]  (non-FSE for B31)
        - (receivables, senior) row lgd  ==  dict["receivables"]

        Arrange: produce DataFrame and dict for each framework.
        Act:     extract floats from DataFrame, cast Decimal to float.
        Assert:  values agree within pytest.approx tolerance.
        """
        for is_b31 in (False, True):
            df = get_firb_lgd_table(is_basel_3_1=is_b31)
            d = get_firb_lgd_table_for_framework(is_b31)

            # unsecured senior — for B31 we want the non-FSE row
            if is_b31:
                df_unsecured_lgd = (
                    df.filter(
                        (pl.col("collateral_type") == "unsecured")
                        & (pl.col("seniority") == "senior")
                        & (pl.col("is_fse") == False)  # noqa: E712
                    )
                    .select("lgd")
                    .item()
                )
            else:
                df_unsecured_lgd = (
                    df.filter(
                        (pl.col("collateral_type") == "unsecured")
                        & (pl.col("seniority") == "senior")
                    )
                    .select("lgd")
                    .item()
                )

            dict_unsecured_lgd = float(d["unsecured_senior"])

            assert df_unsecured_lgd == pytest.approx(dict_unsecured_lgd), (
                f"Framework is_b31={is_b31}: DataFrame unsecured senior lgd "
                f"({df_unsecured_lgd}) != dict unsecured_senior ({dict_unsecured_lgd})"
            )

            # receivables senior — no is_fse split for receivables row
            if is_b31:
                df_receivables_lgd = (
                    df.filter(
                        (pl.col("collateral_type") == "receivables")
                        & (pl.col("seniority") == "senior")
                        & (pl.col("is_fse") == False)  # noqa: E712
                    )
                    .select("lgd")
                    .item()
                )
            else:
                df_receivables_lgd = (
                    df.filter(
                        (pl.col("collateral_type") == "receivables")
                        & (pl.col("seniority") == "senior")
                    )
                    .select("lgd")
                    .item()
                )

            dict_receivables_lgd = float(d["receivables"])

            assert df_receivables_lgd == pytest.approx(dict_receivables_lgd), (
                f"Framework is_b31={is_b31}: DataFrame receivables senior lgd "
                f"({df_receivables_lgd}) != dict receivables ({dict_receivables_lgd})"
            )

    # -------------------------------------------------------------------------
    # 6. Re-export object identity
    # -------------------------------------------------------------------------

    def test_re_export_object_identity(self) -> None:
        """Symbols in rwa_calc.data.tables are the same objects as in firb_lgd sub-module.

        Guards against shadowing or re-definition in the package __init__.py
        that would cause callers using different import paths to receive
        different objects.

        Arrange: import each symbol from both rwa_calc.data.tables and
                 rwa_calc.data.tables.firb_lgd.
        Act:     compare with ``is``.
        Assert:  all four symbols are identical objects.
        """
        # Import from top-level package re-export
        from rwa_calc.data.tables import BASEL31_FIRB_SUPERVISORY_LGD as b31_dict_top
        from rwa_calc.data.tables import FIRB_SUPERVISORY_LGD as crr_dict_top
        from rwa_calc.data.tables import get_firb_lgd_table as ft_top
        from rwa_calc.data.tables import get_firb_lgd_table_for_framework as ffw_top

        # Import from sub-module directly
        from rwa_calc.data.tables.firb_lgd import BASEL31_FIRB_SUPERVISORY_LGD as b31_dict_sub
        from rwa_calc.data.tables.firb_lgd import FIRB_SUPERVISORY_LGD as crr_dict_sub
        from rwa_calc.data.tables.firb_lgd import get_firb_lgd_table as ft_sub
        from rwa_calc.data.tables.firb_lgd import (
            get_firb_lgd_table_for_framework as ffw_sub,
        )

        # Assert object identity (not just equality)
        assert ft_top is ft_sub, (
            "get_firb_lgd_table from rwa_calc.data.tables is NOT the same object "
            "as from rwa_calc.data.tables.firb_lgd — re-export is shadowing the function."
        )
        assert ffw_top is ffw_sub, (
            "get_firb_lgd_table_for_framework from rwa_calc.data.tables is NOT the same "
            "object as from rwa_calc.data.tables.firb_lgd."
        )
        assert crr_dict_top is crr_dict_sub, (
            "FIRB_SUPERVISORY_LGD from rwa_calc.data.tables is NOT the same object "
            "as from rwa_calc.data.tables.firb_lgd."
        )
        assert b31_dict_top is b31_dict_sub, (
            "BASEL31_FIRB_SUPERVISORY_LGD from rwa_calc.data.tables is NOT the same "
            "object as from rwa_calc.data.tables.firb_lgd."
        )
