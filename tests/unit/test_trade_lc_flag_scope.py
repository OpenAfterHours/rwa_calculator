"""TR-01: the trade-LC flag reaches a drawn loan only from the loan's OWN parent facility.

Pipeline position:
    Loader -> HierarchyResolver (``enrich.propagate_facility_qrre_columns``)

Defect pinned (review TR-01, both regimes, RWA understated):
    ``_broadcast_trade_lc_flag`` OR-aggregated ``is_short_term_trade_lc`` over
    every facility of a counterparty and coalesced the result onto EVERY loan of
    that counterparty — including loans under no facility, and loans under a
    facility that is not trade finance at all. One trade-LC facility therefore
    switched on the PS1/26 Art. 120(2A)/121(4) short-term window (B31 SA 40% ->
    20%), the Art. 121(6)(b) sovereign-floor exemption, and the CRR Art. 162(3)
    one-day maturity floor for the counterparty's whole loan book.

Rule text (verbatim):
    PS1/26 Art. 121(4): "Exposures to institutions for which a credit assessment
    by a nominated ECAI is not available, where the original maturity of the
    exposure was six months or less and the exposure arose from the movement of
    goods, shall be assigned a risk weight in accordance with Table 5A."
    CRR Art. 162(3)(b): "self-liquidating short-term trade finance transactions
    connected to the exchange of goods or services with a residual maturity of up
    to one year as referred to in point (80) of Article 4(1)".

    Both conditions are properties of the TRANSACTION. A counterparty's other
    business does not meet them, so a loan inherits the flag only from the
    facility it is drawn under (``parent_facility_reference``).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.engine.hierarchy.enrich import propagate_facility_qrre_columns

_CP = "CP_TRADE_IMPORTER"


def _facilities() -> pl.LazyFrame:
    """One trade-LC facility and one ordinary term facility, same counterparty."""
    return pl.LazyFrame(
        {
            "facility_reference": ["FAC_TRADE_LC", "FAC_TERM"],
            "counterparty_reference": [_CP, _CP],
            "is_revolving": [False, False],
            "is_qrre_transactor": [False, False],
            "is_secured": [False, False],
            "limit": [1_000_000.0, 1_000_000.0],
            "facility_termination_date": pl.Series([None, None], dtype=pl.Date),
            "is_short_term_trade_lc": [True, False],
        }
    )


def _exposures() -> pl.LazyFrame:
    """Three drawn loans (flag null, as ``unify`` emits them) and one contingent.

    - LOAN_UNDER_TRADE: drawn under the trade-LC facility.
    - LOAN_UNDER_TERM: drawn under the ordinary facility of the same counterparty.
    - LOAN_STANDALONE: no parent facility at all.
    - CONT_OWN_FALSE: a contingent under the trade facility carrying its own
      sealed ``False`` — the per-row value must survive the inheritance.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "LOAN_UNDER_TRADE",
                "LOAN_UNDER_TERM",
                "LOAN_STANDALONE",
                "CONT_OWN_FALSE",
            ],
            "exposure_type": ["loan", "loan", "loan", "contingent"],
            "counterparty_reference": [_CP, _CP, _CP, _CP],
            "parent_facility_reference": ["FAC_TRADE_LC", "FAC_TERM", None, "FAC_TRADE_LC"],
            "is_short_term_trade_lc": pl.Series([None, None, None, False], dtype=pl.Boolean),
            "maturity_date": [date(2027, 6, 1)] * 4,
        }
    )


def _flags() -> dict[str, bool | None]:
    out = propagate_facility_qrre_columns(_exposures(), _facilities()).collect()
    return dict(zip(out["exposure_reference"], out["is_short_term_trade_lc"], strict=True))


def test_loan_under_trade_facility_inherits_the_flag() -> None:
    """A loan drawn under the trade-LC facility is trade finance: flag True."""
    # Arrange / Act
    flags = _flags()

    # Assert
    assert flags["LOAN_UNDER_TRADE"] is True


def test_loan_under_another_facility_of_the_same_counterparty_is_not_flagged() -> None:
    """The defect: the counterparty-level OR leaked True onto this loan."""
    # Arrange / Act
    flags = _flags()

    # Assert
    assert flags["LOAN_UNDER_TERM"] is False, (
        "a loan under an ordinary facility picked up the trade-LC flag of a "
        "SIBLING facility of the same counterparty (TR-01 counterparty broadcast)"
    )


def test_standalone_loan_of_a_trade_counterparty_is_not_flagged() -> None:
    """A loan under no facility has no trade-finance attestation at all."""
    # Arrange / Act
    flags = _flags()

    # Assert
    assert flags["LOAN_STANDALONE"] is False, (
        "a standalone loan picked up the counterparty's trade-LC flag "
        "(TR-01 counterparty broadcast)"
    )


def test_contingent_keeps_its_own_sealed_value() -> None:
    """Coalesce order: the row's own non-null value wins over the parent facility."""
    # Arrange / Act
    flags = _flags()

    # Assert
    assert flags["CONT_OWN_FALSE"] is False


def test_flag_is_never_null_after_propagation() -> None:
    """Downstream consumers read the flag without a null guard of their own."""
    # Arrange / Act
    flags = _flags()

    # Assert
    assert all(value is not None for value in flags.values())
