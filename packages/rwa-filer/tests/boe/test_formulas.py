"""
``boe.formulas`` — the dimensions a rule's XBRL formula closes — and what the
importer, the catalogue and the engine each do with them.

The taxonomy package here is a few formula files written by hand in the shape
the Bank's are published in: a value assertion, filters hung off the variable
set, filters hung off single variables. Nothing is read from the real package;
``test_packaged_rulebooks.py`` pins what the real one yields.

References:
- packages/rwa-filer/src/rwa_filer/boe/formulas.py
- XBRL Formula 1.0; Dimension Filters 1.0
"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import polars as pl
import pytest

from boe_builders import T01, T02, book, ref, rule
from pack_builders import SAMPLE_MODULE, build_pack, build_return
from rwa_filer.boe.catalogue import rulebook_from
from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    Accuracy,
    evaluate_rules,
)
from rwa_filer.boe.formulas import FormulaPackageError, read_formula_reach
from rwa_filer.boe.importer import (
    dump_rulebook,
    has_formula_reach,
    import_workbook,
    is_rulebook_current,
    without_formula_reach,
    write_rulebook,
)
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.boe.formulas import RuleReach
    from rwa_filer.taxonomy.pack import TaxonomyPack

EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)
FOLDER = "pub/www.example.test/fws/test/test/2027-01-01/val"

_NAMESPACES = (
    'xmlns:link="http://www.xbrl.org/2003/linkbase" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:gen="http://xbrl.org/2008/generic" '
    'xmlns:va="http://xbrl.org/2008/assertion/value" '
    'xmlns:variable="http://xbrl.org/2008/variable" '
    'xmlns:df="http://xbrl.org/2008/filter/dimension" '
    'xmlns:bf="http://xbrl.org/2008/filter/boolean"'
)


# ---------------------------------------------------------------------------
# Builders — one formula file, in the published shape
# ---------------------------------------------------------------------------


def explicit(label: str, dimension: str, *members: str) -> str:
    listed = "".join(f"<df:member><df:qname>{m}</df:qname></df:member>" for m in members)
    return (
        f'<df:explicitDimension xlink:type="resource" xlink:label="{label}">'
        f"<df:dimension><df:qname>{dimension}</df:qname></df:dimension>{listed}"
        "</df:explicitDimension>"
    )


def typed(label: str, dimension: str) -> str:
    return (
        f'<df:typedDimension xlink:type="resource" xlink:label="{label}">'
        f"<df:dimension><df:qname>{dimension}</df:qname></df:dimension></df:typedDimension>"
    )


def set_arc(to: str, *, complement: bool = False) -> str:
    return (
        '<variable:variableSetFilterArc xlink:type="arc" xlink:from="rule" '
        f'xlink:to="{to}" complement="{str(complement).lower()}"/>'
    )


def variable(name: str) -> str:
    return (
        f'<variable:factVariable xlink:type="resource" xlink:label="rule.{name}" '
        'bindAsSequence="false"/>'
        f'<variable:variableArc xlink:type="arc" xlink:from="rule" xlink:to="rule.{name}" '
        f'name="{name}"/>'
    )


def variable_arc(source: str, to: str, *, complement: bool = False) -> str:
    return (
        f'<variable:variableFilterArc xlink:type="arc" xlink:from="{source}" xlink:to="{to}" '
        f'complement="{str(complement).lower()}" cover="true"/>'
    )


def formula(*parts: str) -> str:
    body = "".join(parts)
    return (
        f'<?xml version="1.0" encoding="utf-8"?><link:linkbase {_NAMESPACES}>'
        '<gen:link xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">'
        '<va:valueAssertion xlink:type="resource" xlink:label="rule" test="true()"/>'
        f"{body}</gen:link></link:linkbase>"
    )


def package(path: Path, formulas: dict[str, str], *, folder: str = FOLDER) -> Path:
    with zipfile.ZipFile(path, "a") as archive:
        for rule_id, content in formulas.items():
            archive.writestr(f"{folder}/vr-{rule_id}.xml", content)
            # The message files that sit beside every formula are not formulas.
            archive.writestr(f"{folder}/vr-{rule_id}-err-en.xml", "<not-a-formula/>")
    return path


#: Closes EXC for the whole set; closes UDI (typed) for the set; fixes BAS to a
#: real member; closes TRI for v0 only; and has a default pin nested in an
#: ``or`` filter, which closes nothing.
SHAPES = formula(
    explicit("f0", "tst_dim:EXC", "tst_EC:x0"),
    set_arc("f0"),
    typed("f1", "tst_dim:UDI"),
    set_arc("f1", complement=True),
    explicit("f2", "tst_dim:BAS", "tst_BA:x9"),
    set_arc("f2"),
    variable("v0"),
    variable("v1"),
    explicit("v0f0", "tst_dim:TRI", "tst_TR:x0"),
    variable_arc("rule.v0", "v0f0"),
    explicit("v1f0", "tst_dim:TRI", "tst_TR:x5"),
    variable_arc("rule.v1", "v1f0"),
    '<bf:orFilter xlink:type="resource" xlink:label="or"/>',
    variable_arc("rule.v1", "or"),
    explicit("nested", "tst_dim:MCY", "tst_MC:x0"),
    variable_arc("or", "nested"),
)


# ---------------------------------------------------------------------------
# Reading a formula
# ---------------------------------------------------------------------------


class TestWhatAFormulaCloses:
    @pytest.fixture
    def reach(self, tmp_path: Path) -> RuleReach:
        return read_formula_reach(package(tmp_path / "t.zip", {"r1": SHAPES}), ["r1"]).rules["r1"]

    def test_a_dimension_fixed_to_its_default_member_for_the_set_is_closed(
        self, reach: RuleReach
    ) -> None:
        assert "tst_dim:EXC" in reach.closed

    def test_a_typed_dimension_required_absent_is_closed(self, reach: RuleReach) -> None:
        assert "tst_dim:UDI" in reach.closed

    def test_a_dimension_fixed_to_a_real_member_is_not_closed(self, reach: RuleReach) -> None:
        """That member is the cell's own: the rule text already names it."""
        assert "tst_dim:BAS" not in reach.closed

    def test_a_dimension_closed_on_one_variable_is_closed_for_that_variable_only(
        self, reach: RuleReach
    ) -> None:
        assert reach.closed_by_variable == {"v0": frozenset({"tst_dim:TRI"})}

    def test_a_filter_nested_in_a_boolean_filter_closes_nothing(self, reach: RuleReach) -> None:
        """It is one alternative of an ``or``; the fact may pass by another."""
        everything = set(reach.closed) | {
            d for dims in reach.closed_by_variable.values() for d in dims
        }
        assert "tst_dim:MCY" not in everything

    def test_a_present_typed_dimension_and_a_member_list_close_nothing(
        self, tmp_path: Path
    ) -> None:
        # Arrange — "has UDI" (not complemented), and EXC in a list of two.
        content = formula(
            typed("f0", "tst_dim:UDI"),
            set_arc("f0"),
            explicit("f1", "tst_dim:EXC", "tst_EC:x0", "tst_EC:x1"),
            set_arc("f1"),
        )

        # Act
        reach = read_formula_reach(package(tmp_path / "t.zip", {"r1": content}), ["r1"])

        # Assert
        assert reach.rules["r1"].closed == frozenset()


