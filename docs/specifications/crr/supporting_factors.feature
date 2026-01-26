@crr @supporting-factors
Feature: CRR Supporting Factors
  As a bank calculating RWA under the CRR framework
  I need to apply SME and infrastructure supporting factors where eligible
  So that my capital requirements reflect the regulatory concessions in CRR Art. 501

  Background:
    Given the regulatory framework is "CRR"

  # =============================================================================
  # SME Supporting Factor (CRR Art. 501)
  # =============================================================================

  @CRR-A10
  Scenario: SME corporate receives 0.7619 supporting factor
    Given a counterparty "SME_CORP_001" of type "CORPORATE"
    And the counterparty annual turnover is £30,000,000
    And the SME turnover threshold is £44,000,000
    And a loan "LOAN_CORP_SME_001" with drawn amount £2,000,000
    And the exposure is below the SME exposure threshold of €1.5m
    When the SA risk weight is calculated
    Then the exposure class should be "CORPORATE_SME"
    And the base risk weight should be 100%
    And the SME supporting factor of 0.7619 should be applied
    And the RWA after supporting factor should be £1,523,800

  @CRR-A11
  Scenario: SME retail receives 0.7619 supporting factor
    Given a counterparty "SME_RTL_001" of type "SME"
    And the counterparty annual turnover is £5,000,000
    And a loan "LOAN_RTL_SME_001" with drawn amount £500,000
    When the SA risk weight is calculated
    Then the exposure class should be "RETAIL_OTHER"
    And the base risk weight should be 75%
    And the SME supporting factor of 0.7619 should be applied
    And the RWA after supporting factor should be £285,712.50

  @CRR-A12
  Scenario: Large corporate does not receive SME supporting factor
    Given a counterparty "LARGE_CORP_001" of type "CORPORATE"
    And the counterparty annual turnover is £500,000,000
    And the SME turnover threshold is £44,000,000
    And a loan "LOAN_CORP_UK_001" with drawn amount £25,000,000
    When the SA risk weight is calculated
    Then the exposure class should be "CORPORATE"
    And the base risk weight should be 100%
    And the supporting factor should be 1.0
    And the RWA after supporting factor should be £25,000,000

  Scenario: SME exposure above €1.5m threshold receives reduced factor
    Given a counterparty of type "CORPORATE"
    And the counterparty annual turnover is £30,000,000
    And a loan with drawn amount £2,000,000
    And the total SME exposure exceeds €1.5m threshold
    When the SA risk weight is calculated
    Then the portion up to €1.5m receives 0.7619 factor
    And the portion above €1.5m receives 0.85 factor

  Scenario: SME supporting factor applied after risk weight calculation
    Given a counterparty classified as SME
    And the base RWA is £1,000,000
    When supporting factors are applied
    Then the calculation order should be:
      | Step | Calculation                           |
      | 1    | Calculate base RWA (EAD × RW)         |
      | 2    | Apply SME factor (× 0.7619)           |
      | 3    | Result is final RWA                   |

  # =============================================================================
  # Infrastructure Supporting Factor (CRR Art. 501a)
  # =============================================================================

  Scenario: Qualifying infrastructure project receives 0.75 supporting factor
    Given a counterparty operating a qualifying infrastructure project
    And the project meets all CRR Art. 501a criteria
    And a loan with drawn amount £10,000,000
    When the SA risk weight is calculated
    Then the infrastructure supporting factor of 0.75 should be applied

  Scenario: Infrastructure factor eligibility criteria
    Given an exposure to an infrastructure entity
    When determining infrastructure factor eligibility
    Then the following criteria must be met:
      | Criterion                                    |
      | Project in EEA or OECD country               |
      | Contractual revenue stream from public body  |
      | Revenues predictable and cover obligations   |
      | Operator can meet financial obligations      |
      | Material revenue from non-public sources     |

  # =============================================================================
  # Combined Supporting Factors
  # =============================================================================

  Scenario: SME infrastructure project receives both factors
    Given a counterparty that is both an SME
    And the counterparty operates a qualifying infrastructure project
    And a loan with drawn amount £5,000,000
    When the SA risk weight is calculated
    Then both SME and infrastructure factors may apply
    And the combined factor is 0.7619 × 0.75 = 0.5714

  # =============================================================================
  # IRB Supporting Factors
  # =============================================================================

  Scenario: SME corporate under F-IRB receives supporting factor
    Given a counterparty classified as "CORPORATE_SME"
    And the calculation approach is "F-IRB"
    And the IRB RWA before supporting factor is £800,000
    When supporting factors are applied
    Then the SME supporting factor of 0.7619 should be applied
    And the RWA after supporting factor should be £609,520

  Scenario: Large corporate under IRB does not receive SME factor
    Given a counterparty of type "CORPORATE"
    And the counterparty annual turnover exceeds €50m
    And the calculation approach is "F-IRB"
    When supporting factors are applied
    Then no SME supporting factor should be applied
    And the supporting factor should be 1.0
