"""
Taxonomy releases — which release a run uses for a module, and why.

Pipeline position:
    releases.json (the shipped releases) + taxonomy/data packs + boe/data rule books
        ->  resolve_release(module, taxonomy, today=...)  ->  Release
        ->  readers / xbrl / validate / filing / workflow.compare / dash

Key responsibilities:
- Name the releases this package ships (``releases.json``) and the ones it no
  longer ships (``retired.json``), so an error can say where a retired one went.
- Choose the release a run uses for one module. A version the user names is
  used as named. With none named, the default is the release LIVE for the
  module on the run date; a module with no live release takes its future
  release when there is exactly one. The default never chooses between
  several: with more than one candidate it stops and asks for a version.
- Take the taxonomy pack, the rule book, the Bank's validations deny list and
  the register of known issues with the published rules (``boe.issues``) from
  the SAME release, always.
- Say what each shipped release is for a module on the run date — live, future
  or superseded — from the dates in that release's pack for the module. The
  status belongs to a module, not to a release: one release can be live for
  one module and future for another.

Why the run date and not the return's reference date: the user picks the
release, and the reference date never does. A reference date the chosen release
does not cover for the module is reported by the structure check (``STR011``),
not used to choose. The deny list is read on the same date, for the same
reason: it is the gateway's configuration when the return is submitted.

References:
- docs/plans/taxonomy-release-selection.md — the decisions this module implements
- Bank of England Banking Taxonomy — each release's entry points and validity
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.catalogue import available_rulebooks, load_rulebook
from rwa_filer.boe.deny import DenyList, load_deny_list
from rwa_filer.boe.issues import IssueRegister, load_issues
from rwa_filer.taxonomy.pack import available_packs, load_packaged, pack_info

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.taxonomy.pack import PackInfo, TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: The package the two release files are package data of.
RELEASES_PACKAGE: Final = "rwa_filer"
#: The releases this package ships. The one file edited by hand to add or
#: retire a release; the contract tests hold the packaged data to it.
RELEASES_FILE: Final = "releases.json"
#: The releases this package no longer ships, and where each can still be had.
RETIRED_FILE: Final = "retired.json"
#: The layout of both files this module reads.
RELEASES_FORMAT: Final = 1

#: A module's status in a release on a date, from that release's pack dates.
STATUS_LIVE: Final = "live"
STATUS_FUTURE: Final = "future"
STATUS_SUPERSEDED: Final = "superseded"

#: Why a run uses the release it does.
CHOSEN_DEFAULT: Final = "default"
CHOSEN_VERSION: Final = "version"
#: A library caller passed the taxonomy pack itself.
CHOSEN_PACK: Final = "pack"

#: The command-line spelling of "name a release", quoted in error messages.
_ASK: Final = "--taxonomy VERSION"
#: ``.../mod/<module>.xsd`` — the module an entry point is for.
_ENTRY_POINT_MODULE: Final = re.compile(r"/mod/([A-Za-z0-9_]+)\.xsd$")


class ReleaseNotFoundError(LookupError):
    """No shipped release satisfies the request; the message says what would."""


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class ModuleRelease:
    """One shipped release that has a pack for a module, and the module's status in it.

    Attributes:
        version: The release, e.g. ``"4.1.1"``.
        info: That release's pack for the module: its entry point and dates.
        status: ``live``, ``future`` or ``superseded`` on the date it was
            worked out for.
    """

    version: str
    info: PackInfo
    status: str

    @property
    def summary(self) -> str:
        """The status and the date that decides it, e.g. ``future from 1 January 2027``."""
        return describe_status(self.status, self.info)


@dataclass(frozen=True)
class Release:
    """The release a run uses for one module, and why it was chosen.

    Attributes:
        version: The release.
        module: The reporting module.
        pack: The release's taxonomy pack for the module.
        rulebook: The release's rule book for the module, or ``None`` when the
            release packages none for it (only a pack a library caller built
            itself can lack one: every shipped pack has a rule book).
        status: The module's status in this release on ``run_date``.
        chosen_by: ``default``, ``version`` (named by the user) or ``pack``
            (a library caller passed the pack).
        run_date: The date the status was worked out for.
        shipped: Every shipped release with a pack for the module, newest
            first, with its status on ``run_date`` — this one included when it
            is shipped.
        deny_list: The Bank's validations deny list for the release
            (``boe.deny``): the rules its gateway no longer runs, or runs as
            warnings. Empty for a release that ships none — a pack a library
            caller built itself. Give one of your own with ``replace``.
        issues: The release's register of known issues with the published
            rules (``boe.issues``): what labels a result, never what decides
            it. Empty for a release that ships none. A caller's own rule book
            is protected by each issue's fingerprint: a rule that is not the
            one an issue pinned is never labelled.
    """

    version: str
    module: str
    pack: TaxonomyPack
    rulebook: RuleBook | None
    status: str
    chosen_by: str
    run_date: date
    shipped: tuple[ModuleRelease, ...] = ()
    deny_list: DenyList = field(default_factory=DenyList.empty)
    issues: IssueRegister = field(default_factory=IssueRegister.empty)

    @property
    def info(self) -> PackInfo:
        """The pack's identity and dates."""
        return self.pack.info

    @property
    def summary(self) -> str:
        """The module's status in this release, e.g. ``live since 1 January 2027``."""
        return describe_status(self.status, self.info)

    @property
    def others(self) -> tuple[ModuleRelease, ...]:
        """The other shipped releases with a pack for the module, newest first."""
        return tuple(option for option in self.shipped if option.version != self.version)

    def covers(self, reference_date: date) -> bool:
        """Whether this release's pack for the module applies on ``reference_date``."""
        return self.info.applies_to(reference_date)


