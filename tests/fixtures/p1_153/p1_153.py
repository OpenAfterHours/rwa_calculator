"""
Generate P1.153 fixtures: CRR Art. 155(3) PD/LGD equity approach (scenario CRR-J21).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (domain/enums.py, engine/equity/calculator.py, data/tables/crr_equity_pd_lgd.py)

Key responsibilities:
- Produce one counterparty row: corporate financial-sector entity with IRB permissions,
  so the equity exposure routes to the Art. 155(3) PD/LGD IRB path under CRR.
- Produce one equity exposure row: exchange-traded equity, EAD = GBP 1,000,000,
  has_default_definition_info=True (no 1.5x scaling per Art. 155(3)).
- Seed has_default_definition_info as pl.Boolean via with_columns, forward-compatibly:
  EQUITY_EXPOSURE_SCHEMA does not yet declare this column (Wave 4 adds it).
  Once the engine-implementer adds it, with_columns is a no-op update.

Scenario rationale (CRR Art. 155(3)):

    Under CRR Art. 155(3), institutions that have received supervisory permission to
    use the PD/LGD approach may apply it to equity exposures.  The approach uses
    supervisory parameters from Art. 165:
        - PD floor:  Art. 165(1)(c) exchange-traded equity = 0.40%
        - LGD:       Art. 165(2) non-diversified-PE = 90%
        - M:         Art. 165(3) = 5 years (fixed)
    Combined with the IRB corporate K formula (Art. 153(1)) and the 1.06 CRR
    scaling factor (Art. 153), the worked exposure yields RW = ~192%.

    Art. 155(3) last sub-paragraph: where an institution does NOT have adequate
    default-definition data, a 1.5x scaling is applied.  has_default_definition_info=True
    means the institution has such data -> the 1.5x scaling does NOT apply.

Hand calculation (CRR, CalculationConfig.crr(), reporting_date=2026-06-30):

    exposure_reference         = EQ-PDLGD-001
    equity_type                = exchange_traded (EquityType.EXCHANGE_TRADED)
    is_exchange_traded         = True
    EAD                        = 1,000,000
    has_default_definition_info = True  -> 1.5x NOT applied

    PD floor     = 0.0040   [Art. 165(1)(c): exchange-traded equity]
    LGD          = 0.90     [Art. 165(2): not private_equity_diversified -> 90%]
    M            = 5.0      [Art. 165(3): fixed maturity]
    scaling      = 1.06     [Art. 153(1)]

    f(PD) = (1 - exp(-50 x 0.0040)) / (1 - exp(-50)) = 0.18126924692
    R     = 0.12 x f + 0.24 x (1 - f) = 0.21824769037
    G(PD) = N^-1(0.0040) = -2.65206980587
    conditional_pd = N[(G(PD) + sqrt(R/(1-R)) x G(0.999)) / sqrt(1-R)]
                   = N[(-2.99877 + 1.63276)] = N[-1.36601] = 0.0859757
    K     = LGD x conditional_pd - PD x LGD
          = 0.90 x 0.0859757 - 0.0040 x 0.90 = 0.0736714
          (prior hand-calc gave 0.07377817 due to misrounded (1-R)^-0.5 = 1.13075282;
           correct value is 1.131007314)
    b     = (0.11852 - 0.05478 x ln(0.0040))^2 = 0.17722890
    MA    = (1 + (5-2.5) x b) / (1 - 1.5 x b) = 1.96561
    RW    = K x 12.5 x 1.06 x MA = 1.918731  (191.87%)
    RWEA  = RW x EAD = 1,918,731
    EL    = PD x LGD x EAD = 3,600

Expected outputs:
    pd_floored                = 0.0040    (exact)
    lgd                       = 0.90      (exact)
    maturity                  = 5.0       (exact)
    correlation               = 0.218248  (+-1e-5)
    k                         = 0.0736714 (+-1e-5)
    maturity_adjustment       = 1.965610  (+-1e-4)
    scaling_factor            = 1.06      (exact)
    risk_weight               = 1.918731  (+-1e-3 rel)
    expected_loss             = 3600.0    (+-0.5)
    rwa / rwa_final           = 1,918,731 (+-50)
    equity_pd_lgd_cap_binds   = False     (exact)

References:
    - CRR Art. 155(3): PD/LGD approach for equity; 1.5x scaling absent default data
    - CRR Art. 165(1)(c): PD floor exchange-traded equity = 0.40%
    - CRR Art. 165(2): supervisory LGD = 90% (non-diversified-PE)
    - CRR Art. 165(3): M = 5 years (fixed)
    - CRR Art. 153(1): corporate IRB K formula
    - CRR Art. 153: 1.06 scaling factor
    - scenario-P1.153.md: worked hand-calculation (CRR-J21)

Usage:
    cd /home/philm/projects/rwa_calculator/tmp/worktrees/P1.153 && \\
    PYTHONPATH=/home/philm/projects/rwa_calculator/tmp/worktrees/P1.153/src \\
    /home/philm/projects/rwa_calculator/.venv/bin/python \\
    tests/fixtures/p1_153/p1_153.py
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

COUNTERPARTY_REF: str = "CP-PDLGD-001"
EXPOSURE_REF: str = "EQ-PDLGD-001"

# Exposure economics
EAD_FINAL: float = 1_000_000.0

# Framework parameters
REPORTING_DATE: date = date(2026, 6, 30)

# ---------------------------------------------------------------------------
# Supervisory parameters (Art. 165) — authoritative for test-writer
# ---------------------------------------------------------------------------

#: Art. 165(1)(c): PD floor for exchange-traded equity
PD_FLOOR: float = 0.0040  # 0.40%

#: Art. 165(2): supervisory LGD for non-private_equity_diversified equity
LGD_SUPERVISORY: float = 0.90  # 90%

#: Art. 165(3): fixed maturity for equity PD/LGD approach
MATURITY_YEARS: float = 5.0

#: Art. 153: CRR scaling factor
SCALING_FACTOR: float = 1.06

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer assertions)
# ---------------------------------------------------------------------------

#: Vasicek asset correlation (R) ≈ 0.218248
EXPECTED_CORRELATION: float = 0.21824769037

#: Capital requirement K ≈ 0.0736714
EXPECTED_K: float = 0.07367139

#: Maturity adjustment MA ≈ 1.96561
EXPECTED_MATURITY_ADJUSTMENT: float = 1.96561

#: Risk weight = K x 12.5 x scaling x MA ≈ 191.87%
EXPECTED_RISK_WEIGHT: float = 1.9187310

#: Expected loss = PD x LGD x EAD = 0.0040 x 0.90 x 1,000,000 = 3,600
EXPECTED_EL: float = 3_600.0

#: RWA = risk_weight x EAD ≈ 1,918,731
EXPECTED_RWA: float = 1_918_731.0

#: Art. 155(3) cap check: EL x 12.5 + RWEA = 45,000 + 1,918,731 = 1,963,731 <= EAD x 12.5
#: => cap does NOT bind
EXPECTED_CAP_BINDS: bool = False


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.153 counterparty: corporate financial-sector entity with IRB permissions.

    entity_type="corporate": routes to CORPORATE exposure class for SA/IRB dispatch.
    is_financial_sector_entity=True: the entity is a regulated firm that holds
        equity stakes under the IRB equity approach (Art. 155(3) permission).
    apply_fi_scalar=False: no additional FI correlation scalar needed for the equity
        PD/LGD path (the scalar applies to non-equity corporate/institution exposures).
    default_status=False: performing counterparty.
    country_code="GB": domestic GBP counterparty.

    Note: the equity PD/LGD approach (Art. 155(3)) requires supervisory permission
    from the PRA.  The fixture models the counterparty as a corporate/FSE to mirror
    the kind of entity a CRR-regulated bank would hold equity in under this path.
    The permission is controlled by the config flag equity_pd_lgd (Wave 4 engine work).
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
    P1.153 equity exposure: exchange-traded equity with PD/LGD approach.

    equity_type="exchange_traded": routes to Art. 165(1)(c) PD floor = 0.40%
        and Art. 165(2) LGD = 90% (not private_equity_diversified).
    is_exchange_traded=True: confirms the listing status (drives PD floor band).
    fair_value=1,000,000: carrying value / EAD basis for the exposure.
    has_default_definition_info=True: Art. 155(3) — institution has adequate
        default-definition data -> 1.5x scaling does NOT apply.

    NOTE: has_default_definition_info is a PROPOSED-NEW column on
    EQUITY_EXPOSURE_SCHEMA (added by the engine-implementer in Wave 4).
    The builder seeds it forward-compatibly via with_columns after constructing
    from dtypes_of(EQUITY_EXPOSURE_SCHEMA).  Once the engine adds the column,
    the with_columns call becomes a schema-preserving no-op update.
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
    # NOTE: has_default_definition_info is NOT in this dataclass because it is
    # appended via with_columns (forward-compatible pattern) rather than via
    # the schema-typed constructor path.

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


def create_p1153_counterparty() -> pl.DataFrame:
    """
    Return the P1.153 counterparty as a single-row DataFrame.

    One row: CP-PDLGD-001 — corporate financial-sector entity (FSE), domestic GB.

    is_financial_sector_entity=True models the class of regulated counterparty
    whose equity is held under the Art. 155(3) IRB PD/LGD permission.
    The entity_type="corporate" ensures the exposure class resolves correctly
    under the CRR classifier without falling into the institution branch (which
    would change the IRB K formula parameters).
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="PD/LGD Equity Holdings (GB) — P1.153",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_financial_sector_entity=True,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1153_equity_exposure() -> pl.DataFrame:
    """
    Return the P1.153 equity exposure as a single-row DataFrame.

    One row: EQ-PDLGD-001 — exchange-traded equity, GBP 1,000,000, PD/LGD approach.

    has_default_definition_info=True is appended via with_columns because
    EQUITY_EXPOSURE_SCHEMA does not yet declare this column.  The column is
    pl.Boolean and is written into the parquet so that:
      - Pre-engine-implementer: tests can read the column from the parquet directly.
      - Post-engine-implementer: with_columns is a schema-preserving no-op update
        (the engine will have declared the column with the same dtype).

    Key column choices:
      equity_type="exchange_traded" -> Art. 165(1)(c) PD floor = 0.40%,
                                       Art. 165(2) LGD = 90% (not diversified PE)
      is_exchange_traded=True       -> confirms listing for PD band resolution
      fair_value=1_000_000.0        -> EAD basis (no carrying_value override)
      is_speculative=False          -> standard equity, not speculative
      is_significant_investment=False -> no significant investment override
      is_government_supported=False -> standard commercial equity
    """
    row = _EquityExposure(
        exposure_reference=EXPOSURE_REF,
        counterparty_reference=COUNTERPARTY_REF,
        equity_type="exchange_traded",
        currency="GBP",
        fair_value=EAD_FINAL,
        is_exchange_traded=True,
        is_speculative=False,
        is_government_supported=False,
        is_significant_investment=False,
    )

    # Build from the declared schema (excludes has_default_definition_info — not yet in schema).
    df = pl.DataFrame([row.to_dict()], schema=dtypes_of(EQUITY_EXPOSURE_SCHEMA))

    # Append has_default_definition_info as pl.Boolean.
    # True -> institution has adequate default-definition data -> 1.5x NOT applied (Art. 155(3)).
    # Forward-compatible: once EQUITY_EXPOSURE_SCHEMA declares this field, with_columns
    # is a no-op update on the already-typed Boolean column.
    return df.with_columns(
        pl.Series("has_default_definition_info", [True], dtype=pl.Boolean)
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1153_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.153 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet      — 1 row  (CP-PDLGD-001)
        equity_exposure.parquet   — 1 row  (EQ-PDLGD-001, has_default_definition_info=True)

    The equity_exposure parquet includes has_default_definition_info (pl.Boolean)
    even though EQUITY_EXPOSURE_SCHEMA does not yet declare it.  The engine-implementer
    will add the column in Wave 4; the parquet is forward-compatible.

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p1_153/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1153_counterparty()),
        ("equity_exposure", create_p1153_equity_exposure()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.153 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<25} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario CRR-J21: CRR Art. 155(3) PD/LGD equity approach")
    print()
    print(f"  Counterparty: {COUNTERPARTY_REF} — corporate FSE, GB, no default")
    print(f"  Exposure:     {EXPOSURE_REF}  — exchange_traded equity, GBP {EAD_FINAL:,.0f}")
    print(f"  Reporting:    {REPORTING_DATE}")
    print()
    print("  Art. 165 supervisory parameters:")
    print(f"    PD floor (exchange_traded, Art. 165(1)(c)) = {PD_FLOOR:.4f}  ({PD_FLOOR:.2%})")
    print(f"    LGD (non-diversified-PE, Art. 165(2))      = {LGD_SUPERVISORY:.2f}  (90%)")
    print(f"    M (Art. 165(3))                            = {MATURITY_YEARS:.1f} years")
    print(f"    scaling factor (Art. 153)                  = {SCALING_FACTOR}")
    print(f"    has_default_definition_info                = True  (no 1.5x, Art. 155(3))")
    print()
    print("  Expected outputs:")
    print(f"    correlation (R)      ≈ {EXPECTED_CORRELATION:.6f}")
    print(f"    K                    ≈ {EXPECTED_K:.6f}")
    print(f"    maturity_adjustment  ≈ {EXPECTED_MATURITY_ADJUSTMENT:.5f}")
    print(f"    risk_weight          ≈ {EXPECTED_RISK_WEIGHT:.5f}  ({EXPECTED_RISK_WEIGHT:.2%})")
    print(f"    expected_loss        = {EXPECTED_EL:,.0f}")
    print(f"    rwa / rwa_final      ≈ {EXPECTED_RWA:,.0f}")
    print(f"    cap_binds            = {EXPECTED_CAP_BINDS}")
    print()
    # Verify has_default_definition_info column presence and dtype
    eq_df = pl.read_parquet(saved["equity_exposure"])
    if "has_default_definition_info" in eq_df.columns:
        dtype = eq_df.schema["has_default_definition_info"]
        val = eq_df["has_default_definition_info"].to_list()[0]
        print(f"  has_default_definition_info dtype: {dtype}, value: {val}")
    else:
        print("  WARNING: has_default_definition_info column missing from equity_exposure parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1153_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
