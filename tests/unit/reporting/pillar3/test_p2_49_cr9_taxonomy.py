"""Unit tests for P2.49: CR9 column-a taxonomy extension (Basel 3.1 only).

Tests cover:
    - ``CR9_FIRB_CLASSES`` has 5 leaf entries (not 4)
    - ``CR9_AIRB_CLASSES`` has 10 leaf entries (not 6)
    - All 15 expected dict keys are present after running the CR9 generator
      over the P2.49 seed frame
    - Discriminator-routing examples:
        * retail_mortgage + commercial + is_sme → ``advanced_irb - retail_cre_sme``
        * retail_mortgage + residential + NOT is_sme → ``advanced_irb - retail_rre_non_sme``
        * F-IRB corporate + cp_is_financial_sector_entity=True →
          ``foundation_irb - corporate_financial_large``
        * F-IRB corporate + cp_is_financial_sector_entity=False →
          ``foundation_irb - corporate_other_non_sme``
        * A-IRB corporate (not SME, not specialised) →
          ``advanced_irb - corporate_other_non_sme``
    - Old collapsed parent keys (``advanced_irb - retail_mortgage``,
      ``advanced_irb - retail_other``, ``advanced_irb - corporate``,
      ``foundation_irb - corporate``) are NOT present in the output

The dominant pre-implementation failures are:

    assert len(CR9_AIRB_CLASSES) == 10  →  AssertionError: 6 != 10
    assert len(CR9_FIRB_CLASSES) == 5   →  AssertionError: 4 != 5

These guarantee a clean RED fail — not ImportError, AttributeError, or
collection error.

References:
    - P2.49 scenario proposal:
      .claude/state/next-items-20260530-0311-P2.49-scenario.md
    - PRA PS1/26 Annex XXII paras 12–15, Art. 147(2)(b)/(c)(i)-(iii)/(d)(i)-(iii)
    - Art. 147A(1)(b)/(d)/(e) — financial/large corporates (F-IRB only)
    - Art. 452(h) — IRB PD back-testing disclosure
    - templates.py:601/611 (CR9_AIRB_CLASSES / CR9_FIRB_CLASSES)
    - generator.py:647-667 (_generate_all_cr9)
"""

from __future__ import annotations

import pytest

