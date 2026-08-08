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
  only read under an election nothing exercises. It MUST come back UNREACHABLE.
  If the scorecard reports it as an escape, the reachability probe is broken and
  every other "not detected" verdict is suspect. This is not hypothetical: the
  same mutation once produced 52/52 passing floor properties, which read as
  proof the properties were vacuous. They were not; the path was dead.
- ``control-reachable-output-floor-schedule`` mutates the step that IS read, so
  the pair distinguishes "no gate covers this" from "nothing ran".

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
        old='irb_class_rwa.get(("advanced_irb", "institution"), 0.0)',
        new='irb_class_rwa.get(("advanced_irb", "institutions"), 0.0)',
        summary="C 02.00 row 0330 keyed on a class string no enum member produces",
        rationale=(
            "The live defect at the sibling line asks for 'central_government' "
            "where the enum says 'central_govt_central_bank', which pins row 0310 "
            "to zero for the template's whole life. This is the same shape on the "
            "correct institution lookup: the row silently zeroes while the "
            "independently-computed approach total still counts the RWEA, so the "
            "template stays internally plausible. LESSONS B2."
        ),
    ),
    Mutant(
        id="known-c02-stranded-subclass",
        category="known_defect",
        target=TARGET_C02,
        old='row_values["0340"] = {"0010": airb_corp + airb_sl_excl}',
        new='row_values["0340"] = {"0010": airb_corp}',
        summary="C 02.00 row 0340 drops the specialised-lending limb",
        rationale=(
            "Mirrors the live defect where the A-IRB corporate lookups never ask "
            "for corporate_sme, stranding 13,606,784.12 on the rich portfolio. "
            "RWEA falls out of the breakdown while the parent total still counts "
            "it. LESSONS B6 -- and note the missing pair is by definition not in "
            "the row list, so reading the list cannot find it."
        ),
    ),
    Mutant(
        id="known-p3-empty-class-tuple",
        category="known_defect",
        target="src/rwa_calc/reporting/pillar3/templates.py",
        old='("15", "Equity", ("equity",)),',
        new='("15", "Equity", ()),',
        summary="A Pillar 3 SA disclosure row bound to no exposure class",
        rationale=(
            "SA_DISCLOSURE_CLASSES row 11 (high_risk) is bound to an empty tuple "
            "today, so the row can never populate. Same shape on a row that "
            "currently works: the sheet is emitted, the row is present, and it "
            "reports nothing."
        ),
    ),
    Mutant(
        id="known-sovereign-ladder-flattened",
        category="known_defect",
        target="src/rwa_calc/engine/sa/rgla.py",
        old='has_sovereign_cqs = pl.col("cp_sovereign_cqs").is_not_null() & (pl.col("cp_sovereign_cqs") > 0)',
        new="has_sovereign_cqs = pl.lit(False)",
        summary="RGLA sovereign-derived ladder flattened to its fallback",
        rationale=(
            "The live Art. 121(1) Table 5 defect is exactly this on the "
            "institution class: the sovereign CQS is never read, so every "
            "unrated exposure takes the flat fallback -- conservative at CQS 1-2 "
            "and ANTI-conservative at CQS 6. RGLA implements the same ladder "
            "correctly, so flattening it reproduces the defect on a covered path."
        ),
    ),
    # =========================================================================
    # LESSONS traps in mechanical form
    # =========================================================================
    Mutant(
        id="lessons-b1-dead-carrier",
        category="lessons",
        target="src/rwa_calc/reporting/corep/c07.py",
        old='_CCF_CARRIERS: tuple[str, ...] = ("ccf", "ccf_applied")',
        new='_CCF_CARRIERS: tuple[str, ...] = ("ccf_applied",)',
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
        old='return sum((cells.get(ref) or 0.0) for ref in ("0050", "0060", "0070", "0080"))',
        new='return sum((cells.get(ref) or 0.0) for ref in ("0040", "0050", "0060", "0070", "0080"))',
        summary="C 07.00 subtotal counts a breakdown column and its parent",
        rationale=(
            "LESSONS E3: subtracting the breakdown AND the subtotal double-counts. "
            "Inflow and outflow must bind the same capped magnitude; reading the "
            "raw carrier on one side and the capped twin on the other CREATES "
            "exposure."
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
        old="r_corporate = 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)",
        new="r_corporate = 0.14 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)",
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
        old="corporate_denom = 1.0 - math.exp(-50.0)",
        new="corporate_denom = 1.0 - math.exp(-45.0)",
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
        old='beneficial_rw = pl.min_horizontal(blended_rw, pl.col("risk_weight"))',
        new='beneficial_rw = pl.max_horizontal(blended_rw, pl.col("risk_weight"))',
        summary="CRM benefit cap inverted from min to max",
        rationale=(
            "LESSONS D1 territory: these adjustments are benefit-only capped, and "
            "the SA pipe runs unconditionally to feed the Basel 3.1 output floor. "
            "Inverting the cap moves the floor wherever it binds."
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
        old='    "institution_rw_b31_ecra": LookupTable(\n        name="institution_rw_b31_ecra",',
        new='    "institution_rw_b31_ecra": LookupTable(\n        name="institution_rw_b31_ecra_MUTANT",',
        summary="Basel 3.1 institution ECRA table renamed so its lookup misses",
        rationale=(
            "PS1/26 Art. 120(1) Table 3 gives CQS 2 a 30% weight where CRR gives "
            "50%. A rename breaks the binding rather than the value, which is the "
            "shape a refactor produces."
        ),
    ),
    Mutant(
        id="generic-corporate-correlation-high",
        category="generic",
        target=TARGET_IRB_FORMULAS,
        old="r_corporate = 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)",
        new="r_corporate = 0.12 * f_pd_corp + 0.22 * (1.0 - f_pd_corp)",
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
        target=TARGET_IRB_FORMULAS,
        old="scaling = 1.06 if apply_scaling_factor else 1.0",
        new="scaling = 1.0 if apply_scaling_factor else 1.06",
        summary="IRB scaling factor applied to the wrong regime",
        rationale=(
            "CRR keeps the 1.06 factor and PS1/26 Art. 153(1)(c) removes it. "
            "Inverting the branch leaves both regimes internally consistent and "
            "moves every IRB risk weight in both -- a regime mix-up of exactly "
            "the kind a dual-framework codebase invites."
        ),
    ),
    Mutant(
        id="generic-firb-institution-key",
        category="generic",
        target=TARGET_C02,
        old='firb_inst = irb_class_rwa.get(("foundation_irb", "institution"), 0.0)',
        new='firb_inst = irb_class_rwa.get(("foundation_irb", "institutions"), 0.0)',
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
        old='firb_sl = irb_class_rwa.get(("foundation_irb", "specialised_lending"), 0.0)',
        new="firb_sl = 0.0",
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
        summary="Rulepack scalar read only under an election nothing exercises",
        rationale=(
            "MUST come back UNREACHABLE. This entry is consumed only when a firm "
            "elects skip_transitional on OutputFloorConfig, which no test does. "
            "Mutating it once produced 52/52 passing floor properties, which read "
            "as proof they were vacuous -- they were not, the path was dead. If "
            "the scorecard calls this an escape, the probe is broken and every "
            "other 'not detected' verdict in the report is unsafe."
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
            "same kind of edit -- but this one is on the live path, so it must be "
            "REACHABLE. The pair is what distinguishes 'no gate covers this' from "
            "'nothing ran'.\n\n"
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
