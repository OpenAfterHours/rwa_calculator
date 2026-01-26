@crr @provisions
Feature: CRR Provision Treatment
  As a bank accounting for credit risk provisions
  I need to correctly apply provision treatment for SA and IRB
  So that my RWA and capital reflect provision adequacy per CRR Art. 158-159

  Background:
    Given the regulatory framework is "CRR"

  # =============================================================================
  # Provisions under Standardised Approach
  # =============================================================================

  @CRR-G1
  Scenario: Specific provisions reduce SA exposure value
    Given a corporate exposure with gross amount £1,000,000
    And specific credit risk adjustments of £100,000
    And the calculation approach is "SA"
    When the exposure value is calculated
    Then the net exposure should be £900,000
    And the risk weight applies to the net exposure

  @CRR-G2
  Scenario: General provisions do not reduce SA exposure
    Given a corporate exposure with gross amount £1,000,000
    And general credit risk adjustments of £50,000
    And the calculation approach is "SA"
    When the exposure value is calculated
    Then the exposure should remain £1,000,000
    And general provisions are treated separately in capital

  Scenario: Defaulted exposure with high provision coverage
    Given a defaulted corporate exposure of £500,000
    And specific provisions of £200,000 (40% coverage)
    And the calculation approach is "SA"
    When the SA risk weight is calculated
    Then the net exposure is £300,000
    And the risk weight may be reduced from 150%
    And the reduction depends on provision adequacy

  # =============================================================================
  # Expected Loss under IRB
  # =============================================================================

  @CRR-G3
  Scenario: Expected loss calculation for non-defaulted exposure
    Given a corporate exposure with:
      | Parameter | Value      |
      | EAD       | £5,000,000 |
      | PD        | 2.00%      |
      | LGD       | 45%        |
    And the calculation approach is "F-IRB"
    And the exposure is not in default
    When the expected loss is calculated
    Then EL should equal PD × LGD × EAD
    And EL should be £45,000 (2% × 45% × £5,000,000)

  @CRR-G4
  Scenario: Expected loss for defaulted exposure
    Given a defaulted corporate exposure with:
      | Parameter     | Value      |
      | EAD           | £1,000,000 |
      | Best est. LGD | 60%        |
    And the calculation approach is "F-IRB"
    When the expected loss is calculated
    Then EL should equal Best Estimate LGD × EAD
    And EL should be £600,000

  # =============================================================================
  # EL vs Provisions Comparison
  # =============================================================================

  @CRR-G5
  Scenario: Expected loss shortfall reduces CET1
    Given a portfolio with total EL of £1,000,000
    And total eligible provisions of £700,000
    And the calculation approach is "IRB"
    When the EL comparison is performed
    Then there is a shortfall of £300,000
    And the shortfall should be deducted from CET1 capital

  @CRR-G6
  Scenario: Excess provisions may be added to Tier 2
    Given a portfolio with total EL of £1,000,000
    And total eligible provisions of £1,200,000
    And the calculation approach is "IRB"
    When the EL comparison is performed
    Then there is an excess of £200,000
    And the excess may be added to Tier 2 capital
    And the addition is capped at 0.6% of IRB RWA

  Scenario: EL comparison at portfolio level
    Given an IRB portfolio with:
      | Exposure | EAD        | PD   | LGD | EL      | Provision |
      | A        | £2,000,000 | 1%   | 45% | £9,000  | £5,000    |
      | B        | £3,000,000 | 2%   | 45% | £27,000 | £30,000   |
      | C        | £5,000,000 | 0.5% | 45% | £11,250 | £15,000   |
    When the portfolio EL comparison is performed
    Then total EL is £47,250
    And total provisions is £50,000
    And there is a net excess of £2,750

  # =============================================================================
  # IFRS 9 Provision Stages
  # =============================================================================

  @CRR-G7
  Scenario: Stage 1 provisions (12-month ECL)
    Given a performing exposure
    And IFRS 9 Stage 1 provision of £10,000
    When determining provision eligibility for IRB
    Then Stage 1 provisions are eligible for EL comparison
    And the provision covers 12-month expected credit loss

  @CRR-G8
  Scenario: Stage 2 provisions (lifetime ECL)
    Given an exposure with significant credit deterioration
    And IFRS 9 Stage 2 provision of £50,000
    When determining provision eligibility
    Then Stage 2 provisions are eligible for EL comparison
    And the provision covers lifetime expected credit loss

  @CRR-G9
  Scenario: Stage 3 provisions (credit-impaired)
    Given a credit-impaired (defaulted) exposure
    And IFRS 9 Stage 3 provision of £200,000
    When determining provision eligibility
    Then Stage 3 provisions are eligible for EL comparison
    And specific provisions reduce exposure under SA

  Scenario: Provision aggregation across stages
    Given a portfolio with provisions:
      | Stage   | Amount    | Type     |
      | Stage 1 | £100,000  | GCRA     |
      | Stage 2 | £250,000  | GCRA     |
      | Stage 3 | £500,000  | SCRA     |
    When aggregating eligible provisions for IRB
    Then total eligible provisions should be £850,000
    And this is compared to total EL

  # =============================================================================
  # Provision Caps and Limits
  # =============================================================================

  @CRR-G10
  Scenario: Tier 2 addition cap of 0.6% of IRB RWA
    Given IRB RWA of £100,000,000
    And excess provisions of £1,000,000
    When calculating Tier 2 eligible amount
    Then the cap is 0.6% × £100,000,000 = £600,000
    And only £600,000 can be added to Tier 2
    And £400,000 excess cannot be recognized

  Scenario: No Tier 2 cap when shortfall exists
    Given IRB RWA of £100,000,000
    And EL shortfall of £500,000
    When calculating capital impact
    Then the full shortfall is deducted from CET1
    And no amount is added to Tier 2

  # =============================================================================
  # Mixed Approach Portfolio
  # =============================================================================

  @CRR-G11
  Scenario: Separate provision treatment for SA and IRB
    Given a mixed portfolio:
      | Approach | Exposure   | Provision |
      | SA       | £20,000,000| £500,000  |
      | F-IRB    | £30,000,000| £800,000  |
    When provisions are applied
    Then SA provisions reduce exposure value directly
    And IRB provisions are compared to expected loss
    And the treatments are applied separately

  Scenario: Provision allocation between approaches
    Given a general provision pool of £1,000,000
    And portfolio split:
      | Approach | EAD Proportion |
      | SA       | 40%            |
      | IRB      | 60%            |
    When allocating provisions
    Then provisions should be allocated proportionally
    And SA receives £400,000 allocation
    And IRB receives £600,000 allocation
