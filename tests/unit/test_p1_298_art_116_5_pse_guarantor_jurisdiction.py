"""
P1.298: CRR Art. 116(5) jurisdiction gate on the PSE *guarantor* branch.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/rw_adjustments.py::apply_guarantee_substitution)
                 -> IRBCalculator (engine/irb/guarantee.py::_compute_guarantor_rw_sa)
    Both compile ``engine/sa/guarantor_rw.py::build_guarantor_rw_expr``.

Key responsibilities:
- A third-country PSE guarantor with no asserted equivalence determination is a
  "comparable direct exposure" weighted at Art. 116(5)'s flat 100%, so the
  substituted weight on the covered part is 100% whatever its CQS — not the
  Table 2A 20% / 50% / 150% the guarantor branch gave before.
- The gate reads the GUARANTOR's own jurisdiction (``guarantor_country_code`` /
  ``guarantor_is_equivalent_jurisdiction``), never the obligor's ``cp_*`` twins.
- The RGLA branch, which shares the PSE branch's Table 1B/2A values and its
  unrated fallback, is untouched: Art. 115 has no "Otherwise 100%" residual.

Regulatory basis (quoted verbatim):
    CRR Art. 116(5): "When competent authorities of a third country jurisdiction,
    which apply supervisory and regulatory arrangements at least equivalent to
    those applied in the United Kingdom, treat exposures to public sector entities
    in accordance with paragraph 1 or 2, institutions may risk weight exposures to
    such public sector entities in the same manner. Otherwise the institutions
    shall apply a risk weight of 100 %."
    CRR Art. 235(1): "g the risk weight of exposures to the protection provider as
    specified under Chapter 2 of this Regulation ...".
    PS1/26 Art. 235(1)(a): "rg = the risk weight of a comparable direct exposure to
    the protection provider as specified under the Credit Risk: Standardised
    Approach (CRR) Part and Chapter 2 of Title II of Part Three of CRR."
    PS1/26 Art. 116(3A) admits third-country PSEs to paragraphs 1 and 2 only "For
    the purpose of Article 116(5) of CRR", and Art. 116(5) reads "[Note: Provision
    not in PRA Rulebook]" — it survives in CRR. One gate, both regimes.

References:
    - CRR Art. 116(5), Art. 201(1)(e), Art. 235(1)
    - PRA PS1/26 Art. 116(3A), Art. 235(1)(a)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.irb.transforms import (
    apply_guarantee_substitution as irb_apply_guarantee_substitution,
)
from rwa_calc.engine.sa.rw_adjustments import apply_guarantee_substitution

# Art. 116(5) residual for a non-equivalent third-country PSE.
NON_EQUIVALENT_RW: float = 1.00
# PS1/26 Art. 116(2) Table 2A / CRR Art. 116(2) -> Art. 120 Table 3 (identical).
TABLE_2A: dict[int, float] = {1: 0.20, 2: 0.50, 6: 1.50}
# Art. 115(1)(b) Table 1B — the RGLA control (identical values to Table 2A).
TABLE_1B: dict[int, float] = {1: 0.20, 6: 1.50}

_ABSENT = object()


def _config(regime: str) -> CalculationConfig:
    """CRR (2026) or Basel 3.1 (2027) configuration — the gate is regime-invariant."""
    if regime == "b31":
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


def _guarantee_frame(
    *,
    entity_type: str,
    cqs: int | None,
    country: str | None,
    equivalent: bool | None | object,
    obligor_country: str = "GB",
    obligor_equivalent: bool | None = None,
    obligor_rw: float = 1.50,
    irb: bool = False,
) -> pl.LazyFrame:
    """One fully guaranteed row; ``equivalent=_ABSENT`` omits the flag column."""
    data: dict[str, list[Any]] = {
        "exposure_reference": ["EXP001"],
        "ead_final": [1_000_000.0],
        "risk_weight": [obligor_rw],
        "guaranteed_portion": [1_000_000.0],
        "unguaranteed_portion": [0.0],
        "guarantor_entity_type": [entity_type],
        "guarantor_cqs": [cqs],
        "guarantor_country_code": [country],
        "cp_country_code": [obligor_country],
        "cp_is_equivalent_jurisdiction": [obligor_equivalent],
        "currency": ["GBP"],
    }
    schema: dict[str, pl.DataType] = {
        "guarantor_cqs": pl.Int8(),
        "guarantor_country_code": pl.String(),
        "cp_country_code": pl.String(),
        "cp_is_equivalent_jurisdiction": pl.Boolean(),
    }
    if equivalent is not _ABSENT:
        data["guarantor_is_equivalent_jurisdiction"] = [equivalent]
        schema["guarantor_is_equivalent_jurisdiction"] = pl.Boolean()
    if irb:
        data.update(
            {
                "pd": [0.02],
                "lgd": [0.45],
                "maturity": [5.0],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "rwa": [1_000_000.0 * obligor_rw],
            }
        )
    return pl.LazyFrame(data, schema_overrides=schema)


def _sa_guarantor_rw(regime: str, **frame: Any) -> float:
    """SA substitution path: the ``guarantor_rw`` priced for the covered part."""
    result = apply_guarantee_substitution(_guarantee_frame(**frame), _config(regime)).collect()
    return float(result["guarantor_rw"][0])


def _irb_guarantor_rw(regime: str, **frame: Any) -> float:
    """IRB path: no guarantor PD, so ``guarantor_rw`` is the SA ``guarantor_rw_sa``."""
    lf = _guarantee_frame(irb=True, **frame)
    result = lf.pipe(irb_apply_guarantee_substitution, _config(regime)).collect()
    return float(result["guarantor_rw"][0])


# label -> (frame kwargs, expected guarantor RW, pre-fix RW or None when unchanged)
_CASES: dict[str, tuple[dict[str, Any], float, float | None]] = {
    # --- the gate binds: third country, no affirmative determination -> 100% ---
    "us-cqs1-flag-null": (
        {"entity_type": "pse_institution", "cqs": 1, "country": "US", "equivalent": None},
        NON_EQUIVALENT_RW,
        TABLE_2A[1],
    ),
    "us-cqs1-flag-false": (
        {"entity_type": "pse_institution", "cqs": 1, "country": "US", "equivalent": False},
        NON_EQUIVALENT_RW,
        TABLE_2A[1],
    ),
    "us-cqs1-flag-column-absent": (
        {"entity_type": "pse_institution", "cqs": 1, "country": "US", "equivalent": _ABSENT},
        NON_EQUIVALENT_RW,
        TABLE_2A[1],
    ),
    # A null country cannot prove UK-ness (the direct path's null rule).
    "null-country-cqs1-flag-null": (
        {"entity_type": "pse_institution", "cqs": 1, "country": None, "equivalent": None},
        NON_EQUIVALENT_RW,
        TABLE_2A[1],
    ),
    # Art. 116(2) PSEs include the pse_sovereign entity type (SA class PSE).
    "us-pse-sovereign-cqs2-flag-null": (
        {"entity_type": "pse_sovereign", "cqs": 2, "country": "US", "equivalent": None},
        NON_EQUIVALENT_RW,
        TABLE_2A[2],
    ),
    # The RWA-REDUCING slice: "Otherwise ... 100 %" is flat, whatever the rating.
    "us-cqs6-flag-null": (
        {"entity_type": "pse_institution", "cqs": 6, "country": "US", "equivalent": None},
        NON_EQUIVALENT_RW,
        TABLE_2A[6],
    ),
    # Anti-sibling: the OBLIGOR is a US counterparty with equivalence asserted;
    # the guarantor's own flag is null. A gate wired to cp_* would grant 20%.
    "obligor-equivalent-guarantor-not": (
        {
            "entity_type": "pse_institution",
            "cqs": 1,
            "country": "US",
            "equivalent": None,
            "obligor_country": "US",
            "obligor_equivalent": True,
        },
        NON_EQUIVALENT_RW,
        TABLE_2A[1],
    ),
    # --- permitted limbs: must NOT move ---
    "us-cqs1-flag-true": (
        {"entity_type": "pse_institution", "cqs": 1, "country": "US", "equivalent": True},
        TABLE_2A[1],
        None,
    ),
    "gb-cqs2-flag-null": (
        {"entity_type": "pse_institution", "cqs": 2, "country": "GB", "equivalent": None},
        TABLE_2A[2],
        None,
    ),
    # Mirror of the anti-sibling case: the OBLIGOR is non-equivalent, the
    # guarantor is equivalent. A gate wired to cp_* would deny the 20%.
    "obligor-not-equivalent-guarantor-is": (
        {
            "entity_type": "pse_institution",
            "cqs": 1,
            "country": "US",
            "equivalent": True,
            "obligor_country": "US",
            "obligor_equivalent": None,
        },
        TABLE_2A[1],
        None,
    ),
    # Unrated non-GB PSE was already 100% (the unrated fallback).
    "us-unrated-flag-null": (
        {"entity_type": "pse_institution", "cqs": None, "country": "US", "equivalent": None},
        NON_EQUIVALENT_RW,
        None,
    ),
    # --- RGLA control: Art. 115 has no Art. 116(5)-style residual ---
    "rgla-us-cqs1-flag-null": (
        {"entity_type": "rgla_institution", "cqs": 1, "country": "US", "equivalent": None},
        TABLE_1B[1],
        None,
    ),
    "rgla-us-cqs6-flag-null": (
        {"entity_type": "rgla_institution", "cqs": 6, "country": "US", "equivalent": None},
        TABLE_1B[6],
        None,
    ),
}

_MOVED = sorted(label for label, (_, _, pre) in _CASES.items() if pre is not None)


class TestSAGuarantorPSEJurisdictionGate:
    """SA guarantee substitution: the guarantor PSE branch applies Art. 116(5)."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("label", sorted(_CASES))
    def test_guarantor_rw(self, regime: str, label: str) -> None:
        """
        Arrange: one fully guaranteed SA row; the guarantor's class, CQS, country
                 and equivalence flag vary per case.
        Act:     apply_guarantee_substitution under the named regime.
        Assert:  guarantor_rw is the Art. 116(5)-gated direct weight of the guarantor.
        """
        frame, expected, _pre_fix = _CASES[label]

        rw = _sa_guarantor_rw(regime, **frame)

        assert rw == pytest.approx(expected, abs=1e-12), (
            f"{regime}/{label}: guarantor_rw {rw} != {expected} (CRR Art. 116(5) / Art. 235(1))"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("label", _MOVED)
    def test_gated_rows_left_the_table_2a_weight(self, regime: str, label: str) -> None:
        """
        Anti-confound: every gated row moved OFF the Table 2A weight it took before.

        Arrange: the cases the gate binds on (each with a pre-fix weight != 100%).
        Act:     apply_guarantee_substitution.
        Assert:  the result is not the pre-fix Table 2A weight.
        """
        frame, _expected, pre_fix = _CASES[label]

        rw = _sa_guarantor_rw(regime, **frame)

        assert rw != pytest.approx(pre_fix, abs=1e-12)


class TestIRBGuarantorPSEJurisdictionGate:
    """IRB guarantee substitution: guarantor_rw_sa carries the same gate."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        "label",
        [
            "us-cqs1-flag-null",
            "us-cqs1-flag-column-absent",
            "null-country-cqs1-flag-null",
            "us-cqs6-flag-null",
            "obligor-equivalent-guarantor-not",
            "us-cqs1-flag-true",
            "gb-cqs2-flag-null",
            "rgla-us-cqs6-flag-null",
        ],
    )
    def test_guarantor_rw_sa(self, regime: str, label: str) -> None:
        """
        Arrange: one fully guaranteed IRB row, no guarantor PD (RWSM fallback).
        Act:     the IRB apply_guarantee_substitution.
        Assert:  guarantor_rw (= guarantor_rw_sa) equals the SA path's gated weight.
        """
        frame, expected, _pre_fix = _CASES[label]

        rw = _irb_guarantor_rw(regime, **frame)

        assert rw == pytest.approx(expected, abs=1e-12), (
            f"{regime}/{label}: IRB guarantor_rw {rw} != {expected}"
        )


class TestBenefitTestAfterTheGate:
    """The strict-< Art. 193(1) benefit test sees the gated weight."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_non_equivalent_cqs1_guarantee_declined_over_100pct_obligor(self, regime: str) -> None:
        """
        Arrange: obligor at 100%, US CQS1 PSE guarantor with no equivalence flag.
        Act:     SA guarantee substitution.
        Assert:  guarantor_rw 1.00 is not < 1.00, so the guarantee is not beneficial
                 (pre-fix: 0.20 < 1.00, beneficial).
        """
        frame = _guarantee_frame(
            entity_type="pse_institution", cqs=1, country="US", equivalent=None, obligor_rw=1.0
        )

        result = apply_guarantee_substitution(frame, _config(regime)).collect()

        assert result["is_guarantee_beneficial"][0] is False

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_non_equivalent_cqs6_guarantee_now_beneficial_over_150pct_obligor(
        self, regime: str
    ) -> None:
        """
        Arrange: obligor at 150%, US CQS6 PSE guarantor with no equivalence flag.
        Act:     SA guarantee substitution.
        Assert:  guarantor_rw 1.00 < 1.50, so the guarantee is beneficial
                 (pre-fix: 1.50 is not < 1.50, declined) — the RWA-reducing slice.
        """
        frame = _guarantee_frame(
            entity_type="pse_institution", cqs=6, country="US", equivalent=None, obligor_rw=1.5
        )

        result = apply_guarantee_substitution(frame, _config(regime)).collect()

        assert result["is_guarantee_beneficial"][0] is True
