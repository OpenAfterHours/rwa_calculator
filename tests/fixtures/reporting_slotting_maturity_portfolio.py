"""
Short-dated slotting legs under both regimes and both Art. 153(5)(d) states — the
C 08.06 / OF 08.06 and Pillar 3 CR10 short-maturity rows.

Pipeline position:
    build_reporting_slotting_maturity_bundle(reporting_date) -> RawDataBundle
        -> PipelineOrchestrator (PermissionMode.IRB; Basel 3.1 with and without the
           slotting short-maturity election) -> AggregatedResultBundle
        -> COREPGenerator (C 08.06 / OF 08.06) and Pillar3Generator (CR10)

Why this portfolio exists (``.claude/LESSONS.md`` B5). Until it was registered no
registered run held a slotting leg with less than 2.5 years to maturity, in either
regime: every slotting leg in ``RUNS`` had ``is_short_maturity`` False. So the
short-maturity rows of C 08.06 / OF 08.06 (0010, 0030, 0050, 0070, 0090, 0110) and
of CR10 (1, 3, 5, 7, 9, 11) were dead estate-wide, and P1.204 — which made the
Basel 3.1 column A / C a firm election (PS1/26 Art. 153(5)(d)) and re-keyed those
rows on the band the leg is weighted in — was invisible to the supervisory
register and both ratchets.

PS1/26 Art. 153(5)(c): an institution "shall" assign column B to 'Strong' and
column D to 'Good'; (d): it "may", "if less than 2.5 years remain until maturity",
assign column A / column C instead. Table A gives 'Satisfactory' one column. UK
CRR Art. 153(5) Table 1's "less than 2,5 years" row is a "shall" for every grade.

## The four legs — two that move, two that must not

All project finance (operational), no provisions, routed to slotting by a
specialised-lending row, a slotting permission and an internal rating with no PD.

    ref               | grade        | maturity | EAD        | CRR / B31 elected | B31 default
    ------------------|--------------|----------|------------|-------------------|------------------
    SLM-LN-STRONG-S   | strong       | 1.5y     | 10,000,000 | 50% row 0010 / 1  | 70% row 0020 / 2
    SLM-LN-GOOD-S     | good         | 1.5y     |  6,000,000 | 70% row 0030 / 3  | 90% row 0040 / 4
    SLM-LN-SAT-S      | satisfactory | 1.5y     |  4,000,000 | 115% row 0050 / 5 | 115% row 0050 / 5
    SLM-LN-STRONG-L   | strong       | 5.0y     |  8,000,000 | 70% row 0020 / 2  | 70% row 0020 / 2

(row = C 08.06 / OF 08.06 row, then CR10 row.)

- ``SLM-LN-STRONG-S`` and ``SLM-LN-GOOD-S`` MOVE with the election: column A / C
  (short rows) when elected and under CRR, column B / D (long rows) by default.
- ``SLM-LN-SAT-S`` must NOT move: Table A has one 'Satisfactory' column, so the
  leg stays on its "< 2.5 years" row in every state, and the Total "< 2.5 years"
  row (0110 / 11) is never empty — a firm without the election still reports it.
- ``SLM-LN-STRONG-L`` must NOT move: it keeps row 0020 / 2 live in every state, so
  a change that EMPTIED the long Strong row is distinguishable from one that moved
  the short Strong leg off it (B5's two-leg pattern).

Hand calculation (RWEA / EL, no provisions):

    state            | STRONG-S          | GOOD-S            | SAT-S             | STRONG-L          | total
    -----------------|-------------------|-------------------|-------------------|-------------------|----------------------
    CRR, B31 elected | 5,000,000 / 0     | 4,200,000 / 24,000| 4,600,000/112,000 | 5,600,000 / 32,000| 19,400,000 / 168,000
    B31 default      | 7,000,000 / 40,000| 5,400,000 / 48,000| 4,600,000/112,000 | 5,600,000 / 32,000| 22,600,000 / 232,000

The Basel 3.1 output floor does not bind in either state: S-TREA 28,000,000 (the
SA-equivalent 100% for operational project finance), x = 60%, OF-ADJ =
-12.5 x EL = -2,900,000 default / -2,100,000 elected, threshold 13,900,000 /
14,700,000 below U-TREA. A non-zero OF-ADJ is what ``boe_b0793`` (publisher issue
PI-25) mis-states, so that rule breaks on both Basel 3.1 runs of this book exactly
as it does on the other IRB books — a register entry to bank, never a figure to
bend.

What it is NOT: an HVCRE, pre-operational or Art. 153(5)(e)/(f) book.

References:
- PRA PS1/26 Art. 153(5)(c)-(d) Table A; Art. 158(6) Table B
- UK CRR Art. 153(5) Table 1; Art. 158(6) Table B
- PRA PS1/26 Annex II OF 08.06 rows 0010-0120; Annex XXIV UKB CR10 column c
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions``, or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

#: The gate's IRB reporting dates (``test_supervisory_validations._irb_config``),
#: and the prior-period dates its C 08.04 opening balance is taken at.
REPORTING_DATE: dict[str, date] = {"CRR": date(2025, 12, 31), "BASEL_3_1": date(2027, 6, 1)}
PRIOR_DATE: dict[str, date] = {"CRR": date(2025, 6, 30), "BASEL_3_1": date(2027, 1, 1)}

#: Months to maturity from the reporting date. 18 months is short at the reporting
#: date AND at the prior date six months earlier (24 months, still < 2.5 years).
_SHORT_MONTHS: int = 18
_LONG_MONTHS: int = 60

LN_STRONG_SHORT: str = "SLM-LN-STRONG-S"
LN_GOOD_SHORT: str = "SLM-LN-GOOD-S"
LN_SAT_SHORT: str = "SLM-LN-SAT-S"
LN_STRONG_LONG: str = "SLM-LN-STRONG-L"

EAD_STRONG_SHORT: float = 10_000_000.0
EAD_GOOD_SHORT: float = 6_000_000.0
EAD_SAT_SHORT: float = 4_000_000.0
EAD_STRONG_LONG: float = 8_000_000.0

#: loan reference -> (slotting grade, months to maturity, drawn amount).
LEGS: dict[str, tuple[str, int, float]] = {
    LN_STRONG_SHORT: ("strong", _SHORT_MONTHS, EAD_STRONG_SHORT),
    LN_GOOD_SHORT: ("good", _SHORT_MONTHS, EAD_GOOD_SHORT),
    LN_SAT_SHORT: ("satisfactory", _SHORT_MONTHS, EAD_SAT_SHORT),
    LN_STRONG_LONG: ("strong", _LONG_MONTHS, EAD_STRONG_LONG),
}

#: The legs the Art. 153(5)(d) election moves between rows.
MOVING_LEGS: tuple[str, ...] = (LN_STRONG_SHORT, LN_GOOD_SHORT)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_slotting_maturity_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the four-leg slotting book as a sealed ``RawDataBundle``.

    Maturities are stated relative to ``reporting_date`` so the short legs are
    short in whichever regime the bundle is run; register each run with
    ``functools.partial`` over its own date. Run it with ``slotting_maturity_config``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(reporting_date),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        specialised_lending=_specialised_lending(),
    )


# ---------------------------------------------------------------------------
# Supporting public functions
# ---------------------------------------------------------------------------


def slotting_maturity_config(framework: str, *, elected: bool = False) -> CalculationConfig:
    """The IRB run config, with or without the PS1/26 Art. 153(5)(d) election.

    Written out rather than cloned from the gate's shared IRB helper: that helper
    passes ``enforce_retail_granularity=False`` for a retail book, and this book
    has no retail obligor, so the production default stands. ``elected`` is a
    Basel 3.1 keyword only — CRR's Table 1 maturity rows are mandatory, so the
    ``crr`` factory takes no such argument and the CRR arm ignores it.
    """
    return _config(framework, REPORTING_DATE[framework], elected=elected)


def slotting_maturity_prior_config(framework: str, *, elected: bool = False) -> CalculationConfig:
    """The same config at the prior reporting date, for C 08.04's opening balance.

    The election is carried into the prior frame: running the opening balance on
    the other column would manufacture a movement no input change caused.
    """
    return _config(framework, PRIOR_DATE[framework], elected=elected)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _config(framework: str, reporting_date: date, *, elected: bool) -> CalculationConfig:
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=reporting_date, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
        slotting_short_maturity_election=elected,
    )


def _counterparty(loan_reference: str) -> str:
    """One obligor per leg: the specialised-lending table is keyed by counterparty."""
    return loan_reference.replace("-LN-", "-CP-")


def _counterparties() -> pl.DataFrame:
    rows = [
        {
            "counterparty_reference": _counterparty(ref),
            "entity_type": "specialised_lending",
            "country_code": "GB",
        }
        for ref in LEGS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal ratings with ``model_id`` and NO PD — the slotting routing pair."""
    rows = [
        {
            "rating_reference": f"SLM-RTG-{ref}",
            "counterparty_reference": _counterparty(ref),
            "rating_type": "internal",
            "model_id": _MODEL_ID,
            "rating_date": date(2024, 12, 31),
        }
        for ref in LEGS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans(reporting_date: date) -> pl.DataFrame:
    rows = [
        {
            "loan_reference": ref,
            "counterparty_reference": _counterparty(ref),
            "product_type": "term_loan",
            "drawn_amount": drawn,
            "currency": "GBP",
            "value_date": date(2024, 12, 31),
            "maturity_date": _add_months(reporting_date, months),
            "seniority": "senior",
        }
        for ref, (_grade, months, drawn) in LEGS.items()
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _specialised_lending() -> pl.DataFrame:
    rows = [
        {
            "counterparty_reference": _counterparty(ref),
            "sl_type": "project_finance",
            "project_phase": "operational",
            "slotting_category": grade,
            "is_hvcre": False,
        }
        for ref, (grade, _months, _drawn) in LEGS.items()
    ]
    return pl.DataFrame(rows)


def _add_months(start: date, months: int) -> date:
    """``start`` plus whole calendar months (day clamped to 28, never past month end)."""
    total = start.month - 1 + months
    return date(start.year + total // 12, total % 12 + 1, min(start.day, 28))
