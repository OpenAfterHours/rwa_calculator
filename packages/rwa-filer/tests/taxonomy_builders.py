"""
Builders for the taxonomy-compiler tests: a miniature publisher in a temp folder.

The real inputs — the Bank of England's annotated templates, DPM dictionary and
XBRL taxonomy package — are the publisher's files and are not redistributed, so
the unit tests run against a synthetic module laid out exactly the same way:

- ``build_annotated_workbook`` — Note, Table of Contents, a hidden-style
  ``Enumerations`` sheet and two table sheets: a closed table with a fixed z-axis
  (``T01.00.01.01``) and an open-row table with a typed key (``T02.00.01.01``);
- ``build_dictionary_workbook`` — Domains, Dimensions, Metrics and member sheets;
- ``build_taxonomy_package`` — an extracted package tree: manifest, the module's
  ``-pre.xml``, and each table's ``-rend`` / ``-lab-codes`` / ``-lab-en`` / ``-def``.

The closed table is built so that every reportability outcome occurs once:

    cell         workbook   hypercubes   outcome
    r0010/c0010  white      accept       emitted, "workbook"
    r0010/c0020  white      accept       emitted, "workbook"
    r0020/c0010  white      reject       dropped, recorded
    r0020/c0020  grey       accept       emitted, "linkbase"

``map_instance`` is the reverse direction used by the opt-in integration test:
stream an XBRL instance and count how many pack cells each fact maps to.
"""

from __future__ import annotations

import collections
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

MODULE = "DEMO01"
ENTRY_POINT = "http://www.example.test/fws/demo/2026-01-01/mod/demo01.xsd"
CLOSED_TABLE = "T01.00.01.01"
OPEN_TABLE = "T02.00.01.01"

GREY = PatternFill(fill_type="solid", fgColor="FFBBBBBB")
EBA = "http://www.eba.europa.eu/eu/fr/xbrl/crr/dict"
HYPERCUBE = "http://www.eurofiling.info/eu/fr/xbrl/ext/model.xsd#hyp"
ROLE = "http://www.example.test/role/"
XLINK = "http://www.w3.org/1999/xlink"
NAMESPACES = (
    'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:gen="http://xbrl.org/2008/generic" '
    'xmlns:label="http://xbrl.org/2008/label" xmlns:table="http://xbrl.org/2014/table" '
    'xmlns:formula="http://xbrl.org/2008/formula" xmlns:xbrldt="http://xbrl.org/2005/xbrldt" '
    f'xmlns:xlink="{XLINK}"'
)


# ── Annotated workbook ────────────────────────────────────────────────────────


def build_annotated_workbook(path: Path) -> Path:
    """Write the miniature annotated-templates workbook and return its path."""
    workbook = Workbook()
    note = workbook.active
    note.title = "Note"
    note["B6"] = "Demo Authority Annotated Templates Demo Reporting v9.9.9"

    contents = workbook.create_sheet("Table of Contents")
    contents.append([None, None, "DEMO01 Demo module"])
    contents.append(["Template code", "Description", MODULE])
    contents.append(["T01.00.01", "T01.00.01 DEMO"])
    contents.append([CLOSED_TABLE, "DEMO TABLE", CLOSED_TABLE])
    contents.append(["T02.00.01", "T02.00.01 DESKS"])
    contents.append([OPEN_TABLE, "DESK TABLE", OPEN_TABLE])

    _closed_sheet(workbook.create_sheet(CLOSED_TABLE))
    _open_sheet(workbook.create_sheet(OPEN_TABLE))

    enumerations = workbook.create_sheet("Enumerations")
    # row 1: the fixed z-axis of the closed table. The EMPTY first entry is the
    # all-default "Total" sheet, exactly as the publisher leaves it.
    enumerations["B1"] = "Euro (0002): eba_dim:CUE (Currency of the exposure) eba_CU:EUR (Euro)"
    workbook.save(path)
    return path