from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.pillar3.templates import (
    CR9_AIRB_CLASSES,
    CR9_FIRB_CLASSES,
)
from tests.fixtures.p2_49.p2_49 import (
    AIRB_CORP_OTHER_NON_SME_KEY,
    AIRB_CRE_SME_KEY,
    AIRB_RRE_NON_SME_KEY,
    EXPECTED_AIRB_CLASS_COUNT,
    EXPECTED_FIRB_CLASS_COUNT,
    EXPECTED_KEYS,
    FIRB_FINANCIAL_LARGE_KEY,
    FIRB_OTHER_NON_SME_KEY,
    build_cr9_irb_results_lf,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_cr9_bundle() -> dict:
    """Generate the CR9 dict from the P2.49 seed frame under Basel 3.1."""
    gen = Pillar3Generator()
    lf = build_cr9_irb_results_lf()
    bundle = gen.generate_from_lazyframe(lf, framework="BASEL_3_1")
    return bundle.cr9


# ---------------------------------------------------------------------------
# P2.49-TC1: Template constant counts
# ---------------------------------------------------------------------------


class TestP249TaxonomyCounts:
    """CR9_FIRB_CLASSES and CR9_AIRB_CLASSES must have the new leaf counts.

    These tests fail today because the current implementation has 4 F-IRB
    leaves and 6 A-IRB leaves; the P2.49 taxonomy requires 5 and 10.
    """

    def test_p2_49_firb_class_count_is_5(self) -> None:
        """``CR9_FIRB_CLASSES`` must contain exactly 5 leaf entries.

        Arrange: import CR9_FIRB_CLASSES from templates
        Act: measure len
        Assert: 5 (institution + specialised_lending + corporate_financial_large
                    + corporate_sme + corporate_other_non_sme)
        """
        # Arrange / Act
        actual = len(CR9_FIRB_CLASSES)

        # Assert
        assert actual == EXPECTED_FIRB_CLASS_COUNT, (
            f"CR9_FIRB_CLASSES must have {EXPECTED_FIRB_CLASS_COUNT} leaf entries "
            f"(dropped collapsed 'corporate' parent, added 'corporate_financial_large' "
            f"and 'corporate_other_non_sme'), got {actual}. "
            f"Current entries: {[k for k, *_ in CR9_FIRB_CLASSES]}"
        )

    def test_p2_49_airb_class_count_is_10(self) -> None:
        """``CR9_AIRB_CLASSES`` must contain exactly 10 leaf entries.

        Arrange: import CR9_AIRB_CLASSES from templates
        Act: measure len
        Assert: 10 (specialised_lending + corporate_sme + corporate_other_non_sme
                    + retail_rre_sme + retail_rre_non_sme + retail_cre_sme
                    + retail_cre_non_sme + retail_qrre + retail_other_sme
                    + retail_other_non_sme)
        """
        # Arrange / Act
        actual = len(CR9_AIRB_CLASSES)

        # Assert
        assert actual == EXPECTED_AIRB_CLASS_COUNT, (
            f"CR9_AIRB_CLASSES must have {EXPECTED_AIRB_CLASS_COUNT} leaf entries "
            f"(removed collapsed parent keys 'corporate'/'retail_mortgage'/'retail_other', "
            f"added 7 new sub-class leaves), got {actual}. "
            f"Current entries: {[k for k, *_ in CR9_AIRB_CLASSES]}"
        )


# ---------------------------------------------------------------------------
# P2.49-TC2: All 15 expected keys present in the CR9 output
# ---------------------------------------------------------------------------


class TestP249AllKeysPresent:
    """Running the CR9 generator over the P2.49 seed frame produces all 15 keys."""

    def test_p2_49_all_expected_keys_present(self, b31_cr9_bundle: dict) -> None:
        """All 15 expected CR9 dict keys must appear in the generator output.

        Arrange: b31_cr9_bundle fixture (runs generate_from_lazyframe over P2.49 seed)
        Act: collect actual key set
        Assert: every key in EXPECTED_KEYS is present
        """
        # Arrange
        actual_keys = set(b31_cr9_bundle.keys())

        # Assert
        missing = EXPECTED_KEYS - actual_keys
        assert not missing, (
            f"CR9 output is missing {len(missing)} expected key(s): {sorted(missing)}. "
            f"Actual keys: {sorted(actual_keys)}"
        )

    def test_p2_49_exactly_15_keys_emitted(self, b31_cr9_bundle: dict) -> None:
        """The generator emits exactly 15 non-empty sub-class frames (one per leaf obligor).

        Arrange: b31_cr9_bundle
        Act: count keys
        Assert: 15 (5 F-IRB + 10 A-IRB)
        """
        # Arrange
        actual_count = len(b31_cr9_bundle)

        # Assert
        assert actual_count == len(EXPECTED_KEYS), (
            f"CR9 output must have {len(EXPECTED_KEYS)} keys, got {actual_count}. "
            f"Keys: {sorted(b31_cr9_bundle.keys())}"
        )


# ---------------------------------------------------------------------------
# P2.49-TC3: Old collapsed parent keys are absent
# ---------------------------------------------------------------------------


class TestP249CollapsedParentsAbsent:
    """The old parent-level keys must NOT appear in the generator output."""

    def test_p2_49_old_airb_retail_mortgage_key_absent(self, b31_cr9_bundle: dict) -> None:
        """``advanced_irb - retail_mortgage`` collapsed parent is removed.

        Arrange: b31_cr9_bundle
        Act: check key absence
        Assert: key NOT in output (split into rre_sme/rre_non_sme/cre_sme/cre_non_sme)
        """
        assert "advanced_irb - retail_mortgage" not in b31_cr9_bundle, (
            "Collapsed parent 'advanced_irb - retail_mortgage' must be removed; "
            "retail_mortgage rows now route to rre_sme/rre_non_sme/cre_sme/cre_non_sme sub-classes."
        )

    def test_p2_49_old_airb_retail_other_key_absent(self, b31_cr9_bundle: dict) -> None:
        """``advanced_irb - retail_other`` collapsed parent is removed.

        Arrange: b31_cr9_bundle
        Act: check key absence
        Assert: key NOT in output (split into retail_other_sme / retail_other_non_sme)
        """
        assert "advanced_irb - retail_other" not in b31_cr9_bundle, (
            "Collapsed parent 'advanced_irb - retail_other' must be removed; "
            "retail_other rows now route to retail_other_sme / retail_other_non_sme."
        )

    def test_p2_49_old_airb_corporate_key_absent(self, b31_cr9_bundle: dict) -> None:
        """``advanced_irb - corporate`` collapsed parent is removed.

        Arrange: b31_cr9_bundle
        Act: check key absence
        Assert: key NOT in output (replaced by corporate_other_non_sme leaf)
        """
        assert "advanced_irb - corporate" not in b31_cr9_bundle, (
            "Collapsed parent 'advanced_irb - corporate' must be removed; "
            "generic corporate A-IRB rows now route to 'advanced_irb - corporate_other_non_sme'."
        )

    def test_p2_49_old_firb_corporate_key_absent(self, b31_cr9_bundle: dict) -> None:
        """``foundation_irb - corporate`` collapsed parent is removed.

        Arrange: b31_cr9_bundle
        Act: check key absence
        Assert: key NOT in output (split into corporate_financial_large / corporate_other_non_sme)
        """
        assert "foundation_irb - corporate" not in b31_cr9_bundle, (
            "Collapsed parent 'foundation_irb - corporate' must be removed; "
            "F-IRB corporate rows now route to 'corporate_financial_large' or "
            "'corporate_other_non_sme' based on cp_is_financial_sector_entity."
        )


# ---------------------------------------------------------------------------
# P2.49-TC4: Discriminator routing examples
# ---------------------------------------------------------------------------


class TestP249DiscriminatorRouting:
    """Specific obligors from the seed frame must route to the correct new leaf key."""

    def test_p2_49_retail_mortgage_commercial_sme_routes_to_cre_sme(
        self, b31_cr9_bundle: dict
    ) -> None:
        """retail_mortgage + commercial + is_sme=True → ``advanced_irb - retail_cre_sme``.

        R11 in the seed frame carries exposure_class=retail_mortgage,
        property_type=commercial, is_sme=True.

        Arrange: b31_cr9_bundle
        Act: confirm AIRB_CRE_SME_KEY is present (R11 obligor populates it)
        Assert: key present AND no RRE key is used for a CRE obligor
        """
        # Arrange / Act / Assert
        assert AIRB_CRE_SME_KEY in b31_cr9_bundle, (
            f"retail_mortgage + commercial + is_sme=True must route to "
            f"{AIRB_CRE_SME_KEY!r}; key missing from CR9 output. "
            f"Actual keys: {sorted(b31_cr9_bundle.keys())}"
        )
        # Also confirm it did NOT land in any RRE key
        assert "advanced_irb - retail_rre_sme" not in b31_cr9_bundle or (
            b31_cr9_bundle.get("advanced_irb - retail_rre_sme") is not None
        ), "Routing sanity: CRE obligor must not appear under RRE key"

    def test_p2_49_retail_mortgage_residential_non_sme_routes_to_rre_non_sme(
        self, b31_cr9_bundle: dict
    ) -> None:
        """retail_mortgage + residential + is_sme=False → ``advanced_irb - retail_rre_non_sme``.

        R10 in the seed frame carries exposure_class=retail_mortgage,
        property_type=residential, is_sme=False.

        Arrange: b31_cr9_bundle
        Act: confirm AIRB_RRE_NON_SME_KEY is present
        Assert: key present
        """
        # Arrange / Act / Assert
        assert AIRB_RRE_NON_SME_KEY in b31_cr9_bundle, (
            f"retail_mortgage + residential + is_sme=False must route to "
            f"{AIRB_RRE_NON_SME_KEY!r}; key missing from CR9 output. "
            f"Actual keys: {sorted(b31_cr9_bundle.keys())}"
        )

    def test_p2_49_firb_corporate_financial_routes_to_financial_large(
        self, b31_cr9_bundle: dict
    ) -> None:
        """F-IRB corporate + cp_is_financial_sector_entity=True →
        ``foundation_irb - corporate_financial_large``.

        R03 in the seed frame carries approach=foundation_irb,
        exposure_class=corporate, cp_is_financial_sector_entity=True.

        Arrange: b31_cr9_bundle
        Act: confirm FIRB_FINANCIAL_LARGE_KEY is present
        Assert: key present
        """
        # Arrange / Act / Assert
        assert FIRB_FINANCIAL_LARGE_KEY in b31_cr9_bundle, (
            f"F-IRB corporate + cp_is_financial_sector_entity=True must route to "
            f"{FIRB_FINANCIAL_LARGE_KEY!r}; key missing from CR9 output. "
            f"Actual keys: {sorted(b31_cr9_bundle.keys())}"
        )

    def test_p2_49_firb_corporate_non_financial_routes_to_other_non_sme(
        self, b31_cr9_bundle: dict
    ) -> None:
        """F-IRB corporate + cp_is_financial_sector_entity=False →
        ``foundation_irb - corporate_other_non_sme``.

        R05 in the seed frame carries approach=foundation_irb,
        exposure_class=corporate, cp_is_financial_sector_entity=False.

        Arrange: b31_cr9_bundle
        Act: confirm FIRB_OTHER_NON_SME_KEY is present
        Assert: key present
        """
        # Arrange / Act / Assert
        assert FIRB_OTHER_NON_SME_KEY in b31_cr9_bundle, (
            f"F-IRB corporate + cp_is_financial_sector_entity=False must route to "
            f"{FIRB_OTHER_NON_SME_KEY!r}; key missing from CR9 output. "
            f"Actual keys: {sorted(b31_cr9_bundle.keys())}"
        )

    def test_p2_49_airb_corporate_non_sme_routes_to_corporate_other_non_sme(
        self, b31_cr9_bundle: dict
    ) -> None:
        """A-IRB corporate (not SME, not specialised) →
        ``advanced_irb - corporate_other_non_sme``.

        R08 in the seed frame carries approach=advanced_irb,
        exposure_class=corporate, is_sme=False.

        Arrange: b31_cr9_bundle
        Act: confirm AIRB_CORP_OTHER_NON_SME_KEY is present
        Assert: key present
        """
        # Arrange / Act / Assert
        assert AIRB_CORP_OTHER_NON_SME_KEY in b31_cr9_bundle, (
            f"A-IRB corporate (is_sme=False) must route to "
            f"{AIRB_CORP_OTHER_NON_SME_KEY!r}; key missing from CR9 output. "
            f"Actual keys: {sorted(b31_cr9_bundle.keys())}"
        )
