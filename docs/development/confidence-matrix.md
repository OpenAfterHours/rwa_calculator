# Confidence & Evidence Matrix

<!-- GENERATED FILE — DO NOT EDIT. Regenerate: uv run python scripts/generate_confidence_matrix.py -->

Per-article view of the **independent evidence layers** that already exist in this project, joined so a reader can see, for each regulatory article, whether it is backed by an implementation, a hand-derived golden, and/or a test — and where those layers disagree. **This page is generated** from those layers; a wrong row is a finding in one of the sources, never a docs edit.

## Evidence layers

| Layer | Source | Nature |
|---|---|---|
| **Code** | `tests/contracts/data/citation_snapshot.json` (`@cites` annotations) | citable anchor — a decorated function |
| **Pack** | resolved rulepacks via `rwa_calc.rulebook.resolve` | citable anchor — a cited regulatory value |
| **Source** | text scan of `src/rwa_calc/**/*.py` | implementation footprint — the article is named in production code (not necessarily `@cites`-annotated) |
| **Oracle** | `tests/oracle/expected_values.json` (`regulation` field) | a hand-derived golden (parenthetical contrast notes excluded) |
| **Tests** | text scan of `tests/**/*.py` | **heuristic** — a lexical citation match, not an executed link |

## Scoring rule

An article has a **citable anchor** when the *Code* (`@cites`) or *Pack* layer cites it — a machine-verifiable link. Being named in production *Source* is a **weaker signal**: usually an implementation footprint, but a docstring `References:` mention alone can also produce it. The tier is:

