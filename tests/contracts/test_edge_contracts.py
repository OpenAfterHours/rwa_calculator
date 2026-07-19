"""
Contract tests for the Phase 3 producer-sealed edge machinery.

Pins the behaviour of ``contracts/edges.py``:
- ``EdgeColumn`` / ``EdgeContract`` construction rules (the Boolean-only
  null-fill conservatism gate at declaration time)
- ``EdgeContract.conform``: assert + producer-owned defaults + strip
  undeclared scratch + canonical column order; schema violations raise
- ``seal`` / ``sealed_edge_of``: branding semantics — a brand never survives
  a frame transformation (a transformed frame is no longer the sealed frame)
- Bundle ``__post_init__`` brand validation via ``SEALED_FRAME_FIELDS``

References:
- docs/plans/target-architecture-migration.md (Phase 3)
- docs/plans/engine-defensiveness-boundary-hardening.md (conservatism gate)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, CRMAdjustedBundle
from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
    AGGREGATOR_SUMMARY_EDGES,
    FLOOR_IMPACT_EDGE,
    RAW_TABLE_EDGES,
    REPORTING_SURFACE,
    SUMMARY_BY_APPROACH_EDGE,
    SUMMARY_BY_CLASS_EDGE,
    SUMMARY_BY_CLASS_METHOD_EDGE,
    SUPPORTING_FACTOR_IMPACT_EDGE,
    EdgeColumn,
    EdgeContract,
    EdgeContractViolation,
    reseal_with,
    seal,
    seal_lenient,
    sealed_edge_of,
)


def _contract(**overrides: EdgeColumn) -> EdgeContract:
    """A small but representative edge contract for tests."""
    columns: dict[str, EdgeColumn] = {
        "exposure_reference": EdgeColumn(dtype=pl.String),
        "ead": EdgeColumn(dtype=pl.Float64),
        "is_defaulted": EdgeColumn(
            dtype=pl.Boolean,
            required=False,
            default=False,
            fill_null_default=True,
        ),
        "turnover_m": EdgeColumn(
            dtype=pl.Float64,
            required=False,
            default=None,
            null_meaning="null means turnover unknown — SME factor not applied (tri-state)",
        ),
    }
    columns.update(overrides)
    return EdgeContract(name="test_edge", columns=columns)


def _conformant_frame() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2"],
            "ead": [100.0, 200.0],
            "is_defaulted": [True, None],
            "turnover_m": [None, 40.0],
        },
        schema={
            "exposure_reference": pl.String,
            "ead": pl.Float64,
            "is_defaulted": pl.Boolean,
            "turnover_m": pl.Float64,
        },
    )


class TestEdgeContractDeclarationRules:
    """The conservatism gate is enforced when the contract is DECLARED."""

    def test_fill_null_default_on_non_boolean_dtype_raises(self):
        with pytest.raises(ValueError, match="Boolean"):
            EdgeContract(
                name="bad",
                columns={
                    "ead": EdgeColumn(
                        dtype=pl.Float64,
                        required=False,
                        default=0.0,
                        fill_null_default=True,
                    )
                },
            )

    def test_fill_null_default_without_default_raises(self):
        with pytest.raises(ValueError, match="default"):
            EdgeContract(
                name="bad",
                columns={
                    "flag": EdgeColumn(
                        dtype=pl.Boolean,
                        required=False,
                        fill_null_default=True,
                    )
                },
            )

    def test_required_column_with_default_raises(self):
        # A default on a required column is dead config — the producer must
        # emit it; declaring both hides which behaviour is intended.
        with pytest.raises(ValueError, match="required"):
            EdgeContract(
                name="bad",
                columns={"ead": EdgeColumn(dtype=pl.Float64, default=0.0)},
            )


class TestConform:
    def test_missing_required_column_raises_naming_edge_and_column(self):
        contract = _contract()
        lf = _conformant_frame().drop("ead")

        with pytest.raises(EdgeContractViolation, match="test_edge") as excinfo:
            contract.conform(lf)

        assert "ead" in str(excinfo.value)

    def test_dtype_mismatch_raises_with_expected_and_actual(self):
        contract = _contract()
        lf = _conformant_frame().with_columns(pl.col("ead").cast(pl.Int64))

        with pytest.raises(EdgeContractViolation) as excinfo:
            contract.conform(lf)

        message = str(excinfo.value)
        assert "ead" in message
        assert "Float64" in message
        assert "Int64" in message

    def test_multiple_violations_reported_in_one_raise(self):
        contract = _contract()
        lf = (
            _conformant_frame()
            .drop("exposure_reference")
            .with_columns(pl.col("ead").cast(pl.Int64))
        )

        with pytest.raises(EdgeContractViolation) as excinfo:
            contract.conform(lf)

        message = str(excinfo.value)
        assert "exposure_reference" in message
        assert "ead" in message

    def test_absent_optional_column_added_with_default(self):
        contract = _contract()
        lf = _conformant_frame().drop("is_defaulted")

        out = contract.conform(lf).collect()

        assert out["is_defaulted"].to_list() == [False, False]
        assert out.schema["is_defaulted"] == pl.Boolean

    def test_absent_optional_with_null_default_added_as_typed_null(self):
        contract = _contract()
        lf = _conformant_frame().drop("turnover_m")

        out = contract.conform(lf).collect()

        assert out["turnover_m"].to_list() == [None, None]
        assert out.schema["turnover_m"] == pl.Float64

    def test_present_null_boolean_with_fill_null_default_is_filled(self):
        contract = _contract()

        out = contract.conform(_conformant_frame()).collect()

        # Row 2 had is_defaulted=None; fill_null_default=True fills it.
        assert out["is_defaulted"].to_list() == [True, False]

    def test_present_null_float_never_filled(self):
        # turnover_m row 1 is null and must stay null (tri-state semantics;
        # Float fills are anti-conservative — Risk sign-off gate).
        contract = _contract()

        out = contract.conform(_conformant_frame()).collect()

        assert out["turnover_m"].to_list() == [None, 40.0]

    def test_undeclared_scratch_column_stripped(self):
        contract = _contract()
        lf = _conformant_frame().with_columns(pl.lit(1).alias("_scratch_total"))

        out = contract.conform(lf).collect()

        assert "_scratch_total" not in out.columns

    def test_columns_emerge_in_contract_order(self):
        contract = _contract()
        lf = _conformant_frame().select("turnover_m", "is_defaulted", "ead", "exposure_reference")

        out = contract.conform(lf).collect()

        assert out.columns == ["exposure_reference", "ead", "is_defaulted", "turnover_m"]

    def test_explicit_false_boolean_never_flipped_by_fill(self):
        contract = _contract(
            committed=EdgeColumn(
                dtype=pl.Boolean, required=False, default=True, fill_null_default=True
            )
        )
        lf = _conformant_frame().with_columns(
            pl.Series("committed", [False, None], dtype=pl.Boolean)
        )

        out = contract.conform(lf).collect()

        assert out["committed"].to_list() == [False, True]


class TestSealBranding:
    def test_sealed_frame_carries_edge_brand(self):
        contract = _contract()

        sealed = seal(_conformant_frame(), contract)

        assert sealed_edge_of(sealed) == "test_edge"

    def test_unsealed_frame_has_no_brand(self):
        assert sealed_edge_of(_conformant_frame()) is None

    def test_brand_does_not_survive_transformation(self):
        # Load-bearing semantics: any transformation produces a NEW frame
        # that has not been through the seal — it must not claim the brand.
        contract = _contract()
        sealed = seal(_conformant_frame(), contract)

        transformed = sealed.with_columns(pl.lit(1).alias("extra"))

        assert sealed_edge_of(transformed) is None

    def test_seal_applies_conform_semantics(self):
        contract = _contract()
        lf = _conformant_frame().with_columns(pl.lit(1).alias("_scratch"))

        out = seal(lf, contract).collect()

        assert "_scratch" not in out.columns

    def test_seal_raises_on_violation(self):
        contract = _contract()

        with pytest.raises(EdgeContractViolation):
            seal(_conformant_frame().drop("ead"), contract)


class TestEmptyFrame:
    def test_empty_frame_is_schema_complete_and_sealed(self):
        contract = _contract()

        empty = contract.empty_frame()

        assert sealed_edge_of(empty) == "test_edge"
        collected = empty.collect()
        assert collected.height == 0
        assert collected.columns == [
            "exposure_reference",
            "ead",
            "is_defaulted",
            "turnover_m",
        ]
        assert collected.schema["ead"] == pl.Float64


class TestBundleBrandValidation:
    """SEALED_FRAME_FIELDS-registered bundle fields demand the right brand."""

    @pytest.fixture()
    def registered_crm_exposures(self, monkeypatch: pytest.MonkeyPatch):
        from rwa_calc.contracts import bundles as bundles_module

        monkeypatch.setitem(
            bundles_module.SEALED_FRAME_FIELDS,
            "CRMAdjustedBundle.exposures",
            "test_edge",
        )

    def test_correctly_branded_frame_constructs(self, registered_crm_exposures):
        sealed = seal(_conformant_frame(), _contract())

        bundle = CRMAdjustedBundle(exposures=sealed)

        assert bundle.exposures is sealed

    def test_unbranded_frame_on_registered_field_raises(self, registered_crm_exposures):
        with pytest.raises(EdgeContractViolation, match="CRMAdjustedBundle.exposures"):
            CRMAdjustedBundle(exposures=_conformant_frame())

    def test_wrong_brand_on_registered_field_raises(self, registered_crm_exposures):
        other = EdgeContract(
            name="other_edge",
            columns={"exposure_reference": EdgeColumn(dtype=pl.String)},
        )
        sealed_other = seal(pl.LazyFrame({"exposure_reference": ["E1"]}), other)

        with pytest.raises(EdgeContractViolation, match="other_edge"):
            CRMAdjustedBundle(exposures=sealed_other)

    def test_unregistered_fields_accept_unbranded_frames(self, monkeypatch: pytest.MonkeyPatch):
        # While a field is unregistered, unbranded frames are accepted —
        # the strangler ramp. CRMAdjustedBundle.exposures is registered in
        # production now, so deregister it to pin the ramp semantics.
        from rwa_calc.contracts import bundles as bundles_module

        monkeypatch.delitem(bundles_module.SEALED_FRAME_FIELDS, "CRMAdjustedBundle.exposures")

        bundle = CRMAdjustedBundle(exposures=_conformant_frame())

        assert bundle.crm_errors == []

    def test_none_optional_field_skipped(self, monkeypatch: pytest.MonkeyPatch):
        from rwa_calc.contracts import bundles as bundles_module

        monkeypatch.setitem(
            bundles_module.SEALED_FRAME_FIELDS,
            "CRMAdjustedBundle.collateral_allocation",
            "test_edge",
        )
        sealed = seal(_conformant_frame(), _contract())
        monkeypatch.setitem(
            bundles_module.SEALED_FRAME_FIELDS,
            "CRMAdjustedBundle.exposures",
            "test_edge",
        )

        bundle = CRMAdjustedBundle(exposures=sealed, collateral_allocation=None)

        assert bundle.collateral_allocation is None


class TestConformLenient:
    """Input-boundary variant: external data quality must never raise."""

    def test_missing_required_injected_as_typed_null_and_reported(self):
        contract = _contract()
        lf = _conformant_frame().drop("ead")

        out, missing = contract.conform_lenient(lf)
        collected = out.collect()

        assert missing == ["ead"]
        assert collected["ead"].to_list() == [None, None]
        assert collected.schema["ead"] == pl.Float64

    def test_dtype_mismatch_cast_not_raised(self):
        contract = _contract()
        lf = _conformant_frame().with_columns(
            pl.Series("ead", ["100.5", "not-a-number"], dtype=pl.String)
        )

        out, missing = contract.conform_lenient(lf)
        collected = out.collect()

        assert missing == []
        # strict=False cast: invalid values become null, never an exception.
        assert collected["ead"].to_list() == [100.5, None]
        assert collected.schema["ead"] == pl.Float64

    def test_absent_optional_injected_with_default_not_reported(self):
        contract = _contract()
        lf = _conformant_frame().drop("is_defaulted")

        out, missing = contract.conform_lenient(lf)

        assert missing == []
        assert out.collect()["is_defaulted"].to_list() == [False, False]

    def test_scratch_stripped_and_contract_order(self):
        contract = _contract()
        lf = _conformant_frame().with_columns(pl.lit(1).alias("_scratch"))

        out, missing = contract.conform_lenient(lf)
        collected = out.collect()

        assert missing == []
        assert collected.columns == [
            "exposure_reference",
            "ead",
            "is_defaulted",
            "turnover_m",
        ]

    def test_boolean_fill_applied_after_cast(self):
        # A pl.Null-inferred column must be cast to Boolean before the fill
        # (ordering is load-bearing — mirrors loader.enforce_schema).
        contract = _contract()
        lf = _conformant_frame().with_columns(pl.lit(None).alias("is_defaulted"))

        out, _ = contract.conform_lenient(lf)

        assert out.collect()["is_defaulted"].to_list() == [False, False]

    def test_seal_lenient_brands_and_reports(self):
        contract = _contract()

        out, missing = seal_lenient(_conformant_frame().drop("ead"), contract)

        assert sealed_edge_of(out) == "test_edge"
        assert missing == ["ead"]


class TestRawTableEdges:
    """The loader's per-table edge contracts, seeded from the input schemas."""

    def test_covers_every_raw_data_bundle_frame_field(self):
        import dataclasses

        from rwa_calc.contracts.bundles import RawDataBundle

        frame_fields = {
            f.name
            for f in dataclasses.fields(RawDataBundle)
            if "LazyFrame" in str(f.type) and f.name != "ccr"
        }

        assert set(RAW_TABLE_EDGES) == frame_fields

    def test_edge_names_carry_raw_prefix(self):
        assert all(edge.name == f"raw_{field_name}" for field_name, edge in RAW_TABLE_EDGES.items())

    def test_loans_edge_matches_loan_schema_dtypes(self):
        from rwa_calc.data.schemas import LOAN_SCHEMA

        edge = RAW_TABLE_EDGES["loans"]

        assert set(edge.columns) == set(LOAN_SCHEMA)
        assert all(edge.columns[name].dtype == spec.dtype for name, spec in LOAN_SCHEMA.items())

    def test_boolean_defaults_fill_preserved_from_loader_semantics(self):
        # FACILITY_SCHEMA.committed: Boolean default True, regulatory
        # load-bearing (CRR Art. 166) — the edge must keep the null fill.
        edge = RAW_TABLE_EDGES["facilities"]

        committed = edge.columns["committed"]

        assert committed.fill_null_default is True
        assert committed.default is True

    def test_float_and_string_columns_never_fill(self):
        for field_name, edge in RAW_TABLE_EDGES.items():
            for col_name, col in edge.columns.items():
                if col.fill_null_default:
                    assert col.dtype == pl.Boolean, (
                        f"{field_name}.{col_name}: non-Boolean fill is anti-conservative"
                    )


