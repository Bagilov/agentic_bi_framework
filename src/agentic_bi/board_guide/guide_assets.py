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
  display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap; }
header h1 { font-size: 16px; margin: 0; }
header .meta { font-size: 12px; opacity: .82; }
header a.back { color: #7fd4ff; text-decoration: none; font-size: 13px; }
.stage { position: relative; margin: 18px auto; width: min(1400px, 96vw); }
.imgwrap { position: relative; border: 1px solid #c9d2de; background: #fff;
  box-shadow: 0 2px 10px rgba(20, 34, 54, .10); }
.imgwrap img { display: block; width: 100%; height: auto; max-width: 100%;
  object-fit: contain; }
.hot { position: absolute; box-sizing: border-box; cursor: pointer;
  border: 1.5px solid rgba(0, 132, 255, .65); background: rgba(0, 132, 255, .09);
  transition: background .15s, box-shadow .15s; }
.hot.overlap { border-style: dashed; }
.hot:hover, .hot.active { background: rgba(0, 132, 255, .30);
  box-shadow: 0 0 0 2px #0084ff; }
.hotlabel { display: none; position: absolute; top: 4px; left: 4px; z-index: 3;
  max-width: min(90vw, 320px); padding: 2px 7px; border-radius: 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  background: rgba(24, 33, 45, .92); color: #fff; font-size: 12px;
  font-weight: 600; pointer-events: none; }
.hot:hover .hotlabel, .hot.active .hotlabel { display: block; }
.hot.label-above .hotlabel { top: auto; bottom: 100%; margin-bottom: 3px; }
.hot.label-below .hotlabel { top: 100%; margin-top: 3px; }
.empty, .noimg { margin: 14px 18px; padding: 12px 14px; border-radius: 8px;
  background: #fff8e1; border: 1px solid #f0d68a; color: #6b5200; font-size: 13px; }
.noimg { margin: 0; text-align: center; }
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
.voverlap { font-size: 12px; color: #8a4b00; margin-top: 6px; }
.vdax { margin-top: 6px; }
.vdax summary { cursor: pointer; color: #1a56a0; font-size: 12px; }
.vdax code { display: block; font-size: 11px; white-space: pre-wrap;
  background: #f6f8fa; border-radius: 4px; padding: 6px; margin-top: 4px; }
.printlist { display: none; font-size: 12px; }
.printlist h2 { font-size: 13px; margin: 0 0 4px; }
.printlist ol { margin: 0; padding-left: 20px; }
.printlist li { margin: 3px 0; }

/* Wide screens: the fixed panel is 370 px wide on the right, so the stage
   reserves that column instead of putting the top-right hotspots underneath. */
@media (min-width: 1101px) {
  .stage { box-sizing: border-box; padding-right: 400px; }
}

/* Narrow screens: the panel must not sit on top of the screenshot, and the
   stage keeps the image's own height so percentage hotspots stay aligned. */
@media (max-width: 1100px) {
  .stage { width: 100%; margin: 12px 0; }
  .panel { position: static; width: auto; max-height: none; margin: 12px 18px 24px;
    box-shadow: none; }
}

/* Print: no shadows or dark backgrounds, the panel flows after the image, and
   the screenshot is never split across pages. The image is scaled by width only:
   a height cap would activate `object-fit: contain` inside a wrapper whose
   hotspots stay container-relative, so a tall screenshot would letterbox and
   every hotspot would drift by the side padding. */
@page { margin: 10mm; }
@media print {
  body { background: #fff; color: #000; }
  header { background: #fff; color: #000; border-bottom: 1px solid #999; }
  header a.back { color: #000; }
  .stage { width: 100%; margin: 0; padding-right: 0; }
  .imgwrap { box-shadow: none; border-color: #888;
    break-inside: avoid; page-break-inside: avoid; }
  .hot { background: transparent; box-shadow: none; }
  .hotlabel { display: none !important; }
  .panel { position: static; width: auto; max-height: none; margin: 8px 0 0;
    border: 0; border-top: 1px solid #999; border-radius: 0; box-shadow: none;
    padding: 8px 0 0; }
  .panel .hint { display: none; }
  .printlist { display: block; margin: 10px 0 0; }
  .empty, .noimg { background: #fff; border-color: #999; color: #000; }
}
"""

INDEX_CSS = """
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: #f4f6f9; color: #1c2430; padding: 24px; }
h1 { font-size: 18px; } .sub { color: #667; font-size: 13px; margin: 4px 0 18px; }
ol { padding-left: 22px; } li { margin: 8px 0; }
li a { color: #0069d9; text-decoration: none; }
li a:hover { text-decoration: underline; }
.meta { color: #788; font-size: 12px; margin-left: 8px; }
.empty { padding: 12px 14px; border-radius: 8px; background: #fff8e1;
  border: 1px solid #f0d68a; color: #6b5200; font-size: 13px; }
.skipped { margin-top: 22px; font-size: 13px; }
.skipped h2 { font-size: 14px; color: #6b5200; margin: 0 0 6px; }
.skipped ul { padding-left: 22px; } .skipped li { margin: 4px 0; color: #555; }
@media print {
  body { background: #fff; padding: 0; }
  li a { color: #000; }
  .empty { background: #fff; border-color: #999; color: #000; }
}
"""

# Hover/click panel driven by a `REFS` array of HTML strings (one per hotspot).
PAGE_JS = """
const REFS = window.__GUIDE_REFS__ || [];
const hot = document.querySelectorAll('.hot');
const panel = document.getElementById('panel');
const hint = '<span class="hint">Наведите курсор на визуал — появится справка.</span>';
const show = h => {
  hot.forEach(x => x.classList.remove('active'));
  h.classList.add('active');
  if (panel) panel.innerHTML = REFS[Number(h.dataset.i)] || hint;
};
hot.forEach(h => {
  h.addEventListener('mouseenter', () => show(h));
  h.addEventListener('focus', () => show(h));
  h.addEventListener('mouseleave', () => { h.classList.remove('active'); });
  h.addEventListener('blur', () => { h.classList.remove('active'); });
  h.addEventListener('click', () => show(h));
  h.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      show(h);
    }
  });
});
const shot = document.querySelector('.imgwrap img');
if (shot) shot.addEventListener('error', () => {
  const wrap = shot.closest('.imgwrap');
  hot.forEach(h => h.remove());
  shot.remove();
  if (wrap) {
    const broken = document.createElement('div');
    broken.className = 'noimg';
    broken.textContent = 'Скриншот не загрузился: hotspots скрыты.';
    wrap.appendChild(broken);
  }
  if (panel) panel.innerHTML = hint;
});
"""

__all__ = ["INDEX_CSS", "PAGE_CSS", "PAGE_JS"]
