# MyDataLabs.in — Comprehensive Site Audit

**Audited:** 2026-07-26
**Target:** https://www.mydatalabs.in (live) + local source at `mydatalabs-in/`
**Pages in scope:** `/` (home), `/hormuz-index`, `/reports/<slug>` (coming-soon), `/api/hormuz-index/data.json`, `/api/hormuz-index/data.csv`, `/sitemap.xml`, `/robots.txt`

**Verdict in one line:** The engineering and visual craft are genuinely strong — this looks and reads like a Bloomberg terminal page — but the site makes verifiability claims ("verified", "empirical", "peer-reviewable", "citation-ready") that the underlying data cannot currently support. That single gap is the highest-severity issue on the site and it undermines every other strength. Fix that first; everything else is tuning.

---

## Severity Index

| # | Issue | Category | Severity |
|---|---|---|---|
| 1 | Vessel dataset is placeholder data labelled "Verified" / "Empirical" | Methodology / Content | **Critical** |
| 2 | Press-wire dispatch hardcodes numbers that will drift from live index | Content / Methodology | **Critical** |
| 3 | Canonical + sitemap + OG all point to non-www; site resolves at www | SEO | **High** |
| 4 | Every page load triggers 3 live yfinance calls → 1.3s TTFB | UX / Performance | **High** |
| 5 | Index mathematically floored at 100 — cannot register de-escalation | Methodology | **High** |
| 6 | 404s render the 500 error template | UX | **High** |
| 7 | No `Article`/`WebSite`/`BreadcrumbList` schema; `Dataset` claims a CC licence not stated anywhere on-site | SEO / Methodology | Medium |
| 8 | Heading hierarchy broken on `/hormuz-index` (h1 → h3, no h2) | SEO / Accessibility | Medium |
| 9 | No visible focus styles anywhere; dropdown nav is keyboard-hostile | Accessibility | Medium |
| 10 | 234 KB 1024×1024 PNG served as a 32px header logo *and* as the OG image | Performance / SEO | Medium |
| 11 | Static assets served through the Python function with `Cache-Control: no-cache` | Performance | Medium |
| 12 | No methodology page, no about page, no author identity, no contact | Content / SEO (E-E-A-T) | Medium |
| 13 | Three duplicate copies of `static/` in the repo | Maintainability | Low |
| 14 | Dead code: `_trend_chart()` and the SVG tooltip block in `theme.js` | Maintainability | Low |
| 15 | Missing security headers (CSP, X-Content-Type-Options, Referrer-Policy) | Technical | Low |

---

## 1. Content

### What works

