#!/usr/bin/env python3
"""
Download regulatory reference documents to docs/assets/.

Downloads PRA PS1/26, CRR, and EBA template documents needed for
development. Files with known direct URLs are fetched automatically;
remaining files are listed with manual download instructions.

Usage:
    python scripts/download_docs.py
    python scripts/download_docs.py --force
    python scripts/download_docs.py --list
    python scripts/download_docs.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "docs" / "assets"

USER_AGENT = "Mozilla/5.0 (rwa-calc document fetcher)"

BOE_PS126_BASE = (
    "https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january"
)
BOE_PS126_LANDING = (
    "https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement"
)
PRA_RULEBOOK = "https://www.prarulebook.co.uk/pra-rules/crr-firms"

BOE_CRR_BASE = (
    "https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2023/november/"
)

@dataclass(frozen=True)
class DocEntry:
    """A regulatory document to download or acquire manually."""

    filename: str
    description: str
    url: str | None  # None = manual download required
    source: str  # Landing page or source description for manual downloads


# ── Manifest ─────────────────────────────────────────────────────────────────
# All regulatory documents expected in docs/assets/.
# Entries with a url are downloaded automatically; others require manual download.

MANIFEST: list[DocEntry] = [
    # --- PS1/26 appendices (auto-downloadable) ---
    DocEntry(
        filename="ps126app1.pdf",
        description="PRA PS1/26 Appendix 1 — Basel 3.1 near-final rules",
        url=f"{BOE_PS126_BASE}/ps126app1.pdf",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-xx-credit-risk-sa-disclosure-instructions.pdf",
        description="PRA PS1/26 Annex XX credit risk sa disclosure instructions",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/2026/january/annex-xx-credit-risk-sa-disclosure-instructions.pdf",
        source=BOE_PS126_BASE,
    ),
    DocEntry(
        filename="ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf",
        description="PRA PS1/26 Annex XXII credit risk irb disclosure instructions",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/2026/january/annex-xxii-credit-risk-irb-disclosure-instructions.pdf",
        source=BOE_PS126_BASE,
    ),
    DocEntry(
        filename="ps1-26-annex-xxiv-credit-risk-irb-disclosure-instructions.pdf",
        description="PRA PS1/26 Annex XXIV credit risk irb disclosure instructions",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/2026/january/annex-xxiv-credit-risk-irb-disclosure-instructions.pdf",
        source=BOE_PS126_BASE,
    ),
    DocEntry(
        filename="ps126app17.pdf",
        description="PRA PS1/26 Appendix 17 — template guidance",
        url=f"{BOE_PS126_BASE}/ps126app17.pdf",
        source=BOE_PS126_LANDING,
    ),
    # --- PS1/26 annexes (manual download from landing page) ---
    DocEntry(
        filename="comparison-of-the-final-rules.pdf",
        description="Comparison of Basel 3.1 final rules",
        url=f"{BOE_PS126_BASE}/comparison-of-the-final-rules.pdf",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-ii-reporting-instructions.pdf",
        description="Basel 3.1 Annex II reporting instructions",
        url=f"{BOE_PS126_BASE}/annex-ii-reporting-instructions.pdf",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="crr-annex-ii-reporting-instructins.pdf",
        description="CRR Annex II reporting instructions",
        url=f"{BOE_CRR_BASE}/annex-ii-instructions-for-reporting-on-own-funds.pdf",
        source=PRA_RULEBOOK,
    ),
    DocEntry(
        filename="crr-annex-xx-instructions-regarding-disclosure.PDF",
        description="CRR Annex XX disclosure instructions",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2024/march/annex-xx-instructions-regarding-disclosure.pdf",
        source=PRA_RULEBOOK,
    ),
    # DocEntry(
    #     filename="crr-pillar3-irb-credit-risk-instructions.pdf",
    #     description="CRR Pillar 3 IRB credit risk instructions",
    #     url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/annex-pillar3-irb-credit-risk-instructions.pdf",
    #     source=PRA_RULEBOOK,
    # ),
    DocEntry(
        filename="crr-pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf",
        description="CRR Pillar 3 risk-weighted exposure and leverage ratio instructions",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf",
        source=PRA_RULEBOOK,
    ),
    DocEntry(
        filename="crr-pillar3-specialised-lending-instructions.pdf",
        description="CRR Pillar 3 specialised lending instructions",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/pillar3-specialised-lending-instructions.pdf",
        source=PRA_RULEBOOK,
    ),
    # --- Reporting templates (manual download) ---
    # DocEntry(
    #     filename="0F07 - annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx",
    #     description="Credit risk SA reporting template (OF 07.00)",
    #     url=None,
    #     source=BOE_PS126_LANDING,
    # ),
    # DocEntry(
    #     filename="CRR - corep-own-funds.xlsx",
    #     description="CRR COREP own funds template",
    #     url=None,
    #     source=PRA_RULEBOOK,
    # ),
    # DocEntry(
    #     filename="OF0801-annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx",
    #     description="Credit risk IRB reporting template (OF 08.01)",
    #     url=None,
    #     source=BOE_PS126_LANDING,
    # ),
    # DocEntry(
    #     filename="OF0802-annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx",
    #     description="Credit risk IRB reporting template (OF 08.02)",
    #     url=None,
    #     source=BOE_PS126_LANDING,
    # ),
]


# ── Public API ───────────────────────────────────────────────────────────────


def main() -> int:
    """Entry point: parse arguments and run the download workflow."""
    parser = argparse.ArgumentParser(
        description="Download regulatory reference documents to docs/assets/.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download files even if they already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be done without downloading",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list all documents in the manifest and exit",
    )
    args = parser.parse_args()

    if args.list:
        _print_manifest()
        return 0

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    results = download_documents(MANIFEST, ASSETS_DIR, force=args.force, dry_run=args.dry_run)
    print_summary(results)

    failures = [r for r in results if r["status"] == "failed"]
    return 1 if failures else 0


def download_documents(
    manifest: list[DocEntry],
    assets_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict[str, str | int]]:
    """Iterate the manifest and download files with known URLs.

    Returns a list of result dicts with keys: filename, status, detail, bytes.
    """
    results: list[dict[str, str | int]] = []

    for entry in manifest:
        dest = assets_dir / entry.filename

        if entry.url is None:
            results.append(
                {
                    "filename": entry.filename,
                    "status": "manual",
                    "detail": entry.source,
                    "bytes": 0,
                }
            )
            continue

        if dest.exists() and not force:
            size = dest.stat().st_size
            print(f"  skip     {entry.filename} (already exists, {_fmt_size(size)})")
            results.append(
                {
                    "filename": entry.filename,
                    "status": "skipped",
                    "detail": "already exists",
                    "bytes": size,
                }
            )
            continue

        if dry_run:
            print(f"  would download  {entry.filename}")
            results.append(
                {
                    "filename": entry.filename,
                    "status": "dry-run",
                    "detail": entry.url,
                    "bytes": 0,
                }
            )
            continue

        print(f"  fetch    {entry.filename} ...", end=" ", flush=True)
        try:
            nbytes = _download_file(entry.url, dest)
            print(f"done ({_fmt_size(nbytes)})")
            results.append(
                {
                    "filename": entry.filename,
                    "status": "downloaded",
                    "detail": "ok",
                    "bytes": nbytes,
                }
            )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"FAILED ({exc})")
            results.append(
                {
                    "filename": entry.filename,
                    "status": "failed",
                    "detail": str(exc),
                    "bytes": 0,
                }
            )

    return results


def print_summary(results: list[dict[str, str | int]]) -> None:
    """Print a summary of download results and manual download instructions."""
    downloaded = [r for r in results if r["status"] == "downloaded"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed = [r for r in results if r["status"] == "failed"]
    manual = [r for r in results if r["status"] == "manual"]
    dry_run = [r for r in results if r["status"] == "dry-run"]

    total_bytes = sum(int(r["bytes"]) for r in downloaded)

    print()
    print("Download Summary")
    print("=" * 50)
    if downloaded:
        print(f"  Downloaded:  {len(downloaded)} files ({_fmt_size(total_bytes)})")
    if skipped:
        print(f"  Skipped:     {len(skipped)} files (already exist)")
    if dry_run:
        print(f"  Dry run:     {len(dry_run)} files (would download)")
    if failed:
        print(f"  Failed:      {len(failed)} files")
    if manual:
        print(f"  Manual:      {len(manual)} files (no direct URL)")

    if failed:
        print()
        print("Failed downloads:")
        for r in failed:
            print(f"  - {r['filename']}: {r['detail']}")

    if manual:
        print()
        print("Manual downloads required:")
        print("-" * 50)

        # Group by source
        by_source: dict[str, list[dict[str, str | int]]] = {}
        for r in manual:
            source = str(r["detail"])
            by_source.setdefault(source, []).append(r)

        for source, entries in by_source.items():
            print(f"\n  Source: {source}")
            for r in entries:
                print(f"    - {r['filename']}")

        print()
        print(f"  Save manual downloads to: {ASSETS_DIR}")


# ── Private helpers ──────────────────────────────────────────────────────────


def _download_file(url: str, dest: Path) -> int:
    """Download a single file. Returns bytes written."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data = response.read()
        dest.write_bytes(data)
        return len(data)


def _fmt_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


def _print_manifest() -> None:
    """Print all documents in the manifest as a table."""
    auto = [e for e in MANIFEST if e.url is not None]
    manual = [e for e in MANIFEST if e.url is None]

    print(f"Regulatory Document Manifest ({len(MANIFEST)} files)")
    print("=" * 70)

    if auto:
        print(f"\nAuto-downloadable ({len(auto)}):")
        for entry in auto:
            print(f"  {entry.filename}")
            print(f"    {entry.description}")

    if manual:
        print(f"\nManual download ({len(manual)}):")
        for entry in manual:
            print(f"  {entry.filename}")
            print(f"    {entry.description}")

    print(f"\nTarget directory: {ASSETS_DIR}")


if __name__ == "__main__":
    sys.exit(main())
