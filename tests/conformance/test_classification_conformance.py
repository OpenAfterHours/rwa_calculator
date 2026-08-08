"""
C4a — the classifier against an externally-authored decision table.

Pipeline position:
    classification_table.toml + portfolios.combinations
        -> classifier stage exit -> these assertions

Key responsibilities:
- Assert the classifier reproduces the table on EVERY generated combination of
  the discriminating input space, for all four classification outputs.
- Treat a combination with no verdict in the table as a HARD FAILURE. That is
  what turns "we test what we thought of" into "we test the space".
- Assert the emitted class values stay inside the codomains the exposure-class
  articles define — CRR Art. 112 for the SA carrier, CRR/PS1/26 Art. 147(2) for
  the IRB one.
- Carry each believed engine defect as a named strict xfail stating the
  regulation, both figures and which side is thought wrong. A disagreement is
  the product; tuning the table to agree would destroy the component.

Cost control: the classifier prefix runs ONCE per regime (memoised in
``portfolios.classified``) over a portfolio of one obligor per combination, and
every assertion below reads that one frame.

References:
- CRR Art. 112, Art. 147; PS1/26 Art. 147, Art. 147A
- docs/plans/independent-validation-system.md §C4a
"""

from __future__ import annotations

import logging

import pytest

from tests.conformance import portfolios
from tests.conformance.table import FIELDS, UNSOURCED, load_table

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Codomains — the exposure classes each framework's own enumeration admits.
# Written out from the article text, then compared against the ExposureClass
# member set so a renamed member cannot silently empty either codomain.
# ---------------------------------------------------------------------------

#: CRR Art. 112(1)(a)-(q), as represented by this codebase's class values.
#: (m) securitisation positions and (n)/(o) short-term/CIU have no member.
SA_CODOMAIN: frozenset[str] = frozenset(
    {
        "central_govt_central_bank",  # (a)
        "rgla",  # (b)
        "pse",  # (c)
        "mdb",  # (d)
        "international_organisation",  # (e)
        "institution",  # (f)
        "corporate",  # (g)
        "retail_other",  # (h)
        "retail_mortgage",  # (i)
        "residential_mortgage",  # (i)
        "commercial_mortgage",  # (i)
        "defaulted",  # (j)
        "high_risk",  # (k)
        "covered_bond",  # (l)
        "equity",  # (p)
        "other",  # (q)
    }
)

