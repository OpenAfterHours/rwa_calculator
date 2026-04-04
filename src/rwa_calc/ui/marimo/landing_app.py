"""
RWA Calculator Landing Page.

Dashboard hub page for the interactive UI, providing navigation
to all calculator apps and the editable workbench.

Usage:
    Served at the root path (/) by the multi-app server.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="full", css_file="shared/theme.css", html_head_file="shared/head.html")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    import sys as _sys
    from pathlib import Path as _P

    _shared = str(_P(__file__).parent / "shared")
    if _shared not in _sys.path:
        _sys.path.insert(0, _shared)
    from sidebar import create_sidebar as _create_sidebar

    _create_sidebar(mo)
    return


@app.cell
def _(mo):
    mo.Html(
        """
<style>
/* -------------------------------------------------------
   Scoped landing page styles
   ------------------------------------------------------- */
.rwa-landing {
  position: relative;
  width: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
    Roboto, Helvetica, Arial, sans-serif;
  color: var(--foreground, #1a1a2e);
}

/* --- Formula background -------------------------------- */
.rwa-landing .formula-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  user-select: none;
  overflow: hidden;
  z-index: 0;
}

.rwa-landing .formula {
  position: absolute;
  font-family: "JetBrains Mono", "Roboto Mono",
    "Fira Code", monospace;
  white-space: nowrap;
  line-height: 1;
  opacity: 0.06;
  color: var(--foreground, #000);
}

@media (prefers-color-scheme: dark) {
  .rwa-landing .formula { opacity: 0.10; }
}

.rwa-landing .f1  { top:8%;  left:2%;  font-size:0.9rem;
  transform:rotate(-2deg); }
.rwa-landing .f2  { top:45%; left:55%; font-size:1.2rem;
  transform:rotate(1deg); }
.rwa-landing .f3  { top:72%; left:1%;  font-size:0.75rem;
  transform:rotate(-1deg); }
.rwa-landing .f4  { top:24%; left:40%; font-size:0.85rem;
  transform:rotate(2deg); }
.rwa-landing .f5  { top:5%;  left:62%; font-size:0.8rem;
  transform:rotate(-3deg); }
.rwa-landing .f6  { top:85%; left:35%; font-size:0.95rem;
  transform:rotate(1.5deg); }
.rwa-landing .f7  { top:38%; left:6%;  font-size:1.0rem;
  transform:rotate(-0.5deg); }
.rwa-landing .f8  { top:3%;  left:30%; font-size:0.7rem;
  transform:rotate(2.5deg); }
.rwa-landing .f9  { top:58%; left:75%; font-size:0.75rem;
  transform:rotate(-1.5deg); }
.rwa-landing .f10 { top:18%; left:80%; font-size:0.8rem;
  transform:rotate(0.5deg); }
.rwa-landing .f11 { top:78%; left:70%; font-size:1.2rem;
  transform:rotate(-2.5deg); }
.rwa-landing .f12 { top:34%; left:52%; font-size:0.7rem;
  transform:rotate(1deg); }

/* --- Hero ---------------------------------------------- */
.rwa-landing .hero {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 4rem 1.5rem 2rem;
}

.rwa-landing .hero-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.rwa-landing .hero h1 {
  font-size: 2.4rem;
  font-weight: 700;
  margin: 0 0 0.75rem;
  color: var(--foreground, #1a1a2e);
}

.rwa-landing .hero .tagline {
  font-size: 1.15rem;
  line-height: 1.6;
  opacity: 0.65;
  max-width: 600px;
  margin: 0 0 1rem;
}

.rwa-landing .hero .version-badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 600;
  background: rgba(255, 145, 0, 0.12);
  color: #ff9100;
  margin-bottom: 2rem;
}

/* --- App cards grid ------------------------------------ */
.rwa-landing .cards {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1.25rem;
  max-width: 960px;
  margin: 0 auto;
  padding: 0 1.5rem 2rem;
}

.rwa-landing .card {
  display: flex;
  flex-direction: column;
  padding: 1.75rem;
  border-radius: 12px;
  border: 1px solid var(--border, rgba(0,0,0,0.08));
  background: var(--card, #fff);
  text-decoration: none;
  color: var(--card-foreground, inherit);
  transition: border-color 0.2s, box-shadow 0.2s,
    transform 0.15s;
}

.rwa-landing .card:hover {
  border-color: #ff9100;
  box-shadow: 0 4px 20px rgba(255, 145, 0, 0.12);
  transform: translateY(-2px);
}

.rwa-landing .card .card-icon {
  font-size: 2rem;
  margin-bottom: 0.75rem;
}

.rwa-landing .card h3 {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 0.5rem;
}

.rwa-landing .card p {
  font-size: 0.9rem;
  opacity: 0.7;
  margin: 0;
  line-height: 1.5;
}

.rwa-landing .card .card-arrow {
  margin-top: auto;
  padding-top: 1rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: #ff9100;
}

/* --- Workbench banner ---------------------------------- */
.rwa-landing .workbench {
  position: relative;
  z-index: 1;
  max-width: 960px;
  margin: 0.5rem auto 3rem;
  padding: 0 1.5rem;
}

.rwa-landing .workbench a {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.75rem;
  border-radius: 12px;
  border: 1px dashed var(--border, rgba(0,0,0,0.12));
  text-decoration: none;
  color: inherit;
  transition: border-color 0.2s, background 0.2s;
}

.rwa-landing .workbench a:hover {
  border-color: #ff9100;
  background: rgba(255, 145, 0, 0.04);
}

@media (prefers-color-scheme: dark) {
  .rwa-landing .workbench a:hover {
    background: rgba(255, 145, 0, 0.06);
  }
}

.rwa-landing .workbench .wb-text {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.rwa-landing .workbench .wb-text strong {
  font-size: 1rem;
}

.rwa-landing .workbench .wb-text span {
  font-size: 0.85rem;
  opacity: 0.6;
}

.rwa-landing .workbench .wb-arrow {
  font-size: 1.2rem;
  color: #ff9100;
  font-weight: 600;
}

/* --- Footer -------------------------------------------- */
.rwa-landing .landing-footer {
  position: relative;
  z-index: 1;
  text-align: center;
  padding: 1rem 1.5rem 2rem;
  font-size: 0.8rem;
  opacity: 0.45;
}

/* --- Responsive ---------------------------------------- */
@media (max-width: 640px) {
  .rwa-landing .hero h1 { font-size: 1.8rem; }
  .rwa-landing .hero .tagline { font-size: 1rem; }
  .rwa-landing .cards {
    grid-template-columns: 1fr;
  }
  .rwa-landing .f1,
  .rwa-landing .f3,
  .rwa-landing .f5 { display: none; }
}
</style>

<div class="rwa-landing">
  <!-- Formula background -->
  <div class="formula-bg" aria-hidden="true">
    <span class="formula f1">\
K = LGD \u00d7 \u03a6[\u221a(1\u2212R)\u00b9 \u00d7 \
\u03a6\u00b9(PD) + \u221a(R/(1\u2212R)) \u00d7 \
\u03a6\u00b9(0.999)] \u2212 PD \u00d7 LGD</span>
    <span class="formula f2">\
RWA = K \u00d7 12.5 \u00d7 EAD</span>
    <span class="formula f3">\
R = 0.12 \u00d7 (1 \u2212 e\u207b\u2075\u2070\u00b7\
\u1d3e\u1d30) / (1 \u2212 e\u207b\u2075\u2070) + 0.24 \
\u00d7 [1 \u2212 (1 \u2212 e\u207b\u2075\u2070\u00b7\
\u1d3e\u1d30) / (1 \u2212 e\u207b\u2075\u2070)]</span>
    <span class="formula f4">\
b = (0.11852 \u2212 0.05478 \u00d7 ln(PD))\u00b2</span>
    <span class="formula f5">\
MA = (1 + (M \u2212 2.5) \u00d7 b) / (1 \u2212 1.5 \
\u00d7 b)</span>
    <span class="formula f6">\
\u03a6(x) = \u00bd[1 + erf(x/\u221a2)]</span>
    <span class="formula f7">\
EL = PD \u00d7 LGD</span>
    <span class="formula f8">\
RW = K \u00d7 12.5 \u00d7 MA</span>
    <span class="formula f9">\
CCF \u00d7 Off-Balance = EAD</span>
    <span class="formula f10">\
SA: RWA = EAD \u00d7 RW%</span>
    <span class="formula f11">\
\u03a6\u207b\u00b9(PD)</span>
    <span class="formula f12">\
N[(1\u2212R)\u207b\u2070\u00b7\u2075 \u00d7 G(PD)]</span>
  </div>

  <!-- Hero -->
  <div class="hero">
    <div class="hero-icon">\U0001f3e6</div>
    <h1>RWA Calculator</h1>
    <p class="tagline">
      High-performance Risk-Weighted Assets calculation
      for Basel&nbsp;3.1 and CRR frameworks
    </p>
    <span class="version-badge">PRA PS1/26 Compliant</span>
  </div>

  <!-- App cards -->
  <div class="cards">
    <a class="card" href="/calculator">
      <div class="card-icon">\U0001f9ee</div>
      <h3>Calculator</h3>
      <p>
        Run RWA calculations with Standardised and IRB
        approaches. Configure framework, upload data,
        and compute results.
      </p>
      <div class="card-arrow">Open \u2192</div>
    </a>

    <a class="card" href="/results">
      <div class="card-icon">\U0001f4ca</div>
      <h3>Results Explorer</h3>
      <p>
        Analyse, filter, and drill down into calculation
        results. Export to Excel or Parquet for further
        analysis.
      </p>
      <div class="card-arrow">Open \u2192</div>
    </a>

    <a class="card" href="/comparison">
      <div class="card-icon">\u2696\ufe0f</div>
      <h3>Impact Analysis</h3>
      <p>
        Compare CRR vs Basel&nbsp;3.1 frameworks
        side-by-side. Waterfall charts, exposure-level
        deltas, and impact summaries.
      </p>
      <div class="card-arrow">Open \u2192</div>
    </a>

    <a class="card" href="https://openafterhours.github.io/rwa_calculator/" target="_blank">
      <div class="card-icon">\U0001f4d6</div>
      <h3>Documentation</h3>
      <p>
        Regulatory reference, risk weight tables,
        IRB parameters, and framework guides
        on the documentation site.
      </p>
      <div class="card-arrow">View Docs \u2197</div>
    </a>
  </div>

  <!-- Workbench -->
  <div class="workbench">
    <a href="/workbench">
      <div class="wb-text">
        <strong>\U0001f4bb Workbench</strong>
        <span>
          Open editable Python notebooks for custom
          analysis and ad-hoc calculations
        </span>
      </div>
      <div class="wb-arrow">\u2192</div>
    </a>
  </div>

  <!-- Footer -->
  <div class="landing-footer">
    UK Credit Risk RWA Calculator &bull; Basel 3.1 &amp;
    CRR &bull; Polars-powered
  </div>
</div>
"""
    )


if __name__ == "__main__":
    app.run()
