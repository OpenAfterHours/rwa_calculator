"""
Differential fuzzing: the engine against an independent stdlib shadow calculator.

Pipeline position:
    ExposureSpec -> portfolios.run (full pipeline) -> per-leg risk weight / RWEA
        vs tests.oracle.derivations.branch_sa.shadow_sa (independent re-derivation)

What this proves:
    The recorded golden files in ``tests/expected_outputs/`` cannot detect a
    wrong constant -- they are engine output compared against engine output. The
    oracle suite catches wrong constants but only at ~130 fixed points. This test
    closes the gap between them: it re-derives the Standardised-Approach risk
    weight from the regulation in ``branch_sa`` (stdlib only, never imports the
    engine) and asserts the engine reproduces it over a whole generated domain,
    to the oracle suite's 1e-6 relative tolerance. A risk weight that is 45%
    where the article says 50% is invisible to conservation, monotonicity and
    the goldens; it is visible here.

Scope -- the shadow covers only DRAWN, UNMITIGATED, NON-DEFAULTED, on-balance
single exposures under the Standardised Approach (see ``branch_sa`` for the full
covered/excluded list). The generated domain is therefore RESTRICTED to that
subset rather than reusing ``strategies.exposure_specs`` wholesale, which also
emits off-balance-sheet legs, collateral, guarantees, defaults and IRB routing:
- entity types: sovereign, institution, corporate (non-SME), individual (retail);
- no internal PD / firm LGD (so every leg routes SA), no CRM, no off-BS leg;
- corporates carry no revenue, so no SME classification and no Art. 501 factor;
- individuals stay under ``RETAIL_MAX_DRAWN`` so the Art. 123 / 123A retail size
  limit (EUR 1m, ~GBP 880k) does not reclassify them to corporate mid-example.
The B31 retail 75% branch is also contingent on the property config's
``enforce_retail_granularity=False`` (``portfolios.config_for``): with granularity
enforcement ON, PS1/26 Art. 123A(1)(b)(iii)'s 0.2%-of-portfolio limb is
unsatisfiable for a single obligor, which reclassifies it to corporate at 100%.
The shadow's 75% therefore matches the engine only under the config this suite
runs; that config is the documented one, so the comparison is like-for-like.
Residential real-estate LTV splitting IS in the shadow but is NOT reachable
through ``ExposureSpec`` (which has no property_type / LTV), so it is checked
against the independently-derived oracle RE values instead of the engine
(``test_shadow_rre_matches_the_independent_oracle``).

Non-degeneracy: ``test_engine_matches_shadow_across_the_sa_matrix`` is a
deterministic sweep over every (entity type x CQS x framework) branch, so the
covered domain is exercised exhaustively regardless of what the generator draws;
the fuzz then adds random amounts and combinations on top, and
``test_fuzz_explored_multiple_classes`` asserts the generator itself was not
degenerate.

References:
- tests/oracle/README.md, tests/oracle/derivations/branch_sa.py
- CRR / PS1/26 Art. 114, 120, 121, 122, 123, 125 / 124F (cited in branch_sa)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.oracle.derivations import branch_sa
from tests.properties.portfolios import RETAIL_MAX_DRAWN, ExposureSpec, results_df

#: The oracle suite's tolerance. Both sides are the same regulation computed two
#: independent ways, so a real disagreement is a wrong constant, not float dust.
TOLERANCE = 1e-6

#: portfolios regime name -> the framework token branch_sa speaks.
REGIME_TO_FRAMEWORK: dict[str, str] = {"CRR": branch_sa.CRR, "B31": branch_sa.BASEL_3_1}

#: Above this GBP revenue a corporate is not an SME on this engine (MEASURED:
#: 40m classifies SME, 900m does not; None never does). The fuzz uses no revenue
#: so it never triggers SME; this only guards the deterministic B31 SME case.
_SME_REVENUE_CEILING = 50_000_000.0

#: Each example is one full pipeline run per regime (~1s here, uncached). Kept
#: modest on purpose: the deterministic matrix already pins every branch, so the
#: fuzz only has to exercise random amounts and entity/CQS combinations on top of
#: it. 20 x 2 regimes keeps the file near a minute while still drawing a wide mix
#: of amounts against each entity type.
FUZZ_EXAMPLES = 20


# =============================================================================
# Deterministic matrix -- the exhaustive, non-degenerate differential sweep
# =============================================================================


def _spec(
    entity_type: str,
    *,
    cqs: int | None,
    drawn: float,
    country_code: str = "GB",
    annual_revenue: float | None = None,
) -> ExposureSpec:
    """An in-scope, SA-routing, unmitigated single exposure."""
    return ExposureSpec(
        entity_type=entity_type,
        drawn=drawn,
        external_cqs=cqs,
        internal_pd=None,
        firm_lgd=None,
        annual_revenue=annual_revenue,
        country_code=country_code,
        off_bs_nominal=0.0,
        collateral_value=0.0,
        guarantee_amount=0.0,
        is_defaulted=False,
    )


def _matrix_cases() -> list[tuple[str, str, ExposureSpec]]:
    """Every covered (entity x CQS x framework) branch, one exposure each."""
    cases: list[tuple[str, str, ExposureSpec]] = []
    for regime in ("CRR", "B31"):
        # Sovereign: the whole Table 1 ladder via a foreign (US) sovereign, plus
        # the Art. 114(4) domestic-sterling 0% override via a GB one.
        for cqs in (None, 1, 2, 3, 4, 5, 6):
            cid = f"{regime}-sovereign-US-cqs{cqs}"
            cases.append(
                (cid, regime, _spec("sovereign", cqs=cqs, drawn=1_000_000.0, country_code="US"))
            )
        for cqs in (None, 3):
            cid = f"{regime}-sovereign-GB-cqs{cqs}"
            cases.append(
                (cid, regime, _spec("sovereign", cqs=cqs, drawn=1_000_000.0, country_code="GB"))
            )
        # Institution and corporate: their full CQS ladders plus the unrated limb.
        for entity in ("institution", "corporate"):
            for cqs in (None, 1, 2, 3, 4, 5, 6):
                cid = f"{regime}-{entity}-cqs{cqs}"
                cases.append((cid, regime, _spec(entity, cqs=cqs, drawn=1_000_000.0)))
        # Retail.
        cases.append((f"{regime}-retail", regime, _spec("individual", cqs=None, drawn=300_000.0)))
    # PS1/26 Art. 122(11) unrated SME -> 85% is B31-only (CRR's SME factor is
    # out of scope), so it is pinned here rather than in the fuzz.
    cases.append(
        (
            "B31-corporate-sme-unrated",
            "B31",
            _spec("corporate", cqs=None, drawn=1_000_000.0, annual_revenue=20_000_000.0),
        )
    )
    return cases


@pytest.mark.parametrize(
    ("regime", "spec"),
    [pytest.param(regime, spec, id=cid) for cid, regime, spec in _matrix_cases()],
)
def test_engine_matches_shadow_across_the_sa_matrix(regime: str, spec: ExposureSpec) -> None:
    """The engine reproduces the shadow's SA weight and RWEA for every branch."""
    _assert_engine_matches_shadow(spec, regime)


