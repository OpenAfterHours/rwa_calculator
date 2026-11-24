"""OF 08.01 row 0200 follows the Art. 122(8) output-floor election (P1.475).

PS1/26 Annex II, OF 08.01 row 0200 "Of which: investment grade": "Institutions
shall report values that are consistent with approach used for the purpose of
calculating the output floor in accordance with [...] Article 92(3a)."
Art. 92(3A)(b)(ii) points S-TREA at Art. 122(8): (a) 100% for every unrated
corporate the firm weights under the IRB Approach, or (b) the Art. 122(6)
65% / 135% weights from its own investment-grade assessment.

So the row's population is the IRB legs whose S-TREA weight came from an
investment-grade assessment, which is what the engine seals as
``sa_investment_grade_assessed`` (True = the assessment set the 65%; null where
another rule — Art. 122(11), Art. 133, Art. 127 — sets the weight). Under
(8)(a) the firm makes no such assessment for the floor, the carrier is null on
every leg, and the row is left unreported (LESSONS B4: a zero is a fact, an
empty cell is not). The raw counterparty input ``cp_is_investment_grade``
must not populate it on its own: at HEAD it did, whatever the election.

References:
- PS1/26 Art. 122(8), Art. 92(3A)(b)(ii)
- PS1/26 Annex II, OF 08.01 rows 0190 / 0200 (printed p.118)
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._irb_sheet_frames import OF08_CORPORATE_NON_SME_FIRB

_IG_EAD = 2_000.0
_NIG_EAD = 1_000.0


def _unrated_irb_corporates(assessed: list[bool | None]) -> pl.LazyFrame:
    """Two unrated F-IRB corporates, one flagged investment grade on its input.

    ``assessed`` is the sealed ``sa_investment_grade_assessed`` carrier per leg:
    ``[True, False]`` is what an Art. 122(8)(b) run seals, ``[None, None]`` an
    Art. 122(8)(a) run. ``cqs`` is null on both — the sealed ECAI carrier.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_UNRATED_IG", "IRB_CORP_UNRATED_NIG"],
            "counterparty_reference": ["CP_IG", "CP_NIG"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [_IG_EAD, _NIG_EAD],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [_IG_EAD, _NIG_EAD],
            "rwa_final": [1_000.0, 800.0],
            "risk_weight": [0.50, 0.80],
            "pd_floored": [0.003, 0.02],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5],
            "cqs": pl.Series([None, None], dtype=pl.Int8),
            "cp_is_investment_grade": [True, False],
            "sa_investment_grade_assessed": pl.Series(assessed, dtype=pl.Boolean),
        }
    )


def _row_0200_ead(assessed: list[bool | None]) -> float | None:
    """Generate Basel 3.1 OF 08.01 and read row 0200 col 0110 on the F-IRB corporate sheet."""
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
        _unrated_irb_corporates(assessed), framework="BASEL_3_1"
    )
    sheet = bundle.c08_01[OF08_CORPORATE_NON_SME_FIRB]
    return sheet.filter(pl.col("row_ref") == "0200")["0110"][0]


class TestRow0200FollowsTheFloorElection:
    """Row 0200 is the investment-grade-assessed subset under (8)(b), and empty under (8)(a)."""

    def test_row_0200_reports_the_assessed_investment_grade_legs_under_8b(self) -> None:
        """Art. 122(8)(b): row 0200 = the leg assessed investment grade (EAD 2,000)."""
        # Arrange
        assessed: list[bool | None] = [True, False]

        # Act
        ead = _row_0200_ead(assessed)

        # Assert
        assert ead == pytest.approx(_IG_EAD)

    def test_row_0200_unreported_under_8a_whatever_the_input_flag(self) -> None:
        """Art. 122(8)(a): no IG assessment for the floor, so row 0200 is empty, not 0.

        The input flags one leg investment grade; at HEAD that alone put 2,000
        in the row although the floor weighted it at 100%.
        """
        # Arrange
        assessed: list[bool | None] = [None, None]

        # Act
        ead = _row_0200_ead(assessed)

        # Assert
        assert ead is None
