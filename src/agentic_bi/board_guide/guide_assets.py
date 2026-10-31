"""Static HTML/CSS for the annotated board guide.

The guide is deliberately plain: a page header, the screenshot with absolutely
positioned hotspot divs (canvas percentages), and a fixed side panel filled from
a JSON array on hover/click. No framework, no CDN, no network.

Public API:
    PAGE_CSS   - the page stylesheet
    INDEX_CSS  - the index stylesheet
    PAGE_JS    - the hover/click script (reads a `REFS` array)
"""

from __future__ import annotations

PAGE_CSS = """
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  margin: 0; background: #f4f6f9; color: #1c2430; }
header { padding: 10px 18px; background: #1f2630; color: #fff;
  display: flex; gap: 14px; align-items: baseline; }
header h1 { font-size: 16px; margin: 0; }
header .meta { font-size: 12px; opacity: .82; }
header a.back { color: #7fd4ff; text-decoration: none; font-size: 13px; }
.stage { position: relative; margin: 18px auto; width: min(1400px, 96vw); }
.imgwrap { position: relative; border: 1px solid #c9d2de; background: #fff;
  box-shadow: 0 2px 10px rgba(20, 34, 54, .10); }
.imgwrap img { display: block; width: 100%; }
.hot { position: absolute; box-sizing: border-box; cursor: pointer;
  border: 1.5px solid rgba(0, 132, 255, .65); background: rgba(0, 132, 255, .09);
  transition: background .15s, box-shadow .15s; }
.hot:hover, .hot.active { background: rgba(0, 132, 255, .30);
  box-shadow: 0 0 0 2px #0084ff; }
.panel { position: fixed; right: 12px; top: 64px; width: 340px; max-height: 84vh;
  overflow: auto; background: #fff; border: 1px solid #d6dee9; border-radius: 8px;
  padding: 12px 14px; box-shadow: 0 6px 22px rgba(20, 34, 54, .18); }
.panel .hint { color: #667; font-size: 13px; }
.vtype { font-weight: 700; color: #0069d9; margin-bottom: 6px; }
.tagrow { margin-bottom: 6px; }
.tag { display: inline-block; background: #e8f0fe; color: #1a56a0; border-radius: 10px;
  padding: 1px 8px; margin: 2px 3px 2px 0; font-size: 12px; }
.vmeasure { font-weight: 600; margin: 6px 0; }
.vfilter { font-size: 12px; color: #555; margin: 4px 0; }
.vdax { margin-top: 6px; }
.vdax summary { cursor: pointer; color: #1a56a0; font-size: 12px; }
.vdax code { display: block; font-size: 11px; white-space: pre-wrap;
  background: #f6f8fa; border-radius: 4px; padding: 6px; margin-top: 4px; }
"""

INDEX_CSS = """
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: #f4f6f9; color: #1c2430; padding: 24px; }
h1 { font-size: 18px; } .sub { color: #667; font-size: 13px; margin: 4px 0 18px; }
ol { padding-left: 22px; } li { margin: 8px 0; }
li a { color: #0069d9; text-decoration: none; }
li a:hover { text-decoration: underline; }
.meta { color: #788; font-size: 12px; margin-left: 8px; }
"""

# Hover/click panel driven by a `REFS` array of HTML strings (one per hotspot).
PAGE_JS = """
const REFS = window.__GUIDE_REFS__ || [];
const hot = document.querySelectorAll('.hot');
const panel = document.getElementById('panel');
const hint = '<span class="hint">Наведите курсор на визуал — появится справка.</span>';
hot.forEach(h => {
  h.addEventListener('mouseenter', () => {
    hot.forEach(x => x.classList.remove('active'));
    h.classList.add('active');
    if (panel) panel.innerHTML = REFS[Number(h.dataset.i)] || hint;
  });
  h.addEventListener('mouseleave', () => { h.classList.remove('active'); });
  h.addEventListener('click', () => {
    if (panel) panel.innerHTML = REFS[Number(h.dataset.i)] || hint;
  });
});
"""

__all__ = ["INDEX_CSS", "PAGE_CSS", "PAGE_JS"]
