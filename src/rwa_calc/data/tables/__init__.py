"""
Regulatory lookup tables for RWA calculations.

This package historically hosted regulatory lookup tables; the SA risk-weight
and CRM supervisory-haircut table modules have been relocated into ``engine/``
(Phase 5 / S13) now that their values live in the rulepack packs. The only
remaining module is the (test-only) F-IRB floor/cap helper.

Modules:
    firb_lgd: F-IRB PD/maturity floors and caps (CRR Art. 162/163)
"""
