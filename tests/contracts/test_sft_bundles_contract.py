"""Contract tests for the SFT (FCCM) data-transfer bundles (Phase 4).

Pins the structural shape of the SFT/FCCM separation Phase 4 bundles
(docs/plans/sft-fccm-separation.md):

- ``SftTradeBundle`` / ``SftCollateralBundle`` — frozen leaf bundles, each a
  LazyFrame holder + ``errors``, brand-validated in ``__post_init__``.
- ``RawSFTBundle(trades, collateral=None, errors=...)`` — composite with an
  OPTIONAL collateral leaf (an uncollateralised SFT has none).
- ``RawDataBundle.sft`` — additive optional field defaulting None, mirroring
  ``ccr`` so every existing construction is unaffected.
- ``SEALED_FRAME_FIELDS`` — the two SFT leaf frames carry the ``raw_sft_*``
  brands so they seal through the STANDARD loader seal path.

These are pure structural / brand checks — no calculation behaviour or
loader wiring (that lives in the integration loader round-trip test).

References:
    - CRR Art. 220(1)(a) — single-counterparty SFT scope
    - CRR Art. 223(5) — FCCM E* formula
    - CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

import rwa_calc.contracts.bundles as bundles
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, sealed_edge_of

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(name: str) -> type:
    """Fetch a bundle class by name, asserting it exists."""
    cls = getattr(bundles, name, None)
    assert cls is not None, (
        f"rwa_calc.contracts.bundles does not expose '{name}'. "
        f"Add the class to src/rwa_calc/contracts/bundles.py (SFT/FCCM Phase 4)."
    )
    return cls


def _sealed_trades() -> pl.LazyFrame:
    """An empty trades frame sealed for the raw_sft_trades edge."""
    return SFT_TABLE_EDGES["sft_trades"].empty_frame()


def _sealed_collateral() -> pl.LazyFrame:
    """An empty collateral frame sealed for the raw_sft_collateral edge."""
    return SFT_TABLE_EDGES["sft_collateral"].empty_frame()


# ===========================================================================
# 1. Leaf bundles — existence, frozen, two-field shape, brand validation
# ===========================================================================

_LEAF_SPECS: list[tuple[str, str, str]] = [
    ("SftTradeBundle", "sft_trades", "raw_sft_trades"),
    ("SftCollateralBundle", "sft_collateral", "raw_sft_collateral"),
]
_LEAF_NAMES = [s[0] for s in _LEAF_SPECS]


@pytest.mark.parametrize("class_name", _LEAF_NAMES)
def test_leaf_bundle_is_frozen_dataclass(class_name: str) -> None:
    """Each SFT leaf bundle must be a frozen dataclass."""
    cls = _get(class_name)
    assert dataclasses.is_dataclass(cls), f"'{class_name}' must be a @dataclass"
    params = cls.__dataclass_params__  # ty: ignore[unresolved-attribute]
    assert params.frozen is True, f"'{class_name}' must be frozen"


@pytest.mark.parametrize("class_name, lf_field, _brand", _LEAF_SPECS)
def test_leaf_bundle_has_lazyframe_and_errors_fields(
    class_name: str, lf_field: str, _brand: str
) -> None:
    """Each SFT leaf bundle has exactly (LazyFrame holder, errors)."""
    cls = _get(class_name)
    field_names = [f.name for f in dataclasses.fields(cls)]
    assert field_names == [lf_field, "errors"], (
        f"'{class_name}' fields must be ['{lf_field}', 'errors'], got {field_names}"
    )


@pytest.mark.parametrize("class_name, lf_field, brand_name", _LEAF_SPECS)
def test_leaf_bundle_accepts_correctly_branded_frame(
    class_name: str, lf_field: str, brand_name: str
) -> None:
    """A leaf bundle constructs when its frame carries the right raw_sft_* brand."""
    cls = _get(class_name)
    frame = _sealed_trades() if lf_field == "sft_trades" else _sealed_collateral()
    assert sealed_edge_of(frame) == brand_name

    instance = cls(**{lf_field: frame})

    assert getattr(instance, lf_field) is frame
    assert instance.errors == []


@pytest.mark.parametrize("class_name, lf_field, _brand", _LEAF_SPECS)
def test_leaf_bundle_rejects_unbranded_frame(class_name: str, lf_field: str, _brand: str) -> None:
    """A leaf bundle rejects an unbranded frame (SEALED_FRAME_FIELDS-registered)."""
    from rwa_calc.contracts.edges import EdgeContractViolation

    cls = _get(class_name)
    with pytest.raises(EdgeContractViolation, match=class_name):
        cls(**{lf_field: pl.LazyFrame({"x": [1]})})


@pytest.mark.parametrize("class_name, lf_field, _brand", _LEAF_SPECS)
def test_leaf_bundle_errors_default_factory_distinct(
    class_name: str, lf_field: str, _brand: str
) -> None:
    """Two leaf bundles must not share the same errors list (default_factory=list)."""
    cls = _get(class_name)
    frame = _sealed_trades() if lf_field == "sft_trades" else _sealed_collateral()
    a = cls(**{lf_field: frame})
    b = cls(**{lf_field: frame})
    assert a.errors is not b.errors


# ===========================================================================
# 2. SEALED_FRAME_FIELDS registration
# ===========================================================================


def test_sealed_frame_fields_registers_both_sft_leaf_frames() -> None:
    """The two SFT leaf frames carry raw_sft_* brands in SEALED_FRAME_FIELDS."""
    fields = bundles.SEALED_FRAME_FIELDS
    assert fields.get("SftTradeBundle.sft_trades") == "raw_sft_trades"
    assert fields.get("SftCollateralBundle.sft_collateral") == "raw_sft_collateral"


# ===========================================================================
# 3. RawSFTBundle composite — collateral optional
# ===========================================================================


def test_raw_sft_bundle_is_frozen_dataclass() -> None:
    """RawSFTBundle must be a frozen dataclass."""
    cls = _get("RawSFTBundle")
    assert dataclasses.is_dataclass(cls)
    params = cls.__dataclass_params__  # ty: ignore[unresolved-attribute]
    assert params.frozen is True


def test_raw_sft_bundle_field_set_and_order() -> None:
    """RawSFTBundle fields are exactly (trades, collateral, errors) in order."""
    cls = _get("RawSFTBundle")
    field_names = [f.name for f in dataclasses.fields(cls)]
    assert field_names == ["trades", "collateral", "errors"], (
        f"RawSFTBundle fields must be ['trades', 'collateral', 'errors'], got {field_names}"
    )


def test_raw_sft_bundle_collateral_defaults_none() -> None:
    """collateral must default None — an uncollateralised SFT has no collateral."""
    cls = _get("RawSFTBundle")
    collateral_field = next(f for f in dataclasses.fields(cls) if f.name == "collateral")
    assert collateral_field.default is None


def test_raw_sft_bundle_constructs_without_collateral() -> None:
    """RawSFTBundle constructs from trades alone (uncollateralised case)."""
    RawSFTBundle = _get("RawSFTBundle")
    SftTradeBundle = _get("SftTradeBundle")

    instance = RawSFTBundle(trades=SftTradeBundle(sft_trades=_sealed_trades()))

    assert instance.collateral is None
    assert instance.errors == []


def test_raw_sft_bundle_constructs_with_collateral() -> None:
    """RawSFTBundle constructs with both leaf bundles (collateralised case)."""
    RawSFTBundle = _get("RawSFTBundle")
    SftTradeBundle = _get("SftTradeBundle")
    SftCollateralBundle = _get("SftCollateralBundle")

    instance = RawSFTBundle(
        trades=SftTradeBundle(sft_trades=_sealed_trades()),
        collateral=SftCollateralBundle(sft_collateral=_sealed_collateral()),
    )

    assert instance.collateral is not None


# ===========================================================================
# 4. RawDataBundle.sft — additive optional field, defaults None
# ===========================================================================


def test_raw_data_bundle_has_sft_field_defaulting_none() -> None:
    """RawDataBundle.sft must exist, default None, and reference RawSFTBundle."""
    RawDataBundle = _get("RawDataBundle")
    sft_field = next((f for f in dataclasses.fields(RawDataBundle) if f.name == "sft"), None)
    assert sft_field is not None, (
        "RawDataBundle has no 'sft' field. "
        "Add 'sft: RawSFTBundle | None = None' (SFT/FCCM Phase 4)."
    )
    assert sft_field.default is None
    ann = str(RawDataBundle.__annotations__.get("sft", ""))
    assert "RawSFTBundle" in ann, f"RawDataBundle.sft annotation must reference RawSFTBundle: {ann}"


def test_create_empty_raw_data_bundle_sft_is_none() -> None:
    """create_empty_raw_data_bundle() stays backward-compatible: sft is None."""
    create_fn = getattr(bundles, "create_empty_raw_data_bundle", None)
    assert create_fn is not None
    instance = create_fn()
    assert instance.sft is None


def test_raw_data_bundle_accepts_sft_keyword() -> None:
    """RawDataBundle stores a supplied RawSFTBundle via the sft= keyword."""
    from tests.fixtures.raw_bundle import make_raw_bundle

    RawSFTBundle = _get("RawSFTBundle")
    SftTradeBundle = _get("SftTradeBundle")
    rsft = RawSFTBundle(trades=SftTradeBundle(sft_trades=_sealed_trades()))

    instance = make_raw_bundle(
        facilities=pl.LazyFrame(),
        loans=pl.LazyFrame(),
        counterparties=pl.LazyFrame(),
        facility_mappings=pl.LazyFrame(),
        sft=rsft,
    )

    assert instance.sft is rsft


# ===========================================================================
# 5. Phase 0b — fixture builder optionally populates the margining fields
# ===========================================================================


def test_builder_defaults_to_unmargined_sft() -> None:
    """The default A11 builder emits an UNMARGINED SFT (is_margined defaults False).

    Existing fixtures call build_sft_bundle_a11/a12 unchanged — they must stay
    unmargined so the Phase 0b carry-only change cannot move any output.
    """
    from tests.fixtures.ccr.sft_bundle_builder import build_sft_bundle_a11

    bundle = build_sft_bundle_a11()
    row = bundle.trades.sft_trades.collect().row(0, named=True)
    assert row["is_margined"] is False
    assert row["remargining_frequency_days"] == 1
    assert row["mpor_floor_category"] == "repo_only"
    assert row["mpor_days_override"] is None


def test_builder_can_emit_margined_sft() -> None:
    """The builder OPTIONALLY populates the Art. 285 margining fields when asked."""
    from tests.fixtures.ccr.sft_bundle_builder import build_margined_sft_bundle

    bundle = build_margined_sft_bundle(
        remargining_frequency_days=2,
        mpor_floor_category="other",
        has_margin_dispute_doubling=True,
        mpor_days_override=12,
    )
    row = bundle.trades.sft_trades.collect().row(0, named=True)
    assert row["is_margined"] is True
    assert row["remargining_frequency_days"] == 2
    assert row["mpor_floor_category"] == "other"
    assert row["has_margin_dispute_doubling"] is True
    assert row["mpor_days_override"] == 12
