# Plan: Corporate-to-Retail Reclassification with Hybrid IRB Permissions

## Problem Statement

A firm has the following IRB approvals:
- **AIRB** for retail exposures (including corporates that qualify as "regulatory retail")
- **FIRB** for corporate exposures

Under CRR Art. 147(5) / Basel CRE30.16-17, corporate exposures CAN be treated as retail ("regulatory retail" or "SME retail") if:
1. Aggregated exposure to the obligor/group < EUR 1m
2. The exposure is managed as part of a retail portfolio (similar risk characteristics)
3. The firm has internal LGD estimates (required for AIRB)

### Current Gaps

1. **`is_managed_as_retail` flag exists but is unused**: The counterparty schema has this flag, and it's joined to exposures (`cp_is_managed_as_retail`), but it's never used in classification logic.

2. **No downward reclassification**: The classifier only reclassifies retail exposures UP to corporate when they exceed the EUR 1m threshold. It does NOT reclassify corporates DOWN to retail.

3. **No hybrid IRB permission**: There's no `IRBPermissions` configuration that grants AIRB for retail and FIRB for corporate simultaneously.

4. **LGD availability check missing**: AIRB requires modelled LGD. If no internal LGD estimate exists, the exposure must use FIRB (supervisory LGD).

---

## Solution Overview

### Reclassification Logic

For a **corporate** exposure to be reclassified to **retail** (and receive AIRB treatment):

| Condition | Field | Check |
|-----------|-------|-------|
| Managed as retail | `cp_is_managed_as_retail` | `= True` |
| Below threshold | `qualifies_as_retail` | `= True` (aggregated < EUR 1m) |
| Has modelled LGD | `lgd` | `IS NOT NULL` |

If **ALL** conditions are met → Reclassify to `RETAIL_OTHER` → AIRB treatment

If **ANY** condition fails → Stays as `CORPORATE` / `CORPORATE_SME` → FIRB treatment

### Expected Outcomes

| Scenario | Exposure Class | Approach | LGD Source |
|----------|---------------|----------|------------|
| Corporate, managed as retail, < EUR 1m, has LGD, **with property collateral** | `RETAIL_MORTGAGE` | AIRB | Modelled |
| Corporate, managed as retail, < EUR 1m, has LGD, **no property collateral** | `RETAIL_OTHER` | AIRB | Modelled |
| Corporate, managed as retail, < EUR 1m, NO LGD | `CORPORATE` | FIRB | Supervisory |
| Corporate, managed as retail, >= EUR 1m | `CORPORATE` | FIRB | Supervisory |
| Corporate, NOT managed as retail | `CORPORATE` | FIRB | Supervisory |
| Retail (individual), < EUR 1m | `RETAIL_OTHER` | AIRB | Modelled |
| Retail (individual), >= EUR 1m | `CORPORATE` | FIRB | Supervisory |

**Note:** Reclassified corporates are NOT eligible for QRRE, even if the facility is revolving.

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/rwa_calc/domain/enums.py` | Add `RETAIL_AIRB_CORPORATE_FIRB` to `IRBApproachOption` |
| `src/rwa_calc/contracts/config.py` | Add `IRBPermissions.retail_airb_corporate_firb()` factory method |
| `src/rwa_calc/engine/classifier.py` | Add downward reclassification logic in `_apply_retail_classification()` |
| `src/rwa_calc/api/models.py` | Add `"retail_airb_corporate_firb"` to `irb_approach` Literal type |
| `src/rwa_calc/api/service.py` | Handle new approach option in `_create_config()` |
| `src/rwa_calc/ui/marimo/rwa_app.py` | Add new option to IRB approach dropdown |
| `tests/unit/test_irb_permissions.py` | Add tests for new factory method |
| `tests/unit/test_classifier.py` | Add tests for downward reclassification |

---

## Implementation Details

### 1. Add Enum Value (`domain/enums.py`)

```python
class IRBApproachOption(Enum):
    # ... existing values ...
    RETAIL_AIRB_CORPORATE_FIRB = "retail_airb_corporate_firb"