def _closed_sheet(sheet: Any) -> None:
    sheet["A1"] = f"{CLOSED_TABLE} - {CLOSED_TABLE} DEMO TABLE"
    _grey(sheet, "A3", "Sheets (Z1)")
    dropdown = DataValidation(type="list", formula1="Enumerations!$A$1:$B$1")
    dropdown.add("B3")
    sheet.add_data_validation(dropdown)
    _grey(sheet, "D5", "Amount")
    _grey(sheet, "E5", "Other")
    sheet["F5"] = "eba_dim:MCY (Main category)"
    _grey(sheet, "D6", "0010")
    _grey(sheet, "E6", "0020")
    _grey(sheet, "A7", "Total")
    _grey(sheet, "C7", "0010")
    sheet["F7"] = "eba_MC:x1 (All)"
    _grey(sheet, "B8", "Of which: part")
    _grey(sheet, "C8", "0020")
    _grey(sheet, "E8", None)  # greyed: not reportable according to the workbook
    sheet["F8"] = "eba_MC:x2 (Part)"
    sheet["C9"] = "Metrics"
    sheet["D9"] = "eba_met:mi1 (Amount)"
    sheet["E9"] = "eba_met:mi2 (Other amount)"
    sheet["C10"] = "eba_dim:BAS (Base)"
    sheet["D10"] = "eba_BA:x9 (Exposures)"
    sheet["E10"] = "eba_BA:x0 (Not applicable)"  # a default member, stated explicitly


def _open_sheet(sheet: Any) -> None:
    sheet["A1"] = f"{OPEN_TABLE} - {OPEN_TABLE} DESK TABLE"
    _grey(sheet, "B3", "Desk name")
    _grey(sheet, "A4", 'Desk number "mandatory" (0005) String used as an artificial identifier')
    sheet["A4"].comment = Comment("eba_dim:UDI (Unique desk identifier)", "builder")
    _grey(sheet, "B4", "0010")
    sheet["A6"] = "Metrics"
    sheet["B6"] = "eba_met:si3 (Desk name)"
    sheet["A7"] = "eba_dim:BAS (Base)"
    sheet["B7"] = "eba_BA:x9 (Exposures)"


def _grey(sheet: Any, cell: str, value: str | None) -> None:
    sheet[cell] = value
    sheet[cell].fill = GREY


# ── Dictionary workbook ───────────────────────────────────────────────────────


def build_dictionary_workbook(path: Path) -> Path:
    """Write the miniature DPM dictionary workbook and return its path."""
    workbook = Workbook()
    domains = workbook.active
    domains.title = "Domains"
    domains.append(["Label (en)", "Code", "Description (en)", "Type", "Owner", "Data type"])
    for code, kind, data_type in (
        ("BA", "explicit", None),
        ("MC", "explicit", None),
        ("CU", "explicit", None),
        ("IS", "typed", "STRING"),
    ):
        domains.append([code, code, None, kind, "eba", data_type])

    dimensions = workbook.create_sheet("Dimensions")
    dimensions.append(
        ["Label (en)", "Code", "Description (en)", "Owner", "Domain owner", "Domain code"]
        + ["Default member code", "Default member owner"]
    )
    for label, code, domain in (
        ("Base", "BAS", "BA"),
        ("Main category", "MCY", "MC"),
        ("Currency of the exposure", "CUE", "CU"),
        ("Unique desk identifier", "UDI", "IS"),
    ):
        dimensions.append([label, code, None, "eba", "eba", domain, None, None])

    metrics = workbook.create_sheet("Metrics")
    metrics.append(
        ["Label (en)", "Code", "Description (en)", "Owner", "Data type"]
        + ["Referenced domain owner", "Referenced domain code"]
        + ["Referenced hierarchy owner", "Referenced hierarchy code", "Period type"]
    )
    metrics.append(["Amount", "mi1", None, "eba", "MONETARY", None, None, None, None, "instant"])
    metrics.append(
        ["Other amount", "mi2", None, "eba", "MONETARY", None, None, None, None, "instant"]
    )
    metrics.append(["Desk name", "si3", None, "eba", "STRING", None, None, None, None, "instant"])

    for domain, members in (
        ("BA", ("x0", "x9")),
        ("MC", ("x0", "x1", "x2")),
        ("CU", ("x0", "EUR")),
    ):
        sheet = workbook.create_sheet(f"eba_{domain}")
        sheet.append(["Label (en)", "Code", "Description (en)", "Owner", "Release", "Default"])
        for member in members:
            sheet.append([member, member, None, "eba", None, str(member == "x0")])
    workbook.save(path)
    return path


# ── Taxonomy package ──────────────────────────────────────────────────────────