class TestConditionalColumns:
    """inject=False: declared-if-present (validated, never stripped, never injected)."""

    @staticmethod
    def _edge() -> EdgeContract:
        return EdgeContract(
            name="cond_edge",
            columns={
                "exposure_reference": EdgeColumn(dtype=pl.String),
                "guarantor_pd": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
            },
        )

    def test_absent_conditional_not_injected(self):
        out = self._edge().conform(pl.LazyFrame({"exposure_reference": ["E1"]})).collect()

        assert "guarantor_pd" not in out.columns

    def test_present_conditional_kept_and_validated(self):
        lf = pl.LazyFrame(
            {"exposure_reference": ["E1"], "guarantor_pd": [0.02]},
            schema={"exposure_reference": pl.String, "guarantor_pd": pl.Float64},
        )

        out = self._edge().conform(lf).collect()

        assert out["guarantor_pd"].to_list() == [0.02]

    def test_present_conditional_wrong_dtype_raises(self):
        lf = pl.LazyFrame(
            {"exposure_reference": ["E1"], "guarantor_pd": [1]},
            schema={"exposure_reference": pl.String, "guarantor_pd": pl.Int64},
        )

        with pytest.raises(EdgeContractViolation, match="guarantor_pd"):
            self._edge().conform(lf)

    def test_lenient_does_not_inject_conditional(self):
        out, missing = self._edge().conform_lenient(pl.LazyFrame({"exposure_reference": ["E1"]}))

        assert missing == []
        assert "guarantor_pd" not in out.collect().columns

    def test_inject_false_on_required_column_rejected(self):
        with pytest.raises(ValueError, match="inject"):
            EdgeContract(
                name="bad",
                columns={"x": EdgeColumn(dtype=pl.Float64, inject=False)},
            )


