"""
P1.355 — the QRRE per-individual aggregate must be capped at the multi-option
facility's umbrella limit (CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (RawDataBundle -> HierarchyResolver -> ExposureClassifier, exercising
    ``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``)

Key responsibilities:
- Provide ``build_p1_355_raw_bundle`` carrying every multi-option-facility
  (MOF) leg below on its own counterparty, so each per-individual aggregate is
  isolated and no leg's outcome depends on another's. The acceptance sibling
  pins this bundle's portfolio totals, so later controls live in the two
  bundles below rather than being added to it.
- Provide ``build_p1_355_guard_bundle``: the overdrawn-umbrella guard's controls
  on contingent drawings (on- and off-balance-sheet) and on currency (drawings
  compared with the root's limit in the ROOT facility's currency).
- Provide ``build_p1_355_duplicate_bundle``: a duplicated facility reference
  (DQ004; the pipeline continues) must not multiply any leg through the
  root-limit join.
- Provide ``build_p1_355_shared_bundle``: two individuals under ONE umbrella,
  each also holding a standalone revolver, so the cap must be applied per
  (individual, umbrella) and never pooled across the umbrella's owners.
- Exercise the grain P1.320 left standing: a drawn leg keys on its IMMEDIATE
  (sub-)facility and carries the sub-limit, every MOF waterfall / residual leg
  keys on the ROOT and carries the root's limit — and nothing caps the limits
  under one root by the root's own limit. P1.320's leg (v) is the fourth mover;
  it lives in ``tests/fixtures/p1_320`` and is re-pointed there.

The approved reading (owner sign-off, P1.355 decision brief): an individual's
aggregate nominal exposure under one umbrella is ``min(umbrella limit, sum of
the distinct limits counted under it)``, and it is never the largest single
sub-limit (the "max trap" — it drops every other sub-limit). Today's
conservative result is KEPT in four cases, each pinned by a control below:

1. the umbrella carries no limit (null root);
2. a sub-limit under the umbrella is null;
3. the individual has drawn more under the umbrella than its limit — an
   overdrawn or zero-limit root, where the cap would count them below their own
   drawn balance — or a drawing under it cannot be put in the umbrella's
   currency (no FX rate);
4. a sibling sub-line fails the QRRE gate (its waterfall leg still charges the
   root's limit — P1.320 leg (vi), unchanged).

QRRE ceiling — read from the pack, never typed here (LESSONS A4):
    ``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)``
    CRR:  EUR 100,000 x eur_gbp_rate -> GBP 87,320.00 at the default rate.
    B31:  GBP 90,000.00 (native).

Leg inventory (aggregate = the counterparty's Art. 147(5A)(c) figure, GBP):

    MOVERS — retail_other at HEAD, retail_qrre once capped
    (NRL)  no root leg          root 80,000; subs 60,000 + 60,000; 40,000
                                 drawn under each. The umbrella is fully drawn
                                 so no waterfall / residual leg exists — only
                                 the two sub-keyed loans.
                                 HEAD 120,000 -> capped 80,000.
    (DEEP) three levels         root 70,000 -> mid 40,000 -> leaf 20,000;
                                 10,000 drawn under the leaf. Waterfall legs for
                                 BOTH the mid and the nested leaf, plus a
                                 residual, all at the root's 70,000.
                                 HEAD 90,000 (20,000 + 70,000) -> capped 70,000.
                                 A CRR mover only: 90,000 is within the B31
                                 ceiling ("or less") and above the CRR one, so
                                 HEAD already splits the regimes here.
    (XOWN) sub owned by a       root 70,000 owned by CP_XOWN_ROOT; sub 25,000
           second individual    owned by CP_XOWN_SUB, who draws 10,000 under it.
                                 CP_XOWN_SUB holds the loan (25,000) and the
                                 sub's waterfall leg (root's 70,000).
                                 HEAD 95,000 -> capped 70,000. CP_XOWN_ROOT
                                 holds only the residual: 70,000 either way.

    CONTROLS — the same class on both sides
    (ABOVE)    umbrella above     root 100,000; subs 60,000 + 60,000; 50,000
               the ceiling,       drawn under each. HEAD 120,000, capped
               fully drawn        100,000: retail_other both sides. The MAX
                                  TRAP gives 60,000 and wrongly admits it.
    (NULLFULL) null root,         root limit null; subs 50,000 + 50,000 fully
               fully drawn        drawn. No root leg. 100,000 both sides: a
                                  null umbrella caps nothing. The max trap gives
                                  50,000 and wrongly admits it.
    (NULLPART) null root,         root limit null; subs 30,000 + 30,000, 10,000
               partially drawn    drawn under each. The root-keyed waterfall legs
                                  carry a null limit -> unbounded both sides.
                                  A "sum of the sub-limits" rule for a null root
                                  would give 60,000 and admit it — the owner
                                  kept today's result instead.
    (RESID)    umbrella above     root 100,000; sub 25,000; 10,000 drawn under
               the ceiling, with  the sub. Legs: loan 25,000, waterfall 100,000,
               a residual leg     residual 100,000. HEAD 125,000, capped 100,000:
                                  retail_other. Reading "anything drawn
                                  directly against the root" as a DRAWN amount
                                  rather than the root's own limit gives
                                  min(100,000, 25,000) and wrongly admits it.
    (BULLET)   the plan bullet's  root 50,000; subs 30,000 + 30,000; 10,000
               own example        drawn under SUBA. HEAD 80,000, capped 50,000:
                                  retail_qrre both sides — the live-cell
                                  control (LESSONS B5): it keeps the QRRE
                                  population non-empty pre-fix.
    (NULLSUB)  null sub-limit     root 50,000; sub limit null; 10,000 drawn
               under a limited    under the sub. Legs: loan (null -> unbounded)
               umbrella           and the residual (50,000). Unbounded both
                                  sides: a null limit inside the umbrella keeps
                                  today's result rather than being capped.
    (OVER)     overdrawn          root 50,000; subs 60,000 + 60,000; 55,000
               umbrella           drawn under each (110,000 > the root). No root
                                  leg. HEAD 120,000; the root's limit does not
                                  bound what the individual drew, so no cap:
                                  120,000, retail_other both sides. Capping at
                                  the root would give 50,000 — below the
                                  individual's own 110,000 drawn balance, and
                                  wrongly QRRE.
    (ZERO)     zero umbrella      root limit 0; subs 60,000 + 60,000; 40,000
               limit              drawn under each. No root leg. The same guard:
                                  120,000 both sides, retail_other. Capping at 0
                                  would admit it (a feed that writes "no limit"
                                  as 0 is the plausible source).

Guard bundle (``build_p1_355_guard_bundle``) — every leg a fully drawn
umbrella (no waterfall / residual leg) unless stated, so the only question is
whether the root's limit caps the two sub-limits:

    (ONB)    on-balance-sheet  root 50,000; subs 60,000 + 60,000; a 30,000 loan
             contingent        under SUBA and a 30,000 ON-balance-sheet
                               contingent under SUBB. 60,000 drawn > the root:
                               no cap, 120,000, retail_other both sides. The
                               unified frame carries an ONB contingent's amount
                               in ``drawn_amount`` (``nominal_amount`` is 0), so
                               a guard reading only a contingent's nominal sees
                               30,000 and wrongly caps (50,000 -> QRRE).
    (OFB)    off-balance-sheet the same with an OFF-balance-sheet contingent
             contingent        (amount in ``nominal_amount``): a guard reading
                               only ``drawn_amount`` wrongly caps.
    (FXEUR)  one-currency      root EUR 80,000; subs EUR 60,000 + 60,000; EUR
             EUR book,         42,000 drawn under each — 84,000 > the root in
             overdrawn         EUR, so no cap: retail_other both sides. In the
                               reporting currency the drawings are GBP 73,349 <
                               80,000, so a guard comparing them with the root's
                               EUR limit unconverted wrongly caps.
    (FXOK)   one-currency      as FXEUR with EUR 40,000 drawn under each —
             EUR book, within  80,000, within the root: CAPPED, a MOVER (HEAD
                               120,000 -> 80,000). The guard is not merely
                               refusing every non-GBP umbrella.
    (FXMIX)  GBP drawings      root EUR 80,000; subs EUR 60,000 + 60,000; GBP
             under a EUR       36,000 drawn under each = EUR 82,455 at the
             umbrella          run's rate > the root: no cap, retail_other. A
                               guard that compares the GBP amounts, or converts
                               them the wrong way (EUR 62,870), wrongly caps.
    (NORATE) a drawing the run root GBP 80,000; subs GBP 60,000 + 60,000; USD
             cannot convert    40,000 drawn under each and no USD rate. The
                               hierarchy leaves the unmeasurable drawings out of
                               the root's netting, so waterfall legs exist
                               (root-keyed, 80,000): HEAD 200,000. The guard
                               cannot measure the drawings, so no cap: 200,000,
                               retail_other. A guard that skipped them (sum of
                               nothing = 0) would cap at 80,000 and admit it.

Duplicate bundle (``build_p1_355_duplicate_bundle``) — the facilities table
repeats two references (DQ004):

    (DUP)    duplicated MOF    the NRL shape on a root listed twice: root
             root              80,000; subs 60,000 + 60,000; 40,000 drawn under
                               each. One row per loan, each carrying the root's
                               limit once: capped 80,000, QRRE.
    (DUPS)   duplicated        a facility listed twice, limit 50,000, one loan
             single-level      of 10,000 under it: its own root. The root-limit
             facility          join must add no copy beyond those the
                               immediate-parent join already makes.

Shared bundle (``build_p1_355_shared_bundle``) — the per-INDIVIDUAL half of
the cap's key. CONTROLS: retail_other at HEAD and after the fix, in both regimes.

    (SHARED) one umbrella,    root 80,000 owned by CP_SHARED_A; sub A 60,000
             two individuals  (CP_SHARED_A) and sub B 60,000 (CP_SHARED_B),
                              40,000 drawn under each — the umbrella is fully
                              drawn, so no root-keyed leg. Each individual also
                              holds a standalone 50,000 revolver, 10,000 drawn
                              (a loan and its ``_UNDRAWN`` headroom leg).
                              Each individual: min(80,000, 60,000) + 50,000 =
                              110,000, over both ceilings — retail_other.
                              A cap keyed on the umbrella ALONE pools the two
                              owners: min(80,000, 120,000) = 80,000 credited to
                              whichever owner holds the first candidate leg,
                              0 to the other, whose figure falls to 50,000 and
                              is wrongly admitted to QRRE. The headroom-netting
                              sibling works per root across every obligor, which
                              is why that grain is the natural wrong copy.

Field mapping (both regimes): as ``tests/fixtures/p1_320`` — natural-person,
pool-managed retail counterparties (``is_managed_as_retail=True`` isolates the
(c) limb from the owed-amount retail test), revolving / unsecured / committed
``LR`` facilities with ``is_qrre_transactor=False``, drawn loans in GBP unless a
leg above states another currency. The guard bundle's FX table carries EUR ->
GBP at ``EUR_GBP_RATE`` (the config default, so the CRR ceiling is unchanged)
and deliberately no USD rate.

References:
- CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c): QRRE per-individual aggregate.
- ``src/rwa_calc/engine/hierarchy/facility_undrawn.py``: MOF waterfall rows and
  the residual carry the ROOT's ``limit`` and key on the root.
- ``src/rwa_calc/engine/hierarchy/enrich.py``: a drawn leg's ``facility_limit``
  comes from its IMMEDIATE parent; ``root_facility_limit`` from its root.

Usage:
    from tests.fixtures.p1_355.p1_355 import build_p1_355_raw_bundle
    from tests.fixtures.p1_355.p1_355 import build_p1_355_guard_bundle
    from tests.fixtures.p1_355.p1_355 import build_p1_355_duplicate_bundle
    from tests.fixtures.p1_355.p1_355 import build_p1_355_shared_bundle
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.bundles import RawDataBundle

# ---------------------------------------------------------------------------
# Identity constants — one counterparty per leg (isolated aggregates)
# ---------------------------------------------------------------------------

#: (NRL) fully drawn umbrella, no root leg — MOVER.
CP_NRL: str = "P1355_CP_NRL"
FAC_NRL_ROOT: str = "P1355_FAC_NRL_ROOT"
FAC_NRL_SUBA: str = "P1355_FAC_NRL_SUBA"
FAC_NRL_SUBB: str = "P1355_FAC_NRL_SUBB"
LN_NRL_A: str = "P1355_LN_NRL_A"
LN_NRL_B: str = "P1355_LN_NRL_B"

#: (DEEP) three-level hierarchy — CRR MOVER, B31 control.
CP_DEEP: str = "P1355_CP_DEEP"
FAC_DEEP_ROOT: str = "P1355_FAC_DEEP_ROOT"
FAC_DEEP_MID: str = "P1355_FAC_DEEP_MID"
FAC_DEEP_LEAF: str = "P1355_FAC_DEEP_LEAF"
LN_DEEP: str = "P1355_LN_DEEP"
EXP_DEEP_MID_UNDRAWN: str = FAC_DEEP_ROOT + "_UNDRAWN_" + FAC_DEEP_MID
EXP_DEEP_LEAF_UNDRAWN: str = FAC_DEEP_ROOT + "_UNDRAWN_" + FAC_DEEP_LEAF
EXP_DEEP_RESIDUAL: str = FAC_DEEP_ROOT + "_UNDRAWN_RESIDUAL"

#: (XOWN) sub-facility owned by a second individual — MOVER for that individual.
CP_XOWN_ROOT: str = "P1355_CP_XOWN_ROOT"
CP_XOWN_SUB: str = "P1355_CP_XOWN_SUB"
FAC_XOWN_ROOT: str = "P1355_FAC_XOWN_ROOT"
FAC_XOWN_SUB: str = "P1355_FAC_XOWN_SUB"
LN_XOWN: str = "P1355_LN_XOWN"
EXP_XOWN_SUB_UNDRAWN: str = FAC_XOWN_ROOT + "_UNDRAWN_" + FAC_XOWN_SUB
EXP_XOWN_RESIDUAL: str = FAC_XOWN_ROOT + "_UNDRAWN_RESIDUAL"

#: (ABOVE) fully drawn umbrella whose own limit is above the ceiling — control.
CP_ABOVE: str = "P1355_CP_ABOVE"
FAC_ABOVE_ROOT: str = "P1355_FAC_ABOVE_ROOT"
FAC_ABOVE_SUBA: str = "P1355_FAC_ABOVE_SUBA"
FAC_ABOVE_SUBB: str = "P1355_FAC_ABOVE_SUBB"
LN_ABOVE_A: str = "P1355_LN_ABOVE_A"
LN_ABOVE_B: str = "P1355_LN_ABOVE_B"

#: (NULLFULL) null umbrella limit, fully drawn subs — control.
CP_NULLFULL: str = "P1355_CP_NULLFULL"
FAC_NULLFULL_ROOT: str = "P1355_FAC_NULLFULL_ROOT"
FAC_NULLFULL_SUBA: str = "P1355_FAC_NULLFULL_SUBA"
FAC_NULLFULL_SUBB: str = "P1355_FAC_NULLFULL_SUBB"
LN_NULLFULL_A: str = "P1355_LN_NULLFULL_A"
LN_NULLFULL_B: str = "P1355_LN_NULLFULL_B"

#: (NULLPART) null umbrella limit, partially drawn subs — control.
CP_NULLPART: str = "P1355_CP_NULLPART"
FAC_NULLPART_ROOT: str = "P1355_FAC_NULLPART_ROOT"
FAC_NULLPART_SUBA: str = "P1355_FAC_NULLPART_SUBA"
FAC_NULLPART_SUBB: str = "P1355_FAC_NULLPART_SUBB"
LN_NULLPART_A: str = "P1355_LN_NULLPART_A"
LN_NULLPART_B: str = "P1355_LN_NULLPART_B"

#: (RESID) umbrella above the ceiling with a residual leg — control.
CP_RESID: str = "P1355_CP_RESID"
FAC_RESID_ROOT: str = "P1355_FAC_RESID_ROOT"
FAC_RESID_SUB: str = "P1355_FAC_RESID_SUB"
LN_RESID: str = "P1355_LN_RESID"
EXP_RESID_SUB_UNDRAWN: str = FAC_RESID_ROOT + "_UNDRAWN_" + FAC_RESID_SUB
EXP_RESID_RESIDUAL: str = FAC_RESID_ROOT + "_UNDRAWN_RESIDUAL"

#: (BULLET) the plan bullet's own example — live-cell control.
CP_BULLET: str = "P1355_CP_BULLET"
FAC_BULLET_ROOT: str = "P1355_FAC_BULLET_ROOT"
FAC_BULLET_SUBA: str = "P1355_FAC_BULLET_SUBA"
FAC_BULLET_SUBB: str = "P1355_FAC_BULLET_SUBB"
LN_BULLET: str = "P1355_LN_BULLET"
EXP_BULLET_SUBA_UNDRAWN: str = FAC_BULLET_ROOT + "_UNDRAWN_" + FAC_BULLET_SUBA
EXP_BULLET_SUBB_UNDRAWN: str = FAC_BULLET_ROOT + "_UNDRAWN_" + FAC_BULLET_SUBB

#: (NULLSUB) null sub-limit under a limited umbrella — control.
CP_NULLSUB: str = "P1355_CP_NULLSUB"
FAC_NULLSUB_ROOT: str = "P1355_FAC_NULLSUB_ROOT"
FAC_NULLSUB_SUB: str = "P1355_FAC_NULLSUB_SUB"
LN_NULLSUB: str = "P1355_LN_NULLSUB"
EXP_NULLSUB_RESIDUAL: str = FAC_NULLSUB_ROOT + "_UNDRAWN_RESIDUAL"

#: (OVER) umbrella overdrawn by the individual — control.
CP_OVER: str = "P1355_CP_OVER"
FAC_OVER_ROOT: str = "P1355_FAC_OVER_ROOT"
FAC_OVER_SUBA: str = "P1355_FAC_OVER_SUBA"
FAC_OVER_SUBB: str = "P1355_FAC_OVER_SUBB"
LN_OVER_A: str = "P1355_LN_OVER_A"
LN_OVER_B: str = "P1355_LN_OVER_B"

#: (ZERO) umbrella with a zero limit — control.
CP_ZERO: str = "P1355_CP_ZERO"
FAC_ZERO_ROOT: str = "P1355_FAC_ZERO_ROOT"
FAC_ZERO_SUBA: str = "P1355_FAC_ZERO_SUBA"
FAC_ZERO_SUBB: str = "P1355_FAC_ZERO_SUBB"
LN_ZERO_A: str = "P1355_LN_ZERO_A"
LN_ZERO_B: str = "P1355_LN_ZERO_B"

# --- Guard bundle -----------------------------------------------------------

#: (ONB) a loan plus an on-balance-sheet contingent overdraw the umbrella — control.
CP_ONB: str = "P1355_CP_ONB"
FAC_ONB_ROOT: str = "P1355_FAC_ONB_ROOT"
FAC_ONB_SUBA: str = "P1355_FAC_ONB_SUBA"
FAC_ONB_SUBB: str = "P1355_FAC_ONB_SUBB"
LN_ONB: str = "P1355_LN_ONB"
CT_ONB: str = "P1355_CT_ONB"

#: (OFB) a loan plus an off-balance-sheet contingent overdraw the umbrella — control.
CP_OFB: str = "P1355_CP_OFB"
FAC_OFB_ROOT: str = "P1355_FAC_OFB_ROOT"
FAC_OFB_SUBA: str = "P1355_FAC_OFB_SUBA"
FAC_OFB_SUBB: str = "P1355_FAC_OFB_SUBB"
LN_OFB: str = "P1355_LN_OFB"
CT_OFB: str = "P1355_CT_OFB"

#: (FXEUR) a EUR book overdrawn in EUR, within the root in GBP — control.
CP_FXEUR: str = "P1355_CP_FXEUR"
FAC_FXEUR_ROOT: str = "P1355_FAC_FXEUR_ROOT"
FAC_FXEUR_SUBA: str = "P1355_FAC_FXEUR_SUBA"
FAC_FXEUR_SUBB: str = "P1355_FAC_FXEUR_SUBB"
LN_FXEUR_A: str = "P1355_LN_FXEUR_A"
LN_FXEUR_B: str = "P1355_LN_FXEUR_B"

#: (FXOK) a EUR book drawn within its root — MOVER.
CP_FXOK: str = "P1355_CP_FXOK"
FAC_FXOK_ROOT: str = "P1355_FAC_FXOK_ROOT"
FAC_FXOK_SUBA: str = "P1355_FAC_FXOK_SUBA"
FAC_FXOK_SUBB: str = "P1355_FAC_FXOK_SUBB"
LN_FXOK_A: str = "P1355_LN_FXOK_A"
LN_FXOK_B: str = "P1355_LN_FXOK_B"

#: (FXMIX) GBP drawings under a EUR umbrella, over it in EUR — control.
CP_FXMIX: str = "P1355_CP_FXMIX"
FAC_FXMIX_ROOT: str = "P1355_FAC_FXMIX_ROOT"
FAC_FXMIX_SUBA: str = "P1355_FAC_FXMIX_SUBA"
FAC_FXMIX_SUBB: str = "P1355_FAC_FXMIX_SUBB"
LN_FXMIX_A: str = "P1355_LN_FXMIX_A"
LN_FXMIX_B: str = "P1355_LN_FXMIX_B"

#: (NORATE) drawings in a currency the run holds no rate for — control.
CP_NORATE: str = "P1355_CP_NORATE"
FAC_NORATE_ROOT: str = "P1355_FAC_NORATE_ROOT"
FAC_NORATE_SUBA: str = "P1355_FAC_NORATE_SUBA"
FAC_NORATE_SUBB: str = "P1355_FAC_NORATE_SUBB"
LN_NORATE_A: str = "P1355_LN_NORATE_A"
LN_NORATE_B: str = "P1355_LN_NORATE_B"

# --- Duplicate bundle -------------------------------------------------------

#: (DUP) the NRL shape under a root the facilities table lists twice — MOVER.
CP_DUP: str = "P1355_CP_DUP"
FAC_DUP_ROOT: str = "P1355_FAC_DUP_ROOT"
FAC_DUP_SUBA: str = "P1355_FAC_DUP_SUBA"
FAC_DUP_SUBB: str = "P1355_FAC_DUP_SUBB"
LN_DUP_A: str = "P1355_LN_DUP_A"
LN_DUP_B: str = "P1355_LN_DUP_B"

#: (DUPS) a single-level facility the facilities table lists twice.
CP_DUPS: str = "P1355_CP_DUPS"
FAC_DUPS: str = "P1355_FAC_DUPS"
LN_DUPS: str = "P1355_LN_DUPS"
EXP_DUPS_UNDRAWN: str = FAC_DUPS + "_UNDRAWN"

# --- Shared bundle ----------------------------------------------------------

#: (SHARED) two individuals under one umbrella, each with a standalone revolver.
CP_SHARED_A: str = "P1355_CP_SHARED_A"
CP_SHARED_B: str = "P1355_CP_SHARED_B"
FAC_SHARED_ROOT: str = "P1355_FAC_SHARED_ROOT"
FAC_SHARED_SUBA: str = "P1355_FAC_SHARED_SUBA"
FAC_SHARED_SUBB: str = "P1355_FAC_SHARED_SUBB"
FAC_SHARED_OWN_A: str = "P1355_FAC_SHARED_OWN_A"
FAC_SHARED_OWN_B: str = "P1355_FAC_SHARED_OWN_B"
LN_SHARED_A: str = "P1355_LN_SHARED_A"
LN_SHARED_B: str = "P1355_LN_SHARED_B"
LN_SHARED_OWN_A: str = "P1355_LN_SHARED_OWN_A"
LN_SHARED_OWN_B: str = "P1355_LN_SHARED_OWN_B"
EXP_SHARED_OWN_A_UNDRAWN: str = FAC_SHARED_OWN_A + "_UNDRAWN"
EXP_SHARED_OWN_B_UNDRAWN: str = FAC_SHARED_OWN_B + "_UNDRAWN"

# ---------------------------------------------------------------------------
# Monetary constants (GBP) — fixture INPUTS, not regulatory values. The QRRE
# ceiling is deliberately not typed here (LESSONS A4).
# ---------------------------------------------------------------------------

NRL_ROOT_LIMIT: float = 80_000.0
NRL_SUB_LIMIT: float = 60_000.0
NRL_DRAWN: float = 40_000.0  # per sub; 2 x 40,000 == the root limit -> no root leg

DEEP_ROOT_LIMIT: float = 70_000.0
DEEP_MID_LIMIT: float = 40_000.0
DEEP_LEAF_LIMIT: float = 20_000.0
DEEP_DRAWN: float = 10_000.0

XOWN_ROOT_LIMIT: float = 70_000.0
XOWN_SUB_LIMIT: float = 25_000.0
XOWN_DRAWN: float = 10_000.0

ABOVE_ROOT_LIMIT: float = 100_000.0
ABOVE_SUB_LIMIT: float = 60_000.0
ABOVE_DRAWN: float = 50_000.0  # per sub; 2 x 50,000 == the root limit -> no root leg

NULLFULL_SUB_LIMIT: float = 50_000.0  # fully drawn
NULLPART_SUB_LIMIT: float = 30_000.0
NULLPART_DRAWN: float = 10_000.0

RESID_ROOT_LIMIT: float = 100_000.0
RESID_SUB_LIMIT: float = 25_000.0
RESID_DRAWN: float = 10_000.0

BULLET_ROOT_LIMIT: float = 50_000.0
BULLET_SUB_LIMIT: float = 30_000.0
BULLET_DRAWN: float = 10_000.0

NULLSUB_ROOT_LIMIT: float = 50_000.0
NULLSUB_DRAWN: float = 10_000.0

OVER_ROOT_LIMIT: float = 50_000.0
OVER_SUB_LIMIT: float = 60_000.0
OVER_DRAWN: float = 55_000.0  # per sub; 2 x 55,000 > the root limit

ZERO_ROOT_LIMIT: float = 0.0
ZERO_SUB_LIMIT: float = 60_000.0
ZERO_DRAWN: float = 40_000.0  # per sub

#: ONB / OFB: one 30,000 loan + one 30,000 contingent = 60,000 > the 50,000 root.
CONT_ROOT_LIMIT: float = 50_000.0
CONT_SUB_LIMIT: float = 60_000.0
CONT_DRAWN: float = 30_000.0  # the loan, and the contingent's amount

#: FX legs: every facility in EUR. FXEUR draws past the root in EUR only;
#: FXOK draws exactly the root; FXMIX draws in GBP past the root in EUR.
FX_ROOT_LIMIT: float = 80_000.0  # EUR
FX_SUB_LIMIT: float = 60_000.0  # EUR
FXEUR_DRAWN: float = 42_000.0  # EUR, per sub; 84,000 > 80,000 in EUR
FXOK_DRAWN: float = 40_000.0  # EUR, per sub; 80,000 == the root
FXMIX_DRAWN: float = 36_000.0  # GBP, per sub; 72,000 GBP = EUR 82,455

#: NORATE: GBP facilities, USD drawings, no USD rate in the run.
NORATE_ROOT_LIMIT: float = 80_000.0
NORATE_SUB_LIMIT: float = 60_000.0
NORATE_DRAWN: float = 40_000.0  # USD, per sub

#: EUR -> GBP, as ``CalculationConfig.eur_gbp_rate`` defaults — a fixture input
#: for the FX table, not a regulatory value.
EUR_GBP_RATE: float = 0.8732

DUP_ROOT_LIMIT: float = 80_000.0
DUP_SUB_LIMIT: float = 60_000.0
DUP_DRAWN: float = 40_000.0  # per sub; 2 x 40,000 == the root -> no root leg
DUPS_LIMIT: float = 50_000.0
DUPS_DRAWN: float = 10_000.0

SHARED_ROOT_LIMIT: float = 80_000.0
SHARED_SUB_LIMIT: float = 60_000.0
SHARED_DRAWN: float = 40_000.0  # per sub; 2 x 40,000 == the root -> no root leg
SHARED_OWN_LIMIT: float = 50_000.0  # each individual's standalone revolver
SHARED_OWN_DRAWN: float = 10_000.0

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2030, 1, 4)

# ---------------------------------------------------------------------------
# Schemas (mirror ``tests/fixtures/p1_320``)
# ---------------------------------------------------------------------------

_CP_SCHEMA: dict[str, PolarsDataType] = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "default_status": pl.Boolean,
    "apply_fi_scalar": pl.Boolean,
    "is_managed_as_retail": pl.Boolean,
    "is_natural_person": pl.Boolean,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
}

_FAC_SCHEMA: dict[str, PolarsDataType] = {
    "facility_reference": pl.String,
    "counterparty_reference": pl.String,
    "currency": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "limit": pl.Float64,
    "committed": pl.Boolean,
    "is_revolving": pl.Boolean,
    "is_qrre_transactor": pl.Boolean,
    "is_secured": pl.Boolean,
    "seniority": pl.String,
    "risk_type": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
}

_LOAN_SCHEMA: dict[str, PolarsDataType] = {
    "loan_reference": pl.String,
    "counterparty_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "lgd": pl.Float64,
    "seniority": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "risk_type": pl.String,
}

_CONT_SCHEMA: dict[str, PolarsDataType] = {
    "contingent_reference": pl.String,
    "counterparty_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "currency": pl.String,
    "nominal_amount": pl.Float64,
    "lgd": pl.Float64,
    "seniority": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "risk_type": pl.String,
    "bs_type": pl.String,
}

_FX_SCHEMA: dict[str, PolarsDataType] = {
    "currency_from": pl.String,
    "currency_to": pl.String,
    "rate": pl.Float64,
}

_MAPPING_SCHEMA: dict[str, PolarsDataType] = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,
}

_EMPTY_LENDING_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_counterparty_reference": pl.String,
        "child_counterparty_reference": pl.String,
    }
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_p1_355_raw_bundle() -> RawDataBundle:
    """Return the P1.355 RawDataBundle carrying every umbrella-cap leg.

    See the module docstring for the leg inventory and the arithmetic each leg
    exhibits. Every leg sits on its own counterparty (XOWN on two), so the
    per-individual QRRE aggregates are isolated.
    """
    return make_raw_bundle(
        facilities=_facilities(),
        loans=_loans(),
        counterparties=_counterparties(),
        facility_mappings=_facility_mappings(),
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


def build_p1_355_guard_bundle() -> RawDataBundle:
    """Return the RawDataBundle carrying the overdrawn-umbrella guard's controls.

    ONB / OFB (contingent drawings), FXEUR / FXOK / FXMIX (drawings compared in
    the root facility's currency) and NORATE (a drawing the run cannot convert),
    each on its own counterparty; see the module docstring. The FX table holds
    EUR -> GBP only.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(_guard_facility_rows(), schema=_FAC_SCHEMA),
        loans=pl.LazyFrame(_guard_loan_rows(), schema=_LOAN_SCHEMA),
        contingents=pl.LazyFrame(_guard_contingent_rows(), schema=_CONT_SCHEMA),
        counterparties=pl.LazyFrame(
            [
                _counterparty(CP_ONB, "P1.355 Loan And On-Balance-Sheet Contingent"),
                _counterparty(CP_OFB, "P1.355 Loan And Off-Balance-Sheet Contingent"),
                _counterparty(CP_FXEUR, "P1.355 EUR Book Overdrawn In EUR"),
                _counterparty(CP_FXOK, "P1.355 EUR Book Within Its Umbrella"),
                _counterparty(CP_FXMIX, "P1.355 GBP Drawings Under A EUR Umbrella"),
                _counterparty(CP_NORATE, "P1.355 Drawings With No FX Rate"),
            ],
            schema=_CP_SCHEMA,
        ),
        facility_mappings=pl.LazyFrame(_guard_mapping_rows(), schema=_MAPPING_SCHEMA),
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
        fx_rates=pl.LazyFrame(
            [{"currency_from": "EUR", "currency_to": "GBP", "rate": EUR_GBP_RATE}],
            schema=_FX_SCHEMA,
        ),
    )


