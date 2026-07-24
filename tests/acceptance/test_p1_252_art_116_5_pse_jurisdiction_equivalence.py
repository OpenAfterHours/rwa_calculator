"""
P1.252: CRR Art. 116(5) / PS1/26 Art. 116(3A) — third-country PSE jurisdiction
equivalence gate, with a flat 100% fallback.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator
        -> OutputAggregator

Key responsibilities:
- Prove a third-country PSE with no asserted Treasury equivalence determination
  is risk-weighted at a flat 100%, and that this suppresses ALL THREE PSE
  branches: Art. 116(1) Table 2 (sovereign-derived), Art. 116(2) Table 2A
  (own rating) and the Art. 116(3) short-term 20%.
- Prove the gate is REGIME-INVARIANT — it binds identically under CRR and
  Basel 3.1 (see the regulatory note below), so every case is parametrised
  over both configs.
- Prove the two permitted limbs are untouched: a UK PSE, and a third-country
  PSE whose jurisdiction equivalence IS asserted.

Regulatory basis — the equivalence requirement exists in BOTH regimes:

    UK CRR Art. 116(5) (crr.pdf p.115) verbatim:
        "When competent authorities of a third country jurisdiction, which
        apply supervisory and regulatory arrangements at least equivalent to
        those applied in the United Kingdom, treat exposures to public sector
        entities in accordance with paragraph 1 or 2, institutions may risk
        weight exposures to such public sector entities in the same manner.
        Otherwise the institutions shall apply a risk weight of 100%.
        For the purposes of this paragraph, the Treasury may by regulations
        determine whether a third country applies supervisory and regulatory
        arrangements at least equivalent to those applied in the United
        Kingdom."

    PS1/26 Art. 116 (ps126app1.pdf pp.37-38) scopes paragraphs 1, 2 and 3 to
    "UK public sector entities" and admits third-country PSEs only through:
        "3A. For the purpose of Article 116(5) of CRR, the references in
        paragraphs 1 and 2 to: (a) the central government of the UK means the
        central government of the jurisdiction in which the third country
        public sector entity is based; and (b) UK public sector entities means
        third country public sector entities."
    and records Art. 116(5) itself as "[Note: Provision not in PRA Rulebook]"
    because the Treasury equivalence power stays in CRR. So under Basel 3.1 the
    CRR Art. 116(5) test is still the sole gateway — hence no pack Feature and
    no regime branch: one gate, both regimes.

Defect under test (pre-fix):
    ``engine/sa/risk_weights.py`` applied the Table 2, Table 2A and short-term
    branches to every PSE row keyed only on cqs / cp_sovereign_cqs /
    original_maturity_years, with no jurisdiction predicate anywhere (the audit
    notes no equivalence input existed in the schemas at all). A German unrated
    PSE whose sovereign is CQS 1 therefore received 20% in both regimes.

Null semantics for the new input:
    ``is_equivalent_jurisdiction`` is a nullable Boolean on the counterparty.
    NULL MEANS NOT EQUIVALENT. Equivalence is an affirmative Treasury
    determination; the absence of an assertion cannot manufacture one, and
    Art. 116(5)'s own residual is the 100% weight. Only an explicit True opens
    the Table 2 / 2A limbs. UK PSEs never consult the flag — a UK PSE is not a
    third-country PSE, so ``cp_country_code == "GB"`` short-circuits the gate.

References:
    - UK CRR Art. 116(1)/(2)/(3)/(5)
    - PRA PS1/26 Art. 116(1)/(2)/(3)/(3A)
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS6 (P1.252)
    - tests/acceptance/basel31/test_p1_112_pse_sovereign_derived_rw.py — the
      equivalent-jurisdiction positive control (Table 2 keys on the PSE's OWN
      sovereign CQS, not on GB-ness); reconciled with this item.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 6, 30)
_LONG_MATURITY = date(2032, 6, 30)  # 5y original maturity — not short-term
_SHORT_MATURITY = date(2027, 9, 1)  # ~0.17y original maturity — Art. 116(3)

EAD: float = 100_000_000.0

# Art. 116(1) Table 2 (sovereign-derived) and Art. 116(2) Table 2A (own
# rating) — identical values in both regimes.
TABLE_2_CQS1: float = 0.20
TABLE_2_CQS2: float = 0.50
TABLE_2A_CQS2: float = 0.50
SHORT_TERM_RW: float = 0.20
# Art. 116(5) residual for a third-country PSE without Treasury equivalence.
NON_EQUIVALENT_RW: float = 1.00

SOVEREIGN_CQS1: int = 1
SOVEREIGN_CQS2: int = 2
OWN_CQS2: int = 2

# label -> (country, sovereign_cqs, own_cqs, equivalence flag, maturity, expected RW)
_SCENARIOS: tuple[tuple[str, str, int, int | None, bool | None, date, float], ...] = (
    # --- permitted limbs (must NOT move) ---
    # UK PSE, unrated, sovereign CQS1 -> Table 2. Never consults the flag.
    ("GB-UNRATED", "GB", SOVEREIGN_CQS1, None, None, _LONG_MATURITY, TABLE_2_CQS1),
    # UK PSE, short-dated -> Art. 116(3) 20%. Sovereign CQS2 deliberately, so
    # the 20% is DISCRIMINATING: Table 2 CQS2 would be 50%, and this row is the
    # control proving the Art. 116(3) suppression below is jurisdictional
    # rather than a blanket removal of the short-term branch.
    ("GB-SHORT", "GB", SOVEREIGN_CQS2, None, None, _SHORT_MATURITY, SHORT_TERM_RW),
    # Third-country PSE WITH equivalence asserted -> Table 2 on its OWN
    # sovereign's CQS (PS1/26 Art. 116(3A)(a)). This is the P1.112 case.
    ("DE-EQUIV", "DE", SOVEREIGN_CQS1, None, True, _LONG_MATURITY, TABLE_2_CQS1),
    # --- limb (b): NO Art. 116(3) 20% for ANY non-UK PSE, even an equivalent
    # one. PS1/26 Art. 116(3A) remaps "UK public sector entities" for
    # paragraphs 1 and 2 ONLY; paragraph 3 keeps its literal UK scope. CRR
    # Art. 116(5) likewise admits third-country PSEs only "in accordance with
    # paragraph 1 or 2". So these fall through to Table 2 / Table 2A.
    # Unrated + short-dated -> Table 2 CQS2 = 50%, NOT the 20%.
    ("DE-EQUIV-SHORT", "DE", SOVEREIGN_CQS2, None, True, _SHORT_MATURITY, TABLE_2_CQS2),
    # Rated + short-dated -> Table 2A CQS2 = 50%, NOT the 20%.
    (
        "DE-EQUIV-SHORT-RATED",
        "DE",
        SOVEREIGN_CQS1,
        OWN_CQS2,
        True,
        _SHORT_MATURITY,
        TABLE_2A_CQS2,
    ),
    # --- limb (a): third-country PSE with NO equivalence assertion -> 100% ---
    # Suppresses Art. 116(1) Table 2 (pre-fix 20%).
    ("DE-UNRATED", "DE", SOVEREIGN_CQS1, None, None, _LONG_MATURITY, NON_EQUIVALENT_RW),
    # Suppresses Art. 116(2) Table 2A own-rating (pre-fix 50%).
    ("DE-RATED", "DE", SOVEREIGN_CQS1, OWN_CQS2, None, _LONG_MATURITY, NON_EQUIVALENT_RW),
    # Suppresses the Art. 116(3) short-term 20% (pre-fix 20%).
    ("DE-SHORT", "DE", SOVEREIGN_CQS1, None, None, _SHORT_MATURITY, NON_EQUIVALENT_RW),
    # An explicit False is not an assertion of equivalence.
    ("DE-EXPLICIT-FALSE", "DE", SOVEREIGN_CQS1, None, False, _LONG_MATURITY, NON_EQUIVALENT_RW),
)

# What each scenario returned before the gate existed — used as the
# anti-confound assertion. Limb (a) rows moved off their Art. 116(1)/(2)/(3)
# weight; limb (b) rows moved off the Art. 116(3) 20% they were wrongly granted.
_PRE_FIX_RW: dict[str, float] = {
    "DE-UNRATED": TABLE_2_CQS1,
    "DE-RATED": TABLE_2A_CQS2,
    "DE-SHORT": SHORT_TERM_RW,
    "DE-EXPLICIT-FALSE": TABLE_2_CQS1,
    "DE-EQUIV-SHORT": SHORT_TERM_RW,
    "DE-EQUIV-SHORT-RATED": SHORT_TERM_RW,
}

_FACILITY_MAPPING_SCHEMA = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,
}


def _build_bundle() -> RawDataBundle:
    """One unrated-or-rated PSE loan per scenario, each with its own counterparty."""
    counterparties, facilities, loans, ratings = [], [], [], []
    for label, country, sov_cqs, own_cqs, equivalent, maturity, _rw in _SCENARIOS:
        counterparties.append(
            {
                "counterparty_reference": f"CP-{label}",
                "counterparty_name": f"P1.252 PSE ({label})",
                "entity_type": "pse_institution",
                "country_code": country,
                "sovereign_cqs": sov_cqs,
                "default_status": False,
                "is_financial_sector_entity": False,
                "apply_fi_scalar": False,
                "is_equivalent_jurisdiction": equivalent,
            }
        )
        facilities.append(
            {
                "facility_reference": f"F-{label}",
                "counterparty_reference": f"CP-{label}",
                "currency": "GBP",
                "value_date": _REPORTING_DATE,
                "maturity_date": maturity,
                "limit": EAD,
                "committed": True,
                "seniority": "senior",
                "risk_type": "funded",
            }
        )
        loans.append(
            {
                "loan_reference": label,
                "counterparty_reference": f"CP-{label}",
                "currency": "GBP",
                "value_date": _REPORTING_DATE,
                "maturity_date": maturity,
                "drawn_amount": EAD,
                "interest": 0.0,
                "seniority": "senior",
            }
        )
        if own_cqs is not None:
            ratings.append(
                {
                    "rating_reference": f"RTG-{label}",
                    "counterparty_reference": f"CP-{label}",
                    "rating_type": "external",
                    "rating_agency": "Moody's",
                    "cqs": own_cqs,
                    "pd": None,
                    "rating_date": _REPORTING_DATE,
                }
            )

    return make_raw_bundle(
        facilities=pl.DataFrame(facilities, schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(loans, schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.DataFrame(counterparties, schema=dtypes_of(COUNTERPARTY_SCHEMA)),
        facility_mappings=pl.LazyFrame(schema=_FACILITY_MAPPING_SCHEMA),
        ratings=pl.DataFrame(ratings, schema=dtypes_of(RATINGS_SCHEMA)),
    )


def _run(config: CalculationConfig) -> dict[str, dict]:
    """Run the shared PSE book through the SA pipeline, keyed by exposure_reference.

    Each facility also emits a zero-limit ``*_UNDRAWN`` child row; only the
    drawn loan rows carry the PSE weights under test, so the map is filtered
    to the scenario labels.
    """
    labels = {label for label, *_ in _SCENARIOS}
    results = PipelineOrchestrator().run_with_data(_build_bundle(), config)
    assert results.sa_results is not None, "SA results must not be None for an SA-only config"
    rows = {
        row["exposure_reference"]: row
        for row in results.sa_results.collect().to_dicts()
        if row["exposure_reference"] in labels
    }
    assert set(rows) == labels, f"Expected one SA row per scenario, got {sorted(rows)}"
    return rows


# ---------------------------------------------------------------------------
# Both-regime fixtures — the gate is regime-invariant
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crr_rows() -> dict[str, dict]:
    """CRR SA results for the shared PSE book."""
    return _run(
        CalculationConfig.crr(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    )


@pytest.fixture(scope="module")
def b31_rows() -> dict[str, dict]:
    """Basel 3.1 SA results for the shared PSE book."""
    return _run(
        CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    )


@pytest.fixture(scope="module")
def rows_by_regime(crr_rows: dict[str, dict], b31_rows: dict[str, dict]) -> dict[str, dict]:
    """Both regimes' result maps, keyed by regime label."""
    return {"crr": crr_rows, "b31": b31_rows}


