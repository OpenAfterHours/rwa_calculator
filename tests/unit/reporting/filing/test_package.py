"""
The filing package for a generated estate: complete, validated, written.

Pipeline position:
    COREPTemplateBundle -> filing.build_filing_package
        -> FilingOutcome(mapping, rwa-filer FilingPackage)

What is pinned here is the one decision this calculator makes for itself: a
return that is MISSING figures is not written unless the caller asks, and then
says exactly what it left out. Whether the placed figures may be filed is
``rwa-filer``'s decision and is tested there. Frames are synthetic; the two
facts used throughout are a real, rule-clean pair of OF 07.00 cells.

References:
- src/rwa_calc/reporting/filing/package.py — the adapter under test
- Bank of England Banking Taxonomy v4.1.1 (PRA001)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from rwa_calc.reporting.filing import FilingOutcome, build_filing_package
from rwa_calc.reporting.filing.canonical import REASON_COLUMN
from rwa_calc.reporting.filing.package import BLOCKED_BY_UNPLACED
from rwa_filer.model import ReturnHeader
from rwa_filer.xbrl.reader import read_instance

from ._builders import build_corep, build_frame

FRAMEWORK = "BASEL_3_1"
LEI = "5493001KJTIIGC8Y1R12"
HEADER = ReturnHeader(LEI, date(2027, 3, 31), "PRA001")

#: OF 07.00, corporates: original exposure and value adjustments. The published
#: rules that can run on these two cells pass.
CLEAN = {"0010": {"0010": 1_000_000.0, "0030": -5_000.0}}


def build(tmp_path: Path, cells: dict[str, dict[str, float]], **options: Any) -> FilingOutcome:
    corep = build_corep(FRAMEWORK, c07_00={"corporate": build_frame(cells)})
    return build_filing_package(corep, HEADER, tmp_path / "out", **options)


def test_a_complete_clean_estate_is_written_and_is_submittable(tmp_path: Path) -> None:
    # Act
    outcome = build(tmp_path, CLEAN)

    # Assert
    assert outcome.written and outcome.blocked_by is None
    assert outcome.is_complete and outcome.is_submittable
    assert outcome.package is not None and outcome.package.instance_path is not None
    assert outcome.package.instance_path.name == f"{LEI}_PRA001_2027-03-31.xbrl"


def test_the_written_file_carries_the_generated_figures(tmp_path: Path) -> None:
    """Read back with the instance reader: the cells and the values that went in."""
    # Act
    outcome = build(tmp_path, CLEAN)
    assert outcome.package is not None and outcome.package.instance_path is not None
    back = read_instance(outcome.package.instance_path)

    # Assert
    assert back.findings == ()
    assert back.ret.facts.select("table", "sheet", "row", "column", "value").sort(
        "column"
    ).rows() == [
        ("OF07.00.01.01", "0008", "0010", "0010", 1_000_000.0),
        ("OF07.00.01.01", "0008", "0010", "0030", -5_000.0),
    ]


def test_an_estate_with_a_figure_that_has_no_place_is_not_written(tmp_path: Path) -> None:
    """A file that validates and is quietly missing a figure is the worst outcome."""
    # Arrange — column 9998 is in no published table.
    cells = {"0010": {**CLEAN["0010"], "9998": 42.0}}

    # Act
    outcome = build(tmp_path, cells)

    # Assert — nothing on disk, and the outcome names the figure.
    assert not outcome.written and outcome.blocked_by == BLOCKED_BY_UNPLACED
    assert outcome.package is None and not (tmp_path / "out").exists()
    assert not outcome.is_complete and not outcome.is_submittable
    assert outcome.unplaced_figures.select(
        "template", "row", "column", "value", "reason"
    ).rows() == [("c07_00", "0010", "9998", 42.0, REASON_COLUMN)]


def test_an_incomplete_estate_can_be_written_on_request_and_is_never_submittable(
    tmp_path: Path,
) -> None:
    # Arrange
    cells = {"0010": {**CLEAN["0010"], "9998": 42.0}}

    # Act
    outcome = build(tmp_path, cells, allow_incomplete=True)

    # Assert — written, the validation of what WAS written is clean, and the
    # outcome still does not call the return submittable.
    assert outcome.written and outcome.package is not None
    assert outcome.package.validation.is_submittable
    assert not outcome.is_complete and not outcome.is_submittable
    assert outcome.unplaced_figures.height == 1


def test_a_zero_with_no_place_does_not_make_the_estate_incomplete(tmp_path: Path) -> None:
    # Arrange
    cells = {"0010": {**CLEAN["0010"], "9998": 0.0}}

    # Act
    outcome = build(tmp_path, cells)

    # Assert
    assert outcome.is_complete and outcome.written


def test_rule_checks_that_do_not_pass_stop_the_file_unless_overridden(tmp_path: Path) -> None:
    """One cell of OF 02.00 on its own: no published rule can run on it (VAL003)."""
    # Arrange
    corep = build_corep(
        FRAMEWORK,
        c07_00={"corporate": build_frame(CLEAN)},
        c_02_00=build_frame({"0010": {"0010": 1_234_567.89}}),
    )

    # Act
    stopped = build_filing_package(corep, HEADER, tmp_path / "stopped")
    forced = build_filing_package(corep, HEADER, tmp_path / "forced", allow_rule_breaks=True)

    # Assert
    assert not stopped.written and stopped.blocked_by == "rules"
    assert forced.written and not forced.is_submittable
