"""
Back-compat shim for the exposure classification stage.

The implementation moved to the stage package
``rwa_calc.engine.stages.classify`` (migration Phase 4 Slice 3):
``classifier`` (ExposureClassifier recipe), ``attributes``, ``subtypes``,
``re_split_flags``, ``permissions``, ``approach``, ``audit``, and the
``stage`` adapter. This module remains only so historical imports
(``from rwa_calc.engine.classifier import ExposureClassifier``) keep
working; new code should import from the stage package directly.

References:
- CRR Art. 112-134: Exposure classes
- CRR Art. 147-153: IRB approach assignment
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging

from rwa_calc.engine.stages.classify import ExposureClassifier as ExposureClassifier

logger = logging.getLogger(__name__)
