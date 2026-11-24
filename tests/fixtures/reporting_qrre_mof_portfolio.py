"""
QRRE multi-option-facility reporting portfolio (P1.355; the P5.54 shape).

Pipeline position:
    build_reporting_qrre_mof_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator (C 08.01 / OF 08.01, C 02.00)

Key responsibilities:
- Put qualifying revolving retail (QRRE) under MULTI-OPTION facilities (an
  umbrella root with committed sub-lines) inside the registered reporting estate,
  so the supervisory register, the goldens and the coverage ratchets can see the
  CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) per-individual aggregate move
  (LESSONS B5). Before this book the estate's only QRRE leg
  (``reporting_irb_classes_portfolio``) was a single facility drawn to its limit:
  no headroom leg and no umbrella, so neither the P1.320 leg-multiplication fix
  nor the P1.355 umbrella cap could change any reported cell.
- Be two-legged on BOTH IRB retail sheets, so a change that zeroed a sheet is
  distinguishable from one that moved a row between them.

Retail obligors — all natural persons managed as retail, internally rated,
own-estimate LGD, so every retail leg is A-IRB (CRR Art. 154(3)-(4) / PS1/26 Art. 147(5A) are
A-IRB-only). Every facility is revolving, unsecured, committed and
unconditionally cancellable (``risk_type`` ``LR``), so only the (c) limb — the
per-individual aggregate nominal — decides QRRE:

    obligor        facilities                                  aggregate (HEAD -> fix)
    -------------  ------------------------------------------  -----------------------
    MOVER          root 80,000; subs 60,000 + 60,000; 40,000    120,000 -> 80,000
                   drawn under each (fully drawn umbrella: no   retail_other -> QRRE
                   root-keyed leg)
    HEADROOM       root 50,000; subs 30,000 + 30,000; 10,000    80,000 -> 50,000
                   drawn under sub A; the two root-keyed        QRRE both sides
                   waterfall legs carry the 40,000 headroom     (the QRRE sheet's
                                                                live-cell control)
    SHARED_A /     root 80,000 (A); sub A 60,000 (A), sub B     110,000 each, both sides
    SHARED_B       60,000 (B), 40,000 drawn under each; each    retail_other both sides
                   also holds a standalone 50,000 revolver,     (the retail-other
                   10,000 drawn                                 sheet's control)

Plus one F-IRB anchor: ``CORP``, a large (non-SME) corporate with an internal PD
and no own LGD, one drawn term loan. It is not part of the QRRE question. It is
there so the Basel 3.1 return files the OF 08.01 FIRB-and-slotting Total (sheet
0002) beside the A-IRB one: on an A-IRB-only book that sheet is not emitted, and
``boe_b1041`` (ERROR) — which demands a slotting-row (0080) fact on sheet 0002 or
0010 from every OF 08.01 filer, publisher issue PI-06 — breaks. That break is a
filing-posture question for its own item, not something a QRRE coverage book
should bank (measured: the A-IRB-only variant of this book adds exactly that one
gateway break). Its PD keeps its F-IRB risk weight below 100% in both regimes,
so it does not add this book to ``boe_b0908`` ("exposure value should be at least
RWEA", publisher issue PI-27) either.

``HEADROOM`` also exhibits P1.320's grain: counted once per leg its aggregate
would be 30,000 + 50,000 + 50,000 = 130,000 and it would leave QRRE.
``SHARED_A`` / ``SHARED_B`` exhibit the per-individual half of the P1.355 key: a
cap pooled across the umbrella's two owners credits 80,000 to one and 0 to the
other, whose figure falls to 50,000 and leaves the retail-other sheet.

QRRE ceiling — never typed here (LESSONS A4); read with
``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)``:
CRR EUR 100,000 at the run's EUR/GBP rate, Basel 3.1 GBP 90,000. The acceptance
test asserts each obligor's figures straddle it as designed.

References:
- CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c): the per-individual aggregate.
- tests/fixtures/p1_355/p1_355.py: the unit-level legs this book reuses
  (NRL, BULLET, SHARED).
- tests/acceptance/reporting/test_qrre_mof_portfolio.py: the reporting
  assertions.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions``, or no row routes IRB.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_MOVER: str = "QMOF-CP-MOVER"
CP_HEADROOM: str = "QMOF-CP-HEADROOM"
CP_SHARED_A: str = "QMOF-CP-SHARED-A"
CP_SHARED_B: str = "QMOF-CP-SHARED-B"
CP_CORP: str = "QMOF-CP-CORP"

FAC_MOVER_ROOT: str = "QMOF-FAC-MOVER-ROOT"
FAC_MOVER_SUBA: str = "QMOF-FAC-MOVER-SUBA"
FAC_MOVER_SUBB: str = "QMOF-FAC-MOVER-SUBB"
FAC_HEADROOM_ROOT: str = "QMOF-FAC-HEADROOM-ROOT"
FAC_HEADROOM_SUBA: str = "QMOF-FAC-HEADROOM-SUBA"
FAC_HEADROOM_SUBB: str = "QMOF-FAC-HEADROOM-SUBB"
FAC_SHARED_ROOT: str = "QMOF-FAC-SHARED-ROOT"
FAC_SHARED_SUBA: str = "QMOF-FAC-SHARED-SUBA"
FAC_SHARED_SUBB: str = "QMOF-FAC-SHARED-SUBB"
FAC_SHARED_OWN_A: str = "QMOF-FAC-SHARED-OWN-A"
FAC_SHARED_OWN_B: str = "QMOF-FAC-SHARED-OWN-B"

LN_MOVER_A: str = "QMOF-LN-MOVER-A"
LN_MOVER_B: str = "QMOF-LN-MOVER-B"
LN_HEADROOM: str = "QMOF-LN-HEADROOM"
LN_SHARED_A: str = "QMOF-LN-SHARED-A"
LN_SHARED_B: str = "QMOF-LN-SHARED-B"
LN_SHARED_OWN_A: str = "QMOF-LN-SHARED-OWN-A"
LN_SHARED_OWN_B: str = "QMOF-LN-SHARED-OWN-B"
LN_CORP: str = "QMOF-LN-CORP"

#: The hierarchy's headroom legs, spelled from its naming rule: an MOF root's
#: waterfall leg per sub-line, a standalone facility's single undrawn leg.
EXP_HEADROOM_SUBA_UNDRAWN: str = FAC_HEADROOM_ROOT + "_UNDRAWN_" + FAC_HEADROOM_SUBA
EXP_HEADROOM_SUBB_UNDRAWN: str = FAC_HEADROOM_ROOT + "_UNDRAWN_" + FAC_HEADROOM_SUBB
EXP_SHARED_OWN_A_UNDRAWN: str = FAC_SHARED_OWN_A + "_UNDRAWN"
EXP_SHARED_OWN_B_UNDRAWN: str = FAC_SHARED_OWN_B + "_UNDRAWN"

# Monetary inputs (GBP) — fixture inputs, not regulatory values.
MOVER_ROOT_LIMIT: float = 80_000.0
MOVER_SUB_LIMIT: float = 60_000.0
MOVER_DRAWN: float = 40_000.0  # per sub; 2 x 40,000 == the root -> no root leg

HEADROOM_ROOT_LIMIT: float = 50_000.0
HEADROOM_SUB_LIMIT: float = 30_000.0
HEADROOM_DRAWN: float = 10_000.0  # under sub A only

SHARED_ROOT_LIMIT: float = 80_000.0
SHARED_SUB_LIMIT: float = 60_000.0
SHARED_DRAWN: float = 40_000.0  # per sub; 2 x 40,000 == the root -> no root leg
SHARED_OWN_LIMIT: float = 50_000.0
SHARED_OWN_DRAWN: float = 10_000.0

#: The F-IRB anchor: a large corporate's drawn term loan, above the SME ceiling.
CORP_DRAWN: float = 500_000.0
CORP_ANNUAL_REVENUE: float = 400_000_000.0
PD_CORP: float = 0.003

#: One obligor grade for the whole book, so the class move is the only
#: difference between the retail sheets' cells (no PD-band confound).
PD_RETAIL: float = 0.02
#: Own-estimate LGD on every facility and loan (above both regimes' retail
#: unsecured input floors, so no floor binds and moves a cell on its own).
LGD_RETAIL: float = 0.60

#: The legs that move from the retail-other to the QRRE sheet under P1.355.
MOVERS: tuple[str, ...] = (LN_MOVER_A, LN_MOVER_B)
#: Legs on the QRRE sheet on both sides of the change.
QRRE_SURVIVORS: tuple[str, ...] = (
    LN_HEADROOM,
    EXP_HEADROOM_SUBA_UNDRAWN,
    EXP_HEADROOM_SUBB_UNDRAWN,
)
#: Legs on the retail-other sheet on both sides of the change.
OTHER_SURVIVORS: tuple[str, ...] = (
    LN_SHARED_A,
    LN_SHARED_B,
    LN_SHARED_OWN_A,
    LN_SHARED_OWN_B,
    EXP_SHARED_OWN_A_UNDRAWN,
    EXP_SHARED_OWN_B_UNDRAWN,
)

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_qrre_mof_bundle() -> RawDataBundle:
    """Assemble the QRRE multi-option-facility portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``. Run it with
    ``PermissionMode.IRB``: every obligor carries an internal PD and the matching
    ``model_permissions`` row, and every facility and loan an own-estimate LGD
    attested by ``has_sufficient_collateral_data``, which is what routes retail
    A-IRB.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        facilities=_facilities(),
        loans=_loans(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    corporate = {
        "counterparty_reference": CP_CORP,
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": CORP_ANNUAL_REVENUE,
    }
    rows = [
        {
            "counterparty_reference": ref,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
            # Earns in the loans' currency: no Art. 123B currency-mismatch
            # fallback and no SA010 data-quality finding on the Basel 3.1 run.
            "borrower_income_currency": "GBP",
        }
        for ref in (CP_MOVER, CP_HEADROOM, CP_SHARED_A, CP_SHARED_B)
    ]
    return pl.DataFrame([*rows, corporate], schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    pds = {
        CP_MOVER: PD_RETAIL,
        CP_HEADROOM: PD_RETAIL,
        CP_SHARED_A: PD_RETAIL,
        CP_SHARED_B: PD_RETAIL,
        CP_CORP: PD_CORP,
    }
    rows = [
        {
            "rating_reference": f"QMOF-RTG-{ref}",
            "counterparty_reference": ref,
            "rating_type": "internal",
            "pd": pd_value,
            "model_id": _MODEL_ID,
            "rating_date": _VALUE_DATE,
        }
        for ref, pd_value in pds.items()
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _facilities() -> pl.DataFrame:
    rows = [
        _facility(FAC_MOVER_ROOT, CP_MOVER, MOVER_ROOT_LIMIT),
        _facility(FAC_MOVER_SUBA, CP_MOVER, MOVER_SUB_LIMIT),
        _facility(FAC_MOVER_SUBB, CP_MOVER, MOVER_SUB_LIMIT),
        _facility(FAC_HEADROOM_ROOT, CP_HEADROOM, HEADROOM_ROOT_LIMIT),
        _facility(FAC_HEADROOM_SUBA, CP_HEADROOM, HEADROOM_SUB_LIMIT),
        _facility(FAC_HEADROOM_SUBB, CP_HEADROOM, HEADROOM_SUB_LIMIT),
        _facility(FAC_SHARED_ROOT, CP_SHARED_A, SHARED_ROOT_LIMIT),
        _facility(FAC_SHARED_SUBA, CP_SHARED_A, SHARED_SUB_LIMIT),
        _facility(FAC_SHARED_SUBB, CP_SHARED_B, SHARED_SUB_LIMIT),
        _facility(FAC_SHARED_OWN_A, CP_SHARED_A, SHARED_OWN_LIMIT),
        _facility(FAC_SHARED_OWN_B, CP_SHARED_B, SHARED_OWN_LIMIT),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _loans() -> pl.DataFrame:
    rows = [
        _loan(LN_MOVER_A, CP_MOVER, MOVER_DRAWN),
        _loan(LN_MOVER_B, CP_MOVER, MOVER_DRAWN),
        _loan(LN_HEADROOM, CP_HEADROOM, HEADROOM_DRAWN),
        _loan(LN_SHARED_A, CP_SHARED_A, SHARED_DRAWN),
        _loan(LN_SHARED_B, CP_SHARED_B, SHARED_DRAWN),
        _loan(LN_SHARED_OWN_A, CP_SHARED_A, SHARED_OWN_DRAWN),
        _loan(LN_SHARED_OWN_B, CP_SHARED_B, SHARED_OWN_DRAWN),
        # The F-IRB anchor: no own LGD, so it takes the Art. 161 supervisory LGD.
        {
            "loan_reference": LN_CORP,
            "counterparty_reference": CP_CORP,
            "product_type": "term_loan",
            "drawn_amount": CORP_DRAWN,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "seniority": "senior",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    pairs = [
        (FAC_MOVER_ROOT, FAC_MOVER_SUBA, "facility"),
        (FAC_MOVER_ROOT, FAC_MOVER_SUBB, "facility"),
        (FAC_MOVER_SUBA, LN_MOVER_A, "loan"),
        (FAC_MOVER_SUBB, LN_MOVER_B, "loan"),
        (FAC_HEADROOM_ROOT, FAC_HEADROOM_SUBA, "facility"),
        (FAC_HEADROOM_ROOT, FAC_HEADROOM_SUBB, "facility"),
        (FAC_HEADROOM_SUBA, LN_HEADROOM, "loan"),
        (FAC_SHARED_ROOT, FAC_SHARED_SUBA, "facility"),
        (FAC_SHARED_ROOT, FAC_SHARED_SUBB, "facility"),
        (FAC_SHARED_SUBA, LN_SHARED_A, "loan"),
        (FAC_SHARED_SUBB, LN_SHARED_B, "loan"),
        (FAC_SHARED_OWN_A, LN_SHARED_OWN_A, "loan"),
        (FAC_SHARED_OWN_B, LN_SHARED_OWN_B, "loan"),
    ]
    rows = [
        {"parent_facility_reference": parent, "child_reference": child, "child_type": kind}
        for parent, child, kind in pairs
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _facility(reference: str, counterparty: str, limit: float) -> dict[str, object]:
    """One revolving, unsecured, committed, unconditionally-cancellable retail line.

    ``lgd`` + ``has_sufficient_collateral_data`` reach the headroom legs the
    hierarchy mints from the facility, so they resolve A-IRB like the loans.
    """
    return {
        "facility_reference": reference,
        "counterparty_reference": counterparty,
        "product_type": "revolving_credit_facility",
        "limit": limit,
        "risk_type": "LR",
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "committed": True,
        "is_revolving": True,
        "is_secured": False,
        "is_qrre_transactor": False,
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }


def _loan(reference: str, counterparty: str, drawn_amount: float) -> dict[str, object]:
    """One drawn revolving retail loan with an attested own-estimate LGD."""
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty,
        "product_type": "revolving_credit_facility",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }
