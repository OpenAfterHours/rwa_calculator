"""
Classification domain package.

Pipeline position:
    ccr_sa_ccr -> classifier -> crm_processor

Layout:
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
``engine/re_split/flagging.py`` (Slice 4) and invoked from ``classifier``.

The ``run(ctx, rulepack, run_config)`` adapter that wires this domain into the
fold lives at ``engine/stages/classify.py``, not here: ``engine/stages/`` is
the wiring layer and holds nothing else. This package is the only home of the
classification domain; import ``ExposureClassifier`` from here.

References:
- CRR Art. 112: SA exposure classes; CRR Art. 147: IRB exposure classes
- docs/plans/architecture-review-2026-08-29.md §2 (the stages/domain split)
"""

from __future__ import annotations

from rwa_calc.engine.classify.classifier import ExposureClassifier as ExposureClassifier
