"""
``rwa-filer diff`` reads two returns, and loads no taxonomy release it does not read.

Pipeline position:
    cli._diff  ->  cli._diff_side   a fact table or a workbook: read, its release
                                    CHOSEN (``release.release_choice``), nothing loaded
               ->  cli._load        an XBRL instance: read with its pack
        ->  workflow.diff.diff_returns  ->  the cells that differ

What is pinned:
- two files that name no taxonomy are compared without a pack, rule book, deny
  list or issue register being loaded — by count, with the count proven live on
  a ``diff`` that does have to load (one side an XBRL instance);
- a module or a version no shipped release has, a fact table without its
  header, a missing file and an unsupported one are refused by ``diff`` in the
  words ``validate`` uses, with nothing on standard output;
- ``diff`` reads a file as every other command does (``readers.open_source``):
  the same header, option by option, and the same facts.

Mutation evidence, each probe one change to ``cli._diff`` or ``cli._diff_side``,
measured 2026-11-22:

- every side read by ``_load`` (the code before the change): red on the three
  cases of ``test_diff_of_two_files_that_name_no_taxonomy_loads_no_release``
  alone — a pack, a rule book, a deny list and an issue register loaded per
  side;
- the release no longer chosen: red on the eight unknown-module and
  unshipped-version cases of
  ``test_diff_refuses_what_validate_refuses_in_the_same_words``;
- the header options not applied over the header read: red on six cases of
  ``test_diff_reads_a_file_as_every_other_command_does`` and the two
  workbook-moved-to-a-module-no-release-has refusals;
- a workbook read with its own header where all three options were given: red
  on three cases of ``test_diff_reads_a_file_as_every_other_command_does`` and
  the workbook case of the no-release count.

References:
- rwa_filer.release — ``release_choice``: choosing a release without loading it
- rwa_filer.readers — ``open_source``: the reading every other command uses
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from pack_builders import VALID_LEI
from rwa_filer import cli
from rwa_filer import release as release_module
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, build_parser, main
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.readers import HeaderFields, open_source, read_return
from rwa_filer.readers.excel import write_workbook
from rwa_filer.release import resolve_release
from rwa_filer.xbrl.writer import write_instance

if TYPE_CHECKING:
    from pathlib import Path

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
#: What a release is made of: each is loaded once per release resolved.
LOADERS = ("load_packaged", "load_rulebook", "load_deny_list", "load_issues")

#: v0174_m holds: r0070 = r0080 + r0090 + r0091 on C 01.00.
BEFORE = {"0070": 11000.0, "0080": 0.0, "0090": 8000.0, "0091": 3000.0}
#: One figure changed, one removed.
AFTER = {"0070": 12000.0, "0080": 0.0, "0090": 8000.0}
DIFFERENCE = (
    "DIFFERENT: 1 changed, 0 added, 1 removed, 2 unchanged\n"
    "  changed C01.00.01.01[r0070][c0010]: 11000.0 -> 12000.0\n"
    "  removed C01.00.01.01[r0091][c0010]: 3000.0 -> None\n"
)


def _frame(values: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "table": ["C01.00.01.01"] * len(values),
            "row": list(values),
            "column": ["0010"] * len(values),
            "value": list(values.values()),
        }
    )


def _return(values: dict[str, float], **header: str) -> CanonicalReturn:
    stated = ReturnHeader(
        entity_identifier=VALID_LEI, reference_date=date(2027, 3, 31), module="PRA001", **header
    )
    return CanonicalReturn.from_frame(stated, _frame(values))


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    """The BEFORE return as each kind of file, and the AFTER return as a fact table."""
    pack = resolve_release("PRA001", "4.1.1").pack
    paths = {
        "csv": tmp_path / "before.csv",
        "parquet": tmp_path / "before.parquet",
        "xlsx": tmp_path / "before.xlsx",
        "xbrl": tmp_path / "before.xbrl",
        "after": tmp_path / "after.csv",
    }
    _frame(BEFORE).write_csv(paths["csv"])
    _frame(BEFORE).write_parquet(paths["parquet"])
    # The workbook states a header of its own that is NOT the defaults, so a
    # reading that kept it where the options should replace it is visible.
    own = _return(BEFORE, currency="USD", entity_name="Example Bank plc")
    write_workbook(pack, paths["xlsx"], ret=own)
    assert read_return(paths["xlsx"]).header == own.header, "the workbook lost its own header"
    paths["xbrl"].write_bytes(write_instance(_return(BEFORE), pack).content)
    _frame(AFTER).write_csv(paths["after"])
    return paths


@pytest.fixture
def loaded(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """How often each part of a release was loaded, counted where a release is built."""
    counts = dict.fromkeys(LOADERS, 0)

    def counting(name: str) -> object:
        real = getattr(release_module, name)

        def load(*args: object) -> object:
            counts[name] += 1
            return real(*args)

        return load

    for name in LOADERS:
        monkeypatch.setattr(release_module, name, counting(name))
    return counts


# ---------------------------------------------------------------------------
# Nothing loaded that is not read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["csv", "parquet", "xlsx"])
def test_diff_of_two_files_that_name_no_taxonomy_loads_no_release(
    kind: str,
    files: dict[str, Path],
    loaded: dict[str, int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange — the count is live on this very command: an instance needs its pack.
    main(["diff", str(files["xbrl"]), str(files["after"]), *HEADER_ARGS])
    with_an_instance = (dict(loaded), capsys.readouterr().out)
    assert all(count >= 1 for count in with_an_instance[0].values()), (
        f"reading an instance loaded {with_an_instance[0]}: the loaders are not being counted"
    )
    for name in loaded:
        loaded[name] = 0

    # Act
    code = main(["diff", str(files[kind]), str(files["after"]), *HEADER_ARGS])

    # Assert — the same answer as with the instance, and nothing loaded for it.
    captured = capsys.readouterr()
    assert loaded == dict.fromkeys(LOADERS, 0)
    assert (code, captured.out, captured.err) == (EXIT_FAILED, DIFFERENCE, "")
    assert with_an_instance[1] == DIFFERENCE


def test_diff_of_a_file_with_itself_is_identical(
    files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["diff", str(files["csv"]), str(files["parquet"]), *HEADER_ARGS])

    # Assert
    assert code == EXIT_OK
    assert capsys.readouterr().out == "IDENTICAL: 0 changed, 0 added, 0 removed, 4 unchanged\n"


# ---------------------------------------------------------------------------
# Every refusal, in the words it always had
# ---------------------------------------------------------------------------

_NO_HEADER = (
    "rwa-filer: a fact table carries no header: --entity, --reference-date and --module "
    "are all required\n"
)
REFUSALS = [
    pytest.param(
        "csv",
        ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "XYZ999"],
        "rwa-filer: No shipped taxonomy release has module XYZ999. Shipped releases: 4.1.1.\n",
        id="a-module-no-release-has",
    ),
    pytest.param(
        "parquet",
        [*HEADER_ARGS, "--taxonomy", "9.9.9"],
        "rwa-filer: Taxonomy 9.9.9 is not shipped in this version of rwa-filer. "
        "Shipped releases: 4.1.1.\n",
        id="a-release-that-is-not-shipped",
    ),
    pytest.param(
        "xlsx",
        ["--taxonomy", "9.9.9"],
        "rwa-filer: Taxonomy 9.9.9 is not shipped in this version of rwa-filer. "
        "Shipped releases: 4.1.1.\n",
        id="a-workbook-against-a-release-that-is-not-shipped",
    ),
    pytest.param(
        "xlsx",
        ["--module", "XYZ999"],
        "rwa-filer: No shipped taxonomy release has module XYZ999. Shipped releases: 4.1.1.\n",
        id="a-workbook-moved-to-a-module-no-release-has",
    ),
    pytest.param("csv", [], _NO_HEADER, id="a-fact-table-with-no-header"),
    pytest.param(
        "parquet",
        ["--entity", VALID_LEI, "--module", "PRA001"],
        _NO_HEADER,
        id="a-fact-table-with-part-of-a-header",
    ),
    pytest.param("missing", HEADER_ARGS, "rwa-filer: file not found: {path}\n", id="no-such-file"),
    pytest.param(
        "text",
        HEADER_ARGS,
        "rwa-filer: unsupported file type '.txt'; expected one of "
        ".parquet, .csv, .xlsx, .xbrl, .zip\n",
        id="a-file-type-nothing-reads",
    ),
]


@pytest.mark.parametrize("position", ["previous", "current"])
@pytest.mark.parametrize(("kind", "options", "expected"), REFUSALS)
def test_diff_refuses_what_validate_refuses_in_the_same_words(
    position: str,
    kind: str,
    options: list[str],
    expected: str,
    files: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange — the refused file is one side; the other is a file that reads.
    (tmp_path / "notes.txt").write_text("not a return")
    refused = {"missing": tmp_path / "absent.csv", "text": tmp_path / "notes.txt"}.get(
        kind, files.get(kind, tmp_path)
    )
    sound = files["after"] if kind in ("missing", "text") else refused
    sides = [refused, sound] if position == "previous" else [sound, refused]

    # Act
    code = main(["diff", *map(str, sides), *options])
    diffed = capsys.readouterr()
    main(["validate", str(refused), *options])
    validated = capsys.readouterr()

    # Assert — written out, so the two commands cannot be wrong together.
    assert (code, diffed.out) == (EXIT_FAILED, "")
    assert diffed.err == expected.format(path=refused)
    assert validated.err == diffed.err


# ---------------------------------------------------------------------------
# One reading for every command
# ---------------------------------------------------------------------------

#: Header options in every shape: none, some, all three, and all of them.
OPTIONS = {
    "none": [],
    "one-that-is-not-required": ["--currency", "EUR"],
    "one-of-the-required-three": ["--module", "PRA116"],
    "two-of-the-three": ["--entity", "OTHER", "--reference-date", "2028-06-30"],
    "the-required-three": HEADER_ARGS,
    "all-five": [
        *HEADER_ARGS,
        "--currency",
        "EUR",
        "--entity-scheme",
        "http://example.test/scheme",
    ],
    "with-a-named-release": [*HEADER_ARGS, "--taxonomy", "4.1.1"],
}
#: A workbook with each; a fact table with those that give it the three it
#: needs (without them it is refused, which is pinned above).
READINGS = [
    pytest.param(kind, options, id=f"{kind}-{name}")
    for kind in ("csv", "parquet", "xlsx")
    for name, options in OPTIONS.items()
    if kind == "xlsx" or set(HEADER_ARGS) <= set(options)
]


@pytest.mark.parametrize(("kind", "options"), READINGS)
def test_diff_reads_a_file_as_every_other_command_does(
    kind: str, options: list[str], files: dict[str, Path]
) -> None:
    # Arrange
    assert {field.name for field in dataclasses.fields(HeaderFields)} == {
        "entity",
        "reference_date",
        "module",
        "currency",
        "entity_scheme",
    }, "a header option was added: give it a case here, and apply it in cli._diff_side"
    path = files[kind]
    args = build_parser().parse_args(["diff", str(path), str(path), *options])

    # Act
    read = cli._diff_side(args, path)
    opened = open_source(path, cli._header_fields(args), taxonomy=args.taxonomy).ret

    # Assert
    assert read.header == opened.header
    assert read.facts.equals(opened.facts)
    assert read.indicators == opened.indicators
