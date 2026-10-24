### 1. Валидация границы
*   **`spec.py:from_dict`** — `dash["name"]` вызывает `KeyError`, если ключ отсутствует. `validate_spec` проверяет отсутствие имени, но до неё код не дойдёт из-за падения на парсинге. **Severity: critical**
*   **`spec.py:from_dict`** — `dash.get("pages", [])` не проверяет тип. Если в YAML передано `pages: "string"`, итерация пройдёт по символам, и `_parse_page` упадёт с `AttributeError` (так как ожидает `dict`). **Severity: critical**
*   **`spec.py:_field_dict`** — если `el.field` (или `axis`/`value`) не является словарём (например, строка или `None`), вызов `f.get(...)` упадёт с `AttributeError`. `validate_spec` проверяет только факт наличия (`if not el.field`), но не тип. **Severity: warning**

### 2. Консистентность данных
*   **`engine_layout.py:build_layout_from_spec`** — ожидает структуру `spec["tables"][0]["name"]`, в то время как `spec.py` формирует `DashboardSpec` с полем `table` (строка) и `pages`. Это два несовместимых формата. Попытка скормить `DashboardSpec` (или его dict-представление) в эту функцию вызовет `KeyError: 'tables'`. **Severity: critical**
*   **`validate_pbix.py:validate_layout`** и **`web_checks.py:_field_issues` / `_projection_issues`** — предполагают, что `sv.get("prototypeQuery")` — это словарь. Однако в Power BI `prototypeQuery` часто хранится как JSON-строка. Если там строка, то `pq.get("From")` / `pq.get("Select")` вызовет `AttributeError: 'str' object has no attribute 'get'` (необходимо было применять `_as_obj` или `json.loads`, как это сделано для `vc.get("query")`). **Severity: critical**

### 3. Пороги
*   **`thresholds.py:resolve_thresholds`** — функция `validate_override` существует, но **нигде не вызывается** внутри `resolve_thresholds`. Если в спеке передать строку вместо числа (например, `quality.max_layout_problems: "0"`), порог тихо перезапишется строкой. При последующем сравнении `len(problems) > get_threshold(...)` будет `TypeError`. **Severity: warning**
*   **`thresholds.py:get_threshold`** — если передан несуществующий ключ (опечатка), возвращается `None`. Если вызывающий код делает `if value > threshold:`, будет `TypeError`. **Severity: warning**
*   **`thresholds.py:_quality_thresholds`** — `quality.min_visuals_per_section` по умолчанию `0`. Это позволяет публиковать пустые страницы без предупреждения (fail-open), хотя логичнее требовать хотя бы один визуал или явно предупреждать. **Severity: nit**

### 4. Web-checks
*   **`web_checks.py:element_issues`** — если `registry is None` (например, не установлен `pbixray` или реестр не передан), проверка `_field_issues` (model-membership) **полностью пропускается** без генерации какого-либо `Issue` (предупреждения) о том, что модель не проверена. В `web_inspect.py` это лишь добавляет флаг `fields_checked=False`, но в итоговом отчёте нет явного предупреждения "model checks skipped due to missing registry". **Severity: warning**

### 5. Дефекты
1.  **`spec.py:from_dict`**: Падение с `KeyError` / `AttributeError` на границе ввода вместо возврата структурированной ошибки валидации. **Severity: critical**
2.  **`validate_pbix.py:validate_layout`** и **`web_checks.py`**: Падение с `AttributeError`, если `prototypeQuery` пришёл в виде строки, а не dict. **Severity: critical**
3.  **`engine_layout.py:build_layout_from_spec`**: Ожидает `spec["tables"]`, что несовместимо с `DashboardSpec` из `spec.py` (ошибка `KeyError`). **Severity: critical**
4.  **`thresholds.py:resolve_thresholds`**: Отсутствие вызова `validate_override` позволяет передать строку вместо числа, что сломает сравнение порогов на этапе quality gate. **Severity: warning**
