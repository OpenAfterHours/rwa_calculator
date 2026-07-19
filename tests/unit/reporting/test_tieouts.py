"""
Unit tests for the cross-template consistency (tie-out) checker.

Exercises ``check_cross_template_consistency`` over synthetic COREP / Pillar 3
bundles: a consistent estate produces no findings, a seeded inconsistency is
caught with the right code/field, absent templates are skipped, and the
tolerance behaves at the boundary. Also guards the curated registries so a
future maintainer cannot silently equate a recorded non-comparable pair.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle
from rwa_calc.reporting.tieouts import (
    ERROR_CROSS_TEMPLATE_INCONSISTENCY,
    NON_COMPARABLE_PAIRS,
    TIE_OUTS,
    check_cross_template_consistency,
)

# A self-consistent set of aggregates the five curated ties all foot against:
#   SA (C 07.00)  = 100   equity (C 02.00 0420) = 10   IRB (C 08.01) = 200
#   C 02.00 0060 (SA incl. equity) = 110   0220 (IRB) = 200
#   C 02.00 0050 (credit risk) = 0010 (total) = OV1 29 = 310
_SA_RWEA = 100.0
_EQUITY_RWEA = 10.0
_IRB_RWEA = 200.0
_CREDIT_RISK = _SA_RWEA + _EQUITY_RWEA + _IRB_RWEA  # 310


def _c02(cells: dict[str, float]) -> pl.DataFrame:
    """Minimal C 02.00 frame: one value column (0010) keyed by row_ref."""
    rows = [{"row_ref": ref, "row_name": ref, "0010": value} for ref, value in cells.items()]
    return pl.DataFrame(
        rows, schema={"row_ref": pl.String, "row_name": pl.String, "0010": pl.Float64}
    )


def _single_sheet(col_ref: str, value: float) -> pl.DataFrame:
    """A per-class sheet carrying one total-row (0010) value under ``col_ref``."""
    return pl.DataFrame(
        [{"row_ref": "0010", "row_name": "Total", col_ref: value}],
        schema={"row_ref": pl.String, "row_name": pl.String, col_ref: pl.Float64},
    )


def _ov1(rows: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"row_ref": ref, "row_name": ref, "a": value} for ref, value in rows.items()],
        schema={"row_ref": pl.String, "row_name": pl.String, "a": pl.Float64},
    )


def _consistent_bundles(
    *,
    total: float = _CREDIT_RISK,
    sa: float = _SA_RWEA,
    equity: float = _EQUITY_RWEA,
    irb: float = _IRB_RWEA,
    framework: str = "CRR",
) -> tuple[COREPTemplateBundle, Pillar3TemplateBundle]:
    """Build a COREP + Pillar 3 bundle pair whose five ties foot by default."""
    corep = COREPTemplateBundle(
        c07_00={"corporate": _single_sheet("0220", sa)},
        c08_01={"corporate": _single_sheet("0260", irb)},
        c08_02={},
        c_02_00=_c02(
            {
                "0010": total,
                "0050": total,
                "0060": sa + equity,
                "0220": irb,
                "0420": equity,
            }
        ),
        framework=framework,
    )
    pillar3 = Pillar3TemplateBundle(
        ov1=_ov1({"29": total, "3": irb, "4": 0.0, "5": 0.0}),
        framework=framework,
    )
    return corep, pillar3


def test_consistent_bundles_produce_no_findings():
    # Arrange
    corep, pillar3 = _consistent_bundles()

    # Act
    findings = check_cross_template_consistency(corep, pillar3, "CRR")

    # Assert
    assert findings == []


def test_seeded_total_inconsistency_is_caught():
    # Arrange: perturb the C 02.00 total so it no longer equals OV1 row 29.
    corep, pillar3 = _consistent_bundles()
    broken_c02 = corep.c_02_00.with_columns(
        pl.when(pl.col("row_ref") == "0010")
        .then(pl.lit(_CREDIT_RISK + 5_000.0))
        .otherwise(pl.col("0010"))
        .alias("0010")
    )
    corep_broken = COREPTemplateBundle(
        c07_00=corep.c07_00,
        c08_01=corep.c08_01,
        c08_02=corep.c08_02,
        c_02_00=broken_c02,
        framework="CRR",
    )

    # Act
    findings = check_cross_template_consistency(corep_broken, pillar3, "CRR")

    # Assert
    names = {f.field_name for f in findings}
    assert "total_rwea_c02_vs_ov1" in names
    finding = next(f for f in findings if f.field_name == "total_rwea_c02_vs_ov1")
    assert finding.code == ERROR_CROSS_TEMPLATE_INCONSISTENCY
    assert finding.severity is ErrorSeverity.ERROR
    assert finding.category is ErrorCategory.BUSINESS_RULE


def test_seeded_irb_inconsistency_is_caught():
    # Arrange: break only the IRB sheet aggregate — both IRB ties should fire.
    corep, pillar3 = _consistent_bundles()
    corep_broken = COREPTemplateBundle(
        c07_00=corep.c07_00,
        c08_01={"corporate": _single_sheet("0260", _IRB_RWEA + 1_000.0)},
        c08_02=corep.c08_02,
        c_02_00=corep.c_02_00,
        framework="CRR",
    )

    # Act
    findings = check_cross_template_consistency(corep_broken, pillar3, "CRR")

    # Assert
    names = {f.field_name for f in findings}
    assert names == {"irb_rwea_c08_01_vs_c02", "irb_rwea_c08_01_vs_ov1"}


def test_missing_templates_are_skipped_without_error():
    # Arrange: no C 02.00, no OV1, empty C 08.01 dict — every tie loses a side.
    corep = COREPTemplateBundle(
        c07_00={"corporate": _single_sheet("0220", _SA_RWEA)},
        c08_01={},
        c08_02={},
        c_02_00=None,
        framework="CRR",
    )
    pillar3 = Pillar3TemplateBundle(ov1=None, framework="CRR")

    # Act
    findings = check_cross_template_consistency(corep, pillar3, "CRR")

    # Assert
    assert findings == []


def _total_tie_fires(corep, ov1_df) -> bool:
    """True iff the total_rwea_c02_vs_ov1 tie is among the findings."""
    findings = check_cross_template_consistency(
        corep, Pillar3TemplateBundle(ov1=ov1_df, framework="CRR"), "CRR"
    )
    return any(f.field_name == "total_rwea_c02_vs_ov1" for f in findings)


def test_absolute_tolerance_floor_governs_at_small_magnitudes():
    # At the small default magnitude (_CREDIT_RISK ~ 3e2) the relative term
    # rtol*max ~ 3e-7 sits BELOW atol=1e-6, so the absolute floor governs: a
    # diff under atol passes, a diff comfortably over it fails.
    corep_ok, _ = _consistent_bundles()
    within = _ov1({"29": _CREDIT_RISK + 5e-7, "3": _IRB_RWEA, "4": 0.0, "5": 0.0})
    outside = _ov1({"29": _CREDIT_RISK + 5e-6, "3": _IRB_RWEA, "4": 0.0, "5": 0.0})

    assert not _total_tie_fires(corep_ok, within)  # 5e-7 < atol 1e-6
    assert _total_tie_fires(corep_ok, outside)  # 5e-6 > atol + rtol*max


def test_relative_tolerance_dominates_at_large_magnitudes():
    # At 1e12 the relative term rtol*max ~ 1e3 dwarfs atol (1e-6), so rtol alone
    # decides: a diff of 5e2 (far above atol, below rtol*max) PASSES and a diff
    # of 5e3 (above rtol*max) FAILS — isolating the relative tolerance.
    big = 1e12
    corep_ok, _ = _consistent_bundles(total=big, sa=big * 0.4, equity=0.0, irb=big * 0.6)
    within = _ov1({"29": big + 5e2, "3": big * 0.6, "4": 0.0, "5": 0.0})
    outside = _ov1({"29": big + 5e3, "3": big * 0.6, "4": 0.0, "5": 0.0})

    assert not _total_tie_fires(corep_ok, within)  # 5e2 < rtol*max ~ 1e3
    assert _total_tie_fires(corep_ok, outside)  # 5e3 > rtol*max ~ 1e3


def test_framework_gating_skips_inapplicable_ties():
    # Arrange: a framework no curated tie targets — nothing runs, nothing breaks.
    corep, pillar3 = _consistent_bundles()

    # Act
    findings = check_cross_template_consistency(corep, pillar3, "SOME_OTHER_REGIME")

    # Assert
    assert findings == []


@pytest.mark.parametrize(
    ("expected_pair"),
    [
        ("UK CR6", "C 08.01"),
        ("UK CR7", "C 08.01"),
        ("UKB CR9", "C 08.05"),
        ("C 08.07", "C 08.01"),
        ("C 09.01", "C 07.00"),
        ("UK CR4", "C 07.00"),
    ],
)
def test_non_comparable_pairs_are_recorded(expected_pair):
    recorded = {ncp.pair for ncp in NON_COMPARABLE_PAIRS}
    assert expected_pair in recorded
    ncp = next(n for n in NON_COMPARABLE_PAIRS if n.pair == expected_pair)
    assert ncp.reason  # non-empty rationale
    assert ncp.regulatory_reference


def test_no_tie_reconciles_a_non_comparable_pair():
    """Guard: the curated ties never equate a recorded non-comparable pair."""
    non_comparable = {frozenset(ncp.pair) for ncp in NON_COMPARABLE_PAIRS}
    for tie in TIE_OUTS:
        if len(tie.templates) < 2:
            continue
        tie_pair = frozenset(tie.templates)
        assert tie_pair not in non_comparable, (
            f"tie {tie.name!r} reconciles a recorded non-comparable pair {tie.templates}"
        )
