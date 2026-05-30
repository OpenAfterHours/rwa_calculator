"""
P2.31 / CRR-A.CCF11 — Annex I concrete-product to ``risk_type`` mapping.

Scenario:
    CRR Annex I and PRA PS1/26 Table A1 define CCF bands by abstract ``risk_type``
    (FR / MR / MLR / LR).  No data-layer table currently maps concrete OBS *product
    descriptions* (e.g. "ACCEPTANCE", "PERFORMANCE_BOND") to those bands.  P2.31
    adds a framework-invariant ``ANNEX1_PRODUCT_RISK_TYPE`` lookup and a fill step
    in ``engine/ccf.py`` that resolves ``risk_type`` from ``obs_product`` whenever
    ``risk_type`` is null/empty.  Explicit ``risk_type`` always wins (backward
    compatible).

Regulatory citations:
    - CRR (EU 575/2013) Annex I paras 1–4: OBS risk bands by category.
    - CRR Art. 111(1): SA EAD = drawn + CCF × undrawn.
    - PRA PS1/26 App 1, Art. 111(1) Table A1 Row 1 (FR 100%) and Row 6(a)/(b)
      (MLR 20%) — docs/assets/ps126app1.pdf pp.29–32.

Exposures under test (all contingents, nominal £2,000,000 each, CRR config):

    CONT_P231_ACCEPT (P2.31-FR — load-bearing):
        obs_product="ACCEPTANCE", risk_type=None
        Expected: resolved risk_type="FR", ccf=1.00, ead_from_ccf=2_000_000
        Pre-fix:  risk_type=null (pass-through), ccf=0.50, ead_from_ccf=1_000_000

    CONT_P231_PERFBOND (P2.31-MLR-PERFBOND):
        obs_product="PERFORMANCE_BOND", risk_type=None
        Expected: resolved risk_type="MLR", ccf=0.20, ead_from_ccf=400_000
        Pre-fix:  risk_type=null (pass-through), ccf=0.50, ead_from_ccf=1_000_000

    CONT_P231_DOCLC (P2.31-MLR-DOCLC):
        obs_product="DOCUMENTARY_CREDIT", risk_type=None
        Expected: resolved risk_type="MLR", ccf=0.20, ead_from_ccf=400_000
        Pre-fix:  risk_type=null (pass-through), ccf=0.50, ead_from_ccf=1_000_000

    CONT_P231_OVERRIDE (P2.31-LR-OVERRIDE — regression guard):
        obs_product="ACCEPTANCE", risk_type="LR" (explicit wins)
        Expected: retained risk_type="LR", ccf=0.00, ead_from_ccf=0
        Pre-fix:  PASSES (explicit LR already routes correctly)

Test strategy:
    Import the four rows from ``create_p231_contingents()`` (which carries the
    new ``obs_product`` column) and run them directly through
    ``CCFCalculator.apply_ccf()``.  This mirrors the P2.32 / P2.33 CCF-stage-
    isolated harness and ensures ``obs_product`` reaches the engine without passing
    through the loader (which would silently drop any not-yet-schema-registered
    column).

    Load-bearing failure: the ACCEPTANCE row currently falls to the SA default
    CCF (no ``risk_type`` → null → empty string → default MR-equivalent 0.50).
    After the engine-implementer adds the ``ANNEX1_PRODUCT_RISK_TYPE`` fill,
    the row resolves FR → 1.00 → EAD 2,000,000.

References:
    - CRR Annex I para 1 / PS1/26 Table A1 Row 1: acceptances → FR (100%)
    - CRR Annex I Row 6(a) / PS1/26 Table A1 Row 6(a): documentary credits → MLR (20%)
    - CRR Annex I Row 6(b) / PS1/26 Table A1 Row 6(b): performance bonds → MLR (20%)
    - src/rwa_calc/data/tables/ccf.py: SA_CCF_CRR["FR"]=1.00, SA_CCF_CRR["MLR"]=0.20,
      SA_CCF_CRR["LR"]=0.00
    - tests/fixtures/p2_31/p2_31.py: scenario constants and factory functions
"""

from __future__ import annotations

from datetime import date
from typing import cast

