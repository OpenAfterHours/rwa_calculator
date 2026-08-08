"""
Phase O1 (a) -- Standardised Approach oracles under UK CRR.

Every risk weight below was read out of `docs/assets/crr.pdf` (the onshored
Regulation (EU) No 575/2013 as amended for the UK) and is cited to the article
and table it came from. Nothing here reads the engine.

References:
- Art. 114  central governments and central banks (Table 1)
- Art. 115  regional governments and local authorities
- Art. 116  public sector entities (Table 2)
- Art. 117  multilateral development banks
- Art. 118  international organisations
- Art. 120  rated institutions (Tables 3 and 4)
- Art. 121  unrated institutions (Table 5)
- Art. 122  corporates (Table 6)
- Art. 123  retail
- Art. 124-126  exposures secured by immovable property
- Art. 127  exposures in default
- Art. 129  covered bonds (Table 6A)
- Art. 133  equity
- Art. 134  other items
- Art. 501 / 501a  SME and infrastructure supporting factors
"""

from __future__ import annotations

from typing import Any

from .formulas import blend_two_bands, sme_supporting_factor
from .record import oracle

FRAMEWORK = "CRR"
PHASE = "O1"

M = 1_000_000.0


def _sa(
    oracle_id: str,
    exposure_class: str,
    regulation: str,
    risk_weight: float,
    inputs: dict[str, Any],
    *,
    ead: float = M,
    rwa: float | None = None,
    intermediate: dict[str, Any] | None = None,
    extra_expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=FRAMEWORK,
        approach="SA",
        exposure_class=exposure_class,
        regulation=regulation,
        ead=ead,
        risk_weight=risk_weight,
        inputs={"exposure_class": exposure_class, **inputs},
        intermediate=intermediate,
        rwa=rwa,
        extra_expected=extra_expected,
    )


# -----------------------------------------------------------------------------
# Central governments and central banks -- Art. 114
# -----------------------------------------------------------------------------
# Art. 114(2) Table 1:  CQS  1     2     3     4     5     6
#                        RW   0%   20%   50%  100%  100%  150%
# Art. 114(1): 100% where none of the paragraph 2-7 treatments apply (unrated).
# Art. 114(4): UK central government / Bank of England, in sterling -> 0%.
#
# Country and currency are load-bearing: a non-UK sovereign in a foreign
# currency keeps the Art. 114(4) override out of the way.
_SOVEREIGN_TABLE_1 = {1: 0.00, 2: 0.20, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}

_FOREIGN = {"country_code": "US", "currency": "USD"}

# Art. 116(5) makes the Table 2 / Art. 120 treatment of a THIRD-COUNTRY public
# sector entity conditional on a Treasury equivalence determination; absent one,
# the risk weight is a flat 100%. A UK PSE keeps that condition out of the way,
# so these oracles test Table 2 itself rather than the equivalence gate.
_UK = {"country_code": "GB", "currency": "GBP", "local_currency": "GBP"}


def sovereigns() -> list[dict[str, Any]]:
    ids = {1: "ORC-004", 2: "ORC-002", 3: "ORC-005", 4: "ORC-006", 6: "ORC-007"}
    out = [
        _sa(
            ids[cqs],
            "central_govt_central_bank",
            f"CRR Art. 114(2) Table 1: CQS {cqs} sovereign (foreign ccy) -> "
            f"{_SOVEREIGN_TABLE_1[cqs]:.0%} RW",
            _SOVEREIGN_TABLE_1[cqs],
            {"cqs": cqs, "entity_type": "sovereign", **_FOREIGN},
            ead=5 * M if cqs == 2 else M,
        )
        for cqs in sorted(ids)
    ]
    out.append(
        _sa(
            "ORC-008",
            "central_govt_central_bank",
            "CRR Art. 114(1): sovereign with no ECAI assessment -> 100% RW",
            1.00,
            {"cqs": None, "entity_type": "sovereign", **_FOREIGN},
        )
    )
    out.append(
        _sa(
            "ORC-009",
            "central_govt_central_bank",
            "CRR Art. 114(4): UK central government, denominated and funded in sterling -> 0% RW",
            0.00,
            {
                "cqs": 3,
                "entity_type": "sovereign",
                "country_code": "GB",
                "currency": "GBP",
                "local_currency": "GBP",
            },
        )
    )
    return out


