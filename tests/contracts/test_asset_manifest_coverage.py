"""
Contract: every ``docs/assets/`` file the repository names in a form this test reads can be
fetched by a fresh clone.

Pipeline position:
    Outside the calculation pipeline: guards ``scripts/download_docs.py``'s
    ``MANIFEST`` against the ``docs/assets/`` files the repository names.

Key responsibilities:
- Every ``docs/assets/`` file named in one of the four forms below is a manifest
  filename, or the member an archive entry extracts. The assets are git-ignored
  (``*.xlsx``, ``docs/assets/*.pdf``), so a fresh clone or a git worktree holds none
  of them, and ``download_docs.py`` is the only way to get one. A name with no
  manifest entry is evidence that exists only on one operator's disk.
- The citation scan is not vacuous: it must find a known citation of each form
  (``_ANCHORS``). A scan that reads nothing would otherwise pass.
- The published template workbooks the COREP and Pillar 3 generators are held to
  are manifest entries with a download URL: the template layout (row and column
  codes, band labels) lives only in those workbooks, not in the instruction PDFs.

The four forms read (``_named_assets``):
1. ``docs/assets/<name>`` written out in a tracked prose, config or code file;
2. ``<...assets...> / "<name>"`` — a literal name joined onto an assets-directory
   constant in tracked Python;
3. the ``file`` of each document in every packaged rwa-filer publisher-issue
   register (``rwa_filer.boe.issues``), which
   ``tests/contracts/test_publisher_issue_quotes.py`` opens from ``docs/assets``;
4. ``scripts/regulation_text.py``'s ``REGIME_DOCUMENTS``, which it downloads by
   manifest filename.

Not read: a bare filename held in a variable and joined elsewhere (e.g.
``KNOWN_ISSUES_LOG`` in ``test_publisher_issue_quotes.py``), a glob pattern
(``scripts/build_filer_release.py``), ``IMPLEMENTATION_PLAN.md``, where a bullet may
name an artefact still to be acquired, and this module, whose self-tests name made-up
files. A name in an unread form needs its own check, or a citation in one of the four.

None of these tests needs the network or the files on disk, so none skips in CI.

References:
- IMPLEMENTATION_PLAN.md P1.349 (template workbooks cited but not reproducible)
- docs/development/scripts.md: ``scripts/download_docs.py``
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

import pytest
from scripts import download_docs, regulation_text

from rwa_filer.boe.issues import available_issue_registers, load_issues

REPO_ROOT = Path(__file__).resolve().parents[2]

# Document types an asset citation can name; the extension is matched in any case.
_DOC_EXTENSIONS = "pdf|xls|xlsx|xlsm|doc|docx|zip|csv"

# A filename: the first character is not space, quote, glob, path or template syntax
# (so ``docs/assets/*.pdf``, ``docs/assets/{name}.pdf`` and a bare ``docs/assets/`` are
# not citations), and the rest may hold spaces and brackets ("CRR - corep-own-funds.xlsx",
# "annex (2).pdf"). The run is lazy and bounded, so it stops at the first extension.
_NAME = rf"[^\s\"'`<>|*?/\\{{}}\[\]()$][^\n\"'`<>|*?/\\{{}}]{{0,150}}?\.(?i:{_DOC_EXTENSIONS})"
_END = r"(?![A-Za-z0-9_])"

# Form 1: ``docs/assets/<name>`` in a tracked file.
_CITED_ASSET = re.compile(rf"docs/assets/(?P<name>{_NAME}){_END}")
# Form 2: a literal name joined onto an assets-directory constant (``ASSETS_DIR / "x.xlsx"``).
_JOINED_ASSET = re.compile(
    rf"\b\w*(?i:assets)\w*\s*/\s*(?P<quote>[\"'])(?P<name>{_NAME}){_END}(?P=quote)"
)

# File types that carry prose, config or code; generated data (goldens, parquet, packs)
# is not scanned.
_SCANNED_SUFFIXES = frozenset(
    {".md", ".py", ".toml", ".yml", ".yaml", ".txt", ".sh", ".cfg", ".ini"}
)

# The work queue is exempt: a plan bullet may name an artefact still to be acquired,
# which is how P1.349 itself began. So is this module, whose pattern self-tests name
# made-up files. Everything else that cites an asset cites it as evidence a reader is
# expected to open.
_EXEMPT_FILES = frozenset(
    {"IMPLEMENTATION_PLAN.md", "tests/contracts/test_asset_manifest_coverage.py"}
)
_EXEMPT_PREFIXES = ("docs/assets/",)

# One known citation of each form, with the site that makes it. If the scan stops
# finding one, the form it stands for has gone blind and the coverage test would pass
# on whatever it no longer sees.
_ANCHORS = {
    "ps126app1.pdf": "docs/specifications/output-reporting.md",
    "CRR - corep-own-funds.xlsx": "docs/specifications/output-reporting.md",
    "crr-pillar3-irb-credit-risk-instructions.pdf": "docs/features/pillar3-disclosures.md",
    "eba-validation-rules.xlsx": "scripts/extract_validation_rules.py (path join)",
    "boe-xbrl-filing-manual.pdf": "publisher-issue register 4.1.1 (boe-filing-manual)",
    "crr.pdf": "scripts/regulation_text.py (REGIME_DOCUMENTS['crr'])",
}

# URL basename of each published template workbook -> the templates it lays out.
_TEMPLATE_WORKBOOKS = {
    "corep-own-funds.xlsx": "CRR COREP C 02.00 / C 07.00 / C 08.0x / C 09.0x",
    "annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx": "Basel 3.1 OF 07.00",
    "annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx": "Basel 3.1 OF 08.01",
    "annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx": "Basel 3.1 OF 08.02",
    "annex-i-output-floor-and-capital-summaries-disclosure-templates.xlsx": (
        "Basel 3.1 UKB OV1 / KM1 / CMS1 / CMS2, UK INS1 / INS2 / OVC"
    ),
    "annex-xix-credit-risk-sa-disclosure-templates.xlsx": "Basel 3.1 UKB CRD / CR4 / CR5",
    "annex-xxi-credit-risk-irb-disclosure-templates.xlsx": (
        "Basel 3.1 UKB CRE / CR6 / CR6-A / CR7 / CR7-A, UK CR8 / CR9 / CR9.1"
    ),
    "annex-xxiii-credit-risk-irb-disclosure-templates.xlsx": "Basel 3.1 UKB CR10",
    "annex-xxv-ccr-disclosure-templates.xlsx": (
        "Basel 3.1 UK CCRA, UKB CCR1 / CCR3, UK CCR4 / CCR5 / CCR6 / CCR7 / CCR8"
    ),
}


def test_every_cited_asset_has_a_download_manifest_entry() -> None:
    """A named ``docs/assets/`` file must resolve to something download_docs.py fetches."""
    # Arrange
    named = _named_assets()
    blind = {name: site for name, site in _ANCHORS.items() if site not in named.get(name, set())}
    assert not blind, (
        "the asset scan no longer finds citations it is known to find, so the coverage "
        "assertion below would pass on what it cannot see. Missing (name -> site that "
        f"cites it): {blind}. Mend the scan, or repoint the anchor if the citation moved."
    )
    fetchable = _manifest_filenames()

    # Act
    unfetchable = {name: sorted(sites) for name, sites in named.items() if name not in fetchable}

    # Assert
    assert not unfetchable, (
        "docs/assets/ files named by the repository but absent from "
        "scripts/download_docs.py MANIFEST (add a DocEntry with its URL, or a "
        f"manual entry naming its source): {unfetchable}"
    )


@pytest.mark.parametrize("published_name", sorted(_TEMPLATE_WORKBOOKS))
def test_published_template_workbook_is_downloadable(published_name: str) -> None:
    """Each template workbook a generator is held to has a manifest entry with a URL."""
    # Arrange
    templates = _TEMPLATE_WORKBOOKS[published_name]

    # Act
    entries = [
        entry
        for entry in download_docs.MANIFEST
        if entry.url is not None and PurePosixPath(entry.url).name == published_name
    ]

    # Assert
    assert len(entries) == 1, (
        f"expected exactly one MANIFEST entry downloading {published_name} "
        f"({templates}); found {len(entries)}"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("In `docs/assets/CRR - corep-own-funds.xlsx` sheet 2.", "CRR - corep-own-funds.xlsx"),
        ("see docs/assets/Annex-XXVI.Pdf p.4", "Annex-XXVI.Pdf"),
        ("see docs/assets/annex-xxvi.xls.", "annex-xxvi.xls"),
        ("(docs/assets/annex-xxvi.docx)", "annex-xxvi.docx"),
        ("`docs/assets/annex (2).pdf`", "annex (2).pdf"),
        ("[CR5](docs/assets/annex-xix.xlsx)", "annex-xix.xlsx"),
        ("docs/assets/ps1-26-annex-xx-instructions.PDF,", "ps1-26-annex-xx-instructions.PDF"),
    ],
    ids=["spaces", "mixed-case-ext", "xls", "docx", "parentheses", "markdown-link", "upper-ext"],
)
def test_scan_reads_the_whole_cited_name(text: str, expected: str) -> None:
    """The citation pattern keeps the whole filename, whatever its case, spacing or type."""
    # Act
    names = [m.group("name") for m in _CITED_ASSET.finditer(text)]

    # Assert
    assert names == [expected]


@pytest.mark.parametrize(
    "text",
    ["`docs/assets/` is git-ignored", "docs/assets/*.pdf", "docs/assets/{name}.pdf"],
    ids=["directory", "glob", "template"],
)
def test_scan_ignores_what_is_not_a_citation(text: str) -> None:
    """A directory mention, a glob or a format template names no file."""
    # Act
    names = [m.group("name") for m in _CITED_ASSET.finditer(text)]

    # Assert
    assert names == []


def test_scan_reads_a_name_joined_onto_an_assets_constant() -> None:
    """``ASSETS_DIR / "x.xlsx"`` names ``docs/assets/x.xlsx`` as surely as the path does."""
    # Arrange
    text = 'BOE_FILE = ASSETS_DIR / "boe-validation-rules-banking-reporting-v4.1.1.xlsx"'

    # Act
    names = [m.group("name") for m in _JOINED_ASSET.finditer(text)]

    # Assert
    assert names == ["boe-validation-rules-banking-reporting-v4.1.1.xlsx"]


def _manifest_filenames() -> set[str]:
    """Every filename download_docs.py writes: each entry's file and any extracted member."""
    names = {entry.filename for entry in download_docs.MANIFEST}
    names |= {
        entry.extract_as or PurePosixPath(entry.extract_member).name
        for entry in download_docs.MANIFEST
        if entry.extract_member is not None
    }
    return names


