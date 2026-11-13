"""
The reader and writer against the Bank of England's own PRA001 sample instance.

Opt-in, never in CI: the sample is the publisher's file and is not
redistributed. SKIPPED unless ``RWA_FILER_BOE_DIR`` names a directory holding
it (``*_PRA001_*.xbrl``, searched recursively):

    RWA_FILER_BOE_DIR=/path/to/downloads \
        uv run pytest packages/rwa-filer/tests/xbrl/test_boe_sample.py -q

This is the strongest evidence short of the regulator's own gateway that the
packaged pack, the reader and the writer agree with the Bank's taxonomy. The
sample holds one fact for every data point of the module — 61,428 of them,
across all 104 tables — in a file this package did not write. If the pack had a
data point wrong, a fact would fail to match (``XBR001``); if the writer put a
member in the wrong place, the rewritten file would not hold the same facts.

The counts below were measured on the v4.1.1 sample (taxonomy package dated
2026-08-17). A new publication needs a new measurement, not an edit.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer.model import CanonicalReturn
from rwa_filer.validate.structure import FINDING_HEADER_INVALID, check_structure
from rwa_filer.xbrl.reader import InstanceReading, _content, _distinct_facts, _parse, read_instance
from rwa_filer.xbrl.writer import write_instance

BOE_DIR = os.environ.get("RWA_FILER_BOE_DIR")

pytestmark = pytest.mark.skipif(
    not BOE_DIR, reason="set RWA_FILER_BOE_DIR to a directory holding the BoE PRA001 sample"
)

SAMPLE_FACTS = 61_428
SAMPLE_TABLES = 104
SAMPLE_INDICATORS = 83


@pytest.fixture(scope="module")
def sample_path() -> Path:
    found = sorted(Path(BOE_DIR or "").rglob("*_PRA001_*.xbrl"))
    if not found:
        pytest.skip("no *_PRA001_*.xbrl sample instance under RWA_FILER_BOE_DIR")
    return found[0]


@pytest.fixture(scope="module")
def reading(sample_path: Path) -> InstanceReading:
    return read_instance(sample_path)


def test_every_fact_of_the_sample_is_a_data_point_of_the_packaged_pack(
    reading: InstanceReading,
) -> None:
    # Assert — nothing unmatched, nothing orphaned, no filing-rule breach.
    assert reading.findings == ()
    assert reading.facts == SAMPLE_FACTS
    assert len(reading.ret.tables) == SAMPLE_TABLES
    assert len(reading.ret.indicators or {}) == SAMPLE_INDICATORS


def test_the_sample_is_structurally_clean_apart_from_its_placeholder_header(
    reading: InstanceReading,
) -> None:
    """The sample's LEI is a placeholder and its date predates the taxonomy's start."""
    # Act
    findings = check_structure(reading.ret, reading.pack)

    # Assert
    assert {finding.code for finding in findings} == {FINDING_HEADER_INVALID}


def test_rewriting_the_sample_gives_the_same_facts(
    sample_path: Path, reading: InstanceReading
) -> None:
    """Every metric, dimension member, value and decimals — across all 104 tables."""
    # Arrange — a header the structure checks accept; the facts are untouched.
    header = replace(
        reading.ret.header, entity_identifier=VALID_LEI, reference_date=date(2027, 3, 31)
    )
    ret = CanonicalReturn(header, reading.ret.facts, reading.ret.indicators)

    def fact_set(content: bytes) -> set[tuple[object, ...]]:
        facts, _findings = _distinct_facts(_parse(content), reading.pack)
        return {(f.metric, f.members, f.value, f.text, f.decimals) for f in facts}

    # Act
    instance = write_instance(ret, reading.pack)

    # Assert
    assert instance.facts == SAMPLE_FACTS
    assert len(instance.filing_indicators) == SAMPLE_INDICATORS
    assert fact_set(instance.content) == fact_set(_content(sample_path))
