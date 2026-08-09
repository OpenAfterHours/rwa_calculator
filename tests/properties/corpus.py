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

#: Exposures that the real-estate loan-splitter actually FANS OUT, one parent
#: exposure into a secured leg plus a residual leg.
#:
#: Deliberately kept OUT of :data:`CORPUS` below. Every property module
#: parametrises over ``CORPUS``, so adding it there would subject seven unrelated
#: property suites (monotonicity, regime deltas, homogeneity, the output-floor
#: identities, ...) to a row-count-changing stage in one step, and a failure in
#: any of them would be indistinguishable from the split defect this portfolio
#: exists to expose. Import it by name instead. Promoting it into ``CORPUS`` is
#: worth doing once the split legs are conserved, and needs a full-suite blast
#: radius measurement rather than a grep (`.claude/LESSONS.md` D2, D3).
#:
#: Every leg is unrated so the residual takes the corporate unrated risk weight
#: and the arithmetic of the split is legible: a changed number is the split, not
#: a changed rating lookup.
RE_SPLIT: tuple[ExposureSpec, ...] = (
    # Exactly-covered: property value == exposure, so the secured leg is the
    # regime's LTV cap outright (80% CRR Art. 125 / 55% PS1/26 Art. 124F) and the
    # residual is the remainder. This is the measured reproducer for the
    # carrier-duplication defect.
    ExposureSpec(
        entity_type="corporate",
        drawn=1_000_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
    ),
    # Under-collateralised: the cap binds well below the exposure, so the residual
    # leg is the larger of the two and a residual-side error cannot hide behind a
    # small number.
    ExposureSpec(
        entity_type="corporate",
        drawn=2_000_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
    ),
    # Over-collateralised commercial: the property exceeds the exposure, so the
    # cap is slack on the CRE side. ``rental_to_interest_ratio`` is attested
    # because CRR Art. 126(2)(d) makes the preferential CRE treatment conditional
    # on rental income covering interest costs — without it the CRE limb is
    # ineligible and this leg would silently stop being a split at all.
    ExposureSpec(
        entity_type="corporate",
        drawn=1_000_000.0,
        external_cqs=None,
        collateral_value=1_500_000.0,
        collateral_property_type="commercial",
        collateral_rental_to_interest_ratio=2.0,
    ),
    # A prior charge ranking ahead of us, which PS1/26 Art. 124F(2) deducts from
    # the secured cap. Under CRR Art. 125 there is no such deduction, so this leg
    # is also the one that makes the two regimes disagree on the split point.
    ExposureSpec(
        entity_type="corporate",
        drawn=1_000_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
        collateral_prior_charge_ltv=0.2,
    ),
)

#: Exposures that BOTH reach the real-estate loan-splitter AND carry eligible
#: financial collateral — one exposure, two mitigation routes.
#:
#: Also deliberately kept OUT of :data:`CORPUS`, for the same reason
#: :data:`RE_SPLIT` is: it changes the row count.
#:
#: This is the only shape on which ``collateral_adjusted_value`` is non-zero on a
#: row the splitter emitted. On an RE-only split it is 0.0 on every leg, because
#: immovable property is recognised through the exposure class and the Art. 125 /
#: Art. 124F cap rather than through the Art. 223 volatility-adjusted collateral
#: value. So a carrier that the splitter allocates across legs and the collapse
#: path must sum back up was, for that carrier, exercised by nothing in the
#: estate: every fixture either split with no financial collateral or carried
#: financial collateral without splitting. A leg-share that the collapse dropped
#: would leave the parent silently holding one leg's fraction — and
#: ``collateral_adjusted_value`` is compared by the reconciliation engine, so the
#: consequence is a real reconciliation break rather than a cosmetic one.
#:
#: Property values are set so the split point differs between the regimes (the
#: caps are ``re_split_{rre,cre}_secured_ltv_cap``, and only Basel 3.1 deducts a
#: prior charge), and the financial pledge is sized well below the exposure so
#: the Art. 223 adjusted value is a genuine partial cover with a remainder — a
#: fully covered exposure has no remainder and hides a mis-weighted blend.
RE_SPLIT_WITH_FINANCIAL: tuple[ExposureSpec, ...] = (
    # Residential property plus cash. Cash takes a zero volatility adjustment
    # (Art. 224 Table 1), so the adjusted value equals the market value and the
    # allocation across legs is legible by inspection.
    ExposureSpec(
        entity_type="corporate",
        drawn=2_000_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
        financial_collateral_value=400_000.0,
        financial_collateral_type="cash",
    ),
    # Residential property plus a sovereign bond, which DOES take a volatility
    # adjustment, so the adjusted value is strictly below the market value and a
    # leg that carried the raw value instead would be distinguishable.
    ExposureSpec(
        entity_type="corporate",
        drawn=2_000_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
        financial_collateral_value=600_000.0,
        financial_collateral_type="government_bond",
    ),
    # A prior charge on the property, so the two regimes split this exposure at
    # different points (PS1/26 Art. 124F(2) deducts it, CRR Art. 125 does not)
    # while the financial pledge is identical — the leg shares therefore differ
    # by regime and a hardcoded share would fail on one of them.
    ExposureSpec(
        entity_type="corporate",
        drawn=2_000_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
        collateral_prior_charge_ltv=0.2,
        financial_collateral_value=400_000.0,
        financial_collateral_type="cash",
    ),
    # No property: financial collateral only, and therefore NO split. The
    # control leg — it keeps ``collateral_adjusted_value`` populated on an
    # unsplit row, so a change to the split-leg allocation is distinguishable
    # from a change to the carrier itself (`.claude/LESSONS.md` B5).
    ExposureSpec(
        entity_type="corporate",
        drawn=2_000_000.0,
        external_cqs=None,
        financial_collateral_value=500_000.0,
        financial_collateral_type="cash",
    ),
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
