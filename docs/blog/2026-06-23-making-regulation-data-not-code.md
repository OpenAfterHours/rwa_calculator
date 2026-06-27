# Making Regulation Data, Not Code: The Rulebook Migration

*Every risk weight, LGD floor, scaling factor, and supporting-factor switch in this calculator used to live in Python. Now they live in a cited, content-hashed rulebook of data that a regulator can read, diff, and replay — and the engine is no longer allowed to know which regime it is computing.*

Published 2026-06-23. Code references are pinned to commit [`7e7ed7ec`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec).

---

This post picks the series back up after the season-one finale ([What I Got Wrong, What's Next](2026-06-16-what-i-got-wrong-whats-next.md), the eighth post). That post closed a chapter; it did not close the project. The agent loop kept running through June, and the largest single piece of work it produced is the one I want to write up here, because it is the deepest architecture change since [the pipeline post](2026-05-05-the-pipeline.md) — the second post in the series and, until now, the one that explained the most about how this thing is shaped.

The change has a boring name and an unboring consequence. It is the *rulebook migration*: the work that took every regulatory value out of code and turned it into data. Not data in the loose sense of "a config file someone can edit" — data in the regulated sense: each value carries a citation to the article it comes from, the whole set is hashed so a run can prove which numbers produced it, and the engine that consumes those numbers is no longer permitted to branch on whether it is computing under the old regime or the new one. That last property is the one I care about most, and it is the one a script now enforces on every commit.

I am going to make the engineering case and the regulatory case in the same breath, because for once they are the same case.

## The thing I kept apologising for

For most of season one, the honest answer to "where does the 35% residential-mortgage risk weight live?" was: in a Python package called `src/rwa_calc/data/tables/`. The pipeline post even praised this — it argued that pulling regulatory scalars out of the engine and into a dedicated data package was what made the regulatory surface *discoverable*, so an auditor could read one file instead of grepping the engine. That was true and it was not enough.

It was not enough for two reasons. The first is that `data/tables/` was still Python. A risk weight was a module-level `dict` or a `Decimal` constant, and the only thing tying it to the regulation was a comment, if that. There was no machine-checkable link from the number to the article. The second, worse reason is that the engine still *knew the regime*. All through the calculators, behaviour forked on a pair of booleans hanging off the config object:

```python
scaling_factor = 1.06 if config.is_crr else 1.0
```

That single line appeared, in spirit, in four separate engine sites. The IRB scaling factor (CRR Art. 153(1): the 1.06 multiplier on internal-ratings RWA, which PRA PS1/26 removes) was reconstructed independently each time someone needed it. So were the supporting factors, the LGD floors, the maturity treatments — each a small `if config.is_crr` somewhere in a transform. Every one of those is a place where the CRR path and the Basel 3.1 path could silently drift apart, which is exactly the failure mode [the pipeline post opened with](2026-05-05-the-pipeline.md): a value used in two regulatory contexts that is allowed to disagree between them. I had fixed *one* instance of that (the FX rate) with a factory method. The regime booleans were the same disease, untreated, scattered across the engine.

The migration — internally "Phase 5", and the slice that finished it was tagged "S13" — did three things at once. It deleted the `data/tables/` package outright. It rehomed every value as a *cited entry* in a small set of rulebook *packs*. And it made the engine forget the regime, replacing `if config.is_crr` with a read of a cited on/off flag whose name describes the rule, not the regime. The current source tree no longer contains a `rwa_calc.data.tables` module with any regulatory content in it; the package is gone, and an architecture check refuses to let it come back.

## Regimes are data, not code

The new home is [`src/rwa_calc/rulebook/`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec/src/rwa_calc/rulebook). The guiding principle, lifted straight from the migration plan, is "regimes are data": a regulatory framework is not a code path, it is a *set of values with provenance*, and the difference between CRR and Basel 3.1 is a difference in that set, not a difference in the engine.

The package has a clean spine, one file per responsibility:

- [`model.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/model.py) — the vocabulary: the small fixed set of *rule shapes* a regulatory value can take, plus `Citation`.
- [`packs/common.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/packs/common.py), [`packs/crr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/packs/crr.py), [`packs/b31.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/packs/b31.py) — the values themselves, authored as data.
- [`registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/registry.py) — the literal map from a regime id to its ordered pack layers.
- [`resolve.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/resolve.py) — composition: merge the packs for one regime and date into a frozen, content-hashed `ResolvedRulepack`.
- [`compile.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/compile.py) — the single place a regulatory `Decimal` becomes a Polars `float`.
- [`audit.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/audit.py) — serialise the resolved pack into a run's audit manifest and diff two snapshots.

Read top to bottom, that is the whole story: *author values as cited data, layer them per regime, resolve and hash them once per run, compile them to expressions once, and record exactly which set produced the result.* The rest of this post is the detail under each of those verbs.

## A vocabulary of rule shapes

The first thing the migration had to decide was: what *kinds* of thing is a regulatory value? It is tempting to say "a number", but that is wrong in a way that matters. A risk weight is a number; a phase-in percentage is a number that depends on the date; an LGD floor by collateral type is a *table* of numbers; a haircut by CQS and residual maturity is a *multi-key* table; "do supporting factors apply under this regime" is not a number at all, it is a switch.

[`model.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/model.py) names exactly ten rule shapes and no more: `ScalarParam`, `IntParam`, `DateParam`, `LookupTable`, `CategoryMap`, `BandedTable`, `Schedule`, `DecisionTable`, `FormulaParams`, and `Feature`. Each is a frozen dataclass. Each carries a mandatory `Citation`. With three deliberate exceptions — `IntParam` (regulatory *counts*, like an MPOR business-day floor, which must stay integers), `DateParam` (calendar dates, like the Basel 3.1 commencement date), and `CategoryMap` (a classification mapping from one string label to another) — every value is a `Decimal`. Not a float. The float comes later, in exactly one place.

The shapes are a closed vocabulary on purpose. A closed vocabulary is reviewable: a reader who learns these ten shapes can read any pack entry in the codebase. It is also what lets the downstream machinery be generic — `resolve.py` can hash any shape, `audit.py` can summarise any shape, `compile.py` knows how to turn each compilable shape into an expression. A `BandedTable`, for instance, validates its own structure at construction: a `None` upper bound is the catch-all and must be last, and finite bounds must be strictly increasing, so an ill-formed threshold ladder raises a `ValueError` the moment a pack defines it, not three stages later when a row falls through a gap.

The piece that earns its keep with the regulatory audience is `Citation`. It is a three-field record — `framework`, `article`, and an optional `note` — and its string form is not free text:

```python
def __str__(self) -> str:
    if self.framework == "PS1/26":
        return f"PS1/26, paragraph {self.article}"
    return f"{self.framework} Art. {self.article}"
```

That output deliberately matches the watchfire citation grammar the project uses everywhere else (`CRR Art. 153(1)`; `PS1/26, paragraph 161`), described in [the citation-tracking doc](../development/citation-tracking.md). So the provenance carried by a *data value* in the rulebook is in the same grammar as the `@cites(...)` decorators carried by *functions* in the engine. The same article string indexes both. An auditor can ask "what cites Art. 161?" and get back both the LGD-floor data entries and the IRB code that consumes them.

## Show me one value

Abstraction is cheap; here is the real thing. Two entries from [`packs/b31.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/packs/b31.py), trimmed only of their comments:

```python
"irb_scaling_factor": ScalarParam(
    name="irb_scaling_factor",
    value=Decimal("1.0"),
    citation=Citation("PS1/26", "153", "(1)"),
),
"supporting_factors": Feature(
    name="supporting_factors",
    enabled=False,
    citation=Citation("PS1/26", "501", "SME/infrastructure supporting factors removed"),
),
"airb_lgd_floor": Feature(
    name="airb_lgd_floor",
    enabled=True,
    citation=Citation("PS1/26", "161", "(5)"),
),
```

And the matching entries from [`packs/crr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/packs/crr.py): `irb_scaling_factor` is `Decimal("1.06")` cited to `CRR Art. 153(1)`; `supporting_factors` is `enabled=True` cited to `CRR Art. 501`; `airb_lgd_floor` is `enabled=False`, cited to `CRR Art. 164` with the note "no A-IRB own-estimate LGD floor under CRR".

Stop on those three pairs, because they are the whole argument in miniature. The difference between the two regimes is not a branch anywhere in the engine. It is three data entries that differ in value, each carrying the article that says *why* it differs. Basel 3.1 removes the IRB 1.06 scaling factor (`1.06` → `1.0`). Basel 3.1 removes the SME and infrastructure supporting factors (`enabled=True` → `enabled=False`). Basel 3.1 imposes A-IRB own-estimate LGD floors that CRR did not (`enabled=False` → `enabled=True`). The engine reads `pack.scalar("irb_scaling_factor")` and `pack.feature("supporting_factors")`; it never asks which regime it is in.

## Resolution, layering, and a content hash

A regime is not one pack — it is an *ordered list* of packs. [`registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/registry.py) holds the literal map, and it is allowed no conditionals, loops, or comprehensions — just a dict and a tuple, so the composition is grep-able:

```python
REGIME_PACKS: dict[str, tuple[str, ...]] = {
    "crr": ("common", "crr"),
    "b31": ("common", "b31"),
}
```

`common` holds everything both regimes share (FX haircut, SA-CCR alpha, the FCSM RW floor, and so on); `crr` and `b31` are the amendment layers. [`resolve(regime_id, reporting_date)`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/resolve.py#L212) imports each named pack in order and does `merged.update(module.ENTRIES)`, so a later pack overrides an earlier one on a name collision. That is how `b31`'s `irb_scaling_factor = 1.0` cleanly replaces the `common`-or-`crr` `1.06`: not by a flag, by a layer.

Then it does the thing that makes this an audit artifact rather than a config loader. It computes a SHA-256 *content hash* over a canonical serialisation of every resolved entry — name, kind, citation string, and a stable value representation — and freezes the result into a `ResolvedRulepack` carrying that hash. The serialisation is deliberately built from stable string forms (`str(Decimal)`, sorted dict items, ISO dates) and never from Python's salted `hash()` or the `repr` of an unordered set, so the digest is identical across processes and across machines. Two runs that resolve the same regime at the same date get byte-identical hashes; change a single risk weight in a pack and the hash moves.

This is reproducible, and you can check it yourself. At this commit:

```text
crr@2026-12-31  content_hash 3ec7a75bc4dd538f…  187 cited entries
b31@2027-01-01  content_hash 8723f3776afc8728…  223 cited entries
```

The CRR pack resolves to 187 cited entries, the Basel 3.1 pack to 223 — Basel 3.1 carries more because it adds the revised SA risk-weight tables, the slotting revisions, the output floor schedule, and the new approach restrictions on top of the shared `common` base. (Those two figures, like every count in this post, are reproducible: [`scripts/blog_counts.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/blog_counts.py) prints the live canonical figures, and a two-line `resolve(...).content_hash` prints the digests.)

The `ResolvedRulepack` exposes *shape-checked* accessors — `scalar`, `feature`, `lookup`, `banded`, `decision`, `formula`, `schedule_value`, `int_param`, `date_param`, `category_map` — and each one is strict in two directions. Ask for a name that is not in the pack and you get a `KeyError` naming the pack id. Ask for the wrong *shape* — `feature("irb_scaling_factor")` when that entry is a `ScalarParam` — and you get a `TypeError`. A typo or a regime misread fails loudly at the accessor, not quietly three stages downstream as a wrong number. That strictness is the data-layer equivalent of the frozen-bundle discipline from the pipeline post: make the wrong thing impossible to express, rather than merely discouraged.

## The one Decimal-to-float boundary

The packs are `Decimal` at rest, because regulatory parameters are exact and float arithmetic is not. But the engine is Polars, and Polars maths over millions of rows is `Float64`. Somewhere those two facts have to meet. The migration insists they meet in exactly one file.

[`compile.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/compile.py) is the only place in the rulebook where `float(...)` is applied to a regulatory `Decimal`. It is a handful of plain typed functions: `scalar_lit` turns a `ScalarParam` into a `pl.lit(float(...))`; `lookup_expr` turns a `LookupTable` into an exact-match `when/then` chain; `banded_expr` turns a `BandedTable` into a cumulative threshold ladder; `decision_expr` turns a `DecisionTable` into a multi-key `when/then`; `formula_param_lit` pulls one named parameter out of a `FormulaParams` bundle. They are compiled once per run, not once per row. `model.py` and `resolve.py` stay pure `Decimal`; `audit.py` serialises Decimal-as-string and never floats anything. So the boundary is a single, reviewable seam — if you want to know everywhere precision is lost, you read one short module.

This is also where the no-namespace rule from the pipeline era keeps biting: the compilers are module-level functions, not a registered Polars namespace, because [`scripts/arch_check.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/arch_check.py) check 14 bans namespace registration project-wide.

## What the auditor gets

Here is where the regulatory audience should lean in. Every run of the calculator writes a `manifest.json` (when an audit cache directory is configured), and [`audit.py::serialize_pack`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/audit.py#L49) embeds the *entire resolved rulepack* into it under a `rulepack` key — the regime id, the content hash, and every cited entry with its kind, citation, and value summary. The relevant lines in [`engine/pipeline.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/pipeline.py#L543) are literally:

```python
# audit the rulepack that produced this result
"rulepack": serialize_pack(rulepack.pack),
```

So a capital number produced by this engine is no longer just a number. It travels with the run id, the per-stage timings, the accumulated data-quality errors (the pipeline-post mechanisms), *and* a complete, hashed snapshot of the regulatory parameters that produced it. "What did the calculator believe about Basel 3.1's residential RE risk weight on this run?" is answerable from the manifest alone, down to the article.

And because the snapshot is hashed and serialised, two of them can be *diffed*. `audit.py` ships a `rulepack-diff a.json b.json` CLI that buckets entry-level changes into `added` / `removed` / `changed_value` / `changed_citation` / `changed_kind` and exits non-zero on any difference, so CI — or a model-risk reviewer — can gate on unexpected regulatory-data drift. If someone changes a risk weight in a pack, the diff shows the article, the before, and the after. That is change control for the regulation itself, expressed as data. For a framework where model changes are supposed to be tracked, justified, and approved, having the *parameters* be a diffable, hashed artifact is not a nicety; it is most of what the tracking is for.

## Branching became a Feature flag

Return to the line I kept apologising for. Under the old design, the engine decided supporting factors by asking the config which regime it was. Under the new design, [`engine/supporting_factors.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/supporting_factors.py) asks the pack a question about the *rule*:

```python
if not resolved_pack.feature("supporting_factors"):
    return ...  # no factor
```

No `is_crr` anywhere. The engine does not know or care that it is Basel 3.1; it knows that *this run's rulepack says supporting factors are off*, and it knows the citation if it is asked. The regime seam has moved entirely into the rulebook, where the `Feature(enabled=False, citation=Citation("PS1/26", "501", ...))` carries the reason.

This is enforced, not merely encouraged. `arch_check.py` is the project's commit-time architecture gate — seventeen numbered checks. Six of them bear directly on this migration:

- **Checks 5 and 6** forbid any module under `engine/**` from declaring its own regulatory scalar or input-domain string-enum collection at module scope. A new risk weight in a calculator is a build failure; it has to go in a pack.
- **Check 12** is a hard ban, with no allowlist, on `engine/**` importing `rwa_calc.data.tables`. The package is gone; the check makes sure no one resurrects it instead of reading the pack.
- **Check 14** bans Polars namespace registration (the compilers stay plain functions).
- **Check 15** requires the stage registry to be a literal list.
- **Check 17** is the one that closes the loop: `engine/**` may not branch on `config.is_crr` or `config.is_basel_3_1`. Regime-specific behaviour must read a cited pack `Feature`. The check catches both the attribute read and the `getattr` form.

Worth a worked number, because the supporting-factor switch and the scaling factor are not abstractions — they move capital. Take one £10m senior corporate exposure on the foundation IRB approach whose *unscaled* risk-weighted assets, after the full Basel correlation-and-maturity machinery, come to £8.00m. Under CRR the engine multiplies by `irb_scaling_factor = 1.06` and reports **£8.48m**. Under Basel 3.1 it multiplies by `1.0` and reports **£8.00m** — a 5.66% reduction on that exposure from a single cited scalar flipping from `1.06` to `1.0`. Before the migration, that 1.06 was reconstructed as `1.06 if config.is_crr else 1.0` in four engine sites, any one of which could have been missed in a refactor. After it, the value is read in one way from one cited entry, and the only thing that decides 1.06 versus 1.0 is which pack layer won during `resolve`. The IRB output floor — [the subject of post 5](2026-05-26-the-output-floor-and-why-basel-31-bites.md) — then bites on the *floored* number, which is why getting the unfloored regime parameters into a single auditable home mattered before the floor work could be trusted.

## The honest remainder

A migration post that claimed total victory would be lying, and this series does not do that. Three honest remainders.

**The shims.** When `data/tables/` was deleted, the SA risk-weight table modules and the CRM supervisory-haircut module did not vanish — they moved into the engine and were rewritten as *thin pack-binding shims*. [`engine/sa/crr_risk_weight_tables.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/sa/crr_risk_weight_tables.py), [`engine/sa/b31_risk_weight_tables.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/sa/b31_risk_weight_tables.py), and [`engine/crm/haircut_tables.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/crm/haircut_tables.py) still exist, and consumers still import familiar names like `COLLATERAL_HAIRCUTS` from them — but those names are now *computed from the pack*. The haircut shim opens with `resolve("crr", …)` and `resolve("b31", …)` and builds its dicts from the `collateral_haircuts` `DecisionTable`. The shape of the old API survives so its callers did not all have to change at once; the source of truth underneath is the pack. That is a strangler boundary doing its job, not a finished edge.

**Two deliberate regime-boolean exceptions.** Check 17's allowlist is not empty, and it should not be. The genuine one is in [`engine/pipeline.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/pipeline.py): a CRR-only EUR→GBP threshold sync. CRR thresholds are EUR-denominated and converted at a configured rate; Basel 3.1's UK thresholds are GBP-native (PS1/26). That is a real regime *asymmetry* in the run lifecycle with no clean `Feature` analogue, so it stays in the facade and is allowlisted with that justification. The other flavour lives at the CCR boundary: the SA-CCR adapter [`engine/ccr/pipeline_adapter.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/engine/ccr/pipeline_adapter.py) still has a parameter literally named `is_basel_3_1`, gating the PRA PS1/26 Art. 274(2A) transitional alpha add-on. But even here the migration reached in: the CCR *stage* that calls the adapter no longer reads `config.is_basel_3_1` — it passes `rulepack.pack.feature("ccr_transitional_alpha_addon_applicable")`, a cited Feature. The regime-named parameter is a residual name at a function seam; the value driving it is already data. (Two further allowlist entries are not regime asymmetries at all — they are no-pack bootstrap fallbacks on test paths that production never takes, retired when the pack becomes a mandatory argument on those entry points.)

**The strangler scaffolding.** The object every stage receives is still [`RulepackV0`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/rulebook/v0.py) — a frozen facade introduced in the earlier "Phase 4" signature-freeze, which carries the full config as a passthrough *and* attaches the resolved, content-hashed pack. The `v0` in the name is honest: it still exposes `is_crr`, `is_basel_3_1`, and a `scaling_factor` property for the consumers not yet migrated onto direct pack reads. The facade let the final stage signature — `Stage(ctx, rulepack, run_config)` — land *before* the implementation underneath it was swapped, so the migration could proceed slice by slice without churning every call site. Its regime-aware surface shrinks further as the last consumers move to `pack.scalar(...)` and `pack.feature(...)`. I would rather ship a named, visible strangler than pretend the last 5% is done.

## What it bought, and what it cost

What it bought: the regulatory parameters are now a first-class, cited, hashed, diffable artifact that travels with every run, and the engine has been structurally separated from the question of which regime it computes — enforced, not aspirational, by six of the seventeen architecture checks. The CRR-versus-Basel-3.1 difference is now legible as a list of value differences, each with an article attached, instead of a forest of `if config.is_crr` branches an auditor would have to find by reading the engine. That is the property the pipeline post wanted and could only half-deliver from a Python `data/tables/` package.

What it cost: a closed vocabulary of ten rule shapes that every new value has to fit, a `Decimal`-to-float discipline that has to be respected, a layer of resolution and compilation between a value and its use, and a residue of shims, allowlisted exceptions, and a still-named `v0` facade that the migration has not yet finished swallowing. It is more machinery than a constant in a module. It is the machinery audit demands leave behind — the same argument the whole series has been making, applied this time to the regulation itself rather than to the data flowing through it.

The next post leaves the engine room for the first time in a while: it is about turning this thing from a Marimo workbench into something with a web front end, and what changes — and what must not — when a regulated calculator grows a UI.

---

**Read next:** [*From Workbench to Web App*](2026-06-25-from-workbench-to-web-app.md) — taking the calculator from an interactive notebook to a deployable app without loosening any of the audit guarantees this post is about.

**Further reading:**

- [Architecture: Pipeline](../architecture/pipeline.md) — the stage-by-stage reference; the rulepack is threaded through every stage here.
- [Development: Citation Tracking](../development/citation-tracking.md) — the watchfire grammar that `Citation.__str__` matches, and the article→function index.
- [Specifications: Audit Cache](../specifications/audit-cache.md) — the per-run `manifest.json` that now embeds the resolved rulepack snapshot.
- [The Pipeline: Why Regulation Forced an Immutable Design](2026-05-05-the-pipeline.md) — the predecessor architecture post; the data/engine split this migration completes.
- [The Output Floor and Why Basel 3.1 Bites](2026-05-26-the-output-floor-and-why-basel-31-bites.md) — what the regime parameters feed into.
- [`scripts/blog_counts.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/blog_counts.py) — the canonical-counts script behind every figure in this post.
