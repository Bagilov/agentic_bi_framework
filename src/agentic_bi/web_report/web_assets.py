"""Static HTML/CSS/JS assets for the dashboard clone (layout view).

Adapted from the process-mining HTML report tooling: the stats grid, the
slide-in filter panel and the hover-tooltip interaction are reused. The
centerpiece is different — instead of a process graph, the clone draws the
report **layout**: every element at its true position/size, with a mock glyph for
its visual type. Hovering shows metrics and violations; the filter panel dims
everything that does not match a chosen problem area.

The palette is theme-aware (light by default, dark under
``prefers-color-scheme: dark``), honors ``prefers-reduced-motion``, collapses to
one column below 720px and strips interactive chrome when printed.

The assets are plain strings (no interpolation); values are injected by
`web_render` and `web_mock`.
"""

from __future__ import annotations

# Size exception (>300 lines): CSS/JS live as one asset per concern; splitting
# the document contract across modules made the print/a11y rules harder to keep
# consistent. The strings are static, not generated code.
# Accessible light-first shell; a dark palette overrides the tokens below.
CSS = """
:root {
  --bg-from:#f4f7fb; --bg-to:#e8eef7;
  --surface:#ffffff; --surface-2:#f1f5fa; --panel:rgba(10,60,100,0.04);
  --text:#16202f; --muted:#4f5d70; --accent:#0069a3; --accent-ink:#ffffff;
  --focus:#0a84ff; --canvas:#ffffff; --grid:rgba(20,40,70,0.07);
  --chrome:rgba(10,30,60,0.06); --border:rgba(0,105,163,0.78);
  --err:#941e15; --warn:#733f00; --info:#0a5f46;
  --err-bg:rgba(192,39,29,0.12); --warn-bg:rgba(154,91,0,0.12);
  --info-bg:rgba(13,115,85,0.12); --body-ink:#0b4f74;
  --el-bg:#e8eef4; --el-bg-error:#ebdcdf; --el-bg-warning:#e7e3dc;
  --shadow:0 8px 30px rgba(20,40,70,.18);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg-from:#1a1a2e; --bg-to:#16213e;
    --surface:#141a2f; --surface-2:#121a2e; --panel:rgba(255,255,255,0.05);
    --text:#e6ecf3; --muted:#9aa7b8; --accent:#00d4ff; --accent-ink:#04212b;
    --focus:#00d4ff; --canvas:#121a2e; --grid:rgba(255,255,255,0.03);
    --chrome:rgba(0,0,0,0.28); --border:rgba(0,212,255,0.62);
    --err:#ff8a94; --warn:#ffb733; --info:#5fd9b0;
    --err-bg:rgba(255,71,87,0.16); --warn-bg:rgba(255,165,2,0.20);
    --info-bg:rgba(78,204,163,0.18); --body-ink:#9fd8ff;
    --el-bg:#1e2538; --el-bg-error:#382135; --el-bg-warning:#413625; --shadow:0 8px 30px rgba(0,0,0,.5);
  }
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;
  background:linear-gradient(135deg,var(--bg-from) 0%,var(--bg-to) 100%);
  color:var(--text); min-height:100vh; padding:20px;
}
.container { max-width:1600px; margin:0 auto; }
h1 { text-align:center; color:var(--accent); margin-bottom:10px; font-size:2.2em; }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; border:0; }
.subtitle { text-align:center; color:var(--muted); margin-bottom:22px; }
:where(button,select,summary,[tabindex]):focus-visible {
  outline:3px solid var(--focus); outline-offset:2px; }
.stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:16px; margin-bottom:22px; }
.stat-card { background:var(--panel); border-radius:15px; padding:16px;
  text-align:center; border:1px solid var(--border); }
.stat-value { font-size:2em; font-weight:bold; color:var(--accent); }
.stat-card.error .stat-value { color:var(--err); }
.stat-card.warning .stat-value { color:var(--warn); }
.stat-card.info .stat-value { color:var(--info); }
.stat-label { color:var(--muted); margin-top:5px; font-size:.9em; }

/* page tabs */
.page-tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
.tab { background:var(--panel); color:var(--text); border:1px solid var(--border);
  border-radius:10px 10px 0 0; padding:9px 16px; cursor:pointer; font-size:.95em;
  white-space:nowrap; }
.tab:hover { background:var(--info-bg); }
.tab.active { background:var(--info-bg); color:var(--text); font-weight:bold;
  border-bottom:3px solid var(--accent); }
.tab.error { border-color:var(--err); } .tab.warning { border-color:var(--warn); }
.tab-badge { margin-left:8px; font-size:.8em; opacity:.85; }

/* active state must survive forced-colors/high-contrast, where background and
   inset shadows are not painted */
@media (forced-colors: active) {
  .tab.active { background:Highlight; color:HighlightText;
    border:2px solid Highlight; border-bottom:3px solid Highlight; }
  .el { border-color:CanvasText; }
  .el.error, .el.warning, .el.ok { border-style:dashed; }
}

/* layout canvas mirrors the report page */
.layout-host { overflow:auto; border:1px solid var(--border); border-radius:10px;
  background:var(--canvas); padding:10px; }
.canvas-wrap { display:none; }
.canvas-wrap.active { display:block; }
/* page caption: hidden on screen (the active tab names the page), printed */
.canvas-title { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; border:0; }
.canvas { position:relative; margin:0 auto; background:var(--surface-2);
  background-image:linear-gradient(var(--grid) 1px,transparent 1px),
    linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:40px 40px; }

/* one element box, placed by true geometry */
.el { position:absolute; background:var(--panel);
  border:2px solid var(--border); border-radius:6px; overflow:hidden;
  cursor:pointer; text-align:left; color:inherit;
  transition:opacity .15s, box-shadow .15s, border-color .15s; }
.el:hover { box-shadow:0 0 0 2px var(--accent); z-index:5; }
.el.error { border-color:var(--err); background:var(--err-bg); }
.el.warning { border-color:var(--warn); background:var(--warn-bg); }
.el.ok { border-color:var(--info); }
.el.dim { opacity:0.14; }
.el-chrome { display:flex; justify-content:space-between; align-items:center;
  gap:6px; padding:3px 6px; background:var(--chrome); font-size:.72em; }
.el-title { white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  color:var(--text); }
.el-body { width:100%; height:calc(100% - 20px); color:var(--body-ink); padding:4px; }
.el-body svg { width:100%; height:100%; display:block; }
/* the donut glyph punches its hole with a surface fill; on an element the
   surface under the hole is that element's own background, which for a severity
   element is its tint over the canvas, not the default `--el-bg` */
.el-body svg circle[fill="var(--surface-2)"] { fill:var(--el-bg); }
.el.error .el-body svg circle[fill="var(--surface-2)"] { fill:var(--el-bg-error); }
.el.warning .el-body svg circle[fill="var(--surface-2)"] { fill:var(--el-bg-warning); }
/* page-level filter diagnostics: they belong to no element box */
.page-issues { list-style:none; margin:0 0 10px; display:flex; flex-direction:column;
  gap:6px; font-size:.85em; }
.page-issues li { display:flex; align-items:baseline; gap:8px; }
/* the page filter classes a page's findings too, and a class without a screen
   rule was simply invisible: the only `.page-issues li.dim` rule lived in the
   print block and forced opacity back to 1 */
.page-issues li.dim { opacity:0.25; }
.el-empty { position:absolute; inset:20px 0 0; display:flex; align-items:center;
  justify-content:center; text-align:center; padding:6px; font-size:.8em;
  color:var(--muted); }
.badge { border-radius:10px; padding:1px 8px; font-size:.78em; font-weight:bold; }
.badge.error { background:var(--err-bg); color:var(--err); }
.badge.warning { background:var(--warn-bg); color:var(--warn); }
.badge.info, .badge.ok { background:var(--info-bg); color:var(--info); }

/* explicit empty state instead of a blank page */
.empty-state { text-align:center; padding:48px 20px; border:1px dashed var(--border);
  border-radius:12px; background:var(--panel); margin:18px 0; }
.empty-state h2 { color:var(--accent); font-size:1.25em; margin-bottom:8px; }
.empty-state p { color:var(--muted); max-width:52ch; margin:0 auto; }
.empty-icon { font-size:2.2em; line-height:1; margin-bottom:10px; color:var(--accent); }

/* details table */
.section { background:var(--panel); border-radius:15px; padding:20px;
  margin-top:22px; border:1px solid var(--border); }
.section > summary { cursor:pointer; color:var(--accent); font-size:1.15em;
  font-weight:bold; }
.section > summary:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
.table-scroll { overflow-x:auto; margin-top:14px; }
.data-table { width:100%; border-collapse:collapse; }
.data-table th, .data-table td { padding:8px 10px; text-align:left;
  border-bottom:1px solid var(--border); font-size:.92em; overflow-wrap:anywhere; }
.data-table th { background:var(--info-bg); color:var(--text); white-space:nowrap; }
.data-table tr:hover { background:var(--panel); }
.data-table tr.dim { opacity:0.25; }
.data-table td.num-error { color:var(--err); font-weight:bold; }
.data-table td.num-warn { color:var(--warn); font-weight:bold; }

/* filters (slide-in) */
.filter-toggle { position:fixed; left:0; top:120px; z-index:35; cursor:pointer;
  background:var(--accent); color:var(--accent-ink); font-weight:bold;
  padding:10px 14px; border:0; font-size:1em; border-radius:0 12px 12px 0;
  transition:left .25s ease; }
/* click-away scrim: a real backdrop, not a documented-but-missing overlay */
.filter-scrim { position:fixed; inset:0; z-index:25; display:none;
  background:rgba(8,20,35,.45); }
.filter-scrim.open { display:block; }
.filter-panel { position:fixed; left:-320px; top:0; width:320px; height:100%;
  z-index:30; background:var(--surface); border-right:1px solid var(--border);
  padding:22px; overflow:auto; visibility:hidden;
  transition:left .25s ease, visibility 0s linear .25s; }
.filter-panel.open { left:0; visibility:visible;
  transition:left .25s ease, visibility 0s; }
.filter-header { display:flex; justify-content:space-between; align-items:center;
  margin-bottom:18px; gap:10px; }
.filter-header h2 { color:var(--accent); font-size:1.15em; }
.btn-close, .filter-panel button { background:var(--panel); color:var(--accent);
  border:1px solid var(--border); border-radius:8px; padding:6px 12px; cursor:pointer; }
.filter-group { margin-bottom:14px; }
.filter-group label { display:block; color:var(--muted); font-size:.85em;
  margin-bottom:4px; }
.filter-group select { width:100%; padding:8px; border-radius:8px;
  background:var(--surface-2); color:var(--text); border:1px solid var(--border); }
.footer { text-align:center; margin-top:26px; color:var(--muted); font-size:.9em; }

/* detail popover */
#detailCard { position:fixed; right:18px; bottom:18px; width:380px; max-height:60vh;
  overflow:auto; z-index:40; background:var(--surface); border:1px solid var(--border);
  border-radius:12px; padding:16px; display:none; box-shadow:var(--shadow);
  color:var(--text); }
#detailCard:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
#detailCard h2 { color:var(--accent); margin-bottom:8px; font-size:1.05em; }
.detail-head { display:flex; justify-content:space-between; align-items:flex-start;
  gap:10px; }
#detailCard .row { font-size:.9em; color:var(--text); margin:3px 0; }
#detailCard ul { margin:8px 0 0 16px; font-size:.88em; }
#detailCard li { margin:3px 0; }

/* narrow viewport: one column, scrollable tables, no clipped labels */
@media (max-width: 720px) {
  body { padding:10px; }
  h1 { font-size:1.55em; }
  .stats-grid { grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; }
  .page-tabs { flex-wrap:nowrap; overflow-x:auto; padding-bottom:4px; }
  .tab { flex:0 0 auto; }
  .layout-host { overflow-x:auto; }
  .section { padding:12px; }
  .filter-panel { width:min(320px,88vw); }
  #detailCard { right:8px; left:8px; bottom:8px; width:auto; max-height:50vh; }
}

/* motion-sensitive users get no transitions or animations */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition:none !important; animation:none !important;
    scroll-behavior:auto !important; }
}

/* print: no controls, dark tokens replaced, details expanded, colors kept */
@media print {
  @page { size:A4 landscape; margin:10mm; }
  /* printing from a system dark theme must not keep the dark tokens: override
     the same custom properties the dark block sets, otherwise text stays
     light-on-white (measured 1.19:1–2.44:1 before this override). */
  :root {
    --bg-from:#fff; --bg-to:#fff;
    --surface:#fff; --surface-2:#fff; --panel:#fff;
    --text:#000; --muted:#222; --accent:#0a4a6e; --accent-ink:#fff;
    --focus:#0a4a6e; --canvas:#fff; --grid:transparent;
    --chrome:transparent; --border:#555;
    --err:#8a1a12; --warn:#6b3f00; --info:#0a5c45;
    --err-bg:#f4e6e4; --warn-bg:#f6efe0; --info-bg:#e4f1ec;
    --body-ink:#111; --el-bg:#fff; --shadow:none;
    --el-bg-error:#f4e6e4; --el-bg-warning:#f6efe0;
  }
  body { background:#fff !important; color:#000 !important; padding:0; }
  * { text-shadow:none !important; box-shadow:none !important;
    transition:none !important; animation:none !important;
    -webkit-print-color-adjust:exact !important;
    print-color-adjust:exact !important; }
  .badge.error { color:#8a1a12 !important; }
  .badge.warning { color:#6b3f00 !important; }
  .badge.info, .badge.ok { color:#0a5c45 !important; }
  .filter-toggle, .filter-scrim, .filter-panel, #detailCard, .footer,
  .page-tabs, header, .stats-grid { display:none !important; }
  .stat-card, .section, .layout-host { border:0 !important; }
  .layout-host { overflow:visible; padding:0; }
  .canvas-wrap { display:block !important; break-inside:avoid; page-break-inside:avoid; }
  /* each page starts on a fresh sheet, so a caption never separates from the
     canvas it names. The header and the summary counters are screen chrome and
     are hidden above: keeping them made the first canvas overflow the sheet by
     their height, so `break-inside:avoid` pushed it to page 2 and a one-page
     report printed as two (measured in Chrome: 3 sheets before, 1 after). */
  .canvas-wrap ~ .canvas-wrap { break-before:page; page-break-before:always; }
  /* every printed canvas carries its page name (the tabs are hidden). The line
     height is explicit so the caption's box is the same on every platform and
     matches the space `_print_scale` reserves; `line-height:normal` is 23 px in
     Chrome, i.e. 4.3 px more than the font size the budget assumed. */
  .canvas-title { position:static; width:auto; height:auto; margin:0 0 6px;
    overflow:visible; clip:auto; white-space:normal; display:block !important;
    color:#000 !important; font-size:14pt; line-height:1.2; }
  /* page-level findings print above the caption; the fit reserves one 21 px row
     per notice plus the 10 px list gap, so the row height is pinned too (the
     badge's 1 px vertical padding makes the flex row taller than its line box) */
  .page-issues { margin:0 0 10px; gap:0; font-size:.85em; }
  .page-issues li { line-height:19px; min-height:21px; align-items:center; }
  .page-issues li.dim { opacity:1; }
  /* a canvas wider than the sheet is scaled by the renderer-computed factor:
     paged media has no horizontal pagination, so it would otherwise be clipped */
  .canvas { background:#fff !important; background-image:none !important;
    zoom:var(--print-scale,1); break-inside:avoid; page-break-inside:avoid; }
  .el { break-inside:avoid; page-break-inside:avoid; }
  /* a collapsed <details> must still print its metrics table. The modern rule
     below is enough in Chromium; `details-content` does not exist in Safari,
     where the display rule on the children is what expands the section. */
  details:not([open]) > *:not(summary) { display:block !important; }
  details::details-content { content-visibility:visible !important; }
  #detailsSection .table-scroll { display:block !important; }
  #metrics-table { height:auto !important; }
  .data-table { font-size:10pt; }
  .data-table thead { display:table-header-group; }
  .data-table tr { break-inside:avoid; page-break-inside:avoid; }
}
"""

