(function () {
  "use strict";

  var root = document.documentElement;

  // --- Analytics -------------------------------------------------------
  // Safe GA4 tracking wrapper — delegates to global window.trackEvent or gtag
  function track(name, params) {
    if (typeof window.trackEvent === "function") {
      window.trackEvent(name, params);
    } else if (typeof window.gtag === "function") {
      window.gtag("event", name, Object.assign({ page_path: location.pathname }, params || {}));
    }
  }

  function currentTheme() {
    return root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

  // --- Shared chart palette ------------------------------------------------
  // The two dashboards draw with different engines — ECharts on /hormuz-index,
  // Chart.js on /lok-sabha-index — and each used to carry its own grid colour,
  // tick colour, tooltip chrome and label font. Small divergences (0.06 vs 0.08
  // grid alpha, #64748B vs #475569 ticks, Inter vs JetBrains Mono numerals) are
  // exactly what made two otherwise identical layouts read as two products.
  // One source of truth; both engines map it to their own option names.
  //
  // Canvas and ECharts cannot read CSS custom properties, which is why these
  // are literals here rather than var(--grid-color) — but they are the same
  // values style.css uses, and both charts rebuild on `themechange`.
  window.MDL = window.MDL || {};
  window.MDL.chartPalette = function () {
    var isDark = currentTheme() !== "light";
    return {
      isDark: isDark,
      // Axis labels and other chart text.
      text: isDark ? "#94A3B8" : "#475569",
      // Grid lines, axis lines and tooltip borders.
      grid: isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)",
      tooltipBg: isDark ? "#0F172A" : "#FFFFFF",
      tooltipBorder: isDark ? "#334155" : "#E2E8F0",
      tooltipText: isDark ? "#F8FAFC" : "#0F172A",
      // Numerals are monospaced on both charts so columns of figures line up
      // the way they do in every table on the site.
      tickFont: "JetBrains Mono, monospace",
      labelFont: "Inter, system-ui, sans-serif",
      tickSize: 11,
      // Series colours shared by both dashboards.
      blue: isDark ? "#38BDF8" : "#0284C7",
      red: isDark ? "#EF4444" : "#DC2626",
      green: isDark ? "#10B981" : "#059669",
      greenText: isDark ? "#34D399" : "#047857",
      violet: isDark ? "#A78BFA" : "#7C3AED"
    };
  };

  // --- Theme toggle --------------------------------------------------------
  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.setAttribute("aria-pressed", currentTheme() === "dark" ? "true" : "false");

    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) { /* private mode */ }
      toggle.setAttribute("aria-pressed", next === "dark" ? "true" : "false");
      // Canvas-rendered charts cannot inherit CSS variables, so they have to be
      // told to rebuild with the new palette.
      document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
      track("theme_toggle", { theme: next });
    });
  }

  // --- Navigation Clicks ---------------------------------------------------
  document.addEventListener("click", function (e) {
    var navLink = e.target.closest ? e.target.closest(".site-nav a, .footer-links a, .brand") : null;
    if (!navLink || !navLink.href) return;
    var isFooter = !!navLink.closest(".site-footer");
    var isHeader = !!navLink.closest(".site-header");
    track("nav_click", {
      nav_label: (navLink.textContent || "").trim(),
      nav_target: navLink.getAttribute("href"),
      nav_location: isHeader ? "header" : (isFooter ? "footer" : "body")
    });
  });

  // --- Data Download Clicks ------------------------------------------------
  document.addEventListener("click", function (e) {
    var link = e.target.closest ? e.target.closest("[data-track-download], a[href*='.csv'], a[href*='.json']") : null;
    if (!link) return;
    var href = link.getAttribute("href") || link.getAttribute("data-href") || "";
    if (href.endsWith(".csv") || href.endsWith(".json") || link.hasAttribute("data-track-download")) {
      var filename = href.split("/").pop() || href;
      var ext = filename.split(".").pop() || "file";
      track("file_download", {
        file_name: filename,
        file_extension: ext,
        link_url: href,
        dataset_name: link.getAttribute("data-dataset") || "HMX-INDEX"
      });
    }
  });

  // --- Categories dropdown -------------------------------------------------
  // Previously CSS :hover / :focus-within only, which left keyboard users
  // unable to open it: the button had no handler, so Enter and Space did
  // nothing and Escape could not close it.
  var dropdowns = Array.prototype.slice.call(document.querySelectorAll(".dropdown"));

  function closeDropdown(dd) {
    dd.classList.remove("is-open");
    var btn = dd.querySelector(".dropdown-toggle");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  dropdowns.forEach(function (dd) {
    var btn = dd.querySelector(".dropdown-toggle");
    if (!btn) return;

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var isOpen = dd.classList.toggle("is-open");
      btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
      if (isOpen) {
        var first = dd.querySelector(".dropdown-menu a");
        if (first) first.focus();
      }
    });

    dd.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeDropdown(dd);
        btn.focus();
      }
    });

    // Tabbing out of the menu closes it.
    dd.addEventListener("focusout", function (e) {
      if (!dd.contains(e.relatedTarget)) closeDropdown(dd);
    });
  });

  document.addEventListener("click", function (e) {
    dropdowns.forEach(function (dd) {
      if (!dd.contains(e.target)) closeDropdown(dd);
    });
  });

  // --- Copy to clipboard ---------------------------------------------------
  // navigator.clipboard is undefined on insecure origins and in some in-app
  // browsers. Calling .then() on it directly threw a TypeError and the button
  // silently did nothing — on the press dispatch, the primary action.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      try {
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) { resolve(); } else { reject(new Error("execCommand copy failed")); }
      } catch (err) {
        document.body.removeChild(ta);
        reject(err);
      }
    });
  }

  function flash(btn, message, revertHtml) {
    btn.textContent = message;
    btn.classList.add("btn-copied");
    setTimeout(function () {
      btn.innerHTML = revertHtml;
      btn.classList.remove("btn-copied");
    }, 2200);
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-copy-target]") : null;
    if (!btn) return;

    var target = document.getElementById(btn.getAttribute("data-copy-target"));
    if (!target) return;

    var text = (target.value || target.innerText || target.textContent || "").trim();
    var original = btn.innerHTML;

    var targetId = target.id || "unknown";

    copyText(text).then(function () {
      flash(btn, "✓ Copied", original);
      track("copy_to_clipboard", { content_type: targetId, page_path: location.pathname });
    }).catch(function () {
      // Give the user something they can act on rather than a dead button.
      flash(btn, "Press Ctrl+C to copy", original);
      if (window.getSelection && document.createRange) {
        var range = document.createRange();
        range.selectNodeContents(target);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      track("copy_to_clipboard_fallback", { content_type: targetId, page_path: location.pathname });
    });
  });

  // --- Outbound link clicks -------------------------------------------------
  // Everything else on the site is an internal navigation, already captured by
  // the per-page page_view. target="_blank" anchors (currently: the CC BY
  // licence link in the footer, methodology page and data page) are the only
  // outbound clicks, tracked with GA4's recommended "click" event shape.
  document.addEventListener("click", function (e) {
    var link = e.target.closest ? e.target.closest('a[target="_blank"]') : null;
    if (!link || !link.href) return;
    track("click", {
      link_url: link.href,
      link_text: (link.textContent || "").trim(),
      outbound: true,
      page_path: location.pathname
    });
  });

  /* --- Report tabs ------------------------------------------------------
     Dashboard / Methodology on /hormuz-index. The hash is kept in sync so
     /hormuz-index#methodology deep-links straight to the methodology tab —
     that is the target of the /methodology redirect, of the event log's
     source links, and of any citation made while it was its own page. */
  var reportTabs = Array.prototype.slice.call(document.querySelectorAll("[data-report-tab]"));
  if (reportTabs.length) {
    var showTab = function (name, pushHash) {
      var matched = false;
      reportTabs.forEach(function (btn) {
        var isTarget = btn.getAttribute("data-report-tab") === name;
        btn.classList.toggle("active", isTarget);
        btn.setAttribute("aria-selected", isTarget ? "true" : "false");
        if (isTarget) matched = true;
      });
      if (!matched) return false;

      Array.prototype.forEach.call(document.querySelectorAll(".report-panel"), function (panel) {
        panel.classList.toggle("active", panel.id === "tab-" + name);
      });

      if (pushHash) {
        // replaceState, not a hash assignment: setting location.hash would
        // scroll to the panel and push an entry per tab click.
        history.replaceState(null, "", name === "dashboard" ? location.pathname : "#" + name);
      }
      // Charts sized while their panel was display:none come out 0x0.
      window.dispatchEvent(new Event("resize"));
      return true;
    };

    reportTabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tabName = btn.getAttribute("data-report-tab");
        showTab(tabName, true);
        track("report_tab_switch", {
          report_slug: location.pathname.replace(/^\//, "") || "home",
          tab_name: tabName,
          page_path: location.pathname
        });
      });
    });

    if (location.hash) showTab(location.hash.slice(1), false);
    window.addEventListener("hashchange", function () {
      if (location.hash) showTab(location.hash.slice(1), false);
    });
  }

  // --- Table & Details Expansion Tracking ---------------------------------
  document.addEventListener("toggle", function (e) {
    if (!e.target || e.target.tagName !== "DETAILS") return;
    var summary = e.target.querySelector("summary");
    var label = summary ? (summary.textContent || "").trim() : "details";
    var name = e.target.className || e.target.id || label.slice(0, 40);
    track("table_expand", {
      element_name: name,
      element_label: label,
      is_open: e.target.open,
      page_path: location.pathname
    });
  }, true);

  // --- CTA & Deep Link Clicks ----------------------------------------------
  document.addEventListener("click", function (e) {
    var cta = e.target.closest ? e.target.closest("[data-cta], .exec-briefing-link, .ppi-privacy-link") : null;
    if (!cta) return;
    var target = cta.getAttribute("href") || cta.getAttribute("data-cta") || "";
    var label = (cta.textContent || "").trim();
    track("cta_click", {
      cta_label: label,
      cta_target: target,
      page_path: location.pathname
    });
  });

  // --- Global Exception Tracking -------------------------------------------
  window.addEventListener("error", function (e) {
    var message = e.message || (e.error && e.error.message) || "Script error";
    var filename = e.filename ? e.filename.split("/").pop() : "inline";
    track("exception", {
      description: (filename + ": " + message).slice(0, 100),
      fatal: false,
      page_path: location.pathname
    });
  });

  window.addEventListener("unhandledrejection", function (e) {
    var reason = e.reason ? (e.reason.message || String(e.reason)) : "Unhandled promise rejection";
    track("exception", {
      description: ("Promise: " + reason).slice(0, 100),
      fatal: false,
      page_path: location.pathname
    });
  });

})();

