"""
Building a taxonomy release — the Bank's publication, compiled to package data.

Pipeline position:
    the Bank's downloads for one release (taxonomy package, DPM workbooks,
    validation workbooks, sample instances)
        ->  find_bank_files  ->  build_release  (offline, on an owner's machine)
        ->  taxonomy/data/<module>-<version>/ + boe/data/<family>-<version>.json
        ->  measure_release  ->  the numbers the release's tests hold it to
    ``scripts/build_filer_release.py`` is the command; this module is what it runs.

Key responsibilities:
- Find the publication's files by name anywhere under one folder, whether the
  Bank's zips are unpacked or not.
- Compile every module the annotated workbooks list, and package it only when
  every fact of the Bank's own sample instance for it is a data point of the
  compiled pack. A module that fails is not packaged; the reason is reported.
- Import every validation workbook with the taxonomy package's formula reach,
  under the release's own version — never the version in a file name, which
  can differ (4.1.1's financial statements workbook is named v4.1.0).
- Give each packaged module the end date its newer releases imply: the day
  before a newer release's pack for it applies, where that release changes the
  module's entry point. A module a newer release leaves unchanged stays open.
- Regenerate the template-level engine's Basel 3.1 extract (``rwa_filer.rules``)
  from the newest listed release's Banking Reporting workbook. That engine
  holds one release, not a choice of them.
- Remove the data of every release ``releases.json`` no longer lists — its
  validations deny list included — and record each in ``retired.json`` with
  the last rwa-filer version that shipped it, so an error can say where it went.
- Leave a release's validations deny list (``boe/data/deny/<version>.json``)
  alone when the release is rebuilt: it is not part of the Bank's publication
  of the release, but a separate, monthly one, imported on its own
  (``boe.deny_importer``; ``scripts/build_filer_release.py --deny-list``).
- Leave a release's register of known issues with the published rules
  (``boe/data/issues/<version>.json``) alone too: it is curated by hand from
  evidence, never built. A release built for the first time gets an EMPTY
  register, and a WARNING lists the open issues of the release before it, each
  to carry into the new register (with its example re-measured) or close.
- Measure a packaged release: the counts and the closed-by-formula register
  its tests are held to.
- Check a packaged release: rebuild it in a scratch folder and report every
  file that differs. The compiler and the importer are byte-reproducible, so
  any difference is a real one.

References:
- docs/plans/taxonomy-release-selection.md — §7.3 (the build), §7.4 (measurements)
- Bank of England Banking Taxonomy — taxonomy package, DPM dictionary, annotated
  templates, validation rule workbooks, sample instances
"""

from __future__ import annotations

import filecmp
import json
import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer import __version__
from rwa_filer.boe.catalogue import rulebook_from
from rwa_filer.boe.deny import DENY_DIRECTORY, deny_list_file
from rwa_filer.boe.formulas import DEFAULT_MEMBER
from rwa_filer.boe.grammar import references
from rwa_filer.boe.importer import import_workbook, rulebook_file_name, write_rulebook
from rwa_filer.boe.issues import ISSUES_DIRECTORY, ISSUES_FORMAT, issue_register_file
from rwa_filer.release import RELEASES_FILE, RELEASES_FORMAT, RETIRED_FILE, version_key
from rwa_filer.rules.importer import boe_extract_name, extract_boe, write_extract
from rwa_filer.taxonomy import _workbook
from rwa_filer.taxonomy.compiler import compile_pack
from rwa_filer.taxonomy.pack import PACK_FILE, SOURCE_LINKBASE, load_pack, write_pack
from rwa_filer.xbrl.reader import read_instance

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rwa_filer.boe.catalogue import Rule, RuleBook
    from rwa_filer.taxonomy.pack import TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: Where, under the package source folder, each kind of release data lives.
PACKS_SUBDIR: Final = Path("taxonomy") / "data"
RULEBOOKS_SUBDIR: Final = Path("boe") / "data"
DENY_SUBDIR: Final = Path("boe").joinpath(*DENY_DIRECTORY)
ISSUES_SUBDIR: Final = Path("boe").joinpath(*ISSUES_DIRECTORY)
RULES_SUBDIR: Final = Path("rules") / "data"

