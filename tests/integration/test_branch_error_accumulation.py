"""
Integration: branch-path calculator warnings reach AggregatedResultBundle.errors.

Migration Phase 2 (docs/plans/target-architecture-migration.md): the pipeline
orchestrator passes an error accumulator into every calculate_branch call (and
the output-floor calculate_unified call), and merges the accumulated warnings
into the result bundle with their ORIGINAL codes — not rewritten to PIPELINE_*.

The trigger here is an equity-entity counterparty whose loan lands in the main
exposure table: the classifier routes it approach="equity", the pipeline's SA
branch picks it up, and the SA calculator emits SA005 (CRR Art. 133 — equity
in main table misses full equity treatment).
"""

from __future__ import annotations

from datetime import date

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_EQUITY_IN_MAIN_TABLE
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator

from .conftest import make_counterparty, make_loan, make_raw_data_bundle


class TestBranchErrorsReachResultBundle:
    """Warnings generated inside calculate_branch surface on the result."""

    def test_sa005_reaches_result_errors_with_original_code(self) -> None:
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(counterparty_reference="CP_EQ", entity_type="equity"),
                make_counterparty(counterparty_reference="CP_CORP", entity_type="corporate"),
            ],
            loans=[
                make_loan(loan_reference="LOAN_EQ", counterparty_reference="CP_EQ"),
                make_loan(loan_reference="LOAN_CORP", counterparty_reference="CP_CORP"),
            ],
        )
        config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

        result = PipelineOrchestrator().run_with_data(bundle, config)

        assert result.results is not None
        sa005 = [e for e in result.errors if e.code == ERROR_EQUITY_IN_MAIN_TABLE]
        assert sa005, (
            "SA005 generated inside the SA branch must reach the result bundle "
            f"(got codes: {sorted({e.code for e in result.errors})})"
        )
        assert sa005[0].severity == ErrorSeverity.WARNING

    def test_clean_portfolio_accumulates_no_branch_warnings(self) -> None:
        """A plain corporate portfolio adds no branch-path warnings."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(counterparty_reference="CP_1")],
            loans=[make_loan(loan_reference="LOAN_1", counterparty_reference="CP_1")],
        )
        config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

        result = PipelineOrchestrator().run_with_data(bundle, config)

        assert ERROR_EQUITY_IN_MAIN_TABLE not in {e.code for e in result.errors}
