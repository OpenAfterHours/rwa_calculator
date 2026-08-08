"""
Callable Standardised-Approach shadow calculator (differential-fuzzing branch).

Pipeline position:
    (none) -- this module is deliberately outside the engine, exactly like the
    rest of ``tests/oracle/derivations/``. It never imports ``rwa_calc``.

Why this exists:
    ``sa_crr`` and ``sa_b31`` re-derive the SA risk weights but only for a fixed
    catalogue of ORC-nnn fact patterns. This module turns the same regulation
    into a *callable* branch calculator -- ``shadow_sa(...)`` for arbitrary
    ``(framework, entity_type, cqs, ead, ...)`` -- so a Hypothesis test can fuzz
    the engine against an independent re-derivation over a whole domain rather
    than at a handful of points (``tests/properties/test_differential_shadow.py``).

    It is NOT registered in ``derivations.MODULES`` and produces no oracle
    records, so ``expected_values.json`` is unchanged by its existence. The AST
    import-ban in ``test_oracle.py`` still parses it (it globs ``*.py``), so it
    must stay stdlib-only.

Scope -- COVERED branches (drawn, unmitigated, non-defaulted, on-balance-sheet
single exposures, GBP-denominated as the property portfolios build them):
    - Central governments / central banks (Art. 114): the Art. 114(4) domestic
      sterling 0% override, and Table 1 on the sovereign's own CQS otherwise.
    - Institutions (Art. 120 rated / Art. 121 unrated): the ECRA Table 3 ladder
      when rated; the unrated default (CRR Art. 121(2) -> 100%; PS1/26 SCRA with
      no determinable grade -> Grade C 150%).
    - Corporates (Art. 122): Table 6 when rated; the unrated default (100%); and
      the PS1/26 Art. 122(11) unrated-SME flat 85% weight.
    - Retail (Art. 123): the qualifying / regulatory-retail 75% weight.
    - Residential real estate LTV splitting (CRR Art. 125(2)(d); PS1/26
      Art. 124F with 124L) -- the preferential weight on the slice within the
      value limit, counterparty weight above it. This branch is exercised by the
      oracle cross-check rather than by the engine fuzz (see EXCLUDED below).

Scope -- EXCLUDED branches, stated explicitly (no silent caps -- the fuzz
strategy restricts its domain to the covered set and says so):
    - The CRR Art. 501 SME supporting factor. Its EUR 2.5m tier threshold is
      converted to GBP at the run's FX rate, so the RWEA multiplier is not
      derivable from the article alone in a stdlib module. MEASURED: a GBP 5m
      SME took factor 0.81153554, not the 0.80595 a EUR==GBP threshold gives.
      The B31 SME weight (85%) carries no such factor and IS covered.
    - The Art. 501a infrastructure supporting factor (same reason class).
    - Off-balance-sheet credit conversion factors (Art. 111 / Annex I).
    - Credit risk mitigation of every kind (Art. 193+): collateral, guarantees,
      currency- and maturity-mismatch. Every input here is unmitigated.
    - Defaulted exposures (Art. 127) and the provision-coverage split.
    - RGLA (Art. 115), PSE (Art. 116), MDB (Art. 117), international
      organisations (Art. 118), covered bonds (Art. 129), equity (Art. 133),
      high-risk items (PS1/26 Art. 128). Several are clean table lookups but are
      held out to bound the shadow to the classes the brief names.
    - The PS1/26 Art. 122(6) investment-grade unrated-corporate weights (65% /
      135%) -- they need a firm-level PRA permission election, not an input.
    - The PS1/26 Art. 123(3)(a) QRRE transactor 45% weight -- no transactor flag
      is expressible through the property-suite ``ExposureSpec``.
    - Income-producing / materially-dependent real estate (PS1/26 Art. 124G /
      124I), ADC (Art. 124K) and commercial real estate. Only the
      not-materially-dependent residential split is covered.
    - Any EU-sovereign special treatment. Only a GB-domestic sovereign (0%) and
      a foreign sovereign on Table 1 are in scope.

References:
    - CRR Art. 114, 120, 121, 122, 123, 125; Art. 501.
    - PRA PS1/26 Art. 114, 120, 121, 122, 123, 124F, 124L.
"""

from __future__ import annotations

from typing import NamedTuple

from .formulas import blend_two_bands

# Framework tokens, matching CalculationConfig / the oracle records.
CRR = "CRR"
BASEL_3_1 = "BASEL_3_1"

# Entity types this shadow can classify. Anything else raises -- a silent
# fall-through is exactly the ``LESSONS.md`` B1/B2 failure mode.
_SUPPORTED_ENTITY_TYPES = frozenset({"sovereign", "institution", "corporate", "individual"})


class ShadowSA(NamedTuple):
    """One SA branch result: the risk weight, the RWEA, the class it implies."""

    risk_weight: float
    rwa: float
    exposure_class: str
    regulation: str