#: The layout of a measurement file.
MEASUREMENTS_FORMAT: Final = 1

#: How the Bank names its files. Matched case-insensitively against base names.
_ANNOTATED: Final = re.compile(r"annotated templates.*\.xlsx$", re.IGNORECASE)
_DICTIONARY: Final = re.compile(r"dpm dictionary.*\.xlsx$", re.IGNORECASE)
_VALIDATIONS: Final = re.compile(r"validations.*\.xlsx$", re.IGNORECASE)
#: The Banking Reporting workbook (not "Banking Reporting for SDDTs").
_BANKING_REPORTING: Final = re.compile(r"validations banking reporting v\d", re.IGNORECASE)
#: Every packaged Basel 3.1 template-level extract, of any release.
_TEMPLATE_EXTRACTS: Final = "basel31-boe-v*-credit-risk.json"
#: ``<LEI>_GB_banking_<MODULE>_<date>_<timestamp>.xbrl`` — the module without
#: its underscores (``PRAGAAP`` for ``PRA_GAAP``).
_SAMPLE: Final = re.compile(r"_banking_([A-Za-z0-9]+)_\d{4}-\d{2}-\d{2}_.*\.xbrl$")
#: ``.../<framework>/<YYYY-MM-DD>/mod/<module>.xsd`` — the date an entry point names.
_ENTRY_POINT_DATE: Final = re.compile(r"/(\d{4}-\d{2}-\d{2})/mod/[^/]+\.xsd$")
#: A taxonomy package declares itself in this member.
_PACKAGE_MANIFEST: Final = "META-INF/taxonomyPackage.xml"
#: Where the Bank's zips are unpacked, beside them.
_EXTRACTED: Final = ".rwa-filer-extracted"
#: A finding the XBRL reader makes for a fact that is no data point of the pack.
_NOT_A_DATAPOINT: Final = "XBR001"


class BankFilesError(ValueError):
    """The folder does not hold one complete publication."""


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class BankFiles:
    """One release's publication, as found on disk.

    Attributes:
        taxonomy_package: The XBRL taxonomy package (a zip).
        dictionary: The DPM dictionary workbook.
        annotated: The annotated-templates workbooks, one per framework.
        workbooks: The validation rule workbooks, one per framework.
        samples: Sample instance per module, keyed by the module code without
            underscores, upper case (``PRAGAAP``).
    """

    taxonomy_package: Path
    dictionary: Path
    annotated: tuple[Path, ...]
    workbooks: tuple[Path, ...]
    samples: Mapping[str, Path] = field(default_factory=dict)

    def sample_for(self, module: str) -> Path | None:
        """The sample instance for ``module``, or ``None``."""
        return self.samples.get(module.replace("_", "").upper())


@dataclass(frozen=True)
class ModuleBuild:
    """What building one module of the release did.

    Attributes:
        module: The module code.
        key: Its pack's directory name, when packaged.
        packaged: Whether its pack was written.
        reason: Why it was not, when it was not.
        tables: Tables in the compiled pack.
        cells: Reportable cells in the compiled pack.
    """

    module: str
    key: str | None
    packaged: bool
    reason: str | None = None
    tables: int = 0
    cells: int = 0


@dataclass(frozen=True)
class ReleaseBuild:
    """What building a release did, for the summary and the review.

    Attributes:
        version: The release.
        modules: One entry per module the annotated workbooks list.
        rulebooks: The rule-book files written.
        end_dates: The packs given an end date by this build, as
            ``(key, valid_to)``.
        retired: The releases removed because ``releases.json`` no longer lists
            them.
        template_extract: The template-level extract written, when this is the
            newest listed release.
    """

    version: str
    modules: tuple[ModuleBuild, ...]
    rulebooks: tuple[str, ...]
    end_dates: tuple[tuple[str, str], ...] = ()
    retired: tuple[str, ...] = ()
    template_extract: str | None = None

    @property
    def refused(self) -> tuple[ModuleBuild, ...]:
        """The modules not packaged, with their reasons."""
        return tuple(item for item in self.modules if not item.packaged)


