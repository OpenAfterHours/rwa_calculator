"""
The oracle record shape.

Every oracle is one JSON-serialisable dict with the same five parts:

``exposure_id``
    ``ORC-nnn``. Matches a section heading in ``ORACLE_DERIVATIONS.md``.
``regulation``
    The article the expected value was read out of. One line, quotable.
``inputs``
    Driver keyword arguments -- fed verbatim to ``tests/oracle/drivers.py``.
    These are *inputs*, so sourcing them from the engine's column vocabulary
    costs nothing; the independence constraint is about expected values.
``intermediate``
    Optional named intermediates (correlation, maturity adjustment, LGD,
    conditional PD, ...). The test compares whichever of these the engine
    also publishes, so a mismatch names the step that diverged instead of
    just reporting a wrong RWA.
``expected``
    The derived answer. Always carries ``risk_weight`` and ``rwa``.
``unasserted``
    Optional. Keys published in ``expected`` / ``intermediate`` that the test
    must NOT compare, because the value could not be sourced from a document
    available here. Publishing the number but declining to assert it keeps the
    gap visible instead of hiding it behind a silently-omitted field.
"""

from __future__ import annotations

from typing import Any


def oracle(
    *,
    oracle_id: str,
    phase: str,
    framework: str,
    approach: str,
    exposure_class: str,
    regulation: str,
    ead: float,
    risk_weight: float,
    inputs: dict[str, Any] | None = None,
    intermediate: dict[str, Any] | None = None,
    rwa: float | None = None,
    extra_expected: dict[str, Any] | None = None,
    unasserted: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build one oracle record.

    ``rwa`` defaults to ``ead * risk_weight``. Pass it explicitly only where
    the regulation makes RWA something other than that product (for example a
    supporting factor applied after the risk weight).
    """
    expected: dict[str, Any] = {
        "risk_weight": risk_weight,
        "rwa": ead * risk_weight if rwa is None else rwa,
    }
    if extra_expected:
        expected.update(extra_expected)

    record: dict[str, Any] = {
        "exposure_id": oracle_id,
        "phase": phase,
        "framework": framework,
        "approach": approach,
        "exposure_class": exposure_class,
        "regulation": regulation,
        "inputs": {"ead": ead, **(inputs or {})},
        "expected": expected,
    }
    if intermediate:
        record["intermediate"] = intermediate
    if unasserted:
        record["unasserted"] = list(unasserted)
    return record
