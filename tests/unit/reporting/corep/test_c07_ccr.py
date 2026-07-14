"""
COREP C 07.00 — counterparty-credit-risk rows (0090-0130) and the QCCP "of which".

Annex II puts CCR exposures in C 07.00 rows 0090-0130: row 0110 is the additive
parent (ALL derivative netting sets, including QCCP-cleared ones) and row 0120 is
its "of which: centrally cleared through a QCCP" subset.

The QCCP discriminator is the project's canonical one —
``(cp_entity_type == "ccp") & cp_is_qccp.fill_null(True)`` — under which an ABSENT
flag on a ``ccp`` entity QUALIFIES, and only an explicit ``False`` demotes it:
- engine/sa/risk_weights.py (the Art. 306(1)(a) 2% pin)
- engine/aggregator/aggregator.py (the rwa_ccr_qccp_trade partition)
- reporting/pillar3/templates.py (mirrors the aggregator partition)
- data/schemas.py ("only an explicit False demotes a ccp entity_type")

A null flag therefore lands in row 0120. Keying the row on a bare
``cp_is_qccp == True`` silently under-reported the "of which" cell while the same
sheet's 2% risk-weight band showed the exposure — the regression these tests pin.

References:
- COREP Annex II, C 07.00 rows 0110/0120; CRR Art. 301(1), Art. 306(1)(a)
- docs/plans/c07-ccr-derivatives.md
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator


def _ccr_derivative_results() -> pl.LazyFrame:
    """Derivative netting-set rows (risk_type == "CCR_DERIVATIVE") on the institution sheet.

    - CCR_QCCP_NULL_FLAG: a ``ccp`` counterparty whose ``cp_is_qccp`` flag is
      NULL. Under the canonical QCCP rule an absent flag QUALIFIES, so this
      netting set is risk-weighted at the Art. 306(1)(a) 2% pin.
    - CCR_CCP_DEMOTED: a ``ccp`` counterparty with an explicit
      ``cp_is_qccp = False`` — only an explicit False demotes it, so it takes
      the ordinary institution weight (20%).
    - CCR_BANK: a bilateral (non-CCP) bank netting set, 20%.
    - SA_INST_LOAN: a plain SA loan (no ``risk_type``) that must not reach the
      derivative netting-set rows at all.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "CCR_QCCP_NULL_FLAG",
                "CCR_CCP_DEMOTED",
                "CCR_BANK",
                "SA_INST_LOAN",
            ],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["institution"] * 4,
            "drawn_amount": [1000.0, 400.0, 600.0, 5000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 400.0, 600.0, 5000.0],
            "rwa_final": [20.0, 80.0, 120.0, 1000.0],
            "risk_weight": [0.02, 0.20, 0.20, 0.20],
            "risk_type": ["CCR_DERIVATIVE", "CCR_DERIVATIVE", "CCR_DERIVATIVE", None],
            "cp_entity_type": ["ccp", "ccp", "institution", "institution"],
            "cp_is_qccp": [None, False, None, None],
            "counterparty_reference": ["CCP_1", "CCP_2", "BANK_1", "BANK_2"],
            "scra_provision_amount": [0.0] * 4,
            "gcra_provision_amount": [0.0] * 4,
        }
    )


class TestC0700QCCPDerivativeRows:
    """C 07.00 rows 0110 / 0120 — derivative netting sets and the QCCP "of which".

    COREP Annex II: row 0110 "Derivatives & Long Settlement Transactions netting
    sets" is the ADDITIVE PARENT of row 0120 "of which: centrally cleared through
    a QCCP".

    Why: the project's canonical QCCP discriminator is
    ``(cp_entity_type == "ccp") & cp_is_qccp.fill_null(True)`` — an ABSENT flag on
    a ``ccp`` entity is treated as QUALIFYING, and only an explicit ``False``
    demotes it to the institution ladder:

    - ``engine/sa/risk_weights.py`` (QCCP trade-exposure weight)
    - ``engine/aggregator/aggregator.py`` (QCCP roll-up)
    - ``reporting/pillar3/templates.py`` (Pillar 3 QCCP split)
    - ``data/schemas.py`` ``cp_is_qccp``: "only an explicit ``False`` demotes a
      ``ccp`` entity_type"

    A CCP netting set with a null flag is therefore risk-weighted at 2% and must
    also be reported in row 0120 — otherwise the "of which" cell understates and
    contradicts the 2% band on its own sheet.

    References:
        CRR Art. 306(1)(a): 2% trade-exposure weight for QCCP-cleared trades
        CRR Art. 272(88): qualifying CCP definition
        COREP Annex II C 07.00 rows 0110 / 0120
    """

    def test_row_0120_counts_ccp_netting_set_with_null_qccp_flag(self) -> None:
        """A ``ccp`` netting set with a NULL ``cp_is_qccp`` lands in both 0110 and 0120."""
        # Arrange
        gen = LedgerShimCorepGenerator()
        lf = _ccr_derivative_results()

        # Act
        bundle = gen.generate_from_lazyframe(lf, framework="CRR")
        inst = bundle.c07_00["institution"]
        row_0110 = inst.filter(pl.col("row_ref") == "0110")
        row_0120 = inst.filter(pl.col("row_ref") == "0120")

        # Assert: parent row 0110 holds every derivative netting set (and only those)
        assert len(row_0110) == 1
        assert row_0110["0200"][0] == pytest.approx(2000.0)  # 1000 + 400 + 600
        assert row_0110["0220"][0] == pytest.approx(220.0)  # 20 + 80 + 120

        # Assert: row 0120 holds the null-flag CCP netting set — an absent flag qualifies
        assert len(row_0120) == 1
        assert row_0120["0200"][0] == pytest.approx(1000.0)
        assert row_0120["0220"][0] == pytest.approx(20.0)

    def test_row_0120_excludes_explicitly_non_qualifying_ccp(self) -> None:
        """An explicit ``cp_is_qccp = False`` on a ``ccp`` stays out of 0120, but is in 0110."""
        # Arrange — a single demoted CCP netting set, nothing else
        gen = LedgerShimCorepGenerator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["CCR_CCP_DEMOTED"],
                "approach_applied": ["standardised"],
                "exposure_class": ["institution"],
                "drawn_amount": [400.0],
                "undrawn_amount": [0.0],
                "ead_final": [400.0],
                "rwa_final": [80.0],
                "risk_weight": [0.20],
                "risk_type": ["CCR_DERIVATIVE"],
                "cp_entity_type": ["ccp"],
                "cp_is_qccp": [False],
                "counterparty_reference": ["CCP_2"],
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
            }
        )

        # Act
        bundle = gen.generate_from_lazyframe(lf, framework="CRR")
        inst = bundle.c07_00["institution"]
        row_0110 = inst.filter(pl.col("row_ref") == "0110")
        row_0120 = inst.filter(pl.col("row_ref") == "0120")

        # Assert: the parent still reports it
        assert row_0110["0200"][0] == pytest.approx(400.0)
        assert row_0110["0220"][0] == pytest.approx(80.0)

        # Assert: the QCCP "of which" is empty — only an explicit False demotes
        assert row_0120["0200"][0] is None
        assert row_0120["0220"][0] is None
