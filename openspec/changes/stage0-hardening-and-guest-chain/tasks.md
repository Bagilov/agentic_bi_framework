# Tasks: stage0-hardening-and-guest-chain

> Привязка к BR из `proposal.md` (BR-1..BR-7). Отмечено фактическое состояние.

## 1. Подготовка

- [x] 1.1 Ревью с Qwen (4 раунда), находки воспроизведены на pre-fix коде
      (`other/qwen-review/`, `docs/REVIEW_DECISIONS.md`)
- [x] 1.2 Харнесс доказательства в реальном браузере и на реальном `.pbix`
      (`other/e2e-verification/`)
- [x] 1.3 План этапов 0–4 с критериями готовности (`docs/IMPROVEMENT_PLAN.md`)

## 2. Web-report — устранение исполнения данных как кода (BR-1)

- [x] 2.1 `_json_for_script`: экранирование `<`/`>`/`&` на стоке сериализации
      (`web_report/web_render.py`)
- [x] 2.2 Убрать JS-in-HTML: `data-key` + `addEventListener`, `escapeHtml` в
      клиенте (`web_report/web_render.py`, `web_report/web_assets.py`)
- [x] 2.3 Регрессионные тесты, падающие на pre-fix коде
      (`tests/test_web_report_injection.py`, 6)

## 3. Бинарный слой — читаемость записи (BR-2, BR-3)

- [x] 3.1 `serialize_virtual_directory` через `ElementTree` (байт-идентично
      нормальным путям) (`pbix_binary/abf_model.py`)
- [x] 3.2 Обязательная self-verification вывода `apply_patches`
      (`pbix_binary/patch_pipeline.py`)
- [x] 3.3 Неоднозначность — ошибка; `occurrence` (0-based) / `"all"`; ленивый
      непересекающийся скан (`pbix_binary/patch_pipeline.py`)
- [x] 3.4 Документировать `occurrence` в `patch_cli` и `docs/IMPLEMENTATION.md`
- [x] 3.5 Регрессионные тесты (`tests/test_pbix_binary_hardening.py`, 11)

## 4. Guest-цепочка — одна ограниченная команда (BR-4, BR-5, BR-6)

- [x] 4.1 Модули: `guest_types`, `guest_vm`, `guest_winrm`, `guest_staging`,
      `guest_task`, `guest_transport`
- [x] 4.2 Оркестратор `guest_chain` + staged-build `guest_chain_build` + CLI
      `guest_chain_cli`
- [x] 4.3 Один `Deadline`, teardown в `finally`, VM-стоп только если подняла цепочка
- [x] 4.4 Стейдж-сервер: один файл, одноразовый токен, 404 на прочее, SHA-256
      (`guest_staging.py`)
- [x] 4.5 `ps_quote` во всех PowerShell-точках (`guest_types`, `guest_task`,
      `guest_staging`, `guest_winrm`, `guest_chain_build`, `desktop_oracle_guest.py`)
- [x] 4.6 `_pth`/src из конфига, не хардкод (`guest_chain_build.py`)
- [x] 4.7 Маркер-файл `EXITCODE=` из единой константы (`guest_task.py`)
- [x] 4.8 Порт движка: `run_engine_build(port=…)` + `-Port` в `_engine_build.ps1`
- [x] 4.9 Extra `guest = ["pywinrm>=0.5"]` в `pyproject.toml` (+ `all`)
- [x] 4.10 Офлайн-тесты (`tests/test_guest_chain.py`)
- [x] 4.11 Документация (`docs/DEVELOPMENT_MACOS.md`, `docs/AGENT_PLAYBOOK.md`,
      `docs/IMPLEMENTATION.md`, `README.md`)
- [x] 4.12 Раунд 5: fail-closed SHA-256 при пустом хеше
      (`guest_staging.push_file`); `StageError` на ненулевой exit
      (`guest_winrm.run_ps`); `--json`-вердикт без стектрейса
      (`guest_chain_cli._emit`) + регрессионные тесты

## 5. Контракты границ (BR-7)

- [x] 5.1 Находки раунда 4 зафиксированы: CLI отдают стектрейсы вместо кодов;
      `lineage.main()` без контракта; код `2` перегружен; `from_manifest`
      принимает любой `stage`; мёртвый `path` в `render_kilo_agent`
      (`other/qwen-review/round4-findings.md`)
- [x] 5.2 CLI: общий boundary-handler `cli_support.run_boundary` (0 успех / 1
      runtime / 2 плохой вход); применён к `visual-check`, `brand-audit`,
      `engine`, `test-build`, `lineage`, `antipatterns`, `report`, `pbix-patch`;
      `lineage.main()`/`pdf_report.main()` получили возврат кода
- [x] 5.3 `agents.from_manifest`: валидация `stage`; `all_agents` отвергает
      неизвестный этап; убран мёртвый `path` из `render_kilo_agent`
- [x] 5.4 U-4: дефолтные выходы больше не пишутся внутрь пакета
      (`lineage/pbi_lineage.py`, `antipatterns/pbi_antipatterns.py` — CWD-relative
      `output_files/`)
- [x] 5.5 Тесты: `tests/test_agents.py` (G-1/G-3), `tests/test_cli_boundary.py`
      (коды границ + дефолтные пути)
