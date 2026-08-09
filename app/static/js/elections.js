/* ==========================================================================
   Lok Sabha Projection Engine — dashboard behaviour
   --------------------------------------------------------------------------
   Ported from the standalone india-elections template. Four changes were made
   in the move, all of them forced by the shared site shell:

   * The API base comes from data-api on .elections-dash rather than being
     hardcoded to "/api", since the endpoints now live under a report prefix.
   * Inline onclick attributes became listeners bound here. switchTab used the
     implicit global `event` to find the clicked button, which only works in
     browsers that still set it.
   * The page's own theme toggle is gone; the site header owns the theme now,
     and theme.js fires a `themechange` event this file listens for.
   * renderBacktest was defined twice, byte-identical. One copy remains.
   ========================================================================== */

(function () {
  "use strict";

  var root = document.querySelector(".elections-dash");
  if (!root) return;

  var API = root.getAttribute("data-api") || "/api/lok-sabha-index";

  var dailyChart = null;
  var globalForecastData = null;
  var globalEvents = [];
  var globalAnalytics = null;
  var globalEventCategories = [];
  var showEvents = true;

  // Full extent of the data, cached so the scrollbar can size its thumb
  // against it without walking the series on every scroll event.
  var fullRange = null;
  var suppressScrollSync = false;

  function $(id) { return document.getElementById(id); }

  // Events left visible after the category filters in the legend.
  function visibleEvents() {
    return globalEvents.filter(function (ev) { return !hiddenCategories.has(ev.category); });
  }

  // Draws the event annotations on top of the chart. Point events become
  // vertical markers with a rotated label; ranged events become shaded bands.
  // Everything is driven by the events API, so adding an entry to
  // engine/events.py is all it takes to put a new marker on the chart.
  var eventOverlayPlugin = {
    id: "eventOverlay",
    beforeDatasetsDraw: function (chart) {
      var events = visibleEvents();
      if (!showEvents || !events.length) return;
      var ctx = chart.ctx;
      var area = chart.chartArea;
      var x = chart.scales.x;
      if (!x || !area) return;

      var top = area.top, bottom = area.bottom, left = area.left, right = area.right;
      var min = x.min, max = x.max;

      // Labels are only drawn where there is room for them. At full zoom two
      // decades of events would otherwise overprint into an unreadable smear;
      // zooming in reveals the ones skipped here.
      var drawnLabelX = [];
      var LABEL_GAP_PX = 15;
      var hasRoom = function (px) {
        return !drawnLabelX.some(function (prev) { return Math.abs(prev - px) < LABEL_GAP_PX; });
      };

      // Oldest first, so the labels that survive crowding are stable as the
      // user pans rather than flickering between neighbours.
      var ordered = events.slice().sort(function (a, b) { return a.date.localeCompare(b.date); });

      ordered.forEach(function (ev) {
        var startMs = new Date(ev.date).getTime();
        var endMs = ev.end_date ? new Date(ev.end_date).getTime() : startMs;

        // Skip anything entirely outside the current zoom window.
        if (endMs < min || startMs > max) return;

        var xStart = x.getPixelForValue(Math.max(startMs, min));
        var xEnd = x.getPixelForValue(Math.min(endMs, max));

        ctx.save();
        if (ev.is_range && xEnd - xStart > 1.5) {
          ctx.fillStyle = hexToRgba(ev.color, 0.13);
          ctx.fillRect(xStart, top, xEnd - xStart, bottom - top);
          ctx.strokeStyle = hexToRgba(ev.color, 0.45);
          ctx.lineWidth = 1;
          ctx.setLineDash([4, 4]);
          ctx.strokeRect(xStart, top, xEnd - xStart, bottom - top);
          ctx.setLineDash([]);
        } else {
          ctx.beginPath();
          ctx.moveTo(xStart, top);
          ctx.lineTo(xStart, bottom);
          ctx.strokeStyle = hexToRgba(ev.color, 0.75);
          ctx.lineWidth = 1.6;
          ctx.setLineDash([3, 3]);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Label, rotated so markers stay readable when several events fall
        // close together.
        var labelX = ev.is_range ? (xStart + xEnd) / 2 : xStart;
        if (labelX > left + 6 && labelX < right - 6 && hasRoom(labelX)) {
          drawnLabelX.push(labelX);
          ctx.translate(labelX, top + 6);
          ctx.rotate(-Math.PI / 2);
          ctx.textAlign = "right";
          ctx.font = "600 10px Inter, system-ui, sans-serif";
          ctx.fillStyle = ev.color;
          ctx.fillText(ev.label, -4, 3);
        }
        ctx.restore();
      });
    }
  };

  function wrapText(text, maxChars) {
    if (!text) return [];
    var limit = maxChars || 50;
    var words = String(text).split(" ");
    var lines = [];
    var currentLine = "";

    words.forEach(function (w) {
      if ((currentLine + (currentLine ? " " : "") + w).length > limit) {
        if (currentLine) lines.push(currentLine);
        currentLine = w;
      } else {
        currentLine += (currentLine ? " " : "") + w;
      }
    });
    if (currentLine) lines.push(currentLine);
    return lines;
  }

  function hexToRgba(hex, alpha) {
    var h = String(hex).replace("#", "");
    var r = parseInt(h.substring(0, 2), 16);
    var g = parseInt(h.substring(2, 4), 16);
    var b = parseInt(h.substring(4, 6), 16);
    return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
  }

  function track(name, params) {
    if (typeof window.trackEvent === "function") {
      window.trackEvent(name, params);
    } else if (typeof window.gtag === "function") {
      window.gtag("event", name, Object.assign({ page_path: location.pathname }, params || {}));
    }
  }

  // --- Tabs ---------------------------------------------------------------

  function switchTab(tabName) {
    root.querySelectorAll(".tab-btn").forEach(function (b) {
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    });
    root.querySelectorAll(".tab-content").forEach(function (c) { c.classList.remove("active"); });

    // Find the tab button by name rather than trusting whatever was clicked.
    // "Read full briefing →" is also a [data-tab] element: passing it through
    // marked a link as the selected tab and left the real tab bar showing
    // Dashboard while the Methodology panel was open.
    var btn = root.querySelector(".tab-btn[data-tab='" + tabName + "']");
    if (btn) {
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
    }
    var panel = $("tab-" + tabName);
    if (panel) panel.classList.add("active");

    // Chart.js sizes to a hidden container as 0x0. Re-measure whenever a panel
    // becomes visible so a chart drawn while hidden is not stuck collapsed.
    if (dailyChart) dailyChart.resize();

    track("report_tab_switch", {
      report_slug: "lok-sabha-index",
      tab_name: tabName,
      page_path: location.pathname
    });
  }

  // --- Theme --------------------------------------------------------------
  // The site header owns the toggle. Canvas cannot inherit CSS variables, so
  // the chart is rebuilt on the palette change — preserving the zoom window,
  // which a naive rebuild would throw away.

  document.addEventListener("themechange", function () {
    if (!globalForecastData) return;
    var prev = dailyChart ? { min: dailyChart.scales.x.min, max: dailyChart.scales.x.max } : null;
    renderDailyChart(globalForecastData);
    if (prev) dailyChart.zoomScale("x", prev, "none");
  });

  // Series drawn on the chart. Order here is the dataset order, and the
  // clickable legend is generated from it, so adding a line means adding one
  // entry rather than editing three places.
  var SERIES_SPEC = [
    { key: "NDA_proj_seats",        label: "NDA Projected",            color: "#FF9933", width: 2,   dash: null },
    { key: "INDIA_proj_seats",      label: "INDIA Projected",          color: "#00BFFF", width: 2,   dash: null },
    { key: "NDA_proj_seats_ma7",    label: "NDA 7D Avg",               color: "#FFD9A8", width: 1.6, dash: null },
    { key: "NDA_proj_seats_ma30",   label: "NDA 30D Avg",              color: "#B45309", width: 1.8, dash: [5, 3] },
    { key: "INDIA_proj_seats_ma7",  label: "INDIA 7D Avg",             color: "#A5E4FF", width: 1.6, dash: null },
    { key: "INDIA_proj_seats_ma30", label: "INDIA 30D Avg",            color: "#0369A1", width: 1.8, dash: [5, 3] },
    { key: null, constant: 293,     label: "2024 NDA (293)",           color: "#FF9933", width: 1.6, dash: [6, 6] },
    { key: null, constant: 234,     label: "2024 INDIA (234)",         color: "#00BFFF", width: 1.6, dash: [6, 6] },
    { key: null, constant: 272,     label: "Majority (272)",           color: "#EF4444", width: 1.5, dash: [2, 4] }
  ];

  // Datasets the user has hidden by clicking the legend, kept outside the
  // chart so a rebuild (theme switch, data refresh) preserves the choice.
  var hiddenSeries = new Set([4, 5]);
  var hiddenCategories = new Set();

  async function initDashboard() {
    bindControls();

    var preloadedEl = $("elections-preloaded");
    var preloadedData = null;
    if (preloadedEl) {
      try {
        preloadedData = JSON.parse(preloadedEl.textContent);
      } catch (err) {
        console.error("Failed to parse preloaded elections data:", err);
      }
    }

    try {
      var chartFields = SERIES_SPEC
        .filter(function (s) { return s.key; })
        .map(function (s) { return s.key; })
        .concat(["date"])
        .join(",");

      var fcPromise = fetch(API + "/daily_forecast?fields=" + chartFields).then(function (r) { return r.json(); });

      var ovData, taData, evData, btData, inData;

      if (preloadedData) {
        ovData = preloadedData.overview;
        taData = preloadedData.trend_analytics;
        evData = preloadedData.events || {};
        btData = preloadedData.backtest;
        inData = preloadedData.insights;
      } else {
        var primaryResponses = await Promise.all([
          fetch(API + "/overview"),
          fetch(API + "/trend_analytics"),
          fetch(API + "/events")
        ]);
        var primaryPayloads = await Promise.all(primaryResponses.map(function (r) { return r.json(); }));
        ovData = primaryPayloads[0];
        taData = primaryPayloads[1];
        evData = primaryPayloads[2];
      }

      globalEvents = evData.events || [];
      globalAnalytics = taData;

      renderKPIs(ovData, taData);
      renderSeriesLegend();
      renderEventLegend(evData.categories || []);

      if (btData) renderBacktest(btData);
      if (inData) renderInsights(inData);

      var fcData = await fcPromise;
      globalForecastData = fcData;
      renderDailyChart(fcData);

      if (!preloadedData) {
        Promise.all([
          fetch(API + "/backtest_results"),
          fetch(API + "/insights")
        ]).then(function (secResponses) {
          return Promise.all(secResponses.map(function (r) { return r.json(); }));
        }).then(function (secPayloads) {
          renderBacktest(secPayloads[0]);
          renderInsights(secPayloads[1]);
        }).catch(function (err) {
          console.error("Secondary data error:", err);
        });
      }
    } catch (err) {
      console.error("Dashboard init error:", err);
    }

    fetch(API + "/data_status?check_remote=0")
      .then(function (r) { return r.json(); })
      .then(renderFreshness)
      .catch(function (err) { console.error("Status check failed:", err); });
  }

  // --- Control wiring -----------------------------------------------------

  function bindControls() {
    root.querySelectorAll("[data-tab]").forEach(function (el) {
      el.addEventListener("click", function () { switchTab(el.getAttribute("data-tab")); });
    });

    root.querySelectorAll(".range-btn[data-range]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var raw = btn.getAttribute("data-range");
        setRange(raw === "all" ? "all" : parseInt(raw, 10), btn);
      });
    });

    var reset = $("btn-reset-zoom");
    if (reset) reset.addEventListener("click", resetZoom);

    var chk = $("chk-events");
    if (chk) chk.addEventListener("change", toggleEvents);

    var bar = $("chart-scrollbar");
    if (bar) bar.addEventListener("scroll", onChartScroll);

    // Redraw the scrollbar thumb when the viewport changes width; its size is
    // computed from the bar's pixel width.
    window.addEventListener("resize", syncScrollbar);
  }

  // --- KPI cards ----------------------------------------------------------

  function signed(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    var d = (digits === undefined) ? 0 : digits;
    return (v > 0 ? "+" : "") + Number(v).toFixed(d);
  }

  function deltaChip(label, value, digits, invert) {
    // invert=true means a negative number is the good direction; nothing here
    // uses it yet, but seat losses for the opposition read that way.
    var good = invert ? value < 0 : value > 0;
    var cls = (value === 0 || value === null) ? "d-flat" : (good ? "d-up" : "d-down");
    var arrow = (value === 0 || value === null) ? "" : (value > 0 ? "▲" : "▼");
    return '<span class="delta-chip ' + cls + '">' + arrow + " " +
      signed(value, digits) + ' <span class="d-label">' + label + "</span></span>";
  }

  function renderKPIs(ovData, analytics) {
    if (!ovData || !ovData.latest_forecast) return;

    var forecast = ovData.latest_forecast;
    var seats = forecast.point_estimate.predicted_seats;
    var ci = forecast.confidence_intervals;
    var prob = forecast.majority_probability;
    var series = (analytics && analytics.series) || {};

    var cards = [
      {
        valueId: "nda-seat-val", prefix: "nda", ciId: "nda-ci", badgeId: "nda-badge",
        seats: seats.NDA,
        lastElection: ovData.actual_2024_nda,
        ma30: series.NDA_proj_seats ? series.NDA_proj_seats.ma_30d : null,
        ci: ci.NDA,
        prob: prob.NDA
      },
      {
        valueId: "india-seat-val", prefix: "india", ciId: "india-ci", badgeId: "india-badge",
        seats: seats.INDIA,
        lastElection: ovData.actual_2024_india,
        ma30: series.INDIA_proj_seats ? series.INDIA_proj_seats.ma_30d : null,
        ci: ci.INDIA,
        prob: prob.INDIA
      }
    ];

    cards.forEach(function (card) {
      var valEl = $(card.valueId);
      if (valEl) valEl.innerText = card.seats;

      var vsLE = card.seats - card.lastElection;
      var vs30 = (card.ma30 === null || card.ma30 === undefined) ? null : card.seats - card.ma30;

      var vsleEl = $(card.prefix + "-delta-vsle");
      if (vsleEl) {
        var sign = vsLE >= 0 ? "+" : "";
        var iconSvg = vsLE >= 0
          ? '<svg width="12" height="12" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" fill-rule="evenodd"></path></svg>'
          : '<svg width="12" height="12" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z" fill-rule="evenodd"></path></svg>';
        vsleEl.className = "kpi-delta-val " + (vsLE >= 0 ? "kpi-delta-up" : "kpi-delta-down");
        vsleEl.innerHTML = iconSvg + " " + sign + vsLE;
      }

      var vs30El = $(card.prefix + "-delta-vs30");
      if (vs30El && vs30 !== null) {
        var sign30 = vs30 >= 0 ? "+" : "";
        var icon30 = vs30 >= 0
          ? '<svg width="12" height="12" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" fill-rule="evenodd"></path></svg>'
          : '<svg width="12" height="12" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" fill-rule="evenodd"></path></svg>';
        vs30El.className = "kpi-delta-val " + (vs30 >= 0 ? "kpi-delta-up" : "kpi-delta-down");
        vs30El.innerHTML = icon30 + " " + sign30 + vs30.toFixed(1);
      }

      var ciEl = $(card.ciId);
      if (ciEl) {
        ciEl.innerText = card.ci.p5 + "–" + card.ci.p95;
      }

      var badge = $(card.badgeId);
      if (badge) {
        var wins = card.seats >= ovData.majority_threshold;
        badge.className = "kpi-status-badge " + (wins ? "kpi-status-majority" : "kpi-status-short");
        badge.innerHTML = (wins ? '<svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" fill-rule="evenodd"></path></svg> MAJORITY (≥272)' : '<svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" fill-rule="evenodd"></path></svg> SHORT OF 272');
      }
    });

    var outcomes = [
      { name: "NDA MAJORITY", p: prob.NDA, color: "var(--accent-nda, #F97316)" },
      { name: "INDIA MAJORITY", p: prob.INDIA, color: "var(--accent-india, #2563EB)" },
      { name: "HUNG PARLIAMENT", p: prob.HUNG, color: "#16A34A" }
    ].sort(function (a, b) { return b.p - a.p; });

    var top = outcomes[0];
    var outcomeVal = $("outcome-val");
    if (outcomeVal) {
      outcomeVal.innerText = (top.p * 100).toFixed(0) + "%";
    }

    var outcomeBadge = $("outcome-badge");
    if (outcomeBadge) {
      outcomeBadge.innerText = top.name;
    }

    var alt1Val = $("outcome-alt1-val");
    if (alt1Val && outcomes[1]) {
      alt1Val.innerText = (outcomes[1].p * 100).toFixed(0) + "%";
    }

    var alt2Val = $("outcome-alt2-val");
    if (alt2Val && outcomes[2]) {
      alt2Val.innerText = (outcomes[2].p * 100).toFixed(0) + "%";
    }
  }

  // --- Clickable series legend --------------------------------------------

  function renderSeriesLegend() {
    var box = $("series-legend");
    if (!box) return;

    box.innerHTML = SERIES_SPEC.map(function (spec, i) {
      var off = hiddenSeries.has(i) ? " legend-off" : "";
      var pill = spec.dash
        ? '<div class="color-pill dashed" style="background:' + spec.color + '"></div>'
        : '<div class="color-pill" style="background:' + spec.color + '"></div>';
      return '<div class="legend-item clickable' + off + '" data-series="' + i + '" ' +
        'title="Click to show or hide this line">' + pill + " " + spec.label + "</div>";
    }).join("");

    box.querySelectorAll("[data-series]").forEach(function (el) {
      el.addEventListener("click", function () {
        toggleSeries(parseInt(el.getAttribute("data-series"), 10));
      });
    });
  }

  function toggleSeries(index) {
    var spec = SERIES_SPEC[index];
    var isHiddenNow = !hiddenSeries.has(index);
    if (hiddenSeries.has(index)) hiddenSeries.delete(index);
    else hiddenSeries.add(index);

    if (dailyChart) {
      dailyChart.data.datasets[index].hidden = hiddenSeries.has(index);
      // Rescale: the removed series may have been what set the bounds.
      autoscaleY();
    }
    renderSeriesLegend();

    track("chart_series_toggle", {
      series_name: spec ? spec.label : "Series " + index,
      series_index: index,
      action: isHiddenNow ? "hide" : "show",
      page_path: location.pathname
    });
  }

  function toggleEvents() {
    showEvents = $("chk-events").checked;
    if (dailyChart) dailyChart.update("none");
    track("chart_events_toggle", {
      show_events: showEvents,
      page_path: location.pathname
    });
  }

  function renderEventLegend(categories) {
    var box = $("event-legend");
    if (!box) return;
    globalEventCategories = categories;

    box.innerHTML = '<strong style="color:var(--text-main)">Events (click to hide):</strong> ' +
      categories.map(function (c) {
        var off = hiddenCategories.has(c.name) ? " legend-off" : "";
        return '<span class="ev-chip clickable' + off + '" data-category="' + escapeAttr(c.name) + '">' +
          '<span class="ev-dot" style="background:' + c.color + '"></span>' + c.name + "</span>";
      }).join("");

    box.querySelectorAll("[data-category]").forEach(function (el) {
      el.addEventListener("click", function () { toggleCategory(el.getAttribute("data-category")); });
    });
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  function toggleCategory(name) {
    var isHiddenNow = !hiddenCategories.has(name);
    if (hiddenCategories.has(name)) hiddenCategories.delete(name);
    else hiddenCategories.add(name);
    renderEventLegend(globalEventCategories);
    if (dailyChart) dailyChart.update("none");
    track("chart_event_filter", {
      category_name: name,
      action: isHiddenNow ? "hide" : "show",
      page_path: location.pathname
    });
  }

  function renderDailyChart(data) {
    var canvas = $("dailyForecastChart");
    if (!canvas || !data || !data.length) return;
    var ctx = canvas.getContext("2d");

    if (dailyChart) dailyChart.destroy();

    // One palette for both dashboards; see window.MDL.chartPalette in theme.js.
    // This chart used to carry its own slightly different grid alpha, tick
    // colour and tooltip chrome, which is what made it look like it came from a
    // different site than the Hormuz trajectory chart.
    var p = (window.MDL && window.MDL.chartPalette) ? window.MDL.chartPalette() : {
      text: "#94A3B8", grid: "rgba(255,255,255,0.08)", tooltipBg: "#0F172A",
      tooltipBorder: "#334155", tooltipText: "#F8FAFC",
      tickFont: "JetBrains Mono, monospace", labelFont: "Inter, system-ui, sans-serif",
      tickSize: 11
    };
    var gridColor = p.grid;
    var tickColor = p.text;
    var tooltipBg = p.tooltipBg;
    var tooltipText = p.tooltipText;

    // The x axis is a real time scale, so each point carries its own timestamp
    // and zoom windows are date ranges, not row offsets.
    var stamps = data.map(function (d) { return new Date(d.date).getTime(); });
    fullRange = { min: stamps[0], max: stamps[stamps.length - 1] };

    var datasets = SERIES_SPEC.map(function (spec, i) {
      return {
        label: spec.label,
        data: spec.key
          ? data.map(function (d, j) { return { x: stamps[j], y: d[spec.key] }; })
          : data.map(function (d, j) { return { x: stamps[j], y: spec.constant }; }),
        borderColor: spec.color,
        borderWidth: spec.width,
        borderDash: spec.dash || undefined,
        pointRadius: 0,
        fill: false,
        tension: spec.key ? 0.15 : 0,
        hidden: hiddenSeries.has(i)
      };
    });

    dailyChart = new Chart(ctx, {
      type: "line",
      plugins: [eventOverlayPlugin],
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        parsing: false,
        normalized: true,
        interaction: { mode: "index", intersect: false, axis: "x" },
        plugins: {
          legend: { display: false },
          decimation: { enabled: true, algorithm: "lttb", samples: 900 },
          tooltip: {
            backgroundColor: tooltipBg,
            titleColor: tooltipText,
            bodyColor: tooltipText,
            borderColor: p.tooltipBorder,
            borderWidth: 1,
            padding: 10,
            boxPadding: 4,
            cornerRadius: 8,
            titleFont: { family: p.labelFont, size: 12, weight: '700' },
            bodyFont: { family: p.tickFont, size: 11 },
            // Nine series at once makes the tooltip unreadable. Two things are
            // dropped: anything the user has hidden via the legend, and the
            // flat reference lines, whose values never change and are already
            // named in the legend.
            filter: function (item) {
              if (!dailyChart.isDatasetVisible(item.datasetIndex)) return false;
              var spec = SERIES_SPEC[item.datasetIndex];
              return !!(spec && spec.key);
            },
            callbacks: {
              title: function (items) {
                return items.length ? new Date(items[0].parsed.x).toISOString().slice(0, 10) : "";
              },
              // Surface any event on the hovered date, cleanly wrapped into lines
              // so long event descriptions never spill horizontally over the box.
              afterBody: function (items) {
                if (!items.length || !showEvents) return [];
                var day = new Date(items[0].parsed.x).toISOString().slice(0, 10);
                var hits = visibleEvents().filter(function (ev) {
                  return day >= ev.date && day <= (ev.end_date || ev.date);
                });
                if (!hits.length) return [];

                var lines = [""];
                hits.forEach(function (ev) {
                  var titleText = "📌 " + ev.label;
                  var descText = ev.description || "";
                  lines = lines.concat(wrapText(titleText, 45));
                  if (descText) {
                    lines = lines.concat(wrapText(descText, 48));
                  }
                });
                return lines;
              }
            }
          },
          zoom: {
            pan: { enabled: true, mode: "x", onPanComplete: afterViewportChange },
            zoom: {
              wheel: { enabled: true, speed: 0.08 },
              pinch: { enabled: true },
              drag: { enabled: false },
              mode: "x",
              onZoomComplete: afterViewportChange
            },
            limits: {
              // Do not let the user zoom past a single week or pan outside the
              // data range.
              x: { min: fullRange.min, max: fullRange.max, minRange: 7 * 24 * 3600 * 1000 }
            }
          }
        },
        scales: {
          x: {
            type: "time",
            time: {
              unit: "month",
              tooltipFormat: "yyyy-MM-dd",
              displayFormats: { day: "dd MMM yy", month: "MMM yy", year: "yyyy" }
            },
            grid: { color: gridColor },
            ticks: { color: tickColor, font: { family: p.tickFont, size: p.tickSize }, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }
          },
          y: {
            grid: { color: gridColor },
            ticks: { color: tickColor, font: { family: p.tickFont, size: p.tickSize } },
            title: { display: true, text: "Projected seats (of 543)", color: tickColor, font: { family: p.labelFont, size: 12 } },
            // Bounds are set by autoscaleY() from whatever is actually on
            // screen. A fixed 225–310 window wasted most of the plot area
            // whenever the user narrowed to one series or zoomed into a few
            // months: a 2-seat move inside an 85-seat window is a flat line.
            min: undefined,
            max: undefined
          }
        }
      }
    });

    autoscaleY(false);
    dailyChart.update("none");
    syncScrollbar();
  }

  // --- Y-axis autoscaling -------------------------------------------------
  //
  // The y bounds follow what is actually visible: only the series left on by
  // the legend, and only their points inside the current x window. Hiding
  // every line but "Projected NDA seats" and zooming to 30 days should fill
  // the plot with those 30 days, not leave them as a flat trace across a
  // window sized for the 234–293 reference lines.
  //
  // Called after every action that changes either of those two inputs:
  // build, legend toggle, range button, reset, zoom, pan, scrollbar drag.

  var Y_PAD_FRACTION = 0.06;   // headroom above and below, as a share of span
  var Y_MIN_SPAN = 1.0;        // tight minimum span (1 seat) so subtle moves fill available height

  function autoscaleY(update) {
    if (!dailyChart || !globalForecastData) return;

    var x = dailyChart.scales.x;
    if (!x) return;
    var lo = (x && isFinite(x.min)) ? x.min : (fullRange ? fullRange.min : -Infinity);
    var hi = (x && isFinite(x.max)) ? x.max : (fullRange ? fullRange.max : Infinity);

    var min = Infinity;
    var max = -Infinity;

    dailyChart.data.datasets.forEach(function (ds, i) {
      if (hiddenSeries.has(i) || ds.hidden) return;
      var spec = SERIES_SPEC[i];

      // A reference line is a single constant; it has no points worth
      // scanning, but while it is visible it must stay inside the window or
      // the user has hidden it for nothing.
      if (spec && !spec.key) {
        if (spec.constant < min) min = spec.constant;
        if (spec.constant > max) max = spec.constant;
        return;
      }

      ds.data.forEach(function (pt) {
        if (!pt || pt.x < lo || pt.x > hi) return;
        var y = pt.y;
        if (y === null || y === undefined || Number.isNaN(y)) return;
        if (y < min) min = y;
        if (y > max) max = y;
      });
    });

    // Nothing visible, or nothing inside the window: leave the axis alone
    // rather than collapsing it to an empty range.
    if (!isFinite(min) || !isFinite(max)) return;

    var span = max - min;
    if (span <= 0) {
      min = min - 0.5;
      max = max + 0.5;
      span = 1.0;
    } else if (span < Y_MIN_SPAN) {
      var mid = (max + min) / 2;
      min = mid - Y_MIN_SPAN / 2;
      max = mid + Y_MIN_SPAN / 2;
      span = Y_MIN_SPAN;
    }

    var pad = Math.max(0.4, span * Y_PAD_FRACTION);
    var computedMin = Math.max(0, Math.floor(min - pad));
    var computedMax = Math.min(543, Math.ceil(max + pad));

    if (computedMax <= computedMin) {
      computedMax = Math.min(543, computedMin + 2);
    }

    dailyChart.options.scales.y.min = computedMin;
    dailyChart.options.scales.y.max = computedMax;

    if (update !== false) dailyChart.update("none");
  }

  // Every viewport change moves both the scrollbar thumb and the y bounds.
  // Zoom and pan report through here so the two can never disagree.
  function afterViewportChange() {
    autoscaleY();
    syncScrollbar();
    track("chart_pan_zoom", {
      chart_id: "dailyForecastChart",
      page_path: location.pathname
    });
  }

  // --- Chart controls -----------------------------------------------------

  function setRange(days, btn) {
    if (!dailyChart || !globalForecastData || !globalForecastData.length) return;

    root.querySelectorAll(".range-btn[data-range]").forEach(function (b) { b.classList.remove("active"); });
    if (btn) btn.classList.add("active");

    track("chart_range_select", {
      range_value: String(days),
      chart_name: "lok_sabha_daily_forecast",
      page_path: location.pathname
    });

    if (days === "all") {
      dailyChart.resetZoom();
      afterViewportChange();
      return;
    }
    var fromMs = Math.max(fullRange.min, fullRange.max - days * 24 * 3600 * 1000);
    dailyChart.zoomScale("x", { min: fromMs, max: fullRange.max }, "none");
    afterViewportChange();
  }

  function resetZoom() {
    if (!dailyChart) return;
    dailyChart.resetZoom();
    root.querySelectorAll(".range-btn[data-range]").forEach(function (b) { b.classList.remove("active"); });
    var allBtn = root.querySelector('.range-btn[data-range="all"]');
    if (allBtn) allBtn.classList.add("active");
    afterViewportChange();

    track("chart_reset_zoom", {
      chart_name: "lok_sabha_daily_forecast",
      page_path: location.pathname
    });
  }

  // --- Horizontal scrollbar -----------------------------------------------
  //
  // A native scrollbar is easier to grab than a drag-pan, especially on a
  // trackpad. The inner spacer is sized so that the thumb takes up the same
  // fraction of the bar as the visible window takes of the full date range;
  // scrolling it maps back onto the chart's x window. The suppressScrollSync
  // flag stops the two from fighting each other when a programmatic update
  // triggers the scroll handler.

  function syncScrollbar() {
    var bar = $("chart-scrollbar");
    var inner = $("chart-scrollbar-inner");
    var readout = $("scroll-readout");
    if (!bar || !inner || !dailyChart || !fullRange) return;

    var x = dailyChart.scales.x;
    var total = fullRange.max - fullRange.min;
    var visible = x.max - x.min;
    var fraction = Math.min(1, Math.max(0.001, visible / total));

    suppressScrollSync = true;
    inner.style.width = (bar.clientWidth / fraction) + "px";
    var scrollable = inner.offsetWidth - bar.clientWidth;
    var offset = total > visible ? (x.min - fullRange.min) / (total - visible) : 0;
    bar.scrollLeft = scrollable * offset;
    // Release on the next frame: setting scrollLeft fires onscroll async.
    requestAnimationFrame(function () { suppressScrollSync = false; });

    if (readout) {
      readout.innerText = fraction >= 0.999
        ? "Showing the full range: " +
          new Date(fullRange.min).toISOString().slice(0, 10) + " to " +
          new Date(fullRange.max).toISOString().slice(0, 10)
        : "Showing " + new Date(x.min).toISOString().slice(0, 10) + " to " +
          new Date(x.max).toISOString().slice(0, 10) +
          "  (" + (fraction * 100).toFixed(1) + "% of the full range)";
    }
  }

  function onChartScroll() {
    if (suppressScrollSync || !dailyChart || !fullRange) return;

    var bar = $("chart-scrollbar");
    var inner = $("chart-scrollbar-inner");
    var scrollable = inner.offsetWidth - bar.clientWidth;
    if (scrollable <= 0) return;

    var x = dailyChart.scales.x;
    var visible = x.max - x.min;
    var total = fullRange.max - fullRange.min;
    var offset = bar.scrollLeft / scrollable;

    var newMin = fullRange.min + offset * (total - visible);
    dailyChart.zoomScale("x", { min: newMin, max: newMin + visible }, "none");
    autoscaleY();

    var readout = $("scroll-readout");
    if (readout) {
      readout.innerText = "Showing " + new Date(newMin).toISOString().slice(0, 10) +
        " to " + new Date(newMin + visible).toISOString().slice(0, 10) +
        "  (" + ((visible / total) * 100).toFixed(1) + "% of the full range)";
    }
  }

  // --- Data freshness -----------------------------------------------------

  function renderFreshness(status) {
    var pill = $("freshness-pill");
    if (!pill) return;
    pill.classList.remove("stale", "error");
    if (status.is_stale === null || status.remote_error) {
      pill.classList.add("error");
      pill.innerHTML = '<span class="dot"></span>Data through ' +
        (status.local_latest_date || "—") + " (source unreachable)";
    } else if (status.is_stale) {
      pill.classList.add("stale");
      pill.innerHTML = '<span class="dot"></span>Data through ' +
        status.local_latest_date + " (" + status.days_behind + " day(s) behind source)";
    } else {
      pill.innerHTML = '<span class="dot"></span>Current through ' + status.local_latest_date;
    }
  }

  // --- Backtest -----------------------------------------------------------

  function renderBacktest(bt) {
    var summary = $("backtest-summary");
    var matrix = $("backtest-matrix");
    if (!summary || !matrix || !bt) return;

    var overall = (bt.overall_mae === null || bt.overall_mae === undefined)
      ? "—" : bt.overall_mae.toFixed(2);
    summary.innerHTML =
      '<div class="metric-tile" style="display:inline-block; min-width:220px;">' +
      '<div class="m-label">Overall mean absolute error</div>' +
      '<div class="m-value">' + overall +
      ' <span style="font-size:14px; font-weight:500; color:var(--text-muted)">seats</span></div>' +
      '<div class="m-sub">averaged across alliances and elections</div>' +
      "</div>";

    matrix.innerHTML = "";
    ["2019", "2024"].forEach(function (year) {
      var res = bt[year];
      if (!res) return;

      var rows = ["NDA", "INDIA", "OTHERS"].map(function (alliance) {
        var pred = res.predicted_seats[alliance];
        var actual = res.actual_seats[alliance];
        var diff = pred - actual;
        var label = (year === "2019" && alliance === "INDIA") ? "UPA alliance"
          : (alliance === "OTHERS" ? "Non-aligned / regional" : alliance);
        var color = Math.abs(diff) <= 10 ? "#10B981" : (Math.abs(diff) <= 30 ? "#F59E0B" : "#EF4444");
        return "<tr><td>" + label + "</td>" +
          "<td><strong>" + pred + "</strong></td>" +
          "<td>" + actual + "</td>" +
          '<td><span style="color:' + color + '">' +
          (diff > 0 ? "+" : "") + diff + " seats</span></td></tr>";
      }).join("");

      var vote = res.projected_vote_share
        ? "Projected NDA vote share " + res.projected_vote_share.NDA + "%"
        : "";

      matrix.insertAdjacentHTML("beforeend",
        '<div class="backtest-card">' +
        '<div class="backtest-title">' +
        "<span>" + year + " Lok Sabha election</span>" +
        '<span class="badge badge-nda">MAE ' + res.mae.toFixed(1) + "</span>" +
        "</div>" +
        '<div class="table-scroll"><table class="table-custom">' +
        "<thead><tr><th>Alliance</th><th>Predicted</th><th>Actual</th><th>Difference</th></tr></thead>" +
        "<tbody>" + rows + "</tbody></table></div>" +
        '<div style="font-size:11.5px; color:var(--text-muted); margin-top:10px;">' +
        "Survey window " + (res.window || "—") + " · composite " +
        (res.composite_sentiment === undefined || res.composite_sentiment === null
          ? "—" : (res.composite_sentiment > 0 ? "+" : "") + res.composite_sentiment.toFixed(1)) +
        (vote ? " · " + vote : "") +
        "</div></div>");
    });
  }

  // --- Insights: impact tables + executive summary ------------------------

  function renderInsights(data) {
    if (!data) return;
    renderImpacts(data.impacts);
    renderSummary(data.summary);
  }

  function eventColor(category) {
    var match = globalEventCategories.find(function (c) { return c.name === category; });
    return match ? match.color : "var(--text-muted)";
  }

  function whenLabel(row) {
    var fmt = function (iso) {
      var d = new Date(iso);
      return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    };
    if (!row.end_date) {
      var d = new Date(row.date);
      return fmt(row.date) + " " + d.getFullYear();
    }
    var y0 = new Date(row.date).getFullYear();
    var y1 = new Date(row.end_date).getFullYear();
    return y0 === y1
      ? fmt(row.date) + " – " + fmt(row.end_date) + " " + y1
      : fmt(row.date) + " " + y0 + " – " + fmt(row.end_date) + " " + y1;
  }

  function impactRows(rows, positive) {
    if (!rows || !rows.length) {
      return '<tr><td colspan="5" style="color:var(--text-muted)">Nothing scored in this direction.</td></tr>';
    }
    var color = positive ? "#10B981" : "#EF4444";

    return rows.map(function (row) {
      var partial = row.partial
        ? ' <span class="pill-partial" title="Post-window truncated by the end of the data; ' +
          row.post_days_used + ' days used">partial</span>' : "";
      var noise = row.within_noise
        ? ' <span class="pill-noise" title="Move is smaller than this series normal 30-day ' +
          'drift, so it is not distinguishable from ordinary wandering">within noise</span>' : "";
      var confounders = row.confounded_by && row.confounded_by.length
        ? "Overlaps: " + row.confounded_by.slice(0, 3).join(", ") +
          (row.confounded_by.length > 3 ? " +" + (row.confounded_by.length - 3) + " more" : "")
        : "No overlapping events";

      return "<tr" + (row.within_noise ? ' class="row-noise"' : "") + ">" +
        '<td><span class="ev-dot" style="background:' + eventColor(row.category) + '"></span>' +
        '<span class="impact-label">' + row.label + "</span>" + partial + noise +
        '<span class="impact-note">' + confounders + "</span></td>" +
        '<td style="white-space:nowrap">' + whenLabel(row) + "</td>" +
        '<td class="num" style="color:' + color + '">' + signed(row.impact_seats, 1) + "</td>" +
        '<td class="num" style="color:' + color + '">' +
        (row.impact_composite === null ? "—" : signed(row.impact_composite, 1)) + "</td>" +
        '<td class="num">' + (row.z === null ? "—" : signed(row.z, 2)) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderImpacts(impacts) {
    if (!impacts) return;

    $("impact-positive").innerHTML = impactRows(impacts.positive, true);
    $("impact-negative").innerHTML = impactRows(impacts.negative, false);

    var m = impacts.method;
    $("impact-method").innerText =
      "Mean projected NDA seats from each incident’s start through " + m.post_days +
      " days after it ended, minus the " + m.pre_days + " days before it began. " +
      impacts.evaluated + " incidents scored, " + impacts.reported + " reportable.";

    var ex = impacts.excluded || {};
    var reasons = [];
    if (ex.elections) reasons.push(ex.elections +
      " general elections (the projection predicts elections, so scoring them just returns the campaign swing)");
    if (ex.contradicts_nature) reasons.push(ex.contradicts_nature +
      " whose measured move ran opposite to the nature of the event, which makes them unattributable rather than a finding");
    if (ex.below_noise_floor) reasons.push(ex.below_noise_floor +
      " too small to separate from ordinary drift");
    $("impact-excluded").innerHTML = reasons.length
      ? " <strong>Excluded:</strong> " + reasons.join("; ") + "."
      : "";
  }

  function renderSummary(summary) {
    if (!summary) return;

    var asOf = $("dash-asof");
    if (asOf) asOf.innerText = "Survey data through " + summary.as_of_date + ".";

    $("summary-asof").innerText =
      "Position as of " + summary.as_of_date + ". All figures below are computed from the " +
      "same series the chart draws.";

    $("summary-headlines").innerHTML =
      summary.headlines.map(function (h) { return "<li>" + h + "</li>"; }).join("");

    var driverItems = function (list, sign) {
      if (!list || !list.length) return "<li>None recorded.</li>";
      return list.map(function (d) {
        return "<li><strong>" + d.metric + "</strong> — " + d.share.toFixed(1) +
          '% of respondents, <span class="driver-val" style="color:' +
          (sign > 0 ? "#10B981" : "#EF4444") + '">' +
          signed(d.contribution, 1) + "</span> index points</li>";
      }).join("");
    };

    $("drivers-negative").innerHTML = driverItems(summary.drivers.negative, -1);
    $("drivers-positive").innerHTML = driverItems(summary.drivers.positive, 1);

    $("summary-caveats").innerHTML =
      summary.caveats.map(function (c) { return "<li>" + c + "</li>"; }).join("");
  }

  initDashboard();
})();
