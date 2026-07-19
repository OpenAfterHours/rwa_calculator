"""Unit tests for P1.244: the Art. 147(5A)(a)-(b) QRRE assignment gates.

CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b) admit a revolving retail
exposure to the qualifying revolving retail exposures (QRRE) sub-class only when
it is (a) to an individual and (b) revolving, UNSECURED, and — to the extent it
is not drawn — unconditionally cancellable. The engine previously tested only
the revolving flag and the (c) per-individual aggregate limit, so a secured
revolving retail facility, a non-cancellable undrawn commitment, or a
non-natural-person RETAIL_OTHER row could wrongly become QRRE (QRRE's lower
correlation understates RWA).

Scope (both regimes — the same conditions apply under CRR Art. 154(4) and the
gates are not regime-Featured):
- Secured revolving retail (is_secured=True)      -> RETAIL_OTHER (unsecured gate).
- Undrawn revolving line with a non-LR risk_type   -> RETAIL_OTHER (cancellable gate).
- Non-individual RETAIL_OTHER (direct transform)   -> stays RETAIL_OTHER (individuals gate).
- The unsecured, LR-cancellable individual control -> RETAIL_QRRE (unchanged).
- CLS010 fires once for the gate-demoted rows and NOT for the all-pass control.

References:
- CRR Art. 154(4)(a)-(c); PRA PS1/26 Art. 147(5A)(a)-(c).
- CRR Art. 111(1) / PS1/26 Table A1 Row 7: LR = unconditionally cancellable CCF.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.stages.classify.subtypes import classify_exposure_subtypes
from tests.fixtures.p1_244.p1_244 import (
    EXP_CONTROL,
    EXP_NOT_CANCELLABLE,
    EXP_SECURED,
    LOAN_DRAWN_CONTROL,
    LOAN_DRAWN_SECURED,
    build_p1_244_control_only_raw_bundle,
    build_p1_244_drawn_leg_raw_bundle,
    build_p1_244_raw_bundle,
    make_subtypes_frame,
)

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2027, 1, 4))


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 4))


def _classify(config: CalculationConfig):
    raw = build_p1_244_raw_bundle()
    resolved = HierarchyResolver().resolve(raw, config)
    return ExposureClassifier().classify(resolved, config)


def _drawn_leg_classes(config: CalculationConfig) -> dict[str, str]:
    raw = build_p1_244_drawn_leg_raw_bundle()
    resolved = HierarchyResolver().resolve(raw, config)
    result = ExposureClassifier().classify(resolved, config)
    df = result.all_exposures.select("exposure_reference", "exposure_class").collect()
    return dict(zip(df["exposure_reference"], df["exposure_class"], strict=True))


@pytest.fixture(scope="module")
def crr_classes(crr_config: CalculationConfig) -> dict[str, str]:
    result = _classify(crr_config)
    df = result.all_exposures.select("exposure_reference", "exposure_class").collect()
    return dict(zip(df["exposure_reference"], df["exposure_class"], strict=True))


@pytest.fixture(scope="module")
def b31_classes(b31_config: CalculationConfig) -> dict[str, str]:
    result = _classify(b31_config)
    df = result.all_exposures.select("exposure_reference", "exposure_class").collect()
    return dict(zip(df["exposure_reference"], df["exposure_class"], strict=True))


@pytest.fixture(scope="module")
def crr_drawn_leg_classes(crr_config: CalculationConfig) -> dict[str, str]:
    return _drawn_leg_classes(crr_config)


@pytest.fixture(scope="module")
def b31_drawn_leg_classes() -> dict[str, str]:
    # Art. 123A(1)(b)(ii) granularity is Basel-3.1-only and, on this 2-obligor
    # test portfolio, would demote BOTH drawn legs to CORPORATE regardless of
    # is_secured — orthogonal noise for the QRRE unsecured gate. Disable it via
    # the documented isolation switch so only the is_secured coupling on the
    # drawn leg discriminates (the fully-undrawn bundle sidesteps this with
    # drawn=0, which the drawn leg cannot).
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 4), enforce_retail_granularity=False
    )
    return _drawn_leg_classes(config)


# =============================================================================
# (b) unsecured gate — a secured revolving retail facility is demoted
# =============================================================================


class TestUnsecuredGate:
    """Art. 147(5A)(b): QRRE must be unsecured (is_secured=True -> RETAIL_OTHER)."""

    def test_crr_secured_revolving_retail_is_not_qrre(self, crr_classes: dict[str, str]) -> None:
        assert crr_classes[EXP_SECURED] == _RETAIL_OTHER

    def test_b31_secured_revolving_retail_is_not_qrre(self, b31_classes: dict[str, str]) -> None:
        assert b31_classes[EXP_SECURED] == _RETAIL_OTHER

    def test_crr_unsecured_control_stays_qrre(self, crr_classes: dict[str, str]) -> None:
        assert crr_classes[EXP_CONTROL] == _QRRE

    def test_b31_unsecured_control_stays_qrre(self, b31_classes: dict[str, str]) -> None:
        assert b31_classes[EXP_CONTROL] == _QRRE


# =============================================================================
# (b) unsecured gate — the DRAWN loan leg inherits the facility attestation
# =============================================================================


class TestUnsecuredGateDrawnLeg:
    """Art. 147(5A)(b): the facility ``is_secured`` attestation is coalesced onto
    the DRAWN loan leg (``enrich._join_facility_qrre_columns`` — coupling Site B),
    not only onto the synthetic facility_undrawn row (Site A). A fully-drawn
    individual revolving loan under a secured facility demotes to RETAIL_OTHER;
    its unsecured control stays QRRE."""

    def test_crr_secured_drawn_loan_leg_is_not_qrre(
        self, crr_drawn_leg_classes: dict[str, str]
    ) -> None:
        assert crr_drawn_leg_classes[LOAN_DRAWN_SECURED] == _RETAIL_OTHER

    def test_b31_secured_drawn_loan_leg_is_not_qrre(
        self, b31_drawn_leg_classes: dict[str, str]
    ) -> None:
        assert b31_drawn_leg_classes[LOAN_DRAWN_SECURED] == _RETAIL_OTHER

    def test_crr_unsecured_drawn_loan_control_stays_qrre(
        self, crr_drawn_leg_classes: dict[str, str]
    ) -> None:
        assert crr_drawn_leg_classes[LOAN_DRAWN_CONTROL] == _QRRE

    def test_b31_unsecured_drawn_loan_control_stays_qrre(
        self, b31_drawn_leg_classes: dict[str, str]
    ) -> None:
        assert b31_drawn_leg_classes[LOAN_DRAWN_CONTROL] == _QRRE


# =============================================================================
# (b) unconditionally-cancellable gate — undrawn non-LR line is demoted
# =============================================================================


class TestUnconditionallyCancellableGate:
    """Art. 147(5A)(b): an undrawn commitment must be unconditionally cancellable
    (LR risk_type). A non-LR (MR) undrawn revolving line is demoted."""

    def test_crr_non_cancellable_undrawn_is_not_qrre(self, crr_classes: dict[str, str]) -> None:
        assert crr_classes[EXP_NOT_CANCELLABLE] == _RETAIL_OTHER

    def test_b31_non_cancellable_undrawn_is_not_qrre(self, b31_classes: dict[str, str]) -> None:
        assert b31_classes[EXP_NOT_CANCELLABLE] == _RETAIL_OTHER


# =============================================================================
# (a) individuals gate — a non-natural-person RETAIL_OTHER row cannot be QRRE
# =============================================================================


class TestIndividualsGate:
    """Art. 147(5A)(a): QRRE is limited to individuals. A non-natural-person
    RETAIL_OTHER row (only reachable at the transform boundary — the entity map
    routes non-individuals away from RETAIL_OTHER) stays RETAIL_OTHER."""

    @staticmethod
    def _subtype_class(config: CalculationConfig, entity_type: str, natural: bool) -> str:
        frame = make_subtypes_frame(cp_entity_type=entity_type, cp_is_natural_person=natural)
        out = classify_exposure_subtypes(frame, config).select("exposure_class").collect()
        return out["exposure_class"][0]

    def test_crr_non_individual_retail_is_not_qrre(self, crr_config: CalculationConfig) -> None:
        assert self._subtype_class(crr_config, "company", False) == _RETAIL_OTHER

    def test_b31_non_individual_retail_is_not_qrre(self, b31_config: CalculationConfig) -> None:
        assert self._subtype_class(b31_config, "company", False) == _RETAIL_OTHER

    def test_crr_individual_control_is_qrre(self, crr_config: CalculationConfig) -> None:
        assert self._subtype_class(crr_config, "individual", True) == _QRRE

    def test_b31_individual_control_is_qrre(self, b31_config: CalculationConfig) -> None:
        assert self._subtype_class(b31_config, "individual", True) == _QRRE


# =============================================================================
# CLS010 gate-demotion warning
# =============================================================================


class TestQRREGateDemotionWarning:
    """CLS010 fires once when a would-be QRRE row is denied by an (a)/(b) gate,
    and stays silent when every gate passes."""

    def test_b31_cls010_emitted_for_gate_demotions(self, b31_config: CalculationConfig) -> None:
        result = _classify(b31_config)
        cls010 = [e for e in result.classification_errors if e.code == "CLS010"]
        assert len(cls010) == 1

    def test_crr_cls010_emitted_for_gate_demotions(self, crr_config: CalculationConfig) -> None:
        result = _classify(crr_config)
        cls010 = [e for e in result.classification_errors if e.code == "CLS010"]
        assert len(cls010) == 1

    def test_b31_no_cls010_when_all_gates_pass(self, b31_config: CalculationConfig) -> None:
        raw = build_p1_244_control_only_raw_bundle()
        resolved = HierarchyResolver().resolve(raw, b31_config)
        result = ExposureClassifier().classify(resolved, b31_config)
        cls010 = [e for e in result.classification_errors if e.code == "CLS010"]
        assert cls010 == []


# =============================================================================
# The unconditionally-cancellable limb only bites the undrawn portion
# =============================================================================


class TestFullyDrawnCancellabilityIsTrivial:
    """Art. 147(5A)(b) cancellability applies only 'to the extent they are not
    drawn'. A fully-drawn (undrawn_amount=0) individual unsecured revolving row
    with a non-LR risk_type is still QRRE — there is nothing undrawn to cancel."""

    @pytest.mark.parametrize("config_name", ["crr_config", "b31_config"])
    def test_fully_drawn_non_lr_row_stays_qrre(
        self, config_name: str, request: pytest.FixtureRequest
    ) -> None:
        config = request.getfixturevalue(config_name)
        frame = make_subtypes_frame(cp_entity_type="individual", cp_is_natural_person=True)
        # Fully drawn: no undrawn commitment, non-LR risk_type -> cancellable
        # limb is trivially satisfied.
        frame = frame.with_columns(
            pl.lit(0.0).alias("undrawn_amount"), pl.lit("MR").alias("risk_type")
        )
        out = classify_exposure_subtypes(frame, config).select("exposure_class").collect()
        assert out["exposure_class"][0] == _QRRE
