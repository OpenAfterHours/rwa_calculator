"""
Specialised lending under the Basel 3.1 SA, end to end (review cluster "sl").

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SA / Slotting
    -> Aggregator, through ``PipelineOrchestrator.run_with_data``.

Three defects, each measured through the real pipeline on a small in-memory
bundle (GBP 1,000,000 drawn loans to GB specialised-lending SPVs, revenue
GBP 500m so no SME limb, value 2025-01-01, maturity 2030-01-01; Basel 3.1 at
2027-06-30, CRR at 2026-06-30):

IV-01 — the project-finance phase never reached the SA risk weight. The SL join
selected only ``sl_type`` / ``slotting_category`` / ``is_hvcre``, so
``sl_project_phase`` was always null and every unrated PF row took the 100%
operational weight. PRA PS1/26 Art. 122B(2)(c): "project finance exposures
shall be assigned a risk weight of 130% during the pre-operational phase, and
(subject to paragraph 4) 100% during the operational phase." Art. 122B(4):
"Where a project finance exposure is in the operational phase and is considered
high quality in accordance with the criteria in paragraph 5, an institution
shall assign a risk weight of 80%." Art. 122B(3) defines the operational phase
by evidenced conditions ("a positive net cash-flow that is sufficient to cover
any remaining contractual obligations ... and (b) declining long-term debt"),
so a phase that is not supplied is not demonstrated: ORCHESTRATOR DECISION —
null / unrecognised phase takes the pre-operational weight and raises SA006.
The 80% leg is RWA-reducing; it is taken only on the firm's explicit
``high_quality_operational`` attestation of the Art. 122B(5) criteria.

IV-02 / RG-01 — IPRE / HVCRE were forced onto the slotting approach with no IRB
permission at all. PS1/26 Art. 107(1): institutions "shall apply either the
Standardised Approach ... or, if permitted by the PRA in accordance with ...
Article 143, the IRB Approach"; Art. 147A(1)(c): for IPRE and HVCRE "(i) the
Standardised Approach for exposures where permission has been granted under
Article 148 or Article 150; or (ii) the Slotting Approach for all other IPRE
exposures and HVCRE exposures". ORCHESTRATOR DECISION — the forced slotting
requires an IRB / slotting permission covering the exposure and no applicable
standardised (Art. 148 / 150) model-permission row; otherwise SA (including the
Art. 124K 150% ADC weight where the row is ADC).

IV-03 — the Art. 133(5) 150% subordinated-debt weight missed specialised-lending
rows. PS1/26 Art. 133(5): "An institution shall assign a risk weight of 150% to
an exposure that is a subordinated debt instrument, an own funds instrument or
an equity instrument and is not classified as an equity exposure". Table A2
ranks row (3) "Subordinated debt, equity and other own funds instruments" above
the corporate class, of which specialised lending is a sub-class (Art. 122A).
ORCHESTRATOR DECISION — the predicate includes the SL class; CRR unchanged.

Every Basel 3.1 assertion has a CRR control on the same inputs (LESSONS C7).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_EAD = 1_000_000.0
_B31_DATE = date(2027, 6, 30)
_CRR_DATE = date(2026, 6, 30)
_MODEL_ID = "SL_REVIEW_MODEL"
_PF_PHASE_MISSING = "SA006"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _cp(ref: str, entity_type: str = "specialised_lending") -> dict[str, Any]:
    return {
        "counterparty_reference": ref,
        "entity_type": entity_type,
        "country_code": "GB",
        "annual_revenue": 500_000_000.0,
    }


def _loan(ref: str, cp_ref: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "drawn_amount": _EAD,
        "currency": "GBP",
        "value_date": date(2025, 1, 1),
        "maturity_date": date(2030, 1, 1),
        "seniority": "senior",
        "is_under_construction": False,
    }
    row.update(extra)
    return row


def _sl(rows: list[tuple[str, str, str | None, bool]]) -> pl.DataFrame:
    """(counterparty, sl_type, project_phase, is_hvcre) -> SL table, grade 'strong'."""
    return pl.DataFrame(
        {
            "counterparty_reference": [r[0] for r in rows],
            "sl_type": [r[1] for r in rows],
            "project_phase": [r[2] for r in rows],
            "slotting_category": ["strong"] * len(rows),
            "is_hvcre": [r[3] for r in rows],
        },
        schema={
            "counterparty_reference": pl.String,
            "sl_type": pl.String,
            "project_phase": pl.String,
            "slotting_category": pl.String,
            "is_hvcre": pl.Boolean,
        },
    )


def _config(
    regime: str,
    *,
    permission_mode: PermissionMode = PermissionMode.STANDARDISED,
    irb_permissions: IRBPermissions | None = None,
) -> CalculationConfig:
    if regime == "crr":
        config = CalculationConfig.crr(reporting_date=_CRR_DATE, permission_mode=permission_mode)
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=_B31_DATE, permission_mode=permission_mode
        )
    if irb_permissions is not None:
        config = dataclasses.replace(config, irb_permissions=irb_permissions)
    return config


def _run(config: CalculationConfig, **frames: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Run the pipeline; return {exposure_reference: row} and the error codes."""
    result = PipelineOrchestrator().run_with_data(make_raw_bundle(**frames), config)
    rows = result.results.collect().to_dicts()
    return {row["exposure_reference"]: row for row in rows}, {e.code for e in result.errors}


