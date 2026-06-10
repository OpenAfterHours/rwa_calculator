"""
P8.29: transitional alpha add-on acceptance tests — CCR-ALPHA-ADDON-1..4 + 2-NS guard.

Pipeline position:
    Loader -> HierarchyResolver -> CCRStage (apply_wwr_gate / transitional_add_on step
        NOT YET WIRED) -> Classifier -> CRM -> SA Calculator -> OutputAggregator

Key responsibilities:
- Prove that the engine applies the phased transitional alpha add-on under Basel 3.1
  for legacy CVA-exempt trades with non-financial counterparties (α=1.0 base).
- Phase schedule: 60% (2027) / 40% (2028) / 20% (2029) / 0% (2030+).
- Gate conditions for the add-on to fire:
    1. Framework must be Basel 3.1 (NOT CRR).
    2. ``is_legacy_cva_exempt == True`` on trade frame.
    3. ``alpha_applied == 1.0`` (non-financial / pension-scheme carve-out).
    4. Reporting year in {2027, 2028, 2029}; year >= 2030 → add-on = 0.

Expected values strategy:
    The transitional add-on formula is:
        addon_full    = 0.4 × (RC + PFE) = 0.4 × pfe_addon   (RC=0 in CCR-A1 economics)
        EAD_phased    = EAD(α=1.0) + phase × addon_full
                      = EAD(α=1.0) × (1 + 0.4 × phase)
        transitional_add_on = phase × addon_full

    The Basel 3.1 SA-CCR engine computes different PFE values to CRR (different
    supervisory factors) and values also change with remaining maturity as the
    reporting_date advances through 2027-2030.  Expected values are therefore derived
    dynamically from the non-legacy NFC baseline (ADDON-2, same economics, no add-on)
    so they track the actual engine PFE at each reporting date.

    Phase schedule:
        2027: phase = 0.6 → factor = 1 + 0.4×0.6 = 1.24
        2028: phase = 0.4 → factor = 1 + 0.4×0.4 = 1.16
        2029: phase = 0.2 → factor = 1 + 0.4×0.2 = 1.08
        2030: phase = 0.0 → factor = 1.0 (add-on expired)

Load-bearing RED assertions (fail on unfixed engine):
    ADDON-1 (legacy NFC, Basel 3.1 @2027-06-30):
        ``transitional_add_on`` column is absent → row.get(...) == None →
        AssertionError: None != approx(base_pfe × 0.6 × 0.4)
        ``ead_ccr`` == base_ead (no uplift) →
        AssertionError: base_ead != approx(base_ead × 1.24)

    Phasing canary:
        ead(@2027) == ead(@2030) on the unfixed engine (same value — no add-on at
        any year, but maturity-adjusted so not literally equal; however ead(@2027)
        must be GREATER than ead(@2030) after the fix).

    2-NS guard:
        NS-NFC-ADDON-01 transitional_add_on is None → AssertionError: None > 0

Scenarios that pass (regression guards):
    ADDON-2 (non-legacy NFC @2027): add-on must NOT fire (None or 0.0 accepted).
    ADDON-3 (legacy financial @2027): α=1.4 gate excludes the add-on (passes now).
    ADDON-4 (legacy NFC under CRR): framework gate suppresses the add-on (passes now).

References:
    - PRA PS1/26 Art. 274(2A) — transitional alpha add-on (60%/40%/20%)
    - PRA PS1/26 Art. 274(2B) — leverage-ratio exclusion (out of engine scope)
    - CRR Art. 274(2) — EAD = α × (RC + PFE); α=1.4 default; α=1.0 carve-out
    - EMIR Art. 2(9) — non-financial counterparty definition
    - tests/fixtures/ccr/p829_addon_builder.py — P8.29 fixture builders
    - tests/expected_outputs/ccr/CCR-A1.json — authoritative pfe_addon / EAD anchors
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p829_addon_builder import (
    P829_EAD_ALPHA14,
    P829_NS_FIN_LEGACY_ID,
    P829_NS_NFC_LEGACY_ID,
    P829_NS_NFC_NONLEG_ID,
    P829_PFE_ADDON,
    build_p829_bundle,
    build_p829_two_ns_book,
)

# Phase fractions for each reporting year (Art. 274(2A) schedule).
_PHASE = {2027: 0.6, 2028: 0.4, 2029: 0.2, 2030: 0.0}

# Multiplier from EAD(α=1) to transitional EAD:  factor = 1 + 0.4 × phase
_FACTOR = {yr: 1.0 + 0.4 * ph for yr, ph in _PHASE.items()}


# ---------------------------------------------------------------------------
# Config factories — each test controls framework + reporting_date.
# ---------------------------------------------------------------------------


def _b31_config(year: int) -> CalculationConfig:
    """Basel 3.1 config for 30 June of the given year."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(year, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )


