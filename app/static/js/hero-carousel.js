/* Home page featured-index carousel.
 *
 * The track is a scroll-snap container, so a phone gets native swipe and
 * momentum for free and the slides stay readable with JavaScript disabled —
 * this file only adds the arrows, the dots and the rotation on top of it.
 */
(function () {
  "use strict";

  var root = document.querySelector(".hcar");
  if (!root) return;

  var track = root.querySelector(".hcar-track");
  var slides = Array.prototype.slice.call(root.querySelectorAll(".hcar-slide"));
  var dots = Array.prototype.slice.call(root.querySelectorAll("[data-hcar-dot]"));
  if (!track || slides.length < 2) return;

  var reduceMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  var interval = parseInt(root.getAttribute("data-autoplay"), 10) || 7000;
  var current = 0;
  var timer = null;
  var paused = false;

  function scrollTo(index, smooth) {
    var slide = slides[index];
    if (!slide) return;
    var left = slide.offsetLeft - track.offsetLeft;
    // scroll-behavior is set in CSS, but an explicit behaviour keeps a
    // programmatic jump honest when the user has asked for reduced motion.
    if (track.scrollTo) {
      track.scrollTo({ left: left, behavior: smooth ? "smooth" : "auto" });
    } else {
      track.scrollLeft = left;
    }
  }

  function paint(index) {
    current = index;
    for (var i = 0; i < dots.length; i++) {
      var active = i === index;
      dots[i].classList.toggle("is-active", active);
      if (active) {
        dots[i].setAttribute("aria-current", "true");
      } else {
        dots[i].removeAttribute("aria-current");
      }
    }
  }

  function go(index, source) {
    var next = (index + slides.length) % slides.length;
    scrollTo(next, !reduceMotion.matches);
    paint(next);
    if (source && typeof window.trackEvent === "function") {
      window.trackEvent("hero_carousel_change", {
        slide: slides[next].getAttribute("data-slide") || String(next),
        method: source
      });
    }
  }

  // --- Rotation -------------------------------------------------------------

  function stop() {
    if (timer) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  function start() {
    stop();
    if (paused || reduceMotion.matches || document.hidden) return;
    timer = window.setInterval(function () {
      go(current + 1, null);
    }, interval);
  }

  function pause() {
    paused = true;
    stop();
  }

  function resume() {
    paused = false;
    start();
  }

  // A banner that keeps moving while someone is reading it, hovering a link or
  // tabbing through the CTAs is the thing everybody hates about carousels.
  root.addEventListener("mouseenter", pause);
  root.addEventListener("mouseleave", resume);
  root.addEventListener("focusin", pause);
  root.addEventListener("focusout", function (e) {
    if (!root.contains(e.relatedTarget)) resume();
  });
  root.addEventListener("touchstart", pause, { passive: true });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
    else start();
  });
  if (reduceMotion.addEventListener) {
    reduceMotion.addEventListener("change", function () {
      if (reduceMotion.matches) stop();
      else start();
    });
  }

  // --- Controls -------------------------------------------------------------

  var prev = root.querySelector('[data-hcar="prev"]');
  var next = root.querySelector('[data-hcar="next"]');
  if (prev) prev.addEventListener("click", function () { go(current - 1, "arrow"); });
  if (next) next.addEventListener("click", function () { go(current + 1, "arrow"); });

  dots.forEach(function (dot) {
    dot.addEventListener("click", function () {
      go(parseInt(dot.getAttribute("data-hcar-dot"), 10) || 0, "dot");
    });
  });

  root.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") { go(current - 1, "keyboard"); e.preventDefault(); }
    if (e.key === "ArrowRight") { go(current + 1, "keyboard"); e.preventDefault(); }
  });

  // Swipes and any other scroll of the track are the source of truth for which
  // slide is showing, so the dots follow the container rather than the clicks.
  var settle = null;
  track.addEventListener("scroll", function () {
    if (settle) window.clearTimeout(settle);
    settle = window.setTimeout(function () {
      var nearest = 0;
      var best = Infinity;
      for (var i = 0; i < slides.length; i++) {
        var distance = Math.abs(slides[i].offsetLeft - track.offsetLeft - track.scrollLeft);
        if (distance < best) { best = distance; nearest = i; }
      }
      if (nearest !== current) paint(nearest);
    }, 120);
  }, { passive: true });

  paint(0);
  start();
})();
