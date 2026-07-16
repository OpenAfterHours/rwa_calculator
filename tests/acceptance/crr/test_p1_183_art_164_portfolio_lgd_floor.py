"""
P1.183: CRR Art. 164(4)/(5) portfolio-level A-IRB retail-RE LGD floor.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> IRBCalculator
        -> Aggregator (new portfolio-level LGD-floor helper) -> AggregatedResultBundle

Key responsibilities:
- Confirm a residential-RE A-IRB book whose exposure-at-default-weighted
  (EW-avg) own-estimate LGD falls below the 10% Art. 164(4) floor raises
  exactly one IRB007 warning naming both the computed EW-avg and the floor.
- Confirm the warning is purely informational: the book's total rwa_final
  is bit-identical whether or not the check exists (Art. 164(4) is a
  monitoring/disclosure requirement here, not a capital add-on).
- Confirm a compliant book stays silent, AND that the Art. 164(4)
  central-government-guarantee exclusion is genuinely exercised (not just
  vacuously true) — a fifth, very-low-LGD, centrally-guaranteed exposure
  would drag the same book below the floor if wrongly included.
- Confirm the whole five-loan portfolio collapses to ONE bucket-level
  warning (not one per breaching exposure, not a duplicate warning per
  book) when all five loans run through a single pipeline call.

Defect under test (pre-fix):
    No portfolio-level LGD-floor check exists at all yet — the aggregator
    helper, the IRB007 error code, and the CRR pack Feature
    ``crr_retail_re_portfolio_lgd_floor`` are all absent (see
    tests/unit/rulebook/test_retail_re_portfolio_lgd_floor_pack_entries.py
    for the pack-level pins). CRR A-IRB also applies no per-exposure LGD
    floor (``airb_lgd_floor`` is a Basel-3.1-only Feature —
    engine/irb/formulas.py::_lgd_floor_expression), so every own-LGD value
    in this fixture reaches the aggregator unclipped, exactly as this
    scenario's hand-calc assumes.

Hand-calculation (CalculationConfig.crr(permission_mode=PermissionMode.IRB),
reporting_date=2026-01-01 — see tests/fixtures/p1_183/p1_183.py for the full
derivation):

    Breach book (LN_E1_P183 + LN_E2_P183):
        E1: ead_final=1,000,000  lgd=0.05 -> lgd x ead =  50,000
        E2: ead_final=3,000,000  lgd=0.08 -> lgd x ead = 240,000
        EW-avg = 290,000 / 4,000,000 = 0.0725 = 7.25% < 10% -> ONE IRB007

    Compliant book (LN_E3_P183 + LN_E4_P183 + LN_E5_P183):
        E3: ead_final=2,000,000  lgd=0.12 -> lgd x ead = 240,000
        E4: ead_final=2,000,000  lgd=0.10 -> lgd x ead = 200,000
        EW-avg (E3+E4 only) = 440,000 / 4,000,000 = 0.11 = 11.00% >= 10%
        E5: ead_final=2,000,000  lgd=0.02, 100% guaranteed by CP_GOV_P183
            (central government, CQS 1, 0% RW) -> EXCLUDED per Art. 164(4)
        If E5 were wrongly included: (440,000+40,000)/6,000,000 = 8.00% < 10%
        -> would (wrongly) warn. Correct exclusion -> book stays at 11.00%,
        no warning — the proof is the ABSENCE of a warning.

    All five together (one residential-RE bucket, E5 still excluded):
        EW-avg = (50,000+240,000+240,000+200,000) / 8,000,000
               = 730,000 / 8,000,000 = 0.09125 = 9.125% < 10% -> ONE IRB007

References:
    - CRR Art. 164(4): portfolio-level minimum EW-avg LGD for A-IRB retail
      exposures secured by residential (10%) / commercial (15%) real estate.
    - CRR Art. 164(4): the residential/commercial-RE floor does not apply to
      exposures guaranteed by central governments (Art. 115(1)/116(4)
      equivalence basis).
    - tests/fixtures/p1_183/p1_183.py: fixture builder, scenario constants,
      and the full hand-calculation this file's expected values are drawn
      from.
    - docs/plans/compliance-audit-crr-111-241-rectification.md (P1.183,
      art164-4-5-portfolio-lgd-floor finding).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_183.p1_183 import (
    LOAN_E1_REF,
    LOAN_E2_REF,
    LOAN_E3_REF,
    LOAN_E4_REF,
    LOAN_E5_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_183"
_REPORTING_DATE = date(2026, 1, 1)

# IRB007 does not exist as a named constant yet — the engine-implementer
# adds it to contracts/errors.py. String literal, not an import, so this
# file fails on assertion values only, never on a not-yet-defined constant.
_IRB007 = "IRB007"

# Pinned pre-fix RWA-neutrality golden — observed from a live pipeline run
# TODAY (uv run pytest, no code changes) over the isolated breach book
# (LN_E1_P183 + LN_E2_P183 only). See
# test_p1_183_breach_book_rwa_is_unchanged_by_the_warning for the per-row
# breakdown. RWA is NOT lgd x ead (that would be under-stating it — the
# A-IRB correlation/maturity-adjustment formula drives the real number);
# this is the observed ``rwa_final`` sum, pinned so the future warning
# helper is proven never to touch it.
_BREACH_BOOK_RWA_PRE_FIX = 301_185.0126657611


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle(loan_refs: tuple[str, ...] | None = None) -> RawDataBundle:
    """
    Build a P1.183 RawDataBundle, optionally filtered to a subset of loans
    (and the matching guarantee row, if its beneficiary loan is included).

    Lets each test isolate its own book (breach / compliant+exclusion-prover
    / all five) from the one shared fixture directory without needing
    per-scenario parquet files. ``loan_refs=None`` includes every loan.
    """
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    guarantees = pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet")
    if loan_refs is not None:
        loans = loans.filter(pl.col("loan_reference").is_in(list(loan_refs)))
        guarantees = guarantees.filter(pl.col("beneficiary_reference").is_in(list(loan_refs)))

    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=guarantees,
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
    )


def _crr_config() -> CalculationConfig:
    """CRR A-IRB config, reporting_date matching the fixture-report's verified run."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )


def _run(loan_refs: tuple[str, ...] | None) -> AggregatedResultBundle:
    """Run the P1.183 fixtures (optionally filtered) through the CRR A-IRB pipeline."""
    bundle = _build_bundle(loan_refs)
    results = PipelineOrchestrator().run_with_data(bundle, _crr_config())
    assert results.irb_results is not None, (
        "IRB results should not be None — check PermissionMode.IRB config"
    )
    return results


def _irb007_errors(errors: list) -> list:
    """Filter a CalculationError list down to IRB007 (portfolio LGD floor) entries."""
    return [e for e in errors if e.code == _IRB007]


# ---------------------------------------------------------------------------
# Module-scoped pipeline runs — one per book
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def breach_results() -> AggregatedResultBundle:
    """CRR A-IRB pipeline results for the breach book alone (LN_E1 + LN_E2)."""
    return _run((LOAN_E1_REF, LOAN_E2_REF))


@pytest.fixture(scope="module")
def compliant_results() -> AggregatedResultBundle:
    """CRR A-IRB pipeline results for the compliant book + exclusion prover (LN_E3/E4/E5)."""
    return _run((LOAN_E3_REF, LOAN_E4_REF, LOAN_E5_REF))


@pytest.fixture(scope="module")
def all_five_results() -> AggregatedResultBundle:
    """CRR A-IRB pipeline results for all five loans in one combined run."""
    return _run(None)


# ---------------------------------------------------------------------------
# P1.183 acceptance tests — CRR
# ---------------------------------------------------------------------------