import polars as pl
import pytest
from tests.fixtures.p2_31.p2_31 import (
    CONT_REF_ACCEPT,
    CONT_REF_DOCLC,
    CONT_REF_OVERRIDE,
    CONT_REF_PERFBOND,
    EXPECTED_CCF_ACCEPT,
    EXPECTED_CCF_DOCLC,
    EXPECTED_CCF_OVERRIDE,
    EXPECTED_CCF_PERFBOND,
    EXPECTED_EAD_ACCEPT,
    EXPECTED_EAD_DOCLC,
    EXPECTED_EAD_OVERRIDE,
    EXPECTED_EAD_PERFBOND,
    RESOLVED_RISK_TYPE_ACCEPT,
    RESOLVED_RISK_TYPE_OVERRIDE,
    SCENARIO_ID,
    create_p231_contingents,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator

# ---------------------------------------------------------------------------
# Module-scoped fixture: run CCF stage once for all test classes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_31_crr_ccf_results() -> pl.DataFrame:
    """
    Load P2.31 contingent factory rows and run them through CCFCalculator (CRR).

    The contingent DataFrame is produced by ``create_p231_contingents()``, which
    carries the new ``obs_product`` String column directly (injected via
    ``with_columns``, matching the P2.32 / P2.33 precedent).  The column is NOT
    yet in CONTINGENTS_SCHEMA (engine-implementer adds it), but it survives the
    CCF stage because ``apply_ccf`` preserves unknown extra columns.

    Pre-pipeline column setup:
        ``CCFCalculator.apply_ccf`` expects ``nominal_amount`` (already in the
        fixture) and ``drawn_amount`` (not present — added as 0.0 here, matching
        fully-undrawn contingent semantics).

    Pre-fix behaviour (engine ignores ``obs_product``):
        CONT_P231_ACCEPT    → ccf = 0.50  (null risk_type → MR default)
        CONT_P231_PERFBOND  → ccf = 0.50  (null risk_type → MR default)
        CONT_P231_DOCLC     → ccf = 0.50  (null risk_type → MR default)
        CONT_P231_OVERRIDE  → ccf = 0.00  (explicit LR — already correct)

    Returns:
        Collected DataFrame with CCF output columns (ccf, ead_from_ccf, risk_type).
    """
    # Arrange — build contingent LazyFrame from factory (includes obs_product)
    contingents_lf = (
        create_p231_contingents()
        .lazy()
        .with_columns(
            pl.lit(0.0).alias("drawn_amount"),
        )
    )

    config = CalculationConfig.crr(reporting_date=date(2027, 1, 1))
    calculator = CCFCalculator()

    # Act — apply CCF stage directly (no full pipeline needed)
    result_lf = calculator.apply_ccf(contingents_lf, config)

    return cast(pl.DataFrame, result_lf.collect())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row(df: pl.DataFrame, cont_ref: str) -> dict:
    """Return the single result row for ``cont_ref``, or raise for a clear error."""
    rows = df.filter(pl.col("contingent_reference") == cont_ref).to_dicts()
    assert len(rows) == 1, (
        f"{SCENARIO_ID}: expected exactly 1 row for contingent_reference={cont_ref!r}, "
        f"got {len(rows)}. Available: {df['contingent_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Test class — ACCEPTANCE row (CONT_P231_ACCEPT) — LOAD-BEARING
# ---------------------------------------------------------------------------


class TestP231AcceptanceFRMapping:
    """
    P2.31 ACCEPTANCE row: obs_product="ACCEPTANCE", risk_type=None.

    The engine must resolve risk_type="FR" from obs_product and apply
    SA_CCF_CRR["FR"] = 1.00.

    Pre-fix: ccf = 0.50 (null risk_type falls to MR default), EAD = 1_000_000.
    All assertions in this class FAIL until the engine adds the
    ANNEX1_PRODUCT_RISK_TYPE fill in engine/ccf.py.

    References:
        - CRR Annex I para 1 / PS1/26 Table A1 Row 1: acceptances → FR (100%)
    """

    def test_p2_31_acceptance_resolves_risk_type_fr(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        ACCEPTANCE: engine resolves risk_type = "FR" from obs_product.

        Arrange: CONT_P231_ACCEPT, obs_product=ACCEPTANCE, risk_type=None,
                 nominal_amount=2_000_000, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  risk_type == "FR".

        Pre-fix failure: risk_type is None (obs_product ignored — no fill logic).

        References:
            CRR Annex I para 1: acceptances are full-risk (FR) OBS items.
            SA_CCF_CRR["FR"] = 1.00 (data/tables/ccf.py).
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_ACCEPT)

        # Assert — LOAD-BEARING: pre-fix gives None, expected "FR"
        assert row["risk_type"] == RESOLVED_RISK_TYPE_ACCEPT, (
            f"{SCENARIO_ID} ACCEPTANCE row ({CONT_REF_ACCEPT}): "
            f"expected risk_type={RESOLVED_RISK_TYPE_ACCEPT!r} "
            f"(resolved from obs_product='ACCEPTANCE' via ANNEX1_PRODUCT_RISK_TYPE, "
            f"CRR Annex I para 1), "
            f"got {row['risk_type']!r}. "
            f"Engine does not yet apply the obs_product -> risk_type fill."
        )

    def test_p2_31_acceptance_ccf_is_100_pct(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        ACCEPTANCE: ccf == 1.00 (FR direct credit substitute, CRR Annex I para 1).

        Arrange: CONT_P231_ACCEPT, obs_product=ACCEPTANCE, risk_type=None,
                 nominal_amount=2_000_000, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 1.00.

        Pre-fix failure: ccf == 0.50 (null risk_type → MR default, SA_CCF_CRR).

        References:
            CRR Annex I para 1 / PS1/26 Table A1 Row 1: FR → CCF 100%.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_ACCEPT)

        # Assert — LOAD-BEARING: pre-fix gives 0.50, expected 1.00
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_ACCEPT, abs=1e-6), (
            f"{SCENARIO_ID} ACCEPTANCE row ({CONT_REF_ACCEPT}): "
            f"expected ccf={EXPECTED_CCF_ACCEPT} "
            f"(CRR Annex I para 1 / Table A1 Row 1 — FR 100%), "
            f"got {row['ccf']:.4f}. "
            f"Engine does not yet resolve obs_product='ACCEPTANCE' -> FR; "
            f"null risk_type falls to MR default (0.50)."
        )

    def test_p2_31_acceptance_ead_is_2m(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        ACCEPTANCE: ead_from_ccf == 2_000_000.00 (nominal 2M × CCF 1.00).

        Arrange: CONT_P231_ACCEPT, nominal_amount=2_000_000, drawn_amount=0,
                 obs_product=ACCEPTANCE, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 2_000_000.00.

        Pre-fix failure: ead_from_ccf == 1_000_000.00 (2M × 0.50 MR default).

        References:
            CRR Art. 111(1): EAD = drawn + CCF × undrawn.
            CCF = 1.00 from FR resolution (Annex I para 1).
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_ACCEPT)

        # Assert — LOAD-BEARING: pre-fix gives 1_000_000, expected 2_000_000
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_ACCEPT, rel=1e-4), (
            f"{SCENARIO_ID} ACCEPTANCE row ({CONT_REF_ACCEPT}): "
            f"expected ead_from_ccf={EXPECTED_EAD_ACCEPT:,.2f} "
            f"(2_000_000 × 1.00, Annex I para 1 FR), "
            f"got {row['ead_from_ccf']:,.2f}. "
            f"Pre-fix EAD = 1_000_000.00 (2M × 0.50, null risk_type → MR default)."
        )


