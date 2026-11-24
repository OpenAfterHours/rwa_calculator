"""
P1.206 -- one predicate for "private equity in sufficiently diversified portfolios".

Rule text (onshored UK CRR, legislation.gov.uk point-in-time text, 2026-01-01):

- Art. 155(2): "Risk weight (RW) 190 % for private equity exposures in
  sufficiently diversified portfolios. Risk weight (RW) 290 % for exchange
  traded equity exposures. Risk weight (RW) 370 % for all other equity
  exposures."
- Art. 155(3): "... For private equity exposures in sufficiently diversified
  portfolios an LGD of 65 % may be used. For these purposes M shall be five
  years."
- Art. 165(2): "Private equity exposures in sufficiently diversified portfolios
  may be assigned an LGD of 65 %. All other such exposures shall be assigned an
  LGD of 90 %."

All three paragraphs use the same test, so the engine holds one predicate for
it, and the IRB-Simple (Art. 155(2)) and PD/LGD (Art. 155(3) / 165(2)) branches
both read it. The predicate's one input encoding is
``equity_type == "private_equity_diversified"``. Before P1.206 the IRB-Simple
branch also honoured a boolean ``is_diversified_portfolio`` that the PD/LGD
branch ignored. The loader never declared that column and stripped it at the
seal, so in production the second encoding was dead. On a hand-built frame it
split the two branches (190% under IRB-Simple, 90% LGD under PD/LGD for the same
row).

Basel 3.1: PS1/26 Arts. 155(1)-(4) and 165(1)-(3) are all "[Note: Provision left
blank]" (ps126app1.pdf pp.105, 115), i.e. deleted. Equity is weighted under
Art. 133 and the diversified predicate is not read. The Basel 3.1 run below is a
NON-MOVING control: this change cannot redden it (LESSONS C7 -- recorded, not
dropped). What it does detect is the CRR diversified relief leaking into
Basel 3.1.

Hand calculation (EAD = carrying value = fair value = 1,000,000):

    IRB-Simple (Art. 155(2), Art. 158(7) EL):
        PE_DIV  private_equity_diversified   RW 190%  RWA 1,900,000  EL 0.8% =  8,000
        PE      private_equity               RW 370%  RWA 3,700,000  EL 2.4% = 24,000

    PD/LGD (Art. 155(3), 165; has_default_definition_info=True so no 1.5x):
        PD    = 1.25%  (Art. 165(1)(d): private equity is "all other equity")
        M     = 5      (Art. 165(3));  scaling 1.06 (Art. 153(1))
        f     = (1 - exp(-50 x 0.0125)) / (1 - exp(-50))       = 0.4647385715
        R     = 0.12 f + 0.24 (1 - f)                           = 0.1842313714
        G(PD) = N^-1(0.0125)                                    = -2.2414027276
        cPD   = N[G(PD)/sqrt(1-R) + sqrt(R/(1-R)) x N^-1(0.999)] = 0.1555123929
        b     = (0.11852 - 0.05478 ln 0.0125)^2                 = 0.1285705940
        MA    = (1 + 2.5 b) / (1 - 1.5 b)                       = 1.6371630175
        PE_DIV  LGD 65%: K = 0.65 (cPD - PD) = 0.0929580554
                RW = K x 12.5 x 1.06 x MA = 2.01648425   EL = 0.0125 x 0.65 x 1m = 8,125
        PE      LGD 90%: K = 0.90 (cPD - PD) = 0.1287111536
                RW = K x 12.5 x 1.06 x MA = 2.79205511   EL = 0.0125 x 0.90 x 1m = 11,250
        Art. 155(3) cap: EL x 12.5 + RWEA <= 12,500,000 holds for both (not binding).

    Basel 3.1, reporting date 2030-06-30 (after the rules 4.1-4.3 transitional),
    no business age (Art. 133(4) higher-risk, conservative): both legs 400%.

PE_FLAG is ``private_equity`` with ``is_diversified_portfolio=True``, as the user
guide used to tell firms to supply it. The loader does not declare that column,
so the row is weighted as undiversified private equity in every regime. A firm
claims Art. 155(2)/165(2) diversification through the equity type.

References:
- CRR Art. 155(2), 155(3), 158(7), 165(1)(d), 165(2), 165(3)
- PRA PS1/26 Arts. 155, 165 (left blank); Art. 133(4)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import VALID_EQUITY_TYPES
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.pipeline import PipelineOrchestrator

EAD = 1_000_000.0

_CRR_IRB_SIMPLE = CalculationConfig.crr(
    reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB
)
_CRR_PD_LGD = CalculationConfig.crr(
    reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB, equity_pd_lgd=True
)
_B31 = CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))

_CONFIGS: dict[str, CalculationConfig] = {
    "crr_irb_simple": _CRR_IRB_SIMPLE,
    "crr_pd_lgd": _CRR_PD_LGD,
    "b31": _B31,
}

#: Hand-derived (risk_weight, expected_loss) per leg per run -- see the module docstring.
_EXPECTED: dict[str, dict[str, tuple[float, float | None]]] = {
    "crr_irb_simple": {
        "PE_DIV": (1.90, 8_000.0),
        "PE": (3.70, 24_000.0),
        "PE_FLAG": (3.70, 24_000.0),
    },
    "crr_pd_lgd": {
        "PE_DIV": (2.01648425, 8_125.0),
        "PE": (2.79205511, 11_250.0),
        "PE_FLAG": (2.79205511, 11_250.0),
    },
    "b31": {
        "PE_DIV": (4.00, None),
        "PE": (4.00, None),
        "PE_FLAG": (4.00, None),
    },
}

#: Art. 165(2) supervisory LGD the PD/LGD run must assign each leg.
_EXPECTED_PD_LGD_LGD = {"PE_DIV": 0.65, "PE": 0.90, "PE_FLAG": 0.90}

_CACHE: dict[str, pl.DataFrame] = {}


def _run(run: str) -> pl.DataFrame:
    """Run the three-leg equity book end to end, through the loader seal."""
    if run in _CACHE:
        return _CACHE[run]
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["PE_FUND"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
        }
    )
    equity = pl.DataFrame(
        {
            "exposure_reference": ["PE_DIV", "PE", "PE_FLAG"],
            "counterparty_reference": ["PE_FUND"] * 3,
            "equity_type": ["private_equity_diversified", "private_equity", "private_equity"],
            "currency": ["GBP"] * 3,
            "carrying_value": [EAD] * 3,
            "fair_value": [EAD] * 3,
            "has_default_definition_info": [True] * 3,
            # The retired second encoding, supplied as the user guide used to say.
            "is_diversified_portfolio": [False, False, True],
        }
    )
    result = PipelineOrchestrator().run_with_data(
        make_raw_bundle(counterparties=counterparties, equity_exposures=equity), _CONFIGS[run]
    )
    assert not [e for e in result.errors if "contract violated" in e.message]
    _CACHE[run] = result.results.collect()
    return _CACHE[run]


def _leg(run: str, leg: str) -> dict:
    frame = _run(run)
    return frame.filter(pl.col("exposure_reference") == leg).row(0, named=True)


@pytest.mark.parametrize(
    ("run", "leg"), [(run, leg) for run, legs in _EXPECTED.items() for leg in legs]
)
def test_diversified_private_equity_weight_and_expected_loss(run: str, leg: str) -> None:
    """Each leg takes its hand-derived Art. 155(2) / 155(3) / 133 weight and EL."""
    # Arrange
    expected_rw, expected_el = _EXPECTED[run][leg]

    # Act
    row = _leg(run, leg)

    # Assert
    assert row["ead_final"] == pytest.approx(EAD)
    assert row["risk_weight"] == pytest.approx(expected_rw, rel=1e-7)
    assert row["rwa_final"] == pytest.approx(expected_rw * EAD, rel=1e-7)
    if expected_el is None:
        assert row["expected_loss"] is None
    else:
        assert row["expected_loss"] == pytest.approx(expected_el, rel=1e-9)


@pytest.mark.parametrize("leg", sorted(_EXPECTED_PD_LGD_LGD))
def test_pd_lgd_assigns_the_art_165_2_lgd(leg: str) -> None:
    """Art. 165(2): 65% for diversified private equity, 90% for all other."""
    # Act
    row = _leg("crr_pd_lgd", leg)

    # Assert
    assert row["equity_method"] == "pd_lgd", "the PD/LGD run must take the Art. 155(3) path"
    assert row["lgd"] == pytest.approx(_EXPECTED_PD_LGD_LGD[leg])


@pytest.mark.parametrize("equity_type", sorted(VALID_EQUITY_TYPES))
@pytest.mark.parametrize("stray_flag", [False, True])
def test_irb_simple_and_pd_lgd_agree_on_which_rows_are_diversified_private_equity(
    equity_type: str, stray_flag: bool
) -> None:
    """Art. 155(2) 190% and Art. 165(2) 65% select exactly the same rows.

    The frame is hand-built and deliberately carries a stray
    ``is_diversified_portfolio`` column -- the second encoding the IRB-Simple
    branch used to read and the PD/LGD branch never did. Production strips that
    column at the loader seal (the contract test pins that), so this is not
    evidence about production input. It asserts that the two branches classify
    any row the same way, which holds whether or not a later change declares a
    diversification flag, provided both branches read one predicate.
    """
    # Arrange
    frame = pl.DataFrame(
        {
            "exposure_reference": ["ROW"],
            "equity_type": [equity_type],
            "ead_final": [EAD],
            "is_diversified_portfolio": [stray_flag],
        }
    ).lazy()
    calculator = EquityCalculator()

    # Act
    simple = calculator.calculate_branch(frame, _CRR_IRB_SIMPLE).collect().row(0, named=True)
    pd_lgd = calculator.calculate_branch(frame, _CRR_PD_LGD).collect().row(0, named=True)

    # Assert
    assert simple["equity_method"] == "irb_simple"
    assert pd_lgd["equity_method"] == "pd_lgd"
    simple_says_diversified = simple["risk_weight"] == pytest.approx(1.90)
    pd_lgd_says_diversified = pd_lgd["lgd"] == pytest.approx(0.65)
    assert simple_says_diversified == pd_lgd_says_diversified, (
        f"{equity_type} (stray flag {stray_flag}): IRB-Simple RW {simple['risk_weight']} "
        f"vs PD/LGD LGD {pd_lgd['lgd']} -- the branches read different diversified-PE "
        "predicates (CRR Art. 155(2) and 165(2) share one test)"
    )
    if equity_type == "private_equity_diversified":
        assert simple_says_diversified, "the equity type is the predicate's own encoding"
