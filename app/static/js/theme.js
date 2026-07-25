(function () {
  // --- Theme Toggle ---
  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");

  function currentTheme() {
    var stored = localStorage.getItem("theme");
    if (stored) return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
    });
  }

  // --- Copy to Clipboard Handler ---
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy-target]");
    if (!btn) return;

    var targetId = btn.getAttribute("data-copy-target");
    var targetElem = document.getElementById(targetId);
    if (!targetElem) return;

    var textToCopy = targetElem.value || targetElem.innerText || targetElem.textContent;

    navigator.clipboard.writeText(textToCopy).then(function () {
      var origText = btn.innerHTML;
      btn.innerHTML = '<span class="icon">✓</span> Copied!';
      btn.classList.add("btn-copied");
      setTimeout(function () {
        btn.innerHTML = origText;
        btn.classList.remove("btn-copied");
      }, 2000);
    }).catch(function (err) {
      console.error("Clipboard copy failed:", err);
    });
  });

  // --- Interactive Trend Tooltip ---
  var trendSvg = document.querySelector(".trend-svg");
  var tooltip = document.getElementById("trend-tooltip");

  if (trendSvg && tooltip) {
    var points = trendSvg.querySelectorAll(".trend-point-group");
    points.forEach(function (pt) {
      pt.addEventListener("mouseenter", function (e) {
        var week = pt.getAttribute("data-week");
        var score = pt.getAttribute("data-score");
        var level = pt.getAttribute("data-level");
        var isCf = pt.getAttribute("data-ceasefire") === "1";
        var cfTitle = pt.getAttribute("data-title") || "";
        var srcName = pt.getAttribute("data-source-name") || "";
        var srcUrl = pt.getAttribute("data-source-url") || "#";

        var html = '<strong>Week of ' + week + '</strong><br/>Score: <span style="font-weight:700;">' + score + '</span> (' + level + ')';
        if (isCf) {
          html += '<div style="margin-top:4px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.15); color:#34D399; font-weight:600;">🕊️ ' + cfTitle + '</div>';
        }
        if (srcName && srcUrl !== "#") {
          html += '<div style="margin-top:4px;"><a href="' + srcUrl + '" target="_blank" rel="noopener" style="color:#60A5FA; font-size:0.75rem; text-decoration:underline;">📰 Source: ' + srcName + ' &rarr;</a></div>';
        }

        tooltip.innerHTML = html;
        tooltip.style.display = "block";
        
        var rect = pt.getBoundingClientRect();
        var containerRect = trendSvg.parentElement.getBoundingClientRect();
        tooltip.style.left = Math.max(10, Math.min(containerRect.width - 200, rect.left - containerRect.left - 30)) + "px";
        tooltip.style.top = (rect.top - containerRect.top - 65) + "px";
      });
    });

    trendSvg.addEventListener("mouseleave", function () {
      tooltip.style.display = "none";
    });
  }
})();

