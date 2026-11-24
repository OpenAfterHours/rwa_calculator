"""
Acceptance test: the cross-template tie-outs hold on a real end-to-end run.

Runs the full pipeline over the IRB fixture estate (SA + F-IRB + A-IRB +
slotting) for both frameworks, generates the COREP and Pillar 3 template
bundles the same way production does, and asserts
``check_cross_template_consistency`` finds ZERO breaks. This is the ground-truth
gate for the curated ties: if a real run failed a tie we believed valid, the tie
(not the tolerance) is wrong.

One break follows from any binding floor: P3.8 — Pillar 3 OV1 rows 3-5 still
sum ``rwa_final``, which carries the engine's pro-rata floor add-on, while
C 08.01 reports the un-floored own-approach RWEA, so ``irb_rwea_c08_01_vs_ov1``
differs by exactly the engine's shortfall (the module docstring of
``reporting/tieouts.py`` records it). The Basel 3.1 test therefore admits that
one tie, only by exactly the shortfall the run's own ``OutputFloorSummary``
states; when P3.8 lands the amount is zero and the tie must hold. Since P1.367
the floor does NOT bind on this estate at the 2027 multiplier (measured: U-TREA
341,093,331.90 against a threshold of 270,268,958.40 — before P1.367 the subset
formula bound by 1,012,555.79), so the shortfall is zero and that tie must hold
here too; the allowance stays for the estate's binding states.

``total_rwea_c02_vs_ov1`` is NOT admitted. Until P1.367 the engine took the
Basel 3.1 output floor over the modelled subset and re-added the SA book outside
the max, so OV1 row 29 (Σ ``rwa_final``) exceeded the PS1/26 Art. 92(2A) TREA
that C 02.00 states by up to (1 − x) · SA book. Both are now the whole-book max,
and the tie must hold exactly.

The IRB fixture estate carries no equity, so it cannot see the IRB-equity terms
of ``irb_rwea_c08_01_vs_ov1``. The MIXED book below can: the rich reporting book
with ``RP-EQ-LISTED`` made an Art. 48(4) significant investment, under the
default CRR IRB config (one input flag, no non-default config), and again with
``equity_pd_lgd``. Its non-equity IRB legs populate C 08.01, and its
``irb_fixed_rw`` / ``pd_lgd`` legs are IRB equity OUTSIDE UK 4a — OV1 row 3
since P1.343, C 02.00 r0420 always, C 08.01 never. Before the tie added r0420
and UK 4a, that book fired TIE001 by exactly those legs' RWEA (measured:
-2,500,000.00 and -27,628,496.01) on a consistent estate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest
from workbooks.shared.fixture_loader import load_fixtures

from rwa_calc.contracts.bundles import OutputFloorSummary, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import RAW_TABLE_EDGES
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import EquityApproach, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle
from rwa_calc.reporting.tieouts import TIE_OUTS, check_cross_template_consistency
from tests.acceptance.acceptance_helpers import make_irb_bundle
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.reporting_portfolio import EQ_LISTED, build_reporting_bundle

_OV1_IRB_TIE = "irb_rwea_c08_01_vs_ov1"
_TIE_OUTS_BY_NAME = {tie.name: tie for tie in TIE_OUTS}

# The mixed book's runs: name -> (config, framework, the sealed equity methods
# the population guard requires). The CRR configs are the rich book's golden one
# (``test_reporting_golden._crr_config``) and that one with ``equity_pd_lgd``;
# Basel 3.1 is its golden one, a NON-MOVING control: PS1/26 Art. 147A(1)(h)
# sends every equity leg to the SA, so neither equity term exists there and the
# tie is the one it always was (.claude/LESSONS.md C7 — recorded, kept).
_MIXED_RUNS: dict[str, tuple[CalculationConfig, str, frozenset[str]]] = {
    "crr_fixed_rw": (
        CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        ),
        "CRR",
        frozenset({EquityApproach.IRB_FIXED_RISK_WEIGHT.value, EquityApproach.IRB_SIMPLE.value}),
    ),
    "crr_pd_lgd": (
        CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            permission_mode=PermissionMode.IRB,
            equity_pd_lgd=True,
        ),
        "CRR",
        frozenset({EquityApproach.IRB_FIXED_RISK_WEIGHT.value, EquityApproach.PD_LGD.value}),
    ),
    "b31": (
        CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1),
            permission_mode=PermissionMode.IRB,
            enforce_retail_granularity=False,
        ),
        "BASEL_3_1",
        frozenset({EquityApproach.SA.value}),
    ),
}

# The IRB-method equity that is NOT OV1 UK 4a (Art. 155(2)) — anchored on the
# enum, not on ov1.py's tuple (.claude/LESSONS.md B3).
_IRB_EQUITY_OUTSIDE_UK4A: frozenset[str] = frozenset(
    {EquityApproach.PD_LGD.value, EquityApproach.IRB_FIXED_RISK_WEIGHT.value}
)


@dataclass(frozen=True)
class _MixedRun:
    """One run of the mixed book: both template bundles, the summary, the ledger."""

    corep: COREPTemplateBundle
    pillar3: Pillar3TemplateBundle
    summary: OutputFloorSummary | None
    ledger: pl.DataFrame


def _run_and_generate(framework: str):
    """Run the IRB fixture estate and return (corep_bundle, pillar3_bundle)."""
    bundle = make_irb_bundle(load_fixtures(), create_full_irb_model_permissions())
    if framework == "CRR":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1), permission_mode=PermissionMode.IRB
        )
    response = PipelineOrchestrator().run_with_data(bundle, config)
    summary = response.output_floor_summary
    # Thread the run's OutputFloorSummary exactly as production does
    # (api/rest.py get_template_bundles): without it C 02.00 cannot state the
    # Basel 3.1 floor (row 0010 column 0030), so on a run whose floor binds the
    # C 02.00 TREA read the un-floored total while OV1 [29] (Σ rwa_final) carried
    # the add-on — a harness gap, not a template one. The floor binds on this
    # estate since the product-review fixes raised S-TREA (e.g. IV-01 / IV-02).
    corep = COREPGenerator().generate_from_lazyframe(
        response.results,
        framework=framework,
        output_floor_summary=summary,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(
        response.results,
        framework=framework,
        output_floor_summary=summary,
    )
    return corep, pillar3, summary


def _amount(text: str | None) -> float:
    return float((text or "0").replace(",", ""))


@pytest.fixture(scope="module")
def crr_bundles():
    return _run_and_generate("CRR")


@pytest.fixture(scope="module")
def b31_bundles():
    return _run_and_generate("BASEL_3_1")


def test_crr_run_has_no_tieout_findings(crr_bundles):
    corep, pillar3, _summary = crr_bundles
    findings = check_cross_template_consistency(corep, pillar3, "CRR")
    assert findings == [], [str(f) for f in findings]


def test_b31_run_has_no_tieout_findings(b31_bundles):
    """Every tie holds, bar one known Pillar 3 gap by exactly its amount."""
    corep, pillar3, summary = b31_bundles
    findings = check_cross_template_consistency(corep, pillar3, "BASEL_3_1")
    _assert_only_known_b31_floor_gaps(findings, summary)


def test_crr_run_exercises_the_irb_and_sa_ties(crr_bundles):
    """Guard: the real run actually POPULATES both SA and IRB sides, so the
    zero-findings assertion above is not vacuously passing on skipped ties."""
    corep, _pillar3, _summary = crr_bundles
    assert corep.c07_00  # SA sheets present
    assert corep.c08_01  # IRB sheets present
    assert corep.c_02_00 is not None


# ---------------------------------------------------------------------------
# The mixed book: non-equity IRB plus IRB-method equity outside UK 4a (P1.343)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mixed_runs() -> dict[str, _MixedRun]:
    """The mixed book under each of ``_MIXED_RUNS``' configurations."""
    return {name: _run_mixed_book(name) for name in _MIXED_RUNS}


