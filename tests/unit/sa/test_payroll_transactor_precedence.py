"""
Unit tests for the precedence of the payroll 35% over the transactor 45% (P1.350).

Pipeline position:
    CRMProcessor -> SACalculator.calculate_branch -> Aggregation

Why these tests matter:
    PS1/26 Art. 123(3) opens "Subject to paragraph 4, retail exposures shall be
    assigned the following risk weights: (a) regulatory retail exposures that are
    transactor exposures shall be assigned a risk weight of 45%; ...". Paragraph 4
    gives "Retail exposures arising due to loans granted ... against the
    unconditional transfer of part of the borrower's pension or salary" 35%,
    provided its conditions (a)-(d) are met. "Subject to paragraph 4" puts the
    35% above the WHOLE paragraph-3 ladder, the 45% transactor weight included.
    The Basel 3.1 chain tested the transactor limb first, so a regulatory-retail
    transactor that is also a payroll loan took 45% instead of 35%.

    Paragraph 4 applies to "Retail exposures", not only to regulatory retail, so
    the 35% must not depend on Art. 123A qualification: the non-qualifying
    payroll cells stay 35%, not 100%.

    The expected weight of every cell is derived here from the article text
    (``_b31_expected_weight``), never from the engine's when-chain, so the grid
    cannot share the chain's ordering (LESSONS B3 / C1).

    CRR has no transactor weight (CRR Art. 123 has one 75% retail weight and the
    payroll subparagraph), so the cell cannot be wrong under CRR and the CRR leg
    is a parity guard that is green before and after the change.

    A payroll row whose own dates fail condition (d) keeps the 45% transactor
    weight; that leg is pinned by
    ``tests/unit/sa/test_payroll_maturity_limb.py`` (P1.365).

References:
- PRA PS1/26 Art. 123(3) chapeau "Subject to paragraph 4" and points (a)-(c)
- PRA PS1/26 Art. 123(4): payroll / pension loans, 35%
- CRR Art. 123 final subparagraph (payroll / pension loans, 35%)
"""

from __future__ import annotations

from datetime import date
from itertools import product

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator

_EAD = 25_000.0
_PAYROLL_RW = 0.35  # PS1/26 Art. 123(4); CRR Art. 123 final subparagraph
_TRANSACTOR_RW = 0.45  # PS1/26 Art. 123(3)(a)
_REGULATORY_RETAIL_RW = 0.75  # PS1/26 Art. 123(3)(b)
_NON_REGULATORY_RETAIL_RW = 1.00  # PS1/26 Art. 123(3)(c)

_RETAIL_CLASSES = ("RETAIL_QRRE", "RETAIL_OTHER")

# (exposure_class, is_qrre_transactor, is_payroll_loan, qualifies_as_retail)
_GRID = list(product(_RETAIL_CLASSES, (True, False), (True, False), (True, False)))


def _grid_id(cell: tuple[str, bool, bool, bool]) -> str:
    """Readable test id, e.g. ``RETAIL_QRRE-transactor-payroll-qualifies``."""
    exposure_class, transactor, payroll, qualifies = cell
    return "-".join(
        [
            exposure_class,
            "transactor" if transactor else "non_transactor",
            "payroll" if payroll else "non_payroll",
            "qualifies" if qualifies else "non_qualifying",
        ]
    )


def _b31_expected_weight(*, transactor: bool, payroll: bool, qualifies: bool) -> float:
    """PS1/26 Art. 123(3)-(4), read as written.

    Paragraph 4 first, because paragraph 3 is "Subject to paragraph 4" and
    paragraph 4 speaks of "Retail exposures" (not only regulatory retail).
    Then paragraph 3: (a) regulatory retail transactor, (b) regulatory retail
    non-transactor, (c) all other retail. Condition (d) of paragraph 4 is met
    here because no maturity data is supplied (see the module docstring).
    """
    if payroll:
        return _PAYROLL_RW
    if not qualifies:
        return _NON_REGULATORY_RETAIL_RW
    return _TRANSACTOR_RW if transactor else _REGULATORY_RETAIL_RW


def _config(regime: str) -> CalculationConfig:
    """The regime's calculation config, built through its factory."""
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _retail_row(
    exposure_class: str, *, transactor: bool, payroll: bool, qualifies: bool
) -> pl.LazyFrame:
    """One natural-person retail row, no maturity data, flags as given."""
    return pl.DataFrame(
        {
            "exposure_reference": ["RTL_P1350"],
            "ead_final": [_EAD],
            "exposure_class": [exposure_class],
            "cqs": [None],
            "is_sme": [False],
            "is_infrastructure": [False],
            "is_qrre_transactor": [transactor],
            "is_payroll_loan": [payroll],
            "qualifies_as_retail": [qualifies],
        },
        schema_overrides={"cqs": pl.Int8},
    ).lazy()


def _run(regime: str, row: pl.LazyFrame) -> dict:
    """Run the SA branch on one row and return it as a dict."""
    return SACalculator().calculate_branch(row, _config(regime)).collect().to_dicts()[0]


class TestB31PayrollOutranksTransactorWeight:
    """Basel 3.1: the Art. 123(4) 35% overrides the Art. 123(3)(a) 45%."""

    @pytest.mark.parametrize("exposure_class", _RETAIL_CLASSES)
    def test_qualifying_transactor_payroll_loan_takes_payroll_weight(
        self, exposure_class: str
    ) -> None:
        """Transactor + payroll + regulatory retail: 35%, not 45%."""
        # Arrange
        row = _retail_row(exposure_class, transactor=True, payroll=True, qualifies=True)

        # Act
        result = _run("b31", row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)
        assert result["rwa_pre_factor"] == pytest.approx(_EAD * _PAYROLL_RW)

    @pytest.mark.parametrize("cell", _GRID, ids=[_grid_id(cell) for cell in _GRID])
    def test_retail_ladder_cell_matches_article_123(
        self, cell: tuple[str, bool, bool, bool]
    ) -> None:
        """Every (class, transactor, payroll, qualifies) cell takes the Art. 123 weight.

        Guards the cells the reorder must NOT move: a payroll limb conjoined
        with Art. 123A qualification would send the non-qualifying payroll
        cells to 100%, and a transactor limb that lost its qualification gate
        would send the non-qualifying transactor cells to 45%.
        """
        # Arrange
        exposure_class, transactor, payroll, qualifies = cell
        row = _retail_row(
            exposure_class, transactor=transactor, payroll=payroll, qualifies=qualifies
        )
        expected = _b31_expected_weight(transactor=transactor, payroll=payroll, qualifies=qualifies)

        # Act
        result = _run("b31", row)

        # Assert
        assert result["risk_weight"] == pytest.approx(expected)


class TestCrrPayrollTransactorParity:
    """CRR has no transactor weight; the same row takes the payroll 35%."""

    @pytest.mark.parametrize("exposure_class", _RETAIL_CLASSES)
    def test_qualifying_transactor_payroll_loan_takes_payroll_weight(
        self, exposure_class: str
    ) -> None:
        """CRR Art. 123 final subparagraph: 35% whatever the transactor flag."""
        # Arrange
        row = _retail_row(exposure_class, transactor=True, payroll=True, qualifies=True)

        # Act
        result = _run("crr", row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)
