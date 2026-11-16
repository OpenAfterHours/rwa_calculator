"""
Building a taxonomy release from the publisher's files — ``rwa_filer.release_build``.

Run on a miniature publication: the compiler tests' annotated workbook, DPM
dictionary and taxonomy package (module ``DEMO01``, version 9.9.9), a one-rule
validation workbook, and a sample instance written from the compiled pack.

The miniature taxonomy package holds no XBRL formulas, so the rule book is
imported without formula reach here (``import_workbook`` is wrapped to drop
the package). Formula reach on the real publication is what the opt-in
``boe/test_importer.py`` and ``build_filer_release.py --check`` hold.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import taxonomy_builders as builders
from pack_builders import VALID_LEI
from rwa_filer import __version__, release_build
from rwa_filer.boe.importer import REQUIRED_COLUMNS
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.release_build import (
    BankFiles,
    BankFilesError,
    build_release,
    check_release,
    find_bank_files,
    measure_release,
    reconcile_end_dates,
)
from rwa_filer.taxonomy.compiler import compile_pack
from rwa_filer.taxonomy.pack import load_pack, write_pack
from rwa_filer.xbrl.writer import write_instance

openpyxl = pytest.importorskip("openpyxl", reason="the publisher's workbooks need rwa-filer[excel]")

VERSION = "9.9.9"
KEY = f"{builders.MODULE.lower()}-{VERSION}"
SAMPLE_NAME = f"{VALID_LEI}_GB_banking_{builders.MODULE}_2026-01-31_20260101000000000.xbrl"


@dataclass(frozen=True)
class Publication:
    """The miniature publication's folder, and the package root it is built into."""

    source: Path
    root: Path


@pytest.fixture
def publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Publication:
    # The publisher's files, named as the Bank names them.
    source = tmp_path / "downloads"
    source.mkdir()
    annotated = builders.build_annotated_workbook(
        source / f"Bank of England Banking Annotated Templates v{VERSION} Demo.xlsx"
    )
    dictionary = builders.build_dictionary_workbook(
        source / f"Bank of England Banking DPM dictionary v{VERSION}.xlsx"
    )
    builders.zip_package(builders.build_taxonomy_package(tmp_path / "taxonomy"), source / "pkg.zip")
    _validation_workbook(
        source / f"Bank of England Banking Taxonomy Validations Demo v{VERSION}.xlsx"
    )
    _sample(annotated, dictionary, source / "pkg.zip", source / SAMPLE_NAME, tmp_path / "scratch")

    # The package it is built into: one listed release and nothing packaged.
    root = tmp_path / "rwa_filer"
    (root / release_build.PACKS_SUBDIR).mkdir(parents=True)
    (root / release_build.RULEBOOKS_SUBDIR).mkdir(parents=True)
    _write_releases(root, [VERSION])
    (root / "retired.json").write_text(json.dumps({"format": 1, "releases": []}))

    # No formulas in the miniature package: import the rule book without reach.
    original = release_build.import_workbook
    monkeypatch.setattr(
        release_build,
        "import_workbook",
        lambda workbook, **kwargs: original(workbook, taxonomy_version=kwargs["taxonomy_version"]),
    )
    return Publication(source=source, root=root)


# ---------------------------------------------------------------------------
# Finding the files
# ---------------------------------------------------------------------------


def test_the_publications_files_are_found_by_the_banks_names(publication: Publication) -> None:
    files = find_bank_files(publication.source)

    assert files.taxonomy_package.name == "pkg.zip"
    assert "DPM dictionary" in files.dictionary.name
    assert [path.name for path in files.annotated] == [
        f"Bank of England Banking Annotated Templates v{VERSION} Demo.xlsx"
    ]
    assert len(files.workbooks) == 1
    assert files.sample_for(builders.MODULE) == publication.source / SAMPLE_NAME


def test_the_banks_zips_are_unpacked_beside_them(publication: Publication, tmp_path: Path) -> None:
    # Arrange — the DPM and validation workbooks only inside a zip.
    zipped = tmp_path / "zipped"
    zipped.mkdir()
    shutil.copy(publication.source / "pkg.zip", zipped / "pkg.zip")
    with zipfile.ZipFile(zipped / "boe-banking-taxonomy-dpm.zip", "w") as bundle:
        for path in publication.source.glob("*.xlsx"):
            bundle.write(path, f"nested/{path.name}")

    # Act
    files = find_bank_files(zipped)

    # Assert
    assert files.dictionary.parent.name == "boe-banking-taxonomy-dpm"
    assert len(files.annotated) == 1 and len(files.workbooks) == 1


