@common @hierarchy @classification
Feature: Counterparty Hierarchy and Exposure Classification
  As a bank processing credit exposures
  I need to correctly resolve counterparty hierarchies and classify exposures
  So that ratings are inherited correctly and exposure classes are accurate

  # =============================================================================
  # Counterparty Hierarchy
  # =============================================================================

  @HIER-1
  Scenario: Subsidiary inherits rating from parent
    Given a subsidiary counterparty "SUB_001" with no external rating
    And the parent entity "PARENT_001" has CQS 2
    When the rating is resolved for risk weighting
    Then the subsidiary should inherit the parent's CQS of 2
    And the inheritance path should be documented

  @HIER-2
  Scenario: Multi-level hierarchy rating inheritance
    Given a counterparty "GRANDCHILD_001" with no external rating
    And its parent "CHILD_001" also has no external rating
    And the ultimate parent "ULT_PARENT_001" has CQS 1
    When the rating is resolved
    Then the counterparty should inherit CQS 1 from ultimate parent
    And the full inheritance chain should be traced

  @HIER-3
  Scenario: Own rating takes precedence over inherited
    Given a subsidiary counterparty "SUB_002" with CQS 3
    And the parent entity "PARENT_002" has CQS 1
    When the rating is resolved for risk weighting
    Then the subsidiary's own rating of CQS 3 should be used
    And parent rating should not override

  Scenario: Unrated counterparty with unrated parent
    Given a counterparty with no external rating
    And the parent entity also has no external rating
    And there is no ultimate parent with a rating
    When the rating is resolved
    Then the counterparty should be treated as unrated
    And the unrated risk weight should apply

  Scenario Outline: Rating inheritance priority
    Given counterparty has own rating: <own_rating>
    And parent has rating: <parent_rating>
    And group has rating: <group_rating>
    When the rating is resolved
    Then the used rating should be: <used_rating>

    Examples:
      | own_rating | parent_rating | group_rating | used_rating |
      | CQS 2      | CQS 1         | CQS 1        | CQS 2       |
      | none       | CQS 3         | CQS 2        | CQS 3       |
      | none       | none          | CQS 4        | CQS 4       |
      | none       | none          | none         | unrated     |

  # =============================================================================
  # Lending Group Aggregation
  # =============================================================================

  @HIER-4
  Scenario: Lending group aggregation for retail threshold
    Given multiple exposures to entities in lending group "LG_001":
      | Entity     | Exposure    |
      | ENTITY_A   | £400,000    |
      | ENTITY_B   | £350,000    |
      | ENTITY_C   | £300,000    |
    And the retail threshold is £1,000,000
    When the lending group total is calculated
    Then the total exposure should be £1,050,000
    And the threshold is exceeded
    And entities should be reclassified from retail

  @HIER-5
  Scenario: Residential property excluded from retail threshold
    Given a natural person counterparty
    And exposures:
      | Type                | Amount    |
      | Personal loan       | £400,000  |
      | Credit card         | £100,000  |
      | Residential mortgage| £600,000  |
    And the retail threshold is £1,000,000
    When the retail threshold is evaluated
    Then only non-property exposures count (£500,000)
    And the threshold is not exceeded
    And the counterparty remains retail classified

  Scenario: Lending group includes connected parties
    Given a natural person "PERSON_A"
    And their connected parties in the same lending group:
      | Party      | Relationship |
      | SPOUSE_A   | Spouse       |
      | COMPANY_A  | Sole trader  |
    When lending group exposure is aggregated
    Then all connected party exposures should be included
    And the total determines retail threshold breach

  # =============================================================================
  # Exposure Class Determination
  # =============================================================================

  @CLASS-1
  Scenario: Central government classified as Sovereign
    Given a counterparty of type "CENTRAL_GOVERNMENT"
    And the counterparty is UK Government
    When the exposure class is determined
    Then the exposure class should be "SOVEREIGN"
    And the SA risk weight table for sovereigns should apply

  @CLASS-2
  Scenario: Credit institution classified as Institution
    Given a counterparty of type "CREDIT_INSTITUTION"
    And the counterparty is a UK-regulated bank
    When the exposure class is determined
    Then the exposure class should be "INSTITUTION"
    And UK-specific deviations should apply

  @CLASS-3
  Scenario: Large corporate classification
    Given a counterparty of type "CORPORATE"
    And annual turnover exceeds €50m
    And the exposure is not specialised lending
    When the exposure class is determined
    Then the exposure class should be "CORPORATE"
    And no SME treatment should apply

  @CLASS-4
  Scenario: SME corporate classification
    Given a counterparty of type "CORPORATE"
    And annual turnover is £30,000,000 (below €50m equivalent)
    When the exposure class is determined
    Then the exposure class should be "CORPORATE_SME"
    And SME supporting factor eligibility should be checked

  @CLASS-5
  Scenario: Natural person retail classification
    Given a counterparty of type "NATURAL_PERSON"
    And total exposure to lending group is £500,000
    And the exposure is a personal loan
    When the exposure class is determined
    Then the exposure class should be "RETAIL_OTHER"
    And the 75% retail risk weight should apply

  @CLASS-6
  Scenario: Residential mortgage classification
    Given a counterparty of type "NATURAL_PERSON"
    And the product is a residential mortgage
    And secured by the borrower's primary residence
    When the exposure class is determined
    Then the exposure class should be "RETAIL_MORTGAGE"
    And LTV-based risk weights should apply

  @CLASS-7
  Scenario: QRRE classification
    Given a retail revolving credit facility
    And the facility is unsecured
    And credit limit does not exceed €100,000
    And the facility is unconditionally cancellable
    When the exposure class is determined
    Then the exposure class should be "RETAIL_QRRE"
    And the QRRE correlation formula should apply under IRB

  Scenario Outline: Entity type to exposure class mapping
    Given a counterparty of type "<entity_type>"
    And turnover is <turnover>
    And exposure is <exposure>
    When the exposure class is determined
    Then the class should be "<exposure_class>"

    Examples:
      | entity_type           | turnover | exposure    | exposure_class   |
      | CENTRAL_GOVERNMENT    | N/A      | £1,000,000  | SOVEREIGN        |
      | CENTRAL_BANK          | N/A      | £5,000,000  | SOVEREIGN        |
      | REGIONAL_GOVERNMENT   | N/A      | £2,000,000  | RGLA             |
      | LOCAL_AUTHORITY       | N/A      | £1,000,000  | RGLA             |
      | PUBLIC_SECTOR_ENTITY  | N/A      | £3,000,000  | PSE              |
      | CREDIT_INSTITUTION    | N/A      | £10,000,000 | INSTITUTION      |
      | INVESTMENT_FIRM       | N/A      | £5,000,000  | INSTITUTION      |
      | CORPORATE             | £100m    | £25,000,000 | CORPORATE        |
      | CORPORATE             | £20m     | £2,000,000  | CORPORATE_SME    |
      | NATURAL_PERSON        | N/A      | £50,000     | RETAIL_OTHER     |

  # =============================================================================
  # SA vs IRB Exposure Class Differences
  # =============================================================================

  @CLASS-8
  Scenario: RGLA treatment differs between SA and IRB
    Given a counterparty of type "REGIONAL_GOVERNMENT"
    When determining exposure class for SA
    Then the class may be "RGLA" with specific SA rules
    When determining exposure class for IRB
    Then the class should map to "INSTITUTION" or "CORPORATE"
    And the IRB formula should apply accordingly

  Scenario: PSE treatment varies by approach
    Given a counterparty of type "PUBLIC_SECTOR_ENTITY"
    When determining exposure class for SA
    Then the class is "PSE" with sovereign or institution treatment
    When determining exposure class for IRB
    Then PSE may receive institution or corporate treatment
    And the specific mapping depends on PSE category

  # =============================================================================
  # Approach Assignment
  # =============================================================================

  @APPROACH-1
  Scenario: Exposure assigned to SA when no IRB permission
    Given a corporate exposure
    And the bank has no IRB permission for corporates
    When the calculation approach is determined
    Then the approach should be "SA"
    And SA risk weights should apply

  @APPROACH-2
  Scenario: Exposure assigned to F-IRB with permission
    Given a corporate exposure
    And the bank has F-IRB permission for corporates
    And the exposure meets IRB eligibility criteria
    When the calculation approach is determined
    Then the approach should be "F-IRB"
    And supervisory LGD should be used

  @APPROACH-3
  Scenario: Specialised lending assigned to slotting
    Given an income-producing real estate exposure
    And the exposure qualifies as specialised lending
    And the bank does not have full IRB for this class
    When the calculation approach is determined
    Then the approach should be "SLOTTING"
    And slotting category risk weights should apply

  Scenario: Mixed approach portfolio
    Given a portfolio with multiple exposure classes
    And the bank has:
      | Exposure Class | Permission |
      | Corporate      | F-IRB      |
      | Retail         | A-IRB      |
      | Institution    | SA         |
    When approaches are assigned
    Then each exposure should use the permitted approach
    And results should be aggregated across approaches
