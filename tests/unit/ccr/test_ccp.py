"""
Unit tests for apply_ccp_risk_weight (P8.25 — CCR-B1 QCCP trade exposure RW).

Pins the expected behaviour of the CCP risk-weight assignment per
CRR Art. 306 and Art. 307:

    CCR-B1a (is_qccp=True,  is_client_cleared=False) → risk_weight = 0.02
    CCR-B1b (is_qccp=True,  is_client_cleared=True)  → risk_weight = 0.04
    CCR-B1c (is_qccp=False, is_client_cleared=False)  → risk_weight = NULL
             (pass-through to SA institution path — 0.20 applied downstream)

Load-bearing invariant: EAD must not be mutated by apply_ccp_risk_weight.

References:
    - CRR Art. 306(1) — 2% RW for clearing member's own trade exposures to QCCP
    - CRR Art. 306(4) — RWA = EAD × 2%
    - CRR Art. 307    — 4% RW for client-cleared exposures through a clearing member
    - CRR Art. 107(2)(a) — non-QCCP exposures routed as institution (SA), 20% CQS 1
    - BCBS CRE54.14   — 2% supervisory risk weight (proprietary trade exposures)
    - BCBS CRE54.15   — 4% supervisory risk weight (client-cleared trade exposures)
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.ccr.qccp_builder import (
    QCCP_EAD,
    QCCP_RW_CLIENT_CLEARED,
    QCCP_RW_PROPRIETARY,
    build_qccp_trade_fixture,
)

# ---------------------------------------------------------------------------
# Subject under test.
# engine/ccr/ccp.py does not exist yet — the import will raise ImportError.
# We let the ImportError propagate to the test body so each test fails with
# the correct signal (ImportError) rather than at collection time.
# ---------------------------------------------------------------------------
try:
    from rwa_calc.engine.ccr.ccp import apply_ccp_risk_weight
except (ImportError, ModuleNotFoundError):
    apply_ccp_risk_weight = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Parametrised variants
# ---------------------------------------------------------------------------

_VARIANTS = [
    pytest.param(
        True,
        False,
        QCCP_RW_PROPRIETARY,
        "risk_weight",
        id="CCR-B1a-qccp-proprietary",
    ),
    pytest.param(
        True,
        True,
        QCCP_RW_CLIENT_CLEARED,
        "risk_weight",
        id="CCR-B1b-qccp-client-cleared",
    ),
]


# ===========================================================================
# 1. Risk weight — QCCP proprietary (CCR-B1a, Art. 306(1))
# ===========================================================================


def test_ccr_b1a_qccp_proprietary_risk_weight() -> None:
    """QCCP proprietary trade exposure: apply_ccp_risk_weight must return 0.02.

    Arrange:
        CCR-B1a fixture: is_qccp=True, is_client_cleared=False.
        EAD column pre-populated with QCCP_EAD (4_750_088.326...).

    Act:
        apply_ccp_risk_weight(exposures, counterparties, trades) -> LazyFrame.

    Assert:
        risk_weight == 0.02 (QCCP_PROPRIETARY_RW, Art. 306(1)).

    References: CRR Art. 306(1); BCBS CRE54.14.
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    fixture = build_qccp_trade_fixture(is_qccp=True, is_client_cleared=False)
    exposures = pl.LazyFrame({"ead_ccr": [QCCP_EAD]})

    # Act
    result_lf = apply_ccp_risk_weight(
        exposures=exposures,
        counterparties=fixture.counterparty.lazy(),
        trades=fixture.trades.lazy(),
    )
    result = result_lf.collect()

    # Assert
    actual_rw = result["risk_weight"][0]
    assert actual_rw == pytest.approx(QCCP_RW_PROPRIETARY, rel=1e-9), (
        f"CCR-B1a (is_qccp=True, is_client_cleared=False): "
        f"expected risk_weight={QCCP_RW_PROPRIETARY} (Art. 306(1)), got {actual_rw!r}. "
        "BCBS CRE54.14: 2% supervisory risk weight for proprietary trade exposures to QCCP."
    )


# ===========================================================================
# 2. Risk weight — QCCP client-cleared (CCR-B1b, Art. 307)
# ===========================================================================


