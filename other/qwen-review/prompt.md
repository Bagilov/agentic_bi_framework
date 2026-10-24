# Ревью Python-репозитория agentic_bi_framework и план улучшений

Ты — независимый senior-ревьюер. Ниже измеренное состояние репозитория. Дай
критику (что важно, что шум), архитектурную оценку и приоритизированный план
улучшений по этапам (цель → шаги → критерий готовности → трудоёмкость).

## Проект
Self-contained framework для агентной работы с Power BI `.pbix`: сборка отчётов
(донорский бинарный `DataModel` + генерация `Report/Layout`), валидация,
бренд-аудит `.pptx`, lineage/DAX-извлечение, публикация на Power BI Report
Server, бинарное ABF-редактирование, HTML-клон дашбордов, PDF lineage-отчёт.
Заявлено: ядро — только stdlib, интеграции — optional extras.
Опубликован: `agentic-bi-framework 0.0.1b1` (github Bagilov/agentic_bi_framework).

## Факты (HEAD, 2026-10-21)
- 17 413 строк Python в `src/agentic_bi/`, 93 модуля, 6 подпакетов
  (pbix_binary, web_report, lineage, report, reportserver, antipatterns).
- Плоский `src/agentic_bi/`: 12 `engine*.py`, 10 `brand*.py`, 4 `skeleton*.py`.
- ruff 0.17: `check` — чисто, `format --check` — чисто (116 файлов).
- **Нет CI** (.github отсутствует), нет pre-commit-конфига, нет CHANGELOG,
  нет `py.typed`, нет тайп-чекера (mypy/pyright), нет конфига coverage.
- tests/: 10 модулей + conftest, 98 тестов. `.venv/bin/python -m pytest -q` →
  88 passed, 2 skipped. Но `.venv/bin/pytest -q` → **2 ошибки сбора**:
  два тест-модуля делают `from tests.web_report_fixtures import ...`, а `tests/`
  не пакет. Итог: результат зависит от способа запуска.
- Из 93 модулей 67 не упоминаются в тестах по имени (в т.ч. `validate_pbix`,
  `rebuild`, `skeleton*`, `brand_*`, `automate`, `thresholds`, `agents`, весь
  `lineage/`). Реального coverage-отчёта нет.
- 9 файлов >300 строк без обоснования исключения: board 361,
  reportserver/pbix_analysis 331, brand_audit_eval 328,
  lineage/lineage_brand_metrics 327, skeleton_visuals 317, brand_eval 314,
  automate 312, skeleton_assembly 310, dax_detail 301.
- 23 × `# noqa: F401` — модули-фасады с реэкспортом, без `__all__`, без
  `py.typed` (публичный контракт не выражен).
- 36 × `except Exception` (~20 с `noqa: BLE001`), часть без комментария.
- 5 × `: Any`, 10 × `# type: ignore` (ленивые опциональные импорты).
- `winrm` (pywinrm) импортируется в `desktop_oracle_guest.py`, но **не объявлен
  ни в одном extra**.
- Дефолтные имена донорских объектов (`fact_table`, `kpi_measures`) зашиты как
  значения по умолчанию в `board.py`, `automate.py`, `spec.py`,
  `validate_pbix.py`, `board_fake.py` — при заявленной агентостичности.
- Отладочный инструментарий внутри пакета: `board_fake.py`, `_engine_oracle.py`,
  `desktop_oracle_guest.py`, `test_build.py` (последний — console_script).
- `scripts/test_build.py` — 23 строки (ниже собственного минимума 25).
- Windows-only часть: AS engine `msmdsrv.exe`, PowerShell, WinRM session 0 →
  scheduled task Interactive; на macOS нужен готовый `.abf` или Windows VM.

## Вопросы
1. Что из этого реально важно, а что шум? Отдельно — риск «pytest красный,
   python -m pytest зелёный».
2. Архитектура: дробить ли плоский пакет на подпакеты (engine/, brand/,
   skeleton/)? Как относиться к фасадам-реэкспортам?
3. План улучшений: 3–5 этапов с целью, шагами, критерием готовности и
   трудоёмкостью. Что даёт максимум за минимум (CI + фикс импорта тестов +
   coverage)?
4. Чего не хватает как библиотеке: `py.typed`, `__all__`, тайп-чекер,
   проверка extras, публикация в PyPI.
5. Что делать с дефолтами `fact_table`/`kpi_measures` и отладочными модулями
   внутри пакета?
