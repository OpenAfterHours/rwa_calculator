"""
P1.278 — CRR Art. 160(2) / 160(6) top-down PD for purchased corporate receivables.

Where an institution "is not able to estimate PDs or an institution's PD estimates do
not meet the requirements set out in Section 6", CRR Art. 160(2) prescribes the PD:

    (a) senior claims       -> PD = the institution's estimate of EL divided by LGD
    (b) subordinated claims -> PD = the institution's estimate of EL
    (c) [deferred] a reliable EL decomposition may supply PD directly

and Art. 160(6) first sentence: for dilution risk of purchased corporate receivables
"PD shall be set equal to the EL estimate of the institution for dilution risk".

The LGD denominator in (a) is not free: CRR Art. 161(1)(e)/(f)/(g) fix the supervisory
purchased-receivables LGDs precisely "where an institution is not able to estimate PDs
or the institution's PD estimates do not meet the requirements set out in Section 6",
and PS1/26 Art. 161(1)(e)/(f)/(g) + 161(2)(a) tie the same values explicitly to
"where PD is determined in accordance with point (a) of Article 160(2)". So the
denominator is the subtype's supervisory LGD (CRR 45% senior; PS1/26 40% senior) —
already the pack table this engine reads for the LGD side of the same articles.

The gap: nothing derived a PD, and the classifier's IRB gate is
``internal_pd.is_not_null()`` (engine/stages/classify/approach.py:110), so a
receivables pool with no obligor PD fell to the Standardised Approach entirely.

Regime scope: BOTH. PS1/26 Art. 160(2)(a)-(c) and 160(6) carry the CRR text over
verbatim (Art. 160(2)(c) reworded from "permission ... to use own LGD estimates" to
"using the Advanced IRB Approach in accordance with Article 147A"), so this is not a
CRR-only treatment and needs no regime Feature — only the pack's regime-keyed LGD.

References:
- CRR Art. 160(2)(a)/(b): senior PD = EL/LGD; subordinated PD = EL
- CRR Art. 160(6) first sentence: dilution-risk PD = EL estimate for dilution risk
- CRR Art. 160(1): the 0.03% corporate/institution PD floor still applies
- CRR Art. 161(1)(e)/(f)/(g): the supervisory LGDs that fix the (a) denominator
- PS1/26 Art. 160(2)/(6), Art. 161(1)(e)-(g), Art. 161(2)(a): same treatment under B31
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.irb.transforms import apply_firb_lgd, classify_approach
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_CP = "CP_P1278"
_LOAN = "LN_P1278"
_VALUE_DATE = date(2025, 1, 15)
_MATURITY_DATE = date(2027, 12, 31)
_DRAWN = 1_000_000.0

# CRR Art. 161(1)(e) senior purchased-receivables supervisory LGD = 45%;
# PS1/26 Art. 161(1)(e) = 40%. Both are pack values, asserted via the derived PD.
_LGD_SENIOR_CRR = 0.45
_LGD_SENIOR_B31 = 0.40

# EL rate chosen so the CRR division lands on a round PD: 0.0225 / 0.45 = 0.05.
_EL_SENIOR = 0.0225
_PD_SENIOR_CRR = _EL_SENIOR / _LGD_SENIOR_CRR  # 0.05
_PD_SENIOR_B31 = _EL_SENIOR / _LGD_SENIOR_B31  # 0.05625

_EL_SUBORDINATED = 0.30  # Art. 160(2)(b): PD = EL, no division
_EL_DILUTION = 0.40  # Art. 160(6): PD = EL for dilution risk

# The LGD side of the same articles. CRR Art. 161(1)(f) / PS1/26 Art. 161(1)(f):
# subordinated purchased receivables 100%. CRR Art. 161(1)(g) 75% dilution risk;
# PS1/26 Art. 161(1)(g) raises it to 100%. The generic senior-unsecured value
# (CRR 45% / PS1/26 40% non-FSE) is what a row must NOT fall back to.
_LGD_PR_SUBORDINATED = 1.00
_LGD_PR_DILUTION_CRR = 0.75
_LGD_PR_DILUTION_B31 = 1.00
_LGD_GENERIC_CRR = 0.45
_LGD_GENERIC_B31 = 0.40

# Revenue below the PS1/26 Art. 147A GBP 440m large-corporate cut (which forces
# F-IRB and so masks the A-IRB path) but far above the SME turnover test.
_MID_CORPORATE_REVENUE = 200_000_000.0


def _crr_config() -> CalculationConfig:
    """CRR config with org-wide IRB permissions (no model_permissions table).

    ``irb_permissions`` is supplied explicitly so the org-wide permission path
    (``_build_orgwide_permission_exprs``) grants IRB on CORPORATE — this test
    isolates the ``internal_pd.is_not_null()`` gate, not model-permission matching.
    """
    return replace(
        CalculationConfig.crr(reporting_date=date(2025, 12, 31)),
        irb_permissions=IRBPermissions.full_irb(),
    )


def _crr_firb_only_config() -> CalculationConfig:
    """CRR config granting F-IRB (not A-IRB) on CORPORATE.

    The regulatorily meaningful route for an Art. 160(2) pool: an institution that
    cannot estimate the PD is, for these receivables, on the Foundation treatment
    with the Art. 161(1)(e)-(g) supervisory LGDs.
    """
    return replace(
        CalculationConfig.crr(reporting_date=date(2025, 12, 31)),
        irb_permissions=IRBPermissions(
            permissions={
                ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB},
            }
        ),
    )


def _b31_config() -> CalculationConfig:
    return replace(
        CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31)),
        irb_permissions=IRBPermissions.full_irb_b31(),
    )


def _b31_airb_config() -> CalculationConfig:
    """B31 config that actually reaches A-IRB on CORPORATE.

    ``full_irb_b31()`` cannot: PS1/26 Art. 147A forces the large corporate in
    ``_counterparties()`` onto F-IRB, which masks the A-IRB LGD path entirely.
    Pair this with ``_counterparties(revenue=_MID_CORPORATE_REVENUE)``.
    """
    return replace(
        CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31)),
        irb_permissions=IRBPermissions(
            permissions={ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.AIRB}}
        ),
    )


def _counterparties(
    *, revenue: float = 500_000_000.0, entity_type: str = "corporate"
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [_CP],
            "entity_type": [entity_type],
            "country_code": ["GB"],
            # Large corporate by default: annual_revenue well above the SME
            # threshold so the row stays CORPORATE (not CORPORATE_SME) and the
            # class is unambiguous.
            "annual_revenue": [revenue],
            "total_assets": [800_000_000.0],
            "default_status": [False],
        }
    )


def _exposures(
    *,
    purchased_receivables_subtype: str | None,
    el_estimate: float | None = None,
    el_dilution_estimate: float | None = None,
    internal_pd: float | None = None,
    lgd: float | None = None,
) -> pl.LazyFrame:
    """Sparse hierarchy-exit exposure frame (the seal injects the rest as nulls)."""
    return pl.LazyFrame(
        {
            "exposure_reference": [_LOAN],
            "exposure_type": ["loan"],
            "counterparty_reference": [_CP],
            "value_date": [_VALUE_DATE],
            "maturity_date": [_MATURITY_DATE],
            "currency": ["GBP"],
            "drawn_amount": [_DRAWN],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "seniority": ["senior"],
            "lgd": [lgd],
            "internal_pd": [internal_pd],
            "purchased_receivables_subtype": [purchased_receivables_subtype],
            "el_estimate": [el_estimate],
            "el_dilution_estimate": [el_dilution_estimate],
        },
        schema={
            "exposure_reference": pl.String,
            "exposure_type": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "undrawn_amount": pl.Float64,
            "nominal_amount": pl.Float64,
            "seniority": pl.String,
            "lgd": pl.Float64,
            "internal_pd": pl.Float64,
            "purchased_receivables_subtype": pl.String,
            "el_estimate": pl.Float64,
            "el_dilution_estimate": pl.Float64,
        },
    )


def _classify(
    config: CalculationConfig,
    exposures: pl.LazyFrame,
    *,
    counterparties: pl.LazyFrame | None = None,
) -> dict:
    return (
        _classified_frame(config, exposures, counterparties=counterparties).collect().to_dicts()[0]
    )


def _classified_frame(
    config: CalculationConfig,
    exposures: pl.LazyFrame,
    *,
    counterparties: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    bundle = make_resolved_bundle(
        exposures,
        counterparty_lookup=make_counterparty_lookup(
            counterparties=counterparties if counterparties is not None else _counterparties()
        ),
        lending_group_totals=pl.LazyFrame(
            schema={"lending_group_reference": pl.String, "total_exposure": pl.Float64}
        ),
        hierarchy_errors=[],
    )
    return ExposureClassifier().classify(bundle, config).all_exposures


def _classify_with_lgd(
    config: CalculationConfig,
    exposures: pl.LazyFrame,
    *,
    counterparties: pl.LazyFrame | None = None,
) -> dict:
    """Classify, then run the IRB LGD assignment the classified row lands on.

    The top-down PD (classifier) and the Art. 161(1)(e)-(g) supervisory LGD
    (``engine/irb/transforms.py::apply_firb_lgd``) sit in different stages, so a
    classifier-only assertion cannot see which LGD the derived-PD row actually
    gets. ``pad_crm_exit_defaults`` supplies the crm_exit contract columns the
    IRB branch reads (it only fills what is missing, so the classifier's real
    ``approach`` survives).
    """
    classified = _pad(_classified_frame(config, exposures, counterparties=counterparties))
    applied = classified.pipe(classify_approach, config).pipe(apply_firb_lgd, config)
    return applied.collect().to_dicts()[0]


# ---------------------------------------------------------------------------
# (A) Art. 160(2)(a) — senior claims: PD = EL / LGD
# ---------------------------------------------------------------------------


class TestSeniorTopDownPD:
    def test_crr_senior_pd_is_el_over_supervisory_lgd(self) -> None:
        # Arrange — no obligor PD; a senior receivables pool with an EL estimate
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=_EL_SENIOR)

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — 0.0225 / 0.45 = 0.05 (Art. 161(1)(e) denominator)
        assert row["internal_pd"] == pytest.approx(_PD_SENIOR_CRR)
        assert row["pd"] == pytest.approx(_PD_SENIOR_CRR)

    def test_b31_senior_pd_uses_the_b31_supervisory_lgd(self) -> None:
        # Arrange — same EL, different regime denominator (PS1/26 Art. 161(1)(e) 40%)
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=_EL_SENIOR)

        # Act
        row = _classify(_b31_config(), exposures)

        # Assert — 0.0225 / 0.40 = 0.05625, NOT the CRR 0.05
        assert row["internal_pd"] == pytest.approx(_PD_SENIOR_B31)

    def test_senior_pool_now_routes_to_irb_instead_of_sa(self) -> None:
        """The gap itself: the derived PD must open the IRB gate.

        Pinned to A-IRB exactly, not ``in {FIRB, AIRB}``. ``full_irb()`` grants
        A-IRB on CORPORATE and the org-wide permission path does not require a
        modelled LGD (``permissions.py::_build_orgwide_permission_exprs``), so the
        derived PD alone lands this row on A-IRB — carrying no LGD. Asserting the
        looser set hid exactly that: the deferral note reasoned the row would fall
        to F-IRB "where the supervisory LGD is applied", which is true only on the
        model-permission path. ``test_senior_pool_routes_to_firb_under_foundation_permissions``
        covers the Foundation route.
        """
        # Arrange
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=_EL_SENIOR)

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — pre-fix this row was ApproachType.SA (no internal_pd at all)
        assert row["approach"] == ApproachType.AIRB.value

    def test_senior_lgd_on_advanced_irb_is_the_subtype_value_not_a_coincidence(self) -> None:
        """Art. 161(1)(e) senior = 45% CRR / 40% B31 — equal to the generic value.

        The senior subtype LGD and the generic senior-unsecured LGD coincide in
        both regimes, so this row reads correct even when the subtype branch is
        skipped entirely. It is pinned so that the subordinated and dilution tests
        are not the only guard, and so a future regime change that moved one value
        without the other would surface here rather than silently.
        """
        # Arrange
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=_EL_SENIOR)

        # Act
        row = _classify_with_lgd(_crr_config(), exposures)

        # Assert — 45% either way; the value is right, the route is what matters
        assert row["approach"] == ApproachType.AIRB.value
        assert row["lgd"] == pytest.approx(_LGD_SENIOR_CRR)
        assert _LGD_SENIOR_CRR == _LGD_GENERIC_CRR, "coincidence documented, not asserted logic"

    def test_senior_pool_routes_to_firb_under_foundation_permissions(self) -> None:
        """With F-IRB (not A-IRB) permission the pool lands on Foundation.

        This is the route Art. 160(2) contemplates: no compliant own PD, hence
        the Art. 161(1)(e) supervisory LGD rather than an own estimate.
        """
        # Arrange
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=_EL_SENIOR)

        # Act
        row = _classify(_crr_firb_only_config(), exposures)

        # Assert
        assert row["approach"] == ApproachType.FIRB.value


# ---------------------------------------------------------------------------
# (B) Art. 160(2)(b) — subordinated claims: PD = EL (no division)
# ---------------------------------------------------------------------------


class TestSubordinatedTopDownPD:
    def test_subordinated_pd_equals_el_without_division(self) -> None:
        # Arrange
        exposures = _exposures(
            purchased_receivables_subtype="subordinated", el_estimate=_EL_SUBORDINATED
        )

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — PD = EL exactly; dividing by the 100% Art. 161(1)(f) LGD would
        # coincide here, but dividing by the 45% senior LGD (0.667) would not.
        assert row["internal_pd"] == pytest.approx(_EL_SUBORDINATED)

    def test_subordinated_lgd_is_the_supervisory_value_on_advanced_irb(self) -> None:
        """CRR Art. 161(1)(f) / PS1/26 Art. 161(2)(a)(ii): 100%, not the generic 45%.

        The derived PD is what opens the IRB gate, and the org-wide permission path
        grants A-IRB without requiring a modelled LGD, so this row reaches A-IRB
        carrying no LGD at all. The Art. 161(1)(e)-(g) subtype LGDs must still bind:
        CRR Art. 161(1) prescribes them with no approach qualifier, and PS1/26
        Art. 161(2)(a) says an A-IRB institution "shall apply" them where the PD
        comes from Art. 160(2). Falling back to the generic senior-unsecured value
        understates LGD by 55pp and is anti-conservative.
        """
        # Arrange
        exposures = _exposures(
            purchased_receivables_subtype="subordinated", el_estimate=_EL_SUBORDINATED
        )

        # Act
        row = _classify_with_lgd(_crr_config(), exposures)

        # Assert — the A-IRB route is the one under test, then the LGD it applies
        assert row["approach"] == ApproachType.AIRB.value
        assert row["lgd"] == pytest.approx(_LGD_PR_SUBORDINATED)
        assert row["lgd_input"] == pytest.approx(_LGD_PR_SUBORDINATED)

    def test_b31_subordinated_lgd_is_the_supervisory_value_on_advanced_irb(self) -> None:
        # Arrange — a mid-size corporate, so PS1/26 Art. 147A does not force F-IRB
        exposures = _exposures(
            purchased_receivables_subtype="subordinated", el_estimate=_EL_SUBORDINATED
        )

        # Act
        row = _classify_with_lgd(
            _b31_airb_config(),
            exposures,
            counterparties=_counterparties(revenue=_MID_CORPORATE_REVENUE),
        )

        # Assert — PS1/26 Art. 161(1)(f) 100%, not the 40% non-FSE senior value
        assert row["approach"] == ApproachType.AIRB.value
        assert row["lgd"] == pytest.approx(_LGD_PR_SUBORDINATED)

    def test_firm_supplied_lgd_still_outranks_the_supervisory_subtype_value(self) -> None:
        """CRR Art. 161(2) / PS1/26 Art. 161(2)(b): a decomposed own LGD is kept.

        Both frameworks make the supervisory subtype LGD conditional on the firm
        NOT having a reliable own estimate — CRR Art. 161(2) permits "the LGD
        estimate for purchased corporate receivables" where the institution can
        decompose its EL estimates into PDs and LGDs, and PS1/26 Art. 161(2)(b)(i)
        requires the decomposition's LGD. A supplied ``lgd`` is that estimate, so
        it must survive; this is why the fix keys on the absence of an own LGD
        rather than on the approach.
        """
        # Arrange
        exposures = _exposures(
            purchased_receivables_subtype="subordinated",
            el_estimate=_EL_SUBORDINATED,
            lgd=0.62,
        )

        # Act
        row = _classify_with_lgd(_crr_config(), exposures)

        # Assert — the firm's estimate, not the 100% supervisory value
        assert row["lgd"] == pytest.approx(0.62)


# ---------------------------------------------------------------------------
# (C) Art. 160(6) — dilution risk: PD = EL estimate for dilution risk
# ---------------------------------------------------------------------------


class TestDilutionRiskTopDownPD:
    def test_dilution_pd_equals_the_dilution_el_estimate(self) -> None:
        # Arrange — the dilution EL is a SEPARATE input from the default-risk EL
        exposures = _exposures(
            purchased_receivables_subtype="dilution_risk",
            el_dilution_estimate=_EL_DILUTION,
        )

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert
        assert row["internal_pd"] == pytest.approx(_EL_DILUTION)

    def test_dilution_lgd_is_the_crr_supervisory_value_on_advanced_irb(self) -> None:
        """CRR Art. 161(1)(g) / PS1/26 Art. 161(2)(a)(iii): 75% under CRR, not 45%.

        Note CRR Art. 161(1)(g) carries no "unable to estimate PDs" condition at
        all — the 75% dilution-risk LGD is unconditional on the subtype.
        """
        # Arrange
        exposures = _exposures(
            purchased_receivables_subtype="dilution_risk",
            el_dilution_estimate=_EL_DILUTION,
        )

        # Act
        row = _classify_with_lgd(_crr_config(), exposures)

        # Assert
        assert row["approach"] == ApproachType.AIRB.value
        assert row["lgd"] == pytest.approx(_LGD_PR_DILUTION_CRR)

    def test_b31_dilution_lgd_is_the_raised_supervisory_value_on_advanced_irb(self) -> None:
        # Arrange — PS1/26 Art. 161(1)(g) raises dilution risk from 75% to 100%
        exposures = _exposures(
            purchased_receivables_subtype="dilution_risk",
            el_dilution_estimate=_EL_DILUTION,
        )

        # Act
        row = _classify_with_lgd(
            _b31_airb_config(),
            exposures,
            counterparties=_counterparties(revenue=_MID_CORPORATE_REVENUE),
        )

        # Assert
        assert row["approach"] == ApproachType.AIRB.value
        assert row["lgd"] == pytest.approx(_LGD_PR_DILUTION_B31)

    def test_dilution_row_ignores_the_default_risk_el_estimate(self) -> None:
        # Arrange — only el_estimate populated on a dilution_risk row
        exposures = _exposures(
            purchased_receivables_subtype="dilution_risk", el_estimate=_EL_SENIOR
        )

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — Art. 160(6) needs the dilution EL; the default-risk EL is not it
        assert row["internal_pd"] is None
        assert row["approach"] == ApproachType.SA.value


# ---------------------------------------------------------------------------
# (D) Null semantics — an absent EL estimate must change nothing
# ---------------------------------------------------------------------------


class TestNullSemantics:
    def test_subtype_without_el_estimate_stays_on_sa(self) -> None:
        # Arrange — a receivables pool the firm supplied no EL estimate for
        exposures = _exposures(purchased_receivables_subtype="senior")

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — PD stays NULL (never 0.0) and the row keeps today's SA route
        assert row["internal_pd"] is None
        assert row["pd"] is None
        assert row["approach"] == ApproachType.SA.value

    def test_el_estimate_without_subtype_is_ignored(self) -> None:
        # Arrange — Art. 160(2) is a purchased-receivables rule only
        exposures = _exposures(purchased_receivables_subtype=None, el_estimate=_EL_SENIOR)

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert
        assert row["internal_pd"] is None
        assert row["approach"] == ApproachType.SA.value

    def test_retail_row_with_a_subtype_derives_no_top_down_pd(self) -> None:
        """Art. 160(2)/(6) reach purchased *corporate* receivables only.

        Without a class gate a retail row carrying ``subtype="senior"`` would take
        ``PD = EL / 0.45``, where 0.45 is the CORPORATE Art. 161(1)(e) LGD. Retail
        IRB is own-estimate only: Art. 163 has no senior EL/LGD limb and there is
        no supervisory retail LGD, so nothing authorises that divisor. The row must
        derive nothing and keep its existing route.
        """
        # Arrange — a natural person, so the row classifies retail, not corporate
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=_EL_SENIOR)

        # Act
        row = _classify(
            _crr_config(), exposures, counterparties=_counterparties(entity_type="individual")
        )

        # Assert — no derived PD, and therefore no IRB route opened by one
        assert row["exposure_class_irb"] not in {
            ExposureClass.CORPORATE.value,
            ExposureClass.CORPORATE_SME.value,
        }
        assert row["internal_pd"] is None
        assert row["pd"] is None

    def test_firm_supplied_pd_outranks_the_top_down_derivation(self) -> None:
        # Arrange — Art. 160(2) fires only where the institution cannot estimate PD
        exposures = _exposures(
            purchased_receivables_subtype="senior",
            el_estimate=_EL_SENIOR,
            internal_pd=0.012,
        )

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — the firm's own estimate is kept, not 0.05
        assert row["internal_pd"] == pytest.approx(0.012)


# ---------------------------------------------------------------------------
# (E) Probability bounds — EL/LGD can exceed 1.0
# ---------------------------------------------------------------------------


class TestDerivedPDBounds:
    def test_derived_pd_is_capped_at_one(self) -> None:
        # Arrange — 0.60 / 0.45 = 1.333..., not a probability
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=0.60)

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — capped at 100% (the Art. 160(3) ceiling for a defaulted obligor)
        assert row["internal_pd"] == pytest.approx(1.0)

    def test_non_positive_el_estimate_does_not_derive_a_pd(self) -> None:
        # Arrange — a zero EL cannot mean "PD = 0"; treat it as no estimate
        exposures = _exposures(purchased_receivables_subtype="senior", el_estimate=0.0)

        # Act
        row = _classify(_crr_config(), exposures)

        # Assert — no derivation, no silent PD 0.0, row stays on SA
        assert row["internal_pd"] is None
        assert row["approach"] == ApproachType.SA.value
