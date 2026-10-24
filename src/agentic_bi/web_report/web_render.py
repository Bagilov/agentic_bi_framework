"""Render the dashboard clone as a *layout* of the original report.

The output mirrors the source report: page tabs, and on each page every element
is placed at its true `Report/Layout` position/size and drawn with a mock glyph
for its visual type (the real visuals cannot render without the engine). Each
element is interactive:

* hovering shows a tooltip with its metrics and the checks it violated;
* problem elements are outlined by severity (red/amber);
* the filter panel (severity / page / visual type / check id) dims everything
  that does not match, so problem spots can be isolated on the layout.

A collapsed "details" section carries the flat metrics table and the issue list
for those who want the tabular view.

Public API:
    render_html(model, title=...) -> str
    write_html(model, path, title=...) -> Path

The page needs no network except the vis-network CDN (unused when the layout has
no graph); the layout itself is pure HTML/CSS.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from agentic_bi.web_report.web_assets import CSS, SCRIPT
from agentic_bi.web_report.web_mock import mock_body
from agentic_bi.web_report.web_model import ElementReport, WebReportModel

logger = logging.getLogger(__name__)

_SEVERITY_LABEL = {"error": "Ошибка", "warning": "Предупр.", "info": "Инфо"}

# Fallback canvas when a page has no explicit size.
_DEFAULT_W, _DEFAULT_H = 1280, 720


# Characters json.dumps leaves alone that are unsafe inside a <script> element.
_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _json_for_script(payload: object) -> str:
    """Serialize `payload` for embedding inside a `<script>` element.

    `json.dumps` escapes quotes and backslashes but not `<` or `>`, so a string
    taken from the report (a visual title, an entity name in an issue message)
    could close the script element early and inject markup. Escaping happens at
    this single sink rather than per input, so every current and future source is
    covered. The escape keeps the document valid JSON.
    """
    text = json.dumps(payload, ensure_ascii=False)
    for char, escaped in _SCRIPT_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


def _tooltip(el: ElementReport) -> str:
    m = el.metrics
    head = f"{el.label} · {el.visual_type}"
    lines = [
        f"полей: {m.fields}",
        f"ролей: {m.roles}",
        f"цветов: {m.colors}",
        f"фильтров: {m.filters}",
    ]
    body = " | ".join(lines)
    if not el.issues:
        return f"{head}\n{body}\nнарушений нет"
    found = "\n".join(f"[{i.severity}] {i.check_id}: {i.message}" for i in el.issues)
    return f"{head}\n{body}\n{found}"


def _page_tabs(model: WebReportModel) -> str:
    tabs = []
    for idx, page in enumerate(model.pages):
        worst = _page_worst(page)
        bad = sum(1 for e in page.elements if e.issues)
        cls = f"tab {worst}" if bad else "tab ok"
        active = " active" if idx == 0 else ""
        tabs.append(
            f'<button class="{cls}{active}" data-page-tab="{idx}" '
            f'onclick="showPage({idx})">{_e(page.name)}'
            f'<span class="tab-badge">{bad}</span></button>'
        )
    return "".join(tabs)


def _page_worst(page) -> str:
    if any(i.severity == "error" for e in page.elements for i in e.issues):
        return "error"
    if any(i.severity == "warning" for e in page.elements for i in e.issues):
        return "warning"
    if any(e.issues for e in page.elements):
        return "info"
    return "ok"


def _element_box(el: ElementReport) -> str:
    m = el.metrics
    severity = m.worst if el.issues else "ok"
    checks = ",".join(sorted({i.check_id for i in el.issues}))
    corner = _SEVERITY_LABEL[m.worst] if el.issues else "OK"
    style = f"left:{el.x}px;top:{el.y}px;width:{el.width}px;height:{el.height}px;"
    return (
        f'<div class="el {severity}" data-el="1" data-page="{_e(el.page)}" '
        f'data-kind="{_e(el.visual_type)}" data-severity="{severity}" '
        f'data-checks="{_e(checks)}" data-key="{_e(el.key)}" style="{style}" '
        f'title="{_e(_tooltip(el))}">'
        f'<div class="el-chrome"><span class="el-title">{_e(el.label)}</span>'
        f'<span class="badge {severity}">{corner}</span></div>'
        f'<div class="el-body">{mock_body(el.visual_type)}</div>'
        f"</div>"
    )


def _pages(model: WebReportModel) -> str:
    out = []
    for idx, page in enumerate(model.pages):
        w = int(page.width or _DEFAULT_W)
        h = int(page.height or _DEFAULT_H)
        active = " active" if idx == 0 else ""
        boxes = "".join(_element_box(el) for el in page.elements)
        out.append(
            f'<section class="canvas-wrap{active}" data-page="{idx}">'
            f'<div class="canvas" style="width:{w}px;height:{h}px">{boxes}</div>'
            f"</section>"
        )
    return "".join(out)


def _summary_cards(model: WebReportModel) -> str:
    s = model.summary()
    cards = [
        ("", s["pages"], "Страниц"),
        ("", s["elements"], "Элементов"),
        ("error", s["error"], "Ошибок"),
        ("warning", s["warning"], "Предупреждений"),
        ("info", s["info"], "Инфо"),
    ]
    return "".join(
        f'<div class="stat-card {cls}"><div class="stat-value">{val}</div>'
        f'<div class="stat-label">{label}</div></div>'
        for cls, val, label in cards
    )


def _filter_options(model: WebReportModel) -> tuple[str, str, str]:
    pages = [(i, p.name) for i, p in enumerate(model.pages)]
    kinds = sorted({e.visual_type for e in model.elements})
    checks = sorted({i.check_id for e in model.elements for i in e.issues})
    page_opts = '<option value="">Все страницы</option>' + "".join(
        f'<option value="{i}">{_e(n)}</option>' for i, n in pages
    )
    kind_opts = '<option value="">Все типы</option>' + "".join(
        f'<option value="{_e(k)}">{_e(k)}</option>' for k in kinds
    )
    check_opts = '<option value="">Все проверки</option>' + "".join(
        f'<option value="{_e(c)}">{_e(c)}</option>' for c in checks
    )
    return page_opts, kind_opts, check_opts


def _detail_rows(model: WebReportModel) -> str:
    rows = []
    for el in model.elements:
        m = el.metrics
        severity = m.worst if el.issues else "ok"
        badge_text = _SEVERITY_LABEL[m.worst] if el.issues else "OK"
        checks = ", ".join(sorted({i.check_id for i in el.issues})) or "—"
        rows.append(
            f'<tr data-detail="{_e(el.key)}" data-severity="{severity}">'
            f"<td>{_e(el.page)}</td><td>{_e(el.label)}</td>"
            f"<td>{_e(el.visual_type)}</td><td>{m.fields}</td>"
            f"<td>{m.roles}</td><td>{m.colors}</td><td>{m.filters}</td>"
            f'<td style="color:#ff4757">{m.errors}</td>'
            f'<td style="color:#ffa502">{m.warnings}</td>'
            f"<td>{_e(checks)}</td>"
            f'<td><span class="badge {severity}">{badge_text}</span></td></tr>'
        )
    return "".join(rows)


def render_html(model: WebReportModel, title: str = "Dashboard Clone") -> str:
    """Render the report clone as an interactive layout."""
    page_opts, kind_opts, check_opts = _filter_options(model)
    model_json = _json_for_script(_model_payload(model))
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(title)} · {_e(model.source)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>{_e(title)}</h1>
  <div class="subtitle">Макет отчёта: {_e(model.source)} · наведите на элемент и
    включите фильтры, чтобы выделить проблемные места</div>

  <div class="stats-grid">{_summary_cards(model)}</div>

  <div class="page-tabs" id="pageTabs">{_page_tabs(model)}</div>
  <div class="layout-host" id="layoutHost">{_pages(model)}</div>

  <details class="section" id="detailsSection">
    <summary>Метрики и нарушения по элементам (таблица)</summary>
    <table class="data-table" id="metrics-table">
      <thead><tr>
        <th>Страница</th><th>Элемент</th><th>Тип</th><th>Полей</th>
        <th>Ролей</th><th>Цветов</th><th>Фильтров</th><th>Ошибок</th>
        <th>Предупр.</th><th>Проверки</th><th>Статус</th>
      </tr></thead>
      <tbody>{_detail_rows(model)}</tbody>
    </table>
  </details>
</div>

<div class="filter-toggle" onclick="toggleFilterPanel()">Фильтры</div>
<div class="filter-panel" id="filterPanel">
  <div class="filter-header">
    <h3>Проблемные места</h3>
    <button class="btn-close" onclick="toggleFilterPanel()">×</button>
  </div>
  <div class="filter-group">
    <label for="filter-severity">Уровень</label>
    <select id="filter-severity" onchange="applyFilters()">
      <option value="">Все уровни</option>
      <option value="error">Только ошибки</option>
      <option value="warning">Предупреждения</option>
      <option value="info">Инфо</option>
      <option value="ok">Без нарушений</option>
    </select>
  </div>
  <div class="filter-group">
    <label for="filter-page">Страница</label>
    <select id="filter-page" onchange="applyFilters()">{page_opts}</select>
  </div>
  <div class="filter-group">
    <label for="filter-kind">Тип визуала</label>
    <select id="filter-kind" onchange="applyFilters()">{kind_opts}</select>
  </div>
  <div class="filter-group">
    <label for="filter-check">Проверка</label>
    <select id="filter-check" onchange="applyFilters()">{check_opts}</select>
  </div>
  <div class="filter-group">
    <button onclick="resetFilters()">Сбросить</button>
  </div>
  <div class="filter-group"><span id="filter-count" class="stat-label"></span></div>
</div>

<div class="footer">{_e(title)} · agentic_bi.web_report</div>
<div id="detailCard"></div>

<script>window.__REPORT_MODEL__ = {model_json};</script>
<script>{SCRIPT}</script>
</body>
</html>
"""


def _model_payload(model: WebReportModel) -> dict:
    """The compact model handed to the client (details lookup)."""
    return {
        "source": model.source,
        "summary": model.summary(),
        "pages": [
            {
                "name": p.name,
                "width": p.width,
                "height": p.height,
                "elements": [
                    {
                        "key": e.key,
                        "label": e.label,
                        "visual_type": e.visual_type,
                        "x": e.x,
                        "y": e.y,
                        "width": e.width,
                        "height": e.height,
                        "metrics": vars(e.metrics),
                        "issues": [vars(i) for i in e.issues],
                    }
                    for e in p.elements
                ],
            }
            for p in model.pages
        ],
    }


def write_html(
    model: WebReportModel, path: str | Path, title: str = "Dashboard Clone"
) -> Path:
    """Render and write the clone HTML; returns the written path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(model, title=title), encoding="utf-8")
    logger.info("web_report: %s (%d B)", path, path.stat().st_size)
    return path
