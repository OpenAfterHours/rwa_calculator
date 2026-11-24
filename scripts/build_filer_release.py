"""
Build, check or re-measure one rwa-filer taxonomy release from the Bank's files.

The owner's command for packaging a Bank of England banking taxonomy release
into ``packages/rwa-filer``. It runs ``rwa_filer.release_build`` against this
checkout's package source; nothing here is shipped.

Usage:
    # Package a release listed in releases.json (and retire any no longer listed)
    uv run python scripts/build_filer_release.py 4.2.0

    # Rebuild in a scratch folder and fail on any file that differs
    uv run python scripts/build_filer_release.py 4.1.1 --check

    # Re-measure a packaged release without the Bank's files (keeps the sample counts)
    uv run python scripts/build_filer_release.py 4.1.1 --measure-only

    # Import the Bank's validations deny list for a release (or --check it)
    uv run python scripts/build_filer_release.py 4.1.1 --deny-list [--check]

The Bank's downloads for a release are read from ``.taxonomy/boe-banking-<version>/``
at the repository root (git-ignored, beside the referee's taxonomy package): the
taxonomy package zip, and the DPM, validations and sample-instances zips, or
their unpacked contents. The location is fixed on purpose — a path built from
the command line is a ``pythonsecurity:S8707`` sink (``arch_check`` check 19);
a caller that needs another folder imports ``rwa_filer.release_build`` and
passes it. Each build and each check writes the release's measurement file,
``packages/rwa-filer/tests/releases/<version>/measurements.json``: the numbers
its tests hold it to, re-measured, never typed.

The deny list is not part of a release's publication: the Bank publishes it,
and the known-issues log beside it, between releases, and both change monthly.
``--deny-list`` reads the newest of each from ``docs/assets/`` (git-ignored;
``scripts/check_bank_publications.py`` fetches the Bank's current ones) — the
newest by the month and year in the Bank's file name — and writes, or with
``--check`` compares, ``packages/rwa-filer/src/rwa_filer/boe/data/deny/<version>.json``.
A file the pattern matches whose name gives no month and year (a ``-v2``
suffix) fails the command rather than being skipped: it may be the newest, and
skipping it would check an older list green. Every code the list names that
matches no rule of the release is printed, and kept in the file under
``unmatched``. The scheduled Bank Publications workflow runs ``--check`` for
every shipped release against the Bank's current files.

Exit codes:
    0  built, checked identical, or measured
    1  the check found a difference, or the folder is not a complete publication
    2  usage error

References:
- docs/plans/taxonomy-release-selection.md — §7 (making a release quick)
- rwa_filer.release_build — what each step does
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

from rwa_filer.boe.deny import deny_list_file
from rwa_filer.boe.deny_importer import (
    import_deny_list,
    is_deny_list_current,
    write_deny_list,
)
from rwa_filer.release_build import (
    BankFilesError,
    build_release,
    check_release,
    dump_measurements,
    find_bank_files,
    listed_applies_from,
    listed_releases,
    measure_release,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = _REPO_ROOT / "packages" / "rwa-filer" / "src" / "rwa_filer"
MEASUREMENTS_ROOT = _REPO_ROOT / "packages" / "rwa-filer" / "tests" / "releases"

#: The releases releases.json lists. The command line picks one BY NAME; every
#: path below is a constant of the release it names, not built from argv.
RELEASES: dict[str, str] = {version: version for version in listed_releases(PACKAGE_ROOT)}
DOWNLOADS: dict[str, Path] = {
    version: _REPO_ROOT / ".taxonomy" / f"boe-banking-{version}" for version in RELEASES
}
MEASUREMENTS: dict[str, Path] = {
    version: MEASUREMENTS_ROOT / version / "measurements.json" for version in RELEASES
}
DENY_LISTS: dict[str, Path] = {
    version: PACKAGE_ROOT / "boe" / "data" / "deny" / deny_list_file(version)
    for version in RELEASES
}
#: Where the Bank's between-release files are kept (git-ignored), and how each is named.
ASSETS = _REPO_ROOT / "docs" / "assets"
DENY_LIST_PATTERN = "boe-banking-validations-deny-list-*.xlsx"
KNOWN_ISSUES_PATTERN = "boe-banking-known-issues-*.xlsx"
#: Where the Bank publishes both files: the file name is appended.
BANK_FILES_URL = (
    "https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/"
    "regulatory-reporting/banking/"
)
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_DATED_NAME = re.compile(r"-(?P<month>[a-z]+)-(?P<year>\d{4})\.xlsx$")

#: The name of the handler ``main`` gives rwa-filer's logger, so a second run replaces it.
_HANDLER_NAME = "build_filer_release"


def main(argv: list[str] | None = None) -> int:
    """Build, check or measure the release named on the command line."""
    parser = argparse.ArgumentParser(
        description="Build, check or re-measure one rwa-filer taxonomy release."
    )
    parser.add_argument(
        "version", choices=sorted(RELEASES), help="the release, as releases.json lists it"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="rebuild in a scratch folder and compare"
    )
    mode.add_argument(
        "--measure-only", action="store_true", help="re-measure the packaged release only"
    )
    parser.add_argument(
        "--deny-list",
        action="store_true",
        help="import the Bank's validations deny list for the release from docs/assets "
        "(with --check, compare it with the packaged one) instead of building the release",
    )
    args = parser.parse_args(argv)
    _log_to_stdout()
    version = RELEASES[args.version]
    source = DOWNLOADS[version]

    started = time.perf_counter()
    if args.deny_list:
        if args.measure_only:
            parser.error("--deny-list does not measure: use it alone or with --check")
        return _deny_list(version, check=args.check)
    if args.measure_only:
        _write_measurements(version, None)
        print(f"\nMeasured taxonomy {version} in {time.perf_counter() - started:.0f}s.")
        return 0
    if not source.is_dir():
        print(
            f"error: put the Bank's downloads for {version} in "
            f"{source.relative_to(_REPO_ROOT).as_posix()}/ (the taxonomy package zip and the "
            "DPM, validations and sample-instances zips)",
            file=sys.stderr,
        )
        return 1
    try:
        applies_from = listed_applies_from(PACKAGE_ROOT, version)
        files = find_bank_files(source)
    except (BankFilesError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.check:
        differences = check_release(version, files, PACKAGE_ROOT, applies_from=applies_from)
        _write_measurements(version, files.samples)
        print(f"\nChecked taxonomy {version} in {time.perf_counter() - started:.0f}s")
        if differences:
            for difference in differences:
                print(f"  [DIFF] {difference}")
            return 1
        print("  [OK] the packaged release is exactly what the Bank's files yield")
        return 0

    build = build_release(version, files, PACKAGE_ROOT, applies_from=applies_from)
    _print_build(build)
    _write_measurements(version, files.samples)
    print(f"\nDone in {time.perf_counter() - started:.0f}s. Review the diff before committing.")
    return 0


class UndatedBankFileError(ValueError):
    """A file matches the Bank's naming pattern, but its name gives no month and year."""


