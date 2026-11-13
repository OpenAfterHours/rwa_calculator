"""
The filing package — one return, validated, as the files a firm submits and keeps.

Pipeline position:
    CanonicalReturn -> validate_return -> xbrl.write_instance
        -> <name>.xbrl (+ <name>.zip) + <name>.manifest.json

Key responsibilities:
- Decide whether a return may be written. A structure finding always stops it:
  such a return cannot be expressed in the taxonomy at all. A broken published
  rule stops it by default, because the regulator would reject the file — and
  can be overridden, because a preparer sometimes needs the file to investigate.
- Write the instance, and a zip beside it when the Filing Manual requires one
  (over 10 MB) or the caller asks for one.
- Write a manifest: what was filed, against which taxonomy, with which checksum
  and under which validation result. It is the evidence that the file a firm
  uploaded is the file that was checked.
- Be reproducible. Nothing in the three files depends on when or where they
  were built unless the caller passes a creation time.

References:
- BoE XBRL Filing Manual v1.0.1: "Submission of an XBRL file" (files over
  10 MB are zipped), rule 1.1 (the ``.xbrl`` extension, inside a zip too)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from rwa_filer import __version__
from rwa_filer.validate.report import to_record
from rwa_filer.validate.returns import validate_return
from rwa_filer.xbrl.writer import GENERATOR_ID, InstanceOptions, write_instance

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.rules.catalogue import RuleSet
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import Finding
    from rwa_filer.validate.returns import ReturnValidation
    from rwa_filer.xbrl.writer import Instance

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: An instance larger than this MUST be zipped before upload (Filing Manual).
ZIP_THRESHOLD_BYTES: Final = 10 * 1024 * 1024

INSTANCE_SUFFIX: Final = ".xbrl"
ZIP_SUFFIX: Final = ".zip"
MANIFEST_SUFFIX: Final = ".manifest.json"
MANIFEST_FORMAT: Final = 1

#: Why a return was not written.
BLOCKED_BY_STRUCTURE: Final = "structure"
BLOCKED_BY_RULES: Final = "rules"

#: The timestamp of the instance inside a zip. Fixed, so a zip of the same
#: instance is the same zip; it is the earliest date the format can hold.
_ZIP_DATE: Final = (1980, 1, 1, 0, 0, 0)


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class FilingPackage:
    """What building a filing produced.

    Attributes:
        validation: The validation the decision rests on. Always present.
        blocked_by: ``None`` when the instance was written; otherwise
            ``"structure"`` or ``"rules"`` — what stopped it.
        instance: The written instance's counts, or ``None``.
        instance_path: The ``.xbrl`` file, or ``None``.
        zip_path: The ``.zip`` holding it, where one was written.
        manifest_path: The manifest. Written whenever the instance is.
    """

    validation: ReturnValidation
    blocked_by: str | None = None
    instance: Instance | None = None
    instance_path: Path | None = None
    zip_path: Path | None = None
    manifest_path: Path | None = None

    @property
    def written(self) -> bool:
        """Whether an instance was written."""
        return self.instance_path is not None

    @property
    def upload_path(self) -> Path | None:
        """The file to upload: the zip where there is one, else the instance."""
        return self.zip_path or self.instance_path


def build_filing(
    ret: CanonicalReturn,
    directory: Path,
    *,
    pack: TaxonomyPack | None = None,
    ruleset: RuleSet | None = None,
    options: InstanceOptions | None = None,
    name: str | None = None,
    allow_rule_breaks: bool = False,
    always_zip: bool = False,
    source_findings: Sequence[Finding] = (),
) -> FilingPackage:
    """Validate ``ret`` and, if it may be filed, write its filing package.

    Args:
        ret: The return.
        directory: Where the files go. Created if absent.
        pack: The taxonomy. Defaults to the packaged pack for the return's
            module and reference date.
        ruleset: The rules to run. Defaults to the module's packaged rule set.
        options: How numbers are stated in the instance.
        name: The files' base name. Defaults to
            ``<entity>_<module>_<reference date>``.
        allow_rule_breaks: Write the instance even though a published rule is
            broken or rule coverage is insufficient. The result still says so.
        always_zip: Write a zip whatever the instance's size.
        source_findings: Findings from reading the return's source, e.g. an
            XBRL instance. They count as structure findings.

    Returns:
        A ``FilingPackage``. Nothing is written when ``blocked_by`` is set.

    Raises:
        PackNotFoundError: no ``pack`` was given and none is packaged.
    """
    options = options or InstanceOptions()
    validation = validate_return(ret, pack, ruleset=ruleset, source_findings=source_findings)
    if validation.structure:
        return FilingPackage(validation=validation, blocked_by=BLOCKED_BY_STRUCTURE)
    if validation.blocking and not allow_rule_breaks:
        return FilingPackage(validation=validation, blocked_by=BLOCKED_BY_RULES)

    instance = write_instance(ret, validation.pack, options=options)
    base = name or default_name(ret)
    directory.mkdir(parents=True, exist_ok=True)
    instance_path = directory / f"{base}{INSTANCE_SUFFIX}"
    instance_path.write_bytes(instance.content)

    zip_path = None
    if always_zip or len(instance.content) > ZIP_THRESHOLD_BYTES:
        zip_path = directory / f"{base}{ZIP_SUFFIX}"
        _write_zip(zip_path, instance_path.name, instance.content)

    manifest_path = directory / f"{base}{MANIFEST_SUFFIX}"
    manifest = _manifest(ret, validation, instance, options, instance_path, zip_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    logger.info(
        "filing package written: %s (%d bytes, %d fact(s)); submittable=%s",
        instance_path.name,
        len(instance.content),
        instance.facts,
        validation.is_submittable,
    )
    return FilingPackage(
        validation=validation,
        instance=instance,
        instance_path=instance_path,
        zip_path=zip_path,
        manifest_path=manifest_path,
    )


def default_name(ret: CanonicalReturn) -> str:
    """``<entity>_<module>_<reference date>``, safe as a file name on any system."""
    header = ret.header
    entity = re.sub(r"[^A-Za-z0-9]+", "", header.entity_identifier) or "entity"
    module = re.sub(r"[^A-Za-z0-9]+", "", header.module) or "module"
    return f"{entity}_{module}_{header.reference_date.isoformat()}"


# =============================================================================
# Private helpers
# =============================================================================


def _write_zip(path: Path, member: str, content: bytes) -> None:
    """A zip holding the instance and nothing else, byte-identical for identical input."""
    info = zipfile.ZipInfo(member, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, content, compresslevel=9)


def _manifest(
    ret: CanonicalReturn,
    validation: ReturnValidation,
    instance: Instance,
    options: InstanceOptions,
    instance_path: Path,
    zip_path: Path | None,
) -> dict[str, Any]:
    """What was written, against what, with which checksum, under which verdict."""
    record = to_record(ret, validation)
    return {
        "format": MANIFEST_FORMAT,
        "generator": {"id": GENERATOR_ID, "version": __version__},
        "created_at": options.created_at.isoformat(timespec="seconds")
        if options.created_at
        else None,
        "header": record["header"],
        "taxonomy": record["taxonomy"],
        "instance": {
            "file": instance_path.name,
            "bytes": len(instance.content),
            "sha256": hashlib.sha256(instance.content).hexdigest(),
            "facts": instance.facts,
            "cells": instance.cells,
            "contexts": instance.contexts,
            "filing_indicators": list(instance.filing_indicators),
            "monetary_decimals": options.monetary_decimals,
            "percentage_decimals": options.percentage_decimals,
        },
        "zip": None
        if zip_path is None
        else {
            "file": zip_path.name,
            "bytes": zip_path.stat().st_size,
            "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        },
        "upload": (zip_path or instance_path).name,
        "validation": {
            "submittable": record["submittable"],
            "summary": record["summary"],
            "findings": record["findings"],
        },
    }
