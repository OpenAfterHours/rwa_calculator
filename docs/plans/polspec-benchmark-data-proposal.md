# polspec for benchmark and stress data generation

**Status:** Proposal, 2026-09-05. Evaluation of [polspec](https://github.com/MaxwellB13/polspec)
v0.1.5 against `tests/benchmarks/data_generators.py` at master `540a9b3a`. Every number
below was measured on one 16-thread Windows developer machine with the commands in the
appendix, or is quoted from a docstring and labelled as such. Nothing here is implemented.

**Revised the same day, after the first review.** Three of the statements in the first
draft were overtaken or wrong, and are corrected in place with a `Correction:` marker
rather than silently rewritten: polspec *is* on PyPI (0.1.5, uploaded 2026-09-03; the
README's "not published yet" is stale); the foreign-key reproducibility defect was fixed on
upstream `main` in `31a5c9a` (PR #17, 11:52 UTC, 29 minutes after the snapshot evaluated
here) and that fix ships in no release yet; and the polars floor is no longer a blocker
because this branch bumps rwa_calc's lock to 1.44.1. The gating list in *What would need to
change in polspec* has shrunk from three items to one.

## The answer in one paragraph

polspec is worth adopting as the **primitive layer** of the benchmark and stress data
generators — the part that turns a column declaration into a seeded, domain-respecting
column at scale — but not as a drop-in replacement for the generator, and not for any
fixture whose values are hand-derived (acceptance scenarios, oracle cases, reporting
goldens). The case rests on three things it does that our generator does not: it can be
**driven from `data/schemas.py`** so a newly declared column is exercised at scale by
default instead of by a follow-up commit; it **streams to parquet** in bounded memory, which
reopens the 10M scale we removed because generation alone ran out of memory; and it
produces the 1M-counterparty shape in **under a second** against a documented minute. It
is six days old, the same-seed reproducibility it documents was **false for any spec with a
foreign key** in the 0.1.5 release (fixed on upstream `main` the same day, unreleased as of
writing), and six of the shapes our generator needs are not expressible in it today.
Adoption is therefore gated on one thing — a tagged polspec release that contains the
reproducibility fix — and structured so that polspec sits behind one bridge module of ours.

## What polspec is

Declare a `FrameSpec` once — one `ColSpec(dtype, nullable, bounds, choices, weights,
distribution, rules=[ColRule(...)])` per column plus `__foreign_keys__`, `__checks__` and
`__unique_together__` — then `generate(n, seed, references=...)` and `validate(df)` from the
same declaration.

Generation is a Rust extension (pyo3 + rayon, xoshiro RNG) that fills every column
**independently** in 65,536-row chunks, each chunk seeded from the column position and chunk
index so the result is thread-count invariant. Two vectorised Polars passes then run over
the finished frame: `ColRule`s overwrite a column on rows matching a condition (SQL `CASE`
semantics, first match wins, choices only), and `ForeignKey`s overwrite key columns with
values sampled from a parent frame supplied via `references=`, or from the frame itself for
`references="self"`. `generate_batches` and `sink_parquet` / `sink_csv` / `sink_ipc` /
`sink_ndjson` run the same pipeline chunk by chunk. `method="cartesian"` builds the
cross-product of every finite domain so every enum combination appears at least once.

`validate()` / `inspect()` compile every declared check into one Polars aggregation and
report all breaches together. Specs round-trip through YAML and generated Python;
`from_dataframe` profiles an existing frame into a spec; a CLI does the same from files.

Maturity, stated by the project itself: repository created 2026-08-30, first tag
2026-08-31, v0.1.5 on 2026-09-03, 30 commits, one author, MIT. **Correction:** the first
draft said "not on PyPI", repeating the README; the index itself says otherwise —
`https://pypi.org/pypi/polspec/json` lists 0.1.0 to 0.1.5 with the same author and project
URLs, the 0.1.5 wheels for Linux x86_64/aarch64, macOS x86_64/arm64 and Windows x86_64
plus an sdist uploaded 2026-09-03. `uv add --dev polspec` resolves today. The README's
install section is what is stale. The README says the API, the YAML format and the values
a given seed produces are all unstable before 1.0, and `main` already carries breaking
changes over v0.1.5 (a `TableSpec` value type, a `col()` predicate language replacing the
dict form of `ColRule.when`, an exception hierarchy, and since `31a5c9a` a `Registry` that
generates a whole related set of specs in one call). Requires `polars>=1.44.1,<2` and
Python 3.12+.

## What we have today

Three hand-rolled generators, two of them the same code twice.

| Generator | Lines | Purpose | Verdict |
|---|---:|---|---|
| `tests/benchmarks/data_generators.py` | 1,506 | 8 tables, numpy, cached to parquet at 10k / 100k / 1m | Replace the primitive layer |
| `tests/acceptance/stress/conftest.py` | 681 | Same entity/product/book maps re-implemented for the 10k correctness suite | Delete; share one portfolio module |
| `tests/properties/portfolios.py` | 641 | Hypothesis-shrinkable small portfolios for the property suite | Leave alone — different job |

Measured on the benchmark generator at master:

| Scale | Rows produced | Generate + collect | Source |
|---|---:|---:|---|
| 10k counterparties | 88,500 | 0.44 s | measured |
| 100k counterparties | 885,000 | 4.29 s | measured |
| 1M counterparties | ~8.85M | "~60s+", "~1.5 GB peak" | `tests/benchmarks/conftest.py` docstring |
| 10M counterparties | — | removed: "data generation alone OOMs" | same docstring |

`cProfile` at 100k attributes about 60% of the 4.9 s to Python-side string and object
construction — `{built-in method new_str}` 1.48 s across 62 calls, the per-row
`loan_refs` loop in `generate_loans` 0.90 s of own time, `new_from_any_values` 0.34 s —
and not to random sampling. The `[f"CP_{i:08d}" for i in range(n)]` list comprehensions
and `[base_date + timedelta(days=int(d)) for d in ...]` lists are the cost, and they scale
linearly into the 1M and 10M figures above.

The maintenance pattern matters more than the speed. `git log --since=2026-03-01` shows 36
commits to `data_generators.py`; by subject line roughly half of them exist to add or
re-home a newly declared schema column (`is_qccp`, `counterparty_type`, `is_sft`,
`rental_to_interest_ratio`, the due-diligence fields, `model_id` three times, the netting
reference twice, "emit branch-added schema columns"). The mechanism: `ensure_columns` fills
any column the generator forgot with its declared default, so a new column is never
*missing* from the benchmark — it is silently constant, usually null or `False`, and the
benchmark stops measuring the code that reads it until someone notices. That is the
`.claude/LESSONS.md` B1 shape (a guard that never fires) applied to performance coverage.

Two fidelity gaps in the current data are worth recording because a rewrite is the moment to
close them. The dataset contains no `specialised_lending` table, and the classifier sources
`sl_type` / `slotting_category` from that table (`engine/classify/attributes.py`), so the
`SL_<CATEGORY>_...` loan references the generator constructs to "embed the slotting category"
route nothing to slotting despite the module docstring's claim of slotting coverage. And
because no `model_permissions` table is produced, the whole benchmark portfolio is
standardised-approach only (recorded in project memory as "benchmark harness is all-SA").

## What the proof of concept showed

A two-table spec shaped like `COUNTERPARTY_SCHEMA` (17 columns: weighted entity mix,
weighted country, lognormal revenue, two `ColRule`s, a nullable self-referencing parent key,
seven all-null optional columns) and `LOAN_SCHEMA` (30 columns: weighted product mix, six
`ColRule`s deriving `book_code`, constant `value_date` via `choices`, bounded `maturity_date`,
lognormal `drawn_amount` floored at 10,000, `lgd` rules, 17 all-null optional columns, a
foreign key to counterparties). Installed from the v0.1.5 Windows wheel into a scratch
virtualenv; the spec and commands are in the appendix.

| Check | Result |
|---|---|
| Runs on our locked polars 1.42.1 (`--no-deps` install) | Yes — byte-identical output to 1.44.1, its declared floor |
| 100k counterparties + 300k loans × 30 cols | 0.07 s + 0.08 s |
| 1M counterparties + 3M loans × 30 cols | 0.19 s + 0.75 s |
| 10M loans × 30 cols streamed with `sink_parquet`, `batch_size=500_000`, zstd | 16–18 s, peak working set 1.07 GB, 250–320 MB file, 10,000,000 rows read back |
| Foreign key integrity (anti-join of loans to counterparties) | 0 orphans |
| `ColRule` conditional overwrite | 0 violations across 300k rows |
| `ColRule(choices=[None])` to null a column under a condition | Works (undocumented) |
| Weighted choices | Entity mix within 0.1 pp of declared at 100k |
| 12-character random string primary keys | 0 duplicates at 100k |
| Same seed twice, spec **without** a foreign key | Identical frames |
| Same seed twice, spec **with** a foreign key | **Differs** — only the FK-sampled column(s) |
| `validate()` on a column whose rules assign values outside its `choices` | Fails: `book_code` 33,171 "invalid" values, `lgd` 12,121 |
| Self-reference shape at 100k | No self-loops or 2-cycles, but no control over depth or acyclicity |
| Foreign-key fan-out at 3 loans per counterparty | 5.0% of counterparties receive no loan; one receives 12 |

The reproducibility failure is isolated and explained. `_apply_foreign_keys` builds the
parent key pool with `parent_df.select(ref_cols).drop_nulls().unique()` and then
`.sample(n, seed=...)`. Polars `unique()` does not guarantee row order, so the same seed
samples different rows on each call. polspec already handles the identical hazard in
`_resolve_bounded_categorical` with `unique(maintain_order=True)` and a comment saying why;
the FK path just lacked the flag. For us this would have meant a cached benchmark parquet
could not be regenerated byte-identically, and the "same seed on the same version always
produces the same frame" contract the roadmap calls load-bearing did not hold for any spec
that has a foreign key — which every table of ours except counterparties does.

**Correction:** the first draft said the defective line was also present on `main`. It was
at the snapshot evaluated (`7a25f2b`, 11:23 UTC); upstream fixed it 29 minutes later in
`31a5c9a` (PR #17), which changes the call to `unique(maintain_order=True)` and adds
`test_generate_foreign_key_is_reproducible_for_a_seed` on a 50-row parent. That test is
adequate: measured here on polars 1.44.1, `unique()` on a 50-row frame returned a different
row order on every one of 40 calls, and `maintain_order=True` returned one, so the test
fails on the pre-fix code rather than passing vacuously. The fix is in no tagged release —
the 0.1.5 wheel on PyPI still has the defect — so adoption pins whichever tag first
contains `31a5c9a`.

The `validate()` failure is a sharp edge rather than a defect: polspec checks a column's
values against its own `choices`, not against the union of its rules' choices, and its
declaration-time consistency check covers `Enum` categories and `bounds` but not `choices`.
The fix on our side is to list every rule value in the column's `choices`; the fix on theirs
is a declaration-time check.

## Proposal: how we would use it

### Shape

```
data/schemas.py  (ColumnSpec: dtype, default, required, NumericDomain | EnumDomain,
                  TABLE_FOREIGN_KEYS, TABLE_UNIQUE_KEYS)
        │  read by
        ▼
tests/fixtures/polspec_bridge.py      base FrameSpec per table, derived, ~150 lines
        │  overridden by
        ▼
tests/benchmarks/portfolio.py         the 8-table benchmark portfolio: mixes, amounts,
                                      hierarchies, generation order — replaces
                                      data_generators.py and the stress duplicate
        │  materialised by
        ▼
polspec  generate() / sink_parquet()  → tests/benchmarks/data/<scale>/*.parquet (cached, as now)
```

**The bridge** turns `TABLE_SCHEMAS[name]` into a `FrameSpec`: dtype maps one-to-one;
`NumericDomain` becomes `bounds` (polspec bounds are inclusive, so an open end such as
`effective_maturity > 0` is nudged by one ULP until polspec grows exclusive bounds);
`EnumDomain` becomes `choices`; `TABLE_FOREIGN_KEYS` becomes `__foreign_keys__`;
`TABLE_UNIQUE_KEYS` becomes `unique=True`. An optional column with a declared default
generates as that constant unless the portfolio overrides it. The bridge is the only module
that imports polspec, so its API churn touches one file.

**The portfolio** is ours and stays ours — it is regulatory judgment, not plumbing: the
entity, product and book mixes, revenue-by-entity-type, amounts as a fraction of revenue,
the 60/50/35/15 hierarchy depth mix, collateral coverage, rating mix by entity type. It
overrides the roughly 40 columns that carry the story and inherits the rest from the bridge.
Every other column is then generated inside its declared domain instead of being pinned to
its default, which is the coverage gain.

**Generation order** follows the foreign keys: counterparties → ratings, facilities, loans,
contingents (`references={Counterparties: cps}`) → collateral (`references={Loans: ...}`) →
mappings. Hierarchies are generated **level-wise** — roots, then depth-2 rows with
`references` restricted to the roots frame, then depth-3 against depth-2 — which gives the
acyclic, depth-controlled trees `HierarchyResolver` benchmarks need without waiting for
polspec to grow tree generation. Reference identifiers stay readable (`CP_00000001`) via a
post-pass `pl.int_range(...).cast(pl.String).str.zfill(8)` rather than random strings.

**Materialisation** uses `sink_parquet` into the existing `tests/benchmarks/data/<scale>/`
cache, so `conftest.py` and `get_or_create_dataset` keep their interface, and a `10m` scale
becomes possible behind the same opt-in marker pattern as `scale_1m`.

**A new gate** that today does not exist: after generating, run the pipeline's own
`validate_bundle_values` over the benchmark bundle and assert zero data-quality errors, and
run `FrameSpec.validate` over each table. The benchmark data would then be proven to respect
the input contract it benchmarks; nothing asserts that now.

### Out of scope, deliberately

- `tests/fixtures/p1_*`, `tests/oracle/`, `tests/expected_outputs/` and the reporting
  goldens: hand-derived rows whose values are the point. Seed values are unstable across
  polspec versions by its own statement.
- `tests/properties/` and `tests/robustness/`: Hypothesis strategies that already read
  `ColumnSpec.domain`, and that deliberately generate *invalid* data. polspec generating from
  the declaration would be the `.claude/LESSONS.md` B3 trap there; it is fine for
  benchmarks, whose job is valid data at volume.
- Using polspec's `validate()` in `src/`: `contracts/validation.py` already reads the same
  declarations and emits `CalculationError`s. Two validators over one declaration is drift
  waiting to happen.

A follow-on worth a separate look: `method="cartesian"` over a chosen subset of columns
(entity type × product × risk type × seniority × collateral type) would build a coverage
portfolio for the `RUNS` register in `tests/acceptance/reporting/` — the dead-cell problem
`.claude/LESSONS.md` B5 records is exactly "no golden portfolio has this combination".

## What would need to change in polspec

Ranked. As first drafted, three items gated adoption; after the same-day review only one
does. The rest we can work around in the portfolio module and would retire the workaround
as each lands.

**Blocking**

1. ~~**Publish to PyPI.**~~ **Correction: already done.** 0.1.5 has been on PyPI since
   2026-09-03 (see *What polspec is*). What remains is a documentation fix upstream: the
   README's install section still says "not published to PyPI yet" and tells readers to
   build from a checkout with maturin, which is what sent the first draft of this page
   wrong.
2. **A tagged release containing the foreign-key reproducibility fix.** The code change
   (`unique(maintain_order=True)` in `_apply_foreign_keys`) and its regression test landed
   upstream in `31a5c9a`, so nothing remains to write; the 0.1.5 wheel on PyPI predates it.
   This is now the single item that gates adoption: we pin the first tag that includes
   `31a5c9a`, and until it exists a git source at that commit compiles with maturin, which
   puts a Rust toolchain into CI for a test dependency.
3. ~~**Relax the `polars>=1.44.1` floor.**~~ **Correction: resolved on our side.** This
   branch bumps rwa_calc's lock from polars 1.42.1 to 1.44.1 (`uv lock --upgrade-package
   polars`; only `polars` and `polars-runtime-32` moved), so the floor is met without
   asking polspec to change it. The gate results for the bump are recorded in *Sequencing*
   below.

**Fidelity — expressiveness our generator has and polspec lacks**

4. **Derived columns.** `limit = revenue × U(0.01, 0.10)`, `market_value = drawn × U(0.5, 1.5)`,
   `maturity_date = value_date + days`. The `col()` predicate language on `main` already has
   arithmetic; what is missing is a sampling node (`uniform(lo, hi)`, `normal(...)`) and a
   post-generation evaluation pass, `ColSpec(..., derive=...)`.
5. **`ColRule` that sets `bounds` / `distribution`, not only `choices`.** Revenue by entity
   type is five different uniform ranges keyed on one column.
6. **Parent attributes through a foreign key.** A loan's product mix depends on its obligor's
   `entity_type`. Either `ForeignKey(..., carry=["entity_type"])` or a documented pattern
   (generate the key, join the parent, then apply rules).
7. **Acyclic self-reference with depth control**, e.g.
   `ForeignKey(..., references="self", acyclic=True, depth=(2, 4))`. Level-wise generation
   is the workaround.
8. **Fan-out control on foreign keys** — a fixed or distributed children-per-parent count,
   and "every parent referenced at least once". With-replacement sampling leaves 5% of
   parents childless at 3:1.
9. **Sequence and template string columns** — `format="CP_{:08d}"` / `sequence=True` — for
   readable, unique-by-construction keys. Random 12-character strings had no collisions at
   100k but are opaque in a profile.
10. **Exclusive bounds** (`Bound(0, 1, lower_closed=False)`) to mirror `NumericDomain`'s
    open ends without the ULP nudge.
11. **Declaration-time check that a rule's `choices` are within the column's `choices`**,
    matching the checks it already runs against `Enum` categories and `bounds`.
12. ~~**Generate a related set from the foreign-key graph** in one call.~~ **Correction:
    landed upstream in `31a5c9a`** as `Registry(Customers, Orders, ...)` with `order()`,
    `generate_all` (a per-spec seed, so adding a table changes no other) and
    `generate_related`. Unreleased at the time of writing. Our portfolio module still does
    the level-wise hierarchy generation by hand, because `Registry` walks the foreign-key
    graph between specs and does not address item 7 within one.

## Risks and how the shape above contains them

- **Alpha churn.** v0.1.5 → `main` already breaks `ColRule.when`, adds `Spec.spec`, and
  renames exceptions. Pin an exact version, and keep every polspec import in the bridge.
- **Seed values change across versions.** Regenerate the cached parquets on every upgrade
  and never compare benchmark numbers across a regeneration without saying so. Never use it
  for goldens.
- **Compiled extension.** Windows development and Linux CI are both covered by the release
  wheels; a contributor on an unlisted platform needs Rust.
- **Single author, six days old, two stars.** The fallback if the project stalls is either
  the current numpy generator, kept until Step 2 below is merged, or a pure-Polars rewrite of
  the primitive layer behind the same bridge interface.
- **Generating from the declaration cannot disagree with the declaration.** Correct and
  intended for benchmarks; the robustness suite keeps owning the invalid-input axis.

## Alternative considered

Rewrite `data_generators.py` in pure Polars expressions, no new dependency. It would remove
the Python list building that dominates the profile and allow `sink_parquet` streaming, so
it solves the speed and the 10M memory problem. It does not solve the churn: every new
schema column still needs a hand-written expression, or we write our own
`ColumnSpec`-to-generator layer — which is polspec's core. The recommendation is polspec for
the primitive layer, with the pure-Polars rewrite as the fallback if the blocking items are
not taken up.

## Sequencing

| Step | Owner | Content | Done when |
|---|---|---|---|
| 0 | us → polspec | Ask upstream for a tagged release containing `31a5c9a`, and for the README install section to say the package is on PyPI. Items 1 and 3 need no upstream action any more. | A tag newer than `31a5c9a` exists |
| 1 | us | `tests/fixtures/polspec_bridge.py` + counterparties/loans in a new `tests/benchmarks/portfolio.py`, side by side with the old generator; equality of row counts, entity mix and `get_dataset_statistics` hierarchy stats | Both generators produce statistically equivalent 100k sets |
| 2 | us | All eight tables incl. level-wise hierarchies; `specialised_lending` and `model_permissions` tables so slotting and IRB are actually exercised; switch `conftest.py`; delete the stress duplicate; regenerate caches; CI Benchmarks job green | `data_generators.py` deleted |
| 3 | us | `scale_10m` via `sink_parquet` behind an opt-in marker; the zero-DQ-error gate on benchmark bundles | 10M runs on a developer laptop |

### The polars bump, executed on this branch

Item 3 was done rather than deferred, and it was not a lock-only change. Moving the lock
from 1.42.1 to 1.44.1 turned 68 tests red on a suite that is green at 1.42.1, all through
two engine sites and one pre-existing polars regression: on 1.44.1 `pl.max_horizontal` and
`pl.min_horizontal` return a length-1 column without the broadcast flag when every input is
scalar-backed (pola-rs/polars#29082, fixed by #29083 on 2026-09-02, in no release as of
1.44.1). `ensure_columns` fills every absent optional column with a scalar literal, so any
reducer whose operands all derive from such columns hits it; the two the fixtures drove were
the Art. 147(4C)(b)(ii) group-revenue max in `classify/attributes.py` and the Art. 279c(1)
business-day clamp in `ccr/maturity_factor.py`. Both are rewritten as value-identical
element-wise expressions with the revert condition in a comment; a standalone repro is clean
on 1.43.2, and 1.43.0, 1.43.1 and 1.44.0 are yanked on PyPI, so 1.44.1 was the only
non-yanked candidate meeting polspec's floor.

| Gate on 1.44.1 with both workarounds | Result |
|---|---|
| `uv run pytest tests/` (dev-loop default) | 12,868 passed, 59 skipped, 23 xfailed, 0 failed |
| `ty`, `ruff check`, `ruff format --check`, `arch_check` | clean (watchfire soft findings pre-existing) |
| `scripts/coverage_report.py --check` | no ratcheted metric moved |
| `tests/contracts/test_arch_migration_gates.py` | passes — the first CCR rewrite used `fill_null` and moved the `engine_fill_null_sites` ratchet 468 → 469; the shipped form uses a `when` branch instead |
| `tests/integration/test_stage_edges.py` | plan-node ceilings re-measured on 1.44.1 and re-pinned; version pin moved to 1.44 |

The residual risk is stated in the changelog: roughly 90 other horizontal-reducer call sites
were not driven with all-scalar inputs by any fixture, so a customer file omitting an optional
column that feeds one of them would fail its stage loudly — a `PIPELINE_*` error, never a
wrong number — until a polars release containing #29083 is locked and the two workarounds are
reverted.

Candidate plan bullets for `plan-curator`: a Tier-4/P8 item for Steps 1–2 (test
infrastructure; touches `tests/benchmarks/` and `tests/acceptance/stress/` only, no shared
engine files), and a follow-on for Step 3. The specialised-lending and IRB fidelity gaps are
worth their own bullets whether or not polspec is adopted.

## Appendix: reproducing the measurements

Scratch environment (the wheel installs with `--no-deps` so its polars floor is not enforced):

```bash
uv venv psvenv --python 3.13
uv pip install --python psvenv/Scripts/python.exe "polars==1.42.1" pyyaml pyarrow psutil
uv pip install --python psvenv/Scripts/python.exe --no-deps \
  https://github.com/MaxwellB13/polspec/releases/download/v0.1.5/polspec-0.1.5-cp312-abi3-win_amd64.whl
```

Current generator timing and profile:

```bash
uv run python -c "
import time; from tests.benchmarks.data_generators import generate_benchmark_dataset
for n in (10_000, 100_000):
    t = time.perf_counter(); ds = generate_benchmark_dataset(n_counterparties=n, seed=42)
    rows = sum(v.collect().height for v in ds.values()); print(n, f'{time.perf_counter()-t:.2f}s', rows)"
uv run python -m cProfile -s tottime -c "from tests.benchmarks.data_generators import generate_benchmark_dataset as g; [v.collect() for v in g(100_000).values()]" | head -30
```

The v0.1.5 spec used for the proof of concept, abridged to the constructs that matter
(`ColRule.when` takes the dict form in v0.1.5; `main` has moved to `col()` predicates):

```python
import datetime as dt
import polars as pl
from polspec import ColRule, ColSpec, ForeignKey, FrameSpec

class Counterparties(FrameSpec):
    counterparty_reference = ColSpec(pl.String, string_length=(12, 12), unique=True)
    entity_type = ColSpec(pl.String, choices={"corporate": .35, "individual": .30,
                                               "institution": .15, "sovereign": .10,
                                               "specialised_lending": .10})
    annual_revenue = ColSpec(pl.Float64, bounds=(0.0, 1e12), distribution="lognormal",
                             distribution_params={"mean": 16.0, "std": 2.5})
    default_status = ColSpec(pl.Boolean, weights=[0.98, 0.02])
    is_natural_person = ColSpec(pl.Boolean, rules=[
        ColRule(when={"column": "entity_type", "equals": "individual"}, choices=[True]),
        ColRule(when={"column": "entity_type", "not_equals": "individual"}, choices=[False]),
    ])
    borrower_income_currency = ColSpec(pl.String, nullable=True, null_probability=0.0,
        choices=["GBP", "USD", "EUR", "JPY"],
        rules=[ColRule(when={"column": "entity_type", "not_equals": "individual"}, choices=[None])])
    parent_counterparty_reference = ColSpec(pl.String, string_length=(12, 12),
                                            nullable=True, null_probability=0.40)
    sovereign_cqs = ColSpec(pl.Int32, nullable=True, null_probability=1.0)  # ×7 such columns
    __foreign_keys__ = [ForeignKey("parent_counterparty_reference", references="self",
                                   ref_columns="counterparty_reference")]

class Loans(FrameSpec):
    loan_reference = ColSpec(pl.String, string_length=(14, 14), unique=True)
    counterparty_reference = ColSpec(pl.String, string_length=(12, 12))
    product_type = ColSpec(pl.String, choices={"TERM_LOAN": .3, "RCF_DRAWING": .15, "TRADE_LOAN": .05,
                                               "PERSONAL_LOAN": .1, "RESIDENTIAL_MORTGAGE": .15,
                                               "CREDIT_CARD": .05, "INTERBANK_LOAN": .1, "SOVEREIGN_LOAN": .1})
    book_code = ColSpec(pl.String, choices=["CORP_LENDING"], rules=[
        ColRule(when={"column": "product_type", "equals": "CREDIT_CARD"}, choices=["RETAIL_CARDS"]),
        # ... five more product -> book rules
    ])
    value_date = ColSpec(pl.Date, choices=[dt.date(2026, 1, 1)])
    maturity_date = ColSpec(pl.Date, bounds=(dt.date(2027, 1, 1), dt.date(2033, 1, 1)))
    drawn_amount = ColSpec(pl.Float64, bounds=(10_000.0, 5e7), distribution="lognormal",
                           distribution_params={"mean": 12.5, "std": 1.2})
    lgd = ColSpec(pl.Float64, choices=[0.45], rules=[
        ColRule(when={"column": "product_type", "equals": "RESIDENTIAL_MORTGAGE"}, choices=[0.10]),
        ColRule(when={"column": "product_type", "equals": "CREDIT_CARD"}, choices=[0.85]),
    ])
    # ... 17 all-null optional columns as above
    __foreign_keys__ = [ForeignKey("counterparty_reference", references=Counterparties)]

cps = Counterparties.generate(1_000_000, seed=42)
loans = Loans.generate(3_000_000, seed=43, references={Counterparties: cps})
Loans.sink_parquet("loans_10m.parquet", 10_000_000, batch_size=500_000, seed=44,
                   references={Counterparties: cps}, compression="zstd")
```

The reproducibility defect, minimal:

```python
a = Counterparties.generate(1000, seed=7)
b = Counterparties.generate(1000, seed=7)
[c for c in a.columns if not a[c].equals(b[c])]   # ['parent_counterparty_reference']
la = Loans.generate(1000, seed=7, references={Counterparties: a})
lb = Loans.generate(1000, seed=7, references={Counterparties: a})
[c for c in la.columns if not la[c].equals(lb[c])]  # ['counterparty_reference']
Loans.generate(1000, seed=7).equals(Loans.generate(1000, seed=7))  # True — no references, no FK pass
```
