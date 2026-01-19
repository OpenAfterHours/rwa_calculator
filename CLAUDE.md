## Reference Documentation

### UK Basel 3.1 Credit Risk References

When working on this project, to understand some of the regulations for the RWA calculation, refer to these resource (taking the PRA resources as priority over BCBS):

#### Current regulations
Please focus on the Credit Risk sections
- https://www.prarulebook.co.uk/pra-rules/crr-firms
- https://www.legislation.gov.uk/eur/2013/575/contents

#### Basel 3.1 implentation
- PRA PS9/24 for UK-specific implementation rules - https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2
- BCBS CRE standards for underlying methodology - https://www.bis.org/basel_framework/standard/CRE.htm?tldate=20260111
- PRA CP16/22 - Implementation of Basel 3.1 Standards - https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards
Each of the above is also found in PDF format within the ref_docs folder.

Key topics:
- Standardised approach risk weights (CRE20-22)
- IRB approach (CRE30-36)
- Credit risk mitigation (CRE22)
- Equity approach (CR60)
- Exposure classes and slotting criteria

## Tools
Utilise the following tooling:
- Use Polars as the default dataframe library - prioritising LazyFrames over Eager. check the resources found here: https://docs.pola.rs/api/python/stable/reference/index.html
- DuckDB for areas where it is more suitable than polars
- UV and UV native commands i.e. UV add instead of UV pip install
- Marimo for workbooks - check the resources found here: https://docs.marimo.io/api/
- Pytest for testing

## Coding standards
- Research ideas before starting to code. Create a plan and the implement the plan.
- TDD should be utilised when implementing the plan to ensure what has been coded satisfies what was needed.
- Clean code principles should be utilised
- When structuring a module please include the main entry point at the top with next key priority elements underneath so it's like reading a book when i'm trying to understand whats happening
- Update the documentation after any updates