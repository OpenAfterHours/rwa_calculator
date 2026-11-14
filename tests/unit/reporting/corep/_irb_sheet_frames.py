"""Hand-built Basel 3.1 IRB books for the OF 08 sheet-axis tests.

Built on the ``_c02_frames`` leg lists — one leg per figure OF 02.00 can place,
each with a distinct amount — so the same book can be read through OF 02.00 and
through OF 08 and the two compared leg by leg.

``EXPECTED_SHEET_CODE`` says which PUBLISHED sheet each leg belongs on. It is
written from the published sheet labels (Bank of England taxonomy v4.1.1, table
``OF08.01.01.01``) and the leg's own approach, class, SME flag and property
type — not from the generator's key names — and is resolved to a sheet key
through the filing sheet map, which
``tests/contracts/test_of08_published_sheets.py`` holds to the taxonomy.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from tests.unit.reporting.corep._c02_frames import MODELLED_LEGS, Leg, b31_frame

FRAMEWORK = "BASEL_3_1"

#: Leg reference -> the published sheet code it belongs on.
EXPECTED_SHEET_CODE: dict[str, str] = {
    "F_INST": "0006",  # Institutions (FIRB approach)
    "F_SL": "0010",  # Corporates - Specialised Lending (FIRB approach or slotting approach)
    "F_FSE": "0022",  # Corporates - Financial corporates and large corporates (FIRB approach)
    "F_SME": "0024",  # Corporates - Other general corporates - SME (FIRB approach)
    "F_OTH": "0012",  # Corporates - Other general corporates - non-SME (FIRB approach)
    "A_SL": "0009",  # Corporates - Specialised Lending (AIRB approach)
    "A_SME": "0023",  # Corporates - Other general corporates - SME (AIRB approach)
    "A_OTH": "0011",  # Corporates - Other general corporates - non-SME (AIRB approach)
    "A_RES_SME": "0020",  # Retail - Secured by residential immovable property - SME
    "A_RES": "0021",  # Retail - Secured by residential immovable property non-SME
    "A_COM_SME": "0018",  # Retail - Secured by commercial immovable property SME
    "A_COM": "0019",  # Retail - Secured by commercial immovable property non-SME
    "A_QRRE": "0015",  # Retail - Qualifying revolving (AIRB approach)
    "A_OSME": "0016",  # Retail - Other SME (AIRB approach)
    "A_ONON": "0017",  # Retail - Other non-SME (AIRB approach)
    # Annex II row 0080: slotting "shall only apply to the exposure sub-class
    # 'corporate - specialised lending'".
    "SL_PF": "0010",
    "SL_OF": "0010",
    "SL_CF": "0010",
    "SL_IPRE": "0010",
    "SL_HVCRE": "0010",
}

TOTAL_AIRB_CODE = "0001"
TOTAL_FIRB_SLOTTING_CODE = "0002"
SLOTTING_SHEET_CODE = "0010"

#: The published codes whose sheets add into each Total (``boe_b0748`` /
#: ``boe_b0749`` state the two lists).
AIRB_CODES = ("0009", "0023", "0011", "0020", "0021", "0018", "0019", "0015", "0016", "0017")
FIRB_SLOTTING_CODES = ("0006", "0010", "0022", "0024", "0012")


def sheet_key(code: str) -> str:
    """Our sheet key for a published sheet code — exactly one, or the test fails."""
    (key,) = SHEET_INDEX_MAPS["of08"][code].bundle_keys
    return key


#: Our key for each published sheet, named for the published label — for a test
#: that reads one sheet of a hand-built Basel 3.1 book. Resolved through the
#: filing sheet map, never written as a key.
OF08_TOTAL_AIRB = sheet_key("0001")
OF08_TOTAL_FIRB_SLOTTING = sheet_key("0002")
OF08_INSTITUTIONS_FIRB = sheet_key("0006")
OF08_SPECIALISED_LENDING_AIRB = sheet_key("0009")
OF08_SPECIALISED_LENDING_FIRB_SLOTTING = sheet_key("0010")
OF08_CORPORATE_NON_SME_AIRB = sheet_key("0011")
OF08_CORPORATE_NON_SME_FIRB = sheet_key("0012")
OF08_RETAIL_QRRE = sheet_key("0015")
OF08_RETAIL_OTHER_SME = sheet_key("0016")
OF08_RETAIL_OTHER_NON_SME = sheet_key("0017")
OF08_RETAIL_COMMERCIAL_SME = sheet_key("0018")
OF08_RETAIL_COMMERCIAL_NON_SME = sheet_key("0019")
OF08_RETAIL_RESIDENTIAL_SME = sheet_key("0020")
OF08_RETAIL_RESIDENTIAL_NON_SME = sheet_key("0021")
OF08_CORPORATE_FINANCIAL_LARGE_FIRB = sheet_key("0022")
OF08_CORPORATE_SME_AIRB = sheet_key("0023")
OF08_CORPORATE_SME_FIRB = sheet_key("0024")


def irb_sheet(framework: str, exposure_class: str, b31_key: str) -> str:
    """The sheet a leg reports on: its exposure class under CRR, a published
    class-and-approach sheet (``b31_key``, one of the ``OF08_*`` names) under
    Basel 3.1. For a test that runs one book under both frameworks."""
    return b31_key if framework == FRAMEWORK else exposure_class


def legs_on(code: str, legs: tuple[Leg, ...] = MODELLED_LEGS) -> tuple[Leg, ...]:
    """The legs that belong on published sheet ``code``."""
    return tuple(leg for leg in legs if EXPECTED_SHEET_CODE.get(leg.reference) == code)


def pd_of(leg: Leg) -> float:
    """A distinct PD per leg, inside the "0.75 to <1.75" band (leaf row 0080)."""
    return 0.0080 + leg.own / 100_000.0


def lgd_of(leg: Leg) -> float:
    """A distinct LGD per leg."""
    return 0.20 + leg.own / 2_000.0


def maturity_of(leg: Leg) -> float:
    """A distinct maturity in years per leg."""
    return 1.0 + leg.own / 200.0


def irb_book(legs: tuple[Leg, ...] = MODELLED_LEGS) -> pl.LazyFrame:
    """``b31_frame`` with the per-leg parameters OF 08.01-08.05 report.

    Every leg is its own obligor, drawn, with EAD ``2 x own`` (``_c02_frames``).
    """
    by_reference = {leg.reference: leg for leg in legs}
    references = [leg.reference for leg in legs]
    parameters = pl.DataFrame(
        {
            "exposure_reference": references,
            "pd_floored": [pd_of(by_reference[ref]) for ref in references],
            "pd": [pd_of(by_reference[ref]) for ref in references],
            "lgd_floored": [lgd_of(by_reference[ref]) for ref in references],
            "irb_maturity_m": [maturity_of(by_reference[ref]) for ref in references],
            "counterparty_reference": [f"CP_{ref}" for ref in references],
            "drawn_amount": [by_reference[ref].own * 2.0 for ref in references],
            "expected_loss": [by_reference[ref].own / 100.0 for ref in references],
            "exposure_type": ["loan" for _ in references],
        }
    )
    return b31_frame(legs).join(parameters.lazy(), on="exposure_reference", how="left")


def cell(frame: pl.DataFrame, row_ref: str, col_ref: str) -> float | None:
    """One cell of a template frame; ``None`` when it is empty or the row is absent."""
    matched = frame.filter(pl.col("row_ref") == row_ref)
    if matched.height == 0:
        return None
    value = matched[col_ref][0]
    return None if value is None else float(value)