# ---------------------------------------------------------------------------
# Test class — PERFORMANCE_BOND row (CONT_P231_PERFBOND)
# ---------------------------------------------------------------------------


class TestP231PerformanceBondMLRMapping:
    """
    P2.31 PERFORMANCE_BOND row: obs_product="PERFORMANCE_BOND", risk_type=None.

    The engine must resolve risk_type="MLR" from obs_product and apply
    SA_CCF_CRR["MLR"] = 0.20.

    Pre-fix: ccf = 0.50 (null risk_type falls to MR default), EAD = 1_000_000.
    Both assertions FAIL until the engine adds the fill logic.

    References:
        - CRR Annex I Row 6(b) / PS1/26 Table A1 Row 6(b): performance bonds → MLR (20%)
    """

    def test_p2_31_performance_bond_ccf_is_20_pct(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        PERFORMANCE_BOND: ccf == 0.20 (MLR, Annex I Row 6(b)).

        Arrange: CONT_P231_PERFBOND, obs_product=PERFORMANCE_BOND, risk_type=None,
                 nominal_amount=2_000_000, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.20.

        Pre-fix failure: ccf == 0.50 (null risk_type → MR default).

        References:
            CRR Annex I Row 6(b) / PS1/26 Table A1 Row 6(b): performance bonds → 20%.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_PERFBOND)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_PERFBOND, abs=1e-6), (
            f"{SCENARIO_ID} PERFORMANCE_BOND row ({CONT_REF_PERFBOND}): "
            f"expected ccf={EXPECTED_CCF_PERFBOND} "
            f"(CRR Annex I Row 6(b) / Table A1 Row 6(b) — MLR 20%), "
            f"got {row['ccf']:.4f}. "
            f"Engine does not yet resolve obs_product='PERFORMANCE_BOND' -> MLR."
        )

    def test_p2_31_performance_bond_ead_is_400k(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        PERFORMANCE_BOND: ead_from_ccf == 400_000.00 (2M × 0.20).

        Arrange: CONT_P231_PERFBOND, nominal_amount=2_000_000, drawn_amount=0,
                 obs_product=PERFORMANCE_BOND, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 400_000.00.

        Pre-fix failure: ead_from_ccf == 1_000_000.00 (2M × 0.50 MR default).

        References:
            CRR Art. 111(1), Annex I Row 6(b): MLR CCF = 20%.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_PERFBOND)

        # Assert
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_PERFBOND, rel=1e-4), (
            f"{SCENARIO_ID} PERFORMANCE_BOND row ({CONT_REF_PERFBOND}): "
            f"expected ead_from_ccf={EXPECTED_EAD_PERFBOND:,.2f} "
            f"(2_000_000 × 0.20, Annex I Row 6(b) MLR), "
            f"got {row['ead_from_ccf']:,.2f}. "
            f"Pre-fix EAD = 1_000_000.00 (2M × 0.50, null risk_type → MR default)."
        )