# -----------------------------------------------------------------------------
# RGLA -- Art. 115; PSE -- Art. 116; MDB -- Art. 117; IO -- Art. 118
# -----------------------------------------------------------------------------
# Art. 115(5): UK RGLA not treated as central government, in sterling -> 20%.
# Art. 115(1): otherwise risk-weighted as exposures to institutions, which for
#   an unrated RGLA routes to Art. 121 Table 5 on the sovereign CQS.
# Art. 116(1) Table 2 (unrated PSE, on the central government's CQS):
#   CQS  1     2     3     4     5     6
#   RW  20%   50%  100%  100%  100%  150%
# Art. 117(2): named MDBs -> 0%.
# Art. 118: named international organisations -> 0%.
_PSE_TABLE_2 = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.50}


def public_sector() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-010",
            "rgla",
            "CRR Art. 115(5): UK regional government, sterling -> 20% RW",
            0.20,
            {
                "cqs": None,
                "entity_type": "rgla_institution",
                "country_code": "GB",
                "currency": "GBP",
                "local_currency": "GBP",
            },
        ),
        _sa(
            "ORC-011",
            "rgla",
            "CRR Art. 115(1) with Art. 121 Table 5: non-UK unrated RGLA weighted "
            "as an institution on a CQS-2 sovereign -> 50% RW",
            0.50,
            {"cqs": None, "entity_type": "rgla_institution", "sovereign_cqs": 2, **_FOREIGN},
        ),
        _sa(
            "ORC-012",
            "pse",
            "CRR Art. 116(1) Table 2: unrated PSE, central government CQS 1 -> 20% RW",
            _PSE_TABLE_2[1],
            {"cqs": None, "entity_type": "pse_sovereign", "sovereign_cqs": 1, **_UK},
        ),
        _sa(
            "ORC-013",
            "pse",
            "CRR Art. 116(1) Table 2: unrated PSE, central government CQS 3 -> 100% RW",
            _PSE_TABLE_2[3],
            {"cqs": None, "entity_type": "pse_sovereign", "sovereign_cqs": 3, **_UK},
        ),
        *third_country_pse_equivalence(),
        _sa(
            "ORC-014",
            "mdb",
            "CRR Art. 117(2): MDB named in the Art. 117(2) list -> 0% RW",
            0.00,
            {"cqs": None, "entity_type": "mdb_named", **_FOREIGN},
        ),
        _sa(
            "ORC-015",
            "international_organisation",
            "CRR Art. 118: named international organisation -> 0% RW",
            0.00,
            {"cqs": None, "entity_type": "international_org", **_FOREIGN},
        ),
    ]


# -----------------------------------------------------------------------------
# Third-country PSEs and the Art. 116(5) equivalence determination
# -----------------------------------------------------------------------------
# Art. 116(5), verbatim from crr.pdf p114:
#
#   "When competent authorities of a third country jurisdiction, which apply
#    supervisory and regulatory arrangements at least equivalent to those
#    applied in the [United Kingdom], treat exposures to public sector entities
#    in accordance with paragraph 1 or 2, institutions may risk weight exposures
#    to such public sector entities in the same manner. Otherwise the
#    institutions shall apply a risk weight of 100 %."
#
# So the determination is a switch with two lawful outcomes, and this pins both
# limbs across the whole input domain: the flag asserted, denied, and simply not
# asserted, on each of the two PSE entity types. A third-country PSE whose
# central government is CQS 1 therefore takes 20% where the determination is
# made, and 100% in every other case.
#
# This enumeration exists because it was first reported as a defect -- "the
# equivalence flag is inert" -- which was wrong. The flag had been passed under
# a name the driver did not alias, so it never reached
# ``cp_is_equivalent_jurisdiction`` and the engine saw the default of null.
# ``drivers.reject_unknown_columns`` now makes that mistake impossible; these
# oracles keep the real behaviour pinned.
_PSE_EQUIVALENCE_IDS = {
    ("pse_sovereign", True): "ORC-130",
    ("pse_sovereign", False): "ORC-131",
    ("pse_sovereign", None): "ORC-132",
    ("pse_institution", True): "ORC-133",
    ("pse_institution", False): "ORC-134",
    ("pse_institution", None): "ORC-135",
}

