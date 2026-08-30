"""Isolating mutation: the base-presence test scoped to the SHEET, not the template.

``_same_base`` asks whether the other side holds this leg's base exposure
anywhere on this TEMPLATE. Scope that question to the sheet the matrix is drawn
for and it reads plausibly — "is their leg in this part of the return?" — and
misses the canonical case outright: a guarantee leg is reported under the
GUARANTOR's exposure class, so it sits on a different sheet from the loan it was
split off, and their extract holds that loan whole one sheet over. The label
then goes back to ``ours_only``: "their extract has no such exposure", about an
exposure their extract holds in full.

Changes ONE thing: the ``sheet`` argument. ``_side_keys`` and ``_key_series``
run unmodified — the wrapper only redirects the argument, so a red is
attributable to the SCOPE and not to a transcription slip in a reimplementation
(README rule 1).

The redirect is armed only for the duration of ``_migration_pairs``, which is
the sole caller of ``_side_keys`` inside the matrix path. ``_decompose`` also
asks for the template-wide set (``their_all`` / ``our_all``) and must keep
getting it, or the waterfall's four-way partition would move too and the red set
would stop being about this one thing.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_same_base_is_group_scoped
"""

from __future__ import annotations

import pytest

#: The sheet the matrix is currently being built for, or ``None`` outside it.
_SHEET: list[str | None] = [None]

#: Redirected calls across the session. Session scope for the same reason the
#: other plugins here use it: most tests never build a matrix.
_APPLIED = [0]


@pytest.fixture(autouse=True)
def _the_base_is_looked_for_on_this_sheet_only():
    import rwa_calc.analysis.return_recon as module

    original_keys = module._side_keys
    original_pairs = module._migration_pairs

    def _scoped(side, key_column, template_id, sheet):  # noqa: ANN001, ANN202
        if sheet is None and _SHEET[0] is not None:
            _APPLIED[0] += 1
            return original_keys(side, key_column, template_id, _SHEET[0])
        return original_keys(side, key_column, template_id, sheet)

    def _pairs(recon, template_id, sheet, predicate_key, money_column):  # noqa: ANN001, ANN202
        _SHEET[0] = sheet
        try:
            return original_pairs(recon, template_id, sheet, predicate_key, money_column)
        finally:
            _SHEET[0] = None

    module._side_keys = _scoped
    module._migration_pairs = _pairs
    assert module._side_keys is not original_keys, "the patch did not take"
    try:
        yield
    finally:
        module._side_keys = original_keys
        module._migration_pairs = original_pairs


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the redirect never fired.

    Zero redirects means no matrix asked the base question in this run, so the
    colour is about the selection of tests and not about the scope.
    """
    if not _APPLIED[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_same_base_is_group_scoped: NOT APPLIED - no matrix asked the "
            "base-presence question in this run, so its colour means nothing."
        )
