"""
Fetch the Bank of England's current deny list and known-issues log, and check every shipped release.

Pipeline position:
    (not a pipeline stage) — the command the scheduled Bank Publications workflow runs
    the Bank's banking reporting page  ->  discover_publications  ->  docs/assets/<the Bank's names>
        ->  scripts/build_filer_release.py <release> --deny-list --check, for every shipped release

The Bank publishes its validations deny list and its banking known-issues log
between taxonomy releases, monthly, and both override the taxonomy. rwa-filer
packages the list per release (``boe/data/deny/<release>.json``, joined to the
log), and ``build_filer_release.py --deny-list --check`` says whether the
packaged list is still the Bank's - but only against files someone has
downloaded. This command downloads them, so a list published next month reaches
the check without anyone remembering to fetch it (escape log, 2026-11-16).

Key responsibilities:
- Find each file by the link the Bank's banking reporting page gives it, never
  by a month typed here: ``scripts/download_docs.py`` names the November 2026
  files, and would fetch those for ever.
- Fail closed where it cannot tell which file is current: no link, more than
  one, a link outside the Bank's banking reporting folder, or a name the check
  cannot date (``build_filer_release`` reads the newest file by the month and
  year that end its name, so a ``-v2`` suffix would leave an older file checked).
- Download each under the Bank's own name, from the Bank's folder; the name is
  rebuilt from the month and year read off the link, so nothing the page says
  reaches a path or a URL unchecked.
- Confirm each downloaded file is the one the check will read: a newer-dated
  file already in ``docs/assets`` would otherwise be checked in its place.
- Run ``build_filer_release.py <release> --deny-list --check`` for every release
  rwa-filer ships. A newer known-issues log alone also fails it: the packaged
  list records the log it was joined to, byte for byte.

Usage:
    uv run python scripts/check_bank_publications.py

Exit codes:
    0  every shipped release's packaged deny list is exactly what the Bank's
       current files yield
    1  a file could not be found, fetched or dated, or a packaged list is out of
       date: re-import it with ``scripts/build_filer_release.py <release> --deny-list``

References:
- docs/development/escape-log.md — 2026-11-16, the deny-list entry
- .github/workflows/bank-publications.yml
- tests/contracts/test_bank_publications.py
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_filer_release  # noqa: E402  (needs REPO_ROOT on sys.path)
from scripts.download_docs import (  # noqa: E402
    BOE_BANKS_REPORTING_LANDING,
    USER_AGENT,
)

from rwa_filer.release import shipped_releases  # noqa: E402

#: Each file fetched, by kind: the pattern ``build_filer_release`` reads it by.
PUBLICATIONS: dict[str, str] = {
    "deny_list": build_filer_release.DENY_LIST_PATTERN,
    "known_issues": build_filer_release.KNOWN_ISSUES_PATTERN,
}
#: The host and folder the Bank publishes both files in.
BANK_HOST = urlsplit(build_filer_release.BANK_FILES_URL).netloc
BANK_FOLDER = urlsplit(build_filer_release.BANK_FILES_URL).path
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_TIMEOUT_SECONDS = 60


class PublicationError(Exception):
    """The Bank's page does not say, unambiguously, which file is current."""


def main(argv: list[str] | None = None) -> int:
    """Fetch the Bank's current files and check every shipped release's deny list against them."""
    argparse.ArgumentParser(
        description="Fetch the Bank's current deny list and known-issues log into docs/assets "
        "and check every shipped release's packaged deny list against them."
    ).parse_args(argv)
    folder = build_filer_release.ASSETS
    try:
        page = _fetch(BOE_BANKS_REPORTING_LANDING).decode("utf-8", errors="replace")
        names = discover_publications(page)
        for name in names.values():
            _download(name, folder)
        stale = _not_read(names, folder)
    except (PublicationError, build_filer_release.UndatedBankFileError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if stale:
        for line in stale:
            print(f"error: {line}", file=sys.stderr)
        return 1
    status = 0
    for version in shipped_releases():
        status = max(status, build_filer_release.main([version, "--deny-list", "--check"]))
    return status


def discover_publications(page: str) -> dict[str, str]:
    """Each file's kind -> the name the Bank's banking reporting page links it by.

    Raises:
        PublicationError: for a kind, the page links no file, more than one, one
            outside the Bank's banking reporting folder, or one whose name gives
            no month and year.
    """
    links = {_normalised(href) for href in _HREF.findall(page)}
    found: dict[str, str] = {}
    for kind, pattern in PUBLICATIONS.items():
        stem = pattern.removesuffix("*.xlsx")
        named = sorted(link for link in links if stem in link.lower())
        if not named:
            raise PublicationError(
                f"the Bank's page ({BOE_BANKS_REPORTING_LANDING}) links no {stem}<month>-<year>.xlsx"
            )
        if len(named) > 1:
            raise PublicationError(
                f"the Bank's page links {len(named)} files named {stem}...: {', '.join(named)}; "
                "which is current cannot be told"
            )
        found[kind] = _dated_name(named[0], stem)
    return found


def _dated_name(link: str, stem: str) -> str:
    """The file's name, rebuilt from the month and year its link ends with."""
    if not link.startswith(BANK_FOLDER):
        raise PublicationError(
            f"{link} is not in the Bank's banking reporting folder ({BANK_HOST}{BANK_FOLDER})"
        )
    name = link.removeprefix(BANK_FOLDER)
    when = build_filer_release.bank_file_date(name)
    if when is None or not name.startswith(stem):
        raise PublicationError(
            f"cannot date {name}: the deny-list check reads the Bank's files by the "
            "-<month>-<year>.xlsx that ends their names"
        )
    year, month = when
    rebuilt = f"{stem}{build_filer_release.MONTHS[month]}-{year:04d}.xlsx"
    if rebuilt != name:
        raise PublicationError(f"cannot date {name}: it is not {rebuilt}")
    return rebuilt


def _download(name: str, folder: Path) -> None:
    """Fetch ``name`` from the Bank's folder into ``folder``, replacing any copy there."""
    data = _fetch(build_filer_release.BANK_FILES_URL + name)
    folder.mkdir(parents=True, exist_ok=True)
    # Through the handle: fetched content must not reach a path-taking call (S2083).
    with (folder / name).open("wb") as handle:
        handle.write(data)
    print(f"  fetched {name} ({len(data):,} bytes)")


def _not_read(names: dict[str, str], folder: Path) -> list[str]:
    """Each fetched file the deny-list check would NOT read: a newer-dated one is in ``folder``."""
    problems = []
    for kind, name in names.items():
        newest = build_filer_release.newest_bank_file(PUBLICATIONS[kind], folder)
        if newest is not None and newest.name != name:
            problems.append(
                f"{folder} holds {newest.name}, which the deny-list check reads before the "
                f"{name} the Bank lists now, so the deny-list check would check "
                f"{newest.name}: remove it"
            )
    return problems


def _normalised(href: str) -> str:
    """A link as its path on the Bank's host; a link elsewhere as its URL, without a query."""
    parts = urlsplit(html.unescape(href))
    if parts.netloc in ("", BANK_HOST):
        return parts.path
    return parts._replace(query="", fragment="").geturl()


def _fetch(url: str) -> bytes:
    """GET ``url`` (a constant of this module or the Bank's folder plus a rebuilt name)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        return response.read()


if __name__ == "__main__":
    sys.exit(main())
