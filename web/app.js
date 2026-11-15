/* FINN client. No framework, no build step: one file, served as-is. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem('finn.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('finn.' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok && !j.error) j.error = `Request failed (${r.status})`;
  return j;
};

const S = { tab: 'brief', window: store.get('window', '24h'), from: null, to: null, meta: null, digest: null, loading: false,
  rules: null, symbols: null, buried: store.get('buried', []), seen: store.get('seen', null), research: null, qa: [], speaking: false };

/* ---------- formatting ---------- */
const inr = n => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const cr = v => v == null ? 'n/a' : Math.abs(v) >= 1e5 ? `₹${(v / 1e5).toFixed(2)} L cr` : `₹${inr(v)} cr`;
const signed = (v, d = 1) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
const val = (v, unit) => v == null ? 'n/a' : unit === 'cr' ? cr(v) : unit === 'rs' ? `₹${inr(v)}` : unit === '%' ? `${(+v).toFixed(1)}%`
  : unit === 'x' ? `${(+v).toFixed(v < 10 ? 2 : 1)}×` : unit === 'pts' ? `${signed(+v)} pts` : unit === 'days' ? `${Math.round(v)} days` : String(v);
const delta = v => v == null ? '<span class="faint">n/a</span>' : `<span class="delta ${v >= 0 ? 'up' : 'down'}">${signed(v)}%</span>`;
const ago = iso => {
  const m = (Date.now() - new Date(iso)) / 60000;
  if (m < 60) return `${Math.max(1, Math.round(m))}m ago`;
  if (m < 36 * 60) return `${Math.round(m / 60)}h ago`;
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
};
const dayName = d => new Date(d + 'T12:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
const icon = { play: '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10-6.5z"/></svg>', stop: '<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>', mic: '<svg class="icon" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21"/></svg>',
  go: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>' };

function toast(msg, action, fn) {
  const t = $('#toast');
  t.innerHTML = `<span>${esc(msg)}</span>${action ? `<button>${esc(action)}</button>` : ''}`;
  t.hidden = false;
  if (action) $('button', t).onclick = () => { t.hidden = true; fn(); };
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.hidden = true; }, 5000);
}

/* ---------- data ---------- */
function digestQuery() {
  const p = new URLSearchParams({ window: S.window, vol: S.rules.vol, px: S.rules.px, lookback: S.rules.lookback,
    care: S.rules.care.join(','), mute: S.rules.mute.join(','), symbols: S.symbols.join(',') });
  if (S.from) { p.set('from', S.from); if (S.to) p.set('to', S.to); }
  return p.toString();
}
async function loadDigest(silent) {
  if (!silent) { S.loading = true; if (S.tab === 'brief') render(); }
  const d = await api('/api/digest?' + digestQuery()).catch(() => ({ error: 'offline' }));
  S.loading = false;
  if (d.error) { if (!silent) { S.digestError = d.error; render(); } return; }
  S.digestError = null; S.digest = d;
  announce(d, silent);
  if (S.tab === 'brief' || S.tab === 'rules') render();
}
function announce(d, polled) {
  const ids = d.act.map(i => i.id);
  if (S.seen === null || !polled) {  // first visit, or the user changed the view themselves: nothing is "new"
    S.seen = [...new Set([...(S.seen || []), ...ids])].slice(-400); store.set('seen', S.seen); return;
  }
  const fresh = d.act.filter(i => !S.seen.includes(i.id));
  if (!fresh.length) return;
  S.seen = [...new Set([...S.seen, ...ids])].slice(-400); store.set('seen', S.seen);
  const f = fresh[0], body = `${f.symbol}: ${f.title}` + (fresh.length > 1 ? ` (+${fresh.length - 1} more)` : '');
  toast('New: ' + body);
  if (store.get('notify', false) && 'Notification' in window && Notification.permission === 'granted') {
    navigator.serviceWorker?.ready.then(r => r.showNotification('FINN', { body, icon: 'icon.svg', tag: f.id })).catch(() => new Notification('FINN', { body }));
  }
}

