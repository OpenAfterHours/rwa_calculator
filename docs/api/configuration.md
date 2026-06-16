# Configuration API

The configuration module provides immutable dataclasses for controlling calculation
behavior. All configurations are frozen (`@dataclass(frozen=True)`) and use factory
methods for self-documenting creation.

## Module: `rwa_calc.contracts.config`

### `PolarsEngine`

```python
PolarsEngine = Literal["cpu", "gpu", "streaming"]
```

Type alias controlling the Polars collection engine. `"streaming"` (default) processes
in batches for lower memory usage; `"cpu"` loads everything into memory.

### `CalculationConfig`

Master configuration for RWA calculations. Bundles all framework-specific settings.
Use factory methods `.crr()` and `.basel_3_1()` instead of constructing directly.

```python
@dataclass(frozen=True)
class CalculationConfig:
    """
    Attributes:
        regime_id: Regime identifier ("crr" | "b31") — the regime carrier.
        reporting_date: As-of date for the calculation.
        base_currency: Currency for reporting (default "GBP").
        apply_fx_conversion: Whether to convert exposures to base_currency.
        output_floor: Output floor configuration.
        post_model_adjustments: Post-model adjustments (Basel 3.1 only).
        permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing).
        use_investment_grade_assessment: Art. 122(6) election — IG=65% / non-IG=135%.
        eur_gbp_rate: EUR/GBP exchange rate for monetary-threshold conversion.
        collect_engine: Polars engine for .collect() — "cpu" (default).
    """

    regime_id: str  # "crr" | "b31" — the regime carrier
    reporting_date: date
    base_currency: str = "GBP"
    apply_fx_conversion: bool = True
    output_floor: OutputFloorConfig = field(default_factory=OutputFloorConfig.crr)
    post_model_adjustments: PostModelAdjustmentConfig = field(
        default_factory=PostModelAdjustmentConfig.crr
    )
    ccr: CCRConfig = field(default_factory=CCRConfig)
    permission_mode: PermissionMode = PermissionMode.STANDARDISED
    irb_permissions: IRBPermissions | None = None
    equity_transitional: EquityTransitionalConfig = field(default_factory=EquityTransitionalConfig)
    eur_gbp_rate: Decimal = Decimal("0.8732")
    enable_double_default: bool = False
    use_investment_grade_assessment: bool = False
    crm_collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE
    airb_collateral_method: AIRBCollateralMethod | None = None
    collect_engine: PolarsEngine = "cpu"
    spill_edges: bool = False
    spill_dir: Path | None = None
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    audit_cache_dir: Path | None = None
    audit_cache_max_runs: int | None = None
```

!!! note "Regulatory values live in the rulepack, not in config"
    `CalculationConfig` carries firm inputs and elections only. PD/LGD floors,
    supporting factors, monetary thresholds and the 1.06 IRB scaling factor are
    **not** config fields — they are cited entries in the rulepack packs
    (`rwa_calc.rulebook.packs.{common,crr,b31}`) resolved via
    `rwa_calc.rulebook.resolve.resolve(regime_id, reporting_date)`. `regime_id`
    is the carrier; `framework` / `is_crr` / `is_basel_3_1` survive as derived
    read-only properties.

#### Properties

```python
    @property
    def is_crr(self) -> bool:
        """Check if using CRR framework."""

    @property
    def is_basel_3_1(self) -> bool:
        """Check if using Basel 3.1 framework."""

    def get_output_floor_percentage(self) -> Decimal:
        """Get the applicable output floor percentage for the reporting date."""
```

#### Factory Methods