@dataclass(frozen=True)
class RetiredRelease:
    """A release this package used to ship.

    Attributes:
        version: The release.
        last_shipped_in: The last rwa-filer version that shipped it.
        entry_points: The entry points of its modules, so a file naming one
            can be told where its taxonomy went.
    """

    version: str
    last_shipped_in: str
    entry_points: tuple[str, ...] = ()


def resolve_release(
    module: str | None,
    taxonomy: str | None = None,
    *,
    entry_point: str | None = None,
    today: date | None = None,
) -> Release:
    """The release a run uses for ``module``.

    Args:
        module: The reporting module (case-insensitive). May be ``None`` when
            ``entry_point`` is given: the entry point names the module.
        taxonomy: The release the user named, e.g. ``"4.1.1"``; ``None`` for
            the default (see the module docstring).
        entry_point: The entry point a file names in its ``schemaRef``. Only a
            release whose pack has exactly this entry point can read the file.
        today: The run date. Defaults to today.

    Raises:
        ReleaseNotFoundError: the named release is not shipped, has no pack for
            the module, or does not have the file's entry point; no shipped
            release has the module or the entry point; or no release was named
            and more than one could be the default.
    """
    run_date = today or date.today()
    named = taxonomy.strip() if taxonomy is not None else None
    if named is not None and named not in shipped_releases():
        raise ReleaseNotFoundError(_not_shipped(named, shipped_releases()))
    wanted = _module_for(module, entry_point, run_date)
    options = module_releases(wanted, today=run_date)
    if named is not None:
        return _named(wanted, named, options, entry_point, run_date)
    candidates = tuple(
        option
        for option in options
        if entry_point is None or option.info.entry_point == entry_point
    )
    if not candidates:
        raise ReleaseNotFoundError(_nothing_for(wanted, entry_point))
    return _release(_default(wanted, candidates), CHOSEN_DEFAULT, options, run_date)


def release_for_pack(
    pack: TaxonomyPack, rulebook: RuleBook | None = None, *, today: date | None = None
) -> Release:
    """The release of a pack a library caller passed in.

    The rule book defaults to the shipped one of the pack's release for its
    module — the same release, never another — and is ``None`` when the pack's
    version is not shipped or packages none for the module. The deny list and
    the issue register are the shipped ones of the pack's release, or empty
    when it is not shipped.
    """
    run_date = today or date.today()
    module = pack.info.module
    return Release(
        version=pack.info.version,
        module=module,
        pack=pack,
        rulebook=rulebook if rulebook is not None else release_rulebook(pack.info.version, module),
        status=status_on(pack.info, run_date),
        chosen_by=CHOSEN_PACK,
        run_date=run_date,
        shipped=module_releases(module, today=run_date),
        deny_list=release_deny_list(pack.info.version),
        issues=release_issues(pack.info.version),
    )


