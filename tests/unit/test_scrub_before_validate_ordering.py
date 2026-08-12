"""
The loader nulls non-finite inputs BEFORE validating column domains.

Pipeline position:
    parquet feed -> ParquetLoader (``_scrub_and_validate``) ->
    PipelineOrchestrator.run_with_data (same gate again, de-duplicated)

The ordering is load-bearing for two separate reasons, and this module pins
both. Neither was catchable before: the pre-existing double-report guard
(``tests/unit/test_pipeline_validation.py``) builds a bundle with no
non-finite values, so the transformation between the loader's pass and the
pipeline's is the identity and the two passes trivially agree.

**1. NaN is a non-finite input, not a domain violation.** Polars evaluates
``NaN >= 0`` as True, so a NaN PD fails only the upper bound of ``[0, 1]``
and the domain gate reports it as IRB001 "outside its regulatory domain".
DQ011 is the truthful code. Scrubbing first nulls it, and null is never a
domain violation.

**2. The pipeline's de-duplication is only sound if both passes see the same
data.** ``engine/pipeline.py::_new_input_domain_errors`` runs the same gate
at the pipeline entry so the in-memory ``run_with_data`` path is covered,
and subtracts the errors already on the bundle. Domain errors carry an
aggregate row count in their message, so scrubbing a row **changes the
identity** of every surviving error rather than removing it — the set
difference then matches nothing and the same row is reported twice with two
contradictory counts. Measured on the pre-fix tree, one ``ratings.pd``
column holding ``[nan, 1.5]``::

    PASS 1 (loader, pre-scrub)
       R_NAN | 'pd' outside its regulatory domain [0, 1] - 2 row(s) (value=nan)
       R_BAD | 'pd' outside its regulatory domain [0, 1] - 2 row(s) (value=1.5)
    PASS 2 (pipeline entry, post-scrub)
       R_BAD | 'pd' outside its regulatory domain [0, 1] - 1 row(s) (value=1.5)

    result.errors IRB001 count = 3, R_BAD named twice claiming 2 and 1.

A firm triaging that cannot tell which count is the truth.

References:
- CRR Art. 160/163: PD is a probability — the domain is [0, 1]
- docs/plans/test-space-correctness-proposal.md (Phase 0)
- docs/development/escape-log.md — DQ011's own entry
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.errors import (
    ERROR_NON_FINITE_RAW_INPUT,
    ERROR_PD_OUT_OF_RANGE,
)
from rwa_calc.contracts.validation import scrub_non_finite_values, validate_bundle_values
from rwa_calc.engine.loader import ParquetLoader
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_calc.contracts.bundles import RawDataBundle

NAN_REF = "R_NAN"
BAD_REF = "R_BAD"


@pytest.fixture
def mixed_ratings_bundle() -> RawDataBundle:
    """One ``pd`` column carrying both a NaN and a genuine domain violation."""
    ratings = pl.DataFrame(
        {
            "rating_reference": [NAN_REF, BAD_REF],
            "counterparty_reference": ["C1", "C1"],
            "pd": [float("nan"), 1.5],
        }
    )
    return make_raw_bundle(ratings=ratings)


def _pd_domain_errors(bundle: RawDataBundle) -> list:
    """IRB001 errors the domain gate raises against ``pd`` on *bundle*."""
    return [
        e
        for e in validate_bundle_values(bundle)
        if e.code == ERROR_PD_OUT_OF_RANGE and e.field_name == "pd"
    ]


def test_nan_is_not_reported_as_a_domain_violation(mixed_ratings_bundle: RawDataBundle) -> None:
    """After scrubbing, only the genuine out-of-domain row carries IRB001."""
    # Arrange
    scrubbed = scrub_non_finite_values(mixed_ratings_bundle)

    # Act
    refs = {e.exposure_reference for e in _pd_domain_errors(scrubbed)}

    # Assert — the NaN row is DQ011's business, not IRB001's.
    assert refs == {BAD_REF}, (
        f"expected only {BAD_REF} to carry a PD domain violation after scrubbing, got {refs}. "
        "Polars evaluates NaN >= 0 as True, so an unscrubbed NaN fails only the upper bound "
        "and is misreported as out-of-domain when DQ011 is the truthful code."
    )


def test_the_nan_row_is_still_reported_somewhere(mixed_ratings_bundle: RawDataBundle) -> None:
    """Scrubbing must not silence the NaN — it re-codes it, it does not drop it."""
    # Act
    scrubbed = scrub_non_finite_values(mixed_ratings_bundle)

    # Assert — the whole point of the ordering is a truthful code, not a quieter one.
    dq011 = [e for e in scrubbed.errors if e.code == ERROR_NON_FINITE_RAW_INPUT]
    assert dq011, (
        "the NaN pd was nulled but raised no DQ011. Scrubbing that reports nothing is "
        "exactly the silent-absence failure the input contract exists to close."
    )


def test_scrubbing_first_makes_the_two_gate_passes_agree(
    mixed_ratings_bundle: RawDataBundle,
) -> None:
    """The de-dup key is the whole error, so both passes must produce identical sets.

    ``_new_input_domain_errors`` subtracts ``set(bundle.errors)`` from a fresh
    run of the same gate. That is exact-match set arithmetic over a frozen
    dataclass whose message embeds an aggregate count — so it is sound only
    when the data is unchanged between the passes. Scrubbing in the loader,
    before validating, is what guarantees that.
    """
    # Arrange — the loader's pass: scrub, then validate.
    scrubbed = scrub_non_finite_values(mixed_ratings_bundle)
    loader_pass = _pd_domain_errors(scrubbed)

    # Act — the pipeline's pass: scrub again (a no-op), then validate again.
    rescrubbed = scrub_non_finite_values(scrubbed)
    pipeline_pass = _pd_domain_errors(rescrubbed)

    # Assert — identical sets, so the set difference is empty and nothing double-reports.
    assert set(pipeline_pass) == set(loader_pass), (
        "the two gate passes disagree, so the pipeline's set-difference de-dup will "
        "re-report rows the loader already reported. Messages:\n"
        f"  loader:   {[e.message for e in loader_pass]}\n"
        f"  pipeline: {[e.message for e in pipeline_pass]}"
    )


def test_the_loader_itself_validates_after_scrubbing(tmp_path: Path) -> None:
    """The ordering must hold in ``engine/loader.py``, not merely be achievable.

    The three tests above call ``scrub_non_finite_values`` themselves, so they
    pin the *semantics* of the ordering and would pass whatever order the
    loader used. This one drives ``ParquetLoader.load()`` and asserts on what
    the loader actually emits — it is the test that fails if the scrub is moved
    back after the validation. Measured against the pre-fix ordering::

        loader-path IRB001 count = 2
           RT_ACME_PD | 'pd' outside its regulatory domain [0, 1] - 2 row(s) (value=1.5)
           RT_NAN     | 'pd' outside its regulatory domain [0, 1] - 2 row(s) (value=nan)
    """
    # Arrange — a real parquet feed carrying a NaN pd alongside a percent-scale one.
    from tests.acceptance.test_percent_scale_pd_feed import PERCENT_SCALE_PD, _write_feed

    source = _write_feed(tmp_path, PERCENT_SCALE_PD)
    ratings = pl.read_parquet(source.ratings_file)
    with_nan = pl.concat(
        [
            ratings,
            ratings.with_columns(
                pl.lit("RT_NAN").alias("rating_reference"),
                pl.lit(float("nan")).alias("pd"),
            ),
        ]
    )
    with_nan.write_parquet(source.ratings_file)

    # Act
    bundle = ParquetLoader(tmp_path, source).load()

    # Assert — the NaN row must not appear as a domain violation.
    domain_refs = {e.exposure_reference for e in bundle.errors if e.code == ERROR_PD_OUT_OF_RANGE}
    assert "RT_NAN" not in domain_refs, (
        "the loader reported a NaN pd as an out-of-domain value. It validates before "
        "scrubbing, so Polars' NaN >= 0 == True leaks a non-finite input into IRB001. "
        f"IRB001 named: {sorted(domain_refs)}"
    )
    assert any(e.code == ERROR_NON_FINITE_RAW_INPUT for e in bundle.errors), (
        "the NaN pd raised no DQ011 on the loader path — it was neither re-coded nor reported."
    )


def test_no_row_is_named_twice_by_the_pd_domain_gate(
    mixed_ratings_bundle: RawDataBundle,
) -> None:
    """A row named twice with two counts is untriageable — pin the shape directly."""
    # Arrange
    scrubbed = scrub_non_finite_values(mixed_ratings_bundle)

    # Act — merge exactly as the pipeline does.
    already = set(scrubbed.errors)
    fresh = [e for e in validate_bundle_values(scrubbed) if e not in already]
    merged = list(scrubbed.errors) + fresh
    named = [
        e.exposure_reference
        for e in merged
        if e.code == ERROR_PD_OUT_OF_RANGE and e.exposure_reference is not None
    ]

    # Assert
    assert len(named) == len(set(named)), (
        f"a row is named more than once by the PD domain gate: {named}. "
        "Each naming carries its own aggregate count, so a firm cannot tell which is true."
    )
