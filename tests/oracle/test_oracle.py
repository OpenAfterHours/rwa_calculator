"""
Oracle test suite.

Validates engine outputs against independent hand-calculations whose arithmetic
is documented in ORACLE_DERIVATIONS.md and reproduced programmatically by
derive.py (stdlib-only). The point of this suite is to break the self-referential
loop in tests/expected_outputs/{crr,basel31}/, where expected values are recorded
engine outputs and therefore cannot detect a wrong implementation -- only a
*regression* relative to current behaviour.

Lock mechanism: expected_values.json embeds a SHA-256 hash of
ORACLE_DERIVATIONS.md (with line endings normalised to LF). The first test below
asserts that hash is current. If the doc changes without a corresponding
re-derivation, that test fails loudly with instructions on how to recover -- so
it is impossible to silently re-pin oracle values to engine output.

Tolerance: relative error <= 1e-6 against the hand-derived value. This is
significantly tighter than the 1% tolerance used by the regression-style
acceptance tests, because the oracle is testing analytical correctness, not
data-quality robustness.

Pipeline position tested: each oracle calls the relevant calculator's
`calculate_branch` directly via tests/fixtures/single_exposure.py. This deliberately
bypasses hierarchy / classifier / CRM stages so the oracle exercises only the
regulatory math. Pipeline-integration concerns are tested elsewhere.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from tests.fixtures.single_exposure import (
    calculate_single_irb_exposure,
    calculate_single_sa_exposure,
)

HERE = Path(__file__).parent
DOC_PATH = HERE / "ORACLE_DERIVATIONS.md"
JSON_PATH = HERE / "expected_values.json"


# =============================================================================
# Oracle data + lock
# =============================================================================


@pytest.fixture(scope="module")
def oracle_payload() -> dict[str, Any]:
    return json.loads(JSON_PATH.read_text())


@pytest.fixture(scope="module")
def oracles_by_id(oracle_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {o["exposure_id"]: o for o in oracle_payload["oracles"]}


def _normalised_doc_hash() -> str:
    raw = DOC_PATH.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def test_derivations_doc_hash_matches_lock(oracle_payload: dict[str, Any]) -> None:
    """ORACLE_DERIVATIONS.md and expected_values.json may not drift apart.

    If this fails, ORACLE_DERIVATIONS.md has been edited since
    expected_values.json was last regenerated. To recover:

      1. Confirm the new derivations are correct.
      2. Update derive.py to match (constants, formulas).
      3. Run: uv run python tests/oracle/derive.py
      4. Re-run this test suite.

    Do NOT hand-edit expected_values.json to silence this failure -- that
    defeats the purpose of the oracle.
    """
    actual = _normalised_doc_hash()
    expected = oracle_payload["derivations_doc_hash"]
    assert actual == expected, (
        f"\nORACLE_DERIVATIONS.md hash drift detected.\n"
        f"  doc (actual):  {actual}\n"
        f"  json (locked): {expected}\n"
        f"Re-run: uv run python tests/oracle/derive.py"
    )


# =============================================================================
# Configurations
# =============================================================================


@pytest.fixture(scope="module")
def crr_sa_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture(scope="module")
def crr_irb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# Assertion helper
# =============================================================================


def _assert_oracle_match(
    actual_rwa: float,
    actual_rw: float | None,
    oracle: dict[str, Any],
    tol_rel: float,
) -> None:
    expected_rwa = float(oracle["expected"]["rwa"])
    expected_rw = float(oracle["expected"]["risk_weight"])
    oid = oracle["exposure_id"]
    reg = oracle["regulation"]

    if expected_rwa == 0:
        assert actual_rwa == 0, f"{oid}: expected RWA 0, got {actual_rwa}"
    else:
        rel = abs(actual_rwa - expected_rwa) / abs(expected_rwa)
        assert rel <= tol_rel, (
            f"\n{oid}: RWA mismatch beyond {tol_rel:.0e} relative tolerance.\n"
            f"  expected: {expected_rwa:,.10f}  (per {reg})\n"
            f"  actual:   {actual_rwa:,.10f}\n"
            f"  rel err:  {rel:.3e}"
        )

    if actual_rw is not None and expected_rw != 0:
        rw_rel = abs(actual_rw - expected_rw) / abs(expected_rw)
        assert rw_rel <= tol_rel, (
            f"\n{oid}: risk-weight mismatch beyond {tol_rel:.0e} relative tolerance.\n"
            f"  expected RW: {expected_rw:.10f}  (per {reg})\n"
            f"  actual RW:   {actual_rw:.10f}\n"
            f"  rel err:     {rw_rel:.3e}"
        )


# =============================================================================
# Oracles
# =============================================================================


def test_orc_001_sa_corporate_unrated(
    oracles_by_id: dict[str, dict[str, Any]],
    oracle_payload: dict[str, Any],
    crr_sa_config: CalculationConfig,
) -> None:
    """ORC-001: SA unrated corporate -> 100% RW (CRR Art. 122(2))."""
    oracle = oracles_by_id["ORC-001"]
    sa = SACalculator()
    result = calculate_single_sa_exposure(
        sa,
        ead=Decimal(str(oracle["inputs"]["ead"])),
        exposure_class="CORPORATE",
        config=crr_sa_config,
        cqs=oracle["inputs"]["cqs"],
    )
    _assert_oracle_match(
        actual_rwa=float(result["rwa"]),
        actual_rw=float(result.get("risk_weight", 0.0)),
        oracle=oracle,
        tol_rel=oracle_payload["tolerance_relative"],
    )


def test_orc_002_sa_sovereign_cqs2(
    oracles_by_id: dict[str, dict[str, Any]],
    oracle_payload: dict[str, Any],
    crr_sa_config: CalculationConfig,
) -> None:
    """ORC-002: SA CQS-2 sovereign (foreign ccy) -> 20% RW (CRR Art. 114(2) Table 1).

    Country US + currency USD avoids the Art. 114(3) UK domestic 0% override
    so this oracle exercises the Table 1 ECAI lookup cleanly.
    """
    oracle = oracles_by_id["ORC-002"]
    sa = SACalculator()
    result = calculate_single_sa_exposure(
        sa,
        ead=Decimal(str(oracle["inputs"]["ead"])),
        exposure_class=oracle["exposure_class"],
        config=crr_sa_config,
        cqs=oracle["inputs"]["cqs"],
        country_code=oracle["inputs"]["country_code"],
        currency=oracle["inputs"]["currency"],
    )
    _assert_oracle_match(
        actual_rwa=float(result["rwa"]),
        actual_rw=float(result.get("risk_weight", 0.0)),
        oracle=oracle,
        tol_rel=oracle_payload["tolerance_relative"],
    )


def test_orc_003_firb_corporate(
    oracles_by_id: dict[str, dict[str, Any]],
    oracle_payload: dict[str, Any],
    crr_irb_config: CalculationConfig,
) -> None:
    """ORC-003: F-IRB corporate, full Art. 153(1) risk-weight formula.

    Tightest oracle in the suite -- exercises the inverse normal, correlation,
    and maturity-adjustment compositions. A bug in any of those would surface
    here even when the SA oracles still pass.
    """
    oracle = oracles_by_id["ORC-003"]
    irb = IRBCalculator()
    result = calculate_single_irb_exposure(
        irb,
        ead=Decimal(str(oracle["inputs"]["ead"])),
        pd=Decimal(str(oracle["inputs"]["pd"])),
        lgd=Decimal(str(oracle["inputs"]["lgd"])),
        maturity=Decimal(str(oracle["inputs"]["maturity"])),
        exposure_class="CORPORATE",
        config=crr_irb_config,
    )
    rwa_field = result.get("rwa_post_factor", result.get("rwa"))
    rw_field = result.get("risk_weight")
    _assert_oracle_match(
        actual_rwa=float(rwa_field) if rwa_field is not None else 0.0,
        actual_rw=float(rw_field) if rw_field is not None else None,
        oracle=oracle,
        tol_rel=oracle_payload["tolerance_relative"],
    )