def test_ccr_b1b_qccp_client_cleared_risk_weight() -> None:
    """QCCP client-cleared trade exposure: apply_ccp_risk_weight must return 0.04.

    Arrange:
        CCR-B1b fixture: is_qccp=True, is_client_cleared=True.
        EAD column pre-populated with QCCP_EAD.

    Act:
        apply_ccp_risk_weight(exposures, counterparties, trades) -> LazyFrame.

    Assert:
        risk_weight == 0.04 (QCCP_CLIENT_CLEARED_RW, Art. 307).

    References: CRR Art. 307; BCBS CRE54.15.
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    fixture = build_qccp_trade_fixture(is_qccp=True, is_client_cleared=True)
    exposures = pl.LazyFrame({"ead_ccr": [QCCP_EAD]})

    # Act
    result_lf = apply_ccp_risk_weight(
        exposures=exposures,
        counterparties=fixture.counterparty.lazy(),
        trades=fixture.trades.lazy(),
    )
    result = result_lf.collect()

    # Assert
    actual_rw = result["risk_weight"][0]
    assert actual_rw == pytest.approx(QCCP_RW_CLIENT_CLEARED, rel=1e-9), (
        f"CCR-B1b (is_qccp=True, is_client_cleared=True): "
        f"expected risk_weight={QCCP_RW_CLIENT_CLEARED} (Art. 307), got {actual_rw!r}. "
        "BCBS CRE54.15: 4% supervisory risk weight for client-cleared exposures."
    )


# ===========================================================================
# 3. Risk weight — non-QCCP pass-through (CCR-B1c, Art. 107(2)(a))
# ===========================================================================


def test_ccr_b1c_non_qccp_risk_weight_is_null() -> None:
    """Non-QCCP counterparty: apply_ccp_risk_weight must return NULL risk_weight.

    The 0.20 SA-Institution weight for CQS-1 is applied by the downstream
    SA classifier (P8.30), NOT by ccp.py.  The CCP module signals pass-through
    with NULL so the routing layer knows to invoke the SA path.

    Arrange:
        CCR-B1c fixture: is_qccp=False, is_client_cleared=False.
        EAD column pre-populated with QCCP_EAD.

    Act:
        apply_ccp_risk_weight(exposures, counterparties, trades) -> LazyFrame.

    Assert:
        risk_weight is NULL (None) — not 0.20.

    References: CRR Art. 107(2)(a) — routing to SA institution handled elsewhere.
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    fixture = build_qccp_trade_fixture(is_qccp=False, is_client_cleared=False)
    exposures = pl.LazyFrame({"ead_ccr": [QCCP_EAD]})

    # Act
    result_lf = apply_ccp_risk_weight(
        exposures=exposures,
        counterparties=fixture.counterparty.lazy(),
        trades=fixture.trades.lazy(),
    )
    result = result_lf.collect()

    # Assert
    actual_rw = result["risk_weight"][0]
    assert actual_rw is None, (
        f"CCR-B1c (is_qccp=False, is_client_cleared=False): "
        f"expected risk_weight=NULL (non-QCCP pass-through to SA path), got {actual_rw!r}. "
        "apply_ccp_risk_weight must NOT apply 0.20 — that is the SA-Institution CQS-1 weight "
        "applied downstream by the classifier (P8.30). CRR Art. 107(2)(a)."
    )


# ===========================================================================
# 4. EAD invariant — must not be mutated across all three variants
# ===========================================================================


@pytest.mark.parametrize(
    "is_qccp,is_client_cleared",
    [
        pytest.param(True, False, id="CCR-B1a-proprietary"),
        pytest.param(True, True, id="CCR-B1b-client-cleared"),
        pytest.param(False, False, id="CCR-B1c-non-qccp"),
    ],
)
def test_ccp_does_not_mutate_ead(is_qccp: bool, is_client_cleared: bool) -> None:
    """apply_ccp_risk_weight must not change the ead_ccr column.

    EAD is computed by SA-CCR (P8.11) and is identical across all three CCR-B1
    variants — the CCP module only annotates the risk_weight column.

    Arrange:
        Fixture with is_qccp and is_client_cleared as parametrised.
        ead_ccr pre-set to QCCP_EAD (4_750_088.326134375).

    Act:
        apply_ccp_risk_weight(exposures, counterparties, trades)

    Assert:
        ead_ccr == QCCP_EAD (rel=1e-9) — identical in / identical out.

    References:
        - CRR Art. 306(4): RWA = EAD × 2% (EAD from SA-CCR, not modified here).
        - P8.25 load-bearing invariant.
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    fixture = build_qccp_trade_fixture(is_qccp=is_qccp, is_client_cleared=is_client_cleared)
    exposures = pl.LazyFrame({"ead_ccr": [QCCP_EAD]})

    # Act
    result_lf = apply_ccp_risk_weight(
        exposures=exposures,
        counterparties=fixture.counterparty.lazy(),
        trades=fixture.trades.lazy(),
    )
    result = result_lf.collect()

    # Assert
    actual_ead = result["ead_ccr"][0]
    assert actual_ead == pytest.approx(QCCP_EAD, rel=1e-9), (
        f"Variant (is_qccp={is_qccp}, is_client_cleared={is_client_cleared}): "
        f"ead_ccr must not be mutated by apply_ccp_risk_weight. "
        f"Expected {QCCP_EAD!r}, got {actual_ead!r}. "
        "P8.25 load-bearing invariant: EAD is identical across all CCR-B1 variants."
    )


# ===========================================================================
# 5. RWA correctness — CCR-B1a (Art. 306(4))
# ===========================================================================


def test_ccr_b1a_rwa_proprietary() -> None:
    """CCR-B1a RWA = EAD × 0.02 per Art. 306(4).

    Arrange:
        CCR-B1a fixture: is_qccp=True, is_client_cleared=False.
        EAD = QCCP_EAD (4_750_088.326134375).

    Act:
        apply_ccp_risk_weight and compute rwa = ead_ccr * risk_weight.

    Assert:
        rwa == QCCP_EAD * 0.02 == QCCP_RWA_PROPRIETARY (95_001.7665...).

    References: CRR Art. 306(4).
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    from tests.fixtures.ccr.qccp_builder import QCCP_RWA_PROPRIETARY

    fixture = build_qccp_trade_fixture(is_qccp=True, is_client_cleared=False)
    exposures = pl.LazyFrame({"ead_ccr": [QCCP_EAD]})

    # Act
    result_lf = apply_ccp_risk_weight(
        exposures=exposures,
        counterparties=fixture.counterparty.lazy(),
        trades=fixture.trades.lazy(),
    )
    result = result_lf.collect()
    actual_rwa = result["ead_ccr"][0] * result["risk_weight"][0]

    # Assert
    assert actual_rwa == pytest.approx(QCCP_RWA_PROPRIETARY, rel=1e-9), (
        f"CCR-B1a RWA: expected {QCCP_RWA_PROPRIETARY!r} (EAD × 0.02, Art. 306(4)), "
        f"got {actual_rwa!r}."
    )


