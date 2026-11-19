"""
SA-CCR collateral, margin-term and reporting-currency findings: CCR024-CCR026.

Pipeline position:
    ccr_sa_ccr / sft_fccm stages — each stage builds the findings plans from the
    same engine/ccr expressions that price its netting sets and hands them here,
    where they are collected once (:func:`collect_findings`) and decoded into
    row-named errors.

Key responsibilities:
- CCR024 (WARNING) — a ``ccr.ccr_collateral`` item left out of VM and NICA: not
  Art. 197 eligible financial collateral, or pledged against a non-enforceable
  netting set of several trades that Art. 274(1) splits into single-transaction
  netting sets (``engine/ccr/collateral.py``).
- CCR025 (WARNING) — a netting set and its margin agreement state different
  values of the same CSA term; the conservative value is applied
  (``engine/ccr/margin_terms.py``).
- CCR026 (ERROR) — an amount with no spot rate to the reporting currency is used
  unconverted (``engine/ccr/reporting_currency.py``).
- Follow the input gate's sampling contract: up to ``sample_cap`` row-named
  errors per (code, table / term / reason), then one summary carrying the
  truthful count of the rows it omits.

References:
- CCR (CRR) Part Art. 274(1), 275(2), 276(1)(a)/(b), 279b(3); CRR Art. 197,
  Art. 285.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_CCR_COLLATERAL_NOT_RECOGNISED,
    ERROR_CCR_MARGIN_TERMS_CONFLICT,
    ERROR_CCR_NO_REPORTING_CURRENCY_RATE,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

#: A findings plan and the decoder that turns its collected rows into errors.
FindingsPlan = tuple[pl.LazyFrame | None, Callable[[pl.DataFrame], list[CalculationError]]]

_COLLATERAL_REASONS = {
    "not_eligible": (
        "is not Art. 197 eligible financial collateral (a non-financial type, a debt "
        "security below the Art. 197(1)(b)/(d) credit quality, or an equity outside "
        "a main index)",
        "CCR (CRR) Part Art. 276(1)(a)/(b); CRR Art. 197",
    ),
    "not_attributable": (
        "names a netting set that is not legally enforceable and holds several "
        "trades; Art. 274(1) treats each trade as its own netting set and the item "
        "cannot be attributed to one of them",
        "CCR (CRR) Part Art. 274(1); CRR Art. 272(4)",
    ),
}


def collect_findings(plans: Sequence[FindingsPlan]) -> list[CalculationError]:
    """Collect every findings plan in one ``pl.collect_all`` and decode it.

    Args:
        plans: ``(plan, decoder)`` pairs; a None plan is skipped.

    Returns:
        The decoded errors, in plan order.
    """
    live = [(plan, decode) for plan, decode in plans if plan is not None]
    if not live:
        return []
    frames = pl.collect_all([plan for plan, _ in live])
    errors: list[CalculationError] = []
    for frame, (_, decode) in zip(frames, live, strict=True):
        errors.extend(decode(frame))
    return errors


def ccr_collateral_errors(findings: pl.DataFrame, sample_cap: int = 5) -> list[CalculationError]:
    """CCR024 — collateral items left out of the netting set's VM and NICA.

    Args:
        findings: Collected ``engine/ccr/collateral.py::ccr_collateral_findings``.
        sample_cap: Maximum row-named errors per reason.

    Returns:
        The errors, grouped by reason.
    """
    errors: list[CalculationError] = []
    for reason, (treatment, citation) in _COLLATERAL_REASONS.items():
        rows = findings.filter(pl.col("reason") == reason)
        errors.extend(
            CalculationError(
                code=ERROR_CCR_COLLATERAL_NOT_RECOGNISED,
                message=(
                    f"[ccr.ccr_collateral] item '{row['ccr_collateral_reference']}' "
                    f"(netting set '{row['netting_set_id']}', type "
                    f"'{row['collateral_type']}', issuer CQS {row['issuer_cqs']}) "
                    f"{treatment}; it is left out of VM and NICA (no relief if "
                    "received, no exposure if posted)."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                regulatory_reference=citation,
                field_name="collateral_type" if reason == "not_eligible" else "netting_set_id",
                actual_value=_shown(row["collateral_type"]),
            )
            for row in rows.head(sample_cap).iter_rows(named=True)
        )
        errors.extend(
            _summary(
                ERROR_CCR_COLLATERAL_NOT_RECOGNISED,
                "ccr.ccr_collateral",
                reason,
                rows.height,
                sample_cap,
                ErrorSeverity.WARNING,
                citation,
            )
        )
    return errors


def margin_term_conflict_errors(
    findings: pl.DataFrame, sample_cap: int = 5
) -> list[CalculationError]:
    """CCR025 — a netting set's CSA term disagrees with its margin agreement's.

    Args:
        findings: Collected ``engine/ccr/margin_terms.py::margin_term_conflicts``.
        sample_cap: Maximum row-named errors per term.

    Returns:
        The errors, grouped by term.
    """
    citation = "CCR (CRR) Part Art. 275(2); CRR Art. 285"
    errors: list[CalculationError] = []
    for term in findings["term"].unique(maintain_order=True).to_list():
        rows = findings.filter(pl.col("term") == term)
        errors.extend(
            CalculationError(
                code=ERROR_CCR_MARGIN_TERMS_CONFLICT,
                message=(
                    f"[ccr.netting_sets] netting set '{row['netting_set_id']}' states "
                    f"{term} {row['netting_set_value']:,.2f} but margin agreement "
                    f"'{row['margin_agreement_id']}' states {row['agreement_value']:,.2f}; "
                    f"the conservative {row['applied_value']:,.2f} is applied."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                counterparty_reference=_optional_str(row["counterparty_reference"]),
                regulatory_reference=citation,
                field_name=term,
                expected_value=f"{row['agreement_value']}",
                actual_value=f"{row['netting_set_value']}",
            )
            for row in rows.head(sample_cap).iter_rows(named=True)
        )
        errors.extend(
            _summary(
                ERROR_CCR_MARGIN_TERMS_CONFLICT,
                "ccr.netting_sets",
                term,
                rows.height,
                sample_cap,
                ErrorSeverity.WARNING,
                citation,
            )
        )
    return errors


def reporting_currency_errors(
    findings: pl.DataFrame, sample_cap: int = 5
) -> list[CalculationError]:
    """CCR026 — amounts left in a currency with no rate to the reporting currency.

    Args:
        findings: Collected
            ``engine/ccr/reporting_currency.py::reporting_currency_findings``.
        sample_cap: Maximum row-named errors per table.

    Returns:
        The errors, grouped by table.
    """
    citation = "CCR (CRR) Part Art. 279b(3), Art. 275; CRR Art. 223(5)"
    errors: list[CalculationError] = []
    for table in findings["table"].unique(maintain_order=True).to_list():
        rows = findings.filter(pl.col("table") == table)
        errors.extend(
            CalculationError(
                code=ERROR_CCR_NO_REPORTING_CURRENCY_RATE,
                message=(
                    f"[{table}] record '{row['record_id']}' (netting set "
                    f"'{row['netting_set_id']}') is denominated in "
                    f"{_shown(row['currency'])}, which has no fx_rates row to the "
                    "reporting currency; its amounts are used unconverted, so the "
                    "netting set's exposure value is not in the reporting currency."
                ),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.DATA_QUALITY,
                regulatory_reference=citation,
                field_name="currency",
                expected_value="a currency with an fx_rates row to the reporting currency",
                actual_value=_shown(row["currency"]),
            )
            for row in rows.head(sample_cap).iter_rows(named=True)
        )
        errors.extend(
            _summary(
                ERROR_CCR_NO_REPORTING_CURRENCY_RATE,
                table,
                "currency",
                rows.height,
                sample_cap,
                ErrorSeverity.ERROR,
                citation,
            )
        )
    return errors


def _summary(
    code: str,
    table: str,
    field: str,
    height: int,
    sample_cap: int,
    severity: ErrorSeverity,
    citation: str,
) -> list[CalculationError]:
    """One summary error carrying the count of rows beyond ``sample_cap``."""
    omitted = height - min(height, sample_cap)
    if not omitted:
        return []
    return [
        CalculationError(
            code=code,
            message=(
                f"[{table}] '{field}': {omitted} additional record(s) with the same "
                f"finding omitted beyond sample_cap={sample_cap}"
            ),
            severity=severity,
            category=ErrorCategory.DATA_QUALITY,
            regulatory_reference=citation,
            field_name=field,
        )
    ]


def _shown(value: object) -> str:
    return "null" if value is None else f"'{value}'"


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
