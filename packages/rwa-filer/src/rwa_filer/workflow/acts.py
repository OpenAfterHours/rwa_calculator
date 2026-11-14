"""
The recorded acts — a build, a sign-off, a verification — as one call each.

Pipeline position:
    rwa-filer build / signoff / verify   ─┐
    rwa-filer dash (Build & sign off)    ─┴─>  record_build / record_signoff / verify_filing
        ->  ledger.append_entry, signoff.sign_off, signoff.verify_package

Key responsibilities:
- Be the one place that decides what the audit ledger records for each act,
  so the command line and the dashboard cannot record the same act two ways.
- Record a sign-off in the ledger only once it is certain to be given: a
  refused sign-off leaves the ledger as it was.
- Check a package the way ``rwa-filer verify`` does — the files, the sign-off
  and the ledger together, including that the sign-off was recorded in this
  ledger and not another.

References:
- rwa_filer.workflow.ledger — the hash-chained record
- rwa_filer.workflow.signoff — the approval and the package check
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from rwa_filer.filing import MANIFEST_SUFFIX
from rwa_filer.workflow.ledger import (
    EVENT_ADJUSTMENT,
    EVENT_BUILD,
    EVENT_SIGNOFF,
    LEDGER_SUFFIX,
    append_entry,
    read_ledger,
    verify_ledger,
)
from rwa_filer.workflow.signoff import (
    SignOffError,
    check_signoff,
    read_signoff,
    sign_off,
    verify_package,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from rwa_filer.filing import FilingPackage
    from rwa_filer.workflow.adjustments import AppliedAdjustment
    from rwa_filer.workflow.signoff import SignOff

logger = logging.getLogger(__name__)


def ledger_beside(manifest: Path) -> Path:
    """The default ledger of the package ``manifest`` describes."""
    base = manifest.name.removesuffix(MANIFEST_SUFFIX)
    return manifest.with_name(f"{base}{LEDGER_SUFFIX}")


def ledger_for_instance(instance: Path) -> Path:
    """The default ledger of a package whose instance is ``instance``."""
    return instance.with_name(f"{instance.stem}{LEDGER_SUFFIX}")


def record_build(  # noqa: PLR0913 - each argument is a separate fact about the build
    ledger: Path,
    package: FilingPackage,
    *,
    applied: Sequence[AppliedAdjustment],
    forced: bool,
    author: str,
    at: datetime,
) -> None:
    """Record a written package in the ledger: its adjustments, then the build.

    Raises:
        ValueError: the package was not written, or the ledger cannot be read.
    """
    instance = package.instance
    if instance is None or package.instance_path is None:
        raise ValueError("nothing was written, so there is no build to record")
    if applied:
        append_entry(
            ledger,
            EVENT_ADJUSTMENT,
            {"adjustments": [item.as_record() for item in applied]},
            author=author,
            at=at,
        )
    append_entry(
        ledger,
        EVENT_BUILD,
        {
            "instance": package.instance_path.name,
            "sha256": hashlib.sha256(instance.content).hexdigest(),
            "facts": instance.facts,
            "submittable": package.validation.is_submittable,
            "forced": forced,
        },
        author=author,
        at=at,
    )


def record_signoff(  # noqa: PLR0913 - each argument is a separate fact about the approval
    manifest: Path,
    *,
    ledger: Path,
    approver: str,
    role: str,
    at: datetime,
    statement: str | None = None,
    acknowledge_findings: bool = False,
) -> SignOff:
    """Sign off the package ``manifest`` describes, recording it in ``ledger`` if there is one.

    Raises:
        SignOffError: the sign-off is refused (see ``signoff.check_signoff``),
            or the ledger does not verify. Nothing is recorded either way.
        ValueError: a file is not readable as what it should be.
    """
    has_ledger = ledger.is_file()
    if has_ledger and (problems := verify_ledger(ledger)):
        raise SignOffError(f"the audit ledger does not verify: {problems[0]}")
    check_signoff(manifest, approver=approver, role=role, acknowledge_findings=acknowledge_findings)
    entry = None
    if has_ledger:
        entry = append_entry(
            ledger,
            EVENT_SIGNOFF,
            {"manifest": manifest.name, "approver": approver, "role": role},
            author=approver,
            at=at,
        )
    return sign_off(
        manifest,
        approver=approver,
        role=role,
        at=at,
        statement=statement,
        acknowledge_findings=acknowledge_findings,
        ledger_head=entry.hash if entry is not None else None,
    )


def verify_filing(
    manifest: Path, *, ledger: Path | None = None, require_signoff: bool = True
) -> list[str]:
    """Every way a package, its sign-off and its ledger fail to agree. Empty means they do.

    ``ledger`` names the ledger to check; without one, the ledger beside the
    package is checked if there is one.
    """
    named = ledger is not None
    ledger = ledger or ledger_beside(manifest)
    problems = verify_package(manifest, require_signoff=require_signoff)
    if not named and not ledger.is_file():
        return problems
    problems += verify_ledger(ledger)
    try:
        approval = read_signoff(manifest)
    except ValueError:
        approval = None
    if approval is not None and approval.ledger_head is not None and not problems:
        hashes = {entry.hash for entry in read_ledger(ledger)}
        if approval.ledger_head not in hashes:
            problems.append("the audit ledger is not the one the sign-off was recorded in")
    return problems
