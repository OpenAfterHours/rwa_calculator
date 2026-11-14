"""
What every dashboard page shares — the workspace, the templates, the layout.

Pipeline position:
    route handler  ->  DashContext.render  ->  Jinja template (extends base.html)

Key responsibilities:
- Render a page with what its layout needs on every page: the theme, the
  returns opened this session, and the sections a return's pages offer.
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

from starlette.exceptions import HTTPException
from starlette.templating import Jinja2Templates

from rwa_filer import __version__
from rwa_filer.dash.referee_jobs import JobBoard

if TYPE_CHECKING:
    from datetime import date, datetime

    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.workspace import OpenedReturn, Workspace

TEMPLATES_DIR: Final = Path(__file__).resolve().parent / "templates"
STATIC_DIR: Final = Path(__file__).resolve().parent / "static"

THEME_COOKIE: Final = "rwa_filer_theme"
THEMES: Final = ("dark", "light")
#: The look a session starts in: the dark slate of ``rwa-ui`` and the docs.
DEFAULT_THEME: Final = "dark"


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
    Section("filing", "Build & sign off", "/filing"),
    Section("compare", "Compare", "/compare"),
    Section("referee", "Referee (Arelle)", "/referee"),
)


# =============================================================================
# Public entry point
# =============================================================================


class DashContext:
    """The workspace and templates a running dashboard renders its pages from."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.jobs = JobBoard(workspace.directory)
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
        status_code: int = 200,
        **context: Any,
    ) -> Response:
        """Render ``name`` with the layout's shared values and ``context``."""
        values = {
            "theme": theme_of(request),
            "opened_returns": self.workspace.returns(),
            "current": None,
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
        """The return the address names.

        Raises:
            HTTPException: 404, when no return is open under that id.
        """
        opened = self.workspace.get(str(request.path_params.get("return_id", "")))
        if opened is None:
            raise HTTPException(status_code=404, detail="No return is open under that address.")
        return opened


def theme_of(request: Request) -> str:
    """The look the person chose, or the default."""
    chosen = request.cookies.get(THEME_COOKIE, DEFAULT_THEME)
    return chosen if chosen in THEMES else DEFAULT_THEME


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
