"""
Opening a return from a form — the one way every page that takes a file reads it.

Pipeline position:
    open form (upload or path, header fields)  ->  read_open_form  ->  OpenRequest
        ->  (in a dashboard task)  OpenRequest.open  ->  Workspace.open  ->  OpenedReturn

Key responsibilities:
- Take a file the browser uploaded, or the path of one on this machine, and
  the header a fact table needs, and make it ready to open in the workspace.
- Refuse, in words a person can act on, a fact table without its header or a
  reference date that is not a date — at once, before any reading is
  attempted, so a refusal the form can make is never kept waiting behind the
  long work of reading and validating.
- Keep the Open page and the Compare page reading a file the same way.
- Take, optionally, the columns to break a fact table down by and the column
  that holds each line's reference (``readers.detail``), and refuse at once an
  answer to a repeat that is not one of the choices.

References:
- rwa_filer.readers.open_source — what opening a file means
- dash.tasks — where the opening itself runs
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from rwa_filer.readers import DetailSpec, HeaderFields, carries_header

if TYPE_CHECKING:
    from starlette.datastructures import FormData

    from rwa_filer.dash.workspace import OpenedReturn, Workspace
    from rwa_filer.progress import ProgressCallback

#: The text fields of an open form, echoed back when a return cannot be opened.
FORM_FIELDS: Final = (
    "path",
    "entity",
    "reference_date",
    "module",
    "currency",
    "taxonomy",
    "breakdown",
    "line_ref",
    "on_repeat",
)


@dataclass(frozen=True)
class OpenRequest:
    """A return an open form names: checked, on this machine, ready to be opened.

    Attributes:
        path: Where the file is — the upload as saved in the workspace, or the
            path the person typed.
        name: The name the person knows the file by.
        fields: The header the person typed in.
        taxonomy: The release asked for, by version, or ``None`` for the default.
        detail: The columns to break the file down by, and its line reference;
            ``None`` to read it as a return, one row per cell.
    """

    path: Path
    name: str
    fields: HeaderFields
    taxonomy: str | None
    detail: DetailSpec | None = None

    def open(self, workspace: Workspace, progress: ProgressCallback | None = None) -> OpenedReturn:
        """Read and validate the file in ``workspace`` — the long part, told to ``progress``.

        Raises:
            ValueError: the file cannot be read.
            ReleaseNotFoundError: the taxonomy release could not be resolved.
        """
        return workspace.open(
            self.path,
            self.fields,
            name=self.name,
            taxonomy=self.taxonomy,
            progress=progress,
            detail=self.detail,
        )


async def read_open_form(workspace: Workspace, form: FormData) -> OpenRequest:
    """The return an open form names, saved into the workspace if it was uploaded.

    Raises:
        ValueError: nothing was named, the header is incomplete for a fact
            table, the date is not a date, or the breakdown asked for is not
            one that can be read.
    """
    values = form_values(form)
    fields = header_fields(values)
    detail = detail_spec(values)
    path, name = await _source(workspace, form, values["path"])
    if not carries_header(path) and not (fields.entity and fields.reference_date and fields.module):
        raise ValueError(
            f"{name} is a fact table, which carries no header: give the entity, the "
            "reference date and the module."
        )
    return OpenRequest(
        path=path, name=name, fields=fields, taxonomy=values["taxonomy"] or None, detail=detail
    )


def form_values(form: FormData) -> dict[str, str]:
    """The open form's text fields, trimmed."""
    return {name: str(form.get(name) or "").strip() for name in FORM_FIELDS}


def header_fields(values: dict[str, str]) -> HeaderFields:
    """The header the person typed in.

    Raises:
        ValueError: the reference date is not a date.
    """
    text = values.get("reference_date", "")
    try:
        reference_date = date.fromisoformat(text) if text else None
    except ValueError:
        raise ValueError(f"{text!r} is not a date: write it as YYYY-MM-DD.") from None
    return HeaderFields(
        entity=values.get("entity") or None,
        reference_date=reference_date,
        module=values.get("module") or None,
        currency=values.get("currency") or None,
    )


def detail_spec(values: dict[str, str]) -> DetailSpec | None:
    """The breakdown the person asked for, or ``None`` for none.

    Raises:
        ValueError: the answer to a repeated line reference is not a choice, or
            a column is named twice.
    """
    spec = DetailSpec.from_text(
        values.get("breakdown"), values.get("line_ref"), values.get("on_repeat")
    )
    return spec if spec.active else None


def page_number(text: str | None) -> int:
    """A page number from an address, 1 for anything that is not one."""
    try:
        return int(text) if text else 1
    except ValueError:
        return 1


async def _source(workspace: Workspace, form: FormData, path_text: str) -> tuple[Path, str]:
    """Where the return to open is, and the name to show it under.

    Raises:
        ValueError: neither a file nor a path was given.
    """
    upload = form.get("file")
    if isinstance(upload, UploadFile) and upload.filename:
        content = await upload.read()
        saved = await run_in_threadpool(workspace.save_upload, upload.filename, content)
        return saved, upload.filename
    if path_text:
        path = Path(path_text).expanduser()
        return path, path.name
    raise ValueError("Choose a file to open, or give the path of one on this machine.")