```python
    @classmethod
    def crr(
        cls,
        reporting_date: date,
        permission_mode: PermissionMode = PermissionMode.STANDARDISED,
        eur_gbp_rate: Decimal = Decimal("0.8732"),
        enable_double_default: bool = False,
        crm_collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE,
        collect_engine: PolarsEngine = "cpu",
        spill_dir: Path | None = None,
        log_level: str = "INFO",
        log_format: Literal["text", "json"] = "text",
    ) -> CalculationConfig:
        """
        Create CRR (Basel 3.0) configuration.

        CRR characteristics (these regulatory values resolve from the CRR
        rulepack pack, not from config fields):
        - Single PD floor (0.03%) for all classes
        - No LGD floors for A-IRB
        - SME supporting factor (0.7619/0.85)
        - Infrastructure supporting factor (0.75)
        - No output floor
        - 1.06 scaling factor for IRB K
        - Optional double-default treatment (Art. 153(3), 202)
        """

    @classmethod
    def basel_3_1(
        cls,
        reporting_date: date,
        permission_mode: PermissionMode = PermissionMode.STANDARDISED,
        post_model_adjustments: PostModelAdjustmentConfig | None = None,
        use_investment_grade_assessment: bool = False,
        institution_type: InstitutionType | None = None,
        reporting_basis: ReportingBasis | None = None,
        gcra_amount: float = 0.0,
        sa_t2_credit: float = 0.0,
        art_40_deductions: float = 0.0,
        skip_transitional_floor: bool = False,
        crm_collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE,
        airb_collateral_method: AIRBCollateralMethod = AIRBCollateralMethod.LGD_MODELLING,
        collect_engine: PolarsEngine = "cpu",
        spill_dir: Path | None = None,
        log_level: str = "INFO",
        log_format: Literal["text", "json"] = "text",
    ) -> CalculationConfig:
        """
        Create Basel 3.1 (PRA PS1/26) configuration.

        Basel 3.1 characteristics:
        - Differentiated PD floors by exposure class
        - LGD floors for A-IRB by collateral type
        - No supporting factors
        - Output floor (72.5%, transitional from 60% in 2027)
        - 1.06 scaling factor removed
        """
```

The full keyword list for each factory:

| Argument | `crr()` | `basel_3_1()` | Knob it controls |
|---|---|---|---|
| `reporting_date` | required | required | as-of date |
| `permission_mode` | yes | yes | SA-only vs IRB routing |
| `eur_gbp_rate` | yes | n/a (GBP-native) | CRR EUR-threshold FX |
| `enable_double_default` | yes | n/a (Art. 153(3) blanked) | CRR Art. 153(3) — see [`enable_double_default`](#enable_double_default) |
| `use_investment_grade_assessment` | n/a | yes | Art. 122(6)/(8) — see [`use_investment_grade_assessment`](#use_investment_grade_assessment) |
| `crm_collateral_method` | yes | yes | Art. 191A SA financial collateral — see [`crm_collateral_method`](#crm_collateral_method) |
| `airb_collateral_method` | n/a | yes | Art. 169A/169B A-IRB collateral — see [`airb_collateral_method`](#airb_collateral_method) |
| `post_model_adjustments` | n/a | yes | Art. 153(5A)/154(4A)/158(6A) PMAs |
| `institution_type` | n/a | yes | Art. 92 para 2A floor applicability |
| `reporting_basis` | n/a | yes | Art. 92 para 2A floor applicability |
| `gcra_amount` / `sa_t2_credit` / `art_40_deductions` | n/a | yes | OF-ADJ inputs (Art. 92 para 2A) |
| `skip_transitional_floor` | n/a | yes | Art. 92 para 5 — bypass 60/65/70% phase-in |
| `collect_engine` / `spill_dir` | yes | yes | Polars engine |
| `log_level` / `log_format` | yes | yes | observability |

#### Factory Overrides — Worked Examples

The factories return a fully-configured `CalculationConfig`; pass keyword
overrides to flip a knob on one factory call rather than constructing the
config by hand. For knobs that the factory does **not** expose (e.g. equity
transitionals, raw `output_floor` field swaps), use `dataclasses.replace`
on the returned config — see [Replace-based overrides](#replace-based-overrides)
below.

##### CRR — toggle double-default and the SA financial collateral method

```python
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod, PermissionMode

# CRR baseline with Art. 153(3) double-default *and* the Art. 222 simple
# financial collateral method on the SA leg, plus a non-default EUR/GBP
# rate for retail / SME threshold conversion.
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    permission_mode=PermissionMode.IRB,
    eur_gbp_rate=Decimal("0.8800"),
    enable_double_default=True,                              # Art. 153(3)
    crm_collateral_method=CRMCollateralMethod.SIMPLE,        # Art. 222 (SA-only)
    log_format="json",                                       # audit-ready logs
)

assert config.is_crr
assert config.enable_double_default is True
assert config.crm_collateral_method is CRMCollateralMethod.SIMPLE
```

See the per-knob sections for regulatory derivation:
[`enable_double_default`](#enable_double_default),
[`crm_collateral_method`](#crm_collateral_method).

##### Basel 3.1 — Art. 122(6)/(8) IG assessment + Foundation A-IRB collateral + skip-transitional floor

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import (
    AIRBCollateralMethod,
    CRMCollateralMethod,
    InstitutionType,
    PermissionMode,
    ReportingBasis,
)

# Stand-alone UK IRB firm, individual basis, electing:
# - Art. 122(6)(b)/(8)(b) IG vs non-IG split for unrated corporates
# - Art. 191A Part 2 / Art. 169A election to use the Foundation
#   Collateral Method on the A-IRB book
# - Art. 222 Simple Method on the SA financial collateral book
# - Art. 92 para 5 voluntary skip of the 60/65/70% transitional → 72.5%
#   from day one
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    permission_mode=PermissionMode.IRB,
    use_investment_grade_assessment=True,                          # Art. 122(6)/(8)
    airb_collateral_method=AIRBCollateralMethod.FOUNDATION,        # Art. 169A
    crm_collateral_method=CRMCollateralMethod.SIMPLE,              # Art. 222
    institution_type=InstitutionType.STANDALONE_UK,                # Art. 92 para 2A(a)(i)
    reporting_basis=ReportingBasis.INDIVIDUAL,
    skip_transitional_floor=True,                                  # Art. 92 para 5
)

assert config.is_basel_3_1
assert config.use_investment_grade_assessment is True
assert config.airb_collateral_method is AIRBCollateralMethod.FOUNDATION
assert config.crm_collateral_method is CRMCollateralMethod.SIMPLE
assert config.output_floor.is_floor_applicable() is True
assert config.get_output_floor_percentage() == Decimal("0.725")    # phased-in from day one
```

See the per-knob sections for regulatory derivation:
[`use_investment_grade_assessment`](#use_investment_grade_assessment),
[`airb_collateral_method`](#airb_collateral_method),
[`crm_collateral_method`](#crm_collateral_method).

##### Replace-based overrides

A small number of genuine config fields are not exposed as factory keywords
(e.g. `equity_transitional`, the raw `output_floor` dataclass,
`apply_fx_conversion`, `sync_eur_gbp_rate_from_fx_table`). For test harnesses
or research workflows that need to swap one of these, build the config from
the factory and use `dataclasses.replace`:

```python
from dataclasses import replace
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))

# Adjust the EUR/GBP rate used for monetary-threshold conversion without
# disturbing any other framework defaults.
config = replace(config, eur_gbp_rate=Decimal("0.8800"))

assert config.eur_gbp_rate == Decimal("0.8800")
```

`replace(...)` returns a new frozen instance — the original config is
untouched, preserving the immutability contract.

!!! note "Regulatory values are not config fields"
    To vary a regulatory value (PD/LGD floors, supporting factors, monetary
    thresholds, the IRB scaling factor) you author or override a **rulepack
    pack** entry, not a config field — these resolve from the resolved
    rulepack (`rwa_calc.rulebook.resolve.resolve(regime_id, reporting_date)`),
    not from `CalculationConfig`.

!!! note "PD floors, LGD floors and supporting factors live in the rulepack"
    The former `PDFloors`, `LGDFloors` and `SupportingFactors` config
    dataclasses were removed in Phase 5. PD floors (CRR Art. 163 single 0.03%;
    Basel 3.1 differentiated, CRE30.55), A-IRB LGD floors (CRE30.41) and the
    CRR SME/infrastructure supporting factors (Art. 501/501a) are now cited
    entries in the rulepack packs
    (`rwa_calc.rulebook.packs.{common,crr,b31}`) resolved via
    `rwa_calc.rulebook.resolve.resolve(regime_id, reporting_date)`. To vary one
    of these values, author or override a pack entry — not a config field.

### `OutputFloorConfig`

Output floor configuration for Basel 3.1. The output floor (CRE99.1-8, PS1/26 Ch.12)
requires IRB RWAs to be at least 72.5% of the equivalent SA RWAs.

```python
@dataclass(frozen=True)
class OutputFloorConfig:
    enabled: bool = False
    floor_percentage: Decimal = Decimal("0.725")  # 72.5%
    transitional_start_date: date | None = None
    transitional_end_date: date | None = None
    transitional_floor_schedule: dict[date, Decimal] = field(default_factory=dict)

    def get_floor_percentage(self, calculation_date: date) -> Decimal:
        """Get the applicable floor percentage for a given date.

        Returns 0% if floor is disabled or the calculation date precedes
        the transitional start date (PS1/26: 1 Jan 2027 for UK firms).

        Transitional schedule:
        PRA compressed schedule (4-year, not BCBS 6-year):
        - 2027: 60%
        - 2028: 65%
        - 2029: 70%
        - 2030+: 72.5%
        """

    @classmethod
    def crr(cls) -> OutputFloorConfig:
        """CRR: No output floor."""

    @classmethod
    def basel_3_1(cls) -> OutputFloorConfig:
        """Basel 3.1 output floor with PRA transitional schedule."""
```

!!! note "Retail thresholds live in the rulepack"
    The former `RetailThresholds` config dataclass was removed in Phase 5. The
    retail-qualification monetary thresholds (CRR EUR 1m / EUR 100k QRRE,
    converted to GBP; Basel 3.1 GBP-native) are now cited rulepack entries
    (EUR base) resolved from the pack via
    `rwa_calc.rulebook.resolve.resolve(regime_id, reporting_date)` and scaled by
    `eur_gbp_rate` at read time (`engine/thresholds.py`).

### `PermissionMode`

High-level permission mode controlling whether the firm uses SA for all
exposures or routes exposures to IRB based on model-level permissions.

```python
class PermissionMode(StrEnum):
    STANDARDISED = "standardised"
    IRB = "irb"
```

| Mode | Behaviour |
|------|-----------|
| `STANDARDISED` | All exposures use the Standardised Approach. No IRB routing. |
| `IRB` | Approach routing is driven by the `model_permissions` input table. Each model's approved approach (AIRB, FIRB, slotting) is resolved per-exposure. Exposures without a matching model permission fall back to SA. If no `model_permissions` file is provided, **all exposures fall back to SA** with a warning. |

!!! note "Model permissions required for IRB mode"
    When `permission_mode=PermissionMode.IRB`, the calculator requires
    `model_permissions` input data to determine which exposures use FIRB,
    AIRB, or slotting. Without it, the pipeline falls back to SA for all
    exposures and emits a warning. See
    [Input Schemas — Model Permissions](../data-model/input-schemas.md#model-permissions-schema).

### `enable_double_default`

| Field | Type | Default | Defined on |
|-------|------|---------|-----------|
| `enable_double_default` | `bool` | `False` | `CalculationConfig` (`contracts/config.py:832`) |

Enables the CRR Art. 153(3) double-default risk-weight formula for IRB
exposures covered by eligible unfunded credit protection. When `True`,
the protected portion of an IRB exposure attracts the scaled
double-default capital charge

```
K_dd = K_obligor × (0.15 + 160 × PD_guarantor)
```

instead of the standard guarantee-substitution treatment. Eligibility for
the protection provider follows CRR Art. 202 (institutions, investment
firms, insurance undertakings, export credit agencies meeting the CQS
threshold) and the operational requirements of Art. 217.

!!! warning "CRR-only — removed under Basel 3.1"
    PRA PS1/26 blanks Art. 153(3), Art. 202, and Art. 217. Setting
    `enable_double_default=True` only takes effect under the CRR
    framework; under `CalculationConfig.basel_3_1(...)` the flag is
    inert because the double-default treatment is removed. See the
    [A-IRB Specification — double-default removal](../specifications/basel31/airb-calculation.md#double-default-removal).

The factory method `CalculationConfig.crr()` accepts this knob directly:

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode

config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    permission_mode=PermissionMode.IRB,
    enable_double_default=True,  # Art. 153(3) double-default treatment
)

assert config.enable_double_default is True
```

For the regulatory derivation of the formula, eligibility criteria, and a
worked example, see:

- [User guide — CRM Double Default](../user-guide/methodology/crm.md#double-default-crr-only)
- [CRR Specification — Credit Risk Mitigation](../specifications/crr/credit-risk-mitigation.md)

### `use_investment_grade_assessment`

| Field | Type | Default | Defined on |
|-------|------|---------|-----------|
| `use_investment_grade_assessment` | `bool` | `False` | `CalculationConfig` (`contracts/config.py:833`) |

Enables the PRA PS1/26 **Art. 122(6)** investment-grade / non-investment-grade
split for unrated non-SME corporate exposures under the Basel 3.1 SA. When
`True`, an unrated corporate that the firm has internally assessed as
investment grade (`cp_is_investment_grade = True` on the counterparty input
table) attracts a **65%** risk weight (Art. 122(6)(a)); an unrated corporate
assessed as non-investment grade attracts **135%** (Art. 122(6)(b)). When
`False` (default) every unrated non-SME corporate attracts the Art. 122(5)
default of **100%**.

Under **Art. 122(8)** the same election also drives the SA-equivalent risk
weight used in the *S-TREA leg* of the Art. 92(2A) output floor. An IRB
firm that has set `use_investment_grade_assessment=True` automatically uses
the 65%/135% split in S-TREA (Art. 122(8)(b)); an IRB firm that has left it
`False` uses the flat 100% S-TREA treatment (Art. 122(8)(a)). The Art. 122(11)
SME carve-out (85%) overrides both branches regardless of the flag.

!!! warning "Basel 3.1 only — flag absent from `CalculationConfig.crr()`"
    The factory `CalculationConfig.crr(...)` does **not** expose
    `use_investment_grade_assessment`; the Art. 122(6)/(8) sub-categories are
    Basel 3.1 additions that have no analogue in the CRR Art. 122 corporate
    table (CQS-only, with unrated = 100%). The field exists on the underlying
    `CalculationConfig` dataclass for both frameworks, but is silently inert
    under the CRR SA path — only the Basel 3.1 SA path consumes it
    (`engine/sa/risk_weights.py`).

!!! note "PRA permission and notification obligations"
    Branch (b) — i.e. setting this flag to `True` — requires **prior PRA
    permission** under Art. 122(6) plus the sound-processes obligation in
    Art. 122(7). For an IRB firm the additional Art. 122(8)(b) final sentence
    requires the firm to **give notice to the PRA** both when it starts and
    when it ceases applying the (b) treatment to S-TREA. The calculator does
    not enforce either obligation — it is the operator's responsibility to
    confirm permission before flipping the flag.

The factory method `CalculationConfig.basel_3_1()` accepts this knob directly:

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode

config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    permission_mode=PermissionMode.IRB,
    use_investment_grade_assessment=True,  # Art. 122(6)/(8) IG=65% / non-IG=135%
)

assert config.use_investment_grade_assessment is True
```

For the regulatory derivation, S-TREA interaction, scope of the election,
and worked examples, see:

- [Basel 3.1 SA Risk Weights — Corporate Sub-Categories (Art. 122(4)–(11))](../specifications/basel31/sa-risk-weights.md#corporate-sub-categories-art-122411)
- [Basel 3.1 SA Risk Weights — Output-Floor Election for Unrated Corporates (Art. 122(7)–(8))](../specifications/basel31/sa-risk-weights.md#output-floor-election-for-unrated-corporates-art-12278)
- [Blog — The Output Floor and Why Basel 3.1 Bites](../blog/2026-06-23-the-output-floor-and-why-basel-31-bites.md#the-art-1228-election)

### `crm_collateral_method`

| Field | Type | Default | Defined on |
|-------|------|---------|-----------|
| `crm_collateral_method` | `CRMCollateralMethod` | `CRMCollateralMethod.COMPREHENSIVE` | `CalculationConfig` (`contracts/config.py:838`) |

Firm-wide election under **CRR Art. 191A / PRA PS1/26 Art. 191A** for how
financial collateral is recognised under the **Standardised Approach**. The
choice applies to all SA exposures and cannot be made on a per-exposure basis.
IRB exposures always use the Foundation Collateral Method regardless of this
flag.

The enum lives in `rwa_calc.domain.enums`:

```python
class CRMCollateralMethod(StrEnum):
    COMPREHENSIVE = "comprehensive"  # FCCM — Art. 223-224 (default)
    SIMPLE = "simple"                # FCSM — Art. 222 (SA-only, 20% RW floor)
```

| Member | String value | Treatment | Regulatory basis |
|--------|--------------|-----------|------------------|
| `COMPREHENSIVE` | `"comprehensive"` | **Financial Collateral Comprehensive Method (FCCM).** Reduces EAD via supervisory haircuts (`H_c`, `H_fx`, maturity-mismatch). Applicable to both SA and IRB. | CRR Art. 223 (volatility adjustments), Art. 224 (own-estimate haircuts) |
| `SIMPLE` | `"simple"` | **Financial Collateral Simple Method (FCSM).** SA-only. Substitutes the collateral's own SA risk weight on the secured portion, subject to a **20% floor**. EAD is **not** reduced. Special 0% RW for same-currency cash deposits and 0%-RW sovereign bonds. | CRR Art. 222 |

**Defaults by factory method:**

| Factory | Default value |
|---------|---------------|
| `CalculationConfig.crr(...)` | `CRMCollateralMethod.COMPREHENSIVE` (factory default) |
| `CalculationConfig.basel_3_1(...)` | `CRMCollateralMethod.COMPREHENSIVE` (factory default) |

Both factories expose this knob as a constructor keyword. Pass the enum
directly to elect the Simple Method:

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod

config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    crm_collateral_method=CRMCollateralMethod.SIMPLE,  # Art. 222 (FCSM)
)

assert config.crm_collateral_method is CRMCollateralMethod.SIMPLE
```

!!! note "Election scope"
    Art. 191A makes this a **firm-wide** election. The calculator treats the
    config field accordingly: the same value is applied to every SA exposure
    in the run. Switching mid-run requires constructing a new config.

For the regulatory derivation and worked examples, see:

- [CRR Specification — Credit Risk Mitigation](../specifications/crr/credit-risk-mitigation.md)
- [User guide — CRM methodology](../user-guide/methodology/crm.md)

### `airb_collateral_method`

| Field | Type | Default | Defined on |
|-------|------|---------|-----------|
| `airb_collateral_method` | `AIRBCollateralMethod \| None` | `None` | `CalculationConfig` (`contracts/config.py:843`) |

Election for how A-IRB firms recognise collateral in their LGD estimates under
**Basel 3.1** (PRA PS1/26 Art. 169A / 169B). Under CRR, A-IRB collateral
recognition is free-form (no method constraint), so this field is `None` and
inert under `CalculationConfig.crr(...)`. Art. 191A Part 2 governs the choice
under Basel 3.1.

The enum lives in `rwa_calc.domain.enums`:

```python
class AIRBCollateralMethod(StrEnum):
    LGD_MODELLING = "lgd_modelling"  # Art. 169A (default under B31)
    FOUNDATION = "foundation"        # Art. 229-231 (supervisory LGDS/LGDU)
```

| Member | String value | Treatment | Regulatory basis |
|--------|--------------|-----------|------------------|
| `LGD_MODELLING` | `"lgd_modelling"` | **LGD Modelling Collateral Method.** Default for A-IRB under Basel 3.1. The firm models collateral effects directly in its own LGD estimates. Where data is sufficient (Art. 169A(1)(a)) the modelled LGD is kept; where data is insufficient (Art. 169B), the calculator falls back to the Foundation formula (Art. 230 / 231) using the firm's own unsecured LGD as `LGDU` instead of the supervisory value. | PRA PS1/26 Art. 169A, Art. 169B |
| `FOUNDATION` | `"foundation"` | **Foundation Collateral Method.** A-IRB firm elects to use the same Foundation Collateral Method as F-IRB, with supervisory `LGDS` and supervisory `LGDU`. Same formula and parameters as F-IRB collateral recognition. | CRR Art. 229, Art. 230, Art. 231; PRA PS1/26 Art. 191A Part 2 |
| `None` | — | Field unset. Used by `CalculationConfig.crr(...)` because A-IRB collateral recognition is free-form under CRR — no method constraint applies. | CRR (no equivalent of Art. 191A Part 2) |

**Defaults by factory method:**

| Factory | Default value |
|---------|---------------|
| `CalculationConfig.crr(...)` | `None` (dataclass default — A-IRB is free-form under CRR; not exposed as a `crr()` keyword) |
| `CalculationConfig.basel_3_1(...)` | `AIRBCollateralMethod.LGD_MODELLING` (factory default — Art. 169A) |

`CalculationConfig.basel_3_1(...)` exposes this knob as a constructor
keyword. To elect the Foundation Collateral Method instead of the Art. 169A
LGD-modelling default, pass it directly to the factory:

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import AIRBCollateralMethod, PermissionMode

config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    permission_mode=PermissionMode.IRB,
    airb_collateral_method=AIRBCollateralMethod.FOUNDATION,  # Art. 169A election → Foundation
)

assert config.airb_collateral_method is AIRBCollateralMethod.FOUNDATION
```

!!! warning "Basel 3.1 only — inert under CRR"
    `airb_collateral_method` only takes effect under
    `CalculationConfig.basel_3_1(...)`. Under CRR, A-IRB collateral
    recognition has no statutory method constraint (Art. 181 / Art. 183
    govern own-estimate LGD with no Art. 191A Part 2 overlay), so the
    calculator ignores the field. Setting it on a CRR config is allowed
    for round-tripping but has no calculation effect.

For the regulatory derivation, fallback mechanics, and worked examples, see:

- [Basel 3.1 A-IRB Specification](../specifications/basel31/airb-calculation.md)
- [User guide — CRM methodology](../user-guide/methodology/crm.md)

## Usage Examples

### CRR Configuration

```python
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode

# SA-only CRR configuration (default)
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
)

# CRR with IRB routing (requires model_permissions input data)
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    permission_mode=PermissionMode.IRB,
)

# Access configuration
print(f"Regime: {config.regime_id}")             # "crr"
print(f"Framework: {config.framework}")          # RegulatoryFramework.CRR (derived property)
print(f"Is CRR: {config.is_crr}")                # True (derived property)
```

!!! note "Regulatory values resolve from the rulepack"
    The 1.06 IRB scaling factor and the SME/infrastructure supporting factors
    are no longer config attributes. They are cited rulepack entries — read
    them via `rwa_calc.rulebook.resolve.resolve(config.regime_id,
    config.reporting_date)`, not from `config`.

### Basel 3.1 Configuration

```python
# Basel 3.1 with IRB routing (auto-calculates output floor from reporting_date)
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    permission_mode=PermissionMode.IRB,
)

