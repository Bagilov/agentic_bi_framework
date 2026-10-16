"""Static HTML/CSS/JS assets for the dashboard clone (layout view).

Adapted from the process-mining HTML report tooling: the dark shell, the stats
grid, the slide-in filter panel and the hover-tooltip interaction are reused.
The centerpiece is different — instead of a process graph, the clone draws the
report **layout**: every element at its true position/size, with a mock glyph for
its visual type. Hovering shows metrics and violations; the filter panel dims
everything that does not match a chosen problem area.

The assets are plain strings (no interpolation); values are injected by
`web_render`.
"""

from __future__ import annotations

# Dark shell + layout canvas: same tokens as the process-mining report.
CSS = """
:root {
  --accent:#00d4ff; --err:#ff4757; --warn:#ffa502; --info:#4ecca3;
  --panel:rgba(255,255,255,0.05); --border:rgba(0,212,255,0.2); --canvas:#0f1526;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
  color:#e0e0e0; min-height:100vh; padding:20px;
}
.container { max-width:1600px; margin:0 auto; }
h1 { text-align:center; color:var(--accent); margin-bottom:10px; font-size:2.2em;
  text-shadow:0 0 10px rgba(0,212,255,0.5); }
.subtitle { text-align:center; color:#888; margin-bottom:22px; }
.stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:16px; margin-bottom:22px; }
.stat-card { background:var(--panel); border-radius:15px; padding:16px;
  text-align:center; border:1px solid var(--border); }
.stat-value { font-size:2em; font-weight:bold; color:var(--accent); }
.stat-card.error .stat-value { color:var(--err); }
.stat-card.warning .stat-value { color:var(--warn); }
.stat-card.info .stat-value { color:var(--info); }
.stat-label { color:#888; margin-top:5px; font-size:.9em; }

/* page tabs */
.page-tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
.tab { background:var(--panel); color:#cfd8e3; border:1px solid var(--border);
  border-radius:10px 10px 0 0; padding:9px 16px; cursor:pointer; font-size:.95em; }
.tab:hover { background:rgba(0,212,255,0.18); }
.tab.active { background:rgba(0,212,255,0.25); color:#fff; font-weight:bold; }
.tab.error { border-color:var(--err); } .tab.warning { border-color:var(--warn); }
.tab-badge { margin-left:8px; font-size:.8em; opacity:.85; }

/* layout canvas mirrors the report page */
.layout-host { overflow:auto; border:1px solid var(--border); border-radius:10px;
  background:var(--canvas); padding:10px; }
.canvas-wrap { display:none; }
.canvas-wrap.active { display:block; }
.canvas { position:relative; margin:0 auto; background:#121a2e;
  background-image:linear-gradient(rgba(255,255,255,0.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,0.03) 1px,transparent 1px);
  background-size:40px 40px; }

/* one element box, placed by true geometry */
.el { position:absolute; background:rgba(255,255,255,0.05);
  border:2px solid rgba(255,255,255,0.18); border-radius:6px; overflow:hidden;
  cursor:pointer; transition:opacity .15s, box-shadow .15s, border-color .15s; }
.el:hover { box-shadow:0 0 0 2px var(--accent), 0 0 14px rgba(0,212,255,.5); z-index:5; }
.el.error { border-color:var(--err); background:rgba(255,71,87,0.10); }
.el.warning { border-color:var(--warn); background:rgba(255,165,2,0.10); }
.el.ok { border-color:rgba(78,204,163,0.45); }
.el.dim { opacity:0.14; }
.el-chrome { display:flex; justify-content:space-between; align-items:center;
  gap:6px; padding:3px 6px; background:rgba(0,0,0,0.28); font-size:.72em; }
.el-title { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#dfe8f3; }
.el-body { width:100%; height:calc(100% - 20px); color:#9fd8ff; padding:4px; }
.el-body svg { width:100%; height:100%; display:block; }
.badge { border-radius:10px; padding:1px 8px; font-size:.78em; font-weight:bold; }
.badge.error { background:rgba(255,71,87,0.25); color:var(--err); }
.badge.warning { background:rgba(255,165,2,0.25); color:var(--warn); }
.badge.info { background:rgba(78,204,163,0.22); color:var(--info); }
.badge.ok { background:rgba(78,204,163,0.18); color:var(--info); }

/* details table */
.section { background:var(--panel); border-radius:15px; padding:20px;
  margin-top:22px; border:1px solid var(--border); }
.section > summary { cursor:pointer; color:var(--accent); font-size:1.15em;
  font-weight:bold; }
.data-table { width:100%; border-collapse:collapse; margin-top:14px; }
.data-table th, .data-table td { padding:8px 10px; text-align:left;
  border-bottom:1px solid rgba(255,255,255,0.1); font-size:.92em; }
.data-table th { background:rgba(0,212,255,0.2); color:var(--accent); }
.data-table tr:hover { background:rgba(255,255,255,0.05); }
.data-table tr.dim { opacity:0.25; }

/* filters (slide-in) */
.filter-toggle { position:fixed; left:0; top:120px; z-index:20; cursor:pointer;
  background:var(--accent); color:#04212b; font-weight:bold; padding:10px 14px;
  border-radius:0 12px 12px 0; }
.filter-panel { position:fixed; left:-320px; top:0; width:320px; height:100%;
  z-index:30; background:#141a2f; border-right:1px solid var(--border);
  padding:22px; overflow:auto; transition:left .25s ease; }
.filter-header { display:flex; justify-content:space-between; align-items:center;
  margin-bottom:18px; }
.filter-header h3 { color:var(--accent); }
.btn-close, .filter-panel button { background:var(--panel); color:var(--accent);
  border:1px solid var(--border); border-radius:8px; padding:6px 12px; cursor:pointer; }
.filter-group { margin-bottom:14px; }
.filter-group label { display:block; color:#aaa; font-size:.85em; margin-bottom:4px; }
.filter-group select { width:100%; padding:8px; border-radius:8px;
  background:#0f1526; color:#e0e0e0; border:1px solid var(--border); }
.footer { text-align:center; margin-top:26px; color:#666; font-size:.9em; }

/* detail popover */
#detailCard { position:fixed; right:18px; bottom:18px; width:380px; max-height:60vh;
  overflow:auto; z-index:40; background:#141a2f; border:1px solid var(--border);
  border-radius:12px; padding:16px; display:none; box-shadow:0 8px 30px rgba(0,0,0,.5); }
#detailCard h3 { color:var(--accent); margin-bottom:8px; font-size:1.05em; }
#detailCard .row { font-size:.9em; color:#c9d4e0; margin:3px 0; }
#detailCard ul { margin:8px 0 0 16px; font-size:.88em; }
#detailCard li { margin:3px 0; }
"""