def build_taxonomy_package(root: Path) -> Path:
    """Write an extracted taxonomy package tree under ``root`` and return it."""
    base = root / "www.example.test/fws/demo/2026-01-01"
    _write(
        root / "META-INF/taxonomyPackage.xml",
        '<tp:taxonomyPackage xmlns:tp="http://xbrl.org/2016/taxonomy-package"><tp:entryPoints>'
        f'<tp:entryPoint><tp:name>{MODULE}</tp:name><tp:entryPointDocument href="{ENTRY_POINT}"/>'
        "</tp:entryPoint></tp:entryPoints></tp:taxonomyPackage>",
    )
    _write(base / "mod/demo01.xsd", '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"/>')
    arcs = ""
    for number, table in enumerate((CLOSED_TABLE, OPEN_TABLE), 1):
        stem = table.lower()
        arcs += (
            f'<link:loc xlink:href="../tab/tab.xsd#boe_tg{table[:-3]}" xlink:label="g{number}"/>'
            f'<link:loc xlink:href="../tab/{stem}/{stem}-rend.xml#boe_t{table}" xlink:label="t{number}"/>'
            f'<gen:arc xlink:from="g{number}" xlink:to="t{number}"/>'
        )
    _write(base / "mod/demo01-pre.xml", _linkbase(f"<gen:link>{arcs}</gen:link>"))

    closed = base / "tab" / CLOSED_TABLE.lower()
    stem = CLOSED_TABLE.lower()
    _write(
        closed / f"{stem}-rend.xml",
        _linkbase(
            f'<gen:link><table:table id="boe_t{CLOSED_TABLE}" xlink:label="t"/>'
            '<table:breakdown id="boe_a3" xlink:label="a3"/>'
            '<table:tableBreakdownArc xlink:from="t" xlink:to="a3" axis="z"/>'
            '<table:ruleNode id="boe_a3.root" xlink:label="a3.root" abstract="true"/>'
            '<table:breakdownTreeArc xlink:from="a3" xlink:to="a3.root"/>'
            '<table:ruleNode id="boe_c1" xlink:label="c1"/>'
            '<table:definitionNodeSubtreeArc xlink:from="a3.root" xlink:to="c1"/>'
            '<table:ruleNode id="boe_c2" xlink:label="c2"><formula:explicitDimension '
            'dimension="eba_dim:CUE"><formula:member><formula:qname>eba_CU:EUR</formula:qname>'
            "</formula:member></formula:explicitDimension></table:ruleNode>"
            '<table:definitionNodeSubtreeArc xlink:from="a3.root" xlink:to="c2"/></gen:link>'
        ),
    )
    _write(
        closed / f"{stem}-lab-codes.xml",
        labels_linkbase(
            f"{stem}-rend.xml",
            [
                (f"boe_t{CLOSED_TABLE}", "rc-code", CLOSED_TABLE),
                (f"boe_t{CLOSED_TABLE}", "filing-indicator-code", "T01.00.01"),
                ("boe_c1", "rc-code", "0001"),
                ("boe_c2", "rc-code", "0002"),
            ],
        ),
    )
    _write(
        closed / f"{stem}-lab-en.xml",
        labels_linkbase(
            f"{stem}-rend.xml", [("boe_c1", "label", "Total"), ("boe_c2", "label", "Euro")]
        ),
    )
    currency = ("eba_CUE", "eba_CU", "cu", ["x0", "EUR"])
    _write(
        closed / f"{stem}-def.xml",
        definition_linkbase(
            [
                (
                    "eba_mi1",
                    [("eba_BAS", "eba_BA", "ba", ["x9"]), ("eba_MCY", "eba_MC", "mc", ["x1"])],
                )
                + ([currency],),
                # the second cube parks CUE's members in another role (xbrldt:targetRole)
                (
                    "eba_mi2",
                    [
                        ("eba_BAS", "eba_BA", "ba", ["x0"]),
                        ("eba_MCY", "eba_MC", "mc", ["x1", "x2"]),
                    ],
                )
                + ([currency],),
            ],
            park_last_dimension=(False, True),
        ),
    )

    opened = base / "tab" / OPEN_TABLE.lower()
    stem = OPEN_TABLE.lower()
    _write(
        opened / f"{stem}-rend.xml",
        _linkbase(f'<gen:link><table:table id="boe_t{OPEN_TABLE}" xlink:label="t"/></gen:link>'),
    )
    _write(
        opened / f"{stem}-lab-codes.xml",
        labels_linkbase(
            f"{stem}-rend.xml",
            [
                (f"boe_t{OPEN_TABLE}", "rc-code", OPEN_TABLE),
                (f"boe_t{OPEN_TABLE}", "filing-indicator-code", OPEN_TABLE),
            ],
        ),
    )
    _write(opened / f"{stem}-lab-en.xml", labels_linkbase(f"{stem}-rend.xml", []))
    _write(
        opened / f"{stem}-def.xml",
        definition_linkbase(
            [("eba_si3", [("eba_BAS", "eba_BA", "ba", ["x9"]), ("eba_UDI", None, None, [])], [])]
        ),
    )
    return root


