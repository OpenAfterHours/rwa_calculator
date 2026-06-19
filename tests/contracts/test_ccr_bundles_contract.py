"""Contract tests for CCR data-transfer bundles (P8.1).

Verifies that TradeBundle, NettingSetBundle, MarginAgreementBundle, and
CCRCollateralBundle satisfy the frozen-dataclass bundle contract required
by the CCR pipeline. These are pure structural / protocol checks — they
do NOT test calculation behaviour or column schemas (those are P8.5).

(The P8.3 CCRCalculator protocol-shape tests were removed in migration
Phase 2: the protocol never gained an implementation — the CCR engine is
wired as free functions via the pipeline's CCR stage — so the protocol
and its shape tests were dead weight.)

References:
- CRR Art. 272 definitions (trades, netting sets, margin agreements)
- CRR Art. 295-297 netting recognition
- CRR Art. 274-280 SA-CCR EAD calculation
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawCCRBundle as RawCCRBundleType
    from rwa_calc.contracts.config import CalculationConfig

# ---------------------------------------------------------------------------
# Import the modules under test at module scope — these always succeed
# because rwa_calc.contracts.bundles and rwa_calc.contracts.protocols both
# exist.  Individual classes are fetched via getattr() inside each test so
# that a missing class surfaces as an AssertionError rather than an
# ImportError at collection time.
# ---------------------------------------------------------------------------
import rwa_calc.contracts.bundles as bundles
import rwa_calc.contracts.config as config_module  # CCRConfig / CalculationConfig (P8.6)

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
# C. Exact field set — six fields in declared order
# ---------------------------------------------------------------------------


def test_raw_ccr_bundle_has_exactly_seven_fields_in_order() -> None:
    """RawCCRBundle must have exactly seven fields: trades, netting_sets, margin_agreements,
    ccr_collateral, failed_trades, default_fund_contributions, errors — in that order.
    (failed_trades added by P8.24; default_fund_contributions added by P8.49.)"""
    # Arrange
    cls = getattr(bundles, "RawCCRBundle", None)
    assert cls is not None, "'RawCCRBundle' not found — see test_raw_ccr_bundle_exists"

    # Act
    fields = dataclasses.fields(cls)
    field_names = [f.name for f in fields]

    # Assert — exactly seven fields
    assert len(fields) == 7, f"'RawCCRBundle' must have exactly 7 fields, got {field_names}"

    # Assert — names and order
    expected = [
        "trades",
        "netting_sets",
        "margin_agreements",
        "ccr_collateral",
        "failed_trades",
        "default_fund_contributions",
        "errors",
    ]
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
    # Guard — if P8.1 prerequisites missing, fail with clear AssertionError.
    # Per-variable asserts (not assert all(...)) so the type-checker can narrow
    # each name from `Any | None` to `Any` before the construction below.
    assert TradeBundle is not None, "P8.1 leaf bundle 'TradeBundle' not found"
    assert NettingSetBundle is not None, "P8.1 leaf bundle 'NettingSetBundle' not found"
    assert MarginAgreementBundle is not None, "P8.1 leaf bundle 'MarginAgreementBundle' not found"
    assert CCRCollateralBundle is not None, "P8.1 leaf bundle 'CCRCollateralBundle' not found"

    def _make_instance() -> RawCCRBundleType:
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
    # Per-variable asserts (not assert all(...)) so the type-checker can narrow
    # each name from `Any | None` to `Any` before the construction below.
    assert TradeBundle is not None, "P8.1 leaf bundle 'TradeBundle' not found"
    assert NettingSetBundle is not None, "P8.1 leaf bundle 'NettingSetBundle' not found"
    assert MarginAgreementBundle is not None, "P8.1 leaf bundle 'MarginAgreementBundle' not found"
    assert CCRCollateralBundle is not None, "P8.1 leaf bundle 'CCRCollateralBundle' not found"

    rccr = RawCCRBundle(
        trades=TradeBundle(trades=pl.LazyFrame()),
        netting_sets=NettingSetBundle(netting_sets=pl.LazyFrame()),
        margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
    )

    # Act — construct RawDataBundle with ccr= explicitly set
    # create_empty_raw_data_bundle does not accept **kwargs, so we build directly
    instance = make_raw_bundle(
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


# ===========================================================================
# P8.6 — CCRConfig dataclass defaults + CalculationConfig factory wiring
# ===========================================================================
#
# Helpers
# -------
_REPORTING_DATE = date(2026, 1, 1)


def _get_ccr_config_cls() -> type:
    """Return CCRConfig class, asserting it exists in config_module."""
    cls = getattr(config_module, "CCRConfig", None)
    assert cls is not None, (
        "rwa_calc.contracts.config does not expose 'CCRConfig'. "
        "Add the class to src/rwa_calc/contracts/config.py (P8.6)."
    )
    return cls


def _get_calculation_config_cls() -> type[CalculationConfig]:
    """Return CalculationConfig class from config_module."""
    cls = getattr(config_module, "CalculationConfig", None)
    assert cls is not None, "CalculationConfig not found in rwa_calc.contracts.config"
    return cls


class TestCCRConfigDefaults:
    """P8.6 — CCRConfig dataclass fields and CalculationConfig factory wiring."""

    # -----------------------------------------------------------------------
    # Dataclass-level tests
    # -----------------------------------------------------------------------

    def test_ccrconfig_default_construction_method(self) -> None:
        """CCRConfig().method must default to 'sa_ccr'."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act
        instance = cls()

        # Assert
        assert instance.method == "sa_ccr", (
            f"CCRConfig().method expected 'sa_ccr', got {instance.method!r}. "
            "Add field: method: Literal['sa_ccr'] = 'sa_ccr'"
        )

    def test_ccrconfig_default_construction_alpha(self) -> None:
        """CCRConfig().alpha must default to Decimal('1.4') per CRR Art. 274(2)."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act
        instance = cls()

        # Assert
        assert instance.alpha == Decimal("1.4"), (
            f"CCRConfig().alpha expected Decimal('1.4'), got {instance.alpha!r}. "
            "Add field: alpha: Decimal = Decimal('1.4')"
        )

    def test_ccrconfig_default_construction_enable_ccp_exposures(self) -> None:
        """CCRConfig().enable_ccp_exposures must default to True."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act
        instance = cls()

        # Assert
        assert instance.enable_ccp_exposures is True, (
            f"CCRConfig().enable_ccp_exposures expected True, "
            f"got {instance.enable_ccp_exposures!r}. "
            "Add field: enable_ccp_exposures: bool = True"
        )

    def test_ccrconfig_default_construction_mpor_floor_days(self) -> None:
        """CCRConfig().mpor_floor_days must default to 10 per CRR Art. 285."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act
        instance = cls()

        # Assert
        assert instance.mpor_floor_days == 10, (
            f"CCRConfig().mpor_floor_days expected 10, got {instance.mpor_floor_days!r}. "
            "Add field: mpor_floor_days: int = 10"
        )

    def test_ccrconfig_default_construction_recognise_im(self) -> None:
        """CCRConfig().recognise_im must default to True."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act
        instance = cls()

        # Assert
        assert instance.recognise_im is True, (
            f"CCRConfig().recognise_im expected True, got {instance.recognise_im!r}. "
            "Add field: recognise_im: bool = True"
        )

    def test_ccrconfig_is_frozen(self) -> None:
        """Assigning to CCRConfig().alpha must raise dataclasses.FrozenInstanceError."""
        # Arrange
        cls = _get_ccr_config_cls()
        instance = cls()

        # Act + Assert
        with pytest.raises(dataclasses.FrozenInstanceError):
            instance.alpha = Decimal("1.5")  # type: ignore[misc]

    def test_ccrconfig_accepts_supervisory_alpha_above_default(self) -> None:
        """CCRConfig(alpha=Decimal('1.5')).alpha must equal Decimal('1.5')."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act
        instance = cls(alpha=Decimal("1.5"))

        # Assert
        assert instance.alpha == Decimal("1.5"), (
            f"CCRConfig(alpha=Decimal('1.5')).alpha expected Decimal('1.5'), "
            f"got {instance.alpha!r}."
        )

    def test_ccrconfig_method_literal_only_sa_ccr(self) -> None:
        """The 'method' field annotation must be Literal['sa_ccr'] (string form)."""
        # Arrange
        cls = _get_ccr_config_cls()

        # Act — with from __future__ import annotations, annotations are strings
        raw_annotation = cls.__annotations__.get("method", "")

        # Assert — "Literal" and "sa_ccr" both appear in the annotation string
        annotation_str = str(raw_annotation)
        assert "Literal" in annotation_str and "sa_ccr" in annotation_str, (
            f"CCRConfig.method annotation must be Literal['sa_ccr'], "
            f"got {raw_annotation!r}. "
            "Declare: method: Literal['sa_ccr'] = 'sa_ccr'"
        )

    # -----------------------------------------------------------------------
    # CalculationConfig.crr() factory tests
    # -----------------------------------------------------------------------

    def test_calculationconfig_crr_has_ccr_attribute(self) -> None:
        """CalculationConfig.crr() must expose a .ccr attribute that is a CCRConfig."""
        # Arrange
        calc_cls = _get_calculation_config_cls()
        ccr_cls = _get_ccr_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE)

        # Assert
        assert hasattr(cfg, "ccr"), (
            "CalculationConfig.crr() result has no 'ccr' attribute. "
            "Add field: ccr: CCRConfig = field(default_factory=CCRConfig) to CalculationConfig "
            "and wire it in the .crr() factory."
        )
        assert isinstance(cfg.ccr, ccr_cls), (
            f"CalculationConfig.crr().ccr must be an instance of CCRConfig, got {type(cfg.ccr)!r}."
        )

    def test_calculationconfig_crr_default_alpha(self) -> None:
        """CalculationConfig.crr().ccr.alpha must equal Decimal('1.4')."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.alpha == Decimal("1.4"), (
            f"CalculationConfig.crr().ccr.alpha expected Decimal('1.4'), got {cfg.ccr.alpha!r}."
        )

    def test_calculationconfig_crr_default_mpor(self) -> None:
        """CalculationConfig.crr().ccr.mpor_floor_days must equal 10."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.mpor_floor_days == 10, (
            f"CalculationConfig.crr().ccr.mpor_floor_days expected 10, "
            f"got {cfg.ccr.mpor_floor_days!r}."
        )

    def test_calculationconfig_crr_default_enable_ccp_exposures(self) -> None:
        """CalculationConfig.crr().ccr.enable_ccp_exposures must be True."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.enable_ccp_exposures is True, (
            f"CalculationConfig.crr().ccr.enable_ccp_exposures expected True, "
            f"got {cfg.ccr.enable_ccp_exposures!r}."
        )

    def test_calculationconfig_crr_default_recognise_im(self) -> None:
        """CalculationConfig.crr().ccr.recognise_im must be True."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.recognise_im is True, (
            f"CalculationConfig.crr().ccr.recognise_im expected True, got {cfg.ccr.recognise_im!r}."
        )

    def test_calculationconfig_crr_ccr_alpha_kwarg_pass_through(self) -> None:
        """CalculationConfig.crr(ccr_alpha=Decimal('1.5')).ccr.alpha must equal Decimal('1.5')."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE, ccr_alpha=Decimal("1.5"))

        # Assert
        assert cfg.ccr.alpha == Decimal("1.5"), (
            f"CalculationConfig.crr(ccr_alpha=Decimal('1.5')).ccr.alpha expected "
            f"Decimal('1.5'), got {cfg.ccr.alpha!r}. "
            "Add kwarg 'ccr_alpha' to CalculationConfig.crr() and pass it to CCRConfig."
        )

    def test_calculationconfig_crr_mpor_floor_days_kwarg_pass_through(self) -> None:
        """CalculationConfig.crr(mpor_floor_days=20).ccr.mpor_floor_days must equal 20."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.crr(reporting_date=_REPORTING_DATE, mpor_floor_days=20)

        # Assert
        assert cfg.ccr.mpor_floor_days == 20, (
            f"CalculationConfig.crr(mpor_floor_days=20).ccr.mpor_floor_days expected 20, "
            f"got {cfg.ccr.mpor_floor_days!r}. "
            "Add kwarg 'mpor_floor_days' to CalculationConfig.crr() and pass it to CCRConfig."
        )

    # -----------------------------------------------------------------------
    # CalculationConfig.basel_3_1() factory tests
    # -----------------------------------------------------------------------

    def test_calculationconfig_basel_3_1_has_ccr_attribute(self) -> None:
        """CalculationConfig.basel_3_1() must expose a .ccr attribute that is a CCRConfig."""
        # Arrange
        calc_cls = _get_calculation_config_cls()
        ccr_cls = _get_ccr_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE)

        # Assert
        assert hasattr(cfg, "ccr"), (
            "CalculationConfig.basel_3_1() result has no 'ccr' attribute. "
            "Add field: ccr: CCRConfig = field(default_factory=CCRConfig) to CalculationConfig "
            "and wire it in the .basel_3_1() factory."
        )
        assert isinstance(cfg.ccr, ccr_cls), (
            f"CalculationConfig.basel_3_1().ccr must be an instance of CCRConfig, "
            f"got {type(cfg.ccr)!r}."
        )

    def test_calculationconfig_basel_3_1_default_alpha(self) -> None:
        """CalculationConfig.basel_3_1().ccr.alpha must equal Decimal('1.4')."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.alpha == Decimal("1.4"), (
            f"CalculationConfig.basel_3_1().ccr.alpha expected Decimal('1.4'), "
            f"got {cfg.ccr.alpha!r}."
        )

    def test_calculationconfig_basel_3_1_default_mpor(self) -> None:
        """CalculationConfig.basel_3_1().ccr.mpor_floor_days must equal 10."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.mpor_floor_days == 10, (
            f"CalculationConfig.basel_3_1().ccr.mpor_floor_days expected 10, "
            f"got {cfg.ccr.mpor_floor_days!r}."
        )

    def test_calculationconfig_basel_3_1_default_enable_ccp_exposures(self) -> None:
        """CalculationConfig.basel_3_1().ccr.enable_ccp_exposures must be True."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.enable_ccp_exposures is True, (
            f"CalculationConfig.basel_3_1().ccr.enable_ccp_exposures expected True, "
            f"got {cfg.ccr.enable_ccp_exposures!r}."
        )

    def test_calculationconfig_basel_3_1_default_recognise_im(self) -> None:
        """CalculationConfig.basel_3_1().ccr.recognise_im must be True."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE)

        # Assert
        assert cfg.ccr.recognise_im is True, (
            f"CalculationConfig.basel_3_1().ccr.recognise_im expected True, "
            f"got {cfg.ccr.recognise_im!r}."
        )

    def test_calculationconfig_basel_3_1_ccr_alpha_kwarg_pass_through(self) -> None:
        """CalculationConfig.basel_3_1(ccr_alpha=Decimal('1.5')).ccr.alpha must equal Decimal('1.5')."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE, ccr_alpha=Decimal("1.5"))

        # Assert
        assert cfg.ccr.alpha == Decimal("1.5"), (
            f"CalculationConfig.basel_3_1(ccr_alpha=Decimal('1.5')).ccr.alpha expected "
            f"Decimal('1.5'), got {cfg.ccr.alpha!r}. "
            "Add kwarg 'ccr_alpha' to CalculationConfig.basel_3_1() and pass it to CCRConfig."
        )

    def test_calculationconfig_basel_3_1_mpor_floor_days_kwarg_pass_through(self) -> None:
        """CalculationConfig.basel_3_1(mpor_floor_days=20).ccr.mpor_floor_days must equal 20."""
        # Arrange
        calc_cls = _get_calculation_config_cls()

        # Act
        cfg = calc_cls.basel_3_1(reporting_date=_REPORTING_DATE, mpor_floor_days=20)

        # Assert
        assert cfg.ccr.mpor_floor_days == 20, (
            f"CalculationConfig.basel_3_1(mpor_floor_days=20).ccr.mpor_floor_days expected 20, "
            f"got {cfg.ccr.mpor_floor_days!r}. "
            "Add kwarg 'mpor_floor_days' to CalculationConfig.basel_3_1() and pass it to CCRConfig."
        )
