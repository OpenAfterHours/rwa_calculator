# The dashboard

`rwa-filer dash` starts a dashboard on your own machine and opens it in the
browser. It shows the same validation `rwa-filer validate` prints, and lets you
walk from the verdict, to a broken rule, to the cells on the template grid that
broke it.

```bash
# Nothing to install first: uvx fetches rwa-filer into a throwaway environment
uvx rwa-filer@latest dash

# Open a return straight away
uvx rwa-filer@latest dash return.xbrl

# A fact table carries no header, so give one
uvx rwa-filer@latest dash facts.parquet --entity 5493001KJTIIGC8Y1R12 \
    --reference-date 2027-03-31 --module PRA001
```

The command prints one address and opens it:

```text
rwa-filer dash is running at http://localhost:8765/returns/2e5c2d7d?token=…
The address carries this session's token: keep it to yourself. Ctrl+C stops it.
```

!!! warning "The regulator's validation is authoritative"
    The dashboard shows `rwa-filer`'s own checks. A clean result is evidence that
    a return is well-formed, not a guarantee that the regulator will accept it.

## Options

| Option | What it does |
|--------|--------------|
| `FILE` | A return to open as the dashboard starts: `.parquet`, `.csv`, `.xlsx`, `.xbrl` or a `.zip` holding one |
| `--entity`, `--reference-date`, `--module`, `--currency` | The return header. Required with a fact table; with a workbook or an instance, each one given overrides the file's own |
| `--taxonomy VERSION` | The taxonomy release every return opened in this session is validated against, unless the open form names another. The default is the release live for each return's module (see [Taxonomy releases](index.md#taxonomy-releases)) |
| `--port N` | The port to try first (default 8765). If it is taken the next free one is used, so two dashboards can run side by side |
| `--no-browser` | Print the address but do not open a browser |
| `--workdir DIR` | Where the dashboard keeps files opened in it. The default is a new temporary folder |
| `--progress` / `--no-progress` | Whether to show how far opening `FILE` has got before the dashboard starts. Shown by default in a terminal (see [Seeing how far a check has got](index.md#seeing-how-far-a-check-has-got)) |

## The pages

**Open a return.** Choose a file, or type the path of one on this machine. A
fact table needs its header (entity, reference date, module); a workbook or an
XBRL instance states its own, and anything entered on the form overrides it.
The form also names the taxonomy release to validate against; left at its
default, it is the release live for the return's module. Returns you open stay
listed until the dashboard is stopped.

Under **Break it down (optional)**, a fact table can be opened as a detail:
several rows per cell, each saying in its own columns where it came from — a
business unit, a source system, a journal. Name those columns, and optionally
the column holding each line's own reference (see
[A fact table with several rows per cell](index.md#a-fact-table-with-several-rows-per-cell)).
The rows of a cell are added together, and the sum is the figure validated and
filed; the rows are kept, so the Templates and Investigate pages can split any
figure by those columns. A file opened without them can be broken down later
from its Overview or Investigate page, which list the columns the file has that
were not read.

**While a return is validated.** A small return opens straight onto its
overview. If the work is still going after a second, which a full PRA001 return
always is, a progress page replaces the frozen form. It shows each step
(reading the file, checking its structure, evaluating the published rules), a
bar with how many of the rules are done, and how long the work has run. The page
keeps itself up to date and moves on to the overview the moment the work ends,
not at the next refresh. A page of the same return asked for while it is being
validated waits for that validation rather than starting another. If the file
cannot be opened, the reason appears on the Open page with the form still
filled in. You can leave the page meanwhile: the work is listed under **Under
way** in the side navigation until it ends. The same progress page appears when
a return is opened against another release, when another version is opened on
the Compare page, after an override is drafted or withdrawn (the return is
validated again with it), and while a package is built.

Every page of a return shows, in the top bar, the taxonomy release it was
validated against, the module's status in it (live or future) and whether the
release was the default or chosen. When another shipped release has the module,
a switch beside it opens the same file again against that release, as a second
return beside the first, so the two can be compared. Drafted overrides are not
carried across: a cell one release accepts may not exist in another.

One file is one return, validated on its own. Put every template of the return
in that file: one fact table with a row per cell, one workbook (`rwa-filer
template --tables ...` writes the worksheets), or one instance. Rules that check
one template against another run only when both are in the same return, so
templates opened as separate files are never checked against each other.

**Every page shows the return as it would be filed now.** Once you draft an
override (see *Build & sign off* below), the Overview, the Rules, the template
grid, the Build & sign off page and the verdict in the top bar are all worked
out for the return with the drafted overrides applied, the way a build would
validate it. A banner on each page says how many overrides are applied and how
many blocking findings the return had as opened. An override that clears a
break clears it on every page, and withdrawing it brings the break back. The
return is validated again once each time the overrides change, not each time
a page is drawn. The file itself is never changed: overrides live beside it
until a build applies them. Compare is the exception: it compares the two
files as they were opened.

**Overview.** Whether anything blocks submission, and the counts behind the
answer: structure findings, rule breaks by severity, how many of the rules the
module enforces were executed, and — for every rule that was not — why
(`template_not_reported`, `no_data`, ...). "No breaks" is never shown on its own:
a return on which few rules ran says so, as `VAL003` does on the command line.
Each reported template is listed with the rules that read it.

Below them, **Linked templates not in this return** lists every template the
return leaves out that rules check a reported template against — OF 09.02 for a
return holding OF 08.01 without it, say — with how many rules did not run
because of it and which reported templates they read. These are the `VAL004`
warnings. The gateway does not run those rules either while the template is not
filed, so leaving one out does not fail them: the return is accepted unchecked,
and the regulator does not get those figures. Load each template the firm is
required to report. A template the return declares not filed (a negative filing
indicator in an XBRL instance) is not listed.

**Rules.** Every enforced rule, filtered by status (failed, passed, not
evaluated), severity, template, or words in its ID or label. Picking a rule shows
the expression as the Bank's workbook states it, how many of its evaluations
held and how many broke, and for each of the first breaks the cells it read with
the values they held. Each of those cells links to the template grid.

**Known issues with the published rules.** A result a known issue explains (see
[Known issues with the published rules](index.md#known-issues-with-the-published-rules))
carries a "Known issue PI-nn" chip on the rules list, the overview's breaks and
the module reference page, or an "Open question PI-nn" chip where the issue is a
question to the Bank about how the rule is meant to be read. Picking the rule,
or a cell a labelled break read in the template grid, shows a callout: the
issue's title, where it stands with the Bank, how many of the breaks here are
where it applies (and how many are not, and so are not explained by it), the
first passage of the instructions it rests on, what a firm can do meanwhile, and
the command that prints the whole issue.
The verdict beside it is unchanged.

**Templates.** One table of the return, laid out in the publisher's own rows,
columns and sheets — the layout `rwa-filer template` writes as a workbook. Cells
the taxonomy does not accept on a sheet are hatched. Every cell a broken rule
read is outlined, red for an Error rule and amber for a Warning one, including
the empty cells a rule read at its default, which are often what the break is
about. That is every break of the rule, not only the first few the Rules page
lists: a rule that breaks on every row of every sheet marks every row. Pick a cell to see its row and column labels, its value and data type,
and the broken rules that read it. Each rule is shown with the publisher's
description of it, so `boe_b0713` reads as "the total exposure row 0010 shall
equal the sum of all the sheets for each exposure class" rather than as a code.
**Read the rule** expands it in place, without leaving the grid: how many of its
evaluations broke, the break that read this cell with the value of every cell it
read (each linking to that cell on the grid, this one outlined), and the
expression and scope as the Bank's workbook states them. The panel widens while
a rule is open, and a rule opened on one cell stays open as you pick others in
the same browser tab. **Show only this rule's cells** greys out every other
rule's marks; **Open on the Rules page** shows the rule with its first breaks
and how many there are in all.

For a return opened with breakdown columns, the panel also says **where this
figure comes from**: the picked cell split by one of the columns (a switch
moves between them), each member's amount and share. A member that breaks,
on its own figures, a broken rule reading the cell is marked in amber; a
figure an override has changed shows the change as *Not in the detail*. Each
broken rule reading the cell then says **who breaks it**: the rule run again
on each member's rows alone, every member's two sides of the comparison beside
the return's, and one sentence saying where the gap is — "All of the 100,000 is
in Asset Finance. The other 3 business_unit members meet the rule on their own
figures."

**Investigate.** For a return opened with breakdown columns: every broken rule
against the members of one column, each run again on that member's rows alone.
The table has one row per broken rule and one column per member that breaks
something, with how many of the rule's breaks the member is in and by how much,
beside the return's own gap. Members' gaps add up to the return's for a rule
that is a sum or a difference; where they do not (an override drafted on a
summed figure, a rule that is not a plain sum), the remainder is shown as in no
member, never spread over them. Below it, **Hold in the return, break inside a
member** lists the evaluations a total hides: a rule the return meets that a
member's own figures break, usually two figures wrong in opposite directions.
Only rules over amounts are searched, as a percentage or a count cannot be
judged on part of the rows. Picking a member shows the rules it breaks, each
with a link to the cell on the template grid, a note to copy and send to
whoever owns the member's figures, and its figures as CSV. The first time a
column is asked for, the rules are run on every member behind the progress
page; the result is kept until the drafted overrides change. A return opened
without breakdown columns shows the columns its file has and opens it again
with the ones you pick.

**Build & sign off.** The same three acts as `rwa-filer build`, `signoff` and
`verify`, recording the same things:

- *Overrides.* Pick a cell on the template grid and draft an override: a new
  value, or taking the cell out of the return (unreported, which is not the same
  as zero), with the reason — required, because it is recorded. A draft is
  checked against the ones already made, so one that could never be applied is
  refused when it is made. Drafted cells show their new value on the grid,
  outlined in blue, and the grid's red and amber marks are those of the return
  with the overrides applied, so a cell whose break an override clears is no
  longer marked. Below the overrides, the page says what they change: the
  blocking findings and rule breaks before and after, then each rule they move.
  A broken rule that now holds is listed under *Fixed*. A broken rule that no
  longer runs, because the overrides took out the figures it reads, is listed
  under *No longer run*, with the reason. It is not counted as fixed, because
  nothing checks those figures any more. Any rule the overrides newly break is
  listed under *Newly broken*. The page also counts the rules that held as
  opened and no longer run.
- *Build.* Choose the folder (beside the opened file by default, or a `filing`
  folder in the working directory for an uploaded one) and the options the
  command takes: monetary accuracy, percentage decimals, declaring unreported
  templates, always zipping, omitting the creation time. A return a published
  rule blocks is written only if you choose to write it anyway, and the manifest
  records that you did; a structure finding stops the file whatever you choose.
  With a preparer's name the build — and the overrides applied before it — go
  into the audit ledger beside the files. The written files can be downloaded
  from the page; nothing else can.
- *Sign off.* The approver and their capacity, optionally a statement, bound to
  the instance's SHA-256. A package the validation found not submittable is
  signed only with the findings acknowledged. A refused sign-off records
  nothing in the ledger.
- *Verify.* That the instance and zip are the files the manifest describes, that
  the sign-off was given for exactly them, and that the ledger is intact and is
  the one the sign-off was recorded in.

A build from the dashboard is the build the command makes: the same return,
overrides and options give byte-identical files.

**Compare.** This return beside another one: a version already opened, or a
file opened from the page, such as the instance already filed or the return your
current system produces for the same date. The earlier one is the baseline.
First, why they differ, as `rwa-filer compare` says it. Every cell is counted
by category (the same, within the files' rounding, a zero against a blank, a
template only one side files, material), and the material differences are
grouped into findings. Each finding says which return the Bank's rules point
at, with each rule's standing in both, and links to its cells. Rules are judged
as the Bank's gateway runs them today: one its validations deny list switches
off is named as switched off, never as broken. Then every cell that changed,
was added or was removed, by table, filterable by kind, by category and by
finding, with the difference in each figure. After that come
any header field that differs, and what the change did to the verdict: the
broken rules the later version fixed, the ones it newly breaks, and the
blocking findings before and after. Swap the two to read the change the other
way. The counts are `rwa-filer diff`'s own. A pair is compared once per
session, so filtering does not re-run the rules. The first comparison of a pair
that takes more than a second runs behind the progress page, and a second tab
asking for the same pair waits for it rather than comparing again.

**Referee (Arelle).** The second opinion `rwa-filer referee` gives: the Arelle
XBRL processor checks a written instance against the Bank's taxonomy package,
and its verdict on every rule is set beside this package's own. The page offers
the instances this return has — the file itself when it is an XBRL instance, and
every package a build wrote — and asks for the taxonomy package's path and,
optionally, the interpreter that has Arelle and a pattern for the rules to run.
The run goes on in the background (a large module takes minutes and several GB)
and the page shows how many workers have finished, then the verdict, Arelle's
messages, and every rule on which the two engines part. Arelle is optional: the
page says how to install it when it is not there.

**Taxonomies & rules.** Every shipped taxonomy release's modules, each with its
status in that release today, its pack and its rule book, the rules it enforces
and whether a return of it can be validated (both a pack and a rule book); and
for each module in each release its tables and its enforced rules, searchable —
without a return open.

The theme switch in the top bar swaps between the dark look (the default, as in
`rwa-ui` and these docs) and a light one; the choice is remembered.

## Who can use it

The dashboard listens on `127.0.0.1` and nowhere else, so nothing outside
this machine can reach it. The address it prints carries a random token for the
session: opening it sets a cookie, and every request after that must carry the
cookie. Another user of the same machine, or a web page that guesses the port,
is refused. A form posted from another site is refused too, and so is a request
for any host name other than the loopback ones, which stops a page that rebinds
its own name to `127.0.0.1`.

There is deliberately no option to listen on a network interface: the server
speaks plain HTTP, so it would send the session token, and every figure of the
return, across that network unencrypted. Both cookies it sets are `HttpOnly`;
they are also marked `Secure` whenever a page is served over HTTPS (on plain
HTTP to this machine some browsers refuse a `Secure` cookie altogether).

Nothing is sent anywhere: files are read where they are, or kept in the working
folder when they are uploaded through the browser.

## Why these dependencies

`rwa-filer` itself needs only Polars. The dashboard adds Starlette, uvicorn,
Jinja2 and python-multipart — a small, pure-Python web stack, with no FastAPI or
pydantic — and they are ordinary dependencies rather than an extra so that
`uvx rwa-filer@latest dash` (or a bare `uvx rwa-filer dash`) works exactly as
typed. Nothing on the validation or filing path imports them: they load only
when the `dash` command runs.
