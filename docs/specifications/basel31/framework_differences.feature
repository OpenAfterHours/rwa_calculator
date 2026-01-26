@basel31
Feature: Basel 3.1 Framework Differences from CRR
  As a bank preparing for Basel 3.1 implementation (January 2027)
  I need to understand the key differences in RWA calculation
  So that I can correctly calculate capital under the new framework per PRA PS9/24

  Background:
    Given the regulatory framework is "BASEL_3_1"
    And the implementation date is 1 January 2027

  # =============================================================================
  # Removal of Supporting Factors
  # =============================================================================

  @BASEL31-F1
  Scenario: No SME supporting factor under Basel 3.1
    Given a counterparty classified as "CORPORATE_SME"
    And the counterparty annual turnover is £30,000,000
    And a loan with drawn amount £2,000,000
    And the base risk weight is 100%
    When the Basel 3.1 RWA is calculated
    Then no SME supporting factor should be applied
    And the supporting factor should be 1.0
    And the RWA should be £2,000,000 (not reduced)

  @BASEL31-F2
  Scenario: No infrastructure supporting factor under Basel 3.1
    Given an exposure to a qualifying infrastructure project
    And a loan with drawn amount £10,000,000
    And the base risk weight is 100%
    When the Basel 3.1 RWA is calculated
    Then no infrastructure supporting factor should be applied
    And the RWA should be £10,000,000

  Scenario: Comparison of CRR vs Basel 3.1 for SME
    Given identical SME exposures under both frameworks
    And the exposure amount is £1,000,000
    And the base risk weight is 100%
    When calculating under CRR
    Then SME factor 0.7619 applies, RWA = £761,900
    When calculating under Basel 3.1
    Then no SME factor applies, RWA = £1,000,000
    And Basel 3.1 RWA is 31% higher

  # =============================================================================
  # Removal of 1.06 Scaling Factor
  # =============================================================================

  @BASEL31-F3
  Scenario: No 1.06 scaling factor in IRB formula under Basel 3.1
    Given a counterparty with internal PD of 1.00%
    And supervisory LGD of 45%
    And EAD of £1,000,000
    And the IRB capital requirement K is 5.00%
    When the Basel 3.1 IRB RWA is calculated
    Then the formula should be K × 12.5 × EAD (no 1.06 factor)
    And RWA should be £625,000 (not £662,500)

  Scenario: Comparison of CRR vs Basel 3.1 IRB scaling
    Given identical IRB exposures under both frameworks
    And the capital requirement K is 5.00%
    And EAD is £1,000,000
    When calculating under CRR
    Then RWA = K × 12.5 × 1.06 × EAD = £662,500
    When calculating under Basel 3.1
    Then RWA = K × 12.5 × EAD = £625,000
    And Basel 3.1 is 5.66% lower due to no scaling

  # =============================================================================
  # Output Floor (72.5% of SA)
  # =============================================================================

  @BASEL31-F4
  Scenario: Output floor constrains IRB RWA to 72.5% of SA
    Given an IRB exposure with calculated RWA of £500,000
    And the equivalent SA RWA would be £1,000,000
    And the output floor is 72.5%
    When the output floor is applied
    Then the floor amount is £1,000,000 × 72.5% = £725,000
    And since IRB RWA (£500,000) < floor (£725,000)
    Then the final RWA should be £725,000

  @BASEL31-F5
  Scenario: Output floor does not bind when IRB exceeds floor
    Given an IRB exposure with calculated RWA of £800,000
    And the equivalent SA RWA would be £1,000,000
    And the output floor is 72.5%
    When the output floor is applied
    Then the floor amount is £725,000
    And since IRB RWA (£800,000) > floor (£725,000)
    Then the final RWA should be £800,000

  Scenario: Output floor calculation at portfolio level
    Given a portfolio of IRB exposures
    And total IRB RWA is £50,000,000
    And total SA-equivalent RWA is £80,000,000
    When the portfolio output floor is calculated
    Then the floor is £80,000,000 × 72.5% = £58,000,000
    And since IRB (£50m) < floor (£58m), the floor binds
    And reported RWA should be £58,000,000

  # =============================================================================
  # Differentiated PD Floors
  # =============================================================================

  @BASEL31-F6
  Scenario: Corporate PD floor remains 0.03%
    Given a corporate exposure under Basel 3.1
    And internal PD is 0.01%
    When the PD floor is applied
    Then the floored PD should be 0.03%

  @BASEL31-F7
  Scenario: Retail other PD floor is 0.05%
    Given a retail (non-QRRE) exposure under Basel 3.1
    And internal PD is 0.01%
    When the PD floor is applied
    Then the floored PD should be 0.05%

  @BASEL31-F8
  Scenario: Retail QRRE PD floor is 0.10%
    Given a qualifying revolving retail exposure under Basel 3.1
    And internal PD is 0.05%
    When the PD floor is applied
    Then the floored PD should be 0.10%

  Scenario Outline: Basel 3.1 differentiated PD floors by exposure class
    Given an exposure class of "<exposure_class>"
    And internal PD is <input_pd>
    When the Basel 3.1 PD floor is applied
    Then the floored PD should be <floored_pd>

    Examples:
      | exposure_class  | input_pd | floored_pd |
      | CORPORATE       | 0.01%    | 0.03%      |
      | CORPORATE       | 0.05%    | 0.05%      |
      | CORPORATE_SME   | 0.01%    | 0.03%      |
      | RETAIL_OTHER    | 0.01%    | 0.05%      |
      | RETAIL_OTHER    | 0.10%    | 0.10%      |
      | RETAIL_QRRE     | 0.05%    | 0.10%      |
      | RETAIL_QRRE     | 0.15%    | 0.15%      |
      | RETAIL_MORTGAGE | 0.01%    | 0.05%      |

  # =============================================================================
  # LGD Floors for A-IRB
  # =============================================================================

  @BASEL31-F9
  Scenario: Unsecured LGD floor of 25% under Basel 3.1 A-IRB
    Given an unsecured exposure under A-IRB
    And the bank's internal LGD estimate is 20%
    When the Basel 3.1 LGD floor is applied
    Then the floored LGD should be 25%

  @BASEL31-F10
  Scenario: Financial collateral LGD floor of 0% under Basel 3.1
    Given an exposure fully secured by eligible financial collateral
    And the bank's internal LGD estimate is 5%
    When the Basel 3.1 LGD floor is applied
    Then the floored LGD should be 5% (floor is 0%)

  @BASEL31-F11
  Scenario: Real estate collateral LGD floor of 10%
    Given an exposure secured by residential property
    And the bank's internal LGD estimate is 8%
    When the Basel 3.1 LGD floor is applied
    Then the floored LGD should be 10%

  Scenario Outline: Basel 3.1 LGD floors by collateral type
    Given an exposure secured by <collateral_type>
    And the bank's internal LGD estimate is <input_lgd>
    When the Basel 3.1 LGD floor is applied
    Then the floored LGD should be <floored_lgd>

    Examples:
      | collateral_type       | input_lgd | floored_lgd |
      | unsecured             | 20%       | 25%         |
      | unsecured             | 30%       | 30%         |
      | financial_collateral  | 3%        | 3%          |
      | receivables           | 10%       | 15%         |
      | commercial_property   | 12%       | 15%         |
      | residential_property  | 8%        | 10%         |
      | other_physical        | 18%       | 20%         |

  # =============================================================================
  # Revised Slotting Risk Weights
  # =============================================================================

  @BASEL31-F12
  Scenario: Basel 3.1 slotting with updated risk weights
    Given a specialised lending exposure under Basel 3.1
    And the slotting category is "STRONG"
    And remaining maturity exceeds 2.5 years
    And the exposure amount is £10,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 50% (reduced from CRR 70%)
    And the RWA should be £5,000,000

  Scenario Outline: Basel 3.1 slotting risk weights comparison
    Given a specialised lending exposure
    And the slotting category is "<category>"
    And remaining maturity exceeds 2.5 years
    When comparing CRR vs Basel 3.1
    Then CRR risk weight is <crr_rw>
    And Basel 3.1 risk weight is <basel31_rw>

    Examples:
      | category     | crr_rw | basel31_rw |
      | STRONG       | 70%    | 50%        |
      | GOOD         | 90%    | 70%        |
      | SATISFACTORY | 115%   | 100%       |
      | WEAK         | 250%   | 150%       |
      | DEFAULT      | 0%     | 350%       |

  # =============================================================================
  # Revised Residential Mortgage LTV Bands
  # =============================================================================

  @BASEL31-F13
  Scenario: Basel 3.1 residential mortgage with LTV-based bands
    Given a residential mortgage under Basel 3.1
    And property value is £500,000
    And loan balance is £350,000
    And LTV is 70%
    When the SA risk weight is calculated
    Then the risk weight should be determined by the 70% LTV band
    And not use the CRR split treatment at 80%

  Scenario Outline: Basel 3.1 residential mortgage LTV bands
    Given a residential mortgage with LTV of <ltv>
    When the Basel 3.1 SA risk weight is calculated
    Then the risk weight should be <risk_weight>

    Examples:
      | ltv   | risk_weight |
      | 50%   | 20%         |
      | 60%   | 25%         |
      | 70%   | 30%         |
      | 80%   | 40%         |
      | 90%   | 50%         |
      | 100%  | 70%         |

  # =============================================================================
  # Due Diligence Requirements
  # =============================================================================

  @BASEL31-F14
  Scenario: External ratings require due diligence under Basel 3.1
    Given a corporate exposure with external rating
    And the external CQS is 2
    When applying the SA risk weight
    Then the bank must perform due diligence
    And the bank may increase the risk weight if concerns identified
    And the bank must document the due diligence assessment

  Scenario: Due diligence for unrated exposures
    Given an unrated corporate exposure
    When applying the SA risk weight
    Then enhanced due diligence requirements apply
    And risk weight may exceed the standard 100%
    And documentation of assessment is required
