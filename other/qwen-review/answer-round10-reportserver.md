## Assistant

### 1. Небезопасная работа с сетью/ответом
*   **`diagnostics.py:list_root_items`, `list_all_catalog`, `entity_summary`** и **`pbix_analysis.py:list_powerbi`**: Жестко задан лимит `$top: 1000` / `500` без обработки `@odata.nextLink`. 
    *   *Условие:* Если в каталоге Report Server >1000 элементов, API вернет только первую тысячу. 
    *   *Severity:* **Critical**. Инструмент аудита молча обрежет данные и выдаст «успешно, но не полностью», что делает диагностику ненадежной.
*   **`diagnostics.py:_get_json`**: При статусе != 200 или не-JSON теле (например, HTML-страница ошибки 500/403) возвращает `{}`. 
    *   *Условие:* Сбой сети или прав доступа.
    *   *Severity:* **Warning**. Ошибка сервера тихо превратится в «объектов не найдено» (пустой список). Для аудита лучше падать с явной ошибкой.
*   **`reportserver_client.py:NegotiateSession.__init__`** и **`automate.py:verify_published`**: Глобальное отключение проверок SSL (`verify=False`, `urllib3.disable_warnings`). 
    *   *Severity:* **Warning**. Риск MITM-атаки, если хост сервера подменен или скомпрометирован.

### 2. Пути и имена
*   **`automate.py:verify_published`**: Формирование `server_path` и вставка в OData-запрос `CatalogItems(Path='{server_path}')`. 
    *   *Условие:* Если `report_name` содержит одинарную кавычку `'` (например, `My'Report`), это сломает синтаксис OData (инъекция/падение запроса).
    *   *Severity:* **Warning**. Требуется экранирование кавычек (`''`) для OData.
*   **`pbix_analysis.py:run`**: Использование `item['Id'][:8]`. 
    *   *Условие:* Если сервер вернет элемент без поля `Id` (сбой схемы, специфичный тип), будет `KeyError`.
    *   *Severity:* **Warning**.
*   *Санитизация имен (`_sanitize`, `slug`)*: Работает корректно (заменяет `/`, `\` и спецсимволы), обхода каталога (path traversal) через имена из сервера нет. **Нет замечаний по безопасности путей**.

### 3. Детекторы антипаттернов
*   **`antipattern_detectors.py:analyze_calc_column`**: Регулярка `r"\b(?:YEAR|MONTH|QUARTER)\s*([?Date]?"`. 
    *   *Условие:* Незакрытая скобка `(` перед `[?Date]?`. 
    *   *Severity:* **Critical**. Вызовет `re.error: missing ), unterminated subpattern` в рантайме при анализе любой вычисляемой колонки не из техн. календаря.
*   **`antipattern_detectors.py:analyze_measure`**: Детектор `dax.calculate_no_filter` использует `re.search(r"CALCULATE\s*\(\s*[A-Za-z_\[\]\s'\.]+\s*\)", expr)`. 
    *   *Условие:* Символы `(` и `)` не входят в разрешенный класс символов. Выражение `CALCULATE(SUM([A]))` не сматчится.
    *   *Severity:* **Warning**. Ложноотрицательное срабатывание (пропуск антипаттерна).
*   **`antipattern_detectors.py:analyze_measure`**: Детектор `dax.hardcoded_value` ищет числа `"\d+"|\b\d{2,4}\b` рядом с `IF`/`SWITCH`. 
    *   *Условие:* Не игнорирует комментарии DAX (`//`, `/* */`) и строковые литералы.
    *   *Severity:* **Warning**. Ложноположительные срабатывания.
*   **`dax_detail.py:_extract_thresholds`**: `re.findall(r"([<>=]=?)\s*(\d+.\d+)", expr)`. 
    *   *Условие:* Точка в `\d+.\d+` означает «любой символ», а не literal dot. Сматчит `123a456`.
    *   *Severity:* **Warning**. Нужно `\d+\.\d+`.

### 4. Граница CLI и автоматизация
*   **`cli_support.py:run_boundary`**: Ловит `OSError, ValueError, NotImplementedError`. Остальное (например, `TypeError`, `KeyError`) пробрасывается как traceback, что соответствует документации («unexpected error is not swallowed»). **Нет замечаний**.
*   **`automate.py:verify_published`**: Использует `requests_negotiate_sspi`. 
    *   *Условие:* Если эта опциональная зависимость не установлена, будет `ImportError`, который не обрабатывается в `run()`.
    *   *Severity:* **Warning**. Пайплайн упадет на шаге верификации.
*   **`engine_cli.py:main`**: Возвращает `1`, если `result.get("verify") == "FAILED"`. 
    *   *Условие:* Нет явной гарантии, что `pipe.run` вернет именно такую строку при ошибке (может вернуть `False` или `None`).
    *   *Severity:* **Nit**.

### 5. Дефекты
*   **`antipattern_detectors.py:analyze_calc_column`**: Падение с `re.error` из-за синтаксиса regex (описано в п.3). **Critical**.
*   **`diagnostics.py`**: Отсутствие пагинации OData (описано в п.1). **Critical**.
*   **`pbix_index.py:_drill_rows`**: `lin.get("sources", {}).get("by_table", {}).items()`. 
    *   *Условие:* Если `sources` в JSON lineage окажется списком или `None`, вызов `.get("by_table")` бросит `AttributeError`.
    *   *Severity:* **Warning**.
*   **`reportserver_client.py:NegotiateSession.request`**: В цикле `for _ in range(4):` при `resp.status_code == 401` и отсутствии `WWW-Authenticate` или невалидном base64, код делает `return resp`. Но если `challenge.split(" ", 1)[1]` упадет с `IndexError`, оно перехватится `except Exception: return resp`. Это корректно, но `resp` может быть `None` в теории (хотя `requests` всегда возвращает Response). **Nit**.
