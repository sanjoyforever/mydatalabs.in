(function () {
  "use strict";

  var root = document.documentElement;

  // --- Analytics -------------------------------------------------------
  // GA4 is loaded in base.html on every page (page_view fires automatically
  // on load). This wraps gtag so a missing/blocked GA script never breaks a
  // click handler — an ad blocker dropping analytics must not also break
  // the copy button it's attached to.
  function track(name, params) {
    if (typeof window.gtag === "function") {
      window.gtag("event", name, params || {});
    }
  }

  function currentTheme() {
    return root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

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
})();
