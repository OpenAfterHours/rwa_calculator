"""
What every dashboard page shares — the workspace, the templates, the layout.

Pipeline position:
    route handler  ->  DashContext.render  ->  Jinja template (extends base.html)

Key responsibilities:
- Render a page with what its layout needs on every page: the theme, the
  returns opened this session, and the sections a return's pages offer.
- Hand every page of a return one ``WorkingReturn``, so the layout's verdict
  is the one for the return a build would file now — with the drafted
  overrides applied — on whichever page it is drawn.
- Find the return a page address names, or answer "not found".
- Hold the layout's section list in one place, so adding a page is one line.

References:
- dash/templates/base.html — the layout these values fill
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.parse import urlencode

from starlette.datastructures import QueryParams
from starlette.exceptions import HTTPException
from starlette.templating import Jinja2Templates

from rwa_filer import __version__
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.referee_jobs import JobBoard
from rwa_filer.dash.security import TOKEN_PARAMETER, served_securely
from rwa_filer.dash.tasks import TaskBoard
from rwa_filer.release import shipped_releases
from rwa_filer.validate.review import SHOW_ALL, ReviewFilter

if TYPE_CHECKING:
    from datetime import date, datetime

    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.workspace import OpenedReturn, WorkingReturn, Workspace

TEMPLATES_DIR: Final = Path(__file__).resolve().parent / "templates"
STATIC_DIR: Final = Path(__file__).resolve().parent / "static"

THEME_COOKIE: Final = "rwa_filer_theme"
REVIEW_COOKIE: Final = "rwa_filer_review"
REVIEW_KEYS: Final = ("money", "bps", "hide_zero")
THEMES: Final = ("dark", "light")
#: The look a session starts in: the dark slate of ``rwa-ui`` and the docs.
DEFAULT_THEME: Final = "dark"
#: Seconds a form that starts long work waits for it before sending the person
#: to its progress page. Work quicker than this is answered as if it were not
#: in the background at all; slower work shows its progress within a second.
PROGRESS_AFTER_SECONDS: Final = 1.0


@dataclass(frozen=True)
class Section:
    """One page of an opened return, as the side navigation lists it."""

    key: str
    label: str
    suffix: str


#: The pages of an opened return, in the order the navigation lists them.
SECTIONS: Final = (
    Section("overview", "Overview", ""),
    Section("rules", "Rules", "/rules"),
    Section("templates", "Templates", "/templates"),
    Section("investigate", "Investigate", "/investigate"),
    Section("filing", "Build & sign off", "/filing"),
    Section("compare", "Compare", "/compare"),
    Section("referee", "Referee (Arelle)", "/referee"),
)


# =============================================================================
# Public entry point
# =============================================================================


class DashContext:
    """The workspace and templates a running dashboard renders its pages from.

    ``tasks`` holds the long work its forms start — opening, re-validating and
    building a return — and ``progress_after`` is how long a form waits for
    that work before showing its progress page instead.
    """

    def __init__(
        self, workspace: Workspace, *, progress_after: float = PROGRESS_AFTER_SECONDS
    ) -> None:
        self.workspace = workspace
        self.jobs = JobBoard(workspace.directory)
        self.tasks = TaskBoard()
        self.progress_after = progress_after
        self._flashes: dict[str, str] = {}
        self.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        self.templates.env.filters["count"] = format_count
        self.templates.env.filters["long_date"] = long_date
        self.templates.env.filters["moment"] = moment
        self.templates.env.filters["figure"] = figure
        # Jinja types its globals after its own defaults; ours are of other types.
        shared = cast("dict[str, Any]", self.templates.env.globals)
        shared.update(version=__version__, sections=SECTIONS, link=link)

    def render(
        self,
        request: Request,
        name: str,
        *,
        working: WorkingReturn | None = None,
        review: ReviewFilter | None = None,
        status_code: int = 200,
        **context: Any,
    ) -> Response:
        """Render ``name`` with the layout's shared values and ``context``.

        ``working`` is the return the page is about: the layout draws its
        ``current`` — the return with its drafted overrides applied — as
        ``current``, and says when that differs from the file as opened.
        """
        if review is None:
            review = review_of(request) if working else SHOW_ALL
        report = working.current.validation.report if working else None
        values = {
            "theme": theme_of(request),
            "opened_returns": self.workspace.returns(),
            "running_tasks": self.tasks.running(),
            "shipped_releases": shipped_releases(),
            "current": working.current if working else None,
            "working": working,
            "review": review,
            "review_query": review_query(request.url.query),
            "visible_rule_count": sum(
                r.status == STATUS_FAIL and r.unsatisfied > review.hidden_count(r)
                for r in (report.results if report else ())
            ),
            "section": "",
            **context,
        }
        return self.templates.TemplateResponse(request, name, values, status_code=status_code)

    def flash(self, return_id: str, message: str) -> None:
        """Keep a message for the next page drawn for ``return_id`` — a refusal
        made by a form whose answer is a redirect back to the page it came from."""
        self._flashes[return_id] = message

    def take_flash(self, return_id: str) -> str | None:
        """The message kept for ``return_id``, once."""
        return self._flashes.pop(return_id, None)

    def opened(self, request: Request) -> OpenedReturn:
        """The return the address names, as it was opened.

        Raises:
            HTTPException: 404, when no return is open under that id.
        """
        opened = self.workspace.get(str(request.path_params.get("return_id", "")))
        if opened is None:
            raise HTTPException(status_code=404, detail="No return is open under that address.")
        return opened

    def working(self, request: Request) -> WorkingReturn:
        """The return the address names, with the overrides drafted for it applied.

        Raises:
            HTTPException: 404, when no return is open under that id.
        """
        return self.workspace.working(self.opened(request))


def theme_of(request: Request) -> str:
    """The look the person chose, or the default."""
    chosen = request.cookies.get(THEME_COOKIE, DEFAULT_THEME)
    return chosen if chosen in THEMES else DEFAULT_THEME


def review_of(request: Request) -> ReviewFilter:
    """This browser's saved settings. The cookie path scopes them to one open return."""
    try:
        return read_review(QueryParams(request.cookies.get(REVIEW_COOKIE, "")))
    except ValueError:
        return SHOW_ALL


