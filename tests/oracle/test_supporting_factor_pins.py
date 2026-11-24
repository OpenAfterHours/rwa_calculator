"""
Oracle pins for the SME supporting factor in both regimes (P1.323).

Pipeline position:
    Oracle meta-tests. They read ``tests/oracle/expected_values.json`` and drive
    ``tests/oracle/drivers.py``; nothing here derives an expected value.

Why this file exists:
    ``test_oracle.py::test_engine_matches_oracle`` compares only the keys an
    oracle record asserts. It skips any key named in ``unasserted``, and it
    skips without a word any key the engine does not publish. Until P1.323 the
    two Basel 3.1 SME oracles (ORC-060 on the SA, ORC-097 on F-IRB) kept their
    RWEA in ``unasserted``, because PS1/26 is silent on the CRR Art. 501 SME
    supporting factor. A Basel 3.1 run that re-applied the factor therefore
    stayed green in the oracle suite.

    The silence was never an open question. Art. 501 and Art. 501a are revoked
    by HM Treasury, not by the PRA: S.I. 2026/45 (the Financial Services and
    Markets Act 2023 (Commencement No. 12 and Saving Provisions) Regulations
    2026) reg. 3(b) and Schedule Part 1 bring their revocation into force on
    1 January 2027, and none of regs. 4-8 saves either article. That is why
    ``ps126app1.pdf`` neither restates nor deletes them. These tests stop an SME
    oracle from dropping either half of the pin again, in either regime.

Key responsibilities:
- Every SME supporting-factor oracle asserts both its RWEA and its supporting
  factor, and the factor is its regime's: 0.7619 under CRR Art. 501(1) with
  E* below EUR 2.5m, and exactly 1 under Basel 3.1.
- The engine publishes the ``supporting_factor`` carrier for each of them, so
  the comparison in ``test_oracle.py`` cannot pass by finding nothing to compare.

References:
- CRR Art. 501(1): SME supporting factor, in force until 31 December 2026
- S.I. 2026/45 reg. 3(b) and Schedule Part 1: revocation of CRR Art. 501 and
  Art. 501a from 1 January 2027
- PS1/26 Annex II, OF 07.00 col 0220 and OF 08.01 col 0260: the Basel 3.1 RWEA
  columns carry no supporting-factor adjustment
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.oracle.test_oracle import ORACLES, _run

#: ``(oracle id, framework, the regime's SME supporting factor)``. One SA and
#: one F-IRB case per regime, so each regime's pin can fail on its own.
_SME_FACTOR_ORACLES = (
    pytest.param("ORC-038", "CRR", 0.7619, id="crr-sa-ORC-038"),
    pytest.param("ORC-087", "CRR", 0.7619, id="crr-firb-ORC-087"),
    pytest.param("ORC-060", "BASEL_3_1", 1.0, id="b31-sa-ORC-060"),
    pytest.param("ORC-097", "BASEL_3_1", 1.0, id="b31-firb-ORC-097"),
)


@pytest.mark.parametrize(("oracle_id", "framework", "factor"), _SME_FACTOR_ORACLES)
def test_sme_oracle_asserts_its_rwea_and_its_regime_supporting_factor(
    oracle_id: str, framework: str, factor: float
) -> None:
    """An SME oracle pins RWEA = EAD x RW x the regime's factor, and asserts both."""
    # Arrange
    record = _record(oracle_id)
    expected = record["expected"]

    # Act
    asserted = set(expected) - set(record.get("unasserted", ()))

    # Assert
    assert record["framework"] == framework
    assert {"rwa", "supporting_factor"} <= asserted, (
        f"{oracle_id} does not assert {sorted({'rwa', 'supporting_factor'} - asserted)}: "
        "test_oracle.py would skip it, so a supporting factor wrongly applied or "
        "wrongly dropped in this regime would pass the oracle suite"
    )
    assert expected["supporting_factor"] == factor
    assert expected["rwa"] == pytest.approx(
        record["inputs"]["ead"] * expected["risk_weight"] * factor, rel=1e-12
    )


@pytest.mark.parametrize(("oracle_id", "framework", "factor"), _SME_FACTOR_ORACLES)
def test_engine_publishes_the_supporting_factor_each_sme_oracle_pins(
    oracle_id: str, framework: str, factor: float
) -> None:
    """The engine row carries ``supporting_factor``, so the oracle's comparison is live."""
    # Arrange
    record = _record(oracle_id)

    # Act
    row = _run(record)

    # Assert
    assert row.get("supporting_factor") is not None, (
        f"the {framework} engine row for {oracle_id} publishes no supporting_factor: "
        "test_oracle.py skips a key the engine does not publish, so the "
        f"{factor} pin would compare nothing"
    )


def _record(oracle_id: str) -> dict[str, Any]:
    return next(o for o in ORACLES if o["exposure_id"] == oracle_id)
