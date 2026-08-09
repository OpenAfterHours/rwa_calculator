"""
Back-compat shim for the exposure classification stage.

The implementation moved to the stage package
``rwa_calc.engine.stages.classify`` (migration Phase 4 Slice 3):
``classifier`` (ExposureClassifier recipe), ``attributes``, ``subtypes``,
``permissions``, ``approach``, ``audit``, and the ``stage`` adapter. The
real-estate candidate flagging the classifier invokes lives one package
over, in ``rwa_calc.engine.stages.re_split.flagging``.

This module forwards ``ExposureClassifier`` and nothing else. It is
scheduled for removal: the only remaining callers are test modules plus
the module-path string lists in ``tests/contracts/test_logging_contract.py``
and ``tests/integration/test_logging_pipeline.py``, and retiring it is a
mechanical import repoint held back only so it lands on a quiet tree.
Import from the stage package in new code; do not add callers here.

References:
- CRR Art. 112-134: Exposure classes
- CRR Art. 147-153: IRB approach assignment
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging

from rwa_calc.engine.stages.classify import ExposureClassifier as ExposureClassifier

logger = logging.getLogger(__name__)
