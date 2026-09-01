/* Hard-Metric Democracy Index dashboard.
 *
 * The whole scored panel — 30 economies x 25 years — ships inside the page as
 * one JSON block, so year switching, reweighting, re-ranking, sorting and
 * filtering all happen here rather than as a round trip. That is the point of
 * the weight sliders: a reader who has to wait 300ms per drag never discovers
 * that most of this league table does not depend on the weights at all.
 *
 * Rows arrive as bare arrays (see app/precomputed.py::_build_democracy_index).
 * The keyed form was 1.1MB of repeated field names; positionally it is a tenth
 * of that. ROW is the decoder and the only place the layout is known.
 */
(function () {
  "use strict";

  var el = document.getElementById("hmdi-data");
  if (!el) return;

  var DATA;
  try {
    DATA = JSON.parse(el.textContent);
  } catch (err) {
    return;
  }

  var ROW = { COMPOSITE: 0, RANK: 1, PILLARS: 2, METRICS: 3, CONTEXT: 4, ANCHORS: 5 };

  var PILLARS = DATA.pillars;
  var PILLAR_KEYS = PILLARS.map(function (p) { return p.key; });
  var METRICS = DATA.metrics;
  var COUNTRY_BY_CODE = {};
  DATA.countries.forEach(function (c) { COUNTRY_BY_CODE[c.code] = c; });

  var PILLAR_FLOOR = 1.0;

  /* V-Dem's expert-coded Liberal Democracy Index, carried as a comparator and
     never as an input: it is looked up by year and is deliberately untouched by
     the weight sliders. Scores and in-panel ranks arrive as arrays aligned to
     DATA.years, so a year is one index lookup rather than a re-rank. */
  var VDEM = DATA.vdem || { years: [], scores: {}, ranks: {} };

  function vdemAt(code, year) {
    var i = DATA.years.indexOf(year);
    if (i < 0) return { score: null, rank: null };
    var sc = VDEM.scores && VDEM.scores[code];
    var rk = VDEM.ranks && VDEM.ranks[code];
    return {
      score: sc && sc[i] != null ? sc[i] : null,
      rank: rk && rk[i] != null ? rk[i] : null
    };
  }

  var state = {
    year: DATA.years[DATA.years.length - 1],
    weights: Object.assign({}, DATA.defaultWeights),
    sort: { key: "rank", dir: 1 },
    search: "",
    region: "",
    // Six countries is the most a line chart carries before it becomes a
    // spaghetti plot. These are chosen to span the range rather than to be
    // interesting: top, bottom, and the large democracies people arrive for.
    traj: ["NOR", "DEU", "USA", "IND", "BRA", "CHN"]
  };

  var charts = {};

  // --- Scoring, mirrored from app/indices/democracy.py ----------------------
  // Duplicated deliberately: the alternative is a request per slider drag. The
  // server remains authoritative — it renders the initial table and every
  // precomputed figure — and the parity test in tests/test_democracy.py pins
  // the two implementations to the same numbers.

  function normaliseWeights(w) {
    var cleaned = {};
    var total = 0;
    PILLAR_KEYS.forEach(function (k) {
      var v = Math.max(0, Number(w[k]) || 0);
      cleaned[k] = v;
      total += v;
    });
    if (total <= 0) return Object.assign({}, DATA.defaultWeights);
    PILLAR_KEYS.forEach(function (k) { cleaned[k] = cleaned[k] / total; });
    return cleaned;
  }

  function compositeFrom(pillarScores, weights) {
    var w = normaliseWeights(weights);
    var total = 0;
    var used = 0;
    PILLAR_KEYS.forEach(function (k, i) {
      if (w[k] <= 0) return;
      total += w[k] * Math.log(Math.max(pillarScores[i], PILLAR_FLOOR));
      used += w[k];
    });
    if (used <= 0) return 0;
    return Math.round(Math.exp(total / used) * 100) / 100;
  }

  function normaliseMetric(spec, value) {
    if (value === null || value === undefined) return null;
    var lo = spec.lo;
    var hi = spec.hi;
    if (hi === lo) return 100;
    var clamped = Math.max(lo, Math.min(hi, value));
    var score = spec.better === "high"
      ? ((clamped - lo) / (hi - lo)) * 100
      : ((hi - clamped) / (hi - lo)) * 100;
    return Math.round(score * 100) / 100;
  }

  function tierFor(score) {
    for (var i = 0; i < DATA.tiers.length; i++) {
      if (score >= DATA.tiers[i].lower) return DATA.tiers[i];
    }
    return DATA.tiers[DATA.tiers.length - 1];
  }

  /* Every country for one year, rescored under the current weights and
     re-ranked. Ranking is recomputed rather than read off the row because the
     stored rank belongs to the default weighting. */
  function rankedFor(year, weights) {
    var rows = [];
    DATA.countries.forEach(function (c) {
      var raw = DATA.panelRows[c.code + "-" + year];
      if (!raw) return;
      var pillars = raw[ROW.PILLARS];
      var composite = compositeFrom(pillars, weights);
      var tier = tierFor(composite);
      rows.push({
        code: c.code,
        name: c.name,
        region: c.region,
        regime: c.regime_type,
        gdpRank: c.gdp_rank,
        pillars: pillars,
        metrics: raw[ROW.METRICS],
        context: raw[ROW.CONTEXT],
        anchorBits: raw[ROW.ANCHORS],
        anchorShare: countBits(raw[ROW.ANCHORS]) / METRICS.length,
        vdemScore: vdemAt(c.code, year).score,
        vdemRank: vdemAt(c.code, year).rank,
        composite: composite,
        tier: tier.label,
        status: tier.status
      });
    });
    rows.sort(function (a, b) {
      return b.composite - a.composite || a.name.localeCompare(b.name);
    });
    rows.forEach(function (r, i) { r.rank = i + 1; });
    return rows;
  }

  function countBits(n) {
    var c = 0;
    while (n) { c += n & 1; n >>= 1; }
    return c;
  }

  // --- Rendering -----------------------------------------------------------

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function visibleRows(rows) {
    var q = state.search.trim().toLowerCase();
    return rows.filter(function (r) {
      if (state.region && r.region !== state.region) return false;
      if (!q) return true;
      return r.name.toLowerCase().indexOf(q) !== -1 || r.code.toLowerCase().indexOf(q) !== -1;
    });
  }

  function sortRows(rows) {
    var key = state.sort.key;
    var dir = state.sort.dir;
    var pick = {
      rank: function (r) { return r.rank; },
      name: function (r) { return r.name; },
      composite: function (r) { return r.composite; },
      tier: function (r) { return r.composite; },   // tier is a band of the score
      anchor: function (r) { return r.anchorShare; },
      vdem: function (r) { return r.vdemRank == null ? 999 : r.vdemRank; }
    }[key] || function (r) { return r.rank; };

    return rows.slice().sort(function (a, b) {
      var va = pick(a);
      var vb = pick(b);
      if (typeof va === "string") return dir * va.localeCompare(vb);
      return dir * (va - vb);
    });
  }

  function renderTable(rows) {
    var tbody = document.getElementById("hmdi-tbody");
    if (!tbody) return;

    var shown = sortRows(visibleRows(rows));
    var accent = PILLARS[0].color;

    tbody.innerHTML = shown.map(function (r) {
      var pills = r.pillars.map(function (score, i) {
        var p = PILLARS[i];
        return '<span title="' + esc(p.label) + ": " + score.toFixed(1) + '" style="background:' +
          p.color + "; opacity:" + (0.25 + 0.75 * (score / 100)).toFixed(2) + ';">' +
          Math.round(score) + "</span>";
      }).join("");

      return '<tr tabindex="0" data-code="' + r.code + '" data-region="' + esc(r.region) + '">' +
        '<td class="hmdi-rank">' + r.rank + "</td>" +
        '<td><div class="hmdi-country"><span class="hmdi-code">' + r.code + "</span><span>" +
          esc(r.name) + "</span></div></td>" +
        '<td class="hmdi-num"><div class="hmdi-score-cell">' +
          '<span class="hmdi-score-bar"><i style="width:' + r.composite + "%; background:" + accent + ';"></i></span>' +
          "<strong>" + r.composite.toFixed(1) + "</strong></div></td>" +
        '<td class="hmdi-pill-cells">' + pills + "</td>" +
        '<td class="hmdi-num hmdi-vdem-col">' + (r.vdemRank == null
          ? '<span class="hmdi-vdem-chip is-empty">—</span>'
          : '<span class="hmdi-vdem-chip" title="V-Dem liberal democracy index ' +
            r.vdemScore.toFixed(3) + " (" + state.year + ')">' + r.vdemRank +
            "<i>" + r.vdemScore.toFixed(2) + "</i></span>") + "</td>" +
        '<td><span class="status-badge status-' + r.status + '">' + esc(r.tier) + "</span></td>" +
        '<td class="hmdi-num"><span class="hmdi-anchor-chip' +
          (r.anchorShare < 0.5 ? " is-thin" : "") + '">' +
          Math.round(r.anchorShare * 100) + "%</span></td>" +
        "</tr>";
    }).join("");

    var count = document.getElementById("hmdi-row-count");
    if (count) {
      count.textContent = shown.length === rows.length
        ? rows.length + " economies"
        : shown.length + " of " + rows.length + " economies";
    }
  }

  function renderKpis(rows) {
    if (!rows.length) return;
    var top = rows[0];
    var bottom = rows[rows.length - 1];
    var spread = top.composite - bottom.composite;

    set("hmdi-kpi-top-name", top.name);
    set("hmdi-kpi-top-score", top.composite.toFixed(1));
    set("hmdi-kpi-top-tier", top.tier);
    set("hmdi-kpi-bottom-name", bottom.name);
    set("hmdi-kpi-bottom-score", bottom.composite.toFixed(1));
    set("hmdi-kpi-bottom-tier", bottom.tier);
    set("hmdi-kpi-spread", spread.toFixed(1));
    set("hmdi-rank-year", state.year);
    set("hmdi-year-readout", state.year);
  }

  function set(id, text) {
    var node = document.getElementById(id);
    if (node) node.textContent = text;
  }

  // --- Charts --------------------------------------------------------------

  function palette() {
    var dark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
      dark: dark,
      axis: dark ? "#334155" : "#CBD5E1",
      label: dark ? "#94A3B8" : "#475569",
      split: dark ? "rgba(148,163,184,0.08)" : "rgba(0,0,0,0.06)",
      tooltip: {
        backgroundColor: dark ? "#1E293B" : "#FFFFFF",
        borderColor: dark ? "#334155" : "#CBD5E1",
        textStyle: { color: dark ? "#F8FAFC" : "#0F172A" },
        extraCssText: "max-width:320px; white-space:normal; border-radius:8px;"
      }
    };
  }

  function mount(id) {
    var dom = document.getElementById(id);
    if (!dom || typeof echarts === "undefined") return null;
    var fallback = dom.querySelector(".chart-fallback");
    if (fallback) fallback.remove();
    if (charts[id]) charts[id].dispose();
    charts[id] = echarts.init(dom);
    return charts[id];
  }

  var COUNTRY_COLORS = ["#38BDF8", "#A78BFA", "#34D399", "#FBBF24", "#F87171", "#F472B6", "#22D3EE", "#FB923C"];

  function drawTrajectories() {
    var chart = mount("hmdi-traj-chart");
    if (!chart) return;
    var p = palette();
    var years = DATA.years;

    var series = state.traj.map(function (code, i) {
      var country = COUNTRY_BY_CODE[code];
      return {
        name: country ? country.name : code,
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2 },
        itemStyle: { color: COUNTRY_COLORS[i % COUNTRY_COLORS.length] },
        emphasis: { focus: "series" },
        data: years.map(function (y) {
          var raw = DATA.panelRows[code + "-" + y];
          return raw ? compositeFrom(raw[ROW.PILLARS], state.weights) : null;
        })
      };
    });

    // The panel mean under the current weights, not the precomputed one: a
    // reader who has reweighted should be compared against a mean computed the
    // same way, or the reference line silently belongs to a different index.
    series.push({
      name: "Panel mean",
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2, type: "dashed", color: p.label },
      itemStyle: { color: p.label },
      z: 1,
      data: years.map(function (y) {
        var vals = DATA.countries.map(function (c) {
          var raw = DATA.panelRows[c.code + "-" + y];
          return raw ? compositeFrom(raw[ROW.PILLARS], state.weights) : null;
        }).filter(function (v) { return v !== null; });
        if (!vals.length) return null;
        return Math.round((vals.reduce(function (a, b) { return a + b; }, 0) / vals.length) * 10) / 10;
      })
    });

    // Y bounds from the plotted values only: on a 0-100 scale the panel lives
    // in a narrow band, and a fixed 0-100 axis flattens every trajectory into a
    // straight line. Padded by 8% of the range and clamped to [0, 100].
    var plotted = [];
    series.forEach(function (s) {
      s.data.forEach(function (v) { if (v !== null && v !== undefined) plotted.push(v); });
    });
    var lo = 0, hi = 100;
    if (plotted.length) {
      var mn = Math.min.apply(null, plotted);
      var mx = Math.max.apply(null, plotted);
      var pad = Math.max((mx - mn) * 0.08, 1);
      lo = Math.max(0, Math.floor(mn - pad));
      hi = Math.min(100, Math.ceil(mx + pad));
    }

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 46, right: 24, top: 44, bottom: 34 },
      tooltip: Object.assign({ trigger: "axis" }, p.tooltip),
      legend: { top: 4, textStyle: { color: p.label, fontSize: 11 }, icon: "circle", type: "scroll" },
      xAxis: {
        type: "category",
        data: years.map(String),
        axisLine: { lineStyle: { color: p.axis } },
        axisLabel: { color: p.label, fontSize: 10 }
      },
      yAxis: {
        type: "value", min: lo, max: hi, name: "Composite",
        nameTextStyle: { color: p.label, fontSize: 10 },
        axisLabel: { color: p.label, fontSize: 10 },
        splitLine: { lineStyle: { color: p.split } }
      },
      series: series
    });
  }

  function drawMovers() {
    var chart = mount("hmdi-movers-chart");
    if (!chart) return;
    var p = palette();

    var first = DATA.years[0];
    var last = DATA.years[DATA.years.length - 1];
    var rows = DATA.countries.map(function (c) {
      var a = DATA.panelRows[c.code + "-" + first];
      var b = DATA.panelRows[c.code + "-" + last];
      if (!a || !b) return null;
      return {
        name: c.name,
        delta: Math.round((compositeFrom(b[ROW.PILLARS], state.weights) -
                           compositeFrom(a[ROW.PILLARS], state.weights)) * 10) / 10
      };
    }).filter(Boolean).sort(function (x, y) { return x.delta - y.delta; });

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 130, right: 40, top: 16, bottom: 30 },
      tooltip: Object.assign({
        trigger: "item",
        formatter: function (i) {
          return i.name + "<br/><strong>" + (i.value > 0 ? "+" : "") + i.value.toFixed(1) +
            "</strong> points, " + first + " to " + last;
        }
      }, p.tooltip),
      xAxis: {
        type: "value",
        axisLabel: { color: p.label, fontSize: 10 },
        splitLine: { lineStyle: { color: p.split } }
      },
      yAxis: {
        type: "category",
        data: rows.map(function (r) { return r.name; }),
        axisLine: { lineStyle: { color: p.axis } },
        axisLabel: { color: p.label, fontSize: 10 }
      },
      series: [{
        type: "bar",
        data: rows.map(function (r) {
          return {
            value: r.delta,
            itemStyle: { color: r.delta >= 0 ? "#34D399" : "#F87171", borderRadius: 3 }
          };
        })
      }]
    });
  }

  function drawPillarMeans() {
    var chart = mount("hmdi-pillar-chart");
    if (!chart) return;
    var p = palette();

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 44, right: 20, top: 40, bottom: 30 },
      tooltip: Object.assign({ trigger: "axis" }, p.tooltip),
      legend: { top: 2, textStyle: { color: p.label, fontSize: 11 }, icon: "circle", type: "scroll" },
      xAxis: {
        type: "category",
        data: DATA.panel.map(function (d) { return String(d.year); }),
        axisLine: { lineStyle: { color: p.axis } },
        axisLabel: { color: p.label, fontSize: 10 }
      },
      yAxis: {
        type: "value", min: 0, max: 100,
        axisLabel: { color: p.label, fontSize: 10 },
        splitLine: { lineStyle: { color: p.split } }
      },
      series: PILLARS.map(function (pl) {
        return {
          name: pl.short,
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { width: 2 },
          itemStyle: { color: pl.color },
          emphasis: { focus: "series" },
          data: DATA.panel.map(function (d) { return d.pillars[pl.key]; })
        };
      })
    });
  }

  function drawAnchorDensity() {
    var chart = mount("hmdi-anchor-chart");
    if (!chart) return;
    var p = palette();

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 48, right: 20, top: 20, bottom: 30 },
      tooltip: Object.assign({
        trigger: "axis",
        formatter: function (params) {
          var d = DATA.anchorDensity[params[0].dataIndex];
          return "<strong>" + d.year + "</strong><br/>" + d.anchor_cells + " of " +
            d.total_cells + " cells on a source<br/>" + (d.share * 100).toFixed(1) + "%";
        }
      }, p.tooltip),
      xAxis: {
        type: "category",
        data: DATA.anchorDensity.map(function (d) { return String(d.year); }),
        axisLine: { lineStyle: { color: p.axis } },
        axisLabel: { color: p.label, fontSize: 10 }
      },
      yAxis: {
        type: "value", min: 0, max: 100,
        axisLabel: { color: p.label, fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: p.split } }
      },
      series: [{
        type: "bar",
        barWidth: "70%",
        data: DATA.anchorDensity.map(function (d) {
          var pct = Math.round(d.share * 1000) / 10;
          return {
            value: pct,
            itemStyle: {
              borderRadius: [3, 3, 0, 0],
              color: pct < 20 ? "#F87171" : (pct < 45 ? "#FBBF24" : "#34D399")
            }
          };
        })
      }]
    });
  }

  // --- Country drawer ------------------------------------------------------

  var lastFocused = null;

  function openDrawer(code, rows) {
    var row = rows.filter(function (r) { return r.code === code; })[0];
    if (!row) return;

    lastFocused = document.activeElement;

    set("hmdi-drawer-name", row.name);
    set("hmdi-drawer-sub", row.regime + " · " + row.region + " · GDP rank #" + row.gdpRank +
        " · panel year " + state.year);
    set("hmdi-drawer-score", row.composite.toFixed(1));
    set("hmdi-drawer-rank", "#" + row.rank);
    set("hmdi-drawer-anchor", Math.round(row.anchorShare * 100) + "%");
    set("hmdi-drawer-vdem", row.vdemRank == null
      ? "—"
      : "#" + row.vdemRank + " · " + row.vdemScore.toFixed(2));

    var tbody = document.getElementById("hmdi-drawer-metrics");
    if (tbody) {
      tbody.innerHTML = METRICS.map(function (m, i) {
        var raw = row.metrics[i];
        var score = normaliseMetric(m, raw);
        var anchored = (row.anchorBits >> i) & 1;
        return "<tr><td>" + esc(m.short) + '</td><td class="hmdi-num">' +
          (raw === null ? "—" : raw.toLocaleString()) + " " + esc(m.unit) +
          '</td><td class="hmdi-num"><strong>' + (score === null ? "—" : score.toFixed(0)) +
          '</strong></td><td class="hmdi-num" title="' +
          (anchored ? "Anchored to a published figure for this year" : "Interpolated between anchor years") +
          '">' + (anchored ? "●" : "○") + "</td></tr>";
      }).join("");
    }

    var ctx = document.getElementById("hmdi-drawer-context");
    if (ctx) {
      ctx.innerHTML = DATA.contextMetrics.map(function (c, i) {
        var v = row.context[i];
        return "<tr><td>" + esc(c.short) + '</td><td class="hmdi-num">' +
          (v === null || v === undefined ? "—" : v.toLocaleString()) + " " + esc(c.unit) + "</td></tr>";
      }).join("");
    }

    var backdrop = document.getElementById("hmdi-drawer-backdrop");
    var drawer = document.getElementById("hmdi-drawer");
    backdrop.setAttribute("data-open", "true");
    drawer.hidden = false;
    // Next frame, so the transform transition has a frame to run from.
    requestAnimationFrame(function () { drawer.setAttribute("data-open", "true"); });
    // The page behind the backdrop must not scroll with the drawer, or the
    // table slides away underneath it while the panel is open.
    document.body.style.overflow = "hidden";
    drawer.scrollTop = 0;
    drawer.focus();

    drawRadar(row);
    if (window.trackEvent) window.trackEvent("hmdi_country_open", { country: code, year: state.year });
  }

  function drawRadar(row) {
    var chart = mount("hmdi-drawer-radar");
    if (!chart) return;
    var p = palette();

    // Panel mean under the current weights, as the comparison shape. A radar
    // with one polygon on it says nothing; the question is always "compared to
    // what".
    var means = PILLAR_KEYS.map(function (_, i) {
      var vals = DATA.countries.map(function (c) {
        var raw = DATA.panelRows[c.code + "-" + state.year];
        return raw ? raw[ROW.PILLARS][i] : null;
      }).filter(function (v) { return v !== null; });
      return Math.round((vals.reduce(function (a, b) { return a + b; }, 0) / vals.length) * 10) / 10;
    });

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: p.tooltip,
      legend: { bottom: 0, textStyle: { color: p.label, fontSize: 10 }, icon: "circle" },
      radar: {
        indicator: PILLARS.map(function (pl) { return { name: pl.short, max: 100 }; }),
        radius: "62%",
        center: ["50%", "46%"],
        axisName: { color: p.label, fontSize: 10 },
        splitLine: { lineStyle: { color: p.split } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: p.split } }
      },
      series: [{
        type: "radar",
        data: [
          {
            value: row.pillars,
            name: row.name,
            itemStyle: { color: "#38BDF8" },
            areaStyle: { opacity: 0.22 }
          },
          {
            value: means,
            name: "Panel mean",
            itemStyle: { color: p.label },
            lineStyle: { type: "dashed" },
            areaStyle: { opacity: 0.05 }
          }
        ]
      }]
    });
  }

  function closeDrawer() {
    var backdrop = document.getElementById("hmdi-drawer-backdrop");
    var drawer = document.getElementById("hmdi-drawer");
    backdrop.setAttribute("data-open", "false");
    drawer.setAttribute("data-open", "false");
    // Hidden only after the slide-out finishes, or the panel vanishes instead
    // of leaving.
    setTimeout(function () { drawer.hidden = true; }, 220);
    document.body.style.overflow = "";
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  // --- Wiring --------------------------------------------------------------

  var currentRows = [];

  function refresh(redrawCharts) {
    currentRows = rankedFor(state.year, state.weights);
    renderTable(currentRows);
    renderKpis(currentRows);
    if (redrawCharts) {
      drawTrajectories();
      drawMovers();
    }
  }

  function buildTrajPicker() {
    var host = document.getElementById("hmdi-traj-picker");
    if (!host) return;
    host.innerHTML = DATA.countries.map(function (c) {
      var on = state.traj.indexOf(c.code) !== -1;
      return '<button type="button" data-code="' + c.code + '" aria-pressed="' + on + '">' +
        c.code + "</button>";
    }).join("");

    host.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button[data-code]");
      if (!btn) return;
      var code = btn.getAttribute("data-code");
      var at = state.traj.indexOf(code);
      if (at !== -1) {
        state.traj.splice(at, 1);
      } else {
        // Eight lines is already past the point of legibility; adding a ninth
        // drops the oldest rather than refusing, so the control never feels
        // stuck.
        if (state.traj.length >= 8) state.traj.shift();
        state.traj.push(code);
      }
      Array.prototype.forEach.call(host.querySelectorAll("button[data-code]"), function (b) {
        b.setAttribute("aria-pressed", state.traj.indexOf(b.getAttribute("data-code")) !== -1);
      });
      drawTrajectories();
    });
  }

  function wire() {
    var yearInput = document.getElementById("hmdi-year");
    if (yearInput) {
      yearInput.addEventListener("input", function () {
        state.year = Number(yearInput.value);
        refresh(false);
      });
      // Charts redraw on release rather than on every pixel of the drag: the
      // trajectory chart re-scores 750 rows and the movers chart re-sorts 30.
      yearInput.addEventListener("change", function () { refresh(true); });
    }

    PILLARS.forEach(function (p) {
      var slider = document.getElementById("hmdi-w-" + p.key);
      if (!slider) return;
      slider.addEventListener("input", function () {
        state.weights[p.key] = Number(slider.value);
        syncWeightLabels();
        refresh(false);
      });
      slider.addEventListener("change", function () { refresh(true); });
    });

    var reset = document.getElementById("hmdi-reset-weights");
    if (reset) {
      reset.addEventListener("click", function () {
        state.weights = Object.assign({}, DATA.defaultWeights);
        PILLARS.forEach(function (p) {
          var slider = document.getElementById("hmdi-w-" + p.key);
          if (slider) slider.value = 20;
        });
        syncWeightLabels();
        refresh(true);
      });
    }

    var search = document.getElementById("hmdi-search");
    if (search) {
      search.addEventListener("input", function () {
        state.search = search.value;
        renderTable(currentRows);
      });
    }

    var region = document.getElementById("hmdi-region");
    if (region) {
      region.addEventListener("change", function () {
        state.region = region.value;
        renderTable(currentRows);
      });
    }

    document.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort");
        if (state.sort.key === key) {
          state.sort.dir *= -1;
        } else {
          state.sort.key = key;
          // Rank and name read naturally ascending; a score column almost
          // always wants its best value first.
          state.sort.dir = (key === "rank" || key === "name") ? 1 : -1;
        }
        document.querySelectorAll("th[data-sort]").forEach(function (other) {
          other.removeAttribute("aria-sort");
        });
        th.setAttribute("aria-sort", state.sort.dir === 1 ? "ascending" : "descending");
        renderTable(currentRows);
      });
    });

    var tbody = document.getElementById("hmdi-tbody");
    if (tbody) {
      tbody.addEventListener("click", function (ev) {
        var tr = ev.target.closest("tr[data-code]");
        if (tr) openDrawer(tr.getAttribute("data-code"), currentRows);
      });
      tbody.addEventListener("keydown", function (ev) {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        var tr = ev.target.closest("tr[data-code]");
        if (!tr) return;
        ev.preventDefault();
        openDrawer(tr.getAttribute("data-code"), currentRows);
      });
    }

    var closeBtn = document.getElementById("hmdi-drawer-close");
    if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
    var backdrop = document.getElementById("hmdi-drawer-backdrop");
    if (backdrop) backdrop.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeDrawer();
    });

    // Tabs. Same contract as the other report pages: a data-report-tab button
    // shows #tab-<name> and hides the rest.
    document.querySelectorAll("[data-report-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        showTab(btn.getAttribute("data-report-tab"));
      });
    });

    // Links from the dashboard into a methodology section have to switch tab
    // first, or they scroll to an element inside a display:none panel and
    // appear to do nothing.
    document.querySelectorAll("[data-goto-method]").forEach(function (link) {
      link.addEventListener("click", function (ev) {
        ev.preventDefault();
        showTab("methodology");
        var target = document.querySelector(link.getAttribute("href"));
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    window.addEventListener("resize", function () {
      Object.keys(charts).forEach(function (k) { if (charts[k]) charts[k].resize(); });
    });

    // theme.js fires this on toggle. Canvas cannot inherit CSS variables, so
    // every chart is rebuilt rather than restyled.
    window.addEventListener("themechange", function () {
      drawTrajectories();
      drawMovers();
      drawPillarMeans();
      drawAnchorDensity();
    });
  }

  function showTab(name) {
    document.querySelectorAll("[data-report-tab]").forEach(function (b) {
      var on = b.getAttribute("data-report-tab") === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    document.querySelectorAll(".report-panel").forEach(function (p) { p.style.display = "none"; });
    var target = document.getElementById("tab-" + name);
    if (target) target.style.display = "block";

    // ECharts sizes to a container that was display:none as 0x0, so anything
    // first revealed by a tab switch needs a resize once it has a box.
    Object.keys(charts).forEach(function (k) { if (charts[k]) charts[k].resize(); });
    if (name === "methodology" && !charts["hmdi-anchor-chart"]) drawAnchorDensity();
  }

  function syncWeightLabels() {
    var total = PILLAR_KEYS.reduce(function (a, k) { return a + (Number(state.weights[k]) || 0); }, 0);
    PILLARS.forEach(function (p) {
      var out = document.getElementById("hmdi-w-" + p.key + "-val");
      if (!out) return;
      // Shown as the normalised share, not the raw slider position: five
      // sliders at 50 is equal weighting, and printing "50%" five times would
      // say otherwise.
      var share = total > 0 ? (Number(state.weights[p.key]) || 0) / total : 0;
      out.textContent = Math.round(share * 100) + "%";
    });
  }

  function init() {
    // The panel arrives keyed on the default weighting; state.weights holds
    // slider positions (0-50), which normaliseWeights turns into shares.
    state.weights = {};
    PILLAR_KEYS.forEach(function (k) { state.weights[k] = 20; });

    syncWeightLabels();
    buildTrajPicker();
    wire();
    refresh(true);
    drawPillarMeans();
    drawAnchorDensity();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
