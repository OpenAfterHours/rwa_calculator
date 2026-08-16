"""
P1.314 (CRR) — Art. 114(7): the funding limb must be tested against the
**pre-FX denomination**, not the post-FX reporting currency.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> FXConverter -> CRMProcessor
    -> SACalculator -> Aggregator

Why this leg exists, and why no unit leg can replace it:
    ``tests/fixtures/single_exposure.py::calculate_single_sa_exposure`` builds
    no ``original_currency`` column, so ``denomination_currency_expr``
    collapses to ``pl.col("currency")`` on every unit frame. A wrong
    implementation that compares the funding currency against
    ``pl.col("currency")`` instead of the pre-FX denomination is therefore
    INDISTINGUISHABLE from the correct one on all of legs A-K in
    ``tests/unit/test_p1_314_art_114_115_funded_currency.py``.

    On a real post-FX frame it is not. The FX converter overwrites ``currency``
    with the reporting currency (GBP here) and preserves the denomination in
    ``original_currency`` (EUR) — the hazard ``risk_weights.py`` already warns
    about above ``ccy_expr``. Measured on that shape:

        correct             FUNDEUR rw=0.00   FUNDUSD rw=1.50
        wrong currency col  FUNDEUR rw=1.50   FUNDUSD rw=1.50   <- destroys
                                                                   legitimate
                                                                   Art. 114(7)
                                                                   relief

    So ``LN_P314_EU_FUNDEUR`` at 0.00 is the discriminating assertion, and
    ``LN_P314_EU_FUNDUSD`` at 1.50 is the leg that keeps it honest: without a
    mover, "both rows are 0.00" would also pass.

Key assertions:
    LN_P314_EU_FUNDEUR (funded EUR): denominated AND funded in the DE domestic
        currency -> Art. 114(7) 0% extension applies -> risk_weight 0.00.
        Green pre- and post-fix; discriminating against the ``currency``-column
        mistake, not against the missing limb.
    LN_P314_EU_FUNDUSD (funded USD): funding limb fails -> Art. 114(2) Table 1
        at CQS 6 -> risk_weight 1.50. PRE-FIX 0.00 -> this test FAILS.

References:
    - CRR Art. 114(7): "...exposures to their central government and central
      bank denominated and funded in the domestic currency..."
    - tests/fixtures/p1_314/p1_314.py — bundle builder and hand-calculation.
    - .claude/state/outputs/P1.314-scenario.md, ADDENDUM "RESHAPED P1".
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_314.p1_314 import (
    EXPECTED_RW_FUNDEUR,
    EXPECTED_RW_FUNDUSD,
    LOAN_FUNDEUR_REF,
    LOAN_FUNDUSD_REF,
    build_p314_bundle,
    create_p314_counterparties,
    create_p314_fx_rates,
    create_p314_loans,
    create_p314_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, FACILITY_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.domain.branch_reasons import SA_RISK_WEIGHT_BRANCH_REASON, UNKNOWN_FALLBACK
from rwa_calc.engine.pipeline import PipelineOrchestrator

#: 10,000,000 EUR drawn x 0.86 EUR->GBP (tests/fixtures/p1_314) = the GBP EAD
#: every row carries after conversion. Asserted rather than assumed: a zero or
#: unconverted EAD would make the RWA assertions vacuous, and an EAD still at
#: 10,000,000 would mean the frame never went through FX — which is the whole
#: premise of this leg.
EXPECTED_EAD_GBP = 8_600_000.0


def _config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )


def _control_bundle() -> RawDataBundle:
    """The same portfolio with the funding currency simply not reported.

    Used only by the error-channel assertion: under the PERMISSIVE convention
    an unreported funding currency is not a data-quality event, so this run
    must raise exactly the codes the populated run raises.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=create_p314_loans().lazy().drop("funding_currency"),
        counterparties=create_p314_counterparties().lazy(),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=create_p314_ratings().lazy(),
        fx_rates=create_p314_fx_rates().lazy(),
    )


