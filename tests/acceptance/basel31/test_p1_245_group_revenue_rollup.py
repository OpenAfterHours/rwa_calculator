"""
P1.245 acceptance twins — Art. 147(4C)(b)(ii) group revenue roll-up end-to-end.

End-to-end (RawDataBundle -> PipelineOrchestrator) demonstration that the
financial/large-corporates F-IRB-only subclass (Art. 147A(1)(e)) is assigned on
the HIGHEST level of consolidation: the hierarchy stage resolves each
subsidiary's ultimate parent from ``org_mappings`` and the classifier rolls
group revenue up that chain before the large-corp test.

    SUB_LARGE  (own 50m) under PARENT_BIG (500m)   -> B31 F-IRB / CRR A-IRB
    SUB_NULL   (own null) under PARENT_BIG (500m)  -> B31 F-IRB / CRR A-IRB
    SUB_SMALL  (own 50m) under PARENT_SMALL (50m)  -> B31 A-IRB / CRR A-IRB
    STANDALONE (own 500m, no parent)               -> B31 F-IRB / CRR A-IRB

Under CRR the subclass does not exist, so all four route to A-IRB — the control
that proves the branch is B31-scoped. The roll-up flip raises RWA (the modelled
own LGD 35% is replaced by the F-IRB senior-corporate supervisory LGD 40%).

References:
- PRA PS1/26 Art. 147(4C)(b)(ii) / Art. 147A(1)(e); P1.245.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_245.p1_245 import (
    LOAN_STANDALONE,
    LOAN_SUB_LARGE,
    LOAN_SUB_NULL,
    LOAN_SUB_SMALL,
    build_p1_245_raw_bundle,
)

_CRR_DATE = date(2026, 12, 31)
_B31_DATE = date(2027, 6, 30)

_FIRB = ApproachType.FIRB.value
_AIRB = ApproachType.AIRB.value


def _run(config: CalculationConfig):
    return PipelineOrchestrator().run_with_data(build_p1_245_raw_bundle(), config)


@pytest.fixture(scope="module")
def crr_result():
    return _run(CalculationConfig.crr(reporting_date=_CRR_DATE, permission_mode=PermissionMode.IRB))


@pytest.fixture(scope="module")
def b31_result():
    return _run(
        CalculationConfig.basel_3_1(reporting_date=_B31_DATE, permission_mode=PermissionMode.IRB)
    )


def _find(result, loan_ref: str) -> tuple[str, dict]:
    """Return (result_set_name, row_dict) for the loan across SA / IRB / slotting."""
    for name, lf in (
        ("sa", result.sa_results),
        ("irb", result.irb_results),
        ("slotting", result.slotting_results),
    ):
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        if len(df) > 0:
            return name, df.to_dicts()[0]
    msg = f"exposure {loan_ref!r} not found in any result set"
    raise AssertionError(msg)


def _approach(result, loan_ref: str) -> str:
    result_set, row = _find(result, loan_ref)
    assert result_set == "irb", f"{loan_ref} expected in IRB results, was {result_set}"
    return row["approach_applied"]


# =============================================================================
# Basel 3.1 twin — the group roll-up assigns the F-IRB-only subclass
# =============================================================================


class TestB31GroupRollUpEndToEnd:
    def test_small_sub_under_large_group_is_firb(self, b31_result) -> None:
        assert _approach(b31_result, LOAN_SUB_LARGE) == _FIRB

    def test_null_own_sub_under_large_group_is_firb(self, b31_result) -> None:
        assert _approach(b31_result, LOAN_SUB_NULL) == _FIRB

    def test_small_sub_under_small_group_is_airb(self, b31_result) -> None:
        assert _approach(b31_result, LOAN_SUB_SMALL) == _AIRB

    def test_standalone_large_is_firb(self, b31_result) -> None:
        assert _approach(b31_result, LOAN_STANDALONE) == _FIRB

    def test_roll_up_flip_raises_rwa_above_airb_peer(self, b31_result) -> None:
        """The F-IRB flip (supervisory LGD 40%) exceeds the A-IRB peer (own LGD 35%).

        SUB_LARGE and SUB_SMALL share PD, EAD and own LGD; only SUB_LARGE flips to
        F-IRB, whose higher supervisory LGD lifts RWA above its A-IRB peer.
        """
        _, flipped = _find(b31_result, LOAN_SUB_LARGE)
        _, airb_peer = _find(b31_result, LOAN_SUB_SMALL)
        assert flipped["rwa"] > airb_peer["rwa"]


# =============================================================================
# CRR control — no subclass, so every corporate keeps A-IRB
# =============================================================================


class TestCRRHasNoSubclassEndToEnd:
    def test_small_sub_under_large_group_is_airb_under_crr(self, crr_result) -> None:
        assert _approach(crr_result, LOAN_SUB_LARGE) == _AIRB

    def test_null_own_sub_under_large_group_is_airb_under_crr(self, crr_result) -> None:
        assert _approach(crr_result, LOAN_SUB_NULL) == _AIRB

    def test_standalone_large_is_airb_under_crr(self, crr_result) -> None:
        assert _approach(crr_result, LOAN_STANDALONE) == _AIRB