_THIRD_COUNTRY = {"country_code": "US", "currency": "USD"}


def third_country_pse_equivalence() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for (entity_type, determined), oracle_id in _PSE_EQUIVALENCE_IDS.items():
        if determined is True:
            risk_weight = _PSE_TABLE_2[1]
            reg = (
                "CRR Art. 116(5) first limb with Art. 116(1) Table 2: the "
                "Treasury has determined the third country equivalent, so a PSE "
                "whose central government is CQS 1 may be risk weighted in the "
                "same manner -> 20% RW"
            )
        else:
            risk_weight = 1.00
            state = "denied" if determined is False else "not asserted"
            reg = (
                f"CRR Art. 116(5) second limb: equivalence {state}, so "
                f"'otherwise the institutions shall apply a risk weight of "
                f"100 %' -> 100% RW"
            )
        out.append(
            _sa(
                oracle_id,
                "pse",
                reg,
                risk_weight,
                {
                    "cqs": None,
                    "entity_type": entity_type,
                    "sovereign_cqs": 1,
                    "is_equivalent_jurisdiction": determined,
                    **_THIRD_COUNTRY,
                },
            )
        )
    return out


# -----------------------------------------------------------------------------
# Institutions -- Art. 120 (rated) and Art. 121 (unrated)
# -----------------------------------------------------------------------------
# Art. 120(1) Table 3 (residual maturity > 3 months):
#   CQS  1     2     3     4     5     6
#   RW  20%   50%   50%  100%  100%  150%
# Art. 121(1) Table 5 (unrated, on the sovereign's CQS):
#   CQS  1     2     3     4     5     6
#   RW  20%   50%  100%  100%  100%  150%
# Art. 121(2): unrated institution in a country whose central government is
#   itself unrated -> 100%.
_INSTITUTION_TABLE_3 = {1: 0.20, 2: 0.50, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
_INSTITUTION_TABLE_5 = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.50}

_LONG_DATED = {"residual_maturity_years": 5.0, "original_maturity_years": 5.0}


# Art. 121(1) Table 5 is pinned across its WHOLE domain, one oracle per credit
# quality step, plus Art. 121(2) for the unrated-sovereign case. Testing the
# members that happen to be interesting is how a rule family gets mis-diagnosed:
# the engine returns a flat 100% here, which is conservative at CQS 1 and 2,
# correct by coincidence at CQS 3, 4 and 5, and *anti-conservative* at CQS 6.
# Sampling only the low steps hides the one step that under-weights.
#
# The CQS 3/4/5 oracles pass today only because the flat fallback happens to
# equal Table 5 there. They are worth their keep anyway: they pin the value, so
# a future change to that fallback cannot move them silently.
_TABLE_5_ORACLE_IDS = {
    1: "ORC-105",
    2: "ORC-020",
    3: "ORC-106",
    4: "ORC-107",
    5: "ORC-108",
    6: "ORC-109",
}


