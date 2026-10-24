# Ревью: lineage-анализ и генерация отчётов (JSON / PlantUML / PDF)

Ты — независимый ревьюер Python-кода. К промпту приложены **файлы** (3 бандла).

ВАЖНО: чат принимает не более ~5 вложений, поэтому код собран в 3 бандла — это
markdown, где секции разделены строкой
`==================== FILE: <путь> ====================`. Читай код из бандлов:
- `round9-code-1-lineage-core.md` — `lineage/lineage_types.py`,
  `lineage_model.py`, `lineage_query.py`, `lineage_origins.py`,
  `lineage_origins_data.py`, `pbi_lineage.py`
- `round9-code-2-lineage-output.md` — `lineage_sources.py`,
  `lineage_export.py`, `lineage_export_data.py`, `lineage_plantuml.py`,
  `lineage_plantuml_render.py`, `lineage_brand.py`, `lineage_brand_metrics.py`,
  `lineage_brand_report.py`
- `round9-code-3-report.md` — `report/__init__.py`, `lineage_matrix.py`,
  `lineage_table.py`, `lineage_brand_cols.py`, `pdf_report.py`, `pdf_tables.py`,
  `pdf_diagram.py`, `plantuml_tools.py`

## Что за код

Пакет `agentic_bi` (stdlib-only ядро). Здесь — подсистема **трассировки
происхождения данных (lineage)** и **отчёты по ней**:

1. **Модель lineage** (`lineage_model.py`, `lineage_types.py`): читает
   `Report/Layout` из `.pbix`, строит связи таблица→поле→визуал/страница,
   источники и вычисляемые объекты. `lineage_query.py` — разбор queryRef/DAX,
   `lineage_origins*.py` — происхождение столбцов (источники, выражения).
2. **Вывод** (`lineage_export*.py`, `lineage_sources.py`): сборка JSON-модели
   для отчёта и диаграмм. `lineage_plantuml*.py` — генерация PlantUML
   (экранирование!). `lineage_brand*.py` — метрики соответствия бренду.
3. **Отчёты** (`report/`): `lineage_matrix.py` / `lineage_table.py` — таблицы,
   `pdf_report.py` / `pdf_tables.py` / `pdf_diagram.py` — PDF (reportlab),
   `plantuml_tools.py` — рендер диаграммы в картинку.

Контекст: вход — **недоверенный** `Report/Layout` (имена таблиц/полей/визуалов
из чужого `.pbix`). Эти имена попадают в JSON, в текст PlantUML и в PDF.
Отчёт по lineage влияет на решения о том, что где используется.

## Что вернуть

1. **Внедрение в вывод.** Может ли недоверенное имя (таблица/поле/визуал/
   заголовок) сломать или подделать вывод: PlantUML (кавычки, `@startuml`,
   перевод строки, `"`), JSON (экранирование), PDF/reportlab (разметка,
   незакрытые теги, XML-escape)? Файл:функция + условие.
2. **Устойчивость к неожиданному layout.** Где отсутствие ключа/`None`/не-dict
   приведёт к `KeyError`/`AttributeError`/`TypeError` вместо пропуска?
   Особенно парсинг queryRef/DAX (`lineage_query.py`, `lineage_model.py`).
3. **Логика связей.** Может ли lineage молча дать неполный или неверный граф:
   потерянная связь, таблица без полей, дубликат узла, регистр имён, агрегаты
   (`Sum(T.c)`), вычисляемые столбцы? Файл:функция + условие.
4. **Отчёты.** Есть ли деление на ноль, пустой DataFrame/таблица, чрезмерная
   память при большом числе страниц/связей, потеря данных при экспорте?
5. **Дефекты.** Только высокоуверенные: что реально сломается или соврёт.
   Границы: пустой layout, один визуал, имя с юникодом/кавычками, 0 связей.

По каждому — файл:функция, условие, severity (critical/warning/nit). Если по
пункту нет замечаний — «нет замечаний». Не пересказывай код.
