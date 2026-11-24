"""
Integration tests: a beneficial and a declined guarantor on one exposure, end to end.

Each case runs ``PipelineOrchestrator.run_with_data`` on
``tests/fixtures/multi_guarantor_decline_portfolio.py`` under CRR (2026-06-01) and
Basel 3.1 (2027-06-01) and asserts every leg against a hand calculation. The
facility carries a drawn loan (E = 1,000,000 at CCF 100%) and a synthetic undrawn
leg (nominal 1,000,000), each guaranteed by guarantor A (beneficial) and guarantor
B (declined), as percentages of the leg.

What a decline does (the rule text):

- CRR Art. 193(1): "No exposure in respect of which an institution obtains credit
  risk mitigation shall produce a higher risk-weighted exposure amount or expected
  loss amount than an otherwise identical exposure in respect of which an
  institution has no credit risk mitigation." PS1/26 deletes 193(1) and adds
  193(2A): "an institution may choose to disregard any item of credit protection."
- CRR Art. 235(1) / PS1/26 Art. 235(1)(a): the covered part is sized before any
  conversion factor, "Eg, shall equal min{GA, E}", with "the exposure value of an
  off-balance sheet item ... 100% of its value"; CRR Art. 236(3) uses the same
  CCF=100% basis on the IRB side. Art. 235(1)(b): the uncovered part "En" is
  "the remainder of the exposure" at the risk weight "as if there were no unfunded
  credit protection".

So declining B means E is covered by A alone: A's covered part becomes
min(GA_A, E) on the CCF=100% basis, priced at A's weight after A's conversion
factor, and the rest of E is uncovered at the obligor's weight. A must never cover
more than GA_A, and no part of E may be priced twice.

Hand-calc inputs (pack entries named, values not restated in prose elsewhere):

- Obligor IRB weight r: CRR Art. 153(1) with PD 0.30%, F-IRB senior unsecured LGD
  (CRR 45% / PS1/26 40%), residual maturity M (CRR 4.0y / Basel 3.1 3.0y — the
  fixture's MATURITY) and the CRR 1.06 scaling factor; ``_irb_risk_weight``.
- Conversion factors for ``risk_type="MR"``: ``sa_ccf`` MR 50% in both regimes; the
  F-IRB factor is ``firb_credit_line_ccf`` 75% under CRR and the SA factor under
  Basel 3.1 (``firb_uses_sa_ccf``). An SA-treated guarantor's covered part takes
  the SA factor (``engine/crm/guarantees.py::_apply_cross_approach_ccf``).
- Guarantor A, an institution at CQS 2: 50% (CRR Art. 120 Table 3) / 30%
  (PS1/26 Art. 120 Table 3, ECRA). Guarantor X, a corporate at CQS 3: 100% / 75%
  (Art. 122 Table 6). The SA obligor is an unrated corporate (100%); SA guarantor B
  a CQS 5 corporate (150%), IRB guarantor B carries an internal PD of 20%, so its
  parameter-substituted weight exceeds r.

Pre-fix figures (measured on efa3181) are quoted per case so the size of each
correction is on record. The SA over-covered case is review GT-09 / plan P1.458
scaled by 10,000: loan 916,667 / 816,667 against A-only 750,000 / 650,000, the
undrawn leg CRR 583,333 against an unprotected 500,000.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cache
from math import exp, log, sqrt
from statistics import NormalDist

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.multi_guarantor_decline_portfolio import (
    B31_REPORTING_DATE,
    CRR_REPORTING_DATE,
    DRAWN_AMOUNT,
    LOAN,
    OBLIGOR,
    UNDRAWN,
    UNDRAWN_AMOUNT,
    DeclineScenario,
    Party,
    build_multi_guarantor_decline_bundle,
)

_TOL = 1e-6
#: The IRB hand-calc's inverse normal agrees with the engine's to ~1e-11 relative.
_REL = 1e-9
_OBLIGOR_PD = 0.003
_GA = "MGD-CP-GA"
_GB = "MGD-CP-GB"
_GX = "MGD-CP-GX"


@dataclass(frozen=True)
class _Basis:
    """The per-regime regulatory inputs of the hand calculation."""

    reporting_date: date
    firb_lgd: float
    maturity_years: float
    scaling: float
    sa_ccf: float
    irb_ccf: float
    rw_institution_cqs2: float
    rw_corporate_cqs3: float


BASES: dict[str, _Basis] = {
    "crr": _Basis(CRR_REPORTING_DATE, 0.45, 4.0, 1.06, 0.50, 0.75, 0.50, 1.00),
    "b31": _Basis(B31_REPORTING_DATE, 0.40, 3.0, 1.00, 0.50, 0.50, 0.30, 0.75),
}

_GUARANTOR_A = Party(_GA, "institution", cqs=2)
SCENARIOS: dict[str, DeclineScenario] = {
    # 50% + 100% over-covers E, so the CRM split pro-rates A to 1/3 of E and leaves
    # A with unused protection once B is declined.
    "irb-over": DeclineScenario(
        Party(OBLIGOR, "corporate", pd=_OBLIGOR_PD),
        _GUARANTOR_A,
        Party(_GB, "corporate", pd=0.20),
        0.5,
        1.0,
    ),
    # 30% + 40% under-covers E: A is already at its full GA, nothing to reallocate.
    "irb-under": DeclineScenario(
        Party(OBLIGOR, "corporate", pd=_OBLIGOR_PD),
        _GUARANTOR_A,
        Party(_GB, "corporate", pd=0.20),
        0.3,
        0.4,
    ),
    "sa-over": DeclineScenario(
        Party(OBLIGOR, "corporate"), _GUARANTOR_A, Party(_GB, "corporate", cqs=5), 0.5, 1.0
    ),
    "sa-under": DeclineScenario(
        Party(OBLIGOR, "corporate"), _GUARANTOR_A, Party(_GB, "corporate", cqs=5), 0.3, 0.4
    ),
    # IRB obligor with an external CQS 2 too, so the Basel 3.1 output-floor SA pass
    # (which runs on IRB legs first) DECLINES X — 75% against the obligor's SA 50% —
    # while the IRB pass, against r = 0.877 (PD 1%), finds A and X both beneficial.
    "irb-scope": DeclineScenario(
        Party(OBLIGOR, "corporate", cqs=2, pd=0.01),
        _GUARANTOR_A,
        Party(_GX, "corporate", cqs=3),
        0.5,
        1.0,
    ),
}


@dataclass(frozen=True)
class _Leg:
    """Expected per-leg figures; ``None`` skips a column the case does not pin."""

    ead: float
    rwa: float
    guaranteed: float | None = None
    expected_loss: float | None = None


def _irb_risk_weight(pd: float, basis: _Basis) -> float:
    """Corporate IRB risk weight, CRR Art. 153(1) / PS1/26 Art. 153(1) (large corporate)."""
    norm = NormalDist()
    weight = (1 - exp(-50 * pd)) / (1 - exp(-50))
    correlation = 0.12 * weight + 0.24 * (1 - weight)
    b = (0.11852 - 0.05478 * log(pd)) ** 2
    conditional = norm.cdf(
        (norm.inv_cdf(pd) + sqrt(correlation) * norm.inv_cdf(0.999)) / sqrt(1 - correlation)
    )
    k = (basis.firb_lgd * conditional - pd * basis.firb_lgd) * (
        (1 + (basis.maturity_years - 2.5) * b) / (1 - 1.5 * b)
    )
    return k * 12.5 * basis.scaling


def _ref(parent: str, guarantor: str | None) -> str:
    return f"{parent}__REM" if guarantor is None else f"{parent}__G_{guarantor}"


def _expected_irb_over(basis: _Basis) -> dict[str, _Leg]:
    """A covers min(GA_A, E) = 500,000 of each leg; B's 500,000 is uncovered at r.

    Pre-fix (CRR): loan A leg guaranteed 500,000 on ead 333,333 (RWA 250,000) and B
    keeps 666,667 at r (494,239) — 744,239, above the unprotected 741,358.
    """
    r = _irb_risk_weight(_OBLIGOR_PD, basis)
    el = _OBLIGOR_PD * basis.firb_lgd
    g = basis.rw_institution_cqs2
    a_undrawn = 500_000.0 * basis.sa_ccf
    b_undrawn = 500_000.0 * basis.irb_ccf
    return {
        _ref(LOAN, _GA): _Leg(500_000.0, 500_000.0 * g, 500_000.0, 0.0),
        _ref(LOAN, _GB): _Leg(500_000.0, 500_000.0 * r, None, 500_000.0 * el),
        _ref(LOAN, None): _Leg(0.0, 0.0, 0.0, 0.0),
        _ref(UNDRAWN, _GA): _Leg(a_undrawn, a_undrawn * g, a_undrawn, 0.0),
        _ref(UNDRAWN, _GB): _Leg(b_undrawn, b_undrawn * r, None, b_undrawn * el),
        _ref(UNDRAWN, None): _Leg(0.0, 0.0, 0.0, 0.0),
    }


def _expected_irb_under(basis: _Basis) -> dict[str, _Leg]:
    """No protection is left unused, so nothing moves; A's undrawn cover is post-CCF.

    Pre-fix: undrawn A leg guaranteed 300,000 against its ead 150,000 — the CCF=100%
    protection amount compared with the post-CCF covered exposure — RWA 2x A's.
    """
    r = _irb_risk_weight(_OBLIGOR_PD, basis)
    el = _OBLIGOR_PD * basis.firb_lgd
    g = basis.rw_institution_cqs2
    a_undrawn = 300_000.0 * basis.sa_ccf
    return {
        _ref(LOAN, _GA): _Leg(300_000.0, 300_000.0 * g, 300_000.0, 0.0),
        _ref(LOAN, _GB): _Leg(400_000.0, 400_000.0 * r, None, 400_000.0 * el),
        _ref(LOAN, None): _Leg(300_000.0, 300_000.0 * r, 0.0, 300_000.0 * el),
        _ref(UNDRAWN, _GA): _Leg(a_undrawn, a_undrawn * g, a_undrawn, 0.0),
        _ref(UNDRAWN, _GB): _Leg(
            400_000.0 * basis.irb_ccf,
            400_000.0 * basis.irb_ccf * r,
            None,
            400_000.0 * basis.irb_ccf * el,
        ),
        _ref(UNDRAWN, None): _Leg(
            300_000.0 * basis.irb_ccf,
            300_000.0 * basis.irb_ccf * r,
            0.0,
            300_000.0 * basis.irb_ccf * el,
        ),
    }


def _expected_sa_over(basis: _Basis) -> dict[str, _Leg]:
    """GT-09: A-only — CRR loan 750,000 / undrawn 375,000; Basel 3.1 650,000 / 325,000."""
    g = basis.rw_institution_cqs2
    half_undrawn = 500_000.0 * basis.sa_ccf
    return {
        _ref(LOAN, _GA): _Leg(500_000.0, 500_000.0 * g, 500_000.0),
        _ref(LOAN, _GB): _Leg(500_000.0, 500_000.0),
        _ref(LOAN, None): _Leg(0.0, 0.0, 0.0),
        _ref(UNDRAWN, _GA): _Leg(half_undrawn, half_undrawn * g, half_undrawn),
        _ref(UNDRAWN, _GB): _Leg(half_undrawn, half_undrawn),
        _ref(UNDRAWN, None): _Leg(0.0, 0.0, 0.0),
    }


def _expected_sa_under(basis: _Basis) -> dict[str, _Leg]:
    """Nothing to reallocate. Pre-fix: undrawn A leg guaranteed 300,000 on ead 150,000."""
    g = basis.rw_institution_cqs2
    ccf = basis.sa_ccf
    return {
        _ref(LOAN, _GA): _Leg(300_000.0, 300_000.0 * g, 300_000.0),
        _ref(LOAN, _GB): _Leg(400_000.0, 400_000.0),
        _ref(LOAN, None): _Leg(300_000.0, 300_000.0, 0.0),
        _ref(UNDRAWN, _GA): _Leg(300_000.0 * ccf, 300_000.0 * ccf * g, 300_000.0 * ccf),
        _ref(UNDRAWN, _GB): _Leg(400_000.0 * ccf, 400_000.0 * ccf),
        _ref(UNDRAWN, None): _Leg(300_000.0 * ccf, 300_000.0 * ccf, 0.0),
    }


EXPECTED = {
    "irb-over": _expected_irb_over,
    "irb-under": _expected_irb_under,
    "sa-over": _expected_sa_over,
    "sa-under": _expected_sa_under,
}


def _rwea(frame: pl.DataFrame) -> str:
    """The calculators' RWEA: before the Basel 3.1 output floor, which is a
    portfolio-level allocation (it binds on ``irb-under``) and not CRM."""
    return "rwa_pre_floor" if "rwa_pre_floor" in frame.columns else "rwa_final"


@cache
def _run(scenario: str, regime: str) -> pl.DataFrame:
    """One pipeline run per (scenario, regime); every test reads the same frame."""
    mode = PermissionMode.STANDARDISED if scenario.startswith("sa") else PermissionMode.IRB
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    config = factory(reporting_date=BASES[regime].reporting_date, permission_mode=mode)
    bundle = build_multi_guarantor_decline_bundle(SCENARIOS[scenario])
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


def _actual_legs(frame: pl.DataFrame, expected: dict[str, _Leg]) -> dict[str, _Leg]:
    """Project the run onto the same shape as ``expected`` (columns it pins only)."""
    rows = {row["exposure_reference"]: row for row in frame.iter_rows(named=True)}
    rwea = _rwea(frame)
    return {
        ref: _Leg(
            ead=rows[ref]["ead_final"],
            rwa=rows[ref][rwea],
            guaranteed=None if leg.guaranteed is None else rows[ref]["guaranteed_portion"],
            expected_loss=None if leg.expected_loss is None else rows[ref]["expected_loss"],
        )
        for ref, leg in expected.items()
        if ref in rows
    }


def _approx(legs: dict[str, _Leg]) -> dict[str, object]:
    return {
        ref: (
            pytest.approx(leg.ead, rel=_REL, abs=_TOL),
            pytest.approx(leg.rwa, rel=_REL, abs=_TOL),
            None if leg.guaranteed is None else pytest.approx(leg.guaranteed, rel=_REL, abs=_TOL),
            None
            if leg.expected_loss is None
            else pytest.approx(leg.expected_loss, rel=_REL, abs=_TOL),
        )
        for ref, leg in legs.items()
    }


def _plain(legs: dict[str, _Leg]) -> dict[str, tuple]:
    return {ref: (leg.ead, leg.rwa, leg.guaranteed, leg.expected_loss) for ref, leg in legs.items()}


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("scenario", list(EXPECTED))
def test_every_leg_matches_the_hand_calculation(scenario: str, regime: str) -> None:
    """Per leg: exposure value, RWEA, covered amount and (IRB) expected loss."""
    # Arrange
    expected = EXPECTED[scenario](BASES[regime])

    # Act
    actual = _actual_legs(_run(scenario, regime), expected)

    # Assert
    assert _plain(actual) == _approx(expected)


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_no_leg_is_covered_beyond_its_own_exposure_value(scenario: str, regime: str) -> None:
    """``guaranteed_portion <= ead_final`` on every leg — the covered part is part of E."""
    # Arrange
    frame = _run(scenario, regime)

    # Act
    over = frame.filter(
        pl.col("guaranteed_portion").fill_null(0.0) > pl.col("ead_final") + _TOL
    ).select("exposure_reference", "guaranteed_portion", "ead_final")

    # Assert
    assert over.height == 0, over.to_dicts()


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("scenario", list(EXPECTED))
def test_protection_never_raises_rwea_above_the_unprotected_exposure(
    scenario: str, regime: str
) -> None:
    """CRR Art. 193(1): per parent, RWEA with the guarantees <= RWEA without them."""
    # Arrange
    basis = BASES[regime]
    if scenario.startswith("irb"):
        r = _irb_risk_weight(_OBLIGOR_PD, basis)
        unprotected = {LOAN: DRAWN_AMOUNT * r, UNDRAWN: UNDRAWN_AMOUNT * basis.irb_ccf * r}
    else:
        unprotected = {LOAN: DRAWN_AMOUNT, UNDRAWN: UNDRAWN_AMOUNT * basis.sa_ccf}

    # Act
    frame = _run(scenario, regime)
    protected = dict(
        frame.group_by("parent_exposure_reference").agg(pl.col(_rwea(frame)).sum()).iter_rows()
    )

    # Assert
    breaches = {
        parent: (protected[parent], ceiling)
        for parent, ceiling in unprotected.items()
        if protected[parent] > ceiling * (1 + _REL) + _TOL
    }
    assert breaches == {}


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_reallocation_conserves_the_split_balance_sheet_amounts(scenario: str, regime: str) -> None:
    """Moving cover between legs moves their amounts too: legs still sum to the parent."""
    # Arrange
    frame = _run(scenario, regime)

    # Act
    drawn = frame.filter(pl.col("parent_exposure_reference") == LOAN)["drawn_amount"].sum()
    nominal = frame.filter(pl.col("parent_exposure_reference") == UNDRAWN)["nominal_amount"].sum()

    # Assert
    assert (drawn, nominal) == (
        pytest.approx(DRAWN_AMOUNT, abs=_TOL),
        pytest.approx(UNDRAWN_AMOUNT, abs=_TOL),
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_output_floor_pass_does_not_reallocate_irb_legs(regime: str) -> None:
    """The IRB legs are reallocated on the IRB benefit test alone.

    Under Basel 3.1 the SA calculator runs on IRB legs first, for the output floor's
    SA-equivalent RWEA (``engine/stages/calc.py``). There the obligor's SA weight is
    50% (CQS 2), so X (75%) is declined; on the IRB basis (r = 0.877 at PD 1%) both A
    and X are beneficial and the CRM split's pro-rata allocation stands: A 1/3, X 2/3.
    Pre-fix, the SA pass zeroed X's cover on the IRB legs, so the IRB pass priced X's
    666,667 at r and inflated A to 500,000: 1,177,004 against 900,000.

    The SA-equivalent stays on that allocation too: X's legs at the obligor's SA 50%
    (declined on that basis), A's at 30%.

    CRR has no SA pass over IRB legs, so its twin cannot be reddened; it is kept as
    the control that both regimes allocate the same way.
    """
    # Arrange
    basis = BASES[regime]
    g_a, g_x = basis.rw_institution_cqs2, basis.rw_corporate_cqs3
    a_loan, x_loan = DRAWN_AMOUNT / 3, DRAWN_AMOUNT * 2 / 3
    a_undrawn, x_undrawn = a_loan * basis.sa_ccf, x_loan * basis.sa_ccf
    expected = {
        _ref(LOAN, _GA): pytest.approx(a_loan * g_a, abs=_TOL),
        _ref(LOAN, _GX): pytest.approx(x_loan * g_x, abs=_TOL),
        _ref(UNDRAWN, _GA): pytest.approx(a_undrawn * g_a, abs=_TOL),
        _ref(UNDRAWN, _GX): pytest.approx(x_undrawn * g_x, abs=_TOL),
    }

    # Act
    rows = {
        row["exposure_reference"]: row for row in _run("irb-scope", regime).iter_rows(named=True)
    }

    # Assert
    assert {ref: rows[ref]["rwa_final"] for ref in expected} == expected


def test_output_floor_sa_equivalent_keeps_the_crm_allocation() -> None:
    """Basel 3.1 S-TREA input on the scope case: SA-basis weights on the CRM allocation."""
    # Arrange
    basis = BASES["b31"]
    a_loan, x_loan = DRAWN_AMOUNT / 3, DRAWN_AMOUNT * 2 / 3
    obligor_sa_rw = 0.50  # corporate CQS 2, PS1/26 Art. 122 Table 6
    expected = {
        _ref(LOAN, _GA): pytest.approx(a_loan * basis.rw_institution_cqs2, abs=_TOL),
        _ref(LOAN, _GX): pytest.approx(x_loan * obligor_sa_rw, abs=_TOL),
    }

    # Act
    rows = {
        row["exposure_reference"]: row for row in _run("irb-scope", "b31").iter_rows(named=True)
    }

    # Assert
    assert {ref: rows[ref]["sa_rwa"] for ref in expected} == expected