# =============================================================================
# Cited risk-weight tables
# =============================================================================
#
# Defined here at their point of use (rather than imported from ``sa_crr`` /
# ``sa_b31``) so the callable calculator is independently auditable: a reader
# can settle every constant against the article without leaving the module, and
# the differential test rests on a second, self-contained re-derivation.

# CRR Art. 114(2) Table 1 (sovereign, rated).
_CRR_SOVEREIGN_TABLE_1 = {1: 0.00, 2: 0.20, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
# CRR Art. 120(1) Table 3 (rated institution, residual maturity > 3 months).
_CRR_INSTITUTION_TABLE_3 = {1: 0.20, 2: 0.50, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
# CRR Art. 122(1) Table 6 (rated corporate).
_CRR_CORPORATE_TABLE_6 = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.50, 6: 1.50}

# PS1/26 Art. 114(2) Table 1 (sovereign, rated) -- unchanged from CRR.
_B31_SOVEREIGN_TABLE_1 = {1: 0.00, 2: 0.20, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
# PS1/26 Art. 120(1) Table 3 (rated institution): CQS 2 is 30% here, 50% in CRR.
_B31_INSTITUTION_TABLE_3 = {1: 0.20, 2: 0.30, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
# PS1/26 Art. 122(2) Table 6 (rated corporate): CQS 3 is 75% here, 100% in CRR.
_B31_CORPORATE_TABLE_6 = {1: 0.20, 2: 0.50, 3: 0.75, 4: 1.00, 5: 1.50, 6: 1.50}

# CRR Art. 122(2) / Art. 114(1): an unrated corporate / sovereign with no other
# treatment falls to 100%.
_UNRATED_RW = 1.00
# CRR Art. 121(2): an unrated institution whose central government is itself
# unrated -> 100%. Through the property portfolios no sovereign CQS is ever
# attached to the institution's country, so this is the operative CRR default.
_CRR_UNRATED_INSTITUTION_RW = 1.00
# PS1/26 Art. 121(2) Table 5: SCRA grades A/B/C -> 40% / 75% / 150%. Derived
# from the grading rules for an institution the inputs disclose nothing about:
# Art. 121(1)(a) makes an institution ineligible for Grade A where its published
# regulatory-capital and buffer requirements are not disclosed ("may not be
# classified as Grade A"); Art. 121(1)(b) then requires Grade C where the minimum
# regulatory requirements are not disclosed ("shall be classified as Grade C").
# With no disclosure at all the exposure is Grade C -> 150% (Table 5A is 150% for
# Grade C as well, so the <=3-month maturity routing cannot move it). The engine's
# 150% is a corroborating observation, not the source of this value.
_B31_UNRATED_INSTITUTION_RW = 1.50
# CRR Art. 123 / PS1/26 Art. 123(3)(b): qualifying (regulatory, non-transactor)
# retail -> 75%.
_RETAIL_RW = 0.75
# PS1/26 Art. 122(11): an unrated SME that is not a retail exposure -> 85%.
_B31_SME_CORPORATE_RW = 0.85

# CRR Art. 125(1)(a) / (2)(d): residential mortgage preferential weight and the
# value share it applies to; Art. 124(1) sends the residual to the counterparty
# weight (a qualifying natural person, Art. 123, 75%).
_CRR_RRE_PREFERENTIAL_RW = 0.35
_CRR_RRE_VALUE_SHARE = 0.80
# PS1/26 Art. 124F(1): 20% on the slice up to 55% of value; Art. 124L(1)(a):
# 75% natural-person counterparty weight on the residual.
_B31_RRE_PREFERENTIAL_RW = 0.20
_B31_RRE_VALUE_SHARE = 0.55
_RRE_COUNTERPARTY_RW = 0.75


# =============================================================================
# Main public entry point
# =============================================================================


def shadow_sa(
    *,
    framework: str,
    entity_type: str,
    cqs: int | None,
    ead: float,
    country_code: str = "GB",
    currency: str = "GBP",
    is_sme: bool = False,
) -> ShadowSA:
    """Re-derive the SA risk weight and RWEA for one in-scope exposure.

    ``framework`` is ``"CRR"`` or ``"BASEL_3_1"``. ``entity_type`` is one of
    :data:`_SUPPORTED_ENTITY_TYPES`. ``cqs`` is the exposure's own external
    credit-quality step (1-6) or ``None`` when unrated. ``country_code`` /
    ``currency`` carry the Art. 114(4) domestic-currency test for sovereigns.

    RWEA is ``ead * risk_weight`` throughout the covered scope: every excluded
    branch (supporting factors, defaulted add-ons, CRM) is exactly what would
    make RWEA something other than that product, which is why they are excluded.
    """
    if framework not in (CRR, BASEL_3_1):
        raise ValueError(f"unknown framework {framework!r}")
    if entity_type not in _SUPPORTED_ENTITY_TYPES:
        raise ValueError(
            f"entity_type {entity_type!r} is outside the shadow's scope; see the "
            f"module docstring for the covered set {sorted(_SUPPORTED_ENTITY_TYPES)}"
        )

    if entity_type == "sovereign":
        rw, exposure_class, reg = _sovereign(framework, cqs, country_code, currency)
    elif entity_type == "institution":
        rw, exposure_class, reg = _institution(framework, cqs)
    elif entity_type == "corporate":
        rw, exposure_class, reg = _corporate(framework, cqs, is_sme=is_sme)
    else:  # "individual"
        rw, exposure_class, reg = _retail(framework)

    return ShadowSA(risk_weight=rw, rwa=ead * rw, exposure_class=exposure_class, regulation=reg)


def shadow_sa_rre(framework: str, ltv: float, ead: float) -> ShadowSA:
    """Residential-real-estate LTV split for a qualifying natural person.

    CRR Art. 125(2)(d): the preferential 35% weight applies to the slice of the
    loan up to 80% of the property value, the 75% counterparty weight above it.
    PS1/26 Art. 124F(1) with Art. 124L(1)(a): 20% up to 55% of value, 75% above.

    ``ltv`` is loan / property value; the value share is ``value = ead / ltv``.
    """
    if framework == CRR:
        preferential_rw = _CRR_RRE_PREFERENTIAL_RW
        value_share = _CRR_RRE_VALUE_SHARE
        reg = "CRR Art. 125(2)(d) with Art. 124(1)"
    elif framework == BASEL_3_1:
        preferential_rw = _B31_RRE_PREFERENTIAL_RW
        value_share = _B31_RRE_VALUE_SHARE
        reg = "PS1/26 Art. 124F(1) with Art. 124L(1)(a)"
    else:
        raise ValueError(f"unknown framework {framework!r}")

    property_value = ead / ltv
    rw = blend_two_bands(
        exposure=ead,
        secured_amount=value_share * property_value,
        secured_rw=preferential_rw,
        residual_rw=_RRE_COUNTERPARTY_RW,
    )
    return ShadowSA(risk_weight=rw, rwa=ead * rw, exposure_class="retail_mortgage", regulation=reg)


# =============================================================================
# Per-class branches (private)
# =============================================================================


def _sovereign(
    framework: str, cqs: int | None, country_code: str, currency: str
) -> tuple[float, str, str]:
    cls = "central_govt_central_bank"
    # Art. 114(4): a domestic-currency exposure to the UK central government -> 0%.
    if country_code == "GB" and currency == "GBP":
        return 0.00, cls, "Art. 114(4): UK central government, domestic sterling -> 0%"
    table = _CRR_SOVEREIGN_TABLE_1 if framework == CRR else _B31_SOVEREIGN_TABLE_1
    if cqs is None:
        return _UNRATED_RW, cls, "Art. 114(1): unrated sovereign -> 100%"
    return table[cqs], cls, f"Art. 114(2) Table 1: sovereign CQS {cqs}"


def _institution(framework: str, cqs: int | None) -> tuple[float, str, str]:
    cls = "institution"
    if cqs is None:
        if framework == CRR:
            return _CRR_UNRATED_INSTITUTION_RW, cls, "CRR Art. 121(2): unrated institution -> 100%"
        return (
            _B31_UNRATED_INSTITUTION_RW,
            cls,
            "PS1/26 Art. 121(2) Table 5: unrated institution, no determinable SCRA grade -> 150%",
        )
    table = _CRR_INSTITUTION_TABLE_3 if framework == CRR else _B31_INSTITUTION_TABLE_3
    return table[cqs], cls, f"Art. 120(1) Table 3: rated institution CQS {cqs}"


def _corporate(framework: str, cqs: int | None, *, is_sme: bool) -> tuple[float, str, str]:
    if is_sme:
        if framework == CRR:
            raise ValueError(
                "CRR SME corporates are excluded from the shadow: the Art. 501 "
                "supporting factor's EUR->GBP threshold is not derivable here"
            )
        if cqs is None:
            return _B31_SME_CORPORATE_RW, "corporate_sme", "PS1/26 Art. 122(11): unrated SME -> 85%"
        # A rated SME still reads its rating off Table 6; only the unrated 85%
        # limb is in scope for the fuzz.
        raise ValueError("rated SME corporates are outside the shadow's fuzz scope")

    cls = "corporate"
    if cqs is None:
        return _UNRATED_RW, cls, "Art. 122(2)/(5): unrated corporate -> 100%"
    table = _CRR_CORPORATE_TABLE_6 if framework == CRR else _B31_CORPORATE_TABLE_6
    return table[cqs], cls, f"Art. 122 Table 6: rated corporate CQS {cqs}"


def _retail(framework: str) -> tuple[float, str, str]:
    reg = (
        "CRR Art. 123: qualifying retail -> 75%"
        if framework == CRR
        else "PS1/26 Art. 123(3)(b): regulatory retail, non-transactor -> 75%"
    )
    return _RETAIL_RW, "retail_other", reg
