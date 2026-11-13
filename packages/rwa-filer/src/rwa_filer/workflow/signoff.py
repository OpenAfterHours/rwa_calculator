"""
Sign-off — an approval bound to the checksum of the file approved.

Pipeline position:
    <name>.manifest.json + files on disk  ->  sign_off   ->  <name>.signoff.json
    <name>.manifest.json                  ->  verify_package  ->  problems

Key responsibilities:
- Record who approved a filing, in what capacity and when — against the
  SHA-256 of the instance, not against a file name. A file changed after
  sign-off has a different checksum and the sign-off no longer applies to it.
- Refuse to sign what is not there to sign: a package whose files do not match
  their manifest, or — unless the approver explicitly acknowledges it — one
  the validation says is not submittable.
- Check a package before upload: instance, zip, manifest and sign-off must
  all describe the same bytes.

A sign-off is a recorded attestation, not a digital signature: it shows what
was approved and that it has not changed since, to anyone who trusts the
sign-off file. It does not prove who wrote that file.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

MANIFEST_SUFFIX: Final = ".manifest.json"
SIGNOFF_SUFFIX: Final = ".signoff.json"
SIGNOFF_FORMAT: Final = 1


class SignOffError(ValueError):
    """The package cannot be signed off as it stands."""


# =============================================================================
# Public API
# =============================================================================


@dataclass(frozen=True)
class SignOff:
    """A recorded approval of one filing package.

    Attributes:
        approver / role: Who approved, and in what capacity.
        at: When, ISO 8601.
        instance_sha256: The checksum of the instance approved.
        manifest_sha256: The checksum of the manifest it was approved under.
        submittable: Whether the validation in that manifest found nothing
            blocking.
        acknowledged_findings: The approver signed although it did not.
        statement: The approver's own words, if any.
        ledger_head: The last hash of the audit ledger at sign-off, if one was
            given — what makes later alteration of the ledger detectable.
    """

    approver: str
    role: str
    at: str
    instance_sha256: str
    manifest_sha256: str
    submittable: bool
    acknowledged_findings: bool = False
    statement: str | None = None
    ledger_head: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "format": SIGNOFF_FORMAT,
            "approver": self.approver,
            "role": self.role,
            "at": self.at,
            "instance_sha256": self.instance_sha256,
            "manifest_sha256": self.manifest_sha256,
            "submittable": self.submittable,
            "acknowledged_findings": self.acknowledged_findings,
            "statement": self.statement,
            "ledger_head": self.ledger_head,
        }


def signoff_path(manifest: Path) -> Path:
    """Where the sign-off for ``manifest`` is kept: beside it, ``<name>.signoff.json``."""
    name = manifest.name
    base = name[: -len(MANIFEST_SUFFIX)] if name.endswith(MANIFEST_SUFFIX) else manifest.stem
    return manifest.with_name(f"{base}{SIGNOFF_SUFFIX}")


def sign_off(  # noqa: PLR0913 - each argument is a separate fact about the approval
    manifest: Path,
    *,
    approver: str,
    role: str,
    at: datetime,
    statement: str | None = None,
    acknowledge_findings: bool = False,
    ledger_head: str | None = None,
) -> SignOff:
    """Record an approval of the package ``manifest`` describes; write it beside it.

    Raises:
        SignOffError: the approver or role is blank; the files on disk are not
            the ones the manifest describes; or the validation found something
            blocking and ``acknowledge_findings`` was not given.
    """
    if not approver.strip() or not role.strip():
        raise SignOffError("a sign-off names the approver and the capacity they approve in")
    problems = verify_package(manifest, require_signoff=False)
    if problems:
        raise SignOffError(f"the package does not verify and was not signed: {problems[0]}")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    submittable = bool(record["validation"]["submittable"])
    if not submittable and not acknowledge_findings:
        raise SignOffError(
            "the validation in the manifest found something that blocks submission; sign-off "
            "needs the findings to be acknowledged explicitly"
        )
    approval = SignOff(
        approver=approver.strip(),
        role=role.strip(),
        at=at.isoformat(timespec="seconds"),
        instance_sha256=record["instance"]["sha256"],
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        submittable=submittable,
        acknowledged_findings=not submittable,
        statement=statement.strip() if statement and statement.strip() else None,
        ledger_head=ledger_head,
    )
    signoff_path(manifest).write_text(
        json.dumps(approval.as_record(), indent=2) + "\n", encoding="utf-8"
    )
    logger.info("signed off %s by %s (%s)", manifest.name, approval.approver, approval.role)
    return approval


def read_signoff(manifest: Path) -> SignOff | None:
    """The sign-off recorded beside ``manifest``, or ``None`` if there is none.

    Raises:
        ValueError: the sign-off file is not one.
    """
    path = signoff_path(manifest)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return SignOff(
            approver=str(record["approver"]),
            role=str(record["role"]),
            at=str(record["at"]),
            instance_sha256=str(record["instance_sha256"]),
            manifest_sha256=str(record["manifest_sha256"]),
            submittable=bool(record["submittable"]),
            acknowledged_findings=bool(record.get("acknowledged_findings", False)),
            statement=record.get("statement"),
            ledger_head=record.get("ledger_head"),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"{path.name} is not a sign-off record: {error}") from error


def verify_package(manifest: Path, *, require_signoff: bool = True) -> list[str]:
    """Every way the package ``manifest`` describes fails to verify. Empty means intact.

    Checks that the instance and the zip on disk are the bytes the manifest
    records, and — where a sign-off is required or present — that it was given
    for exactly this instance under exactly this manifest.
    """
    if not manifest.is_file():
        return [f"{manifest.name} does not exist"]
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
        instance = record["instance"]
        archive = record.get("zip")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return [f"{manifest.name} is not a filing manifest: {error}"]

    problems = _file_problems(manifest.with_name(str(instance["file"])), instance, "instance")
    if archive is not None:
        problems += _file_problems(manifest.with_name(str(archive["file"])), archive, "zip")

    try:
        approval = read_signoff(manifest)
    except ValueError as error:
        return [*problems, str(error)]
    if approval is None:
        if require_signoff:
            problems.append("the package has not been signed off")
        return problems
    if approval.instance_sha256 != instance["sha256"]:
        problems.append("the sign-off was given for a different instance")
    if approval.manifest_sha256 != hashlib.sha256(manifest.read_bytes()).hexdigest():
        problems.append("the manifest has changed since the sign-off was given")
    return problems


# =============================================================================
# Private helpers
# =============================================================================


def _file_problems(path: Path, recorded: dict[str, Any], label: str) -> list[str]:
    if not path.is_file():
        return [f"the {label} {path.name} is missing"]
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != recorded["sha256"]:
        return [f"the {label} {path.name} is not the file the manifest describes"]
    return []
