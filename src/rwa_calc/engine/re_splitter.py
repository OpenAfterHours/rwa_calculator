"""
Back-compat shim for the real-estate loan-splitter stage.

The implementation moved to the stage package
``rwa_calc.engine.stages.re_split`` (migration Phase 4 Slice 4):
``splitter`` (``RealEstateSplitter`` + the split/allocation helpers),
``flagging`` (the classify-invoked candidate flagging), and the ``stage``
adapter. This module remains only so historical imports
(``from rwa_calc.engine.re_splitter import RealEstateSplitter``) keep
working; new code should import from the stage package directly.

References:
- CRR Art. 125/126; PRA PS1/26 Art. 124F/124H (RE exposure splitting)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging

from rwa_calc.engine.stages.re_split import RealEstateSplitter as RealEstateSplitter

logger = logging.getLogger(__name__)