def _errors_with_code(config: CalculationConfig, code: str, **frames: Any) -> list[str]:
    result = PipelineOrchestrator().run_with_data(make_raw_bundle(**frames), config)
    return [e.message for e in result.errors if e.code == code]


# ---------------------------------------------------------------------------
# IV-01: project-finance phase
# ---------------------------------------------------------------------------

_PF_PHASES: list[tuple[str, str | None]] = [
    ("PRE", "pre_operational"),
    ("HQ", "high_quality_operational"),
    ("OP", "operational"),
    ("NULL", None),
    ("BAD", "construction"),
]


def _pf_phase_frames() -> dict[str, pl.DataFrame]:
    return {
        "counterparties": pl.DataFrame([_cp(f"PF_{tag}") for tag, _ in _PF_PHASES]),
        "loans": pl.DataFrame([_loan(f"L_{tag}", f"PF_{tag}") for tag, _ in _PF_PHASES]),
        "specialised_lending": _sl(
            [(f"PF_{tag}", "project_finance", phase, False) for tag, phase in _PF_PHASES]
        ),
    }


class TestProjectFinancePhaseReachesSARiskWeight:
    """IV-01: the PF phase input drives the Art. 122B(2)(c)/(4) weight."""

    @pytest.mark.parametrize(
        ("loan_ref", "expected_rw", "expected_phase"),
        [
            ("L_PRE", 1.30, "pre_operational"),
            ("L_HQ", 0.80, "high_quality_operational"),
            ("L_OP", 1.00, "operational"),
            ("L_NULL", 1.30, "pre_operational"),
            ("L_BAD", 1.30, "pre_operational"),
        ],
    )
    def test_b31_sa_pf_risk_weight_follows_phase(
        self, loan_ref: str, expected_rw: float, expected_phase: str
    ) -> None:
        """B31 SA-only firm: 130% / 80% / 100%, unevidenced phase -> 130%."""
        # Arrange / Act
        rows, _ = _run(_config("b31"), **_pf_phase_frames())

        # Assert
        row = rows[loan_ref]
        assert row["approach_applied"] == ApproachType.SA.value
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(_EAD * expected_rw)
        assert row["sl_project_phase"] == expected_phase

    def test_b31_unevidenced_phase_raises_one_sa006_counting_both_rows(self) -> None:
        """The null and the unrecognised phase are reported once, with their count."""
        messages = _errors_with_code(_config("b31"), _PF_PHASE_MISSING, **_pf_phase_frames())

        assert len(messages) == 1
        assert messages[0].startswith("2 project-finance exposure(s)")

    @pytest.mark.parametrize("loan_ref", ["L_PRE", "L_HQ", "L_OP", "L_NULL", "L_BAD"])
    def test_crr_pf_phase_has_no_effect(self, loan_ref: str) -> None:
        """CRR has no SA project-finance table: unrated SL is corporate 100%."""
        rows, codes = _run(_config("crr"), **_pf_phase_frames())

        assert rows[loan_ref]["risk_weight"] == pytest.approx(1.00)
        assert rows[loan_ref]["rwa_final"] == pytest.approx(_EAD)
        assert _PF_PHASE_MISSING not in codes

    def test_crr_null_phase_is_not_defaulted(self) -> None:
        """No Art. 122B under CRR: the null phase is carried as supplied."""
        rows, _ = _run(_config("crr"), **_pf_phase_frames())

        assert rows["L_NULL"]["sl_project_phase"] is None
        assert rows["L_NULL"]["rwa_final"] == pytest.approx(_EAD)

    @pytest.mark.parametrize(
        ("loan_ref", "expected_sa_rwa"),
        [("L_PRE", 1_300_000.0), ("L_HQ", 800_000.0), ("L_NULL", 1_300_000.0)],
    )
    def test_b31_slotted_pf_output_floor_sa_equivalent_uses_phase(
        self, loan_ref: str, expected_sa_rwa: float
    ) -> None:
        """A slotting-permissioned firm's PF row carries the phase into ``sa_rwa``."""
        config = _config("b31", irb_permissions=IRBPermissions.full_irb_b31())

        rows, _ = _run(config, **_pf_phase_frames())

        assert rows[loan_ref]["approach_applied"] == ApproachType.SLOTTING.value
        assert rows[loan_ref]["sa_rwa"] == pytest.approx(expected_sa_rwa)