- [x] 5.6 Раунд 6: `pbix-patch` обёрнут в `run_boundary` (битый JSON спеки → 2, а
      не трассировка); `test-build` отдаёт `ValueError` вместо `SystemExit` на
      ошибке конфигурации

## 5b. Декларативный spec-путь (раунд 7)

Область: `spec.py` → `engine_layout*.py`, `validate_pbix.py`, `thresholds.py`,
`web_report/`. Обмен с Qwen завершён (промпт/ответ `prompt-round7-spec-path.md`,
`answer-round7-spec-path.md`, бандлы `round7-code-{1,2,3}-*.md`); все находки
воспроизведены до фикса.

- [x] 5b.1 `spec.py`: границы недоверенного ввода — `from_dict` без `name` не
      падает; `_field_dict` без `property` даёт сообщение, а не `KeyError`;
      не-dict элемент/поле и не-list `elements` отвергаются
- [x] 5b.2 `validate_spec`: дубликаты имён страниц, `pos` (4 int), неизвестный
      `kind`, отсутствующий `property`
- [x] 5b.3 `engine_layout.build_report([])` → `ValueError` вместо `IndexError`;
      `build_gallery({'tables': []})` → `ValueError`
- [x] 5b.4 `thresholds`: вложенная форма `quality.thresholds` /
      `deploy.guardrails` разворачивается (раньше молча игнорировалась —
      fail-open на жестком гейте); неверный тип откатывается к дефолту с логом;
      неизвестный ключ — warning; `bool` отвергается для `int`-порога;
      `get_threshold` с опечаткой логирует
- [x] 5b.5 `validate_pbix`: пустой реестр `{}` больше не подменяется
      `EXAMPLE_REGISTRY` (только `None`); `prototypeQuery` строкой парсится
- [x] 5b.6 `web_report`: `has_in_filter` и координаты `web_inspect` устойчивы к
      не-dict фильтру и нечисловой координате; `prototypeQuery` строкой не
      роняет `web_checks`; пропуск model-membership без реестра даёт warning
- [x] 5b.7 Тесты: `tests/test_spec_path.py` (22) + warning-тест web-cli

## 5c. Раунды 8–11: аудит новых областей (с Qwen, кроме блокировки в 11)

Каждый раунд — область, не покрытая ранее; каждая находка воспроизводилась до
фикса; ложные находки Qwen фиксировались как опровергнутые
(`other/qwen-review/README.md`, `docs/REVIEW_DECISIONS.md`).

- [x] 5c.1 Раунд 8 — гейт публикации (`brand_audit*`, `engine_verify*`,
      `rebuild`): `luminance` на не-hex не падает; layout декодируется по
      энкодингу (UTF-16/UTF-8); декоративные визуалы не требуют проекций;
      `singleVisualGroup`/контейнер без `config` пропускаются; неизвестный фон
      не подменяется белым; градиентная заливка → `PAINT-UNRESOLVED`;
      `font_weight` с пробелами; `verify_bindings` без учёта регистра
- [x] 5c.2 Раунд 9 — lineage и отчёты: агрегированный queryRef
      (`Sum(T.c)`) сохраняет таблицу (14/168 → 1 на доноре); не-строковый
      queryRef не падает; `_pu_escape` экранирует двойную кавычку; имена
      таблиц сопоставляются без регистра
- [x] 5c.3 Раунд 10 — Report Server и антипаттерны: обход OData следует
      `@odata.nextLink` (`reportserver/odata.py`); корректный детектор
      `CALCULATE` без фильтра (скан по балансу скобок); OData-литералы
      экранируются; `KeyError` на неполном элементе и молчаливый пустой
      ответ исключены; CLI-контракт `verify`
- [x] 5c.4 Раунд 11 — board/skeleton/агенты: детерминированные имена
      (`hash()` → SHA-1); валидный/отсутствующий `OrderBy` в `card_visual`;
      `odata_quote` во всех `$filter`; доменная ошибка вместо `KeyError`;
      `Visual` требует обязательные входы; DAX-литерал заголовка экранируется;
      `validate_spec` проверяет `visual_type` и строковые фильтры;
      неположительные размеры клампятся
- [x] 5c.5 Тесты раундов 8–11: `test_gate_robustness.py` (26),
      `test_lineage_report_robustness.py` (10),
      `test_reportserver_robustness.py` (17),
      `test_board_skeleton_robustness.py` (13),
      `test_board_spec_validation.py` (21)

## 6. Приёмка

- [x] 6.1 `ruff check .` и `ruff format --check .` — чисто
- [x] 6.2 `python -m pytest` и `pytest -q` — 299 passed, 2 skipped
- [x] 6.3 Сквозная проверка в реальном браузере: pre-fix исполняет, post-fix нет
- [x] 6.4 Сквозная проверка `.pbix`: pre-fix пишет битый, post-fix парсится
- [x] 6.5 Cold-start guest-цепочка: `BUILT` + `MODEL_LOADED`, exit 0, VM
      остановлена цепочкой
- [ ] 6.6 CI (этап 1 плана) — не начат
- [x] 6.7 Локальное ревью незакоммиченного кода: 6 находок закрыто, живой прогон
      после фиксов повторён
