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
| `mutate_terms_amount_drifts_from_its_pairs` | half of `measurement`'s amount moved into `row_placement` AFTER `_terms` ran — the total, the counts and the pairs all untouched | 22 / 110 | **all six census parametrisations, on the SUM assertion itself** (`test_return_recon.py:2560`, obtained 700,000 against a claimed 1,600,000), the term filter, and 12 pre-existing term-amount tests |
| `mutate_pairs_rank_by_money` | `_rank` ordered on the side's own money, as the old leg listing was | 8 / 124 | every ordering-dependent test: the driver ranking, both cap tests, the placement test (the mover is off the page) |
| `mutate_rank_without_the_tie_break` | `_rank` ordered on `\|delta\|` alone — the `pair.key` component of the sort key deleted | 2 / 130 | the tied-slice half of the ranking test only — **and it scored 132 passed / exit 0 before that half existed** |
| `mutate_pairs_silent_cap` | `CellPairs.hidden_keys` forced to `0` | 6 / 126 | the two cap tests and the uncapped/capped comparison only |
| `mutate_cap_claims_it_showed_everything` | `CellPairs.shown_delta` forced to `total_delta`, so `hidden_delta` reads `0.00` however much money the cap left off | 2 / 130 | the tightened half of the cap test, on its ADEQUACY limb — **and it scored 132 passed / exit 0 before that half existed** |
| `mutate_terms_differing_is_population` | `CellTerm.differing_keys` restated as `keys` | 8 / 124 | the `differing_keys` test and all six census parametrisations |
| `mutate_pairs_drop_refusal` | a refused cell's table loses its `refusal` string | 13 / 119 | all five refusal tests plus the census's refusal mirror |
| `mutate_terms_skip_agreeing_keys` | `_terms` fed only the non-zero pairs, so every `keys` count collapses to the drivers | 22 / 110 | the census, the term filter, the `differing_keys` test — **and eight PRE-EXISTING split-exposure tests**, which already assert an agreeing pair is COUNTED (`keys["measurement"] == 1`) |
| `mutate_cell_reads_its_row_not_its_group` | `_predicate_key` resolved for the ROW's first column instead of the cell's | 6 / 126 | the group-scoping test **and four pre-existing `decompose_cell` tests** — `_cell_money` is shared, so the waterfall over-counts with the drill-down |
| `mutate_pairs_fill_absent_side_zero` | `_KeyPair`'s absent side filled `0.0` instead of NULL | 2 / 130 | the signed-money test only |
| `mutate_placements_rows_span_the_template` | `row_refs` not scoped to the cell's sheet | 2 / 130 | the sheet-placement test only |
| `mutate_placements_carriers_scoped_to_sheet` | the class / approach / role carriers scoped to the cell's sheet | 2 / 130 | the sheet-placement test only |
| `mutate_placements_ignore_the_base_reference` | `_placements` keyed on the leg, out of lockstep with `_key_money` | 2 / 130 | the split-exposure placement test only |
| `mutate_cell_term_stops_validating` | `CellTerm.__post_init__` replaced by a no-op, so `differing_keys > keys` constructs again | **unmeasured — red-pending** | the four incoherent-count cases, once the constructor bound lands; it FAILS CLOSED until then |

Eight of these are worth understanding, and the first one most.

