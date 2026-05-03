"""
P1.114 fixture package — null-propagation defect in model permissions filter.

This package contains a minimal, self-contained set of fixtures for scenario P1.114:
a counterparty with null country_code and a facility/loan with null book_code, paired
with a model permissions row that has country_codes=null (no geo restriction) and
excluded_book_codes="TRADE_FINANCE" (non-null book exclusion).

Post-fix expected behaviour: the exposure routes to FIRB because book_code=null is
not in the exclusion list {"TRADE_FINANCE"}.

Pre-fix behaviour: null-propagation in the book_not_excluded predicate causes
permission_valid to be null, which falls through to SA.

Reference: IMPLEMENTATION_PLAN.md item P1.114, CRR Art. 143.
"""
