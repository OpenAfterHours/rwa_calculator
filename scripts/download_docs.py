#!/usr/bin/env python3
"""
Download regulatory reference documents to docs/assets/.

Downloads PRA PS1/26, CRR, EBA template and reporting validation-rule
documents needed for development. Files with known direct URLs are fetched
automatically; remaining files are listed with manual download instructions.
An archive entry may also name a member to extract after download.

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
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "docs" / "assets"

USER_AGENT = "Mozilla/5.0 (rwa-calc document fetcher)"

BOE_PS126_BASE = "https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january"
BOE_PS126_LANDING = "https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement"
PRA_RULEBOOK = "https://www.prarulebook.co.uk/pra-rules/crr-firms"

BOE_CRR_BASE = "https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2023/november/"

# Reporting templates and disclosure annexes are published under the banking
# regulatory-reporting media path; the PS1/26 (Basel 3.1) set sits in its 2026/january folder.
BOE_BANKING_REPORTING_BASE = (
    "https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/"
    "regulatory-reporting/banking"
)
BOE_PS126_REPORTING_BASE = f"{BOE_BANKING_REPORTING_BASE}/2026/january"

# The taxonomy, its validations and the known-issues log are published on this sub-page.
BOE_BANKS_REPORTING_LANDING = (
    "https://www.bankofengland.co.uk/prudential-regulation/regulatory-reporting/"
    "regulatory-reporting-banking-sector/banks-building-societies-and-investment-firms"
)
EBA_REPORTING_LANDING = (
    "https://www.eba.europa.eu/risk-and-data-analysis/reporting/reporting-frameworks"
)

# Download outcomes after which a post-download extraction step still applies.
# A "manual" or "failed" entry has no usable archive on disk.
EXTRACTABLE_STATUSES = frozenset({"downloaded", "skipped", "dry-run"})


@dataclass(frozen=True)
class DocEntry:
    """A regulatory document to download or acquire manually.

    Setting ``extract_member`` marks the download as an archive: after it is
    fetched (or found already present), that member is extracted alongside it.
    """

    filename: str
    description: str
    url: str | None  # None = manual download required
    source: str  # Landing page or source description for manual downloads
    extract_member: str | None = None  # Archive member to extract post-download
    extract_as: str | None = None  # Extracted filename (defaults to the member's own name)


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
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/2026/january/annex-ii-reporting-instructions.pdf",
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
    DocEntry(
        filename="crr.pdf",
        description="Current CRR rules when onshoring",
        url="https://www.legislation.gov.uk/eur/2013/575/data.pdf",
        source=PRA_RULEBOOK,
    ),
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
    DocEntry(
        filename="crr-pillar3-irb-credit-risk-instructions.pdf",
        description="CRR Pillar 3 Annex XXII — IRB credit risk disclosure instructions",
        url=f"{BOE_BANKING_REPORTING_BASE}/pillar3-irb-credit-risk-instructions.pdf",
        source=PRA_RULEBOOK,
    ),
    DocEntry(
        filename="ps1-26-annex-ii-output-floor-and-capital-summaries-disclosure-instructions.pdf",
        description=(
            "PRA PS1/26 Annex II — output floor and capital summaries disclosure instructions "
            "(UKB OV1, KM1, CMS1, CMS2; UK INS1, INS2, OVC)"
        ),
        url=f"{BOE_PS126_REPORTING_BASE}/annex-ii-output-floor-and-capital-summaries-disclosure-instructions.pdf",
        source=BOE_PS126_LANDING,
    ),
    # --- Published template workbooks ---
    # The row / column codes and band labels of a template live only in its workbook;
    # the instruction PDFs give ranges. The first four keep the filenames the
    # specifications cite them by.
    DocEntry(
        filename="CRR - corep-own-funds.xlsx",
        description=(
            "CRR Annex I COREP own funds templates — one sheet per template "
            "('2' = C 02.00, '7' = C 07.00, '8.1'-'8.7' = C 08.0x, '9.1'/'9.2' = C 09.0x)"
        ),
        url=f"{BOE_BANKING_REPORTING_BASE}/corep-own-funds.xlsx",
        source=BOE_BANKS_REPORTING_LANDING,
    ),
    DocEntry(
        filename="0F07 - annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx",
        description="PRA PS1/26 Annex I — OF 07.00 credit risk SA reporting template",
        url=f"{BOE_PS126_REPORTING_BASE}/annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="OF0801-annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx",
        description="PRA PS1/26 Annex I — OF 08.01 credit risk IRB reporting template",
        url=f"{BOE_PS126_REPORTING_BASE}/annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="OF0802-annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx",
        description="PRA PS1/26 Annex I — OF 08.02 credit risk IRB reporting template",
        url=f"{BOE_PS126_REPORTING_BASE}/annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-i-output-floor-and-capital-summaries-disclosure-templates.xlsx",
        description=(
            "PRA PS1/26 Annex I — output floor and capital summaries disclosure templates "
            "(UKB OV1, KM1, CMS1, CMS2; UK INS1, INS2, OVC)"
        ),
        url=f"{BOE_PS126_REPORTING_BASE}/annex-i-output-floor-and-capital-summaries-disclosure-templates.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-xix-credit-risk-sa-disclosure-templates.xlsx",
        description=(
            "PRA PS1/26 Annex XIX — credit risk SA disclosure templates (UKB CRD, CR4, CR5); "
            "the instructions are Annex XX"
        ),
        url=f"{BOE_PS126_REPORTING_BASE}/annex-xix-credit-risk-sa-disclosure-templates.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-xxi-credit-risk-irb-disclosure-templates.xlsx",
        description=(
            "PRA PS1/26 Annex XXI — credit risk IRB disclosure templates "
            "(UKB CRE, CR6, CR6-A, CR7, CR7-A; UK CR8, CR9, CR9.1)"
        ),
        url=f"{BOE_PS126_REPORTING_BASE}/annex-xxi-credit-risk-irb-disclosure-templates.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-xxiii-credit-risk-irb-disclosure-templates.xlsx",
        description=(
            "PRA PS1/26 Annex XXIII — exposures subject to the slotting approach "
            "disclosure template (UKB CR10)"
        ),
        url=f"{BOE_PS126_REPORTING_BASE}/annex-xxiii-credit-risk-irb-disclosure-templates.xlsx",
        source=BOE_PS126_LANDING,
    ),
    DocEntry(
        filename="ps1-26-annex-xxv-ccr-disclosure-templates.xlsx",
        description=(
            "PRA PS1/26 Annex XXV — counterparty credit risk disclosure templates "
            "(Table UK CCRA; UKB CCR1, CCR3; UK CCR4, CCR5, CCR6, CCR7, CCR8)"
        ),
        url=f"{BOE_PS126_REPORTING_BASE}/annex-xxv-ccr-disclosure-templates.xlsx",
        source=BOE_PS126_LANDING,
    ),
    # --- Reporting validation rules ---
    DocEntry(
        filename="eba-validation-rules.xlsx",
        description=(
            "EBA validation rules for COREP/FINREP "
            "(all framework versions; sheet 'v3.0(3.0.1)' = current CRR)"
        ),
        url="https://www.eba.europa.eu/sites/default/files/2026-06/12d2a6ae-9f58-47ab-a684-cdc9924ed4aa/%28up%20to%203.5%29%20EBA_validation_rules_2026-06-10.xlsx",
        source=EBA_REPORTING_LANDING,
    ),
    DocEntry(
        filename="boe-banking-taxonomy-validations-v4.1.1.zip",
        description=(
            "BoE banking XBRL taxonomy validation rules v4.1.1 "
            "(Banking Reporting module, entry point PRA001 — contains the OF credit-risk tables)"
        ),
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/boe-banking-taxonomy-validations-v411.zip",
        source=BOE_BANKS_REPORTING_LANDING,
        extract_member="Bank of England Banking Taxonomy Validations Banking Reporting v4.1.1.xlsx",
        extract_as="boe-validation-rules-banking-reporting-v4.1.1.xlsx",
    ),
    DocEntry(
        filename="boe-banking-taxonomy-release-note-v4.1.1.pdf",
        description="BoE banking XBRL taxonomy v4.1.1 release note (entry points, SchemaRefs)",
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/boebankingtaxonomyreleasenotev411.pdf",
        source=BOE_BANKS_REPORTING_LANDING,
    ),
    DocEntry(
        filename="boe-banking-known-issues-august-2026.xlsx",
        description=(
            "BoE banking taxonomy known-issues log (27 Aug 2026) — rules downgraded or "
            "deactivated between taxonomy releases"
        ),
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/boe-banking-known-issues-august-2026.xlsx",
        source=BOE_BANKS_REPORTING_LANDING,
    ),
    DocEntry(
        filename="boe-banking-known-issues-november-2026.xlsx",
        description=(
            "BoE banking taxonomy known-issues log (16 Nov 2026) — why rules were "
            "downgraded or deactivated; joined to the deny list for the issue numbers"
        ),
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/boe-banking-known-issues-november-2026.xlsx",
        source=BOE_BANKS_REPORTING_LANDING,
    ),
    DocEntry(
        filename="boe-banking-validations-deny-list-november-2026.xlsx",
        description=(
            "BoE banking validations deny list (Nov 2026) — rules the gateway no longer "
            "runs, or runs as warnings, per taxonomy release; imported into rwa-filer by "
            "scripts/build_filer_release.py --deny-list"
        ),
        url="https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/boe-banking-validations-deny-list-november-2026.xlsx",
        source=BOE_BANKS_REPORTING_LANDING,
    ),
    # --- XBRL filing ---
    DocEntry(
        filename="boe-xbrl-filing-manual.pdf",
        description=(
            "BoE XBRL Filing Manual v1.0.1 (30 May 2024; published as "
            "xbrl-filing-manual-april-2024.pdf) — quoted page by page by the rwa-filer "
            "publisher-issue register (document 'boe-filing-manual')"
        ),
        url=f"{BOE_BANKING_REPORTING_BASE}/2025/xbrl-filing-manual-april-2024.pdf",
        source=BOE_BANKS_REPORTING_LANDING,
    ),
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
    """Iterate the manifest, download files with known URLs and extract archives.

    Returns a list of result dicts with keys: filename, status, detail, bytes.
    An archive entry yields two results: one for the archive, one for the
    member extracted from it.
    """
    results: list[dict[str, str | int]] = []

    for entry in manifest:
        archive = assets_dir / entry.filename
        result = _acquire(entry, archive, force=force, dry_run=dry_run)
        results.append(result)

        if entry.extract_member is None or result["status"] not in EXTRACTABLE_STATUSES:
            continue

        dest = assets_dir / (entry.extract_as or Path(entry.extract_member).name)
        results.append(_extract(archive, entry.extract_member, dest, force=force, dry_run=dry_run))

    return results


def print_summary(results: list[dict[str, str | int]]) -> None:
    """Print a summary of download results and manual download instructions."""
    downloaded = [r for r in results if r["status"] == "downloaded"]
    extracted = [r for r in results if r["status"] == "extracted"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed = [r for r in results if r["status"] == "failed"]
    manual = [r for r in results if r["status"] == "manual"]
    dry_run = [r for r in results if r["status"] == "dry-run"]

    total_bytes = sum(int(r["bytes"]) for r in downloaded)
    extracted_bytes = sum(int(r["bytes"]) for r in extracted)

    print()
    print("Download Summary")
    print("=" * 50)
    if downloaded:
        print(f"  Downloaded:  {len(downloaded)} files ({_fmt_size(total_bytes)})")
    if extracted:
        print(f"  Extracted:   {len(extracted)} files ({_fmt_size(extracted_bytes)})")
    if skipped:
        print(f"  Skipped:     {len(skipped)} files (already present)")
    if dry_run:
        print(f"  Dry run:     {len(dry_run)} files (would download or extract)")
    if failed:
        print(f"  Failed:      {len(failed)} files")
    if manual:
        print(f"  Manual:      {len(manual)} files (no direct URL)")

    if failed:
        print()
        print("Failures:")
        for r in failed:
            print(f"  - {r['filename']}: {r['detail']}")

    if manual:
        _print_manual_instructions(manual)


# ── Private helpers ──────────────────────────────────────────────────────────


def _acquire(
    entry: DocEntry,
    dest: Path,
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, str | int]:
    """Fetch one manifest entry to ``dest``. Returns a result dict, never raises."""
    if entry.url is None:
        return {
            "filename": entry.filename,
            "status": "manual",
            "detail": entry.source,
            "bytes": 0,
        }

    if dest.exists() and not force:
        size = dest.stat().st_size
        print(f"  skip     {entry.filename} (already exists, {_fmt_size(size)})")
        return {
            "filename": entry.filename,
            "status": "skipped",
            "detail": "already exists",
            "bytes": size,
        }

    if dry_run:
        print(f"  would download  {entry.filename}")
        return {
            "filename": entry.filename,
            "status": "dry-run",
            "detail": entry.url,
            "bytes": 0,
        }

    print(f"  fetch    {entry.filename} ...", end=" ", flush=True)
    try:
        nbytes = _download_file(entry.url, dest)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"FAILED ({exc})")
        return {
            "filename": entry.filename,
            "status": "failed",
            "detail": str(exc),
            "bytes": 0,
        }

    print(f"done ({_fmt_size(nbytes)})")
    return {
        "filename": entry.filename,
        "status": "downloaded",
        "detail": "ok",
        "bytes": nbytes,
    }


def _extract(
    archive: Path,
    member: str,
    dest: Path,
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, str | int]:
    """Extract one member of ``archive`` to ``dest``. Returns a result dict, never raises.

    A missing archive, a missing member or an unreadable zip is reported as a
    "failed" result so it flows into print_summary and the main() exit code.
    """
    if dest.exists() and not force:
        size = dest.stat().st_size
        print(f"  skip     {dest.name} (already extracted, {_fmt_size(size)})")
        return {
            "filename": dest.name,
            "status": "skipped",
            "detail": "already extracted",
            "bytes": size,
        }

    if dry_run:
        print(f"  would extract   {dest.name} from {archive.name}")
        return {
            "filename": dest.name,
            "status": "dry-run",
            "detail": f"{archive.name} :: {member}",
            "bytes": 0,
        }

    print(f"  extract  {dest.name} ...", end=" ", flush=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            data = bundle.read(member)
        dest.write_bytes(data)
    except KeyError:
        detail = f"member not found in {archive.name}: {member}"
        print(f"FAILED ({detail})")
        return {"filename": dest.name, "status": "failed", "detail": detail, "bytes": 0}
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"FAILED ({exc})")
        return {"filename": dest.name, "status": "failed", "detail": str(exc), "bytes": 0}

    print(f"done ({_fmt_size(len(data))})")
    return {
        "filename": dest.name,
        "status": "extracted",
        "detail": f"from {archive.name}",
        "bytes": len(data),
    }


def _print_manual_instructions(manual: list[dict[str, str | int]]) -> None:
    """Print manual-download instructions grouped by source."""
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
            if entry.extract_member is not None:
                extracted = entry.extract_as or Path(entry.extract_member).name
                print(f"    -> extracts {extracted}")

    if manual:
        print(f"\nManual download ({len(manual)}):")
        for entry in manual:
            print(f"  {entry.filename}")
            print(f"    {entry.description}")

    print(f"\nTarget directory: {ASSETS_DIR}")


if __name__ == "__main__":
    sys.exit(main())