- **`mutate_terms_amount_drifts_from_its_pairs` is the detector for the
  invariant the whole feature rests on**, and it also measures what the
  PRE-EXISTING gate could not have caught. It moves money between two terms and
  preserves the total, so `explained` still equals the reported delta and
  `reconciles` stays TRUE — and
  `test_four_terms_sum_to_the_cell_delta_on_every_additive_cell` **passes 6 / 6
  under it**, verified by running that test alone against the mutation. The
  four-way identity is a statement about the SUM of the terms; a term that is
  wrong by exactly what another term is wrong by leaves that sum untouched.
  Only `test_every_terms_pairs_sum_to_that_term_on_every_additive_cell` sees
  it, and it sees it in all six parametrisations.

  That was worth proving rather than asserting. The red was traced to the
  assertion line before being believed — `assert sum(pair.delta for pair in
  pairs) == pytest.approx(term.amount)`, obtained 700,000 against a claimed
  1,600,000 on `c08_03/corporate/0010/0010` — because the three assertions in
  that loop share one failure message, so "the census went red" alone would not
  have told anyone WHICH contract failed. Note also what stays green and
  should: `test_the_capped_term_filter_reports_the_keys_it_left_off` asserts
  `total_delta`, which is computed from the pairs and is therefore still right.
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
- **`mutate_rank_without_the_tie_break` is a GAP rather than a vacuity, and the
  distinction changes how you close it.** The fixture already distinguished
  right from wrong — on the probe cell only 7 of 38 keys carry a delta, so
  `|delta|` fixes 7 rows and the KEY fixes the other 18 — and nothing asserted
  on it. No new fixture was needed, only an assertion, which is the cheaper and
  higher-confidence half of these two findings.

  What makes it worth a plugin rather than a note: **the wrong answer is not
  even deterministic.** Python's sort is stable, so without the tie-break the
  residual order is `_classify`'s, which is polars `group_by` order —
  implementation-defined and thread-scheduling dependent. Two separate
  processes over the identical cell produced two different pages (one showing
  `SPLIT_FILL_A1`, which the correct ordering never renders; the other showing
  `PROBE_AGREE_28`, `_27`, `_23`, …), 17 of 25 rows moved, and 6–7 exposures
  swapped in or out each time. Meanwhile `shown_delta` stayed 63,000.00 and
  `hidden_keys` stayed 13 in **both** states: every published figure ties out,
  so nothing looks wrong. An analyst refreshing one cell sees an inventory that
  moved under them. Non-determinism that renders a plausible page is the
  hardest kind to notice and the easiest to dismiss — assert on the ORDER, not
  only on the totals.

  The closing assertion is anchored on the uncapped table's own tied keys,
  sorted independently, so it is not a restatement of `_rank`.
- **`mutate_cap_claims_it_showed_everything` is the same lesson again, and it
  found a VACUOUS test rather than an undetected one.** The code was right; the
  suite simply had no input that could distinguish `shown_delta` from
  `total_delta`. A spy over the unmutated `cell_pairs` across the whole file
  recorded **7,021 calls, `shown_delta != total_delta` on ZERO of them**, and
  all four assertion sites pinned `hidden_delta` to `0.0` — because
  `CELL_PAIRS_LIMIT = 25` on a 38-key probe puts all seven drivers on the page
  and leaves the tail empty. The mutation therefore scored 132 passed, exit 0.

  The cure is to tighten the cap until the tail carries money (`limit=3`:
  shown 35,000, hidden 28,000, measured identical under both frameworks), and
  the limb that closes it is again an **adequacy** assertion — `assert
  tight.hidden_delta != 0.0` — which is the one that goes red under the
  mutation. That is twice in one item that the anti-vacuity guard turned out to
  be the real detector, so treat "assert the fixture can distinguish the two
  states" as a first-class assertion here, not as scaffolding.

  Note what the DEFAULT cap still cannot tell you, and why both halves stay:
  the first half pins the ordinary case (every driver shown, tail genuinely
  empty), the second the case a real book always reaches, where `measurement`
  holds thousands of keys and the drivers do not all fit in the top 25.
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

## The rendered pair-table set

Written for the 2026-08-30 render half — the page that replaced two
independently-ranked per-side leg listings with one paired table, and added the
sheet-level conservation line beneath the waterfall. Baseline for
`tests/unit/ui/test_views_return_recon.py` is **88 passed**; every row was
re-measured against that baseline after the last test was added, with `-n 0`.

The defect being closed, measured on the pre-change page (`269bca8e`) with the
same probe portfolio these tests use: a cell reporting a **221,000** difference
rendered **50 rows**, of which **50 were loans that agree to the penny** and
**0 of the 7 drivers** appeared at all. The 50 rows were 25 exposures listed
twice, once per side, because each side was read and capped independently.