# Check output floor percentage (transitional for 2027 = 60%)
floor = config.get_output_floor_percentage()
print(f"Output floor: {floor:.0%}")  # 60%

# Fully phased-in (2030+)
config = CalculationConfig.basel_3_1(
    reporting_date=date(2030, 1, 1),
    permission_mode=PermissionMode.IRB,
)
floor = config.get_output_floor_percentage()
print(f"Output floor: {floor:.1%}")  # 72.5%
```

### Accessing Floors

PD/LGD floors, the IRB scaling factor and supporting factors are no longer
config attributes — they resolve from the rulepack pack. Resolve the pack for
the run's regime and reporting date, then read the floor/factor entries from
the resolved rulepack:

```python
from rwa_calc.rulebook.resolve import resolve

# Resolve the frozen, content-hashed rulepack for this run.
pack = resolve(config.regime_id, config.reporting_date)

# PD/LGD floors, supporting factors and the IRB scaling factor are cited
# entries on the resolved pack (read via the pack's entry accessors), not
# attributes on `config`.
```

### Permission Mode

```python
from rwa_calc.domain.enums import PermissionMode

# SA-only — all exposures use standardised approach
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    permission_mode=PermissionMode.STANDARDISED,  # default
)

# IRB mode — model_permissions input data drives approach routing
# Each exposure is matched to its model's approved approach (AIRB, FIRB, slotting)
# Exposures without a model permission fall back to SA
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    permission_mode=PermissionMode.IRB,
)
```

## Related

- [Pipeline API](pipeline.md)
- [Contracts API](contracts.md)
- [Engine API](engine.md)
- [Framework Comparison](../framework-comparison/index.md)
