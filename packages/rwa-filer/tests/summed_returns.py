"""
Returns that tell the two readings of a summed reference apart, for Arelle and the engine.

A summed reference in a published rule (``seq: True``) adds up either every row
or member of an open dimension, or only those the rest of the rule is read at,
and the rule's TEXT does not say which: the XBRL formula does, by covering the
dimension on the summed variable or leaving it uncovered. The engine once read
the text alone, and summed every obligor grade in ``boe_b0760``-``b0763`` —
failing every grade of every OF 08.02 sheet with more than one. Nothing caught
it, because the Bank's own sample instance has ONE open row per open-row table
and no member on OF 08.06's open axis: on it, the two readings agree.

These returns are built so that they disagree. Each open-row table carries
several rows and OF 08.06 two types of specialised lending, and each family has
a row (or member) that holds and one that breaks, so a verdict alone cannot
hide a wrong count (``.claude/LESSONS.md`` B5). They cover every rule the scan
of 2026-11-16 found the text-only reading got wrong, in every packaged rule book
with a taxonomy pack, plus the ``boe_b0752`` / ``boe_b0814`` family as the
control whose sum genuinely spans every grade:

- PRA001: OF 08.02 (``boe_b0760``-``b0763``) beside OF 08.01's class total
  (``boe_b0752_*``, ``boe_b0814_*``); OF 08.06 beside OF 08.01 r0080
  (``boe_b0816``-``b0822``, ``boe_b1043``); C 14.00 / C 14.01
  (``v7372_m``-``v7377_m``); C 06.02 (``v11871_m``).
- PRA116: SC 14.00 / SC 14.01 (``boe_b0117_ss``-``b0122_ss``); SC 06.02
  (``v11871_m``).
- MRL003: BR 01.00 (``boe_b4101``, ``boe_b4102``).

Arelle's counts on these returns are pinned in
``tests/releases/4.1.1/oracles/summed_references_oracle.json``; regenerate with
the referee, never by hand::

    uv run python packages/rwa-filer/tests/summed_returns.py \\
        --taxonomy-package .taxonomy/boe-banking-4.1.1/boe-banking-v411.zip \\
        --arelle-python <python with arelle-release>

References:
- XBRL Variables 1.0 — bind as sequence, covered aspects, implicit filtering
- docs/development/escape-log.md, 2026-11-16
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Final

import polars as pl

from rwa_filer.model import DECIMALS_EXACT, CanonicalReturn, ReturnHeader
from rwa_filer.taxonomy.pack import TaxonomyPack, load_packaged

LEI: Final = "5493001KJTIIGC8Y1R12"
REFERENCE_DATE: Final = date(2027, 3, 31)
#: The release the returns are written against, and the packs they use.
RELEASE: Final = "4.1.1"
PACKS: Final = {"PRA001": "pra001-4.1.1", "PRA116": "pra116-4.1.1", "MRL003": "mrl003-4.1.1"}

#: The rules each return exists for, and the control family beside them. The
#: oracle holds Arelle's counts for exactly these; a pattern, so that a family
#: is enumerated by its prefix rather than by the members someone remembered.
RULES: Final = {
    "PRA001": (
        r"^(boe_b076[0-3]|boe_b0752_\d+|boe_b0814_\d+|boe_b081[6-9]|boe_b082[0-2]|boe_b1043"
        r"|v737[2-7]_m|v11871_m)$"
    ),
    "PRA116": r"^(boe_b011[7-9]_ss|boe_b012[0-2]_ss|v11871_m)$",
    "MRL003": r"^(boe_b410[12])$",
}

_COLUMNS: Final = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]

# OF 08.02 sheet 0001, three obligor grades. The (-) columns are reported
# negative. Grades 1 and 2 foot on every identity; grade 3 breaks the outflow
# subtotal (0070: -20 - 5 + 0 = -25, reported -30) and the RWEA after
# adjustments (0260: 30 + 3 + 0 + 0 = 33, reported 40), and foots on the rest.
_GRADES: Final = {
    1: {"0020": 1000, "0035": -50, "0040": -60, "0050": -30, "0060": -10, "0070": -100,
        "0080": 20, "0090": 870, "0251": 100, "0252": 10, "0253": 5, "0254": -15,
        "0260": 100, "0280": 40, "0281": -4, "0282": 36},
    2: {"0020": 500, "0035": 0, "0040": -50, "0050": 0, "0060": 0, "0070": -50,
        "0080": 0, "0090": 450, "0251": 60, "0252": 0, "0253": 0, "0254": 0,
        "0260": 60, "0280": 10, "0281": 0, "0282": 10},
    3: {"0020": 300, "0035": 0, "0040": -20, "0050": -5, "0060": 0, "0070": -30,
        "0080": 0, "0090": 270, "0251": 30, "0252": 3, "0253": 0, "0254": 0,
        "0260": 40, "0280": 6, "0281": 1, "0282": 7},
}  # fmt: skip

#: OF 08.06's total row (0095) for two types of specialised lending, by column,
#: and OF 08.01 r0080's matching column on each of sheets 0002 and 0010. Each
#: published identity is "the sum over every type equals the class figure,
#: which both sheets show"; it holds for every pair here but c0080 vs c0260.
#: Read one type at a time, every one of them breaks.
_SLOTTING: Final = {
    # OF 08.06 column: (OF 08.01 table, column, x132, x129, the class figure)
    "0010": ("OF08.01.01.01", "0020", 100, 50, 150),
    "0020": ("OF08.01.01.01", "0090", 90, 40, 130),
    "0030": ("OF08.01.01.02", "0100", 20, 10, 30),
    "0031": ("OF08.01.01.02", "0100", 25, 5, 30),
    "0040": ("OF08.01.01.01", "0110", 80, 30, 110),
    "0050": ("OF08.01.01.02", "0120", 5, 5, 10),
    "0060": ("OF08.01.01.02", "0130", 4, 6, 10),
    "0080": ("OF08.01.01.01", "0260", 70, 35, 99),
}

#: C 14.01 (summed over two of its sheets) against C 14.00's cap of 100, per
#: securitisation and column. S1 is within the cap everywhere; S2 is over it on
#: 0310 only. Summed over BOTH securitisations every column is over the cap —
#: so a sum that wrongly spans the rows breaks for both, on every column.
_CAP: Final = 100
_SECURITISATIONS: Final = {
    "S1": {"0310": (30, 20), "other": (40, 20)},
    "S2": {"0310": (70, 50), "other": (30, 30)},
}


def build_returns() -> dict[str, CanonicalReturn]:
    """The three returns, by module."""
    return {
        "PRA001": _pra001(load_packaged(PACKS["PRA001"])),
        "PRA116": _pra116(load_packaged(PACKS["PRA116"])),
        "MRL003": _mrl003(load_packaged(PACKS["MRL003"])),
    }


def oracle_path() -> Path:
    """Where Arelle's counts on these returns are kept."""
    return (
        Path(__file__).parent / "releases" / RELEASE / "oracles" / "summed_references_oracle.json"
    )