def _named_assets() -> dict[str, set[str]]:
    """Map each ``docs/assets/`` filename the repository names to the sites that name it."""
    named: dict[str, set[str]] = defaultdict(set)
    for rel, text in _tracked_texts():
        for match in _CITED_ASSET.finditer(text):
            named[match.group("name")].add(rel)
        if rel.endswith(".py"):
            for match in _JOINED_ASSET.finditer(text):
                named[match.group("name")].add(f"{rel} (path join)")
    for release in available_issue_registers():
        for key, document in load_issues(release).documents.items():
            if document.file is not None:
                named[document.file].add(f"publisher-issue register {release} ({key})")
    for regime, filename in regulation_text.REGIME_DOCUMENTS.items():
        named[filename].add(f"scripts/regulation_text.py (REGIME_DOCUMENTS[{regime!r}])")
    return named


def _tracked_texts() -> list[tuple[str, str]]:
    """Each tracked, non-exempt prose / config / code file with its text."""
    tracked = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.splitlines()
    texts = []
    for rel in tracked:
        if rel in _EXEMPT_FILES or rel.startswith(_EXEMPT_PREFIXES):
            continue
        if PurePosixPath(rel).suffix not in _SCANNED_SUFFIXES:
            continue
        path = REPO_ROOT / rel
        if path.is_file():
            texts.append((rel, path.read_text(encoding="utf-8", errors="replace")))
    return texts