def build_release(
    version: str,
    files: BankFiles,
    root: Path,
    *,
    applies_from: Mapping[str, date] | None = None,
    prune: bool = True,
) -> ReleaseBuild:
    """Build release ``version`` from the Bank's files into the package at ``root``.

    Args:
        version: The release, e.g. ``"4.2.0"``. Must be listed in ``root``'s
            ``releases.json``.
        files: The publication (``find_bank_files``).
        root: The package source folder (``.../src/rwa_filer``): the packs go
            under ``taxonomy/data``, the rule books under ``boe/data``.
        applies_from: Module -> the first reference date its pack applies to,
            where that is not the date its entry point names (4.1.1's Basel 3.1
            returns name 2026-08-17 and apply from 2027-01-01).
        prune: Remove the data of releases ``releases.json`` no longer lists,
            and record them in ``retired.json``.

    Raises:
        ValueError: ``version`` is not listed in ``releases.json``.
    """
    listed = listed_releases(root)
    if version not in listed:
        raise ValueError(f"{version} is not listed in {root / RELEASES_FILE}: add it first")
    packs_root, rulebooks_root = root / PACKS_SUBDIR, root / RULEBOOKS_SUBDIR
    _remove_release(version, packs_root, rulebooks_root)
    modules = _build_packs(version, files, packs_root, applies_from or {})
    rulebooks = _build_rulebooks(version, files, rulebooks_root)
    template_extract = _build_template_extract(version, files, root / RULES_SUBDIR, listed)
    _start_issue_register(version, root, listed)
    retired = _prune(listed, root) if prune else ()
    end_dates = reconcile_end_dates(packs_root, listed)
    logger.info(
        "built taxonomy %s: %d module(s) packaged, %d refused, %d rule book(s)",
        version,
        sum(item.packaged for item in modules),
        sum(not item.packaged for item in modules),
        len(rulebooks),
    )
    return ReleaseBuild(
        version=version,
        modules=modules,
        rulebooks=rulebooks,
        end_dates=end_dates,
        retired=retired,
        template_extract=template_extract,
    )


def check_release(
    version: str,
    files: BankFiles,
    root: Path,
    *,
    applies_from: Mapping[str, date] | None = None,
) -> list[str]:
    """Every difference between release ``version`` as packaged and as the files yield.

    The release is rebuilt in a scratch copy of ``root``; the packaged data is
    not touched. An empty list means the packaged release is exactly what the
    Bank's files give.
    """
    with tempfile.TemporaryDirectory(prefix="rwa-filer-check-") as scratch:
        copy = Path(scratch) / "rwa_filer"
        copy.mkdir()
        for name in (RELEASES_FILE, RETIRED_FILE):
            shutil.copy(root / name, copy / name)
        for subdir in (PACKS_SUBDIR, RULEBOOKS_SUBDIR, RULES_SUBDIR):
            if (root / subdir).is_dir():
                shutil.copytree(root / subdir, copy / subdir)
        build_release(version, files, copy, applies_from=applies_from, prune=False)
        return _differences(version, root, copy)


