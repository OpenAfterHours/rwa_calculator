"""
The deterministic portfolio corpus every property is checked against.

Key responsibilities:
- Give the suite a fixed, diverse set of portfolios that is run ONCE per regime
  and reused by every property, via the ``portfolios.run`` memo. Generation
  explores; the corpus guarantees a floor of coverage that does not depend on
  what the generator happened to draw.
- Reach the parts of the estate whose emptiness has hidden defects before:
  off-balance-sheet conversion factors, CRM substitution legs, the defaulted
  branch, and the F-IRB / A-IRB class axis.

Each portfolio exists for a reason that is written down. A portfolio nobody can
name the purpose of is a portfolio nobody will notice going dark
(`.claude/LESSONS.md` B5).

References:
- CRR Art. 111 / Annex I, PS1/26 Art. 111 Table A1: the conversion-factor buckets
- CRR Art. 127, PS1/26 Art. 127: defaulted exposures and provision coverage
- CRR Art. 235: substitution of the protection provider's risk weight
"""

from __future__ import annotations

from tests.properties.portfolios import ExposureSpec

# ---------------------------------------------------------------------------
# The portfolios
# ---------------------------------------------------------------------------

#: Every SA obligor type this engine distinguishes, drawn and unmitigated, so a
#: mis-weighted class shows as one changed leg rather than as a blend.
SA_BROAD: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="sovereign", drawn=9_000_000.0, external_cqs=1),
    ExposureSpec(entity_type="rgla_sovereign", drawn=3_000_000.0, external_cqs=None),
    ExposureSpec(entity_type="rgla_institution", drawn=3_500_000.0, external_cqs=2),
    ExposureSpec(entity_type="pse_institution", drawn=2_500_000.0, external_cqs=2),
    ExposureSpec(entity_type="mdb", drawn=4_000_000.0, external_cqs=2),
    ExposureSpec(entity_type="mdb_named", drawn=4_500_000.0, external_cqs=None),
    ExposureSpec(entity_type="international_org", drawn=1_500_000.0, external_cqs=None),
    ExposureSpec(entity_type="covered_bond", drawn=6_000_000.0, external_cqs=1),
    ExposureSpec(entity_type="institution", drawn=2_000_000.0, external_cqs=3),
    ExposureSpec(entity_type="corporate", drawn=5_000_000.0, external_cqs=3),
    ExposureSpec(entity_type="corporate", drawn=1_200_000.0, annual_revenue=20_000_000.0),
    ExposureSpec(entity_type="individual", drawn=400_000.0, external_cqs=None),
)

#: One off-balance-sheet leg per CRR Annex I / PS1/26 Table A1 conversion-factor
#: bucket. This is the portfolio shape whose absence hid four C 07.00 defects for
#: the template's entire life.
OFF_BALANCE_SHEET: tuple[ExposureSpec, ...] = tuple(
    ExposureSpec(
        entity_type="corporate",
        drawn=1_000_000.0,
        off_bs_nominal=2_000_000.0,
        off_bs_risk_type=risk_type,
        external_cqs=3,
    )
    for risk_type in ("FR", "FRC", "MR", "MR_ISSUED", "MLR", "OC", "LR")
)