# =============================================================================
# Fuzz -- random amounts and combinations on top of the matrix
# =============================================================================

_CQS = st.one_of(st.none(), st.integers(min_value=1, max_value=6))
_BIG_AMOUNTS = st.floats(
    min_value=10_000.0, max_value=20_000_000.0, allow_nan=False, allow_infinity=False
)
_RETAIL_AMOUNTS = st.floats(
    min_value=10_000.0, max_value=RETAIL_MAX_DRAWN, allow_nan=False, allow_infinity=False
)

#: (framework, exposure_class) pairs the fuzz actually reached -- read by
#: ``test_fuzz_explored_multiple_classes`` to prove the generator is not
#: degenerate. Populated as the fuzz runs; the project's xdist ``loadfile`` pins
#: this file to one worker, so the two tests share this module state in order.
_FUZZ_COVERAGE: set[tuple[str, str]] = set()


@st.composite
def _sa_specs(draw: st.DrawFn) -> ExposureSpec:
    """A single in-scope SA exposure: any covered entity type, random amount."""
    entity_type = draw(st.sampled_from(("sovereign", "institution", "corporate", "individual")))
    if entity_type == "individual":
        return _spec("individual", cqs=None, drawn=draw(_RETAIL_AMOUNTS))
    if entity_type == "sovereign":
        return _spec(
            "sovereign",
            cqs=draw(_CQS),
            drawn=draw(_BIG_AMOUNTS),
            country_code=draw(st.sampled_from(("GB", "US"))),
        )
    return _spec(entity_type, cqs=draw(_CQS), drawn=draw(_BIG_AMOUNTS))


@pytest.mark.parametrize("regime", ["CRR", "B31"])
@settings(max_examples=FUZZ_EXAMPLES)
@given(spec=_sa_specs())
def test_engine_matches_shadow_on_generated_exposures(spec: ExposureSpec, regime: str) -> None:
    """Random in-scope SA exposures: the engine still equals the shadow."""
    shadow = _assert_engine_matches_shadow(spec, regime)
    _FUZZ_COVERAGE.add((REGIME_TO_FRAMEWORK[regime], shadow.exposure_class))


def test_fuzz_explored_multiple_classes() -> None:
    """The generator was not degenerate: it reached several classes, both regimes.

    Guards against a strategy that silently collapses to one entity type -- a
    vacuous pass that would evidence nothing (``.claude/LESSONS.md`` C2/B5).
    Relies on running after the fuzz in the same file; the suite's ``loadfile``
    distribution guarantees that.
    """
    assert _FUZZ_COVERAGE, (
        "no fuzz coverage recorded -- run this with "
        "test_engine_matches_shadow_on_generated_exposures, not in isolation"
    )
    frameworks = {fw for fw, _cls in _FUZZ_COVERAGE}
    classes = {cls for _fw, cls in _FUZZ_COVERAGE}
    assert frameworks == {branch_sa.CRR, branch_sa.BASEL_3_1}, (
        f"fuzz only exercised frameworks {frameworks}"
    )
    assert len(classes) >= 3, f"fuzz collapsed to too few exposure classes: {classes}"