def read_review(params: QueryParams) -> ReviewFilter:
    return ReviewFilter.from_text(
        params.get("money", ""), params.get("bps", ""), params.get("hide_zero") == "1"
    )


def review_query(query: str) -> str:
    """Preserve tab-local navigation when saving a preference, including repeated fields."""
    return urlencode(
        [
            (k, v)
            for k, v in QueryParams(query).multi_items()
            if k not in REVIEW_KEYS and k != TOKEN_PARAMETER
        ]
    )


def save_review(request: Request, response: Response, return_id: str, review: ReviewFilter) -> None:
    path = f"/returns/{return_id}"
    if review.money is None and review.basis_points is None and not review.hide_zero_null:
        response.delete_cookie(
            REVIEW_COOKIE,
            path=path,
            httponly=True,
            secure=served_securely(request),
            samesite="strict",
        )
        return
    response.set_cookie(
        REVIEW_COOKIE,
        urlencode(
            {
                "money": str(review.money) if review.money is not None else "",
                "bps": str(review.basis_points) if review.basis_points is not None else "",
                "hide_zero": "1" if review.hide_zero_null else "",
            }
        ),
        path=path,
        httponly=True,
        secure=served_securely(request),
        samesite="strict",
    )


def link(path: str, **params: object) -> str:
    """``path`` with the given query parameters, leaving out the empty ones."""
    kept = [(name, str(value)) for name, value in params.items() if value not in (None, "")]
    return f"{path}?{urlencode(kept)}" if kept else path


def long_date(value: date) -> str:
    """``2027-03-31`` as ``31 March 2027`` (``%-d`` is not portable to Windows)."""
    return f"{value.day} {value:%B %Y}"


def moment(value: datetime) -> str:
    """A time as ``14 Nov 2026, 17:05 UTC``."""
    return f"{value.day} {value:%b %Y, %H:%M} UTC"


def figure(value: object) -> str:
    """A cell's value as a person reads it: grouped digits, text as it is, a dash for none."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,}"
    return str(value)


def format_count(value: int | float) -> str:
    """A count with grouped digits: ``1441`` reads ``1,441``."""
    return f"{value:,}"
