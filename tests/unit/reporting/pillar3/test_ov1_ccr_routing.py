"""
Pillar 3 OV1 — the CCR "of which" ROUTING: which Chapter 6 leg lands in which row.

Pipeline position:
    synthetic sealed-shape ledger -> Pillar3Generator (ledger shim) -> OV1
    (and, directly, ``ov1._prepare`` — the four derived discriminator columns
    the row-6 block's cell predicates key off)

The routing this file pins, and WHY — Chapter 6's section boundaries:

    Section 3  = Art. 274-280f  (SA-CCR)                       -> row 7
    Section 6  = Art. 283       (IMM)                          -> row 8 (null: not implemented)
    Section 9  = Art. 300-311   ("Own funds requirements for
                 exposures to a central counterparty")         -> row UK8a
    the residual ("CCR RWEAs ... that are not disclosed under
                 rows 7, 8 and UK 8a")                         -> row 9

**Section 9 runs Art. 300 to Art. 311 — so Art. 307-309 (own funds requirements
for contributions to the default fund of a CCP) sit INSIDE it.** A default-fund
contribution IS an "exposure to a central counterparty": it belongs in row UK8a,
NOT in the row-9 residual. (The EU/UK CCR8 template says the same thing from the
other side — it carries explicit prefunded/unfunded default-fund rows under its
QCCP and non-QCCP blocks, i.e. they are CCP exposures.) A CCP-faced SFT is
likewise Section 9, by Art. 301(1)(b): the section's material scope reaches
securities financing transactions, not only derivatives. What is left for row 9
is the true residual — a CCR leg faced to a NON-CCP counterparty, which today
means an FCCM SFT faced to a bilateral counterparty.

That is the whole point of this file. The routing above is what ``ov1.py``
already DOES, but until now nothing tested it, and the module's comments recorded
the OPPOSITE basis (they claimed default-fund contributions were "neither Section
3 nor Section 9" and so fell to row 9). Correct behaviour resting on a wrong
recorded basis is a defect waiting for its first refactor: the comment is what the
next reader believes. These assertions are the pin that would have caught it.

No fixture carries a ``CCR_DEFAULT_FUND`` leg, so the default-fund route is
unreachable from any portfolio-driven test — hence the synthetic ledger here. It
is number-neutral by construction: no golden reads this file's data.

References:
- CRR Part 8 Art. 438; PRA PS1/26 Annex XX (UKB OV1) — rows 6, 7, 8, UK 8a, 9
- CRR Chapter 6 Section 3 (Art. 274-280f, SA-CCR); Section 6 (Art. 283, IMM);
  Section 9 (Art. 300-311, exposures to a CCP — incl. Art. 301 material scope
  and Art. 307-309 default-fund contributions)
- tests/acceptance/reporting/test_ov1_ccr.py — the same block, portfolio-driven
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.ov1 import (
    _IS_CCP,
    _IS_CCR,
    _IS_OTHER_CCR,
    _IS_SA_CCR,
    _prepare,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

_ABS = 1e-6

# The OV1 CCR block.
_ROW_CCR = "6"
_ROW_SA_CCR = "7"
_ROW_IMM = "8"
_ROW_CCP = "UK8a"
_ROW_OTHER_CCR = "9"

# One leg per route, at a decade-unique RWEA: every digit position of a reported
# cell identifies exactly one leg, so a mis-route cannot hide inside a sum.
#
#   leg                       risk_type          cp_entity_type   rwa_final   row
#   ------------------------  -----------------  --------------  ----------  -----
#   a corporate term loan     (none)             corporate       1,000,000     1
#   a bilateral derivative    CCR_DERIVATIVE     institution       700,000     7   Section 3
#   a QCCP-cleared derivative CCR_DERIVATIVE     ccp                80,000   UK8a  Section 9
#   a CCP-faced SFT           CCR_SFT            ccp                 8,000   UK8a  Section 9
#   a default-fund contrib.   CCR_DEFAULT_FUND   ccp                   800   UK8a  Section 9
#   a bilateral SFT           CCR_SFT            institution         9,000     9   residual
_RWA_LOAN = 1_000_000.0
_RWA_DERIV_BILATERAL = 700_000.0
_RWA_DERIV_CCP = 80_000.0
_RWA_SFT_CCP = 8_000.0
_RWA_DEFAULT_FUND = 800.0
_RWA_SFT_BILATERAL = 9_000.0

# The four Section-9 / Section-3 / residual aggregates the block must report.
_EXPECTED_SA_CCR = _RWA_DERIV_BILATERAL
_EXPECTED_CCP = _RWA_DERIV_CCP + _RWA_SFT_CCP + _RWA_DEFAULT_FUND  # 88,800
_EXPECTED_OTHER_CCR = _RWA_SFT_BILATERAL
_EXPECTED_CCR = _EXPECTED_SA_CCR + _EXPECTED_CCP + _EXPECTED_OTHER_CCR
_EXPECTED_NON_CCR = _RWA_LOAN
_EXPECTED_TOTAL = _EXPECTED_NON_CCR + _EXPECTED_CCR

_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")


def _ledger() -> pl.LazyFrame:
    """One leg per CCR route, plus a non-CCR control.

    ``approach_applied`` is ``standardised`` on every leg — including the CCR
    ones. That is the CRR ledger's real shape, and the trap the block's
    ``risk_type`` cut exists to survive.
    """
    return pl.LazyFrame(
        [
            {
                "exposure_id": "LOAN-01",
                "risk_type": None,
                "cp_entity_type": "corporate",
                "cp_is_qccp": None,
                "approach_applied": "standardised",
                "rwa_final": _RWA_LOAN,
            },
            {
                "exposure_id": "DERIV-BILATERAL-01",
                "risk_type": "CCR_DERIVATIVE",
                "cp_entity_type": "institution",
                "cp_is_qccp": None,
                "approach_applied": "standardised",
                "rwa_final": _RWA_DERIV_BILATERAL,
            },
            {
                "exposure_id": "DERIV-CCP-01",
                "risk_type": "CCR_DERIVATIVE",
                "cp_entity_type": "ccp",
                "cp_is_qccp": True,
                "approach_applied": "standardised",
                "rwa_final": _RWA_DERIV_CCP,
            },
            {
                "exposure_id": "SFT-CCP-01",
                "risk_type": "CCR_SFT",
                "cp_entity_type": "ccp",
                "cp_is_qccp": True,
                "approach_applied": "standardised",
                "rwa_final": _RWA_SFT_CCP,
            },
            {
                "exposure_id": "DFC-01",
                "risk_type": "CCR_DEFAULT_FUND",
                "cp_entity_type": "ccp",
                "cp_is_qccp": True,
                "approach_applied": "standardised",
                "rwa_final": _RWA_DEFAULT_FUND,
            },
            {
                "exposure_id": "SFT-BILATERAL-01",
                "risk_type": "CCR_SFT",
                "cp_entity_type": "institution",
                "cp_is_qccp": None,
                "approach_applied": "standardised",
                "rwa_final": _RWA_SFT_BILATERAL,
            },
        ],
        schema_overrides={"risk_type": pl.String, "cp_is_qccp": pl.Boolean},
    )


# =============================================================================
# The routing table — ``_prepare``'s four discriminator flags, leg by leg
# =============================================================================

# (leg, risk_type, cp_entity_type) -> (is_ccr, is_sa_ccr, is_ccp, is_other_ccr)
_ROUTES: tuple[tuple[str, str | None, str, tuple[bool, bool, bool, bool]], ...] = (
    # Art. 307-309 default-fund contributions are Section 9 (Art. 300-311) —
    # an "exposure to a central counterparty". UK8a, not the row-9 residual.
    ("default-fund contribution", "CCR_DEFAULT_FUND", "ccp", (True, False, True, False)),
    # Art. 301(1)(b): Section 9's material scope reaches SFTs, not just
    # derivatives. A CCP-faced SFT is a CCP exposure. UK8a.
    ("CCP-faced SFT", "CCR_SFT", "ccp", (True, False, True, False)),
    # The residual: a CCR leg faced to a NON-CCP counterparty and not SA-CCR.
    ("bilateral SFT", "CCR_SFT", "institution", (True, False, False, True)),
    # Section 3 (Art. 274-280f): a derivative NOT faced to a CCP.
    ("bilateral derivative", "CCR_DERIVATIVE", "institution", (True, True, False, False)),
    # A cleared derivative is Section 9, not Section 3 — the CCP cut wins.
    ("CCP-cleared derivative", "CCR_DERIVATIVE", "ccp", (True, False, True, False)),
    # The non-CCR control: no flag at all, so it stays in row 1.
    ("corporate term loan", None, "corporate", (False, False, False, False)),
)


@pytest.mark.parametrize(("leg", "risk_type", "entity", "flags"), _ROUTES)
def test_ov1_ccr_leg_routes_to_its_chapter_6_section(
    leg: str, risk_type: str | None, entity: str, flags: tuple[bool, bool, bool, bool]
) -> None:
    """Each CCR leg sets exactly the discriminator flag its Chapter 6 section implies.

    Section 9 is Art. 300-311 ("exposures to a central counterparty"), so the
    Art. 307-309 default-fund contribution and the Art. 301(1)(b) CCP-faced SFT
    are BOTH CCP exposures -> ``ov1_is_ccp`` -> row UK8a. Row 9 is the residual
    the instructions define ("not disclosed under rows 7, 8 and UK 8a"): a CCR
    leg faced to a non-CCP counterparty.

    Arrange: a one-leg synthetic ledger at the given (risk_type, cp_entity_type).
    Act:     ``ov1._prepare`` — the real derivation the cell predicates key off.
    Assert:  the four flags are exactly as the section boundaries require.
    """
    # Arrange
    lf = pl.LazyFrame(
        [{"risk_type": risk_type, "cp_entity_type": entity, "rwa_final": 1.0}],
        schema_overrides={"risk_type": pl.String},
    )

    # Act
    prepared = _prepare(lf, set(lf.collect_schema().names())).collect()
    got = tuple(bool(prepared[col][0]) for col in (_IS_CCR, _IS_SA_CCR, _IS_CCP, _IS_OTHER_CCR))

    # Assert
    assert got == flags, (
        f"a {leg} (risk_type={risk_type!r}, cp_entity_type={entity!r}) routes to "
        f"{dict(zip((_IS_CCR, _IS_SA_CCR, _IS_CCP, _IS_OTHER_CCR), got, strict=True))}, "
        f"but Chapter 6 puts it at "
        f"{dict(zip((_IS_CCR, _IS_SA_CCR, _IS_CCP, _IS_OTHER_CCR), flags, strict=True))}. "
        "Section 9 (row UK8a) is Art. 300-311 — it takes EVERY leg faced to a CCP: the "
        "Art. 307-309 default-fund contribution and the Art. 301(1)(b) CCP-faced SFT "
        "included. Row 9 is only the residual: a CCR leg faced to a non-CCP."
    )


def test_ov1_ccr_flags_partition_the_ccr_population() -> None:
    """Rows 7 / UK8a / 9 are mutually exclusive, and together they exhaust row 6.

    The of-which rows partition row 6 — so on every leg, ``is_sa_ccr + is_ccp +
    is_other_ccr`` must be exactly 1 when ``is_ccr``, and exactly 0 when not. A
    leg routed to two rows would be double-counted; a CCR leg routed to none
    would vanish from the block while still sitting in row 6.

    Arrange: the six-leg synthetic ledger (one per route).
    Act:     ``ov1._prepare``.
    Assert:  the flag count per leg is 1 iff the leg is CCR.
    """
    # Arrange + Act
    lf = _ledger()
    prepared = _prepare(lf, set(lf.collect_schema().names())).collect()

    # Assert
    for row in prepared.iter_rows(named=True):
        hits = sum(bool(row[col]) for col in (_IS_SA_CCR, _IS_CCP, _IS_OTHER_CCR))
        want = 1 if row[_IS_CCR] else 0
        assert hits == want, (
            f"leg {row['exposure_id']} sets {hits} of the three of-which flags "
            f"({_IS_SA_CCR} / {_IS_CCP} / {_IS_OTHER_CCR}); it must set exactly {want}. "
            "Rows 7 / UK8a / 9 PARTITION row 6 — two flags double-count the leg, zero "
            "flags drop it out of the block while leaving it in row 6."
        )


# =============================================================================
# The same routing, read off the executed template
# =============================================================================


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_ov1_ccr_block_reports_each_section_at_its_own_rwea(framework: str) -> None:
    """Row 7 / UK8a / 9 report the Section 3 / Section 9 / residual RWEA, per the ledger.

    The decade-unique leg values make each cell decodable: UK8a must be 88,800 —
    the cleared derivative (80,000) PLUS the CCP-faced SFT (8,000) PLUS the
    Art. 307-309 default-fund contribution (800), all three being exposures to a
    CCP under Section 9 (Art. 300-311). Row 9 must be 9,000 — the bilateral SFT
    ALONE. Under the wrong basis (default-fund contributions as "neither Section
    3 nor Section 9") UK8a would report 88,000 and row 9 would report 9,800.

    Arrange: the six-leg synthetic ledger, mirrored onto the sealed shape.
    Act:     Pillar3Generator -> OV1, both frameworks (the block is in both).
    Assert:  rows 1 / 6 / 7 / UK8a / 9 / 29 at their hand-derived values;
             row 8 (IMM) stays null.
    """
    # Arrange + Act
    bundle = LedgerShimPillar3Generator().generate_from_lazyframe(_ledger(), framework=framework)
    assert bundle.ov1 is not None, f"[{framework}] OV1 was not generated"
    cells = {row["row_ref"]: row["a"] for row in bundle.ov1.iter_rows(named=True)}

    # Assert
    expected: dict[str, float] = {
        "1": _EXPECTED_NON_CCR,
        _ROW_CCR: _EXPECTED_CCR,
        _ROW_SA_CCR: _EXPECTED_SA_CCR,
        _ROW_CCP: _EXPECTED_CCP,
        _ROW_OTHER_CCR: _EXPECTED_OTHER_CCR,
        "29": _EXPECTED_TOTAL,
    }
    for ref, want in expected.items():
        assert cells[ref] == pytest.approx(want, abs=_ABS), (
            f"[{framework}] OV1 row {ref} column a: expected {want:,.2f}, got {cells[ref]}. "
            f"Row UK8a is Section 9 (Art. 300-311, 'exposures to a central counterparty') "
            f"and takes the CCP-cleared derivative, the CCP-faced SFT (Art. 301(1)(b)) AND "
            f"the default-fund contribution (Art. 307-309, which sits INSIDE Section 9). "
            f"Row 9 is the residual only — the SFT faced to a non-CCP counterparty."
        )
    assert cells[_ROW_IMM] is None, (
        f"[{framework}] OV1 row {_ROW_IMM} (Section 6, internal model method) must stay "
        f"null — IMM is not implemented, and null is not the same claim as 0.0. Got "
        f"{cells[_ROW_IMM]}."
    )
