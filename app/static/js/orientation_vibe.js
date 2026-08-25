/**
 * orientation_vibe.js — the shared Deeksharambh report.
 *
 * The public link is handed to students, parents and heads of department, so
 * it carries the impact page's design rather than the admin console's: one
 * loud number per idea, ink outlines, hard shadows, and everything arriving
 * as it is scrolled to. The admin dashboard keeps orientation_report.js —
 * same payload, different audience, deliberately different voice.
 *
 *   OrientationVibe.renderReport(hostEl, report)
 *   OrientationVibe.renderDepartments(hostEl, overview, { onPick })
 *   OrientationVibe.renderScorecard(hostEl, scorecard)
 */
(function (global) {
  'use strict';

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const num = (v, digits = 1) =>
    (v === null || v === undefined) ? '—' : Number(v).toFixed(digits);

  const signed = v => (v === null || v === undefined)
    ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(1);

  const STILL = !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);

  const INK = '#17110a';
  const GRAPE = '#6d28d9';
  const SUN = '#f5b731';
  const LIME = '#58cc4a';
  const SKY = '#2ba7d9';
  const ROSE = '#f0567a';
  const RUST = '#c2410c';
  const EMPTY = '#e4d9c4';

  /** What an average out of ten actually feels like. */
  const MOODS = [
    [9, 'Buzzing',        '#15803d'],
    [8, 'Loving it',      '#3f9142'],
    [7, 'Good vibes',     '#7a9a1e'],
    [6, 'Warming up',     '#d9a441'],
    [5, 'Mixed feelings', '#d97706'],
    [0, 'Needs a lift',   RUST],
  ];
  const mood = avg => (avg === null || avg === undefined)
    ? ['No answers yet', '#8d8378']
    : (MOODS.find(m => avg >= m[0]) || MOODS[MOODS.length - 1]).slice(1);

  // Each section reads as its own chapter, in the page's own palette.
  const ACCENTS = [GRAPE, LIME, SUN, SKY, ROSE, '#b45309', '#15803d', '#7c2d92'];

  const PANELS = [
    ['impactful',  'Sessions that landed',  'What to protect',        LIME],
    ['needs_work', 'Sessions needing work', 'What to redesign',       RUST],
    ['stressors',  'Biggest stressors',     'Friction in week one',   SUN],
    ['keep',       'Keep next year',        'In their own words',     GRAPE],
    ['stop',       'Stop next year',        'Cut from the programme', ROSE],
    ['introduce',  'Introduce next year',   'What they are asking for', SKY],
    ['challenges', 'Challenges settling in', 'What got in the way',     '#8a6d3b'],
    ['least_connecting', 'Least connecting', 'Sessions that did not land', '#5b6b8c'],
    ['reasons',    'Why they scored us so', 'Behind the recommendation', '#2b7a78'],
  ];

  // ── Charts ────────────────────────────────────────────────────────────────
  //
  // Building the markup only queues a chart; a canvas cannot be drawn on
  // before it is in the document. `paintCharts` instantiates the queue after
  // the HTML is inserted, and drops whatever the previous render left behind.

  const CHART_FONT = 'Outfit, system-ui, sans-serif';
  const TOOLTIP = {
    backgroundColor: 'rgba(23,17,10,.94)', padding: 11, cornerRadius: 10, displayColors: false,
    titleFont: { family: CHART_FONT, size: 12, weight: '800' },
    bodyFont: { family: CHART_FONT, size: 12 },
  };

  let queued = [];
  let seq = 0;

  function chart(config, options) {
    const o = options || {};
    if (!global.Chart) return o.fallback || '';
    const id = 'ov-chart-' + (++seq);
    queued.push({ id: id, config: config });
    return `<div class="ov-chart" style="height:${o.height || 190}px">
        <canvas data-ov-chart="${id}"></canvas>
      </div>`;
  }

  function paintCharts(host) {
    (host.ovCharts || []).forEach(c => { try { c.destroy(); } catch (err) { /* gone already */ } });
    host.ovCharts = [];
    const specs = queued;
    queued = [];
    if (!global.Chart) return;
    specs.forEach(spec => {
      const canvas = host.querySelector(`canvas[data-ov-chart="${spec.id}"]`);
      if (canvas) host.ovCharts.push(new global.Chart(canvas, spec.config));
    });
  }

  /** A count-per-answer column chart. `dark` puts it on the hero. */
  function countChart(options, colours, opts) {
    const o = opts || {};
    const counts = options.map(x => x.count || 0);
    const answered = counts.reduce((sum, n) => sum + n, 0);
    const ink = o.dark ? 'rgba(255,255,255,.8)' : '#7d7060';
    const grid = o.dark ? 'rgba(255,255,255,.16)' : '#ece0cc';

    return {
      type: 'bar',
      data: {
        labels: options.map(x => x.label),
        datasets: [{
          data: counts,
          backgroundColor: colours,
          borderRadius: 7, borderSkipped: false, maxBarThickness: 52,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: STILL ? false : { duration: 700, easing: 'easeOutCubic' },
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
            border: { color: o.dark ? 'rgba(255,255,255,.3)' : '#ece0cc' },
            ticks: { color: ink, font: { family: CHART_FONT, size: 11, weight: '700' } },
          },
          y: {
            beginAtZero: true,
            grid: { color: grid, drawTicks: false },
            border: { display: false },
            ticks: {
              color: ink, font: { family: CHART_FONT, size: 10.5 },
              precision: 0, maxTicksLimit: 5, padding: 6,
            },
          },
        },
      },
    };
  }

  /** The recommendation split, as a ring. */
  function ringChart(segments) {
    return {
      type: 'doughnut',
      data: {
        labels: segments.map(s => s.label),
        datasets: [{
          data: segments.map(s => s.value),
          backgroundColor: segments.map(s => s.colour),
          borderColor: INK, borderWidth: 2, hoverOffset: 6,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '62%',
        animation: STILL ? false : { duration: 700 },
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, TOOLTIP, {
            callbacks: { label: item => `${item.label}: ${item.parsed}` },
          }),
        },
      },
    };
  }

  // ── Small components ──────────────────────────────────────────────────────

  const tile = (value, label, tone, share) => `
    <div class="ov-tile ov-rise" style="--tone:${tone}">
      <b><span data-count>${esc(value)}</span></b>
      <span>${esc(label)}</span>
      ${share === null || share === undefined ? ''
        : `<div class="ov-meter"><i data-fill="${Math.max(0, Math.min(100, share))}"></i></div>`}
    </div>`;

  /** A labelled bar. `width` scales against the biggest answer. */
  function bar(option, tone) {
    const width = Math.max(0, Math.min(100,
      option.width === undefined ? (option.pct || 0) : option.width));
    return `
      <div class="ov-bar">
        <div class="ov-bar-head">
          <span class="ov-bar-label" title="${esc(option.label)}">${esc(option.label)}</span>
          <span class="ov-bar-value">${option.count} · ${num(option.pct, 0)}%</span>
        </div>
        <div class="ov-track" style="--tone:${tone}"><i data-fill="${width}"></i></div>
      </div>`;
  }

  const bars = (options, tone, limit) => {
    const rows = limit ? options.slice(0, limit) : options;
    return rows.length
      ? rows.map(o => bar(o, tone)).join('')
      : '<div class="ov-empty">No answers yet</div>';
  };

  /** Top answers as a ranked list. */
  function podium(options, tone, limit = 5) {
    if (!options || !options.length) return '<div class="ov-empty">No answers yet</div>';
    const top = Math.max(1, ...options.map(o => o.count));
    return options.slice(0, limit).map((o, i) => `
      <div class="ov-rank">
        <div class="ov-rank-badge" style="--tone:${tone}">${i + 1}</div>
        <div class="ov-rank-body">
          <div class="ov-bar-head">
            <span class="ov-bar-label" title="${esc(o.label)}">${esc(o.label)}</span>
          </div>
          <div class="ov-track" style="--tone:${tone}"><i data-fill="${100 * o.count / top}"></i></div>
        </div>
        <div class="ov-rank-count">${o.count}<small>${num(o.pct, 0)}%</small></div>
      </div>`).join('');
  }

  const questionOf = (report, key) => {
    for (const section of report.sections || []) {
      const found = section.questions.find(q => q.key === key);
      if (found) return found;
    }
    return null;
  };

  // ── Big components ────────────────────────────────────────────────────────

  /** The headline: the one number, the mood, and how the ten points fell. */
  function hero(report) {
    const h = report.headline, c = report.coverage || {};
    const [word, colour] = mood(h.vibe);
    const vibeQ = questionOf(report, 'q2');

    const spread = vibeQ ? `
      <div class="ov-hero-panel">
        <div class="ov-hero-kicker">How the ten points fell</div>
        ${chart(countChart(vibeQ.options,
                           vibeQ.options.map(o => (o.count ? mood(Number(o.label))[1] : 'rgba(255,255,255,.16)')),
                           { dark: true, title: label => `Rated ${label} out of 10` }),
                { height: 176 })}
        <div class="ov-hero-note">1 — I wanted to leave · 10 — I wish it never ended</div>
      </div>` : '';

    return `
      <section class="ov-hero ov-rise" style="--mood:${colour}">
        <div class="ov-hero-score">
          <div class="ov-hero-kicker">Overall vibe of the students</div>
          <div class="ov-hero-big"><span data-count>${num(h.vibe, 1)}</span><small>/ 10</small></div>
          <div class="ov-hero-mood">${esc(word)}</div>
          <div class="ov-hero-split">
            <div class="ov-half">
              <b data-count>${report.count}</b>
              <span>Students answered</span>
              <i>of ${c.eligible || report.count} in scope</i>
            </div>
            <div class="ov-half">
              <b data-count>${num(c.pct, 0)}%</b>
              <span>Response rate</span>
              <i>${c.pending || 0} still to answer</i>
            </div>
          </div>
        </div>
        ${spread}
      </section>`;
  }

  function tiles(report) {
    const h = report.headline, c = report.coverage || {};
    const npsValue = h.nps === null || h.nps === undefined ? '—' : num(h.nps, 0);
    return `<div class="ov-tiles">
      ${tile(num(h.vibe, 1), 'Vibe / 10', mood(h.vibe)[1], h.vibe === null ? 0 : h.vibe * 10)}
      ${tile(npsValue, 'Net promoter score', GRAPE,
             h.nps === null || h.nps === undefined ? 0 : (h.nps + 100) / 2)}
      ${tile(num(h.belonging, 1), 'I belong here / 10', SKY, h.belonging === null ? 0 : h.belonging * 10)}
      ${tile(num(h.success, 1), 'I can succeed / 10', LIME, h.success === null ? 0 : h.success * 10)}
      ${tile(num(h.bridge, 1), 'Bridge course / 5', SUN, h.bridge === null ? 0 : h.bridge * 20)}
      ${tile(String(report.count), 'Responses', INK, null)}
    </div>`;
  }

  /** Promoters, passives and detractors — the ring and the three counts. */
  function npsCard(report) {
    const h = report.headline;
    const q = questionOf(report, 'q34') || h;
    const segs = [
      { value: q.promoters || 0,  colour: LIME, label: 'Promoters 9–10' },
      { value: q.passives || 0,   colour: SUN,  label: 'Passives 7–8' },
      { value: q.detractors || 0, colour: RUST, label: 'Detractors 0–6' },
    ];
    const total = segs.reduce((s, x) => s + x.value, 0);
    const nps = h.nps === null || h.nps === undefined ? '—' : (h.nps > 0 ? '+' : '') + num(h.nps, 0);

    return `
      <section class="ov-card ov-rise">
        <span class="ov-kicker">Would they recommend JAIN?</span>
        <h2 class="ov-title">${nps} net promoter score</h2>
        <p class="ov-sub">${total} student${total === 1 ? '' : 's'} answered, averaging
          ${num(h.nps_avg, 2)} out of 10. Promoters minus detractors, as a share of everyone who
          answered.</p>
        ${chart(ringChart(segs), { height: 210 })}
        <div class="ov-split3">
          ${segs.map(s => `
            <div class="ov-cell" style="--tone:${s.colour}">
              <b>${s.value}</b>
              <span>${esc(s.label)}</span>
              <small>${total ? Math.round(100 * s.value / total) : 0}% of those who answered</small>
            </div>`).join('')}
        </div>
      </section>`;
  }

  /** Who actually filled the form. */
  function whoAnswered(report) {
    const rows = report.departments || [];
    if (!rows.length) return '';
    const top = Math.max(1, ...rows.map(r => r.count));
    const levels = report.levels || [];
    return `
      <section class="ov-card ov-rise">
        <span class="ov-kicker">Who answered</span>
        <h2 class="ov-title">${rows.length} department${rows.length === 1 ? '' : 's'}</h2>
        <p class="ov-sub">${levels.length
          ? levels.map(l => `${l.count} ${esc(l.level)}`).join(' · ')
          : 'Every reply counted here.'}</p>
        <div style="margin-top:16px">
          ${rows.map(r => bar(
            { label: r.dept, count: r.count, pct: r.pct, width: 100 * r.count / top }, GRAPE)).join('')}
        </div>
      </section>`;
  }

  function highlightPanels(report) {
    const highlights = report.highlights || {};
    return `<div class="ov-panels">
      ${PANELS.map(([key, title, note, tone], i) => `
        <section class="ov-panel ov-rise" style="--tone:${tone};--d:${i * 60}ms">
          <div class="ov-panel-head">
            <span class="ov-panel-title">${esc(title)}</span>
            <span class="ov-panel-note">${esc(note)}</span>
          </div>
          ${podium(highlights[key], tone, 5)}
        </section>`).join('')}
    </div>`;
  }

  /** A 1..max distribution, plotted against a counted axis. */
  function scaleStrip(q) {
    const scale = q.max || 10;
    const colours = q.options.map(o =>
      (o.count ? mood((Number(o.label) / scale) * 10)[1] : EMPTY));
    return chart(countChart(q.options, colours,
                            { title: label => `Answered ${label} of ${scale}` }),
                 { height: 168 });
  }

  function questionCard(q, tone) {
    const head = `<div class="ov-q-title">${esc(q.label)}</div>`;

    if (q.kind === 'matrix') {
      return `<div class="ov-q">
        ${head}<div class="ov-q-sub">${q.answered} answered</div>
        ${q.rows.map(r => `
          <div class="ov-q-row">
            <div class="ov-q-row-label">${esc(r.label)}</div>
            ${bars(r.options, tone)}
          </div>`).join('')}
      </div>`;
    }
    if (q.kind === 'nps') {
      return `<div class="ov-q">
        ${head}
        <div class="ov-q-sub">${q.answered} answered · average ${num(q.avg, 2)} / 10 · NPS ${num(q.nps, 0)}</div>
        <div class="ov-split3">
          <div class="ov-cell" style="--tone:${LIME}"><b>${q.promoters}</b><span>Promoters</span></div>
          <div class="ov-cell" style="--tone:${SUN}"><b>${q.passives}</b><span>Passives</span></div>
          <div class="ov-cell" style="--tone:${RUST}"><b>${q.detractors}</b><span>Detractors</span></div>
        </div>
        ${scaleStrip(q)}
      </div>`;
    }
    if (q.kind === 'scale') {
      return `<div class="ov-q">
        ${head}<div class="ov-q-sub">${q.answered} answered · average ${num(q.avg, 2)} / ${q.max}</div>
        ${scaleStrip(q)}
      </div>`;
    }
    const suffix = q.kind === 'multi' ? ` · ${q.picks} selections` : '';
    return `<div class="ov-q">
      ${head}<div class="ov-q-sub">${q.answered} answered${suffix}</div>
      ${bars(q.options, tone, 12)}
    </div>`;
  }

  function sections(report) {
    return (report.sections || []).map((s, i) => {
      const tone = ACCENTS[i % ACCENTS.length];
      return `
        <section class="ov-card ov-rise" id="ov-sec-${i}" style="--tone:${tone}">
          <div class="ov-section-head">
            <div>
              <span class="ov-kicker" style="color:${tone}">Section ${i + 1}</span>
              <h2 class="ov-title">${esc(s.title)}</h2>
            </div>
            <span class="ov-panel-note">${s.questions.length} question${s.questions.length === 1 ? '' : 's'}</span>
          </div>
          <div class="ov-qgrid">${s.questions.map(q => questionCard(q, tone)).join('')}</div>
        </section>`;
    }).join('');
  }

  function sectionNav(report) {
    if (!(report.sections || []).length) return '';
    return `<nav class="ov-nav ov-rise">
      ${report.sections.map((s, i) =>
        `<a class="ov-nav-chip" href="#ov-sec-${i}" style="--tone:${ACCENTS[i % ACCENTS.length]}">${esc(s.title)}</a>`
      ).join('')}
    </nav>`;
  }

  // ── Motion ────────────────────────────────────────────────────────────────
  //
  // Cards rise as they are reached, figures count up to their value, and bars
  // grow to their share — once each, and never under prefers-reduced-motion.

  function countUp(el) {
    const raw = el.textContent.trim();
    const m = /^([+-]?\d[\d,]*)(\.\d+)?(%?)$/.exec(raw);
    if (!m) return;
    const target = parseFloat(raw.replace(/[,%]/g, ''));
    const decimals = m[2] ? m[2].length - 1 : 0;
    const suffix = m[3] || '';
    if (STILL || !target) return;
    const started = performance.now(), span = 900;
    const tick = now => {
      const t = Math.min((now - started) / span, 1);
      el.textContent = (target * (1 - Math.pow(1 - t, 3))).toFixed(decimals) + suffix;
      if (t < 1) requestAnimationFrame(tick); else el.textContent = raw;
    };
    requestAnimationFrame(tick);
  }

  function fill(el) {
    const target = el.getAttribute('data-fill') || '0';
    if (STILL) { el.style.width = target + '%'; return; }
    requestAnimationFrame(() => requestAnimationFrame(() => { el.style.width = target + '%'; }));
  }

  function animate(host) {
    const show = el => {
      el.classList.add('in');
      el.querySelectorAll('[data-count]').forEach(countUp);
      el.querySelectorAll('[data-fill]').forEach(fill);
    };
    if (STILL || !global.IntersectionObserver) {
      host.querySelectorAll('.ov-rise').forEach(show);
      return;
    }
    const io = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        show(entry.target);
        io.unobserve(entry.target);
      });
    }, { threshold: .1, rootMargin: '0px 0px -5% 0px' });
    host.querySelectorAll('.ov-rise').forEach(el => io.observe(el));
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function paint(host, markup) {
    host.innerHTML = markup;
    paintCharts(host);
    animate(host);
  }

  function renderReport(host, report) {
    if (!host) return;
    queued = [];
    if (!report || !report.count) {
      paintCharts(host);
      host.innerHTML = '<div class="ov-empty-card">No orientation responses for this selection yet.</div>';
      return;
    }
    paint(host,
      hero(report) +
      tiles(report) +
      `<div class="ov-two">${npsCard(report)}${whoAnswered(report)}</div>` +
      highlightPanels(report) +
      sectionNav(report) +
      sections(report));
  }

  /** The leaderboard. `onPick` gets the department name, if given. */
  function renderDepartments(host, overview, options) {
    if (!host) return;
    queued = [];
    const opts = options || {};
    const rows = [...((overview || {}).departments || [])]
      .sort((a, b) => (b.vibe ?? -999) - (a.vibe ?? -999));
    if (!rows.length) {
      host.innerHTML = '<div class="ov-empty-card">No departments have answered yet.</div>';
      return;
    }

    const clickable = typeof opts.onPick === 'function';
    const tag = clickable ? 'button' : 'div';
    const overall = overview.overall;

    paint(host, `<div class="ov-depts">${rows.map((r, i) => {
      const [word, colour] = mood(r.vibe);
      return `
        <${tag} ${clickable ? 'type="button"' : ''} class="ov-dept ov-rise"
                style="--tone:${colour};--d:${Math.min(i, 8) * 40}ms" data-dept="${esc(r.dept)}">
          <div class="ov-dept-rank">${i + 1}</div>
          <div class="ov-dept-body">
            <div class="ov-dept-name">${esc(r.dept)}</div>
            <div class="ov-dept-meta">
              ${r.filled} of ${r.eligible} answered (${num(r.pct, 0)}%) ·
              NPS ${r.nps === null ? '—' : num(r.nps, 0)} ·
              belonging ${num(r.belonging, 1)}/10${
                r.top_session ? ` · loudest praise: ${esc(r.top_session)}` : ''}
            </div>
            <div class="ov-track" style="--tone:${colour}">
              <i data-fill="${r.vibe === null || r.vibe === undefined ? 2 : r.vibe * 10}"></i>
            </div>
          </div>
          <div class="ov-dept-score" style="--tone:${colour}">
            <b>${num(r.vibe, 1)}</b><span>${esc(word)}</span>
          </div>
        </${tag}>`;
    }).join('')}
    ${overall ? `
      <div class="ov-dept-average ov-rise">
        <b>${esc(overview.campus)} average</b>
        <span>vibe ${num(overall.vibe, 1)}/10</span>
        <span>NPS ${overall.nps === null ? '—' : num(overall.nps, 0)}</span>
        <span>belonging ${num(overall.belonging, 1)}/10</span>
        <span>${overall.filled} of ${overall.eligible} answered (${num(overall.pct, 0)}%)</span>
      </div>` : ''}
    </div>`);

    if (clickable) {
      host.querySelectorAll('.ov-dept').forEach(el =>
        el.addEventListener('click', () => opts.onPick(el.dataset.dept)));
    }
  }

  /** One department's card, for a link that opens only that department. */
  function renderScorecard(host, card) {
    if (!host) return;
    queued = [];
    if (!card || !card.dept) {
      host.innerHTML = '<div class="ov-empty-card">No scorecard for this department yet.</div>';
      return;
    }
    const d = card.department || {};
    const [word, colour] = mood(d.vibe);

    const metrics = (card.metrics || []).map((m, i) => {
      const scale = m.max || 10;
      const width = v => (v === null || v === undefined) ? 0
        : (m.key === 'nps' ? Math.max(0, (v + 100) / 2) : Math.max(0, Math.min(100, 100 * v / scale)));
      const shown = v => (v === null || v === undefined) ? '—'
        : (m.key === 'nps' ? num(v, 0) : num(v, 1));
      const ahead = m.delta === null || m.delta === undefined ? null : m.delta >= 0;
      return `
        <div class="ov-metric ov-rise" style="--d:${i * 60}ms">
          <div class="ov-bar-head">
            <span class="ov-bar-label">${esc(m.label)}</span>
            <span class="ov-metric-value">${shown(m.value)}${m.max ? `<small> / ${m.max}</small>` : ''}</span>
          </div>
          <div class="ov-track" style="--tone:${colour}">
            <i data-fill="${width(m.value)}"></i>
            ${m.campus === null || m.campus === undefined ? ''
              : `<u style="left:${width(m.campus)}%" title="Campus average ${shown(m.campus)}"></u>`}
          </div>
          <div class="ov-metric-note ${ahead === null ? '' : (ahead ? 'up' : 'down')}">
            ${ahead === null ? 'No campus figure to compare with'
              : `${signed(m.delta)} against the ${esc(card.campus)} average of ${shown(m.campus)}`}
          </div>
        </div>`;
    }).join('');

    paint(host, `
      <section class="ov-card ov-rise ov-scorecard" style="--tone:${colour}">
        <span class="ov-kicker">Vibe scorecard</span>
        <h2 class="ov-title">${esc(card.dept)}</h2>
        <p class="ov-sub">
          ${card.rank ? `Ranked <b>${card.rank}</b> of ${card.of} departments on vibe in ${esc(card.campus)}.`
                      : `In ${esc(card.campus)}.`}
          ${d.filled} of ${d.eligible} students answered.
        </p>
        <div class="ov-score-head">
          <div class="ov-score-big">
            <b><span data-count>${num(d.vibe, 1)}</span><small>/ 10</small></b>
            <span>${esc(word)}</span>
          </div>
          <div class="ov-score-facts">
            <div><b data-count>${card.rank || '—'}</b><span>Rank of ${card.of}</span></div>
            <div><b data-count>${d.filled}</b><span>Answered</span></div>
            <div><b data-count>${num(d.pct, 0)}%</b><span>Response rate</span></div>
          </div>
        </div>
        <div class="ov-metrics">${metrics}</div>
        ${d.top_session || d.top_stressor ? `
          <div class="ov-score-words">
            ${d.top_session ? `<div class="ov-cell" style="--tone:${LIME}">
              <span>Loudest praise</span><b class="ov-quote">${esc(d.top_session)}</b></div>` : ''}
            ${d.top_stressor ? `<div class="ov-cell" style="--tone:${SUN}">
              <span>Biggest stressor</span><b class="ov-quote">${esc(d.top_stressor)}</b></div>` : ''}
          </div>` : ''}
      </section>`);
  }

  global.OrientationVibe = { renderReport, renderDepartments, renderScorecard, mood, esc, num };
})(window);