# =============================================================================
# Residential real estate -- shadow vs the independent oracle (not the engine)
# =============================================================================

_ORACLE_JSON = Path(__file__).resolve().parents[1] / "oracle" / "expected_values.json"

#: The RRE LTV-split oracles: CRR Art. 125(2)(d) at LTV 0.60 / 1.00, PS1/26
#: Art. 124F at LTV 0.50 / 1.00. Their values are derived independently in
#: ORACLE_DERIVATIONS.md; matching them proves the callable shadow reproduces the
#: same regulation the fixed oracle encodes for a branch the engine fuzz cannot
#: reach (ExposureSpec has no property_type / LTV).
_RRE_ORACLE_IDS = ("ORC-028", "ORC-029", "ORC-065", "ORC-066")


def _rre_oracles() -> list[dict[str, Any]]:
    payload = json.loads(_ORACLE_JSON.read_text())
    by_id: dict[str, dict[str, Any]] = {
        record["exposure_id"]: record
        for record in payload["oracles"]
        if record["exposure_id"] in _RRE_ORACLE_IDS
    }
    missing = [oid for oid in _RRE_ORACLE_IDS if oid not in by_id]
    assert not missing, f"expected RRE oracle(s) absent from expected_values.json: {missing}"
    return [by_id[oid] for oid in _RRE_ORACLE_IDS]


@pytest.mark.parametrize("record", _rre_oracles(), ids=_RRE_ORACLE_IDS)
def test_shadow_rre_matches_the_independent_oracle(record: dict[str, Any]) -> None:
    """The shadow's RRE LTV split reproduces the hand-derived oracle value."""
    framework = record["framework"]
    ead = float(record["inputs"]["ead"])
    ltv = float(record["inputs"]["ltv"])
    want_rw = float(record["expected"]["risk_weight"])
    want_rwa = float(record["expected"]["rwa"])

    shadow = branch_sa.shadow_sa_rre(framework, ltv, ead)

    assert _rel_err(want_rw, shadow.risk_weight) <= TOLERANCE, (
        f"{record['exposure_id']}: oracle RW {want_rw}, shadow {shadow.risk_weight}"
    )
    assert _rel_err(want_rwa, shadow.rwa) <= TOLERANCE, (
        f"{record['exposure_id']}: oracle RWA {want_rwa}, shadow {shadow.rwa}"
    )


# =============================================================================
# Private helpers
# =============================================================================


def _shadow_for(spec: ExposureSpec, framework: str) -> branch_sa.ShadowSA:
    """Map an ExposureSpec onto the shadow's inputs and re-derive."""
    is_sme = (
        spec.entity_type == "corporate"
        and spec.annual_revenue is not None
        and spec.annual_revenue < _SME_REVENUE_CEILING
    )
    return branch_sa.shadow_sa(
        framework=framework,
        entity_type=spec.entity_type,
        cqs=spec.external_cqs,
        ead=spec.drawn,
        country_code=spec.country_code,
        currency="GBP",
        is_sme=is_sme,
    )


def _assert_engine_matches_shadow(spec: ExposureSpec, regime: str) -> branch_sa.ShadowSA:
    """Run the engine on one exposure and assert it agrees with the shadow."""
    framework = REGIME_TO_FRAMEWORK[regime]
    shadow = _shadow_for(spec, framework)

    df = results_df((spec,), regime)
    assert df.height == 1, f"expected one leg for {spec}, got {df.height}"
    row = df.to_dicts()[0]

    diffs: list[str] = []
    for field, want, got in (
        ("ead", spec.drawn, _num(row.get("ead_final"))),
        ("risk_weight", shadow.risk_weight, _num(row.get("risk_weight"))),
        ("rwa", shadow.rwa, _num(row.get("rwa_final"))),
    ):
        if _rel_err(want, got) > TOLERANCE:
            diffs.append(f"{field}: shadow={want!r} engine={got!r}")

    engine_class = row.get("exposure_class")
    if engine_class != shadow.exposure_class:
        diffs.append(f"exposure_class: shadow={shadow.exposure_class!r} engine={engine_class!r}")

    assert not diffs, (
        f"\nengine disagrees with the shadow for {spec} under {regime}\n"
        f"  shadow regulation: {shadow.regulation}\n  " + "\n  ".join(diffs)
    )
    return shadow


def _num(value: Any) -> float:
    """Coerce an engine cell to float, treating a null money/weight as 0.0."""
    return 0.0 if value is None else float(value)


def _rel_err(want: float, got: float) -> float:
    """Relative error, with the oracle suite's exact-zero convention."""
    if want == 0.0:
        return 0.0 if got == 0.0 else float("inf")
    return abs(got - want) / abs(want)