def test_a_folder_without_a_dictionary_is_not_a_publication(publication: Publication) -> None:
    next(publication.source.glob("*DPM dictionary*")).unlink()

    with pytest.raises(BankFilesError, match="exactly one DPM dictionary"):
        find_bank_files(publication.source)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def test_a_release_is_built_into_packs_and_rule_books(publication: Publication) -> None:
    # Act
    build = build_release(VERSION, find_bank_files(publication.source), publication.root)

    # Assert
    (module,) = build.modules
    assert (module.module, module.key, module.packaged, module.reason) == (
        builders.MODULE,
        KEY,
        True,
        None,
    )
    assert build.rulebooks == (f"demo-{VERSION}.json",)
    pack = load_pack(publication.root / release_build.PACKS_SUBDIR / KEY)
    assert pack.info.version == VERSION
    assert pack.info.valid_from == date(2026, 1, 1), "the date the entry point names"


def test_a_releases_json_date_overrides_the_entry_points(publication: Publication) -> None:
    build_release(
        VERSION,
        find_bank_files(publication.source),
        publication.root,
        applies_from={builders.MODULE: date(2027, 1, 1)},
    )

    pack = load_pack(publication.root / release_build.PACKS_SUBDIR / KEY)
    assert pack.info.valid_from == date(2027, 1, 1)


def test_a_module_with_no_sample_to_check_it_against_is_not_packaged(
    publication: Publication,
) -> None:
    (publication.source / SAMPLE_NAME).unlink()

    build = build_release(VERSION, find_bank_files(publication.source), publication.root)

    (refused,) = build.refused
    assert refused.reason == "no sample instance to check it against"
    assert not (publication.root / release_build.PACKS_SUBDIR / KEY).exists()


def test_a_module_whose_sample_has_facts_the_pack_lacks_is_not_packaged(
    publication: Publication, tmp_path: Path
) -> None:
    # Arrange — the sample's fact renamed to a metric the module does not have.
    sample = publication.source / SAMPLE_NAME
    text = sample.read_text(encoding="utf-8")
    metric = text.split("<eba_met:", 1)[1].split(" ", 1)[0]
    sample.write_text(text.replace(f"eba_met:{metric}", "eba_met:zz999"), encoding="utf-8")

    # Act
    build = build_release(VERSION, find_bank_files(publication.source), publication.root)

    # Assert
    (refused,) = build.refused
    assert refused.reason is not None and "no data point of the compiled pack" in refused.reason


def test_a_release_not_listed_in_releases_json_is_not_built(publication: Publication) -> None:
    with pytest.raises(ValueError, match="not listed"):
        build_release("1.2.3", find_bank_files(publication.source), publication.root)


def test_a_release_no_longer_listed_is_removed_and_recorded_as_retired(
    publication: Publication,
) -> None:
    # Arrange — an older release on disk that releases.json no longer lists.
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)
    _relabel(publication.root, VERSION, "9.0.0")
    _write_releases(publication.root, [VERSION])

    # Act
    build = build_release(VERSION, files, publication.root)

    # Assert
    assert build.retired == ("9.0.0",)
    assert not list((publication.root / release_build.PACKS_SUBDIR).glob("*-9.0.0"))
    retired = json.loads((publication.root / "retired.json").read_text())["releases"]
    assert retired == [
        {
            "version": "9.0.0",
            "last_shipped_in": __version__,
            "entry_points": [builders.ENTRY_POINT],
        }
    ]


def test_a_rebuild_keeps_the_releases_deny_list_and_retirement_removes_it(
    publication: Publication,
) -> None:
    """The deny list is the Bank's separate, monthly publication: a rebuild cannot remake it."""
    # Arrange — 9.0.0 on disk, no longer listed; both releases with a deny list.
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)
    _relabel(publication.root, VERSION, "9.0.0")
    _write_releases(publication.root, [VERSION])
    deny = publication.root / release_build.DENY_SUBDIR
    deny.mkdir(parents=True)
    for version in (VERSION, "9.0.0"):
        (deny / f"{version}.json").write_text("{}", encoding="utf-8")

    # Act
    build_release(VERSION, files, publication.root)

    # Assert
    assert sorted(path.name for path in deny.iterdir()) == [f"{VERSION}.json"]


# ---------------------------------------------------------------------------
# End dates
# ---------------------------------------------------------------------------


def test_an_older_pack_ends_the_day_before_a_newer_entry_point_applies(
    publication: Publication,
) -> None:
    # Arrange — 9.0.0 and 9.9.9 with different entry points; 9.9.9 from 2027-01-01.
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)
    _relabel(publication.root, VERSION, "9.0.0", entry_point=builders.ENTRY_POINT + "?old")
    _write_releases(publication.root, ["9.0.0", VERSION])
    build_release(
        VERSION, files, publication.root, applies_from={builders.MODULE: date(2027, 1, 1)}
    )

    # Act
    older = load_pack(publication.root / release_build.PACKS_SUBDIR / "demo01-9.0.0")

    # Assert
    assert older.info.valid_to == date(2026, 12, 31)