| plugin | what it changes | red / green | reddens |
|---|---|---|---|
| `mutate_pair_absent_side_is_a_zero` | `_pair_side` renders a NULL side as a figure — the banned Float null-fill, at the rendering boundary rather than in the model | 1 / 87 | the not-held test only (`'0' == 'not held'`) |
| `mutate_pair_note_says_nothing` | `_pair_note` returns `""` — the cap stops admitting to itself | 3 / 85 | the cap test **and both empty-table tests**, which is the point: one function carries "what the cap hid" AND "why there is no table" |
| `mutate_cause_filter_is_ignored` | `_selected_term` always resolves to every cause, so a waterfall click widens instead of narrowing | 1 / 87 | the cause-filter test only (the returned causes go from `{row placement}` to all of them) |
| `mutate_sheet_total_sums_every_row` | `_parent_flag` forced to `False`, so the sheet total includes the parent bands | 5 / 83 | both conservation parametrisations (**22,000 against 11,000 — exactly doubled**), both double-count parametrisations, and the rendered figure |
| `mutate_sheet_total_zero_fills_unmeasurable` | `_leaf_delta` counts an unmeasurable leaf as `0.0` | 1 / 87 | the undecidable test only — the column comes back `decidable`, netting to `0`, over a column their mapping cannot populate at all |
| `mutate_sheet_total_sums_an_average` | `sheet_conservation` handed a decomposition whose `metric` reads `"sum"`, so it nets a NON-ADDITIVE column | 3 / 85 | both non-additive parametrisations and the refused-cell render |
| `mutate_loan_link_drops_return_to` | the loan link loses its `return_to`, by rewriting the TEMPLATE in memory | 1 / 87 | the breadcrumb test only (`KeyError: 'return_to'`) |

Five of these are worth understanding.

- **`mutate_loan_link_drops_return_to` came back a FALSE GREEN first, by
  README mechanism 2 — the mutation never applied.** The loader wrapper
  delegated everything but `get_source` through `__getattr__`, so Jinja's
  `Environment.get_template` resolved `load` to the *inner* loader's bound
  method, which calls the inner `get_source` and never reached the rewrite. 85
  green, and it looked like evidence that nothing asserts the breadcrumb. The
  fix is structural on both sides: the wrapper subclasses `BaseLoader` so
  `load` dispatches back to the override, and the plugin **counts its own
  rewrites and fails the session at zero** — demonstrated by running it against
  `test_grid_styles.py`, which renders nothing and now exits 1 with
  `NOT APPLIED` rather than passing.
- **It is also the only template-level mutation here**, because markup has no
  module attribute to patch. It rewrites the source *in memory* through the
  loader and touches nothing on disk. That is not fastidiousness: this tree is
  shared with other agents, and a mutation left on disk is measured by all of
  them without their knowing (LESSONS G, `defect_injection.py`).
- **`mutate_sheet_total_sums_every_row` does NOT redden
  `test_the_explanation_reports_the_parent_flag_as_measured`, and that green is
  a coincidence rather than a gap.** The mutation forces every flag to `False`
  and that test asserts `row_is_parent is False` on a row which really is a
  leaf, so mutant and original agree there. Do not cite the green either way.
- **`mutate_sheet_total_sums_an_average` is the one whose defect actually
  shipped into a render.** The first version of this panel computed the sheet
  total for every column, so C 08.03 col 0050 — an exposure-weighted average PD
  — printed "the sheet total is +0.0000" and "Column 0050 NETS across this
  sheet". It was found by rendering the panel and READING it, not by a test; the
  guard, the tests and this plugin all exist because a sum down a column of
  averages has no referent and reads exactly like one that does. Note what this
  says about the gate: every assertion in the file was green while the page said
  a meaningless thing in confident language.
- **The conservation pair is asymmetric on purpose.** Under
  `mutate_sheet_total_sums_every_row` the *moved-row* half of
  `test_a_moved_row_nets_across_the_sheet_and_a_one_sided_exposure_does_not`
  stays green — a parent row's delta nets exactly as its children's do, so
  double-counting a portfolio whose only difference is a move still totals
  zero. Only the one-sided half moves. A conservation test built on the netting
  case alone would have been silent on the double-count entirely.


## The migration-matrix label + drill-down set

