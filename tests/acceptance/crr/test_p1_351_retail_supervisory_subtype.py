"""P1.351 — the retail purchased-receivable supervisory-LGD population, pinned.

CRR Art. 161(1)(e)/(f) confine the senior/subordinated supervisory LGD rates to
purchased **corporate** receivables (`crr.pdf` p.157), and Art. 164(1) supplies a
retail rate for **dilution risk only**. So a retail A-IRB/F-IRB purchased
receivable carrying subtype ``senior`` or ``subordinated`` with a null LGD sits
outside every supervisory limb — and today takes the corporate rate silently.

**These tests pin TODAY'S behaviour, deliberately.** P1.351's fix is an error
channel signal (IRB009), not a value change, and it is currently BLOCKED on the
branch-census matrix (see the plan bullet). Until it lands, this file is the only
thing in the estate that exercises the ``supervisory_subtype`` dispatch end to
end — `scripts/branch_census_baseline.json` banks that branch as *dead* precisely
because ``purchased_receivables_subtype`` is null in every other fixture.

So this is a **fail-first anchor held in advance**: when IRB009 ships, the
``errors`` assertions below invert for rows 1 and 2 and must stay unchanged for
rows 3, 4 and 5. That asymmetry is the whole guard — a fix that emits on the
dilution row (Art. 164(1) legislates for it) or the corporate row (Art. 161(1)(e)
authorises it) is over-reaching, and nothing else would catch that.

Two measured facts recorded here because they are easy to get backwards:

- Row 1 (``senior``) applies **the same LGD as row 5 (no subtype at all)** —
  0.45. On this F-IRB route the subtype's only observable effect is the audit
  trail, not the number. ``is_firb_cleared`` in ``apply_firb_lgd`` has no subtype
  condition, so any null-LGD F-IRB row clears via the seniority fallback.
- ``UNKNOWN_FALLBACK``/BR001 is therefore **not** reachable on this route, and
  that is **deliberate, not a coverage gap**. ``is_firb_cleared`` fires for any
  F-IRB row with a null LGD, so the ``SUPERVISORY_FIRB`` case is reached before
  the ``otherwise`` clause is ever evaluated — an F-IRB row always has a
  supervisory fallback by construction, i.e. it IS justified (CRR Art. 161(1)(a)).
  ``scripts/branch_census_baseline.json`` banks that limb as desired-dead with the
  note that rows newly landing on it are "a loss of justification". So a fixture
  aimed at it would be **lighting a limb the estate wants dark**. Do not build one
  for this item.

Basel 3.1 is **not covered and cannot be**: Art. 147A blocks retail F-IRB, the
A-IRB gate requires ``has_modelled_lgd`` (which a null-LGD row cannot satisfy),
and the remaining B31 retail limbs are mutually exclusive with an IRB route. CRR
only, and that is a finding rather than an omission.

References:
- CRR Art. 161(1)(e)/(f): senior / subordinated purchased CORPORATE receivables
- CRR Art. 164(1): retail LGD — dilution risk only
- PS1/26 Art. 161(1)(e)/(f), Art. 164(1)(b): the Basel 3.1 equivalents
"""

from __future__ import annotations

