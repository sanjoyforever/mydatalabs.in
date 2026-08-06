/* HMX-INDEX dashboard charts.
 *
 * Chart data is passed in a JSON <script> block rather than interpolated into
 * JS literals, so template values can never break the script or open an
 * injection path.
 *
 * Every chart is built from a factory that reads the current theme at call
 * time and re-runs on "themechange", because canvas cannot inherit CSS
 * variables — previously the palette was read once on load and toggling to
 * light mode left the charts dark until a reload.
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("hmx-chart-data");
  if (!dataEl) return;

  var DATA;
  try {
    DATA = JSON.parse(dataEl.textContent);
  } catch (err) {
    return;
  }

  var charts = [];

  // Shared with the projection dashboard's Chart.js charts; defined in theme.js
  // so the two engines cannot drift apart. The fallback keeps this file working
  // if theme.js ever fails to load.
  function palette() {
    if (window.MDL && window.MDL.chartPalette) return window.MDL.chartPalette();
    var isDark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
      isDark: isDark,
      text: isDark ? "#94A3B8" : "#475569",
      grid: isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)",
      tooltipBg: isDark ? "#0F172A" : "#FFFFFF",
      tooltipBorder: isDark ? "#334155" : "#E2E8F0",
      tooltipText: isDark ? "#F8FAFC" : "#0F172A",
      tickFont: "JetBrains Mono, monospace",
      labelFont: "Inter, system-ui, sans-serif",
      tickSize: 11,
      blue: isDark ? "#38BDF8" : "#0284C7",
      red: isDark ? "#EF4444" : "#DC2626",
      green: isDark ? "#10B981" : "#059669",
      greenText: isDark ? "#34D399" : "#047857",
      violet: isDark ? "#A78BFA" : "#7C3AED"
    };
  }

  function tooltipBase(p) {
    return {
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText }
    };
  }

  function clearFallback(dom) {
    var fallback = dom.querySelector(".chart-fallback");
    if (fallback) fallback.remove();
  }

  function failFallback(dom, message) {
    var fallback = dom.querySelector(".chart-fallback");
    if (fallback) fallback.textContent = message;
  }

  /* Registers a chart: builds it now, rebuilds it on theme change, and keeps
   * it sized to its container. */
  function register(domId, buildOption) {
    var dom = document.getElementById(domId);
    if (!dom) return;

    if (typeof echarts === "undefined") {
      failFallback(dom, "Chart library could not be loaded. The figures are in the data table below.");
      return;
    }

    var instance;
    try {
      instance = echarts.init(dom);
      instance.setOption(buildOption(palette()));
    } catch (err) {
      failFallback(dom, "This chart could not be drawn. The figures are in the data table below.");
      return;
    }

    clearFallback(dom);
    charts.push({ instance: instance, build: buildOption });

    // Charts inside a closed <details> render at zero width; resize once the
    // container has real dimensions.
    if (window.ResizeObserver) {
      new ResizeObserver(function () { instance.resize(); }).observe(dom);
    }
    setTimeout(function () { instance.resize(); }, 100);
  }

  window.addEventListener("resize", function () {
    charts.forEach(function (c) { c.instance.resize(); });
  });

  document.addEventListener("themechange", function () {
    var p = palette();
    charts.forEach(function (c) {
      c.instance.setOption(c.build(p), true);
    });
  });

  // --- 1. Weekly trend trajectory -----------------------------------------
  register("echart-trend-container", function (p) {
    var truceLines = (DATA.trend.ceasefires || []).map(function (d) {
      return {
        xAxis: d,
        lineStyle: { color: p.green, type: "dotted", width: 2 },
        label: { formatter: "Truce", position: "insideStartTop", color: p.greenText, fontSize: 10, fontWeight: "bold" }
      };
    });

    // Reader perception rides the same axis as the model. Weeks with no
    // publishable vote count arrive as nulls; connectNulls stays off so the
    // line breaks there instead of interpolating an opinion nobody gave.
    var perception = DATA.trend.perception || [];
    var hasPerception = perception.some(function (v) { return v !== null && v !== undefined; });

    return {
      backgroundColor: "transparent",
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      tooltip: Object.assign({
        trigger: "axis",
        formatter: function (params) {
          var rows = params.map(function (s) {
            var v = (s.value === null || s.value === undefined) ? "no votes" : s.value;
            return s.seriesName + ": <strong>" + v + "</strong>";
          });
          return "<strong>Week of " + params[0].name + "</strong><br/>" + rows.join("<br/>");
        }
      }, tooltipBase(p)),
      grid: { top: 35, right: 30, bottom: 45, left: 55 },
      xAxis: {
        type: "category",
        data: DATA.trend.dates,
        axisLine: { lineStyle: { color: p.grid } },
        axisLabel: { color: p.text, fontSize: p.tickSize, fontFamily: p.tickFont }
      },
      yAxis: {
        type: "value",
        scale: true,
        min: 95,
        max: function (v) { return Math.ceil(v.max + 10); },
        splitLine: { lineStyle: { color: p.grid } },
        axisLabel: { color: p.text, fontSize: p.tickSize, fontFamily: p.tickFont }
      },
      series: [{
        name: "HMX-INDEX",
        type: "line",
        smooth: true,
        symbolSize: 7,
        itemStyle: { color: p.blue },
        lineStyle: { width: 3, color: p.blue },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: p.isDark ? "rgba(56,189,248,0.35)" : "rgba(2,132,199,0.28)" },
            { offset: 1, color: "rgba(56,189,248,0.0)" }
          ])
        },
        markLine: {
          symbol: ["none", "none"],
          data: [{
            yAxis: 100.0,
            lineStyle: { color: p.text, type: "dashed", width: 1.5 },
            label: { formatter: "Baseline 100.0", position: "insideEndTop", color: p.text, fontSize: 10 }
          }].concat(truceLines)
        },
        data: DATA.trend.scores
      }].concat(hasPerception ? [{
        name: "Public Perception",
        type: "line",
        smooth: true,
        symbolSize: 6,
        connectNulls: false,
        itemStyle: { color: p.violet },
        lineStyle: { width: 2, color: p.violet, type: "dashed" },
        data: perception
      }] : [])
    };
  });

  // --- 2. Incidents by flag state -----------------------------------------
  register("echart-country-container", function (p) {
    return {
      backgroundColor: "transparent",
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      tooltip: Object.assign({
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: "{b}: <strong>{c} modelled incidents</strong>"
      }, tooltipBase(p)),
      // left was sized for old "emoji + full country name" labels; codes are
      // two characters, so the axis only needs enough room for that.
      grid: { top: 15, right: 40, bottom: 25, left: 46 },
      xAxis: {
        type: "value",
        minInterval: 1,
        splitLine: { lineStyle: { color: p.grid } },
        axisLabel: { color: p.text, fontSize: p.tickSize, fontFamily: p.tickFont }
      },
      yAxis: {
        type: "category",
        data: (DATA.flags.countries || []).slice().reverse(),
        axisLine: { lineStyle: { color: p.grid } },
        axisLabel: { color: p.text, fontSize: p.tickSize, fontFamily: p.tickFont, fontWeight: "bold" },
        axisTick: { show: false }
      },
      series: [{
        type: "bar",
        data: (DATA.flags.counts || []).slice().reverse(),
        itemStyle: { borderRadius: [0, 4, 4, 0], color: p.red },
        label: { show: true, position: "right", color: p.text, fontWeight: "bold" }
      }]
    };
  });

  // --- 3. Cumulative incidents by month ------------------------------------
  register("echart-month-container", function (p) {
    var counts = DATA.months.cumulative || [];
    var top = counts.length ? Math.ceil((Math.max.apply(null, counts) * 1.15) / 10) * 10 : 10;

    return {
      backgroundColor: "transparent",
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      tooltip: Object.assign({
        trigger: "axis",
        formatter: "{b}: <strong>{c} modelled incidents to date</strong>"
      }, tooltipBase(p)),
      grid: { top: 30, right: 30, bottom: 45, left: 40 },
      xAxis: {
        type: "category",
        data: DATA.months.labels,
        axisLine: { lineStyle: { color: p.grid } },
        axisLabel: { color: p.text, fontSize: p.tickSize, fontFamily: p.tickFont }
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        max: top,
        splitLine: { lineStyle: { color: p.grid } },
        axisLabel: { color: p.text, fontSize: p.tickSize, fontFamily: p.tickFont }
      },
      series: [{
        name: "Cumulative modelled incidents",
        type: "line",
        smooth: true,
        symbolSize: 8,
        itemStyle: { color: p.red },
        lineStyle: { width: 3, color: p.red },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(239,68,68,0.4)" },
            { offset: 1, color: "rgba(239,68,68,0.0)" }
          ])
        },
        label: { show: true, position: "top", color: p.red, fontWeight: "bold" },
        data: counts
      }]
    };
  });
})();
