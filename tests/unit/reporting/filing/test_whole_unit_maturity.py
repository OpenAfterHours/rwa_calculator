"""
An exposure-weighted average maturity is filed in the whole units its data point is typed in.

Pipeline position:
    COREPTemplateBundle -> filing.build_canonical_return
        -> CanonicalMapping(canonical return, unplaced cells)

PS1/26 Annex II asks for the exposure-weighted average maturity in days on
OF 08.01 / OF 08.02 column 0250 (p.111, p.118) and in years on OF 08.03 column
0080 (p.121). The PRA001 taxonomy files both on integer-typed metrics —
``eba_met:ii163`` "Maturity value (days)" and ``eba_met:ii791`` "Maturity value
(years)", inherited from the EBA dictionary — so a fraction there is not valid
XBRL, and the structure check refuses it (``STR006``).

The Bank's XBRL Filing Manual v1.0.1 (rule 2.18, PDF p.23) settles how the
average becomes a whole number: "if numbers are for any reason rounded, they
MUST be rounded as per the XBRL 2.1 specification (i.e. [IEEE-754] 4.3.1
Rounding-direction attributes to nearest, roundTiesToEven)", and its accuracy
table (PDF p.25) gives an integer ``decimals`` 0, "Must be reported without any
decimal part". So the adapter rounds those two metrics, and only those two:
every other integer metric is a count, where a fraction is a defect the
structure check must keep refusing.

What is pinned here:
- The two averaged metrics are rounded to nearest, ties to even — not half up,
  not truncated.
- A tie reached through float dust in the weighting is filed as the exact tie.
- A rounded return passes the structure check and is written as an integer.
- A fractional COUNT is not rounded and is still refused.
- The premise itself, against the taxonomy pack: both metrics are integer-typed
  and are the metrics of the averaged maturity columns (LESSONS B3).

References:
- src/rwa_calc/reporting/filing/canonical.py — the adapter under test
- PRA PS1/26 Annex II — OF 08.01 c0250 (p.111), OF 08.02 (p.118), OF 08.03
  c0080 (p.121)
- Bank of England XBRL Filing Manual v1.0.1, rule 2.18
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    CanonicalMapping,
    build_canonical_return,
)
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.writer import write_instance
from tests.unit.reporting.corep._irb_sheet_frames import OF08_INSTITUTIONS_FIRB

from ._builders import build_corep, build_frame

FRAMEWORK = "BASEL_3_1"
LEI = "5493001KJTIIGC8Y1R12"

#: F-IRB institutions: the published sheet our OF08_INSTITUTIONS_FIRB key files on.
SHEET = "0006"
ROW = "0010"

#: The two averaged maturity metrics and the cells Annex II asks them in.
DAYS = "eba_met:ii163"
YEARS = "eba_met:ii791"
AVERAGED_COLUMNS = {
    ("OF08.01.01.01", "0250"): DAYS,
    ("OF08.02.01.01", "0250"): DAYS,
    ("OF08.03.01.01", "0080"): YEARS,
}

TABLE_OF = {"c08_01": "OF08.01.01.01", "c08_03": "OF08.03.01.01", "c08_05": "OF08.05.00.01"}

#: Two exposures at the same maturity whose exposure-weighted average is not
#: that maturity in binary floating point.
WEIGHTS = (20_809_580.76, 45_813_575.51)


def mapping(template: str, column: str, value: float) -> CanonicalMapping:
    """One figure on the F-IRB institutions sheet, row 0010, placed in the PRA001 taxonomy."""
    corep = build_corep(
        FRAMEWORK, **{template: {OF08_INSTITUTIONS_FIRB: build_frame({ROW: {column: value}})}}
    )
    header = ReturnHeader(
        entity_identifier=LEI, reference_date=date(2027, 3, 31), module=FILING_MODULE
    )
    return build_canonical_return(corep, header)


def placed(result: CanonicalMapping) -> list[tuple[Any, ...]]:
    return result.canonical.facts.select(
        "table", "sheet", "open_key", "row", "column", "value"
    ).rows()


def weighted_average(maturity: float) -> float:
    """The exposure-weighted average of ``WEIGHTS``, all at ``maturity``."""
    return sum(maturity * weight for weight in WEIGHTS) / sum(WEIGHTS)


def pack() -> Any:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "column", "computed", "filed"),
    [
        pytest.param("c08_01", "0250", 912.5, 912.0, id="days-tie-to-even-down"),
        pytest.param("c08_01", "0250", 1672.9999999999995, 1673.0, id="days-float-dust"),
        pytest.param("c08_03", "0080", 2.5, 2.0, id="years-tie-to-even-down"),
        pytest.param("c08_03", "0080", 3.5, 4.0, id="years-tie-to-even-up"),
        pytest.param("c08_03", "0080", 4.583561643835616, 5.0, id="years-to-nearest"),
    ],
)
def test_an_average_maturity_is_filed_in_whole_units_rounded_half_to_even(
    template: str, column: str, computed: float, filed: float
) -> None:
    # Arrange / Act
    result = mapping(template, column, computed)

    # Assert
    assert placed(result) == [(TABLE_OF[template], SHEET, None, ROW, column, filed)]


def test_a_tie_reached_through_float_dust_is_filed_as_the_exact_tie() -> None:
    """Two loans at 2.5 years average 2.5000000000000004 in floating point.

    The order of summation must not decide which side of a tie the filing lands
    on: the figure is snapped before it is rounded, so it files as 2.5 does.
    """
    # Arrange
    years = weighted_average(2.5)
    days = weighted_average(912.5)
    assert years != 2.5, "the weights must leave float dust, or this test proves nothing"
    assert days != 912.5, "the weights must leave float dust, or this test proves nothing"

    # Act
    filed_years = placed(mapping("c08_03", "0080", years))
    filed_days = placed(mapping("c08_01", "0250", days))

    # Assert
    assert [fact[-1] for fact in filed_years + filed_days] == [2.0, 912.0]


def test_a_rounded_maturity_return_passes_the_structure_check_and_is_written_as_an_integer() -> (
    None
):
    # Arrange
    taxonomy = pack()
    result = mapping("c08_03", "0080", 4.583561643835616)

    # Act
    findings = check_structure(result.canonical, taxonomy)
    content = write_instance(result.canonical, taxonomy).content.decode("utf-8")

    # Assert
    assert findings == []
    assert 'decimals="0" unitRef="upure">5</eba_met:ii791>' in content


# ---------------------------------------------------------------------------
# What is not rounded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "column"),
    [
        pytest.param("c08_01", "0300", id="OF08.01-obligors"),
        pytest.param("c08_03", "0060", id="OF08.03-obligors"),
        pytest.param("c08_05", "0020", id="OF08.05-obligors"),
    ],
)
def test_a_fractional_count_is_not_rounded_and_is_still_refused(template: str, column: str) -> None:
    """A fractional number of obligors is wrong, not imprecise: it stays a finding.

    Detects the over-broad fix that rounds every integer-typed data point —
    under it the value files as 2.0 and the structure check finds nothing.
    """
    # Arrange
    result = mapping(template, column, 2.5)

    # Act
    findings = check_structure(result.canonical, pack())

    # Assert
    assert [fact[-1] for fact in placed(result)] == [2.5]
    assert [finding.code for finding in findings] == ["STR006"]


# ---------------------------------------------------------------------------
# The premise, against the taxonomy
# ---------------------------------------------------------------------------


def test_the_averaged_metrics_are_integer_typed_in_the_filing_taxonomy() -> None:
    """The rounding is keyed to two metrics; this says why, from the pack itself.

    If a later release retypes a maturity metric as a decimal, or moves the
    averaged columns onto another metric, this fails with the reason — rather
    than the rounding going quiet and ``STR006`` coming back unexplained. And a
    new integer metric that is not a count forces a decision on whether it is
    an average too.
    """
    # Arrange
    taxonomy = pack()
    metric_of = pl.DataFrame(
        {
            "datapoint": list(range(len(taxonomy.datapoints))),
            "metric": [point.metric for point in taxonomy.datapoints],
        },
        schema={"datapoint": taxonomy.cells.schema["datapoint"], "metric": pl.String},
    )

    # Act
    averaged = (
        taxonomy.cells.join(metric_of, on="datapoint")
        .filter(
            pl.struct("table", "column").is_in(
                [{"table": table, "column": column} for table, column in AVERAGED_COLUMNS]
            )
        )
        .group_by("table", "column")
        .agg(pl.col("metric").unique(), pl.len().alias("cells"))
    )
    integer_labels = {
        qname: metric.label
        for qname, metric in taxonomy.metrics.items()
        if metric.data_type == "integer" and qname not in (DAYS, YEARS)
    }

    # Assert
    assert taxonomy.metrics[DAYS].data_type == "integer"
    assert taxonomy.metrics[YEARS].data_type == "integer"
    assert {
        (table, column): metrics for table, column, metrics, _cells in averaged.iter_rows()
    } == {key: [metric] for key, metric in AVERAGED_COLUMNS.items()}
    assert all(cells > 0 for *_key, cells in averaged.iter_rows())
    assert {
        qname: label
        for qname, label in integer_labels.items()
        if not label.startswith(("Number of", "Length of"))
    } == {}