def _row(df: pl.DataFrame, loan_ref: str) -> dict:
    """Return the single result row for a loan, by its SOURCE reference."""
    rows = df.filter(pl.col("source_exposure_reference") == loan_ref).to_dicts()
    assert len(rows) == 1, (
        f"P1.314 CRR: expected exactly 1 result row for {loan_ref}, got {len(rows)}. "
        f"A vanished row is neither a result nor an error. "
        f"All rows: {df.get_column('source_exposure_reference').to_list()}"
    )
    return rows[0]


@pytest.fixture(scope="module")
def sa_results() -> pl.DataFrame:
    """One CRR run of the P1.314 bundle; the SA branch must have been emitted."""
    results = PipelineOrchestrator().run_with_data(build_p314_bundle(), _config())
    assert results.sa_results is not None, (
        "P1.314 CRR: sa_results is None under STANDARDISED — the SA branch was "
        "not emitted at all, so no risk-weight assertion below means anything."
    )
    return results.sa_results.collect()


class TestP1314Art1147FundedCurrencyCrrEndToEnd:
    """CRR: the Art. 114(7) funding limb across a real FX-converted frame."""

    # ---- PRECONDITION: the frame really is post-FX --------------------------

    def test_p1_314_crr_rows_are_post_fx_eur_denominated(self, sa_results: pl.DataFrame) -> None:
        """The premise of this whole file: currency == GBP, original == EUR.

        If the FX converter had left ``currency`` at EUR, the wrong
        implementation and the correct one would agree and this file would be
        a decorative duplicate of the unit legs.
        """
        # Arrange / Act
        rows = [_row(sa_results, LOAN_FUNDEUR_REF), _row(sa_results, LOAN_FUNDUSD_REF)]

        # Assert
        for row in rows:
            ref = row["source_exposure_reference"]
            assert row["currency"] == "GBP", (
                f"P1.314 CRR: {ref} should report in GBP after FX conversion, got "
                f"{row['currency']!r}. Without the post-FX shape this leg cannot "
                f"discriminate a comparison against pl.col('currency')."
            )
            assert row["original_currency"] == "EUR", (
                f"P1.314 CRR: {ref} should preserve its EUR denomination in "
                f"original_currency, got {row['original_currency']!r}."
            )
            assert row["ead_final"] == pytest.approx(EXPECTED_EAD_GBP, abs=1e-9), (
                f"P1.314 CRR: {ref} ead_final should be {EXPECTED_EAD_GBP:,.2f} "
                f"(10,000,000 EUR x 0.86), got {row['ead_final']}."
            )

    # ---- DISCRIMINATING against the pre-fix engine --------------------------

    def test_p1_314_crr_usd_funded_eu_sovereign_loses_the_zero_extension(
        self, sa_results: pl.DataFrame
    ) -> None:
        """LN_P314_EU_FUNDUSD: EUR-denominated but USD-funded -> 150%, not 0%.

        PRE-FIX: risk_weight = 0.00 (the funding limb is absent on the direct
        path) -> this test FAILS.
        POST-FIX: risk_weight = 1.50, rwa_final = 12,900,000.
        """
        # Arrange / Act
        row = _row(sa_results, LOAN_FUNDUSD_REF)

        # Assert
        assert row["risk_weight"] is not None, "P1.314 CRR: risk_weight is NULL on the mover."
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_FUNDUSD, abs=1e-9), (
            f"P1.314 CRR: {LOAN_FUNDUSD_REF} risk_weight should be "
            f"{EXPECTED_RW_FUNDUSD:.2f} (DE sovereign CQS 6 — the Art. 114(7) 0% "
            f"extension is denied because the exposure is not FUNDED in EUR). "
            f"Got {row['risk_weight']:.4f}; 0.00 means the funding limb never "
            f"reached the direct exposure path."
        )
        assert row["rwa_final"] is not None, "P1.314 CRR: rwa_final is NULL on the mover."
        assert row["rwa_final"] == pytest.approx(
            EXPECTED_EAD_GBP * EXPECTED_RW_FUNDUSD, abs=1e-9
        ), (
            f"P1.314 CRR: {LOAN_FUNDUSD_REF} rwa_final should be "
            f"{EXPECTED_EAD_GBP * EXPECTED_RW_FUNDUSD:,.2f}, got {row['rwa_final']:,.4f}."
        )

    # ---- DISCRIMINATING against the wrong-column implementation -------------

    def test_p1_314_crr_eur_funded_eu_sovereign_keeps_the_zero_extension(
        self, sa_results: pl.DataFrame
    ) -> None:
        """LN_P314_EU_FUNDEUR: denominated AND funded in EUR -> 0% survives.

        Green before AND after the correct fix — deliberately. This is the leg
        that fails if the funding currency is compared against the POST-FX
        ``currency`` column ("EUR" == "GBP" -> False), which would wrongly
        report 1.50 and destroy legitimate Art. 114(7) relief on every
        non-base-currency sovereign exposure in a real portfolio. Do not
        rewrite it for not failing first.
        """
        # Arrange / Act
        row = _row(sa_results, LOAN_FUNDEUR_REF)

        # Assert
        assert row["risk_weight"] is not None, "P1.314 CRR: risk_weight is NULL on the survivor."
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_FUNDEUR, abs=1e-9), (
            f"P1.314 CRR: {LOAN_FUNDEUR_REF} risk_weight should be "
            f"{EXPECTED_RW_FUNDEUR:.2f} — the exposure is denominated AND funded "
            f"in EUR, the DE domestic currency, so Art. 114(7) applies. Got "
            f"{row['risk_weight']:.4f}; 1.50 means the funding currency was "
            f"compared against the post-FX 'currency' column (GBP) instead of the "
            f"pre-FX denomination in 'original_currency'."
        )
        assert row["rwa_final"] is not None, "P1.314 CRR: rwa_final is NULL on the survivor."
        assert row["rwa_final"] == pytest.approx(0.0, abs=1e-9), (
            f"P1.314 CRR: {LOAN_FUNDEUR_REF} rwa_final should be 0.00, got {row['rwa_final']:,.4f}."
        )

    # ---- NEGATIVE SPACE -----------------------------------------------------

    def test_p1_314_crr_branch_reason_is_populated_on_both_rows(
        self, sa_results: pl.DataFrame
    ) -> None:
        """Both rows carry an explanation, and neither is the "I do not know" name.

        ``sa_risk_weight_branch_reason`` is the Art. 121(6) sovereign-floor
        vocabulary; a CGCB row is out of that rule's scope and must be named
        ``not_institution``. UNKNOWN_FALLBACK here would mean the domesticity
        predicate the funding limb extends had gone indeterminate.
        """
        # Arrange / Act
        rows = [_row(sa_results, LOAN_FUNDEUR_REF), _row(sa_results, LOAN_FUNDUSD_REF)]

        # Assert
        for row in rows:
            reason = row[SA_RISK_WEIGHT_BRANCH_REASON]
            assert reason is not None, (
                f"P1.314 CRR: {row['source_exposure_reference']} carries a NULL "
                f"{SA_RISK_WEIGHT_BRANCH_REASON}."
            )
            assert reason != UNKNOWN_FALLBACK, (
                f"P1.314 CRR: {row['source_exposure_reference']} is named "
                f"{UNKNOWN_FALLBACK} — a domesticity predicate went indeterminate."
            )

    def test_p1_314_crr_funding_currency_raises_no_new_error_codes(self) -> None:
        """The error channel is unmoved by the funding currency.

        Under the PERMISSIVE convention an unreported funding currency is not a
        data-quality event, and a reported one that mismatches the denomination
        is a risk-weight outcome rather than an error. Both runs must therefore
        raise exactly the same code set. Stated as a set equality against a
        control run rather than as "no errors", so the assertion still means
        something on a regime whose baseline is non-empty.
        """
        # Arrange / Act
        live = PipelineOrchestrator().run_with_data(build_p314_bundle(), _config())
        control = PipelineOrchestrator().run_with_data(_control_bundle(), _config())

        # Assert
        live_codes = sorted({e.code for e in live.errors})
        control_codes = sorted({e.code for e in control.errors})
        assert live_codes == control_codes, (
            f"P1.314 CRR: reporting a funding currency changed the error channel. "
            f"With funding_currency: {live_codes}. Without: {control_codes}. "
            f"Any conservatism about an unreported funding currency belongs here, "
            f"not in the risk weight — but it must be a deliberate decision."
        )