def test_a_module_a_newer_release_leaves_unchanged_stays_open(publication: Publication) -> None:
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)
    _relabel(publication.root, VERSION, "9.0.0")
    _write_releases(publication.root, ["9.0.0", VERSION])

    changed = reconcile_end_dates(publication.root / release_build.PACKS_SUBDIR, ["9.0.0", VERSION])

    assert changed == ()
    assert (
        load_pack(publication.root / release_build.PACKS_SUBDIR / "demo01-9.0.0").info.valid_to
        is None
    )


# ---------------------------------------------------------------------------
# Checking and measuring
# ---------------------------------------------------------------------------


def test_a_packaged_release_rebuilt_from_its_files_is_identical(publication: Publication) -> None:
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)

    assert check_release(VERSION, files, publication.root) == []


def test_a_packaged_file_that_differs_from_what_the_files_yield_is_reported(
    publication: Publication,
) -> None:
    # Arrange
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)
    rulebook = publication.root / release_build.RULEBOOKS_SUBDIR / f"demo-{VERSION}.json"
    rulebook.write_text(rulebook.read_text().replace('"rules"', '"rules" ', 1))

    # Act / Assert
    assert check_release(VERSION, files, publication.root) == [
        f"differs: boe/data/demo-{VERSION}.json"
    ]


def test_a_release_is_measured_from_its_packaged_data(publication: Publication) -> None:
    # Arrange
    files = find_bank_files(publication.source)
    build_release(VERSION, files, publication.root)

    # Act
    measured = measure_release(VERSION, publication.root, samples=files.samples)

    # Assert
    assert measured["version"] == VERSION
    assert measured["rulebooks"][f"demo-{VERSION}.json"]["enforced"] == {builders.MODULE: 1}
    assert measured["packs"][builders.MODULE]["applies_from"] == "2026-01-01"
    assert measured["samples"][builders.MODULE]["facts"] == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validation_workbook(path: Path) -> None:
    """One enforced rule for DEMO01, in the columns the importer requires."""
    header = [*REQUIRED_COLUMNS, "T1"]
    values = {
        "Rule code": "v0001_m",
        "Framework version code": "demo",
        "Expression": "{t: T01.00.01.01, r: 0010, c: 0010} >= 0",
        "Include in XBRL": "yes",
        "Deactivated": "no",
        "Always execute": "no",
        "Severity and modules": f"ERROR - {builders.MODULE}|",
        "T1": builders.CLOSED_TABLE,
    }
    book = openpyxl.Workbook()
    book.active.title = "Note"
    sheet = book.create_sheet("demo")
    sheet.append(header)
    sheet.append([values.get(name) for name in header])
    book.save(path)


def _sample(annotated: Path, dictionary: Path, package: Path, path: Path, scratch: Path) -> None:
    """A one-fact instance written from the compiled pack, as the Bank's sample would be."""
    compiled = compile_pack(annotated, dictionary, package, module=builders.MODULE)
    write_pack(compiled, scratch, valid_from=date(2026, 1, 1))
    pack = load_pack(scratch)
    cell = pack.cells.filter(pl.col("table") == builders.CLOSED_TABLE).row(0, named=True)
    facts = pl.DataFrame(
        [
            {
                "table": cell["table"],
                "sheet": cell["sheet"],
                "row": cell["row"],
                "column": cell["column"],
                "value": 1.0,
            }
        ]
    )
    header = ReturnHeader(VALID_LEI, date(2026, 1, 31), builders.MODULE)
    path.write_bytes(write_instance(CanonicalReturn.from_frame(header, facts), pack).content)


def _write_releases(root: Path, versions: list[str]) -> None:
    payload = {"format": 1, "releases": [{"version": version} for version in versions]}
    (root / "releases.json").write_text(json.dumps(payload))


def _relabel(root: Path, version: str, as_version: str, *, entry_point: str | None = None) -> None:
    """Copy release ``version``'s data as release ``as_version``."""
    packs, books = root / release_build.PACKS_SUBDIR, root / release_build.RULEBOOKS_SUBDIR
    target = packs / f"demo01-{as_version}"
    shutil.copytree(packs / f"demo01-{version}", target)
    payload = json.loads((target / "pack.json").read_text())
    payload["info"]["version"] = as_version
    if entry_point is not None:
        payload["info"]["entry_point"] = entry_point
    (target / "pack.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    rulebook = json.loads((books / f"demo-{version}.json").read_text())
    rulebook["source"]["taxonomy"] = as_version
    (books / f"demo-{as_version}.json").write_text(json.dumps(rulebook))


def test_the_files_dataclass_finds_a_sample_whatever_the_modules_underscores() -> None:
    files = BankFiles(
        taxonomy_package=Path("p.zip"),
        dictionary=Path("d.xlsx"),
        annotated=(),
        workbooks=(),
        samples={"PRAGAAP": Path("s.xbrl")},
    )

    assert files.sample_for("PRA_GAAP") == Path("s.xbrl")
