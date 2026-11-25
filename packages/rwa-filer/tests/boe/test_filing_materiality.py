"""Reported precision and presence at the Bank's measured PRA001 boundaries."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from rwa_filer.boe.catalogue import load_rulebook
from rwa_filer.boe.engine import Accuracy, evaluate_rules
from rwa_filer.taxonomy.pack import TaxonomyPack, load_packaged
from rwa_filer.validate.returns import validate_return
from rwa_filer.validate.review import ReviewFilter
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import InstanceOptions, UnwritableReturnError, write_instance
from summed_returns import canonical_return


@pytest.fixture(scope="module")
def pack() -> TaxonomyPack:
    return load_packaged("pra001-4.1.1")


@pytest.mark.parametrize(
    ("total", "expected"), [(99.99, "PASS"), (100.01, "PASS"), (100.02, "FAIL")]
)
def test_b0768_includes_the_penny_boundary(pack: TaxonomyPack, total: float, expected: str) -> None:
    ret = canonical_return(
        "PRA001",
        [
            ("OF08.03.01.01", "0012", None, row, "0010", value, None, 2)
            for row, value in [("0070", total), ("0080", 100.0)]
        ],
    )
    rules = load_rulebook("banking_reporting-4.1.1.json").enforced("PRA001")
    (result,) = evaluate_rules(ret, pack, [next(r for r in rules if r.rule_id == "boe_b0768")])
    assert result.status == expected


def test_positive_subpenny_is_the_same_fact_before_and_after_filing(pack: TaxonomyPack) -> None:
    ret = canonical_return(
        "PRA001", [("OF08.01.01.01", "0002", None, "0010", "0102", 0.004, None, 2)]
    )
    written = read_instance(write_instance(ret, pack).content, pack=pack)
    assert written.ret.facts["value"].to_list() == [0.004]
    rules = load_rulebook("banking_reporting-4.1.1.json").enforced("PRA001")
    rule = next(r for r in rules if r.rule_id == "boe_b1037")
    assert [evaluate_rules(source, pack, [rule])[0].status for source in (ret, written.ret)] == [
        "FAIL",
        "FAIL",
    ]


def test_visible_small_nonzero_in_empty_cell_displays_its_value(pack: TaxonomyPack) -> None:
    ret = canonical_return(
        "PRA001", [("OF08.01.01.01", "0006", None, "0010", "0102", 1e-8, None, 2)]
    )
    rule = next(
        r
        for r in load_rulebook("banking_reporting-4.1.1.json").enforced("PRA001")
        if r.rule_id == "boe_b1039"
    )
    (result,) = evaluate_rules(ret, pack, [rule])
    (visible,) = ReviewFilter(hide_zero_null=True).visible(result)
    assert any(cell.endswith(" = 0.00000001") for cell in visible.cells)


@pytest.mark.parametrize(("stated", "default"), [(-6, -3), (None, -6), (None, -(10**40))])
def test_excessively_coarse_accuracy_blocks_validation_and_writing(
    pack: TaxonomyPack, stated: int | None, default: int
) -> None:
    ret = canonical_return(
        "PRA001", [("OF08.03.01.01", "0012", None, "0070", "0010", 101000.0, None, stated)]
    )
    checked = validate_return(ret, pack, accuracy=Accuracy(monetary_decimals=default))
    assert any(f.code == "STR012" and f.is_blocking for f in checked.structure)
    with pytest.raises(UnwritableReturnError, match="STR012"):
        write_instance(ret, pack, options=InstanceOptions(monetary_decimals=default))


def test_working_list_filters_individual_occurrences_after_gateway_severity(
    pack: TaxonomyPack,
) -> None:
    ret = canonical_return(
        "PRA001",
        [
            ("OF08.01.01.01", "0006", None, "0010", "0101", 0.0, None, 2),
            ("OF08.01.01.01", "0006", None, "0010", "0102", 1.0, None, 2),
            ("OF08.03.01.01", "0012", None, "0070", "0010", 100.02, None, 2),
            ("OF08.03.01.01", "0012", None, "0080", "0010", 100.0, None, 2),
        ],
    )
    rules = load_rulebook("banking_reporting-4.1.1.json").enforced("PRA001")
    numeric, empty = evaluate_rules(
        ret,
        pack,
        [next(r for r in rules if r.rule_id == code) for code in ("boe_b0768", "boe_b1039")],
        max_failures=None,
    )
    review = ReviewFilter(money=Decimal("0.02"), hide_zero_null=True)
    assert len(review.visible(empty)) == 1
    assert review.visible(empty)[0].addresses[0].column == "0102"
    assert len(review.visible(numeric)) == 1
    warning = replace(numeric, severity="WARNING")
    assert review.visible(warning) == ()
    assert ReviewFilter(money=Decimal("0.01")).visible(warning) == warning.failures
    assert review.visible(replace(empty, severity="WARNING")) == empty.failures
    assert empty.unsatisfied == 2 and numeric.status == "FAIL"