class TestResealWith:
    """``reseal_with`` — the sanctioned mutate-and-rebrand of a sealed frame."""

    @staticmethod
    def _edge() -> EdgeContract:
        return EdgeContract(
            name="reseal_edge",
            columns={
                "exposure_reference": EdgeColumn(dtype=pl.String),
                "scalar": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
            },
        )

    def test_declared_column_added_and_frame_rebranded(self):
        edge = self._edge()
        sealed = seal(pl.LazyFrame({"exposure_reference": ["E1"]}), edge)

        resealed = reseal_with(sealed, {"scalar": pl.lit(1.5, dtype=pl.Float64)}, edge)

        out = resealed.collect()
        assert sealed_edge_of(resealed) == "reseal_edge"
        assert out["scalar"].to_list() == [1.5]

    def test_undeclared_column_raises_before_conform_can_strip_it(self):
        edge = self._edge()
        sealed = seal(pl.LazyFrame({"exposure_reference": ["E1"]}), edge)
        undeclared_mutation = {"not_declared": pl.lit(9.9)}

        # An undeclared mutation would be silently stripped by conform, dropping
        # the mutation without a trace — reseal_with rejects it up front instead.
        with pytest.raises(EdgeContractViolation, match="not_declared"):
            reseal_with(sealed, undeclared_mutation, edge)


