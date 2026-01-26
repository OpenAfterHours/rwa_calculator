@crr @crm
Feature: CRR Credit Risk Mitigation
  As a bank applying credit risk mitigation techniques
  I need to correctly apply collateral haircuts and guarantee substitution
  So that my RWA reflects eligible CRM per CRR Articles 192-241

  Background:
    Given the regulatory framework is "CRR"

  # =============================================================================
  # Financial Collateral Haircuts (CRR Art. 223-224)
  # =============================================================================

  @CRR-D1
  Scenario: Cash collateral in same currency has zero haircut
    Given an exposure of £1,000,000
    And cash collateral of £200,000 in GBP
    And the exposure is denominated in GBP
    When the collateral haircut is applied
    Then the haircut should be 0%
    And the adjusted collateral value should be £200,000
    And the net exposure should be £800,000

  @CRR-D2
  Scenario: Sovereign debt collateral receives issuer and maturity haircut
    Given an exposure of £1,000,000
    And sovereign debt collateral of £300,000
    And the issuer has CQS 1
    And residual maturity is 3 years
    When the collateral haircut is applied
    Then the haircut should be 2% (per CRR Annex)
    And the adjusted collateral value should be £294,000
    And the net exposure should be £706,000

  @CRR-D3
  Scenario: Corporate debt collateral with CQS 2 and 5-year maturity
    Given an exposure of £1,000,000
    And corporate debt collateral of £400,000
    And the issuer has CQS 2
    And residual maturity is 5 years
    When the collateral haircut is applied
    Then the haircut should be 8%
    And the adjusted collateral value should be £368,000

  Scenario Outline: Supervisory haircuts by collateral type and maturity
    Given sovereign debt collateral with CQS <cqs>
    And residual maturity of <maturity> years
    When the haircut is determined
    Then the haircut should be <haircut>

    Examples:
      | cqs | maturity | haircut |
      | 1   | 0.5      | 0.5%    |
      | 1   | 1        | 0.5%    |
      | 1   | 3        | 2%      |
      | 1   | 5        | 4%      |
      | 1   | 10       | 4%      |
      | 2-3 | 1        | 1%      |
      | 2-3 | 3        | 3%      |
      | 2-3 | 5        | 6%      |

  # =============================================================================
  # FX Mismatch Haircut (CRR Art. 224)
  # =============================================================================

  @CRR-D4
  Scenario: Collateral with currency mismatch receives 8% additional haircut
    Given an exposure denominated in GBP
    And collateral denominated in EUR
    And the base collateral haircut is 2%
    When the FX mismatch haircut is applied
    Then an additional 8% FX haircut should apply
    And the total haircut should be approximately 10%

  Scenario: No FX haircut when currencies match
    Given an exposure denominated in GBP
    And collateral denominated in GBP
    When the FX mismatch haircut is evaluated
    Then no FX haircut should apply

  Scenario: FX haircut formula application
    Given collateral value of £100,000
    And base haircut Hc of 2%
    And FX haircut Hfx of 8%
    When the comprehensive haircut is applied
    Then the adjusted value should follow:
      """
      C_adjusted = C × (1 - Hc) × (1 - Hfx)
      C_adjusted = £100,000 × 0.98 × 0.92 = £90,160
      """

  # =============================================================================
  # Immovable Property Collateral (CRR Art. 125-126)
  # =============================================================================

  @CRR-D5
  Scenario: Residential property collateral with LTV <= 80%
    Given an exposure of £500,000
    And residential property valued at £700,000
    And the LTV ratio is 71%
    When the collateral is evaluated for CRM
    Then the property collateral should be eligible
    And the exposure should receive residential mortgage treatment

  @CRR-D6
  Scenario: Commercial property collateral requires income cover
    Given an exposure of £1,000,000
    And commercial property valued at £2,000,000
    And the property generates rental income
    And the income covers 125% of debt service
    When the collateral is evaluated for CRM
    Then the property collateral should be eligible
    And the lower commercial RE risk weights should apply

  Scenario: Property collateral valuation requirements
    Given an exposure secured by property
    When the collateral eligibility is assessed
    Then the following valuation requirements must be met:
      | Requirement                          |
      | Independent valuation                |
      | Valuation at or below market value   |
      | Revaluation frequency met            |
      | Adequate property insurance          |

  # =============================================================================
  # Guarantee Substitution (CRR Art. 213-215)
  # =============================================================================

  @CRR-D7
  Scenario: Full guarantee from sovereign replaces obligor risk weight
    Given an exposure of £1,000,000 to a corporate
    And the corporate has CQS 4 (100% risk weight)
    And a full guarantee from UK Government (CQS 1)
    When the guarantee substitution is applied
    Then the guarantor risk weight of 0% should apply
    And the RWA should be £0

  @CRR-D8
  Scenario: Partial guarantee provides proportional benefit
    Given an exposure of £1,000,000 to a corporate
    And the corporate has CQS 4 (100% risk weight)
    And a partial guarantee of £600,000 from UK Government (CQS 1)
    When the guarantee substitution is applied
    Then the guaranteed portion (£600,000) receives 0% RW
    And the unguaranteed portion (£400,000) receives 100% RW
    And the total RWA should be £400,000

  Scenario: Guarantee eligibility requirements
    Given an exposure with a guarantee
    When the guarantee eligibility is assessed
    Then the following criteria must be met:
      | Criterion                                    |
      | Guarantee is direct and unconditional        |
      | Guarantee covers all payment obligations     |
      | Guarantee is legally enforceable             |
      | Guarantor is an eligible protection provider |

  @CRR-D9
  Scenario: Guarantee from institution provides partial benefit
    Given an exposure of £1,000,000 to an unrated corporate (100% RW)
    And a full guarantee from a UK bank with CQS 2 (30% RW)
    When the guarantee substitution is applied
    Then the guarantor risk weight of 30% should apply
    And the RWA should be £300,000

  # =============================================================================
  # CRM under IRB (CRR Art. 181)
  # =============================================================================

  @CRR-D10
  Scenario: Collateral reduces LGD under F-IRB
    Given an exposure of £1,000,000
    And eligible financial collateral of £400,000
    And the base supervisory LGD is 45%
    And the calculation approach is "F-IRB"
    When the collateral benefit is applied
    Then the LGD should be reduced per CRR formula
    And the effective LGD should be less than 45%

  Scenario: Real estate collateral reduces LGD under F-IRB
    Given an exposure secured by residential property
    And the LTV ratio is 60%
    And the calculation approach is "F-IRB"
    When the F-IRB LGD is determined
    Then the LGD should be reduced from 45%
    And the reduction should reflect property collateral value

  # =============================================================================
  # Provision Impact (CRR Art. 158-159)
  # =============================================================================

  @CRR-D11
  Scenario: Specific provisions reduce exposure under SA
    Given an exposure of £1,000,000
    And specific credit risk adjustments of £100,000
    And the calculation approach is "SA"
    When the exposure value is calculated
    Then the exposure should be reduced by provisions
    And the net exposure should be £900,000

  @CRR-D12
  Scenario: Expected loss shortfall under IRB
    Given an exposure with EAD of £1,000,000
    And PD of 2% and LGD of 45%
    And provisions of £5,000
    And the calculation approach is "F-IRB"
    When the expected loss comparison is performed
    Then expected loss should be PD × LGD × EAD = £9,000
    And there should be a shortfall of £4,000
    And the shortfall reduces CET1 capital

  Scenario: Excess provisions under IRB
    Given an exposure with EAD of £1,000,000
    And PD of 2% and LGD of 45%
    And provisions of £15,000
    And the calculation approach is "F-IRB"
    When the expected loss comparison is performed
    Then expected loss should be £9,000
    And there should be an excess of £6,000
    And the excess may be added to Tier 2 (capped)

  # =============================================================================
  # Multiple CRM Techniques
  # =============================================================================

  @CRR-D13
  Scenario: Exposure with both collateral and guarantee
    Given an exposure of £1,000,000 to an unrated corporate
    And cash collateral of £200,000
    And a partial guarantee of £300,000 from a CQS 2 bank
    When the CRM techniques are applied
    Then the collateral should first reduce exposure to £800,000
    And the guarantee should cover £300,000 at guarantor RW
    And the remaining £500,000 is at obligor RW

  Scenario: CRM allocation hierarchy
    Given an exposure with multiple CRM techniques
    When CRM benefits are allocated
    Then the allocation should follow this priority:
      | Priority | CRM Technique               |
      | 1        | Financial collateral        |
      | 2        | Real estate collateral      |
      | 3        | Receivables/other physical  |
      | 4        | Guarantees                  |
