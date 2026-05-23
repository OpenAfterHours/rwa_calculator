"""
Contract / acceptance tests for SA-CCR EAD calculation (P8.17).

Pins the expected behaviour of ``compute_ead`` from
``rwa_calc.engine.ccr.sa_ccr`` against the formula:

    EAD = alpha * (RC + PFE)    [CRR Art. 274(2)]

with default α = 1.4 and an override path via CCRConfig.

Three cases from the P8.17 scenario-architect proposal:

- Case A: default α = 1.4, single netting set — RC = 80, PFE = 786_938.68
- Case B: α override to 1.0 via CCRConfig on the same inputs
- Case C: three-row vectorised batch covering two edge conditions
  (over-collateralised RC = 0, zero-PFE netting set)

References:
- CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4 default
- CRR Art. 275(1): RC = max(V − C, 0)
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_compute_ead():  # type: ignore[return]
    """Import compute_ead or fail with a useful message."""
    try:
        from rwa_calc.engine.ccr.sa_ccr import compute_ead

        return compute_ead
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_ead from rwa_calc.engine.ccr.sa_ccr: {exc}. "
            "Implement the function body in P8.17."
        )


# ===========================================================================
# Case A — default α = 1.4, single netting set
# ===========================================================================


def test_compute_ead_default_alpha_case_a() -> None:
    """P8.17 Case A — EAD = 1.4 × (80 + 786_938.68) = 1_101_826.152 (default α).

    No config argument is passed; the function must apply α = 1.4 by default.

    CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4 by regulatory default.
    """
    # Arrange
    compute_ead = _import_compute_ead()

    lf = pl.LazyFrame(
        {
            "netting_set_id": ["NS-001"],
            "counterparty_reference": ["CP-001"],
            "rc_unmargined": [80.0],
            "pfe_addon": [786_938.68],
        }
    )

    # Act
    try:
        result = compute_ead(lf).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_ead raised NotImplementedError: {exc}. "
            "Implement the α×(RC+PFE) body in P8.17 — stub must be replaced."
        )

    # Assert — column present
    assert "ead_ccr" in result.columns, (
        f"Expected 'ead_ccr' column in result; got columns: {result.columns}"
    )

    # Assert — correct value: 1.4 × (80 + 786_938.68) = 1_101_826.152
    assert result["ead_ccr"][0] == pytest.approx(1_101_826.152, rel=1e-9), (
        f"Case A: expected EAD = 1_101_826.152 (α=1.4 × (RC=80 + PFE=786_938.68)); "
        f"got {result['ead_ccr'][0]!r}. CRR Art. 274(2)."
    )


# ===========================================================================
# Case B — α override to 1.0 via CCRConfig
# ===========================================================================


def test_compute_ead_alpha_override_via_config_case_b() -> None:
    """P8.17 Case B — EAD = 1.0 × (80 + 786_938.68) = 787_018.68 (α overridden to 1.0).

    Passes CCRConfig(alpha=Decimal("1.0")); function must use config.alpha
    over the regulatory default.

    CRR Art. 274(2): alpha is a supervisory parameter; firms may be permitted to
    use a lower value subject to PRA approval.
    """
    # Arrange
    compute_ead = _import_compute_ead()

    from rwa_calc.contracts.config import CCRConfig

    cfg = CCRConfig(alpha=Decimal("1.0"))

    lf = pl.LazyFrame(
        {
            "netting_set_id": ["NS-001"],
            "counterparty_reference": ["CP-001"],
            "rc_unmargined": [80.0],
            "pfe_addon": [786_938.68],
        }
    )

    # Act
    try:
        result = compute_ead(lf, config=cfg).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_ead raised NotImplementedError: {exc}. "
            "Implement the α×(RC+PFE) body in P8.17."
        )

    # Assert — correct value: 1.0 × (80 + 786_938.68) = 787_018.68
    assert result["ead_ccr"][0] == pytest.approx(787_018.68, rel=1e-9), (
        f"Case B: expected EAD = 787_018.68 (α=1.0 × (RC=80 + PFE=786_938.68)); "
        f"got {result['ead_ccr'][0]!r}. CCRConfig.alpha should override the default."
    )


# ===========================================================================
# Case C — vectorised three-row batch covering edge conditions
# ===========================================================================


def test_compute_ead_vectorised_three_rows_case_c() -> None:
    """P8.17 Case C — vectorised EAD over three netting sets with edge conditions.

    Row 1 — NS-001: RC=80, PFE=786_938.68 → EAD = 1.4 × 787_018.68 = 1_101_826.152
    Row 2 — NS-002: RC=0,  PFE=50_000     → EAD = 1.4 × 50_000 = 70_000.0
        (over-collateralised netting set; RC floors at zero per Art. 275(1))
    Row 3 — NS-003: RC=1234.5, PFE=0      → EAD = 1.4 × 1_234.5 = 1_728.3
        (no open trades; PFE = 0 because all positions at expiry)

    Also asserts that ``ead_ccr`` column dtype is pl.Float64.

    CRR Art. 274(2): EAD = alpha × (RC + PFE), alpha = 1.4.
    """
    # Arrange
    compute_ead = _import_compute_ead()

    lf = pl.LazyFrame(
        {
            "netting_set_id": ["NS-001", "NS-002", "NS-003"],
            "counterparty_reference": ["CP-001", "CP-002", "CP-003"],
            "rc_unmargined": [80.0, 0.0, 1234.5],
            "pfe_addon": [786_938.68, 50_000.0, 0.0],
        }
    )

    # Act
    try:
        result = compute_ead(lf).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_ead raised NotImplementedError: {exc}. "
            "Implement the α×(RC+PFE) body in P8.17."
        )

    # Assert — dtype is Float64
    assert result.schema["ead_ccr"] == pl.Float64, (
        f"'ead_ccr' column must be pl.Float64; got {result.schema['ead_ccr']}"
    )

    # Assert row 1: 1.4 × (80 + 786_938.68) = 1_101_826.152
    assert result["ead_ccr"][0] == pytest.approx(1_101_826.152, rel=1e-9), (
        f"Row 1 (NS-001): expected EAD=1_101_826.152; got {result['ead_ccr'][0]!r}. "
        "CRR Art. 274(2): EAD = α × (RC + PFE)."
    )

    # Assert row 2: 1.4 × (0 + 50_000) = 70_000
    assert result["ead_ccr"][1] == pytest.approx(70_000.0, rel=1e-9), (
        f"Row 2 (NS-002): expected EAD=70_000.0 (over-coll RC=0); "
        f"got {result['ead_ccr'][1]!r}. CRR Art. 274(2)."
    )

    # Assert row 3: 1.4 × (1234.5 + 0) = 1728.3
    assert result["ead_ccr"][2] == pytest.approx(1_728.3, rel=1e-9), (
        f"Row 3 (NS-003): expected EAD=1_728.3 (PFE=0 edge); "
        f"got {result['ead_ccr'][2]!r}. CRR Art. 274(2)."
    )
