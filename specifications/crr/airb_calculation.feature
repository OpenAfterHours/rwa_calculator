@crr @irb @airb
Feature: CRR Advanced IRB Calculation
  As a bank with A-IRB permission calculating RWA under CRR
  I need to calculate RWA using internal PD, LGD, and CCF estimates
  So that my capital requirements comply with CRR Articles 153-154

  Background:
    Given the regulatory framework is "CRR"
    And the calculation approach is "A-IRB"

  # =============================================================================
  # Internal LGD Estimates (CRR Art. 161)
  # =============================================================================

  @CRR-C1
  Scenario: A-IRB uses bank's internal LGD estimate
    Given a counterparty "CORP_AIRB_001" with internal PD of 1.00%
    And the bank's internal LGD estimate is 35%
    And a loan "LOAN_AIRB_001" with drawn amount £5,000,000
    And the effective maturity is 2.5 years
    When the A-IRB RWA is calculated
    Then the internal LGD of 35% should be used
    And the RWA should be lower than equivalent F-IRB with 45% LGD

  @CRR-C2
  Scenario: A-IRB LGD estimate for secured exposure
    Given a counterparty with internal PD of 1.00%
    And the bank's internal LGD estimate is 20%
    And a loan secured by eligible collateral
    And drawn amount is £3,000,000
    When the A-IRB RWA is calculated
    Then the internal LGD of 20% should be used
    And the collateral benefit should be reflected in lower LGD

  Scenario: A-IRB with no LGD floors under CRR
    Given a counterparty with internal PD of 1.00%
    And the bank's internal LGD estimate is 5%
    And a loan fully secured by financial collateral
    When the A-IRB RWA is calculated
    Then the internal LGD of 5% should be used
    And no LGD floor should be applied under CRR

  # =============================================================================
  # A-IRB CCF (CRR Art. 166)
  # =============================================================================

  @CRR-C3
  Scenario: A-IRB uses bank's modelled CCF
    Given a facility with limit £10,000,000
    And drawn amount is £2,000,000
    And undrawn amount is £8,000,000
    And the bank's internal CCF estimate is 65%
    When the A-IRB EAD is calculated
    Then the internal CCF of 65% should be used
    And EAD should be £2,000,000 + (£8,000,000 × 65%) = £7,200,000

  Scenario: A-IRB CCF must be within regulatory bounds
    Given a facility with undrawn commitment
    And the bank's internal CCF estimate is provided
    When the A-IRB EAD is calculated
    Then the CCF should be between 0% and 100%
    And CCF values outside this range should be rejected

  # =============================================================================
  # Correlation with FI Scalar (CRR Art. 153(2))
  # =============================================================================

  @CRR-C4
  Scenario: Large financial institution receives 1.25 correlation multiplier
    Given a counterparty of type "CREDIT_INSTITUTION"
    And the counterparty total assets exceed €70 billion
    And the counterparty is classified as a large financial sector entity
    And internal PD is 0.50%
    When the A-IRB correlation is calculated
    Then the 1.25 FI scalar should be applied
    And the correlation should be 1.25 × base correlation

  @CRR-C5
  Scenario: Unregulated financial entity receives 1.25 correlation multiplier
    Given a counterparty of type "FINANCIAL_HOLDING"
    And the counterparty is an unregulated financial entity
    And internal PD is 0.50%
    When the A-IRB correlation is calculated
    Then the 1.25 FI scalar should be applied
    And the correlation should be higher than equivalent corporate

  Scenario: Small bank does not receive FI scalar
    Given a counterparty of type "CREDIT_INSTITUTION"
    And the counterparty total assets are below €70 billion
    And the counterparty is regulated
    And internal PD is 0.50%
    When the A-IRB correlation is calculated
    Then the FI scalar should not apply
    And the correlation should use the base formula

  # =============================================================================
  # Complete A-IRB Calculation
  # =============================================================================

  @CRR-C6
  Scenario: Complete A-IRB calculation with all internal estimates
    Given a counterparty "CORP_AIRB_002" with internal PD of 0.75%
    And the bank's internal LGD estimate is 30%
    And a facility with limit £20,000,000
    And drawn amount is £5,000,000
    And the bank's internal CCF estimate is 70%
    And the effective maturity is 3.0 years
    When the A-IRB RWA is calculated
    Then EAD should be £5,000,000 + (£15,000,000 × 70%) = £15,500,000
    And the internal PD, LGD should be used in K formula
    And the RWA should equal K × 12.5 × 1.06 × EAD

  # =============================================================================
  # Defaulted Exposures under A-IRB
  # =============================================================================

  @CRR-C7
  Scenario: Defaulted exposure under A-IRB
    Given a counterparty that is in default
    And the original exposure class was "CORPORATE"
    And the calculation approach is "A-IRB"
    And a loan with drawn amount £1,000,000
    When the A-IRB RWA is calculated
    Then the PD should be set to 100%
    And the LGD used should be the bank's best estimate LGD
    And the expected loss should equal LGD × EAD

  Scenario: LGD for defaulted exposure reflects recovery expectations
    Given a counterparty that is in default
    And the bank's estimated recovery is 60%
    And a loan with EAD of £500,000
    When the A-IRB expected loss is calculated
    Then the LGD should be 40% (100% - recovery)
    And EL should be £200,000

  # =============================================================================
  # Retail A-IRB
  # =============================================================================

  @CRR-C8
  Scenario: Retail QRRE under A-IRB with internal estimates
    Given a retail qualifying revolving exposure
    And the bank's internal PD estimate is 3.00%
    And the bank's internal LGD estimate is 60%
    And total credit limit is £10,000
    When the A-IRB RWA is calculated
    Then the retail QRRE correlation formula should apply
    And the correlation should be capped at 4%
    And the internal PD and LGD should be used

  Scenario: Retail mortgage under A-IRB
    Given a retail mortgage exposure
    And the bank's internal PD estimate is 0.50%
    And the bank's internal LGD estimate is 15%
    And mortgage balance is £300,000
    When the A-IRB RWA is calculated
    Then the residential mortgage correlation of 15% should apply
    And the internal estimates should be used

  # =============================================================================
  # A-IRB vs F-IRB Comparison
  # =============================================================================

  @CRR-C9
  Scenario: A-IRB produces lower RWA when internal LGD is below supervisory
    Given two identical exposures with PD 1.00%
    And one uses F-IRB (supervisory LGD 45%)
    And one uses A-IRB (internal LGD 30%)
    And both have EAD of £1,000,000
    When both calculations are performed
    Then the A-IRB RWA should be lower than F-IRB RWA
    And the ratio should reflect the LGD difference

  Scenario: A-IRB produces higher RWA when internal LGD exceeds supervisory
    Given two identical exposures with PD 1.00%
    And one uses F-IRB (supervisory LGD 45%)
    And one uses A-IRB (internal LGD 55%)
    And both have EAD of £1,000,000
    When both calculations are performed
    Then the A-IRB RWA should be higher than F-IRB RWA
