"""
Returns that tell apart two more readings of a rule the engine once took wrongly.

1. **A plain function returns a plain number.** The Bank's rules write most sums
   as ``isum(...)`` and a few as ``sum(...)``; the formulas behind them are
   ``iaf:sum($v)`` and XPath ``sum($v)``. In the interval-arithmetic functions a
   reported fact carries a rounding allowance of half a unit of its
   ``decimals`` and anything that is not a fact carries none
   (``iaf:splitValueThreshold``), so ``iaf:sum`` keeps the summed facts'
   allowances and XPath ``sum`` returns a number with none — the same for
   ``abs`` against ``iabs``. The engine read both alike, and passed rounded
   figures the gateway fails: ``boe_b0770`` on OF 08.03, ``boe_b0820``-``b0823``
   and ``boe_b0829`` on OF 08.06 against OF 08.01, ``boe_b0794`` (``abs``) on
   OF 16.00 and SC 16.00, and SDDT ``boe_b1037_ss`` on SC 34.00. Nothing caught
   it: every oracle return was exact to the unit, where an allowance is zero
   either way.
2. **The default member of an open sheet axis is a sheet of its own.** OF 08.06's
   type-of-specialised-lending axis accepts its default member (``eba_TA:x0``,
   "all activities"): a fact reported with no member is on the all-types sheet,
   one place among the others. The engine gave such a fact no place on the
   axis, so its cells were read into every type's evaluation — ``boe_b0815``
   and ``boe_b1042`` failed on each type sheet, and ``boe_b0823`` / ``b0829``
   lost the all-types sheet's own evaluation. The summed-reference returns
   (``summed_returns.py``) file no all-types sheet, and the Bank's sample none
   at all.

Each return has, for each rule it exists for, an evaluation where the two
readings agree and one where they differ (or, where the rule is evaluated once,
the one that differs), so a verdict alone cannot hide a wrong count
(``.claude/LESSONS.md`` B5):

- ``rounded`` (PRA001): figures rounded to thousands at ``decimals`` -3, and
  OF 08.06 at -2, as the Filing Manual permits (rule 2.18). The ``isum``
  siblings ``boe_b0768``, ``b0769``, ``b0816``, ``b0817`` and ``b0819`` are
  the controls: the same rounding gap, and they pass.
- ``rounded_sddt`` (PRA116): the same for SC 34.00 and SC 16.00.
- ``all_types`` (PRA001): project finance and IPRE on their own OF 08.06
  sheets, and the all-types sheet beside them with its own category rows.
- ``all_types_total_only`` (PRA001): the same, with only the total row (0095)
  on the all-types sheet. The two readings differ on other counts here: the
  all-types sheet's total no longer foots on category rows of its own.

Arelle's counts on these returns are pinned in
``tests/releases/4.1.1/oracles/rounding_and_default_oracle.json``; regenerate
with the referee, never by hand::

    uv run python packages/rwa-filer/tests/rounding_and_default_returns.py \\
        --taxonomy-package .taxonomy/boe-banking-v411.zip \\
        --arelle-python <python with arelle-release>

References:
- Bank of England XBRL Filing Manual v1.0.1, rule 2.18 (decimals, interval
  arithmetic)
- Bank of England interval-arithmetics function linkbase
  (``iaf:splitValueThreshold``, ``iaf:numeric-equal``)
- XBRL Dimensions 1.0 — dimension defaults
- docs/development/escape-log.md, 2026-11-16
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from rwa_filer.model import CanonicalReturn
from rwa_filer.taxonomy.pack import load_packaged
from summed_returns import RELEASE, arelle_version, canonical_return

#: Each return's module, and the pack it is written against.
MODULES: Final = {
    "rounded": "PRA001",
    "rounded_sddt": "PRA116",
    "all_types": "PRA001",
    "all_types_total_only": "PRA001",
}
PACKS: Final = {"PRA001": "pra001-4.1.1", "PRA116": "pra116-4.1.1"}

#: The rules each return exists for, and the controls beside them.
RULES: Final = {
    "rounded": r"^(boe_b076[89]|boe_b0770|boe_b0794|boe_b081[679]|boe_b082[0-3]|boe_b0829)$",
    "rounded_sddt": r"^(boe_b0794|boe_b1037_ss)$",
    "all_types": r"^(boe_b081[5-9]|boe_b082[0-3]|boe_b0829|boe_b063[2-6]|boe_b1042|boe_b0743)$",
    "all_types_total_only": (
        r"^(boe_b081[5-9]|boe_b082[0-3]|boe_b0829|boe_b063[2-6]|boe_b1042|boe_b0743)$"
    ),
}

#: Thousands, as the Filing Manual allows a monetary figure to be rounded; and
#: hundreds, for the side of an OF 08.06 identity that is stated more finely.
_THOUSANDS: Final = -3
_HUNDREDS: Final = -2

# OF 08.03 PD bands, by column. 0070 = 0080 + 0090 and 0100 = 0110 + 0120 are
# the isum controls; 0130 = 0140 + 0150 + 0160 is ``boe_b0770``'s plain sum.
# Column 0010 is each true figure rounded to the nearest thousand: every
# parent is 1,000 off its rounded parts, inside the isum allowance (500 for
# each fact) and outside a plain sum's (500 for the parent alone). Column 0020
# foots exactly.
_PD_BANDS: Final = {
    "0010": {"0080": 12_345_000, "0090": 8_765_000, "0070": 21_111_000,
             "0110": 12_345_000, "0120": 8_765_000, "0100": 21_111_000,
             "0140": 12_345_000, "0150": 8_765_000, "0160": 3_210_000, "0130": 24_321_000},
    "0020": {"0080": 1_000_000, "0090": 2_000_000, "0070": 3_000_000,
             "0110": 1_000_000, "0120": 2_000_000, "0100": 3_000_000,
             "0140": 1_000_000, "0150": 2_000_000, "0160": 3_000_000, "0130": 6_000_000},
}  # fmt: skip

# OF 16.00 / SC 16.00, the average of three years (``boe_b0794``): row 0030's
# average, stated to hundreds, is 300 off the average of three figures stated
# to thousands — inside their iabs allowance (500), outside abs's (none). Row
# 0050 is exact.
_THREE_YEARS: Final = {
    "0030": ((3_000_000, 3_000_000, 3_000_000), (3_000_300, _HUNDREDS)),
    "0050": ((2_000_000, 3_000_000, 4_000_000), (3_000_000, _THOUSANDS)),
}

# OF 08.06 for one type of specialised lending (project finance, x129) beside
# OF 08.01 r0080 on sheets 0002 and 0010: (OF 08.01 table, column, figure).
# OF 08.06 states each figure 300 higher, to hundreds; OF 08.01 to thousands.
# ``isum`` on the OF 08.01 side (b0816, b0817, b0819) allows 50 + 500 and
# holds; ``sum`` (b0820-b0823, b0829) allows 50 and breaks.
_SLOTTING: Final = {
    "0010": ("OF08.01.01.01", "0020", 5_000_000),
    "0020": ("OF08.01.01.01", "0090", 5_000_000),
    "0040": ("OF08.01.01.01", "0110", 5_000_000),
    "0050": ("OF08.01.01.02", "0120", 1_000_000),
    "0060": ("OF08.01.01.02", "0130", 1_000_000),
    "0080": ("OF08.01.01.01", "0260", 4_000_000),
    "0090": ("OF08.01.01.01", "0280", 40_000),
    "0100": ("OF08.01.01.01", "0290", -30_000),
}
_GAP: Final = 300

# SC 34.00 (``boe_b1037_ss``): row 0020 against the plain sum of rows
# 0160-0200. Column 0010's total is 1,000 off its five parts (allowance: 500
# for the total alone; 3,000 were the parts' added); column 0020 foots.
_SC34_PARTS: Final = {"0160": 1_000_000, "0170": 2_000_000, "0180": 3_000_000,
                      "0190": 4_000_000, "0200": 5_000_000}  # fmt: skip
_SC34_TOTALS: Final = {"0010": 15_001_000, "0020": 15_000_000}

# OF 08.06 with two types and the all-types sheet (no member): project finance
# in "Good / other" (row 0055), IPRE in "Satisfactory" (row 0065), each
# repeated in its sheet's total (0095), and both on the all-types sheet (in
# its category rows and total, or in its total alone). The columns: original
# exposure, after CRM substitution, exposure value, RWEA, expected loss, (-)
# provisions. OF 08.01 r0080 carries the class figures.
_TYPE_COLUMNS: Final = ("0010", "0020", "0040", "0080", "0090", "0100")
_PROJECT_FINANCE: Final = (1000.0, 1000.0, 1000.0, 900.0, 8.0, -5.0)
_IPRE: Final = (2000.0, 2000.0, 2000.0, 2300.0, 56.0, -20.0)
_CLASS_COLUMNS: Final = ("0020", "0090", "0110", "0260", "0280", "0290")


def build_returns() -> dict[str, CanonicalReturn]:
    """The four returns, by name (see ``MODULES`` for each one's module)."""
    return {
        "rounded": canonical_return("PRA001", [*_pd_bands(), *_three_years("OF"), *_slotting()]),
        "rounded_sddt": canonical_return("PRA116", [*_sc34(), *_three_years("SC")]),
        "all_types": canonical_return("PRA001", _all_types(category_rows=True)),
        "all_types_total_only": canonical_return("PRA001", _all_types(category_rows=False)),
    }


def oracle_path() -> Path:
    """Where Arelle's counts on these returns are kept."""
    return (
        Path(__file__).parent
        / "releases"
        / RELEASE
        / "oracles"
        / "rounding_and_default_oracle.json"
    )


# =============================================================================
# The returns
# =============================================================================


def _pd_bands() -> list[tuple[Any, ...]]:
    return [
        ("OF08.03.01.01", "0012", None, row, column, value, None, _THOUSANDS)
        for column, figures in _PD_BANDS.items()
        for row, value in figures.items()
    ]


def _three_years(prefix: str) -> list[tuple[Any, ...]]:
    table = f"{prefix}16.00.01.04"
    rows: list[tuple[Any, ...]] = []
    for row, (years, (average, decimals)) in _THREE_YEARS.items():
        rows += [
            (table, None, None, row, column, value, None, _THOUSANDS)
            for column, value in zip(("0010", "0020", "0030"), years, strict=True)
        ]
        rows.append((table, None, None, row, "0040", average, None, decimals))
    return rows


def _slotting() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for column, (table, class_column, figure) in _SLOTTING.items():
        rows.append(("OF08.06.01.01", None, "x129", "0095", column, figure + _GAP, None, _HUNDREDS))
        rows += [
            (table, sheet, None, "0080", class_column, figure, None, _THOUSANDS)
            for sheet in ("0002", "0010")
        ]
    return rows


def _sc34() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for column, total in _SC34_TOTALS.items():
        rows.append(("SC34.00.01.01", None, None, "0020", column, total, None, _THOUSANDS))
        rows += [
            ("SC34.00.01.01", None, None, row, column, value, None, _THOUSANDS)
            for row, value in _SC34_PARTS.items()
        ]
    return rows


def _all_types(*, category_rows: bool) -> list[tuple[Any, ...]]:
    """The two type sheets, and the all-types sheet with or without category rows."""
    both = tuple(a + b for a, b in zip(_PROJECT_FINANCE, _IPRE, strict=True))
    all_categories = {"0055": _PROJECT_FINANCE, "0065": _IPRE} if category_rows else {}
    rows: list[tuple[Any, ...]] = []
    for member, categories, totals in (
        ("x129", {"0055": _PROJECT_FINANCE}, _PROJECT_FINANCE),
        ("x10001", {"0065": _IPRE}, _IPRE),
        (None, all_categories, both),
    ):
        for row, figures in (*categories.items(), ("0095", totals)):
            rows += [
                ("OF08.06.01.01", None, member, row, column, value, None, 0)
                for column, value in zip(_TYPE_COLUMNS, figures, strict=True)
            ]
    for sheet in ("0002", "0010"):
        rows += [
            ("OF08.01.01.01", sheet, None, "0080", column, value, None, 0)
            for column, value in zip(_CLASS_COLUMNS, both, strict=True)
        ]
        rows.append(("OF08.01.01.01", sheet, None, "0080", "0282", both[4], None, 0))
    rows.append(("OF02.00.01.01", None, None, "0412", "0010", _PROJECT_FINANCE[3], None, 0))
    rows.append(("OF02.00.01.01", None, None, "0415", "0010", _IPRE[3], None, 0))
    return rows


# =============================================================================
# Regenerating the oracle — needs Arelle and the Bank's taxonomy package
# =============================================================================


def _measure(taxonomy_package: Path, arelle_python: Path | None) -> dict[str, Any]:
    from rwa_filer.referee.runner import run_referee
    from rwa_filer.xbrl.writer import write_instance

    measured: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for name, ret in build_returns().items():
            module = MODULES[name]
            instance = write_instance(ret, load_packaged(PACKS[module]))
            path = Path(scratch) / f"{name}.xbrl"
            content = instance.content
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            result = run_referee(
                path,
                taxonomy_package,
                python=arelle_python,
                rules=RULES[name],
                filing_rules=False,
            )
            if not result.complete or result.errors:
                raise SystemExit(f"{name}: Arelle did not finish cleanly: {result.errors}")
            measured[name] = {
                "module": module,
                "facts": instance.facts,
                "rules": {
                    rule_id: [verdict.satisfied, verdict.unsatisfied]
                    for rule_id, verdict in sorted(result.rules.items())
                },
            }
    return measured


def main(argv: list[str] | None = None) -> int:
    """Re-measure the oracle with Arelle and write it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--taxonomy-package", type=Path, required=True)
    parser.add_argument("--arelle-python", type=Path)
    args = parser.parse_args(argv)
    oracle = {
        "_comment": (
            "Arelle's verdict, as [satisfied, unsatisfied] evaluation counts, on the "
            "returns tests/rounding_and_default_returns.py builds: rounded figures "
            "under plain sum() and abs(), and an all-types OF 08.06 sheet beside two "
            "types. Regenerate with that module's main, never by hand."
        ),
        "processor": arelle_version(args.arelle_python),
        "taxonomy": f"Bank of England Banking Taxonomy v{RELEASE}",
        "returns": _measure(args.taxonomy_package, args.arelle_python),
    }
    path = oracle_path()
    path.write_text(json.dumps(oracle, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
