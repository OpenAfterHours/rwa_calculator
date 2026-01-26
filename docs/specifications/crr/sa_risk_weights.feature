@crr @sa
Feature: CRR Standardised Approach Risk Weights
  As a bank calculating RWA under the CRR framework
  I need to apply correct SA risk weights by exposure class and credit quality
  So that my capital requirements comply with CRR Articles 112-134

  Background:
    Given the regulatory framework is "CRR"
    And the calculation approach is "SA"

  # =============================================================================
  # Sovereign Exposures (CRR Art. 114)
  # =============================================================================

  @CRR-A1
  Scenario: UK Sovereign with CQS 1 receives 0% risk weight
    Given a counterparty "UK_GOV_001" of type "CENTRAL_GOVERNMENT"
    And the counterparty country is "GB"
    And the counterparty has CQS 1
    And a loan "LOAN_SOV_UK_001" with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the exposure class should be "SOVEREIGN"
    And the risk weight should be 0%
    And the RWA should be £0

  Scenario Outline: Sovereign risk weights by CQS
    Given a counterparty of type "CENTRAL_GOVERNMENT"
    And the counterparty has CQS <cqs>
    And a loan with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the risk weight should be <risk_weight>

    Examples:
      | cqs | risk_weight |
      | 1   | 0%          |
      | 2   | 20%         |
      | 3   | 50%         |
      | 4   | 100%        |
      | 5   | 100%        |
      | 6   | 150%        |

  # =============================================================================
  # Institution Exposures (CRR Art. 120-121)
  # =============================================================================

  @CRR-A4
  Scenario: UK Institution with CQS 2 receives 30% risk weight (UK deviation)
    Given a counterparty "BANK_UK_001" of type "CREDIT_INSTITUTION"
    And the counterparty country is "GB"
    And the counterparty has CQS 2
    And a loan "LOAN_INST_UK_003" with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the exposure class should be "INSTITUTION"
    And the risk weight should be 30%
    And the RWA should be £300,000

  Scenario Outline: UK Institution risk weights by CQS (with UK deviation)
    Given a counterparty of type "CREDIT_INSTITUTION"
    And the counterparty country is "GB"
    And the counterparty has CQS <cqs>
    And a loan with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the risk weight should be <risk_weight>

    Examples:
      | cqs | risk_weight |
      | 1   | 20%         |
      | 2   | 30%         |
      | 3   | 50%         |
      | 4   | 100%        |
      | 5   | 100%        |
      | 6   | 150%        |

  # =============================================================================
  # Corporate Exposures (CRR Art. 122)
  # =============================================================================

  @CRR-A2
  Scenario: Unrated corporate receives 100% risk weight
    Given a counterparty "CORP_UR_001" of type "CORPORATE"
    And the counterparty has no external rating
    And a loan "LOAN_CORP_UR_001" with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the exposure class should be "CORPORATE"
    And the risk weight should be 100%
    And the RWA should be £1,000,000

  @CRR-A3
  Scenario: Rated corporate with CQS 2 receives 50% risk weight
    Given a counterparty "CORP_UK_003" of type "CORPORATE"
    And the counterparty has CQS 2
    And a loan "LOAN_CORP_UK_003" with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the exposure class should be "CORPORATE"
    And the risk weight should be 50%
    And the RWA should be £500,000

  Scenario Outline: Corporate risk weights by CQS
    Given a counterparty of type "CORPORATE"
    And the counterparty has CQS <cqs>
    And a loan with drawn amount £1,000,000
    When the SA risk weight is calculated
    Then the risk weight should be <risk_weight>

    Examples:
      | cqs | risk_weight |
      | 1   | 20%         |
      | 2   | 50%         |
      | 3   | 100%        |
      | 4   | 100%        |
      | 5   | 150%        |
      | 6   | 150%        |

  # =============================================================================
  # Retail Exposures (CRR Art. 123)
  # =============================================================================

  @CRR-A9
  Scenario: Retail exposure receives fixed 75% risk weight
    Given a counterparty "IND_001" of type "NATURAL_PERSON"
    And the counterparty total exposure is below the retail threshold
    And a loan "LOAN_RTL_IND_001" with drawn amount £50,000
    When the SA risk weight is calculated
    Then the exposure class should be "RETAIL_OTHER"
    And the risk weight should be 75%
    And the RWA should be £37,500

  Scenario: Retail exposure exceeding threshold is reclassified
    Given a counterparty of type "NATURAL_PERSON"
    And the counterparty total exposure to the lending group is £1,200,000
    And the retail threshold is £1,000,000
    When the exposure class is determined
    Then the counterparty should be reclassified as "CORPORATE" or "CORPORATE_SME"
    And the retail risk weight of 75% should not apply

  # =============================================================================
  # Residential Mortgage Exposures (CRR Art. 125)
  # =============================================================================

  @CRR-A5
  Scenario: Residential mortgage with LTV <= 80% receives 35% risk weight
    Given a counterparty of type "NATURAL_PERSON"
    And a residential property valued at £833,333
    And a mortgage "LOAN_RTL_MTG_001" with balance £500,000
    And the LTV ratio is 60%
    When the SA risk weight is calculated
    Then the exposure class should be "RETAIL_MORTGAGE"
    And the risk weight should be 35%
    And the RWA should be £175,000

  @CRR-A6
  Scenario: Residential mortgage with LTV > 80% receives split treatment
    Given a counterparty of type "NATURAL_PERSON"
    And a residential property valued at £1,000,000
    And a mortgage "LOAN_RTL_MTG_002" with balance £850,000
    And the LTV ratio is 85%
    When the SA risk weight is calculated
    Then the exposure class should be "RETAIL_MORTGAGE"
    And the portion up to 80% LTV (£800,000) receives 35% risk weight
    And the portion above 80% LTV (£50,000) receives 75% risk weight
    And the blended risk weight should be approximately 37.35%

  Scenario: Residential mortgage at exactly 80% LTV boundary
    Given a counterparty of type "NATURAL_PERSON"
    And a residential property valued at £500,000
    And a mortgage with balance £400,000
    And the LTV ratio is exactly 80%
    When the SA risk weight is calculated
    Then the risk weight should be 35%
    And no split treatment should apply

  # =============================================================================
  # Commercial Real Estate (CRR Art. 126)
  # =============================================================================

  @CRR-A7
  Scenario: Commercial RE with LTV <= 50% and income cover receives 50% risk weight
    Given a counterparty of type "CORPORATE"
    And a commercial property valued at £1,000,000
    And the property is income-producing with adequate coverage
    And a loan "LOAN_CRE_001" with balance £400,000
    And the LTV ratio is 40%
    When the SA risk weight is calculated
    Then the exposure class should be "SECURED_BY_IMMOVABLE_PROPERTY"
    And the risk weight should be 50%
    And the RWA should be £200,000

  Scenario: Commercial RE without income cover receives corporate risk weight
    Given a counterparty of type "CORPORATE"
    And a commercial property valued at £1,000,000
    And the property is not income-producing
    And a loan with balance £400,000
    When the SA risk weight is calculated
    Then the risk weight should be the counterparty's corporate risk weight

  Scenario Outline: Commercial RE LTV-based risk weights
    Given a commercial property with income coverage
    And the LTV ratio is <ltv>
    When the SA risk weight is calculated
    Then the risk weight should be <risk_weight>

    Examples:
      | ltv  | risk_weight |
      | 40%  | 50%         |
      | 50%  | 50%         |
      | 55%  | 65%         |
      | 60%  | 65%         |
      | 70%  | 80%         |
      | 80%  | 100%        |
      | 100% | 110%        |

  # =============================================================================
  # Defaulted Exposures (CRR Art. 127)
  # =============================================================================

  Scenario: Defaulted exposure receives 150% risk weight under SA
    Given a counterparty that is in default
    And the original exposure class was "CORPORATE"
    And a loan with drawn amount £500,000
    When the SA risk weight is calculated
    Then the exposure should be reclassified to "DEFAULTED"
    And the risk weight should be 150%
    And the RWA should be £750,000

  Scenario: Defaulted residential mortgage with adequate provision
    Given a counterparty that is in default
    And a residential mortgage with balance £300,000
    And specific provisions of £100,000 have been made
    When the SA risk weight is calculated
    Then the risk weight may be reduced to 100%
    And the reduction is subject to provision adequacy rules