def choose_release(
    module: str,
    *,
    release: Release | None = None,
    pack: TaxonomyPack | None = None,
    rulebook: RuleBook | None = None,
    taxonomy: str | None = None,
    today: date | None = None,
) -> Release:
    """The release a library call uses, from whichever of its arguments was given.

    A resolved ``release`` is used as it is; a ``pack`` is used with its own
    release's rule book; otherwise the release is resolved for ``module`` from
    ``taxonomy``. A ``rulebook`` given beside either replaces the release's.

    Raises:
        ValueError: more than one of ``release``, ``pack`` and ``taxonomy`` was
            given — they are three ways of saying the same thing.
        ReleaseNotFoundError: see ``resolve_release``.
    """
    given = [name for name, value in (("release", release), ("pack", pack)) if value is not None]
    if taxonomy is not None:
        given.append("taxonomy")
    if len(given) > 1:
        raise ValueError(f"pass one of release, pack and taxonomy, not {' and '.join(given)}")
    if release is not None:
        return replace(release, rulebook=rulebook) if rulebook is not None else release
    if pack is not None:
        return release_for_pack(pack, rulebook, today=today)
    chosen = resolve_release(module, taxonomy, today=today)
    return replace(chosen, rulebook=rulebook) if rulebook is not None else chosen


# =============================================================================
# Supporting public functions
# =============================================================================


def shipped_releases() -> tuple[str, ...]:
    """The shipped release versions, newest first, compared as numbers."""
    versions = (str(entry["version"]) for entry in _releases_payload()["releases"])
    return tuple(sorted(versions, key=version_key, reverse=True))


def retired_releases() -> tuple[RetiredRelease, ...]:
    """The releases this package no longer ships, as ``retired.json`` records them."""
    return tuple(
        RetiredRelease(
            version=str(entry["version"]),
            last_shipped_in=str(entry["last_shipped_in"]),
            entry_points=tuple(entry.get("entry_points", ())),
        )
        for entry in _retired_payload()["releases"]
    )


def module_releases(module: str, *, today: date | None = None) -> tuple[ModuleRelease, ...]:
    """Every shipped release with a pack for ``module``, newest first, with its status."""
    run_date = today or date.today()
    found: list[ModuleRelease] = []
    for version in shipped_releases():
        info = pack_info(f"{module}-{version}".lower())
        if info is not None:
            found.append(ModuleRelease(version, info, status_on(info, run_date)))
    return tuple(found)


def release_rulebook(version: str, module: str) -> RuleBook | None:
    """The rule book of release ``version`` that covers ``module``, or ``None``."""
    wanted = module.upper()
    for file_name in available_rulebooks():
        if not file_name.endswith(f"-{version}.json"):
            continue
        rulebook = load_rulebook(file_name)
        if rulebook.taxonomy == version and wanted in (name.upper() for name in rulebook.modules):
            return rulebook
    return None


def release_deny_list(version: str) -> DenyList:
    """The Bank's validations deny list of release ``version``.

    Empty for a version this package does not ship. A shipped release with no
    packaged list raises: the wheel is broken, and that must be loud.

    Raises:
        DenyListNotFoundError: ``version`` is shipped but packages no deny list.
    """
    if version not in shipped_releases():
        return DenyList.empty(version)
    return load_deny_list(version)


def release_issues(version: str) -> IssueRegister:
    """The register of known issues with release ``version``'s published rules.

    Empty for a version this package does not ship. A shipped release with no
    packaged register raises: the wheel is broken, and that must be loud.

    Raises:
        IssueRegisterNotFoundError: ``version`` is shipped but packages none.
    """
    if version not in shipped_releases():
        return IssueRegister.empty(version)
    return load_issues(version)


def release_rulebooks(version: str) -> tuple[str, ...]:
    """The file names of release ``version``'s rule books, sorted."""
    return tuple(
        file_name
        for file_name in available_rulebooks()
        if file_name.endswith(f"-{version}.json") and load_rulebook(file_name).taxonomy == version
    )


def release_packs(version: str) -> tuple[PackInfo, ...]:
    """Release ``version``'s packs, ordered by module."""
    return tuple(info for info in available_packs() if info.version == version)


