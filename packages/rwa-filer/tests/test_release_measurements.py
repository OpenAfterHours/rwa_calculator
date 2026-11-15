"""
Each shipped release's packaged data, held to its measurement file.

A two-way gate on everything ``measure_release`` counts: a changed pack or rule
book that is not re-measured fails here, and so does a measurement file that
was edited by hand. Re-measure with::

    uv run python scripts/build_filer_release.py <version> --measure-only

The sample counts are measured on the Bank's sample instances, which are not
redistributed; they are checked by the opt-in ``xbrl/test_boe_sample.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import rwa_filer
from release_measurements import measurements, measurements_path
from rwa_filer.release import shipped_releases
from rwa_filer.release_build import measure_release

PACKAGE_ROOT = Path(rwa_filer.__file__).parent


@pytest.mark.parametrize("version", shipped_releases())
def test_every_shipped_release_has_a_measurement_file(version: str) -> None:
    assert measurements_path(version).is_file(), (
        f"no measurement file for {version}: run scripts/build_filer_release.py {version} "
        "--measure-only"
    )


@pytest.mark.parametrize("version", shipped_releases())
def test_the_packaged_data_is_what_its_measurement_file_says(version: str) -> None:
    # Act
    measured = measure_release(version, PACKAGE_ROOT)
    recorded = measurements(version)

    # Assert — everything but the samples, which need the Bank's files.
    assert {key: value for key, value in measured.items() if key != "samples"} == {
        key: value for key, value in recorded.items() if key != "samples"
    }
    assert set(recorded["samples"]) <= set(recorded["packs"]), "a sample for an unpackaged module"