/* ---------- brief ---------- */
function spark(vals, up) {
  if (!vals || vals.length < 2) return '';
  const lo = Math.min(...vals), hi = Math.max(...vals), w = 56, h = 22;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 2 - (v - lo) / (hi - lo || 1) * (h - 4)).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--${up ? 'up' : 'down'})" stroke-width="1.6"/></svg>`;
}
function moveCard(m) {
  const vol = m.volx != null && m.volx >= 1.5 ? `${m.volx.toFixed(1)}× volume` : 'normal volume';
  return `<button class="move" data-research="${esc(m.symbol)}">
    <div class="row between"><b>${esc(m.symbol)}</b>${spark(m.spark, m.pct >= 0)}</div>
    <div class="pct ${m.pct >= 0 ? 'up' : 'down'}">${signed(m.pct)}%</div>
    <div class="tiny muted">${vol}, ${dayName(m.d)}</div>
    <div class="why ${m.why ? '' : 'none'}">${m.why ? esc(m.why.category_label + ': ' + m.why.title) : 'No filing explains this move.'}</div></button>`;
}
function actCard(i) {
  const rel = i.related.length ? `<div class="related">${i.related.length} more filing${i.related.length > 1 ? 's' : ''} on this, folded in:
    ${i.related.map(r => r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : `<span style="display:block;padding:3px 0">${esc(r.title)}</span>`).join('')}</div>` : '';
  return `<article class="card" data-id="${i.id}">
    <div class="row between"><div class="row grow"><span class="sym">${esc(i.symbol)}</span><span class="co grow">${esc(i.company)}</span></div><span class="tiny faint">${ago(i.dt)}</span></div>
    <h3>${esc(i.title)}</h3>
    <span class="tag">${esc(i.category_label)}</span>
    ${i.summary ? `<p class="sum" style="margin-top:10px">${esc(i.summary)}</p>` : ''}
    ${i.why.length ? `<p class="whyline ${i.move && i.move.pct < 0 ? 'down' : 'up'}">${esc(i.why.join('. '))}</p>` : ''}
    ${i.enrich_kind ? `<div class="enr" data-enrich="${i.id}"><div class="skel" style="width:70%"></div><div class="skel"></div><div class="skel" style="width:85%"></div></div>` : ''}
    ${rel}
    <div class="acts">${i.url && !i.url.startsWith('sample:') ? `<a href="${esc(i.url)}" target="_blank" rel="noopener">Open filing</a>` : ''}
      <button data-research="${esc(i.symbol)}">Research ${esc(i.symbol)}</button><button data-bury="${i.id}">Bury</button></div>
  </article>`;
}
function enrichHtml(e) {
  if (!e || e.status === 'unavailable') return '<p class="cap">Could not read this filing. Open it for details.</p>';
  if (e.kind === 'results') {
    return `<table class="nums"><thead><tr><th>${esc(e.quarter)} quarter</th><th>${esc(e.unit)}</th><th>vs last qtr</th><th>vs last year</th></tr></thead><tbody>
      ${e.rows.map(r => `<tr><td>${esc(r.label)}</td><td class="v">${inr(r.value)}</td><td>${delta(r.qoq)}</td><td>${delta(r.yoy)}</td></tr>`).join('')}</tbody></table>
      ${e.margin ? `<p class="cap" style="color:var(--ink-2)">Margin ${e.margin.value.toFixed(1)}%${e.margin.yoy_pts != null ? `, ${signed(e.margin.yoy_pts)} pts on last year` : ''}</p>` : ''}
      <p class="cap">${esc(e.basis)} figures from ${esc(e.source)}. ${esc(e.note || '')}</p>`;
  }
  if (e.kind === 'management') {
    return e.changes.map(c => {
      const inn = /appoint/.test(c.action);
      return `<div class="person"><div class="dir ${inn ? 'in' : 'out'}">${inn ? 'IN' : 'OUT'}</div><div>
        <b>${esc(c.name)}</b><div class="small muted">${esc([c.role, c.action, c.effective].filter(Boolean).join(', '))}${c.reason ? `. ${esc(c.reason)}` : ''}</div>
        ${c.bio.length ? `<ul>${c.bio.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : inn ? '<div class="small faint" style="margin-top:4px">No profile could be read from this filing.</div>' : ''}
        ${inn ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">Find on LinkedIn</a>` : ''}</div></div>`;
    }).join('') + `<p class="cap">From ${esc(e.source)}. ${esc(e.note || '')}</p>`;
  }
  return '';
}
function knowRow(i) {
  return `<div class="know" data-id="${i.id}"><button class="head" aria-expanded="false">
    <span class="t">${esc(i.title)}</span><span class="tiny faint">${ago(i.dt)}</span>
    <span class="m"><b>${esc(i.symbol)}</b> ${esc(i.category_label)}${i.move ? `, stock ${signed(i.move.pct)}%` : ''}</span></button>
    <div class="body" hidden>${esc(i.summary || 'No summary in the filing.')}${i.enrich_kind ? `<div class="enr" data-enrich-lazy="${i.id}"></div>` : ''}
      <div class="links">${i.url && !i.url.startsWith('sample:') ? `<a href="${esc(i.url)}" target="_blank" rel="noopener">Open filing</a>` : ''}<button data-research="${esc(i.symbol)}">Research ${esc(i.symbol)}</button></div></div></div>`;
}
function renderBrief() {
  const d = S.digest, top = `<div class="top"><span class="mark">FINN</span><div class="row">
    ${S.meta?.sample ? '<span class="pill sample">Sample data</span>' : ''}
    ${d && 'speechSynthesis' in window ? `<button class="pill ${S.speaking ? 'on' : ''}" id="listen" aria-pressed="${S.speaking}">${S.speaking ? icon.stop : icon.play}${S.speaking ? 'Stop' : 'Listen'}</button>` : ''}</div></div>`;
  if (!d) {
    return top + (S.digestError ? `<div class="empty"><b>Can't reach FINN's server.</b><p class="muted">Check your connection, then try again.</p><p style="margin-top:14px"><button class="btn" id="retry">Try again</button></p></div>`
      : `<div class="count"><span>Reading filings</span><span class="rest">across ${S.symbols.length} holdings.</span></div><div class="skel" style="height:120px;border-radius:14px"></div><div class="skel" style="height:120px;border-radius:14px"></div>`);
  }
  const mine = d.act.filter(i => S.buried.includes(i.id)), act = d.act.filter(i => !S.buried.includes(i.id));
  const rest = d.counts.buried + d.counts.know + mine.length;
  const h = d.health, notes = [];
  if (h.errors.length) {
    const f = [...new Set(h.errors.filter(e => e.what === 'filings').map(e => e.symbol))], p = [...new Set(h.errors.filter(e => e.what === 'prices').map(e => e.symbol))];
    if (f.length) notes.push(`Filings did not load for ${f.length} of ${d.counts.holdings} holdings (${f.slice(0, 4).join(', ')}${f.length > 4 ? '…' : ''}). This brief may be missing items.`);
    if (p.length) notes.push(`Prices did not load for ${p.slice(0, 4).join(', ')}${p.length > 4 ? '…' : ''}, so moves are not checked for them.`);
  }
  if (h.stale.length) notes.push(`Showing saved data for ${h.stale.slice(0, 5).join(', ')}; the source did not answer just now.`);
  return top + `
    <button class="pill" id="win">${esc(d.window.label)}${icon.down}</button>
    <h1 class="count"><span>${act.length} need${act.length === 1 ? 's' : ''} you.</span><span class="rest">${rest} ${rest === 1 ? "doesn't" : "don't"}.</span></h1>
    <p class="asof small muted">${d.counts.total} filing${d.counts.total === 1 ? '' : 's'} across ${d.counts.holdings} holdings${S.loading ? ', refreshing…' : `, as of ${new Date(d.generated).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}`}</p>
    ${notes.map(n => `<p class="note">${esc(n)}</p>`).join('')}
    ${d.moves.length ? `<div class="sec"><h2>${d.moves.length} unusual move${d.moves.length > 1 ? 's' : ''}</h2><button data-tab="rules">${S.rules.vol}× volume or ±${S.rules.px}%</button></div><div class="moves">${d.moves.map(moveCard).join('')}</div>` : ''}
    ${act.length ? `<div class="sec"><h2>Needs you</h2></div>${act.map(actCard).join('')}`
      : `<div class="empty" style="margin-top:24px"><b>Nothing needs you.</b><p class="muted">${d.counts.total ? 'Everything filed in this window is routine.' : 'No filings in this window.'} ${S.window === '24h' && !S.from ? 'Markets may have been closed.' : ''}</p>
         ${S.window !== '30d' && !S.from ? `<p style="margin-top:14px"><button class="btn ghost" data-window="${S.window === '24h' ? '3d' : S.window === '3d' ? '7d' : '30d'}">Look back further</button></p>` : ''}</div>`}
    ${d.know.length ? `<div class="sec"><h2>Worth knowing</h2><span class="small faint">${d.know.length}</span></div>${d.know.map(knowRow).join('')}` : ''}
    ${d.buried.length || mine.length ? `<div class="sec"><h2 class="faint">Buried</h2><span class="small faint">${d.counts.buried + mine.length}</span></div><div class="buried">
      ${mine.length ? `<button class="group" aria-expanded="false"><span>Buried by you</span><span>${mine.length}</span></button><div class="items" hidden>${mine.map(i => `<a href="#" data-unbury="${i.id}"><b>${esc(i.symbol)}</b> ${esc(i.title)} (tap to restore)</a>`).join('')}</div>` : ''}
      ${d.buried.map(b => `<button class="group" aria-expanded="false"><span>${esc(b.label)}</span><span>${b.count}</span></button>
        <div class="items" hidden>${b.items.map(i => `<a ${i.url && !i.url.startsWith('sample:') ? `href="${esc(i.url)}" target="_blank" rel="noopener"` : ''}><b>${esc(i.symbol)}</b> ${esc(i.title)}</a>`).join('')}</div>`).join('')}</div>` : ''}`;
}
function fillEnrich(el, id) {
  api('/api/enrich/' + id).then(e => {
    el.innerHTML = enrichHtml(e);
    // A filing titled only "Change in Director(s)" gets a real headline once we know who and what.
    const c = e.kind === 'management' && e.changes && e.changes[0], h = el.closest('.card')?.querySelector('h3');
    if (c && h && /^change in|^updates?$|^appointment$|^resignation$|^cessation$/i.test(h.textContent.trim()))
      h.textContent = `${c.name} ${c.action}${c.role ? ' as ' + c.role : ''}` + (e.changes.length > 1 ? `, and ${e.changes.length - 1} more change${e.changes.length > 2 ? 's' : ''}` : '');
  }).catch(() => { el.innerHTML = enrichHtml(null); });
}
function bury(id) {
  const card = $(`.card[data-id="${id}"]`);
  if (card) { card.style.transform = 'translateX(-110%)'; card.style.opacity = 0; }
  setTimeout(() => {
    S.buried.push(id); store.set('buried', S.buried.slice(-300)); render();
    toast('Buried.', 'Undo', () => { S.buried = S.buried.filter(x => x !== id); store.set('buried', S.buried); render(); });
  }, 160);
}
function swipe(card) {
  let x0 = null, dx = 0;
  card.addEventListener('pointerdown', e => { if (!e.target.closest('a,button')) { x0 = e.clientX; dx = 0; } });
  card.addEventListener('pointermove', e => {
    if (x0 === null) return;
    dx = Math.min(0, e.clientX - x0);
    if (dx < -12) { card.classList.add('dragging'); card.style.transform = `translateX(${dx}px)`; card.style.opacity = 1 + dx / 300; }
  });
  const end = () => {
    if (x0 === null) return;
    card.classList.remove('dragging'); x0 = null;
    if (dx < -110) bury(card.dataset.id); else { card.style.transform = ''; card.style.opacity = ''; }
  };
  card.addEventListener('pointerup', end); card.addEventListener('pointercancel', end); card.addEventListener('pointerleave', end);
}
function windowSheet() {
  const opts = [['24h', 'Last 24 hours'], ['3d', 'Last 3 days'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days']];
  const today = new Date().toISOString().slice(0, 10);
  const sh = $('#sheet');
  sh.innerHTML = `<div class="panel" role="dialog" aria-label="Choose a time window"><h2>Show filings from</h2>
    ${opts.map(([k, l]) => `<button class="opt" role="radio" aria-checked="${!S.from && S.window === k}" data-w="${k}">${l}</button>`).join('')}
    <div class="opt" style="display:block"><span>Or exact dates</span><div class="dates"><label>From<input type="date" id="dfrom" max="${today}" value="${S.from || ''}"></label><label>To<input type="date" id="dto" max="${today}" value="${S.to || today}"></label></div>
    <button class="btn" id="dapply" style="width:100%">Show these dates</button></div></div>`;
  sh.hidden = false;
  sh.onclick = e => {
    if (e.target === sh) { sh.hidden = true; return; }
    const w = e.target.closest('[data-w]');
    if (w) { setWindow(w.dataset.w); sh.hidden = true; }
    if (e.target.id === 'dapply') {
      const f = $('#dfrom').value, t = $('#dto').value;
      if (!f) { toast('Pick a start date.'); return; }
      if (t && t < f) { toast('The end date is before the start date.'); return; }
      S.from = f; S.to = t || null; sh.hidden = true; loadDigest();
    }
  };
}
function setWindow(w) { S.window = w; S.from = S.to = null; store.set('window', w); loadDigest(); }
function listen() {
  if (S.speaking) { speechSynthesis.cancel(); S.speaking = false; render(); return; }
  const u = new SpeechSynthesisUtterance(S.digest.spoken);
  u.lang = 'en-IN'; u.rate = 1.02;
  u.onend = u.onerror = () => { S.speaking = false; if (S.tab === 'brief') render(); };
  S.speaking = true; speechSynthesis.speak(u); render();
}

/* ---------- ask / research ---------- */
function bars(values, tone) {
  const v = values.map(x => x ?? 0), hi = Math.max(...v, 0), lo = Math.min(...v, 0), span = hi - lo || 1, n = v.length, w = 100 / n;
  const y0 = 52 - (0 - lo) / span * 50;
  return `<svg viewBox="0 0 100 54" preserveAspectRatio="none" aria-hidden="true">${v.map((x, i) => {
    const h = Math.abs(x) / span * 50, y = x >= 0 ? y0 - h : y0;
    return `<rect x="${(i * w + w * 0.14).toFixed(1)}" y="${y.toFixed(1)}" width="${(w * 0.72).toFixed(1)}" height="${Math.max(h, 0.8).toFixed(1)}" rx="1.5" fill="var(--${x < 0 ? 'down' : i === n - 1 ? (tone || 'ink') : 'ink-3'})" opacity="${i === n - 1 || x < 0 ? 1 : 0.55}"/>`;
  }).join('')}</svg>`;
}
function chart(set, labels) {
  const last = set.values[set.values.length - 1];
  return `<div class="chart"><div class="l">${esc(set.name)}</div>${bars(set.values)}<div class="ax"><span>${esc(labels[0])}</span><span>${esc(labels[labels.length - 1])}</span></div><div class="n">${val(last, set.unit)}</div></div>`;
}
function cardHtml(c) {
  if (c.key === 'snapshot') {
    const h = c.headline;
    return `<section class="block" id="s-snapshot"><h2>${esc(c.title)}</h2><div class="stats">${c.stats.map(s => `<div class="stat"><div class="l">${esc(s.label)}</div><div class="n">${val(s.value, s.unit)}</div></div>`).join('')}</div>
      ${h ? `<div class="enr">${enrichHtml({ kind: 'results', ...h, source: 'the standardised statements' })}</div>` : ''}</section>`;
  }
  const sets = c.series ? c.series.sets.slice(0, 3) : [];
  return `<section class="block" id="s-${c.key}"><h2>${esc(c.title)}</h2>
    ${c.verdict?.text ? `<p class="verdict ${c.verdict.tone}">${esc(c.verdict.text)}</p>` : ''}
    <div class="stats ${c.stats.filter(s => s.value != null).length === 3 ? 'three' : ''}">${c.stats.filter(s => s.value != null).map(s => `<div class="stat"><div class="l">${esc(s.label)}</div><div class="n">${val(s.value, s.unit)}</div></div>`).join('')}</div>
    ${sets.length ? `<div class="charts ${sets.length === 2 ? 'two' : ''}">${sets.map(s => chart(s, c.series.labels)).join('')}</div>` : ''}
    ${c.momentum?.values?.length ? `<div class="charts two"><div class="chart"><div class="l">Revenue growth, year on year, by quarter</div>${bars(c.momentum.values)}<div class="ax"><span>${esc(c.momentum.labels[0])}</span><span>${esc(c.momentum.labels.at(-1))}</span></div></div>
      <div class="chart"><div class="l">Latest quarter</div><div class="n" style="font-size:22px;margin-top:10px">${c.momentum.values.at(-1) == null ? 'n/a' : signed(c.momentum.values.at(-1)) + '%'}</div><div class="ax"><span>vs ${c.momentum.values[0] == null ? 'n/a' : signed(c.momentum.values[0]) + '%'} four quarters earlier</span></div></div></div>` : ''}</section>`;
}
const VERDICT = { met: ['Delivered', 'good'], beat: ['Beat', 'good'], missed: ['Missed', 'bad'], on_track: ['On track', 'good'], ahead: ['Running ahead', 'good'],
  behind: ['Running behind', 'bad'], pending: ['Not reported yet', ''], unverifiable: ['Not checkable', ''] };
function threadHtml(t) {
  const first = t.said[0], last = t.said.at(-1), u = t.unit === 'pct' ? '%' : '';
  const big = v => v >= 1e7 ? `${+(v / 1e7).toFixed(2)} crore` : v >= 1e6 ? `${+(v / 1e6).toFixed(2)} million` : inr(v);
  const rng = s => t.unit === 'num' ? (s.lo === s.hi ? big(s.lo) : `${big(s.lo)} to ${big(s.hi)}`) : t.unit === 'cr' ? (s.lo === s.hi ? cr(s.lo) : `${cr(s.lo)} to ${cr(s.hi)}`) : s.lo === s.hi ? `${s.lo}%` : `${s.lo}–${s.hi}%`;
  const [vt, vc] = VERDICT[t.verdict_vs_first] || VERDICT.unverifiable;
  let scale = '';
  if (t.actual != null) {
    const all = [first.lo, first.hi, last.lo, last.hi, t.actual], lo = Math.min(...all), hi = Math.max(...all), pad = Math.max((hi - lo) * 0.18, 0.6);
    const a = lo - pad, b = hi + pad, pos = x => ((x - a) / (b - a) * 100).toFixed(1);
    const band = (s, cls) => `<div class="band ${cls}" style="left:${pos(s.lo)}%;width:${Math.max(pos(s.hi) - pos(s.lo), 1.5)}%"></div>`;
    const ap = +pos(t.actual);
    scale = `<div class="scale"><div class="axis"></div>${t.moved ? band(first, 'old') : ''}${band(last, '')}<div class="act ${ap > 82 ? 'r' : ap < 18 ? 'l' : ''}" style="left:${ap}%" data-v="${t.actual}${u} reported"></div></div>
      <div class="legend">${t.moved ? '<span><i class="b"></i>First guidance</span><span><i class="a"></i>Latest guidance</span>' : '<span><i class="a"></i>Guidance</span>'}<span><i class="c"></i>Reported, ${esc(t.period)}${t.final ? '' : ' so far'}</span></div>`;
  }
  let sub = '';
  if (t.moved && t.actual != null) {
    const [lt] = VERDICT[t.verdict_vs_last];
    sub = `<p class="small muted" style="margin-top:8px">Guidance ${t.moved} from ${rng(first)} to ${rng(last)} in ${esc(last.said_on)}. Against the first number: ${vt.toLowerCase()}. Against the ${t.moved === 'cut' ? 'lowered' : 'raised'} one: ${lt.toLowerCase()}.</p>`;
  } else if (t.verdict_vs_first === 'unverifiable') sub = '<p class="small muted" style="margin-top:8px">Not a dated, company-level headline number, so FINN shows it without grading it.</p>';
  return `<div class="thread"><div class="h"><b>${esc(t.label)}${t.year_stated === false ? ', no year stated' : `, FY${t.fy % 100}`}</b><span class="vchip ${vc}">${vt}</span></div>
    ${scale}${sub}
    <ul class="said">${t.said.map(s => `<li><span>${esc(s.said_on)}</span><span><b>${rng(s)}</b><q>${esc(s.quote)}</q>${s.url && !s.url.startsWith('sample:') ? `<a class="tiny" href="${esc(s.url)}" target="_blank" rel="noopener">Transcript, page ${s.page ?? '?'}</a>` : `<span class="tiny faint">Transcript, page ${s.page ?? '?'}</span>`}</span></li>`).join('')}</ul></div>`;
}
function researchHtml() {
  const j = S.research;
  if (!j) return '';
  if (j.state === 'error') return `<div class="empty" style="margin-top:20px"><b>Couldn't research ${esc(j.symbol)}.</b><p class="muted">${esc(j.error || '')}</p><p class="muted" style="margin-top:8px">Check the ticker is the NSE symbol (for example TCS, not Tata Consultancy), then try again.</p></div>`;
  const sd = j.said_did, parts = [];
  const nav = [];
  if (j.cards?.length) nav.push(['snapshot', 'Snapshot']);
  if (sd) nav.push(['said', 'Said vs did']);
  (j.cards || []).slice(1).forEach(c => nav.push([c.key, c.title]));
  if (j.business || j.about) nav.push(['business', 'Business']);
  if (j.cases) nav.push(['cases', 'Bull vs bear']);
  nav.push(['ask', 'Ask'], ['sources', 'Sources']);
  parts.push(`<div class="co-head"><h1>${esc(j.name || j.symbol)}</h1><p class="small muted">${esc([j.symbol, j.sector, j.basis && j.basis + ' figures'].filter(Boolean).join(', '))}</p>
    ${j.state === 'running' ? `<div class="stage"><span class="dot"></span>${esc(j.stage || 'Working')}…</div>` : ''}
    ${j.stale ? '<p class="note">The source did not answer just now. Showing the last saved financials.</p>' : ''}</div>
    <div class="jump">${nav.map(([k, l]) => `<a href="#s-${k}">${esc(l)}</a>`).join('')}</div>`);
  if (j.cards?.length) parts.push(cardHtml(j.cards[0]));
  if (sd) {
    parts.push(`<section class="block" id="s-said"><h2>Said vs did</h2><p class="verdict ${sd.checked ? (sd.kept / sd.checked >= 0.75 ? 'good' : sd.kept / sd.checked <= 0.4 ? 'bad' : 'warn') : ''}">${esc(sd.read)}</p>
      ${j.narrative ? `<p style="margin-bottom:6px">${esc(j.narrative.read)}</p>${(j.narrative.diverge || []).length ? `<ul class="plain">${j.narrative.diverge.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}` : ''}
      ${sd.threads.map(threadHtml).join('')}${sd.more ? `<p class="small muted" style="margin-top:12px">Plus ${sd.more} older ungraded target${sd.more > 1 ? 's' : ''} not shown.</p>` : ''}
      <p class="by">${sd.calls_read.length ? `Read ${sd.calls_read.length} call${sd.calls_read.length > 1 ? 's' : ''}: ${esc(sd.calls_read.join(', '))}.` : 'No readable transcripts were found for this company.'}
      Promises pulled out by ${sd.by === 'model' ? 'a language model' : 'pattern rules (explicit numeric guidance only)'}; every comparison with reported numbers is plain arithmetic.</p></section>`);
  } else if (j.state === 'running') parts.push(`<section class="block" id="s-said"><h2>Said vs did</h2><div class="skel" style="width:80%"></div><div class="skel"></div><div class="skel" style="width:60%"></div></section>`);
  (j.cards || []).slice(1).forEach(c => parts.push(cardHtml(c)));
  if (j.business) {
    const b = j.business;
    parts.push(`<section class="block" id="s-business"><h2>Business</h2><p class="verdict">${esc(b.what)}</p>
      ${(b.segments || []).length ? `<div class="small muted" style="margin-bottom:6px">${esc(b.mix_basis || 'Mix')}</div>${b.segments.map(s => `<div class="kv"><span>${esc(s.name)}</span><span>${s.share_pct != null ? s.share_pct + '%' : ''}</span></div>`).join('')}` : ''}
      ${(b.facts || []).length ? `<ul class="plain" style="margin-top:10px">${b.facts.map(f => `<li>${esc(f)}</li>`).join('')}</ul>` : ''}
      <p class="by">From the ${esc(b.source)}${(b.pages || []).length ? `, pages ${b.pages.join(', ')}` : ''}.</p></section>`);
  } else if (j.about) parts.push(`<section class="block" id="s-business"><h2>Business</h2><p>${esc(j.about)}</p><p class="by">${j.sample ? 'Sample description.' : 'Description from screener.in, not from the annual report. Add a model key to have FINN read the annual report instead.'}</p></section>`);
  if (j.cases && (j.cases.bull.length || j.cases.bear.length)) parts.push(`<section class="block" id="s-cases"><h2>Bull vs bear</h2><div class="cases">
      <div class="bull"><h3>For</h3><ul>${j.cases.bull.map(x => `<li>${esc(x)}</li>`).join('') || '<li class="muted">Nothing in the numbers stands out.</li>'}</ul></div>
      <div class="bear"><h3>Against</h3><ul>${j.cases.bear.map(x => `<li>${esc(x)}</li>`).join('') || '<li class="muted">Nothing in the numbers stands out.</li>'}</ul></div></div>
      <p class="by">${j.cases.by === 'model' ? 'Written by a language model from the computed facts above only.' : 'Assembled by rule from the verdicts above. Add a model key for a written case.'}</p></section>`);
  parts.push(`<section class="block" id="s-ask"><h2>Ask about ${esc(j.symbol)}</h2>
      <form class="askbar" id="qform"><div class="field"><input type="text" id="q" placeholder="Capex? Margins? Debt?" autocomplete="off" enterkeyhint="send"></div><button class="go" aria-label="Ask">${icon.go}</button></form>
      <div id="qa">${S.qa.map(qaHtml).join('')}</div><p class="by">Answers come only from this company's transcripts${j.llm ? ' and annual report' : ''}.</p></section>`);
  parts.push(`<section class="block src" id="s-sources"><h2>Sources</h2>
      ${(j.sources || []).map(s => s.url.startsWith('sample:') ? `<a><span>${esc(s.title)}</span><span class="faint">${s.pages} pages</span></a>` : `<a href="${esc(s.url)}" target="_blank" rel="noopener"><span>${esc(s.title)}</span><span class="faint">${s.pages} pages</span></a>`).join('')}
      ${j.source_url ? `<a href="${esc(j.source_url)}" target="_blank" rel="noopener"><span>Standardised statements</span><span class="faint">screener.in</span></a>` : ''}
      ${(j.skipped || []).map(s => `<a><span class="muted">Skipped: ${esc(s.doc)}</span><span class="faint">${esc(s.why)}</span></a>`).join('')}
      <p class="by">Primary sources only. No news, broker notes or outside knowledge.</p></section>`);
  return parts.join('');
}
function qaHtml(x) {
  return `<div class="qa"><div class="q">${esc(x.question)}</div>
    ${x.pending ? '<div class="skel" style="width:70%"></div>' : x.error ? `<div class="a muted">${esc(x.error)}</div>`
      : `${x.answer ? `<div class="a">${esc(x.answer)}</div>` : x.passages.length ? `<div class="a small muted">${x.llm ? '' : 'No model key is set, so here are the passages that match:'}</div>` : '<div class="a muted">Nothing in the transcripts matches that.</div>'}
        ${x.passages.slice(0, x.answer ? 2 : 4).map(p => `<div class="p">${esc(p.text)} <span class="tiny faint">${esc(p.doc)}, page ${p.page}</span></div>`).join('')}`}</div>`;
}
function renderAsk() {
  const m = S.meta, rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  return `<div class="top"><span class="mark">FINN</span>${m?.sample ? '<span class="pill sample">Sample data</span>' : ''}</div>
    <form class="askbar" id="cmd"><div class="field"><input type="search" id="cmdin" placeholder="Ticker, question or instruction" autocomplete="off" autocapitalize="characters" enterkeyhint="go" value="">
      ${rec ? `<button type="button" class="mic" id="mic" aria-label="Speak">${icon.mic}</button>` : ''}</div><button class="go" aria-label="Go">${icon.go}</button></form>
    ${S.research ? researchHtml() : `<p class="hint">Any NSE ticker works, not only your holdings.</p>
      <div class="sec"><h2>Outside your portfolio</h2></div><div class="chips">${(m?.picks || []).map(s => `<button class="chip" data-research="${esc(s)}">${esc(s)}</button>`).join('')}</div>
      <div class="sec"><h2>Your holdings</h2></div><div class="chips">${S.symbols.map(s => `<button class="chip" data-research="${esc(s)}">${esc(s)}</button>`).join('')}</div>
      <div class="sec"><h2>Or just say it</h2></div>
      ${['What changed this week', 'Alert me if volume is over 3x', `What did ${S.symbols[0]} say about margins?`].map(t => `<button class="try" data-say="${esc(t)}">${esc(t)}</button>`).join('')}`}`;
}
async function openResearch(sym, refresh) {
  S.tab = 'ask'; S.qa = []; S.research = { symbol: sym, state: 'running', stage: 'Loading financials', cards: [] };
  render(); window.scrollTo(0, 0);
  const tick = async first => {
    const j = await api(`/api/research/${encodeURIComponent(sym)}${first && refresh ? '?refresh=1' : ''}`).catch(() => ({ symbol: sym, state: 'error', error: 'The server did not answer.' }));
    if (!S.research || S.research.symbol !== sym) return;
    const changed = JSON.stringify(j) !== JSON.stringify(S.research);
    S.research = j;
    if (changed && S.tab === 'ask' && document.activeElement?.id !== 'q') { const y = window.scrollY; render(); window.scrollTo(0, y); }
    if (j.state === 'running') setTimeout(tick, 1200);
  };
  tick(true);
}
async function command(text) {
  text = text.trim();
  if (!text) return;
  const c = await api('/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, symbol: S.research?.symbol }) });
  if (c.intent === 'research') openResearch(c.symbol);
  else if (c.intent === 'digest') { S.tab = 'brief'; setWindow(c.window); render(); }
  else if (c.intent === 'rule') { Object.assign(S.rules, c.patch); store.set('rules', S.rules); toast(c.say, 'See rules', () => go('rules')); loadDigest(true); }
  else if (c.intent === 'ask') { if (S.research?.symbol !== c.symbol) await openResearch(c.symbol); askQ(c.symbol, c.question); }
  else toast(c.say || 'Not sure what to do with that.');
}
async function askQ(sym, question) {
  const x = { question, pending: true }; S.qa.unshift(x);
  if (S.tab === 'ask') { render(); $('#s-ask')?.scrollIntoView({ block: 'start' }); }
  const r = await api('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: sym, question }) }).catch(() => ({ error: 'The server did not answer.' }));
  Object.assign(x, r, { pending: false, passages: r.passages || [] });
  const box = $('#qa'); if (box) box.innerHTML = S.qa.map(qaHtml).join('');
}
function mic() {
  const R = window.SpeechRecognition || window.webkitSpeechRecognition, b = $('#mic');
  if (!R) return;
  const r = new R(); r.lang = 'en-IN'; r.interimResults = false;
  b.classList.add('live');
  r.onresult = e => { const t = e.results[0][0].transcript; $('#cmdin').value = t; command(t); };
  r.onerror = () => toast('Did not catch that. Try again or type it.');
  r.onend = () => b.classList.remove('live');
  r.start();
}

/* ---------- rules ---------- */
function renderRules() {
  const r = S.rules, m = S.meta, d = S.digest, l = m.llm;
  const cats = m.categories.filter(c => c.key !== 'unclassified');
  return `<div class="top"><span class="mark">FINN</span></div><h1 class="h1">Rules</h1><p class="muted">You decide what counts as unusual. FINN watches for it.</p>
    <section class="block"><h2>Price and volume</h2>
      <div class="rule"><p class="say">Flag a day when volume is <b id="volv">${r.vol}×</b> its ${r.lookback}-session average or more.</p><input type="range" id="vol" min="1.5" max="6" step="0.1" value="${r.vol}" aria-label="Volume multiple"></div>
      <div class="rule"><p class="say">Flag a close that moves <b id="pxv">±${r.px}%</b> or more in a day.</p><input type="range" id="px" min="1" max="12" step="0.5" value="${r.px}" aria-label="Price move percent"></div>
      <div class="rule"><p class="say">Average volume over the last <b id="lbv">${r.lookback}</b> sessions.</p><input type="range" id="lookback" min="5" max="60" step="5" value="${r.lookback}" aria-label="Lookback sessions"></div>
      <p class="by" id="preview">${d ? `These settings flag ${d.counts.moves} move${d.counts.moves === 1 ? '' : 's'} in the current window (${esc(d.window.label.toLowerCase())}).` : ''}</p></section>
    <section class="block"><h2>Filings</h2><p class="small muted" style="margin-bottom:12px">Tap a type to cycle: normal, always surface, always bury.</p>
      <div class="chips">${cats.map(c => `<button class="chip ${r.care.includes(c.key) ? 'care' : r.mute.includes(c.key) ? 'mute' : ''}" data-cat="${esc(c.key)}" aria-label="${esc(c.label)}: ${r.care.includes(c.key) ? 'always surface' : r.mute.includes(c.key) ? 'always bury' : 'normal'}">${esc(c.label)}</button>`).join('')}</div></section>
    <section class="block"><h2>Holdings (${S.symbols.length})</h2>
      <div class="chips">${S.symbols.map(s => `<span class="chip">${esc(s)}<button class="x" data-drop="${esc(s)}" aria-label="Remove ${esc(s)}">×</button></span>`).join('')}</div>
      <form class="askbar" id="addform" style="margin-top:14px"><div class="field"><input type="text" id="add" placeholder="Add an NSE ticker" autocapitalize="characters" autocomplete="off" style="background:var(--ground)"></div><button class="go" aria-label="Add">${icon.go}</button></form>
      <p class="by"><button id="resetp" style="text-decoration:underline">Restore the starting portfolio</button></p></section>
    <section class="block"><h2>Alerts on this phone</h2>
      ${'Notification' in window ? `<p class="small muted" style="margin-bottom:12px">${store.get('notify', false) && Notification.permission === 'granted' ? 'On. FINN checks every 5 minutes while it is open and notifies you of anything new that needs you.' : 'Get a notification when something new needs you. FINN checks every 5 minutes while it is open.'}</p>
      <button class="btn ${store.get('notify', false) && Notification.permission === 'granted' ? 'ghost' : ''}" id="notify">${store.get('notify', false) && Notification.permission === 'granted' ? 'Turn notifications off' : 'Turn notifications on'}</button>`
      : '<p class="small muted">This browser does not support notifications. On iPhone, add FINN to your home screen first.</p>'}</section>
    <section class="block"><h2>Under the hood</h2>
      <div class="kv"><span>Data</span><span>${m.sample ? 'Sample universe (fictional)' : 'Live: Yahoo Finance, NSE/BSE, screener.in'}</span></div>
      ${d ? `<div class="kv"><span>Sources answering</span><span>Filings ${d.health.filings_ok}/${d.counts.holdings}, prices ${d.health.prices_ok}/${d.counts.holdings}</span></div>` : ''}
      <div class="kv"><span>Language model</span><span>${l.ready ? esc(l.provider) : 'None set. Rules and arithmetic only.'}</span></div>
      ${l.ready ? `<div class="kv"><span>Bulk model</span><span>${esc(l.cheap)}: ${l.ledger.cheap.calls} calls, ${l.ledger.cheap.cache_hits} from cache</span></div>
      <div class="kv"><span>Reasoning model</span><span>${esc(l.strong)}: ${l.ledger.strong.calls} calls, ${l.ledger.strong.cache_hits} from cache</span></div>
      <div class="kv"><span>Tokens this run</span><span>${inr(l.ledger.cheap.in + l.ledger.cheap.out)} bulk, ${inr(l.ledger.strong.in + l.ledger.strong.out)} reasoning</span></div>` : ''}
      ${l.ledger.errors ? `<div class="kv"><span>Model errors</span><span>${l.ledger.errors}: ${esc(l.ledger.last_error)}</span></div>` : ''}</section>`;
}
let deb;
function ruleInput(e) {
  const id = e.target.id;
  if (!['vol', 'px', 'lookback'].includes(id)) return;
  S.rules[id] = +e.target.value; store.set('rules', S.rules);
  $('#volv').textContent = S.rules.vol + '×'; $('#pxv').textContent = '±' + S.rules.px + '%'; $('#lbv').textContent = S.rules.lookback;
  $('#preview').textContent = 'Checking…';
  clearTimeout(deb);
  deb = setTimeout(async () => {
    const d = await api('/api/digest?' + digestQuery()); if (d.error) return;
    S.digest = d; const p = $('#preview');
    if (p) p.textContent = `These settings flag ${d.counts.moves} move${d.counts.moves === 1 ? '' : 's'} in the current window (${d.window.label.toLowerCase()}).`;
  }, 350);
}

/* ---------- shell ---------- */
function go(tab) { S.tab = tab; render(); window.scrollTo(0, 0); if (tab === 'rules') api('/api/meta').then(m => { S.meta = m; if (S.tab === 'rules') render(); }); }
function render() {
  const v = $('#view');
  v.innerHTML = S.tab === 'brief' ? renderBrief() : S.tab === 'ask' ? renderAsk() : renderRules();
  $$('.tabs button').forEach(b => b.dataset.tab === S.tab ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
  $$('[data-enrich]', v).forEach(el => fillEnrich(el, el.dataset.enrich));
  $$('.card', v).forEach(swipe);
}
document.addEventListener('click', e => {
  const t = e.target.closest('[data-tab],[data-research],[data-bury],[data-unbury],[data-window],[data-say],[data-cat],[data-drop],#win,#listen,#retry,#mic,#notify,#resetp,.know .head,.buried .group');
  if (!t) return;
  if (t.dataset.tab) return go(t.dataset.tab);
  if (t.dataset.research) return openResearch(t.dataset.research);
  if (t.dataset.bury) return bury(t.dataset.bury);
  if (t.dataset.unbury) { e.preventDefault(); S.buried = S.buried.filter(x => x !== t.dataset.unbury); store.set('buried', S.buried); return render(); }
  if (t.dataset.window) return setWindow(t.dataset.window);
  if (t.dataset.say) return command(t.dataset.say);
  if (t.dataset.cat) {
    const k = t.dataset.cat, r = S.rules;
    if (r.care.includes(k)) { r.care = r.care.filter(x => x !== k); r.mute.push(k); }
    else if (r.mute.includes(k)) r.mute = r.mute.filter(x => x !== k);
    else r.care.push(k);
    store.set('rules', r); render(); return loadDigest(true);
  }
  if (t.dataset.drop) { S.symbols = S.symbols.filter(s => s !== t.dataset.drop); saveSymbols(); render(); return loadDigest(true); }
  if (t.id === 'win') return windowSheet();
  if (t.id === 'listen') return listen();
  if (t.id === 'retry') return loadDigest();
  if (t.id === 'mic') return mic();
  if (t.id === 'resetp') { S.symbols = [...S.meta.portfolio]; saveSymbols(); render(); return loadDigest(true); }
  if (t.id === 'notify') {
    if (store.get('notify', false) && Notification.permission === 'granted') { store.set('notify', false); return render(); }
    return Notification.requestPermission().then(p => { store.set('notify', p === 'granted'); if (p !== 'granted') toast('Notifications are blocked for this site. Allow them in your browser settings.'); render(); });
  }
  if (t.matches('.know .head') || t.matches('.buried .group')) {
    const body = t.nextElementSibling, open = body.hidden;
    body.hidden = !open; t.setAttribute('aria-expanded', open);
    const lazy = open && $('[data-enrich-lazy]', body);
    if (lazy && !lazy.dataset.done) { lazy.dataset.done = 1; lazy.innerHTML = '<div class="skel"></div>'; fillEnrich(lazy, lazy.dataset.enrichLazy); }
  }
});
document.addEventListener('submit', e => {
  e.preventDefault();
  if (e.target.id === 'cmd') { const v = $('#cmdin').value; $('#cmdin').blur(); command(v); }
  if (e.target.id === 'qform') { const q = $('#q').value.trim(); if (q) askQ(S.research.symbol, q); }
  if (e.target.id === 'addform') {
    const s = $('#add').value.trim().toUpperCase().replace(/\.NS$/, '');
    if (!/^[A-Z0-9&\-]{1,20}$/.test(s)) return toast('Enter an NSE ticker, for example TCS.');
    if (S.symbols.includes(s)) return toast(`${s} is already in your holdings.`);
    if (S.symbols.length >= 30) return toast('FINN tracks up to 30 holdings.');
    S.symbols.push(s); saveSymbols(); render(); loadDigest(true); toast(`Added ${s}.`);
  }
});
document.addEventListener('input', ruleInput);
const symKey = () => 'symbols.' + (S.meta.sample ? 'sample' : 'live');
function saveSymbols() { store.set(symKey(), S.symbols); }

(async function boot() {
  S.meta = await api('/api/meta').catch(() => null);
  if (!S.meta || S.meta.error) { S.symbols = []; S.rules = { vol: 2, px: 4, lookback: 20, care: [], mute: [] }; S.digestError = 'offline'; return render(); }
  S.rules = { ...S.meta.rules, ...store.get('rules', {}) };
  S.symbols = store.get(symKey(), S.meta.portfolio);
  render();
  loadDigest();
  setInterval(() => { if (!document.hidden) loadDigest(true); }, 5 * 60 * 1000);
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
})();
