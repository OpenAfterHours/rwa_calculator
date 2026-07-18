"""
P1.234 unit: the Art. 224 Table 1 securitisation supervisory-haircut rows.

Values are the PRINTED 10-day-liquidation figures from the primary sources —
NOT an internal "2x corporate" derivation (which holds for CRR but NOT for
Basel 3.1's 5-band table):

    CRR Art. 224 Table 1 (crr.pdf p.221), securitisation column, 10-day:
        CQS 1  : 0-1y 2%,  1-5y 8%,  5y+ 16%
        CQS 2-3: 0-1y 4%,  1-5y 12%, 5y+ 24%
    PS1/26 Art. 224 Table 1 (ps126app1.pdf p.203), securitisation column, 10-day:
        CQS 1  : 0-1y 2%,  1-3y 8%,  3-5y 8%,  5-10y 16%, 10y+ 16%
        CQS 2-3: 0-1y 4%,  1-3y 12%, 3-5y 12%, 5-10y 24%, 10y+ 24%

References:
    - CRR Art. 224 Table 1; PS1/26 Art. 224 Table 1, securitisation column
      (Art. 197(1)(h) positions).
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.crm.haircut_tables import get_haircut_table

# (cqs, band) -> printed 10-day securitisation haircut.
_CRR_SEC: dict[tuple[int, str], float] = {
    (1, "0_1y"): 0.02,
    (1, "1_5y"): 0.08,
    (1, "5y_plus"): 0.16,
    (2, "0_1y"): 0.04,
    (2, "1_5y"): 0.12,
    (2, "5y_plus"): 0.24,
    (3, "0_1y"): 0.04,
    (3, "1_5y"): 0.12,
    (3, "5y_plus"): 0.24,
}
_B31_SEC: dict[tuple[int, str], float] = {
    (1, "0_1y"): 0.02,
    (1, "1_3y"): 0.08,
    (1, "3_5y"): 0.08,
    (1, "5_10y"): 0.16,
    (1, "10y_plus"): 0.16,
    (2, "0_1y"): 0.04,
    (2, "1_3y"): 0.12,
    (2, "3_5y"): 0.12,
    (2, "5_10y"): 0.24,
    (2, "10y_plus"): 0.24,
    (3, "0_1y"): 0.04,
    (3, "1_3y"): 0.12,
    (3, "3_5y"): 0.12,
    (3, "5_10y"): 0.24,
    (3, "10y_plus"): 0.24,
}


def _haircut(df: pl.DataFrame, collateral_type: str, cqs: int, band: str) -> float:
    row = df.filter(
        (pl.col("collateral_type") == collateral_type)
        & (pl.col("cqs") == cqs)
        & (pl.col("maturity_band") == band)
    )
    assert row.height == 1, f"expected 1 row for {collateral_type}/{cqs}/{band}, got {row.height}"
    return float(row["haircut"][0])


@pytest.mark.parametrize(
    ("is_b31", "expected"),
    [(False, _CRR_SEC), (True, _B31_SEC)],
    ids=["crr", "b31"],
)
def test_securitisation_haircut_matches_table1(
    is_b31: bool, expected: dict[tuple[int, str], float]
) -> None:
    """Every securitisation (cqs, band) haircut equals the printed Table 1 value."""
    df = get_haircut_table(is_basel_3_1=is_b31)
    for (cqs, band), value in expected.items():
        actual = _haircut(df, "securitisation", cqs, band)
        assert actual == pytest.approx(value), (
            f"securitisation {cqs}/{band}: {actual} != printed Table 1 {value}"
        )


def test_crr_securitisation_equals_double_corporate() -> None:
    """CRR only: the securitisation column happens to be 2x the corporate column."""
    df = get_haircut_table(is_basel_3_1=False)
    for cqs in (1, 2, 3):
        for band in ("0_1y", "1_5y", "5y_plus"):
            corp = _haircut(df, "corp_bond", cqs, band)
            sec = _haircut(df, "securitisation", cqs, band)
            assert sec == pytest.approx(2.0 * corp)


def test_b31_securitisation_is_not_double_corporate() -> None:
    """Basel 3.1: the 5-band securitisation column is NOT 2x corporate — it carries
    its own printed values (e.g. CQS1 1-3y sec = 8% vs 2x corp 3% = 6%)."""
    df = get_haircut_table(is_basel_3_1=True)
    corp = _haircut(df, "corp_bond", 1, "1_3y")  # 3%
    sec = _haircut(df, "securitisation", 1, "1_3y")  # 8% (not 6%)
    assert corp == pytest.approx(0.03)
    assert sec == pytest.approx(0.08)
    assert sec != pytest.approx(2.0 * corp)
