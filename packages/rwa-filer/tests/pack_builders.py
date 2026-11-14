"""
A small synthetic taxonomy pack for the tests.

The real packs are compiled from the publisher's files and are large; these
tests need to pin BEHAVIOUR — a greyed cell, a fixed sheet axis, an open one,
an open-row table, a data point shown in two tables — on something a reader can
hold in their head. ``SAMPLE_COMPILED`` is that: a hand-written compiled pack
in the format ``compiler.compile_pack`` produces, for an invented module
``TST001``.

It is test data, not a statement about any real taxonomy.

Tables
- ``T01.00.01.01`` — one sheet, rows 0010/0020/0030, columns 0010 (monetary),
  0020 (percentage), 0030 (string). Cell (0030, 0020) is NOT reportable.
- ``T02.00.01.01`` — fixed sheet axis 0001/0002, rows 0010/0020, column 0010.
- ``T03.00.01.01`` — open sheet axis over ``eba_dim:CEG``: x1 (total), GB, FR.
- ``T04.00.01.01`` — open rows keyed by column 0005; column 0010 (monetary),
  column 0020 (integer).
- ``T05.00.01.01`` / ``T05.00.01.02`` — both show one data point at (0010, 0010).
- ``T06.00.01.01`` — typed cells: 0010 boolean, 0020 date, 0030 enumeration.
- ``T07.00.01.01`` — OPTIONAL open sheet axis over ``tst_dim:TSL`` (default
  ``tst_TA:x0``): a fact with no open key is the "all" sheet, reported with
  the dimension absent.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.taxonomy.pack import TaxonomyPack, load_pack, write_pack

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl

SAMPLE_MODULE = "TST001"
SAMPLE_VALID_FROM = date(2027, 1, 1)
#: A real, checksum-valid LEI, used wherever a test needs a header.
VALID_LEI = "5493001KJTIIGC8Y1R12"

_DATAPOINTS: list[list[Any]] = [
    ["tst_met:mi1", ["tst_dim:BAS", "tst_BA:x1"]],  # 0  T01 r0010 c0010
    ["tst_met:pi1", ["tst_dim:BAS", "tst_BA:x1"]],  # 1  T01 r0010 c0020
    ["tst_met:si1", ["tst_dim:BAS", "tst_BA:x1"]],  # 2  T01 r0010 c0030
    ["tst_met:mi1", ["tst_dim:BAS", "tst_BA:x2"]],  # 3  T01 r0020 c0010
    ["tst_met:pi1", ["tst_dim:BAS", "tst_BA:x2"]],  # 4  T01 r0020 c0020
    ["tst_met:si1", ["tst_dim:BAS", "tst_BA:x2"]],  # 5  T01 r0020 c0030
    ["tst_met:mi1", ["tst_dim:BAS", "tst_BA:x3"]],  # 6  T01 r0030 c0010
    ["tst_met:si1", ["tst_dim:BAS", "tst_BA:x3"]],  # 7  T01 r0030 c0030
    ["tst_met:mi2", ["tst_dim:EXC", "tst_EC:x1"]],  # 8  T02 z0001 r0010
    ["tst_met:mi3", ["tst_dim:EXC", "tst_EC:x1"]],  # 9  T02 z0001 r0020
    ["tst_met:mi2", ["tst_dim:EXC", "tst_EC:x2"]],  # 10 T02 z0002 r0010
    ["tst_met:mi3", ["tst_dim:EXC", "tst_EC:x2"]],  # 11 T02 z0002 r0020
    ["tst_met:mi4", ["eba_dim:CEG", "*open"]],  # 12 T03 r0010
    ["tst_met:mi5", ["eba_dim:CEG", "*open"]],  # 13 T03 r0020
    ["tst_met:mi6", ["tst_dim:OGR", "*typed:tst_typ:ID"]],  # 14 T04 c0010
    ["tst_met:ii1", ["tst_dim:OGR", "*typed:tst_typ:ID"]],  # 15 T04 c0020
    ["tst_met:mi7", []],  # 16 T05.01 and T05.02, r0010 c0010
    ["tst_met:bi1", []],  # 17 T06 c0010
    ["tst_met:di1", []],  # 18 T06 c0020
    ["tst_met:ei1", []],  # 19 T06 c0030
    ["tst_met:mi8", ["tst_dim:TSL", "*open?"]],  # 20 T07 r0010
]

SAMPLE_COMPILED: dict[str, Any] = {
    "format": 1,
    "info": {
        "module": SAMPLE_MODULE,
        "title": "Test module",
        "taxonomy": "test-taxonomy",
        "version": "1.0.0",
        "entry_point": "http://example.test/xbrl/fws/test/2027-01-01/mod/tst001.xsd",
        "sources": {"annotated_workbook": "a.xlsx", "dictionary_workbook": "d.xlsx"},
        "irregularities": [],
    },
    "namespaces": {
        "tst_met": "http://example.test/xbrl/dict/met",
        "tst_dim": "http://example.test/xbrl/dict/dim",
        "tst_typ": "http://example.test/xbrl/dict/typ",
        "tst_BA": "http://example.test/xbrl/dict/dom/BA",
        "tst_EC": "http://example.test/xbrl/dict/dom/EC",
        "tst_TA": "http://example.test/xbrl/dict/dom/TA",
        "tst_ZZ": "http://example.test/xbrl/dict/dom/ZZ",
        "eba_dim": "http://www.eba.europa.eu/xbrl/crr/dict/dim",
        "eba_GA": "http://www.eba.europa.eu/xbrl/crr/dict/dom/GA",
    },
    "metrics": {
        "tst_met:mi1": {"type": "monetary", "period": "instant", "label": "Amount"},
        "tst_met:mi2": {"type": "monetary", "period": "instant", "label": "Exposure"},
        "tst_met:mi3": {"type": "monetary", "period": "instant", "label": "RWEA"},
        "tst_met:mi4": {"type": "monetary", "period": "instant", "label": "Geo exposure"},
        "tst_met:mi5": {"type": "monetary", "period": "instant", "label": "Geo RWEA"},
        "tst_met:mi6": {"type": "monetary", "period": "instant", "label": "Grade exposure"},
        "tst_met:mi7": {"type": "monetary", "period": "instant", "label": "Shared amount"},
        "tst_met:mi8": {"type": "monetary", "period": "instant", "label": "Lending amount"},
        "tst_met:pi1": {"type": "percentage", "period": "instant", "label": "Ratio"},
        "tst_met:ii1": {"type": "integer", "period": "instant", "label": "Obligors"},
        "tst_met:si1": {"type": "string", "period": "instant", "label": "Comment"},
        "tst_met:bi1": {"type": "boolean", "period": "instant", "label": "Flag"},
        "tst_met:di1": {"type": "date", "period": "instant", "label": "Date"},
        "tst_met:ei1": {
            "type": "enumeration",
            "period": "instant",
            "label": "Choice",
            "enumeration": "tst_ZZ:ZZ1",
        },
    },
    "dimensions": {
        "tst_dim:BAS": {"label": "Base", "domain": "tst_BA", "kind": "explicit", "default": None},
        "tst_dim:EXC": {"label": "Class", "domain": "tst_EC", "kind": "explicit", "default": None},
        "eba_dim:CEG": {
            "label": "Geography",
            "domain": "eba_GA",
            "kind": "explicit",
            "default": None,
        },
        "tst_dim:TSL": {
            "label": "Lending type",
            "domain": "tst_TA",
            "kind": "explicit",
            "default": "tst_TA:x0",
        },
        "tst_dim:OGR": {
            "label": "Obligor grade",
            "domain": "tst_ID",
            "kind": "typed",
            "typed_element": "tst_typ:ID",
            "typed_type": "integer",
        },
    },
    "enumerations": {"tst_ZZ:ZZ1": ["tst_ZZ:x1", "tst_ZZ:x2"]},
    "tables": {
        "T01.00.01.01": {
            "title": "Single sheet",
            "group": "T01.00.01",
            "filing_indicator": "T01.00.01",
            "rows": [["0010", "Total"], ["0020", "Part one"], ["0030", "Part two"]],
            "columns": [["0010", "Amount"], ["0020", "Ratio"], ["0030", "Comment"]],
            "open_rows": False,
            "open_keys": [],
            "z": [],
            "cells": [
                ["0010", "0010", None, 0, "workbook"],
                ["0010", "0020", None, 1, "workbook"],
                ["0010", "0030", None, 2, "workbook"],
                ["0020", "0010", None, 3, "workbook"],
                ["0020", "0020", None, 4, "workbook"],
                ["0020", "0030", None, 5, "workbook"],
                ["0030", "0010", None, 6, "workbook"],
                ["0030", "0030", None, 7, "workbook"],
            ],
        },
        "T02.00.01.01": {
            "title": "Fixed sheets",
            "group": "T02.00.01",
            "filing_indicator": "T02.00.01",
            "rows": [["0010", "Exposure"], ["0020", "RWEA"]],
            "columns": [["0010", "Amount"]],
            "open_rows": False,
            "open_keys": [],
            "z": [
                {
                    "kind": "fixed",
                    "code": "Z1",
                    "label": "Sheets",
                    "sheets": [
                        {
                            "code": "0001",
                            "label": "Class one",
                            "members": [["tst_dim:EXC", "tst_EC:x1"]],
                        },
                        {
                            "code": "0002",
                            "label": "Class two",
                            "members": [["tst_dim:EXC", "tst_EC:x2"]],
                        },
                    ],
                }
            ],
            "cells": [
                ["0010", "0010", "0001", 8, "workbook"],
                ["0020", "0010", "0001", 9, "workbook"],
                ["0010", "0010", "0002", 10, "workbook"],
                ["0020", "0010", "0002", 11, "linkbase"],
            ],
        },
        "T03.00.01.01": {
            "title": "Open sheets",
            "group": "T03.00.01",
            "filing_indicator": "T03.00.01",
            "rows": [["0010", "Exposure"], ["0020", "RWEA"]],
            "columns": [["0010", "Amount"]],
            "open_rows": False,
            "open_keys": [],
            "z": [
                {
                    "kind": "open",
                    "code": "0001",
                    "label": "Country",
                    "dimension": "eba_dim:CEG",
                    "members": ["eba_GA:x1", "eba_GA:GB", "eba_GA:FR"],
                    "default_allowed": False,
                }
            ],
            "cells": [
                ["0010", "0010", None, 12, "workbook"],
                ["0020", "0010", None, 13, "workbook"],
            ],
        },
        "T04.00.01.01": {
            "title": "Open rows",
            "group": "T04.00.01",
            "filing_indicator": "T04.00.01",
            "rows": [],
            "columns": [["0010", "Exposure"], ["0020", "Obligors"]],
            "open_rows": True,
            "open_keys": [
                {
                    "code": "0005",
                    "label": "Obligor grade",
                    "dimension": "tst_dim:OGR",
                    "kind": "typed",
                    "typed_element": "tst_typ:ID",
                    "typed_type": "integer",
                    "members": [],
                }
            ],
            "z": [],
            "cells": [[None, "0010", None, 14, "workbook"], [None, "0020", None, 15, "workbook"]],
        },
        "T05.00.01.01": {
            "title": "Shared, first view",
            "group": "T05.00.01",
            "filing_indicator": "T05.00.01",
            "rows": [["0010", "Shared"]],
            "columns": [["0010", "Amount"]],
            "open_rows": False,
            "open_keys": [],
            "z": [],
            "cells": [["0010", "0010", None, 16, "workbook"]],
        },
        "T05.00.01.02": {
            "title": "Shared, second view",
            "group": "T05.00.01",
            "filing_indicator": "T05.00.01",
            "rows": [["0010", "Shared"]],
            "columns": [["0010", "Amount"]],
            "open_rows": False,
            "open_keys": [],
            "z": [],
            "cells": [["0010", "0010", None, 16, "workbook"]],
        },
        "T06.00.01.01": {
            "title": "Typed cells",
            "group": "T06.00.01",
            "filing_indicator": "T06.00.01",
            "rows": [["0010", "Row"]],
            "columns": [["0010", "Flag"], ["0020", "Date"], ["0030", "Choice"]],
            "open_rows": False,
            "open_keys": [],
            "z": [],
            "cells": [
                ["0010", "0010", None, 17, "workbook"],
                ["0010", "0020", None, 18, "workbook"],
                ["0010", "0030", None, 19, "workbook"],
            ],
        },
        "T07.00.01.01": {
            "title": "Optional open sheets",
            "group": "T07.00.01",
            "filing_indicator": "T07.00.01",
            "rows": [["0010", "Lending"]],
            "columns": [["0010", "Amount"]],
            "open_rows": False,
            "open_keys": [],
            "z": [
                {
                    "kind": "open",
                    "code": "0001",
                    "label": "Lending type",
                    "dimension": "tst_dim:TSL",
                    "members": ["tst_TA:x1", "tst_TA:x2"],
                    "default_allowed": True,
                }
            ],
            "cells": [["0010", "0010", None, 20, "workbook"]],
        },
    },
    "datapoints": _DATAPOINTS,
}


def build_pack(directory: Path, **overrides: Any) -> TaxonomyPack:
    """Write ``SAMPLE_COMPILED`` to ``directory`` and load it back.

    ``valid_from`` / ``valid_to`` may be overridden to test resolution by date.
    """
    write_pack(
        SAMPLE_COMPILED,
        directory,
        valid_from=overrides.get("valid_from", SAMPLE_VALID_FROM),
        valid_to=overrides.get("valid_to"),
    )
    return load_pack(directory)


def build_header(**overrides: Any) -> ReturnHeader:
    """A valid header for the sample module; override the field under test."""
    fields: dict[str, Any] = {
        "entity_identifier": VALID_LEI,
        "reference_date": date(2027, 3, 31),
        "module": SAMPLE_MODULE,
    }
    fields.update(overrides)
    return ReturnHeader(**fields)


def build_return(frame: pl.DataFrame, **header: Any) -> CanonicalReturn:
    """A canonical return over ``frame`` with a valid sample header."""
    return CanonicalReturn.from_frame(build_header(**header), frame)