# ---------------------------------------------------------------------------
# Test class — DOCUMENTARY_CREDIT row (CONT_P231_DOCLC)
# ---------------------------------------------------------------------------


class TestP231DocumentaryCreditMLRMapping:
    """
    P2.31 DOCUMENTARY_CREDIT row: obs_product="DOCUMENTARY_CREDIT", risk_type=None.

    The engine must resolve risk_type="MLR" from obs_product and apply
    SA_CCF_CRR["MLR"] = 0.20.

    Pre-fix: ccf = 0.50 (null risk_type falls to MR default), EAD = 1_000_000.
    Both assertions FAIL until the engine adds the fill logic.

    References:
        - CRR Annex I Row 6(a) / PS1/26 Table A1 Row 6(a): documentary credits → MLR (20%)
    """

    def test_p2_31_documentary_credit_ccf_is_20_pct(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        DOCUMENTARY_CREDIT: ccf == 0.20 (MLR, Annex I Row 6(a)).

        Arrange: CONT_P231_DOCLC, obs_product=DOCUMENTARY_CREDIT, risk_type=None,
                 nominal_amount=2_000_000, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.20.

        Pre-fix failure: ccf == 0.50 (null risk_type → MR default).

        References:
            CRR Annex I Row 6(a) / PS1/26 Table A1 Row 6(a): documentary credits → 20%.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_DOCLC)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_DOCLC, abs=1e-6), (
            f"{SCENARIO_ID} DOCUMENTARY_CREDIT row ({CONT_REF_DOCLC}): "
            f"expected ccf={EXPECTED_CCF_DOCLC} "
            f"(CRR Annex I Row 6(a) / Table A1 Row 6(a) — MLR 20%), "
            f"got {row['ccf']:.4f}. "
            f"Engine does not yet resolve obs_product='DOCUMENTARY_CREDIT' -> MLR."
        )

    def test_p2_31_documentary_credit_ead_is_400k(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        DOCUMENTARY_CREDIT: ead_from_ccf == 400_000.00 (2M × 0.20).

        Arrange: CONT_P231_DOCLC, nominal_amount=2_000_000, drawn_amount=0,
                 obs_product=DOCUMENTARY_CREDIT, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 400_000.00.

        Pre-fix failure: ead_from_ccf == 1_000_000.00 (2M × 0.50 MR default).

        References:
            CRR Art. 111(1), Annex I Row 6(a): MLR CCF = 20%.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_DOCLC)

        # Assert
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_DOCLC, rel=1e-4), (
            f"{SCENARIO_ID} DOCUMENTARY_CREDIT row ({CONT_REF_DOCLC}): "
            f"expected ead_from_ccf={EXPECTED_EAD_DOCLC:,.2f} "
            f"(2_000_000 × 0.20, Annex I Row 6(a) MLR), "
            f"got {row['ead_from_ccf']:,.2f}. "
            f"Pre-fix EAD = 1_000_000.00 (2M × 0.50, null risk_type → MR default)."
        )


