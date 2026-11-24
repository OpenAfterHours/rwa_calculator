"""
P1.298: SA011 — a third-country PSE counterparty with no ``is_equivalent_jurisdiction``.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier (engine/classify/audit.py
    ::collect_input_warnings) -> ...

Key responsibilities:
- ``is_equivalent_jurisdiction`` has no default and null means NOT equivalent, so
  a firm that holds third-country PSEs (as obligors, or as guarantors since
  P1.298) and has not populated the column takes CRR Art. 116(5)'s flat 100% on
  them — a 20% Table 2 / 2A weight becomes 100%. The run must say so: one
  aggregate WARNING with the count.
- No alarm where nothing is wrong (LESSONS B9): an all-GB book, and a book whose
  third-country PSEs carry an explicit True or False, raise nothing.

References:
    - CRR Art. 116(5); PS1/26 Art. 116(3A)
    - tests/fixtures/p1_298/p1_298.py — the scenario table
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import (
    ERROR_PSE_EQUIVALENCE_UNASSERTED,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_298.p1_298 import (
    SA_UNASSERTED_PSE_COUNTERPARTIES,
    build_irb_bundle,
    build_sa_bundle,
)
from tests.fixtures.pse_rgla_guarantor.pse_rgla_guarantor import load_pse_rgla_guarantor_bundle


def _config(regime: str, mode: PermissionMode) -> CalculationConfig:
    if regime == "b31":
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30), permission_mode=mode)
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30), permission_mode=mode)


def _sa011(bundle: RawDataBundle, config: CalculationConfig) -> list[CalculationError]:
    errors = PipelineOrchestrator().run_with_data(bundle, config).errors
    return [e for e in errors if e.code == ERROR_PSE_EQUIVALENCE_UNASSERTED]


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_unasserted_pse_counterparties_raise_one_counted_warning(regime: str) -> None:
    """
    Arrange: the SA book — four PSE counterparties outside the UK (or with no
             country) with a null flag: three guarantors and one direct obligor.
    Act:     the full pipeline.
    Assert:  exactly one SA011 WARNING, counting all four.
    """
    found = _sa011(build_sa_bundle(), _config(regime, PermissionMode.STANDARDISED))

    assert len(found) == 1, f"expected one SA011, got {len(found)}"
    warning = found[0]
    assert warning.severity == ErrorSeverity.WARNING
    assert warning.category == ErrorCategory.DATA_QUALITY
    assert warning.field_name == "is_equivalent_jurisdiction"
    assert warning.message.startswith(f"{len(SA_UNASSERTED_PSE_COUNTERPARTIES)} ")


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_all_uk_book_raises_no_warning(regime: str) -> None:
    """
    Arrange: the pse_rgla_guarantor book — every PSE is GB, no flag anywhere.
    Act:     the full pipeline.
    Assert:  no SA011 (a UK PSE never consults the flag).
    """
    found = _sa011(load_pse_rgla_guarantor_bundle(), _config(regime, PermissionMode.IRB))

    assert found == []


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_explicit_flags_raise_no_warning(regime: str) -> None:
    """
    Arrange: the same book with its PSE guarantors moved to the US, one flagged
             False and one True — both explicit assertions.
    Act:     the full pipeline.
    Assert:  no SA011: an explicit False is a determination, not a missing value.
    """
    bundle = build_irb_bundle(cqs2_flag=False, cqs3_flag=True)

    found = _sa011(bundle, _config(regime, PermissionMode.IRB))

    assert found == []


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_one_unasserted_guarantor_is_counted(regime: str) -> None:
    """
    Arrange: as above but the CQS2 guarantor's flag is null.
    Act:     the full pipeline.
    Assert:  one SA011 counting that one guarantor — the alarm discriminates.
    """
    bundle = build_irb_bundle(cqs2_flag=None, cqs3_flag=True)

    found = _sa011(bundle, _config(regime, PermissionMode.IRB))

    assert len(found) == 1
    assert found[0].message.startswith("1 ")