class TestReportingSurface:
    """``REPORTING_SURFACE`` is a documented subset of the exit-edge columns."""

    def test_every_surface_column_is_declared_on_aggregator_exit(self):
        undeclared = REPORTING_SURFACE - set(AGGREGATOR_EXIT_EDGE.columns)

        assert undeclared == set(), f"REPORTING_SURFACE names not on the edge: {undeclared}"

    def test_surface_contains_the_reporting_ledger_and_headline_measures(self):
        # Guards the annotation against silent drift: the 10 reporting_* columns,
        # the substitution-relief column, and the three headline measures.
        assert {"reporting_class", "reporting_approach", "reporting_method"} <= REPORTING_SURFACE
        assert "guarantee_rwa_benefit" in REPORTING_SURFACE
        assert {"rwa_final", "ead_final", "rwa_pre_floor"} <= REPORTING_SURFACE


class TestAggregatorSummaryEdges:
    """The five consumer-read aggregator frames seal against their own edges."""

    def test_registry_maps_field_name_to_matching_edge_name(self):
        for field_name, edge in AGGREGATOR_SUMMARY_EDGES.items():
            assert edge.name == field_name

    def test_summary_by_class_seals_producer_shape(self):
        # Producer shape verified against generate_summary_by_class (no floor):
        # exposure_class, total_ead, exposure_count, total_rwa, avg_risk_weight.
        frame = pl.LazyFrame(
            {
                "exposure_class": ["corporate"],
                "total_ead": [100.0],
                "exposure_count": pl.Series([1], dtype=pl.UInt32),
                "total_rwa": [50.0],
                "avg_risk_weight": [0.5],
            }
        )

        sealed = seal(frame, SUMMARY_BY_CLASS_EDGE)

        assert sealed_edge_of(sealed) == "summary_by_class"
        # floor_binding_count is conditional (inject=False) — absent when the
        # floor did not run, never injected.
        assert "floor_binding_count" not in sealed.collect().columns

    def test_summary_by_class_keeps_conditional_floor_binding_count(self):
        frame = pl.LazyFrame(
            {
                "exposure_class": ["corporate"],
                "total_ead": [100.0],
                "exposure_count": pl.Series([1], dtype=pl.UInt32),
                "total_rwa": [50.0],
                "floor_binding_count": pl.Series([1], dtype=pl.UInt32),
                "avg_risk_weight": [0.5],
            }
        )

        sealed = seal(frame, SUMMARY_BY_CLASS_EDGE).collect()

        assert sealed["floor_binding_count"].to_list() == [1]

    def test_supporting_factor_impact_seals_producer_shape(self):
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "exposure_class": ["corporate"],
                "is_sme": [True],
                "is_infrastructure": [False],
                "ead_final": [100.0],
                "supporting_factor": [0.7619],
                "rwa_pre_factor": [100.0],
                "rwa_post_factor": [76.19],
                "supporting_factor_impact": [23.81],
                "supporting_factor_applied": [True],
            }
        )

        sealed = seal(frame, SUPPORTING_FACTOR_IMPACT_EDGE)

        assert sealed_edge_of(sealed) == "supporting_factor_impact"

    def test_floor_impact_seals_producer_shape(self):
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "rwa_pre_floor": [100.0],
                "floor_rwa": [72.5],
                "is_floor_binding": [True],
                "floor_impact_rwa": [10.0],
                "rwa_post_floor": [110.0],
                "output_floor_pct": [0.725],
            }
        )

        sealed = seal(frame, FLOOR_IMPACT_EDGE)

        assert sealed_edge_of(sealed) == "floor_impact"

    def test_registered_field_rejects_unsealed_summary_frame(self):
        # AggregatedResultBundle.summary_by_class is registered in
        # SEALED_FRAME_FIELDS in production — an unbranded frame must raise.
        results = AGGREGATOR_EXIT_EDGE.empty_frame()
        unsealed_summary = pl.LazyFrame({"x": [1]})

        with pytest.raises(EdgeContractViolation, match="summary_by_class"):
            AggregatedResultBundle(results=results, summary_by_class=unsealed_summary)

    def test_registered_field_accepts_sealed_summary_frame(self):
        results = AGGREGATOR_EXIT_EDGE.empty_frame()
        sealed_summary = SUMMARY_BY_CLASS_EDGE.empty_frame()
        sealed_approach = SUMMARY_BY_APPROACH_EDGE.empty_frame()
        sealed_method = SUMMARY_BY_CLASS_METHOD_EDGE.empty_frame()

        bundle = AggregatedResultBundle(
            results=results,
            summary_by_class=sealed_summary,
            summary_by_approach=sealed_approach,
            summary_by_class_method=sealed_method,
        )

        assert bundle.summary_by_class is sealed_summary
