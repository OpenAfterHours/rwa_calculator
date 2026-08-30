# Isolating mutation plugins

Pytest plugins that each change **exactly one thing** in production code, so a
red test is attributable to that one thing and nothing else. They exist because
*a guard nobody has seen fail is not a guard* — and because this project's
escape-log discipline closes a defect only on evidence the new gate was
**observed red before the fix**.

They are not tests and pytest does not collect them (`mutate_*.py`, not
`test_*.py`). Each patches a module attribute inside an `autouse` fixture and
restores it in a `finally`, so **nothing on disk is modified** and `git status`
stays clean while they run.

## Running one

```sh
PYTHONPATH=tests/mutations uv run pytest <test paths> -p <plugin module name>
```

For example:

```sh
PYTHONPATH=tests/mutations uv run pytest \
  tests/unit/analysis/test_return_recon.py tests/unit/ui/test_views_return_recon.py \
  -q -p mutate_collapse_group_legs
```

On Windows `PYTHONPATH` separates with `;`, not `:`.

## The `return_recon` comparison-key set

Written for the 2026-08-30 split-leg keying fix (`c898d950`). Baseline for the
two suites named above is **163 passed**; each row is the measured red set.

| plugin | what it changes | red / green | reddens |
|---|---|---|---|
| `mutate_prefix_key` | the pre-fix keying — `_comparison_key` back to `pl.col(key_column)` | 22 / 141 | every split test + both `key_column` guards |
| `mutate_drop_base_ref` | a plan frame that projects `source_exposure_reference` away | 24 / 139 | the plan-frame carriage test + every split test |
| `mutate_no_third_rung` | `_key_rungs` without `_FALLBACK_KEY_COLUMN` | 4 / 159 | the two `key_column` equivalence guards only |
| `mutate_no_presence_filter` | `_key_rungs` without its `if name in present` filter | 2 / 161 | the absent-column keying guard only |
| `mutate_collapse_group_legs` | `_group_legs` keyed on the base reference | 2 / 161 | the matrix conservation guard only |

The last two are the ones worth understanding. Each reddens **exactly the guard
written for it and nothing else** — and before those guards existed, both
mutations were completely silent:

- `mutate_no_presence_filter` — the filter is on the **hot production path**
  (the projected legacy plan frame has no `source_exposure_reference` column at
  all, so every legacy-side `_key_money` call takes that branch). Removing it
  raises `ColumnNotFoundError` on every real reconciliation, and the suite was
  blind to it because every fixture pinned the column into `schema_overrides`
  as a typed null. **Null and absent are different code paths, and both occur on
  the same side at once** — the membership legs carry the typed null, the plan
  frame carries nothing.
- `mutate_collapse_group_legs` — the "tidy up the two inconsistent key
  expressions" change the module forbids in prose. `_group_legs` prices with
  `.first()`, so collapsing distinct split legs onto one base key keeps one
  leg's money and discards the other's: measured at **40,000 (`rwa_final`) and
  400,000 (`ead_final`)** against the conservation invariant `row_migration`'s
  own docstring states. Reproduced on two different portfolios with *different
  totals but identical losses to the penny*, which is what shows the loss is one
  specific leg rather than something proportional to portfolio size. The hazard
  self-announced at runtime the whole time — `row_migration` logs *"the first is
  used and the matrix may be wrong"* — and nothing asserted on it. **A log line
  is not a gate.**

## Writing another

Two rules, both learned the expensive way in the batch that produced these:

1. **Change one thing, and do not copy the function you are mutating.**
   `mutate_collapse_group_legs` runs the *original* `_group_legs` over a side
   whose membership legs have the key rewritten — so a red is attributable to
   the key grain, not to a transcription slip in a reimplementation.
2. **Check *why* a probe comes back green, not just that it does.** Three false
   greens occurred while these were being written: one probe parsed `FAILED`
   line prefixes while pytest was emitting ANSI colour; one mutation was
   `x or None` on an object with no `__bool__`, which changes nothing; and one
   run hit a file another agent was mid-edit on. A green probe is a claim that
   needs its own evidence.