@pytest.mark.parametrize("run", list(_MIXED_RUNS))
def test_mixed_book_seals_irb_equity_outside_uk4a_beside_non_equity_irb(
    run: str, mixed_runs: dict[str, _MixedRun]
) -> None:
    """Population guard: the legs the tie test below depends on exist.

    Without non-equity IRB RWEA on C 08.01 the tie is skipped (its left side is
    None); without an ``irb_fixed_rw`` / ``pd_lgd`` leg carrying RWEA, OV1 row 3
    holds no equity and the equity terms are untested — either way the tie test
    would pass on an empty population.

    Arrange: the rich book with ``RP-EQ-LISTED`` a significant investment.
    Act:     run the pipeline -> COREP + Pillar 3.
    Assert:  the sealed equity methods; C 08.01 sheets with RWEA; on the CRR runs,
             non-zero RWEA on equity outside UK 4a.
    """
    # Arrange + Act
    mixed = mixed_runs[run]
    _config, framework, methods = _MIXED_RUNS[run]
    equity = mixed.ledger.filter(pl.col("reporting_approach_origin") == "equity")
    c08_lhs = _TIE_OUTS_BY_NAME[_OV1_IRB_TIE].lhs(mixed.corep, mixed.pillar3)
    outside_uk4a = equity.filter(pl.col("equity_method").is_in(_IRB_EQUITY_OUTSIDE_UK4A))

    # Assert
    assert set(equity["equity_method"].to_list()) == methods, (
        f"[{run}] sealed equity methods {sorted(set(equity['equity_method'].to_list()))}, "
        f"expected {sorted(methods)} — a changed method needs a new fixture, not a new number."
    )
    assert mixed.corep.c08_01, f"[{run}] no C 08.01 sheet: the IRB tie would be skipped"
    assert c08_lhs is not None and c08_lhs > 0.0, f"[{run}] the tie's C 08.01 side is {c08_lhs}"
    if framework == "CRR":
        assert float(outside_uk4a["rwa_final"].sum()) > 0.0, (
            f"[{run}] no RWEA on PD/LGD or fixed-RW equity — the tie's equity terms are untested"
        )