class TestWhichFolderIsRead:
    def test_the_folder_whose_formulas_are_the_rules_asked_about_is_read(
        self, tmp_path: Path
    ) -> None:
        """Two framework versions share rule codes; the closer match is the one meant."""
        # Arrange — r1 exists in both; "full" also has r2, "small" has only r1.
        path = tmp_path / "t.zip"
        closes = formula(explicit("f0", "tst_dim:EXC", "tst_EC:x0"), set_arc("f0"))
        package(path, {"r1": formula(), "r2": formula()}, folder="p/fws/test/full/2027/val")
        package(path, {"r1": closes}, folder="p/fws/test/small/2027/val")

        # Act
        small = read_formula_reach(path, ["r1"])
        full = read_formula_reach(path, ["r1", "r2"])

        # Assert
        assert (small.folder, full.folder) == ("test/small/2027", "test/full/2027")
        assert small.rules["r1"].closed == frozenset({"tst_dim:EXC"})
        assert full.rules["r1"].closed == frozenset()

    def test_a_rule_with_no_formula_file_is_simply_absent(self, tmp_path: Path) -> None:
        reach = read_formula_reach(package(tmp_path / "t.zip", {"r1": SHAPES}), ["r1", "r9"])
        assert set(reach.rules) == {"r1"}

    def test_a_package_with_none_of_the_rules_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FormulaPackageError, match="no formula"):
            read_formula_reach(package(tmp_path / "t.zip", {"r1": SHAPES}), ["other"])

    def test_a_formula_that_declares_an_entity_is_refused_not_parsed(self, tmp_path: Path) -> None:
        # Arrange
        hostile = '<!DOCTYPE x [<!ENTITY a "aaaa">]>' + formula()
        path = package(tmp_path / "t.zip", {"r1": hostile})

        # Act / Assert
        with pytest.raises(FormulaPackageError, match="document type"):
            read_formula_reach(path, ["r1"])


# ---------------------------------------------------------------------------
# The importer and the catalogue
# ---------------------------------------------------------------------------

HEADER = [
    "Framework version code",
    "Rule code",
    "Expression",
    "Include in XBRL",
    "Deactivated",
    "Always execute",
    "Severity and modules",
    "T1",
]
WORKBOOK_NAME = "Bank of England Banking Taxonomy Validations Test v9.8.7.xlsx"