def status_on(info: PackInfo, day: date) -> str:
    """A module's status in a release on ``day``, from the release's pack dates."""
    if day < info.valid_from:
        return STATUS_FUTURE
    if info.valid_to is not None and day > info.valid_to:
        return STATUS_SUPERSEDED
    return STATUS_LIVE


def describe_status(status: str, info: PackInfo) -> str:
    """A status with the date that decides it, as the output and errors word it."""
    if status == STATUS_FUTURE:
        return f"future from {long_date(info.valid_from)}"
    if status == STATUS_SUPERSEDED and info.valid_to is not None:
        return f"superseded after {long_date(info.valid_to)}"
    if info.valid_to is not None:
        return f"live from {long_date(info.valid_from)} to {long_date(info.valid_to)}"
    return f"live since {long_date(info.valid_from)}"


def release_lines(release: Release) -> tuple[str, ...]:
    """What a run used and why, as the first lines of a command's text output.

    The first line names the release, how it was chosen and the module's status
    in it; one line follows for every other shipped release with the module,
    each with the option that selects it. For example::

        Taxonomy 4.1.1 (default) — PRA001 live since 1 January 2027
        Also shipped for PRA001: 4.2.0 future from 1 January 2028 (--taxonomy 4.2.0)
    """
    module = release.module
    chosen = {
        CHOSEN_DEFAULT: "default",
        CHOSEN_VERSION: "--taxonomy",
        CHOSEN_PACK: "pack given",
    }.get(release.chosen_by, release.chosen_by)
    first = f"Taxonomy {release.version} ({chosen}) — {module} {release.summary}"
    if release.chosen_by == CHOSEN_DEFAULT and release.status != STATUS_LIVE:
        first += "; no live release shipped"
    lines = [first]
    lead = f"Also shipped for {module}: "
    for index, option in enumerate(release.others):
        prefix = lead if index == 0 else " " * len(lead)
        lines.append(f"{prefix}{option.version} {option.summary} (--taxonomy {option.version})")
    return tuple(lines)


def release_record(release: Release, reference_date: date | None = None) -> dict[str, Any]:
    """The release as a JSON-ready record: what was used, its dates, and why.

    ``covers_reference_date`` is present when ``reference_date`` is given.
    """
    info = release.info
    record: dict[str, Any] = {
        "module": info.module,
        "version": release.version,
        "entry_point": info.entry_point,
        "status": release.status,
        "applies_from": info.valid_from.isoformat(),
        "applies_to": info.valid_to.isoformat() if info.valid_to else None,
        "run_date": release.run_date.isoformat(),
        "chosen_by": release.chosen_by,
        "shipped": [option.version for option in release.shipped],
    }
    if reference_date is not None:
        record["covers_reference_date"] = release.covers(reference_date)
    return record


def version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """A sort key comparing release versions as numbers, so 4.10.0 sorts after 4.9.0.

    A part that is not a number sorts after every number, by its text.
    """
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"[.\-]", version)
    )


def long_date(day: date) -> str:
    """``1 January 2027`` — how a date reads in output and errors."""
    return f"{day.day} {day:%B} {day.year}"


# =============================================================================
# Private helpers
# =============================================================================


def _module_for(module: str | None, entry_point: str | None, run_date: date) -> str:
    """The module a request is for: as given, else the one ``entry_point`` names.

    Raises:
        ValueError: neither was given (a programming error, not a data condition).
    """
    if module is not None:
        return module.upper()
    if entry_point is None:
        raise ValueError("resolve_release needs a module or an entry point")
    match = _ENTRY_POINT_MODULE.search(entry_point)
    if match is not None:
        named = match.group(1).upper()
        if module_releases(named, today=run_date):
            return named
    for info in available_packs():
        if info.entry_point == entry_point and info.version in shipped_releases():
            return info.module.upper()
    raise ReleaseNotFoundError(_nothing_for(None, entry_point))