def institutions() -> list[dict[str, Any]]:
    rated_ids = {1: "ORC-016", 2: "ORC-017", 3: "ORC-018", 6: "ORC-019"}
    out = [
        _sa(
            rated_ids[cqs],
            "institution",
            f"CRR Art. 120(1) Table 3: rated institution CQS {cqs}, residual "
            f"maturity > 3 months -> {_INSTITUTION_TABLE_3[cqs]:.0%} RW",
            _INSTITUTION_TABLE_3[cqs],
            {"cqs": cqs, "entity_type": "institution", **_LONG_DATED, **_FOREIGN},
        )
        for cqs in sorted(rated_ids)
    ]
    out += [
        _sa(
            _TABLE_5_ORACLE_IDS[cqs],
            "institution",
            f"CRR Art. 121(1) Table 5: unrated institution, central government "
            f"CQS {cqs} -> {_INSTITUTION_TABLE_5[cqs]:.0%} RW",
            _INSTITUTION_TABLE_5[cqs],
            {
                "cqs": None,
                "entity_type": "institution",
                "sovereign_cqs": cqs,
                **_LONG_DATED,
                **_FOREIGN,
            },
        )
        for cqs in sorted(_TABLE_5_ORACLE_IDS)
    ]
    out.append(
        _sa(
            "ORC-021",
            "institution",
            "CRR Art. 121(2): unrated institution whose central government is unrated -> 100% RW",
            1.00,
            {
                "cqs": None,
                "entity_type": "institution",
                "sovereign_cqs": None,
                **_LONG_DATED,
                **_FOREIGN,
            },
        )
    )
    return out


# -----------------------------------------------------------------------------
# Corporates -- Art. 122
# -----------------------------------------------------------------------------
# Art. 122(1) Table 6:
#   CQS  1     2     3     4     5     6
#   RW  20%   50%  100%  100%  150%  150%
# Art. 122(2): unrated -> the higher of 100% and the sovereign's RW.
_CORPORATE_TABLE_6 = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.50, 6: 1.50}


def corporates() -> list[dict[str, Any]]:
    ids = {1: "ORC-022", 2: "ORC-023", 3: "ORC-024", 5: "ORC-025"}
    out = [
        _sa(
            ids[cqs],
            "corporate",
            f"CRR Art. 122(1) Table 6: rated corporate CQS {cqs} -> "
            f"{_CORPORATE_TABLE_6[cqs]:.0%} RW",
            _CORPORATE_TABLE_6[cqs],
            {"cqs": cqs, "entity_type": "corporate", **_FOREIGN},
        )
        for cqs in sorted(ids)
    ]
    out.append(
        _sa(
            "ORC-001",
            "corporate",
            "CRR Art. 122(2): unrated corporate -> 100% RW",
            1.00,
            {"cqs": None, "entity_type": "corporate"},
        )
    )
    return out


# -----------------------------------------------------------------------------
# Retail -- Art. 123
# -----------------------------------------------------------------------------
# Art. 123 first subparagraph: qualifying retail -> 75%.
# Art. 123 final subparagraph (inserted by Reg. 2019/876): pension/salary
#   assignment loans meeting points (a)-(d) -> 35%.
def retail() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-026",
            "retail_other",
            "CRR Art. 123: exposure meeting the retail criteria -> 75% RW",
            0.75,
            {
                "cqs": None,
                "entity_type": "individual",
                "cp_is_natural_person": True,
                "qualifies_as_retail": True,
            },
        ),
        _sa(
            "ORC-027",
            "retail_other",
            "CRR Art. 123 final subparagraph: pension / salary assignment loan "
            "meeting points (a)-(d) -> 35% RW",
            0.35,
            {
                "cqs": None,
                "entity_type": "individual",
                "cp_is_natural_person": True,
                "qualifies_as_retail": True,
                "is_payroll_loan": True,
                "original_maturity_years": 8.0,
                "residual_maturity_years": 8.0,
            },
        ),
    ]


# -----------------------------------------------------------------------------
# Immovable property -- Art. 124-126
# -----------------------------------------------------------------------------
# Art. 125(1)(a): residential property occupied / let by the owner -> 35%,
#   but Art. 125(2)(d) confines the 35% to the part of the loan not exceeding
#   80% of the property value. Art. 124(1) sends the part above the mortgage
#   value to "the risk weight applicable to the unsecured exposures of the
#   counterparty involved" -- here a natural person meeting Art. 123, so 75%.
# Art. 126(1)(a) with 126(2)(d): commercial property -> 50% on the part of the
#   loan up to 50% of market value, subject to the Art. 126(2) conditions
#   (including that repayment does not materially depend on the property's
#   cash-flows -- modelled by the income-cover flag). Otherwise Art. 124(1)
#   assigns 100%.
_RRE_PREFERENTIAL_RW = 0.35
_RRE_LTV_LIMIT = 0.80
_RETAIL_UNSECURED_RW = 0.75


