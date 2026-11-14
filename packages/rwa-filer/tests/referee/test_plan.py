"""
The referee's plan: which assertions an instance can fire, and how they are trimmed.

Everything here runs against a small synthetic taxonomy package built by the
test — an entry point, its filing-indicator preconditions, a few assertion
files of chosen sizes and a few tables — laid out the way the Bank of England
package is. No Arelle, and no publisher file.

The module, ``tst001``
- ``boe_b0001`` (400 bytes) and ``boe_b0002`` (300) need template ``T01.00.01``.
- ``v0003_m`` (300) needs ``T01.00.01`` AND ``T02.00.01``, in one conjoined test.
- ``boe_b0004`` (200) needs ``T02.00.01``.
- ``boe_b0005`` (100) has a precondition of a shape the planner does not
  claim to understand: it is true when ``T03.00.01`` is NOT filed.
- ``boe_b0006`` (250) has TWO preconditions: ``T01.00.01``, and ``T03.00.01``.
- ``boe_b0099`` is referenced by the entry point and has no precondition at all.

Tables ``t01.00.01.01`` and ``t01.00.01.02`` carry the code ``T01.00.01``,
``t02.00.01.01`` carries ``T02.00.01``, ``t03.00.01.01`` carries ``T03.00.01``,
and ``t09.00.01.01`` has no filing-indicator label.
"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr

import pytest

from rwa_filer.referee.plan import (
    ARCROLE_PRECONDITION,
    NS_FIND,
    NS_GEN,
    NS_LINK,
    NS_VARIABLE,
    NS_XLINK,
    ROLE_FILING_INDICATOR_CODE,
    TABLES_ALL,
    TABLES_INDICATED,
    RefereePlanError,
    TaxonomyModule,
    read_instance_header,
    rule_id,
)

BASE_URL = "http://www.example.test/xbrl/fws/tst/2027-01-01"
ENTRY_POINT = f"{BASE_URL}/mod/tst001.xsd"
FRAMEWORK = "tst-package/www.example.test/xbrl/fws/tst/2027-01-01"
XLINK = f"{{{NS_XLINK}}}"
NS_XSD = "http://www.w3.org/2001/XMLSchema"
NS_CATALOG = "urn:oasis:names:tc:entity:xmlns:xml:catalog"
LINKBASE_ARCROLE = "http://www.w3.org/1999/xlink/properties/linkbase"

T01, T02, T03 = "T01.00.01", "T02.00.01", "T03.00.01"
NOT_T03 = f"not($find:t{T03}) or 1 < 2"


@dataclass(frozen=True)
class Rule:
    """One assertion of the synthetic module: ``vr-<name>.xml``, id ``boe_<name>``."""

    name: str
    size: int
    tests: tuple[str, ...]

    @property
    def file(self) -> str:
        return f"vr-{self.name}.xml"

    @property
    def assertion_id(self) -> str:
        return f"boe_{self.name}"


RULES = (
    Rule("boe_b0001", 400, (f"$find:t{T01}",)),
    Rule("boe_b0002", 300, (f"$find:t{T01}",)),
    Rule("v0003_m", 300, (f"($find:t{T01} and $find:t{T02})",)),
    Rule("boe_b0004", 200, (f"$find:t{T02}",)),
    Rule("boe_b0005", 100, (NOT_T03,)),
    Rule("boe_b0006", 250, (f"$find:t{T01}", f"$find:t{T03}")),
)
UNCONDITIONED = "boe_b0099"
TABLES = {
    "t01.00.01.01": T01,
    "t01.00.01.02": T01,
    "t02.00.01.01": T02,
    "t03.00.01.01": T03,
    "t09.00.01.01": None,
}
ALL_FILES = [rule.file for rule in RULES]


def _linkbase_ref(href: str) -> str:
    return (
        f'      <link:linkbaseRef xlink:href="{href}" xlink:type="simple"'
        f' xlink:arcrole="{LINKBASE_ARCROLE}" />\n'
    )


def _entry_point_xsd() -> str:
    refs = [_linkbase_ref("tst001-lab-en.xml"), _linkbase_ref("tst001-pre.xml")]
    refs.append(_linkbase_ref("../val/aset-t01.00.01.01.xml"))
    for name in [*(rule.name for rule in RULES), UNCONDITIONED]:
        refs.append(_linkbase_ref(f"../val/vr-{name}-err-en.xml"))
        refs.append(_linkbase_ref(f"../val/vr-{name}-lab-en.xml"))
    refs.append(_linkbase_ref("../val/find-params.xml"))
    refs.append(_linkbase_ref("tst001-find-prec.xml"))
    imports = [
        '  <xsd:import namespace="http://www.example.test/xbrl/dict/dim"'
        ' schemaLocation="../../../../dict/dim/dim.xsd" />\n'
    ]
    imports += [
        f'  <xsd:import namespace="{BASE_URL}/tab/{table.upper()}"'
        f' schemaLocation="../tab/{table}/{table}.xsd" />\n'
        for table in TABLES
    ]
    imports.append(
        '  <xsd:import namespace="http://www.xbrl.org/2003/instance"'
        ' schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd" />\n'
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<xsd:schema xmlns:xsd="{NS_XSD}" xmlns:link="{NS_LINK}" xmlns:xlink="{NS_XLINK}"'
        f' targetNamespace="{BASE_URL}/mod/tst001" elementFormDefault="qualified">\n'
        "  <xsd:annotation>\n    <xsd:appinfo>\n"
        + "".join(refs)
        + "    </xsd:appinfo>\n  </xsd:annotation>\n"
        + "".join(imports)
        + '  <xsd:element id="tst_TST001" name="TST001" abstract="true" />\n'
        "</xsd:schema>\n"
    )


def _preconditions(rules: tuple[Rule, ...], extra: str = "") -> str:
    """The ``-find-prec`` linkbase, in the publisher's shape: a test, then its assertions."""
    tests = list(dict.fromkeys(test for rule in rules for test in rule.tests))
    located: set[str] = set()
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<link:linkbase xmlns:xlink="{NS_XLINK}" xmlns:link="{NS_LINK}" xmlns:gen="{NS_GEN}"'
        f' xmlns:find="{NS_FIND}" xmlns:variable="{NS_VARIABLE}">\n'
        '  <gen:link xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">\n'
    ]
    for number, test in enumerate(tests, 1):
        parts.append(
            f'    <variable:precondition xlink:type="resource" xlink:label="findPrec{number}"'
            f" test={quoteattr(test)} />\n"
        )
        for rule in rules:
            if test not in rule.tests:
                continue
            label = f"loc_{rule.assertion_id}"
            if rule.name not in located:
                located.add(rule.name)
                parts.append(
                    '    <link:loc xlink:type="locator"'
                    f' xlink:href="../val/{rule.file}#{rule.assertion_id}"'
                    f' xlink:label="{label}" />\n'
                )
            parts.append(
                f'    <gen:arc xlink:type="arc" xlink:arcrole="{ARCROLE_PRECONDITION}"'
                f' xlink:from="{label}" xlink:to="findPrec{number}" />\n'
            )
    parts.append(extra + "  </gen:link>\n</link:linkbase>\n")
    return "".join(parts)