def find_bank_files(directory: Path) -> BankFiles:
    """The publication's files under ``directory``, found by the Bank's names.

    A zip that is not the taxonomy package (the DPM, validations and samples
    archives) is unpacked once, beside it, into ``.rwa-filer-extracted``; only
    its ``.xlsx`` and ``.xbrl`` members are written, under their base names.

    Raises:
        BankFilesError: no taxonomy package or DPM dictionary, more than one of
            either, or no annotated or validation workbook.
    """
    if not directory.is_dir():
        raise BankFilesError(f"not a folder: {directory}")
    packages = []
    for archive in sorted(directory.rglob("*.zip")):
        if _EXTRACTED in archive.parts:
            continue
        if _is_taxonomy_package(archive):
            packages.append(archive)
        else:
            _extract(archive, directory / _EXTRACTED / archive.stem)
    found = [path for path in sorted(directory.rglob("*")) if path.is_file()]
    dictionaries = [path for path in found if _DICTIONARY.search(path.name)]
    annotated = tuple(path for path in found if _ANNOTATED.search(path.name))
    workbooks = tuple(path for path in found if _VALIDATIONS.search(path.name))
    _one(packages, "taxonomy package (a zip holding META-INF/taxonomyPackage.xml)", directory)
    _one(dictionaries, "DPM dictionary workbook", directory)
    if not annotated or not workbooks:
        raise BankFilesError(
            f"{directory} holds {len(annotated)} annotated-templates and {len(workbooks)} "
            "validation workbook(s); a publication needs at least one of each"
        )
    samples: dict[str, Path] = {}
    for path in found:
        match = _SAMPLE.search(path.name)
        if match is not None:
            samples.setdefault(match.group(1).upper(), path)
    return BankFiles(
        taxonomy_package=packages[0],
        dictionary=dictionaries[0],
        annotated=annotated,
        workbooks=workbooks,
        samples=samples,
    )


# =============================================================================
# Supporting public functions
# =============================================================================


def listed_releases(root: Path) -> tuple[str, ...]:
    """The releases ``root``'s ``releases.json`` lists, newest first."""
    payload = _read_json(root / RELEASES_FILE)
    return tuple(
        sorted(
            (str(entry["version"]) for entry in payload["releases"]), key=version_key, reverse=True
        )
    )


def listed_applies_from(root: Path, version: str) -> dict[str, date]:
    """The applies-from exceptions ``releases.json`` records for ``version``."""
    payload = _read_json(root / RELEASES_FILE)
    entry = next((item for item in payload["releases"] if item["version"] == version), None)
    if entry is None:
        raise ValueError(f"{version} is not listed in {root / RELEASES_FILE}")
    return {
        module.upper(): date.fromisoformat(day)
        for module, day in (entry.get("applies_from") or {}).items()
    }


