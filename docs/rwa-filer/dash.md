# The dashboard

`rwa-filer dash` starts a dashboard on your own machine and opens it in the
browser. It shows the same validation `rwa-filer validate` prints, and lets you
walk from the verdict, to a broken rule, to the cells on the template grid that
broke it.

```bash
# Nothing to install first: uvx fetches rwa-filer into a throwaway environment
uvx rwa-filer dash

# Open a return straight away
uvx rwa-filer dash return.xbrl

# A fact table carries no header, so give one
uvx rwa-filer dash facts.parquet --entity 5493001KJTIIGC8Y1R12 \
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
| `--port N` | The port to try first (default 8765). If it is taken the next free one is used, so two dashboards can run side by side |
| `--no-browser` | Print the address but do not open a browser |
| `--workdir DIR` | Where the dashboard keeps files opened in it. The default is a new temporary folder |

## The pages

**Open a return.** Choose a file, or type the path of one on this machine. A
fact table needs its header (entity, reference date, module); a workbook or an
XBRL instance states its own, and anything entered on the form overrides it.
Returns you open stay listed until the dashboard is stopped.

**Overview.** Whether anything blocks submission, and the counts behind the
answer: structure findings, rule breaks by severity, how many of the rules the
module enforces were executed, and — for every rule that was not — why
(`template_not_reported`, `no_data`, ...). "No breaks" is never shown on its own:
a return on which few rules ran says so, as `VAL003` does on the command line.
Each reported template is listed with the rules that read it.

**Rules.** Every enforced rule, filtered by status (failed, passed, not
evaluated), severity, template, or words in its ID or label. Picking a rule shows
the expression as the Bank's workbook states it, how many of its evaluations
held and how many broke, and for each of the first breaks the cells it read with
the values they held. Each of those cells links to the template grid.

**Templates.** One table of the return, laid out in the publisher's own rows,
columns and sheets — the layout `rwa-filer template` writes as a workbook. Cells
the taxonomy does not accept on a sheet are hatched. Every cell a broken rule
read is outlined, red for an Error rule and amber for a Warning one, including
the empty cells a rule read at its default, which are often what the break is
about. Pick a cell to see its row and column labels, its value and data type,
and the rules that read it; pick a rule there to show only that rule's cells.

**Build & sign off.** The same three acts as `rwa-filer build`, `signoff` and
`verify`, recording the same things:

- *Overrides.* Pick a cell on the template grid and draft an override: a new
  value, or taking the cell out of the return (unreported, which is not the same
  as zero), with the reason — required, because it is recorded. A draft is
  checked against the ones already made, so one that could never be applied is
  refused when it is made. Drafted cells show their new value on the grid,
  outlined in blue. *Check the return with these overrides* validates the
  adjusted return and shows the blocking findings before and after.
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

**Compare.** This return beside another version of it — one already opened, or
a file opened from the page, such as the instance already filed. Every cell that
changed, was added or was removed, by table and filterable by kind, with the
difference in each figure; any header field that differs; and what the change did
to the verdict: the broken rules the later version fixed, the ones it newly
breaks, and the blocking findings before and after. Swap the two to read the
change the other way. The counts are `rwa-filer diff`'s own.

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

**Taxonomies & rules.** Every packaged taxonomy pack and rule book, with the
rules each module enforces and whether a return of it can be validated (both a
pack and a rule book), and for each module its tables and its enforced rules,
searchable — without a return open.

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
`uvx rwa-filer dash` works exactly as typed. Nothing on the validation or filing
path imports them: they load only when the `dash` command runs.