class TestP1183Art164PortfolioLGDFloorCRR:
    """P1.183: CRR Art. 164(4)/(5) portfolio-level A-IRB retail-RE LGD floor."""

    # -------------------------------------------------------------------------
    # Breach book — DISCRIMINATING: FAILS today (no IRB007 exists).
    # -------------------------------------------------------------------------

    def test_p1_183_breach_book_raises_one_irb007_warning(
        self, breach_results: AggregatedResultBundle
    ) -> None:
        """
        P1.183 DISCRIMINATING: EW-avg LGD 7.25% < 10% floor -> exactly one IRB007.

        Arrange: LN_E1_P183 (EAD 1M, lgd 5%) + LN_E2_P183 (EAD 3M, lgd 8%).
        Act:     CRR A-IRB pipeline over the breach book alone.
        Assert:  exactly one IRB007 WARNING, message names both the computed
                 EW-avg ("7.25%") and the floor ("10%").

        FAILS today: no IRB007 code exists yet, so this count is 0.
        """
        irb007 = _irb007_errors(breach_results.errors)

        assert len(irb007) == 1, (
            f"P1.183 breach book: expected exactly 1 IRB007 warning "
            f"(EW-avg LGD 7.25% < 10% floor), got {len(irb007)}. "
            f"All errors: {[(e.code, e.message) for e in breach_results.errors]}"
        )
        err = irb007[0]
        assert err.severity == ErrorSeverity.WARNING, (
            f"P1.183: IRB007 should be WARNING severity, got {err.severity}"
        )
        assert "7.25%" in err.message, (
            f"P1.183: IRB007 message should name the computed EW-avg LGD "
            f"'7.25%', got: {err.message!r}"
        )
        assert "10%" in err.message, (
            f"P1.183: IRB007 message should name the Art. 164(4) floor '10%', got: {err.message!r}"
        )

    # -------------------------------------------------------------------------
    # Breach book RWA-neutrality — the check must be purely informational.
    # PASSES today (there's no check to move it yet) and MUST still pass after.
    # -------------------------------------------------------------------------

    def test_p1_183_breach_book_rwa_is_unchanged_by_the_warning(
        self, breach_results: AggregatedResultBundle
    ) -> None:
        """
        P1.183: total rwa_final for the breach book must equal the pre-fix
        golden value, with or without the IRB007 warning present.

        Arrange: LN_E1_P183 + LN_E2_P183 (breach book).
        Act:     CRR A-IRB pipeline; sum rwa_final across the book.
        Assert:  total rwa_final == 301,185.0126657611 (observed from a live
                 pipeline run today — see _BREACH_BOOK_RWA_PRE_FIX).

        Art. 164(4) is a monitoring/disclosure requirement here (it produces
        a WARNING, not a capital add-on), so this number must NEVER move —
        this sub-test guards against the future helper accidentally floor-
        adjusting LGD, EAD, or RWA instead of only emitting a warning. Must
        PASS both before and after the fix.
        """
        total_rwa = breach_results.results.collect()["rwa_final"].sum()

        assert total_rwa == pytest.approx(_BREACH_BOOK_RWA_PRE_FIX, rel=1e-9), (
            f"P1.183: breach book total rwa_final should stay at "
            f"{_BREACH_BOOK_RWA_PRE_FIX:,.4f} (the IRB007 warning must be "
            f"purely informational — it must never adjust RWA), "
            f"got {total_rwa:,.4f}"
        )

    # -------------------------------------------------------------------------
    # Compliant book + exclusion prover — PASSES today, must still pass after.
    # -------------------------------------------------------------------------

    def test_p1_183_compliant_book_with_exclusion_prover_raises_zero_irb007(
        self, compliant_results: AggregatedResultBundle
    ) -> None:
        """
        P1.183: compliant book (11.00%) stays silent, AND the Art. 164(4)
        central-government-guarantee exclusion is genuinely exercised.

        Arrange: LN_E3_P183 (EAD 2M, lgd 12%) + LN_E4_P183 (EAD 2M, lgd 10%)
                 -> EW-avg 11.00% >= 10% on their own. Plus LN_E5_P183
                 (EAD 2M, lgd 2%), 100% guaranteed by CP_GOV_P183 (central
                 government, CQS 1, 0% RW).

                 E5 splits into two IRB result rows (see
                 tests/fixtures/p1_183/p1_183.py's "split-row finding"):
                     LN_E5_P183__G_CP_GOV_P183: is_guaranteed=True,
                         guarantor_exposure_class="central_govt_central_bank",
                         ead_final=2,000,000
                     LN_E5_P183__REM: ead_final=0

                 A population predicate that filters on exposure_class alone
                 (missing the guarantor_exposure_class ==
                 "central_govt_central_bank" exclusion) would wrongly include
                 the 2,000,000 __G_ leg and its 2% LGD.
        Act:     CRR A-IRB pipeline over the compliant book + E5.
        Assert:  zero IRB007. If E5's guaranteed leg is wrongly included,
                 EW-avg drops to 8.00% (440,000+40,000)/6,000,000 and a
                 warning would fire — so this passing today (no check exists)
                 AND passing after the fix (correct exclusion) is the actual
                 proof; a naive implementation that includes E5 breaks this.
        """
        irb007 = _irb007_errors(compliant_results.errors)

        assert len(irb007) == 0, (
            f"P1.183: compliant book (E3+E4 EW-avg 11.00%, E5 excluded per "
            f"Art. 164(4) central-government guarantee) should raise zero "
            f"IRB007 warnings, got {len(irb007)}. If E5's guaranteed leg was "
            f"wrongly included, EW-avg would be 8.00% (<10%) instead. "
            f"All errors: {[(e.code, e.message) for e in compliant_results.errors]}"
        )

    # -------------------------------------------------------------------------
    # All five together — DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_183_all_five_loans_together_raise_exactly_one_irb007(
        self, all_five_results: AggregatedResultBundle
    ) -> None:
        """
        P1.183 DISCRIMINATING: the whole portfolio is ONE residential-RE
        bucket, not one warning per book and not one per breaching exposure.

        Arrange: all five P1.183 loans in a single pipeline run.
        Act:     CRR A-IRB pipeline.
        Assert:  exactly one IRB007 (not two, not four — one per bucket).

        Derivation — E5 excluded (central-government guarantee, Art. 164(4)):
            EW-avg = (E1 50,000 + E2 240,000 + E3 240,000 + E4 200,000)
                     / (1,000,000+3,000,000+2,000,000+2,000,000)
                   = 730,000 / 8,000,000 = 0.09125 = 9.125% < 10% -> ONE warning

        The message-percentage assertion is kept loose ("9.1") to tolerate
        rounding/formatting choices (e.g. "9.13%" vs "9.12%" vs "9.1%") —
        the count (exactly one) and the floor string are the precise pins.

        FAILS today: no IRB007 code exists yet, so this count is 0.
        """
        irb007 = _irb007_errors(all_five_results.errors)

        assert len(irb007) == 1, (
            f"P1.183: all five loans together should raise exactly 1 IRB007 "
            f"(one residential-RE bucket, EW-avg 9.125% < 10%, E1-E4 only — "
            f"E5 excluded), got {len(irb007)}. "
            f"All errors: {[(e.code, e.message) for e in all_five_results.errors]}"
        )
        err = irb007[0]
        assert "9.1" in err.message, (
            f"P1.183: IRB007 message should name the computed EW-avg LGD "
            f"(~9.1%, loosely matched for rounding), got: {err.message!r}"
        )
        assert "10%" in err.message, (
            f"P1.183: IRB007 message should name the Art. 164(4) floor '10%', got: {err.message!r}"
        )
