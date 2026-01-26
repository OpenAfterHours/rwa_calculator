@crr @irb @firb
Feature: CRR Foundation IRB Calculation
  As a bank with F-IRB permission calculating RWA under CRR
  I need to calculate RWA using internal PD with supervisory LGD and CCF
  So that my capital requirements comply with CRR Articles 153-154, 161-163

  Background:
    Given the regulatory framework is "CRR"
    And the calculation approach is "F-IRB"

  # =============================================================================
  # Supervisory LGD (CRR Art. 161)
  # =============================================================================

  @CRR-B1
  Scenario: Senior unsecured exposure uses 45% supervisory LGD
    Given a counterparty "CORP_IRB_001" with internal PD of 1.00%
    And a senior unsecured loan "LOAN_FIRB_001" with drawn amount £5,000,000
    And the effective maturity is 2.5 years
    When the F-IRB RWA is calculated
    Then the supervisory LGD of 45% should be used
    And the correlation should be calculated using the corporate formula
    And the capital requirement K should be derived
    And the RWA should equal K × 12.5 × 1.06 × EAD

  @CRR-B2
  Scenario: Subordinated exposure uses 75% supervisory LGD
    Given a counterparty with internal PD of 1.00%
    And a subordinated loan "LOAN_FIRB_SUB_001" with drawn amount £2,000,000
    And the effective maturity is 2.5 years
    When the F-IRB RWA is calculated
    Then the supervisory LGD of 75% should be used
    And the RWA should be higher than equivalent senior exposure

  # =============================================================================
  # PD Floor (CRR Art. 160)
  # =============================================================================

  @CRR-B3
  Scenario: PD below floor is floored at 0.03%
    Given a counterparty with internal PD of 0.01%
    And a senior unsecured loan with drawn amount £1,000,000
    When the F-IRB RWA is calculated
    Then the PD used should be 0.03% (the floor)
    And the PD floor warning should be logged

  Scenario: PD above floor is used as-is
    Given a counterparty with internal PD of 0.50%
    And a senior unsecured loan with drawn amount £1,000,000
    When the F-IRB RWA is calculated
    Then the PD used should be 0.50%
    And no PD floor adjustment should be made

  Scenario Outline: PD floor application by input PD
    Given a counterparty with internal PD of <input_pd>
    When the PD floor is applied
    Then the PD used in calculation should be <used_pd>

    Examples:
      | input_pd | used_pd |
      | 0.01%    | 0.03%   |
      | 0.02%    | 0.03%   |
      | 0.03%    | 0.03%   |
      | 0.05%    | 0.05%   |
      | 1.00%    | 1.00%   |

  # =============================================================================
  # Corporate Correlation Formula (CRR Art. 153(1))
  # =============================================================================

  @CRR-B4
  Scenario: Corporate correlation calculation
    Given a counterparty with internal PD of 2.00%
    And the exposure class is "CORPORATE"
    When the asset correlation is calculated
    Then the correlation formula should be:
      """
      R = 0.12 × (1 - EXP(-50 × PD)) / (1 - EXP(-50))
        + 0.24 × (1 - (1 - EXP(-50 × PD)) / (1 - EXP(-50)))
      """
    And the correlation should be between 0.12 and 0.24

  # =============================================================================
  # SME Correlation Adjustment (CRR Art. 153(4))
  # =============================================================================

  @CRR-B5
  Scenario: SME receives firm-size correlation adjustment
    Given a counterparty "SME_IRB_001" with internal PD of 2.00%
    And the counterparty annual turnover is £5,000,000
    And the turnover in EUR is approximately €5,880,000
    And a loan "LOAN_FIRB_SME_001" with drawn amount £3,000,000
    When the F-IRB correlation is calculated
    Then the firm size adjustment should reduce correlation
    And the adjustment formula should be:
      """
      R_adjusted = R - 0.04 × (1 - (S - 5) / 45)
      where S = max(5, min(50, turnover in EUR millions))
      """
    And the correlation should be lower than unadjusted corporate

  Scenario: Large corporate receives no firm-size adjustment
    Given a counterparty with internal PD of 2.00%
    And the counterparty annual turnover exceeds €50m
    When the F-IRB correlation is calculated
    Then no firm size adjustment should apply
    And the correlation should equal the base corporate formula

  Scenario Outline: Firm size adjustment by turnover
    Given a counterparty with annual turnover of <turnover_eur>
    When the firm size adjustment is calculated
    Then the S value should be <s_value>

    Examples:
      | turnover_eur | s_value |
      | €3m          | 5       |
      | €5m          | 5       |
      | €10m         | 10      |
      | €25m         | 25      |
      | €50m         | 50      |
      | €100m        | 50      |

  # =============================================================================
  # Maturity Adjustment (CRR Art. 162)
  # =============================================================================

  @CRR-B6
  Scenario: Maturity adjustment for 2.5 year exposure
    Given a counterparty with internal PD of 1.00%
    And a loan with effective maturity of 2.5 years
    When the maturity adjustment is calculated
    Then the maturity adjustment factor should be calculated as:
      """
      b = (0.11852 - 0.05478 × ln(PD))²
      MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
      """
    And the adjustment should be 1.0 for M = 2.5 years

  Scenario: Short maturity exposure receives reduced capital
    Given a counterparty with internal PD of 1.00%
    And a loan with effective maturity of 1.0 year
    When the maturity adjustment is calculated
    Then the adjustment should be less than 1.0
    And the RWA should be lower than 2.5 year equivalent

  Scenario: Long maturity exposure receives increased capital
    Given a counterparty with internal PD of 1.00%
    And a loan with effective maturity of 5.0 years
    When the maturity adjustment is calculated
    Then the adjustment should be greater than 1.0
    And the RWA should be higher than 2.5 year equivalent

  Scenario Outline: Maturity adjustment by effective maturity
    Given a counterparty with internal PD of 1.00%
    And a loan with effective maturity of <maturity> years
    When the maturity adjustment is calculated
    Then the adjustment direction should be <direction>

    Examples:
      | maturity | direction         |
      | 1.0      | decreasing        |
      | 2.5      | neutral           |
      | 3.0      | increasing        |
      | 5.0      | increasing        |

  # =============================================================================
  # Capital Requirement Formula (CRR Art. 153)
  # =============================================================================

  @CRR-B7
  Scenario: Complete F-IRB capital requirement calculation
    Given a counterparty with internal PD of 1.00%
    And a senior unsecured loan with drawn amount £10,000,000
    And the effective maturity is 2.5 years
    When the F-IRB RWA is calculated
    Then the calculation should follow these steps:
      | Step | Component                                        |
      | 1    | Apply PD floor (max of 0.03%, PD)                |
      | 2    | Calculate asset correlation R                    |
      | 3    | Apply firm size adjustment if SME               |
      | 4    | Calculate maturity adjustment b                  |
      | 5    | Calculate K using normal distribution           |
      | 6    | Apply maturity adjustment                        |
      | 7    | RWA = K × 12.5 × 1.06 × EAD                      |

  Scenario: IRB K formula calculation
    Given a counterparty with PD and LGD parameters
    When the capital requirement K is calculated
    Then K should equal:
      """
      K = LGD × [N((1-R)^(-0.5) × G(PD) + (R/(1-R))^0.5 × G(0.999)) - PD] × MA
      where:
        N = standard normal cumulative distribution
        G = inverse standard normal distribution
        R = asset correlation
        MA = maturity adjustment
      """

  # =============================================================================
  # CRR Scaling Factor
  # =============================================================================

  @CRR-B8
  Scenario: CRR 1.06 scaling factor is applied
    Given a counterparty with internal PD of 1.00%
    And a loan with drawn amount £1,000,000
    And the IRB capital requirement K is 5.00%
    When the F-IRB RWA is calculated
    Then the RWA formula should be K × 12.5 × 1.06 × EAD
    And the 1.06 scaling factor should be present

  # =============================================================================
  # Expected Loss (CRR Art. 158)
  # =============================================================================

  @CRR-B9
  Scenario: Expected loss calculation for provision comparison
    Given a counterparty with internal PD of 2.00%
    And the supervisory LGD is 45%
    And a loan with EAD of £5,000,000
    When the expected loss is calculated
    Then EL should equal PD × LGD × EAD
    And EL should be £45,000 (2.00% × 45% × £5,000,000)

  # =============================================================================
  # F-IRB CCF (CRR Art. 166)
  # =============================================================================

  @CRR-B10
  Scenario: F-IRB uses 75% CCF for medium risk commitments
    Given a facility with limit £5,000,000
    And drawn amount is £1,000,000
    And undrawn amount is £4,000,000
    And the commitment is not unconditionally cancellable
    When the F-IRB EAD is calculated
    Then the CCF of 75% should apply to undrawn
    And EAD should be £1,000,000 + (£4,000,000 × 75%) = £4,000,000
