---
name: regulation-text
description: >
  Get the verbatim text of a Basel 3.1 (PRA PS1/26) or UK CRR article on demand, and
  find which calculator code and rulepack entries implement it. Use when you need to
  quote or check what an article actually says (before a change that moves RWA, when
  auditing a citation, when a plan bullet claims a rule), when you need the CRR article
  a PS1/26 article corresponds to, or when you need to know which function cites an
  article or which articles have no code yet. Works offline from a committed index;
  the text itself is fetched and converted locally on first use.
---

# Regulation text: committed index plus on-demand text

The `basel31` and `crr` skills answer **"what number"** (generated from the rulepack).
This skill answers **"what does the rule say, and where is it in our code"**.

Never reconstruct an article from memory (LESSONS A2). Run `show` and quote what it
prints.

## Look up an article

```bash
uv run python scripts/regulation_text.py show "PS1/26 124F"
uv run python scripts/regulation_text.py show "CRR 501a"
uv run python scripts/regulation_text.py show 153          # bare number = PS1/26
uv run python scripts/regulation_text.py find real estate  # search headings / titles
```

`show` prints, in this order:

1. **The index entry** (always, offline): heading, the CRR article it corresponds to,
   the paragraphs marked "Provision left blank" or "Provision not in PRA Rulebook",
   the `@cites` functions and the rulepack entries that cite it.
2. **Any recorded correction** (from `index/corrections.csv`) as a `WARNING:` line.
3. **The text**, from the best source available here:
   - **Official**: the article cut out of `docs/assets/ps126app1.pdf` (PS1/26) or
     `docs/assets/crr.pdf` (UK CRR), with its page numbers. If the PDF is missing,
     `show` downloads it once (via `scripts/download_docs.py`) and converts it into
     the git-ignored cache `.regulation-text/` in the main checkout, shared by every
     worktree. Later lookups in the session are instant.
   - **Snapshot**: if the official text can't be had (no network, host blocked), the
     parsed text bundled in the installed `watchfire` package, clearly labelled. It is a
     third-party parse dated 2026-05-16: it can split or merge paragraphs, and it lacks
     some articles (for example 160 to 164 and 166A to 166D). Good enough to orient;
     **not** good enough to quote for a change that reduces RWA.
   - **Neither**: one line saying why, and the index entry still stands.

Flags: `--offline` (or `RWA_REGTEXT_OFFLINE=1`) never downloads;
`--source official|snapshot|none` forces one source. `RWA_REGTEXT_CACHE` moves the cache.

## The renumbering trap (LESSONS A3)

PS1/26 renumbers. The `crr_article` column (from the `[Note: corresponds to Article NNN]`
line) is the CRR mapping; the PS1/26 heading number is not. Two notes are not synonyms:

- `left_blank`: "Provision left blank" means **deleted** under Basel 3.1.
- `not_in_rulebook`: "Provision not in PRA Rulebook" means it **survives in CRR**, and
  PS1/26 may still cross-reference it.

Both columns come from the snapshot parse. Confirm them in the official text before you
rely on one.

## Answer code questions from the index alone

The CSVs are grep-friendly, one row per article:

```bash
rg '^153,' .claude/skills/regulation-text/index/b31.csv          # who implements Art. 153
rg 'engine/irb/formulas.py' .claude/skills/regulation-text/index/ # what does this file cite
```

| File | Rows | Columns |
| --- | --- | --- |
| `index/b31.csv` | every PS1/26 Appendix 1 article in the snapshot, plus every article the code cites | `article, heading, crr_article, left_blank, not_in_rulebook, in_snapshot, pack_entries, functions` |
| `index/crr.csv` | every UK CRR article in the snapshot, plus every cited one | `article, title, b31_articles, in_snapshot, pack_entries, functions` |
| `index/other.csv` | citations that are not an article (PS1/26 transitional rules such as 4.1, SS paragraphs) | `reference, pack_entries, functions` |
| `index/corrections.csv` | hand-kept amendments the PDFs lack (empty until one is added) | `regime, article, instrument, summary` |

- `functions` entries are `path/under/src/rwa_calc.py::qualname`, with the cited
  sub-reference in brackets when the citation is finer than the article.
- `pack_entries` entries are `regime:entry_name`; read the value in the pack or in
  `docs/data-model/regulatory-tables.md`, never from this skill.
- An article with empty `functions` and `pack_entries` has no code that cites it. That
  is a lead, not a finding: the rule may be implemented without a citation.
- `in_snapshot = no` means the code cites an article the snapshot does not have: check
  the number, then read it in the official text.

## Keeping it current

- The index is **generated**: `uv run python scripts/regulation_text.py index` (it also
  refreshes the `.agents/skills` mirror). Run it after adding or changing a `@cites`
  decorator or a pack `Citation`. `tests/contracts/test_regulation_text.py`
  fails while it is stale, so a new citation cannot land without its row.
- Never hand-edit `b31.csv`, `crr.csv` or `other.csv`. Do hand-edit `corrections.csv`
  when an amending instrument changes an article after the PDF was published: one row
  per affected article, with the instrument and a one-line summary in your own words.
- `uv run python scripts/regulation_text.py check` reports index freshness, recorded
  corrections, and whether each PDF is downloaded and converted here.
- After 1 January 2027 the consolidated PRA Rulebook pages become the up-to-date
  source. They are not fetched yet.

## Why the text is not committed

The PS1/26 documents and the PRA Rulebook are under Bank of England / PRA terms that do
not allow redistributing modified copies, so converted Basel 3.1 text stays in the
git-ignored cache. The committed index holds only article numbers, headings, note
markers and links to our own code. UK CRR text on legislation.gov.uk is under the Open
Government Licence, but it is fetched the same way for now.

## In a cloud session

The cloud container is rebuilt each session, so the cache starts empty. The first
`show` of each regime downloads one PDF (a few MB) from www.bankofengland.co.uk or
www.legislation.gov.uk. If the environment's network settings block those hosts, `show`
says so and falls back to the snapshot and the index. `pymupdf` and `watchfire` come
from PyPI with `uv sync`.
