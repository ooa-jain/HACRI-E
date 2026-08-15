/*
 * report_motion.js — the movement on the shared pages.
 *
 * These pages get sent to people by link, so they open cold: the reader lands
 * on a wall of finished numbers with nothing to say which of them matters.
 * Three things move, and only on the way in:
 *
 *   reveal    cards rise into place as they reach the viewport, in the order
 *             they are read rather than all at once
 *   count     a figure counts up to its value, so the eye lands on it
 *   fill      a bar or ring grows to its share
 *
 * Everything is opt-in through data attributes or the classes the shared
 * stylesheet already sets, nothing here changes a value, and the whole file
 * stands down under prefers-reduced-motion — the page then renders in its
 * final state with no animation at all.
 */
(function () {
  'use strict';

  var STILL = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Easing ──────────────────────────────────────────────────────────── */
  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  /* ── Counting ────────────────────────────────────────────────────────────
     Only a figure that is purely numeric is counted; "3.71 / 3.67" and "—"
     are left exactly as they are. */
  var NUMERIC = /^\s*(\d[\d,]*)(\.\d+)?\s*%?\s*$/;

  function parseFigure(text) {
    var m = NUMERIC.exec(text);
    if (!m) return null;
    return {
      value: parseFloat(text.replace(/[,%\s]/g, '')),
      decimals: m[2] ? m[2].length - 1 : 0,
      percent: text.indexOf('%') !== -1,
      grouped: text.indexOf(',') !== -1,
    };
  }

  function render(figure, value) {
    var out = value.toFixed(figure.decimals);
    if (figure.grouped || (figure.decimals === 0 && value >= 1000)) {
      var bits = out.split('.');
      bits[0] = bits[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      out = bits.join('.');
    }
    return out + (figure.percent ? '%' : '');
  }

  function countUp(el, duration) {
    var figure = parseFigure(el.textContent);
    if (!figure) return;
    if (STILL || figure.value === 0) { el.textContent = render(figure, figure.value); return; }

    var span = duration || 950;
    var started = null;
    el.textContent = render(figure, 0);
    function step(now) {
      if (started === null) started = now;
      var t = Math.min((now - started) / span, 1);
      el.textContent = render(figure, figure.value * easeOutCubic(t));
      if (t < 1) requestAnimationFrame(step);
      else el.textContent = render(figure, figure.value);
    }
    requestAnimationFrame(step);
  }

  /* ── Bars ────────────────────────────────────────────────────────────────
     A bar carries its share in data-fill and grows to it once seen. */
  function fill(el) {
    var target = el.getAttribute('data-fill');
    if (target === null) return;
    if (STILL) { el.style.width = target + '%'; return; }
    el.style.width = '0%';
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { el.style.width = target + '%'; });
    });
  }

  /* ── Reveal ──────────────────────────────────────────────────────────────
     Marked elements start lowered and transparent, then settle as they come
     into view. Children of one group are staggered so a row reads left to
     right instead of arriving in a block. */
  function revealTargets() {
    var groups = [
      ['.summary > div', 60],
      ['.stat-card', 60],
      ['.kpi', 60],
      ['.card', 90],
      ['.charts-card', 90],
      ['.action-banner', 0],
      ['.chart-item', 70],
      ['[data-reveal]', 60],
    ];
    var seen = [];
    groups.forEach(function (pair) {
      var nodes = Array.prototype.slice.call(document.querySelectorAll(pair[0]));
      nodes.forEach(function (node, i) {
        if (seen.indexOf(node) !== -1) return;
        seen.push(node);
        node.classList.add('reveal');
        node.style.setProperty('--reveal-delay', Math.min(i * pair[1], 400) + 'ms');
      });
    });
    return seen;
  }

  function settle(node) {
    node.classList.add('reveal-in');
    // Figures and bars wait for their card, so the movement reads as one thing.
    Array.prototype.forEach.call(node.querySelectorAll('[data-count]'), function (el) {
      countUp(el);
    });
    Array.prototype.forEach.call(node.querySelectorAll('[data-fill]'), fill);
  }

  function start() {
    // Mark the figures worth counting: a card's headline number, never a
    // ratio, a date or a dash.
    Array.prototype.forEach.call(
      document.querySelectorAll('.summary > div > b, .stat-val, .kpi-val, [data-count-me]'),
      function (el) {
        if (parseFigure(el.textContent)) el.setAttribute('data-count', '');
      });

    var nodes = revealTargets();

    if (STILL || !('IntersectionObserver' in window)) {
      nodes.forEach(settle);
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        settle(entry.target);
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });

    nodes.forEach(function (node) { io.observe(node); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.ReportMotion = { countUp: countUp, fill: fill, reveal: revealTargets, settle: settle };
})();
