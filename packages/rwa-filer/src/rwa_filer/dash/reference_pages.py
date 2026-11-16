"""
The Reference pages — what this package carries: taxonomy packs and rule books.

Pipeline position:
    browser  ->  these routes  ->  taxonomy.pack / boe.catalogue
        ->  reference.html, reference_module.html

Key responsibilities:
- List every packaged taxonomy pack and rule book, with the rules each module
  enforces — ``rwa-filer taxonomy list`` and ``rulebook list`` in one place.
- For one module: its tables, as the taxonomy lays them out, and its enforced
  rules, searchable, without a return open.

References:
- rwa_filer.taxonomy.pack — the packs; rwa_filer.boe.catalogue — the rule books
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from functools import cache
from typing import TYPE_CHECKING, Final

from starlette.exceptions import HTTPException
from starlette.routing import Route

from rwa_filer.boe.catalogue import load_rulebook
from rwa_filer.dash.forms import page_number
from rwa_filer.dash.views import title_case
from rwa_filer.release import (
    ReleaseNotFoundError,
    release_deny_list,
    release_packs,
    release_rulebook,
    release_rulebooks,
    resolve_release,
    shipped_releases,
    status_on,
)
from rwa_filer.taxonomy.pack import load_packaged

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.dash.context import DashContext
    from rwa_filer.taxonomy.pack import PackInfo

#: Rules listed per page of a module's rule list.
RULES_PER_PAGE: Final = 100


@dataclass(frozen=True)
class ModuleEntry:
    """One module in one shipped release: its pack and its rule book, each if packaged.

    ``status`` is the module's status in the release today (``live``,
    ``future`` or ``superseded``), or ``None`` when the release packages rules
    but no pack for it.
    """

    release: str
    module: str
    pack: PackInfo | None
    rule_book: str | None
    rules: int
    enforced: int
    status: str | None = None


def routes(context: DashContext) -> list[Route]:
    """The Reference pages, bound to ``context``."""
    pages = ReferencePages(context)
    return [
        Route("/reference", pages.index, name="reference"),
        Route("/reference/{module}", pages.module, name="reference_module"),
    ]


class ReferencePages:
    """The handlers of the Reference pages."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    def index(self, request: Request) -> Response:
        """Every shipped release's modules, with each one's pack, rule book and status."""
        return self.context.render(
            request, "reference.html", section="reference", modules=module_entries()
        )

    def module(self, request: Request) -> Response:
        """One module in one release: its tables and its enforced rules.

        ``?release=`` names the release; without it, the release a run uses for
        the module by default.
        """
        name = str(request.path_params["module"]).upper()
        entries = [item for item in module_entries() if item.module == name]
        if not entries:
            raise HTTPException(status_code=404, detail=f"No module {name} is packaged.")
        wanted = request.query_params.get("release", "").strip() or _default_release(entries)
        entry = next((item for item in entries if item.release == wanted), None)
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"Release {wanted} is not shipped with module {name}."
            )
        pack = load_packaged(entry.pack.key) if entry.pack else None
        tables = (
            [(table, title_case(table.title)) for _, table in sorted(pack.tables.items())]
            if pack
            else []
        )
        query = request.query_params.get("q", "").strip()
        rules = _enforced(entry.release, entry.module)
        needle = query.lower()
        matched = [
            rule
            for rule in rules
            if not needle or needle in f"{rule.rule_id} {rule.label or ''}".lower()
        ]
        pages = max(1, math.ceil(len(matched) / RULES_PER_PAGE))
        page = min(max(page_number(request.query_params.get("page")), 1), pages)
        today = date.today()
        deny_list = release_deny_list(entry.release)
        return self.context.render(
            request,
            "reference_module.html",
            section="reference",
            entry=entry,
            entries=entries,
            tables=tables,
            denied={
                item.rule_id: item.describe()
                for item in deny_list.for_module(entry.module)
                if item.in_force_on(today)
            },
            rules=matched[(page - 1) * RULES_PER_PAGE : page * RULES_PER_PAGE],
            matched=len(matched),
            query=query,
            page=page,
            pages=pages,
        )


def module_entries() -> tuple[ModuleEntry, ...]:
    """Every module of every shipped release, newest release first, with today's status."""
    today = date.today()
    return tuple(
        replace(entry, status=status_on(entry.pack, today) if entry.pack else None)
        for version in shipped_releases()
        for entry in _release_entries(version)
    )


@cache
def _release_entries(version: str) -> tuple[ModuleEntry, ...]:
    """Release ``version``'s modules, from its packs and rule books. Cached: package data."""
    packs = {info.module: info for info in release_packs(version)}
    books: dict[str, tuple[str, int, int]] = {}
    for file_name in release_rulebooks(version):
        rulebook = load_rulebook(file_name)
        for module in rulebook.modules:
            books[module] = (
                f"{rulebook.framework_version} {rulebook.taxonomy}",
                len(rulebook.rules),
                len(rulebook.enforced(module)),
            )
    return tuple(
        ModuleEntry(
            release=version,
            module=module,
            pack=packs.get(module),
            rule_book=books[module][0] if module in books else None,
            rules=books[module][1] if module in books else 0,
            enforced=books[module][2] if module in books else 0,
        )
        for module in sorted(set(packs) | set(books))
    )


def _default_release(entries: list[ModuleEntry]) -> str:
    """The release a run uses for the module by default; for rules only, the newest."""
    try:
        return resolve_release(entries[0].module).version
    except ReleaseNotFoundError:
        return entries[0].release


@cache
def _enforced(version: str, module: str) -> tuple[Rule, ...]:
    rulebook = release_rulebook(version, module)
    return rulebook.enforced(module) if rulebook is not None else ()