```

Update docstring to document the new option.

---

### 2. Add Factory Method (`contracts/config.py`)

```python
@classmethod
def retail_airb_corporate_firb(cls) -> IRBPermissions:
    """
    AIRB for retail, FIRB for corporate.

    Use when firm has:
    - AIRB approval for retail exposures
    - FIRB approval for corporate exposures
    - Ability to reclassify qualifying corporates as regulatory retail

    Corporates can be treated as retail if:
    - Managed as part of retail pool (is_managed_as_retail=True)
    - Aggregated exposure < EUR 1m
    - Has internally modelled LGD
    """
    return cls(
        permissions={
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: {ApproachType.SA, ApproachType.FIRB},
            ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB},
            ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB},
            ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.FIRB},
            ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
            ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
            ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
            ExposureClass.SPECIALISED_LENDING: {ApproachType.SA, ApproachType.SLOTTING, ApproachType.FIRB},
            ExposureClass.EQUITY: {ApproachType.SA},
        }
    )
```

---

### 3. Add Classifier Logic (`engine/classifier.py`)

#### 3a. Add new method `_apply_corporate_to_retail_reclassification()`

Insert after `_apply_retail_classification()` in the pipeline (Step 4a):

```python
def _apply_corporate_to_retail_reclassification(
    self,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Reclassify qualifying corporates to retail for AIRB treatment.

    Per CRR Art. 147(5) / Basel CRE30.16-17, corporate exposures can be
    treated as retail ("regulatory retail") if:
    1. Managed as part of a retail pool (is_managed_as_retail=True)
    2. Aggregated exposure < EUR 1m (qualifies_as_retail=True)
    3. Has internally modelled LGD (lgd IS NOT NULL)

    Reclassification target:
    - With property collateral → RETAIL_MORTGAGE
    - Without property collateral → RETAIL_OTHER
    - NOT eligible for QRRE (even if revolving facility)

    This enables AIRB treatment for small corporates when the firm has
    AIRB approval for retail but only FIRB approval for corporates.
    """
    # Check if this reclassification is relevant
    # Only applies when AIRB is permitted for retail but not for corporate
    airb_for_retail = config.irb_permissions.is_permitted(
        ExposureClass.RETAIL_OTHER, ApproachType.AIRB
    )
    airb_for_corporate = config.irb_permissions.is_permitted(
        ExposureClass.CORPORATE, ApproachType.AIRB
    )

    # If AIRB is permitted for corporate, no need to reclassify
    # If AIRB is not permitted for retail, can't reclassify to get AIRB
    if airb_for_corporate or not airb_for_retail:
        return exposures

    # Add flag for reclassification eligibility
    exposures = exposures.with_columns([
        # Eligible for retail reclassification if ALL conditions met
        pl.when(
            (pl.col("exposure_class").is_in([
                ExposureClass.CORPORATE.value,
                ExposureClass.CORPORATE_SME.value,
            ])) &
            (pl.col("cp_is_managed_as_retail") == True) &
            (pl.col("qualifies_as_retail") == True) &
            (pl.col("lgd").is_not_null())
        ).then(pl.lit(True))
        .otherwise(pl.lit(False))
        .alias("reclassified_to_retail"),
    ])

    # Determine if exposure has property collateral
    # Check residential_collateral_value (from hierarchy) or collateral_type
    exposures = exposures.with_columns([
        pl.when(
            (pl.col("residential_collateral_value") > 0) |
            (pl.col("collateral_type").is_in(["immovable", "residential", "commercial"]))
        ).then(pl.lit(True))
        .otherwise(pl.lit(False))
        .alias("has_property_collateral"),
    ])

    # Reclassify eligible corporates
    # - With property collateral → RETAIL_MORTGAGE
    # - Without property collateral → RETAIL_OTHER
    exposures = exposures.with_columns([
        pl.when(
            (pl.col("reclassified_to_retail") == True) &
            (pl.col("has_property_collateral") == True)
        ).then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
        .when(pl.col("reclassified_to_retail") == True)
        .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
        .otherwise(pl.col("exposure_class"))
        .alias("exposure_class"),
    ])

    return exposures
```

#### 3b. Update `classify()` method

Add Step 4a after Step 4:

```python
# Step 4: Check and apply retail classification (retail → corporate if > threshold)
classified = self._apply_retail_classification(
    classified,
    data.lending_group_totals,
    config,
)

# Step 4a: Check and apply corporate → retail reclassification
# (for qualifying SME corporates with modelled LGD)
classified = self._apply_corporate_to_retail_reclassification(
    classified,
    config,
)
```

#### 3c. Update `_add_classification_audit()`

Add `reclassified_to_retail` to the audit trail:

```python
pl.lit("; reclassified_to_retail="),
pl.col("reclassified_to_retail").cast(pl.String),
```

#### 3d. Update `_build_audit_trail()`

Add column to audit output:

```python
pl.col("reclassified_to_retail"),
```

---

### 4. Update API Models (`api/models.py`)

Update the `irb_approach` field type:

```python
irb_approach: Literal[
    "sa_only", "firb", "airb", "full_irb", "retail_airb_corporate_firb"
] | None = None
```

---

### 5. Update Service (`api/service.py`)

Add handling in `_create_config()`:

```python
elif request.irb_approach == "retail_airb_corporate_firb":
    irb_permissions = IRBPermissions.retail_airb_corporate_firb()
```

---

### 6. Update Marimo UI (`ui/marimo/rwa_app.py`)

Add new option to dropdown:

```python
irb_approach_dropdown = mo.ui.dropdown(
    options={
        "SA Only (No IRB)": "sa_only",
        "Foundation IRB (F-IRB)": "firb",
        "Advanced IRB (A-IRB)": "airb",
        "Full IRB (A-IRB preferred)": "full_irb",
        "Retail A-IRB / Corporate F-IRB": "retail_airb_corporate_firb",
    },
    value="SA Only (No IRB)",
    label="IRB Approach",
)
```

---

## Test Cases

### Unit Tests for IRBPermissions

```python
class TestRetailAIRBCorporateFIRBPermissions:
    """Tests for IRBPermissions.retail_airb_corporate_firb()."""

    def test_airb_permitted_for_retail(self):
        perms = IRBPermissions.retail_airb_corporate_firb()
        assert perms.is_permitted(ExposureClass.RETAIL_OTHER, ApproachType.AIRB)
        assert perms.is_permitted(ExposureClass.RETAIL_MORTGAGE, ApproachType.AIRB)
        assert perms.is_permitted(ExposureClass.RETAIL_QRRE, ApproachType.AIRB)

    def test_firb_permitted_for_corporate(self):
        perms = IRBPermissions.retail_airb_corporate_firb()
        assert perms.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert perms.is_permitted(ExposureClass.CORPORATE_SME, ApproachType.FIRB)

    def test_airb_not_permitted_for_corporate(self):
        perms = IRBPermissions.retail_airb_corporate_firb()
        assert not perms.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)
        assert not perms.is_permitted(ExposureClass.CORPORATE_SME, ApproachType.AIRB)

    def test_firb_not_permitted_for_retail(self):
        perms = IRBPermissions.retail_airb_corporate_firb()
        assert not perms.is_permitted(ExposureClass.RETAIL_OTHER, ApproachType.FIRB)
```

### Unit Tests for Classifier Reclassification

```python
class TestCorporateToRetailReclassification:
    """Tests for corporate → retail reclassification."""

    def test_corporate_with_property_collateral_becomes_retail_mortgage(self):
        """Corporate with property collateral → RETAIL_MORTGAGE."""
        # Setup: Corporate with managed_as_retail, < EUR 1m, LGD, property collateral
        # Assert: exposure_class = RETAIL_MORTGAGE
        # Assert: reclassified_to_retail = True
        # Assert: approach = AIRB

    def test_corporate_without_property_collateral_becomes_retail_other(self):
        """Corporate without property collateral → RETAIL_OTHER."""
        # Setup: Corporate with managed_as_retail, < EUR 1m, LGD, no property collateral
        # Assert: exposure_class = RETAIL_OTHER
        # Assert: reclassified_to_retail = True
        # Assert: approach = AIRB

    def test_corporate_not_reclassified_when_not_managed_as_retail(self):
        """Corporate without managed_as_retail flag stays as CORPORATE."""
        # Assert: exposure_class remains CORPORATE
        # Assert: reclassified_to_retail = False
        # Assert: approach = FIRB

    def test_corporate_not_reclassified_when_exceeds_threshold(self):
        """Corporate > EUR 1m stays as CORPORATE even if managed as retail."""
        # Assert: exposure_class remains CORPORATE
        # Assert: approach = FIRB

    def test_corporate_not_reclassified_when_no_lgd(self):
        """Corporate without modelled LGD stays as CORPORATE."""
        # Assert: exposure_class remains CORPORATE
        # Assert: approach = FIRB (uses supervisory LGD)

    def test_corporate_sme_with_property_becomes_retail_mortgage(self):
        """CORPORATE_SME with property collateral → RETAIL_MORTGAGE."""
        # Assert: exposure_class = RETAIL_MORTGAGE

    def test_reclassified_corporate_not_eligible_for_qrre(self):
        """Reclassified corporate never becomes QRRE even if revolving."""
        # Setup: Corporate with revolving facility, meeting all reclassification criteria
        # Assert: exposure_class = RETAIL_OTHER (not QRRE)

    def test_reclassification_only_when_airb_retail_firb_corporate(self):
        """Reclassification only applies with hybrid permissions."""
        # With full_irb: No reclassification needed (AIRB available for corporate)
        # With firb_only: No reclassification (AIRB not available for retail)
```

### Integration Test

```python
class TestHybridIRBApproachIntegration:
    """Integration tests for retail AIRB / corporate FIRB scenario."""

    def test_mixed_portfolio_correct_approach_assignment(self):
        """
        Portfolio with:
        - Corporate < EUR 1m, managed as retail, has LGD, property collateral → RETAIL_MORTGAGE, AIRB
        - Corporate < EUR 1m, managed as retail, has LGD, no property collateral → RETAIL_OTHER, AIRB
        - Corporate < EUR 1m, managed as retail, NO LGD → CORPORATE, FIRB
        - Corporate >= EUR 1m, managed as retail → CORPORATE, FIRB
        - Corporate, NOT managed as retail → CORPORATE, FIRB
        - Retail individual < EUR 1m → RETAIL_OTHER, AIRB
        """
        pass
```

---

## Implementation Sequence

1. Add `RETAIL_AIRB_CORPORATE_FIRB` to `IRBApproachOption` enum
2. Add `retail_airb_corporate_firb()` factory method to `IRBPermissions`
3. Update `contracts/__init__.py` exports (if needed)
4. Add `_apply_corporate_to_retail_reclassification()` method to classifier
5. Update `classify()` to call new method
6. Update classification audit trail
7. Update `irb_approach` Literal type in `api/models.py`
8. Update `_create_config()` in `api/service.py`
9. Update Marimo UI dropdown
10. Add unit tests for permissions
11. Add unit tests for classifier reclassification
12. Run full test suite to verify no regressions

---

## Verification

### Manual Testing

1. Run Marimo app: `uv run marimo run src/rwa_calc/ui/marimo/rwa_app.py`
2. Select "Retail A-IRB / Corporate F-IRB" from dropdown
3. Run calculation on test data with:
   - Corporate exposures with `is_managed_as_retail=True`, < EUR 1m, with LGD
   - Corporate exposures with `is_managed_as_retail=True`, < EUR 1m, without LGD
4. Verify:
   - First group: `exposure_class=retail_other`, `approach=advanced_irb`
   - Second group: `exposure_class=corporate`, `approach=foundation_irb`

### Columns to Check in Results

| Column | Reclassified (with property) | Reclassified (no property) | Not reclassified |
|--------|------------------------------|---------------------------|------------------|
| `exposure_class` | `retail_mortgage` | `retail_other` | `corporate` / `corporate_sme` |
| `approach` | `advanced_irb` | `advanced_irb` | `foundation_irb` |
| `reclassified_to_retail` | `True` | `True` | `False` |
| `has_property_collateral` | `True` | `False` | N/A |
| `lgd_type` | `modelled` | `modelled` | `supervisory` |

---

## Regulatory References

- **CRR Art. 147(5)**: Exposures to small businesses may be treated as retail if aggregated exposure < EUR 1m
- **CRR Art. 123**: Retail exposure criteria including EUR 1m threshold
- **Basel CRE30.16-17**: Retail exposure definition and eligibility criteria
- **CRR Art. 163**: A-IRB requires internal LGD estimates
- **CRR Art. 161**: F-IRB uses supervisory LGD values

---

## Design Decisions (Confirmed)

1. **QRRE eligibility**: Reclassified corporates are **NOT** eligible for QRRE classification, even if the facility is revolving.

2. **Property collateral treatment**: If the reclassified corporate exposure is secured by property collateral, classify as `RETAIL_MORTGAGE` (not `RETAIL_OTHER`).

3. **Audit trail**: No need to track original exposure class. The `reclassified_to_retail` flag is sufficient.