# Interactivity: page tabs, filter dimming, hover tooltips (native title),
# detail popover from the injected model.
SCRIPT = """
const MODEL = window.__REPORT_MODEL__;

function indexModel() {
  const byKey = {};
  MODEL.pages.forEach((p, pi) => p.elements.forEach(e => {
    e._page = p.name; e._pi = pi; byKey[e.key] = e;
  }));
  return byKey;
}
const BY_KEY = indexModel();

function showPage(idx) {
  document.querySelectorAll('.canvas-wrap').forEach(s =>
    s.classList.toggle('active', s.dataset.page === String(idx)));
  document.querySelectorAll('.tab').forEach((t, i) =>
    t.classList.toggle('active', i === idx));
}

let filterOpen = false;
function toggleFilterPanel() {
  filterOpen = !filterOpen;
  document.getElementById('filterPanel').style.left = filterOpen ? '0' : '-320px';
  document.querySelector('.filter-toggle').style.left = filterOpen ? '320px' : '0';
}

function resetFilters() {
  document.getElementById('filter-severity').value = '';
  document.getElementById('filter-page').value = '';
  document.getElementById('filter-kind').value = '';
  document.getElementById('filter-check').value = '';
  applyFilters();
}

function matches(el, sev, page, kind, check) {
  if (sev) {
    if (sev === 'ok') { if (el.dataset.severity !== 'ok') return false; }
    else if (el.dataset.severity !== sev) return false;
  }
  if (page && el.dataset.page !== page) return false;
  if (kind && el.dataset.kind !== kind) return false;
  if (check && !(el.dataset.checks || '').split(',').includes(check)) return false;
  return true;
}

function applyFilters() {
  const sev = document.getElementById('filter-severity').value;
  const pageIdx = document.getElementById('filter-page').value;
  const page = pageIdx === '' ? '' : (MODEL.pages[+pageIdx] || {}).name;
  const kind = document.getElementById('filter-kind').value;
  const check = document.getElementById('filter-check').value;
  let visible = 0;
  document.querySelectorAll('.el').forEach(el => {
    const ok = matches(el, sev, page, kind, check);
    el.classList.toggle('dim', !ok);
    if (ok) visible++;
  });
  // jump to the selected page when filtering by page
  if (pageIdx !== '') showPage(+pageIdx);
  // dim matching detail rows too (the details table only honors severity)
  document.querySelectorAll('tr[data-detail]').forEach(tr => {
    tr.classList.toggle('dim', !!sev && sev !== 'ok' && tr.dataset.severity !== sev);
  });
  document.getElementById('filter-count').innerText =
    visible + ' элементов показано';
}

function showDetails(key) {
  const el = BY_KEY[key];
  const card = document.getElementById('detailCard');
  if (!el) { card.style.display = 'none'; return; }
  const m = el.metrics;
  const issues = (el.issues || []).length
    ? '<ul>' + el.issues.map(i =>
        '<li><span class="badge ' + i.severity + '">' + i.severity + '</span> '
        + i.check_id + ' — ' + i.message + '</li>').join('') + '</ul>'
    : '<div class="row">нарушений нет</div>';
  card.innerHTML = '<h3>' + el.label + ' · ' + el.visual_type + '</h3>'
    + '<div class="row">страница: ' + el._page + '</div>'
    + '<div class="row">полей: ' + m.fields + ' · ролей: ' + m.roles
    + ' · цветов: ' + m.colors + ' · фильтров: ' + m.filters + '</div>'
    + '<div class="row">ошибок: ' + m.errors + ' · предупр.: ' + m.warnings + '</div>'
    + issues;
  card.style.display = 'block';
}

document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.getElementById('detailCard').style.display = 'none';
      if (filterOpen) toggleFilterPanel();
    }
  });
});
"""
