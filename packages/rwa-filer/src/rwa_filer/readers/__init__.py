"""
Readers — turn a file into a canonical return.

Pipeline position:
    file (.parquet / .csv / .xlsx)  ->  read_return  ->  CanonicalReturn
    any supported file  ->  open_source  ->  SourceReading (return + its release)
        ->  validate.validate_return
    detail file (.parquet / .csv) + DetailSpec  ->  open_source
        ->  SourceReading (the summed return + the rows it was summed from)

Key responsibilities:
- Read each supported file format into the one canonical shape
  (``rwa_filer.model``). A reader's whole job is coordinates and types; it makes
  no judgment about the figures.
- Resolve, in ``open_source``, the taxonomy release a file is read against
  (``rwa_filer.release``): the one the person names, else the default for the
  return's module. An XBRL instance's release must also have the entry point
  the file names.
- Never lose a fact silently. A cell a reader cannot make sense of is kept, as
  text, so the structure check reports it — a reader that dropped it would turn
  a filer's typo into an unreported figure.
- Read a fact table as a detail when asked (``detail.DetailSpec``): several rows
  per cell, summed, with the columns that say where each row came from kept
  beside the return. Asked for nothing, a fact table is read exactly as before.

Module map:
- ``tabular`` — long-format fact tables: Parquet and CSV
- ``excel``   — the workbook layout (one worksheet per table and sheet), and
                the blank-template writer that produces it
- ``detail``  — a fact table of several rows per cell, summed into the return

References:
- rwa_filer.model — the canonical fact schema
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from rwa_filer.model import LEI_SCHEME, ReturnHeader
from rwa_filer.progress import PHASE_READING, Progress, notify
from rwa_filer.readers.detail import (
    DETAIL_SUFFIXES,
    DetailSpec,
    ReturnDetail,
    check_amounts,
    read_detail,
    require_fact_table,
    unread_columns,
)
from rwa_filer.readers.tabular import read_csv, read_parquet
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.progress import ProgressCallback
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import Finding

__all__ = [
    "INSTANCE_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "DetailSpec",
    "HeaderFields",
    "ReturnDetail",
    "SourceReading",
    "carries_header",
    "load_source",
    "open_source",
    "read_csv",
    "read_parquet",
    "read_return",
]

#: File suffixes ``read_return`` understands.
SUPPORTED_SUFFIXES: tuple[str, ...] = (".parquet", ".csv", ".xlsx")

#: An XBRL instance, bare or zipped — read by ``load_source``.
INSTANCE_SUFFIXES: tuple[str, ...] = (".xbrl", ".zip")


@dataclass(frozen=True)
class SourceReading:
    """A return read from a file, with what the reading itself established.

    Attributes:
        ret: The return.
        release: The taxonomy release the return is read against.
            ``open_source`` always sets it; ``load_source`` sets it for an XBRL
            instance (from its ``schemaRef``) and leaves it ``None`` for a
            file that names no taxonomy, whose release follows from the header.
        findings: What the source holds that could not be read as part of the
            module. Empty for a fact table or workbook, whose every cell is
            checked by the structure checks instead.
        detail: The rows the return was summed from, when the file was read
            as a detail (``open_source(..., detail=...)``); ``None`` otherwise.
        unread_columns: A fact table's columns that reading it as a return
            left out, as the file names them — the columns it could be broken
            down by. Empty for any other file, and for one read as a detail.
    """

    ret: CanonicalReturn
    release: Release | None = None
    findings: tuple[Finding, ...] = ()
    detail: ReturnDetail | None = None
    unread_columns: tuple[str, ...] = ()

    @property
    def pack(self) -> TaxonomyPack | None:
        """The release's taxonomy pack, or ``None`` while no release is chosen."""
        return self.release.pack if self.release is not None else None


@dataclass(frozen=True)
class HeaderFields:
    """Return-header fields a person supplies beside a file, each optional.

    A fact table needs the first three: it carries no header of its own. A
    workbook or an instance carries one, and any field given here overrides it.
    """

    entity: str | None = None
    reference_date: date | None = None
    module: str | None = None
    currency: str | None = None
    entity_scheme: str | None = None


def carries_header(path: Path) -> bool:
    """Whether a file of this type states its own return header."""
    suffix = path.suffix.lower()
    return suffix == ".xlsx" or suffix in INSTANCE_SUFFIXES