def _crr_config(year: int = 2027) -> CalculationConfig:
    """CRR config for 30 June of the given year."""
    return CalculationConfig.crr(
        reporting_date=date(year, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Shared helper: locate the single CCR row for a netting set.
# ---------------------------------------------------------------------------


def _locate_ccr_row(result_bundle, ns_id: str, scenario_label: str) -> dict:
    """
    Locate the single synthetic CCR exposure row for the given netting-set ID.

    The pipeline emits one row per netting set with:
        exposure_reference == "ccr__<ns_id>"

    Fails with a clear assertion message if the row is absent.
    """
    df = result_bundle.results.collect()
    expected_ref = f"ccr__{ns_id}"
    rows = df.filter(pl.col("exposure_reference") == expected_ref).to_dicts()
    assert len(rows) == 1, (
        f"{scenario_label}: expected exactly 1 CCR exposure row with "
        f"exposure_reference={expected_ref!r}, got {len(rows)}. "
        f"All ccr__ references: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures — ADDON-1 (legacy NFC) at all four years.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def addon1_2027_result_bundle():
    """
    CCR-ALPHA-ADDON-1 @ Basel 3.1 2027-06-30 (legacy NFC, α=1.0 base).

    Arrange:
        CP-NFC-ADDON-01 (non_financial, legacy CVA-exempt, corporate)
        NS-NFC-ADDON-01, unmargined, T-NFC-ADDON-01 (CCR-A1 economics).
        Framework: Basel 3.1.  Reporting date: 2027-06-30 (phase = 60%).
    """
    bundle = build_p829_bundle("non_financial", True)
    config = _b31_config(2027)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon1_2028_result_bundle():
    """CCR-ALPHA-ADDON-1 @ Basel 3.1 2028-06-30 (phase = 40%)."""
    bundle = build_p829_bundle("non_financial", True)
    config = _b31_config(2028)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon1_2029_result_bundle():
    """CCR-ALPHA-ADDON-1 @ Basel 3.1 2029-06-30 (phase = 20%)."""
    bundle = build_p829_bundle("non_financial", True)
    config = _b31_config(2029)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon1_2030_result_bundle():
    """CCR-ALPHA-ADDON-1 @ Basel 3.1 2030-06-30 (phase = 0% — add-on expired)."""
    bundle = build_p829_bundle("non_financial", True)
    config = _b31_config(2030)
    return PipelineOrchestrator().run_with_data(bundle, config)


# ADDON-2 (non-legacy NFC, same economics) — provides the base EAD at each year.
# The base EAD is the correctly computed EAD(α=1.0) without any transitional uplift.
# Using ADDON-2 isolates the base from any add-on that might be incorrectly applied.


@pytest.fixture(scope="module")
def addon2_2027_result_bundle():
    """
    CCR-ALPHA-ADDON-2 @ Basel 3.1 2027-06-30 (non-legacy NFC, is_legacy_cva_exempt=False).

    Dual role:
      1.  Control: the add-on must NOT fire — regression guard.
      2.  Baseline: provides the clean EAD(α=1.0) for computing expected transitional EAD.
    """
    bundle = build_p829_bundle("non_financial", False)
    config = _b31_config(2027)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon2_2028_result_bundle():
    """CCR-ALPHA-ADDON-2 @ Basel 3.1 2028-06-30 (non-legacy baseline for 2028 EAD)."""
    bundle = build_p829_bundle("non_financial", False)
    config = _b31_config(2028)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon2_2029_result_bundle():
    """CCR-ALPHA-ADDON-2 @ Basel 3.1 2029-06-30 (non-legacy baseline for 2029 EAD)."""
    bundle = build_p829_bundle("non_financial", False)
    config = _b31_config(2029)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon2_2030_result_bundle():
    """CCR-ALPHA-ADDON-2 @ Basel 3.1 2030-06-30 (non-legacy baseline for 2030 EAD)."""
    bundle = build_p829_bundle("non_financial", False)
    config = _b31_config(2030)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon3_2027_result_bundle():
    """
    CCR-ALPHA-ADDON-3 @ Basel 3.1 2027-06-30 (legacy financial, α=1.4 control).

    The add-on gate requires alpha_applied == 1.0; financial CPs get α=1.4, so the
    add-on must NOT fire.
    """
    bundle = build_p829_bundle("financial", True)
    config = _b31_config(2027)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def addon4_crr_result_bundle():
    """
    CCR-ALPHA-ADDON-4 @ CRR 2027-06-30 (legacy NFC, CRR framework gate).

    The transitional add-on is Basel 3.1-only — it must NOT fire under CRR.
    """
    bundle = build_p829_bundle("non_financial", True)
    config = _crr_config(2027)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def two_ns_2027_result_bundle():
    """
    2-NS regression book @ Basel 3.1 2027-06-30.

    NS-NFC-ADDON-01: legacy, add-on FIRES.
    NS-NFC-ADDON-02: non-legacy, add-on suppressed.
    """
    bundle = build_p829_two_ns_book()
    config = _b31_config(2027)
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# Row-locating fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def addon1_2027_row(addon1_2027_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-01 at 2027-06-30 (ADDON-1, legacy)."""
    return _locate_ccr_row(
        addon1_2027_result_bundle, P829_NS_NFC_LEGACY_ID, "CCR-ALPHA-ADDON-1@2027"
    )


@pytest.fixture(scope="module")
def addon1_2028_row(addon1_2028_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-01 at 2028-06-30."""
    return _locate_ccr_row(
        addon1_2028_result_bundle, P829_NS_NFC_LEGACY_ID, "CCR-ALPHA-ADDON-1@2028"
    )


@pytest.fixture(scope="module")
def addon1_2029_row(addon1_2029_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-01 at 2029-06-30."""
    return _locate_ccr_row(
        addon1_2029_result_bundle, P829_NS_NFC_LEGACY_ID, "CCR-ALPHA-ADDON-1@2029"
    )


@pytest.fixture(scope="module")
def addon1_2030_row(addon1_2030_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-01 at 2030-06-30."""
    return _locate_ccr_row(
        addon1_2030_result_bundle, P829_NS_NFC_LEGACY_ID, "CCR-ALPHA-ADDON-1@2030"
    )


@pytest.fixture(scope="module")
def addon2_2027_row(addon2_2027_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-02 at 2027-06-30 (non-legacy baseline)."""
    return _locate_ccr_row(
        addon2_2027_result_bundle, P829_NS_NFC_NONLEG_ID, "CCR-ALPHA-ADDON-2@2027"
    )


@pytest.fixture(scope="module")
def addon2_2028_row(addon2_2028_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-02 at 2028-06-30 (non-legacy baseline)."""
    return _locate_ccr_row(
        addon2_2028_result_bundle, P829_NS_NFC_NONLEG_ID, "CCR-ALPHA-ADDON-2@2028"
    )


@pytest.fixture(scope="module")
def addon2_2029_row(addon2_2029_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-02 at 2029-06-30 (non-legacy baseline)."""
    return _locate_ccr_row(
        addon2_2029_result_bundle, P829_NS_NFC_NONLEG_ID, "CCR-ALPHA-ADDON-2@2029"
    )


@pytest.fixture(scope="module")
def addon2_2030_row(addon2_2030_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-02 at 2030-06-30 (non-legacy baseline)."""
    return _locate_ccr_row(
        addon2_2030_result_bundle, P829_NS_NFC_NONLEG_ID, "CCR-ALPHA-ADDON-2@2030"
    )


@pytest.fixture(scope="module")
def addon3_2027_row(addon3_2027_result_bundle) -> dict:
    """CCR row for NS-FIN-ADDON-01 at 2027-06-30 (financial α=1.4 control)."""
    return _locate_ccr_row(
        addon3_2027_result_bundle, P829_NS_FIN_LEGACY_ID, "CCR-ALPHA-ADDON-3@2027"
    )


@pytest.fixture(scope="module")
def addon4_crr_row(addon4_crr_result_bundle) -> dict:
    """CCR row for NS-NFC-ADDON-01 under CRR @2027-06-30 (framework gate control)."""
    return _locate_ccr_row(
        addon4_crr_result_bundle, P829_NS_NFC_LEGACY_ID, "CCR-ALPHA-ADDON-4@CRR-2027"
    )


@pytest.fixture(scope="module")
def two_ns_ccr_rows(two_ns_2027_result_bundle) -> list[dict]:
    """All CCR exposure rows from the 2-NS result."""
    df = two_ns_2027_result_bundle.results.collect()
    return df.filter(
        pl.col("exposure_reference").str.starts_with("ccr__")
    ).to_dicts()


# ---------------------------------------------------------------------------
# CCR-ALPHA-ADDON-1: phasing acceptance tests (LOAD-BEARING RED).
#
# Strategy: expected EAD for the legacy row is derived from the non-legacy
# baseline EAD (same trade economics, no add-on) by applying the phase factor.
# This correctly tracks the Basel 3.1 PFE as the trade matures across years.
# ---------------------------------------------------------------------------


class TestCCRAlphaAddon1Phasing:
    """
    CCR-ALPHA-ADDON-1 / P8.29: phasing assertions for the legacy NFC add-on.

    Non-financial legacy CVA-exempt trades (is_legacy_cva_exempt=True, α=1.0) must
    receive a transitional uplift to ead_ccr in 2027-2029, phasing out to zero in 2030.

    Expected EAD is derived from the ADDON-2 non-legacy baseline at each year:
        expected_ead = base_ead × factor     where factor = 1 + 0.4 × phase
        expected_addon = base_ead × 0.4 × phase

    Load-bearing RED assertions (unfixed engine — no transitional add-on):
        ead_ccr(legacy) == ead_ccr(non-legacy) at every year (no uplift applied).
        transitional_add_on absent → row.get(...) == None != approx(non-zero).
    """

    def test_addon1_ead_2027(
        self, addon1_2027_row: dict, addon2_2027_row: dict
    ) -> None:
        """
        ADDON-1 @ 2027-06-30: ead_ccr == base_ead × 1.24 (phase=0.6, factor=1.24).

        Arrange:
            CP-NFC-ADDON-01 (non_financial, legacy=True), NS-NFC-ADDON-01,
            CCR-A1 economics, Basel 3.1 @2027-06-30.
            base_ead from ADDON-2 (same economics, non-legacy, no add-on).
        Act:
            Full Basel 3.1 SA pipeline via PipelineOrchestrator.
        Assert:
            ead_ccr == approx(base_ead × 1.24, rel=1e-6).

        This is the primary load-bearing RED assertion for P8.29 @2027.
        The unfixed engine applies no transitional add-on:
            ead_ccr(legacy) == ead_ccr(non-legacy) == base_ead (no uplift).

        Expected failure mode on the unfixed engine:
            assert base_ead == approx(base_ead × 1.24 ± ...)
            i.e. approximately 3_456_960.73 == 4_286_631.30  (3.44M vs 4.29M)

        References:
            PRA PS1/26 Art. 274(2A) — 60% transitional add-on in 2027.
        """
        # Arrange — derive expected EAD from baseline
        base_ead = addon2_2027_row["ead_ccr"]
        expected_ead = base_ead * _FACTOR[2027]  # × 1.24

        # Assert
        actual_ead = addon1_2027_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2027: expected ead_ccr={expected_ead:,.5f} "
            f"(base_ead={base_ead:,.5f} × 1.24 — 60% transitional uplift), "
            f"got {actual_ead:,.5f}. "
            f"Unfixed engine: no transitional add-on → ead_ccr(legacy)==ead_ccr(non-legacy)="
            f"{base_ead:,.3f}. "
            "P8.29 fix: apply phase=0.6 × 0.4 × (RC+PFE) to ead_ccr for Basel 3.1 "
            "@2027 when is_legacy_cva_exempt=True and alpha_applied=1.0. "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon1_ead_2028(
        self, addon1_2028_row: dict, addon2_2028_row: dict
    ) -> None:
        """
        ADDON-1 @ 2028-06-30: ead_ccr == base_ead × 1.16 (phase=0.4, factor=1.16).

        Arrange:
            Same scenario run under Basel 3.1 @2028-06-30.
        Act:
            Full Basel 3.1 SA pipeline.
        Assert:
            ead_ccr == approx(base_ead × 1.16, rel=1e-6).

        Expected failure on unfixed engine: ead(legacy)==ead(non-legacy)=base_ead.

        References: PRA PS1/26 Art. 274(2A) — 40% transitional add-on in 2028.
        """
        # Arrange
        base_ead = addon2_2028_row["ead_ccr"]
        expected_ead = base_ead * _FACTOR[2028]  # × 1.16

        # Assert
        actual_ead = addon1_2028_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2028: expected ead_ccr={expected_ead:,.5f} "
            f"(base_ead={base_ead:,.5f} × 1.16, phase=0.4), got {actual_ead:,.5f}. "
            f"Unfixed engine: no add-on → ead_ccr(legacy)==ead_ccr(non-legacy). "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon1_ead_2029(
        self, addon1_2029_row: dict, addon2_2029_row: dict
    ) -> None:
        """
        ADDON-1 @ 2029-06-30: ead_ccr == base_ead × 1.08 (phase=0.2, factor=1.08).

        Arrange:
            Same scenario run under Basel 3.1 @2029-06-30.
        Act:
            Full Basel 3.1 SA pipeline.
        Assert:
            ead_ccr == approx(base_ead × 1.08, rel=1e-6).

        Expected failure on unfixed engine: ead(legacy)==ead(non-legacy)=base_ead.

        References: PRA PS1/26 Art. 274(2A) — 20% transitional add-on in 2029.
        """
        # Arrange
        base_ead = addon2_2029_row["ead_ccr"]
        expected_ead = base_ead * _FACTOR[2029]  # × 1.08

        # Assert
        actual_ead = addon1_2029_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2029: expected ead_ccr={expected_ead:,.5f} "
            f"(base_ead={base_ead:,.5f} × 1.08, phase=0.2), got {actual_ead:,.5f}. "
            f"Unfixed engine: no add-on → ead_ccr(legacy)==ead_ccr(non-legacy). "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon1_ead_2030(
        self, addon1_2030_row: dict, addon2_2030_row: dict
    ) -> None:
        """
        ADDON-1 @ 2030-06-30: ead_ccr == base_ead (phase=0.0 — add-on expired).

        In 2030 the transitional period has ended (phase=0), so the add-on is zero
        and ead_ccr must equal the non-legacy baseline (same economics, no uplift).

        This assertion PASSES on the unfixed engine (legacy == non-legacy for all years
        since no add-on is applied).  It is a regression guard that the phasing
        schedule terminates correctly.

        References: PRA PS1/26 Art. 274(2A) — phase=0 from 1 Jan 2030.
        """
        # Arrange
        base_ead = addon2_2030_row["ead_ccr"]
        expected_ead = base_ead  # factor = 1.00

        # Assert
        actual_ead = addon1_2030_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2030: expected ead_ccr={expected_ead:,.3f} "
            f"(phase=0, equals non-legacy baseline), got {actual_ead:,.3f}. "
            "PRA PS1/26 Art. 274(2A): add-on fully phased out by 2030."
        )

    def test_addon1_transitional_add_on_2027(
        self, addon1_2027_row: dict, addon2_2027_row: dict
    ) -> None:
        """
        ADDON-1 @ 2027-06-30: transitional_add_on == base_ead × 0.4 × 0.6.

        The ``transitional_add_on`` column (new in P8.29) must be emitted by the engine
        and contain the phased add-on amount: phase × addon_full = 0.6 × 0.4 × (RC+PFE).

        Read defensively via row.get("transitional_add_on") so the unfixed engine
        fails with a clean AssertionError (None != non-zero), NOT a KeyError.

        Expected failure mode on the unfixed engine (column absent):
            assert None == approx(base_ead × 0.24 ± ...)

        References: PRA PS1/26 Art. 274(2A).
        """
        # Arrange — expected add-on = phase × addon_full = 0.6 × 0.4 × base_ead
        base_ead = addon2_2027_row["ead_ccr"]
        expected_addon = base_ead * 0.4 * _PHASE[2027]  # 0.4 × 0.6 = 0.24

        # Assert
        actual_addon = addon1_2027_row.get("transitional_add_on")
        assert actual_addon == pytest.approx(expected_addon, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2027: expected transitional_add_on={expected_addon:,.5f} "
            f"(0.6 × 0.4 × base_ead={base_ead:,.5f}), got {actual_addon!r}. "
            "Column 'transitional_add_on' is not yet emitted by the engine. "
            "P8.29 fix: add transitional_add_on column to the CCR synthetic row "
            "(phase × addon_full for Basel 3.1 2027-29, 0.0 otherwise). "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon1_transitional_add_on_2028(
        self, addon1_2028_row: dict, addon2_2028_row: dict
    ) -> None:
        """
        ADDON-1 @ 2028-06-30: transitional_add_on == base_ead × 0.4 × 0.4 (phase=0.4).

        Defensive .get() — unfixed engine: None != non-zero value.

        References: PRA PS1/26 Art. 274(2A).
        """
        # Arrange
        base_ead = addon2_2028_row["ead_ccr"]
        expected_addon = base_ead * 0.4 * _PHASE[2028]  # 0.4 × 0.4 = 0.16

        # Assert
        actual_addon = addon1_2028_row.get("transitional_add_on")
        assert actual_addon == pytest.approx(expected_addon, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2028: expected transitional_add_on={expected_addon:,.5f} "
            f"(0.4 × 0.4 × base_ead={base_ead:,.5f}), got {actual_addon!r}. "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon1_transitional_add_on_2029(
        self, addon1_2029_row: dict, addon2_2029_row: dict
    ) -> None:
        """
        ADDON-1 @ 2029-06-30: transitional_add_on == base_ead × 0.4 × 0.2 (phase=0.2).

        Defensive .get() — unfixed engine: None != non-zero value.

        References: PRA PS1/26 Art. 274(2A).
        """
        # Arrange
        base_ead = addon2_2029_row["ead_ccr"]
        expected_addon = base_ead * 0.4 * _PHASE[2029]  # 0.4 × 0.2 = 0.08

        # Assert
        actual_addon = addon1_2029_row.get("transitional_add_on")
        assert actual_addon == pytest.approx(expected_addon, rel=1e-6), (
            f"CCR-ALPHA-ADDON-1 @2029: expected transitional_add_on={expected_addon:,.5f} "
            f"(0.2 × 0.4 × base_ead={base_ead:,.5f}), got {actual_addon!r}. "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon1_transitional_add_on_2030_is_zero(self, addon1_2030_row: dict) -> None:
        """
        ADDON-1 @ 2030-06-30: transitional_add_on == 0.0 (phase expired).

        The column must be present and zero in 2030 (or absent, treated as 0).
        This assertion passes on the unfixed engine (no column → None accepted).

        References: PRA PS1/26 Art. 274(2A) — no add-on from 2030 onwards.
        """
        # Assert — accept None or 0.0 for 2030 (phase expired)
        actual_addon = addon1_2030_row.get("transitional_add_on")
        assert actual_addon is None or actual_addon == pytest.approx(0.0, abs=1e-9), (
            f"CCR-ALPHA-ADDON-1 @2030: expected transitional_add_on==0.0 or absent "
            f"(phase=0, add-on expired), got {actual_addon!r}. "
            "PRA PS1/26 Art. 274(2A): no add-on from 2030 onwards."
        )

    def test_addon1_ead_final_equals_ead_ccr_2027(self, addon1_2027_row: dict) -> None:
        """
        ADDON-1 @ 2027: ead_final == ead_ccr — EAD not further mutated after transitional step.

        The transitional add-on must be folded into ead_ccr; ead_final is a pass-through.
        This assertion passes on the unfixed engine (both equal the base EAD) and guards
        against the implementer updating ead_ccr but not propagating to ead_final.

        References: standard pipeline EAD propagation; PRA PS1/26 Art. 274(2A).
        """
        # Arrange / Act
        ead_ccr = addon1_2027_row["ead_ccr"]
        ead_final = addon1_2027_row["ead_final"]

        # Assert
        assert ead_final == pytest.approx(ead_ccr, rel=1e-9), (
            f"CCR-ALPHA-ADDON-1 @2027: ead_final ({ead_final:,.5f}) must equal "
            f"ead_ccr ({ead_ccr:,.5f}). "
            "The transitional add-on must be folded into ead_ccr; ead_final must not "
            "be further mutated."
        )

    def test_addon1_pfe_addon_unchanged_2027(
        self, addon1_2027_row: dict, addon2_2027_row: dict
    ) -> None:
        """
        ADDON-1 @ 2027: pfe_addon == pfe_addon(non-legacy) — unaffected by transitional step.

        pfe_addon is computed before α scaling and must not be modified by the
        transitional add-on step.  Both the legacy and non-legacy paths use the same
        trade economics so their pfe_addon values must be identical.

        This assertion passes on the unfixed engine.

        References: CRR Art. 278 — PFE; Art. 280a — SF_IR.
        """
        # Arrange
        base_pfe = addon2_2027_row["pfe_addon"]

        # Assert
        actual_pfe = addon1_2027_row["pfe_addon"]
        assert actual_pfe == pytest.approx(base_pfe, rel=1e-9), (
            f"CCR-ALPHA-ADDON-1 @2027: expected pfe_addon={base_pfe:,.5f} (same as non-legacy "
            f"baseline), got {actual_pfe:,.5f}. "
            "pfe_addon is α-independent and must not be mutated by the transitional step."
        )


# ---------------------------------------------------------------------------
# Strict phasing canary — cross-year invariants.
# ---------------------------------------------------------------------------


class TestCCRAlphaAddon1PhasingCanary:
    """
    Cross-year canary: legacy ead(@2027) > non-legacy ead(@2027) and ratio check.

    These are the simplest cross-year assertions and catch the case where the
    engine applies no add-on (legacy EAD == non-legacy EAD at every year).

    Canary 1 (LOAD-BEARING RED):
        ead_legacy(@2027) > ead_nonlegacy(@2027) STRICT.
        Unfixed: both equal base_ead (no uplift) → AssertionError: not (x > x)

    Canary 2 (LOAD-BEARING RED):
        ead_legacy(@2027) / ead_nonlegacy(@2027) == approx(1.24, rel=1e-9).
        Unfixed: ratio == 1.0 → AssertionError: 1.0 != approx(1.24)
    """

    def test_legacy_ead_2027_strictly_greater_than_nonlegacy_ead_2027(
        self,
        addon1_2027_row: dict,
        addon2_2027_row: dict,
    ) -> None:
        """
        ead(legacy @2027) > ead(non-legacy @2027) STRICT.

        Legacy (ADDON-1) has phase=0.6 uplift; non-legacy (ADDON-2) has no uplift.
        Same trade economics, so the only difference is the transitional add-on.
        On the unfixed engine both equal the same base_ead → strict inequality fails.

        References: PRA PS1/26 Art. 274(2A).
        """
        # Act
        ead_legacy = addon1_2027_row["ead_ccr"]
        ead_nonlegacy = addon2_2027_row["ead_ccr"]

        # Assert
        assert ead_legacy > ead_nonlegacy, (
            f"CCR-ALPHA-ADDON-1 phasing canary: ead(legacy @2027) must be STRICTLY greater "
            f"than ead(non-legacy @2027). Got ead_legacy={ead_legacy:,.5f}, "
            f"ead_nonlegacy={ead_nonlegacy:,.5f}. "
            f"Unfixed engine: no add-on → both equal {ead_nonlegacy:,.3f}. "
            f"After P8.29 fix: ead_legacy = ead_nonlegacy × 1.24 (phase=0.6). "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_legacy_to_nonlegacy_ead_ratio_2027(
        self,
        addon1_2027_row: dict,
        addon2_2027_row: dict,
    ) -> None:
        """
        ead(legacy @2027) / ead(non-legacy @2027) == approx(1.24, rel=1e-9).

        Factor = 1 + 0.4 × phase = 1 + 0.4 × 0.6 = 1.24.
        Unfixed engine: both EADs equal → ratio == 1.0.

        Expected failure: assert 1.0 == approx(1.24, rel=1e-9)

        References: PRA PS1/26 Art. 274(2A).
        """
        # Arrange
        expected_ratio = _FACTOR[2027]  # 1.24

        # Act
        ead_legacy = addon1_2027_row["ead_ccr"]
        ead_nonlegacy = addon2_2027_row["ead_ccr"]
        actual_ratio = ead_legacy / ead_nonlegacy

        # Assert
        assert actual_ratio == pytest.approx(expected_ratio, rel=1e-9), (
            f"CCR-ALPHA-ADDON-1 @2027 ratio canary: expected ead(legacy)/ead(non-legacy) == "
            f"{expected_ratio} (= 1 + 0.4×0.6), got {actual_ratio:.9f}. "
            f"ead_legacy={ead_legacy:,.5f}, ead_nonlegacy={ead_nonlegacy:,.5f}. "
            f"Unfixed engine: ratio=1.0 (no uplift). "
            "PRA PS1/26 Art. 274(2A)."
        )


# ---------------------------------------------------------------------------
# CCR-ALPHA-ADDON-2: non-legacy NFC control (add-on must NOT fire).
# ---------------------------------------------------------------------------


class TestCCRAlphaAddon2NonLegacyControl:
    """
    CCR-ALPHA-ADDON-2 / P8.29: non-legacy NFC control — add-on must NOT fire.

    is_legacy_cva_exempt=False → gate closed → transitional_add_on == 0.

    This scenario PASSES on the unfixed engine (no add-on exists for either path).
    It is a regression guard that the add-on does NOT fire for non-legacy trades
    once the P8.29 fix is implemented.

    Expected behaviour:
        ead_ccr == pfe_addon (α=1.0, no transitional uplift)
        transitional_add_on == 0.0 (or absent → None → accepted)
    """

    def test_addon2_transitional_add_on_is_zero(self, addon2_2027_row: dict) -> None:
        """
        ADDON-2 @ 2027: transitional_add_on == 0.0 (non-legacy → add-on gate closed).

        Defensive .get() — None is accepted as equivalent to 0.0 here since the
        engine does not yet emit the column.  Post-fix: must be explicitly 0.0.

        This assertion PASSES on the unfixed engine (column absent → None accepted).

        References: PRA PS1/26 Art. 274(2A).
        """
        # Assert — accept None or 0.0 for non-legacy trades
        actual_addon = addon2_2027_row.get("transitional_add_on")
        assert actual_addon is None or actual_addon == pytest.approx(0.0, abs=1e-9), (
            f"CCR-ALPHA-ADDON-2 @2027: transitional_add_on must be 0.0 or absent "
            f"(non-legacy trade, gate closed), got {actual_addon!r}. "
            "PRA PS1/26 Art. 274(2A)."
        )


# ---------------------------------------------------------------------------
# CCR-ALPHA-ADDON-3: legacy financial control (α=1.4 gate excludes add-on).
# ---------------------------------------------------------------------------


class TestCCRAlphaAddon3FinancialControl:
    """
    CCR-ALPHA-ADDON-3 / P8.29: legacy financial CP — add-on must NOT fire.

    The transitional add-on gate requires alpha_applied == 1.0.  Financial
    counterparties receive α=1.4, so the gate is FALSE even if is_legacy_cva_exempt
    is True.

    Expected behaviour:
        ead_ccr == α=1.4 × pfe_addon (no additional transitional add-on)
        transitional_add_on == 0.0 or absent

    Both assertions PASS on the unfixed engine.
    """

    def test_addon3_ead_equals_alpha14_base(self, addon3_2027_row: dict) -> None:
        """
        ADDON-3 @ 2027: ead_ccr == 1.4 × pfe_addon (α=1.4, no transitional add-on).

        Arrange:
            CP-FIN-ADDON-01 (financial, is_legacy_cva_exempt=True), NS-FIN-ADDON-01,
            CCR-A1 economics, Basel 3.1 @2027-06-30.
        Act:
            Full Basel 3.1 SA pipeline.
        Assert:
            ead_ccr == approx(1.4 × pfe_addon, rel=1e-6).

        This PASSES on the unfixed engine.  Post-fix regression guard:
        the α=1.4 gate must exclude the transitional add-on even for legacy trades.

        References:
            CRR Art. 274(2) — α=1.4 for financial CPs.
            PRA PS1/26 Art. 274(2A) — gate: alpha_applied==1.0 required.
        """
        # Arrange — expected EAD is α=1.4 × pfe_addon
        pfe = addon3_2027_row["pfe_addon"]
        expected_ead = pfe * 1.4

        # Assert
        actual_ead = addon3_2027_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-ADDON-3 @2027: expected ead_ccr={expected_ead:,.3f} "
            f"(1.4 × pfe_addon={pfe:,.3f}, no transitional add-on), got {actual_ead:,.3f}. "
            "The transitional add-on gate (alpha_applied==1.0) must exclude "
            "financial counterparties (α=1.4). "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_addon3_transitional_add_on_is_zero(self, addon3_2027_row: dict) -> None:
        """
        ADDON-3 @ 2027: transitional_add_on == 0.0 (α=1.4 gate closed).

        Defensive .get() — None accepted as 0.0 (engine emits no column yet).

        References: PRA PS1/26 Art. 274(2A).
        """
        # Assert
        actual_addon = addon3_2027_row.get("transitional_add_on")
        assert actual_addon is None or actual_addon == pytest.approx(0.0, abs=1e-9), (
            f"CCR-ALPHA-ADDON-3 @2027: transitional_add_on must be 0.0 or absent "
            f"(financial CP, α=1.4 gate closed), got {actual_addon!r}. "
            "PRA PS1/26 Art. 274(2A): gate requires alpha_applied==1.0."
        )


# ---------------------------------------------------------------------------
# CCR-ALPHA-ADDON-4: CRR framework gate (add-on must NOT fire under CRR).
# ---------------------------------------------------------------------------


class TestCCRAlphaAddon4FrameworkGate:
    """
    CCR-ALPHA-ADDON-4 / P8.29: legacy NFC under CRR — framework gate suppresses add-on.

    The transitional add-on is PS1/26 / Basel 3.1 only.  Under CRR the add-on must
    never fire regardless of is_legacy_cva_exempt or counterparty_type.

    Expected behaviour:
        ead_ccr == α=1.0 × pfe_addon (CRR carve-out, no transitional uplift)
        transitional_add_on == 0.0 or absent

    Both assertions PASS on the unfixed engine.
    """

    def test_addon4_ead_equals_pfe_under_crr(self, addon4_crr_row: dict) -> None:
        """
        ADDON-4 @ CRR 2027: ead_ccr == 1.0 × pfe_addon (α=1.0 carve-out, no add-on).

        Arrange:
            CP-NFC-ADDON-01 (non_financial, is_legacy_cva_exempt=True), NS-NFC-ADDON-01,
            CCR-A1 economics, CRR framework @2027-06-30.
        Act:
            Full CRR SA pipeline (framework = CRR, NOT Basel 3.1).
        Assert:
            ead_ccr == approx(pfe_addon, rel=1e-9) — EAD equals PFE since RC=0 and α=1.0.

        This PASSES on the unfixed engine.  Post-fix regression guard:
        CRR framework must suppress the transitional add-on.

        References:
            CRR Art. 274(2) — EAD = α × (RC + PFE), no transitional provision.
            PRA PS1/26 Art. 274(2A) — Basel 3.1 only.
        """
        # Arrange — under CRR α=1.0 carve-out: EAD = pfe_addon (RC=0)
        pfe = addon4_crr_row["pfe_addon"]
        expected_ead = pfe * 1.0

        # Assert
        actual_ead = addon4_crr_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-9), (
            f"CCR-ALPHA-ADDON-4 @CRR-2027: expected ead_ccr={expected_ead:,.3f} "
            f"(CRR framework, α=1.0 × pfe={pfe:,.3f}), got {actual_ead:,.3f}. "
            "The transitional add-on is Basel 3.1 only (PRA PS1/26 Art. 274(2A)). "
            "CRR does not have an Art. 274(2A) provision."
        )

    def test_addon4_transitional_add_on_is_zero_under_crr(
        self, addon4_crr_row: dict
    ) -> None:
        """
        ADDON-4 @ CRR 2027: transitional_add_on == 0.0 (CRR framework gate closed).

        Defensive .get() — None accepted as 0.0 here.

        References: PRA PS1/26 Art. 274(2A) — Basel 3.1 only.
        """
        # Assert
        actual_addon = addon4_crr_row.get("transitional_add_on")
        assert actual_addon is None or actual_addon == pytest.approx(0.0, abs=1e-9), (
            f"CCR-ALPHA-ADDON-4 @CRR-2027: transitional_add_on must be 0.0 or absent "
            f"(CRR framework gate closed), got {actual_addon!r}. "
            "PRA PS1/26 Art. 274(2A) is Basel 3.1 only."
        )


# ---------------------------------------------------------------------------
# 2-NS keyed-join guard.
# ---------------------------------------------------------------------------


class TestCCRAlphaAddonTwoNsKeyedJoinGuard:
    """
    2-NS keyed-join regression guard / P8.29: add-on per-NS collapse.

    WHY single-NS fixtures cannot catch fan-out:
        The 1×1×1 per-scenario tests (CCR-ALPHA-ADDON-1..4) each have one trade per
        NS. A per-trade→per-NS collapse of ``any(is_legacy_cva_exempt)`` that is
        implemented as a cross-join (counterparties × netting_sets) would produce:
          - 1 NS × 1 CP → 1 row — indistinguishable from a correct keyed join.
        This 2-NS book (NS-NFC-ADDON-01: legacy=True, NS-NFC-ADDON-02: legacy=False)
        exposes the bug:
          - Cross-join: 2 NS × 2 CP → 4 rows (fan-out).
          - Correct keyed join: 2 NS × 1 matched CP each → 2 rows.
        Even if the cross-join degenerate-projects back to 2 rows, the legacy flag
        from NS-01 would pollute NS-02, causing NS-02's add-on to fire incorrectly.

    Load-bearing RED assertions:
        Row-count == 2  — passes on unfixed engine (no fan-out in existing join).
        NS-NFC-ADDON-01 transitional_add_on > 0  — FAILS (None not > 0).
        NS-NFC-ADDON-02 transitional_add_on == 0 — passes (None accepted as 0).
    """

    def test_two_ns_book_produces_exactly_two_ccr_rows(
        self, two_ns_ccr_rows: list[dict]
    ) -> None:
        """
        Exactly 2 CCR exposure rows in the 2-NS book.

        Arrange:
            2 netting sets (NS-NFC-ADDON-01: legacy=True, NS-NFC-ADDON-02: legacy=False),
            2 counterparties (both non_financial), 2 trades.
        Act:
            Full Basel 3.1 SA pipeline @2027-06-30.
        Assert:
            Exactly 2 rows with exposure_reference starting with "ccr__".

        A cross-join fan-out in the legacy flag → NS join would produce 4 rows.
        The single-NS scenarios (1×1×1) cannot catch this — only a 2-NS book can.

        References: standard pipeline — one EAD row per netting set.
        """
        # Arrange
        expected_count = 2

        # Assert
        actual_count = len(two_ns_ccr_rows)
        assert actual_count == expected_count, (
            f"CCR-ALPHA-ADDON 2-NS guard: expected {expected_count} CCR rows "
            f"(one per netting set), got {actual_count}. "
            f"NS refs found: {[r.get('exposure_reference') for r in two_ns_ccr_rows]!r}. "
            f"A cross-join of is_legacy_cva_exempt collapse × netting-sets would "
            f"produce {expected_count * expected_count} rows for a {expected_count}-NS book. "
            "Single-NS (1×1×1) scenarios cannot catch this fan-out. "
            "P8.29 fix: aggregate is_legacy_cva_exempt keyed by netting_set_id "
            "before the per-NS add-on computation."
        )

    def test_two_ns_legacy_ns_has_positive_transitional_add_on(
        self, two_ns_ccr_rows: list[dict]
    ) -> None:
        """
        NS-NFC-ADDON-01 (legacy=True) in the 2-NS book: transitional_add_on > 0.

        This is the LOAD-BEARING RED assertion for the 2-NS guard.
        On the unfixed engine the column is absent → row.get(...) == None →
        AssertionError: (None is not None) evaluates to False.

        Read defensively via row.get("transitional_add_on").

        References: PRA PS1/26 Art. 274(2A).
        """
        # Arrange: locate the legacy NS row
        legacy_rows = [
            r for r in two_ns_ccr_rows
            if r.get("exposure_reference") == f"ccr__{P829_NS_NFC_LEGACY_ID}"
        ]
        assert len(legacy_rows) == 1, (
            f"CCR-ALPHA-ADDON 2-NS guard: expected 1 row for NS {P829_NS_NFC_LEGACY_ID!r}, "
            f"got {len(legacy_rows)}. "
            f"All refs: {[r.get('exposure_reference') for r in two_ns_ccr_rows]!r}."
        )
        row = legacy_rows[0]

        # Assert
        actual_addon = row.get("transitional_add_on")
        assert actual_addon is not None and actual_addon > 0, (
            f"CCR-ALPHA-ADDON 2-NS guard: NS {P829_NS_NFC_LEGACY_ID!r} (legacy=True) "
            f"must have transitional_add_on > 0 at Basel 3.1 @2027-06-30. "
            f"Got transitional_add_on={actual_addon!r}. "
            "The unfixed engine does not emit 'transitional_add_on' → None is not > 0. "
            "P8.29 fix: per-NS any(is_legacy_cva_exempt) collapse must be keyed by "
            "netting_set_id so NS-01 (legacy) gets add-on and NS-02 (non-legacy) does not. "
            "PRA PS1/26 Art. 274(2A)."
        )

    def test_two_ns_nonlegacy_ns_has_zero_transitional_add_on(
        self, two_ns_ccr_rows: list[dict]
    ) -> None:
        """
        NS-NFC-ADDON-02 (legacy=False) in the 2-NS book: transitional_add_on == 0.0.

        Non-legacy NS must not receive add-on.  If the per-NS collapse is
        implemented as a cross-join, the legacy=True flag from NS-01 would
        pollute NS-02, causing this to fail even after the add-on is wired.

        Defensive .get() — None accepted as 0.0.

        References: PRA PS1/26 Art. 274(2A).
        """
        # Arrange: locate the non-legacy NS row
        nonleg_rows = [
            r for r in two_ns_ccr_rows
            if r.get("exposure_reference") == f"ccr__{P829_NS_NFC_NONLEG_ID}"
        ]
        assert len(nonleg_rows) == 1, (
            f"CCR-ALPHA-ADDON 2-NS guard: expected 1 row for NS {P829_NS_NFC_NONLEG_ID!r}, "
            f"got {len(nonleg_rows)}. "
            f"All refs: {[r.get('exposure_reference') for r in two_ns_ccr_rows]!r}."
        )
        row = nonleg_rows[0]

        # Assert
        actual_addon = row.get("transitional_add_on")
        assert actual_addon is None or actual_addon == pytest.approx(0.0, abs=1e-9), (
            f"CCR-ALPHA-ADDON 2-NS guard: NS {P829_NS_NFC_NONLEG_ID!r} (legacy=False) "
            f"must have transitional_add_on == 0.0 or absent. "
            f"Got {actual_addon!r}. "
            "If a cross-join leaks legacy=True from NS-01 to NS-02, this fails post-fix. "
            "PRA PS1/26 Art. 274(2A)."
        )