# =============================================================================
# The returns
# =============================================================================


def _pra001(pack: TaxonomyPack) -> CanonicalReturn:
    rows: list[tuple[Any, ...]] = []
    # OF 08.02, and OF 08.01's class total (r0070) as the sum over the grades.
    for grade, figures in _GRADES.items():
        row = f"g{grade}"
        rows.append(("OF08.02.01.01", "0001", None, row, "0005", None, str(grade), None))
        rows += [
            ("OF08.02.01.01", "0001", None, row, column, value, None, 0)
            for column, value in figures.items()
        ]
    for column in _GRADES[1]:
        total = sum(figures[column] for figures in _GRADES.values())
        rows.append(("OF08.01.01.01", "0001", None, "0070", column, total, None, 0))
    # OF 08.06 over two members of its open axis, and OF 08.01 r0080.
    for column, (table, class_column, first, second, figure) in _SLOTTING.items():
        rows.append(("OF08.06.01.01", None, "x132", "0095", column, first, None, 0))
        rows.append(("OF08.06.01.01", None, "x129", "0095", column, second, None, 0))
        rows += [
            (table, sheet, None, "0080", class_column, figure, None, 0)
            for sheet in ("0002", "0010")
        ]
    # Two OF 08.06 columns are tied to the one OF 08.01.01.02 c0100: one fact.
    rows = list(dict.fromkeys(rows))
    rows += _securitisations("C14.00.01.01", "C14.01.01.01", ("0010", "0020"))
    rows += _group_entities(pack, "C06.02.01.01")
    return _return("PRA001", rows)


