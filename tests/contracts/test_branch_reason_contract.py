"""
The branch-reason contract: declared, carried, and never silent.

``docs/plans/test-space-correctness-proposal.md`` Phase 3 asks for three things
that can each fail invisibly:

1. the ``*_branch_reason`` columns are DECLARED at the sealed edges, or the
   aggregator strips them as scratch and the census reads an empty frame;
2. the registry, the edge dtypes and the producing engine agree on the
   vocabulary, or a limb becomes an unstorable value and lands as null;
3. **no row reaches ``UNKNOWN_FALLBACK`` without an accompanying error** — the
   invariant the whole phase exists to establish.

The third is proved END TO END against a portfolio built to trip it, not
against a synthetic bundle. A gate nobody has seen fail is not a gate, and the
shape that trips this one (P1.333: a non-EU institution with no
``cp_local_currency``) is a live anti-conservative defect, so the test doubles
as its regression pin.

References:
- src/rwa_calc/domain/branch_reasons.py — the registry
- src/rwa_calc/contracts/validation.py::validate_branch_reasons — the invariant
- IMPLEMENTATION_PLAN.md P1.333 — the defect the SA case reproduces
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.properties.portfolios import ExposureSpec, build_bundle, config_for

from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
    IRB_BRANCH_EDGE,
    SA_BRANCH_EDGE,
)
from rwa_calc.contracts.errors import ERROR_UNKNOWN_BRANCH_FALLBACK
from rwa_calc.domain.branch_reasons import (
    BRANCH_REASON_VOCABULARIES,
    UNKNOWN_FALLBACK,
    reason_dtype,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator


class TestEdgeDeclaration:
    """A reason column the edge does not declare is stripped as scratch."""

    @pytest.mark.parametrize(
        "edge", [SA_BRANCH_EDGE, IRB_BRANCH_EDGE, AGGREGATOR_EXIT_EDGE], ids=lambda e: e.name
    )
    def test_every_registered_reason_column_is_declared_at_the_calc_edges(self, edge) -> None:
        """``conform`` strips undeclared columns, so an omission is silent.

        Arrange: the registry and one sealed edge.
        Act:     read the edge's declared column names.
        Assert:  every registered reason column is among them.
        """
        missing = sorted(set(BRANCH_REASON_VOCABULARIES) - set(edge.columns))
        assert not missing, (
            f"edge '{edge.name}' does not declare {missing}. EdgeContract.conform "
            "strips undeclared columns, so the reason would vanish between the "
            "producer and the census with nothing raised."
        )

    @pytest.mark.parametrize("column", sorted(BRANCH_REASON_VOCABULARIES))
    def test_edge_dtype_matches_the_registered_vocabulary(self, column: str) -> None:
        """A drifted category list makes a valid limb unstorable — i.e. null.

        Arrange: the registry entry and the aggregator-exit declaration.
        Act:     build the dtype from the vocabulary.
        Assert:  it equals the declared dtype exactly, categories and order.
        """
        declared = AGGREGATOR_EXIT_EDGE.columns[column].dtype
        expected = reason_dtype(BRANCH_REASON_VOCABULARIES[column])
        assert declared == expected
        assert declared.categories.to_list() == expected.categories.to_list()

    @pytest.mark.parametrize("column", sorted(BRANCH_REASON_VOCABULARIES))
    def test_reason_columns_are_optional_and_never_null_filled(self, column: str) -> None:
        """Null means "this decision was not taken", and must survive as null.

        An SA row takes no IRB LGD decision. Filling that null with a named
        limb would put rows into the census that never faced the choice, which
        is the ``.claude/LESSONS.md`` "never fill nulls" rule in its
        measurement-corrupting form.

        Arrange: the aggregator-exit declaration.
        Act:     read its flags.
        Assert:  optional, injected, not null-filled, and null_meaning written.
        """
        spec = AGGREGATOR_EXIT_EDGE.columns[column]
        assert not spec.required, f"{column} is produced by one branch only"
        assert spec.inject, f"{column} must be injected as typed null where absent"
        assert not spec.fill_null_default, f"{column} must never be null-filled"
        assert spec.null_meaning, f"{column} must document what its null means"


class TestUnknownFallbackNeverStandsAlone:
    """The Phase 3 invariant, proved through the full pipeline."""

    def test_a_row_on_unknown_fallback_carries_a_br001_error(self) -> None:
        """The P1.333 shape: non-EU institution, unrated, no local currency.

        ``engine/eu_sovereign.py`` maps a non-EU country to null, so
        ``is_domestic_currency`` is null, ``~is_fx`` is null, and the Art.
        121(6) floor's ``pl.when`` silently takes ``otherwise``. Before Phase 3
        that row carried a confident risk weight and NO signal of any kind.

        **Runs under Basel 3.1, not CRR (changed by P1.334).** UK CRR Art. 121
        has four paragraphs and no floor limb, so the rule is now gated to B31
        and a CRR row abstains on ``REGIME_NOT_APPLICABLE`` — which would empty
        this assertion and trip its own warning. That is the instrument
        correctly following the rule to the only regime that has it, not the
        P1.333 defect being fixed: P1.333 remains open and is a Basel 3.1
        shortfall, which is exactly where this shape now sits.

        Arrange: a one-exposure portfolio in exactly that shape.
        Act:     run the full pipeline.
        Assert:  the row reads UNKNOWN_FALLBACK and a BR001 names it.
        """
        # Arrange
        portfolio = (
            ExposureSpec(
                entity_type="institution", external_cqs=None, country_code="US", drawn=1_000_000.0
            ),
        )

        # Act
        result = PipelineOrchestrator().run_with_data(build_bundle(portfolio), config_for("B31"))
        frame = result.results.select(
            "exposure_reference", "sa_risk_weight_branch_reason"
        ).collect()
        unknown = frame.filter(
            pl.col("sa_risk_weight_branch_reason").cast(pl.String) == UNKNOWN_FALLBACK
        )
        br001 = [e for e in result.errors if e.code == ERROR_UNKNOWN_BRANCH_FALLBACK]

        # Assert
        assert unknown.height == 1, (
            "the P1.333 shape must land on UNKNOWN_FALLBACK — if this is empty the "
            "instrument has stopped detecting the indeterminate domesticity test, "
            "not that the defect is fixed (check the risk weight moved too)"
        )
        assert br001, "a row on UNKNOWN_FALLBACK must be named by a BR001 error"
        named = {e.exposure_reference for e in br001}
        assert set(unknown["exposure_reference"]) <= named

    def test_a_clean_portfolio_raises_no_br001(self) -> None:
        """The gate must be quiet on data it can justify, or it is noise.

        A gate that fires on everything gets switched off. This is the
        anti-vacuity leg: it fails if UNKNOWN_FALLBACK ever becomes the
        engine's default answer.

        Arrange: an ordinary rated GB corporate.
        Act:     run the full pipeline.
        Assert:  no BR001, and no row on UNKNOWN_FALLBACK.
        """
        # Arrange
        portfolio = (ExposureSpec(entity_type="corporate", external_cqs=3, country_code="GB"),)

        # Act
        result = PipelineOrchestrator().run_with_data(build_bundle(portfolio), config_for("CRR"))
        present = [
            c for c in BRANCH_REASON_VOCABULARIES if c in result.results.collect_schema().names()
        ]
        frame = result.results.select(present).collect()

        # Assert
        assert not [e for e in result.errors if e.code == ERROR_UNKNOWN_BRANCH_FALLBACK]
        for column in present:
            unknown = int((frame[column].cast(pl.String) == UNKNOWN_FALLBACK).sum())
            assert unknown == 0, f"{column} reported {unknown} unjustified rows on clean data"
