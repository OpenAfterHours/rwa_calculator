# rwa-filer performance review: where a control run's time goes, and the plan to cut it

**Status:** Phase 1 implemented 2026-11-22 — see [Outcome](#outcome) for what each
change bought, measured against the code before it. Phase 2 and the owner's decisions
are plan item P6.61. Every number below
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
mutants. 70 findings went in, and all ten lenses were challenged: 39 confirmed, 23
reduced, 7 sent back for redesign and 1 marked unsafe, with 54 further items the reviewers
had missed.

The consolidated proposal was then **red-teamed as a whole** by three more teammates —
correctness and regulatory risk, delivery and sequencing, and the user's outcome. All
three returned "proceed, with changes", with two blockers: the acceptance standard named
only our own snapshot and not the external referee, and the guards were planned to arrive
with the changes rather than be in the repository. The [Acceptance](#acceptance) section,
the cuts to phase 1 and the first two owner decisions below are the result.

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

| Defect | Evidence | In phase 1 |
|---|---|---|
| `rwa-filer compare` dies with a Polars `SchemaError` traceback | 36 of 240 golden pairs: any resubmission whose differing fixed-table cells are all in sheet-less templates. The traceback's exit code equals "the returns differ" | Fixed |
| `compare`'s JSON output depends on Python's hash seed | Set iteration order reaches the output where differences tie | Fixed |
| The dashboard's evidence download can return a corrupted file with HTTP 200 when clicked twice | Two requests write the same file name at once; reproduced | Fixed |
| Two threads validating at once in a cold process crash | `KeyError` in the engine in 3 of 52 trials: an unlocked cached parse replaces a rule's tree after another thread keyed its selectors by the old one. The dashboard runs each task in its own thread | Fixed |
| A fact carrying many open dimensions stalls the XBRL reader | The reader tries every subset: 16,384 for one fact at 14 dimensions, about 1 s per fact at 18 | Fixed |
| The declared Polars floor is false | `polars>=1.0.0` is declared; the shipped code calls an API that arrived later | Fixed |
| `match_code` raises `ValueError` on a superscript digit in a code | Verified on shipped code | Plan item |
| `read_evidence` raises `UnicodeDecodeError` on a damaged file | Verified on shipped code | Plan item |
| A fact table whose open keys are written as QNames compares as different from itself | `validate` and `build` accept the form; `diff` and `compare` do not link it | Owner decision |

## The proposal

### Phase 1 — this change: every confirmed, verdict-neutral saving

Nothing in phase 1 changes a verdict, a count, a recorded break or its order, a trace, a
report on standard output, an evidence file or a written XBRL byte. The stated exceptions
are the defect fixes above (a crash becomes an answer; `compare`'s output stops depending
on the hash seed) and one addition on the progress line (item 8).

**1. Stop collecting garbage that is not garbage.** The one-shot command line gets its own
process entry that switches the cyclic collector off, and freezes the heap before exit so
shutdown does not walk it either. `main(argv)` itself is untouched, so an in-process
caller never has its collector changed. The dashboard, which runs until interrupted,
switches it back on before serving. Reading a workbook keeps the collector running: that
is the one input that does make cyclic garbage (with it off, peak memory grew by 111 MB
on a 455-sheet workbook; with it on it is flat). `RWA_FILER_COLLECTOR=on` keeps the
collector on for a run. Library code — pack load, XBRL read — pauses the collector for
the length of the bulk build and restores the state it found, so the dashboard, `rwa-calc`
and the test suite get the same saving without their collector policy being touched. The
package already does exactly this for its Arelle worker.
*Measured alone on unmodified code: `validate` 1.60 → 1.20 s, XBRL `validate` 2.36 →
1.52 s, `diff` 2.45 → 1.24 s, `compare` −33%.*

**2. Load the reference data once, and cheaply.** Build the pack's data points from
dictionary-encoded pairs (0.46 → 0.14 s). Build the XBRL fact index once per pack and
keep it with the pack, in a compact form the collector does not have to walk (0.57 s →
0.13–0.23 s for the first read, nothing for later reads; a tracked index would have cost
0.5 s back at every exit).
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
shared by the verdict and the trace, one address object per reported cell, and — only if
its guard can be made to bite, because the two challengers disagreed on it — the two
sides of the top comparison kept instead of re-evaluated. *Rule loop 1.8–2.0×; tracing a further
1.2–1.4×.* The member-less quadratic is replaced by an indexed lookup that returns the
same cells in the same order (13.7 → 0.9 s). `compare` asks for a trace without the
comparison log it never reads (a further −14%).

**6. Do the structure check per axis, not per cell.** Code alignment loops over the
distinct codes of one axis at a time, so its loop follows the distinct codes written
(at most the pack's 4,939 for codes that name something), not the facts; the resolved frame is split by table once instead of filtered 208 times.
*Structure check 54 → 21 ms on a typical return and 7.2 → 1.9 s at 955,000 facts; a
firm-shaped return of 92,000 facts validates in 6.0 s instead of 8.6 s.*

**7. Read XBRL per context, not per fact**, and bound the open-dimension subsets by the
most any data point leaves open (26,000-fact instance read 2.2–2.6 → 1.1–1.4 s; the
pathological stall becomes 0.5 s).

**8. Tell the user as soon as there is something to tell, and do no work nobody reads.**
When the structure check returns, the progress line says how many structure findings
there are and names the first, so a user with a structurally broken return is told after
about a second instead of after the whole rule run (3.5 s on a firm-sized return);
standard output and the report do not change. The JSON record is built only when
`--report` or `--format json` reads it (44–105 ms on every text `validate`). A run's
identity block is computed once. `build` does not check the structure a second time: a
private, already-checked writer entry is called only from the build, and the public
writer keeps its check. `diff` of two fact tables does not load a rule book it never
reads (0.96 → 0.29 s). `taxonomy list` does not load 14 packs to print one word per line
(1.4 → 0.15 s).

**9. Evidence writing:** one pass per side instead of two lookups per cell, block writes
on the compressed path, no per-evaluation scan of the labelled notes (−0.25 s of 2.5 s at
26,000 facts; identical content, and identical compressed bytes on the same zlib).

**10. Compare and dashboard.** The explanation step walks sorted differences with two
pointers instead of testing every pair (6.7 → 0.4 s, and still linear when a group mixes
rounding allowances). The progress page answers the moment the work ends instead of at
the next one-second poll (−0.3 to −1.0 s on every action over a second). A page asked for
during a re-validation waits for that validation instead of starting a second one. The
evidence download is collected once per validation, by one request at a time, and served
after that; the first comparison of a pair runs behind the progress page instead of as a
frozen page. The browser opens when the server answers, not a fixed 0.8 s later.

**11. Developer controls.** The reader-index change alone takes eleven test files from 72
to 33 s. The member suite runs under `pytest-xdist`, as its own dev-only commit, with the
scaling gates' verdict carried by call counts so parallel workers cannot flake them. The
two slowest tests get an indexed `closing_dimensions`. The declared Polars floor is
corrected and a CI job runs the whole member suite at the floor. The benchmark is committed
(`scripts/rwa_filer_benchmark.py`), so the next change can be measured the same way. The
behaviour snapshot is not: its record of the unchanged code is 510 MB. What it proved is held
in the repository instead by the goldens this change banks from the unchanged code (the
engine corpus, the parse golden, the per-pack equalities).

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

### Acceptance

The snapshot is our engine compared with itself. The change is accepted on these, none of
which is that:

- the member suite, with every new guard, and the root project's gates that read this
  engine's verdicts: `tests/acceptance/reporting` (the supervisory validation register),
  `tests/oracle`, `tests/contracts`, the reporting-coverage ratchet and the filing-mapping
  ratchet, unchanged baselines;
- the wheel-install check, since the console script gains a new entry;
- **the Referee Differential green on the pull request, with no engine verdict
  re-banked**: Arelle and `rwa_filer.boe` agree rule by rule on the golden returns. It
  cannot run in the development container; it runs in CI on this change's paths;
- the Bank's own sample instance (`test_sample_oracle.py`, `test_boe_sample.py`) is the one
  oracle not available to this work. It needs the Bank's sample, which neither the
  container nor CI holds: it is the owner's run, and plan item P6.60 (d) stays open.

Delivered as one pull request cut into one commit per work package, guards and change
together, so a moved verdict can be bisected to a package. Each package was verified in
its own worktree; one cross-package interaction was not seen until after the merge: the
new Polars-floor CI job is red on the commits between `102b144` and `e5c4e76`, because
a lazy-import probe added earlier asserted that `ssl` is not imported, and Polars 1.24
imports it itself. `10098ab` fixes the probe; the job is green from there.

### Phase 2 — proposed, not in this change

| Item | Why it waits |
|---|---|
| Incremental re-validation in a warm process: re-run only the rules whose tables changed | An edit on a 26,000-fact return costs 2.1 s today and about 1.1 s after phase 1; this would take it to about 0.8 s. The challenger could not break its premise in 540 edits, but sent the design back: reuse must be decided by comparing content inside `validate_return`, not by a caller-supplied dirty list. Needs its own design and oracle |
| `compare`: evaluate once per pair, describe on demand | A further 3–4.4× on large comparisons; a large change to the trace model |
| Skip parsing rules whose tables are not reported | About 60 ms after the faster parser. Changes which reason is reported for a rule that both fails to parse and is not reported, unless trust in the packaged books is stored somewhere; the proposed storage was rejected |
| Workbook reading through a faster engine | About 0.2 s of a 2 s cold validate for a 54-sheet workbook, about 1 s of 2.6 s for a 450-sheet one; a new compiled dependency whose cell typing must match the current reader's exactly |
| Overrides applied in Polars; the template grid's marks worked out once | About 3 ms and 8–10 ms on a typical return. The first feeds `build --adjustments`, where a row-order slip would move recorded breaks |
| Pin the Arelle environment so the referee cache holds | CI-only; an unrelated package update costs a 13-minute re-run today. Cannot be verified in the development container |
| Lazy imports across the whole command line | 30–60 ms on a control; about forty handler-local imports in the file every other change also edits |

### Decisions for the owner

These add an interface or change an output on purpose, so they are not taken here.

- **A warm process for the command line — the one thing that makes a repeat run
  instant.** After phase 1 a cold `validate` of a typical return is about 0.9 s, of which
  about 0.6 s is still fixed cost that only a process that stays up can avoid: a repeat
  validation in one process is 0.19 s for a fact table and 0.28 s for a workbook or XBRL
  instance. The smallest safe form is `rwa-filer validate FILE --watch`: the existing
  handler re-run in the same process whenever the file changes, with no daemon and no
  rule memo. It is a new interface, so it is the owner's call; it is the recommended next
  step.
- **Print the verdict before the evidence file is written.** The report would arrive
  24–29% sooner on `validate --evidence`. But today a failed evidence write leaves standard
  output empty and exits 1; afterwards a script would see a complete "submittable" report
  and exit 1, with a truncated evidence file at its final path. It needs an atomic
  evidence write and a distinct exit code first.
- **A structure-only or fail-fast switch**, for a user who wants the structure findings
  and nothing else.
- **Evidence compression level.** Level 6 instead of 9 saves 0.55–0.67 s of a 2.5 s
  evidence write at 26,000 facts; the `.gz` is 12.6% larger and its checksum (and the
  manifest's `evidence.sha256`) changes. Content digest and evidence id do not.
- **Open keys written as QNames** (`eba_GA:FR`) validate normally but compare differently
  from the local-name form. Normalise on read, or raise a structure finding.
- **Positions of facts that share coordinates** follow an unstable sort. Define the order
  (coordinates, then input position) as a stated change.
- **How the tool is launched.** The README's `uvx rwa-filer@latest` checks PyPI on every
  run. Measured in [Outcome](#outcome); if it is material, the advice for interactive use
  becomes an installed tool.

### Rejected

Shipping rule books pre-parsed (saves about 68 ms after the faster parser, and a stale
artefact is the one way to change a verdict silently); a per-user on-disk cache of parsed
rules; a table-to-rules dependency index (under 7 ms); compiling rules to closures;
`os._exit` at the end of the command (7 ms for giving up exit hooks and stream flushes);
reusing a dashboard validation for a build (changes a byte of a signed-off file).

## Expected result of phase 1

One of the red-team reviewers merged three of the lens prototypes (collector entry,
release loading, rule engine) into a single tree and measured it; its standard output is
byte-identical on every row. It lacks the trace, XBRL-reader, structure, compare and
dashboard changes, so the full phase 1 should be somewhat faster. CPU seconds in both
columns, best of 1–3 on a loaded box; the [Outcome](#outcome) section replaces this with
wall-clock on a quiet one, base and new interleaved.

| Path | Today | Three-lens prototype |
|---|---|---|
| `validate`, 251 facts (the fixed floor) | 1.23 | 0.64 |
| `validate`, 2,227 facts, fact table | 1.63 | 0.86 |
| `validate`, 2,227 facts, workbook | 2.04 | 1.08 |
| `validate`, 2,227 facts, XBRL | 2.48 | 1.15 |
| `validate`, 25,987 facts, fact table | 3.42 | 1.59 |
| `validate`, 25,987 facts, XBRL | 5.66 | 2.32 |
| `validate --evidence`, 25,987 facts | 8.52 | 5.07 |
| `build`, 25,987 facts | 4.49 | 2.40 |
| `compare`, 2,227-fact pair | 4.00 | 1.43 |
| `compare`, 25,987 vs 7,987 facts | 12.46 | 5.19 |
| `diff`, two instances | 2.24 | 0.87 |
| `validate`, 92,000 facts, fact table | 7.84 | 2.94 |
| `validate`, 92,000 facts, XBRL (67 MB) | 15.04 | 7.26 |
| `build`, 92,000 facts | 12.74 | 6.00 |
| Dashboard edit, 2,227 facts | 0.30 | 0.19 |
| Dashboard edit, 25,987 facts | 2.13 | 1.08 |
| Repeat validation in a warm process, 2,227 facts | 0.34 | 0.19 |

Phase 1 roughly halves every wait. It does not make a cold command instant: about 0.64 s
of the 0.86 s for a typical return is still fixed cost — interpreter, Polars import, pack
load — before any work. The dashboard is already the warm path, and the first decision
for the owner above is what brings the command line to the same place.

## Outcome

### What phase 1 bought

Cold command line, the code before this change (`85cfe58`) and after it, interleaved case
by case, best of three, wall clock and the child's own CPU (`uv run python
scripts/rwa_filer_benchmark.py run --against merge-base`, the branch point being
`85cfe58` when it was run). The box was shared with review
agents during the run, which falls on both columns alike.

| Command | Before: wall / CPU | After: wall / CPU | Faster |
|---|---|---|---|
| `--help` | 0.30 / 0.30 s | 0.21 / 0.21 s | 1.4× |
| `taxonomy list` | 1.21 / 1.24 s | 0.24 / 0.23 s | 5.0× |
| `validate`, 2,227 facts, fact table | 1.70 / 1.81 s | 0.78 / 0.90 s | 2.2× |
| `validate`, 2,227 facts, XBRL | 2.39 / 2.55 s | 0.85 / 0.92 s | 2.8× |
| `validate`, 7,987 facts, fact table | 2.02 / 2.21 s | 0.86 / 0.98 s | 2.3× |
| `validate`, 25,987 facts, fact table | 3.73 / 3.92 s | 1.40 / 1.55 s | 2.7× |
| `validate`, 25,987 facts, XBRL | 5.71 / 5.83 s | 2.38 / 2.49 s | 2.4× |
| `validate --evidence`, 2,227 facts | 2.27 / 2.38 s | 1.13 / 1.25 s | 2.0× |
| `validate --evidence`, 25,987 facts | 8.83 / 8.93 s | 4.51 / 4.65 s | 2.0× |
| `build`, 2,227 facts | 1.92 / 2.15 s | 0.83 / 0.93 s | 2.3× |
| `build`, 25,987 facts | 4.61 / 4.94 s | 2.16 / 2.35 s | 2.1× |
| `compare`, 2,227 vs 1,821 facts (XBRL) | 3.35 / 3.42 s | 1.12 / 1.23 s | 3.0× |
| `compare`, 25,987 vs 7,987 facts (XBRL) | 11.68 / 11.71 s | 3.83 / 3.97 s | 3.0× |
| `diff`, two XBRL instances | 2.39 / 2.42 s | 0.61 / 0.68 s | 3.9× |
| `diff`, two fact tables | 0.90 / 0.92 s | 0.25 / 0.26 s | 3.6× |

Against the three-lens prototype's CPU figures in the expected-result table above, the
validate rows land within 0.2 s either way (0.90 against 0.86 s on a small fact table,
2.49 against 2.32 s on the large XBRL instance; 0.92 against 1.15 s on the small one), and
`compare`, `diff`, `build` and the evidence export beat it, because the lean trace, the
linear explanation and the evidence and build changes were not in that prototype. Beyond
the command line:

- **A return with a structural error** is now told so on the progress line when the
  structure check returns, 0.5 s into a 25,987-fact validation, instead of at the end.
- **Dashboard:** the progress page answers when the work ends, not up to a second later;
  a second Download evidence click on a 7,987-fact return 2.10 s → 0.17 s; a page asked for
  during a re-validation no longer starts a second one; a pair's first comparison shows
  progress instead of a page that hangs.
- **Memory:** the XBRL reader's index of the pack 110 MB → 4.8 MB, kept once per process;
  a 455-sheet workbook's peak 326-350 MB → 248-271 MB.
- **Large and awkward returns,** where the old code was super-linear: 40 blank-country
  cells on a 200-country return, `validate_return` 3.2-3.6 s → 1.4 s; `compare`'s
  explanation at 200 countries 12.3 s → 0.7 s; two facts carrying 18 open dimensions
  each took 2.16 s of CPU to read, now 0.01 s.
- **The member test suite:** 1,843 tests in 216 s serially before; 2,414 tests (571 of
  them new guards) in 191 s serially after, and about 66-70 s on four workers (`-n auto` on 4 cores), as CI now
  runs it.
- **How the tool is launched** matters as much as several of the rows above: `uvx
  rwa-filer@latest --version` took 0.70-0.78 s against 0.24 s for an installed command,
  because `@latest` asks PyPI on every run. For repeated, interactive use,
  `uv tool install rwa-filer` saves about half a second a command.

### What was not done, and why

| Item | Why |
|---|---|
| Printing the verdict before the evidence | An output change on failure (a complete "submittable" report on stdout, exit 1); the owner's call, recorded in P6.61 |
| A warm process for the command line | A new interface; the owner's call and the recommended next step (P6.61 a) |
| Overrides applied in Polars; the grid's marks cached | 3 ms and 8-10 ms on a typical return; the first feeds `build --adjustments` |
| Skipping the parse of rules whose templates are not reported | About 60 ms after the faster parser, and it changes the reason reported for a rule that both fails to parse and is not reported (P6.61 d) |
| A collector pause in the rule-book and issue-register loaders | Measured 6 and 2 young collections: nothing to win |
| The writer's per-data-point fixed-member cache | 60-70 ms on a 26,000-fact build, a second cache for a small gain |
| Handler-local imports across `cli.py`; signoff and verify imports | 30-60 ms on a control, in the file every other change also edited (P6.61 f) |
| The evidence gzip level | Changes the `.gz` bytes and its checksum in manifests; the owner's call |
| The dashboard's first evidence click as a task | A navigation that ends in a download leaves the progress page behind; the click still blocks for one collection |

### Defects found and fixed on the way

Each has its entry in `docs/development/escape-log.md` (2026-11-22), with its escape class,
the gate that now catches it and the red that gate was seen against: the `compare` crash on
sheet-less templates; `compare`'s dependence on the hash seed; the quadratic explanation
step; the quadratic return of the rule engine on blank-country facts; the two-thread
parsing crash; the XBRL reader's stall on many open dimensions; the false Polars floor; the
dashboard's corrupted evidence download. Smaller ones found and not fixed are plan items
P6.62-P6.65.

### Not verified here

- **The Referee Differential** (Arelle against `rwa_filer.boe`, rule by rule, on the golden
  returns) cannot run in the development container; it runs in CI on this change's paths
  and must be green with no engine verdict re-banked.
- **The Bank's own sample instance** (`test_sample_oracle.py`, `test_boe_sample.py`) needs
  a file neither the container nor CI holds: plan item P6.60 (d).
- **Python 3.14**: the collector policy was measured on 3.14.6 by the cold-start
  challenger and the reader's index on 3.14 by its implementer; the rest of phase 1 was
  measured on 3.13 only.

## Appendix: method

- **Baseline and benchmark.** Sixteen golden Basel 3.1 PRA001 returns built through
  `rwa-calc`, plus the richest one copied out to 50 and 200 countries, as fact tables and
  as written XBRL. Fifteen cold command-line cases (`scripts/rwa_filer_benchmark.py`), best of three; the first baseline, taken before the script existed, timed thirteen of them.
- **Equivalence snapshot.** 146 sections recorded from the unchanged code; timestamps,
  paths and the one digest that covers a timestamp are scrubbed, and a re-run reproduces
  the record exactly.
- **Measuring on a shared box.** Wall-clock moved ±40% between identical runs while the
  reviews ran, so reviewers and challengers quote main-thread CPU, deterministic call
  counts and back-to-back ratios; wall-clock figures are quoted only from quiet stretches.
- **Prototypes.** Each proposal was prototyped in a scratch copy of the package and run
  with that copy first on the import path; every run prints the path of the module under
  test, so no number here was measured on code other than the code it describes.