| Tier | Rule |
|---|---|
| **HIGH** | citable anchor **and** an oracle case exists |
| **MEDIUM** | citable anchor **and** a (heuristic) test reference, but no oracle case |
| **LOW** | citable anchor, but no oracle case and no test reference |
| **UNCITED** | no citable anchor, but named in production source — usually implemented yet un-annotated, though a `References:`-only mention lands here too (the SA-CCR cluster is here: watchfire's index omits those CRR articles, so `@cites` cannot be applied) |
| **GAP** | not implemented at all — cited only by the oracle and/or a test, with no code, pack, or source reference behind it |

Only **GAP** is an actionable coverage hole. **UNCITED** is a citation-debt signal, not a missing-implementation one.

Articles are grouped by the citing instrument and keyed by *base* article (`122` for a `122(2)` citation); the layers cite the same rule at different sub-reference granularity, so the machine-readable snapshot at `tests/contracts/data/confidence_snapshot.json` preserves the full member list per layer for audit.

Package version `0.3.25`. Resolved packs:

- **CRR** (`crr` @ 2026-01-01) — content hash `ce2b4dbd2b2f7daf`
- **Basel 3.1** (`b31` @ 2027-01-01) — content hash `9a883964d8479e76`

## Summary

| Instrument | HIGH | MEDIUM | LOW | UNCITED | GAP | Total |
|---|---|---|---|---|---|---|
| CRR (Capital Requirements Regulation) | 34 | 57 | 11 | 37 | 14 | 153 |
| PS1/26 (PRA Policy Statement) | 24 | 28 | 7 | 31 | 16 | 106 |

## CRR (Capital Requirements Regulation)

| Art. | Code fns | Pack | Src | Oracle | Tests | Confidence |
|---|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 0 | 1 | GAP |
| 2 | 0 | 0 | 0 | 0 | 1 | GAP |
| 4 | 0 | 0 | 10 | 0 | 4 | UNCITED |
| 6 | 0 | 0 | 8 | 0 | 6 | UNCITED |
| 34 | 0 | 0 | 3 | 0 | 3 | UNCITED |
| 36 | 0 | 0 | 0 | 0 | 3 | GAP |
| 48 | 0 | 0 | 0 | 0 | 1 | GAP |
| 62 | 0 | 0 | 5 | 0 | 10 | UNCITED |
| 92 | 0 | 3 | 17 | 0 | 14 | MEDIUM |
| 99 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 107 | 1 | 0 | 11 | 0 | 9 | MEDIUM |
| 109 | 1 | 0 | 5 | 0 | 1 | MEDIUM |
| 110 | 0 | 1 | 4 | 0 | 6 | MEDIUM |
| 111 | 6 | 10 | 20 | 0 | 35 | MEDIUM |
| 112 | 4 | 3 | 18 | 0 | 32 | MEDIUM |
| 113 | 2 | 2 | 11 | 0 | 10 | MEDIUM |
| 114 | 8 | 6 | 14 | 14 | 27 | HIGH |
| 115 | 5 | 10 | 6 | 3 | 9 | HIGH |
| 116 | 5 | 8 | 7 | 9 | 9 | HIGH |
| 117 | 4 | 5 | 7 | 3 | 17 | HIGH |
| 118 | 3 | 2 | 2 | 1 | 7 | HIGH |
| 119 | 1 | 0 | 1 | 0 | 0 | LOW |
| 120 | 1 | 2 | 13 | 6 | 94 | HIGH |
| 121 | 4 | 2 | 7 | 9 | 16 | HIGH |
| 122 | 3 | 4 | 6 | 11 | 68 | HIGH |
| 123 | 4 | 7 | 14 | 2 | 26 | HIGH |
| 124 | 1 | 2 | 8 | 2 | 11 | HIGH |
| 125 | 1 | 3 | 17 | 2 | 21 | HIGH |
| 126 | 2 | 4 | 11 | 2 | 15 | HIGH |
| 127 | 1 | 4 | 3 | 2 | 7 | HIGH |
| 128 | 0 | 3 | 7 | 0 | 5 | MEDIUM |
| 129 | 3 | 2 | 5 | 2 | 4 | HIGH |
| 131 | 2 | 1 | 5 | 0 | 9 | MEDIUM |
| 132 | 0 | 0 | 1 | 0 | 3 | UNCITED |
| 132A | 0 | 0 | 0 | 0 | 2 | GAP |
| 132B | 0 | 0 | 0 | 0 | 1 | GAP |
| 133 | 2 | 3 | 5 | 2 | 13 | HIGH |
| 134 | 2 | 10 | 3 | 2 | 3 | HIGH |
| 135 | 1 | 0 | 3 | 0 | 0 | LOW |
| 136 | 1 | 0 | 4 | 0 | 0 | LOW |
| 137 | 3 | 2 | 5 | 0 | 9 | MEDIUM |
| 138 | 1 | 0 | 3 | 0 | 1 | MEDIUM |
| 139 | 1 | 1 | 1 | 0 | 0 | LOW |
| 140 | 3 | 0 | 4 | 0 | 5 | MEDIUM |
| 141 | 1 | 0 | 1 | 0 | 0 | LOW |
| 142 | 1 | 0 | 4 | 0 | 5 | MEDIUM |
| 143 | 1 | 0 | 7 | 0 | 8 | MEDIUM |
| 147 | 5 | 5 | 20 | 0 | 22 | MEDIUM |
| 148 | 2 | 0 | 8 | 0 | 5 | MEDIUM |
| 150 | 1 | 0 | 4 | 0 | 5 | MEDIUM |
| 151 | 1 | 0 | 2 | 0 | 4 | MEDIUM |
| 153 | 13 | 11 | 29 | 14 | 67 | HIGH |
| 154 | 4 | 0 | 6 | 4 | 17 | HIGH |
| 155 | 7 | 4 | 10 | 3 | 21 | HIGH |
| 158 | 0 | 4 | 11 | 0 | 16 | MEDIUM |
| 159 | 0 | 0 | 8 | 0 | 10 | UNCITED |
| 160 | 2 | 1 | 10 | 1 | 17 | HIGH |
| 161 | 4 | 2 | 15 | 3 | 37 | HIGH |
| 162 | 5 | 16 | 15 | 2 | 33 | HIGH |
| 163 | 2 | 0 | 3 | 0 | 8 | MEDIUM |
| 164 | 3 | 5 | 7 | 0 | 8 | MEDIUM |
| 165 | 1 | 3 | 2 | 0 | 2 | MEDIUM |
| 166 | 2 | 5 | 7 | 0 | 17 | MEDIUM |
| 169 | 0 | 0 | 0 | 0 | 2 | GAP |
| 169A | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 171 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 178 | 1 | 0 | 3 | 0 | 6 | MEDIUM |
| 180 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 181 | 0 | 1 | 5 | 0 | 3 | MEDIUM |
| 191A | 0 | 0 | 2 | 0 | 3 | UNCITED |
| 192 | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 193 | 1 | 0 | 11 | 1 | 6 | HIGH |
| 194 | 2 | 0 | 1 | 0 | 4 | MEDIUM |
| 195 | 1 | 0 | 7 | 0 | 12 | MEDIUM |
| 197 | 4 | 0 | 7 | 19 | 19 | HIGH |
| 198 | 1 | 0 | 2 | 2 | 2 | HIGH |
| 199 | 1 | 0 | 2 | 0 | 15 | MEDIUM |
| 200 | 0 | 0 | 4 | 0 | 3 | UNCITED |
| 201 | 1 | 0 | 2 | 9 | 4 | HIGH |
| 203 | 0 | 0 | 0 | 0 | 1 | GAP |
| 207 | 1 | 0 | 2 | 0 | 7 | MEDIUM |
| 211 | 1 | 0 | 1 | 0 | 3 | MEDIUM |
| 212 | 0 | 0 | 2 | 0 | 0 | UNCITED |
| 213 | 2 | 1 | 6 | 0 | 15 | MEDIUM |
| 215 | 0 | 0 | 2 | 0 | 2 | UNCITED |
| 216 | 0 | 0 | 0 | 0 | 1 | GAP |
| 217 | 2 | 0 | 1 | 0 | 0 | LOW |
| 218 | 1 | 0 | 2 | 2 | 3 | HIGH |
| 219 | 1 | 0 | 3 | 0 | 4 | MEDIUM |
| 220 | 1 | 0 | 8 | 0 | 11 | MEDIUM |
| 221 | 0 | 0 | 2 | 0 | 1 | UNCITED |
| 222 | 2 | 10 | 5 | 22 | 11 | HIGH |
| 223 | 4 | 0 | 17 | 30 | 29 | HIGH |
| 224 | 4 | 10 | 11 | 33 | 44 | HIGH |
| 226 | 2 | 0 | 4 | 0 | 19 | MEDIUM |
| 227 | 0 | 2 | 3 | 0 | 1 | MEDIUM |
| 228 | 0 | 0 | 1 | 25 | 2 | UNCITED |
| 229 | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 230 | 2 | 6 | 15 | 0 | 25 | MEDIUM |
| 231 | 1 | 0 | 1 | 0 | 0 | LOW |
| 232 | 5 | 2 | 6 | 0 | 2 | MEDIUM |
| 233 | 1 | 2 | 5 | 1 | 14 | HIGH |
| 233A | 0 | 0 | 0 | 0 | 3 | GAP |
| 234 | 1 | 0 | 2 | 0 | 4 | MEDIUM |
| 235 | 10 | 1 | 15 | 7 | 18 | HIGH |
| 236 | 0 | 0 | 0 | 0 | 4 | GAP |
| 237 | 2 | 0 | 4 | 0 | 25 | MEDIUM |
| 238 | 2 | 0 | 3 | 0 | 10 | MEDIUM |
| 239 | 0 | 0 | 2 | 0 | 13 | UNCITED |
| 244 | 1 | 0 | 5 | 0 | 0 | LOW |
| 247 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 259 | 0 | 0 | 2 | 0 | 0 | UNCITED |
| 271 | 1 | 0 | 10 | 0 | 31 | MEDIUM |
| 272 | 0 | 0 | 11 | 0 | 27 | UNCITED |
| 273a | 0 | 0 | 1 | 0 | 3 | UNCITED |
| 274 | 4 | 5 | 20 | 0 | 66 | MEDIUM † |
| 275 | 0 | 0 | 8 | 0 | 45 | UNCITED † |
| 277 | 3 | 0 | 5 | 0 | 28 | MEDIUM |
| 277a | 0 | 6 | 3 | 0 | 24 | MEDIUM † |
| 278 | 1 | 4 | 5 | 0 | 31 | MEDIUM |
| 279 | 7 | 0 | 2 | 0 | 0 | LOW |
| 279a | 3 | 20 | 5 | 0 | 11 | MEDIUM |
| 279b | 0 | 4 | 4 | 0 | 39 | MEDIUM † |
| 279c | 0 | 10 | 4 | 0 | 31 | MEDIUM † |
| 280 | 0 | 24 | 3 | 0 | 25 | MEDIUM |
| 280a | 0 | 0 | 3 | 0 | 13 | UNCITED |
| 280b | 0 | 0 | 1 | 0 | 6 | UNCITED |
| 280c | 0 | 0 | 2 | 0 | 9 | UNCITED |
| 281 | 0 | 0 | 0 | 0 | 2 | GAP |
| 282 | 0 | 0 | 0 | 0 | 2 | GAP |
| 283 | 0 | 0 | 0 | 0 | 1 | GAP |
| 285 | 2 | 12 | 7 | 0 | 19 | MEDIUM † |
| 291 | 1 | 2 | 5 | 0 | 5 | MEDIUM |
| 295 | 0 | 0 | 3 | 0 | 18 | UNCITED |
| 300 | 0 | 0 | 2 | 0 | 1 | UNCITED |
| 301 | 0 | 0 | 2 | 0 | 3 | UNCITED |
| 305 | 0 | 0 | 2 | 0 | 0 | UNCITED |
| 306 | 4 | 4 | 17 | 0 | 15 | MEDIUM |
| 307 | 0 | 0 | 1 | 0 | 2 | UNCITED |
| 308 | 0 | 0 | 7 | 0 | 3 | UNCITED |
| 309 | 0 | 0 | 3 | 0 | 3 | UNCITED |
| 378 | 0 | 16 | 6 | 0 | 6 | MEDIUM |
| 379 | 0 | 4 | 4 | 0 | 2 | MEDIUM |
| 380 | 0 | 0 | 2 | 0 | 2 | UNCITED |
| 382 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 430 | 0 | 1 | 1 | 0 | 1 | MEDIUM |
| 438 | 2 | 0 | 3 | 0 | 2 | MEDIUM |
| 439 | 0 | 0 | 2 | 0 | 3 | UNCITED |
| 444 | 4 | 0 | 7 | 0 | 1 | MEDIUM |
| 452 | 2 | 0 | 4 | 0 | 0 | LOW |
| 453 | 2 | 0 | 3 | 0 | 0 | LOW |
| 501 | 4 | 2 | 17 | 2 | 28 | HIGH |
| 501a | 1 | 0 | 4 | 1 | 6 | HIGH |

## PS1/26 (PRA Policy Statement)

| para. | Code fns | Pack | Src | Oracle | Tests | Confidence |
|---|---|---|---|---|---|---|
| 1 | 13 | 0 | 7 | 0 | 0 | LOW |
| 4 | 4 | 11 | 4 | 0 | 0 | LOW |
| 36 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 62 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 92 | 2 | 4 | 20 | 0 | 31 | MEDIUM |
| 110A | 1 | 1 | 3 | 0 | 3 | MEDIUM |
| 111 | 2 | 2 | 9 | 0 | 12 | MEDIUM |
| 112 | 0 | 0 | 4 | 0 | 2 | UNCITED |
| 113 | 0 | 2 | 1 | 0 | 0 | LOW |
| 114 | 3 | 1 | 10 | 2 | 20 | HIGH |
| 115 | 2 | 0 | 3 | 3 | 5 | HIGH |
| 116 | 2 | 0 | 3 | 2 | 8 | HIGH |
| 117 | 2 | 0 | 4 | 2 | 8 | HIGH |
| 118 | 0 | 0 | 1 | 1 | 5 | UNCITED |
| 120 | 0 | 6 | 13 | 2 | 36 | HIGH |
| 120A | 0 | 0 | 4 | 0 | 3 | UNCITED |
| 121 | 1 | 0 | 5 | 4 | 14 | HIGH |
| 122 | 2 | 7 | 7 | 5 | 42 | HIGH |
| 122A | 0 | 1 | 3 | 0 | 3 | MEDIUM |
| 122B | 0 | 0 | 1 | 0 | 2 | UNCITED |
| 123 | 1 | 4 | 3 | 5 | 15 | HIGH |
| 123A | 1 | 1 | 5 | 0 | 12 | MEDIUM |
| 123B | 1 | 5 | 9 | 0 | 12 | MEDIUM |
| 124 | 2 | 1 | 9 | 0 | 8 | MEDIUM |
| 124A | 0 | 0 | 0 | 0 | 4 | GAP |
| 124C | 0 | 0 | 5 | 0 | 1 | UNCITED |
| 124E | 1 | 2 | 2 | 0 | 2 | MEDIUM |
| 124F | 1 | 4 | 10 | 2 | 24 | HIGH |
| 124G | 0 | 3 | 1 | 2 | 6 | HIGH |
| 124H | 0 | 5 | 6 | 1 | 5 | HIGH |
| 124I | 0 | 4 | 2 | 2 | 3 | HIGH |
| 124J | 0 | 2 | 1 | 0 | 3 | MEDIUM |
| 124K | 0 | 2 | 1 | 2 | 4 | HIGH |
| 124L | 0 | 4 | 3 | 1 | 7 | HIGH |
| 126 | 0 | 0 | 0 | 0 | 2 | GAP |
| 127 | 1 | 5 | 3 | 2 | 7 | HIGH |
| 128 | 1 | 1 | 4 | 1 | 7 | HIGH |
| 129 | 2 | 3 | 5 | 2 | 4 | HIGH |
| 132 | 3 | 0 | 2 | 0 | 2 | MEDIUM |
| 132A | 0 | 0 | 0 | 0 | 1 | GAP |
| 132a | 0 | 0 | 0 | 0 | 3 | GAP |
| 133 | 2 | 4 | 5 | 1 | 14 | HIGH |
| 134 | 0 | 0 | 1 | 1 | 2 | UNCITED |
| 136 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 138 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 139 | 1 | 1 | 6 | 0 | 3 | MEDIUM |
| 140 | 2 | 0 | 3 | 0 | 5 | MEDIUM |
| 147 | 13 | 3 | 15 | 0 | 20 | MEDIUM |
| 147A | 2 | 2 | 15 | 0 | 26 | MEDIUM |
| 147B | 0 | 0 | 2 | 0 | 1 | UNCITED |
| 150 | 0 | 0 | 0 | 0 | 1 | GAP |
| 153 | 1 | 9 | 13 | 10 | 25 | HIGH |
| 154 | 0 | 2 | 1 | 6 | 6 | HIGH |
| 155 | 0 | 0 | 0 | 0 | 3 | GAP |
| 158 | 0 | 3 | 0 | 0 | 3 | MEDIUM |
| 159 | 0 | 0 | 0 | 0 | 1 | GAP |
| 160 | 1 | 1 | 4 | 1 | 15 | HIGH |
| 161 | 2 | 4 | 6 | 4 | 38 | HIGH |
| 162 | 1 | 6 | 7 | 0 | 9 | MEDIUM |
| 163 | 2 | 0 | 2 | 2 | 11 | HIGH |
| 164 | 4 | 1 | 2 | 3 | 4 | HIGH |
| 166 | 2 | 0 | 1 | 0 | 0 | LOW |
| 166C | 0 | 1 | 0 | 0 | 3 | MEDIUM |
| 166D | 0 | 3 | 2 | 0 | 2 | MEDIUM |
| 166E | 0 | 0 | 4 | 0 | 2 | UNCITED |
| 169A | 1 | 1 | 5 | 0 | 3 | MEDIUM |
| 169B | 0 | 0 | 0 | 0 | 1 | GAP |
| 180 | 0 | 0 | 0 | 0 | 2 | GAP |
| 181 | 0 | 0 | 4 | 0 | 2 | UNCITED |
| 191A | 0 | 0 | 4 | 0 | 3 | UNCITED |
| 194 | 0 | 0 | 0 | 0 | 2 | GAP |
| 195 | 0 | 0 | 1 | 0 | 2 | UNCITED |
| 197 | 0 | 0 | 0 | 0 | 5 | GAP |
| 198 | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 199 | 1 | 0 | 2 | 0 | 5 | MEDIUM |
| 200 | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 201 | 1 | 0 | 1 | 0 | 2 | MEDIUM |
| 211 | 1 | 0 | 1 | 0 | 1 | MEDIUM |
| 213 | 1 | 1 | 1 | 0 | 1 | MEDIUM |
| 218 | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 219 | 0 | 0 | 0 | 0 | 1 | GAP |
| 220 | 0 | 0 | 0 | 0 | 2 | GAP |
| 222 | 0 | 0 | 4 | 0 | 5 | UNCITED |
| 223 | 0 | 0 | 4 | 0 | 2 | UNCITED |
| 224 | 0 | 2 | 3 | 0 | 11 | MEDIUM |
| 226 | 0 | 0 | 1 | 0 | 2 | UNCITED |
| 227 | 0 | 0 | 1 | 0 | 3 | UNCITED |
| 228 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 230 | 3 | 2 | 8 | 0 | 18 | MEDIUM |
| 231 | 0 | 0 | 0 | 0 | 1 | GAP |
| 232 | 0 | 0 | 1 | 0 | 1 | UNCITED |
| 233 | 0 | 0 | 1 | 0 | 3 | UNCITED |
| 235 | 3 | 1 | 5 | 0 | 20 | MEDIUM |
| 236 | 0 | 0 | 1 | 0 | 7 | UNCITED |
| 237 | 1 | 0 | 1 | 0 | 9 | MEDIUM |
| 238 | 0 | 0 | 0 | 0 | 2 | GAP |
| 239 | 0 | 0 | 1 | 0 | 4 | UNCITED |
| 261 | 0 | 0 | 2 | 0 | 0 | UNCITED |
| 271 | 0 | 0 | 0 | 0 | 1 | GAP |
| 274 | 0 | 2 | 6 | 0 | 7 | MEDIUM |
| 306 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 430 | 0 | 1 | 0 | 0 | 0 | LOW |
| 452 | 0 | 0 | 3 | 0 | 0 | UNCITED |
| 453 | 0 | 0 | 1 | 0 | 0 | UNCITED |
| 456 | 2 | 0 | 3 | 0 | 0 | LOW |
| 501 | 0 | 2 | 0 | 0 | 0 | LOW |

† = watchfire index gap: the article is implemented but its CRR number is absent from watchfire's bundled index, so `@cites` cannot be applied. See the section below.

## Named in source but uncited (UNCITED)

These articles are named in `src/rwa_calc/` production source but carry no `@cites` annotation and no pack value, so no machine-verifiable citation links them. Being named in source is a **weaker implementation signal than `@cites`**: most rows are genuinely implemented code, but a docstring `References:` mention can promote a context-only article here (e.g. a governance requirement the calculator does not compute). Treat a row as implemented only after reading the named modules. They are **not** coverage gaps. Two causes dominate: (1) the SA-CCR / CCR domain (marked †), implemented in `engine/ccr/` but uncitable because watchfire's bundled index omits those CRR articles — each module documents this with a `does not yet contain Art. N` note; (2) a rule that survives from CRR into PS1/26, cited as `PS1/26 Art. N` by the oracle/tests while the packs and code annotate it under `CRR Art. N` — the *Anchored as* column names that citable twin. Rows are ordered by oracle then test weight.

| Article | Src | Oracle | Tests | Watchfire gap | Anchored as |
|---|---|---|---|---|---|
| CRR 228 | 1 | 25 | 2 | — | — |
| PS1/26 118 | 1 | 1 | 5 | — | CRR Art. 118 |
| PS1/26 134 | 1 | 1 | 2 | — | CRR Art. 134 |
| CRR 275 | 8 | 0 | 45 | yes | — |
| CRR 272 | 11 | 0 | 27 | — | — |
| CRR 295 | 3 | 0 | 18 | — | — |
| CRR 239 | 2 | 0 | 13 | — | — |
| CRR 280a | 3 | 0 | 13 | — | — |
| CRR 62 | 5 | 0 | 10 | — | — |
| CRR 159 | 8 | 0 | 10 | — | — |
| CRR 280c | 2 | 0 | 9 | — | — |
| PS1/26 236 | 1 | 0 | 7 | — | — |
| CRR 6 | 8 | 0 | 6 | — | — |
| CRR 280b | 1 | 0 | 6 | — | — |
| PS1/26 222 | 4 | 0 | 5 | — | CRR Art. 222 |
| CRR 4 | 10 | 0 | 4 | — | PS1/26 para. 4 |
| PS1/26 239 | 1 | 0 | 4 | — | — |
| CRR 34 | 3 | 0 | 3 | — | — |
| PS1/26 120A | 4 | 0 | 3 | — | — |
| CRR 132 | 1 | 0 | 3 | — | PS1/26 para. 132 |
| CRR 191A | 2 | 0 | 3 | — | — |
| PS1/26 191A | 4 | 0 | 3 | — | — |
| CRR 200 | 4 | 0 | 3 | — | — |
| PS1/26 227 | 1 | 0 | 3 | — | CRR Art. 227 |
| PS1/26 233 | 1 | 0 | 3 | — | CRR Art. 233 |
| CRR 273a | 1 | 0 | 3 | — | — |
| CRR 301 | 2 | 0 | 3 | — | — |
| CRR 308 | 7 | 0 | 3 | — | — |
| CRR 309 | 3 | 0 | 3 | — | — |
| CRR 439 | 2 | 0 | 3 | — | — |
| PS1/26 112 | 4 | 0 | 2 | — | CRR Art. 112 |
| PS1/26 122B | 1 | 0 | 2 | — | — |
| PS1/26 166E | 4 | 0 | 2 | — | — |
| PS1/26 181 | 4 | 0 | 2 | — | CRR Art. 181 |
| PS1/26 195 | 1 | 0 | 2 | — | CRR Art. 195 |
| CRR 215 | 2 | 0 | 2 | — | — |
| PS1/26 223 | 4 | 0 | 2 | — | CRR Art. 223 |
| PS1/26 226 | 1 | 0 | 2 | — | CRR Art. 226 |
| CRR 307 | 1 | 0 | 2 | — | — |
| CRR 380 | 2 | 0 | 2 | — | — |
| PS1/26 124C | 5 | 0 | 1 | — | — |
| PS1/26 147B | 2 | 0 | 1 | — | — |
| CRR 169A | 1 | 0 | 1 | — | PS1/26 para. 169A |
| CRR 192 | 1 | 0 | 1 | — | — |
| PS1/26 198 | 1 | 0 | 1 | — | CRR Art. 198 |
| PS1/26 200 | 1 | 0 | 1 | — | — |
| PS1/26 218 | 1 | 0 | 1 | — | CRR Art. 218 |
| CRR 221 | 2 | 0 | 1 | — | — |
| CRR 229 | 1 | 0 | 1 | — | — |
| PS1/26 232 | 1 | 0 | 1 | — | CRR Art. 232 |
| CRR 300 | 2 | 0 | 1 | — | — |
| PS1/26 36 | 1 | 0 | 0 | — | — |
| PS1/26 62 | 1 | 0 | 0 | — | — |
| CRR 99 | 1 | 0 | 0 | — | — |
| PS1/26 136 | 1 | 0 | 0 | — | CRR Art. 136 |
| PS1/26 138 | 1 | 0 | 0 | — | CRR Art. 138 |
| CRR 171 | 1 | 0 | 0 | — | — |
| CRR 180 | 1 | 0 | 0 | — | — |
| CRR 212 | 2 | 0 | 0 | — | — |
| PS1/26 228 | 1 | 0 | 0 | — | — |
| CRR 247 | 1 | 0 | 0 | — | — |
| CRR 259 | 2 | 0 | 0 | — | — |
| PS1/26 261 | 2 | 0 | 0 | — | — |
| CRR 305 | 2 | 0 | 0 | — | — |
| PS1/26 306 | 1 | 0 | 0 | — | CRR Art. 306 |
| CRR 382 | 1 | 0 | 0 | — | — |
| PS1/26 452 | 3 | 0 | 0 | — | CRR Art. 452 |
| PS1/26 453 | 1 | 0 | 0 | — | CRR Art. 453 |

## Gaps — cited but not implemented

The actionable list: articles referenced **only** by the oracle and/or a (heuristic) test, with no `@cites` annotation, no pack value, and no mention anywhere in production source. Implemented-but-unannotated articles are **not** here — they are in the UNCITED section above. Many rows below are definitional / scope / own-funds articles that a test docstring names in passing and that this calculator does not compute; the *Anchored as* column flags the rare case where the same number is citable under the other instrument. Rows are ordered by oracle then test weight.

| Article | Oracle cases | Test refs | Anchored as |
|---|---|---|---|
| PS1/26 197 | 0 | 5 | CRR Art. 197 |
| PS1/26 124A | 0 | 4 | — |
| CRR 236 | 0 | 4 | — |
| CRR 36 | 0 | 3 | — |
| PS1/26 132a | 0 | 3 | — |
| PS1/26 155 | 0 | 3 | CRR Art. 155 |
| CRR 233A | 0 | 3 | — |
| PS1/26 126 | 0 | 2 | CRR Art. 126 |
| CRR 132A | 0 | 2 | — |
| CRR 169 | 0 | 2 | — |
| PS1/26 180 | 0 | 2 | — |
| PS1/26 194 | 0 | 2 | CRR Art. 194 |
| PS1/26 220 | 0 | 2 | CRR Art. 220 |
| PS1/26 238 | 0 | 2 | CRR Art. 238 |
| CRR 281 | 0 | 2 | — |
| CRR 282 | 0 | 2 | — |
| CRR 1 | 0 | 1 | PS1/26 para. 1 |
| CRR 2 | 0 | 1 | — |
| CRR 48 | 0 | 1 | — |
| PS1/26 132A | 0 | 1 | — |
| CRR 132B | 0 | 1 | — |
| PS1/26 150 | 0 | 1 | CRR Art. 150 |
| PS1/26 159 | 0 | 1 | — |
| PS1/26 169B | 0 | 1 | — |
| CRR 203 | 0 | 1 | — |
| CRR 216 | 0 | 1 | — |
| PS1/26 219 | 0 | 1 | CRR Art. 219 |
| PS1/26 231 | 0 | 1 | CRR Art. 231 |
| PS1/26 271 | 0 | 1 | CRR Art. 271 |
| CRR 283 | 0 | 1 | — |

## Generator warnings

Citation strings that could not be parsed into a `(framework, article)` pair and were dropped from the join. Fix the source or extend the parser.

- `PS1/26`
