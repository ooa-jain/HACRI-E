/**
 * cohort_report.js — the outcome and impact report, drawn once for both homes.
 *
 * The survey admin's Cohort page and the public shared page call the same
 * renderer, so a committee reading the link sees exactly what the admin sees.
 * Deliberately typographic: no emoji, no decoration that isn't carrying a
 * number.
 *
 *   CohortReport.render(hostEl, report)
 */
(function (global) {
  'use strict';

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const num = (v, digits = 1) =>
    (v === null || v === undefined) ? '—' : Number(v).toFixed(digits);

  const signed = (v, digits = 2) =>
    (v === null || v === undefined) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(digits);

  const pct = v => (v === null || v === undefined) ? '—' : Number(v).toFixed(0) + '%';

  const BASELINE = '#3b3020';
  const POST = '#15803d';
  const STAGE_TONES = ['#1f1a12', '#3b3020', '#d9a441', '#15803d'];

  const delta = (after, before) =>
    (after === null || after === undefined || before === null || before === undefined)
      ? null : Math.round((after - before) * 100) / 100;

  // ── Blocks ────────────────────────────────────────────────────────────────

  /** The wire flow: registered, baseline, Deeksharambh, post. */
  function journey(j) {
    const stages = j.stages || [];
    if (!stages.length) return '';

    const nodes = stages.map((s, i) => `
      ${i ? `<div class="coh-flow-link">
               <span class="coh-flow-pct">${pct(s.of_previous)}</span>
               <span class="coh-flow-arrow"></span>
               ${s.dropped ? `<span class="coh-flow-drop">${s.dropped} lost</span>` : ''}
             </div>` : ''}
      <div class="coh-node" style="--tone:${STAGE_TONES[i % STAGE_TONES.length]}">
        <div class="coh-node-step">Step ${i + 1}</div>
        <div class="coh-node-label">${esc(s.label)}</div>
        <div class="coh-node-count">${s.count}</div>
        <div class="coh-node-share">${pct(s.of_registered)} of registered</div>
        <div class="coh-node-blurb">${esc(s.blurb)}</div>
      </div>`).join('');

    return `
      <section class="coh-card">
        <div class="coh-card-head">
          <div>
            <h2 class="coh-h2">The journey</h2>
            <p class="coh-sub">Students register, complete the baseline survey, then the Deeksharambh
              orientation, and finally the post-workshop survey. Each link shows how many carried
              through to the next step.</p>
          </div>
        </div>
        <div class="coh-flow">${nodes}</div>
        <div class="coh-owed">
          ${owed('Baseline still to complete', j.pending_pre, '#c2410c')}
          ${owed('Deeksharambh still to complete', j.pending_orientation, '#d9a441')}
          ${owed('Post survey still to complete', j.pending_post, BASELINE)}
          ${owed('Finished all three steps', j.fully_done, POST, pct(j.completion_pct))}
        </div>
      </section>`;
  }

  const owed = (label, value, tone, note) => `
    <div class="coh-owed-item" style="--tone:${tone}">
      <div class="coh-owed-value">${value}${note ? `<span>${esc(note)}</span>` : ''}</div>
      <div class="coh-owed-label">${esc(label)}</div>
    </div>`;

  /** A stat tile: value, label, optional comparison note. */
  const tile = (value, label, tone, note) => `
    <div class="coh-tile" style="--tone:${tone}">
      <div class="coh-tile-value">${esc(value)}</div>
      <div class="coh-tile-label">${esc(label)}</div>
      ${note ? `<div class="coh-tile-note">${esc(note)}</div>` : ''}
    </div>`;

  /** A histogram drawn as columns — "how the graph falls". */
  function histogram(rows, tone, caption) {
    const top = Math.max(1, ...rows.map(r => r.count));
    return `
      <div class="coh-hist">
        <div class="coh-hist-plot">
          ${rows.map(r => `
            <div class="coh-hist-col" title="${r.count} students · ${num(r.pct, 1)}%">
              <div class="coh-hist-count">${r.count || ''}</div>
              <div class="coh-hist-track">
                <div class="coh-hist-bar" style="height:${Math.round(100 * r.count / top)}%;background:${tone}"></div>
              </div>
              <div class="coh-hist-label">${esc(r.label)}</div>
            </div>`).join('')}
        </div>
        ${caption ? `<div class="coh-hist-caption">${esc(caption)}</div>` : ''}
      </div>`;
  }

  /** Two bars per row: baseline against post. */
  function compareRows(pre, post, tone1, tone2) {
    const top = Math.max(1, ...pre.map(r => r.count), ...post.map(r => r.count));
    return pre.map((row, i) => {
      const after = post[i] || { count: 0, pct: 0 };
      return `
        <div class="coh-compare">
          <div class="coh-compare-label">${esc(row.label)}</div>
          <div class="coh-compare-bars">
            <div class="coh-compare-row">
              <div class="coh-track"><div class="coh-fill" style="width:${100 * row.count / top}%;background:${tone1}"></div></div>
              <span>${row.count}</span>
            </div>
            <div class="coh-compare-row">
              <div class="coh-track"><div class="coh-fill" style="width:${100 * after.count / top}%;background:${tone2}"></div></div>
              <span>${after.count}</span>
            </div>
          </div>
        </div>`;
    }).join('');
  }

  /** Outcome — the baseline half of the page. */
  function outcome(report) {
    const o = report.outcome;
    if (!o.scored) {
      return `<section class="coh-card coh-bracket" style="--tone:${BASELINE}">
        ${bracketHead('Outcome', 'Where the cohort started', 'Baseline survey')}
        <p class="coh-empty">No scored baseline responses in this scope yet.</p>
      </section>`;
    }
    return `
      <section class="coh-card coh-bracket" style="--tone:${BASELINE}">
        ${bracketHead('Outcome', 'Where the cohort started', 'Baseline survey')}
        <div class="coh-tiles">
          ${tile(o.scored, 'Scored responses', '#1f1a12')}
          ${tile(num(o.avg_lit, 2), 'AI Literacy / 5', BASELINE)}
          ${tile(num(o.avg_read, 2), 'AI Readiness / 5', POST)}
          ${tile(num(o.avg_overall, 2), 'Overall / 5', '#d9a441')}
        </div>
        <div class="coh-grid-2">
          <div class="coh-panel">
            <h3 class="coh-h3">AI Literacy — how the scores fell</h3>
            ${histogram(o.literacy, BASELINE, 'Students by score band, 1 to 5')}
          </div>
          <div class="coh-panel">
            <h3 class="coh-h3">AI Readiness — how the scores fell</h3>
            ${histogram(o.readiness, BASELINE, 'Students by score band, 1 to 5')}
          </div>
        </div>
        <div class="coh-grid-2">
          <div class="coh-panel">
            <h3 class="coh-h3">Quadrant at baseline</h3>
            ${shareList(o.quadrants, BASELINE)}
          </div>
          <div class="coh-panel">
            <h3 class="coh-h3">Band at baseline</h3>
            ${shareList(o.bands, BASELINE)}
          </div>
        </div>
      </section>`;
  }

  /** Impact — the post-workshop half, always read against the baseline. */
  function impact(report) {
    const o = report.outcome, i = report.impact, m = report.movement;
    if (!i.scored) {
      return `<section class="coh-card coh-bracket" style="--tone:${POST}">
        ${bracketHead('Impact', 'Where the cohort ended up', 'Post-workshop survey')}
        <p class="coh-empty">No scored post-workshop responses in this scope yet.</p>
      </section>`;
    }
    const dLit = delta(i.avg_lit, o.avg_lit);
    const dRead = delta(i.avg_read, o.avg_read);
    const dAll = delta(i.avg_overall, o.avg_overall);

    return `
      <section class="coh-card coh-bracket" style="--tone:${POST}">
        ${bracketHead('Impact', 'Where the cohort ended up', 'Post-workshop survey')}
        <div class="coh-tiles">
          ${tile(i.scored, 'Scored responses', '#1f1a12')}
          ${tile(num(i.avg_lit, 2), 'AI Literacy / 5', BASELINE, `${signed(dLit)} on baseline`)}
          ${tile(num(i.avg_read, 2), 'AI Readiness / 5', POST, `${signed(dRead)} on baseline`)}
          ${tile(signed(dAll), 'Overall change', dAll !== null && dAll < 0 ? '#c2410c' : '#d9a441')}
        </div>
        <div class="coh-grid-2">
          <div class="coh-panel">
            <h3 class="coh-h3">AI Literacy — how the scores fell</h3>
            ${histogram(i.literacy, POST, 'Students by score band, 1 to 5')}
          </div>
          <div class="coh-panel">
            <h3 class="coh-h3">AI Readiness — how the scores fell</h3>
            ${histogram(i.readiness, POST, 'Students by score band, 1 to 5')}
          </div>
        </div>
        <div class="coh-panel">
          <div class="coh-legend">
            <span><i style="background:${BASELINE}"></i>Baseline</span>
            <span><i style="background:${POST}"></i>Post workshop</span>
          </div>
          <h3 class="coh-h3">The shift, band by band</h3>
          <div class="coh-grid-2">
            <div>
              <div class="coh-panel-kicker">AI Literacy</div>
              ${compareRows(o.literacy, i.literacy, BASELINE, POST)}
            </div>
            <div>
              <div class="coh-panel-kicker">AI Readiness</div>
              ${compareRows(o.readiness, i.readiness, BASELINE, POST)}
            </div>
          </div>
        </div>
        <div class="coh-grid-2">
          <div class="coh-panel">
            <h3 class="coh-h3">Movement of matched students</h3>
            <p class="coh-sub">${m.matched} student${m.matched === 1 ? '' : 's'} completed both surveys.</p>
            ${m.matched ? `
              <div class="coh-split">
                ${splitCell('Improved', m.gained, m.matched, POST)}
                ${splitCell('No change', m.unchanged, m.matched, '#7c7266')}
                ${splitCell('Declined', m.declined, m.matched, '#c2410c')}
              </div>
              <div class="coh-facts">
                <div><span>Average literacy change</span><b>${signed(m.avg_delta_lit)}</b></div>
                <div><span>Average readiness change</span><b>${signed(m.avg_delta_read)}</b></div>
                <div><span>Changed quadrant</span><b>${m.moved_quadrant}</b></div>
              </div>` : '<p class="coh-empty">Nobody has completed both surveys yet.</p>'}
          </div>
          <div class="coh-panel">
            <h3 class="coh-h3">Quadrant mix, before and after</h3>
            <div class="coh-legend">
              <span><i style="background:${BASELINE}"></i>Baseline</span>
              <span><i style="background:${POST}"></i>Post workshop</span>
            </div>
            ${compareRows(o.quadrants, i.quadrants, BASELINE, POST)}
          </div>
        </div>
      </section>`;
  }

  const bracketHead = (bracket, title, kicker) => `
    <div class="coh-bracket-head">
      <span class="coh-bracket-tag">${esc(bracket)}</span>
      <div>
        <h2 class="coh-h2">${esc(title)}</h2>
        <p class="coh-sub">${esc(kicker)}</p>
      </div>
    </div>`;

  const splitCell = (label, value, total, tone) => `
    <div class="coh-split-cell" style="--tone:${tone}">
      <div class="coh-split-value">${value}</div>
      <div class="coh-split-pct">${total ? Math.round(100 * value / total) : 0}%</div>
      <div class="coh-split-label">${esc(label)}</div>
    </div>`;

  function shareList(rows, tone) {
    const top = Math.max(1, ...rows.map(r => r.count));
    return rows.map(r => `
      <div class="coh-bar">
        <div class="coh-bar-head">
          <span>${esc(r.label)}</span>
          <span class="coh-bar-value">${r.count} · ${num(r.pct, 0)}%</span>
        </div>
        <div class="coh-track"><div class="coh-fill" style="width:${100 * r.count / top}%;background:${tone}"></div></div>
      </div>`).join('');
  }

  /** Where each department started and where it reached, on one 1-5 scale.
   *
   * The single picture the report is really about: a dot at the baseline, a dot
   * after the workshop, and the distance between them.
   */
  function trajectoryRows(report) {
    const rows = [];
    if (report.outcome.avg_overall !== null && report.outcome.avg_overall !== undefined) {
      rows.push({
        dept: 'Overall', overall: true,
        pre: report.outcome.avg_overall,
        post: report.impact.avg_overall,
        delta: delta(report.impact.avg_overall, report.outcome.avg_overall),
        matched: report.movement.matched,
      });
    }
    (report.departments || []).forEach(d => {
      if (d.pre_avg === null || d.pre_avg === undefined) return;
      rows.push({ dept: d.dept, pre: d.pre_avg, post: d.post_avg, delta: d.delta, matched: d.matched });
    });
    return rows;
  }

  const scaleX = v => Math.max(0, Math.min(100, ((v - 1) / 4) * 100));

  function trajectoryTrack(row) {
    const from = scaleX(row.pre);
    const to = row.post === null || row.post === undefined ? null : scaleX(row.post);
    const rising = row.delta === null || row.delta === undefined ? true : row.delta >= 0;
    const bar = to === null ? '' : `
      <span class="coh-traj-link ${rising ? 'up' : 'down'}"
            style="left:${Math.min(from, to)}%;width:${Math.abs(to - from)}%"></span>
      <span class="coh-traj-dot post" style="left:${to}%"><b>${num(row.post, 2)}</b></span>`;
    return `
      <div class="coh-traj-track">
        ${[1, 2, 3, 4, 5].map(t => `<span class="coh-traj-tick" style="left:${scaleX(t)}%"></span>`).join('')}
        ${bar}
        <span class="coh-traj-dot pre" style="left:${from}%"><b>${num(row.pre, 2)}</b></span>
      </div>`;
  }

  function trajectoryBody(report, dept) {
    let rows = trajectoryRows(report);
    if (dept) rows = rows.filter(r => r.overall || r.dept === dept);
    if (!rows.length) return '<p class="coh-empty">No scored responses in this scope yet.</p>';

    return `
      <div class="coh-traj">
        ${rows.map(r => `
          <div class="coh-traj-row${r.overall ? ' overall' : ''}">
            <div class="coh-traj-name">${esc(r.dept)}</div>
            ${trajectoryTrack(r)}
            <div class="coh-traj-delta ${r.delta === null || r.delta === undefined ? '' : (r.delta < 0 ? 'down' : 'up')}">
              ${signed(r.delta)}
            </div>
          </div>`).join('')}
        <div class="coh-traj-axis">
          ${[1, 2, 3, 4, 5].map(t => `<span style="left:${scaleX(t)}%">${t}</span>`).join('')}
        </div>
      </div>`;
  }

  function trajectory(report) {
    const rows = trajectoryRows(report);
    if (!rows.length) return '';
    const options = rows.filter(r => !r.overall).map(r => r.dept);

    return `
      <section class="coh-card coh-traj-card">
        <div class="coh-card-head">
          <div>
            <h2 class="coh-h2">From baseline to post workshop</h2>
            <p class="coh-sub">Where the cohort started and where it reached, on the same 1 to 5 scale.
              The left dot is the baseline, the right dot is the post-workshop score, and the bar between
              them is the distance travelled.</p>
          </div>
          ${options.length > 1 ? `
            <select class="coh-select" id="coh-traj-dept">
              <option value="">Every department</option>
              ${options.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('')}
            </select>` : ''}
        </div>
        <div class="coh-legend">
          <span><i style="background:${BASELINE}"></i>Baseline</span>
          <span><i style="background:${POST}"></i>Post workshop</span>
        </div>
        <div id="coh-traj-body">${trajectoryBody(report, '')}</div>
      </section>`;
  }

  /** AI Literacy × AI Readiness, with an arrow per student from pre to post.
   *
   * Drawn as inline SVG on a 1-5 square split at 3, so the four quadrants read
   * the way the student's own results page presents them.
   */
  function quadrantChart(report) {
    const q = report.quadrant || {};
    const pre = q.pre || [], post = q.post || [], pairs = q.pairs || [];
    if (!pre.length && !post.length) return '';

    // Plot area inside the SVG viewBox, leaving room for the axes.
    const W = 620, H = 520, L = 58, R = 22, T = 20, B = 52;
    const px = v => L + ((v - 1) / 4) * (W - L - R);
    const py = v => H - B - ((v - 1) / 4) * (H - T - B);
    const mid = { x: px(3), y: py(3) };

    const band = (x, y, w, h, fill) =>
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}"></rect>`;

    const quadrantLabel = (x, y, anchor, title, sub, colour) => `
      <text x="${x}" y="${y}" text-anchor="${anchor}" fill="${colour}"
            font-size="11" font-weight="700">${esc(title)}</text>
      <text x="${x}" y="${y + 13}" text-anchor="${anchor}" fill="${colour}"
            font-size="9.5" opacity=".8">${esc(sub)}</text>`;

    const arrows = pairs.map(p => {
      const x1 = px(p.pre_lit), y1 = py(p.pre_read);
      const x2 = px(p.post_lit), y2 = py(p.post_read);
      const rising = (p.post_lit + p.post_read) >= (p.pre_lit + p.pre_read);
      return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"
                    stroke="${rising ? POST : '#c2410c'}" stroke-width="1.1"
                    opacity=".45" marker-end="url(#coh-arrow-${rising ? 'up' : 'down'})"></line>`;
    }).join('');

    const dots = (points, fill, radius) => points.map(p =>
      `<circle cx="${px(p.lit)}" cy="${py(p.read)}" r="${radius}" fill="${fill}"
               fill-opacity=".62" stroke="#fff" stroke-width=".8"></circle>`).join('');

    const centreMark = (point, fill, label) => {
      if (!point) return '';
      return `
        <g>
          <circle cx="${px(point.lit)}" cy="${py(point.read)}" r="8" fill="${fill}"
                  stroke="#fff" stroke-width="2"></circle>
          <text x="${px(point.lit)}" y="${py(point.read) - 15}" text-anchor="middle"
                font-size="10.5" font-weight="700" fill="${fill}"
                paint-order="stroke" stroke="#fff" stroke-width="3.5"
                stroke-linejoin="round">${esc(label)}</text>
        </g>`;
    };

    const ticks = [1, 2, 3, 4, 5];

    return `
      <section class="coh-card">
        <div class="coh-card-head">
          <div>
            <h2 class="coh-h2">Literacy against readiness</h2>
            <p class="coh-sub">Every student placed by what they understand about AI and how ready they
              feel to use it. Each line runs from where a student sat at the baseline to where they sat
              after the workshop; the large markers are the cohort average.</p>
          </div>
        </div>
        <div class="coh-legend">
          <span><i class="round" style="background:${BASELINE}"></i>Baseline</span>
          <span><i class="round" style="background:${POST}"></i>Post workshop</span>
          <span><i style="background:#be123c"></i>Moved backwards</span>
        </div>
        <div class="coh-quad">
          <svg viewBox="0 0 ${W} ${H}" role="img"
               aria-label="AI literacy against AI readiness, baseline and post workshop">
            <defs>
              <marker id="coh-arrow-up" viewBox="0 0 8 8" refX="7" refY="4"
                      markerWidth="5" markerHeight="5" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="${POST}"></path>
              </marker>
              <marker id="coh-arrow-down" viewBox="0 0 8 8" refX="7" refY="4"
                      markerWidth="5" markerHeight="5" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="#be123c"></path>
              </marker>
            </defs>

            ${band(L, T, mid.x - L, mid.y - T, '#fff9e6')}
            ${band(mid.x, T, W - R - mid.x, mid.y - T, '#ebf5ec')}
            ${band(L, mid.y, mid.x - L, H - B - mid.y, '#fbeee6')}
            ${band(mid.x, mid.y, W - R - mid.x, H - B - mid.y, '#f4eee2')}

            ${quadrantLabel(L + 10, T + 18, 'start', 'Q2  AI Enthusiast', 'Low literacy · high readiness', '#7a5f22')}
            ${quadrantLabel(W - R - 10, T + 18, 'end', 'Q1  AI Champion', 'High literacy · high readiness', '#15803d')}
            ${quadrantLabel(L + 10, H - B - 18, 'start', 'Q3  AI Novice', 'Low literacy · low readiness', '#8a3a12')}
            ${quadrantLabel(W - R - 10, H - B - 18, 'end', 'Q4  AI Sceptic', 'High literacy · low readiness', '#2e271c')}

            <line x1="${mid.x}" y1="${T}" x2="${mid.x}" y2="${H - B}" stroke="#94a3b8" stroke-dasharray="4 4"></line>
            <line x1="${L}" y1="${mid.y}" x2="${W - R}" y2="${mid.y}" stroke="#94a3b8" stroke-dasharray="4 4"></line>
            <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="none" stroke="#cbd5e1"></rect>

            ${arrows}
            ${dots(pre, BASELINE, 3.6)}
            ${dots(post, POST, 3.6)}
            ${centreMark(q.pre_centre, BASELINE, 'Baseline average')}
            ${centreMark(q.post_centre, POST, 'Post average')}

            ${ticks.map(t => `
              <text x="${px(t)}" y="${H - B + 18}" text-anchor="middle" font-size="11" fill="#667085">${t}</text>
              <text x="${L - 12}" y="${py(t) + 4}" text-anchor="end" font-size="11" fill="#667085">${t}</text>`).join('')}
            <text x="${(L + W - R) / 2}" y="${H - 10}" text-anchor="middle" font-size="11.5"
                  font-weight="600" fill="#344054">AI Literacy — do I understand AI?</text>
            <text x="16" y="${(T + H - B) / 2}" text-anchor="middle" font-size="11.5" font-weight="600"
                  fill="#344054" transform="rotate(-90 16 ${(T + H - B) / 2})">AI Readiness — am I ready to use AI?</text>
          </svg>
        </div>
        <p class="coh-sub">${pre.length} baseline and ${post.length} post-workshop responses plotted,
          ${pairs.length} of them joined as the same student.${
            q.truncated ? ' Showing the first 800 of each.' : ''}</p>
      </section>`;
  }

  /** Campus toggle strip — the same numbers for Bangalore and Kochi. */
  function campuses(rows, active, onPick) {
    if (!rows.length) return '';
    return `
      <section class="coh-card">
        <h2 class="coh-h2">Campus split</h2>
        <p class="coh-sub">Every step, campus by campus. Select one to scope the whole report to it.</p>
        <div class="coh-campus-grid">
          ${rows.map(c => `
            <button type="button" class="coh-campus${c.campus === active ? ' on' : ''}" data-campus="${esc(c.campus)}">
              <div class="coh-campus-name">${esc(c.campus)}</div>
              <div class="coh-campus-rows">
                ${['registered', 'pre', 'orientation', 'post'].map((key, i) => `
                  <div class="coh-campus-row">
                    <span>${['Registered', 'Baseline', 'Deeksharambh', 'Post survey'][i]}</span>
                    <b>${c[key]}</b>
                  </div>`).join('')}
              </div>
              <div class="coh-campus-foot">
                <span>${pct(c.completion_pct)} completed all</span>
                <span>${c.pending_post} post pending</span>
              </div>
            </button>`).join('')}
        </div>
      </section>`;
  }

  /** Department table — who filled the most, who the least, and who moved. */
  function departments(rows) {
    if (!rows.length) return '';
    return `
      <section class="coh-card">
        <h2 class="coh-h2">Department detail</h2>
        <p class="coh-sub">Ranked by how much of the three-step journey each department has finished.</p>
        <div class="coh-table-wrap">
          <table class="coh-table">
            <thead>
              <tr>
                <th>#</th><th>Department</th><th>Registered</th><th>Baseline</th>
                <th>Deeksharambh</th><th>Post</th><th>Post pending</th>
                <th>Completed</th><th>Baseline / 5</th><th>Post / 5</th><th>Change</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map((r, i) => `
                <tr>
                  <td>${i + 1}</td>
                  <td class="coh-strong">${esc(r.dept)}</td>
                  <td>${r.registered}</td>
                  <td>${r.pre}</td>
                  <td>${r.orientation}</td>
                  <td>${r.post}</td>
                  <td>${r.pending_post ? `<span class="coh-warn">${r.pending_post}</span>` : '0'}</td>
                  <td>
                    <div class="coh-mini-track"><div class="coh-mini-fill" style="width:${r.completion_pct}%"></div></div>
                    <span class="coh-mini-value">${pct(r.completion_pct)}</span>
                  </td>
                  <td>${num(r.pre_avg, 2)}</td>
                  <td>${num(r.post_avg, 2)}</td>
                  <td class="${r.delta === null ? '' : (r.delta < 0 ? 'coh-down' : 'coh-up')}">${signed(r.delta)}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </section>`;
  }

  function leaders(report) {
    const l = report.leaders || {};
    const cells = [
      ['Furthest along', l.most_complete, d => `${pct(d.completion_pct)} completed`],
      ['Most left to do', l.least_complete, d => `${d.pending_post} still owe the post survey`],
      ['Biggest score gain', l.biggest_gain, d => `${signed(d.delta)} on the baseline`],
      ['Smallest score gain', l.smallest_gain, d => `${signed(d.delta)} on the baseline`],
    ].filter(([, row]) => row);
    if (!cells.length) return '';
    return `
      <div class="coh-leaders">
        ${cells.map(([label, row, note]) => `
          <div class="coh-leader">
            <div class="coh-leader-label">${esc(label)}</div>
            <div class="coh-leader-dept">${esc(row.dept)}</div>
            <div class="coh-leader-note">${esc(note(row))}</div>
          </div>`).join('')}
      </div>`;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Draw the whole page. `options.onCampus(name)` makes the campus tiles
   * clickable; omit it and they render as read-only summaries.
   */
  function render(host, report, options) {
    if (!host) return;
    const opts = options || {};
    if (!report || !report.journey || !report.journey.registered) {
      host.innerHTML = '<div class="coh-card coh-empty-card">No students registered in this scope yet.</div>';
      return;
    }

    host.innerHTML =
      journey(report.journey) +
      leaders(report) +
      trajectory(report) +
      quadrantChart(report) +
      campuses(report.campuses || [], opts.activeCampus || '', opts.onCampus) +
      outcome(report) +
      impact(report) +
      departments(report.departments || []);

    // The trajectory has its own department picker; it redraws just that block.
    const picker = host.querySelector('#coh-traj-dept');
    if (picker) {
      picker.addEventListener('change', () => {
        host.querySelector('#coh-traj-body').innerHTML = trajectoryBody(report, picker.value);
      });
    }

    if (typeof opts.onCampus === 'function') {
      host.querySelectorAll('.coh-campus').forEach(el =>
        el.addEventListener('click', () => opts.onCampus(el.dataset.campus)));
    } else {
      host.querySelectorAll('.coh-campus').forEach(el => el.classList.add('coh-campus-static'));
    }
  }

  global.CohortReport = { render, esc, num, signed, pct };
})(window);