# ---------------------------------------------------------------------------
# IV-02 / RG-01: IPRE / HVCRE slotting needs an IRB permission
# ---------------------------------------------------------------------------


def _re_sl_frames(**extra: pl.DataFrame) -> dict[str, pl.DataFrame]:
    frames = {
        "counterparties": pl.DataFrame([_cp("HV"), _cp("IP")]),
        "loans": pl.DataFrame(
            [_loan("L_HV", "HV", is_under_construction=True), _loan("L_IP", "IP")]
        ),
        "specialised_lending": _sl([("HV", "hvcre", None, True), ("IP", "ipre", None, False)]),
    }
    frames.update(extra)
    return frames


def _ratings() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "rating_reference": ["R_HV", "R_IP"],
            "counterparty_reference": ["HV", "IP"],
            "rating_type": ["internal", "internal"],
            "rating_agency": ["internal", "internal"],
            "pd": [0.01, 0.01],
            "rating_date": [date(2026, 1, 1), date(2026, 1, 1)],
            "model_id": [_MODEL_ID, _MODEL_ID],
        }
    )


def _model_permissions(rows: list[tuple[str, str | None]]) -> pl.DataFrame:
    """(approach, ppu_reason) rows for the specialised-lending class."""
    return pl.DataFrame(
        {
            "model_id": [_MODEL_ID] * len(rows),
            "exposure_class": ["specialised_lending"] * len(rows),
            "approach": [r[0] for r in rows],
            "ppu_reason": [r[1] for r in rows],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "ppu_reason": pl.String,
        },
    )