def _named(
    module: str,
    version: str,
    options: tuple[ModuleRelease, ...],
    entry_point: str | None,
    run_date: date,
) -> Release:
    """The release the user named (a shipped one), or an error saying why it cannot be used."""
    match = next((option for option in options if option.version == version), None)
    if match is None:
        raise ReleaseNotFoundError(
            f"Taxonomy {version} has no pack for module {module}. {_shipped_for(module, options)}"
        )
    if entry_point is not None and match.info.entry_point != entry_point:
        raise ReleaseNotFoundError(
            f"Taxonomy {version} cannot read this file: the file names the entry point "
            f"{entry_point}, but {module} in {version} has the entry point "
            f"{match.info.entry_point}. The file can only be read against a release with "
            f"its own entry point. {_shipped_for(module, options)}"
        )
    return _release(match, CHOSEN_VERSION, options, run_date)


def _default(module: str, candidates: tuple[ModuleRelease, ...]) -> ModuleRelease:
    """The default among ``candidates`` (newest first): never a choice between several."""
    live = [option for option in candidates if option.status == STATUS_LIVE]
    if live:
        return live[0]
    future = [option for option in candidates if option.status == STATUS_FUTURE]
    if len(future) == 1:
        return future[0]
    if len(candidates) == 1:
        return candidates[0]
    several = future or list(candidates)
    listed = "; ".join(f"{option.version} ({option.summary})" for option in several)
    raise ReleaseNotFoundError(
        f"{module} has no live release and more than one other could apply; choose one "
        f"by its version ({_ASK}): {listed}."
    )


def _release(
    option: ModuleRelease, chosen_by: str, options: tuple[ModuleRelease, ...], run_date: date
) -> Release:
    """Load the chosen release's pack and rule book for the module."""
    module = option.info.module
    release = Release(
        version=option.version,
        module=module,
        pack=load_packaged(option.info.key),
        rulebook=release_rulebook(option.version, module),
        status=option.status,
        chosen_by=chosen_by,
        run_date=run_date,
        shipped=options,
        deny_list=release_deny_list(option.version),
        issues=release_issues(option.version),
    )
    logger.debug("taxonomy %s for %s (%s, %s)", release.version, module, release.status, chosen_by)
    return release


def _nothing_for(module: str | None, entry_point: str | None) -> str:
    """No shipped release has the module, or the entry point a file names."""
    shipped = ", ".join(shipped_releases()) or "none"
    if entry_point is not None:
        retired = next(
            (item for item in retired_releases() if entry_point in item.entry_points), None
        )
        if retired is not None:
            return (
                f"The file names the entry point {entry_point}, which only taxonomy "
                f"{retired.version} has, and that release is no longer shipped. "
                f"{_last_shipped(retired)}"
            )
        return (
            f"No shipped taxonomy release has the entry point {entry_point}. "
            f"Shipped releases: {shipped}."
        )
    return f"No shipped taxonomy release has module {module}. Shipped releases: {shipped}."


def _not_shipped(version: str, shipped: Iterable[str]) -> str:
    """The user named a release this package does not ship."""
    retired = next((item for item in retired_releases() if item.version == version), None)
    if retired is not None:
        return f"Taxonomy {version} is no longer shipped. {_last_shipped(retired)}"
    return (
        f"Taxonomy {version} is not shipped in this version of rwa-filer. "
        f"Shipped releases: {', '.join(shipped) or 'none'}."
    )


def _last_shipped(retired: RetiredRelease) -> str:
    """Where a retired release can still be had."""
    return (
        f"rwa-filer {retired.last_shipped_in} was the last version to ship it: "
        f'uvx "rwa-filer@{retired.last_shipped_in}" ... --taxonomy {retired.version}'
    )


def _shipped_for(module: str, options: tuple[ModuleRelease, ...]) -> str:
    """Which shipped releases have the module, as an error's closing sentence."""
    if not options:
        return f"No shipped release has module {module}."
    listed = "; ".join(f"{option.version} ({option.summary})" for option in options)
    return f"Shipped releases with {module}: {listed}."


@cache
def _releases_payload() -> Mapping[str, Any]:
    return _read(RELEASES_FILE)


@cache
def _retired_payload() -> Mapping[str, Any]:
    return _read(RETIRED_FILE)


def _read(file_name: str) -> Mapping[str, Any]:
    """One of the two release files, checked for the format this module reads."""
    resource = resources.files(RELEASES_PACKAGE).joinpath(file_name)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if payload.get("format") != RELEASES_FORMAT:
        raise ValueError(
            f"{file_name} format {payload.get('format')!r} is not supported "
            f"(this version reads format {RELEASES_FORMAT})"
        )
    return payload
