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

The Bank's downloads for a release are read from ``.taxonomy/boe-banking-<version>/``
at the repository root (git-ignored, beside the referee's taxonomy package): the
taxonomy package zip, and the DPM, validations and sample-instances zips, or
their unpacked contents. The location is fixed on purpose — a path built from
the command line is a ``pythonsecurity:S8707`` sink (``arch_check`` check 19);
a caller that needs another folder imports ``rwa_filer.release_build`` and
passes it. Each build and each check writes the release's measurement file,
``packages/rwa-filer/tests/releases/<version>/measurements.json``: the numbers
its tests hold it to, re-measured, never typed.

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
import sys
import time
from pathlib import Path
from typing import Any

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
    args = parser.parse_args(argv)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    package_logger = logging.getLogger("rwa_filer")
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)
    version = RELEASES[args.version]
    source = DOWNLOADS[version]

    started = time.perf_counter()
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


def _write_measurements(version: str, samples: dict[str, Path] | Any) -> None:  # noqa: ANN401
    """Measure the packaged release and write its measurement file.

    Without the Bank's samples, the sample counts measured before are kept.
    """
    path = MEASUREMENTS[version]
    measured = measure_release(version, PACKAGE_ROOT, samples=samples)
    if not measured["samples"] and path.is_file():
        measured["samples"] = json.loads(path.read_text(encoding="utf-8")).get("samples", {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_measurements(measured), encoding="utf-8")
    print(f"Wrote {path.relative_to(_REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    sys.exit(main())
