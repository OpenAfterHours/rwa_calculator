"""Isolating mutation: the migration matrix's cells stop being links.

The plan's stated headline for this panel is that clicking an off-diagonal cell
lists the exposures that moved. Strip the anchor and every figure still renders,
every total still foots, the drill-down still works from a hand-typed URL, and
the page looks exactly as it did for the feature's whole life before this — a
grid of numbers with a tooltip. There is no visual tell for "not clickable"
beyond trying it, which is why this needs an assertion rather than a reviewer.

This mutation is on the TEMPLATE, which has no module attribute to patch, so it
wraps the Jinja loader and rewrites the source in memory. **Nothing on disk is
touched** — this tree is shared with other agents and a mutation left applied is
measured by all of them without their knowing.

Changes ONE thing: the anchor around a priced matrix cell. The cell's figure,
its heat shading, its tooltip and the empty cells' sentinel are untouched.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_matrix_cells_are_not_clickable
"""

from __future__ import annotations

import pytest
from jinja2 import BaseLoader

#: Verbatim from ``recon_templates.html``. Asserted present rather than replaced
#: hopefully: a fragment that has moved must fail loudly, not mutate nothing.
_LINK_OPEN = (
    '<a class="cell-link" href="{{ page_url }}?{{ query_base }}'
    "&amp;moved_from={{ cell.our_row_ref|urlencode }}"
    '&amp;moved_to={{ cell.their_row_ref|urlencode }}">{{ cell.display }}</a>'
)
_TEMPLATE = "recon_templates.html"


class _LoaderWithoutTheMatrixLink(BaseLoader):
    """The app's own loader, with the matrix cell's anchor cut out.

    Subclasses ``BaseLoader`` deliberately: inherited ``load`` is what makes the
    ``get_source`` below the one the environment actually calls. A wrapper that
    only delegates through ``__getattr__`` never gets called at all, which is a
    false green this directory has already paid for once.
    """

    def __init__(self, inner: BaseLoader) -> None:
        self._inner = inner
        self.rewrites = 0

    def get_source(self, environment, template):  # noqa: ANN001, ANN202
        source, filename, uptodate = self._inner.get_source(environment, template)
        if template == _TEMPLATE:
            assert _LINK_OPEN in source, (
                "the matrix cell link is not in recon_templates.html as written here, "
                "so this plugin would mutate nothing and report a false green"
            )
            source = source.replace(_LINK_OPEN, "{{ cell.display }}")
            self.rewrites += 1
        return source, filename, uptodate

    def list_templates(self) -> list[str]:
        return self._inner.list_templates()


_REWRITES = [0]


@pytest.fixture(autouse=True)
def _the_matrix_stops_being_clickable():
    from rwa_calc.ui.app import main as module

    environment = module.templates.env
    original = environment.loader
    mutant = _LoaderWithoutTheMatrixLink(original)
    environment.loader = mutant
    environment.cache.clear()
    try:
        yield
    finally:
        environment.loader = original
        environment.cache.clear()
        _REWRITES[0] += mutant.rewrites


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutation never reached the template at all."""
    if not _REWRITES[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_matrix_cells_are_not_clickable: NOT APPLIED - recon_templates.html "
            "was never rendered in this run, so its colour means nothing."
        )
