"""
Opening a return from a form — the one way every page that takes a file reads it.

Pipeline position:
    open form (upload or path, header fields)  ->  open_from_form
        ->  Workspace.open  ->  OpenedReturn

Key responsibilities:
- Take a file the browser uploaded, or the path of one on this machine, and
  the header a fact table needs, and open it in the workspace.
- Refuse, in words a person can act on, a fact table without its header or a
  reference date that is not a date — before any reading is attempted.
- Keep the Open page and the Compare page reading a file the same way.

References:
- rwa_filer.readers.open_source — what opening a file means
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from rwa_filer.readers import HeaderFields, carries_header

if TYPE_CHECKING:
    from starlette.datastructures import FormData

    from rwa_filer.dash.workspace import OpenedReturn, Workspace

#: The text fields of an open form, echoed back when a return cannot be opened.
FORM_FIELDS: Final = ("path", "entity", "reference_date", "module", "currency")


async def open_from_form(workspace: Workspace, form: FormData) -> OpenedReturn:
    """Open the return an open form names.

    Raises:
        ValueError: nothing was named, the header is incomplete for a fact
            table, the date is not a date, or the file cannot be read.
        PackNotFoundError: no taxonomy pack for the module and date.
    """
    values = form_values(form)
    fields = header_fields(values)
    path, name = await _source(workspace, form, values["path"])
    if not carries_header(path) and not (fields.entity and fields.reference_date and fields.module):
        raise ValueError(
            f"{name} is a fact table, which carries no header: give the entity, the "
            "reference date and the module."
        )
    return await run_in_threadpool(workspace.open, path, fields, name=name)


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
