"""Render the dashboard clone as a *layout* of the original report.

The output mirrors the source report: page tabs, and on each page every element
is placed at its true `Report/Layout` position/size and drawn with a mock glyph
for its visual type (the real visuals cannot render without the engine). Each
element is interactive:

* hovering shows a tooltip with its metrics and the checks it violated;
* clicking (or Enter/Space) opens a details popover;
* problem elements are outlined by severity (red/amber);
* the filter panel (severity / page / visual type / check id) dims everything
  that does not match, so problem spots can be isolated on the layout.

A collapsed "details" section carries the flat metrics table and the issue list
for those who want the tabular view.

The document is accessible (landmarks, heading levels, tab semantics, visible
focus, keyboard-operable elements), theme-aware, responsive and printable. A
report with no pages/elements gets an explicit empty state instead of a blank
page, including a placeholder for an individual visual with no data.

Public API:
    render_html(model, title=...) -> str
    write_html(model, path, title=...) -> Path

The page needs no network; the layout itself is pure HTML/CSS.
"""

from __future__ import annotations

import html
import json
import logging
import math
from pathlib import Path

from agentic_bi.web_report.web_assets import CSS, SCRIPT
from agentic_bi.web_report.web_checks import NON_DATA_TYPES
from agentic_bi.web_report.web_mock import mock_body
from agentic_bi.web_report.web_model import ElementReport, WebReportModel

# Size exception (>300 lines): one document template split into named section
# builders kept in file order; headings, landmarks and ARIA ordering only make
# sense read top to bottom.

logger = logging.getLogger(__name__)

_SEVERITY_LABEL = {"error": "Ошибка", "warning": "Предупр.", "info": "Инфо"}
_SEVERITY_ARIA = {
    "error": "есть ошибки",
    "warning": "есть предупреждения",
    "info": "есть замечания",
    "ok": "нарушений нет",
}

# Fallback canvas when a page has no explicit size.
_DEFAULT_W, _DEFAULT_H = 1280, 720

# Printable content box of an A4 landscape sheet with 10 mm margins, in CSS px
# at 96 dpi (297-20 mm and 210-20 mm). Paged media has neither horizontal nor
# vertical pagination, so a canvas is scaled to fit *both* dimensions instead of
# being clipped at the right edge or torn across sheets.
_PRINT_CONTENT_PX = 1046.93
_PRINT_SHEET_PX_H = 718.11
# The printed caption is 14 pt with `line-height:1.2` (set in the print block, so
# the box is the same on every platform) plus its 6 px bottom margin. Using
# `line-height:normal` reserved only the font size: measured in Chrome the line
# box is 23 px, i.e. 4.3 px more than reserved, and a height-bound canvas then
# tore onto a second sheet.
_PRINT_CAPTION_PX = 14 * 96 / 72 * 1.2 + 6
# One page-level notice row and the gap the list adds above the caption. Measured
# in Chrome: the row is 21 px (13.6 px text on a 19 px line box, plus the badge's
# 1 px vertical padding), and the list adds a 10 px bottom margin. A page with an
# unsafe filter carried that block free of charge, so the same 4-5 px overflow
# tearing appeared as without a caption reserve.
_PRINT_NOTICE_LINE_PX = 21.0
_PRINT_NOTICE_GAP_PX = 10.0
#: Characters that fit one printed notice line, measured conservatively: 1046 px
#: of sheet at 13.6 px text fits ~150 Latin characters, but a Cyrillic message
#: averages ~7 px per character and word wrapping wastes part of the last line, so
#: the estimate is 120. A longer message is reserved as extra lines instead of
#: being silently over budget (over-reserving only shrinks the canvas a little).
_PRINT_NOTICE_CHARS = 120
#: Smallest scale the fit will emit. A pathological notice count can exceed the
#: sheet; a floor keeps the CSS declaration valid (a negative `zoom` is ignored,
#: which would print the canvas at full size and tear it even worse).
_PRINT_MIN_SCALE = 0.02
# The PDF page box Chrome produces is 0.42 px shorter than the derived 190 mm:
# keep that back so rounding cannot push the block over the sheet.
_PRINT_SAFETY_PX = 1.0
# Upper bound for geometry taken from a public model: keeps the CSS values finite
# and free of unit/declaration injection.
_MAX_GEOMETRY = 100000.0