def open_source(
    path: Path,
    fields: HeaderFields | None = None,
    *,
    taxonomy: str | None = None,
    today: date | None = None,
    progress: ProgressCallback | None = None,
    detail: DetailSpec | None = None,
) -> SourceReading:
    """Read a file a person named, as ``rwa-filer validate`` and the dashboard do.

    Checks the file exists and is of a supported type, reads it, applies any
    header field given over the header the file states, and resolves the
    taxonomy release the return is read against.

    Args:
        path: The file.
        fields: Header fields given beside the file; each overrides the file's.
        taxonomy: The release to read it against, by version; ``None`` for the
            default (``rwa_filer.release``).
        today: The run date the default release is worked out for.
        progress: Told when the reading starts (``rwa_filer.progress``): a
            large workbook or instance takes seconds to read.
        detail: Read a fact table as a detail: its rows summed into cells, the
            breakdown columns and line reference it names kept beside the
            return (``readers.detail``). ``None``, or a spec that names no
            column, reads the file as before.

    Raises:
        ValueError: the file is missing, of an unsupported type, lacks a header
            it needs, or is not readable as what its suffix says it is; or a
            detail is asked of a file that is not a fact table, names a column
            the file does not have, or holds rows that cannot be summed
            (``readers.detail.DetailError``, a ``ValueError``).
        ReleaseNotFoundError: the release could not be resolved for the
            return's module.
    """
    fields = fields or HeaderFields()
    suffix = path.suffix.lower()
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    if suffix not in (*SUPPORTED_SUFFIXES, *INSTANCE_SUFFIXES):
        accepted = ", ".join((*SUPPORTED_SUFFIXES, *INSTANCE_SUFFIXES))
        raise ValueError(f"unsupported file type {path.suffix!r}; expected one of {accepted}")
    notify(progress, Progress(PHASE_READING, subject=path.name))
    if detail is not None and detail.active:
        require_fact_table(path)
        header = _header(fields, required=True)
        assert header is not None  # noqa: S101 - required=True raises rather than return None
        ret, rows = read_detail(path, header, detail)
        source = SourceReading(ret=ret, detail=rows)
    else:
        source = load_source(
            path, _header(fields, required=not carries_header(path)), taxonomy=taxonomy, today=today
        )
        if suffix in DETAIL_SUFFIXES:
            source = replace(source, unread_columns=unread_columns(path))
    overrides = {
        "entity_identifier": fields.entity,
        "reference_date": fields.reference_date,
        "module": fields.module,
        "currency": fields.currency,
        "entity_scheme": fields.entity_scheme,
    }
    changed = {name: value for name, value in overrides.items() if value}
    if changed:
        ret = source.ret
        source = replace(source, ret=replace(ret, header=replace(ret.header, **changed)))
    if source.release is None:
        source = replace(
            source, release=resolve_release(source.ret.header.module, taxonomy, today=today)
        )
    if source.detail is not None and source.pack is not None:
        check_amounts(source.detail, source.pack)
    return source


def load_source(
    path: Path,
    header: ReturnHeader | None = None,
    *,
    taxonomy: str | None = None,
    today: date | None = None,
) -> SourceReading:
    """Read any supported file: a fact table, a workbook, or an XBRL instance.

    Args:
        path: ``.parquet`` / ``.csv`` / ``.xlsx`` (see ``read_return``), or a
            ``.xbrl`` instance, or a ``.zip`` holding one.
        header: Required for Parquet and CSV. An instance carries its own.
        taxonomy: For an instance, the release to read it against, by version
            (it must have the file's entry point). Unused for any other file,
            whose release ``open_source`` resolves from the header.
        today: The run date an instance's default release is worked out for.

    Raises:
        ValueError: the suffix is not supported, a tabular file was given
            without a header, or an instance is not readable as one.
    """
    if path.suffix.lower() not in INSTANCE_SUFFIXES:
        return SourceReading(ret=read_return(path, header))
    from rwa_filer.xbrl.reader import read_instance

    reading = read_instance(path, taxonomy=taxonomy, today=today)
    return SourceReading(ret=reading.ret, release=reading.release, findings=reading.findings)


def read_return(path: Path, header: ReturnHeader | None = None) -> CanonicalReturn:
    """Read ``path`` into a canonical return, choosing the reader by suffix.

    Args:
        path: A ``.parquet`` or ``.csv`` long-format fact table, or a ``.xlsx``
            workbook in the template layout.
        header: Who is reporting and for which date. REQUIRED for Parquet and
            CSV, which carry facts only. A workbook carries its own header on
            its ``Return`` sheet; pass one to override it.

    Raises:
        ValueError: the suffix is not supported, or a tabular file was given
            without a header. (Usage errors — not conditions in the data.)
    """
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        from rwa_filer.readers.excel import read_workbook

        return read_workbook(path, header)
    if suffix not in (".parquet", ".csv"):
        supported = ", ".join(SUPPORTED_SUFFIXES)
        raise ValueError(f"Unsupported file type {suffix!r}; expected one of {supported}")
    if header is None:
        raise ValueError(
            f"{path.name} carries facts only: supply the return header "
            "(entity identifier, reference date, module)"
        )
    return read_parquet(path, header) if suffix == ".parquet" else read_csv(path, header)


def _header(fields: HeaderFields, *, required: bool) -> ReturnHeader | None:
    """A header from ``fields``, or ``None`` when the file supplies its own.

    Raises:
        ValueError: the file needs a header and the three required fields were
            not all given.
    """
    if not (fields.entity and fields.reference_date and fields.module):
        if required:
            raise ValueError(
                "a fact table carries no header: --entity, --reference-date and --module "
                "are all required"
            )
        return None
    return ReturnHeader(
        entity_identifier=fields.entity,
        reference_date=fields.reference_date,
        module=fields.module,
        currency=fields.currency or "GBP",
        entity_scheme=fields.entity_scheme or LEI_SCHEME,
    )