def newest_bank_file(pattern: str, folder: Path) -> Path | None:
    """The newest of the Bank's files matching ``pattern`` in ``folder``, by the date it names.

    The Bank ends each file's name with the month and year it was published
    (``boe-banking-known-issues-november-2026.xlsx``); that date, not the name's
    alphabetical order, decides which is newest. ``None`` when nothing matches.

    Raises:
        UndatedBankFileError: a file matches ``pattern`` but its name gives no
            month and year. It may be the newest, so it is never skipped: a
            skipped ``...-december-2026-v2.xlsx`` would leave the November file
            checked green.
    """
    dated: list[tuple[tuple[int, int], Path]] = []
    undated: list[str] = []
    for path in sorted(folder.glob(pattern)):
        when = bank_file_date(path.name)
        if when is None:
            undated.append(path.name)
        else:
            dated.append((when, path))
    if undated:
        raise UndatedBankFileError(
            f"cannot date {', '.join(undated)} in {_shown(folder)}/: the Bank's files end "
            "-<month>-<year>.xlsx, and an undated one may be the newest. Rename it to the "
            "name the Bank publishes it under, or remove it"
        )
    return max(dated)[1] if dated else None


def bank_file_date(name: str) -> tuple[int, int] | None:
    """``(year, month index)`` from a Bank file name ending ``-<month>-<year>.xlsx``, or ``None``."""
    match = _DATED_NAME.search(name)
    if match is None or match.group("month") not in MONTHS:
        return None
    return int(match.group("year")), MONTHS.index(match.group("month"))


def _print_build(build: Any) -> None:  # noqa: ANN401 - a ReleaseBuild, imported late
    """The build's summary: what was packaged, what was refused and why."""
    print(f"\nTaxonomy {build.version}")
    for item in build.modules:
        if item.packaged:
            print(f"  packaged  {item.module:<10} {item.tables:>4} tables  {item.cells:>7} cells")
    for item in build.refused:
        print(f"  REFUSED   {item.module:<10} {item.reason}")
    print(f"  rule books: {', '.join(build.rulebooks)}")
    for key, valid_to in build.end_dates:
        print(f"  end date  {key}: {valid_to}")
    for version in build.retired:
        print(f"  retired   {version} (recorded in retired.json)")