def build_p1_355_duplicate_bundle() -> RawDataBundle:
    """Return the RawDataBundle whose facilities table repeats two references.

    DUP (a duplicated MOF root over two 60,000 subs, 40,000 drawn under each)
    and DUPS (a duplicated single-level 50,000 facility, 10,000 drawn); see the
    module docstring. Each duplicate row is identical to its twin, which is the
    shape a double-loaded feed produces.
    """
    facilities = [
        _facility(FAC_DUP_ROOT, CP_DUP, limit=DUP_ROOT_LIMIT),
        _facility(FAC_DUP_ROOT, CP_DUP, limit=DUP_ROOT_LIMIT),
        _facility(FAC_DUP_SUBA, CP_DUP, limit=DUP_SUB_LIMIT),
        _facility(FAC_DUP_SUBB, CP_DUP, limit=DUP_SUB_LIMIT),
        _facility(FAC_DUPS, CP_DUPS, limit=DUPS_LIMIT),
        _facility(FAC_DUPS, CP_DUPS, limit=DUPS_LIMIT),
    ]
    return make_raw_bundle(
        facilities=pl.LazyFrame(facilities, schema=_FAC_SCHEMA),
        loans=pl.LazyFrame(
            [
                _loan(LN_DUP_A, CP_DUP, drawn_amount=DUP_DRAWN),
                _loan(LN_DUP_B, CP_DUP, drawn_amount=DUP_DRAWN),
                _loan(LN_DUPS, CP_DUPS, drawn_amount=DUPS_DRAWN),
            ],
            schema=_LOAN_SCHEMA,
        ),
        counterparties=pl.LazyFrame(
            [
                _counterparty(CP_DUP, "P1.355 Duplicated Umbrella"),
                _counterparty(CP_DUPS, "P1.355 Duplicated Single-Level Facility"),
            ],
            schema=_CP_SCHEMA,
        ),
        facility_mappings=pl.LazyFrame(
            [
                _mapping(FAC_DUP_ROOT, FAC_DUP_SUBA, "facility"),
                _mapping(FAC_DUP_ROOT, FAC_DUP_SUBB, "facility"),
                _mapping(FAC_DUP_SUBA, LN_DUP_A, "loan"),
                _mapping(FAC_DUP_SUBB, LN_DUP_B, "loan"),
                _mapping(FAC_DUPS, LN_DUPS, "loan"),
            ],
            schema=_MAPPING_SCHEMA,
        ),
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


def build_p1_355_shared_bundle() -> RawDataBundle:
    """Return the RawDataBundle with two individuals under ONE umbrella (SHARED).

    The root and sub A belong to CP_SHARED_A, sub B to CP_SHARED_B; each draws
    40,000 under their own sub and each also holds a standalone 50,000 revolver
    with 10,000 drawn. See the module docstring for the arithmetic that makes a
    cap pooled across the umbrella's owners admit one of them to QRRE.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            [
                _facility(FAC_SHARED_ROOT, CP_SHARED_A, limit=SHARED_ROOT_LIMIT),
                _facility(FAC_SHARED_SUBA, CP_SHARED_A, limit=SHARED_SUB_LIMIT),
                _facility(FAC_SHARED_SUBB, CP_SHARED_B, limit=SHARED_SUB_LIMIT),
                _facility(FAC_SHARED_OWN_A, CP_SHARED_A, limit=SHARED_OWN_LIMIT),
                _facility(FAC_SHARED_OWN_B, CP_SHARED_B, limit=SHARED_OWN_LIMIT),
            ],
            schema=_FAC_SCHEMA,
        ),
        loans=pl.LazyFrame(
            [
                _loan(LN_SHARED_A, CP_SHARED_A, drawn_amount=SHARED_DRAWN),
                _loan(LN_SHARED_B, CP_SHARED_B, drawn_amount=SHARED_DRAWN),
                _loan(LN_SHARED_OWN_A, CP_SHARED_A, drawn_amount=SHARED_OWN_DRAWN),
                _loan(LN_SHARED_OWN_B, CP_SHARED_B, drawn_amount=SHARED_OWN_DRAWN),
            ],
            schema=_LOAN_SCHEMA,
        ),
        counterparties=pl.LazyFrame(
            [
                _counterparty(CP_SHARED_A, "P1.355 Umbrella And Sub A Owner"),
                _counterparty(CP_SHARED_B, "P1.355 Sub B Owner"),
            ],
            schema=_CP_SCHEMA,
        ),
        facility_mappings=pl.LazyFrame(
            [
                _mapping(FAC_SHARED_ROOT, FAC_SHARED_SUBA, "facility"),
                _mapping(FAC_SHARED_ROOT, FAC_SHARED_SUBB, "facility"),
                _mapping(FAC_SHARED_SUBA, LN_SHARED_A, "loan"),
                _mapping(FAC_SHARED_SUBB, LN_SHARED_B, "loan"),
                _mapping(FAC_SHARED_OWN_A, LN_SHARED_OWN_A, "loan"),
                _mapping(FAC_SHARED_OWN_B, LN_SHARED_OWN_B, "loan"),
            ],
            schema=_MAPPING_SCHEMA,
        ),
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


# ---------------------------------------------------------------------------
# Frame assembly
# ---------------------------------------------------------------------------


def _counterparties() -> pl.LazyFrame:
    rows = [
        _counterparty(CP_NRL, "P1.355 No Root Leg"),
        _counterparty(CP_DEEP, "P1.355 Three Levels"),
        _counterparty(CP_XOWN_ROOT, "P1.355 Umbrella Owner"),
        _counterparty(CP_XOWN_SUB, "P1.355 Sub-Line Owner"),
        _counterparty(CP_ABOVE, "P1.355 Umbrella Above Ceiling"),
        _counterparty(CP_NULLFULL, "P1.355 Null Umbrella Fully Drawn"),
        _counterparty(CP_NULLPART, "P1.355 Null Umbrella Partially Drawn"),
        _counterparty(CP_RESID, "P1.355 Umbrella Above Ceiling With Residual"),
        _counterparty(CP_BULLET, "P1.355 Bullet Example"),
        _counterparty(CP_NULLSUB, "P1.355 Null Sub-Limit"),
        _counterparty(CP_OVER, "P1.355 Overdrawn Umbrella"),
        _counterparty(CP_ZERO, "P1.355 Zero-Limit Umbrella"),
    ]
    return pl.LazyFrame(rows, schema=_CP_SCHEMA)


def _facilities() -> pl.LazyFrame:
    rows = [
        _facility(FAC_NRL_ROOT, CP_NRL, limit=NRL_ROOT_LIMIT),
        _facility(FAC_NRL_SUBA, CP_NRL, limit=NRL_SUB_LIMIT),
        _facility(FAC_NRL_SUBB, CP_NRL, limit=NRL_SUB_LIMIT),
        _facility(FAC_DEEP_ROOT, CP_DEEP, limit=DEEP_ROOT_LIMIT),
        _facility(FAC_DEEP_MID, CP_DEEP, limit=DEEP_MID_LIMIT),
        _facility(FAC_DEEP_LEAF, CP_DEEP, limit=DEEP_LEAF_LIMIT),
        _facility(FAC_XOWN_ROOT, CP_XOWN_ROOT, limit=XOWN_ROOT_LIMIT),
        _facility(FAC_XOWN_SUB, CP_XOWN_SUB, limit=XOWN_SUB_LIMIT),
        _facility(FAC_ABOVE_ROOT, CP_ABOVE, limit=ABOVE_ROOT_LIMIT),
        _facility(FAC_ABOVE_SUBA, CP_ABOVE, limit=ABOVE_SUB_LIMIT),
        _facility(FAC_ABOVE_SUBB, CP_ABOVE, limit=ABOVE_SUB_LIMIT),
        _facility(FAC_NULLFULL_ROOT, CP_NULLFULL, limit=None),
        _facility(FAC_NULLFULL_SUBA, CP_NULLFULL, limit=NULLFULL_SUB_LIMIT),
        _facility(FAC_NULLFULL_SUBB, CP_NULLFULL, limit=NULLFULL_SUB_LIMIT),
        _facility(FAC_NULLPART_ROOT, CP_NULLPART, limit=None),
        _facility(FAC_NULLPART_SUBA, CP_NULLPART, limit=NULLPART_SUB_LIMIT),
        _facility(FAC_NULLPART_SUBB, CP_NULLPART, limit=NULLPART_SUB_LIMIT),
        _facility(FAC_RESID_ROOT, CP_RESID, limit=RESID_ROOT_LIMIT),
        _facility(FAC_RESID_SUB, CP_RESID, limit=RESID_SUB_LIMIT),
        _facility(FAC_BULLET_ROOT, CP_BULLET, limit=BULLET_ROOT_LIMIT),
        _facility(FAC_BULLET_SUBA, CP_BULLET, limit=BULLET_SUB_LIMIT),
        _facility(FAC_BULLET_SUBB, CP_BULLET, limit=BULLET_SUB_LIMIT),
        _facility(FAC_NULLSUB_ROOT, CP_NULLSUB, limit=NULLSUB_ROOT_LIMIT),
        _facility(FAC_NULLSUB_SUB, CP_NULLSUB, limit=None),
        _facility(FAC_OVER_ROOT, CP_OVER, limit=OVER_ROOT_LIMIT),
        _facility(FAC_OVER_SUBA, CP_OVER, limit=OVER_SUB_LIMIT),
        _facility(FAC_OVER_SUBB, CP_OVER, limit=OVER_SUB_LIMIT),
        _facility(FAC_ZERO_ROOT, CP_ZERO, limit=ZERO_ROOT_LIMIT),
        _facility(FAC_ZERO_SUBA, CP_ZERO, limit=ZERO_SUB_LIMIT),
        _facility(FAC_ZERO_SUBB, CP_ZERO, limit=ZERO_SUB_LIMIT),
    ]
    return pl.LazyFrame(rows, schema=_FAC_SCHEMA)


def _loans() -> pl.LazyFrame:
    rows = [
        _loan(LN_NRL_A, CP_NRL, drawn_amount=NRL_DRAWN),
        _loan(LN_NRL_B, CP_NRL, drawn_amount=NRL_DRAWN),
        _loan(LN_DEEP, CP_DEEP, drawn_amount=DEEP_DRAWN),
        _loan(LN_XOWN, CP_XOWN_SUB, drawn_amount=XOWN_DRAWN),
        _loan(LN_ABOVE_A, CP_ABOVE, drawn_amount=ABOVE_DRAWN),
        _loan(LN_ABOVE_B, CP_ABOVE, drawn_amount=ABOVE_DRAWN),
        _loan(LN_NULLFULL_A, CP_NULLFULL, drawn_amount=NULLFULL_SUB_LIMIT),
        _loan(LN_NULLFULL_B, CP_NULLFULL, drawn_amount=NULLFULL_SUB_LIMIT),
        _loan(LN_NULLPART_A, CP_NULLPART, drawn_amount=NULLPART_DRAWN),
        _loan(LN_NULLPART_B, CP_NULLPART, drawn_amount=NULLPART_DRAWN),
        _loan(LN_RESID, CP_RESID, drawn_amount=RESID_DRAWN),
        _loan(LN_BULLET, CP_BULLET, drawn_amount=BULLET_DRAWN),
        _loan(LN_NULLSUB, CP_NULLSUB, drawn_amount=NULLSUB_DRAWN),
        _loan(LN_OVER_A, CP_OVER, drawn_amount=OVER_DRAWN),
        _loan(LN_OVER_B, CP_OVER, drawn_amount=OVER_DRAWN),
        _loan(LN_ZERO_A, CP_ZERO, drawn_amount=ZERO_DRAWN),
        _loan(LN_ZERO_B, CP_ZERO, drawn_amount=ZERO_DRAWN),
    ]
    return pl.LazyFrame(rows, schema=_LOAN_SCHEMA)


def _facility_mappings() -> pl.LazyFrame:
    rows = [
        _mapping(FAC_NRL_ROOT, FAC_NRL_SUBA, "facility"),
        _mapping(FAC_NRL_ROOT, FAC_NRL_SUBB, "facility"),
        _mapping(FAC_NRL_SUBA, LN_NRL_A, "loan"),
        _mapping(FAC_NRL_SUBB, LN_NRL_B, "loan"),
        _mapping(FAC_DEEP_ROOT, FAC_DEEP_MID, "facility"),
        _mapping(FAC_DEEP_MID, FAC_DEEP_LEAF, "facility"),
        _mapping(FAC_DEEP_LEAF, LN_DEEP, "loan"),
        _mapping(FAC_XOWN_ROOT, FAC_XOWN_SUB, "facility"),
        _mapping(FAC_XOWN_SUB, LN_XOWN, "loan"),
        _mapping(FAC_ABOVE_ROOT, FAC_ABOVE_SUBA, "facility"),
        _mapping(FAC_ABOVE_ROOT, FAC_ABOVE_SUBB, "facility"),
        _mapping(FAC_ABOVE_SUBA, LN_ABOVE_A, "loan"),
        _mapping(FAC_ABOVE_SUBB, LN_ABOVE_B, "loan"),
        _mapping(FAC_NULLFULL_ROOT, FAC_NULLFULL_SUBA, "facility"),
        _mapping(FAC_NULLFULL_ROOT, FAC_NULLFULL_SUBB, "facility"),
        _mapping(FAC_NULLFULL_SUBA, LN_NULLFULL_A, "loan"),
        _mapping(FAC_NULLFULL_SUBB, LN_NULLFULL_B, "loan"),
        _mapping(FAC_NULLPART_ROOT, FAC_NULLPART_SUBA, "facility"),
        _mapping(FAC_NULLPART_ROOT, FAC_NULLPART_SUBB, "facility"),
        _mapping(FAC_NULLPART_SUBA, LN_NULLPART_A, "loan"),
        _mapping(FAC_NULLPART_SUBB, LN_NULLPART_B, "loan"),
        _mapping(FAC_RESID_ROOT, FAC_RESID_SUB, "facility"),
        _mapping(FAC_RESID_SUB, LN_RESID, "loan"),
        _mapping(FAC_BULLET_ROOT, FAC_BULLET_SUBA, "facility"),
        _mapping(FAC_BULLET_ROOT, FAC_BULLET_SUBB, "facility"),
        _mapping(FAC_BULLET_SUBA, LN_BULLET, "loan"),
        _mapping(FAC_NULLSUB_ROOT, FAC_NULLSUB_SUB, "facility"),
        _mapping(FAC_NULLSUB_SUB, LN_NULLSUB, "loan"),
        _mapping(FAC_OVER_ROOT, FAC_OVER_SUBA, "facility"),
        _mapping(FAC_OVER_ROOT, FAC_OVER_SUBB, "facility"),
        _mapping(FAC_OVER_SUBA, LN_OVER_A, "loan"),
        _mapping(FAC_OVER_SUBB, LN_OVER_B, "loan"),
        _mapping(FAC_ZERO_ROOT, FAC_ZERO_SUBA, "facility"),
        _mapping(FAC_ZERO_ROOT, FAC_ZERO_SUBB, "facility"),
        _mapping(FAC_ZERO_SUBA, LN_ZERO_A, "loan"),
        _mapping(FAC_ZERO_SUBB, LN_ZERO_B, "loan"),
    ]
    return pl.LazyFrame(rows, schema=_MAPPING_SCHEMA)


#: The guard bundle's umbrellas: (counterparty, root, sub A, sub B, root limit,
#: sub limit, facility currency). Every one is a two-sub MOF.
_GUARD_UMBRELLAS: tuple[tuple[str, str, str, str, float, float, str], ...] = (
    (CP_ONB, FAC_ONB_ROOT, FAC_ONB_SUBA, FAC_ONB_SUBB, CONT_ROOT_LIMIT, CONT_SUB_LIMIT, "GBP"),
    (CP_OFB, FAC_OFB_ROOT, FAC_OFB_SUBA, FAC_OFB_SUBB, CONT_ROOT_LIMIT, CONT_SUB_LIMIT, "GBP"),
    (CP_FXEUR, FAC_FXEUR_ROOT, FAC_FXEUR_SUBA, FAC_FXEUR_SUBB, FX_ROOT_LIMIT, FX_SUB_LIMIT, "EUR"),
    (CP_FXOK, FAC_FXOK_ROOT, FAC_FXOK_SUBA, FAC_FXOK_SUBB, FX_ROOT_LIMIT, FX_SUB_LIMIT, "EUR"),
    (CP_FXMIX, FAC_FXMIX_ROOT, FAC_FXMIX_SUBA, FAC_FXMIX_SUBB, FX_ROOT_LIMIT, FX_SUB_LIMIT, "EUR"),
    (
        CP_NORATE,
        FAC_NORATE_ROOT,
        FAC_NORATE_SUBA,
        FAC_NORATE_SUBB,
        NORATE_ROOT_LIMIT,
        NORATE_SUB_LIMIT,
        "GBP",
    ),
)


def _guard_facility_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cp, root, sub_a, sub_b, root_limit, sub_limit, currency in _GUARD_UMBRELLAS:
        rows.append(_facility(root, cp, limit=root_limit, currency=currency))
        rows.append(_facility(sub_a, cp, limit=sub_limit, currency=currency))
        rows.append(_facility(sub_b, cp, limit=sub_limit, currency=currency))
    return rows


def _guard_loan_rows() -> list[dict[str, object]]:
    return [
        _loan(LN_ONB, CP_ONB, drawn_amount=CONT_DRAWN),
        _loan(LN_OFB, CP_OFB, drawn_amount=CONT_DRAWN),
        _loan(LN_FXEUR_A, CP_FXEUR, drawn_amount=FXEUR_DRAWN, currency="EUR"),
        _loan(LN_FXEUR_B, CP_FXEUR, drawn_amount=FXEUR_DRAWN, currency="EUR"),
        _loan(LN_FXOK_A, CP_FXOK, drawn_amount=FXOK_DRAWN, currency="EUR"),
        _loan(LN_FXOK_B, CP_FXOK, drawn_amount=FXOK_DRAWN, currency="EUR"),
        _loan(LN_FXMIX_A, CP_FXMIX, drawn_amount=FXMIX_DRAWN),
        _loan(LN_FXMIX_B, CP_FXMIX, drawn_amount=FXMIX_DRAWN),
        _loan(LN_NORATE_A, CP_NORATE, drawn_amount=NORATE_DRAWN, currency="USD"),
        _loan(LN_NORATE_B, CP_NORATE, drawn_amount=NORATE_DRAWN, currency="USD"),
    ]


def _guard_contingent_rows() -> list[dict[str, object]]:
    return [
        _contingent(CT_ONB, CP_ONB, nominal_amount=CONT_DRAWN, bs_type="ONB"),
        _contingent(CT_OFB, CP_OFB, nominal_amount=CONT_DRAWN, bs_type="OFB"),
    ]


def _guard_mapping_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _cp, root, sub_a, sub_b, *_ in _GUARD_UMBRELLAS:
        rows.append(_mapping(root, sub_a, "facility"))
        rows.append(_mapping(root, sub_b, "facility"))
    rows.extend(
        [
            _mapping(FAC_ONB_SUBA, LN_ONB, "loan"),
            _mapping(FAC_ONB_SUBB, CT_ONB, "contingent"),
            _mapping(FAC_OFB_SUBA, LN_OFB, "loan"),
            _mapping(FAC_OFB_SUBB, CT_OFB, "contingent"),
            _mapping(FAC_FXEUR_SUBA, LN_FXEUR_A, "loan"),
            _mapping(FAC_FXEUR_SUBB, LN_FXEUR_B, "loan"),
            _mapping(FAC_FXOK_SUBA, LN_FXOK_A, "loan"),
            _mapping(FAC_FXOK_SUBB, LN_FXOK_B, "loan"),
            _mapping(FAC_FXMIX_SUBA, LN_FXMIX_A, "loan"),
            _mapping(FAC_FXMIX_SUBB, LN_FXMIX_B, "loan"),
            _mapping(FAC_NORATE_SUBA, LN_NORATE_A, "loan"),
            _mapping(FAC_NORATE_SUBB, LN_NORATE_B, "loan"),
        ]
    )
    return rows


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _counterparty(counterparty_reference: str, name: str) -> dict[str, object]:
    """Return one natural-person, pool-managed retail counterparty row."""
    return {
        "counterparty_reference": counterparty_reference,
        "counterparty_name": name,
        "entity_type": "individual",
        "country_code": "GB",
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": True,
        "is_natural_person": True,
        "annual_revenue": 0.0,
        "total_assets": 0.0,
    }


def _facility(
    facility_reference: str,
    counterparty_reference: str,
    *,
    limit: float | None,
    currency: str = "GBP",
) -> dict[str, object]:
    """Return one revolving, unsecured, committed, unconditionally-cancellable
    retail facility row (a QRRE candidate on every limb but (c))."""
    return {
        "facility_reference": facility_reference,
        "counterparty_reference": counterparty_reference,
        "currency": currency,
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "limit": limit,
        "committed": True,
        "is_revolving": True,
        "is_qrre_transactor": False,
        "is_secured": False,
        "seniority": "senior",
        "risk_type": "LR",
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
    }


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    *,
    drawn_amount: float,
    currency: str = "GBP",
) -> dict[str, object]:
    """Return one drawn revolving retail loan row (senior)."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
        "currency": currency,
        "drawn_amount": drawn_amount,
        "lgd": 0.5,
        "seniority": "senior",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "risk_type": "LR",
    }


def _contingent(
    contingent_reference: str,
    counterparty_reference: str,
    *,
    nominal_amount: float,
    bs_type: str,
) -> dict[str, object]:
    """Return one GBP contingent row under a revolving retail sub-line.

    ``bs_type="ONB"`` is an on-balance-sheet (drawn) contingent: the hierarchy
    moves its amount into ``drawn_amount``. ``"OFB"`` keeps it in
    ``nominal_amount``. Either way the hierarchy nets the full amount against
    the umbrella's headroom.
    """
    return {
        "contingent_reference": contingent_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
        "currency": "GBP",
        "nominal_amount": nominal_amount,
        "lgd": 0.5,
        "seniority": "senior",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "risk_type": "LR",
        "bs_type": bs_type,
    }


def _mapping(
    parent_facility_reference: str, child_reference: str, child_type: str
) -> dict[str, object]:
    return {
        "parent_facility_reference": parent_facility_reference,
        "child_reference": child_reference,
        "child_type": child_type,
    }