#: CRR Art. 147(2)(a)-(g) and PS1/26 Art. 147(2), including the PS1/26
#: subclasses (c)(i)-(iii) and (d)(i)-(iii) that this codebase represents as
#: distinct class values.
IRB_CODOMAIN: frozenset[str] = frozenset(
    {
        "central_govt_central_bank",  # (a)
        "institution",  # (b)
        "corporate",  # (c)
        "corporate_sme",  # (c)(iii) SME split
        "specialised_lending",  # (c)(i) / CRR Art. 147(8)
        "retail_other",  # (d) / (d)(iii)
        "retail_qrre",  # (d)(i) / CRR Art. 154(4)
        "retail_mortgage",  # (d)(ii)
        "equity",  # (e)
        "other",  # (g)
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def table():
    """The parsed decision table (validated on load)."""
    return load_table()


@pytest.fixture(scope="module")
def observed() -> dict[str, dict[str, dict[str, str]]]:
    """regime -> combination key -> observed classification outputs.

    Module-scoped: two classifier runs for the whole file.
    """
    return {
        regime: portfolios.verdicts(regime, portfolios.combinations(regime))
        for regime in portfolios.REGIMES
    }


def _in_scope(table, regime: str):
    """Every generated combination the table does not exclude."""
    return [c for c in portfolios.combinations(regime) if table.is_excluded(c) is None]


# ---------------------------------------------------------------------------
# Coverage of the space
# ---------------------------------------------------------------------------


def test_every_generated_combination_reaches_the_classifier(observed) -> None:
    """Every generated combination produces exactly one classified drawn leg.

    Arrange: the space, per regime.
    Act: read the memoised classifier-exit verdicts.
    Assert: no combination is missing. A combination the pipeline silently drops
    would otherwise make every downstream assertion vacuous for that point.
    """
    for regime in portfolios.REGIMES:
        combos = portfolios.combinations(regime)
        missing = [c.key for c in combos if c.key not in observed[regime]]
        assert not missing, f"{regime}: {len(missing)} combination(s) reached no classified row"


@pytest.mark.parametrize("field_name", FIELDS)
def test_no_combination_is_without_a_verdict(table, field_name: str) -> None:
    """A combination with no matching rule is a hard failure, not a default.

    Arrange: the in-scope space (declared exclusions removed).
    Act: resolve the field's rule list for every combination.
    Assert: every one matches a rule. This is the assertion that stops the table
    from silently covering only what its author happened to think of.
    """
    unverdicted = [
        c.key
        for regime in portfolios.REGIMES
        for c in _in_scope(table, regime)
        if table.resolve(c, field_name) is None
    ]
    assert not unverdicted, (
        f"{len(unverdicted)} combination(s) have no {field_name} verdict in "
        f"classification_table.toml: {unverdicted[:12]}"
    )


def test_no_rule_or_exclusion_is_dead(table) -> None:
    """Every authored rule and exclusion is reached by the generated space.

    A rule nothing matches is either a mis-authored condition or a shrunk input
    space; both are gaps, and both must be visible rather than looking like
    coverage.
    """
    space = [c for regime in portfolios.REGIMES for c in portfolios.combinations(regime)]
    coverage = table.coverage(space)
    logger.info("C4a coverage: %s", coverage.as_report())
    assert not coverage.dead_rules, f"rules never matched: {coverage.dead_rules}"
    assert not coverage.dead_exclusions, f"exclusions never matched: {coverage.dead_exclusions}"


def test_coverage_is_reported_and_non_trivial(table) -> None:
    """The coverage numbers exist, are reported, and describe a real space.

    The thresholds are floors on the SHAPE of the space, not targets: they fail
    if the space collapses (a builder change that stops generating, an exclusion
    that swallows everything), which would otherwise turn the whole file green
    and meaningless.
    """
    space = [c for regime in portfolios.REGIMES for c in portfolios.combinations(regime)]
    coverage = table.coverage(space)
    logger.info("C4a coverage: %s", coverage.as_report())
    assert coverage.generated >= 600, coverage.as_report()
    assert coverage.excluded > 0, coverage.as_report()
    assert coverage.asserted >= 2000, coverage.as_report()


# ---------------------------------------------------------------------------
# The conformance assertion itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field_name", FIELDS)
def test_engine_matches_the_table(table, observed, field_name: str) -> None:
    """The classifier reproduces the table everywhere it is not known to differ.

    Arrange: the in-scope space and the memoised classifier outputs.
    Act: compare the observed value against the table's verdict, skipping only
    the fields the table declares ``unsourced``.
    Assert: the set of mismatches is EXACTLY the set the known-disagreement
    register predicts — no new divergence, and no silently-fixed one either. A
    disagreement that gets fixed turns this red, which is deliberate: the
    register entry must then be removed by hand.
    """
    unexpected: list[str] = []
    unfired: list[str] = []
    for regime in portfolios.REGIMES:
        for combo in _in_scope(table, regime):
            rule = table.resolve(combo, field_name)
            assert rule is not None, combo.key
            if rule.verdict == UNSOURCED:
                continue
            actual = observed[regime][combo.key][field_name]
            predicted = table.disagreement_for(combo, field_name)
            if actual == rule.verdict and predicted is not None:
                unfired.append(f"{combo.key} [{predicted.id}]")
            elif actual != rule.verdict and predicted is None:
                unexpected.append(
                    f"{combo.key}: expected {rule.verdict!r} got {actual!r} ({rule.id})"
                )

    assert not unexpected, (
        f"{len(unexpected)} unrecorded {field_name} disagreement(s) with "
        f"classification_table.toml:\n  " + "\n  ".join(unexpected[:20])
    )
    assert not unfired, (
        f"{len(unfired)} recorded {field_name} disagreement(s) no longer fire — if the "
        f"engine was fixed, delete the register entry:\n  " + "\n  ".join(unfired[:20])
    )


# ---------------------------------------------------------------------------
# Codomain — the emitted values must be exposure classes the articles define
# ---------------------------------------------------------------------------


def test_sa_class_stays_inside_the_article_112_codomain(observed) -> None:
    """Every ``exposure_class_sa`` value is a CRR Art. 112(1) exposure class."""
    emitted = {
        row["exposure_class_sa"]
        for regime in portfolios.REGIMES
        for row in observed[regime].values()
    }
    assert emitted <= SA_CODOMAIN, f"not Art. 112 classes: {sorted(emitted - SA_CODOMAIN)}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CRR Art. 147(2) / PS1/26 Art. 147(2) enumerate the IRB exposure classes, and neither "
        "admits a covered-bond, high-risk, MDB or international-organisation class. The "
        "classifier emits all four as exposure_class_irb: entity_type_to_irb_class derives the "
        "correct Art. 147(3) central-government class for mdb_named / international_org, and "
        "sync_irb_exposure_class then overwrites it with the Standardised class, while "
        "covered_bond and high_risk are Standardised-only concepts (Art. 112(1)(l), (k)) with "
        "no Art. 147(2) counterpart at all. The residual limb — CRR Art. 147(7) / PS1/26 "
        "Art. 147(4A) — assigns any such credit obligation to the corporate class. Consequence: "
        "the model-permission lookup keys on exposure_class_irb, so no permission can match "
        "these rows and they are forced Standardised however complete the firm's IRB "
        "permission. The engine is believed wrong; see known_disagreement D3 and D5."
    ),
)
def test_irb_class_stays_inside_the_article_147_codomain(observed) -> None:
    """Every ``exposure_class_irb`` value is a CRR/PS1/26 Art. 147(2) exposure class."""
    emitted = {
        row["exposure_class_irb"]
        for regime in portfolios.REGIMES
        for row in observed[regime].values()
    }
    assert emitted <= IRB_CODOMAIN, f"not Art. 147(2) classes: {sorted(emitted - IRB_CODOMAIN)}"