class TestIpreHvcreSlottingNeedsIrbPermission:
    """IV-02 / RG-01: Art. 147A(1)(c) applies only to a firm permitted to use IRB."""

    @pytest.mark.parametrize(
        ("regime", "loan_ref", "expected_rw"),
        [
            ("b31", "L_HV", 1.50),
            ("b31", "L_IP", 1.00),
            ("crr", "L_HV", 1.00),
            ("crr", "L_IP", 1.00),
        ],
    )
    def test_sa_only_firm_keeps_ipre_hvcre_on_sa(
        self, regime: str, loan_ref: str, expected_rw: float
    ) -> None:
        """No IRB permission: SA in both regimes.

        Basel 3.1: the ADC HVCRE row takes the Art. 124K 150% and the
        unsecured IPRE row 100%; before the fix both were slotted, HVCRE strong
        95% (950,000) and IPRE strong 70% (700,000). CRR (no Art. 124K, no
        forced slotting): unrated corporate 100% for both, before and after.
        """
        rows, _ = _run(_config(regime), **_re_sl_frames())

        row = rows[loan_ref]
        assert row["approach_applied"] == ApproachType.SA.value
        assert row["rwa_final"] == pytest.approx(_EAD * expected_rw)

    @pytest.mark.parametrize(
        ("loan_ref", "expected_rw"),
        [("L_HV", 0.95), ("L_IP", 0.70)],
    )
    def test_b31_orgwide_slotting_permission_still_forces_slotting(
        self, loan_ref: str, expected_rw: float
    ) -> None:
        """Art. 147A(1)(c)(ii) is untouched for a permissioned firm (strong grade)."""
        config = _config("b31", irb_permissions=IRBPermissions.full_irb_b31())

        rows, _ = _run(config, **_re_sl_frames())

        assert rows[loan_ref]["approach_applied"] == ApproachType.SLOTTING.value
        assert rows[loan_ref]["rwa_final"] == pytest.approx(_EAD * expected_rw)

    def test_b31_model_slotting_permission_forces_slotting(self) -> None:
        """A model-permission row for SL slotting keeps IPRE on slotting."""
        config = _config("b31", permission_mode=PermissionMode.IRB)
        frames = _re_sl_frames(
            ratings=_ratings(),
            model_permissions=_model_permissions([(ApproachType.SLOTTING.value, None)]),
        )

        rows, _ = _run(config, **frames)

        assert rows["L_IP"]["approach_applied"] == ApproachType.SLOTTING.value
        assert rows["L_IP"]["rwa_final"] == pytest.approx(700_000.0)

    def test_b31_model_airb_permission_still_forces_slotting(self) -> None:
        """An A-IRB SL permission covers IPRE, which Art. 147A(1)(c)(ii) slots."""
        config = _config("b31", permission_mode=PermissionMode.IRB)
        frames = _re_sl_frames(
            ratings=_ratings(),
            model_permissions=_model_permissions([(ApproachType.AIRB.value, None)]),
        )

        rows, _ = _run(config, **frames)

        assert rows["L_IP"]["approach_applied"] == ApproachType.SLOTTING.value

    def test_b31_art_150_standardised_row_keeps_ipre_on_sa(self) -> None:
        """Art. 147A(1)(c)(i): an Art. 150 SA permission row overrides slotting."""
        config = _config("b31", permission_mode=PermissionMode.IRB)
        frames = _re_sl_frames(
            ratings=_ratings(),
            model_permissions=_model_permissions(
                [
                    (ApproachType.SLOTTING.value, None),
                    (ApproachType.SA.value, "art_150_1_a"),
                ]
            ),
        )

        rows, _ = _run(config, **frames)

        assert rows["L_IP"]["approach_applied"] == ApproachType.SA.value
        assert rows["L_IP"]["rwa_final"] == pytest.approx(_EAD)
        assert rows["L_HV"]["approach_applied"] == ApproachType.SA.value
        assert rows["L_HV"]["rwa_final"] == pytest.approx(1_500_000.0)

    def test_b31_irb_mode_without_model_permissions_stays_sa(self) -> None:
        """IRB mode with no model_permissions table grants no IRB permission."""
        config = _config("b31", permission_mode=PermissionMode.IRB)

        rows, _ = _run(config, **_re_sl_frames())

        assert rows["L_IP"]["approach_applied"] == ApproachType.SA.value


# ---------------------------------------------------------------------------
# IV-03: Art. 133(5) subordinated debt includes specialised lending
# ---------------------------------------------------------------------------


def _sub_debt_frames() -> dict[str, pl.DataFrame]:
    return {
        "counterparties": pl.DataFrame([_cp("PF_OP"), _cp("PF_PRE"), _cp("OF")]),
        "loans": pl.DataFrame(
            [
                _loan("L_MEZZ_OP", "PF_OP", seniority="subordinated"),
                _loan("L_SEN_OP", "PF_OP"),
                _loan("L_MEZZ_PRE", "PF_PRE", seniority="subordinated"),
                _loan("L_MEZZ_OF", "OF", seniority="subordinated"),
            ]
        ),
        "specialised_lending": _sl(
            [
                ("PF_OP", "project_finance", "operational", False),
                ("PF_PRE", "project_finance", "pre_operational", False),
                ("OF", "object_finance", None, False),
            ]
        ),
    }


