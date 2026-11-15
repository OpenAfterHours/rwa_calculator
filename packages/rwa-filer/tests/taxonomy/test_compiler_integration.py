"""
The compiler against the Bank of England's real files — opt-in, never in CI.

Pipeline position:
    BoE annotated templates + DPM dictionary + taxonomy package (v4.1.1)
        -> compiler.compile_pack(module="PRA001") -> compiled pack
        -> every fact of the BoE's own PRA001 sample instance maps to a cell

The publisher's files are not redistributed, so this test is SKIPPED unless
``RWA_FILER_BOE_DIR`` names a directory that holds the downloads. The directory
is searched recursively and the first match in sorted order wins:

    *Annotated Templates*Banking Reporting.xlsx   the annotated workbook
    *DPM dictionary*.xlsx                         the dictionary workbook
    **/META-INF/taxonomyPackage.xml               an extracted taxonomy package that
        defines mod/pra001.xsd (the manifest's grandparent is the package), or else
    *.zip holding both of those                   the zipped taxonomy package
    *_PRA001_*.xbrl                               the sample instance (optional)

Run it with, for example:

    RWA_FILER_BOE_DIR=/path/to/downloads \
        uv run pytest packages/rwa-filer/tests/taxonomy/test_compiler_integration.py -q

The headline counts are the release's measurements (``tests/releases/<version>/``,
which ``scripts/build_filer_release.py`` writes from the same files); which
release the downloads are, the compiled pack says. The finer findings below
them — which tables gain linkbase-only cells, how many sample facts share a
data point — were investigated on 4.1.1 alone, and are checked only against
the 4.1.1 downloads: a new publication needs a new investigation, not an edit.
"""

from __future__ import annotations

import collections
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest

import taxonomy_builders as builders
from release_measurements import measurements
from rwa_filer.taxonomy import compiler

BOE_DIR = os.environ.get("RWA_FILER_BOE_DIR")
#: The release the finer findings below were investigated on.
INVESTIGATED_ON = "4.1.1"

pytestmark = pytest.mark.skipif(
    not BOE_DIR, reason="set RWA_FILER_BOE_DIR to a directory holding a release's BoE downloads"
)


def _first(root: Path, pattern: str) -> Path | None:
    return next(iter(sorted(root.rglob(pattern))), None)


def _taxonomy_package(root: Path) -> Path | None:
    """The package that defines PRA001: an extracted tree if there is one, else a zip."""
    for manifest in sorted(root.rglob("META-INF/taxonomyPackage.xml")):
        package = manifest.parent.parent
        if next(package.rglob("mod/pra001.xsd"), None) is not None:
            return package
    for archive in sorted(root.rglob("*.zip")):
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
        if any(n.endswith("META-INF/taxonomyPackage.xml") for n in names) and any(
            n.endswith("/mod/pra001.xsd") for n in names
        ):
            return archive
    return None


@pytest.fixture(scope="module")
def pack() -> dict[str, Any]:
    root = Path(BOE_DIR or "")
    annotated = _first(root, "*Annotated Templates*Banking Reporting.xlsx")
    dictionary = _first(root, "*DPM dictionary*.xlsx")
    taxonomy = _taxonomy_package(root)
    if not (annotated and dictionary and taxonomy):
        # Other opt-in tests share the variable and need only the sample
        # instances, so a directory without the compiler's inputs is a skip.
        pytest.skip(
            f"RWA_FILER_BOE_DIR={root} does not hold the annotated workbook, the dictionary "
            f"workbook and the taxonomy package (found {annotated}, {dictionary}, {taxonomy})"
        )
    return compiler.compile_pack(annotated, dictionary, taxonomy, module="PRA001")


def test_pra001_compiles_to_the_measured_tables_cells_and_data_points(pack: dict[str, Any]) -> None:
    # Act
    tables = pack["tables"]
    sources = collections.Counter(cell[4] for table in tables.values() for cell in table["cells"])
    indicators = {table["filing_indicator"] for table in tables.values()}

    measured = _measured(pack)

    # Assert
    assert len(tables) == measured["tables"]
    assert len(indicators) == measured["filing_indicators"]
    assert None not in indicators, "every table has a filing indicator from the taxonomy"
    assert sources == {
        "workbook": measured["cells"] - measured["linkbase_cells"],
        "linkbase": measured["linkbase_cells"],
    }, "white in the workbook and accepted by the hypercubes, plus greyed but accepted"
    assert len(pack["datapoints"]) == measured["datapoints"]
    assert pack["info"]["entry_point"] == measured["entry_point"]


def test_pra001_linkbase_only_cells_are_the_known_two_tables(pack: dict[str, Any]) -> None:
    _investigated(pack)

    # Act
    promoted = collections.Counter(
        code
        for code, table in pack["tables"].items()
        for cell in table["cells"]
        if cell[4] == "linkbase"
    )
    dropped = [
        n for n in pack["info"]["irregularities"] if "rejected by the definition linkbase" in n
    ]

    # Assert
    assert promoted == {"OF08.01.01.01": 40, "OF02.00.01.01": 2}
    assert dropped == [], "no white workbook cell is rejected by the v4.1.1 hypercubes"


def test_every_fact_of_the_boe_sample_instance_maps_to_a_cell(pack: dict[str, Any]) -> None:
    # Arrange
    instance = _first(Path(BOE_DIR or ""), "*_PRA001_*.xbrl")
    if instance is None:
        pytest.skip("no *_PRA001_*.xbrl sample instance under RWA_FILER_BOE_DIR")

    # Act
    counts = builders.map_instance(pack, instance)
    measured = _measured(pack)

    # Assert — every sample fact maps, and every pack cell is hit.
    assert counts["facts"] == measurements(pack["info"]["version"])["samples"]["PRA001"]["facts"]
    assert counts["unmapped"] == 0, "every sample fact maps to at least one cell"
    assert counts["cells_hit"] == measured["cells"], "every pack cell is hit by a sample fact"
    if pack["info"]["version"] == INVESTIGATED_ON:
        assert counts["one_cell"] == 61_245, "61,245 facts map to exactly one cell"
        assert counts["many_cells"] == 183, "183 facts are a data point shared by more cells"


def _measured(pack: dict[str, Any]) -> dict[str, Any]:
    """The compiled PRA001 pack's release's measurements of its PRA001 pack."""
    return measurements(pack["info"]["version"])["packs"]["PRA001"]


def _investigated(pack: dict[str, Any]) -> None:
    """Skip a finer finding on downloads of a release it was not investigated on."""
    if pack["info"]["version"] != INVESTIGATED_ON:
        version = pack["info"]["version"]
        pytest.skip(f"investigated on {INVESTIGATED_ON}; these downloads are {version}")
