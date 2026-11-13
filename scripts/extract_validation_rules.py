#!/usr/bin/env python3
"""
Re-extract the committed supervisory validation-rule JSON from the raw workbooks.

The extraction itself — reading a publisher's workbook, filtering to the
credit-risk templates, serialising deterministically — is
``rwa_filer.rules.importer``, and is available to anyone as
``rwa-filer rules import`` / ``rwa-filer rules check``. This script is the
repository's own binding of it: it knows where THIS checkout keeps the two raw
workbooks (``docs/assets/``, gitignored, fetched by ``scripts/download_docs.py``)
and where the committed extracts live (``rwa-filer``'s package data), so one
command refreshes or checks both.

- EBA DPM 3.0(3.0.1) validation rules  -> COREP C 02.00 / C 07.00 / C 08.0x /
  C 09.0x / C 34.xx  (the CRR framework)
- BoE banking_reporting v4.0.0 rules   -> OF02 / OF07 / OF08 / OF09 / C08.04 /
  C09.04 / C34.xx    (the Basel 3.1 framework)

The workbooks are xlsx (gitignored); the JSON extracts are the committed
artefact, so downstream consumers and CI never need the raw files.

Usage:
    uv run python scripts/extract_validation_rules.py
    uv run python scripts/extract_validation_rules.py --check
    uv run python scripts/extract_validation_rules.py --sample 3

References:
- docs/reference/validation-rules/index.md — provenance, schema, formula grammar
- packages/rwa-filer/src/rwa_filer/rules/importer.py — the extraction
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rwa_filer.rules import importer
from rwa_filer.rules.catalogue import EXTRACT_FILES, FRAMEWORK_BASEL_3_1, FRAMEWORK_CRR

# Project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "docs" / "assets"
# The extracts are PACKAGE DATA of rwa-filer, not documentation assets: the
# evaluator reads them at runtime through importlib.resources, so they must ship
# inside the rwa-filer wheel.
OUTPUT_DIR = PROJECT_ROOT / "packages" / "rwa-filer" / "src" / "rwa_filer" / "rules" / "data"

EBA_FILE = ASSETS_DIR / "eba-validation-rules.xlsx"
EBA_OUTPUT = OUTPUT_DIR / EXTRACT_FILES[FRAMEWORK_CRR]

BOE_FILE = ASSETS_DIR / "boe-validation-rules-banking-reporting-v4.0.0.xlsx"
BOE_OUTPUT = OUTPUT_DIR / EXTRACT_FILES[FRAMEWORK_BASEL_3_1]


def main() -> int:
    """Entry point: parse arguments and run the extraction workflow."""
    parser = argparse.ArgumentParser(
        description="Extract credit-risk supervisory validation rules to committed JSON.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-extract and fail non-zero if the committed JSON would change (for CI)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        metavar="N",
        help="print N parsed rules per source to stdout for inspection",
    )
    args = parser.parse_args()

    if not EBA_FILE.exists() or not BOE_FILE.exists():
        missing = [str(p) for p in (EBA_FILE, BOE_FILE) if not p.exists()]
        print("Missing source workbook(s):")
        for path in missing:
            print(f"  - {path}")
        print("\nRun: uv run python scripts/download_docs.py")
        return 1

    eba_payload = importer.extract_eba(EBA_FILE)
    boe_payload = importer.extract_boe(BOE_FILE)

    if args.sample:
        _print_samples(eba_payload, boe_payload, args.sample)

    outputs = ((EBA_OUTPUT, eba_payload), (BOE_OUTPUT, boe_payload))

    if args.check:
        return _check_outputs(outputs)

    for path, payload in outputs:
        importer.write_extract(payload, path)
        counts = payload["filter"]
        print(
            f"  wrote {path.relative_to(PROJECT_ROOT).as_posix()} "
            f"({counts['matched']} rules, {counts['live']} live, "
            f"{_fmt_size(path.stat().st_size)})"
        )
    return 0


def _check_outputs(outputs: tuple[tuple[Path, dict[str, Any]], ...]) -> int:
    """Compare freshly extracted payloads against the committed JSON."""
    stale: list[str] = []
    for path, payload in outputs:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        committed = path.read_text(encoding="utf-8") if path.exists() else None
        if committed is None:
            stale.append(f"{rel} (missing)")
        elif not importer.is_extract_current(payload, committed):
            stale.append(f"{rel} (out of date)")
        else:
            print(f"  ok    {rel}")

    if stale:
        print("\nCommitted extract does not match the source workbooks:")
        for item in stale:
            print(f"  - {item}")
        print("\nRegenerate with: uv run python scripts/extract_validation_rules.py")
        return 1
    return 0


def _print_samples(eba: dict[str, Any], boe: dict[str, Any], count: int) -> None:
    """Print a handful of parsed rules from each source for eyeballing."""
    print(f"\nEBA sample ({eba['filter']['matched']} matched, {eba['filter']['live']} live)")
    print("-" * 78)
    for rule in eba["rules"][:count]:
        print(json.dumps(rule, indent=2))

    print(f"\nBoE sample ({boe['filter']['matched']} matched, {boe['filter']['live']} live)")
    print("-" * 78)
    for rule in boe["rules"][:count]:
        print(json.dumps(rule, indent=2))
    print()


def _fmt_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


if __name__ == "__main__":
    sys.exit(main())