class TestSubordinatedSpecialisedLendingTakesArt1335:
    """IV-03: subordinated SL rows take the Art. 133(5) 150% under Basel 3.1."""

    @pytest.mark.parametrize(
        ("regime", "loan_ref", "expected_rw"),
        [
            ("b31", "L_MEZZ_OP", 1.50),
            ("b31", "L_MEZZ_PRE", 1.50),
            ("b31", "L_MEZZ_OF", 1.50),
            ("b31", "L_SEN_OP", 1.00),
            ("crr", "L_MEZZ_OP", 1.00),
            ("crr", "L_MEZZ_PRE", 1.00),
            ("crr", "L_MEZZ_OF", 1.00),
        ],
    )
    def test_sa_subordinated_sl_risk_weight(
        self, regime: str, loan_ref: str, expected_rw: float
    ) -> None:
        """B31: 150% outranks the PF / OF type weights; CRR keeps corporate 100%."""
        rows, _ = _run(_config(regime), **_sub_debt_frames())

        assert rows[loan_ref]["risk_weight"] == pytest.approx(expected_rw)
        assert rows[loan_ref]["rwa_final"] == pytest.approx(_EAD * expected_rw)

    def test_b31_slotted_subordinated_sl_output_floor_sa_equivalent(self) -> None:
        """The slotted row's output-floor SA-equivalent is the 150% weight.

        The slotting RWEA itself (strong, 70%) is unchanged; ``rwa_final`` is not
        asserted because this portfolio's floor binds (U-TREA 2.8m < 60% x
        S-TREA 5.5m) and spreads an add-on over every row.
        """
        config = _config("b31", irb_permissions=IRBPermissions.full_irb_b31())

        rows, _ = _run(config, **_sub_debt_frames())

        row = rows["L_MEZZ_OP"]
        assert row["approach_applied"] == ApproachType.SLOTTING.value
        assert row["rwa_pre_floor"] == pytest.approx(700_000.0)
        assert row["sa_rwa"] == pytest.approx(1_500_000.0)


# ---------------------------------------------------------------------------
# IV-09 (warning half): a slotted row with no recognised grade is flagged
# ---------------------------------------------------------------------------

_SLOTTING_GRADE_MISSING = "CLS012"


def _graded_frames(grades: list[str | None]) -> dict[str, pl.DataFrame]:
    refs = [f"G{i}" for i in range(len(grades))]
    return {
        "counterparties": pl.DataFrame([_cp(ref) for ref in refs]),
        "loans": pl.DataFrame([_loan(f"L_{ref}", ref) for ref in refs]),
        "specialised_lending": pl.DataFrame(
            {
                "counterparty_reference": refs,
                "sl_type": ["project_finance"] * len(refs),
                "project_phase": ["operational"] * len(refs),
                "slotting_category": grades,
                "is_hvcre": [False] * len(refs),
            },
            schema_overrides={"slotting_category": pl.String},
        ),
    }


def _slotting_config(regime: str) -> CalculationConfig:
    permissions = IRBPermissions.full_irb() if regime == "crr" else IRBPermissions.full_irb_b31()
    return _config(regime, irb_permissions=permissions)


class TestMissingSlottingGradeIsFlagged:
    """IV-09, warning half only: the grade-less slotted row is no longer silent.

    CRR Art. 153(5) and PS1/26 Art. 153(5) weight a slotted exposure by the
    grade the institution assigns it; the engine weights a null or
    unrecognised grade at the cited pack default ``satisfactory`` (115%). That
    default is a recorded owner decision (the verifier: no rule sets a fallback
    grade; switching to 'weak' is not decided) and is unchanged here — the
    defect fixed is that it was applied with no warning, in both regimes.
    """

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_null_and_unrecognised_grade_raise_one_cls012(self, regime: str) -> None:
        messages = _errors_with_code(
            _slotting_config(regime),
            _SLOTTING_GRADE_MISSING,
            **_graded_frames([None, "excellent", "weak"]),
        )

        assert len(messages) == 1
        assert messages[0].startswith("2 slotting exposure(s)")

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_missing_grade_keeps_the_cited_satisfactory_weight(self, regime: str) -> None:
        rows, _ = _run(_slotting_config(regime), **_graded_frames([None, "weak"]))

        assert rows["L_G0"]["approach_applied"] == ApproachType.SLOTTING.value
        assert rows["L_G0"]["rwa_final"] == pytest.approx(1_150_000.0)
        assert rows["L_G1"]["rwa_final"] == pytest.approx(2_500_000.0)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_graded_or_sa_rows_raise_no_cls012(self, regime: str) -> None:
        """Every grade recognised -> silent; an SA-only firm never slots -> silent."""
        graded = _errors_with_code(
            _slotting_config(regime), _SLOTTING_GRADE_MISSING, **_graded_frames(["good", "weak"])
        )
        sa_only = _errors_with_code(
            _config(regime), _SLOTTING_GRADE_MISSING, **_graded_frames([None])
        )

        assert graded == []
        assert sa_only == []