#: F-IRB and A-IRB across every class the model permissions grant, plus retail.
#: The F-IRB / A-IRB split is driven by the presence of a firm LGD estimate.
IRB_MIX: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="sovereign", drawn=9_000_000.0, external_cqs=None, internal_pd=0.004),
    ExposureSpec(
        entity_type="sovereign",
        drawn=7_000_000.0,
        external_cqs=None,
        internal_pd=0.004,
        firm_lgd=0.35,
    ),
    ExposureSpec(
        entity_type="institution", drawn=6_000_000.0, external_cqs=None, internal_pd=0.006
    ),
    ExposureSpec(
        entity_type="institution",
        drawn=5_000_000.0,
        external_cqs=None,
        internal_pd=0.006,
        firm_lgd=0.40,
    ),
    ExposureSpec(
        entity_type="corporate", drawn=50_000_000.0, external_cqs=None, internal_pd=0.0075
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=20_000_000.0,
        external_cqs=None,
        internal_pd=0.010,
        firm_lgd=0.30,
    ),
    # Below the SME revenue ceiling: the corporate_sme class under both approaches.
    ExposureSpec(
        entity_type="corporate",
        drawn=1_500_000.0,
        external_cqs=None,
        internal_pd=0.012,
        annual_revenue=20_000_000.0,
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=1_400_000.0,
        external_cqs=None,
        internal_pd=0.012,
        firm_lgd=0.35,
        annual_revenue=20_000_000.0,
    ),
    # Retail is A-IRB only (Art. 151(4)), so it carries a firm LGD.
    ExposureSpec(
        entity_type="individual",
        drawn=300_000.0,
        external_cqs=None,
        internal_pd=0.020,
        firm_lgd=0.20,
    ),
)

#: Funded and unfunded protection, sized so each exposure is PARTLY covered —
#: a fully-covered leg has no remainder and hides a substitution defect in the
#: half of the split that disappeared.
MITIGATED: tuple[ExposureSpec, ...] = (
    ExposureSpec(
        entity_type="corporate",
        drawn=4_000_000.0,
        external_cqs=4,
        collateral_value=1_500_000.0,
        collateral_type="cash",
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=4_000_000.0,
        external_cqs=4,
        collateral_value=1_500_000.0,
        collateral_type="bond",
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=6_000_000.0,
        external_cqs=5,
        guarantee_amount=2_500_000.0,
        guarantor_entity_type="sovereign",
        guarantor_cqs=1,
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=6_000_000.0,
        external_cqs=5,
        guarantee_amount=2_500_000.0,
        guarantor_entity_type="institution",
        guarantor_cqs=2,
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=8_000_000.0,
        external_cqs=None,
        internal_pd=0.01,
        firm_lgd=0.45,
        collateral_value=3_000_000.0,
        collateral_type="cash",
    ),
)

#: The defaulted branch, on both sides of the Art. 127 provision-coverage split
#: (150% below 20% coverage of the unsecured part, 100% at or above it).
DEFAULTED: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="corporate", drawn=3_000_000.0, external_cqs=5, is_defaulted=True),
    ExposureSpec(
        entity_type="corporate",
        drawn=3_000_000.0,
        external_cqs=5,
        is_defaulted=True,
        provision_amount=900_000.0,
    ),
    ExposureSpec(entity_type="individual", drawn=400_000.0, external_cqs=None, is_defaulted=True),
)

#: Boundary shapes: nothing drawn, a de-minimis amount, and obligors the
#: regulation weights at 0% unconditionally (Art. 117(2), Art. 118).
EDGE_CASES: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="corporate", drawn=0.0, external_cqs=3),
    ExposureSpec(entity_type="corporate", drawn=0.01, external_cqs=3),
    ExposureSpec(entity_type="mdb_named", drawn=5_000_000.0, external_cqs=None),
    ExposureSpec(entity_type="international_org", drawn=5_000_000.0, external_cqs=None),
    ExposureSpec(entity_type="corporate", drawn=1_000_000.0, off_bs_nominal=0.0, external_cqs=None),
)

#: Name -> portfolio. Parametrise over ``.items()`` so a failure names the
#: portfolio rather than printing a wall of specs.
CORPUS: dict[str, tuple[ExposureSpec, ...]] = {
    "sa_broad": SA_BROAD,
    "off_balance_sheet": OFF_BALANCE_SHEET,
    "irb_mix": IRB_MIX,
    "mitigated": MITIGATED,
    "defaulted": DEFAULTED,
    "edge_cases": EDGE_CASES,
}

#: Every corpus portfolio concatenated — the one portfolio that exercises the
#: whole class x approach x mitigation grid in a single run, for the properties
#: whose statement is about the portfolio TOTAL rather than about a leg.
EVERYTHING: tuple[ExposureSpec, ...] = tuple(
    spec for portfolio in CORPUS.values() for spec in portfolio
)
