"""
Pillar 3 OV1 — CRR IRB-method equity outside the simple risk-weight approach is
disclosed in row 3 (F-IRB), never in row 2 (the standardised approach).

Pipeline position:
    equity_exposures (3 legs) -> PipelineOrchestrator -> EquityCalculator
        -> aggregator exit -> Pillar3Generator (OV1) + COREPGenerator (C 02.00)

The defect this file drives out (P1.343):

``reporting/pillar3/ov1.py`` split the equity approach label between row 2 and
row UK 4a on ONE test — "sealed ``irb_simple``, or not" — so every equity leg that
was not Art. 155(2) simple risk-weighted fell to row 2, including the two IRB
methods that are not simple risk-weighted:

- ``pd_lgd`` — Art. 155(3) PD/LGD equity (Chapter 3 of Title II of Part Three);
- ``irb_fixed_rw`` — an IRB firm's Art. 48(4) 250% leg, which Art. 155(1)
  excludes from paragraphs 2-4 and which COREP Annex II puts in CR EQU IRB
  (C 10.01) row 0110 — IRB equity, never SA.

COREP C 02.00 already reports both under r0420 "Equity IRB" and leaves its SA
total r0050 at 0.00, so the two templates contradicted each other on the same
run — measured on this book before the fix: OV1 row 2 500.00 (IRB simple run)
and 787.809643 (PD/LGD run) against C 02.00 r0050 0.00 on both.

Verbatim from the published instructions
(``docs/assets/crr-pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf``,
pp. 0-1):

- Row 2: "RWEAs and own funds requirements calculated in accordance with the CR
  standardised approach (Chapter 2 of Title II of Part Three CRR and Article 379
  CRR)."
- Row 3: "... calculated in accordance with the CR – foundation Internal Ratings
  Based Approach (Chapter 3 of Title II of Part Three CRR), excluding the RWEAs
  disclosed in row 4 for specialised lending exposures subject to the slotting
  approach and in row UK 4a for equities under the simple risk weighted approach
  ..."
- Row UK 4a: "RWEAs and own funds requirements for equities under the simple risk
  weighted approach in accordance with Article 155(2) CRR."
- Row 5: the same Chapter 3 wording, with the same two carve-outs, for the
  advanced IRB approach.

And CRR COREP Annex II (``crr-annex-ii-reporting-instructins.pdf`` p. 134),
CR EQU IRB 1 row 0110: "Institutions applying the IRB Approach shall report risk
weighted exposure amounts for those equity exposures which attract a fixed risk
weight treatment (without however being explicitly treated in accordance with the
Simple Risk Weight approach or the (temporary or permanent) partial use of the
credit risk Standardised approach). As an example: - the risk weighted exposure
amount of equity positions in financial sector entities treated in accordance with
Article 48(4) CRR ... shall be reported in row 0110."

So both legs must leave row 2 (Chapter 2 only), cannot enter UK 4a (Art. 155(2)
only), and must sit in row 3 or row 5 for rows 3 + 4 + UK 4a + 5 to cover
Chapter 3. Row 3 is the owner-confirmed reading (sign-off 2026-11-24): CRR
Art. 165(2)/(3) PRESCRIBE the equity LGD (65%/90%) and M (five years), so no own
estimate of LGD or conversion factor is ever used — the published F-IRB/A-IRB
discriminator (COREP C 02.00 r0250 "IRB Approaches when neither own estimates of
LGD nor Conversion Factors are used" vs r0310). The OV1 instructions name neither
Art. 155(3) nor Art. 48(4), so the row is an inference, not a quoted instruction.

The book (``tests/integration/test_significant_investment_equity.py``'s, EAD 100
each, institution counterparty BANKX):

    leg         type    exch.  sig. inv.   CRR SA     CRR IRB simple     CRR PD/LGD
    SIG         listed  yes    yes         sa 250     irb_fixed_rw 250   irb_fixed_rw 250
    PLAIN       listed  yes    no          sa 100     irb_simple 290     pd_lgd 287.809643
    SIG_OTHER   other   no     yes         sa 250     irb_fixed_rw 250   irb_fixed_rw 250

    OV1 row     CRR SA   CRR IRB simple   CRR PD/LGD       Basel 3.1 (all sa, 250 each)
    1 / 29      600      790              787.809643       750
    2           600      0   (was 500)    0   (was 787.81) 750
    3           0        500 (was 0)      787.809643 (was 0)  0
    UK 4a       0        290              0                (no such row)

Two legs of the fix on one book (``.claude/LESSONS.md`` B5): on the IRB simple
run row 2 and row 3 MOVE while UK 4a SURVIVES at 290.00 — a fix that zeroed the
equity rows, or dumped every IRB method into UK 4a, would also move row 2 and is
caught by the absolute UK 4a and row 3 pins.

Regimes (``.claude/LESSONS.md`` C7): the two CRR IRB runs each fail on their own
before the fix. The CRR SA run and the Basel 3.1 run are NON-MOVING controls and
cannot be reddened by this change — under Basel 3.1 PS1/26 Art. 155(1)-(4) are
"[Note: Provision left blank]" and Art. 147A(1)(h) sends equity to "the
Standardised Approach", so the pack Feature ``equity_irb_approaches_available``
is off, every leg seals ``sa`` and the UKB OV1 has no UK 4a row. That is a
recorded one-regime gap, kept parametrised as a guard against the CRR re-split
leaking into either control.

References:
- CRR Part 8 Art. 438(d); Art. 48(4); Art. 155(1)-(3); Art. 165(2)/(3)
- UK Pillar 3 Annex II, Template UK OV1, rows 1-5 and UK 4a
- CRR COREP Annex II, C 02.00 r0050 / r0250 / r0310 / r0420; C 10.01 r0110
- PS1/26 Art. 147A(1)(h), Art. 155 (deleted)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import exp, log, sqrt
from statistics import NormalDist

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import EquityApproach, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

_REL = 1e-9
_ABS = 1e-6

_SA = EquityApproach.SA.value
_SIMPLE = EquityApproach.IRB_SIMPLE.value
_PD_LGD = EquityApproach.PD_LGD.value
_FIXED = EquityApproach.IRB_FIXED_RISK_WEIGHT.value

_ROW_SA = "2"
_ROW_FIRB = "3"
_ROW_EQUITY_SIMPLE = "UK4a"

# The of-which block of row 1, from the published instruction (not from ov1.py).
_OF_WHICH: tuple[str, ...] = ("2", "3", "4", "UK4a", "5")

# The C 02.00 rows (published codes) OV1's equity cells must agree with.
_C02_SA_TOTAL = "0050"
_C02_EQUITY_IRB = "0420"


def _crr_equity_pd_lgd_rwa(ead: float) -> float:
    """Hand-derived Art. 155(3) RWEA for the PLAIN leg, independent of the engine.

    Corporate K (Art. 153(1)) at the Art. 165(1)(c) exchange-traded PD floor
    0.40%, the Art. 165(2) LGD 90% and the Art. 165(3) M = 5, times the
    Art. 153(1) 1.06 and the Art. 155(3) 1.5 (no Art. 178 default information):
    RW 1.918731 x 1.5 = 2.878096 -> 287.809643 on EAD 100. EL x 12.5 = 4.5, far
    inside the Art. 155(3) cap of EAD x 12.5.
    """
    pd_, lgd, maturity = 0.004, 0.90, 5.0
    normal = NormalDist()
    weight = (1.0 - exp(-50.0 * pd_)) / (1.0 - exp(-50.0))
    correlation = 0.12 * weight + 0.24 * (1.0 - weight)
    b = (0.11852 - 0.05478 * log(pd_)) ** 2
    k = (
        lgd
        * (
            normal.cdf(
                (normal.inv_cdf(pd_) + sqrt(correlation) * normal.inv_cdf(0.999))
                / sqrt(1.0 - correlation)
            )
            - pd_
        )
        * (1.0 + (maturity - 2.5) * b)
        / (1.0 - 1.5 * b)
    )
    return k * 12.5 * 1.06 * 1.5 * ead


_PLAIN_PD_LGD = _crr_equity_pd_lgd_rwa(100.0)

# run -> (config, framework).
_CONFIGS: dict[str, tuple[CalculationConfig, str]] = {
    "crr_sa": (CalculationConfig.crr(reporting_date=date(2026, 6, 30)), "CRR"),
    "crr_irb_simple": (
        CalculationConfig.crr(reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB),
        "CRR",
    ),
    "crr_pd_lgd": (
        CalculationConfig.crr(
            reporting_date=date(2026, 6, 30),
            permission_mode=PermissionMode.IRB,
            equity_pd_lgd=True,
        ),
        "CRR",
    ),
    "b31": (CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30)), "BASEL_3_1"),
}
_MOVING: tuple[str, ...] = ("crr_irb_simple", "crr_pd_lgd")

# run -> leg -> (sealed equity_method, rwa_final): the population guard.
_POPULATION: dict[str, dict[str, tuple[str, float]]] = {
    "crr_sa": {"SIG": (_SA, 250.0), "PLAIN": (_SA, 100.0), "SIG_OTHER": (_SA, 250.0)},
    "crr_irb_simple": {
        "SIG": (_FIXED, 250.0),
        "PLAIN": (_SIMPLE, 290.0),
        "SIG_OTHER": (_FIXED, 250.0),
    },
    "crr_pd_lgd": {
        "SIG": (_FIXED, 250.0),
        "PLAIN": (_PD_LGD, _PLAIN_PD_LGD),
        "SIG_OTHER": (_FIXED, 250.0),
    },
    "b31": {"SIG": (_SA, 250.0), "PLAIN": (_SA, 250.0), "SIG_OTHER": (_SA, 250.0)},
}

# run -> OV1 row -> column a (None = the row must not exist under this framework).
_EXPECTED: dict[str, dict[str, float | None]] = {
    "crr_sa": {"1": 600.0, _ROW_SA: 600.0, _ROW_FIRB: 0.0, _ROW_EQUITY_SIMPLE: 0.0, "29": 600.0},
    "crr_irb_simple": {
        "1": 790.0,
        _ROW_SA: 0.0,
        _ROW_FIRB: 500.0,
        _ROW_EQUITY_SIMPLE: 290.0,
        "29": 790.0,
    },
    "crr_pd_lgd": {
        "1": _PLAIN_PD_LGD + 500.0,
        _ROW_SA: 0.0,
        _ROW_FIRB: _PLAIN_PD_LGD + 500.0,
        _ROW_EQUITY_SIMPLE: 0.0,
        "29": _PLAIN_PD_LGD + 500.0,
    },
    "b31": {"1": 750.0, _ROW_SA: 750.0, _ROW_FIRB: 0.0, _ROW_EQUITY_SIMPLE: None, "29": 750.0},
}

_CELLS: tuple[tuple[str, str], ...] = tuple(
    (run, ref) for run, rows in _EXPECTED.items() for ref in rows
)


@dataclass(frozen=True)
class _Run:
    """One pipeline run: OV1, C 02.00 and the sealed ledger."""

    ov1: pl.DataFrame
    c02: pl.DataFrame
    ledger: pl.DataFrame

    def has_ov1_row(self, ref: str) -> bool:
        return bool(self.ov1.filter(pl.col("row_ref") == ref).height)

    def ov1_row(self, ref: str) -> dict[str, float | str | None]:
        rows = self.ov1.filter(pl.col("row_ref") == ref)
        assert rows.height == 1, f"expected exactly one OV1 row {ref!r}, got {rows.height}"
        return rows.row(0, named=True)

    def has_c02_row(self, ref: str) -> bool:
        return bool(self.c02.filter(pl.col("row_ref") == ref).height)

    def c02_cell(self, ref: str) -> float:
        rows = self.c02.filter(pl.col("row_ref") == ref)
        assert rows.height == 1, f"expected exactly one C 02.00 row {ref!r}, got {rows.height}"
        value = rows.row(0, named=True)["0010"]
        return 0.0 if value is None else float(value)


@pytest.fixture(scope="module")
def runs() -> dict[str, _Run]:
    """One pipeline run of the 3-leg equity book per configuration."""
    return {name: _run(name) for name in _CONFIGS}


# =============================================================================
# Population guard — the legs this file is about actually exist
# =============================================================================


@pytest.mark.parametrize("run", list(_CONFIGS))
def test_book_seals_the_equity_methods_under_test(run: str, runs: dict[str, _Run]) -> None:
    """Each leg seals the method and RWEA the oracle below is built on.

    Without an ``irb_fixed_rw`` and a ``pd_lgd`` leg carrying RWEA, every row-2 /
    row-3 assertion below passes on an empty population — the vacuous green the
    reverted 2026-08-15 attempt stopped at.

    Arrange: the 3-leg equity book under one configuration.
    Act:     run the pipeline.
    Assert:  the sealed equity_method and rwa_final of every leg.
    """
    # Arrange + Act
    ledger = runs[run].ledger

    # Assert
    got = {
        row["exposure_reference"]: (row["equity_method"], row["rwa_final"])
        for row in ledger.select("exposure_reference", "equity_method", "rwa_final").iter_rows(
            named=True
        )
    }
    assert set(got) == set(_POPULATION[run]), f"[{run}] legs on the ledger: {sorted(got)}"
    for leg, (method, rwa) in _POPULATION[run].items():
        assert got[leg][0] == method, (
            f"[{run}] {leg} must seal equity_method {method!r} for this file to test "
            f"anything; got {got[leg][0]!r}. A changed method needs a new fixture, not "
            "a new number."
        )
        assert got[leg][1] == pytest.approx(rwa, rel=_REL, abs=_ABS), (
            f"[{run}] {leg} rwa_final: expected {rwa:,.6f}, got {got[leg][1]}"
        )


# =============================================================================
# The defect — absolute, both moving runs and both controls
# =============================================================================


@pytest.mark.parametrize(("run", "ref"), _CELLS)
def test_ov1_equity_bearing_rows_report_their_hand_derived_values(
    run: str, ref: str, runs: dict[str, _Run]
) -> None:
    """OV1 rows 1, 2, 3, UK 4a and 29 each equal their hand-derived value.

    Row 2 is Chapter 2 only, so the PD/LGD and Art. 48(4) fixed-RW legs leave it;
    UK 4a is Art. 155(2) only, so they do not enter it; they land in row 3.
    Rows 1 and 29 do not move — this is a disclosure re-split, not a capital
    change.

    Arrange: the 3-leg equity book under one configuration.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  the row's column a (absolute), column b null, column c = 8% of a.
    """
    # Arrange + Act
    run_ = runs[run]
    want = _EXPECTED[run][ref]

    # Assert
    if want is None:
        assert not run_.has_ov1_row(ref), (
            f"[{run}] OV1 row {ref} must NOT exist under this framework — the UKB OV1 "
            "row list has no UK 4a row (PS1/26 Art. 147A removes IRB equity)."
        )
        return
    row = run_.ov1_row(ref)
    assert row["b"] is None, f"[{run}] OV1 row {ref} column b must stay null, got {row['b']}"
    assert row["a"] is not None, (
        f"[{run}] OV1 row {ref} column a is NULL — a populated 0.00 is the claim this "
        "book supports, and null is not the same claim."
    )
    assert row["a"] == pytest.approx(want, rel=_REL, abs=_ABS), (
        f"[{run}] OV1 row {ref} column a: expected {want:,.6f}, got {row['a']:,.6f}. "
        "Row 2 is the CR standardised approach (Chapter 2) only; Art. 155(3) PD/LGD "
        "equity and an IRB firm's Art. 48(4) fixed-RW equity are Chapter 3 IRB equity "
        "outside the simple risk-weight approach, disclosed in row 3."
    )
    assert row["c"] == pytest.approx(want * 0.08, rel=_REL, abs=_ABS), (
        f"[{run}] OV1 row {ref} column c must be 8% of column a: expected "
        f"{want * 0.08:,.6f}, got {row['c']}"
    )


@pytest.mark.parametrize("run", _MOVING)
def test_ov1_uk4a_holds_only_the_simple_risk_weighted_leg(run: str, runs: dict[str, _Run]) -> None:
    """UK 4a equals the RWEA of the legs sealed ``irb_simple`` — no more, no less.

    The cell that must SURVIVE the fix (290.00 on the IRB simple run) and must not
    absorb the PD/LGD or fixed-RW legs (0.00 on the PD/LGD run). Read from the
    ledger by the enum value, so it is a second statement of the population, not
    of ``ov1.py``'s predicate.

    Arrange: a CRR IRB run of the 3-leg book.
    Act:     run the pipeline -> Pillar 3 OV1 + the sealed ledger.
    Assert:  UK 4a column a == sum(rwa_final | equity_method == irb_simple).
    """
    # Arrange + Act
    run_ = runs[run]
    simple = run_.ledger.filter(pl.col("equity_method") == _SIMPLE)["rwa_final"].sum()

    # Assert
    assert run_.ov1_row(_ROW_EQUITY_SIMPLE)["a"] == pytest.approx(simple, rel=_REL, abs=_ABS), (
        f"[{run}] OV1 UK 4a must report exactly the Art. 155(2) simple risk-weighted "
        f"legs' RWEA ({simple:,.6f})."
    )


# =============================================================================
# Conservation and the independent second opinion
# =============================================================================


@pytest.mark.parametrize("run", list(_CONFIGS))
def test_ov1_of_which_rows_partition_credit_risk(run: str, runs: dict[str, _Run]) -> None:
    """Rows 2 + 3 + 4 + UK 4a + 5 == row 1 on every run.

    Green before the fix too (the legs fell to row 2, inside the block), so this
    is a guard against the fix dropping a leg OUT of the block — not evidence for
    the fix itself.

    Arrange: the 3-leg equity book under one configuration.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  the present of-which rows sum to row 1, column a and column c.
    """
    # Arrange + Act
    run_ = runs[run]
    present = [ref for ref in _OF_WHICH if run_.has_ov1_row(ref)]
    parent = run_.ov1_row("1")

    # Assert
    for col in ("a", "c"):
        cells = [run_.ov1_row(ref)[col] for ref in present]
        assert all(cell is not None for cell in cells), f"[{run}] null of-which cell: {cells}"
        got = sum(float(cell) for cell in cells)  # type: ignore[arg-type]
        assert got == pytest.approx(parent[col], rel=_REL, abs=_ABS), (
            f"[{run}] OV1 rows {'+'.join(present)} column {col} sum to {got:,.6f}, but "
            f"row 1 reports {parent[col]:,.6f}."
        )


@pytest.mark.parametrize("run", list(_CONFIGS))
def test_ov1_equity_rows_agree_with_corep_c02(run: str, runs: dict[str, _Run]) -> None:
    """OV1 row 2 == C 02.00 r0050, and OV1 row 3 + UK 4a == C 02.00 r0420.

    C 02.00 r0050 is the SA total and r0420 "Equity IRB" (CR EQU IRB, which holds
    the Art. 155(2)/(3) legs and, by C 10.01 r0110, the Art. 48(4) fixed-RW legs).
    The identities are exact on this book only because it carries no CCR, no
    securitisation and no non-equity leg — the premise is asserted first.

    Arrange: the 3-leg equity book under one configuration.
    Act:     run the pipeline -> Pillar 3 OV1 AND COREP C 02.00, one run.
    Assert:  the two templates disclose the same SA and IRB equity amounts.
    """
    # Arrange + Act
    run_ = runs[run]
    origins = set(run_.ledger["reporting_approach_origin"].to_list())
    risk_types = set(run_.ledger["risk_type"].to_list()) - {None}
    uk4a = run_.ov1_row(_ROW_EQUITY_SIMPLE)["a"] if run_.has_ov1_row(_ROW_EQUITY_SIMPLE) else 0.0

    # Assert — the premise, then the identities.
    assert origins == {"equity"}, f"[{run}] the book must be equity only, got {origins}"
    assert not risk_types, f"[{run}] the book must carry no CCR risk type, got {risk_types}"
    assert run_.ov1_row(_ROW_SA)["a"] == pytest.approx(
        run_.c02_cell(_C02_SA_TOTAL), rel=_REL, abs=_ABS
    ), (
        f"[{run}] OV1 row 2 ({run_.ov1_row(_ROW_SA)['a']}) contradicts C 02.00 r0050 "
        f"({run_.c02_cell(_C02_SA_TOTAL):,.6f}) on the same run."
    )
    # OF 02.00 (Basel 3.1) has no "Equity IRB" row at all — PS1/26 Art. 147A — so
    # the IRB equity it discloses is nil by construction.
    c02_equity_irb = run_.c02_cell(_C02_EQUITY_IRB) if run_.has_c02_row(_C02_EQUITY_IRB) else 0.0
    irb_equity = float(run_.ov1_row(_ROW_FIRB)["a"]) + float(uk4a)  # type: ignore[arg-type]
    assert irb_equity == pytest.approx(c02_equity_irb, rel=_REL, abs=_ABS), (
        f"[{run}] OV1 row 3 + UK 4a ({irb_equity:,.6f}) contradicts C 02.00 r0420 "
        f"'Equity IRB' ({c02_equity_irb:,.6f}) on the same run."
    )


def _run(name: str) -> _Run:
    """Run the 3-leg equity book under one configuration; keep OV1, C 02.00, ledger."""
    config, framework = _CONFIGS[name]
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["BANKX"],
            "entity_type": ["institution"],
            "country_code": ["GB"],
        }
    )
    equity = pl.DataFrame(
        {
            "exposure_reference": ["SIG", "PLAIN", "SIG_OTHER"],
            "counterparty_reference": ["BANKX"] * 3,
            "equity_type": ["listed", "listed", "other"],
            "currency": ["GBP"] * 3,
            "carrying_value": [100.0] * 3,
            "fair_value": [100.0] * 3,
            "is_exchange_traded": [True, True, False],
            "is_significant_investment": [True, False, True],
        }
    )
    result = PipelineOrchestrator().run_with_data(
        make_raw_bundle(counterparties=counterparties, equity_exposures=equity), config
    )
    assert not [e for e in result.errors if "contract violated" in e.message]
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    assert pillar3.ov1 is not None, f"[{name}] Pillar 3 OV1 was not generated"
    assert corep.c_02_00 is not None, f"[{name}] COREP C 02.00 was not generated"
    return _Run(ov1=pillar3.ov1, c02=corep.c_02_00, ledger=result.results.collect())