Written for the 2026-08-30 slice that (a) stopped the matrix calling a split
exposure's legs a scope finding and (b) made its cells clickable. Measured on
`tests/unit/analysis/test_return_recon.py` + `tests/unit/ui/test_views_return_recon.py`
together, whose baseline is **259 passed**.

Every row below was measured while that baseline still read 255 passed / 4
failed — `test_a_cell_term_refuses_a_key_count_that_describes_no_population`,
a teammate's in-flight `CellTerm` guard whose production half had not landed
yet — so the red sets are quoted NET of those four, which is what makes them
correct against the clean baseline now that the guard has landed. Confirmed at
the time: those four fail identically with no plugin loaded, and none of these
mutations touches `CellTerm`. **A red set measured against a red baseline needs
that subtraction stated, or the next reader re-measures and finds four extra
failures they cannot attribute.**

The defect being closed, measured on the split fixture before the labels
existed: 100,000 of `rwa_final` on our side and 100,000 on theirs sat under
`ours_only` / `theirs_only` — "their extract has no such exposure" — about a
loan both books hold and agree on to the penny. 1,000,000 each on `ead_final`;
210,000 / 270,000 on the three-substitution review portfolio.

| plugin | what it changes | red / green | reddens |
|---|---|---|---|
| `mutate_absent_is_always_scope` | `_absent_basis` returns `f"{side}_only"` unconditionally — the pre-change label, exactly | 12 / 247 | every label test in both files (6 parametrisations), the totals test, the movers panel's basis, the mixed-cell render, **and the analysis census's label-consistency limb** |
| `mutate_same_base_is_group_scoped` | `_side_keys` redirected to the matrix's own SHEET while `_migration_pairs` runs | 2 / 257 | `test_the_base_presence_test_spans_the_template_not_the_group` only, both frameworks |
| `mutate_a_mixed_cell_reads_as_scope` | the `any` limb deleted from `_absent_basis`, so a two-answer cell reports the scope class | 5 / 254 | both mixed-cell tests and the analysis census |
| `mutate_drill_list_drops_a_leg` | `_migration_pairs` returns a frame one row short **to `migration_legs` only**, discriminated by caller | 6 / 253 | both censuses — the analysis one and all four parametrisations of the view's `test_the_drill_down_reads_the_matrix_it_is_drawn_under` |
| `mutate_movers_note_says_nothing` | `_movers_note` returns `""` — the drill-down's cap stops admitting to itself | 2 / 257 | the cap test and the empty-pair test |
| `mutate_mover_row_hides_which_kind_it_is` | `_same_base_note` returns `""` — the per-leg verdict column goes blank | 2 / 257 | the rendered drill test and the mixed-cell test |
| `mutate_matrix_cells_are_not_clickable` | the matrix cell's `<a class="cell-link">` cut out, by rewriting the TEMPLATE in memory | 1 / 258 | the link test only (`set()` against five priced pairs) |

Six of these are worth understanding.

- **`mutate_absent_is_always_scope` leaves every conservation guard GREEN, and
  that is the evidence the fix was to the LABEL and not to the placement.**
  `test_migration_money_equals_the_groups_distinct_leg_total`,
  `test_the_migration_matrix_conserves_a_split_exposures_money` and
  `test_the_matrix_conserves_money_on_both_sides` all pass under it, because no
  money moves in either state. A mutation that had reddened them would have made
  those three the detectors and told you nothing about the label. The corollary
  matters more: a *fix* that reddened them — collapsing the matrix onto the base
  key — was measured and rejected for exactly that reason.
- **`test_migration_puts_one_sided_legs_in_the_absent_bucket` stays green under
  it too, and that is the discriminator, not a gap.** That leg's base is
  genuinely absent from their side, so `ours_only` is the correct label in BOTH
  states. It staying green is what shows the change narrowed the scope class
  rather than emptying it.
- **`mutate_same_base_is_group_scoped` reddens exactly one test, which is the
  point of writing that test at all.** Scoping the base question to the sheet
  reads perfectly plausibly — "is their leg in this part of the return?" — and
  is wrong for the canonical case: a guarantee leg is reported under the
  GUARANTOR's exposure class, so it sits on a different sheet from the loan it
  was split off. Every other label test is insensitive to the scope because
  their bases are on the same sheet, so without the cross-sheet fixture this
  mutation would have been completely silent.