def _deny_list(version: str, *, check: bool) -> int:
    """Import the newest deny list in ``docs/assets`` for ``version``; write or check it."""
    try:
        workbook = newest_bank_file(DENY_LIST_PATTERN, ASSETS)
        known_issues = newest_bank_file(KNOWN_ISSUES_PATTERN, ASSETS)
    except UndatedBankFileError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if workbook is None:
        print(
            f"error: no {DENY_LIST_PATTERN} in {_shown(ASSETS)}/ "
            "(uv run python scripts/check_bank_publications.py fetches the Bank's current one)",
            file=sys.stderr,
        )
        return 1
    imported = import_deny_list(
        workbook, version, known_issues=known_issues, url=BANK_FILES_URL + workbook.name
    )
    target = DENY_LISTS[version]
    shown = _shown(target)
    print(
        f"\nDeny list {workbook.name} (known issues: {known_issues.name if known_issues else 'none'})"
    )
    if check:
        committed = target.read_text(encoding="utf-8") if target.is_file() else None
        if is_deny_list_current(imported.payload, committed):
            print(f"  [OK] {shown} is exactly what the Bank's workbook yields")
            return 0
        print(f"  [DIFF] {shown} {_why_out_of_date(imported.payload, committed)}")
        return 1
    write_deny_list(imported.payload, target)
    print(f"Wrote {shown}. Review the diff before committing.")
    return 0


def _why_out_of_date(payload: dict[str, Any], committed: str | None) -> str:
    """The rest of a ``[DIFF]`` line: which of the Bank's two files the packaged list predates.

    A packaged list records the deny list AND the known-issues log it was built
    from (file name and sha256), and either moving fails ``--check``. The line
    names the one that moved, so a red run sends its reader to the right file;
    it named the deny-list workbook whichever had moved. When neither moved, the
    import itself changed.
    """
    current = payload.get("source") or {}
    if committed is None:
        return f"is missing: {current.get('file')} yields one"
    try:
        packaged = json.loads(committed).get("source") or {}
    except (json.JSONDecodeError, AttributeError):
        packaged = {}
    current_log = current.get("known_issues") or {}
    packaged_log = packaged.get("known_issues") or {}
    moved = [
        f"{now.get('file') or 'no known-issues log'} (the packaged list is from "
        f"{then.get('file') or 'none'})"
        for now, then in ((current, packaged), (current_log, packaged_log))
        if (now.get("file"), now.get("sha256")) != (then.get("file"), then.get("sha256"))
    ]
    if moved:
        return f"is out of date: the Bank's {' and '.join(moved)}"
    return (
        f"is out of date: it is from {current.get('file')} and "
        f"{current_log.get('file') or 'no known-issues log'}, but they now import to "
        "something else (the import changed)"
    )


def _write_measurements(version: str, samples: dict[str, Path] | Any) -> None:  # noqa: ANN401
    """Measure the packaged release and write its measurement file.

    Without the Bank's samples, the sample counts measured before are kept.
    """
    path = MEASUREMENTS[version]
    measured = measure_release(version, PACKAGE_ROOT, samples=samples)
    if not measured["samples"] and path.is_file():
        measured["samples"] = json.loads(path.read_text(encoding="utf-8")).get("samples", {})
    path.parent.mkdir(parents=True, exist_ok=True)
    # Through the handle: ``measured`` can carry counts read back from this file,
    # and read-back content must not reach a path-taking call (S2083).
    with path.open("w", encoding="utf-8") as handle:
        handle.write(dump_measurements(measured))
    print(f"Wrote {_shown(path)}")


def _log_to_stdout() -> None:
    """Print rwa-filer's progress lines on stdout, once however often ``main`` runs.

    ``scripts/check_bank_publications.py`` runs ``main`` once per shipped release
    in one process; a handler added on each run would print each line once per run.
    """
    package_logger = logging.getLogger("rwa_filer")
    for handler in [item for item in package_logger.handlers if item.name == _HANDLER_NAME]:
        package_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(message)s"))
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)


def _shown(path: Path) -> str:
    """``path`` as output names it: relative to the repository, where it is inside it."""
    return (
        path.relative_to(_REPO_ROOT).as_posix()
        if path.is_relative_to(_REPO_ROOT)
        else path.as_posix()
    )


if __name__ == "__main__":
    sys.exit(main())
