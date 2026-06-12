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

from rwa_calc.contracts.edges import (
    EdgeColumn,
    EdgeContract,
    EdgeContractViolation,
    seal,
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
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

        sealed = seal(_conformant_frame(), _contract())

        bundle = CRMAdjustedBundle(exposures=sealed)

        assert bundle.exposures is sealed

    def test_unbranded_frame_on_registered_field_raises(self, registered_crm_exposures):
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

        with pytest.raises(EdgeContractViolation, match="CRMAdjustedBundle.exposures"):
            CRMAdjustedBundle(exposures=_conformant_frame())

    def test_wrong_brand_on_registered_field_raises(self, registered_crm_exposures):
        other = EdgeContract(
            name="other_edge",
            columns={"exposure_reference": EdgeColumn(dtype=pl.String)},
        )
        sealed_other = seal(pl.LazyFrame({"exposure_reference": ["E1"]}), other)
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

        with pytest.raises(EdgeContractViolation, match="other_edge"):
            CRMAdjustedBundle(exposures=sealed_other)

    def test_unregistered_fields_accept_unbranded_frames(self):
        # The registry is empty by default during the strangler — bundles
        # constructed with plain frames keep working until their edge seals.
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

        bundle = CRMAdjustedBundle(exposures=_conformant_frame())

        assert bundle.crm_errors == []

    def test_none_optional_field_skipped(self, monkeypatch: pytest.MonkeyPatch):
        from rwa_calc.contracts import bundles as bundles_module
        from rwa_calc.contracts.bundles import CRMAdjustedBundle

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
