"""
The preparer's workflow — adjusting, recording, signing off and comparing returns.

Pipeline position:
    CanonicalReturn  ->  adjustments.apply_adjustments  ->  filing.build_filing
        ->  ledger (what was done, by whom)  ->  signoff (who approved which file)
    two returns      ->  diff.diff_returns   (what changed since the last filing)

A filing is rarely the unedited output of a system. Someone corrects a cell,
someone approves the result, and after a resubmission someone has to say what
changed. This package makes each of those a recorded act rather than an edit:

Module map:
- ``adjustments`` — cell-level overrides, each with a stated reason, applied to
  a return with the before and after kept
- ``ledger``      — an append-only, hash-chained record of adjustments, builds
  and sign-offs; any later alteration of an entry is detectable
- ``signoff``     — an approval bound to the checksum of the file approved, and
  the check that a package on disk is still the one that was signed
- ``diff``        — two versions of a return, cell by cell
- ``acts``        — a build, a sign-off and a verification as one call each:
  what the ledger records for each, shared by the command line and the dashboard

What this is not: access control or a digital signature. Nothing here stops a
person who can write the files from writing them; it ensures that what was
done is recorded, and that a file changed after sign-off no longer verifies.
"""

from __future__ import annotations