# Interactivity: page tabs (keyboard-aware), filter dimming, hover tooltips
# (native title), detail popover from the injected model.
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
  document.querySelectorAll('.tab').forEach((t, i) => {
    const on = i === idx;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
    t.setAttribute('tabindex', on ? '0' : '-1');
  });
  // the detail card belongs to an element of one page: leaving that page would
  // leave the card open over content it does not describe.
  if (detailOpen && detailKey && BY_KEY[detailKey]
      && BY_KEY[detailKey]._pi !== idx) hideDetails();
}

function onTabKey(event) {
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const at = tabs.indexOf(document.activeElement);
  if (at < 0) return;
  let next = null;
  if (event.key === 'ArrowRight') next = (at + 1) % tabs.length;
  else if (event.key === 'ArrowLeft') next = (at - 1 + tabs.length) % tabs.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = tabs.length - 1;
  if (next === null) return;
  event.preventDefault();
  tabs[next].focus();
  showPage(next);
}

let filterOpen = false;
let detailOpen = false;
function setFilterToggleLabel(toggle, open) {
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  toggle.setAttribute('aria-label',
    open ? 'Закрыть панель фильтров' : 'Открыть панель фильтров');
}
function toggleFilterPanel(force) {
  const panel = document.getElementById('filterPanel');
  const toggle = document.getElementById('filterToggle');
  const scrim = document.getElementById('filterScrim');
  if (!panel || !toggle || !scrim) return;
  const open = typeof force === 'boolean' ? force : !filterOpen;
  const width = panel.offsetWidth || 320;
  filterOpen = open;
  panel.classList.toggle('open', open);
  panel.style.left = open ? '0' : '-' + width + 'px';
  panel.inert = !open;
  panel.setAttribute('aria-hidden', open ? 'false' : 'true');
  scrim.classList.toggle('open', open);
  toggle.style.left = open ? width + 'px' : '0';
  setFilterToggleLabel(toggle, open);
  if (open) {
    const first = panel.querySelector('button, select, [tabindex]');
    if (first) first.focus();
  } else if (panel.contains(document.activeElement)
      || document.activeElement === document.body) {
    toggle.focus();
  }
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
  // the page is matched by its ordinal: two pages may share a display name, and
  // matching by name then dimmed/hid elements of the other page as well.
  if (page !== '' && el.dataset.pageIdx !== page) return false;
  if (kind && el.dataset.kind !== kind) return false;
  if (check && !(el.dataset.checks || '').split(',').includes(check)) return false;
  return true;
}

