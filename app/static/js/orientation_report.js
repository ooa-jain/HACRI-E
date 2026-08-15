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
 *   OrientationReport.mood(avg) -> [word, '', colour]
 */
(function (global) {
  'use strict';

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const num = (v, digits = 1) =>
    (v === null || v === undefined) ? '—' : Number(v).toFixed(digits);

  /** What an average out of ten actually feels like. */
  const MOODS = [
    [9, 'Buzzing',        '', '#15803d'],
    [8, 'Loving it',      '', '#3f9142'],
    [7, 'Good vibes',     '', '#a3a821'],
    [6, 'Warming up',     '', '#eab308'],
    [5, 'Mixed feelings', '', '#d97706'],
    [0, 'Needs a lift',   '', '#c2410c'],
  ];
  const mood = avg => (avg === null || avg === undefined)
    ? ['No answers yet', '', '#a89e90']
    : (MOODS.find(m => avg >= m[0]) || MOODS[MOODS.length - 1]).slice(1);

  // Section accents, cycled so each section reads as its own chapter.
  const ACCENTS = ['#b9862c', '#15803d', '#8a6320', '#c2410c', '#d9a441',
                   '#c8a96a', '#3f9142', '#a8532a', '#6b5b3e'];

  const PANELS = [
    ['impactful',  'Sessions that landed',   '#15803d'],
    ['needs_work', 'Sessions needing work',  '#c2410c'],
    ['stressors',  'Biggest stressors',      '#d9a441'],
    ['keep',       'Keep next year',         '#b9862c'],
    ['stop',       'Stop next year',         '#992d12'],
    ['introduce',  'Introduce next year',    '#8a6320'],
  ];


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
          ${i + 1}
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
          <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="#f0eade" stroke-width="16"></circle>
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

  // ── Big components ────────────────────────────────────────────────────────

  /** The gradient headline: score, mood, and how the ten points were spread. */
  function hero(report) {
    const h = report.headline, c = report.coverage || {};
    const [word, emoji, colour] = mood(h.vibe);
    const vibeQ = questionOf(report, 'q2');
    const top = vibeQ ? Math.max(1, ...vibeQ.options.map(o => o.count)) : 1;

    const strip = vibeQ ? `
      <div class="ori-strip">
        ${vibeQ.options.map(o => `
          <div class="ori-strip-col" title="${o.count} student(s) rated ${esc(o.label)}/10">
            <div class="ori-strip-bar"
                 style="height:${Math.max(2, Math.round(100 * o.count / top))}%;background:${mood(Number(o.label))[2]}"></div>
          </div>`).join('')}
      </div>
      <div class="ori-strip-axis">
        ${vibeQ.options.map(o => `<span>${esc(o.label)}</span>`).join('')}
      </div>
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
      ${tile(report.count, 'Responses', '#1c1917', null)}
      ${tile(num(c.pct, 0) + '%', 'Response rate', '#15803d', c.pct)}
      ${tile(num(h.vibe, 1), 'Vibe / 10', mood(h.vibe)[2], h.vibe === null ? 0 : h.vibe * 10)}
      ${tile(h.nps === null || h.nps === undefined ? '—' : num(h.nps, 0), 'NPS', '#6b5b3e',
             h.nps === null || h.nps === undefined ? 0 : (h.nps + 100) / 2)}
      ${tile(num(h.belonging, 1), 'Belonging / 10', '#c8a96a', h.belonging === null ? 0 : h.belonging * 10)}
      ${tile(num(h.bridge, 1), 'Bridge course / 5', '#d9a441', h.bridge === null ? 0 : h.bridge * 20)}
    </div>`;
  }

  /** Promoters / passives / detractors, as a ring with a legend. */
  function npsCard(report) {
    const h = report.headline;
    const q = questionOf(report, 'q34') || h;
    const segs = [
      { value: q.promoters || 0,  colour: '#15803d', label: 'Promoters 9–10' },
      { value: q.passives || 0,   colour: '#eab308', label: 'Passives 7–8' },
      { value: q.detractors || 0, colour: '#c2410c', label: 'Detractors 0–6' },
    ];
    const total = segs.reduce((s, x) => s + x.value, 0);
    return `
      <div class="ori-card ori-card-split">
        <div>
          <div class="ori-card-title">Would they recommend JAIN?</div>
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
          <div class="ori-mini" style="--tone:#059669"><b>${q.promoters}</b><span>Promoters 9–10</span></div>
          <div class="ori-mini" style="--tone:#f59e0b"><b>${q.passives}</b><span>Passives 7–8</span></div>
          <div class="ori-mini" style="--tone:#e11d48"><b>${q.detractors}</b><span>Detractors 0–6</span></div>
        </div>
        ${scaleStrip(q, 0)}
      </div>`;
    }
    if (q.kind === 'scale') {
      return `<div class="ori-q">
        ${head}<div class="ori-q-sub">${q.answered} answered · average ${num(q.avg, 2)} / ${q.max}</div>
        ${scaleStrip(q, 1)}
      </div>`;
    }
    const suffix = q.kind === 'multi' ? ` · ${q.picks} selections` : '';
    return `<div class="ori-q">
      ${head}<div class="ori-q-sub">${q.answered} answered${suffix}</div>
      ${bars(q.options, tone, 12)}
    </div>`;
  }

  /** A 1..max distribution drawn as a coloured column strip. */
  function scaleStrip(q, from) {
    const top = Math.max(1, ...q.options.map(o => o.count));
    const scale = q.max || 10;
    return `
      <div class="ori-scale">
        ${q.options.map(o => {
          const score = Number(o.label);
          const tone = mood((score / scale) * 10)[2];
          return `<div class="ori-scale-col" title="${o.count} · ${num(o.pct, 0)}%">
            <div class="ori-scale-count">${o.count || ''}</div>
            <div class="ori-scale-track">
              <div class="ori-scale-bar" style="height:${Math.max(2, Math.round(100 * o.count / top))}%;background:${tone}"></div>
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
        <div class="ori-card-title">Who answered</div>
        <div class="ori-card-sub">${rows.length} department${rows.length === 1 ? '' : 's'}${
          (report.levels || []).length
            ? ' · ' + report.levels.map(l => `${l.count} ${esc(l.level)}`).join(' · ')
            : ''}</div>
        <div class="ori-bars">
          ${rows.map(r => bar(
            { label: r.dept, count: r.count, pct: r.pct, width: 100 * r.count / top },
            '#b9862c')).join('')}
        </div>
      </div>`;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function renderReport(host, report) {
    if (!host) return;
    if (!report || !report.count) {
      host.innerHTML = '<div class="ori-card ori-empty-card">No orientation responses for this selection yet.</div>';
      return;
    }
    host.innerHTML =
      hero(report) +
      tiles(report) +
      `<div class="ori-grid-2-wide">${npsCard(report)}${whoAnswered(report)}</div>` +
      highlightPanels(report) +
      sectionNav(report) +
      sections(report);
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
          <div class="ori-dept-rank">${i + 1}</div>
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

  global.OrientationReport = {
    renderReport, renderDepartments, mood, esc, num, bars, podium, ring, tile,
    ACCENTS,
  };
})(window);