def _number(value: float | int | str | None, default: float = 0.0) -> float:
    """Coerce `value` to a finite number; unparsable input falls back to `default`."""
    try:
        number = float(default if value is None else value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(-_MAX_GEOMETRY, min(_MAX_GEOMETRY, number))


def _size(value: float | int | str | None, default: float) -> float:
    """A canvas dimension: positive and finite, else the fallback."""
    number = _number(value, default)
    return number if number > 0 else default


def _fmt(value: float) -> str:
    """Format a validated number for a CSS declaration (no exponent, no units)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _print_scale(width: float, height: float, notices: int = 0) -> float:
    """The print-only scale that keeps a `width`×`height` canvas on one sheet.

    Args:
        width: canvas width in CSS px.
        height: canvas height in CSS px.
        notices: how many page-level notice lines are printed above the caption.
            They are a real block on the sheet, so a page with an unsafe filter
            needs a smaller canvas than a clean page of the same size.

    Returns:
        A scale in `[_PRINT_MIN_SCALE, 1.0]`; the floor keeps the CSS declaration
        valid when a pathological notice count exceeds the whole sheet.
    """
    reserve = _PRINT_CAPTION_PX + _PRINT_SAFETY_PX
    if notices > 0:
        reserve += notices * _PRINT_NOTICE_LINE_PX + _PRINT_NOTICE_GAP_PX
    return max(
        _PRINT_MIN_SCALE,
        min(
            1.0,
            _PRINT_CONTENT_PX / max(width, 1.0),
            (_PRINT_SHEET_PX_H - reserve) / max(height, 1.0),
        ),
    )


def _notice_lines(page) -> int:
    """The printed line boxes the page's findings occupy above the caption.

    A notice is `CHECK-ID: message` in one line box; a message longer than
    `_PRINT_NOTICE_CHARS` wraps onto another one and is counted, so a verbose
    finding cannot silently push the canvas past the sheet.
    """
    total = 0
    for issue in page.filter_issues:
        text = f"{issue.check_id}: {issue.message}"
        total += max(1, math.ceil(len(text) / _PRINT_NOTICE_CHARS))
    return total


def _scale_text(scale: float) -> str:
    """The scale as a 6-decimal CSS number, rounded down.

    Rounding up can put a canvas a fraction of a pixel past the sheet budget,
    which is enough for the browser to break it onto a second sheet.
    """
    text = f"{math.floor(scale * 1_000_000) / 1_000_000:.6f}"
    return "0" if text.startswith("-") else text


# Characters json.dumps leaves alone that are unsafe inside a <script> element.
_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}


def _e(text: object) -> str:
    """Escape text for HTML text and attribute contexts.

    A literal carriage return cannot survive an attribute: the HTML tokenizer
    normalises CR to LF before the DOM is built, so an element key carrying CR
    reached the client as a different string and clicking the element found no
    entry in `BY_KEY`. `&#13;` is resolved after that normalisation, so the DOM
    value keeps the CR the model meant.
    """
    return html.escape(str(text), quote=True).replace("\r", "&#13;")


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
    body = " | ".join(
        [
            f"полей: {m.fields}",
            f"ролей: {m.roles}",
            f"цветов: {m.colors}",
            f"фильтров: {m.filters}",
        ]
    )
    if not el.issues:
        return f"{head}\n{body}\nнарушений нет"
    found = "\n".join(f"[{i.severity}] {i.check_id}: {i.message}" for i in el.issues)
    return f"{head}\n{body}\n{found}"


def _empty_state(title: str, hint: str, extra: str = "") -> str:
    """An explicit placeholder shown instead of a blank page/section."""
    return (
        f'<div class="empty-state{extra}">'
        f'<div class="empty-icon" aria-hidden="true">◍</div>'
        f"<h2>{_e(title)}</h2><p>{_e(hint)}</p></div>"
    )


def _sev_label(severity: str) -> str:
    """The Russian label for a severity, tolerating a value from a public model."""
    return _SEVERITY_LABEL.get(severity, "Инфо")


def _page_tabs(model: WebReportModel) -> str:
    tabs = []
    for idx, page in enumerate(model.pages):
        worst = _page_worst(page)
        # The badge and the accessible name announce *findings*, so they use the
        # page's issue count. Counting elements that have issues made the tab say
        # "1" while the header said "3 ошибок" for an element with three.
        bad = page.issues
        cls = f"tab {worst}" if bad else "tab ok"
        active = " active" if idx == 0 else ""
        selected = "true" if idx == 0 else "false"
        focus = "0" if idx == 0 else "-1"
        tabs.append(
            f'<button type="button" class="{cls}{active}" role="tab" '
            f'id="pageTab{idx}" aria-controls="pagePanel{idx}" '
            f'aria-selected="{selected}" tabindex="{focus}" '
            f'aria-label="{_e(page.name)}, замечаний: {bad}" '
            f'data-page-tab="{idx}" onclick="showPage({idx})">{_e(page.name)}'
            f'<span class="tab-badge" aria-hidden="true">{bad}</span></button>'
        )
    return "".join(tabs)


def _page_worst(page) -> str:
    issues = [i for e in page.elements for i in e.issues] + list(page.filter_issues)
    if any(i.severity == "error" for i in issues):
        return "error"
    if any(i.severity == "warning" for i in issues):
        return "warning"
    if issues:
        return "info"
    return "ok"


def _element_box(el: ElementReport, page_index: int) -> str:
    m = el.metrics
    severity = m.worst if el.issues else "ok"
    checks = ",".join(sorted({i.check_id for i in el.issues}))
    corner = _sev_label(m.worst) if el.issues else "OK"
    # Geometry is bounded and re-formatted, so a model value like
    # "0;background:url(...)" can never become a second CSS declaration.
    style = (
        f"left:{_fmt(_number(el.x))}px;top:{_fmt(_number(el.y))}px;"
        f"width:{_fmt(_size(el.width, 0.0))}px;"
        f"height:{_fmt(_size(el.height, 0.0))}px;"
    )
    aria = f"{el.label}, {el.visual_type}, {_SEVERITY_ARIA.get(severity, 'есть замечания')}"
    body = mock_body(el.visual_type)
    if not el.fields and el.visual_type not in NON_DATA_TYPES:
        body += '<div class="el-empty">Нет данных для этого визуала</div>'
        aria += ", без данных"
    elif not el.fields:
        body += '<div class="el-empty">Статический элемент</div>'
        aria += ", статический элемент"
    return (
        f'<div class="el {severity}" data-el="1" data-page="{_e(el.page)}" '
        f'data-page-idx="{page_index}" '
        f'data-kind="{_e(el.visual_type)}" data-severity="{severity}" '
        f'data-checks="{_e(checks)}" data-key="{_e(el.key)}" style="{style}" '
        f'role="button" tabindex="0" aria-label="{_e(aria)}" '
        f'aria-haspopup="dialog" aria-controls="detailCard" '
        f'title="{_e(_tooltip(el))}">'
        f'<div class="el-chrome"><span class="el-title">{_e(el.label)}</span>'
        f'<span class="badge {severity}">{corner}</span></div>'
        f'<div class="el-body">{body}</div>'
        f"</div>"
    )


def _page_issue_list(page) -> str:
    """The page-level filter diagnostics, drawn above the canvas.

    Page filters are inspected by `web_inspect` but belong to no element, so
    without this list an unsafe `Condition.In` on `sections[].filters` would be
    counted and then rendered nowhere.
    """
    if not page.filter_issues:
        return ""
    items = "".join(
        f'<li data-severity="{_e(i.severity)}" data-check="{_e(i.check_id)}">'
        f'<span class="badge {_e(i.severity)}">{_sev_label(i.severity)}</span> '
        f"{_e(i.check_id)}: {_e(i.message)}</li>"
        for i in page.filter_issues
    )
    return f'<ul class="page-issues" aria-label="Замечания страницы">{items}</ul>'


def _page_panel(model: WebReportModel, idx: int) -> str:
    page = model.pages[idx]
    active = " active" if idx == 0 else ""
    notices = _page_issue_list(page)
    # The caption is emitted for **every** page, empty or not: on paper the tabs
    # are hidden and `.canvas-title` is the only thing that names the sheet, so an
    # empty page printed as a bare placeholder whose heading was the generic
    # "Страница без визуалов". With several empty pages the sheets were
    # indistinguishable.
    caption = f'<h2 class="canvas-title">{_e(page.name)}</h2>'
    if not page.elements:
        inner = (
            notices
            + caption
            + _empty_state(
                "Страница без визуалов",
                f"На странице «{page.name}» нет элементов: в отчёте нечего "
                "показывать. Добавьте визуалы в .pbix или проверьте Report/Layout.",
                " page-empty",
            )
        )
    else:
        w = _size(page.width, _DEFAULT_W)
        h = _size(page.height, _DEFAULT_H)
        scale = _print_scale(w, h, notices=_notice_lines(page))
        boxes = "".join(_element_box(el, idx) for el in page.elements)
        inner = (
            notices + caption + f'<div class="canvas" style="width:{_fmt(w)}px;'
            f'height:{_fmt(h)}px;--print-scale:{_scale_text(scale)}">'
            f"{boxes}</div>"
        )
    return (
        f'<section class="canvas-wrap{active}" id="pagePanel{idx}" role="tabpanel" '
        f'aria-labelledby="pageTab{idx}" data-page="{idx}">{inner}</section>'
    )


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
        f'<div class="stat-card {cls}" role="listitem"><div class="stat-value">{val}</div>'
        f'<div class="stat-label">{label}</div></div>'
        for cls, val, label in cards
    )


def _filter_options(model: WebReportModel) -> tuple[str, str, str]:
    pages = [(i, p.name) for i, p in enumerate(model.pages)]
    kinds = sorted({e.visual_type for e in model.elements})
    # Page-level filter findings are selectable too: they are rendered in
    # `.page-issues` and were otherwise impossible to isolate, leaving a filter
    # whose only value could not be shown as empty in the panel.
    checks = sorted(
        {i.check_id for e in model.elements for i in e.issues}
        | {i.check_id for p in model.pages for i in p.filter_issues}
    )
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
    """The metrics table rows, carrying the same filter keys as the elements.

    The table honoured only the severity filter, so isolating a page, a kind or
    a check left every row undimmed and the table contradicted the canvas it was
    supposed to describe.
    """
    rows = []
    for page_index, page in enumerate(model.pages):
        for el in page.elements:
            m = el.metrics
            severity = m.worst if el.issues else "ok"
            badge_text = _sev_label(m.worst) if el.issues else "OK"
            checks = ", ".join(sorted({i.check_id for i in el.issues})) or "—"
            keys = ",".join(sorted({i.check_id for i in el.issues}))
            rows.append(
                f'<tr data-detail="{_e(el.key)}" data-severity="{severity}" '
                f'data-page-idx="{page_index}" data-kind="{_e(el.visual_type)}" '
                f'data-checks="{_e(keys)}">'
                f"<td>{_e(el.page)}</td><td>{_e(el.label)}</td>"
                f"<td>{_e(el.visual_type)}</td><td>{m.fields}</td>"
                f"<td>{m.roles}</td><td>{m.colors}</td><td>{m.filters}</td>"
                f'<td class="num-error">{m.errors}</td>'
                f'<td class="num-warn">{m.warnings}</td>'
                f"<td>{_e(checks)}</td>"
                f'<td><span class="badge {severity}">{badge_text}</span></td></tr>'
            )
    return "".join(rows)


def _explorer(model: WebReportModel) -> str:
    """Tabs + layout, or an explicit empty state when there is nothing to draw."""
    if not model.pages:
        return _empty_state(
            "В отчёте нет визуалов",
            "Модель не содержит страниц с элементами: проверьте, что .pbix "
            "содержит Report/Layout с visualContainers. Отчёт не может быть "
            "показан пустым листом.",
        )
    tabs = (
        '<section aria-labelledby="pages-title">'
        '<h2 class="sr-only" id="pages-title">Страницы отчёта</h2>'
        f'<div class="page-tabs" id="pageTabs" role="tablist" '
        f'aria-label="Страницы отчёта">{_page_tabs(model)}</div>'
        f'<div class="layout-host" id="layoutHost">'
        f"{''.join(_page_panel(model, i) for i in range(len(model.pages)))}</div>"
        "</section>"
    )
    return tabs


def _details(model: WebReportModel) -> str:
    if not model.elements:
        return ""
    return (
        '<details class="section" id="detailsSection">'
        "<summary>Метрики и нарушения по элементам (таблица)</summary>"
        '<div class="table-scroll"><table class="data-table" id="metrics-table">'
        "<thead><tr><th>Страница</th><th>Элемент</th><th>Тип</th><th>Полей</th>"
        "<th>Ролей</th><th>Цветов</th><th>Фильтров</th><th>Ошибок</th>"
        f"<th>Предупр.</th><th>Проверки</th><th>Статус</th></tr></thead>"
        f"<tbody>{_detail_rows(model)}</tbody></table></div></details>"
    )


def _filters(model: WebReportModel) -> str:
    if not model.elements:
        return ""
    page_opts, kind_opts, check_opts = _filter_options(model)
    return f"""<div class="filter-scrim" id="filterScrim" aria-hidden="true"
  onclick="toggleFilterPanel(false)"></div>
<button type="button" class="filter-toggle" id="filterToggle"
  aria-controls="filterPanel" aria-expanded="false"
  aria-label="Открыть панель фильтров" onclick="toggleFilterPanel()">Фильтры</button>
<section class="filter-panel" id="filterPanel" role="region"
  aria-labelledby="filterTitle" aria-hidden="true" inert="">
  <div class="filter-header">
    <h2 id="filterTitle">Проблемные места</h2>
    <button type="button" class="btn-close" aria-label="Закрыть панель фильтров"
      onclick="toggleFilterPanel()">×</button>
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
    <button type="button" onclick="resetFilters()">Сбросить</button>
  </div>
  <div class="filter-group"><span id="filter-count" class="stat-label"
    aria-live="polite"></span></div>
</section>"""


def render_html(model: WebReportModel, title: str = "Dashboard Clone") -> str:
    """Render the report clone as an interactive layout."""
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
<main class="container">
  <header>
    <h1>{_e(title)}</h1>
    <p class="subtitle">Макет отчёта: {_e(model.source)} · наведите на элемент и
      включите фильтры, чтобы выделить проблемные места</p>
  </header>

  <section aria-labelledby="stats-title">
    <h2 class="sr-only" id="stats-title">Сводка</h2>
    <div class="stats-grid" role="list">{_summary_cards(model)}</div>
  </section>

  {_explorer(model)}
  {_details(model)}
</main>

{_filters(model)}

<footer class="footer">{_e(title)} · agentic_bi.web_report</footer>
<div id="detailCard" role="dialog" aria-modal="false" aria-labelledby="detailTitle"
  tabindex="-1">
  <div class="detail-head">
    <h2 id="detailTitle">Детали элемента</h2>
    <button type="button" class="btn-close" id="detailClose"
      aria-label="Закрыть детали элемента" onclick="hideDetails()">×</button>
  </div>
  <div id="detailBody"></div>
</div>
<div id="detailLive" class="sr-only" role="status" aria-live="polite"></div>

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