- **The headline is excellent.** "Signals before the headlines." ([home.html:12](app/templates/home.html#L12)) is the single best piece of copy on the site — short, positions the product, implies the value, and reads like a real financial-data brand. Keep it.
- **Audience targeting is explicit and consistent.** "news media outlets, energy desks, and institutional analysts" appears early and the whole site stays loyal to it. Most data sites never name their reader.
- **Concrete numbers everywhere.** "21.0M bpd", "~20% of global petroleum consumption", "adding up to 14 sailing days for Asia-Europe trade" — this is exactly the specificity a journalist needs. Vague copy is the usual failure mode here and you avoided it.
- **The press-wire dispatch is a genuinely smart product idea.** Giving a newsroom a pre-written, copy-pasteable 300-word story with your brand baked into the attribution line is a distribution mechanism, not just a feature. Very few competitors do this.

### Problems

**1.1 — "Verified" is doing work the data cannot support (Critical).**

`app/data/vessel_attacks.json` contains 56 records whose vessel names are `M/T Vessel-303`, `M/T Vessel-242`, `M/T Vessel-130` — sequential placeholder identifiers, not real IMO-registered vessel names. The `source` field on record 3 is literally `"Wikipedia 2026 Crisis Log"`.

This data is surfaced as:
- "**Verified** Vessel Attack Log (56 Incidents)" — [hormuz.html:211](app/templates/hormuz.html#L211)
- "**Empirical** incident analysis across 56 maritime strikes" — [hormuz.html:178](app/templates/hormuz.html#L178)
- "verified 56-incident maritime strike log" inside the `Dataset` JSON-LD — [hormuz.html:17](app/templates/hormuz.html#L17)
- "**Verified** historical snapshots formatted for integration into financial models, news reports, and academic research" — [home.html:209](app/templates/home.html#L209)

A journalist at Reuters or the FT who clicks "expand the log" — which the site actively invites — will see `M/T Vessel-303` and stop trusting the entire site within about four seconds. Everything else on the page is downstream of that moment.

> **Fix (pick one, do not do nothing):**
> - **(a) Make it real.** Populate from UKMTO advisories, IMB Piracy Reporting Centre, and ACLED maritime records with real vessel names, IMO numbers, and per-incident source URLs. This is the version that justifies the "verified" language and is worth doing if you want media pickup.
> - **(b) Label it honestly.** Relabel every instance to "Illustrative Incident Model (synthetic)", add a persistent banner above the log, strip `"verified"` from the JSON-LD `description`, and keep the visual demo. Costs you nothing but the word "verified" — which you don't currently own anyway.
>
> There is no version where placeholder rows stay under the word "Verified."

**1.2 — The press dispatch contains numbers that will silently go stale (Critical).**

[hormuz.html:366-382](app/templates/hormuz.html#L366-L382) mixes Jinja-rendered live values with hardcoded prose:

- `"Hormuz Crisis Index Holds at Severe {{ score }}"` — the word **Severe** is hardcoded. When the index drops to 148 the headline will read "Holds at Severe 148.0" while the badge two inches above says **Acute**.
- `"$96.78 per barrel"`, `"a 48.9% surge"`, `"0.45% of hull value"`, `"25 transits per week"`, `"24.0% of regional traffic"` — all hardcoded, all pulled from the week of 2026-07-20. Brent is live-fetched from yfinance every request; the prose is not. These diverge the moment the market moves.
- `"(+{{ score - 100 }}% above baseline)"` — this is a **points** difference formatted as a **percent**. 173.2 is 73.2 points above baseline, not 73.2% above it. A financial reporter will notice.
- Same issue in the briefing cards: "25 ships/week" and "24% of regional tanker traffic" hardcoded at [hormuz.html:95](app/templates/hormuz.html#L95), and "War-Risk Insurance and BDTI Tanker Freight remain the primary contributors" at [hormuz.html:88](app/templates/hormuz.html#L88) is asserted, not computed — the actual top contributor should be derived from `snapshot.components` sorted by `contribution`.

> **Fix:** Build the dispatch as a server-side template function that renders *every* number and *every* qualitative descriptor from the live snapshot. Derive "key driver" as `max(snapshot.components, key=lambda c: c.contribution)`. Change "% above baseline" to "points above baseline". Nothing in a press release should be a string literal.

**1.3 — An unnamed source is quoted (High).**

[hormuz.html:382](app/templates/hormuz.html#L382) attributes a direct quotation to "MyDataLabs chief quantitative analysts" — plural, anonymous, and inside a document explicitly offered to newsrooms for reproduction. No wire desk will run an anonymous corporate quote, and offering one signals to an experienced editor that no such person exists. Either name a real person with a real title, or replace the quote with an attributed data statement ("MyDataLabs index data shows…").

**1.4 — Fabricated events cite real news organisations (High).**

[routes.py:34-94](app/routes.py#L34-L94) attaches source attributions like "Reuters Middle East", "Lloyd's List Intelligence", "Financial Times World Coverage", and "S&P Global Commodity Insights" to seven events — but every `source_url` is a generic section homepage (`reuters.com/world/middle-east/`), not an article. The UI renders these as "📰 Source: Reuters Middle East →", which reads as "Reuters reported this." Attaching a real newsroom's name to an event with no article behind it is a trademark and defamation exposure, independent of the SEO cost.

> **Fix:** Link to specific articles or remove the source attribution entirely. "MyDataLabs internal event log" is an honest label.

**1.5 — Tone occasionally overshoots.**

"Institutional", "media-grade", "peer-reviewable", "Intelligence Network" appear heavily. Used once, each is positioning; stacked, they read as compensating. "Peer-reviewable quantitative methodology" ([base.html:107](app/templates/base.html#L107)) is a specific claim — peer review means an external party reviewed it. Nobody has. Suggest "fully documented methodology" or "open, reproducible methodology" — both true, both strong.

### Content recommendations, ranked

1. Resolve the verified/synthetic gap. Nothing else matters until this is settled.
2. Make the press dispatch fully dynamic and rename "% above baseline" → "points above baseline".
3. Write a real `/methodology` page: baseline selection rationale, why these seven components, why those weights, why those caps, revision policy, known limitations. This is the single highest-leverage new page — it is what a desk editor asks for before citing you, and it is a natural link magnet.
4. Add `/about` with a named author and credentials, plus `/contact` with a media enquiries address. Anonymous financial data has no authority.
5. Add a changelog/revision-history page. Index providers that restate history without a public record are not citable.
6. Replace the anonymous quote and the newsroom-attributed fake events.

---

## 2. Methodology

### What works

The scoring engine is clean, well-documented, and genuinely well-designed. [scoring.py](app/scoring.py) is index-agnostic, the docstrings explain intent rather than restating code, `invert` for ship traffic is the correct treatment, and per-component caps are a real safeguard against a single spiking asset dominating the composite. Weights sum to exactly 1.0. The `stale` flag on `ComponentResult` shows you thought about data freshness. Publishing the full component matrix with weights, caps, and sources on the page is more transparent than most commercial indices manage.

### Problems

**2.1 — The index cannot go below 100 (High).**

[scoring.py:40](app/scoring.py#L40) clamps every stress score to `max(0.0, min(100.0, score))`, so the composite is `100 + Σ(non-negative)`. Consequences:

- Brent at $40 (a genuine demand collapse / de-escalation signal) scores identically to Brent at $65. Real information is discarded.
- The three "Ceasefire Easing (-7.1 pts)" events in [routes.py](app/routes.py#L69-L93) can only ever move the index *toward* 100, never past it. Your own timeline narrates a directional move the model cannot express.
- The gauge at [hormuz.html:102](app/templates/hormuz.html#L102) reflects this — `max(score - 100, 0)` — so the entire left half of the risk scale is unreachable by construction.

> **Fix:** Either allow negative stress within a bounded floor (e.g. clamp to `[-50, 100]`) so calm registers as calm, or explicitly document this as a one-sided stress index and rename the "Calm (<110)" band, which is currently a 10-point sliver rather than a real state.

**2.2 — Missing data is silently scored as zero stress (High).**

[scoring.py:78](app/scoring.py#L78): `value_for_score = current if current is not None else baseline`. If yfinance fails, Brent falls back to its baseline, contributes 0 stress, and the composite drops by up to 30 points. A transient network error looks exactly like a de-escalating crisis. The `stale` flag is set correctly — but no template reads it. Grep confirms `cr.stale` appears in zero templates; the component table at [hormuz.html:275-307](app/templates/hormuz.html#L275-L307) renders stale and fresh values identically.

> **Fix:** Two changes. (1) Carry forward the last known value instead of the baseline. (2) Render a visible "stale — last updated <date>" badge in the component table, and suppress or asterisk the composite when any component above ~20% weight is stale. A number you can't compute is not the same as a number that is zero.

**2.3 — Four of seven components (50% of index weight) are manually keyed (High).**

`MANUAL_KEYS = {ship_traffic, war_risk, tanker_freight, reroutes}` — [hormuz.py:100](app/indices/hormuz.py#L100). These are currently frozen at `{ship_traffic: 25, war_risk: 0.45, tanker_freight: 1360, reroutes: 24}` in `manual_overrides`. The site advertises "Weekly / Next run: Monday 06:00 UTC" ([home.html:53](app/templates/home.html#L53)), but half the index by weight only moves when someone hand-edits a JSON file. `MANUAL_KEYS` is unconditionally added to `stale_keys` at [hormuz.py:140](app/indices/hormuz.py#L140), so the code knows this — the UI just never says so.

> **Fix:** Publish per-component `last_updated` timestamps in the component table and in the JSON API. Change "Next run: Monday 06:00 UTC" to reflect what actually updates automatically. An honest "3 of 7 components auto-refresh daily; 4 are updated weekly from licensed sources" is more credible than an implied full-auto pipeline.

**2.4 — Persistence does not work in production (High).**

[storage.py](app/storage.py) writes to `app/data/` — read-only on Vercel. The docstring acknowledges this. The practical result: `/api/cron/update-hormuz` returns 200 and appears to succeed, but the write is discarded when the instance recycles. History has been static at 29 weeks ending 2026-07-20. The index will silently stop accumulating history.

> **Fix:** Move to Vercel Blob, Postgres, or a git-commit-back GitHub Action. Until then, have the cron route return `{"persisted": false}` so a monitoring check can catch it rather than reading 200 as success.

**2.5 — Baseline is a single 5-day window (Medium).**

Feb 1–5, 2026 is one week. VIX at 14.5 and Brent at $65 on one specific week is a noisy anchor — pick a different week and every historical score shifts. Standard practice is a trailing multi-month median or a stated "normal regime" window.

> **Fix:** Use a 2024–2025 trailing median as baseline, or publish a sensitivity table showing how the current score changes under alternative baseline windows. The latter is cheap and is exactly the kind of thing that earns analyst trust.

**2.6 — Caps are undocumented judgement calls (Medium).**

Why is Brent's cap +55% but TTF gas's +95%? Why VIX +200% and war-risk +400%? These choices materially determine the composite — a tighter cap makes a component saturate sooner and effectively raises its influence at moderate stress levels. Right now they read as tuned to produce a satisfying-looking chart.

> **Fix:** Document each cap against a historical precedent ("+55% Brent ≈ the 2022 Ukraine invasion peak move"). One sentence per component on the methodology page converts seven arbitrary constants into seven defensible ones.

**2.7 — No stated correlation handling (Medium).**

Brent (30%), TTF gas (10%), and VIX (10%) are correlated during energy shocks — half the index weight moves together on a single event, so the composite is effectively less diversified than the seven-component presentation implies.

> **Fix:** Either acknowledge this explicitly on the methodology page, or publish a component correlation matrix. Sophisticated readers will compute it anyway; better that it comes from you.

**2.8 — No confidence interval or revision policy.**

Point estimates to one decimal ("173.2") imply a precision that four manually-keyed inputs cannot support. Add an uncertainty band, or round to whole numbers and say why.

---

## 3. Design

### What works

This is the strongest area of the site, and it is strong in an unshowy way.

- **The design token system is properly built.** [style.css:7-73](app/static/css/style.css#L7-L73) defines a full dark palette and a complete light-mode override on `:root[data-theme="light"]`. Both themes are real, not an afterthought.
- **No flash-of-wrong-theme.** The inline script at [base.html:56-61](app/templates/base.html#L56-L61) applies the stored theme before first paint. This is a detail most sites get wrong.
- **Typography is well-chosen and disciplined.** Plus Jakarta Sans for headings, Inter for body, JetBrains Mono for all numerics. Monospacing every figure is the correct call for a financial-data product — columns align, digits don't jitter between renders, and it signals "data" without saying it.
- **The status colour system is semantic, not decorative.** `good/warning/serious/critical` mapped to emerald/amber/rose, consistently applied across badges, gauge, stress bars, and delta pills.
- **Information density is well-judged.** The dashboard packs a lot in without feeling cramped — the macro-card grid, the component matrix, and the collapsible incident log each get appropriate visual weight.

### Problems

**3.1 — Heavy inline styling (Medium, maintainability).**

Roughly 100+ inline `style="…"` attributes across the three templates. [hormuz.html:150-166](app/templates/hormuz.html#L150-L166) is a 17-line block with nine inline declarations. This means: colours drift out of the token system, nothing is reusable, and the CSS file is no longer the source of truth for appearance. It also blocks a strict CSP.

> **Fix:** Promote recurring patterns to classes (`.ceasefire-card`, `.dash-meta-label`, `.driver-value`). Target: no inline style that contains a colour or a font declaration. Dynamic widths (`style="width: {{ pct }}%"`) are the legitimate exception.

**3.2 — `--text-muted: #64748B` fails WCAG AA (Medium).**

Against the dark card background this lands around 4.0:1 — below the 4.5:1 minimum for body text. It's used for the update timestamp, the "vs previous week" caption, table units, and the footer legal line. Notably it's the *same* value in both themes ([style.css:23](app/static/css/style.css#L23) and [:73](app/static/css/style.css#L73)), which means it can't be correct for both.

> **Fix:** Lighten dark-mode muted to ~`#94A3B8` and darken light-mode muted to ~`#475569`. Verify with a contrast checker at the actual rendered size.

**3.3 — The 100.0-baseline gauge is misleading (Medium).**

[home.html:119](app/templates/home.html#L119) computes fill as `min(max(score - 100, 0), 100)`, so 173.2 renders as a 73% fill on a bar whose only label is "Baseline = 100.0". A reader naturally reads 73% as "73% of maximum" — but the scale's implicit maximum is 200, which is stated nowhere. The gauge on the Hormuz page ([hormuz.html:114-128](app/templates/hormuz.html#L114-L128)) does this better by labelling the five bands, but the tick marks are at `[10, 25, 50, 80]` while the label boundaries are 110/125/150/180 — correct only because the offset arithmetic happens to line up. That coupling is fragile and undocumented.

> **Fix:** Label both ends of the home-page bar (100 → 200) and derive the tick positions from the band thresholds in code rather than hardcoding a parallel array.

**3.4 — 234 KB logo used at 32px (Medium).**

`logo.png` is 1024×1024 / 234 KB, rendered at 32×32 in the header, 26×26 in the footer, and served as both the OG image and the apple-touch-icon. That's ~10× the page's own HTML weight for an icon, and it's the wrong aspect ratio for social cards.

> **Fix:** Ship `logo-64.webp` (~3 KB) for the header/footer, keep a 180×180 PNG for apple-touch-icon, and create a proper **1200×630** OG card with the index name and current score. Social cards are how a data product spreads on X and LinkedIn — a square logo crops badly and wastes the impression.

**3.5 — Chart colours don't follow the theme toggle (Low).**

[hormuz.html:409](app/templates/hormuz.html#L409) reads `data-theme` once at `DOMContentLoaded`. Toggling to light mode leaves all three ECharts instances with dark-mode axis and tooltip colours until a reload.

> **Fix:** Extract the option-builder into a function and re-invoke `setOption` from the theme-toggle handler in `theme.js`.

**3.6 — Emoji as functional iconography (Low).**

⚠️ 📊 ⚓ 🕊️ 📰 📋 💥 📜 render inconsistently across platforms (Windows Segoe UI Emoji vs. Apple colour emoji vs. Android) and are announced verbatim by screen readers ("dove of peace"). On a page positioning itself as institutional, platform-inconsistent emoji is the detail that reads as amateur.

> **Fix:** Inline SVG icons, `aria-hidden="true"` on anything decorative. Keeps the visual, removes the inconsistency and the screen-reader noise.

**3.7 — Mobile is under-tested (Low).**

Only one meaningful breakpoint (`@media (max-width: 900px)`). The 7-column component matrix and the 7-column vessel log rely on `.table-responsive` horizontal scroll, which on mobile means the first column scrolls away and rows lose their identity.

> **Fix:** `position: sticky; left: 0` on the first `<td>` of both tables, or switch to a stacked card layout below 600px.

---

## 4. SEO

### What works

The on-page fundamentals are better than most sites at this stage: full OG and Twitter card sets, per-page title/description/keyword blocks via Jinja inheritance, `Organization` JSON-LD sitewide plus a `Dataset` graph on the index page, a dynamic sitemap, a valid robots.txt, and semantic URLs (`/hormuz-index`, not `/index?id=1`). HTTPS with HSTS `max-age=63072000` is properly configured.

### Problems

**4.1 — Canonical URLs point at a redirect (High).**

Verified live:

```
https://mydatalabs.in/       → 308 → https://www.mydatalabs.in/
https://www.mydatalabs.in/   → 200
```

But every canonical signal on the site names the **non-www** host:

- `<link rel="canonical" href="https://mydatalabs.in{{ request.path }}">` — [base.html:14](app/templates/base.html#L14)
- `og:url`, `twitter:url` — [base.html:18](app/templates/base.html#L18), [:26](app/templates/base.html#L26)
- Every `<loc>` in the sitemap — [routes.py:382](app/routes.py#L382)
- The `Sitemap:` line in robots.txt — [routes.py:410](app/routes.py#L410)
- All `@id` and `url` values in both JSON-LD blocks

So the page served at `www` declares its canonical to be a URL that immediately 308s back to `www`. Google generally resolves this, but it burns crawl budget, splits link equity, and — because `og:image` and `og:url` also 308 — social scrapers (which frequently do not follow redirects on image URLs) may fail to render your cards at all.

> **Fix:** Pick one host. Recommended: make **non-www** canonical (shorter, matches the brand, matches every existing tag) and change the Vercel redirect direction so `www → apex`. That is a one-setting change in Vercel Domains and requires zero code edits. If you prefer www, you must update all six locations above.

**4.2 — Two live pages, five sitemap entries, one topic (High).**

The sitemap lists seven URLs. Five of them are `/reports/<slug>` pages that all render the same ~120-word "In Development (Q3 2026)" template ([coming_soon.html](app/templates/coming_soon.html)) with only the category label swapped. That is textbook thin, near-duplicate content, submitted for indexing at priority 0.8 — higher than most sites give their real pages.

> **Fix:** Remove the five `/reports/*` URLs from the sitemap and add `<meta name="robots" content="noindex, follow">` to `coming_soon.html`. Reinstate them individually as each index actually launches. Five thin pages against two substantive ones is a materially bad ratio for a young domain.

**4.3 — Broken heading hierarchy on the flagship page (Medium).**

Live check of `/hormuz-index` returns: **1 × h1, 0 × h2, 9 × h3, 6 × h4.** The document jumps h1 → h3 and never uses h2 at all. Every major section — Crisis Severity Gauge, Weekly Trajectory, Vessel Attacks Intelligence, Component Breakdown, Methodology, Press Dispatch — is an `h3`. Search engines and screen readers both use heading depth to infer document structure; right now there is none.

> **Fix:** Promote the six section headings to `h2`, demote the cards within them to `h3`. Purely a tag change, no visual impact if you style by class.

**4.4 — Meta description hardcodes a stale price (Medium).**

[hormuz.html:4](app/templates/hormuz.html#L4): `"Monitors Brent Crude ($96.78), 56 vessel attack incidents, war risk insurance (0.45%)"`. Brent is live-fetched; this string is not. When Brent moves to $80 the SERP snippet advertises $96.78 — a wrong number sitting in the search result of a site whose entire proposition is data accuracy.

> **Fix:** Render it from the snapshot: `Brent (${{ "%.2f"|format(brent) }})`. Or drop the figures and describe the index. Keep it under 155 characters — the current string is ~200 and will truncate.

**4.5 — `keywords` meta tag (Low, but symptomatic).**

[base.html:11](app/templates/base.html#L11). Google has ignored this since 2009. Harmless, but its presence is a signal to any SEO-literate visitor that the optimisation is dated. Remove.

**4.6 — Missing schema types (Medium).**

Currently: `Organization` + `Dataset`. Missing and worth adding:
- `WebSite` with `SearchAction` — sitelinks search box eligibility
- `BreadcrumbList` on `/hormuz-index` — breadcrumb SERP display
- `Dataset.distribution` pointing at the existing `/api/hormuz-index/data.json` and `.csv` endpoints — these are real, working, valuable, and completely invisible to Google Dataset Search right now. This is free upside.
- `Dataset.temporalCoverage: "2026-01-05/.."` and `variableMeasured` for each of the seven components
- `Dataset.license` currently declares CC BY-SA 4.0 ([hormuz.html:25](app/templates/hormuz.html#L25)) but no licence is stated anywhere in the visible site, and the footer says "for research and news reporting" — a different, vaguer grant. Reconcile these; a contradictory licence declaration is worse than none.

**4.7 — The API endpoints are undiscoverable (Medium — this is a missed opportunity).**

`/api/hormuz-index/data.json` and `/api/hormuz-index/data.csv` work, return clean structured data, and are linked from nowhere in the UI, absent from the sitemap, and absent from the schema. An open, citable, machine-readable index feed is exactly the kind of asset that attracts links from data journalists, Kaggle, GitHub awesome-lists, and academic reference pages — the highest-quality backlinks available to a site like this.

> **Fix:** Add a "Data & API" page with endpoint documentation, response schema, a licence statement, and a citation format (BibTeX + AP style). Link it from the nav and footer. Register the dataset with Google Dataset Search.

**4.8 — No `llms.txt` (Medium).**

Returns 308/404. For a site whose content is factual, numeric, and citation-shaped, AI search surfaces (AI Overviews, ChatGPT, Perplexity) are a realistic traffic channel — arguably more realistic than ranking against Reuters for "Strait of Hormuz". An `llms.txt` at the root pointing to the index, the methodology page, and the JSON endpoint is a ~20-line file with real upside.

**4.9 — Keyword strategy is aimed too high.**

Current meta keywords target "Strait of Hormuz", "Geopolitical Risk", "Energy Security" — head terms owned by Reuters, EIA, and CSIS. You will not rank there.

> **Where you can actually win:** "Hormuz crisis index", "HMX-INDEX", "strait of hormuz shipping data 2026", "war risk insurance rate hormuz", "hormuz transit volume weekly", "tanker reroute cape of good hope percentage", "hormuz risk index API", "hormuz crisis index csv". These are low-competition, high-intent, and directly match what your pages actually contain. Branded index terms are how index providers bootstrap — own "HMX-INDEX" completely, then let citations pull you up.

**4.10 — Content depth is below what the SERP rewards.**

Two indexable pages. No blog, no weekly commentary, no archive. A weekly "HMX-INDEX: Week of X" post — 400 words, chart, the week's driver — would compound: 52 indexable, freshly-dated, internally-linked pages per year, each a natural citation target, each reinforcing the index name.

---

## 5. User Experience

### What works

- Two-click depth to any content. Nav is unambiguous.
- The theme toggle persists and doesn't flash.
- One-click copy for both the press story and the ticker quote, with a "✓ Copied!" confirmation — well-executed micro-interaction that respects the target user's actual workflow.
- The collapsible incident log (`<details>`) is the right pattern: native, keyboard-accessible, zero JS, and keeps 56 rows from burying the page.
- The coming-soon page redirects attention to the live report rather than dead-ending. Good recovery design.
- Charts have working tooltips and resize handlers.

### Problems

**5.1 — 1.3s TTFB because every page load hits yfinance (High).**

Measured live: `/` TTFB 1.37s, `/hormuz-index` TTFB 1.30s.

Cause: both `home()` ([routes.py:102](app/routes.py#L102)) and `hormuz_index()` ([routes.py:240](app/routes.py#L240)) call `hormuz.compute_snapshot(persist=False)`, which calls `fetch_live_values()`, which makes **three sequential blocking network calls** to Yahoo Finance ([hormuz.py:112-118](app/indices/hormuz.py#L112-L118)) — on every single request, per user, with no caching.

This is the site's biggest UX liability and it has three separate failure modes:
1. **Speed** — 1.3s TTFB is a poor LCP foundation; Core Web Vitals will not be good.
2. **Fragility** — a Yahoo outage or rate-limit makes all three components `None`, which (per §2.2) silently drops the composite by up to 50 points. Your headline number is hostage to an undocumented third-party endpoint.
3. **Cost/blocking** — under any real traffic you will hit Yahoo rate limits, and every visitor pays serverless compute for a number that changes at most daily.

> **Fix (highest ROI change on the site):** Compute the snapshot on a schedule — Vercel Cron hitting the existing `/api/cron/update-hormuz` route — persist to Blob/DB, and have page routes read the cached value. Serve pages with `Cache-Control: public, s-maxage=3600, stale-while-revalidate=86400`. Expected TTFB: <100ms. This also fixes §2.4 and removes the yfinance dependency from the request path entirely.

**5.2 — 404s render the 500 error page (High).**

[__init__.py:22-24](app/__init__.py#L22-L24) maps `404` to `500.html`. Any typo'd URL or dead inbound link tells the visitor the *server* failed. That reads as "this site is broken", not "that page doesn't exist" — and for a site selling data reliability, it's the worst possible false signal. `/reports/anything-invalid` will trigger it today.

> **Fix:** A dedicated `404.html` — "Page not found", plus links to Home and the Hormuz index.

**5.3 — Static assets are served by the Python function with no caching (Medium).**

Verified: `GET /static/css/style.css` returns `Cache-Control: no-cache`, `X-Vercel-Cache: MISS`. Every CSS, JS, and image request invokes the serverless function and is re-downloaded on every navigation.

> **Fix:** Set `SEND_FILE_MAX_AGE_DEFAULT` and add a Vercel `headers` rule for `/static/*` with `public, max-age=31536000, immutable`, plus a cache-busting query or hashed filename on deploy. Also ensure `handle: filesystem` in [vercel.json](vercel.json) is actually intercepting these — the response headers suggest it currently is not.

**5.4 — No visible focus indicator anywhere (Medium, accessibility).**

Grep across the 1,086-line stylesheet finds exactly one focus-related rule — `.dropdown:focus-within` — and zero `:focus-visible` declarations. A keyboard user cannot see where they are on the page. This is a WCAG 2.4.7 (Level AA) failure.

> **Fix:**
> ```css
> :where(a, button, summary, [tabindex]):focus-visible {
>   outline: 2px solid var(--accent-blue);
>   outline-offset: 2px;
>   border-radius: 4px;
> }
> ```

**5.5 — The Categories dropdown is keyboard-inaccessible (Medium).**

[base.html:78-85](app/templates/base.html#L78-L85): a `<button>` with `aria-haspopup="true"` but no `aria-expanded`, no `click` handler, and no JS. It opens purely via CSS `:hover` / `:focus-within`. Keyboard users can tab to the button but pressing Enter or Space does nothing; the menu only appears if focus lands inside it, and there is no Escape-to-close.

> **Fix:** Wire a click handler toggling `aria-expanded` and a `.is-open` class, close on `Escape` and on outside-click, and add `role="menu"` / `role="menuitem"`. Or — simpler and arguably better — replace the dropdown with a flat nav; you have five categories and only one live report.

**5.6 — No skip-to-content link (Medium, accessibility).**

Keyboard and screen-reader users tab through the full header on every page load. Add a standard visually-hidden-until-focused skip link as the first element in `<body>`.

**5.7 — Charts are invisible to assistive technology (Medium).**

All three ECharts render to `<canvas>` in bare `<div>`s with no `role`, no `aria-label`, and no text alternative. To a screen reader they do not exist. The trend chart and the vessel-attack breakdown are the two most information-dense elements on the flagship page.

> **Fix:** Add `role="img"` and a summarising `aria-label` ("HMX-INDEX weekly trajectory, January to July 2026, rising from 100.0 to 173.2"). Better: a visually-hidden `<table>` with the underlying series — you already have `history` server-side, so it's a few lines of Jinja, and it doubles as crawlable content for SEO.

**5.8 — No loading or error states (Medium).**

If the ECharts CDN fails, [hormuz.html:404-407](app/templates/hormuz.html#L404-L407) logs to console and returns — the user sees three empty 320-340px boxes with no explanation. There is also no skeleton during the ~1.3s server wait.

> **Fix:** Render a visible fallback message inside each chart container that JS removes on successful init. Consider self-hosting ECharts — it removes a third-party single point of failure and a cross-origin round trip.

**5.9 — Clipboard has no fallback (Low).**

`navigator.clipboard` is undefined on non-HTTPS origins and in some in-app browsers. [hormuz.html:588](app/templates/hormuz.html#L588) and [theme.js:31](app/static/js/theme.js#L31) call `.then()` directly on a possibly-undefined API — this throws a TypeError, and the button silently does nothing. On the press-dispatch button that is your primary conversion action.

> **Fix:** Guard for `navigator.clipboard` and fall back to selecting the text with a "Press Ctrl+C" prompt.

**5.10 — No conversion path (Medium, product).**

The site's stated goal is media pickup and analyst adoption. There is currently no email capture, no "get the weekly index in your inbox", no RSS, no contact address, and no social links. A journalist who finds this page and wants next week's number has no way to be told about it. Every visit is terminal.

> **Fix:** Add a weekly-digest email capture on both pages, RSS/JSON feed for the index, and a media-enquiries contact. This is the single largest gap between what the site is built to do and what it currently does.

**5.11 — No cookie/analytics disclosure.**

`localStorage` is used for the theme preference. No privacy policy or terms page exists. For an `.in` domain with likely EU/UK media readership, a minimal privacy page is worth having.

**5.12 — Missing security headers (Low).**

No `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, or `Permissions-Policy`. HSTS is present and correct. Add the rest via `headers` in `vercel.json`. (Note: a strict CSP requires cleaning up the inline styles and the inline theme script first — see §3.1.)

---

## Code Health (not requested, but material to the above)

- **Three identical copies of `static/`** — `app/static/`, `static/`, and `public/static/` are byte-identical (verified by diff). Three places to update a colour, two of which will silently go stale.
- **Dead code:** `_trend_chart()` at [routes.py:120-198](app/routes.py#L120-L198) is a 78-line SVG chart generator, passed to the template as `trend`, and referenced by zero templates — `hormuz.html` uses ECharts instead. The matching SVG tooltip block at [theme.js:44-81](app/static/js/theme.js#L44-L81) queries `.trend-svg`, which no longer exists in any template. ~120 lines of dead code across two files.
- **`__pycache__` is committed** — 12 `.pyc` files, including duplicated 3.12 and 3.13 builds.
- **`firebase-debug.log` in the repo root** alongside Vercel, Docker, and Cloud Run configs — four deployment targets, unclear which is authoritative.
- **`app/templates/500.html` doing double duty** as the 404 page (see §5.2).
- **No tests for `scoring.py`.** `stress_score()` is the mathematical heart of the product and has clear edge cases worth pinning: `baseline == 0`, `invert=True`, values above and below the cap, `current is None`. Half a dozen assertions would protect the one function whose correctness the entire site depends on.

---

## Recommended Order of Work

**Week 1 — credibility and correctness**
1. Resolve the verified/synthetic vessel data question (§1.1) — decide, then execute
2. Make the press dispatch fully dynamic; fix "% above baseline" → "points" (§1.2)
3. Add a real `404.html` (§5.2)
4. Fix canonical/www consistency — one Vercel setting (§4.1)
5. Remove `/reports/*` from the sitemap and add `noindex` (§4.2)

**Week 2 — performance and structure**
6. Move snapshot computation to cron + cache; get TTFB under 200ms (§5.1)
7. Wire durable persistence so history actually accumulates (§2.4)
8. Fix static asset caching (§5.3)
9. Optimise the logo; build a proper 1200×630 OG card (§3.4)
10. Fix heading hierarchy on `/hormuz-index` (§4.3)

**Week 3 — accessibility and trust**
11. Focus styles, skip link, dropdown keyboard support, chart ARIA (§5.4–5.7)
12. Fix `--text-muted` contrast in both themes (§3.2)
13. Write `/methodology`, `/about`, `/contact` (§1 recommendations)
14. Surface the `stale` flag in the component table (§2.2)

**Week 4 — growth**
15. `/data` API documentation page + `Dataset.distribution` schema (§4.7)
16. `llms.txt`, `WebSite` + `BreadcrumbList` schema (§4.6, §4.8)
17. Email capture and RSS (§5.10)
18. Start the weekly index commentary post (§4.10)
19. Address the index floor and baseline-window questions (§2.1, §2.5)

---

## Closing

The build quality here is real — the scoring engine is cleanly abstracted, the design system is properly tokenised, both themes work, the charts are competent, and the press-wire feature shows genuine product thinking about how a data provider actually gets distributed. That is a stronger foundation than most sites at this stage have.

The gap is not craft. It is that the site currently claims more verification than its data can support, and that claim is aimed at exactly the audience — newsroom editors, institutional analysts — that is best equipped to check it. Close that gap and the rest of this document is a tuning list on a product that works.