def workbook(path: Path, *rule_ids: str) -> Path:
    """A rule workbook in the published layout, one harmless rule per code."""
    openpyxl = pytest.importorskip("openpyxl", reason="a rule workbook needs rwa-filer[excel]")
    book_ = openpyxl.Workbook()
    book_.active.title = "Note"
    sheet = book_.create_sheet("test")
    sheet.append(HEADER)
    expression = f"{ref(T01, '0010', '0010')} >= 0"
    for rule_id in rule_ids:
        sheet.append(["test", rule_id, expression, "yes", "no", "no", "ERROR - TST001|", T01])
    book_.save(path)
    return path


@pytest.fixture
def imported(tmp_path: Path) -> dict:
    """A two-rule workbook imported with a package that has a formula for r1 only."""
    path = workbook(tmp_path / WORKBOOK_NAME, "r1", "r2")
    plain = formula(explicit("f0", "tst_dim:BAS", "tst_BA:x0"), set_arc("f0"))
    zipped = package(tmp_path / "taxonomy.zip", {"r1": SHAPES, "r2": plain})
    return import_workbook(path, taxonomy_package=zipped)


class TestTheRuleBookRecordsReach:
    def test_the_file_lists_every_closed_dimension_once_and_each_rule_what_it_leaves_open(
        self, imported: dict
    ) -> None:
        # Assert — r1 closes EXC and UDI and leaves BAS open; r2 the reverse.
        by_id = {entry["id"]: entry for entry in imported["rules"]}
        assert imported["formula_dimensions"] == ["tst_dim:BAS", "tst_dim:EXC", "tst_dim:UDI"]
        assert by_id["r1"]["open"] == ["tst_dim:BAS"]
        assert by_id["r1"]["closed"] == {"v0": ["tst_dim:TRI"]}
        assert by_id["r2"]["open"] == ["tst_dim:EXC", "tst_dim:UDI"]
        formulas = imported["source"]["formulas"]
        assert formulas["folder"] == "test/test/2027-01-01"
        assert len(formulas["package_sha256"]) == 64

    def test_the_catalogue_turns_what_is_left_open_back_into_what_is_closed(
        self, imported: dict
    ) -> None:
        # Act
        rules = {entry.rule_id: entry for entry in rulebook_from(imported).rules}

        # Assert
        assert rules["r1"].closed == frozenset({"tst_dim:EXC", "tst_dim:UDI"})
        assert rules["r1"].closed_by_variable == {"v0": frozenset({"tst_dim:TRI"})}
        assert rules["r2"].closed == frozenset({"tst_dim:BAS"})

    def test_a_rule_book_built_without_a_package_closes_nothing(self, tmp_path: Path) -> None:
        # Act
        plain = import_workbook(workbook(tmp_path / WORKBOOK_NAME, "r1"))

        # Assert
        assert not has_formula_reach(plain)
        assert "formula_dimensions" not in plain
        assert rulebook_from(plain).rules[0].closed == frozenset()


def test_the_package_is_recorded_by_its_content_not_its_file_name(tmp_path: Path) -> None:
    """The same publication saved under another name yields the same rule book."""
    # Arrange
    path = workbook(tmp_path / WORKBOOK_NAME, "r1")
    first = package(tmp_path / "boe-banking-v411.zip", {"r1": SHAPES})
    second = tmp_path / "downloaded (1).zip"
    second.write_bytes(first.read_bytes())

    # Act
    a = import_workbook(path, taxonomy_package=first)
    b = import_workbook(path, taxonomy_package=second)

    # Assert
    assert dump_rulebook(a) == dump_rulebook(b)


class TestCheckingAPackagedRuleBook:
    def test_a_workbook_alone_confirms_the_workbook_content_of_a_file_with_reach(
        self, imported: dict, tmp_path: Path
    ) -> None:
        """Without the package the reach can be neither confirmed nor contradicted."""
        # Arrange
        out = tmp_path / "book.json"
        write_rulebook(imported, out)
        plain = import_workbook(tmp_path / WORKBOOK_NAME)

        # Act / Assert
        assert is_rulebook_current(imported, out)
        assert is_rulebook_current(plain, out)
        assert dump_rulebook(without_formula_reach(json.loads(out.read_text()))) == (
            dump_rulebook(plain)
        )

    def test_a_different_reach_is_out_of_date_when_the_package_is_given(
        self, imported: dict, tmp_path: Path
    ) -> None:
        # Arrange — the packaged file says r1 leaves EXC open as well.
        out = tmp_path / "book.json"
        stale = json.loads(dump_rulebook(imported))
        stale["rules"][0]["open"] = ["tst_dim:BAS", "tst_dim:EXC"]
        write_rulebook(stale, out)

        # Act / Assert
        assert not is_rulebook_current(imported, out)

    def test_a_workbook_alone_still_catches_a_changed_expression(
        self, imported: dict, tmp_path: Path
    ) -> None:
        # Arrange
        out = tmp_path / "book.json"
        stale = json.loads(dump_rulebook(imported))
        stale["rules"][0]["expression"] += " "
        write_rulebook(stale, out)
        plain = import_workbook(tmp_path / WORKBOOK_NAME)

        # Act / Assert
        assert not is_rulebook_current(plain, out)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value"]