def _rre_blended(ltv: float) -> float:
    """35% on the slice up to 80% LTV, 75% counterparty RW above it."""
    exposure = 1.0
    value = exposure / ltv
    return blend_two_bands(
        exposure=exposure,
        secured_amount=_RRE_LTV_LIMIT * value,
        secured_rw=_RRE_PREFERENTIAL_RW,
        residual_rw=_RETAIL_UNSECURED_RW,
    )


def immovable_property() -> list[dict[str, Any]]:
    rw_high_ltv = _rre_blended(1.00)  # 0.35*0.80 + 0.75*0.20 = 0.43
    return [
        _sa(
            "ORC-028",
            "retail_mortgage",
            "CRR Art. 125(1)(a): residential mortgage, LTV 60% (wholly within "
            "the Art. 125(2)(d) 80% limit) -> 35% RW",
            _RRE_PREFERENTIAL_RW,
            {
                "cqs": None,
                "entity_type": "individual",
                "cp_is_natural_person": True,
                "ltv": 0.60,
                "property_type": "residential",
            },
        ),
        _sa(
            "ORC-029",
            "retail_mortgage",
            "CRR Art. 125(2)(d) with Art. 124(1): residential mortgage at LTV "
            "100% -- 35% on the slice up to 80% of value, 75% counterparty RW "
            "on the remainder -> 43% blended RW",
            rw_high_ltv,
            {
                "cqs": None,
                "entity_type": "individual",
                "cp_is_natural_person": True,
                "ltv": 1.00,
                "property_type": "residential",
            },
            intermediate={
                "preferential_rw": _RRE_PREFERENTIAL_RW,
                "ltv_limit": _RRE_LTV_LIMIT,
                "residual_rw": _RETAIL_UNSECURED_RW,
            },
        ),
        _sa(
            "ORC-030",
            "commercial_mortgage",
            "CRR Art. 126(1)(a): commercial mortgage meeting the Art. 126(2) "
            "conditions, LTV 40% -> 50% RW",
            0.50,
            {
                "cqs": None,
                "entity_type": "corporate",
                "ltv": 0.40,
                "property_type": "commercial",
                "has_income_cover": True,
            },
        ),
        _sa(
            "ORC-031",
            "commercial_mortgage",
            "CRR Art. 124(1): commercial mortgage failing the Art. 126(2) conditions -> 100% RW",
            1.00,
            {
                "cqs": None,
                "entity_type": "corporate",
                "ltv": 0.70,
                "property_type": "commercial",
                "has_income_cover": False,
            },
        ),
    ]


# -----------------------------------------------------------------------------
# Default, covered bonds, equity, other items
# -----------------------------------------------------------------------------
# Art. 127(1): the unsecured part of a defaulted item carries
#   150% where specific credit risk adjustments are  < 20%, and
#   100% where they are >= 20%,
# of the unsecured exposure value measured *before* those adjustments -- i.e.
# of (exposure value + specific credit risk adjustments).
# Art. 129(4) Table 6A (rated covered bonds):
#   CQS  1     2     3     4     5     6
#   RW  10%   20%   20%   50%   50%  100%
# Art. 133(2): equity -> 100%.
# Art. 134(1): tangible assets and other items -> 100%.
_COVERED_BOND_TABLE_6A = {1: 0.10, 2: 0.20, 3: 0.20, 4: 0.50, 5: 0.50, 6: 1.00}


def _default_coverage(ead: float, provision: float) -> float:
    """SCRA / (exposure value before SCRA) -- the Art. 127(1) 20% test."""
    return provision / (ead + provision)


