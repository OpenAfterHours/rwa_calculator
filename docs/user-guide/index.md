# User Guide

Welcome to the comprehensive user guide for the UK Credit Risk RWA Calculator. This guide provides detailed information on regulatory frameworks, calculation methodologies, and exposure class treatments.

## Guide Structure

This guide is organized into the following sections:

### Interactive UI

Run calculations without writing code using the web-based interface:

- [**Interactive UI**](interactive-ui.md) - Web-based calculator, results explorer, and regulatory reference

### Regulatory Frameworks

Understand the regulatory requirements that govern RWA calculations:

- [**Overview**](regulatory/index.md) - Introduction to UK credit risk regulations
- [**CRR (Basel 3.0)**](regulatory/crr.md) - Current framework until December 2026
- [**Basel 3.1**](regulatory/basel31.md) - New framework from January 2027
- [**Framework Comparison**](regulatory/comparison.md) - Key differences between frameworks

### Calculation Methodology

Learn how RWA is calculated under different approaches:

- [**Overview**](methodology/index.md) - Introduction to RWA calculation
- [**Standardised Approach**](methodology/standardised-approach.md) - SA calculation methodology
- [**IRB Approach**](methodology/irb-approach.md) - F-IRB and A-IRB methodologies
- [**Specialised Lending**](methodology/specialised-lending.md) - Slotting approach
- [**Credit Risk Mitigation**](methodology/crm.md) - CRM techniques and application
- [**Supporting Factors**](methodology/supporting-factors.md) - SME and infrastructure factors

### Exposure Classes

Understand how different exposures are classified and treated:

- [**Overview**](exposure-classes/index.md) - Exposure classification
- [**Sovereign**](exposure-classes/sovereign.md) - Government and central bank exposures
- [**Institution**](exposure-classes/institution.md) - Bank and investment firm exposures
- [**Corporate**](exposure-classes/corporate.md) - Corporate and SME exposures
- [**Retail**](exposure-classes/retail.md) - Retail mortgage, QRRE, and other retail
- [**Other Classes**](exposure-classes/other.md) - Equity, defaulted, and specialised lending

### Configuration

- [**Configuration Guide**](configuration.md) - How to configure the calculator

## Quick Reference

### Key Formulas

=== "Standardised Approach"

    ```
    RWA = EAD × Risk Weight
    ```

=== "IRB Approach"

    ```
    RWA = K × 12.5 × EAD × MA × [1.06 if CRR]
    ```

    Where K is the capital requirement from the IRB formula.

=== "Slotting"

    ```
    RWA = EAD × Slotting Risk Weight
    ```

### Approach Availability by Exposure Class

| Exposure Class | SA | F-IRB | A-IRB | Slotting |
|----------------|:--:|:-----:|:-----:|:--------:|
| Sovereign | :white_check_mark: | :white_check_mark: | :white_check_mark: | |
| Institution | :white_check_mark: | :white_check_mark: | :white_check_mark: | |
| Corporate | :white_check_mark: | :white_check_mark: | :white_check_mark: | |
| Corporate SME | :white_check_mark: | :white_check_mark: | :white_check_mark: | |
| Retail | :white_check_mark: | | :white_check_mark: | |
| Specialised Lending | :white_check_mark: | | | :white_check_mark: |
| Equity | :white_check_mark: | :white_check_mark: | | |
| Defaulted | :white_check_mark: | :white_check_mark: | :white_check_mark: | |

## For Different Users

### Risk & Audit Teams

Start with:
1. [Interactive UI](interactive-ui.md) - Run calculations without code
2. [Regulatory Frameworks](regulatory/index.md) - Understand the rules
3. [Calculation Methodology](methodology/index.md) - How calculations work
4. [Framework Comparison](regulatory/comparison.md) - CRR vs Basel 3.1 differences

### Business Users

Start with:
1. [Interactive UI](interactive-ui.md) - Run calculations through the web interface
2. [Key Concepts](../getting-started/concepts.md) - Terminology
3. [Exposure Classes](exposure-classes/index.md) - How exposures are classified
4. [Configuration Guide](configuration.md) - Setting up calculations

### Technical Users

See also:
- [Architecture Guide](../architecture/index.md)
- [API Reference](../api/index.md)
- [Data Model](../data-model/index.md)
