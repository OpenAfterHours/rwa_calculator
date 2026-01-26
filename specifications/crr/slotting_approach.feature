@crr @slotting
Feature: CRR Slotting Approach for Specialised Lending
  As a bank calculating RWA for specialised lending exposures
  I need to apply slotting category risk weights correctly
  So that my capital requirements comply with CRR Articles 147(8), 153(5)

  Background:
    Given the regulatory framework is "CRR"
    And the calculation approach is "SLOTTING"

  # =============================================================================
  # Slotting Categories and Risk Weights (CRR Art. 153(5))
  # =============================================================================

  @CRR-E1
  Scenario: Strong category receives 70% risk weight
    Given a specialised lending exposure "SL_PF_001"
    And the slotting category is "STRONG"
    And remaining maturity exceeds 2.5 years
    And the exposure amount is £10,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 70%
    And the RWA should be £7,000,000

  @CRR-E2
  Scenario: Good category receives 90% risk weight
    Given a specialised lending exposure "SL_OF_001"
    And the slotting category is "GOOD"
    And remaining maturity exceeds 2.5 years
    And the exposure amount is £5,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 90%
    And the RWA should be £4,500,000

  @CRR-E3
  Scenario: Satisfactory category receives 115% risk weight
    Given a specialised lending exposure "SL_CF_001"
    And the slotting category is "SATISFACTORY"
    And the exposure amount is £8,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 115%
    And the RWA should be £9,200,000

  @CRR-E4
  Scenario: Weak category receives 250% risk weight
    Given a specialised lending exposure "SL_IPRE_001"
    And the slotting category is "WEAK"
    And the exposure amount is £2,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 250%
    And the RWA should be £5,000,000

  @CRR-E5
  Scenario: Default category receives 0% risk weight (EL covered)
    Given a specialised lending exposure in default
    And the slotting category is "DEFAULT"
    And the exposure amount is £3,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 0%
    And the expected loss should be fully provisioned

  Scenario Outline: CRR slotting risk weights by category
    Given a specialised lending exposure
    And the slotting category is "<category>"
    And the exposure amount is £1,000,000
    When the slotting RWA is calculated
    Then the risk weight should be <risk_weight>
    And the RWA should be <rwa>

    Examples:
      | category     | risk_weight | rwa        |
      | STRONG       | 70%         | £700,000   |
      | GOOD         | 90%         | £900,000   |
      | SATISFACTORY | 115%        | £1,150,000 |
      | WEAK         | 250%        | £2,500,000 |
      | DEFAULT      | 0%          | £0         |

  # =============================================================================
  # Maturity Adjustment for Strong/Good Categories
  # =============================================================================

  @CRR-E6
  Scenario: Strong category with short maturity receives reduced RW
    Given a specialised lending exposure
    And the slotting category is "STRONG"
    And remaining maturity is 2.0 years (less than 2.5 years)
    And the exposure amount is £10,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 50% (reduced from 70%)
    And the RWA should be £5,000,000

  @CRR-E7
  Scenario: Good category with short maturity receives reduced RW
    Given a specialised lending exposure
    And the slotting category is "GOOD"
    And remaining maturity is 1.5 years (less than 2.5 years)
    And the exposure amount is £5,000,000
    When the slotting RWA is calculated
    Then the risk weight should be 70% (reduced from 90%)
    And the RWA should be £3,500,000

  Scenario: Satisfactory category has no maturity adjustment
    Given a specialised lending exposure
    And the slotting category is "SATISFACTORY"
    And remaining maturity is 1.0 year
    When the slotting RWA is calculated
    Then the risk weight should remain 115%
    And no maturity reduction should apply

  Scenario Outline: Maturity adjustment for Strong/Good categories
    Given a specialised lending exposure
    And the slotting category is "<category>"
    And remaining maturity is <maturity> years
    When the slotting RWA is calculated
    Then the risk weight should be <risk_weight>

    Examples:
      | category | maturity | risk_weight |
      | STRONG   | 1.0      | 50%         |
      | STRONG   | 2.0      | 50%         |
      | STRONG   | 2.5      | 70%         |
      | STRONG   | 5.0      | 70%         |
      | GOOD     | 1.0      | 70%         |
      | GOOD     | 2.0      | 70%         |
      | GOOD     | 2.5      | 90%         |
      | GOOD     | 5.0      | 90%         |

  # =============================================================================
  # HVCRE (High Volatility Commercial Real Estate)
  # =============================================================================

  @CRR-E8
  Scenario: HVCRE Strong category receives elevated risk weight
    Given a high-volatility commercial real estate exposure
    And the exposure is classified as HVCRE
    And the slotting category is "STRONG"
    And remaining maturity exceeds 2.5 years
    And the exposure amount is £5,000,000
    When the slotting RWA is calculated
    Then the HVCRE risk weight of 95% should apply (not 70%)
    And the RWA should be £4,750,000

  Scenario Outline: HVCRE elevated risk weights
    Given a high-volatility commercial real estate exposure
    And the slotting category is "<category>"
    And remaining maturity exceeds 2.5 years
    When the slotting RWA is calculated
    Then the risk weight should be <hvcre_rw> (elevated from <base_rw>)

    Examples:
      | category     | base_rw | hvcre_rw |
      | STRONG       | 70%     | 95%      |
      | GOOD         | 90%     | 120%     |
      | SATISFACTORY | 115%    | 140%     |
      | WEAK         | 250%    | 250%     |

  Scenario: HVCRE with short maturity adjustment
    Given a high-volatility commercial real estate exposure
    And the slotting category is "STRONG"
    And remaining maturity is 2.0 years
    When the slotting RWA is calculated
    Then the HVCRE reduced maturity RW of 70% should apply

  # =============================================================================
  # Specialised Lending Types
  # =============================================================================

  @CRR-E9
  Scenario: Project finance classification
    Given an exposure to finance a specific project
    And the repayment depends primarily on project cash flows
    And the lender has significant control over project assets
    When the exposure type is classified
    Then the exposure should be classified as "PROJECT_FINANCE"
    And slotting approach should apply

  @CRR-E10
  Scenario: Object finance classification
    Given an exposure to finance physical assets
    And the assets are ships, aircraft, or rolling stock
    And repayment depends on cash flows from financed assets
    When the exposure type is classified
    Then the exposure should be classified as "OBJECT_FINANCE"
    And slotting approach should apply

  Scenario: Commodities finance classification
    Given an exposure to finance commodity reserves or inventories
    And the exposure is structured for commodity trading
    And repayment depends on commodity sale proceeds
    When the exposure type is classified
    Then the exposure should be classified as "COMMODITIES_FINANCE"
    And slotting approach should apply

  Scenario: Income-producing real estate classification
    Given an exposure to finance real estate
    And the property is held for rental income or resale
    And repayment depends substantially on property cash flows
    When the exposure type is classified
    Then the exposure should be classified as "IPRE"
    And slotting approach should apply

  # =============================================================================
  # Slotting Category Assessment
  # =============================================================================

  @CRR-E11
  Scenario: Slotting assessment criteria
    Given a specialised lending exposure requiring slotting
    When the slotting category is assessed
    Then the following factors should be evaluated:
      | Factor                    | Description                          |
      | Financial strength        | Debt service coverage, leverage      |
      | Political/legal risk      | Country risk, regulatory environment |
      | Transaction/asset risk    | Technology, construction risk        |
      | Strength of sponsor       | Track record, financial support      |
      | Security package          | Quality of collateral/covenants      |

  Scenario: Multiple slotting criteria contribute to category
    Given a project finance exposure
    And financial strength indicators are "STRONG"
    And political/legal risk is "GOOD"
    And transaction characteristics are "SATISFACTORY"
    And sponsor strength is "GOOD"
    When the overall slotting category is determined
    Then the category should reflect the weighted assessment
    And documentation should support the assigned category