def _pra116(pack: TaxonomyPack) -> CanonicalReturn:
    rows = _securitisations("SC14.00.01.01", "SC14.01.01.01", ("0010", "0020"))
    rows += _group_entities(pack, "SC06.02.01.01")
    return _return("PRA116", rows)


def _mrl003(pack: TaxonomyPack) -> CanonicalReturn:
    """Two instruments: I1 reports every column of BR 01.00, I2 every column but 090.

    ``boe_b4102`` (every column reported) holds for I1 and breaks for I2;
    ``boe_b4101`` (a 060/070/080 triple where 050 is ``x8002``) holds for both.
    """
    table = pack.tables["BR01.00.01.01"]
    key = table.open_keys[0].code
    rows: list[tuple[Any, ...]] = []
    for instrument, skipped in (("I1", ()), ("I2", ("090",))):
        rows.append(("BR01.00.01.01", None, None, instrument, key, None, instrument, None))
        for column, _label in table.columns:
            if column in skipped or column == key:
                continue
            if column == "050":
                rows.append(
                    (
                        "BR01.00.01.01",
                        None,
                        None,
                        instrument,
                        column,
                        None,
                        "boe_eba_TA:x8002",
                        None,
                    )
                )
                continue
            rows.append(
                ("BR01.00.01.01", None, None, instrument, *_typed(pack, table.code, None, column))
            )
    return _return("MRL003", rows)


# =============================================================================
# Shared shapes
# =============================================================================


def _securitisations(header: str, positions: str, sheets: tuple[str, ...]) -> list[tuple[Any, ...]]:
    """C 14.00 caps (0230-0280) and C 14.01 positions (0310-0360), per securitisation."""
    rows: list[tuple[Any, ...]] = []
    for code, figures in _SECURITISATIONS.items():
        rows.append((header, None, None, code, "0010", None, code, None))
        for cap_column in ("0230", "0240", "0250", "0260", "0270", "0280"):
            rows.append((header, None, None, code, cap_column, _CAP, None, 0))
        for position, sheet in enumerate(sheets):
            rows.append((positions, sheet, None, code, "0010", None, code, None))
            for column in ("0310", "0320", "0330", "0340", "0350", "0360"):
                value = figures.get(column, figures["other"])[position]
                rows.append((positions, sheet, None, code, column, value, None, 0))
    return rows


def _group_entities(pack: TaxonomyPack, code: str) -> list[tuple[Any, ...]]:
    """C 06.02: E1 reports all four of 0011/0030/0040/0050, E2 three of them.

    ``v11871_m`` — "an entity that reports a figure reports all four" — holds
    for E1 and breaks for E2.
    """
    table = pack.tables[code]
    rows: list[tuple[Any, ...]] = []
    group_key, entity_key = (key.code for key in table.open_keys)
    member = next(key for key in table.open_keys if key.code == group_key).members[0]
    for entity, required in (
        ("E1", ("0011", "0030", "0040", "0050")),
        ("E2", ("0011", "0030", "0040")),
    ):
        row = f"{entity}"
        rows.append((code, None, None, row, group_key, None, member.rpartition(":")[2], None))
        rows.append((code, None, None, row, entity_key, None, entity, None))
        for column in (*required, "0060"):
            rows.append((code, None, None, row, *_typed(pack, code, None, column)))
    return rows