@pytest.mark.parametrize("run", list(_MIXED_RUNS))
def test_mixed_book_ov1_irb_tie_resolves_and_holds(
    run: str, mixed_runs: dict[str, _MixedRun]
) -> None:
    """``irb_rwea_c08_01_vs_ov1`` resolves on both sides and fires no TIE001.

    C 08.01 never holds equity — Art. 155 / Art. 48(4) IRB equity reports in
    C 10.01 and C 02.00 r0420 "Equity IRB" — while OV1 discloses it in UK 4a
    (simple risk weight) and row 3 (PD/LGD, fixed RW). So the tie reads
    C 08.01 + r0420 against rows 3 + 4 + UK 4a + 5. Stated without both equity
    terms it fires on this consistent book by exactly the row-3 equity: measured
    -2,500,000.00 (``crr_fixed_rw``) and -27,628,496.01 (``crr_pd_lgd``).

    Arrange: the rich book with ``RP-EQ-LISTED`` a significant investment.
    Act:     run the pipeline -> COREP + Pillar 3 -> the curated tie-outs.
    Assert:  both sides of the tie resolve, they agree, and no other tie breaks
             (Basel 3.1: bar the two known floor gaps, each by its own amount).
    """
    # Arrange + Act
    mixed = mixed_runs[run]
    _config, framework, _methods = _MIXED_RUNS[run]
    tie = _TIE_OUTS_BY_NAME[_OV1_IRB_TIE]
    lhs = tie.lhs(mixed.corep, mixed.pillar3)
    rhs = tie.rhs(mixed.corep, mixed.pillar3)
    findings = check_cross_template_consistency(mixed.corep, mixed.pillar3, framework)

    # Assert
    assert lhs is not None and rhs is not None, f"[{run}] the tie was skipped: {lhs} vs {rhs}"
    if framework == "CRR":
        assert findings == [], [str(f) for f in findings]
        return
    _assert_only_known_b31_floor_gaps(findings, mixed.summary)


def _assert_only_known_b31_floor_gaps(
    findings: list[CalculationError], summary: OutputFloorSummary | None
) -> None:
    """No tie breaks on a Basel 3.1 run bar one known Pillar 3 gap, by its amount.

    P3.8: OV1 rows 3-5 sum ``rwa_final``, which carries the floor add-on. It is
    admitted only by exactly the amount the run's ``OutputFloorSummary`` derives.
    """
    known = {
        # P3.8: OV1 rows 3-5 sum rwa_final, which carries the floor add-on.
        _OV1_IRB_TIE: summary.shortfall if summary is not None else 0.0,
    }
    others = [f for f in findings if f.field_name not in known]
    assert others == [], [str(f) for f in others]

    for tie, amount in known.items():
        breaks = [f for f in findings if f.field_name == tie]
        if amount < 1.0:
            assert breaks == [], [str(f) for f in breaks]
            continue
        assert len(breaks) == 1, [str(f) for f in breaks]
        gap = abs(_amount(breaks[0].expected_value) - _amount(breaks[0].actual_value))
        assert gap == pytest.approx(amount, abs=0.01), tie


def _mixed_book() -> RawDataBundle:
    """The rich reporting book with ``RP-EQ-LISTED`` an Art. 48(4) significant investment.

    Re-sealed through ``make_raw_bundle`` so the flipped flag reaches the loader
    edge exactly as a parquet-loaded one would.
    """
    base = build_reporting_bundle()
    frames = {name: getattr(base, name) for name in RAW_TABLE_EDGES}
    frames["equity_exposures"] = base.equity_exposures.with_columns(
        (pl.col("exposure_reference") == EQ_LISTED).alias("is_significant_investment")
    )
    return make_raw_bundle(**frames)


def _run_mixed_book(name: str) -> _MixedRun:
    """Run the mixed book under one configuration, generating both bundles as production does."""
    config, framework, _methods = _MIXED_RUNS[name]
    response = PipelineOrchestrator().run_with_data(_mixed_book(), config)
    summary = response.output_floor_summary
    assert not [e for e in response.errors if "contract violated" in e.message]
    return _MixedRun(
        corep=COREPGenerator().generate_from_lazyframe(
            response.results, framework=framework, output_floor_summary=summary
        ),
        pillar3=Pillar3Generator().generate_from_lazyframe(
            response.results, framework=framework, output_floor_summary=summary
        ),
        summary=summary,
        ledger=response.results.collect(),
    )
