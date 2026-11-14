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
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Final

from starlette.exceptions import HTTPException
from starlette.routing import Route

from rwa_filer.boe.catalogue import RuleBookNotFoundError, available_rulebooks, load_rulebook
from rwa_filer.dash.forms import page_number
from rwa_filer.dash.views import title_case
from rwa_filer.taxonomy.pack import available_packs, resolve_pack

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
    """One module: its taxonomy pack, if packaged, and its rule book, if packaged."""

    module: str
    pack: PackInfo | None
    rule_book: str | None
    rules: int
    enforced: int


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
        """Every packaged module, with its pack and its rule book."""
        return self.context.render(
            request, "reference.html", section="reference", modules=module_entries()
        )

    def module(self, request: Request) -> Response:
        """One module: its tables and its enforced rules."""
        name = str(request.path_params["module"]).upper()
        entry = next((item for item in module_entries() if item.module == name), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"No module {name} is packaged.")
        pack = resolve_pack(entry.module, entry.pack.valid_from) if entry.pack else None
        tables = (
            [(table, title_case(table.title)) for _, table in sorted(pack.tables.items())]
            if pack
            else []
        )
        query = request.query_params.get("q", "").strip()
        rules = _enforced(entry.module)
        needle = query.lower()
        matched = [
            rule
            for rule in rules
            if not needle or needle in f"{rule.rule_id} {rule.label or ''}".lower()
        ]
        pages = max(1, math.ceil(len(matched) / RULES_PER_PAGE))
        page = min(max(page_number(request.query_params.get("page")), 1), pages)
        return self.context.render(
            request,
            "reference_module.html",
            section="reference",
            entry=entry,
            tables=tables,
            rules=matched[(page - 1) * RULES_PER_PAGE : page * RULES_PER_PAGE],
            matched=len(matched),
            query=query,
            page=page,
            pages=pages,
        )


@cache
def module_entries() -> tuple[ModuleEntry, ...]:
    """Every module a pack or a rule book is packaged for. Cached: package data."""
    packs = {info.module: info for info in available_packs()}
    books: dict[str, tuple[str, int, int]] = {}
    for file_name in available_rulebooks():
        try:
            rulebook = load_rulebook(file_name)
        except (RuleBookNotFoundError, ValueError):
            continue
        for module in rulebook.modules:
            books[module] = (
                f"{rulebook.framework_version} {rulebook.taxonomy}",
                len(rulebook.rules),
                len(rulebook.enforced(module)),
            )
    return tuple(
        ModuleEntry(
            module=module,
            pack=packs.get(module),
            rule_book=books[module][0] if module in books else None,
            rules=books[module][1] if module in books else 0,
            enforced=books[module][2] if module in books else 0,
        )
        for module in sorted(set(packs) | set(books))
    )


@cache
def _enforced(module: str) -> tuple[Rule, ...]:
    for file_name in available_rulebooks():
        rulebook = load_rulebook(file_name)
        if module in rulebook.modules:
            return rulebook.enforced(module)
    return ()
