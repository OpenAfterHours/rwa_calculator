"""
P1.265 — the Art. 111(1)(c) commitment-to-issue lower-of cap is Basel 3.1 only.

Pipeline position:
    HierarchyResolver -> CCFCalculator.apply_ccf -> SA / F-IRB exposure value

What this pins:
    PS1/26 Art. 111(1)(c) caps a commitment to issue an off-balance-sheet item
    at "the lower of (i) the CCF applicable to the underlying OBS item and
    (ii) the CCF applicable to the commitment type".

    **CRR has no such provision.** CRR Art. 111(1) (``crr.pdf`` PAGE_INDEX
    108-109) gives the four percentages and nothing more — "(a) 100 % if it is
    a full-risk item; (b) 50 % if it is a medium-risk item; (c) 20 % if it is a
    medium/low-risk item; (d) 0 % if it is a low-risk item" — then "The
    off-balance sheet items ... shall be assigned to risk categories as
    indicated in Annex I", then the Art. 223 volatility-adjustment sentence.

    The engine applied the cap under both regimes, so a CRR full-risk
    commitment to issue a low-risk item fell from 100% to 0% on the strength of
    a rule CRR does not contain — an understatement of the whole exposure.

⚠ The citation is a trap worth stating explicitly:
    **PS1/26** Art. 111(1)(c) is the lower-of rule.
    **CRR** Art. 111(1)(c) is "20 % if it is a medium/low-risk item".
    Same address, unrelated provisions. A CRR citation of 111(1)(c) is not
    authority for this cap.

The FR-over-LR pair is chosen deliberately: it is the maximum-swing case
(100% → 0%), so the CRR assertion cannot pass by coincidence, and the Basel 3.1
assertion proves the cap still bites where the article does provide it.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator

_NOMINAL = 1_000_000.0


def _ccf(config: CalculationConfig, risk_type: str, underlying: str | None) -> float:
    """SA CCF for a commitment of ``risk_type`` to issue an ``underlying`` item."""
    frame = pl.DataFrame(
        {
            "exposure_reference": ["C1"],
            "exposure_class": ["corporate"],
            "approach": ["standardised"],
            "drawn_amount": [0.0],
            "nominal_amount": [_NOMINAL],
            "undrawn_amount": [_NOMINAL],
            "risk_type": [risk_type],
            "underlying_risk_type": [underlying],
            "is_revolving": [False],
            "ccf_modelled": [None],
        }
    ).lazy()
    out = CCFCalculator().apply_ccf(frame, config).collect()
    return float(out["ccf"][0])


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2025, 12, 31))


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def test_p1_265_crr_ignores_the_underlying_item(crr_config: CalculationConfig) -> None:
    """Under CRR a full-risk commitment keeps 100% whatever it is a commitment to issue.

    Arrange: a CRR full-risk commitment naming a LOW-risk underlying item.
    Act: apply CCFs.
    Assert: 1.00 — the Art. 111(1)(a) full-risk percentage, unreduced.

    This is the assertion that fails before the fix, at 0.00: the maximum
    possible swing, and the whole exposure value with it.
    """
    assert _ccf(crr_config, "FR", "LR") == pytest.approx(1.0), (
        "P1.265: CRR Art. 111(1) contains no commitment-to-issue lower-of rule — "
        "only the four percentages and the Annex I category assignment. Capping a "
        "CRR full-risk commitment at a low-risk underlying's 0% applies a Basel 3.1 "
        "provision to a regime that does not have it."
    )


def test_p1_265_crr_is_unchanged_without_an_underlying(crr_config: CalculationConfig) -> None:
    """A CRR commitment with no underlying named is unaffected.

    Control: isolates the change to the underlying-bearing path. If this moved,
    the gate would have altered the ordinary CRR CCF ladder rather than just
    the cap.
    """
    assert _ccf(crr_config, "FR", None) == pytest.approx(1.0)
    assert _ccf(crr_config, "MR", None) == pytest.approx(0.5)


def test_p1_265_b31_still_applies_the_lower_of_cap(b31_config: CalculationConfig) -> None:
    """Under Basel 3.1 the cap still bites — the survives-the-change half.

    PS1/26 Art. 111(1)(c) does provide the lower-of rule, so gating it must not
    switch it off where it belongs. Without this, a fix that simply deleted the
    cap would pass every CRR assertion above.
    """
    capped = _ccf(b31_config, "FR", "LR")
    uncapped = _ccf(b31_config, "FR", None)

    assert capped < uncapped, (
        "P1.265: PS1/26 Art. 111(1)(c) caps a commitment at the lower of its own CCF "
        f"and the underlying item's. Got {capped} against an uncapped {uncapped}."
    )


def test_p1_265_b31_cap_never_raises_a_ccf(b31_config: CalculationConfig) -> None:
    """The Basel 3.1 rule is a LOWER-of, so it can only reduce.

    Stated as a property over both orderings rather than a single value: a
    commitment whose own CCF is already the lower of the pair must not be
    lifted to the underlying's. That is the direction the word "lower" fixes,
    and a `max_horizontal` slip would satisfy the previous test while failing
    this one.
    """
    low_commitment_high_underlying = _ccf(b31_config, "LR", "FR")

    assert low_commitment_high_underlying == pytest.approx(_ccf(b31_config, "LR", None)), (
        "P1.265: the cap is a lower-of and must never raise a commitment's CCF "
        "toward a riskier underlying item."
    )
