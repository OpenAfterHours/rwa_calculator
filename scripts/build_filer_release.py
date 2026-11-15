"""
Build, check or re-measure one rwa-filer taxonomy release from the Bank's files.

The owner's command for packaging a Bank of England banking taxonomy release
into ``packages/rwa-filer``. It runs ``rwa_filer.release_build`` against this
checkout's package source; nothing here is shipped.

Usage:
    # Package a release listed in releases.json (and retire any no longer listed)
    uv run python scripts/build_filer_release.py 4.2.0 --from ~/downloads/boe-4.2.0

    # Rebuild in a scratch folder and fail on any file that differs
    uv run python scripts/build_filer_release.py 4.1.1 --from ~/downloads/boe-4.1.1 --check

    # Re-measure a packaged release without the Bank's files (keeps the sample counts)
    uv run python scripts/build_filer_release.py 4.1.1 --measure-only

``--from`` is a folder holding the Bank's downloads for the release — the
taxonomy package zip, and the DPM, validations and sample-instances zips (or
their unpacked contents). Each build and each check writes the release's
measurement file, ``packages/rwa-filer/tests/releases/<version>/measurements.json``:
the numbers its tests hold it to, re-measured, never typed.

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

_REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = _REPO_ROOT / "packages" / "rwa-filer" / "src" / "rwa_filer"
MEASUREMENTS_ROOT = _REPO_ROOT / "packages" / "rwa-filer" / "tests" / "releases"

from rwa_filer.release_build import (  # noqa: E402
    BankFilesError,
    build_release,
    check_release,
    dump_measurements,
    find_bank_files,
    listed_applies_from,
    measure_release,
)


def main(argv: list[str] | None = None) -> int:
    """Build, check or measure the release named on the command line."""
    parser = argparse.ArgumentParser(
        description="Build, check or re-measure one rwa-filer taxonomy release."
    )
    parser.add_argument("version", help="the release, as releases.json lists it, e.g. 4.2.0")
    parser.add_argument(
        "--from", dest="source", type=Path, metavar="DIR", help="the Bank's downloads"
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
    if not args.measure_only and args.source is None:
        parser.error("--from DIR is required unless --measure-only is given")

    started = time.perf_counter()
    try:
        applies_from = listed_applies_from(PACKAGE_ROOT, args.version)
        files = find_bank_files(args.source) if args.source is not None else None
    except (BankFilesError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.check:
        assert files is not None  # noqa: S101 — --from is required above
        differences = check_release(args.version, files, PACKAGE_ROOT, applies_from=applies_from)
        _write_measurements(args.version, files.samples)
        print(f"\nChecked taxonomy {args.version} in {time.perf_counter() - started:.0f}s")
        if differences:
            for difference in differences:
                print(f"  [DIFF] {difference}")
            return 1
        print("  [OK] the packaged release is exactly what the Bank's files yield")
        return 0

    if files is not None:
        build = build_release(args.version, files, PACKAGE_ROOT, applies_from=applies_from)
        _print_build(build)
    _write_measurements(args.version, files.samples if files is not None else None)
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
    path = MEASUREMENTS_ROOT / version / "measurements.json"
    measured = measure_release(version, PACKAGE_ROOT, samples=samples)
    if not measured["samples"] and path.is_file():
        measured["samples"] = json.loads(path.read_text(encoding="utf-8")).get("samples", {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_measurements(measured), encoding="utf-8")
    print(f"Wrote {path.relative_to(_REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    sys.exit(main())
