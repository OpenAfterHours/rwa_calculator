"""Isolating mutation: the pair table's loan link loses its ``return_to``.

The link the exposure column builds carries the cell it came from, so the loan
forensic's breadcrumb comes back to that exact cell. Strip the parameter and the
link still works, still resolves the right loan, and still renders a breadcrumb
-- the ``Referer`` fallback in ``main._loan_return_to`` catches it. That is the
point: the two paths are NOT the same, the fallback depends on a header a
browser may not send and a proxy may strip, and no page-level smoke test can
tell the explicit signal from the inferred one.

This mutation is on the TEMPLATE, which has no module attribute to patch, so it
wraps the Jinja loader and rewrites the source in memory. **Nothing on disk is
touched** -- which matters more than usual here, because this tree is shared
with other agents and a mutation left applied is measured by all of them.

Changes ONE thing: the presence of the query parameter on that one link.

TWO PROOFS THAT IT APPLIED, both learned from this plugin's own first run, which
came back a FALSE GREEN. The wrapper originally delegated everything but
``get_source`` through ``__getattr__``, so ``environment.get_template`` resolved
``load`` to the INNER loader's bound method -- which calls the inner
``get_source`` and never reached the mutation at all. The suite went 85 green
and the probe looked like evidence that nothing asserted the breadcrumb. It is
README mechanism 2 exactly, and it is why this file now (a) subclasses
``BaseLoader`` so ``load`` dispatches back to the override, and (b) counts its
own rewrites and FAILS the session if the count is zero.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_loan_link_drops_return_to
"""

from __future__ import annotations

import pytest
from jinja2 import BaseLoader

#: Verbatim from ``recon_templates.html``. Asserted present rather than replaced
#: hopefully: a fragment that has moved must fail loudly, not mutate nothing.
_RETURN_TO = (
    "&amp;return_to={{ (page_url ~ '?' ~ query_base ~ '&row=' ~ ex.row_ref "
    "~ '&col=' ~ ex.col_ref)|urlencode }}"
)
_TEMPLATE = "recon_templates.html"


class _LoaderWithoutTheBreadcrumb(BaseLoader):
    """The app's own loader, with the one parameter cut out of one template.

    Subclasses ``BaseLoader`` deliberately: inherited ``load`` is what makes
    ``get_source`` below the one the environment actually calls.
    """

    def __init__(self, inner: BaseLoader) -> None:
        self._inner = inner
        self.rewrites = 0

    def get_source(self, environment, template):  # noqa: ANN001, ANN202
        source, filename, uptodate = self._inner.get_source(environment, template)
        if template == _TEMPLATE:
            assert _RETURN_TO in source, (
                "the return_to fragment is not in recon_templates.html as written "
                "here, so this plugin would mutate nothing and report a false green"
            )
            source = source.replace(_RETURN_TO, "")
            self.rewrites += 1
        return source, filename, uptodate

    def list_templates(self) -> list[str]:
        return self._inner.list_templates()


#: Rewrites across the whole session. Counted at SESSION scope, not per test:
#: most tests in a run never render this page, so a per-test proof would error
#: on all of them and bury the one signal it exists to give.
_REWRITES = [0]


@pytest.fixture(autouse=True)
def _the_loan_link_forgets_where_it_came_from():
    from rwa_calc.ui.app import main as module

    environment = module.templates.env
    original = environment.loader
    mutant = _LoaderWithoutTheBreadcrumb(original)
    environment.loader = mutant
    environment.cache.clear()
    try:
        yield
    finally:
        environment.loader = original
        environment.cache.clear()
        _REWRITES[0] += mutant.rewrites


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutation never reached the template at all.

    A run that rendered the page zero times is green for a reason that has
    nothing to do with the breadcrumb, and reporting it as "no test detects
    this" is how a false green becomes cited evidence.
    """
    if not _REWRITES[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_loan_link_drops_return_to: NOT APPLIED — recon_templates.html "
            "was never rendered in this run, so its colour means nothing."
        )