function applyFilters(seed) {
  const sev = document.getElementById('filter-severity').value;
  const pageIdx = document.getElementById('filter-page').value;
  const page = pageIdx;
  const kind = document.getElementById('filter-kind').value;
  const check = document.getElementById('filter-check').value;
  const els = Array.from(document.querySelectorAll('.el'));
  const kept = els.map(el => matches(el, sev, page, kind, check));
  els.forEach((el, i) => el.classList.toggle('dim', !kept[i]));
  // page-level findings are rendered per page, not as elements: dim them by the
  // same severity/check/page criteria so "isolate this finding" also covers them.
  const notices = Array.from(document.querySelectorAll('.page-issues li'));
  notices.forEach(li => {
    const wrap = li.closest('.canvas-wrap');
    const samePage = page === '' || (!!wrap && wrap.dataset.page === page);
    const sameSev = !sev
      || (sev === 'ok' ? false : li.dataset.severity === sev);
    const sameCheck = !check || li.dataset.check === check;
    li.classList.toggle('dim', !(samePage && sameSev && sameCheck));
  });
  // detail rows carry the same keys as the elements, so one predicate drives both
  document.querySelectorAll('tr[data-detail]').forEach(tr => {
    tr.classList.toggle('dim', !matches(tr, sev, page, kind, check));
  });
  // the counter and the visible canvas must describe the same elements:
  // filter by page when one is chosen, else jump to the first matching page.
  let target = pageIdx === '' ? null : +pageIdx;
  if (target === null) {
    const first = els.find((el, i) => kept[i]);
    if (first) target = BY_KEY[first.dataset.key]._pi;
    else {
      // A page-level finding can be the *only* match (it belongs to no element):
      // without this the filter switched nothing, left the matching page hidden
      // and the counter reported "0 элементов показано".
      const notice = notices.find(li => !li.classList.contains('dim'));
      const wrap = notice && notice.closest('.canvas-wrap');
      if (wrap) target = Number(wrap.dataset.page);
    }
  }
  // `seed` only fills the counter on load; jumping there would override the
  // server-rendered first tab and open the report on a different page.
  if (seed !== true && target !== null) showPage(target);
  const active = document.querySelector('.canvas-wrap.active');
  const visible = active ? active.querySelectorAll('.el:not(.dim)').length : 0;
  const shownNotices = active
    ? active.querySelectorAll('.page-issues li:not(.dim)').length : 0;
  document.getElementById('filter-count').innerText =
    visible + ' элементов показано'
    + (shownNotices ? ' · ' + shownNotices + ' замечаний страницы' : '');
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

let detailKey = null;
function showDetails(key) {
  const el = BY_KEY[key];
  const card = document.getElementById('detailCard');
  if (!el) { hideDetails(); return; }
  const m = el.metrics;
  const e = escapeHtml;
  const issues = (el.issues || []).length
    ? '<ul>' + el.issues.map(i =>
        '<li><span class="badge ' + e(i.severity) + '">' + e(i.severity) + '</span> '
        + e(i.check_id) + ' — ' + e(i.message) + '</li>').join('') + '</ul>'
    : '<div class="row">нарушений нет</div>';
  document.getElementById('detailTitle').textContent =
    el.label + ' · ' + el.visual_type + ' · ' + el._page;
  document.getElementById('detailBody').innerHTML =
    '<div class="row">страница: ' + e(el._page) + '</div>'
    + '<div class="row">полей: ' + m.fields + ' · ролей: ' + m.roles
    + ' · цветов: ' + m.colors + ' · фильтров: ' + m.filters + '</div>'
    + '<div class="row">ошибок: ' + m.errors + ' · предупр.: ' + m.warnings + '</div>'
    + issues;
  detailKey = key;
  detailOpen = true;
  card.style.display = 'block';
  card.focus();
  const live = document.getElementById('detailLive');
  if (live) {
    live.textContent = 'Открыты детали: ' + el._page + ' · ' + el.label
      + ', замечаний: ' + (el.issues || []).length;
  }
}

function hideDetails() {
  const card = document.getElementById('detailCard');
  if (!card || !detailOpen) return;
  // Only a close that takes focus *from* the card restores it. When the card is
  // closed as a side effect (tab switch, filter jump) the user's focus is
  // somewhere else — on the tab or the select — and moving it to #filterToggle
  // killed arrow-key tab navigation and ejected focus from the filter panel.
  const ownsFocus = card === document.activeElement
    || card.contains(document.activeElement);
  card.style.display = 'none';
  detailOpen = false;
  const previous = detailKey && Array.from(document.querySelectorAll('.el'))
    .find(node => node.dataset.key === detailKey);
  detailKey = null;
  // clear the announcement so re-opening the same element changes the text and
  // is announced again instead of being swallowed as an unchanged live region
  const live = document.getElementById('detailLive');
  if (live) live.textContent = 'Детали элемента закрыты';
  if (!ownsFocus) return;
  // the owning page may be hidden by now (tab switch, filter jump): focusing an
  // element inside a display:none panel is a no-op that drops focus to <body>.
  const fallback = document.getElementById('filterToggle');
  if (previous && previous.offsetParent) previous.focus();
  else if (fallback) fallback.focus();
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.el').forEach(el => {
    el.addEventListener('click', () => showDetails(el.dataset.key));
    el.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        showDetails(el.dataset.key);
      }
    });
  });
  const tabs = document.getElementById('pageTabs');
  if (tabs) tabs.addEventListener('keydown', onTabKey);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (detailOpen) hideDetails();
      if (filterOpen) toggleFilterPanel(false);
    }
  });
  // seed the counter: the panel's only feedback must not stay empty until the
  // first filter change
  if (document.getElementById('filter-count')) applyFilters(true);
});
"""