def reconcile_end_dates(packs_root: Path, listed: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """Give each listed release's pack the end date its newer releases imply.

    For each module, releases are taken oldest first. A pack ends the day
    before the next newer release's pack applies, when that release changes the
    module's entry point; otherwise it stays open — the release note, not the
    entry point, says when an unchanged module's newer rules take effect (plan
    §10, question 1). Only packs whose end date changes are rewritten.

    Returns:
        ``(key, valid_to)`` for each pack rewritten.
    """
    versions = sorted(listed, key=version_key)
    by_module: dict[str, list[tuple[str, Path, dict[str, Any]]]] = {}
    for version in versions:
        for pack_file in sorted(packs_root.glob(f"*-{version}/{PACK_FILE}")):
            info = _read_json(pack_file)["info"]
            if info["version"] == version:
                by_module.setdefault(info["module"].upper(), []).append((version, pack_file, info))
    changed: list[tuple[str, str]] = []
    for chain in by_module.values():
        for (_old, pack_file, info), (_new, _file, newer) in zip(chain, chain[1:], strict=False):
            wanted = None
            if info["entry_point"] != newer["entry_point"]:
                wanted = (date.fromisoformat(newer["valid_from"]) - timedelta(days=1)).isoformat()
            if info.get("valid_to") != wanted:
                _set_end_date(pack_file, wanted)
                changed.append((pack_file.parent.name, wanted or "open"))
    return tuple(changed)


def measure_release(
    version: str,
    root: Path,
    *,
    samples: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """The numbers release ``version``'s tests hold it to, measured on its packaged data.

    ``samples`` (module -> sample instance) adds what each sample reads back as;
    without them the ``samples`` section is empty and a caller keeps the one it
    measured before.
    """
    packs_root, rulebooks_root = root / PACKS_SUBDIR, root / RULEBOOKS_SUBDIR
    packs = {
        pack.info.module: pack
        for pack_dir in sorted(packs_root.glob(f"*-{version}"))
        if (pack := load_pack(pack_dir)).info.version == version
    }
    books = {
        path.name: book
        for path in sorted(rulebooks_root.glob(f"*-{version}.json"))
        if (book := rulebook_from(_read_json(path))).taxonomy == version
    }
    closed: dict[str, str] = {}
    for module, pack in sorted(packs.items()):
        book = next((item for item in books.values() if module in item.modules), None)
        for rule in book.enforced(module) if book is not None else ():
            if rule.parse_error is not None or not (rule.closed or rule.closed_by_variable):
                continue
            shut = closing_dimensions(pack, rule)
            if shut is not None:
                closed[f"{module}/{rule.rule_id}"] = ", ".join(sorted(shut))
    return {
        "format": MEASUREMENTS_FORMAT,
        "version": version,
        "rulebooks": {name: _measure_rulebook(book) for name, book in books.items()},
        "packs": {module: _measure_pack(pack) for module, pack in sorted(packs.items())},
        "closed_by_formula": closed,
        "samples": _measure_samples(packs, samples or {}),
    }


def closing_dimensions(pack: TaxonomyPack, rule: Rule) -> set[str] | None:
    """The closed dimensions that shut out EVERY cell some reference of ``rule`` names.

    ``None`` when each reference keeps at least one cell its formula admits. A
    static reading of the pack, with no return: which cells the rule text
    names, and whether the formula closes a dimension each of them carries.
    Such a rule is one neither the gateway nor this package can fire.
    """
    shut: set[str] = set()
    for reference in references(rule.tree):
        table = pack.tables.get(reference.table or "")
        if table is None:
            continue
        rows = {table.row_code(code) for code in reference.rows}
        columns = {table.column_code(code) for code in reference.columns}
        sheets = {table.sheet_code(code) for code in reference.sheets}
        named = pack.cells.filter(pl.col("table") == table.code)
        for column, accepted in (("row", rows), ("column", columns), ("sheet", sheets)):
            if accepted:
                named = named.filter(pl.col(column).is_in(sorted(accepted)))
        closed = rule.closed | rule.closed_by_variable.get(reference.variable or "", frozenset())
        hits = [
            closed
            & {
                dimension
                for dimension, member in pack.datapoints[point].dimensions
                if member.rpartition(":")[2] != DEFAULT_MEMBER
            }
            for point in named["datapoint"].unique().to_list()
        ]
        if hits and all(hits):
            shut |= set().union(*hits)
    return shut or None


def dump_measurements(measurements: Mapping[str, Any]) -> str:
    """A measurement file's text: sorted keys, one level per indent, a final newline."""
    return json.dumps(measurements, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


# =============================================================================
# Private helpers — building
# =============================================================================


def _build_packs(
    version: str, files: BankFiles, packs_root: Path, applies_from: Mapping[str, date]
) -> tuple[ModuleBuild, ...]:
    """Compile, check against its sample and write each module the workbooks list."""
    listed: dict[str, Path] = {}
    for workbook in files.annotated:
        for name in _workbook.read_annotated_workbook(workbook).contents.modules:
            listed.setdefault(name.upper(), workbook)
    results: list[ModuleBuild] = []
    for module, workbook in sorted(listed.items()):
        results.append(
            _build_pack(version, module, workbook, files, packs_root, applies_from.get(module))
        )
    return tuple(results)


def _build_pack(  # noqa: PLR0913 - one module's inputs, each needed
    version: str,
    module: str,
    workbook: Path,
    files: BankFiles,
    packs_root: Path,
    applies_from: date | None,
) -> ModuleBuild:
    """One module: compiled, held to the Bank's sample, then written or refused."""
    try:
        compiled = compile_pack(workbook, files.dictionary, files.taxonomy_package, module=module)
    except ValueError as error:
        return ModuleBuild(module, None, packaged=False, reason=f"does not compile: {error}")
    info = compiled["info"]
    module = str(info["module"])
    tables = len(compiled["tables"])
    cells = sum(len(table["cells"]) for table in compiled["tables"].values())
    if info["version"] != version:
        reason = f"the workbook is for taxonomy {info['version']}, not {version}"
        return ModuleBuild(module, None, packaged=False, reason=reason, tables=tables, cells=cells)
    valid_from = applies_from or _entry_point_date(str(info["entry_point"]))
    if valid_from is None:
        reason = f"no date in its entry point {info['entry_point']} and none in releases.json"
        return ModuleBuild(module, None, packaged=False, reason=reason, tables=tables, cells=cells)
    with tempfile.TemporaryDirectory(prefix="rwa-filer-pack-") as scratch:
        written = write_pack(compiled, Path(scratch) / "pack", valid_from=valid_from)
        reason = _sample_problem(module, load_pack(Path(scratch) / "pack"), files)
        if reason is None:
            shutil.copytree(Path(scratch) / "pack", packs_root / written.key)
    packaged = reason is None
    logger.info("%s %s: %s", module, version, "packaged" if packaged else f"refused — {reason}")
    return ModuleBuild(
        module,
        written.key if packaged else None,
        packaged=packaged,
        reason=reason,
        tables=tables,
        cells=cells,
    )


def _sample_problem(module: str, pack: TaxonomyPack, files: BankFiles) -> str | None:
    """Why the Bank's sample says the pack is incomplete, or ``None`` when it agrees."""
    sample = files.sample_for(module)
    if sample is None:
        return "no sample instance to check it against"
    reading = read_instance(sample, pack=pack)
    unplaced = next((item for item in reading.findings if item.code == _NOT_A_DATAPOINT), None)
    if unplaced is not None:
        return (
            f"the Bank's sample {sample.name} has facts that are no data point of the "
            f"compiled pack: {unplaced.message}"
        )
    return None


def _build_rulebooks(version: str, files: BankFiles, rulebooks_root: Path) -> tuple[str, ...]:
    """Import every validation workbook under ``version``, with formula reach."""
    written: list[str] = []
    for workbook in files.workbooks:
        rulebook = import_workbook(
            workbook, taxonomy_version=version, taxonomy_package=files.taxonomy_package
        )
        name = rulebook_file_name(rulebook)
        write_rulebook(rulebook, rulebooks_root / name)
        written.append(name)
        logger.info("%s: %d rule(s) from %s", name, len(rulebook["rules"]), workbook.name)
    return tuple(sorted(written))


def _build_template_extract(
    version: str, files: BankFiles, rules_root: Path, listed: tuple[str, ...]
) -> str | None:
    """Regenerate the template-level Basel 3.1 extract, for the newest listed release only.

    The extract records where its workbook came from. Rebuilt for a release it
    already holds, that provenance — the file it was read from and when it was
    retrieved — is kept, so the rebuild reproduces it; for a new release it is
    the Bank's file and today.
    """
    if not listed or version != listed[0]:
        return None
    workbook = next(
        (path for path in files.workbooks if _BANKING_REPORTING.search(path.name)), None
    )
    if workbook is None:
        logger.warning("no Banking Reporting workbook: the template-level extract is not rebuilt")
        return None
    target = rules_root / boe_extract_name(version)
    previous = _read_json(target)["source"] if target.is_file() else None
    payload = extract_boe(
        workbook,
        version=version,
        archive_member=workbook.name,
        retrieved=previous["retrieved"] if previous else date.today().isoformat(),
    )
    if previous is not None:
        payload["source"]["file"] = previous["file"]
    write_extract(payload, target)
    for stale in rules_root.glob(_TEMPLATE_EXTRACTS):
        if stale != target:
            stale.unlink()
    logger.info("%s: %d template-level rule(s)", target.name, len(payload["rules"]))
    return target.name


def _remove_release(version: str, packs_root: Path, rulebooks_root: Path) -> None:
    """Delete release ``version``'s packs and rule books, so a rebuild leaves none behind."""
    for pack_dir in packs_root.glob(f"*-{version}"):
        if (pack_dir / PACK_FILE).is_file() and _read_json(pack_dir / PACK_FILE)["info"][
            "version"
        ] == version:
            shutil.rmtree(pack_dir)
    for path in rulebooks_root.glob(f"*-{version}.json"):
        if _read_json(path)["source"]["taxonomy"] == version:
            path.unlink()


def _start_issue_register(version: str, root: Path, listed: tuple[str, ...]) -> None:
    """Give a release built for the first time an empty issue register; never overwrite one."""
    folder = root / ISSUES_SUBDIR
    path = folder / issue_register_file(version)
    if path.is_file():
        return
    folder.mkdir(parents=True, exist_ok=True)
    empty = {
        "format": ISSUES_FORMAT,
        "release": version,
        "publisher": "Bank of England",
        "documents": {},
        "checked_against": [],
        "issues": [],
        "appendices": [],
    }
    _write_text(path, json.dumps(empty, indent=1) + "\n")
    ordered = sorted(listed, key=version_key)
    older = ordered[: ordered.index(version)]
    previous = folder / issue_register_file(older[-1]) if older else None
    if previous is None or not previous.is_file():
        return
    still_open = [
        str(issue["id"])
        for issue in _read_json(previous).get("issues", [])
        if issue.get("status") in ("draft", "raised", "acknowledged")
    ]
    if still_open:
        logger.warning(
            "taxonomy %s starts with an empty issue register; re-confirm the %d open issue(s) "
            "of %s against it (carry each, re-measuring its example, or close it): %s",
            version,
            len(still_open),
            older[-1],
            ", ".join(still_open),
        )


def _prune(listed: tuple[str, ...], root: Path) -> tuple[str, ...]:
    """Remove every release on disk ``releases.json`` does not list; record it as retired."""
    packs_root, rulebooks_root = root / PACKS_SUBDIR, root / RULEBOOKS_SUBDIR
    on_disk: dict[str, list[str]] = {}
    for pack_file in sorted(packs_root.glob(f"*/{PACK_FILE}")):
        info = _read_json(pack_file)["info"]
        on_disk.setdefault(str(info["version"]), []).append(str(info["entry_point"]))
    for path in sorted(rulebooks_root.glob("*.json")):
        on_disk.setdefault(str(_read_json(path)["source"]["taxonomy"]), [])
    gone = sorted((version for version in on_disk if version not in listed), key=version_key)
    if not gone:
        return ()
    retired_file = root / RETIRED_FILE
    retired = _read_json(retired_file)
    known = {entry["version"] for entry in retired["releases"]}
    for version in gone:
        _remove_release(version, packs_root, rulebooks_root)
        # Only on retirement: a rebuild keeps the release's deny list and its
        # curated issue register (see above).
        (root / DENY_SUBDIR / deny_list_file(version)).unlink(missing_ok=True)
        (root / ISSUES_SUBDIR / issue_register_file(version)).unlink(missing_ok=True)
        if version not in known:
            retired["releases"].append(
                {
                    "version": version,
                    "last_shipped_in": __version__,
                    "entry_points": sorted(on_disk[version]),
                }
            )
        logger.info("retired taxonomy %s (last shipped in rwa-filer %s)", version, __version__)
    retired["releases"].sort(key=lambda entry: version_key(entry["version"]))
    _write_text(retired_file, json.dumps(retired, indent=2, ensure_ascii=True) + "\n")
    return tuple(gone)


def _differences(version: str, packaged: Path, rebuilt: Path) -> list[str]:
    """Every file of release ``version`` that differs between two package folders."""
    found: list[str] = []
    for subdir, pattern in (
        (PACKS_SUBDIR, f"*-{version}/*"),
        (RULEBOOKS_SUBDIR, f"*-{version}.json"),
        (RULES_SUBDIR, boe_extract_name(version)),
    ):
        ours = {path.relative_to(packaged): path for path in (packaged / subdir).glob(pattern)}
        theirs = {path.relative_to(rebuilt): path for path in (rebuilt / subdir).glob(pattern)}
        found += [f"only packaged: {name}" for name in sorted(set(ours) - set(theirs))]
        found += [f"only rebuilt: {name}" for name in sorted(set(theirs) - set(ours))]
        found += [
            f"differs: {name}"
            for name in sorted(set(ours) & set(theirs))
            if not filecmp.cmp(ours[name], theirs[name], shallow=False)
        ]
    return found


# =============================================================================
# Private helpers — measuring
# =============================================================================


def _measure_rulebook(book: RuleBook) -> dict[str, Any]:
    formulas = book.source.get("formulas") or {}
    return {
        "rules": len(book.rules),
        "enforced": {module: len(book.enforced(module)) for module in sorted(book.modules)},
        "formula_folder": formulas.get("folder"),
        "unreadable": sorted(rule.rule_id for rule in book.rules if rule.parse_error is not None),
    }


def _measure_pack(pack: TaxonomyPack) -> dict[str, Any]:
    return {
        "tables": len(pack.tables),
        "cells": pack.cells.height,
        "linkbase_cells": pack.cells.filter(pl.col("source") == SOURCE_LINKBASE).height,
        "datapoints": len(pack.datapoints),
        "filing_indicators": len(pack.filing_indicators),
        "applies_from": pack.info.valid_from.isoformat(),
        "entry_point": pack.info.entry_point,
    }


def _measure_samples(
    packs: Mapping[str, TaxonomyPack], samples: Mapping[str, Path]
) -> dict[str, Any]:
    measured: dict[str, Any] = {}
    for module, pack in sorted(packs.items()):
        sample = samples.get(module.replace("_", "").upper())
        if sample is None:
            continue
        reading = read_instance(sample, pack=pack)
        measured[module] = {
            "file": sample.name,
            "facts": reading.facts,
            "tables": len(reading.ret.tables),
            "filing_indicators": len(reading.ret.indicators or {}),
        }
    return measured


# =============================================================================
# Private helpers — files
# =============================================================================


def _entry_point_date(entry_point: str) -> date | None:
    match = _ENTRY_POINT_DATE.search(entry_point)
    return date.fromisoformat(match.group(1)) if match is not None else None


def _set_end_date(pack_file: Path, valid_to: str | None) -> None:
    """Rewrite ``pack.json``'s end date, in the form ``write_pack`` writes it."""
    payload = _read_json(pack_file)
    payload["info"]["valid_to"] = valid_to
    _write_text(pack_file, json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through an open handle, never ``Path.write_text``.

    The text is rebuilt from a file this module read. SonarCloud's taint
    analysis (``pythonsecurity:S2083``) reports read-back content reaching the
    data argument of a path-taking call as path traversal; writing through the
    handle leaves the path-taking call (``open``) with no tainted argument at
    all — the same remedy ``scripts/generate_regulatory_tables.py`` uses.
    """
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)


def _is_taxonomy_package(archive: Path) -> bool:
    with zipfile.ZipFile(archive) as bundle:
        return any(name.endswith(_PACKAGE_MANIFEST) for name in bundle.namelist())


def _extract(archive: Path, target: Path) -> None:
    """Write the archive's .xlsx and .xbrl members into ``target``, by base name only."""
    if target.is_dir():
        return
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = Path(member.filename).name
            if member.is_dir() or not name.lower().endswith((".xlsx", ".xbrl")):
                continue
            (target / name).write_bytes(bundle.read(member))


def _one(found: list[Path], what: str, directory: Path) -> None:
    if len(found) != 1:
        listed = ", ".join(path.name for path in found) or "none"
        raise BankFilesError(f"{directory} must hold exactly one {what}; found {listed}")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.name in (RELEASES_FILE, RETIRED_FILE) and payload.get("format") != RELEASES_FORMAT:
        raise ValueError(f"{path} is not a format-{RELEASES_FORMAT} release file")
    return payload