# ---------------------------------------------------------------------------
# P1.252 acceptance tests
# ---------------------------------------------------------------------------

_ALL_LABELS = [label for label, *_ in _SCENARIOS]
_EXPECTED_RW = {label: rw for label, *_rest, rw in _SCENARIOS}
# Limb (a) — non-equivalent third country, flat 100%.
_LIMB_A_LABELS = ["DE-UNRATED", "DE-RATED", "DE-SHORT", "DE-EXPLICIT-FALSE"]
# Limb (b) — equivalent third country, short-dated: no Art. 116(3) 20%.
_LIMB_B_LABELS = ["DE-EQUIV-SHORT", "DE-EQUIV-SHORT-RATED"]


class TestP1252PSEJurisdictionEquivalence:
    """CRR Art. 116(5) / PS1/26 Art. 116(3A) PSE jurisdiction-equivalence gate."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("label", _ALL_LABELS)
    def test_pse_risk_weight(
        self, rows_by_regime: dict[str, dict], regime: str, label: str
    ) -> None:
        """
        Every PSE row takes its Art. 116 weight, gated on jurisdiction.

        Arrange: one unrated-or-rated PSE per jurisdiction / equivalence /
                 maturity combination, EAD 100m.
        Act:     run the SA pipeline under the named regime.
        Assert:  risk_weight matches Art. 116 — Table 2 / Table 2A / short-term
                 20% for UK and equivalence-asserted rows, flat 100% for
                 third-country rows with no asserted determination.
        """
        row = rows_by_regime[regime][label]
        expected = _EXPECTED_RW[label]

        assert row["risk_weight"] == pytest.approx(expected, abs=1e-9), (
            f"{regime}/{label}: expected risk_weight {expected:.2%} per Art. 116, "
            f"got {row['risk_weight']}"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("label", sorted(_PRE_FIX_RW))
    def test_gated_rows_moved_off_the_pre_fix_weight(
        self, rows_by_regime: dict[str, dict], regime: str, label: str
    ) -> None:
        """
        Anti-confound: every suppressed branch actually moved, upward.

        Arrange: the four limb-(a) rows plus the two limb-(b) rows.
        Act:     compare against the weight each returned before the gate.
        Assert:  strictly greater than the pre-fix weight — so the gate cannot
                 pass by leaving any of Table 2, Table 2A or the short-term
                 20% branch in place. DE-RATED (50% -> 100%) additionally
                 proves limb (a) sits ahead of the rated Table 2A join, not
                 just the unrated branch; DE-EQUIV-SHORT (20% -> 50%) proves
                 limb (b) suppresses Art. 116(3) without also blocking the
                 Table 2 fall-through.
        """
        actual = rows_by_regime[regime][label]["risk_weight"]
        pre_fix = _PRE_FIX_RW[label]

        assert actual > pre_fix, (
            f"{regime}/{label}: risk weight must have INCREASED off the pre-fix "
            f"{pre_fix:.2%}, got {actual:.2%}"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("label", _LIMB_A_LABELS)
    def test_limb_a_is_the_flat_100pct(
        self, rows_by_regime: dict[str, dict], regime: str, label: str
    ) -> None:
        """Art. 116(5) residual is a flat 100% constant, not a CQS-varying re-route."""
        actual = rows_by_regime[regime][label]["risk_weight"]
        assert actual == pytest.approx(NON_EQUIVALENT_RW, abs=1e-9), (
            f"{regime}/{label}: expected the flat Art. 116(5) 100%, got {actual:.2%}"
        )

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("label", _LIMB_B_LABELS)
    def test_limb_b_falls_through_to_the_tables_not_the_flat_100pct(
        self, rows_by_regime: dict[str, dict], regime: str, label: str
    ) -> None:
        """
        Limb (b) suppresses only Art. 116(3) — it must NOT reach limb (a)'s 100%.

        Arrange: equivalent third-country PSE, original maturity <= 3 months.
        Act:     read risk_weight.
        Assert:  the Table 2 / Table 2A CQS-2 50% — neither the 20% short-term
                 it used to take, nor the flat 100% that would mean limb (b)
                 had been wired as a jurisdiction block instead of a
                 short-term-only suppression.
        """
        actual = rows_by_regime[regime][label]["risk_weight"]

        assert actual == pytest.approx(0.50, abs=1e-9), (
            f"{regime}/{label}: an equivalent third-country short-dated PSE takes "
            f"its Table 2/2A weight (50%), got {actual:.2%}"
        )
        assert actual != pytest.approx(SHORT_TERM_RW, abs=1e-9)
        assert actual != pytest.approx(NON_EQUIVALENT_RW, abs=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_uk_pse_keeps_the_short_term_20pct(
        self, rows_by_regime: dict[str, dict], regime: str
    ) -> None:
        """
        Control: limb (b) is jurisdictional, not a blanket removal of Art. 116(3).

        Arrange: GB-SHORT — UK PSE, sovereign CQS 2, original maturity <= 3m.
        Act:     read risk_weight.
        Assert:  20% (Art. 116(3)), discriminating against the Table 2 CQS-2
                 50% it would take if the short-term branch had been deleted
                 outright rather than scoped to UK PSEs.
        """
        actual = rows_by_regime[regime]["GB-SHORT"]["risk_weight"]

        assert actual == pytest.approx(SHORT_TERM_RW, abs=1e-9), (
            f"{regime}: a UK PSE keeps the Art. 116(3) 20%, got {actual:.2%}"
        )
        assert actual != pytest.approx(TABLE_2_CQS2, abs=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_non_equivalent_rwa_is_full_ead(
        self, rows_by_regime: dict[str, dict], regime: str
    ) -> None:
        """
        Art. 116(5) 100% carries through to RWA.

        Arrange: DE-UNRATED — EAD 100m, sovereign CQS 1, no equivalence.
        Act:     read ead_final and rwa_final.
        Assert:  RWA = EAD x 100% = 100,000,000, five times the pre-fix
                 20,000,000 that the Table 2 CQS-1 weight produced.
        """
        row = rows_by_regime[regime]["DE-UNRATED"]

        assert row["ead_final"] == pytest.approx(EAD, rel=1e-9)
        assert row["rwa_final"] == pytest.approx(EAD * NON_EQUIVALENT_RW, rel=1e-9), (
            f"{regime}: DE-UNRATED RWA must be {EAD * NON_EQUIVALENT_RW:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )
        assert row["rwa_final"] != pytest.approx(EAD * TABLE_2_CQS1, rel=1e-9)

    def test_gate_is_regime_invariant(
        self, crr_rows: dict[str, dict], b31_rows: dict[str, dict]
    ) -> None:
        """
        The gate binds identically under both regimes.

        Art. 116(5) lives in CRR and PS1/26 Art. 116(3A) explicitly operates
        "for the purpose of Article 116(5) of CRR", so there is no pack Feature
        and no regime branch behind this behaviour.

        Arrange: the same PSE book run under CRR and Basel 3.1.
        Act:     compare every row's risk weight across regimes.
        Assert:  identical — a regression that gated the fix to one regime
                 would break here even if the per-regime tests above passed.
        """
        crr_weights = {label: crr_rows[label]["risk_weight"] for label in _ALL_LABELS}
        b31_weights = {label: b31_rows[label]["risk_weight"] for label in _ALL_LABELS}

        assert crr_weights == pytest.approx(b31_weights, abs=1e-9), (
            f"PSE Art. 116 weights must match across regimes.\n"
            f"CRR: {crr_weights}\nB31: {b31_weights}"
        )
