# Features

This section documents the key features and algorithms of the RWA calculator.

## Feature Documentation

| Feature | Description |
|---------|-------------|
| [Classification](classification.md) | Exposure classification system - entity types, exposure classes, and the classification algorithm |

## Overview

The RWA calculator implements sophisticated algorithms for credit risk capital calculation. This section provides detailed documentation of these features beyond the basic API and schema documentation.

### Classification

The [classification system](classification.md) is the foundation of the RWA calculation:

- **Entity Type Mapping**: 17 entity types map to SA and IRB exposure classes
- **Dual Class System**: SA and IRB classes tracked separately for regulatory compliance
- **SME/Retail Classification**: Revenue and exposure threshold checks
- **FI Scalar Determination**: Large and unregulated financial sector entity identification
- **Audit Trail**: Full traceability of classification decisions

### Future Documentation

Additional feature documentation planned:

- Credit Risk Mitigation (CRM) waterfall
- IRB formula implementation
- Output floor calculation
- Supporting factor application