def defaults_and_others() -> list[dict[str, Any]]:
    thin_provision = 100_000.0
    thick_provision = 300_000.0
    return [
        _sa(
            "ORC-032",
            "defaulted",
            "CRR Art. 127(1)(a): defaulted exposure with specific credit risk "
            "adjustments below 20% of the pre-adjustment unsecured value -> 150% RW",
            1.50,
            {
                "cqs": None,
                "entity_type": "corporate",
                "is_defaulted": True,
                "provision_allocated": thin_provision,
            },
            intermediate={"scra_coverage": _default_coverage(M, thin_provision)},
        ),
        _sa(
            "ORC-033",
            "defaulted",
            "CRR Art. 127(1)(b): defaulted exposure with specific credit risk "
            "adjustments at or above 20% of the pre-adjustment unsecured value "
            "-> 100% RW",
            1.00,
            {
                "cqs": None,
                "entity_type": "corporate",
                "is_defaulted": True,
                "provision_allocated": thick_provision,
            },
            intermediate={"scra_coverage": _default_coverage(M, thick_provision)},
        ),
        _sa(
            "ORC-034",
            "covered_bond",
            "CRR Art. 129(4) Table 6A: rated covered bond CQS 1 -> 10% RW",
            _COVERED_BOND_TABLE_6A[1],
            {"cqs": 1, "entity_type": "covered_bond", **_FOREIGN},
        ),
        _sa(
            "ORC-035",
            "covered_bond",
            "CRR Art. 129(4) Table 6A: rated covered bond CQS 4 -> 50% RW",
            _COVERED_BOND_TABLE_6A[4],
            {"cqs": 4, "entity_type": "covered_bond", **_FOREIGN},
        ),
        _sa(
            "ORC-037",
            "other",
            "CRR Art. 134(1): tangible assets / other items -> 100% RW",
            1.00,
            {"cqs": None, "entity_type": "other_tangible"},
        ),
    ]


def equity() -> list[dict[str, Any]]:
    return [
        oracle(
            oracle_id="ORC-036",
            phase=PHASE,
            framework=FRAMEWORK,
            approach="EQUITY",
            exposure_class="equity",
            regulation="CRR Art. 133(2): equity exposure under the Standardised "
            "Approach -> 100% RW",
            ead=M,
            risk_weight=1.00,
            inputs={"equity_type": "listed", "is_exchange_traded": True},
        )
    ]


# -----------------------------------------------------------------------------
# Supporting factors -- Art. 501 and Art. 501a
# -----------------------------------------------------------------------------
# Art. 501(1): RWEA* = RWEA * [min(E*, EUR 2.5m)*0.7619 + max(E*-2.5m,0)*0.85]/E*
# Art. 501a(1): own funds requirements multiplied by 0.75 for qualifying
#   infrastructure exposures in the corporate or specialised lending classes.
INFRASTRUCTURE_SUPPORTING_FACTOR = 0.75


def supporting_factors() -> list[dict[str, Any]]:
    sme_ead = M
    sme_factor = sme_supporting_factor(sme_ead)
    return [
        _sa(
            "ORC-038",
            "corporate_sme",
            "CRR Art. 122(2) with Art. 501(1): unrated SME corporate at 100% RW, "
            "SME supporting factor 0.7619 (E* below the EUR 2.5m threshold)",
            1.00,
            {"cqs": None, "entity_type": "corporate", "is_sme": True},
            ead=sme_ead,
            rwa=sme_ead * 1.00 * sme_factor,
            intermediate={"supporting_factor": sme_factor},
            extra_expected={"supporting_factor": sme_factor},
        ),
        _sa(
            "ORC-039",
            "corporate",
            "CRR Art. 501a(1): qualifying infrastructure corporate at 100% RW, "
            "own funds requirement multiplied by 0.75",
            1.00,
            {"cqs": None, "entity_type": "corporate", "is_infrastructure": True},
            rwa=M * 1.00 * INFRASTRUCTURE_SUPPORTING_FACTOR,
            intermediate={"supporting_factor": INFRASTRUCTURE_SUPPORTING_FACTOR},
            extra_expected={"supporting_factor": INFRASTRUCTURE_SUPPORTING_FACTOR},
        ),
    ]


def all_oracles() -> list[dict[str, Any]]:
    return [
        *sovereigns(),
        *public_sector(),
        *institutions(),
        *corporates(),
        *retail(),
        *immovable_property(),
        *defaults_and_others(),
        *equity(),
        *supporting_factors(),
    ]
