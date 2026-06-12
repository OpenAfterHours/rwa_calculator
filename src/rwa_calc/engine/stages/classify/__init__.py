"""
Classification stage package (migration Phase 4 — mandatory stage anatomy).

Pipeline position:
    ccr_sa_ccr -> classifier -> crm_processor

Layout:
- ``stage``          — the uniform ``run(ctx, rulepack, run_config)`` adapter
- ``classifier``     — ``ExposureClassifier``: the stage recipe (classify
  sequencing, materialise + seal, bundle build)
- ``attributes``     — counterparty attribute join, SL join, independent
  flags, shared SME size-test expression
- ``subtypes``       — SME / retail / QRRE subtype classification,
  corporate→retail reclassification, IRB-class sync, B31 subclass
- ``permissions``    — model-permission resolution, permission
  expressions, CLS006 diagnostics
- ``approach``       — approach decision ladder + B31 Art. 147A
  restrictions
- ``audit``          — audit trail + input / BEEL data-quality warnings

RE loan-split candidate flagging is co-located with the splitter in
``stages/re_split/flagging.py`` (Slice 4) and invoked from ``classifier``.

``rwa_calc.engine.classifier`` remains as a thin back-compat shim
re-exporting ``ExposureClassifier`` from here.

References:
- CRR Art. 112: SA exposure classes; CRR Art. 147: IRB exposure classes
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

from rwa_calc.engine.stages.classify.classifier import ExposureClassifier as ExposureClassifier
from rwa_calc.engine.stages.classify.stage import run as run
