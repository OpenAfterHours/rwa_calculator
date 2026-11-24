"""
The mutant catalogue for the defect-injection scorecard (C6).

Every entry is a realistic defect: a one-line source edit that a competent
person could plausibly make, or has already made here. Nothing is invented for
the sake of a number -- the catalogue is seeded from three places, in
descending order of evidential weight:

``known_defect``
    Defects this project has actually found. Because they exist in the tree
    today, injecting them again would be a no-op, so each one is applied to the
    *adjacent correct* site of the same shape. If the estate catches the twin
    it would have caught the original.
``lessons``
    ``.claude/LESSONS.md`` traps that have a mechanical form -- B1 (a presence
    guard on a carrier name no run produces), B2 (a class map keyed on a
    non-enum string), B6 (an (approach, class) pair with no row), D4 (a missing
    dtype cast), E3 (a subtotal double-count).
``generic``
    Perturbations of the kind that slip through review: a regulatory constant
    off by one band, a comparison flipped, a benefit cap inverted.

Two entries are deliberate **controls**:

- ``control-unreachable-output-floor-full`` mutates a rulepack scalar that is
  only read under an election no RUNS portfolio makes. The reachability probe MUST
  find it unreachable. In the trust check this control, like every
  ``expect_unreachable`` mutant, is judged on the probe, not on the verdict:
  ``injection_ratchet.py --check`` fails if the probe calls it reachable, and a
  gate may still catch it. One does: a unit test makes the election itself and
  calls the production helper that reads the scalar, so the path is dead to the
  probe's RUNS matrix, not to the test suite. If the probe calls it reachable,
  the probe is broken and every other "not detected" verdict is suspect. This is
  not hypothetical: the same mutation once produced 52/52 passing floor
  properties, which read as proof the properties were vacuous. They were not; the
  path was dead to every portfolio they ran. The banked set ratchet is separate
  and judges its VERDICT like any other mutant's: if that unit test went, the
  control would fall from DETECTED to UNREACHABLE and the nightly would go red.
- ``control-reachable-output-floor-schedule`` mutates the step that IS read, so
  the pair distinguishes "no gate covers this" from "nothing ran". Its REACHABLE
  result is NOT enforced: the trust check fails an expected-reachable mutant
  only when it scores UNREACHABLE (no gate caught it and the probe saw nothing),
  so while a gate catches this control, ``--check`` passes whatever the probe
  says. The harness still lists a contradicted probe under
  ``expectation_mismatches``.

Adding a mutant is one entry here. The runner never needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Mutants applied to a file the catalogue does not list are refused outright,
#: so this doubles as the allowlist of files the harness may ever write to.
CATEGORIES = ("known_defect", "lessons", "generic", "control")

#: Mutation targets shared by several entries.
TARGET_C02 = "src/rwa_calc/reporting/corep/c02.py"
TARGET_IRB_FORMULAS = "src/rwa_calc/engine/irb/formulas.py"
TARGET_B31_PACK = "src/rwa_calc/rulebook/packs/b31.py"


@dataclass(frozen=True)
class Mutant:
    """One injectable defect.

    ``old`` must appear EXACTLY ONCE in ``target``. The self-test enforces both
    halves: absent means the code moved under the catalogue, and duplicated
    means the edit would land somewhere unintended.
    """

    id: str
    category: str
    target: str
    old: str
    new: str
    summary: str
    rationale: str
    #: Set only where the mutant is expected NOT to change any output. The
    #: reachability probe must agree; a mismatch either way is a finding.
    expect_unreachable: bool = False


CATALOGUE: tuple[Mutant, ...] = (
    # =========================================================================
    # Known defects, applied to the adjacent correct site
    # =========================================================================
    Mutant(
        id="known-c02-phantom-class-key",
        category="known_defect",
        target=TARGET_C02,
        old='rows.AIRB_INSTITUTIONS: of_class(_AIRB, "institution"),',
        new='rows.AIRB_INSTITUTIONS: of_class(_AIRB, "institutions"),',
        summary="C 02.00 row 0330 keyed on a class string no enum member produces",
        rationale=(
            "The defect at the sibling line asked for 'central_government' where "
            "the enum says 'central_govt_central_bank', which pinned the A-IRB "
            "central-governments row to zero for the template's whole life (fixed "
            "2026-11-13, when the template took its published row codes; the "
            "sibling now reads the enum value). This is the same shape on the "
            "correct institution lookup: the row silently zeroes while the "
            "independently-computed approach total still counts the RWEA, so the "
            "template stays internally plausible. LESSONS B2."
        ),
    ),
    Mutant(
        id="known-c02-stranded-subclass",
        category="known_defect",
        target=TARGET_C02,
        old="amounts[rows.FIRB_SPECIALISED_LENDING] += slotting",
        new="amounts[rows.FIRB_SPECIALISED_LENDING] += _NOTHING",
        summary="C 02.00 row 0290 drops the supervisory-slotting limb",
        rationale=(
            "Mirrors the defect where the A-IRB corporate lookups never asked "
            "for corporate_sme, stranding 13,606,784.12 on the rich portfolio "
            "(fixed 2026-11-13). RWEA falls out of the breakdown while the parent "
            "total (row 0250) still counts it. LESSONS B6 -- and note the missing "
            "pair is by definition not in the row list, so reading the list "
            "cannot find it."
        ),
    ),
    Mutant(
        id="known-p3-empty-class-tuple",
        category="known_defect",
        target="src/rwa_calc/reporting/pillar3/templates.py",
        old='("6", "Institutions", ("institution",)),',
        new='("6", "Institutions", ()),',
        summary="Pillar 3 CR4/CR5 row 6 (institutions) bound to no exposure class",
        rationale=(
            "SA_DISCLOSURE_CLASSES row 11 (high_risk) is bound to an empty tuple "
            "today, so the row can never populate while both Total rows still "
            "count the leg (pinned by the strict xfail "
            "test_high_risk_leg_reaches_a_pillar3_class_row). Same shape on a "
            "single-class row that works and that the RUNS matrix populates, in "
            "each regime: rich (2,000,000 on balance sheet), off-bs (2,500,000 off "
            "balance sheet) and crm-substitution (EAD 4,300,000). ccr does not: "
            "every money cell of its row 6 is 0.0 in both regimes. The sheet is "
            "emitted, the row is present, and it reports nothing. This used to "
            "empty row 15 (equity), which can never populate -- CR4/CR5 admit only "
            "standardised-origin legs and "
            "every equity leg is stamped 'equity' -- so its only catch was a test "
            "pinning that known zero. Re-targeted under P5.76, together with the "
            "probe change that made any Pillar 3 site visible at all."
        ),
    ),
    Mutant(
        id="known-sovereign-ladder-flattened",
        category="known_defect",
        target="src/rwa_calc/engine/sa/rgla.py",
        old='return is_sovereign_rgla & ((pl.col("cp_country_code") == "GB") | has_sovereign_cqs)',
        new="return is_sovereign_rgla & has_sovereign_cqs",
        summary="A GB devolved-government RGLA drops off the Art. 114 sovereign ladder",
        rationale=(
            "P1.282 found the other limb of this predicate missing: a non-GB "
            "rgla_sovereign was not recognised at all and fell through to the "
            "ordinary Art. 115(1) ladder instead of its central government's "
            "Art. 114 one. This drops the "
            "adjacent GB limb, the one the RUNS matrix exercises: sa-classes' "
            "SAC-LN-RGLA-UK (GB, sterling-denominated and funded) leaves the "
            "Art. 114 ladder at 0% for the Art. 115(5) 20%, in both regimes. It "
            "used to flatten has_sovereign_cqs, the twin of the Art. 121(1) Table 5 "
            "defect (fixed by P1.316), but that limb reads cp_sovereign_cqs and no "
            "RUNS portfolio carries one (P5.22), so it moved nothing the probe sees. "
            "The id predates the re-target (no ladder is flattened now) and is kept "
            "because the banked verdict sets are keyed by id: a rename would leave "
            "detected_ids and force a re-bank."
        ),
    ),
    # =========================================================================
    # LESSONS traps in mechanical form
    # =========================================================================
    Mutant(
        id="lessons-b1-dead-carrier",
        category="lessons",
        target="src/rwa_calc/reporting/corep/ccf_buckets.py",
        old='CCF_CARRIERS: Final[tuple[str, ...]] = ("ccf", "ccf_applied")',
        new='CCF_CARRIERS: Final[tuple[str, ...]] = ("ccf_applied",)',
        summary="CCF carrier ladder reduced to the name no pipeline run produces",
        rationale=(
            "LESSONS B1, measured: the C 07.00 CCF columns bucketed on "
            "'ccf_applied', a name that exists only in data/schemas.py and on "
            "synthetic unit frames, and published nothing for the template's "
            "entire life. Nothing raises -- the presence guard simply never fires."
        ),
    ),
    Mutant(
        id="lessons-d4-missing-cast",
        category="lessons",
        target="src/rwa_calc/engine/sa/central_bank.py",
        old='.then(pl.col("cp_sovereign_cqs").cast(pl.Int8))',
        new='.then(pl.col("cp_sovereign_cqs"))',
        summary="Sovereign CQS lifted without the Int8 cast the edge requires",
        rationale=(
            "LESSONS D4: cp_sovereign_cqs is Int32 while cqs is Int8, and no "
            "unit test can catch the omission -- only the sealed sa_branch edge "
            "enforces it. Cost 200 acceptance failures when it happened."
        ),
    ),
    Mutant(
        id="lessons-e3-subtotal-double-count",
        category="lessons",
        target="src/rwa_calc/reporting/corep/c07.py",
        old='return (cells["0040"] or 0.0) - (cells["0090"] or 0.0) + (cells["0100"] or 0.0)',
        new='return (cells["0040"] or 0.0) - 2.0 * (cells["0090"] or 0.0) + (cells["0100"] or 0.0)',
        summary="C 07.00 col 0110 deducts the substitution outflow twice",
        rationale=(
            "LESSONS E3: subtracting the breakdown AND the subtotal double-counts. "
            "Col 0090 already IS 0050 + 0060 + 0070 + 0080, so a 0110 that removes "
            "the components and 0090 deducts every outflow twice -- the defect "
            "``_net_after_substitution``'s docstring records. This used to add col "
            "0040 inside the 0090 subtotal, but the 0090 Formula's refs never "
            "include 0040, so ``cells.get('0040')`` was always None and the "
            "mutant moved nothing."
        ),
    ),
    # =========================================================================
    # Generic mutations -- engine
    # =========================================================================
    Mutant(
        id="generic-irb-scaling-factor",
        category="generic",
        target="src/rwa_calc/rulebook/packs/crr.py",
        old='"irb_scaling_factor": ScalarParam(\n        name="irb_scaling_factor",\n        value=Decimal("1.06"),',
        new='"irb_scaling_factor": ScalarParam(\n        name="irb_scaling_factor",\n        value=Decimal("1.10"),',
        summary="CRR Art. 153(1) 1.06 scaling factor changed to 1.10",
        rationale=(
            "A wrong regulatory constant: every IRB risk weight moves by 3.8% and "
            "no conservation, bound or monotonicity property notices. This is the "
            "defect class the oracle exists for."
        ),
    ),
    Mutant(
        id="generic-corporate-correlation-low",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="return 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)",
        new="return 0.14 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)",
        summary="Corporate asset correlation lower bound 0.12 -> 0.14",
        rationale=(
            "CRR Art. 153(1) / PS1/26 Art. 153(1)(c). Monotone in PD either way, "
            "so every ordering property still holds."
        ),
    ),
    Mutant(
        id="generic-retail-correlation",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="r_retail_other = 0.03 * f_pd_retail + 0.16 * (1.0 - f_pd_retail)",
        new="r_retail_other = 0.05 * f_pd_retail + 0.16 * (1.0 - f_pd_retail)",
        summary="Retail asset correlation lower bound 0.03 -> 0.05",
        rationale="CRR Art. 154(1) / PS1/26 Art. 154(1)(b). Same shape as above, retail side.",
    ),
    Mutant(
        id="generic-maturity-adjustment-b",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="b = (0.11852 - 0.05478 * pd_safe.log()) ** 2",
        new="b = (0.11852 - 0.05578 * pd_safe.log()) ** 2",
        summary="Maturity adjustment coefficient 0.05478 -> 0.05578",
        rationale=(
            "A transposed digit in the Art. 153(1) maturity adjustment. Small, "
            "plausible, and invisible to anything that does not re-derive it."
        ),
    ),
    Mutant(
        id="generic-correlation-decay",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="/ (1.0 - math.exp(-50.0))",
        new="/ (1.0 - math.exp(-45.0))",
        summary="Corporate correlation decay factor -50 -> -45",
        rationale=(
            "The denominator is within 1e-20 of 1.0 either way, so this is a "
            "REACHABILITY test as much as a detection test: the mutant is "
            "applicable but its numerical effect is below float resolution. "
            "Expect UNREACHABLE, and treat a 'detected' verdict as suspicious."
        ),
        expect_unreachable=True,
    ),
    Mutant(
        id="generic-benefit-cap-inverted",
        category="generic",
        target="src/rwa_calc/engine/sa/rw_adjustments.py",
        old='& (pl.col("guarantor_rw") < pl.col("pre_crm_risk_weight"))',
        new='& (pl.col("guarantor_rw") > pl.col("pre_crm_risk_weight"))',
        summary="SA guarantee benefit test inverted: only a worse guarantor is substituted",
        rationale=(
            "CRR Art. 193(1): no exposure with CRM may produce a higher RWEA than "
            "the identical unprotected one, and the Art. 235(1) blend carries no "
            "min of its own, so apply_guarantee_substitution declines any guarantor "
            "whose weight is not below the obligor's. Inverting that test keeps the "
            "guarantees that raise the weight and declines every one that helps, "
            "and the is_guarantee_beneficial flag it sets also gates the reporting "
            "substitution flows. LESSONS D1 territory: these adjustments are "
            "benefit-only, and the SA pipe runs unconditionally to feed the Basel "
            "3.1 output floor. crm-substitution carries a beneficial SA guarantee "
            "in both regimes. This used to invert the min cap in "
            "apply_third_party_deposit_rw_mapping (Art. 232), the same shape, but "
            "no RUNS portfolio holds a third-party deposit, so it moved nothing "
            "the probe sees. The id predates the re-target (it is a benefit test "
            "now, not a cap) and is kept because the banked verdict sets are keyed "
            "by id: a rename would leave detected_ids and force a re-bank."
        ),
    ),
    Mutant(
        id="generic-cqs-cast-dropped",
        category="generic",
        target="src/rwa_calc/engine/sa/crr_risk_weight_tables.py",
        # The two-line cast block appears twice in this file; the preceding
        # DataFrame construction is what makes the address unambiguous.
        old=(
            "    return pl.DataFrame(data).with_columns(\n"
            "        [\n"
            '            pl.col("cqs").cast(pl.Int8),'
        ),
        new=('    return pl.DataFrame(data).with_columns(\n        [\n            pl.col("cqs"),'),
        summary="CQS join key cast dropped from a risk-weight lookup",
        rationale=(
            "A dtype mismatch on a join key silently produces no match, which "
            "reads as 'unrated' rather than as an error."
        ),
    ),
    Mutant(
        id="generic-b31-institution-cqs2",
        category="generic",
        target=TARGET_B31_PACK,
        old=(
            '        name="institution_rw_b31_ecra",\n'
            "        entries={\n"
            '            CQS.CQS1: Decimal("0.20"),\n'
            '            CQS.CQS2: Decimal("0.30"),'
        ),
        new=(
            '        name="institution_rw_b31_ecra",\n'
            "        entries={\n"
            '            CQS.CQS1: Decimal("0.20"),\n'
            '            CQS.CQS2: Decimal("0.50"),'
        ),
        summary="Basel 3.1 institution ECRA CQS 2 reverts to the CRR 50% weight",
        rationale=(
            "PS1/26 Art. 120(1) Table 3 gives CQS 2 a 30% weight where CRR gives "
            "50%: a Basel 3.1 table carrying the CRR value is the shape a copy-"
            "paste between packs produces. This used to rename the table's "
            "``name`` field, which nothing reads (lookups bind on the dict key), "
            "so it moved no output and no gate could ever see it."
        ),
    ),
    Mutant(
        id="generic-corporate-correlation-high",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="return 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)",
        new="return 0.12 * f_pd_corp + 0.22 * (1.0 - f_pd_corp)",
        summary="Corporate asset correlation upper bound 0.24 -> 0.22",
        rationale=(
            "The other end of the same Art. 153(1) curve. Shares its ``old`` "
            "string with the lower-bound mutant, which is fine -- only one "
            "mutant is ever applied at a time -- and the two together show "
            "whether detection depends on which end of the curve moves."
        ),
    ),
    Mutant(
        id="generic-retail-correlation-decay",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="retail_denom = 1.0 - math.exp(-35.0)",
        new="retail_denom = 1.0 - math.exp(-30.0)",
        summary="Retail correlation decay factor -35 -> -30",
        rationale=(
            "Like the corporate decay twin, the denominator is numerically "
            "indistinguishable from 1.0 either way. Expect UNREACHABLE."
        ),
        expect_unreachable=True,
    ),
    Mutant(
        id="generic-scaling-regime-inverted",
        category="generic",
        target=TARGET_B31_PACK,
        old='"irb_scaling_factor": ScalarParam(\n        name="irb_scaling_factor",\n        value=Decimal("1.0"),',
        new='"irb_scaling_factor": ScalarParam(\n        name="irb_scaling_factor",\n        value=Decimal("1.06"),',
        summary="Basel 3.1 IRB keeps the CRR 1.06 scaling factor",
        rationale=(
            "CRR Art. 153(1) keeps the 1.06 factor and PS1/26 Art. 153(1)(c) "
            "removes it. The regime split lives in the two packs' "
            "irb_scaling_factor entries, so the Basel 3.1 pack carrying the CRR "
            "value is the regime mix-up a copy-paste between packs produces: every "
            "Basel 3.1 IRB-formula risk weight rises 6% while CRR is untouched. Distinct "
            "from generic-irb-scaling-factor, which moves the CRR value. This used "
            "to invert the branch in engine/irb/formulas.py::calculate_irb_rwa, a "
            "scalar wrapper nothing in src/ calls (only the CRR expected-output "
            "workbook does), so no portfolio could reach it. The id predates the "
            "re-target (nothing is inverted now) and is kept because the banked "
            "verdict sets are keyed by id: a rename would leave detected_ids and "
            "force a re-bank."
        ),
    ),
    Mutant(
        id="generic-firb-institution-key",
        category="generic",
        target=TARGET_C02,
        old='rows.FIRB_INSTITUTIONS: of_class(_FIRB, "institution"),',
        new='rows.FIRB_INSTITUTIONS: of_class(_FIRB, "institutions"),',
        summary="C 02.00 F-IRB institution row keyed on a non-enum string",
        rationale=(
            "The F-IRB twin of known-c02-phantom-class-key. Both limbs of the "
            "same template are worth pinning: the A-IRB one is the shape of the "
            "live defect, and this one shows whether detection generalises "
            "across the approach axis or is an accident of one row's coverage."
        ),
    ),
    Mutant(
        id="generic-firb-corporate-stranded",
        category="generic",
        target=TARGET_C02,
        old='rows.FIRB_SPECIALISED_LENDING: of_class(_FIRB, "specialised_lending"),',
        new="rows.FIRB_SPECIALISED_LENDING: _NOTHING,",
        summary="C 02.00 F-IRB specialised-lending RWEA stranded at zero",
        rationale=(
            "LESSONS B6 on the F-IRB limb: the approach total still counts the "
            "specialised-lending RWEA while the of-which row reports none, so "
            "the template foots against itself and the shortfall is invisible "
            "unless something sums the leaves independently."
        ),
    ),
    # =========================================================================
    # Controls -- these prove the reachability probe works
    # =========================================================================
    Mutant(
        id="control-unreachable-output-floor-full",
        category="control",
        target=TARGET_B31_PACK,
        old=('    "output_floor_pct_full": ScalarParam(\n        name="output_floor_pct_full",'),
        new=(
            '    "output_floor_pct_full_MUTANT": ScalarParam(\n'
            '        name="output_floor_pct_full",'
        ),
        summary="Rulepack scalar read only under an election no RUNS portfolio makes",
        rationale=(
            "The reachability PROBE must find this unreachable; the trust check "
            "judges it on the probe, not on the verdict (the banked set ratchet "
            "still judges its verdict). This entry is consumed only when a firm "
            "elects skip_transitional on OutputFloorConfig, which no RUNS portfolio "
            "does. A gate may still catch it, and one does: "
            "tests/unit/rulebook/test_output_floor_features.py makes the election "
            "and calls engine/aggregator/aggregator.py::_output_floor_pct, which "
            "reads this key -- so the path is dead to the probe, not to the test "
            "suite. Mutating it once produced 52/52 passing floor properties, which "
            "read as proof they were vacuous -- they were not, the path was dead to "
            "every portfolio they ran. If the probe calls this reachable, the probe "
            "is broken and every other 'not detected' verdict in the report is "
            "unsafe."
        ),
        expect_unreachable=True,
    ),
    Mutant(
        id="control-reachable-output-floor-schedule",
        category="control",
        target=TARGET_B31_PACK,
        old='(date(2027, 1, 1), Decimal("0.60")),',
        new='(date(2027, 1, 1), Decimal("0.95")),',
        summary="The output-floor schedule step that IS read, raised to 95%",
        rationale=(
            "The reachable twin of the control above. Same article, same pack, "
            "same kind of edit -- but this one is on the live path, so the probe "
            "should find it REACHABLE (reported under expectation_mismatches if "
            "not; the ratchet gates only on an UNREACHABLE verdict). The pair is "
            "what distinguishes 'no gate covers this' from 'nothing ran'.\n\n"
            "The direction is load-bearing and was got wrong first time. The "
            "reporting date (2027-06-01) selects this step, so the entry is "
            "unambiguously live -- but the floor does not BIND on the rich "
            "portfolio at 60%, so LOWERING it to 10% moved nothing and the probe "
            "reported UNREACHABLE. Raising it to 95% forces it to bind. A mutant "
            "on a live path can still be unobservable if it only relaxes a "
            "constraint that was already slack."
        ),
    ),
)


def by_id(mutant_id: str) -> Mutant:
    """Look up one mutant, with a useful error when the id is wrong."""
    for mutant in CATALOGUE:
        if mutant.id == mutant_id:
            return mutant
    raise KeyError(f"unknown mutant {mutant_id!r}; known ids: {[m.id for m in CATALOGUE]}")


def select(ids: list[str] | None = None, categories: list[str] | None = None) -> list[Mutant]:
    """The mutants a run should cover."""
    chosen = list(CATALOGUE)
    if ids:
        chosen = [by_id(mutant_id) for mutant_id in ids]
    if categories:
        wanted = set(categories)
        chosen = [mutant for mutant in chosen if mutant.category in wanted]
    return chosen


def targets() -> frozenset[str]:
    """Every file the harness is permitted to write to."""
    return frozenset(mutant.target for mutant in CATALOGUE)