def _typed(pack: TaxonomyPack, table: str, sheet: str | None, column: str) -> tuple[Any, ...]:
    """``(column, value, text_value, decimals)`` of the cell's own data type."""
    cells = pack.cells.filter((pl.col("table") == table) & (pl.col("column") == column))
    if sheet is not None:
        cells = cells.filter(pl.col("sheet") == sheet)
    datapoint = pack.datapoint(int(cells["datapoint"][0]))
    metric = pack.metrics[datapoint.metric]
    kind = metric.data_type
    if kind == "monetary":
        return (column, 1000.0, None, 0)
    if kind in ("decimal", "percentage"):
        return (column, 0.5, None, 4)
    if kind == "integer":
        return (column, 1.0, None, DECIMALS_EXACT)
    if kind == "date":
        return (column, None, REFERENCE_DATE.isoformat(), None)
    if kind == "boolean":
        return (column, None, "true", None)
    if kind == "enumeration" and metric.enumeration is not None:
        return (column, None, pack.enumerations[metric.enumeration][0], None)
    return (column, None, f"text {column}", None)


def _return(module: str, rows: list[tuple[Any, ...]]) -> CanonicalReturn:
    header = ReturnHeader(entity_identifier=LEI, reference_date=REFERENCE_DATE, module=module)
    return CanonicalReturn.from_frame(header, pl.DataFrame(rows, schema=_COLUMNS, orient="row"))


# =============================================================================
# Regenerating the oracle — needs Arelle and the Bank's taxonomy package
# =============================================================================


def _measure(taxonomy_package: Path, arelle_python: Path | None) -> dict[str, Any]:
    from rwa_filer.referee.runner import run_referee
    from rwa_filer.xbrl.writer import write_instance

    measured: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for module, ret in build_returns().items():
            instance = write_instance(ret, load_packaged(PACKS[module]))
            path = Path(scratch) / f"{module}.xbrl"
            content = instance.content
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            result = run_referee(
                path,
                taxonomy_package,
                python=arelle_python,
                rules=RULES[module],
                filing_rules=False,
            )
            if not result.complete or result.errors:
                raise SystemExit(f"{module}: Arelle did not finish cleanly: {result.errors}")
            measured[module] = {
                "facts": instance.facts,
                "rules": {
                    rule_id: [verdict.satisfied, verdict.unsatisfied]
                    for rule_id, verdict in sorted(result.rules.items())
                },
            }
    return measured


def _arelle_version(arelle_python: Path | None) -> str:
    from rwa_filer.referee.runner import find_arelle_python

    interpreter = find_arelle_python(arelle_python)
    probe = "from importlib.metadata import version; print(version('arelle-release'))"
    found = subprocess.run(  # noqa: S603 - the interpreter the referee itself runs
        [str(interpreter), "-I", "-c", probe], capture_output=True, text=True, check=True
    )
    return f"arelle-release {found.stdout.strip()}"


def main(argv: list[str] | None = None) -> int:
    """Re-measure the oracle with Arelle and write it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--taxonomy-package", type=Path, required=True)
    parser.add_argument("--arelle-python", type=Path)
    args = parser.parse_args(argv)
    oracle = {
        "_comment": (
            "Arelle's verdict, as [satisfied, unsatisfied] evaluation counts, on the "
            "returns tests/summed_returns.py builds: every rule whose summed reference "
            "the text alone misreads, and the boe_b0752/b0814 control family. "
            "Regenerate with that module's main, never by hand."
        ),
        "processor": _arelle_version(args.arelle_python),
        "taxonomy": f"Bank of England Banking Taxonomy v{RELEASE}",
        "returns": _measure(args.taxonomy_package, args.arelle_python),
    }
    path = oracle_path()
    path.write_text(json.dumps(oracle, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