def zip_package(root: Path, archive: Path) -> Path:
    """Zip an extracted package under a top-level folder, as publishers ship it."""
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                bundle.write(path, f"demo-v999/{path.relative_to(root).as_posix()}")
    return archive


def labels_linkbase(rendering: str, labels: list[tuple[str, str, str]]) -> str:
    """A generic-label linkbase: ``(node id, role suffix, text)`` per label."""
    body = ""
    for number, (node, role, text) in enumerate(labels):
        body += (
            f'<link:loc xlink:href="{rendering}#{node}" xlink:label="loc{number}"/>'
            f'<label:label xlink:label="lab{number}" '
            f'xlink:role="http://www.eurofiling.info/xbrl/role/{role}">{text}</label:label>'
            f'<gen:arc xlink:from="loc{number}" xlink:to="lab{number}"/>'
        )
    return _linkbase(f"<gen:link>{body}</gen:link>")


def definition_linkbase(
    cubes: list[tuple[Any, ...]], park_last_dimension: tuple[bool, ...] = ()
) -> str:
    """A definition linkbase of closed hypercubes.

    Each cube is ``(metric id, dimensions, more dimensions)``; a dimension is
    ``(dimension id, domain id, domain folder, member codes)``, with ``None`` for
    the domain of a typed dimension. ``park_last_dimension[i]`` moves cube i's last
    dimension's members into a separate link role reached by ``xbrldt:targetRole``.
    """
    links = ""
    for number, (metric, first, more) in enumerate(cubes):
        dimensions = [*first, *more]
        parked = number < len(park_last_dimension) and park_last_dimension[number]
        role, side_role = f"{ROLE}{number}", f"{ROLE}{number}/side"
        body = (
            f'<link:loc xlink:href="{EBA}/met/met.xsd#{metric}" xlink:label="m"/>'
            f'<link:loc xlink:href="{HYPERCUBE}" xlink:label="h"/>'
            '<link:definitionArc xlink:arcrole="http://xbrl.org/int/dim/arcrole/all" '
            'xlink:from="m" xlink:to="h" xbrldt:closed="true"/>'
        )
        side = ""
        for position, (dimension, domain, folder, members) in enumerate(dimensions):
            is_parked = parked and position == len(dimensions) - 1
            target = f' xbrldt:targetRole="{side_role}"' if is_parked else ""
            locator = (
                f'<link:loc xlink:href="{EBA}/dim/dim.xsd#{dimension}" xlink:label="d{position}"/>'
            )
            body += locator + (
                '<link:definitionArc xlink:arcrole="http://xbrl.org/int/dim/arcrole/'
                f'hypercube-dimension" xlink:from="h" xlink:to="d{position}"{target}/>'
            )
            if domain is None:
                continue
            arcs = (
                f'<link:loc xlink:href="{EBA}/dom/exp.xsd#{domain}" xlink:label="o{position}"/>'
                '<link:definitionArc xlink:arcrole="http://xbrl.org/int/dim/arcrole/'
                f'dimension-domain" xlink:from="d{position}" xlink:to="o{position}" '
                'xbrldt:usable="false"/>'
            )
            for member in members:
                arcs += (
                    f'<link:loc xlink:href="{EBA}/dom/{folder}/mem.xsd#eba_{member}" '
                    f'xlink:label="e{position}{member}"/>'
                    '<link:definitionArc xlink:arcrole="http://xbrl.org/int/dim/arcrole/'
                    f'domain-member" xlink:from="o{position}" xlink:to="e{position}{member}"/>'
                )
            if is_parked:
                side += locator + arcs
            else:
                body += arcs
        links += f'<link:definitionLink xlink:role="{role}">{body}</link:definitionLink>'
        if side:
            links += f'<link:definitionLink xlink:role="{side_role}">{side}</link:definitionLink>'
    return _linkbase(links)


def _linkbase(body: str) -> str:
    return f"<link:linkbase {NAMESPACES}>{body}</link:linkbase>"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── Instance -> pack mapping (integration test) ───────────────────────────────