# ---------------------------------------------------------------------------
# Test class — OVERRIDE row (CONT_P231_OVERRIDE) — explicit-wins regression guard
# ---------------------------------------------------------------------------


class TestP231ExplicitRiskTypeWins:
    """
    P2.31 OVERRIDE row: obs_product="ACCEPTANCE", risk_type="LR" (explicit wins).

    When an explicit ``risk_type`` is supplied, the obs_product fill must NOT
    overwrite it.  Explicit LR → CCF 0.00 → EAD 0.

    These assertions PASS now (they are regression guards — they must remain
    green before and after the engine-implementer's changes).

    References:
        - P2.31 scenario §5: explicit risk_type override is an anti-confound
          — explicit wins, obs_product is ignored.
    """

    def test_p2_31_override_retains_explicit_lr_risk_type(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        OVERRIDE: explicit risk_type="LR" is preserved (obs_product="ACCEPTANCE" ignored).

        Arrange: CONT_P231_OVERRIDE, obs_product=ACCEPTANCE, risk_type="LR",
                 nominal_amount=2_000_000, CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  risk_type == "LR".

        References:
            P2.31 explicit-wins semantics: explicit risk_type always takes precedence.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_OVERRIDE)

        # Assert — regression guard: passes now and must stay green after fix
        assert row["risk_type"] == RESOLVED_RISK_TYPE_OVERRIDE, (
            f"{SCENARIO_ID} OVERRIDE row ({CONT_REF_OVERRIDE}): "
            f"expected explicit risk_type={RESOLVED_RISK_TYPE_OVERRIDE!r} to be preserved, "
            f"got {row['risk_type']!r}. "
            f"Explicit risk_type must win over obs_product fill."
        )

    def test_p2_31_override_ccf_is_0_pct(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        OVERRIDE: ccf == 0.00 (explicit LR → SA_CCF_CRR["LR"] = 0.00).

        Arrange: CONT_P231_OVERRIDE, risk_type="LR" (explicit), CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.00.

        References:
            CRR Annex I para 4 / SA_CCF_CRR["LR"] = 0.00.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_OVERRIDE)

        # Assert — regression guard
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_OVERRIDE, abs=1e-6), (
            f"{SCENARIO_ID} OVERRIDE row ({CONT_REF_OVERRIDE}): "
            f"expected ccf={EXPECTED_CCF_OVERRIDE} (explicit LR, SA_CCF_CRR['LR']=0.00), "
            f"got {row['ccf']:.4f}."
        )

    def test_p2_31_override_ead_is_zero(
        self,
        p2_31_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        OVERRIDE: ead_from_ccf == 0.00 (2M × 0.00).

        Arrange: CONT_P231_OVERRIDE, nominal_amount=2_000_000, drawn_amount=0,
                 risk_type="LR", CRR config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 0.00.

        References:
            CRR Art. 111(1): EAD = drawn + CCF × undrawn; CCF=0.00 → EAD=0.
        """
        # Arrange
        row = _row(p2_31_crr_ccf_results, CONT_REF_OVERRIDE)

        # Assert — regression guard
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_OVERRIDE, abs=1e-2), (
            f"{SCENARIO_ID} OVERRIDE row ({CONT_REF_OVERRIDE}): "
            f"expected ead_from_ccf={EXPECTED_EAD_OVERRIDE:,.2f} (2M × 0.00, LR), "
            f"got {row['ead_from_ccf']:,.2f}."
        )
