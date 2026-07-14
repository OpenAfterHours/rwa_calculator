"""Contract test: C 02.00's local SA-approach tuple stays pinned to SA_CCR_APPROACH.

``reporting/corep/c02.py`` deliberately keeps its own module-local
``_SA_APPROACHES`` tuple rather than importing the shared SA-approach
constant (a shared constant would also widen Pillar 3 CR4/CR5, which
correctly scope CCR out under Basel 3.1). But that locality means it
hardcodes the *string value* of ``SA_CCR_APPROACH``
(``engine/aggregator/_schemas.py``) rather than referencing it.

Failure mode this test catches: if ``SA_CCR_APPROACH`` is ever renamed or
its value changed, ``c02.py``'s literal silently stops matching and
C 02.00 quietly stops footing under Basel 3.1 — its "Of which: Standardised
Approach" row (0060) and SA class rows would drop the SA-CCR derivatives
that row 0010/0050 (flat ledger sums) still carry. This is the exact
defect fixed 2026-07-12 (see c02.py's module docstring / recorded fix).

This test reaches into ``c02._SA_APPROACHES``, a private module-level
name, on purpose: the whole point is to catch drift between a deliberate
local copy and its source of truth, which is invisible from the public
API.
"""

from __future__ import annotations

from rwa_calc.engine.aggregator._schemas import SA_CCR_APPROACH
from rwa_calc.reporting.corep import c02


def test_c02_sa_approaches_include_canonical_sa_ccr_label() -> None:
    """c02._SA_APPROACHES must still contain the canonical SA_CCR_APPROACH value.

    A rename of SA_CCR_APPROACH would silently un-foot C 02.00 under Basel 3.1.
    """
    # Assert — the canonical CCR-via-SA label is present in the local copy.
    assert SA_CCR_APPROACH in c02._SA_APPROACHES

    # Assert — plain SA is present too, so the tuple can't be "simplified"
    # down to just the CCR label.
    assert "standardised" in c02._SA_APPROACHES