def map_instance(pack: dict[str, Any], instance: Path) -> collections.Counter[str]:
    """Stream an XBRL instance and count, per fact, how many pack cells it maps to.

    Returns a counter with ``facts``, ``unmapped``, ``one_cell``, ``many_cells`` and
    ``cells_hit``. A fact maps to a cell when the metric and every explicit member
    are equal and the fact's remaining dimensions are exactly the cell's open ones
    (``*open?`` may be absent). Matching is by namespace URI, not by prefix.
    """
    prefix_of = {uri: prefix for prefix, uri in pack["namespaces"].items()}
    cells_of: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)
    for code, table in pack["tables"].items():
        for position, cell in enumerate(table["cells"]):
            cells_of[cell[3]].append((code, position))
    by_key: dict[Any, list[tuple[int, dict[str, str]]]] = collections.defaultdict(list)
    openable: dict[str, set[str]] = collections.defaultdict(set)
    for number, (metric, flat) in enumerate(pack["datapoints"]):
        pairs = list(zip(flat[0::2], flat[1::2], strict=True))
        fixed = frozenset((d, m) for d, m in pairs if not m.startswith("*"))
        by_key[(metric, fixed)].append((number, {d: m for d, m in pairs if m.startswith("*")}))
        openable[metric].update(d for d, m in pairs if m.startswith("*open"))

    def qname(clark: str) -> str:
        uri, _, local = clark[1:].partition("}")
        return f"{prefix_of.get(uri, '{' + uri + '}')}:{local}"

    xbrli, xbrldi = "{http://www.xbrl.org/2003/instance}", "{http://xbrl.org/2006/xbrldi}"
    skipped = {f"{xbrli}unit", "{http://www.xbrl.org/2003/linkbase}schemaRef"}
    declared: dict[str, str] = {}
    contexts: dict[str, tuple[frozenset[tuple[str, str]], frozenset[str]]] = {}
    counts: collections.Counter[str] = collections.Counter()
    hit: set[tuple[str, int]] = set()
    depth = 0
    for event, element in ET.iterparse(instance, events=("start-ns", "start", "end")):
        if event == "start-ns":
            declared[element[0]] = element[1]
            continue
        if event == "start":
            depth += 1
            continue
        depth -= 1
        if depth != 1:
            continue
        if element.tag == f"{xbrli}context":
            explicit, typed = [], []
            for member in element.iter():
                if member.tag not in {f"{xbrldi}explicitMember", f"{xbrldi}typedMember"}:
                    continue
                prefix, _, local = member.get("dimension").partition(":")
                dimension = f"{prefix_of.get(declared[prefix], prefix)}:{local}"
                if member.tag == f"{xbrldi}typedMember":
                    typed.append(dimension)
                else:
                    prefix, _, local = member.text.strip().partition(":")
                    explicit.append(
                        (dimension, f"{prefix_of.get(declared[prefix], prefix)}:{local}")
                    )
            contexts[element.get("id")] = (frozenset(explicit), frozenset(typed))
        elif element.tag not in skipped and not element.tag.endswith("}fIndicators"):
            counts["facts"] += 1
            explicit, typed = contexts[element.get("contextRef")]
            metric = qname(element.tag)
            matched = _matching_cells(by_key, cells_of, openable[metric], metric, explicit, typed)
            hit.update(matched)
            counts[
                "unmapped" if not matched else "one_cell" if len(matched) == 1 else "many_cells"
            ] += 1
        element.clear()
    counts["cells_hit"] = len(hit)
    return counts


def _matching_cells(
    by_key: dict[Any, list[tuple[int, dict[str, str]]]],
    cells_of: dict[int, list[tuple[str, int]]],
    openable: set[str],
    metric: str,
    explicit: frozenset[tuple[str, str]],
    typed: frozenset[str],
) -> list[tuple[str, int]]:
    """Cells whose data point equals the fact, trying each subset of open dimensions."""
    matched: list[tuple[str, int]] = []
    explicit_dims = {d for d, _ in explicit}
    for opened in _subsets(explicit_dims & openable):
        fixed = frozenset(p for p in explicit if p[0] not in opened)
        for number, placeholders in by_key.get((metric, fixed), ()):
            reported = opened | typed
            required = {d for d, marker in placeholders.items() if marker != "*open?"}
            typed_ok = all(placeholders.get(d, "").startswith("*typed:") for d in typed)
            explicit_ok = all(placeholders.get(d, "").startswith("*open") for d in opened)
            if required <= reported <= placeholders.keys() and typed_ok and explicit_ok:
                matched.extend(cells_of[number])
    return matched


def _subsets(dimensions: set[str]) -> list[frozenset[str]]:
    """The empty set and every 1- or 2-dimension subset (a cell has at most two open ones)."""
    ordered = sorted(dimensions)
    found = [frozenset[str]()]
    found += [frozenset({d}) for d in ordered]
    found += [frozenset({a, b}) for i, a in enumerate(ordered) for b in ordered[i + 1 :]]
    return found
