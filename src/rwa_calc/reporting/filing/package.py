"""
The filing package for a generated Basel 3.1 COREP estate.

Pipeline position:
    COREPTemplateBundle -> canonical.build_canonical_return
        -> rwa_filer.filing.build_filing -> <name>.xbrl (+ .zip) + manifest

Key responsibilities:
- Carry the generated estate through to the file a firm uploads: re-address it
  to the taxonomy, validate it, and have ``rwa-filer`` write the instance.
- Refuse, by default, to write a return that is missing figures. A figure this
  calculator computes and the taxonomy has no cell for cannot be filed; writing
  the rest would produce a file that validates and is quietly incomplete. The
  caller may ask for it anyway, and is told exactly what was left out.

What is decided here and what is not: whether the estate is COMPLETE in the
taxonomy's terms is a fact about this calculator's output, so it is decided
here. Whether the placed figures may be filed — structure, then the published
rules — is ``rwa-filer``'s decision, and is taken as given.

References:
- Bank of England Banking Taxonomy v4.1.1 (PRA001); BoE XBRL Filing Manual
- docs/development/workspace.md — the filing-mapping ratchet lists what has no place
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from rwa_calc.reporting.filing.canonical import build_canonical_return
from rwa_filer.filing import build_filing

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.filing.canonical import CanonicalMapping
    from rwa_filer.filing import FilingPackage
    from rwa_filer.model import ReturnHeader
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.xbrl.writer import InstanceOptions

logger = logging.getLogger(__name__)

#: Why nothing was written: non-zero figures have no cell in the taxonomy.
BLOCKED_BY_UNPLACED: Final = "unplaced_figures"


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class FilingOutcome:
    """What building the filing package for one estate produced.

    Attributes:
        mapping: The estate re-addressed to the taxonomy, with the cells that
            have no place there.
        package: ``rwa-filer``'s result — the validation, and the files where
            they were written. ``None`` when the estate was not complete and
            the build stopped before validation.
    """

    mapping: CanonicalMapping
    package: FilingPackage | None

    @property
    def written(self) -> bool:
        """Whether an instance was written."""
        return self.package is not None and self.package.written

    @property
    def blocked_by(self) -> str | None:
        """Why nothing was written: ``"unplaced_figures"``, ``"structure"``, ``"rules"``."""
        if self.package is None:
            return BLOCKED_BY_UNPLACED
        return self.package.blocked_by

    @property
    def unplaced_figures(self) -> pl.DataFrame:
        """The non-zero figures the written instance does not carry."""
        return self.mapping.unplaced_figures

    @property
    def is_complete(self) -> bool:
        """Whether every non-zero figure of the estate has a place in the taxonomy."""
        return self.unplaced_figures.is_empty()

    @property
    def is_submittable(self) -> bool:
        """Complete, written, and nothing found blocks submission."""
        return (
            self.is_complete
            and self.package is not None
            and self.package.written
            and self.package.validation.is_submittable
        )


def build_filing_package(
    corep: COREPTemplateBundle,
    header: ReturnHeader,
    directory: Path,
    *,
    pack: TaxonomyPack | None = None,
    options: InstanceOptions | None = None,
    name: str | None = None,
    allow_incomplete: bool = False,
    allow_rule_breaks: bool = False,
    always_zip: bool = False,
) -> FilingOutcome:
    """Write the filing package for a generated Basel 3.1 COREP bundle.

    Args:
        corep: The generated COREP bundle (Basel 3.1 framework).
        header: Who is reporting, for which date. Its module must be ``PRA001``.
        directory: Where the files go.
        pack: The taxonomy. Defaults to the packaged pack for the reference date.
        options: How numbers are stated in the instance.
        name: The files' base name.
        allow_incomplete: Write the instance even though non-zero figures have
            no place in the taxonomy. They are left out of the file and listed
            on the outcome.
        allow_rule_breaks: Write the instance even though a published rule is
            broken or rule coverage is insufficient.
        always_zip: Write a zip whatever the instance's size.

    Returns:
        A ``FilingOutcome``. Nothing is written while ``blocked_by`` is set.

    Raises:
        ValueError: ``header.module`` is not ``PRA001``.
        PackNotFoundError: no ``pack`` was given and none is packaged for the
            reference date.
    """
    mapping = build_canonical_return(corep, header, pack=pack)
    missing = mapping.unplaced_figures.height
    if missing and not allow_incomplete:
        logger.warning(
            "filing package not written: %d non-zero figure(s) have no place in the taxonomy",
            missing,
        )
        return FilingOutcome(mapping=mapping, package=None)

    package = build_filing(
        mapping.canonical,
        directory,
        pack=pack,
        options=options,
        name=name,
        allow_rule_breaks=allow_rule_breaks,
        always_zip=always_zip,
    )
    if package.written and missing:
        logger.warning(
            "filing package written WITHOUT %d non-zero figure(s) that have no place in the "
            "taxonomy",
            missing,
        )
    return FilingOutcome(mapping=mapping, package=package)
