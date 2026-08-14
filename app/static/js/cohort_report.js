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

  const BASELINE = '#1e3a8a';
  const POST = '#0d9488';
  const STAGE_TONES = ['#0d2147', '#1e3a8a', '#c9a84c', '#0d9488'];

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
          ${owed('Baseline still to complete', j.pending_pre, '#be123c')}
          ${owed('Deeksharambh still to complete', j.pending_orientation, '#c9a84c')}
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
          ${tile(o.scored, 'Scored responses', '#0d2147')}
          ${tile(num(o.avg_lit, 2), 'AI Literacy / 5', BASELINE)}
          ${tile(num(o.avg_read, 2), 'AI Readiness / 5', POST)}
          ${tile(num(o.avg_overall, 2), 'Overall / 5', '#c9a84c')}
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
          ${tile(i.scored, 'Scored responses', '#0d2147')}
          ${tile(num(i.avg_lit, 2), 'AI Literacy / 5', BASELINE, `${signed(dLit)} on baseline`)}
          ${tile(num(i.avg_read, 2), 'AI Readiness / 5', POST, `${signed(dRead)} on baseline`)}
          ${tile(signed(dAll), 'Overall change', dAll !== null && dAll < 0 ? '#be123c' : '#c9a84c')}
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
                ${splitCell('No change', m.unchanged, m.matched, '#64748b')}
                ${splitCell('Declined', m.declined, m.matched, '#be123c')}
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
      campuses(report.campuses || [], opts.activeCampus || '', opts.onCampus) +
      outcome(report) +
      impact(report) +
      departments(report.departments || []);

    if (typeof opts.onCampus === 'function') {
      host.querySelectorAll('.coh-campus').forEach(el =>
        el.addEventListener('click', () => opts.onCampus(el.dataset.campus)));
    } else {
      host.querySelectorAll('.coh-campus').forEach(el => el.classList.add('coh-campus-static'));
    }
  }

  global.CohortReport = { render, esc, num, signed, pct };
})(window);