def _table_labels(table: str, code: str | None) -> str:
    """A table's ``-lab-codes`` linkbase: its own code and, if any, its indicator code."""
    labels = [
        '    <label:label xlink:type="resource" xlink:label="rc"'
        ' xlink:role="http://www.eurofiling.info/xbrl/role/rc-code"'
        f' xml:lang="en">{table.upper()}</label:label>\n'
    ]
    if code is not None:
        labels.append(
            '    <label:label xlink:type="resource" xlink:label="fi"'
            f' xlink:role="{ROLE_FILING_INDICATOR_CODE}" xml:lang="en">{code}</label:label>\n'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<link:linkbase xmlns:link="{NS_LINK}" xmlns:gen="{NS_GEN}"'
        f' xmlns:label="http://xbrl.org/2008/label" xmlns:xlink="{NS_XLINK}">\n'
        '  <gen:link xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">\n'
        + "".join(labels)
        + "  </gen:link>\n</link:linkbase>\n"
    )


def build_package(path: Path, *, rules: tuple[Rule, ...] = RULES, extra: str = "") -> Path:
    """Write the synthetic taxonomy package zip and return its path."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("tst-package/META-INF/taxonomyPackage.xml", "<taxonomyPackage/>")
        archive.writestr(f"{FRAMEWORK}/mod/tst001.xsd", _entry_point_xsd())
        archive.writestr(f"{FRAMEWORK}/mod/tst001-find-prec.xml", _preconditions(rules, extra))
        for rule in rules:
            archive.writestr(f"{FRAMEWORK}/val/{rule.file}", "x" * rule.size)
        archive.writestr(f"{FRAMEWORK}/val/vr-{UNCONDITIONED}.xml", "x" * 50)
        for table, code in TABLES.items():
            archive.writestr(
                f"{FRAMEWORK}/tab/{table}/{table}-lab-codes.xml", _table_labels(table, code)
            )
        # A file of another framework: no part of this entry point's size.
        archive.writestr("tst-package/www.example.test/xbrl/dict/dim/dim.xsd", "x" * 1000)
    return path


@pytest.fixture
def module(tmp_path: Path) -> TaxonomyModule:
    return TaxonomyModule.read(build_package(tmp_path / "taxonomy.zip"), ENTRY_POINT)


def overlay(module: TaxonomyModule, path: Path, files: list[str], *filed: str, tables: str) -> Path:
    return module.write_overlay(path, files, frozenset(filed), tables=tables)


def member(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def linkbase_refs(xsd: str) -> list[str]:
    root = ElementTree.fromstring(xsd)
    return [ref.get(f"{XLINK}href", "") for ref in root.iter(f"{{{NS_LINK}}}linkbaseRef")]


def imported(xsd: str) -> list[str]:
    root = ElementTree.fromstring(xsd)
    return [node.get("schemaLocation", "") for node in root.iter(f"{{{NS_XSD}}}import")]


def guarded(preconditions: str) -> list[tuple[str, str]]:
    """Every (assertion locator href, precondition test) pair a linkbase joins by an arc."""
    root = ElementTree.fromstring(preconditions)
    tests = {
        node.get(f"{XLINK}label"): node.get("test", "")
        for node in root.iter(f"{{{NS_VARIABLE}}}precondition")
    }
    hrefs = {
        node.get(f"{XLINK}label"): node.get(f"{XLINK}href", "")
        for node in root.iter(f"{{{NS_LINK}}}loc")
    }
    return sorted(
        (hrefs[arc.get(f"{XLINK}from")], tests[arc.get(f"{XLINK}to")])
        for arc in root.iter(f"{{{NS_GEN}}}arc")
    )


# ---------------------------------------------------------------------------
# Reading an entry point
# ---------------------------------------------------------------------------


def test_each_assertion_carries_its_id_size_and_the_indicators_it_needs(
    module: TaxonomyModule,
) -> None:
    # Act
    read = {
        file: (assertion.assertion_id, assertion.size, set(assertion.needs))
        for file, assertion in module.assertions.items()
    }

    # Assert — a single test, a conjoined one, an unrecognised one, and two tests.
    assert read == {
        "vr-boe_b0001.xml": ("boe_boe_b0001", 400, {T01}),
        "vr-boe_b0002.xml": ("boe_boe_b0002", 300, {T01}),
        "vr-v0003_m.xml": ("boe_v0003_m", 300, {T01, T02}),
        "vr-boe_b0004.xml": ("boe_boe_b0004", 200, {T02}),
        "vr-boe_b0005.xml": ("boe_boe_b0005", 100, {T03}),
        "vr-boe_b0006.xml": ("boe_boe_b0006", 250, {T01, T03}),
    }


def test_an_assertion_keeps_every_precondition_test_as_written(module: TaxonomyModule) -> None:
    # Assert — the conjunction is one test; two preconditions are two.
    assert module.assertions["vr-v0003_m.xml"].tests == (f"($find:t{T01} and $find:t{T02})",)
    assert module.assertions["vr-boe_b0006.xml"].tests == (f"$find:t{T01}", f"$find:t{T03}")
    assert module.assertions["vr-boe_b0005.xml"].tests == (NOT_T03,)


def test_an_assertion_knows_its_published_rule_id(module: TaxonomyModule) -> None:
    assert module.assertions["vr-boe_b0001.xml"].rule_id == "boe_b0001"
    assert module.assertions["vr-v0003_m.xml"].rule_id == "v0003_m"


def test_the_entry_point_is_named_and_sized_by_its_own_framework_folder(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Arrange — what the zip itself says is under the framework folder.
    with zipfile.ZipFile(tmp_path / "taxonomy.zip") as archive:
        under_framework = sum(
            info.file_size for info in archive.infolist() if info.filename.startswith(FRAMEWORK)
        )
        everything = sum(info.file_size for info in archive.infolist())

    # Assert — the dictionary of another folder is not counted.
    assert module.name == "tst001"
    assert module.url == ENTRY_POINT
    assert module.xml_bytes == under_framework < everything
    assert module.xml_mb == pytest.approx(under_framework / 1e6)


def test_each_table_is_read_with_its_filing_indicator_code(module: TaxonomyModule) -> None:
    # Assert — two tables share a template; the one with no label has no code.
    assert module.table_codes == {
        "t01.00.01.01": T01,
        "t01.00.01.02": T01,
        "t02.00.01.01": T02,
        "t03.00.01.01": T03,
    }


def test_an_entry_point_with_no_preconditions_linkbase_has_no_known_assertions(
    tmp_path: Path,
) -> None:
    # Arrange
    package = tmp_path / "bare.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(f"{FRAMEWORK}/mod/tst001.xsd", _entry_point_xsd())

    # Act
    bare = TaxonomyModule.read(package, ENTRY_POINT)

    # Assert
    assert bare.assertions == {}
    assert bare.table_codes == {}


@pytest.mark.parametrize(
    "arc",
    [
        pytest.param(("loc_nowhere", "findPrec1"), id="from-an-unknown-locator"),
        pytest.param(("loc_boe_boe_b0001", "findPrec99"), id="to-an-unknown-precondition"),
        pytest.param(("loc_elsewhere", "findPrec1"), id="from-a-locator-outside-val"),
    ],
)
def test_a_precondition_arc_that_cannot_be_resolved_is_refused(
    tmp_path: Path, arc: tuple[str, str]
) -> None:
    """Skipping it would re-emit the preconditions with a guard missing."""
    # Arrange
    extra = (
        '    <link:loc xlink:type="locator" xlink:href="other.xml#boe_x"'
        ' xlink:label="loc_elsewhere" />\n'
        f'    <gen:arc xlink:type="arc" xlink:arcrole="{ARCROLE_PRECONDITION}"'
        f' xlink:from="{arc[0]}" xlink:to="{arc[1]}" />\n'
    )
    package = build_package(tmp_path / "odd.zip", extra=extra)

    # Act / Assert
    with pytest.raises(RefereePlanError, match="precondition arc"):
        TaxonomyModule.read(package, ENTRY_POINT)


def test_one_file_located_as_two_assertions_is_refused(tmp_path: Path) -> None:
    # Arrange
    extra = (
        '    <link:loc xlink:type="locator" xlink:href="../val/vr-boe_b0001.xml#boe_other"'
        ' xlink:label="loc_other" />\n'
        f'    <gen:arc xlink:type="arc" xlink:arcrole="{ARCROLE_PRECONDITION}"'
        ' xlink:from="loc_other" xlink:to="findPrec1" />\n'
    )
    package = build_package(tmp_path / "odd.zip", extra=extra)

    # Act / Assert
    with pytest.raises(RefereePlanError, match="one assertion per file"):
        TaxonomyModule.read(package, ENTRY_POINT)


def test_a_package_that_is_not_a_zip_is_refused_by_name(tmp_path: Path) -> None:
    # Arrange
    package = tmp_path / "not-a-package.zip"
    package.write_text("plain text, not a zip\n")

    # Act / Assert
    with pytest.raises(RefereePlanError, match=r"not-a-package\.zip is not a zip archive"):
        TaxonomyModule.read(package, ENTRY_POINT)


def test_an_arc_of_another_kind_is_not_a_precondition(tmp_path: Path) -> None:
    # Arrange — an arc with a different arcrole, between labels that mean nothing here.
    extra = (
        '    <gen:arc xlink:type="arc" xlink:arcrole="http://xbrl.org/arcrole/2008/element-label"'
        ' xlink:from="loc_nowhere" xlink:to="label_nowhere" />\n'
    )
    package = build_package(tmp_path / "labelled.zip", extra=extra)

    # Act
    read = TaxonomyModule.read(package, ENTRY_POINT)

    # Assert
    assert sorted(read.assertions) == sorted(ALL_FILES)


# ---------------------------------------------------------------------------
# Selecting what an instance can fire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filed", "dropped"),
    [
        pytest.param({T01, T02, T03}, [], id="everything-filed"),
        pytest.param({T01, T02}, ["vr-boe_b0006.xml"], id="conjunction-met"),
        pytest.param(
            {T01},
            ["vr-boe_b0004.xml", "vr-boe_b0006.xml", "vr-v0003_m.xml"],
            id="half-a-conjunction",
        ),
        pytest.param(
            {T03},
            ["vr-boe_b0001.xml", "vr-boe_b0002.xml", "vr-boe_b0004.xml", "vr-boe_b0006.xml"]
            + ["vr-v0003_m.xml"],
            id="only-an-unrelated-template",
        ),
    ],
)
def test_an_assertion_is_kept_only_when_every_template_it_needs_is_filed(
    module: TaxonomyModule, filed: set[str], dropped: list[str]
) -> None:
    # Act
    kept, not_kept = module.select(filed)

    # Assert — a partition of the module's assertions, each side sorted.
    assert not_kept == dropped
    assert kept == sorted(set(ALL_FILES) - set(dropped))


def test_an_unrecognised_precondition_is_kept_never_dropped(module: TaxonomyModule) -> None:
    """``boe_b0005`` holds when T03 is NOT filed: dropping it for a missing T03 is wrong."""
    # Act
    kept_when_nothing_filed, _ = module.select(frozenset())
    kept_when_all_filed, _ = module.select({T01, T02, T03})

    # Assert — whatever is filed, the planner does not presume to decide it.
    assert kept_when_nothing_filed == ["vr-boe_b0005.xml"]
    assert "vr-boe_b0005.xml" in kept_when_all_filed


def test_an_assertion_with_two_preconditions_needs_both(module: TaxonomyModule) -> None:
    # Act
    with_first, _ = module.select({T01})
    with_second, _ = module.select({T03})
    with_both, _ = module.select({T01, T03})

    # Assert
    assert "vr-boe_b0006.xml" not in with_first
    assert "vr-boe_b0006.xml" not in with_second
    assert "vr-boe_b0006.xml" in with_both


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def test_chunks_are_first_fit_decreasing_bins_of_assertion_xml(module: TaxonomyModule) -> None:
    """Largest first; each goes in the first bin with room; an exact fit fits.

    Sizes, largest first: b0001 400, b0002 300, v0003_m 300, b0006 250,
    b0004 200, b0005 100 — against a 600-byte limit.
    """
    # Act
    chunks = module.chunk(ALL_FILES, chunk_mb=600 / 1e6)

    # Assert
    assert chunks == [
        ["vr-boe_b0001.xml", "vr-boe_b0004.xml"],
        ["vr-boe_b0002.xml", "vr-v0003_m.xml"],
        ["vr-boe_b0005.xml", "vr-boe_b0006.xml"],
    ]


def test_no_chunk_exceeds_the_limit_and_none_is_lost(module: TaxonomyModule) -> None:
    # Act
    chunks = module.chunk(ALL_FILES, chunk_mb=600 / 1e6)

    # Assert
    assert sorted(file for chunk in chunks for file in chunk) == sorted(ALL_FILES)
    assert all(sum(module.assertions[file].size for file in chunk) <= 600 for chunk in chunks)


def test_chunking_does_not_depend_on_the_order_files_arrive_in(module: TaxonomyModule) -> None:
    # Act
    forwards = module.chunk(ALL_FILES, chunk_mb=600 / 1e6)
    backwards = module.chunk(reversed(ALL_FILES), chunk_mb=600 / 1e6)
    as_a_set = module.chunk(set(ALL_FILES), chunk_mb=600 / 1e6)

    # Assert
    assert forwards == backwards == as_a_set


def test_a_file_larger_than_the_limit_gets_a_chunk_to_itself(module: TaxonomyModule) -> None:
    # Act — a 250-byte limit, which four of the six files exceed or meet alone,
    # and under which the two smallest (200 and 100) do not fit together either.
    chunks = module.chunk(ALL_FILES, chunk_mb=250 / 1e6)

    # Assert
    assert ["vr-boe_b0001.xml"] in chunks
    assert all(len(chunk) == 1 for chunk in chunks)


def test_everything_fits_one_chunk_under_a_generous_limit(module: TaxonomyModule) -> None:
    assert module.chunk(ALL_FILES, chunk_mb=120.0) == [sorted(ALL_FILES)]
    assert module.chunk([], chunk_mb=120.0) == []


# ---------------------------------------------------------------------------
# The overlay package
# ---------------------------------------------------------------------------

CHUNK = ["vr-boe_b0001.xml", "vr-v0003_m.xml"]


def test_the_overlay_catalog_remaps_the_entry_point_and_its_preconditions(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay0.zip", CHUNK, T01, T02, tables=TABLES_INDICATED)
    catalog = ElementTree.fromstring(member(path, "overlay/META-INF/catalog.xml"))
    rewrites = {
        node.get("uriStartString"): node.get("rewritePrefix", "")
        for node in catalog.iter(f"{{{NS_CATALOG}}}rewriteURI")
    }

    # Assert — exactly the two URLs, each onto a member the overlay really holds.
    assert rewrites == {
        ENTRY_POINT: "../files/tst001.xsd",
        f"{BASE_URL}/mod/tst001-find-prec.xml": "../files/tst001-find-prec.xml",
    }
    with zipfile.ZipFile(path) as archive:
        members = set(archive.namelist())
    for prefix in rewrites.values():
        assert posixpath.normpath(f"overlay/META-INF/{prefix}") in members
    assert "overlay/META-INF/taxonomyPackage.xml" in members


def test_the_overlay_is_a_taxonomy_package_identified_by_module_and_chunk(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay7.zip", CHUNK, T01, tables=TABLES_INDICATED)
    manifest = ElementTree.fromstring(member(path, "overlay/META-INF/taxonomyPackage.xml"))

    # Assert
    identifier = manifest.find("{http://xbrl.org/2016/taxonomy-package}identifier")
    assert identifier is not None
    assert identifier.text == "urn:rwa-filer:referee-overlay:tst001:overlay7"


def test_the_trimmed_entry_point_references_only_the_chunks_assertions(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay0.zip", CHUNK, T01, T02, tables=TABLES_INDICATED)
    refs = linkbase_refs(member(path, "overlay/files/tst001.xsd"))

    # Assert — in the published order: the module's labels; each kept
    # assertion's message linkbase and not its labels; the assertion with no
    # precondition untouched; the parameters and the preconditions. The
    # assertion set, the presentation and every other rule are gone.
    assert refs == [
        "tst001-lab-en.xml",
        "../val/vr-boe_b0001-err-en.xml",
        "../val/vr-v0003_m-err-en.xml",
        "../val/vr-boe_b0099-err-en.xml",
        "../val/vr-boe_b0099-lab-en.xml",
        "../val/find-params.xml",
        "tst001-find-prec.xml",
    ]


def test_an_empty_chunk_still_leaves_what_is_not_understood(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay0.zip", [], T01, tables=TABLES_INDICATED)
    refs = linkbase_refs(member(path, "overlay/files/tst001.xsd"))

    # Assert — no known assertion, but the one with no precondition is never dropped.
    assert [ref for ref in refs if "/vr-" in ref] == [
        "../val/vr-boe_b0099-err-en.xml",
        "../val/vr-boe_b0099-lab-en.xml",
    ]
    assert guarded(member(path, "overlay/files/tst001-find-prec.xml")) == []


def test_only_the_filed_templates_tables_are_imported(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay0.zip", CHUNK, T01, T02, tables=TABLES_INDICATED)
    imports = imported(member(path, "overlay/files/tst001.xsd"))

    # Assert — both tables of T01, the table of T02, not T03's. The table with
    # no readable code stays, and so does every import that is not a table.
    assert imports == [
        "../../../../dict/dim/dim.xsd",
        "../tab/t01.00.01.01/t01.00.01.01.xsd",
        "../tab/t01.00.01.02/t01.00.01.02.xsd",
        "../tab/t02.00.01.01/t02.00.01.01.xsd",
        "../tab/t09.00.01.01/t09.00.01.01.xsd",
        "http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd",
    ]


def test_every_table_stays_imported_when_tables_are_not_trimmed(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay0.zip", CHUNK, T01, tables=TABLES_ALL)
    trimmed = member(path, "overlay/files/tst001.xsd")

    # Assert — the imports as published; the assertion references still trimmed.
    assert imported(trimmed) == imported(module.xsd)
    assert "../val/vr-boe_b0002-err-en.xml" not in linkbase_refs(trimmed)


def test_an_unknown_tables_option_is_a_programming_error(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    with pytest.raises(ValueError, match="tables must be"):
        overlay(module, tmp_path / "overlay0.zip", CHUNK, T01, tables="some")


def test_the_trimmed_preconditions_name_only_the_kept_assertions(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    # Act
    path = overlay(module, tmp_path / "overlay0.zip", CHUNK, T01, T02, tables=TABLES_INDICATED)
    preconditions = member(path, "overlay/files/tst001-find-prec.xml")

    # Assert — each kept assertion, located by file and id, under its own test.
    assert guarded(preconditions) == [
        ("../val/vr-boe_b0001.xml#boe_boe_b0001", f"$find:t{T01}"),
        ("../val/vr-v0003_m.xml#boe_v0003_m", f"($find:t{T01} and $find:t{T02})"),
    ]
    assert "boe_b0002" not in preconditions


def test_the_trimmed_preconditions_keep_every_guard_of_an_assertion(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    """Two preconditions stay two, and a test with markup characters survives."""
    # Arrange
    files = ["vr-boe_b0005.xml", "vr-boe_b0006.xml"]

    # Act
    path = overlay(module, tmp_path / "overlay0.zip", files, T01, T03, tables=TABLES_INDICATED)
    preconditions = member(path, "overlay/files/tst001-find-prec.xml")

    # Assert
    assert guarded(preconditions) == [
        ("../val/vr-boe_b0005.xml#boe_boe_b0005", NOT_T03),
        ("../val/vr-boe_b0006.xml#boe_boe_b0006", f"$find:t{T01}"),
        ("../val/vr-boe_b0006.xml#boe_boe_b0006", f"$find:t{T03}"),
    ]


def test_a_module_read_through_its_overlay_holds_exactly_the_chunk(
    tmp_path: Path, module: TaxonomyModule
) -> None:
    """The trimmed files are themselves a readable entry point: nothing is mangled."""
    # Arrange — the package again, with the overlay's two files in place of its own.
    path = overlay(module, tmp_path / "overlay0.zip", ALL_FILES[2:], T01, tables=TABLES_ALL)
    replaced = {
        f"{FRAMEWORK}/mod/tst001.xsd": member(path, "overlay/files/tst001.xsd"),
        f"{FRAMEWORK}/mod/tst001-find-prec.xml": member(path, "overlay/files/tst001-find-prec.xml"),
    }
    trimmed_package = tmp_path / "trimmed.zip"
    with (
        zipfile.ZipFile(tmp_path / "taxonomy.zip") as source,
        zipfile.ZipFile(trimmed_package, "w") as target,
    ):
        for info in source.infolist():
            target.writestr(info.filename, replaced.get(info.filename, source.read(info)))

    # Act
    reread = TaxonomyModule.read(trimmed_package, ENTRY_POINT)

    # Assert
    assert {file: reread.assertions[file].tests for file in reread.assertions} == {
        file: module.assertions[file].tests for file in ALL_FILES[2:]
    }


# ---------------------------------------------------------------------------
# Rule ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("assertion_id", "expected"),
    [
        pytest.param("boe_boe_b0021", "boe_b0021", id="boe-rule-keeps-its-own-boe"),
        pytest.param("boe_v0718_m", "v0718_m", id="eba-rule-published-by-boe"),
        pytest.param("eba_v0718_m", "v0718_m", id="eba-owner"),
        pytest.param("v0718_m", "v0718_m", id="no-owner-prefix"),
        pytest.param("xyz_boe_b0021", "xyz_boe_b0021", id="prefix-only-at-the-start"),
    ],
)
def test_a_rule_id_is_the_assertion_id_without_its_owner_prefix(
    assertion_id: str, expected: str
) -> None:
    assert rule_id(assertion_id) == expected


# ---------------------------------------------------------------------------
# The instance header
# ---------------------------------------------------------------------------


def write_instance(path: Path, body: str) -> Path:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
        f' xmlns:link="{NS_LINK}" xmlns:xlink="{NS_XLINK}" xmlns:find="{NS_FIND}"'
        ' xmlns:met="http://www.example.test/xbrl/dict/met">\n' + body + "</xbrli:xbrl>\n",
        encoding="utf-8",
    )
    return path


SCHEMA_REF = f'  <link:schemaRef xlink:type="simple" xlink:href="{ENTRY_POINT}"/>\n'
CONTEXT = (
    '  <xbrli:context id="c0"><xbrli:entity><xbrli:identifier scheme="s">E'
    "</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2027-03-31"
    "</xbrli:instant></xbrli:period></xbrli:context>\n"
)


def test_the_header_gives_the_schema_ref_and_the_positive_filing_indicators(
    tmp_path: Path,
) -> None:
    # Arrange — an indicator with no attribute, one filed, one declared NOT filed.
    instance = write_instance(
        tmp_path / "instance.xbrl",
        SCHEMA_REF
        + CONTEXT
        + '  <met:mi1 contextRef="c0" decimals="-3" unitRef="u">5</met:mi1>\n'
        + "  <find:fIndicators>\n"
        + f'    <find:filingIndicator contextRef="c0">{T01}</find:filingIndicator>\n'
        + f'    <find:filingIndicator contextRef="c0" find:filed="true">{T02}'
        + "</find:filingIndicator>\n"
        + f'    <find:filingIndicator contextRef="c0" find:filed="false">{T03}'
        + "</find:filingIndicator>\n"
        + "  </find:fIndicators>\n",
    )

    # Act
    schema_ref, indicators = read_instance_header(instance)

    # Assert
    assert schema_ref == ENTRY_POINT
    assert indicators == {T01, T02}


def test_an_instance_with_no_filing_indicators_files_nothing(tmp_path: Path) -> None:
    # Arrange
    instance = write_instance(tmp_path / "instance.xbrl", SCHEMA_REF + CONTEXT)

    # Act
    _schema_ref, indicators = read_instance_header(instance)

    # Assert
    assert indicators == frozenset()


def test_an_instance_with_no_schema_ref_is_refused(tmp_path: Path) -> None:
    # Arrange
    instance = write_instance(tmp_path / "instance.xbrl", CONTEXT)

    # Act / Assert
    with pytest.raises(RefereePlanError, match="no link:schemaRef"):
        read_instance_header(instance)


@pytest.mark.parametrize(
    "schema_ref",
    [
        pytest.param(f"{BASE_URL}/mod/other.xsd", id="another-module"),
        pytest.param("http://elsewhere.test/mod/tst001.xsd", id="another-host"),
        pytest.param("tst001.xsd", id="a-relative-reference"),
    ],
)
def test_a_schema_ref_that_is_not_in_the_package_is_refused(
    tmp_path: Path, schema_ref: str
) -> None:
    # Arrange
    package = build_package(tmp_path / "taxonomy.zip")

    # Act / Assert
    with pytest.raises(RefereePlanError, match="not an entry point"):
        TaxonomyModule.read(package, schema_ref)


def test_the_plan_errors_are_value_errors() -> None:
    """A caller that validates inputs can catch them with what it already catches."""
    assert issubclass(RefereePlanError, ValueError)
