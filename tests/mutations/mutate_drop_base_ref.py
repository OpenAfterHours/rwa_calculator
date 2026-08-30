"""Isolating mutation: a plan builder that PROJECTS THE BASE REFERENCE AWAY.

Changes exactly one thing — every ``SheetPlan`` returned by every lineage
provider loses ``source_exposure_reference`` from its frame, which is the shape
a future template's plan builder could have. Membership is untouched (it is
built by ``cell_membership``, a separate path), so this isolates the plan
frame's carriage of the column from everything else.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_drop_base_ref
"""

from __future__ import annotations

from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def _plans_without_the_base_reference():
    import rwa_calc.analysis.return_recon as module

    original = module._provider

    def _projecting(template_id: str):
        provider = original(template_id)
        if provider is None:
            return None

        class _Shim:
            def __getattr__(self, name: str) -> object:
                return getattr(provider, name)

            def plans(self, results, cols, framework, errors):  # noqa: ANN001, ANN202
                return {
                    sheet: replace(
                        plan, frame=plan.frame.drop(module._BASE_KEY_COLUMN, strict=False)
                    )
                    for sheet, plan in provider.plans(results, cols, framework, errors).items()
                }

        return _Shim()

    module._provider = _projecting
    try:
        yield
    finally:
        module._provider = original
