# rwa-filer performance review: where a control run's time goes, and the plan to cut it

**Status:** Draft proposal, 2026-11-22. The review is complete; four of its ten lenses and
the proposal as a whole are still under challenge, and this page changes as those report.
The [Outcome](#outcome) section is filled in as the phase 1 work lands. Every number below
was measured on the reference dev container (4 cores, 15 GB, Python 3.13, `rwa-filer`
0.1.5) and is reproducible with the tools in the [appendix](#appendix-method).

## The finding in one sentence

A user who runs `rwa-filer validate` on a typical return waits 1.7 s, and **about 85% of
that wait has nothing to do with their return**: it is the interpreter's garbage collector
re-walking reference data, the taxonomy pack being turned into half a million Python
tuples, every rule in the book being parsed (twice for the rules that run) and the
engine's fact store being built twice. The controls themselves — structure checks, 1,441
PRA001 rules, deny list, publisher-issue labels — take about 0.25 s.

That is why the tool feels slow at every size: the fixed cost is paid by every command,
and the per-fact costs on top of it (XBRL reading, tracing, comparison) carry constants
two to four times larger than they need to be.

## How the review was run

Ten review lenses (cold start, release loading, rule engine, trace and evidence, structure
and readers, XBRL, compare and diff, dashboard, developer gates, architecture) each
measured their subsystem and prototyped their proposals in a scratch copy. Every lens was
then handed to a **second, independent agent whose brief was to refute it**: re-measure
with its own scripts, write its own prototype, and attack the equivalence argument with
mutants. 70 findings went in. At the time of writing six lenses (43 findings) have been
challenged: 26 confirmed, 13 reduced, 3 sent back for redesign and 1 marked unsafe, with
37 further items the reviewers had missed. The challenges of the XBRL, compare, developer
gates and architecture lenses are still running; their findings are marked below where a
phase 1 item rests on one.

Two rules held throughout:

- **A speed-up may not move a verdict.** A behaviour snapshot was recorded from the
  unchanged code before any prototype existed: 146 sections over 18 returns covering every
  rule result and recorded break, the full trace, CLI text and JSON output, evidence
  files, written XBRL bytes and compare/diff output. A proposal counted as verdict-neutral
  only when its prototype reproduced all 146.
- **The snapshot is not enough on its own.** The challengers showed by mutation that it,
  and the package's 1,843 tests, are blind to several of the paths the proposals rewrite
  (see [Guards](#guards-that-land-with-the-changes)). Those guards land first.

## The measured picture

Cold process, best of three, quiet box:

| Command | Return | Today |
|---|---|---|
| `validate` (fact table) | 2,227 facts | 1.70 s |
| `validate` (XBRL instance) | 2,227 facts | 2.57 s |
| `validate` (fact table) | 25,987 facts | 3.00 s |
| `validate` (XBRL instance) | 25,987 facts | 5.75 s |
| `validate --evidence` | 25,987 facts | 8.94 s |
| `build` | 25,987 facts | 4.15 s |
| `compare` (two instances) | 2,227 vs 1,821 facts | 3.68 s |
| `compare` (two instances) | 25,987 vs 7,987 facts | 12.11 s |
| `diff` (two instances) | 2,227 vs 1,821 facts | 2.55 s |
| member test suite (serial) | 1,843 tests | 216 s |

Where the 1.70 s of a small `validate` goes:

| Share | Cost | What it is |
|---|---|---|
| 0.26–0.33 s | cyclic garbage collection | 362 young, 32 middle and 2 full passes over roughly 700,000 objects that live to the end of the process; the run reclaims about 1,000 objects, all of them `argparse`'s own |
| 0.15 s | interpreter shutdown | the same heap walked once more on exit |
| 0.17 s | imports | Polars (about 0.1 s) and all 51 package modules |
| 0.45 s | taxonomy pack load | 61,428 data points turned into 518,270 Python tuples |
| 0.2–0.5 s | rule parsing | all 1,441 rules parsed before checking whether their tables are reported; the 566 that run are parsed a second time |
| 0.25 s | **the controls** | structure checks, rule evaluation, deny list, issue labels, report |

On top of the fixed cost, four per-fact constants are larger than they need to be:

- **XBRL reading** rebuilds a 110 MB index of the whole taxonomy on every file read
  (0.5–0.7 s each, twice per `compare`), and does per fact what could be done per context.
- **Rule evaluation** re-derives per-rule constants on every evaluation: on a 200-country
  return `_Selector.axis()` is called 1.4 million times and the table accessors rebuild
  their code tuples about 770,000 times.
- **Tracing** (evidence, compare) costs three times an evaluation, because a traced
  evaluation looks every cell up again after the verdict has already found it.
- **Code alignment** in the structure check walks every distinct cell in Python, three
  times per validation and five per build: 17–24% of a run on a return with tens of
  thousands of distinct cells.

Two costs grow with the **square** of an input, and no gate sees either:

- Forty facts with no member on an open axis (a few blank country cells in a CSV) turn a
  1.0 s rule run into 5.5 s at 160 countries, and a whole member-less copy into 13.7 s.
- `compare`'s explanation step tests every pair of countries: 6.7 s of a comparison at
  200 countries where 0.4 s suffices.

## Defects found along the way

These are not speed findings. Each is closed by an escape-log entry, not by its fix.

| Defect | Evidence |
|---|---|
| `rwa-filer compare` dies with a Polars `SchemaError` traceback | 36 of 240 golden pairs |
| The dashboard's evidence download can return a corrupted file with HTTP 200 when clicked twice | Two requests write the same file name at once; reproduced |
| Two threads validating at once in a cold process crash | `KeyError` in the engine in 3 of 52 trials: an unlocked cached parse replaces a rule's tree after another thread keyed its selectors by the old one. The dashboard runs each task in its own thread |
| A fact carrying many open dimensions stalls the XBRL reader | The reader tries every subset: about 1 s per fact at 18 dimensions, so a few hundred such facts stall for minutes |
| The declared Polars floor is false | `polars>=1.0.0` is declared; the shipped code calls an API that arrived later |

## The proposal

### Phase 1 — this change: every confirmed, verdict-neutral saving

Nothing in phase 1 changes a verdict, a count, a recorded break or its order, a trace, a
report, an evidence file or a written XBRL byte. The stated exceptions are the defect
fixes above, which turn a crash into an answer.

**1. Stop collecting garbage that is not garbage.** The one-shot command line gets its own
process entry that switches the cyclic collector off, and freezes the heap before exit so
shutdown does not walk it either. The dashboard, which runs until interrupted, switches it
back on before serving. Library code — pack load, rule-book load, XBRL read — pauses the
collector for the length of the bulk build and restores the state it found, so the
dashboard, `rwa-calc` and the test suite get the same saving without their collector
policy being touched. The package already does exactly this for its Arelle worker.
*Measured alone on unmodified code: `validate` 1.60 → 1.20 s, XBRL `validate` 2.36 →
1.52 s, `diff` 2.45 → 1.24 s, `compare` −33%.*

**2. Load the reference data once, and cheaply.** Build the pack's data points from
dictionary-encoded pairs (0.46 → 0.14 s). Build the XBRL fact index once per pack and
keep it with the pack (0.57 s → 0.13–0.23 s for the first read, nothing for later reads).
Cache the per-table code tuples and axis lookups that are recomputed on every access.
Values that are a pure function of an immutable pack are kept on the pack object, so they
live exactly as long as it does and a replaced pack starts empty.

**3. Parse each rule once, and faster.** Keep the trees the parse-error check already
built, and replace the parser's two character-by-character loops with compiled scans
(rule parsing 0.21 → 0.09 s). The single write also removes the two-thread crash.

**4. Build the engine's fact store once per validation**, and build it with a per-table
member dictionary instead of a scan of up to 252 members per fact (store build 2.8–7.9×;
the second pass disappears).

**5. Take the per-rule constants out of the per-evaluation loop.** Cell and place plans
worked out once per rule, an accepted-cell set per selector, one cell lookup per place
shared by the verdict and the trace, the two sides of the top comparison kept instead of
re-evaluated, one address object per reported cell. *Rule loop 1.8–2.0×; tracing a further
1.2–1.4×.* The member-less quadratic is replaced by an indexed lookup that returns the
same cells in the same order (13.7 → 0.9 s). `compare` asks for a trace without the
comparison log it never reads (a further −14%).

**6. Do the structure check per axis, not per cell.** Code alignment loops over the
distinct codes of one axis at a time, bounded by the pack (4,939 pairs) whatever the
return's size; the resolved frame is split by table once instead of filtered 208 times.
*Structure check 54 → 21 ms on a typical return and 7.2 → 1.9 s at 955,000 facts; a
firm-shaped return of 92,000 facts validates in 6.0 s instead of 8.6 s.*

**7. Read XBRL per context, not per fact**, and bound the open-dimension subsets by the
most any data point leaves open (26,000-fact instance read 2.2–2.6 → 1.1–1.4 s; the
pathological stall becomes 0.5 s).

**8. Tell the user as soon as there is something to tell.** Print the verdict before the
evidence file is written (the report arrives 24–29% sooner on `validate --evidence`).
Build the JSON record only when `--report` or `--format json` reads it (44–105 ms on
every text `validate`). Compute a run's identity block once. `build` does not check the
structure a second time. `diff` of two fact tables does not load a rule book it never
reads (0.96 → 0.29 s). `taxonomy list` does not load 14 packs to print one word per line
(1.4 → 0.15 s).

**9. Evidence writing:** one pass per side instead of two lookups per cell, block writes
on the compressed path, no per-evaluation scan of the labelled notes (−0.25 s of 2.5 s at
26,000 facts, identical bytes).

**10. Compare and dashboard.** The explanation step buckets and sorts instead of testing
every pair (6.7 → 0.4 s). The progress page answers the moment the work ends instead of
at the next one-second poll (−0.3 to −1.0 s on every action over a second). A page asked
for during a re-validation waits for that validation instead of starting a second one.
The evidence download is written once per validation and served after that. The template
grid's marks are worked out once per working return. Overrides are applied in Polars
instead of through Python dictionaries. The browser opens when the server answers, not a
fixed 0.8 s later.

**11. Developer controls.** The member suite runs under `pytest-xdist` (1.8× on a loaded
box), the reader-index change alone takes eleven test files from 72 to 33 s, and the two
slowest tests get an indexed `closing_dimensions`.

### Guards that land with the changes

The challengers proved these holes by mutation; each guard is observed red against its
mutant before the change it protects is made.

- **Code alignment has no test at all**: the function can be deleted and all 1,843 tests
  pass. Alignment tests for row, column, sheet and key-column codes land first.
- **Cell order on the member-less path is unpinned**: a mutant returning cells in reverse
  order passes 815 tests. A committed synthetic corpus, banked from the unchanged engine,
  pins results and trace digests on open rows, member-less facts and a reported cell that
  a rule turns away.
- **A reversed data-point pair and a broken parser fast path are invisible** to the tests
  and the snapshot. A per-pack equality test (every data point, same value, same hash, all
  14 packs) and a grammar differential test (old parser against new, over every packaged
  rule cell plus generated input) are blocking.
- **A memo that is never cleared lowers a call count**, so a counted gate alone is green
  on a broken memo. The memo ships with a freshness check: every memoised answer equals
  an unmemoised lookup.
- **Cost gates that do not read a clock.** Stores built per validation (1), fact
  placements per validation and per build, index builds per pack (1), code-alignment
  lookups independent of the return's size, full collections in a one-shot command (0),
  collector state restored after every pause. Scaling tests gain a deterministic
  call-count ratio (4× the input, under 4.4× the calls) beside the time ratio, and cover
  open rows, member-less facts and tracing, none of which is scaled today.

### Phase 2 — proposed, not in this change

| Item | Why it waits |
|---|---|
| Incremental re-validation in a warm process: re-run only the rules whose tables changed | Largest remaining win for the dashboard (an edit on a 26,000-fact return 2.1 → 0.8 s). The challenger could not break its premise in 540 edits, but sent the design back: reuse must be decided by comparing content inside `validate_return`, not by a caller-supplied dirty list. Needs its own design and oracle |
| A warm process for the command line (`validate --watch`, or several files per invocation) | The cold floor after phase 1 is interpreter + Polars import + pack load. Only a warm process gets below it: a repeat validation costs about 0.3 s. A new interface, so a product decision |
| `compare`: evaluate once per pair, describe on demand | A further 3–4.4× on large comparisons; a large change to the trace model |
| Skip parsing rules whose tables are not reported | About 60 ms after the faster parser. Changes which reason is reported for a rule that both fails to parse and is not reported, unless trust in the packaged books is stored somewhere; the proposed storage was rejected |
| Workbook reading through a faster engine | About 0.2 s of a 2 s cold workbook validate; a new compiled dependency whose cell typing must match the current reader's exactly |
| Lazy imports across the whole command line | 30–60 ms on a control; about forty handler-local imports in the file every other change also edits |
| Pin the Arelle environment so the referee cache holds | CI-only; saves about 12 minutes on a cache miss. Cannot be verified in this container |

### Decisions for the owner

These change an output on purpose, so they are not taken here.

- **Evidence compression level.** Level 6 instead of 9 saves 0.55–0.67 s of a 2.5 s
  evidence write at 26,000 facts; the `.gz` is 12.6% larger and its checksum (and the
  manifest's `evidence.sha256`) changes. Content digest and evidence id do not.
- **Open keys written as QNames** (`eba_GA:FR`) validate normally but compare differently
  from the local-name form. Normalise on read, or raise a structure finding.
- **Positions of facts that share coordinates** follow an unstable sort. Define the order
  (coordinates, then input position) as a stated change.
- **Memory.** Keeping the XBRL index with the pack holds 80–110 MB for the life of the
  process in exchange for 0.5 s per later read. Phase 1 takes the trade for the compact
  index only.

### Rejected

Shipping rule books pre-parsed (saves about 68 ms after the faster parser, and a stale
artefact is the one way to change a verdict silently); a per-user on-disk cache of parsed
rules; a table-to-rules dependency index (under 7 ms); compiling rules to closures;
`os._exit` at the end of the command (7 ms for giving up exit hooks and stream flushes);
reusing a dashboard validation for a build (changes a byte of a signed-off file).

## Expected result of phase 1

From the challengers' combined prototypes (CPU seconds, loaded box) — to be replaced by
measured wall-clock figures in the Outcome section:

| Command | Today | Expected |
|---|---|---|
| `validate` (fact table, 2,227 facts) | 1.70 s | 0.8–1.0 s |
| `validate` (XBRL, 2,227 facts) | 2.57 s | 1.0–1.3 s |
| `validate` (fact table, 25,987 facts) | 3.00 s | 1.6–2.0 s |
| `validate --evidence` (25,987 facts) | 8.94 s | 5–6 s |
| `compare` (25,987 vs 7,987 facts) | 12.11 s | 5–7 s |
| `diff` (two instances) | 2.55 s | 1.0–1.2 s |
| `diff` (two fact tables) | 0.98 s | 0.3–0.4 s |
| Dashboard re-validation after an edit | — | 15–25% less CPU, and 0.3–1.0 s less waiting |
| Member test suite | 216 s serial | under 120 s serial, about 60 s on four workers |

"Instant" in the sense of a keystroke is out of reach for a cold process: after phase 1
the floor is about 0.17 s of imports plus the pack load, before any work. The dashboard
is already the warm path (a repeat validation is about 0.3 s), and phase 2's first two
items are what bring the command line to the same place.

## Outcome

*To be completed when phase 1 lands: measured before/after for every row above, what was
dropped and why, and the escape-log entries for the defects.*

## Appendix: method

- **Baseline and benchmark.** Sixteen golden Basel 3.1 PRA001 returns built through
  `rwa-calc`, plus the richest one copied out to 50 and 200 countries, as fact tables and
  as written XBRL. Thirteen cold command-line cases, best of three.
- **Equivalence snapshot.** 146 sections recorded from the unchanged code; timestamps,
  paths and the one digest that covers a timestamp are scrubbed, and a re-run reproduces
  the record exactly.
- **Measuring on a shared box.** Wall-clock moved ±40% between identical runs while the
  reviews ran, so reviewers and challengers quote main-thread CPU, deterministic call
  counts and back-to-back ratios; wall-clock figures are quoted only from quiet stretches.
- **Prototypes.** Each proposal was prototyped in a scratch copy of the package and run
  with that copy first on the import path; every run prints the path of the module under
  test, so no number here was measured on code other than the code it describes.