import pytest
from tests.fixtures.p1_351.p1_351 import (
    LOAN_REF_CORP_SENIOR,
    LOAN_REF_RETAIL_DILUTION,
    LOAN_REF_RETAIL_NOSUBTYPE,
    LOAN_REF_RETAIL_SENIOR,
    LOAN_REF_RETAIL_SUB,
    REPORTING_DATE,
    create_p1351_counterparty,
    create_p1351_loans,
    create_p1351_model_permissions,
    create_p1351_rating,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator


@pytest.fixture(scope="module")
def p1351_result():
    """Run the P1.351 bundle once under CRR, from the fixture's own frames."""
    bundle = make_raw_bundle(
        counterparties=create_p1351_counterparty(),
        loans=create_p1351_loans(),
        ratings=create_p1351_rating(),
        model_permissions=create_p1351_model_permissions(),
    )
    return PipelineOrchestrator().run_with_data(
        bundle, CalculationConfig.crr(reporting_date=REPORTING_DATE)
    )


@pytest.fixture(scope="module")
def p1351_rows(p1351_result) -> dict[str, dict]:
    """Index the result rows by exposure reference."""
    frame = p1351_result.results.collect()
    return {
        row["exposure_reference"]: row for row in frame.to_dicts() if row.get("exposure_reference")
    }


class TestSupervisorySubtypeReachesTheDispatch:
    """The dispatch is exercised at all — it is banked as dead everywhere else."""

    @pytest.mark.parametrize(
        "ref",
        [
            LOAN_REF_RETAIL_SENIOR,
            LOAN_REF_RETAIL_SUB,
            LOAN_REF_RETAIL_DILUTION,
            LOAN_REF_CORP_SENIOR,
        ],
    )
    def test_subtype_rows_take_the_supervisory_subtype_branch(
        self, p1351_rows: dict[str, dict], ref: str
    ) -> None:
        """Every subtype-bearing row is priced by the Art. 161(1) dispatch."""
        row = p1351_rows[ref]

        assert row["irb_lgd_branch_reason"] == "supervisory_subtype", (
            f"{ref} did not reach the supervisory-subtype dispatch. This fixture is "
            "the only thing in the estate that exercises it — the branch census "
            "banks it as dead because the subtype is null everywhere else."
        )


class TestTodaysLgdValues:
    """Absolute LGD/RWA pins. A fix that changes a VALUE here is out of scope."""

    @pytest.mark.parametrize(
        ("ref", "expected_lgd", "expected_rwa"),
        [
            (LOAN_REF_RETAIL_SENIOR, 0.45, 61_465.63),
            (LOAN_REF_RETAIL_SUB, 1.00, 136_590.29),
            (LOAN_REF_RETAIL_DILUTION, 0.75, 102_442.72),
            (LOAN_REF_CORP_SENIOR, 0.45, 101_516.94),
            (LOAN_REF_RETAIL_NOSUBTYPE, 0.45, 61_465.63),
        ],
    )
    def test_lgd_and_rwa(
        self, p1351_rows: dict[str, dict], ref: str, expected_lgd: float, expected_rwa: float
    ) -> None:
        """P1.351 is an ERROR-CHANNEL item: these numbers must not move."""
        row = p1351_rows[ref]

        assert row["lgd_floored"] == pytest.approx(expected_lgd, abs=1e-9)
        assert row["rwa_final"] == pytest.approx(expected_rwa, abs=0.01)

    def test_senior_subtype_changes_the_reason_but_not_the_number(
        self, p1351_rows: dict[str, dict]
    ) -> None:
        """The sharpest fact in the item, and the easiest to get backwards.

        A retail row with ``senior`` and a retail row with NO subtype take the
        SAME LGD by DIFFERENT routes. So on this F-IRB path the unauthorised
        supervisory rate is not a wrong number — it is an unrecorded one.
        """
        with_subtype = p1351_rows[LOAN_REF_RETAIL_SENIOR]
        without_subtype = p1351_rows[LOAN_REF_RETAIL_NOSUBTYPE]

        assert with_subtype["lgd_floored"] == without_subtype["lgd_floored"]
        assert with_subtype["irb_lgd_branch_reason"] != without_subtype["irb_lgd_branch_reason"]
        assert without_subtype["irb_lgd_branch_reason"] == "supervisory_firb"


class TestErrorChannelIsSilentToday:
    """Pinned so P1.351's fix inverts EXACTLY two of these and no others."""

    def test_no_errors_are_raised_for_any_row(self, p1351_result) -> None:
        """Today the unauthorised retail rows are silent. That IS the defect."""
        assert [e.code for e in p1351_result.errors] == [], (
            "Pre-fix this bundle is error-free. When IRB009 ships, exactly the "
            "senior and subordinated RETAIL rows gain a warning — the dilution row "
            "(Art. 164(1) legislates for it) and the corporate row (Art. 161(1)(e) "
            "authorises it) must stay silent, or the guard is over-reaching."
        )

    def test_every_row_is_emitted(self, p1351_rows: dict[str, dict]) -> None:
        """Negative space: a vanished row is neither a result nor an error."""
        for ref in (
            LOAN_REF_RETAIL_SENIOR,
            LOAN_REF_RETAIL_SUB,
            LOAN_REF_RETAIL_DILUTION,
            LOAN_REF_CORP_SENIOR,
            LOAN_REF_RETAIL_NOSUBTYPE,
        ):
            assert ref in p1351_rows, f"{ref} did not reach the results frame"
            assert p1351_rows[ref]["lgd_floored"] is not None
            assert p1351_rows[ref]["rwa_final"] is not None


class TestClassSplitIsWhatDistinguishes:
    """The retail/corporate split is the whole regulatory point."""

    def test_retail_and_corporate_senior_share_a_rate_but_not_an_authority(
        self, p1351_rows: dict[str, dict]
    ) -> None:
        """Both take 0.45; only the corporate one is authorised to.

        CRR Art. 161(1)(e) says "senior purchased CORPORATE receivables". The
        retail row reaching the same rate is the defect — and because the RATE
        matches, no value-based test can distinguish them. Only the class can.
        """
        retail = p1351_rows[LOAN_REF_RETAIL_SENIOR]
        corporate = p1351_rows[LOAN_REF_CORP_SENIOR]

        assert retail["lgd_floored"] == pytest.approx(corporate["lgd_floored"], abs=1e-9)
        assert retail["exposure_class_irb"] == "retail_other"
        assert corporate["exposure_class_irb"] == "corporate"
