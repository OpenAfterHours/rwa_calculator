"""
Securities Financing Transaction (SFT) engine subpackage — FCCM EAD.

Pipeline position:
    HierarchyResolver -> [CCR pipeline adapter] -> sft_rows_to_exposures
        -> Classifier -> CRMProcessor -> SA/IRB/Slotting Calculators

Key responsibilities:
- Compute SFT Exposure at Default (EAD) via the Financial Collateral
  Comprehensive Method (FCCM) per CRR Art. 220-223:
      E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))   (Art. 223(5))
- Shape each netting-set EAD into a synthetic exposure row tagged
  ``ccr_method == "fccm_sft"`` / ``risk_type == "CCR_SFT"`` so the unified
  pipeline consumes it without SFT-aware special-casing downstream.

Extracted from ``engine/ccr`` (Phase 1 of the SFT / FCCM separation — see
docs/plans/sft-fccm-separation.md). FCCM shares no computational code with
SA-CCR and depends only on the CRM supervisory haircut tables
(``engine/crm/haircut_tables.py``), so it lives as a peer of ``engine/ccr``
rather than inside it.

References:
- CRR Art. 220(1)(a): single-counterparty SFT / master-netting-set scope
- CRR Art. 223(5): E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))
- CRR Art. 224 Table 1: supervisory haircuts (H_10) by type / CQS / maturity
- CRR Art. 226(2): H_m = H_10 × √(T_m / 10) liquidation-period scaling
- CRR Art. 271(2): SFT EAD via FCCM, not SA-CCR Art. 274
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from rwa_calc.engine.sft.fccm import SFT_TRANSACTION_TYPE, sft_rows_to_exposures  # noqa: E402

__all__ = [
    "SFT_TRANSACTION_TYPE",
    "sft_rows_to_exposures",
]
