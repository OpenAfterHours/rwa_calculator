# FX Conversion

The calculator supports **multi-currency portfolios** by converting all monetary values to a base currency (GBP by default) before performing calculations.

## Why FX Conversion Matters

Regulatory thresholds (SME turnover, retail exposure limits) are defined in EUR or GBP. Without consistent currency conversion, exposures in foreign currencies would be incorrectly assessed against these thresholds.

## What Gets Converted

| Data Type | Converted Fields |
|-----------|-----------------|
| Exposures | Drawn amount, undrawn amount, nominal amount |
| Collateral | Market value, nominal value |
| Guarantees | Covered amount |
| Provisions | Provision amount |

## Configuration

FX conversion is controlled via `CalculationConfig`:

```python
from rwa_calc.contracts.config import CalculationConfig
from datetime import date

# FX conversion enabled by default (base_currency is always GBP)
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_fx_conversion=True,      # Enable/disable
)
```

## Input Data

FX rates are provided via the `fx_rates` input table:

| Column | Type | Description |
|--------|------|-------------|
| `currency_from` | String | Currency code (e.g., "USD", "EUR") |
| `currency_to` | String | Target currency (must match `base_currency`) |
| `rate` | Float | Exchange rate (source to target) |

### Example FX Rates

```python
fx_rates = pl.DataFrame({
    "currency_from": ["USD", "EUR", "CHF"],
    "currency_to": ["GBP", "GBP", "GBP"],
    "rate": [0.79, 0.87, 0.89],
})
```

## Pipeline Integration

FX conversion occurs **early** in the pipeline, during hierarchy resolution, so that all downstream calculations (threshold checks, collateral haircuts, RWA) use consistent GBP values.

```mermaid
flowchart TD
    A[Raw Data - Mixed Currencies] --> B[FX Conversion]
    B --> C[Hierarchy Resolution]
    C --> D[Classification - GBP thresholds]
    D --> E[CRM - GBP haircuts]
    E --> F[Calculators - GBP RWA]
```

## Audit Trail

The converter preserves original values for audit:

| Audit Field | Description |
|-------------|-------------|
| `original_currency` | Currency before conversion |
| `original_amount` | Amount before conversion |
| `fx_rate_applied` | Rate used for conversion |

## Missing FX Rates

If a currency's FX rate is not provided:
- Values are left unchanged (not converted): the amount stays in its source currency's units and
  keeps its currency code, but every GBP threshold, total and template downstream reads it as
  reporting currency
- `fx_rate_applied` is set to `null`
- The run reports one **`DQ020` ERROR per such currency**, naming the rows and amounts per table
  (loans, contingents, facilities, collateral, guarantees, provisions, equity exposures). The
  engine still passes the amounts through — it has no rate and must not invent one — so the error
  is the signal to supply the missing `currency_from -> base_currency` row.

That 1:1 pass-through used to be silent. Its direction depends on the currency — 1m KWD read as
GBP understates by roughly 60%, 1m ZAR read as GBP overstates roughly twentyfold — so the defect
was the silence, not a bias (review finding RC-11). The check mirrors the converter exactly: an
exact-match `currency == base_currency` test, `fx_rates` rows whose `currency_to` is the base
currency, a null `rate` counting as none, and no `fx_rates` table at all meaning no rate for
anything. A null currency is not reported (there is no mismatch to measure), and nothing is
reported when `apply_fx_conversion=False`. `DQ020` is raised by the pipeline-entry input gate
(`contracts/validation.py`), which holds the run's configuration; facility headroom netting has
its own warning, `HIE005`, below.

| Example | Result |
|---------|--------|
| Loan KWD 1,000,000, `fx_rates` holds EUR only | EAD 1,000,000 (unconverted), **`DQ020` for KWD** |
| Same loan, KWD -> GBP 2.5 supplied | EAD 2,500,000, no `DQ020` |

## Facility Headroom Netting

A facility's undrawn commitment is `limit − utilisation`, and that subtraction is only
meaningful in one currency — the facility's, in which its limit is advised (CRR Art. 4(1)(56):
the extent of the commitment is "determined by the advised limit"). Headroom is computed during
hierarchy unification, **before** the conversion above, so each mapped loan's `drawn_amount` and
contingent's `nominal_amount` is first put in the facility's currency at the same `fx_rates`:

```
amount_in_facility_ccy = amount × rate(child_ccy → GBP) / rate(facility_ccy → GBP)
```

The undrawn row is then converted to the reporting currency with everything else.

| Case | Example | Undrawn |
|------|---------|---------|
| Same currency | GBP 10m line, GBP 4m drawn | 6m GBP (unchanged) |
| Drawing in another currency | GBP 10m line, EUR 5m drawn at 0.85 | 10m − 4.25m = 5.75m GBP |
| Low-unit currency | GBP 10m line, JPY 1bn drawn at 0.005 | 5m GBP (raw netting clipped the line to 0) |
| No rate for the drawing | GBP 10m line, USD 6.5m drawn, no USD rate | 10m GBP, not netted — **HIE005** |
| Conversion disabled | `apply_fx_conversion=False` | netted as supplied (one unit of account) |

An amount with no rate is **not netted**: the headroom is never reduced by an amount the run
cannot measure, and the `HIE005` warning names the facility and the currency so the missing rate
can be supplied. For a Multiple Option Facility, each sub-facility's headroom is netted in its own
currency and converted into the umbrella's currency for the waterfall cap; a sub-limit that cannot
be converted takes no slice (also `HIE005`). See
[Hierarchy & Classification](../../specifications/common/hierarchy-classification.md#undrawn-amount-aggregation).

## Regulatory Thresholds

Key thresholds that depend on correct FX conversion:

| Threshold | EUR Value | GBP Equivalent |
|-----------|-----------|----------------|
| SME turnover | EUR 50m | ~GBP 43.7m |
| SME exposure (SF tier) | EUR 2.5m | ~GBP 2.18m |
| Retail aggregate (CRR) | EUR 1m | ~GBP 873k (at 0.8732) |
| QRRE individual | EUR 100k | ~GBP 100k |

The EUR-to-GBP rate is configurable and defaults to 0.8732.

!!! note "Basel 3.1 Fixed GBP Thresholds"
    Under Basel 3.1 (PRA PS1/26), the retail aggregate threshold is replaced with a fixed
    **GBP 880,000** (Art. 123(1)(b)(ii)) and the QRRE individual limit with **GBP 90,000**
    (Art. 147(5A)(c)). These do not require FX conversion. The table above applies to CRR only.

## Auto-sync of `eur_gbp_rate` from the FX table

`config.eur_gbp_rate` has two separate uses under CRR:

1. Deriving GBP equivalents of EUR regulatory thresholds from the rulepack pack EUR bases at read time (`engine/thresholds.py`).
2. Converting GBP turnover to EUR inside the IRB SME correlation formula (CRR Art. 153(4)).

Exposure/collateral/guarantee/provision **amounts** are converted using the loaded `fx_rates` table (above). Historically, these two mechanisms did not talk to each other — a user could load an up-to-date `fx_rates.parquet` with `(EUR, GBP, 0.90)` and get all amounts converted at 0.90 while the SME correlation and derived GBP thresholds silently continued to use the default 0.8732.

The pipeline now auto-syncs `config.eur_gbp_rate` with the loaded table:

- If the `fx_rates` input contains exactly one `(currency_from="EUR", currency_to="GBP")` row, the orchestrator replaces `config.eur_gbp_rate` via `config.with_fx_rate(derived_rate)` (which carries only the rate); GBP thresholds are then re-derived from the pack EUR bases × the new rate at read time (`engine/thresholds.py`).
- If the passed-in rate and the table rate differ, a `WARNING` is logged on `rwa_calc.engine.pipeline` naming both values, so the mismatch is visible in the audit trail.
- If the table contains more than one `(EUR, GBP)` row, a `WARNING` is logged on `rwa_calc.engine.fx_rate_sync` and the auto-sync is skipped — the caller's rate stands.
- Under Basel 3.1, this is a no-op (thresholds are GBP-native per PRA PS1/26 Art. 153(4)).

### Opting out

If you want the rate you pass into `CalculationConfig.crr(eur_gbp_rate=...)` to win unconditionally (regardless of the FX table contents), set the `sync_eur_gbp_rate_from_fx_table` flag to `False`:

```python
from dataclasses import replace

config = replace(
    CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
        eur_gbp_rate=Decimal("0.8732"),
    ),
    sync_eur_gbp_rate_from_fx_table=False,
)
```

No `WARNING` is emitted in this mode, and the derived thresholds stay pinned to the rate you supplied.
