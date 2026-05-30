"""
Generate P2.38 fixtures: CRR Art. 155(2) non-trading-book short-position netting.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (data/schemas.py, data/tables/crr_equity_rw.py, engine/equity/calculator.py)

Key responsibilities:
- Produce one counterparty row (CP-ISSUER-A) — corporate entity with IRB permissions
  so the equity exposure routes to EquityApproach.IRB_SIMPLE under CRR.
- Produce two equity exposure rows for the same issuer (ISSUER-A):
    EQ-NET-LONG:  +£1,000,000 long position, exchange_traded, explicitly hedged >=1y
    EQ-NET-SHORT: -£400,000  short position, exchange_traded, explicitly hedged >=1y
- Carry THREE new input columns the engine will later consume:
    position_value     (pl.Float64)  Signed MV: +long / -short.
    issuer_reference   (pl.String)   Netting key: same individual stock = same string.
    is_explicitly_hedged (pl.Boolean) True -> hedge is explicit and >= 1 year.
- fair_value is populated for both rows (= absolute value of position_value) so the
  equity calculator's _prepare_columns fair_value -> ead_final chain gives a
  well-defined no-netting-baseline EAD for each row.

Scenario rationale (CRR Art. 155(2)):

    Under CRR Art. 155(2) (IRB Simple Risk Weight Method), short positions held in
    the non-trading book may offset long positions in the same individual stock,
    provided:
      (a) the hedge is explicit, AND
      (b) the hedge covers at least one year (CRR_EQUITY_NETTING_MIN_HEDGE_YEARS=1.0).

    Risk weights (Art. 155(2)):
      - PE-diversified:    190%  (IRB_SIMPLE_EQUITY_RISK_WEIGHTS["private_equity_diversified"])
      - exchange-traded:   290%  (IRB_SIMPLE_EQUITY_RISK_WEIGHTS["exchange_traded"])
      - all-other:         370%  (IRB_SIMPLE_EQUITY_RISK_WEIGHTS["other"])

    Approach gate: EquityApproach.IRB_SIMPLE fires only when:
      config.is_crr=True AND equity_pd_lgd=False AND FIRB/AIRB permission present.

Hand calculation (CRR, CalculationConfig.crr(), reporting_date=2026-06-30):

    Simple RW (exchange_traded) = 2.90  [Art. 155(2) Table, crr_equity_rw.py]
    Netting eligibility:
      - issuer_reference="ISSUER-A" on both rows  -> same individual stock
      - is_explicitly_hedged=True on both rows    -> explicit hedge
      - position_value=-400_000 for the short     -> tenor assumption >=1y satisfied
    Net long = max(0, L + S) = max(0, 1_000_000 + (-400_000)) = 600_000
    EAD_final (long, netted) = 600_000
    RWA (long) = 600_000 * 2.90 = 1_740_000
    EAD_final (short, absorbed) = 0
    RWA (short) = 0

    Anti-confound proof: netted RWA 1_740_000 < no-netting long-only 1_000_000*2.90=2_900_000.

Expected outputs (after engine netting is implemented):
    risk_weight (long)           = 2.90
    ead_final (long, netted)     = 600_000.0
    rwa / rwa_final (long)       = 1_740_000.0
    rwa / rwa_final (short)      = 0.0  (absorbed)
    Issuer-A RWA total           = 1_740_000.0
    K = rwa / 12.5               = 139_200.0
    approach                     = EquityApproach.IRB_SIMPLE

References:
    - CRR Art. 155(1)-(2): IRB Simple Risk Weight Method + netting rule
    - docs/specifications/crr/equity-approach.md L140-143: hedge explicit + >=1y condition
    - src/rwa_calc/data/tables/crr_equity_rw.py: IRB_SIMPLE_EQUITY_RISK_WEIGHTS

Usage:
    cd /home/philm/projects/rwa_calculator/tmp/worktrees/P2.38 && \\
    PYTHONPATH=/home/philm/projects/rwa_calculator/tmp/worktrees/P2.38/src \\
    /home/philm/projects/rwa_calculator/.venv/bin/python \\
    tests/fixtures/p2_38/p2_38.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, EQUITY_EXPOSURE_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP-ISSUER-A"
LONG_EXPOSURE_REF: str = "EQ-NET-LONG"
SHORT_EXPOSURE_REF: str = "EQ-NET-SHORT"
ISSUER_REF: str = "ISSUER-A"

# Reporting date within CRR effective window (until 2026-12-31)
REPORTING_DATE: date = date(2026, 6, 30)

# Exposure economics
LONG_POSITION_VALUE: float = 1_000_000.0  # +long
SHORT_POSITION_VALUE: float = -400_000.0  # -short (signed)
LONG_FAIR_VALUE: float = 1_000_000.0  # abs(long) = EAD basis before netting
SHORT_FAIR_VALUE: float = 400_000.0  # abs(short) = EAD basis before netting

# ---------------------------------------------------------------------------
# IRB Simple risk weight (Art. 155(2) — exchange-traded)
# ---------------------------------------------------------------------------

#: IRB Simple RW for exchange_traded equity (Art. 155(2) Table): 290%
IRB_SIMPLE_RW_EXCHANGE_TRADED: float = 2.90

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer assertions)
# ---------------------------------------------------------------------------

#: Net long after netting: max(0, 1_000_000 + (-400_000))
EXPECTED_NET_LONG: float = 600_000.0

#: EAD final on the long row (post-netting)
EXPECTED_EAD_FINAL_LONG: float = 600_000.0

#: EAD final on the short row (absorbed by the long)
EXPECTED_EAD_FINAL_SHORT: float = 0.0

#: RWA on the long row: 600_000 * 2.90
EXPECTED_RWA_LONG: float = 1_740_000.0

#: RWA on the short row (absorbed)
EXPECTED_RWA_SHORT: float = 0.0

#: Total Issuer-A RWA
EXPECTED_RWA_TOTAL: float = 1_740_000.0

#: Capital requirement K = RWA / 12.5
EXPECTED_K: float = 139_200.0

#: No-netting baseline (long only, for anti-confound assertion)
NO_NETTING_BASELINE_RWA: float = 1_000_000.0 * IRB_SIMPLE_RW_EXCHANGE_TRADED  # 2_900_000.0


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P2.38 counterparty: corporate entity with FIRB/AIRB permission.

    entity_type="corporate": routes to CORPORATE exposure class for SA/IRB dispatch.
    is_financial_sector_entity=False: standard corporate, not an FSE.
    apply_fi_scalar=False: no FI correlation scalar required for equity IRB Simple path.
    default_status=False: performing counterparty.
    country_code="GB": domestic GBP counterparty.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _EquityExposure:
    """
    P2.38 equity exposure row.

    equity_type="exchange_traded": routes to IRB Simple RW = 290% (Art. 155(2)).
    is_exchange_traded=True: confirms listing status.
    fair_value: absolute market value — the equity calculator derives ead_final
        from fair_value via _prepare_columns before netting is applied.

    NOTE: position_value, issuer_reference, and is_explicitly_hedged are
    PROPOSED-NEW columns on EQUITY_EXPOSURE_SCHEMA (added by engine-implementer).
    They are seeded forward-compatibly via with_columns after constructing from
    dtypes_of(EQUITY_EXPOSURE_SCHEMA).  Once the schema declares these fields,
    with_columns becomes a no-op type-preserving update.
    """

    exposure_reference: str
    counterparty_reference: str
    equity_type: str
    currency: str
    fair_value: float
    is_exchange_traded: bool
    is_speculative: bool
    is_government_supported: bool
    is_significant_investment: bool

    def to_dict(self) -> dict:
        return {
            "exposure_reference": self.exposure_reference,
            "counterparty_reference": self.counterparty_reference,
            "equity_type": self.equity_type,
            "currency": self.currency,
            "fair_value": self.fair_value,
            "is_exchange_traded": self.is_exchange_traded,
            "is_speculative": self.is_speculative,
            "is_government_supported": self.is_government_supported,
            "is_significant_investment": self.is_significant_investment,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p238_counterparty() -> pl.DataFrame:
    """
    Return the P2.38 counterparty as a single-row DataFrame.

    One row: CP-ISSUER-A — corporate entity, domestic GB, performing.

    The entity is set up as a standard corporate (not FSE) so that FIRB/AIRB
    permission from CalculationConfig.crr() gates it into EquityApproach.IRB_SIMPLE
    without FSE-path complications.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Issuer-A Corp (GB) — P2.38 netting test",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_financial_sector_entity=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p238_equity_exposures() -> pl.DataFrame:
    """
    Return the P2.38 equity exposures as a two-row DataFrame.

    Row 1 — EQ-NET-LONG (long position):
        position_value=+1_000_000  -> unsigned long
        fair_value=1_000_000       -> ead_final basis (pre-netting)
        is_explicitly_hedged=True  -> netting eligible

    Row 2 — EQ-NET-SHORT (short position):
        position_value=-400_000    -> signed short
        fair_value=400_000         -> abs(short) = ead_final basis (pre-netting)
        is_explicitly_hedged=True  -> netting eligible

    Both rows share issuer_reference="ISSUER-A" — netting key per Art. 155(2)
    ("same individual stock").

    New columns position_value, issuer_reference, is_explicitly_hedged are
    appended via with_columns (forward-compatible pattern).  Once
    EQUITY_EXPOSURE_SCHEMA declares them, with_columns becomes a no-op update.

    Key column choices:
        equity_type="exchange_traded" -> Art. 155(2) IRB Simple RW = 290%
        is_exchange_traded=True       -> confirms listing for branch selection
        is_speculative=False          -> standard equity
        is_government_supported=False -> standard commercial equity
        is_significant_investment=False -> no override
    """
    long_row = _EquityExposure(
        exposure_reference=LONG_EXPOSURE_REF,
        counterparty_reference=COUNTERPARTY_REF,
        equity_type="exchange_traded",
        currency="GBP",
        fair_value=LONG_FAIR_VALUE,
        is_exchange_traded=True,
        is_speculative=False,
        is_government_supported=False,
        is_significant_investment=False,
    )
    short_row = _EquityExposure(
        exposure_reference=SHORT_EXPOSURE_REF,
        counterparty_reference=COUNTERPARTY_REF,
        equity_type="exchange_traded",
        currency="GBP",
        fair_value=SHORT_FAIR_VALUE,
        is_exchange_traded=True,
        is_speculative=False,
        is_government_supported=False,
        is_significant_investment=False,
    )

    # Build from declared schema (excludes three new netting columns — not yet in schema).
    df = pl.DataFrame(
        [long_row.to_dict(), short_row.to_dict()],
        schema=dtypes_of(EQUITY_EXPOSURE_SCHEMA),
    )

    # Append the three new input columns forward-compatibly.
    # position_value: signed float; +long / -short.  Absent from schema until engine Wave 4.
    # issuer_reference: netting key — same string means same individual stock (Art. 155(2)).
    # is_explicitly_hedged: True -> hedge explicit and >= 1 year -> netting permitted.
    return df.with_columns(
        pl.Series("position_value", [LONG_POSITION_VALUE, SHORT_POSITION_VALUE], dtype=pl.Float64),
        pl.Series("issuer_reference", [ISSUER_REF, ISSUER_REF], dtype=pl.String),
        pl.Series("is_explicitly_hedged", [True, True], dtype=pl.Boolean),
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p238_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.38 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet      — 1 row  (CP-ISSUER-A)
        equity_exposure.parquet   — 2 rows (EQ-NET-LONG, EQ-NET-SHORT)
            Includes three new columns: position_value, issuer_reference,
            is_explicitly_hedged (forward-compatible with EQUITY_EXPOSURE_SCHEMA).

    Args:
        output_dir: Target directory.  Defaults to this package directory
            (``tests/fixtures/p2_38/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p238_counterparty()),
        ("equity_exposure", create_p238_equity_exposures()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.38 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<25} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario CRR-J21: CRR Art. 155(2) non-trading-book short-position netting")
    print()
    print(f"  Counterparty:   {COUNTERPARTY_REF} — corporate, GB, performing")
    print(
        f"  Long exposure:  {LONG_EXPOSURE_REF} — exchange_traded, +GBP {LONG_POSITION_VALUE:,.0f}"
    )
    print(
        f"  Short exposure: {SHORT_EXPOSURE_REF} — exchange_traded, -GBP {abs(SHORT_POSITION_VALUE):,.0f}"
    )
    print(f"  Issuer key:     {ISSUER_REF}")
    print(f"  Reporting:      {REPORTING_DATE}")
    print()
    print("  Art. 155(2) hand-calculation:")
    print(f"    IRB Simple RW (exchange_traded)  = {IRB_SIMPLE_RW_EXCHANGE_TRADED:.2f}  (290%)")
    print(
        f"    Net long = max(0, L+S)           = max(0, {LONG_POSITION_VALUE:,.0f} + {SHORT_POSITION_VALUE:,.0f})"
    )
    print(f"                                     = {EXPECTED_NET_LONG:,.0f}")
    print()
    print("  Expected outputs (post-engine netting):")
    print(f"    ead_final (long, netted)    = {EXPECTED_EAD_FINAL_LONG:,.0f}")
    print(f"    ead_final (short, absorbed) = {EXPECTED_EAD_FINAL_SHORT:,.0f}")
    print(f"    rwa (long)                  = {EXPECTED_RWA_LONG:,.0f}")
    print(f"    rwa (short)                 = {EXPECTED_RWA_SHORT:,.0f}")
    print(f"    Issuer-A total RWA          = {EXPECTED_RWA_TOTAL:,.0f}")
    print(f"    K = rwa / 12.5              = {EXPECTED_K:,.0f}")
    print()
    print("  Anti-confound:")
    print(
        f"    Netted RWA {EXPECTED_RWA_TOTAL:,.0f} < no-netting {NO_NETTING_BASELINE_RWA:,.0f}  [OK]"
    )
    print()

    # Verify new columns are present and correctly typed
    eq_df = pl.read_parquet(saved["equity_exposure"])
    for col, expected_dtype in [
        ("position_value", pl.Float64),
        ("issuer_reference", pl.String),
        ("is_explicitly_hedged", pl.Boolean),
    ]:
        if col in eq_df.columns:
            actual_dtype = eq_df.schema[col]
            vals = eq_df[col].to_list()
            status = "OK" if actual_dtype == expected_dtype else "DTYPE MISMATCH"
            print(f"  [{status}] {col}: dtype={actual_dtype}, values={vals}")
        else:
            print(f"  [WARNING] {col} column missing from equity_exposure parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p238_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
