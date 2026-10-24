## Assistant

### 1. Fail-open в вердикте
- **`brand_audit_extract.py:color_hex` / `_paint_observations` / `_textframe_observations`**: Любое исключение при извлечении цвета/шрифта (например, неподдерживаемый тип заливки, отсутствующий атрибут) перехватывается и проглатывается (`logger.debug`), возвращая пустые данные. Элемент тихо пропускается в оценке, что ведет к ложному «OK» для него. (critical)
- **`brand_audit_eval.py:_eval_colors`**: Условие `if not h ... return`. Если у фигуры есть заливка, но `color_hex` не смог её извлечь (градиент, паттерн, специфичная тема), нарушение не фиксируется. (warning)
- **`brand_audit_eval.py:_eval_contrast`**: Условие `bg_default = backgrounds[0][0] if backgrounds else "#ffffff"`. Если фон не обнаружен (например, фон слайда — картинка или градиент), по умолчанию берется белый. Это приводит к ложно-отрицательным срабатываниям: если реальный фон темный, а текст светлый, контраст низкий, но мы сравниваем с белым и пропускаем нарушение. (warning)
- **`engine_verify_checks.py:verify_model_data`**: Если `pbixray` не установлен, возвращается soft-failure (`critical=False`). Сборка может пройти, даже если данные модели не проверены. (warning — заложено в дизайн, но снижает надежность гейта).

### 2. Разбор цвета/шрифта
- **`brand_audit_math.py:luminance`**: Падает с `ValueError`, если `hex_color` невалиден (например, `""` или `"rgb(...)"`). `normalize_hex` вернет `""`, затем `int(h[1:3], 16)` упадет. Это уронит весь аудит, если до проверки контраста доберется некорректный цвет. (critical)
- **`brand_config.py:normalize_hex`**: Для 8-значного hex предполагает ARGB и отрезает первые 2 символа (`v = v[2:]`). Если источник отдает RGBA, отрежется не то. Также не обрабатывается 4-значный short ARGB. (nit)
- **`brand_audit_extract.py:color_hex`**: Обрабатывает только `RGB` и `SCHEME`. Если `color_format.type` — `PATTERN`, `GRADIENT` или `PICTURE`, возвращается `"", False`, и заливка/линия тихо игнорируются. (warning)
- **`brand_audit_math.py:font_weight`**: Ключевые слова включают `"extrabold"`, `"semibold"`. Если имя шрифта `"Brand Sans Extra Bold"` (с пробелами), оно не совпадет с `"extrabold"`, но совпадет с `"bold"`. Вес будет определен неверно. (nit)

### 3. Правила и пороги
- **`brand_audit_eval.py:_eval_document_rules`**: Условие `min_primary = int(cfg.rules.get("primary_color_min", 2))`. Если в конфиге явно указано `0`, проверка тихо отключается (`if extended and min_primary and ...`). Это позволяет скрыть нарушение, но может быть и осознанной фичей. (nit)
- **`brand_rules.py` / `brand_config.py`**: Если `cfg.colors_primary` пуст (ошибка конфига), `accent_hex` по умолчанию становится `"#d32f2f"`. Аудит честно упадет с ошибкой "mandatory accent not found", но сообщение может быть непонятным, если конфиг просто не загрузился. (nit)

### 4. Сверка verify
- **`engine_verify_core.py:load_layout`** и **`engine_verify_brand.py:extract_report_theme`**: Жестко закодирована декодировка `Report/Layout` как `utf-16-le`. При этом `rebuild.py` корректно определяет и UTF-16LE, и UTF-8. Если `.pbix` имеет UTF-8 layout (например, от другого инструмента или после ручного редактирования), `verify_pbix` упадет с `UnicodeDecodeError` или `JSONDecodeError`. (critical)
- **`engine_verify_checks.py:verify_layout`**: Условие `out.append(_check("all visuals have projections", not no_proj, ...))`. Если визуал — декоративная фигура (прямоугольник, картинка, линия) без привязки к данным, у него нет `projections`. Проверка упадет. Декоративные элементы должны иметь право не иметь проекций. (critical)
- **`engine_verify_checks.py:verify_bindings`**: Сравнение имен таблиц и колонок регистрозависимо (`table not in known_tables`). В Power BI модель часто регистронезависима в DAX, но в JSON layout регистр может сохраняться. Если в спеке `"Sales"`, а в layout `"sales"`, будет false-positive. (warning)

### 5. Дефекты
- **`brand_audit_math.py:luminance`**: Падение на невалидном hex (см. п.2). (critical)
- **`engine_verify_core.py:load_layout` / `engine_verify_brand.py:extract_report_theme`**: Падение на UTF-8 layout из-за жесткой привязки к `utf-16-le` (см. п.4). (critical)
- **`engine_verify_checks.py:verify_layout`**: Ложное срабатывание (fail-closed) на декоративных фигурах без `projections` (см. п.4). (critical)
- **`brand_audit_extract.py:color_hex`**: Тихий пропуск градиентов/паттернов, ведущий к fail-open (см. п.2). (warning)
- **`brand_audit_eval.py:_eval_contrast`**: Неверный дефолт фона (`#ffffff`) при отсутствии данных, ведущий к ложно-отрицательным срабатываниям (см. п.1). (warning)