# ===========================================================================
# 6. RWA correctness — CCR-B1b (Art. 307)
# ===========================================================================


def test_ccr_b1b_rwa_client_cleared() -> None:
    """CCR-B1b RWA = EAD × 0.04 per Art. 307.

    Arrange:
        CCR-B1b fixture: is_qccp=True, is_client_cleared=True.
        EAD = QCCP_EAD.

    Act:
        apply_ccp_risk_weight and compute rwa = ead_ccr * risk_weight.

    Assert:
        rwa == QCCP_EAD * 0.04 == QCCP_RWA_CLIENT_CLEARED (190_003.533...).

    References: CRR Art. 307; BCBS CRE54.15.
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    from tests.fixtures.ccr.qccp_builder import QCCP_RWA_CLIENT_CLEARED

    fixture = build_qccp_trade_fixture(is_qccp=True, is_client_cleared=True)
    exposures = pl.LazyFrame({"ead_ccr": [QCCP_EAD]})

    # Act
    result_lf = apply_ccp_risk_weight(
        exposures=exposures,
        counterparties=fixture.counterparty.lazy(),
        trades=fixture.trades.lazy(),
    )
    result = result_lf.collect()
    actual_rwa = result["ead_ccr"][0] * result["risk_weight"][0]

    # Assert
    assert actual_rwa == pytest.approx(QCCP_RWA_CLIENT_CLEARED, rel=1e-9), (
        f"CCR-B1b RWA: expected {QCCP_RWA_CLIENT_CLEARED!r} (EAD × 0.04, Art. 307), "
        f"got {actual_rwa!r}."
    )


# ===========================================================================
# 7. Citation metadata — P6.35: apply_ccp_risk_weight must cite Art. 306 only
# ===========================================================================


def test_apply_ccp_risk_weight_cites_art_306_not_307() -> None:
    """apply_ccp_risk_weight's @cites metadata must be exactly {CRR Art. 306}.

    The function handles both proprietary (Art. 306) and client-cleared
    (Art. 307) branches internally, but Art. 307 governs the *client*-facing
    treatment that the clearing member passes through — it is not an
    independent obligation of apply_ccp_risk_weight itself. The corrected
    citation set is therefore exactly ("CRR Art. 306",); Art. 307 must be
    removed.

    Arrange:
        apply_ccp_risk_weight imported from rwa_calc.engine.ccr.ccp.
        __watchfire__ attribute carries the @cites metadata.

    Act:
        Collect canonical() strings from all Citation objects in __watchfire__.

    Assert:
        actual == ("CRR Art. 306",)  — exactly one citation, Art. 306.
        "CRR Art. 307" not in actual — Art. 307 must not be present.
        "Art. 307" not in (apply_ccp_risk_weight.__doc__ or "") — docstring
        must not reference Art. 307 as a standalone decorator-citation marker.

    References:
        - CRR Art. 306(1) — the article that governs the function's own RW logic.
        - P6.35 — XS citation-metadata correction.
    """
    # Arrange
    if apply_ccp_risk_weight is None:
        pytest.fail(
            "Cannot import apply_ccp_risk_weight from rwa_calc.engine.ccr.ccp. "
            "Module does not exist yet — engine-implementer must create engine/ccr/ccp.py."
        )

    # Act
    citations = getattr(apply_ccp_risk_weight, "__watchfire__", ())
    actual = tuple(c.canonical() for c in citations)

    # Assert
    assert actual == ("CRR Art. 306",), (
        f"apply_ccp_risk_weight.__watchfire__ canonical citations: "
        f"expected ('CRR Art. 306',), got {actual!r}. "
        "P6.35: remove the @cites('CRR Art. 307') decorator — Art. 307 governs "
        "the client-side clearing relationship, not this function's own obligation."
    )
    assert "CRR Art. 307" not in actual, (
        "apply_ccp_risk_weight must not cite CRR Art. 307 — "
        "the @cites('CRR Art. 307') decorator must be removed (P6.35)."
    )