#: RWEA (row 0020) may not exceed exposure (row 0010) — on every sheet of T02.
CAP = f"{ref(T02, '0020', '0010', var='v0')} i<= {ref(T02, '0010', '0010', var='v1')}"
BROKEN = [(T02, "0001", None, "0010", "0010", 100.0), (T02, "0001", None, "0020", "0010", 150.0)]


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def evaluate(pack: TaxonomyPack, a_rule: Rule, rows: list[tuple[object, ...]]) -> RuleResult:
    ret = build_return(pl.DataFrame(rows, schema=COLUMNS, orient="row"))
    (result,) = evaluate_rules(ret, pack, [a_rule], accuracy=EXACT)
    return result


class TestARuleItsFormulaCannotFire:
    """T02's sheets are members of ``tst_dim:EXC``; every cell of it carries one."""

    def test_the_rule_runs_from_its_text_when_the_formula_closes_nothing(
        self, pack: TaxonomyPack
    ) -> None:
        # Act
        result = evaluate(pack, rule("cap", CAP, tables=(T02,)), BROKEN)

        # Assert
        assert result.status == STATUS_FAIL

    def test_a_formula_that_closes_the_tables_sheet_dimension_is_never_evaluated(
        self, pack: TaxonomyPack
    ) -> None:
        """The Bank's OF 91.01 rules: the gateway cannot fire them, so no break is reported."""
        # Arrange
        dead = rule("cap", CAP, tables=(T02,), closed=frozenset({"tst_dim:EXC"}))

        # Act
        result = evaluate(pack, dead, BROKEN)

        # Assert
        assert result.status == STATUS_NOT_EVALUATED
        assert result.reason == REASON_CLOSED_BY_FORMULA
        assert "tst_dim:EXC" in result.detail

    def test_a_dimension_the_cells_do_not_carry_shuts_nothing_out(self, pack: TaxonomyPack) -> None:
        # Arrange — the usual case: a formula closes a hundred dimensions the cell lacks.
        usual = rule("cap", CAP, tables=(T02,), closed=frozenset({"tst_dim:BAS", "tst_dim:TRI"}))

        # Act
        result = evaluate(pack, usual, BROKEN)

        # Assert
        assert result.status == STATUS_FAIL

    def test_a_variable_shut_out_falls_back_on_its_default(self, pack: TaxonomyPack) -> None:
        """Closed for ``v1`` only: exposure is read as its default, zero, and RWEA exceeds it."""
        # Arrange — text alone: 50 <= 100 holds.
        holds = [
            (T02, "0001", None, "0010", "0010", 100.0),
            (T02, "0001", None, "0020", "0010", 50.0),
        ]
        partly = rule(
            "cap", CAP, tables=(T02,), closed_by_variable={"v1": frozenset({"tst_dim:EXC"})}
        )

        # Act
        result = evaluate(pack, partly, holds)

        # Assert — 50 <= 0 does not hold.
        assert (result.satisfied, result.unsatisfied) == (0, 1)


class TestCoverageOfATemplateWhoseRulesCannotFire:
    def test_a_template_whose_only_rules_are_closed_is_not_reported_as_unchecked(
        self, pack: TaxonomyPack
    ) -> None:
        """The gateway has no rule it can run there; that is not a gap in THIS check."""
        # Arrange — T01 has a live rule; T02's only rule is closed by its formula.
        live = rule("live", f"{ref(T01, '0010', '0010')} >= 0", tables=(T01,))
        dead = rule("dead", CAP, tables=(T02,), closed=frozenset({"tst_dim:EXC"}))
        rows = [(T01, None, None, "0010", "0010", 5.0), *BROKEN]
        ret = build_return(pl.DataFrame(rows, schema=COLUMNS, orient="row"))

        # Act
        validation = validate_return(ret, pack, rulebook=book(live, dead), accuracy=EXACT)

        # Assert
        report = validation.report
        assert report is not None
        assert report.not_evaluated_reasons() == {REASON_CLOSED_BY_FORMULA: 1}
        assert "T02.00.01" in report.templates_reported
        assert report.templates_uncovered == ()
        assert report.coverage_shortfall is None
        assert report.module == SAMPLE_MODULE