- **`mutate_drill_list_drops_a_leg` discriminates by CALLER rather than patching
  `migration_legs`, and the first form of it was a false green by README
  mechanism 2.** `ui/views/return_recon` does `from ... import migration_legs`
  and so does the analysis test module, so `setattr` on the analysis module
  reaches neither of their own bindings: patching the module attribute plus the
  view's left the analysis census running the ORIGINAL function and passing.
  Moving the mutation to a module-global lookup *inside* the function body
  (`_migration_pairs`) reaches every caller, and the analysis census went red.
  Note also what it cannot show: mutate the SHARED frame and both aggregations
  move together and everything stays green — which is the structural guarantee
  working, not a gap. It proves the assertions exist, not that the sharing does.
  The view-side census is parametrised over BOTH published prices for a separate
  reason of the same shape: `migration_movers` takes the matrix rather than the
  group and the money column, and a panel that resolved its own price would
  default to `rwa_final` and pass every `rwa_final` assertion while rendering
  the wrong figures under an `ead_final` matrix.
- **`mutate_movers_note_says_nothing` is the same lesson the pair table already
  paid for.** One function carries "what the cap hid" AND "why there is no
  table", and the panel looks complete in both states. The cap test's detector
  is again an ADEQUACY assertion (`assert capped.hidden > 0`, with `limit=1` so
  the tail carries a leg) — "nothing is hidden" and "the cap lies about what it
  hid" are indistinguishable without it.
- **`mutate_mover_row_hides_which_kind_it_is` is what makes `mixed_base_*`
  honest rather than merely cautious.** A mixed cell says "both" on purpose; the
  per-leg column is the only thing that says WHICH. Under the mutation the
  label, every figure, every count and every link stay right and three
  identical-looking rows sit under a label that says they are not the same. Its
  vacuity guard counts calls where the ORIGINAL had something to say, because
  the note is blank by design on a diagonal cell — a run of diagonal cells only
  would agree on every call.
## Writing another

Five rules, all learned the expensive way in the batch that produced these:

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
3. **Make the plugin prove it applied, and fail closed when it did not.** Rule
   2 is a habit and habits are not gates: `mutate_loan_link_drops_return_to`
   went green on a mutation that never ran, and only a deliberate re-read of
   Jinja's `BaseLoader.load` found it. Where the patch is anything more indirect
   than `setattr` on a module — a loader, a wrapper, a class attribute — count
   the applications and fail the session at zero. The check is four lines and it
   turns "I checked" into something the summary line says.
4. **`@dataclass` binds `__post_init__` at DECORATION time, so you cannot add
   one to a frozen dataclass from a plugin — only remove one.** Measured while
   writing `mutate_cell_term_stops_validating`: the generated `__init__` calls
   `self.__post_init__()` only if the attribute existed when the decorator ran
   (`'__post_init__' in Cls.__init__.__code__.co_names` is `False` otherwise),
   so a plugin that ATTACHES a validator is silently inert and its run is a
   false negative about the code, not evidence about the guard. Replacing an
   existing one with a no-op does apply, which is why the mutation direction
   works and the preview direction does not. To prove a not-yet-landed
   constructor guard, use `git worktree add --detach HEAD` or an equivalent
   standalone class — never an attach-from-a-plugin probe, and do not cite one.
5. **A green suite and a red linter on the same tree is a TIMING signal, not a
   contradiction.** The fifth shape of rule 2's mechanism 3, and the first that
   presents as two gates disagreeing rather than as a false red. Measured while
   these were being written: `pytest tests/unit/analysis` returned 220 passed
   and the very next command, `ruff check src tests`, returned `F821 Undefined
   name` in the module those tests exercise — because a teammate's in-flight
   edit landed between the two, and **an undefined name at module scope does not
   break the import, only the call.** Both gates were right about the tree they
   each saw. Before concluding either is wrong, check whether the undefined
   symbol sits on a path the tests reach, and check `git status` for a file you
   do not own. Then report it rather than reverting or finishing it — never
   `git add -A`, never complete another agent's half-written file.
