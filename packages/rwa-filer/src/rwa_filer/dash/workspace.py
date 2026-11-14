"""
The dashboard's workspace — the returns opened in one ``rwa-filer dash`` session.

Pipeline position:
    uploaded file / local path  ->  Workspace.open
        ->  readers.open_source  ->  validate.validate_return
        ->  OpenedReturn  ->  the dashboard's pages

Key responsibilities:
- Hold each opened return with the validation it was given, so that drawing a
  page never re-validates.
- Keep uploaded files under the one directory the session owns, under names a
  browser cannot steer outside it.
- Be safe to call from the server's worker threads.

References:
- rwa_filer.readers.open_source — how a named file is read, as the CLI reads it
- rwa_filer.validate.returns.validate_return — what "validated" means
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from rwa_filer.readers import open_source
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.readers import HeaderFields, SourceReading
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.returns import ReturnValidation

logger = logging.getLogger(__name__)

#: Characters an uploaded file's name may keep; any other run becomes ``_``.
_UNSAFE: Final = re.compile(r"[^A-Za-z0-9._-]+")
#: The name an upload is given when nothing of its own name survives.
_FALLBACK_NAME: Final = "upload"


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class OpenedReturn:
    """One return opened in the dashboard, with what validating it established.

    Attributes:
        return_id: The session's id for it, used in every page address.
        name: The name the person knows the file by.
        path: Where the file is on this machine.
        reading: What reading the file produced.
        validation: The validation, run once when the file was opened.
        opened_at: When it was opened.
    """

    return_id: str
    name: str
    path: Path
    reading: SourceReading
    validation: ReturnValidation
    opened_at: datetime

    @property
    def ret(self) -> CanonicalReturn:
        """The return itself."""
        return self.reading.ret

    @property
    def pack(self) -> TaxonomyPack:
        """The taxonomy the return was validated against."""
        return self.validation.pack


class Workspace:
    """The returns opened in this session, and the directory its files live in."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._returns: dict[str, OpenedReturn] = {}
        self._lock = threading.Lock()

    def open(
        self, path: Path, fields: HeaderFields | None = None, *, name: str | None = None
    ) -> OpenedReturn:
        """Read and validate ``path``, and keep it under a new id.

        Raises:
            ValueError: the file is missing, unsupported, lacks a header it
                needs, or is not readable as what its suffix says it is.
            PackNotFoundError: no taxonomy pack is packaged for the return's
                module and reference date.
        """
        reading = open_source(path, fields)
        validation = validate_return(reading.ret, reading.pack, source_findings=reading.findings)
        opened = OpenedReturn(
            return_id=secrets.token_hex(4),
            name=name or path.name,
            path=path,
            reading=reading,
            validation=validation,
            opened_at=datetime.now(UTC),
        )
        with self._lock:
            self._returns[opened.return_id] = opened
        logger.info("opened %s as %s", opened.name, opened.return_id)
        return opened

    def save_upload(self, filename: str, content: bytes) -> Path:
        """Write an uploaded file into the workspace and return where it went.

        Each upload gets a folder of its own, so two files of the same name
        never overwrite each other.
        """
        folder = self.directory / "uploads" / secrets.token_hex(4)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_file_name(filename)
        path.write_bytes(content)
        return path

    def get(self, return_id: str) -> OpenedReturn | None:
        """The return opened under ``return_id``, if there is one."""
        with self._lock:
            return self._returns.get(return_id)

    def returns(self) -> list[OpenedReturn]:
        """Every return opened in this session, the most recent first."""
        with self._lock:
            opened = list(self._returns.values())
        return sorted(opened, key=lambda item: item.opened_at, reverse=True)


def safe_file_name(filename: str) -> str:
    """``filename`` reduced to a bare name that cannot leave its folder.

    The browser sends the name it likes; only its last path component is kept,
    and only characters that need no quoting anywhere.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("_", base).strip("._")
    return cleaned or _FALLBACK_NAME
