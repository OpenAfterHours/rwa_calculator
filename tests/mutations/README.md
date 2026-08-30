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

## The per-key pair table set

Written for the 2026-08-30 `cell_pairs` slice — the drill-down that names WHICH
contracts drive a cell difference. Baseline for
`tests/unit/analysis/test_return_recon.py` is **132 passed**; every row below
was re-measured against that baseline after the last test was added, rather
than carried forward from an earlier one.

| plugin | what it changes | red / green | reddens |
|---|---|---|---|
| `mutate_pairs_rank_by_money` | `_rank` ordered on the side's own money, as the old leg listing was | 8 / 124 | every ordering-dependent test: the driver ranking, both cap tests, the placement test (the mover is off the page) |
| `mutate_pairs_silent_cap` | `CellPairs.hidden_keys` forced to `0` | 6 / 126 | the two cap tests and the uncapped/capped comparison only |
| `mutate_terms_differing_is_population` | `CellTerm.differing_keys` restated as `keys` | 8 / 124 | the `differing_keys` test and all six census parametrisations |
| `mutate_pairs_drop_refusal` | a refused cell's table loses its `refusal` string | 13 / 119 | all five refusal tests plus the census's refusal mirror |
| `mutate_terms_skip_agreeing_keys` | `_terms` fed only the non-zero pairs, so every `keys` count collapses to the drivers | 22 / 110 | the census, the term filter, the `differing_keys` test — **and eight PRE-EXISTING split-exposure tests**, which already assert an agreeing pair is COUNTED (`keys["measurement"] == 1`) |
| `mutate_cell_reads_its_row_not_its_group` | `_predicate_key` resolved for the ROW's first column instead of the cell's | 6 / 126 | the group-scoping test **and four pre-existing `decompose_cell` tests** — `_cell_money` is shared, so the waterfall over-counts with the drill-down |
| `mutate_pairs_fill_absent_side_zero` | `_KeyPair`'s absent side filled `0.0` instead of NULL | 2 / 130 | the signed-money test only |
| `mutate_placements_rows_span_the_template` | `row_refs` not scoped to the cell's sheet | 2 / 130 | the sheet-placement test only |
| `mutate_placements_carriers_scoped_to_sheet` | the class / approach / role carriers scoped to the cell's sheet | 2 / 130 | the sheet-placement test only |
| `mutate_placements_ignore_the_base_reference` | `_placements` keyed on the leg, out of lockstep with `_key_money` | 2 / 130 | the split-exposure placement test only |

Five of these are worth understanding.

- **The last four each redden exactly one test and nothing else**, which is the
  point: before those tests existed, all four mutations were completely silent.
  Three of them produce an *empty* placement or an empty row list, and an empty
  placement is ALSO the honest shape of a population term — so the wrong answer
  is indistinguishable from a right one without an assertion that says which
  cell it is looking at.
- **`mutate_placements_rows_span_the_template` and
  `mutate_placements_carriers_scoped_to_sheet` are opposites, and both are
  wrong.** The two scopes are deliberately different: `row_refs` is scoped to
  the cell's sheet (empty means "they did not put it on this sheet", which IS
  the sheet-placement finding), while the carriers are template-wide (the class
  they moved it TO lives on the sheet it moved to). Scoping both the same way —
  in either direction — reads plausibly and blanks one of the two facts.
- **`mutate_pairs_silent_cap` is caught by an ADEQUACY assertion**, not by an
  outcome one: `assert table.hidden_keys > 0, "the cap is not engaged"`. A guard
  written to stop the fixture going vacuous turns out to be the detector for
  the cap going silent, because "nothing is hidden" is exactly what both look
  like.
- **`mutate_pairs_drop_refusal` does NOT prove that a refused cell would
  otherwise be paired.** The refusal and the empty `()` come from one return in
  `_decompose`, so no mutation of `cell_pairs` alone can put pairs behind a
  refusal without reimplementing it. What it proves is narrower and still worth
  having: the empty table CARRIES its reason, so `pairs == ()` can never be read
  as "no contract drives this difference". Stated on the plugin itself too, so
  nobody cites it for more than it shows.
- **`mutate_cell_reads_its_row_not_its_group` reddens four tests it was not
  written for, and that is correct attribution rather than spill.** The pair
  table and the waterfall resolve one population through `_cell_money`, so
  "a row has one population" over-counts both at once — measured here at 13 keys
  against 2 on C 08.01 row 0010, and at 3.00x / 1.86x on the review portfolio
  that first found it. A mutation whose red set is confined to the new tests
  would have meant the two had drifted apart.

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