# ---------------------------------------------------------------------------
# Known disagreements — one named strict xfail each
# ---------------------------------------------------------------------------


def _disagreement_ids() -> list[str]:
    return [d.id for d in load_table().disagreements]


@pytest.mark.parametrize("disagreement_id", _disagreement_ids())
def test_known_disagreement(table, observed, disagreement_id: str, request) -> None:
    """The table's verdict for one recorded disagreement — expected to FAIL.

    Each is marked ``xfail(strict=True)`` from the register's own text, so the
    regulation and both figures live next to the assertion, and fixing the
    engine turns the suite red until the register entry is removed deliberately.
    """
    disagreement = next(d for d in table.disagreements if d.id == disagreement_id)
    request.node.add_marker(
        pytest.mark.xfail(
            strict=True,
            reason=(
                f"{disagreement.id}: {disagreement.citation} requires "
                f"{disagreement.field}={disagreement.expected!r}; the engine produces "
                f"{disagreement.observed!r}. The engine is believed wrong. "
                f"{' '.join(disagreement.detail.split())}"
            ),
        )
    )
    mismatched: list[str] = []
    for regime in portfolios.REGIMES:
        for combo in _in_scope(table, regime):
            if not disagreement.matches(combo.as_dict()):
                continue
            rule = table.resolve(combo, disagreement.field)
            assert rule is not None, combo.key
            actual = observed[regime][combo.key][disagreement.field]
            if actual != rule.verdict:
                mismatched.append(f"{combo.key}: expected {rule.verdict!r} got {actual!r}")
    assert not mismatched, (
        f"{disagreement.id}: {len(mismatched)} combination(s) contradict "
        f"{disagreement.citation}:\n  " + "\n  ".join(mismatched[:10])
    )
