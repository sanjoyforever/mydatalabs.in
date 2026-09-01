# MyDataLabs — Geopolitical Risk & Quantitative Intelligence Indices

[![Flask](https://img.shields.io/badge/Framework-Flask_3.0-blue?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![Apache ECharts](https://img.shields.io/badge/Charts-Apache_ECharts_5.5-cyan?style=flat-square&logo=apache)](https://echarts.apache.org/)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel_Serverless-black?style=flat-square&logo=vercel)](https://vercel.com/)
[![Data licence](https://img.shields.io/badge/Data-CC_BY_4.0-green?style=flat-square)](https://creativecommons.org/licenses/by/4.0/)

**MyDataLabs** publishes composite indices for geopolitical stress, energy security, maritime chokepoints, and commercial aviation operations.
* **Tagline**: *"Quantifying the Unquantifiable"*
* **Flagship Indices**:
  * **Hormuz Crisis Index (HMX-INDEX)** &mdash; scores maritime security and energy supply in the Strait of Hormuz against a 100.0 calm baseline.
  * **Airline Pressure Index (API-INDEX)** &mdash; weekly composite score and **7-Region Stress Contribution Analysis** across operational fleet groundings, crack spreads, and geopolitical airspace detours.
  * **Lok Sabha Projection Engine (LS-PROJ)** &mdash; daily opinion tracker and seat projection model for Indian parliamentary elections.
  * **U.S. Sovereign Solvency Index (USS-INDEX)** &mdash; 80-year annual composite (1945&ndash;present) of federal debt, interest burden, primary deficit, productivity and *r*&nbsp;&minus;&nbsp;*g*, with debt dynamics projected as a scenario band rather than a single date.
  * **Hard-Metric Democracy Index (HMDI)** &mdash; ten published counts and rates scored across the top 30 economies for every year since 2000. No expert survey anywhere in it, and the page says plainly what that costs.

The site publishes its full methodology, component weights and caps, refresh cadence and known limitations. The figures are shown on the pages; the underlying datasets are not distributed, and the site exposes no data API.

---

## Data honesty notes

Three things that matter more than any feature in this repo:

1. **The vessel incident log is compiled separately from the index.**
   `app/data/vessel_attacks.json` holds 56 records shown on the dashboard. It contributes
   nothing to the composite score. Vessel names are
   placeholder identifiers (`M/T Vessel-NNN`) rather than IMO-registered names, and the
   per-row `source` field survives on only three rows.

2. **Three of seven components (35% of index weight) are keyed by hand.** War-risk insurance,
   tanker freight and Cape reroutes have no free API. Their current figures live in
   `app/data/hormuz_manual.json`, and each publishes its own `as_of` date, source and confidence
   in the UI. Ship traffic joined the automatic side in 2026-07 (IMF PortWatch); its
   hand-entered figure is retained only as a fallback for feed outages.

3. **Two weekly series are reconstructed, not observed.** For ship traffic and war-risk insurance,
   the weeks before the 2026-07-26 revision were re-anchored from a previously published series
   rather than measured. Flagged `reconstructed_series` in the stored history — now driven by a
   `history_reconstructed` field in the feeder file, so establishing a real series retires the
   caveat with a one-field edit instead of a code change.

---

## Composite index maths

$$\text{Index Score} = 100.0 + \sum \Big[ \text{Weight}_i \times \text{StressScore}(\text{Current}_i, \text{Baseline}_i, \text{Cap}_i) \Big]$$

### 1. Hormuz Crisis Index (HMX-INDEX)

| Component | Weight | Baseline | Cap | Source | Cadence |
| :--- | :---: | :---: | :---: | :--- | :--- |
| Brent Crude | 30% | $64.77 / bbl | +55% | Yahoo Finance (`BZ=F`) | Daily, automatic |
| Hormuz Transits (all commercial vessels) | 15% | 616 transits / wk | −90% (inverted) | IMF PortWatch | Weekly, manual |
| War-Risk Insurance (per transit) | 15% | 0.25% hull value | +3900% | Marsh / market brokers | Weekly, manual |
| Tanker Freight (BDTI) | 15% | 900 index points | +75% | Baltic Exchange | Weekly, manual |
| TTF European Gas | 10% | 34.11 EUR / MWh | +95% | Yahoo Finance (`TTF=F`) | Daily, automatic |
| VIX Volatility Index | 10% | 16.05 | +200% | Yahoo Finance (`^VIX`) | Daily, automatic |
| Cape Reroutes | 5% | 8.0% of traffic | +250% | AIS / Vortexa | Weekly, manual |

### 2. Airline Pressure Index (API-INDEX)

| Component | Weight | Baseline | Cap | Source | Cadence |
| :--- | :---: | :---: | :---: | :--- | :--- |
| Jet Fuel Crack Spread | 25% | $15.00 / bbl | $45.00 / bbl | Yahoo Finance (`HO=F` vs `BZ=F`) / EIA | Daily, automatic |
| Fleet Grounding Ratio | 20% | 5.0% active fleet | 18.0% active fleet | OpenSky Network / Fleets | Weekly, manual |
| ATFM En-Route Delays | 15% | 0.80 min / flt | 3.50 min / flt | Eurocontrol / FAA OPSNET | Weekly, manual |
| Geopolitical Detour Extension | 15% | 4.0% route length | 18.0% route length | Flightradar24 / FIR Notices | Weekly, manual |
| US Airline Equity Stress | 10% | 0.0% dislocation | 60.0% drawdown | Yahoo Finance (NYSE JETS vs S&P 500) | Daily, automatic |
| Refinery Capacity Utilization | 10% | 92.0% utilization | 75.0% utilization | EIA Weekly Petroleum Status | Weekly, automatic |
| SAF Blend Cost Overhead | 5% | $0.00 / bbl | $8.00 / bbl | Argus / Platts SAF Mandates | Monthly, manual |

### 3. U.S. Sovereign Solvency Index (USS-INDEX)

Annual, 1945&ndash;present. Every input is derived from published FRED series by
`scripts/build_solvency_history.py` &mdash; nothing is hand-keyed or estimated.
Unlike the two weekly indices, each component is scored **linearly between a fixed
baseline and a fixed crisis threshold** rather than against a percentage cap, which
lets one formula handle both directions (falling productivity is the stress direction).

| Component | Block | Weight | Baseline (0 stress) | Crisis (100 stress) | FRED series |
| :--- | :--- | :---: | :---: | :---: | :--- |
| Federal Debt Held by the Public | Fiscal | 18% | 35.0% GDP | 150.0% GDP | `FYPUGDA188S` |
| Net Interest / Federal Receipts | Fiscal | 17% | 8.0% | 30.0% | `FYOINT`, `FYFR` |
| Primary Deficit (ex-interest) | Fiscal | 15% | 0.0% GDP | 8.0% GDP | `FYFSD`, `FYOINT`, `GDPA` |
| Labour Productivity Growth (10y) | Growth | 15% | 2.1% CAGR | 0.0% CAGR | `OPHNFB` |
| Real GDP per Capita Growth (10y) | Growth | 15% | 2.2% CAGR | 0.0% CAGR | `A939RX0Q048SBEA` |
| CPI-U Inflation | Monetary | 10% | 2.0% YoY | 10.0% YoY | `CPIAUCNS` |
| Borrowing Cost less Growth (*r*&nbsp;&minus;&nbsp;*g*) | Monetary | 10% | &minus;1.0pp | +3.0pp | derived |

Baselines are anchored on the **measured 1960&ndash;2000 United States**, not chosen by
eye — the debt, primary-deficit, productivity, per-capita and *r*&nbsp;&minus;&nbsp;*g*
baselines are that period's actual means, and the interest-burden baseline is the
1950&ndash;79 mean (the 1960&ndash;2000 figure is inflated by the Volcker era). Only the
inflation baseline is normative (the FOMC's 2% target). As a standing check on the
calibration, FY1965 &mdash; the post-war low &mdash; scores **100.4**, and a test asserts
it stays near 100.

Debt dynamics are projected with $d_t = d_{t-1}(1+r_t)/(1+g_t) + pb_t$ under three
*r*&nbsp;&minus;&nbsp;*g* assumptions. The result is deliberately reported as a **range**:
net interest reaches 35% of receipts in 2032 (adverse), 2041 (baseline), or never
(favourable). A single headline date would report one guess about *r*&nbsp;&minus;&nbsp;*g*
as though it were a finding.

The dashboard also carries three derived panels built off the same series:

* **Fiscal dynamics quadrant** &mdash; every year placed by the two terms of the debt-dynamics
  equation (*r*&nbsp;&minus;&nbsp;*g* horizontally, primary balance vertically), grouped into six eras.
  This is the standard IMF/ECB sustainability quadrant. The U.S. has spent more years *outgrowing*
  its deficit than in any other configuration and sits there in FY2025 &mdash; a position that holds
  only while *r* stays below *g*.
* **Debt-change decomposition** &mdash; the IMF attribution of each year's change in the debt ratio to
  the snowball term, the primary deficit, and a stock-flow residual. The residual is plotted, not
  absorbed: it averages 0.76pp and is largest in 1946&ndash;47 and 2020&ndash;21. FY2022 is the clearest
  case of the two terms opposing &mdash; a 3.5% primary deficit more than cancelled by a &minus;6.6pp
  snowball as inflation eroded the stock, so the ratio fell.
* **Reserve-currency displacement simulator** &mdash; moves reserve share off the dollar and re-runs the
  debt-dynamics recursion live in the browser. The modelled channel is the Treasury convenience yield
  (Warnock &amp; Warnock 2009 ~80bp; Krishnamurthy &amp; Vissing-Jorgensen 2012 ~73bp), defaulting to
  ~2.4bp of added borrowing cost per percentage point of share lost &mdash; exposed as a slider, because
  it is an assumption rather than a measurement. Dollar depreciation, seigniorage and disorderly
  repricing are **not** modelled and are named as such on the page. A test asserts the browser
  implementation reproduces `simulate_reserve_shift()` exactly.

#### Presidential comparison

The dashboard publishes a per-administration decomposition, with both corrections
**estimated from the series rather than assigned**:

| Correction | How it is obtained | Fit |
| :--- | :--- | :--- |
| Cyclical | OLS of the index's annual change on the annual change in the CBO output gap | n=76, R&sup2;=0.47, t=&minus;8.1 |
| Mean reversion | OLS of each term's cyclically adjusted change on the index level it inherited | n=14, R&sup2;=0.25 |

What remains is the **structural residual**. Correcting matters: raw change is
explained by the inherited level alone at R&sup2;=0.42, and residualising removes that
dependence entirely, which moves Eisenhower and Nixon eight places each and Obama nine
against the uncorrected ranking.

Three things are reported that a league table normally omits:

* **The error bar.** The residual standard deviation is **±11.3 points**, a quarter of
  the entire range of scores. **10 of the 14 administrations fall inside it** and are not
  distinguishable from each other or from zero; only Trump (+17.3), Bush 43 (+14.2),
  Eisenhower (&minus;14.1) and Truman (&minus;22.6) clear it.
* **No party signal.** Mean residual is &minus;1.8 for Democratic terms and +1.8 for
  Republican &mdash; a 3.6-point gap against an 11.3-point error bar. A test fails if that
  gap ever exceeds the noise, since the page asserts it does not.
* **Rank range across four weighting schemes** (balanced, fiscal-heavy, growth-heavy,
  equal), so weighting sensitivity is visible rather than hidden by a single ordering.

#### Wars, debt by administration, and items enacted since the data ends

Three further panels, added because the index alone does not answer the questions people
actually ask of it:

* **Wars and the defence burden.** National defence as a share of GDP (FRED
  `A824RE1A156NBEA`, 1929&ndash;) with conflict periods shaded. No "cost of the war" is derived
  from aggregate outlays: applying the standard three-years-prior baseline gives 0.2pp of GDP
  for Vietnam (1962&ndash;64 defence was already 10.9% of GDP) and zero for the Gulf War (fought
  during the drawdown) &mdash; arithmetically correct, analytically useless, and the same
  unidentified-counterfactual problem the presidential panel declines to fake. So the panel
  reports what is measured (the burden, and debt/GDP across each period) and **cites** CRS
  *Costs of Major U.S. Wars* (RS22926) for constant-dollar operation costs, alongside Brown
  University's Costs of War estimate (~$8tn post-9/11 including veterans' care and interest,
  against CRS's $1.1tn for operations alone &mdash; two defensible numbers measuring different
  things). Today's defence burden is **3.7% of GDP, the 4th-lowest of 81 years**, despite a
  budget above $1tn.
* **Debt added by administration**, on three measures &mdash; nominal, constant dollars, and
  change in debt/GDP. They crown three different presidents, which is the reason to show all
  three: prices are ~18&times; their 1945 level, so a nominal ranking mostly sorts by era. A test
  fails if the three ever agree.
* **Enacted since the data ends.** The index stops at the last closed fiscal year, so the
  OBBBA (CBO: **$3.4tn** primary, $4.1tn with interest, $5.5tn if extended) and the 2026 Iran
  conflict (~$30&ndash;40bn) appear in none of the charts. They are listed, sourced, and translated
  into the projection's units rather than folded in &mdash; folding a ten-year score into an
  eighty-year measured series would stop it being a measurement. In cumulative fiscal terms
  **the tax bill is roughly 85&times; the war**: 8.9% of GDP across its window against 0.13% once.

The dashboard closes with an **executive summary** card that states in prose what the
numbers add up to: which administrations can and cannot be separated, why there is no
party signal, what the position means for the rest of the world, and which lever actually
moves the timeline. Every figure it quotes is derived by `executive_summary()` at render
time rather than written into the template &mdash; and its claims are covered by tests, so if
an annual rebuild stops supporting a sentence (the interest burden is no longer a series
high, the party gap exceeds the error bar, tightening the primary deficit stops buying more
time than de-dollarisation costs), the suite fails instead of the page asserting something
untrue.

**No exogenous-shock or baseline-momentum term is subtracted.** Neither has an estimator
on this data; constructions that include them do so as per-president constants, which
makes the ranking an input to the model rather than an output of it. Instead the table
reports each term's share of months in NBER-dated recession and lets the reader weigh it.
Terms follow the **budget-responsibility convention** (a president owns the fiscal years
whose budgets they submitted, so FY2009 with TARP is Bush 43's and Obama starts at FY2010);
the choice is stated because the alternative moves several ranks.

The 80-year series is rebuilt once a year at fiscal-year close:

```bash
python update.py --solvency          # or: python scripts/build_solvency_history.py
```

### 4. Hard-Metric Democracy Index (HMDI)

Annual, 2000&ndash;2024, thirty economies. Every conventional democracy index
&mdash; V-Dem, Freedom House, EIU &mdash; aggregates expert questionnaires. This one
uses only counts, rates and electoral mathematics, so no country is scored on an
opinion about it. **The cost of that discipline is stated on the page rather than
buried:** judicial independence, press pluralism and whether an election was
actually free are the things that matter most, and none of them is a number anyone
publishes, so none of them is here.

| Pillar | Weight | Scored indicators |
| :--- | :---: | :--- |
| Electoral Health & Representation | 20% | Turnout (% of VAP), Gallagher disproportionality, constitutional transfer integrity |
| Power Dispersion & Checks | 20% | Legislative HHI, women's legislative share |
| Economic Equity & Parity | 20% | Income Gini |
| Information & Telemetry Freedom | 20% | Internet disruption person-hours/capita, journalists imprisoned per 10M |
| Due Process & Rule of Law | 20% | Pre-trial detention share, incarceration rate per 100k |

Every indicator is a rate, ratio or per-capita quantity, so India and Norway sit on
one axis and population size drops out. Each is scored linearly between **fixed**
bounds rather than against the sample, so adding a country cannot restate history.

**Aggregation is geometric across pillars, not arithmetic.** An arithmetic mean
makes pillars perfectly substitutable, which let the UAE &mdash; a federal absolute
monarchy with no elected national legislature &mdash; score 61.7 for 2024, four
points *above* the United States, by averaging a legislative-concentration score of
0 against an appointed 50%-female chamber scoring 100. The weighted geometric mean
is the standard fix (it is why the HDI changed in 2010). It barely moves the league
table &mdash; the top twenty shift by at most one place &mdash; while the UAE falls
to 54.6, Saudi Arabia to 31.9 and China to 28.6, the first time any of them reaches
the bottom tier at all.

**Two of the source dataset's twelve indicators were the same indicator twice.**
Effective Number of Parties and the legislative HHI are algebraically identical
(ENP = 10000 / HHI), had been keyed independently, and disagreed with each other by
a median of 6.6%; Gini and Palma summarise one Lorenz curve at &rho;&nbsp;=&nbsp;+0.99.
Both pairs were scoring their construct twice, through two pillars in the ENP case.
HHI and Gini are scored; ENP (derived from HHI) and Palma are published as context.
The full correlation matrix stays on the methodology tab permanently &mdash; the only
reason anyone found those two pairs is that somebody computed it.

**Provenance is first-class.** The panel is not twelve annual series. It is
**1,663 hand-keyed anchor points out of 9,000 country-year-indicator cells (18.5%)**,
with linear interpolation between anchors and flat-carry outside them. That is a
reasonable way to carry sources that do not publish annually &mdash; an election
result exists in election years and not between them &mdash; and it is not
measurement. Every row carries its anchor share, the ranking table shows it, and the
trajectory chart plots panel-wide anchor density beneath the lines so a smooth
trajectory is never mistaken for a stable decade.

`app/data/democracy_anchors.json` is the input of record; the published panel is
generated from it and should never be hand-edited:

```bash
python update.py --democracy         # or: python scripts/build_democracy_history.py
```

---

## Routes

| Path | Purpose |
| :--- | :--- |
| `/` | Landing page, Featured Aviation Intelligence banner, live ticker |
| `/airline-index` | Airline Pressure Index dashboard: trajectory, regional contribution breakdown, interactive simulator |
| `/hormuz-index` | HMX-INDEX dashboard: gauge, trajectory, component matrix, press dispatch |
| `/lok-sabha-index` | Lok Sabha Projection Engine: daily seat forecast + 2019/2024 backtest |
| `/solvency-index` | USS-INDEX dashboard: 80-year trajectory, block decomposition, debt-dynamics scenario band, statutory turning points |
| `/democracy-index` | HMDI dashboard: 30-economy rankings, live pillar reweighting, trajectories against anchor density, per-country indicator drawer, collinearity and saturation diagnostics |
| `/about` | Why a topic is compressed into one number, the construction rules every index shares, and what a single number cannot express |
| `/terms` | Legal disclaimers and use conditions |
| `/methodology` | 301 to `/hormuz-index#methodology`. Kept as a redirect rather than deleted: the URL was indexed and is cited from the event log's source links |
| `/reports/<slug>` | "In development" placeholder for a nav category with no index yet. `noindex`, and deliberately absent from the sitemap |
| `/admin`, `/admin/queue` | Critique moderation queue. Registered **only** when both `SECRET_KEY` and `ADMIN_PASSWORD_HASH` are set — a blueprint that cannot check a password must not be reachable |
| `/sitemap.xml` | Eight indexable pages. `lastmod` per URL comes from the mtime of the file that backs the page (its precomputed artifact, or its template), not from today's date |
| `/robots.txt` | Disallows `/reports/` and `/api/`. `/admin` is deliberately *not* disallowed: it answers `X-Robots-Tag: noindex`, and a path blocked in robots.txt is one a crawler may never fetch and may still list from an inbound link |
| `/llms.txt` | Pointer file for AI answer surfaces: current HMX reading, page index, licence, and the manual-component caveat counted from the component list rather than hardcoded |
| `/favicon.ico` | Multi-resolution site favicon |

There are **no public data endpoints.** The site used to serve
`/api/hormuz-index/data.{json,csv}` and thirteen read endpoints under
`/api/lok-sabha-index/`; all of them were removed so that no dataset is
redistributable. Every figure a dashboard draws is now serialised into the page
that draws it. The only routes left under `/api/` are operational or accept
reader input, and none of them hands out a dataset: `/api/health`,
`/api/cron/update-hormuz`, `/api/hormuz-index/sentiment` (the reader vote
widget), `/api/<report_key>/critique` (GET returns the whitelist of things a
report may be critiqued about; POST queues a submission for moderation) and
`/api/lok-sabha-index/refresh_data` (off unless `ALLOW_WEB_REFRESH` is set).

`tests/test_routes.py::test_no_public_data_endpoints` asserts each removed path
still 404s, so one cannot come back by accident.

---

## Project structure

```
mydatalabs-in/
├── api/index.py               # Vercel serverless WSGI entry point
├── app/
│   ├── data/
│   │   ├── hormuz_history.json     # Weekly series + generated provenance (updater writes)
│   │   ├── hormuz_manual.json      # Current hand-entered figures (humans write)
│   │   ├── vessel_attacks.json     # dashboard incident log (not an index input)
│   │   ├── aviation_history.json   # API-INDEX weekly series
│   │   ├── solvency_history.json   # USS-INDEX annual series (FRED-derived, machine-written)
│   │   ├── democracy_history.json  # HMDI panel, 30 economies × 2000-2024
│   │   ├── democracy_anchors.json  # Per-indicator anchor density (what backs each score)
│   │   ├── vdem_libdem.json        # V-Dem comparator — carried beside HMDI, never an input
│   │   ├── precomputed/            # One JSON per route. See app/precomputed.py
│   │   └── elections/              # CVoter trackers, projections, calibration, catalog
│   ├── elections/             # Lok Sabha Projection Engine
│   │   ├── routes.py          # Page blueprint, mtime-keyed section cache
│   │   └── engine/            # Model: scraper, calibration, seat model, ML suite,
│   │                          #   backtest, insights, events, trend analytics, paths
│   ├── indices/hormuz.py      # Component definitions, fetchers, snapshot assembly
│   ├── indices/aviation.py    # API-INDEX components, regional stress contribution
│   ├── indices/solvency.py    # USS-INDEX: linear baseline→crisis scoring, debt dynamics
│   ├── indices/democracy.py   # HMDI: bounds, pillars, geometric aggregation, diagnostics
│   ├── manual_data.py         # Hand-entered figures: reading, validation, generated notes
│   ├── precomputed.py         # Per-route JSON artifacts. A render never touches the
│   │                          #   network or the database; the updaters pay that cost
│   ├── critiques.py           # Reader critique whitelist, validation, moderation states
│   ├── admin.py               # Moderation queue. Registered only when it can be locked
│   ├── static/
│   │   ├── css/style.css      # Design tokens, dark/light themes, a11y primitives
│   │   ├── css/elections.css  # Projection dashboard, scoped under .elections-dash
│   │   ├── js/theme.js        # Theme toggle, keyboard-accessible nav, clipboard,
│   │   │                      #   and the site-wide GA4 event bindings
│   │   ├── js/charts.js       # ECharts setup, theme-reactive, fallback handling
│   │   ├── js/elections.js    # Chart.js forecast chart, tabs, event overlay
│   │   ├── js/democracy.js    # HMDI table, pillar reweighting, per-country drawer
│   │   ├── js/hero-carousel.js # Home hero rotation
│   │   └── js/vote.js         # HMX-PPI drag-to-vote gauge, anonymous token handling
│   ├── templates/             # base, home, hormuz, aviation, elections, solvency,
│   │   │                      #   democracy, about, terms, methodology, errors
│   │   └── admin/             # Login + moderation queue
│   ├── routes.py              # Routing, snapshot cache, press dispatch derivation,
│   │                          #   sitemap / robots / llms.txt
│   ├── scoring.py             # Generic composite engine (index-agnostic)
│   ├── storage.py             # History persistence with durability reporting
│   ├── db.py                  # Postgres connections + idempotent schema bootstrap
│   ├── votes.py               # HMX-PPI aggregation, dedup and privacy design
│   └── __init__.py            # App factory, security headers, static caching,
│                              #   GA4 + Clarity ids injected into every template
├── scripts/
│   ├── build_assets.py            # Regenerate icons + 1200x630 OG card from logo.png
│   ├── build_solvency_history.py  # USS-INDEX series from FRED (nothing hand-keyed)
│   ├── build_democracy_history.py # HMDI panel + anchor density
│   ├── build_vdem_reference.py    # V-Dem comparator extract
│   ├── populate_aviation_history.py # API-INDEX backfill
│   ├── refresh_sentiment_artifact.py # Rebuild the HMX-PPI precomputed block
│   ├── restate_2026_07_26.py      # Revision artifact: units/cap fix + full recompute
│   ├── update_hormuz.py           # Wrapper around update_data.py
│   ├── update_elections.py        # Operational CVoter refresh (schedule this one)
│   └── elections_pipeline.py      # Full pipeline: fetch → calibrate → backtest → plot
├── tests/                     # scoring, routes, manual data, aviation, solvency,
│                              #   democracy, critiques
├── update_data.py             # Weekly updater
├── push_to_prod.py            # Recompute, validate, commit and push in one step
├── requirements-pipeline.txt  # Offline-only deps (matplotlib, selenium fallback)
├── vercel.json                # Rewrites, cache/security headers, cron schedule
└── app.py                     # Local dev entrypoint
```

---

## Local development

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python app.py                   # http://127.0.0.1:5000
python -m pytest tests/ -q      # 291 tests: scoring, routes, manual data,
                                # aviation, solvency, democracy, critiques
```

### Weekly data update

Edit the three hand-entered figures in `app/data/hormuz_manual.json`. Only four fields move:

```jsonc
"war_risk": {
  "value":  8.2,             // the figure, in this block's "unit"
  "as_of":  "2026-08-17",    // when it was OBSERVED — not when you typed it
  "source": "Marsh",         // published as provenance
  "note":   "low end of the quoted range"
}
```

Leave `as_of` alone if the figure has not changed: the component then shows as STALE, which is
true, rather than being restamped as fresh. History needs no maintenance here — the updater appends
each week's values to `weeks[]` in `hormuz_history.json` on every run.

```bash
# 1. Check the file before doing anything with it:
python update_data.py --check-manual

# 2. Recompute, commit + push. Validation runs first; malformed rows abort the
#    run, overdue ones only warn and publish as STALE:
python update_data.py

# Recompute and persist locally without touching git:
python update_data.py --local

# Preview without writing anything:
python update_data.py --dry-run
```

The updater reports which components are stale, whether the snapshot is degraded, and — importantly —
whether the write actually landed anywhere durable.

The provenance stored alongside the series (`series_source_notes`, `reconstructed_series`) is
**generated on every run** from the feeder file and the snapshot. Do not hand-edit it in
`hormuz_history.json`; it will be overwritten. It used to be prose typed in by hand, which meant it
asserted a "latest observation" from 2026-07-19 for a month after that stopped being true.

By default (no flag) it also commits `app/data/hormuz_history.json` and `vessel_attacks.json` and
pushes to `origin/main` — that push is what triggers the Vercel deployment, since Vercel's own
filesystem is read-only outside `/tmp` and cannot persist the update itself. This is the mode the
scheduled cron job runs in. `--local` skips the git step for local testing; the commit only ever
touches those two data files, never a broad `git add .`.

### Lok Sabha projection data update

```bash
# Update if CVoter has published new survey days; refits the model and rebuilds
# every derived file. Safe to run on a timer — it exits without writing when
# there is nothing new.
python scripts/update_elections.py

python scripts/update_elections.py --check    # report freshness, write nothing
python scripts/update_elections.py --force    # refetch + rebuild after a weight change
python scripts/update_elections.py --quiet    # for Task Scheduler / cron
```

The web app needs no restart: its response cache is keyed on the mtimes of
`cvoter_daily_trackers.csv`, `ideal_model_daily_projections.csv` and
`model_calibration.json`, so the next request after an update rebuilds everything.

Refreshing over HTTP (`POST /api/lok-sabha-index/refresh_data`) is disabled unless
`ALLOW_WEB_REFRESH=1`. An anonymous visitor must not be able to make the server
fetch 41 upstream files and rewrite the dataset.

For model work rather than a routine refresh, the full pipeline — calibration
diagnostics, backtest, Monte Carlo, static chart — is:

```bash
pip install -r requirements.txt -r requirements-pipeline.txt
python scripts/elections_pipeline.py              # fetch if new, then full run
python scripts/elections_pipeline.py --no-fetch   # cached CSVs only
python scripts/elections_pipeline.py --optimize   # + tracker/parameter grid search
```

Like the Hormuz updater, this writes to the repo rather than to the deployed
filesystem: Vercel's is read-only outside `/tmp`, so a data refresh reaches
production by being committed and pushed.

### Regenerating image assets

```bash
python scripts/build_assets.py
```

Produces `logo-64.png`, `favicon.png`, `apple-touch-icon.png` and the 1200×630 `og-card.png` from
`logo.png`, and — if `app/static/img/image1.jpg` is present — the home page hero: three responsive
WebP + JPEG derivatives (640/960/1400px, 12:5) cropped and re-encoded down from whatever the source
photo is (the source itself is excluded from the Vercel bundle via `.vercelignore`; only the
derivatives are ever served). Re-run after replacing either source image.

---

## Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SITE_ORIGIN` | `https://mydatalabs.in` | Canonical origin for canonical tags, OG, sitemap, robots, JSON-LD |
| `CRON_SECRET` | *(unset)* | When set, `/api/cron/update-hormuz` requires `Authorization: Bearer <secret>` |
| `HISTORY_DATA_DIR` | *(unset)* | Writable directory for durable history persistence |
| `SNAPSHOT_TTL_SECONDS` | `3600` | How long a computed snapshot is reused before refetching |
| `STATIC_MAX_AGE` | `31536000` | `Cache-Control: max-age` for `/static/*` |
| `DATABASE_URL` | *(unset, falls back to `db`)* | Postgres DSN for community voting. Unset disables the vote block; nothing else on the site depends on it |
| `VOTE_PEPPER` | *(dev placeholder)* | Secret mixed into vote token hashes. **Set this in production** |
| `MIN_VOTES_TO_PUBLISH` | `1` | Ballots required before the perception number is shown |
| `MAX_VOTES_PER_ORIGIN` | `25` | Weekly ballot ceiling per coarse network hash |
| `SECRET_KEY` | *(unset)* | Session signing key. Required — with `ADMIN_PASSWORD_HASH` — before the `/admin` blueprint is registered at all |
| `ADMIN_PASSWORD_HASH` | *(unset)* | Werkzeug password hash for the moderation queue. Unset means `/admin` does not exist, not that it is open |
| `ALLOW_WEB_REFRESH` | *(unset)* | Enables `/api/lok-sabha-index/refresh_data`. Off by default: it is an operational trigger, not a page |
| `CRITIQUE_MIN_BODY` / `CRITIQUE_MAX_BODY` | `40` / `600` | Length bounds on a submitted critique |
| `CRITIQUE_MAX_REMEDY` | `300` | Length bound on the suggested-remedy field |
| `CRITIQUE_MIN_FILL_SECONDS` | `5` | Minimum time-on-form before a submission is accepted (bot filter) |
| `CRITIQUE_MAX_PER_ORIGIN` | `5` | Submission ceiling per coarse network hash |
| `GA_MEASUREMENT_ID` | `G-3376VRHZW8` | GA4 property. Empty string omits the tag entirely |
| `CLARITY_PROJECT_ID` | `y3gm1j4qyn` | Microsoft Clarity project. Empty string omits the tag entirely |
| `LIVE_CACHE_TTL_SECONDS` | `900` | How long a fetched live quote is reused |
| `LIVE_FETCH_TIMEOUT_SECONDS` | `8` | Per-fetch timeout for a live component |
| `SENTIMENT_HISTORY_WEEKS` | `104` | Weeks of HMX-PPI history carried into the page |


---

## Analytics

GA4 and Microsoft Clarity are injected by the app factory into every template
and rendered in `base.html` only when their id is non-empty, so clearing either
variable removes the tag rather than shipping a broken one.

Everything else goes through one wrapper, defined in `base.html` **before** the
GA tag loads:

```js
window.trackEvent = function (eventName, params) {
  if (typeof window.gtag === "function") {
    window.gtag("event", eventName, Object.assign({ page_path: location.pathname }, params || {}));
  }
};
```

The typeof guard is the point. `gtag/js` is loaded `async`, and an ad-blocker
may mean it never loads at all — a large share of this site's audience runs
one. A missed event is the correct outcome there; a `ReferenceError` thrown out
of a click handler is not, because it would take the interaction down with it.
Every call site guards again for the same reason, so no page depends on
analytics having loaded to work.

| Source | Events |
| :--- | :--- |
| `js/theme.js` *(every page)* | `theme_toggle`, `nav_click`, `nav_drawer_open`, `file_download`, `copy_to_clipboard`, `copy_to_clipboard_fallback`, `click` (outbound), `exit_to_cvoter`, `report_tab_switch`, `table_expand`, `cta_click`, `exception` |
| `js/charts.js` *(Hormuz)* | `chart_pan_zoom` |
| `js/vote.js` *(HMX-PPI)* | `ppi_vote_interact`, `ppi_vote_submit`, `ppi_vote_withdraw`, `ppi_vote_error` |
| `js/elections.js` | `report_tab_switch`, `chart_series_toggle`, `chart_events_toggle`, `chart_event_filter`, `chart_pan_zoom`, `chart_range_select`, `chart_reset_zoom` |
| `js/democracy.js` | `hmdi_country_open` |
| `js/hero-carousel.js` *(home)* | `hero_carousel_change` |
| `templates/aviation.html` | `simulator_interact`, `simulator_reset` |
| `templates/404.html`, `500.html` | `exception` |

`report_tab_switch` is emitted from two places, and they do not overlap:
`theme.js` binds `[data-report-tab]`, which is what every dashboard except the
projection engine uses, while `elections.js` owns its own `[data-tab]` panels.
Giving the two tab systems the same event name but different attributes keeps
the funnel comparable across reports without double-counting the one page that
has its own implementation.

---

## Public Perception Index

A 1–10 rating on the Hormuz dashboard asking readers how severe the situation
feels. The mean rating is stretched onto the same 100–200 scale as the model
score, so a rating of 1 lands on the calm baseline and 10 on maximum stress:

```
index = 100 + (mean_rating - 1) / 9 * 100
```

Sharing the scale is what makes the crowd reading and the composite comparable
at a glance. It is opinion and contributes nothing to HMX-INDEX. Its tallies
are readable only through the widget's own endpoint, which returns aggregate
counts and no per-voter rows.

Votes live in Postgres (`community_votes`); the table is created on first use
by `app/votes.py:SCHEMA`, so a fresh database needs no manual bootstrap.

**Data protection.** No account, no cookie, no IP address, no user agent and no
fingerprint is stored. Uniqueness comes from a random UUID the browser
generates and keeps in `localStorage`, written only when someone actually
votes, and stored server-side only as a peppered SHA-256. Ballot stuffing is
capped against a week-salted HMAC of IP + user agent from which neither input
can be recovered and which cannot be correlated across weeks. The
`localStorage` entry is strictly necessary for the function the visitor asked
for, so it needs no consent banner, and the vote block states it anyway.
Visitors can withdraw a vote from the same block, which deletes the row and
the local ID. See the module docstring in `app/votes.py` for the full rationale.

---

## Deployment

### Vercel

```bash
npx vercel --prod
```

`vercel.json` configures the rewrite to `api/index.py`, immutable caching for `/static/*`, security
headers, and a daily cron hitting `/api/cron/update-hormuz`.

**Set `CRON_SECRET`** in Vercel project settings — Vercel sends it as a bearer token automatically,
and without it the recompute endpoint is publicly callable.

### Canonical host — one setting, do not skip it

Every absolute URL the site emits uses `SITE_ORIGIN`, which defaults to the **apex**
`https://mydatalabs.in`. The deployment must redirect `www → apex` to match, otherwise canonical
tags, OG images and sitemap entries all point at a URL that redirects.

In **Vercel → Project → Settings → Domains**: add both `mydatalabs.in` and `www.mydatalabs.in`, then
set `www.mydatalabs.in` to **redirect to** `mydatalabs.in`.

If you would rather serve from `www`, set `SITE_ORIGIN=https://www.mydatalabs.in` instead — no code
changes are needed either way.

---

## Licence & attribution

Index data is published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Cite as: *MyDataLabs Hormuz Crisis Index (HMX-INDEX) — mydatalabs.in*.

The vessel incident log is not covered by this licence.
