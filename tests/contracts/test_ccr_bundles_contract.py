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
