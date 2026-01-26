@crr @ccf
Feature: CRR Credit Conversion Factors
  As a bank calculating EAD for off-balance sheet exposures
  I need to apply correct credit conversion factors by product type and approach
  So that my EAD calculations comply with CRR Articles 111, 166

  Background:
    Given the regulatory framework is "CRR"

  # =============================================================================
  # SA Credit Conversion Factors (CRR Art. 111)
  # =============================================================================

  @CRR-D1
  Scenario: Full risk commitment receives 100% CCF under SA
    Given a facility classified as "FULL_RISK" (FR)
    And the facility limit is £5,000,000
    And drawn amount is £1,000,000
    And undrawn amount is £4,000,000
    And the calculation approach is "SA"
    When the EAD is calculated
    Then the CCF of 100% should apply to undrawn
    And EAD should be £1,000,000 + (£4,000,000 × 100%) = £5,000,000

  @CRR-D2
  Scenario: Medium risk commitment receives 50% CCF under SA
    Given a facility classified as "MEDIUM_RISK" (MR)
    And the facility limit is £5,000,000
    And drawn amount is £1,000,000
    And undrawn amount is £4,000,000
    And the calculation approach is "SA"
    When the EAD is calculated
    Then the CCF of 50% should apply to undrawn
    And EAD should be £1,000,000 + (£4,000,000 × 50%) = £3,000,000

  @CRR-D3
  Scenario: Medium-low risk commitment receives 20% CCF under SA
    Given a facility classified as "MEDIUM_LOW_RISK" (MLR)
    And the facility limit is £2,000,000
    And drawn amount is £500,000
    And undrawn amount is £1,500,000
    And the calculation approach is "SA"
    When the EAD is calculated
    Then the CCF of 20% should apply to undrawn
    And EAD should be £500,000 + (£1,500,000 × 20%) = £800,000

  @CRR-D4
  Scenario: Low risk (unconditionally cancellable) commitment receives 0% CCF
    Given a facility classified as "LOW_RISK" (LR)
    And the facility is unconditionally cancellable without notice
    And the facility limit is £100,000
    And drawn amount is £20,000
    And undrawn amount is £80,000
    And the calculation approach is "SA"
    When the EAD is calculated
    Then the CCF of 0% should apply to undrawn
    And EAD should be £20,000 (drawn only)

  Scenario Outline: SA CCF by risk category
    Given a facility classified as "<risk_category>"
    And drawn amount is £100,000
    And undrawn amount is £100,000
    And the calculation approach is "SA"
    When the EAD is calculated
    Then the CCF should be <ccf>
    And EAD should be <ead>

    Examples:
      | risk_category   | ccf  | ead      |
      | FULL_RISK       | 100% | £200,000 |
      | MEDIUM_RISK     | 50%  | £150,000 |
      | MEDIUM_LOW_RISK | 20%  | £120,000 |
      | LOW_RISK        | 0%   | £100,000 |

  # =============================================================================
  # F-IRB Credit Conversion Factors (CRR Art. 166)
  # =============================================================================

  @CRR-D5
  Scenario: F-IRB uses 75% CCF for medium risk commitments
    Given a facility classified as "MEDIUM_RISK" (MR)
    And the facility limit is £5,000,000
    And drawn amount is £1,000,000
    And undrawn amount is £4,000,000
    And the calculation approach is "F-IRB"
    When the EAD is calculated
    Then the CCF of 75% should apply to undrawn
    And EAD should be £1,000,000 + (£4,000,000 × 75%) = £4,000,000

  @CRR-D6
  Scenario: F-IRB uses 75% CCF for medium-low risk commitments
    Given a facility classified as "MEDIUM_LOW_RISK" (MLR)
    And the facility limit is £2,000,000
    And drawn amount is £500,000
    And undrawn amount is £1,500,000
    And the calculation approach is "F-IRB"
    When the EAD is calculated
    Then the CCF of 75% should apply to undrawn
    And EAD should be £500,000 + (£1,500,000 × 75%) = £1,625,000

  Scenario Outline: F-IRB CCF by risk category
    Given a facility classified as "<risk_category>"
    And drawn amount is £100,000
    And undrawn amount is £100,000
    And the calculation approach is "F-IRB"
    When the EAD is calculated
    Then the CCF should be <ccf>

    Examples:
      | risk_category   | ccf  |
      | FULL_RISK       | 100% |
      | MEDIUM_RISK     | 75%  |
      | MEDIUM_LOW_RISK | 75%  |
      | LOW_RISK        | 0%   |

  # =============================================================================
  # Special CCF Cases
  # =============================================================================

  @CRR-D7
  Scenario: Trade finance short-term LC receives 20% CCF under F-IRB
    Given a short-term self-liquidating trade letter of credit
    And the facility limit is £1,000,000
    And the commitment is fully undrawn
    And the calculation approach is "F-IRB"
    When the EAD is calculated
    Then the CCF of 20% should apply
    And EAD should be £200,000

  Scenario: Note issuance facility receives applicable CCF
    Given a note issuance facility (NIF)
    And the facility limit is £50,000,000
    And the commitment is fully undrawn
    When the EAD is calculated
    Then the CCF should be determined by the underlying risk category

  Scenario: Revolving underwriting facility
    Given a revolving underwriting facility (RUF)
    And the facility limit is £25,000,000
    When the EAD is calculated
    Then the CCF should be 50% under SA
    And the CCF should be 75% under F-IRB

  # =============================================================================
  # EAD Calculation
  # =============================================================================

  @CRR-D8
  Scenario: EAD calculation with partial draw
    Given a committed facility with:
      | Field        | Value       |
      | Limit        | £10,000,000 |
      | Drawn        | £3,000,000  |
      | Undrawn      | £7,000,000  |
      | Risk Category| MR          |
    And the calculation approach is "SA"
    When the EAD is calculated
    Then EAD should be Drawn + (Undrawn × CCF)
    And EAD should be £3,000,000 + (£7,000,000 × 50%) = £6,500,000

  Scenario: Fully drawn facility has no CCF impact
    Given a facility that is fully drawn
    And the facility limit equals drawn amount of £5,000,000
    And undrawn amount is £0
    When the EAD is calculated
    Then EAD should equal drawn amount
    And CCF should not affect EAD

  Scenario: Fully undrawn facility uses CCF on full limit
    Given a facility that is fully undrawn
    And the facility limit is £2,000,000
    And drawn amount is £0
    And the risk category is "MR"
    And the calculation approach is "SA"
    When the EAD is calculated
    Then EAD should be £2,000,000 × 50% = £1,000,000

  # =============================================================================
  # On-Balance Sheet Items
  # =============================================================================

  @CRR-D9
  Scenario: On-balance sheet loan has implicit 100% CCF
    Given a drawn loan with no undrawn commitment
    And the loan balance is £1,000,000
    When the EAD is calculated
    Then EAD should equal the loan balance
    And the CCF is implicitly 100%

  Scenario: Contingent liability with specific CCF
    Given a financial guarantee
    And the guaranteed amount is £5,000,000
    And the guarantee is not yet called
    And the risk category is "FR"
    When the EAD is calculated
    Then the CCF of 100% should apply
    And EAD should be £5,000,000
