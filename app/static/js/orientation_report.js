/**
 * orientation_report.js — the Deeksharambh report's visual language.
 *
 * One renderer, two homes: the survey admin dashboard and the public shared
 * page both call into this, so a campus reads the same whether you are signed
 * in or someone forwarded you the link.
 *
 * Everything is plain DOM + inline styles: the shared page carries no CSS
 * framework, and the components have to look identical on both.
 *
 *   OrientationReport.renderReport(hostEl, report)
 *   OrientationReport.renderDepartments(hostEl, overview, { onPick })
 *   OrientationReport.renderScorecard(hostEl, scorecard)
 *   OrientationReport.mood(avg) -> [word, emoji, colour]
 */
(function (global) {
  'use strict';

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const num = (v, digits = 1) =>
    (v === null || v === undefined) ? '—' : Number(v).toFixed(digits);

  /** What an average out of ten actually feels like.
   *
   * A muted ramp — green through amber to coral — so a warm cohort and a cold
   * one are still told apart at a glance without the page shouting. */
  const MOODS = [
    [9, 'Buzzing',        '🤩', '#1f9e63'],
    [8, 'Loving it',      '😍', '#46a85b'],
    [7, 'Good vibes',     '😄', '#7faf4c'],
    [6, 'Warming up',     '🙂', '#e0a52e'],
    [5, 'Mixed feelings', '😐', '#e5813c'],
    [0, 'Needs a lift',   '😕', '#e0524d'],
  ];
  const mood = avg => (avg === null || avg === undefined)
    ? ['No answers yet', '🫥', '#a8adb6']
    : (MOODS.find(m => avg >= m[0]) || MOODS[MOODS.length - 1]).slice(1);

  // Section accents, cycled so each section reads as its own chapter. Coral
  // leads; the rest are its supporting cast, all at the same low volume.
  const ACCENTS = ['#f0524b', '#2f9e8f', '#6f6bd8', '#e0913a', '#3b82c4',
                   '#2e9e5b', '#c2549b', '#5b6b8c', '#d1664e'];

  const PANELS = [
    ['impactful',  '🏆 Sessions that landed',   '#2e9e5b'],
    ['needs_work', '🛠️ Sessions needing work',  '#f0524b'],
    ['stressors',  '😰 Biggest stressors',      '#e0913a'],
    ['keep',       '👍 Keep next year',         '#3b82c4'],
    ['stop',       '🚫 Stop next year',         '#b03a5b'],
    ['introduce',  '✨ Introduce next year',    '#6f6bd8'],
  ];

  const MEDALS = ['🥇', '🥈', '🥉'];

  // The one warm accent the chrome is built on, and the grey that stands in
  // for a score nobody gave — a coloured stub would read as a real answer.
  const ACCENT = '#f0524b';
  const EMPTY  = '#eceef2';

  // ── Small building blocks ─────────────────────────────────────────────────

  /** A labelled bar. `tone` colours the fill.
   *
   * The bar reads `width` when given, so a chart can scale bars against the
   * biggest one while still printing each option's true share. */
  function bar(option, tone) {
    const pct = Math.max(0, Math.min(100,
      option.width === undefined ? (option.pct || 0) : option.width));
    return `
      <div class="ori-bar">
        <div class="ori-bar-head">
          <span class="ori-bar-label" title="${esc(option.label)}">${esc(option.label)}</span>
          <span class="ori-bar-value">${option.count} · ${num(option.pct, 0)}%</span>
        </div>
        <div class="ori-track"><div class="ori-fill" style="width:${pct}%;background:${tone}"></div></div>
      </div>`;
  }

  const bars = (options, tone, limit) => {
    const rows = limit ? options.slice(0, limit) : options;
    return rows.length
      ? rows.map(o => bar(o, tone)).join('')
      : '<div class="ori-empty">No answers yet</div>';
  };

  /** Top answers as a podium — medals for the first three. */
  function podium(options, tone, limit = 5) {
    if (!options || !options.length) return '<div class="ori-empty">No answers yet</div>';
    return options.slice(0, limit).map((o, i) => `
      <div class="ori-rank">
        <div class="ori-rank-badge" style="${i < 3 ? '' : `background:${tone}1a;color:${tone}`}">
          ${i < 3 ? MEDALS[i] : i + 1}
        </div>
        <div class="ori-rank-body">
          <div class="ori-rank-label">${esc(o.label)}</div>
          <div class="ori-track"><div class="ori-fill" style="width:${Math.min(100, o.pct)}%;background:${tone}"></div></div>
        </div>
        <div class="ori-rank-value">${o.count}<span>${num(o.pct, 0)}%</span></div>
      </div>`).join('');
  }

  /** An SVG ring — used for the NPS and for response rate. */
  function ring(segments, centre, caption, size = 132) {
    const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
    const r = size / 2 - 11;
    const circumference = 2 * Math.PI * r;
    let offset = 0;
    const arcs = segments.map(s => {
      const length = circumference * (s.value / total);
      const dash = `${length} ${circumference - length}`;
      const arc = `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
        stroke="${s.colour}" stroke-width="16" stroke-dasharray="${dash}"
        stroke-dashoffset="${-offset}" transform="rotate(-90 ${size / 2} ${size / 2})"></circle>`;
      offset += length;
      return arc;
    }).join('');
    return `
      <div class="ori-ring">
        <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
          <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="#f1f2f5" stroke-width="16"></circle>
          ${arcs}
        </svg>
        <div class="ori-ring-centre">
          <div class="ori-ring-value">${esc(centre)}</div>
          <div class="ori-ring-caption">${esc(caption)}</div>
        </div>
      </div>`;
  }

  /** A stat tile with an accent bar and an optional meter. */
  function tile(value, label, tone, share) {
    const meter = (share === null || share === undefined) ? '' :
      `<div class="ori-track" style="margin-top:8px">
         <div class="ori-fill" style="width:${Math.max(0, Math.min(100, share))}%;background:${tone}"></div>
       </div>`;
    return `
      <div class="ori-tile" style="--tone:${tone}">
        <div class="ori-tile-value">${esc(value)}</div>
        <div class="ori-tile-label">${esc(label)}</div>
        ${meter}
      </div>`;
  }

  // ── Charts ────────────────────────────────────────────────────────────────
  //
  // The distributions are drawn by Chart.js, so a count is plotted against a
  // measured axis: gridlines, labels attached to their own columns, and a
  // tooltip that names the students behind each bar. Hand-drawn CSS columns
  // gave a two-pixel sliver for every small bar and floated it against
  // nothing, which is what made the vibe strip unreadable.
  //
  // A canvas cannot be drawn on before it is in the document, so building the
  // markup only queues the chart; `paintCharts` instantiates the queue once
  // the HTML has been inserted. Without Chart.js on the page the builder
  // returns the CSS column strip instead, so the renderer still works alone.

  const STILL = !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const CHART_FONT = 'Outfit, system-ui, sans-serif';

  const TOOLTIP = {
    backgroundColor: 'rgba(23,17,10,.94)',
    padding: 11,
    cornerRadius: 10,
    displayColors: false,
    titleFont: { family: CHART_FONT, size: 12, weight: '800' },
    bodyFont: { family: CHART_FONT, size: 12 },
  };

  let queued = [];
  let seq = 0;

  /** Queue a chart and return the markup that holds it. */
  function chart(config, options) {
    const o = options || {};
    if (!global.Chart) return o.fallback || '';
    const id = 'ori-chart-' + (++seq);
    queued.push({ id: id, config: config });
    return `<div class="ori-chart" style="height:${o.height || 180}px">
        <canvas data-ori-chart="${id}"></canvas>
      </div>`;
  }

  /** Draw everything queued while `host` was being built, and drop the old. */
  function paintCharts(host) {
    (host.oriCharts || []).forEach(c => { try { c.destroy(); } catch (err) { /* gone already */ } });
    host.oriCharts = [];
    const specs = queued;
    queued = [];
    if (!global.Chart) return;
    specs.forEach(spec => {
      const canvas = host.querySelector(`canvas[data-ori-chart="${spec.id}"]`);
      if (canvas) host.oriCharts.push(new global.Chart(canvas, spec.config));
    });
  }

  /** A count-per-answer column chart. `dark` puts it on the hero's gradient. */
  function countChart(options, colours, opts) {
    const o = opts || {};
    const counts = options.map(x => x.count || 0);
    const answered = counts.reduce((sum, n) => sum + n, 0);
    const ink = o.dark ? 'rgba(255,255,255,.82)' : '#7c7266';
    const grid = o.dark ? 'rgba(255,255,255,.15)' : '#ece3d4';

    return {
      type: 'bar',
      data: {
        labels: options.map(x => x.label),
        datasets: [{
          label: 'Students',
          data: counts,
          backgroundColor: colours,
          borderRadius: 7,
          borderSkipped: false,
          maxBarThickness: 54,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: STILL ? false : { duration: 650, easing: 'easeOutCubic' },
        layout: { padding: { top: 4 } },
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, TOOLTIP, {
            callbacks: {
              title: items => (o.title ? o.title(items[0].label) : items[0].label),
              label: item => {
                const n = item.parsed.y;
                const share = answered ? Math.round(100 * n / answered) : 0;
                return `${n} student${n === 1 ? '' : 's'} · ${share}% of those who answered`;
              },
            },
          }),
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: o.dark ? 'rgba(255,255,255,.3)' : '#ece3d4' },
            ticks: { color: ink, font: { family: CHART_FONT, size: 11, weight: '700' } },
          },
          y: {
            beginAtZero: true,
            grid: { color: grid, drawTicks: false },
            border: { display: false },
            // Whole students only, and few enough labels that the axis stays quiet.
            ticks: {
              color: ink, font: { family: CHART_FONT, size: 10.5 },
              precision: 0, maxTicksLimit: 5, padding: 6,
            },
          },
        },
      },
    };
  }

  // ── Big components ────────────────────────────────────────────────────────

  /** The gradient headline: score, mood, and how the ten points were spread. */
  function hero(report) {
    const h = report.headline, c = report.coverage || {};
    const [word, emoji, colour] = mood(h.vibe);
    const vibeQ = questionOf(report, 'q2');
    const top = vibeQ ? Math.max(1, ...vibeQ.options.map(o => o.count)) : 1;

    const strip = vibeQ ? `
      <div class="ori-strip-title">How the ten points were spread</div>
      ${chart(
        countChart(vibeQ.options,
                   vibeQ.options.map(o => (o.count ? mood(Number(o.label))[2] : EMPTY)),
                   { title: label => `Rated ${label} out of 10` }),
        { height: 172, fallback: legacyStrip(vibeQ, top) })}
      <div class="ori-strip-note">1 — I wanted to leave · 10 — I wish it never ended</div>` : '';

    const chip = (value, label) =>
      `<div class="ori-chip"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;

    return `
      <section class="ori-hero" style="--mood:${colour}">
        <div class="ori-hero-score">
          <div class="ori-hero-kicker">Overall vibe of the students</div>
          <div class="ori-hero-row">
            <div class="ori-hero-emoji">${emoji}</div>
            <div>
              <div class="ori-hero-value">${num(h.vibe, 1)}<span>/ 10</span></div>
              <div class="ori-hero-word">${esc(word)}</div>
            </div>
          </div>
        </div>
        <div class="ori-hero-strip">${strip}</div>
        <div class="ori-hero-chips">
          ${chip(h.nps === null || h.nps === undefined ? '—' : num(h.nps, 0), 'NPS')}
          ${chip(num(h.belonging, 1), 'Belonging')}
          ${chip(num(h.success, 1), 'Will succeed')}
          ${chip(num(c.pct, 0) + '%', 'Answered')}
        </div>
      </section>`;
  }

  const questionOf = (report, key) => {
    for (const section of report.sections || []) {
      const found = section.questions.find(q => q.key === key);
      if (found) return found;
    }
    return null;
  };

  function tiles(report) {
    const h = report.headline, c = report.coverage || {};
    return `<div class="ori-tiles">
      ${tile(report.count, 'Responses', ACCENT, null)}
      ${tile(num(c.pct, 0) + '%', 'Response rate', '#2f9e8f', c.pct)}
      ${tile(num(h.vibe, 1), 'Vibe / 10', mood(h.vibe)[2], h.vibe === null ? 0 : h.vibe * 10)}
      ${tile(h.nps === null || h.nps === undefined ? '—' : num(h.nps, 0), 'NPS', '#6f6bd8',
             h.nps === null || h.nps === undefined ? 0 : (h.nps + 100) / 2)}
      ${tile(num(h.belonging, 1), 'Belonging / 10', '#3b82c4', h.belonging === null ? 0 : h.belonging * 10)}
      ${tile(num(h.bridge, 1), 'Bridge course / 5', '#e0913a', h.bridge === null ? 0 : h.bridge * 20)}
    </div>`;
  }

  /** Promoters / passives / detractors, as a ring with a legend. */
  function npsCard(report) {
    const h = report.headline;
    const q = questionOf(report, 'q34') || h;
    const segs = [
      { value: q.promoters || 0,  colour: '#2e9e5b', label: 'Promoters 9–10' },
      { value: q.passives || 0,   colour: '#e9b949', label: 'Passives 7–8' },
      { value: q.detractors || 0, colour: '#e0524d', label: 'Detractors 0–6' },
    ];
    const total = segs.reduce((s, x) => s + x.value, 0);
    return `
      <div class="ori-card ori-card-split">
        <div>
          <div class="ori-card-title">💬 Would they recommend JAIN?</div>
          <div class="ori-card-sub">${total} answered · average ${num(h.nps_avg, 2)} / 10</div>
          <div class="ori-legend">
            ${segs.map(s => `
              <div class="ori-legend-row">
                <span class="ori-dot" style="background:${s.colour}"></span>
                <span class="ori-legend-label">${esc(s.label)}</span>
                <b>${s.value}</b>
                <span class="ori-legend-pct">${total ? Math.round(100 * s.value / total) : 0}%</span>
              </div>`).join('')}
          </div>
        </div>
        ${ring(segs, h.nps === null || h.nps === undefined ? '—' : (h.nps > 0 ? '+' : '') + num(h.nps, 0), 'NPS')}
      </div>`;
  }

  function highlightPanels(report) {
    const highlights = report.highlights || {};
    return `<div class="ori-grid-3">
      ${PANELS.map(([key, title, tone]) => `
        <div class="ori-card">
          <div class="ori-card-title" style="color:${tone}">${esc(title)}</div>
          <div class="ori-ranks">${podium(highlights[key], tone, 5)}</div>
        </div>`).join('')}
    </div>`;
  }

  function questionCard(q, tone) {
    const head = `<div class="ori-q-title">${esc(q.label)}</div>`;

    if (q.kind === 'matrix') {
      return `<div class="ori-q">
        ${head}<div class="ori-q-sub">${q.answered} answered</div>
        ${q.rows.map(r => `
          <div class="ori-q-row">
            <div class="ori-q-row-label">${esc(r.label)}</div>
            ${bars(r.options, tone)}
          </div>`).join('')}
      </div>`;
    }
    if (q.kind === 'nps') {
      return `<div class="ori-q">
        ${head}
        <div class="ori-q-sub">${q.answered} answered · average ${num(q.avg, 2)} / 10 · NPS ${num(q.nps, 0)}</div>
        <div class="ori-split3">
          <div class="ori-mini" style="--tone:#2e9e5b"><b>${q.promoters}</b><span>Promoters 9–10</span></div>
          <div class="ori-mini" style="--tone:#e0913a"><b>${q.passives}</b><span>Passives 7–8</span></div>
          <div class="ori-mini" style="--tone:#e0524d"><b>${q.detractors}</b><span>Detractors 0–6</span></div>
        </div>
        ${scaleStrip(q)}
      </div>`;
    }
    if (q.kind === 'scale') {
      return `<div class="ori-q">
        ${head}<div class="ori-q-sub">${q.answered} answered · average ${num(q.avg, 2)} / ${q.max}</div>
        ${scaleStrip(q)}
      </div>`;
    }
    const suffix = q.kind === 'multi' ? ` · ${q.picks} selections` : '';
    return `<div class="ori-q">
      ${head}<div class="ori-q-sub">${q.answered} answered${suffix}</div>
      ${bars(q.options, tone, 12)}
    </div>`;
  }

  /** A 1..max distribution, plotted against a counted axis. */
  function scaleStrip(q) {
    const scale = q.max || 10;
    const colours = q.options.map(o =>
      (o.count ? mood((Number(o.label) / scale) * 10)[2] : EMPTY));
    return chart(
      countChart(q.options, colours, { title: label => `Answered ${label} of ${scale}` }),
      { height: 168, fallback: legacyScaleStrip(q) });
  }

  // The CSS column strips, kept for the case where Chart.js never loaded: a
  // thin coloured column is worse than a plotted axis, but better than a blank
  // space where the distribution should be.

  function legacyStrip(q, top) {
    return `
      <div class="ori-strip">
        ${q.options.map(o => `
          <div class="ori-strip-col" title="${o.count} student(s) rated ${esc(o.label)}/10">
            <div class="ori-strip-bar"
                 style="height:${Math.max(2, Math.round(100 * o.count / top))}%;background:${
                   o.count ? mood(Number(o.label))[2] : EMPTY}"></div>
          </div>`).join('')}
      </div>
      <div class="ori-strip-axis">
        ${q.options.map(o => `<span>${esc(o.label)}</span>`).join('')}
      </div>`;
  }

  function legacyScaleStrip(q) {
    const top = Math.max(1, ...q.options.map(o => o.count));
    const scale = q.max || 10;
    return `
      <div class="ori-scale">
        ${q.options.map(o => {
          const tone = mood((Number(o.label) / scale) * 10)[2];
          return `<div class="ori-scale-col" title="${o.count} · ${num(o.pct, 0)}%">
            <div class="ori-scale-count">${o.count || ''}</div>
            <div class="ori-scale-track">
              <div class="ori-scale-bar" style="height:${Math.max(2, Math.round(100 * o.count / top))}%;background:${
                o.count ? tone : EMPTY}"></div>
            </div>
            <div class="ori-scale-label">${esc(o.label)}</div>
          </div>`;
        }).join('')}
      </div>`;
  }

  function sections(report) {
    return (report.sections || []).map((s, i) => {
      const tone = ACCENTS[i % ACCENTS.length];
      return `
        <section class="ori-card ori-section" id="ori-sec-${i}" style="--tone:${tone}">
          <div class="ori-section-head">
            <span class="ori-section-title">${esc(s.title)}</span>
            <span class="ori-section-count">${s.questions.length} question${s.questions.length === 1 ? '' : 's'}</span>
          </div>
          <div class="ori-grid-2">${s.questions.map(q => questionCard(q, tone)).join('')}</div>
        </section>`;
    }).join('');
  }

  /** Chips that jump to a section — the report is long. */
  function sectionNav(report) {
    if (!(report.sections || []).length) return '';
    return `<nav class="ori-nav">
      ${report.sections.map((s, i) =>
        `<a class="ori-nav-chip" href="#ori-sec-${i}" style="--tone:${ACCENTS[i % ACCENTS.length]}">${esc(s.title)}</a>`
      ).join('')}
    </nav>`;
  }

  function whoAnswered(report) {
    const rows = report.departments || [];
    if (!rows.length) return '';
    const top = Math.max(1, ...rows.map(r => r.count));
    return `
      <div class="ori-card">
        <div class="ori-card-title">🏢 Who answered</div>
        <div class="ori-card-sub">${rows.length} department${rows.length === 1 ? '' : 's'}${
          (report.levels || []).length
            ? ' · ' + report.levels.map(l => `${l.count} ${esc(l.level)}`).join(' · ')
            : ''}</div>
        <div class="ori-bars">
          ${rows.map(r => bar(
            { label: r.dept, count: r.count, pct: r.pct, width: 100 * r.count / top },
            ACCENT)).join('')}
        </div>
      </div>`;
  }

  // ── Department scorecard ──────────────────────────────────────────────────
  // What a department-scoped share link opens with: this department's vibe,
  // its counts, and every headline number against the campus average.

  const ORDINALS = ['th', 'st', 'nd', 'rd'];
  const ordinal = n => n + (ORDINALS[(n % 100 - 20) % 10] || ORDINALS[n % 100] || ORDINALS[0]);

  /** Where a headline number sits on a 0-100 track of its own scale. */
  const share = (metric, value) => (value === null || value === undefined) ? 0
    : Math.max(0, Math.min(100, metric.key === 'nps'
        ? (value + 100) / 2
        : (value / (metric.max || 10)) * 100));

  const reading = (metric, value) => (value === null || value === undefined) ? '—'
    : metric.key === 'nps' ? (value > 0 ? '+' : '') + num(value, 0) : num(value, 1);

  /** One metric: this department's figure, with the campus average marked on it. */
  function metricCard(metric) {
    const delta = metric.delta;
    const tone = delta === null || delta === undefined ? 'flat'
      : delta > 0.05 ? 'up' : delta < -0.05 ? 'down' : 'flat';
    const sign = delta > 0 ? '+' : '';
    return `
      <div class="ori-metric">
        <div class="ori-metric-label">${esc(metric.label)}</div>
        <div class="ori-metric-value">${reading(metric, metric.value)}${
          metric.max ? `<span>/ ${metric.max}</span>` : ''}</div>
        <div class="ori-metric-track">
          <div class="ori-metric-fill" style="width:${share(metric, metric.value)}%"></div>
          ${metric.campus === null || metric.campus === undefined ? '' :
            `<i class="ori-metric-mark" style="left:${share(metric, metric.campus)}%"
                title="Campus average"></i>`}
        </div>
        <div class="ori-metric-foot">
          <span>campus ${reading(metric, metric.campus)}</span>
          <b class="ori-delta ori-delta-${tone}">${
            delta === null || delta === undefined ? '—' : sign + num(delta, 1)}</b>
        </div>
      </div>`;
  }

  function scorecard(card) {
    const d = card.department || {};
    const [word, emoji, colour] = mood(d.vibe);
    const chip = (value, label) =>
      `<div class="ori-chip"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;

    const rank = card.rank ? `
      <div class="ori-score-rank">
        <b>${card.rank <= 3 ? MEDALS[card.rank - 1] : '#' + card.rank}</b>
        <span>${esc(ordinal(card.rank))} of ${card.of} on vibe</span>
      </div>` : '';

    const note = (icon, label, value) => value ? `
      <div class="ori-score-note">
        <span class="ori-score-note-label">${icon} ${esc(label)}</span>
        <b>${esc(value)}</b>
      </div>` : '';

    return `
      <section class="ori-score" style="--mood:${colour}">
        <div class="ori-score-head">
          <div class="ori-score-face">${emoji}</div>
          <div class="ori-score-id">
            <div class="ori-score-kicker">Deeksharambh 2026 · ${esc(card.campus)}</div>
            <div class="ori-score-name">${esc(card.dept)}</div>
            <div class="ori-score-word">${esc(word)} · ${num(d.vibe, 1)} / 10 overall vibe</div>
          </div>
          ${rank}
        </div>
        <div class="ori-hero-chips ori-score-chips">
          ${chip(d.filled, 'Replies')}
          ${chip(d.pending, 'Still pending')}
          ${chip(d.eligible, 'Eligible')}
          ${chip(num(d.pct, 0) + '%', 'Answered')}
        </div>
        <div class="ori-score-grid">${(card.metrics || []).map(metricCard).join('')}</div>
        <div class="ori-score-notes">
          ${note('🏆', 'Loudest praise', d.top_session)}
          ${note('😰', 'Biggest stressor', d.top_stressor)}
        </div>
        <div class="ori-score-foot">
          Bars are this department; the tick on each bar is the
          ${esc(card.campus)} average
          (${card.campus_overall ? card.campus_overall.filled : 0} replies from
          ${card.campus_overall ? card.campus_overall.eligible : 0} students).
        </div>
      </section>`;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function renderReport(host, report) {
    if (!host) return;
    queued = [];
    if (!report || !report.count) {
      paintCharts(host);
      host.innerHTML = '<div class="ori-card ori-empty-card">No orientation responses for this selection yet.</div>';
      return;
    }
    const markup =
      hero(report) +
      tiles(report) +
      `<div class="ori-grid-2-wide">${npsCard(report)}${whoAnswered(report)}</div>` +
      highlightPanels(report) +
      sectionNav(report) +
      sections(report);

    // The markup goes in first: the charts queued while building it need their
    // canvases to be in the document before they can be drawn.
    host.innerHTML = markup;
    paintCharts(host);
  }

  /** The department leaderboard. `onPick` gets the department name, if given. */
  function renderDepartments(host, overview, options) {
    if (!host) return;
    const opts = options || {};
    const metric = opts.metric || 'vibe';
    const rows = [...(overview.departments || [])]
      .sort((a, b) => (b[metric] ?? -999) - (a[metric] ?? -999));

    if (!rows.length) {
      host.innerHTML = '<div class="ori-card ori-empty-card">No departments have answered yet.</div>';
      return;
    }

    const width = v => {
      if (v === null || v === undefined) return 2;
      if (metric === 'nps') return Math.max(2, (v + 100) / 2);
      if (metric === 'pct') return Math.max(2, v);
      if (metric === 'filled') return Math.max(2, 100 * v / Math.max(...rows.map(r => r.filled), 1));
      return Math.max(2, v * 10);
    };
    const shown = v => v === null || v === undefined ? '—'
      : metric === 'pct' ? num(v, 0) + '%'
      : metric === 'filled' ? String(v)
      : metric === 'nps' ? num(v, 0) : num(v, 1);

    // Rows are buttons only when they actually do something, so the public
    // page does not offer keyboard focus on things that cannot be clicked.
    const clickable = typeof opts.onPick === 'function';
    const tag = clickable ? 'button' : 'div';
    host.innerHTML = rows.map((r, i) => {
      const [word, emoji, colour] = mood(r.vibe);
      return `
        <${tag} ${clickable ? 'type="button"' : ''}
          class="ori-dept${clickable ? ' ori-dept-click' : ''}" data-dept="${esc(r.dept)}">
          <div class="ori-dept-rank">${i < 3 ? MEDALS[i] : i + 1}</div>
          <div class="ori-dept-face">${emoji}</div>
          <div class="ori-dept-body">
            <div class="ori-dept-head">
              <span class="ori-dept-name">${esc(r.dept)}</span>
              <span class="ori-dept-mood" style="color:${colour}">${esc(word)}${
                r[metric] === null || r[metric] === undefined ? '' : ' · ' + shown(r[metric])}</span>
            </div>
            <div class="ori-track"><div class="ori-fill" style="width:${width(r[metric])}%;background:${colour}"></div></div>
            <div class="ori-dept-meta">
              ${r.filled} of ${r.eligible} answered (${num(r.pct, 0)}%) ·
              vibe ${num(r.vibe, 1)}/10 · NPS ${r.nps === null ? '—' : num(r.nps, 0)} ·
              belonging ${num(r.belonging, 1)}/10
              ${r.top_session ? ` · loudest praise: ${esc(r.top_session)}` : ''}
            </div>
          </div>
        </${tag}>`;
    }).join('') + (overview.overall ? `
      <div class="ori-dept-average">
        <b>${esc(overview.campus)} average</b>
        <span>vibe ${num(overview.overall.vibe, 1)}/10</span>
        <span>NPS ${overview.overall.nps === null ? '—' : num(overview.overall.nps, 0)}</span>
        <span>belonging ${num(overview.overall.belonging, 1)}/10</span>
        <span>${overview.overall.filled} of ${overview.overall.eligible} answered (${num(overview.overall.pct, 0)}%)</span>
      </div>` : '');

    if (clickable) {
      host.querySelectorAll('.ori-dept-click').forEach(el =>
        el.addEventListener('click', () => opts.onPick(el.dataset.dept)));
    }
  }

  /** One department's card, for a link that opens only that department. */
  function renderScorecard(host, card) {
    if (!host) return;
    if (!card || !card.dept) {
      host.innerHTML = '<div class="ori-card ori-empty-card">No scorecard for this department yet.</div>';
      return;
    }
    host.innerHTML = scorecard(card);
  }

  global.OrientationReport = {
    renderReport, renderDepartments, renderScorecard, mood, esc, num, bars,
    podium, ring, tile, ACCENTS,
  };
})(window);
