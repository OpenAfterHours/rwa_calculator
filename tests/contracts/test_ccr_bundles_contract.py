"""Contract tests for CCR data-transfer bundles (P8.1).

Verifies that TradeBundle, NettingSetBundle, MarginAgreementBundle, and
CCRCollateralBundle satisfy the frozen-dataclass bundle contract required
by the CCR pipeline. These are pure structural / protocol checks — they
do NOT test calculation behaviour or column schemas (those are P8.5).

References:
- CRR Art. 272 definitions (trades, netting sets, margin agreements)
- CRR Art. 295-297 netting recognition
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Import the module under test at module scope — this always succeeds
# because rwa_calc.contracts.bundles already exists.  Individual classes are
# fetched via getattr() inside each test so that a missing class surfaces as
# an AssertionError rather than an ImportError at collection time.
# ---------------------------------------------------------------------------
import rwa_calc.contracts.bundles as bundles

# ---------------------------------------------------------------------------
# Metadata table — drives parametric tests
# ---------------------------------------------------------------------------
#
# Each entry:  (class_name,  LazyFrame_field_name)
#
_CCR_BUNDLE_SPECS: list[tuple[str, str]] = [
    ("TradeBundle", "trades"),
    ("NettingSetBundle", "netting_sets"),
    ("MarginAgreementBundle", "margin_agreements"),
    ("CCRCollateralBundle", "ccr_collateral"),
]

_CCR_BUNDLE_CLASS_NAMES = [spec[0] for spec in _CCR_BUNDLE_SPECS]


# ===========================================================================
# 1. Existence + module location
# ===========================================================================


@pytest.mark.parametrize("class_name", _CCR_BUNDLE_CLASS_NAMES)
def test_ccr_bundle_exists_in_bundles_module(class_name: str) -> None:
    """Each CCR bundle class must be importable from rwa_calc.contracts.bundles."""
    # Arrange — module is already imported at the top of this file

    # Act
    cls = getattr(bundles, class_name, None)

    # Assert
    assert cls is not None, (
        f"rwa_calc.contracts.bundles does not expose '{class_name}'. "
        f"Add the class to src/rwa_calc/contracts/bundles.py (P8.1)."
    )


# ===========================================================================
# 2. Frozen dataclass check
# ===========================================================================


@pytest.mark.parametrize("class_name", _CCR_BUNDLE_CLASS_NAMES)
def test_ccr_bundle_is_frozen_dataclass(class_name: str) -> None:
    """Each CCR bundle must be a dataclass with frozen=True."""
    # Arrange
    cls = getattr(bundles, class_name, None)
    assert cls is not None, (
        f"'{class_name}' not found — see test_ccr_bundle_exists_in_bundles_module"
    )

    # Act + Assert — is_dataclass
    assert dataclasses.is_dataclass(cls), f"'{class_name}' must be decorated with @dataclass"

    # Act + Assert — frozen
    assert cls.__dataclass_params__.frozen is True, (
        f"'{class_name}' must use @dataclass(frozen=True)"
    )


# ===========================================================================
# 3. Exact field set
# ===========================================================================


@pytest.mark.parametrize("class_name, lf_field_name", _CCR_BUNDLE_SPECS)
def test_ccr_bundle_has_exactly_two_fields(class_name: str, lf_field_name: str) -> None:
    """Each CCR bundle must have exactly two fields: the LazyFrame holder and errors."""
    # Arrange
    cls = getattr(bundles, class_name, None)
    assert cls is not None, f"'{class_name}' not found — run existence test first"

    # Act
    fields = dataclasses.fields(cls)
    field_names = [f.name for f in fields]

    # Assert — exactly two fields
    assert len(fields) == 2, f"'{class_name}' must have exactly 2 fields, got {field_names}"

    # Assert — correct LazyFrame field name
    assert field_names[0] == lf_field_name, (
        f"'{class_name}': first field must be '{lf_field_name}', got '{field_names[0]}'"
    )

    # Assert — second field is 'errors'
    assert field_names[1] == "errors", (
        f"'{class_name}': second field must be 'errors', got '{field_names[1]}'"
    )


# ===========================================================================
# 4. Field type annotations
# ===========================================================================


@pytest.mark.parametrize("class_name, lf_field_name", _CCR_BUNDLE_SPECS)
def test_ccr_bundle_field_type_annotations(class_name: str, lf_field_name: str) -> None:
    """LazyFrame field must be annotated pl.LazyFrame; errors must be list[CalculationError]."""
    # Arrange
    cls = getattr(bundles, class_name, None)
    assert cls is not None, f"'{class_name}' not found — run existence test first"

    annotations = cls.__annotations__

    # Act + Assert — LazyFrame field annotation
    lf_annotation = annotations.get(lf_field_name)
    assert lf_annotation is pl.LazyFrame or lf_annotation == "pl.LazyFrame", (
        f"'{class_name}.{lf_field_name}' must be annotated as pl.LazyFrame, got {lf_annotation!r}"
    )

    # Act + Assert — errors field annotation contains CalculationError
    errors_annotation = annotations.get("errors", "")
    errors_str = str(errors_annotation)
    assert "CalculationError" in errors_str, (
        f"'{class_name}.errors' annotation must reference CalculationError, "
        f"got {errors_annotation!r}"
    )


# ===========================================================================
# 5. Construction round-trip and immutability
# ===========================================================================


@pytest.mark.parametrize("class_name, lf_field_name", _CCR_BUNDLE_SPECS)
def test_ccr_bundle_construction_and_immutability(class_name: str, lf_field_name: str) -> None:
    """Bundles must construct with an empty LazyFrame and reject field reassignment."""
    # Arrange
    cls = getattr(bundles, class_name, None)
    assert cls is not None, f"'{class_name}' not found — run existence test first"

    # Act — construct with empty LazyFrame
    instance = cls(**{lf_field_name: pl.LazyFrame()})

    # Assert — LazyFrame field is stored
    assert getattr(instance, lf_field_name) is not None

    # Assert — errors defaults to empty list
    assert instance.errors == [], f"'{class_name}.errors' must default to [] via default_factory"

    # Assert — frozen: reassignment raises FrozenInstanceError
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, lf_field_name, pl.LazyFrame())


# ===========================================================================
# 6. Mutable-default safety (default_factory=list, not shared [])
# ===========================================================================


@pytest.mark.parametrize("class_name, lf_field_name", _CCR_BUNDLE_SPECS)
def test_ccr_bundle_errors_default_factory_produces_distinct_lists(
    class_name: str, lf_field_name: str
) -> None:
    """Two independently-constructed instances must not share the same errors list."""
    # Arrange
    cls = getattr(bundles, class_name, None)
    assert cls is not None, f"'{class_name}' not found — run existence test first"

    # Act
    inst_a = cls(**{lf_field_name: pl.LazyFrame()})
    inst_b = cls(**{lf_field_name: pl.LazyFrame()})

    # Assert — distinct list objects (default_factory=list, not a shared default)
    assert inst_a.errors is not inst_b.errors, (
        f"'{class_name}.errors' must use default_factory=list — "
        f"two instances share the same list object, indicating a mutable default."
    )


# ===========================================================================
# P8.2 — RawCCRBundle aggregate bundle and RawDataBundle.ccr field
# ===========================================================================


# ---------------------------------------------------------------------------
# A. Existence
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_exists_in_bundles_module() -> None:
    """RawCCRBundle must be importable from rwa_calc.contracts.bundles."""
    # Arrange — module imported at top of file

    # Act
    cls = getattr(bundles, "RawCCRBundle", None)

    # Assert
    assert cls is not None, (
        "rwa_calc.contracts.bundles does not expose 'RawCCRBundle'. "
        "Add the class to src/rwa_calc/contracts/bundles.py (P8.2)."
    )


# ---------------------------------------------------------------------------
# B. Frozen dataclass
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_is_frozen_dataclass() -> None:
    """RawCCRBundle must be a frozen dataclass."""
    # Arrange
    cls = getattr(bundles, "RawCCRBundle", None)
    assert cls is not None, "'RawCCRBundle' not found — see test_raw_ccr_bundle_exists"

    # Act + Assert — is_dataclass
    assert dataclasses.is_dataclass(cls), "'RawCCRBundle' must be decorated with @dataclass"

    # Act + Assert — frozen
    assert cls.__dataclass_params__.frozen is True, (
        "'RawCCRBundle' must use @dataclass(frozen=True)"
    )


# ---------------------------------------------------------------------------
# C. Exact field set — five fields in declared order
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_has_exactly_five_fields_in_order() -> None:
    """RawCCRBundle must have exactly five fields: trades, netting_sets, margin_agreements,
    ccr_collateral, errors — in that order."""
    # Arrange
    cls = getattr(bundles, "RawCCRBundle", None)
    assert cls is not None, "'RawCCRBundle' not found — see test_raw_ccr_bundle_exists"

    # Act
    fields = dataclasses.fields(cls)
    field_names = [f.name for f in fields]

    # Assert — exactly five fields
    assert len(fields) == 5, f"'RawCCRBundle' must have exactly 5 fields, got {field_names}"

    # Assert — names and order
    expected = ["trades", "netting_sets", "margin_agreements", "ccr_collateral", "errors"]
    assert field_names == expected, (
        f"'RawCCRBundle' fields must be {expected} in that order, got {field_names}"
    )


# ---------------------------------------------------------------------------
# D. Field type annotations
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_leaf_field_annotations() -> None:
    """The four leaf-bundle fields must be annotated with their P8.1 classes;
    errors must reference CalculationError."""
    # Arrange
    cls = getattr(bundles, "RawCCRBundle", None)
    assert cls is not None, "'RawCCRBundle' not found — see test_raw_ccr_bundle_exists"

    annotations = cls.__annotations__

    # Act + Assert — each leaf bundle annotation (string form accepted due to __future__ annotations)
    leaf_checks = [
        ("trades", "TradeBundle"),
        ("netting_sets", "NettingSetBundle"),
        ("margin_agreements", "MarginAgreementBundle"),
        ("ccr_collateral", "CCRCollateralBundle"),
    ]
    for field_name, expected_type_name in leaf_checks:
        ann = annotations.get(field_name, "")
        ann_str = str(ann)
        assert expected_type_name in ann_str, (
            f"'RawCCRBundle.{field_name}' annotation must reference '{expected_type_name}', "
            f"got {ann!r}"
        )

    # Assert — errors field references CalculationError
    errors_ann = annotations.get("errors", "")
    errors_str = str(errors_ann)
    assert "CalculationError" in errors_str, (
        f"'RawCCRBundle.errors' annotation must reference CalculationError, got {errors_ann!r}"
    )


# ---------------------------------------------------------------------------
# E. Construction round-trip and immutability
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_construction_and_immutability() -> None:
    """RawCCRBundle must construct from four leaf bundles, default errors to [],
    and reject field reassignment."""
    # Arrange — fetch classes (guarded so failure is AssertionError)
    RawCCRBundle = getattr(bundles, "RawCCRBundle", None)
    assert RawCCRBundle is not None, "'RawCCRBundle' not found — see test_raw_ccr_bundle_exists"

    TradeBundle = getattr(bundles, "TradeBundle", None)
    assert TradeBundle is not None, "'TradeBundle' not found — P8.1 prerequisite missing"

    NettingSetBundle = getattr(bundles, "NettingSetBundle", None)
    assert NettingSetBundle is not None, "'NettingSetBundle' not found — P8.1 prerequisite missing"

    MarginAgreementBundle = getattr(bundles, "MarginAgreementBundle", None)
    assert MarginAgreementBundle is not None, (
        "'MarginAgreementBundle' not found — P8.1 prerequisite missing"
    )

    CCRCollateralBundle = getattr(bundles, "CCRCollateralBundle", None)
    assert CCRCollateralBundle is not None, (
        "'CCRCollateralBundle' not found — P8.1 prerequisite missing"
    )

    # Act — construct with minimal leaf bundle instances
    instance = RawCCRBundle(
        trades=TradeBundle(trades=pl.LazyFrame()),
        netting_sets=NettingSetBundle(netting_sets=pl.LazyFrame()),
        margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
    )

    # Assert — errors defaults to empty list
    assert instance.errors == [], "'RawCCRBundle.errors' must default to [] via default_factory"

    # Assert — leaf fields are stored
    assert instance.trades is not None
    assert instance.netting_sets is not None
    assert instance.margin_agreements is not None
    assert instance.ccr_collateral is not None

    # Assert — frozen: reassignment raises FrozenInstanceError
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.trades = TradeBundle(trades=pl.LazyFrame())


# ---------------------------------------------------------------------------
# F. Mutable-default safety
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_errors_default_factory_produces_distinct_lists() -> None:
    """Two independently-constructed RawCCRBundle instances must not share the same errors list."""
    # Arrange
    RawCCRBundle = getattr(bundles, "RawCCRBundle", None)
    assert RawCCRBundle is not None, "'RawCCRBundle' not found — see test_raw_ccr_bundle_exists"

    TradeBundle = getattr(bundles, "TradeBundle", None)
    NettingSetBundle = getattr(bundles, "NettingSetBundle", None)
    MarginAgreementBundle = getattr(bundles, "MarginAgreementBundle", None)
    CCRCollateralBundle = getattr(bundles, "CCRCollateralBundle", None)
    # Guard — if P8.1 prerequisites missing, fail with clear AssertionError
    assert all(
        x is not None
        for x in [TradeBundle, NettingSetBundle, MarginAgreementBundle, CCRCollateralBundle]
    ), "P8.1 leaf bundles not found — P8.1 prerequisite missing"

    def _make_instance() -> object:
        return RawCCRBundle(
            trades=TradeBundle(trades=pl.LazyFrame()),
            netting_sets=NettingSetBundle(netting_sets=pl.LazyFrame()),
            margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
        )

    # Act
    inst_a = _make_instance()
    inst_b = _make_instance()

    # Assert — distinct list objects
    assert inst_a.errors is not inst_b.errors, (
        "'RawCCRBundle.errors' must use default_factory=list — "
        "two instances share the same list object, indicating a mutable default."
    )


# ---------------------------------------------------------------------------
# G. RawDataBundle.ccr field existence and type annotation
# ---------------------------------------------------------------------------


def test_raw_data_bundle_has_ccr_field_with_none_default() -> None:
    """RawDataBundle must have a 'ccr' field with default None."""
    # Arrange
    RawDataBundle = getattr(bundles, "RawDataBundle", None)
    assert RawDataBundle is not None, "rwa_calc.contracts.bundles does not expose 'RawDataBundle'"

    # Act — find the 'ccr' field among all dataclass fields
    all_fields = dataclasses.fields(RawDataBundle)
    ccr_field = next((f for f in all_fields if f.name == "ccr"), None)

    # Assert — field exists
    assert ccr_field is not None, (
        "'RawDataBundle' has no field named 'ccr'. "
        "Add 'ccr: RawCCRBundle | None = None' to RawDataBundle (P8.2)."
    )

    # Assert — default is None (field.default for simple defaults)
    assert ccr_field.default is None, (
        f"'RawDataBundle.ccr' must default to None, got {ccr_field.default!r}"
    )

    # Assert — annotation references RawCCRBundle (string form due to __future__ annotations)
    ann = RawDataBundle.__annotations__.get("ccr", "")
    ann_str = str(ann)
    assert "RawCCRBundle" in ann_str, (
        f"'RawDataBundle.ccr' annotation must reference 'RawCCRBundle', got {ann!r}"
    )


# ---------------------------------------------------------------------------
# H. Backward compatibility: create_empty_raw_data_bundle() still works, ccr is None
# ---------------------------------------------------------------------------


def test_create_empty_raw_data_bundle_ccr_is_none_by_default() -> None:
    """create_empty_raw_data_bundle() must still work and produce ccr=None."""
    # Arrange
    create_fn = getattr(bundles, "create_empty_raw_data_bundle", None)
    assert create_fn is not None, (
        "'create_empty_raw_data_bundle' not found in rwa_calc.contracts.bundles"
    )

    # Act
    instance = create_fn()

    # Assert — ccr field exists and defaults to None (backward-compatible)
    _sentinel = object()
    ccr_value = getattr(instance, "ccr", _sentinel)
    assert ccr_value is not _sentinel, (
        "'RawDataBundle' object has no attribute 'ccr' — "
        "add 'ccr: RawCCRBundle | None = None' to RawDataBundle (P8.2)."
    )
    assert ccr_value is None, (
        f"'RawDataBundle.ccr' must be None when constructed via "
        f"create_empty_raw_data_bundle(), got {ccr_value!r}"
    )


# ---------------------------------------------------------------------------
# I. RawDataBundle accepts ccr= keyword argument
# ---------------------------------------------------------------------------


def test_raw_data_bundle_accepts_ccr_keyword_argument() -> None:
    """RawDataBundle must accept a RawCCRBundle instance via the ccr= keyword."""
    # Arrange
    RawCCRBundle = getattr(bundles, "RawCCRBundle", None)
    assert RawCCRBundle is not None, (
        "'RawCCRBundle' not found — P8.2 prerequisite: test_raw_ccr_bundle_exists"
    )

    TradeBundle = getattr(bundles, "TradeBundle", None)
    NettingSetBundle = getattr(bundles, "NettingSetBundle", None)
    MarginAgreementBundle = getattr(bundles, "MarginAgreementBundle", None)
    CCRCollateralBundle = getattr(bundles, "CCRCollateralBundle", None)
    assert all(
        x is not None
        for x in [TradeBundle, NettingSetBundle, MarginAgreementBundle, CCRCollateralBundle]
    ), "P8.1 leaf bundles not found — P8.1 prerequisite missing"

    rccr = RawCCRBundle(
        trades=TradeBundle(trades=pl.LazyFrame()),
        netting_sets=NettingSetBundle(netting_sets=pl.LazyFrame()),
        margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
    )

    # Act — construct RawDataBundle with ccr= explicitly set
    # create_empty_raw_data_bundle does not accept **kwargs, so we build directly
    instance = bundles.RawDataBundle(
        facilities=pl.LazyFrame(),
        loans=pl.LazyFrame(),
        counterparties=pl.LazyFrame(),
        facility_mappings=pl.LazyFrame(),
        lending_mappings=pl.LazyFrame(),
        ccr=rccr,
    )

    # Assert — ccr field stores the supplied RawCCRBundle
    assert instance.ccr is rccr, (
        "'RawDataBundle.ccr' did not store the supplied RawCCRBundle instance"
    )
