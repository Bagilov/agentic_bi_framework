## Assistant

### 1. Корректность layout
- **`src/agentic_bi/engine_layout_visual.py:_visual_config`**
  **Условие:** Для визуалов `card`, `gauge`, `kpi`, `scatter` не заданы обязательные поля (например, `v.measure` и `v.value` оба `None`, или для `scatter` `v.x` и `v.value` равны `None`).
  **Последствие:** Вызов `add_agg(None)` сформирует невалидный `queryRef` вида `"Sum(table.None)"`. Power BI не сможет забиндить данные, визуал откроется пустым или с ошибкой парсинга.
  **Severity:** Critical

- **`src/agentic_bi/engine_layout_visual.py:_visual_config`**
  **Условие:** `v.kind == "table"`, но `v.columns` — пустой список.
  **Последствие:** `projections["Values"]` будет пустым. Power BI требует хотя бы одну колонку для рендера таблицы, иначе визуал будет битым.
  **Severity:** Warning

### 2. Границы спеки
- **`src/agentic_bi/spec.py:validate_spec` / `_parse_element`**
  **Условие:** В спеке указан несуществующий `visual_type` (например, `"myCustomChart"`).
  **Последствие:** Валидация пропускает это значение. Оно уйдёт в `singleVisual.visualType`, что приведёт к ошибке рендера в Power BI (неизвестный тип визуала).
  **Severity:** Warning

- **`src/agentic_bi/spec.py:validate_spec`**
  **Условие:** `PageSpec.filters` содержит нестроковые элементы (например, `None`, `int`, `dict`).
  **Последствие:** Проверка отсутствует. В `spec_to_board` -> `PageView.filters` -> `_page_filter` это вызовет `TypeError` при хешировании или сгенерирует невалидный JSON/DAX при формировании имени фильтра.
  **Severity:** Warning

### 3. Экранирование имён
- **`src/agentic_bi/engine_layout_visual.py:_visual_config`**
  **Условие:** `v.title` содержит одинарную кавычку (например, `"Sales '23"`).
  **Последствие:** Формирование DAX-литерала `f"'{v.title}'"` не экранирует кавычки (должно быть `''`). Это ломает DAX-выражение в `objects.title`, вызывая синтаксическую ошибку при открытии отчёта.
  **Severity:** Critical

- **`src/agentic_bi/engine_layout_query.py:_col_item` / `_agg_item`**
  **Условие:** Имя таблицы или колонки содержит пробелы или спецсимволы.
  **Последствие:** `queryRef` формируется как `f"{table}.{name}"` без экранирования. Power BI QOM требует специфичного формата (например, `'table name'[column]`) для имён с пробелами, иначе привязка данных сломается.
  **Severity:** Warning

### 4. Скелет и сборка
- **`src/agentic_bi/board.py:PageView._add` / `_Cursor.next`**
  **Условие:** `self.width < 40` или `canvas_w < 2 * self.x0`.
  **Последствие:** Вычисление `item_w` и `col_w` уходит в минус. Отрицательные `width`/`height` записываются в layout JSON, что может привести к краху рендерера Power BI или некорректному отображению.
  **Severity:** Warning

- **`src/agentic_bi/board_fake.py:build_and_publish`**
  **Условие:** Всегда.
  **Последствие:** Скрипт вручную собирает аргументы для `build_skeleton`, полностью игнорируя `DashboardSpec` и `Board`. Это создаёт расхождение: "интеграционный" пример не проверяет декларативный пайплайн, ради которого написаны `spec.py` и `board.py`.
  **Severity:** Nit

### 5. Дефекты
- **`src/agentic_bi/skeleton_visuals.py:_query_item`**
  **Условие:** Прямой вызов функции (минуя `spec.py`) с объектом `pq_query`, в котором отсутствует ключ `property`.
  **Последствие:** `prop = pq_query["property"]` вызовет `KeyError`. Хотя `spec.py` валидирует вход, прямой API `skeleton_visuals` не защищён от падений.
  **Severity:** Warning

- **`src/agentic_bi/engine_layout_visual.py:Visual.__post_init__`**
  **Условие:** `self.kind` валидируется по `_VISUAL_TYPES`, но не проверяется наличие обязательных полей для конкретного `kind` (например, `axis` для `line` или `columns` для `matrix`).
  **Последствие:** Пустые `projections` или `queryRef` с `None`, что ведёт к пункту 1 (битый layout). Валидация должна быть на этапе создания `Visual`.
  **Severity:** Critical
