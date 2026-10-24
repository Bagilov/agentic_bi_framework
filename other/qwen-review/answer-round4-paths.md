# Agentic BI Framework Code Review

- Chat: `07a5187f-2849-44f0-b86c-6bf902c9a578`

## User

# Ревью: сервисы agentic_bi_framework — пользовательский и агентский пути

Ты — независимый ревьюер. Ниже два пользовательских пути одного Python-пакета
(`agentic_bi`, stdlib-only ядро, опциональные extras). Нужен **разбор по каждому
сервису**: что сломается у реального пользователя/агента, где контракт соврёт.

## Легенда достоверности
- Всё ниже — **измерено** на живом коде (я гонял команды и записал фактический
  exit code и последнюю строку вывода). Это не догадки.
- Ревью — вход, не приказ: если мой факт противоречит твоему убеждению, верь
  факту, но скажи, что именно не сходится.

---

## Путь A. Пользовательский: 11 CLI-точек входа

Все ставятся как консольные скрипты из `[project.scripts]`:

| Команда | Модуль | Назначение |
|---|---|---|
| `agentic-bi-engine` | `engine_cli.py` | сборка `.pbix` через AS-движок Desktop |
| `agentic-bi-test-build` | `test_build.py` | self-test: сборка+валидация+JSON-отчёт |
| `agentic-bi-visual-check` | `visual_check.py` | статическая проверка `Report/Layout` |
| `agentic-bi-brand-audit` | `brand_audit.py` | аудит бренда `.pptx`/`.docx`/`.xlsx` |
| `agentic-bi-lineage` | `lineage/pbi_lineage.py` | родословная данных `.pbix` -> JSON/xlsx/md |
| `agentic-bi-antipatterns` | `antipatterns/pbi_antipatterns.py` | антипаттерны DAX/M |
| `agentic-bi-server` | `reportserver/diagnostics.py` | диагностика Report Server |
| `agentic-bi-report` | `report/pdf_report.py` | PDF-отчёт по родословной |
| `agentic-bi-pbix-patch` | `pbix_binary/patch_cli.py` | байтовые патчи `.pbix` |
| `agentic-bi-web-clone` | `web_report/web_cli.py` | HTML-клон дашборда |
| `agentic-bi-guest-dashboard` | `guest_chain_cli.py` | сборка дашборда в Windows-VM |

### A1. Заявленные exit-коды в docstring vs фактические

Docstrings обещают конкретные коды. Вот **фактические** прогоны на нечитаемом
входе (`/nonexistent.*`):

```
visual-check   /nonexistent.pbix /nonexistent.json   exit=1  FileNotFoundError: '/nonexistent.json'
web-clone      --pbix /nonexistent.pbix --out x.html exit=2  error: [Errno 2] No such file... '.pbix'
pbix-patch     members --pbix /nonexistent.pbix      exit=1  FileNotFoundError: '/nonexistent.pbix'
brand-audit    templates/template.pbix               exit=1  NotImplementedError: format '.pbix' is not supported yet
lineage        /nonexistent.pbix                     exit=1  FileNotFoundError: File not found: /nonexistent.pbix
antipatterns   /nonexistent.pbix                     exit=1  Input not found: /nonexistent.pbix
report         /nonexistent.json                     exit=1  FileNotFoundError: [Errno 2] ...
```

Для `visual-check` и `pbix-patch` последняя строка — **полный traceback**
(`FileNotFoundError` не перехвачен), хотя docstring `patch_cli` декларирует
«Exit codes: 0 on success, 2 on a patch error». То есть нечитаемый вход даёт
необработанный стектрейс и код 1, а не заявленный 2.

`brand-audit` на неподдерживаемом формате (`.pbix`) кидает `NotImplementedError` —
тоже стектрейс и код 1.

`web-clone` единственный, кто ловит и печатает `error: ...` с кодом 2 (так и
заявлено в его docstring).

### A2. Несогласованность кодов между сервисами

- `0/1` (булев «ок»): visual-check, brand-audit, lineage, antipatterns, report, engine, test-build
- `0/1/2` (есть отдельный «ошибка входа/спеки»): web-clone, pbix-patch, guest-dashboard
- `argparse`-ошибка (нет аргументов) = 2 у всех — это совпадает с «ошибкой входа», т.е. 2 перегружен (и «плохой CLI-вызов», и «плохой вход»/«плохая спека»).

Скрипт, который вызывает эти сервисы из пайплайна, не может отличить
«данные плохие» от «вызов неправильный» одинаковым кодом 2.

### A3. `lineage` не возвращает код и не обрабатывает ошибки

`pbi_lineage.main()` не имеет `return`: успех = неявный `None` -> код 0; на
нечитаемом `.pbix` — исключение -> код 1. Docstring/README обещают «build→test→
deploy→control→support», но у модуля нет контракта exit-кодов вообще.

### A4. `--out-dir` по умолчанию пишет внутрь пакета

`lineage`: `out_dir = Path(__file__).resolve().parent / "output_files" / "pbi_lineage"`.
`antipatterns`: `output_files/<stem>_antipatterns.json` **рядом с модулем**
(`Path(__file__).resolve().parent`). В read-only site-packages это `PermissionError`
вместо понятной ошибки. (Это уже известно из прошлых раундов — не переотчитывай как новое,
но скажи, если видишь иное.)

### A5. Что проверяем в первую очередь у пользовательского пути

1. Контракт exit-кодов: единая схема или нет; где стектрейс вместо кода.
2. Валидация входа на границе: `.pbix`/`.json`/`.pptx` — проверяется ли до работы.
3. Идемпотентность/перезапись выходов (где имя дефолтного вывода может затирать).
4. Ошибки инфраструктуры (нет `python-pptx`, нет Java для PlantUML) — это код
   ошибки или тихий пропуск?

---

## Путь B. Агентский: `agents.py` + spec-секция `support`

Концепт: у каждого этапа жизненного цикла (develop/test/deploy/control/support)
есть «support-агент» — манифест (JSON/YAML), который можно:
- положить в декларативную спеку дашборда в `support.agents`;
- материализовать в файл Kilo-агента `.kilo/agent/<id>.md` **без кода**;
- использовать как контракт для Agent Manager / экспертных подагентов.

Агент — НЕ исполнитель и НЕ обязательный шаг; пайплайн работает и без них.

Реестр по умолчанию: `agent.builder` (develop), `agent.tester` (test),
`agent.deployer` (deploy), `agent.watchdog` (control), `agent.supporter` (support).

### B1. Измеренное поведение

```python
from agentic_bi import agents
agents.STAGES == ('develop','test','deploy','control','support')

# 1. неизвестный этап
agents.agents_for_stage("nope")   -> ValueError: Unknown stage 'nope'; allowed: (...)
agents.all_agents("WRONG")        -> []            # молча, без ошибки

# 2. манифест без обязательных полей
agents.from_manifest({})                       -> ValueError: must contain id, role, stage
agents.from_manifest({"id":"x"})               -> ValueError
agents.from_manifest({"id":"x","role":"r"})    -> ValueError

# 3. ЭТАП НЕ ВАЛИДИРУЕТСЯ в from_manifest
agents.from_manifest({"id":"agent.custom","role":"X","stage":"WRONG"})
  -> принят, agent.stage == "WRONG"            # агент существует, но ни одному
                                               # этапу не принадлежит
# 4. enabled у манифеста
agents.from_manifest({..., "enabled": False}).enabled == False
```

### B2. `resolve_agents(spec)` — приоритеты

```python
spec.support = {
  "agents": [{"id":"agent.builder","role":"Custom","stage":"develop","prompt":"OVERRIDE"}],
  "enable_ids": ["agent.deployer"],
  "disable_ids": ["agent.tester"],
}
resolve_agents(spec)
  -> agent.builder  enabled=True role=Custom prompt='OVERRIDE'   # override выиграл
  -> agent.deployer enabled=True                                # включён
  -> agent.watchdog enabled=True                                # по умолчанию
  -> agent.supporter enabled=True
  # agent.tester отсутствует (disable)
```
- `disable_ids` побеждает `enable_ids`, если id в обоих (проверено).
- Агенты, которых нет в реестре (проектные), добавляются в конец результата.

### B3. `render_kilo_agent(agent, path)` — параметр `path` НЕ используется

Сигнатура `render_kilo_agent(agent: SupportAgent, path: str) -> str`, но тело
`path` нигде не читает — только `agent`. В README пример:
`render_kilo_agent(agent, "")` (передают пустую строку, потому что параметр мёртв).
Docstring говорит «file `.kilo/agent/<id>.md`», но путь из аргумента не влияет ни на что.

### B4. Что проверяем у агентского пути

1. Контракт манифеста: какие поля обязательны, что происходит с неизвестным
   `stage`, можно ли молча получить «агента-сироту».
2. Согласованность валидации (`agents_for_stage` кидает, `all_agents`/`from_manifest`
   молчат).
3. Материализация в Kilo-агента: мёртвый параметр `path`, потеря информации
   (triggers/tools/enabled не попадают в .md?), безопасность (id из spec -> имя файла).
4. Приоритеты `resolve_agents`: могут ли override/enable/disable дать неожиданный
   состав (например, включить агента, который по умолчанию выключен, но не выставить
   `enabled=True`).

---

## Что вернуть

По **каждому пункту** (A1..A5, B1..B4) — коротко:
1. подтверждаешь/опровергаешь факт;
2. реальный риск для пользователя/агента (и severity: critical/warning/nit);
3. конкретный фикс (1-2 строки) или «не дефект, потому что ...».

В конце — таблица приоритетов: что чинить в первую очередь по двум путям.
Только высокоуверенные пункты; не выдумывай дефекты, которых нет в фактах выше.

## Assistant

Приветствую. Я провёл независимое ревью на основе предоставленных фактов. 
Моя позиция: **факты измерены верно, но архитектурные и UX-решения, которые к ним привели, содержат системные изъяны**. Я буду опираться на стандарты POSIX (для CLI) и принципы fail-fast (для API).

Ниже разбор по пунктам.

---

## Путь A. Пользовательский (CLI)

### A1. Exit-коды в docstring vs фактические (Traceback вместо кода)
1. **Факт:** Подтверждаю. `visual-check`, `pbix-patch`, `brand-audit` роняют необработанные исключения (`FileNotFoundError`, `NotImplementedError`), что даёт exit=1 и грязный stderr. Контракт docstring нарушен.
2. **Риск (Warning):** В CI/CD пайплайнах парсинг stderr сломается. Пользователь видит «простыню» Python-кода вместо понятной ошибки «Файл не найден». Это нарушает принцип «CLI должен возвращать код, а не стектрейс».
3. **Фикс:** Обернуть тело `main()` во всех CLI-точках в единый декоратор или `try/except`:
   ```python
   try: ...
   except (FileNotFoundError, NotImplementedError) as e:
       print(f"Error: {e}", file=sys.stderr); sys.exit(2)
   ```

### A2. Несогласованность кодов между сервисами
1. **Факт:** Подтверждаю. Код `2` перегружен: у `argparse` это синтаксическая ошибка CLI, а у `web-clone`/`pbix-patch` это ошибка валидации данных.
2. **Риск (Warning):** Скрипт-оркестратор не сможет отличить «пользователь ошибся во флагах» от «битый `.pbix` на входе». Это стандартное соглашение POSIX: `0` — успех, `1` — ошибка выполнения/данных, `2` — ошибка синтаксиса CLI (misuse of shell builtins).
3. **Фикс:** Жёстко стандартизировать. `argparse` пусть остаётся на `2`. Все ошибки валидации входных файлов (не тот формат, не найден, битый) должны возвращать `1`. Сделать базовый класс `CLIError` и ловить его на верхнем уровне.

### A3. `lineage` не возвращает код и не обрабатывает ошибки
1. **Факт:** Подтверждаю. Неявный `return None` -> `sys.exit(0)`. Отсутствие контракта.
2. **Риск (Warning):** Повторяет проблемы A1 и A2. Если `lineage` вызывается в пайплайне `build -> test -> lineage`, падение `lineage` с кодом 1 из-за исключения может быть неверно интерпретировано (или проигнорировано, если пайплайн не настроен на `set -e`).
3. **Фикс:** Добавить явный `sys.exit(0)` в конце `main()`. Добавить в docstring блок `Exit codes: 0 - success, 1 - input/processing error`.

### A4. `--out-dir` по умолчанию пишет внутрь пакета (site-packages)
1. **Факт:** Подтверждаю. `Path(__file__).parent` в установленной библиотеке указывает в `site-packages`.
2. **Риск (Critical):** 
   - В read-only окружениях (Docker, CI, системный Python) это мгновенный `PermissionError`.
   - В dev-окружении это мусорит в исходники, ломает `git status` и не удаляется при `pip uninstall`. Это грубое нарушение принципов упаковки Python.
3. **Фикс:** Изменить дефолт на `Path.cwd() / "agentic_bi_output"` или использовать `tempfile.mkdtemp()` для промежуточных файлов. Для пользовательских артефактов дефолтом всегда должен быть CWD или `~/.cache`.

### A5. Что проверяем в первую очередь у пользовательского пути
1. **Факт:** Это чек-лист, а не дефект. Подтверждаю его релевантность.
2. **Риск:** N/A.
3. **Фикс:** При приёмке следующего PR требовать прохождения именно этих 4 пунктов (особенно п.2 и п.4).

---

## Путь B. Агентский (`agents.py`)

### B1. Измеренное поведение (валидация stage и "агенты-сироты")
1. **Факт:** Подтверждаю. `from_manifest` принимает любой `stage`, создавая «агента-сироту». `all_agents` молчит при неверном stage.
2. **Риск (Critical):** **Silent failure**. Пользователь опечатывается в `stage: "develp"`, агент валидно создаётся, но пайплайн его никогда не дёрнет (так как `agents_for_stage("develop")` его не найдёт). Пользователь будет часами дебажить, почему агент не работает, не подозревая об опечатке.
3. **Фикс:** 
   - В `from_manifest` добавить строгую проверку: `if stage not in STAGES: raise ValueError(...)`.
   - В `all_agents` заменить молчаливый `return []` на `raise ValueError` (для симметрии с `agents_for_stage`).

### B2. `resolve_agents(spec)` — приоритеты
1. **Факт:** Подтверждаю. Логика `disable > enable` работает. Override работает.
2. **Риск (Nit):** Риска нет, логика безопасная (fail-closed). Но она неочевидна для новичка.
3. **Фикс:** Не дефект. Просто вынести приоритеты (`disable_ids` wins over `enable_ids`) в жирный шрифт в README и docstring `resolve_agents`.

### B3. `render_kilo_agent` — мёртвый параметр `path`
1. **Факт:** Подтверждаю. Параметр `path` не используется.
2. **Риск (Warning):** 
   - **API-риск:** Пользователь думает, что функция пишет файл, а она возвращает строгу (или наоборот).
   - **Security-риск (потенциальный):** Если в будущем функцию починят и она начнёт писать файл по `path` или по `agent.id`, то `agent.id` из спеки (которую может сгенерировать LLM или злоумышленник) без санитизации приведёт к **Path Traversal** (например, `id: "../../etc/passwd"`).
3. **Фикс:** 
   - Если функция только рендерит строку: убрать `path` из сигнатуры, переименовать в `render_kilo_agent_markdown(agent) -> str`.
   - Если она должна писать: реализовать запись, но использовать `Path(path).joinpath(sanitize_filename(agent.id))`.

### B4. Что проверяем у агентского пути
1. **Факт:** Чек-лист подтверждён. Пункт 1 (мёртвые параметры/тихие ошибки) уже закрыт в B1.
2. **Риск:** N/A.
3. **Фикс:** Добавить в CI тест, который проверяет, что `from_manifest` с валидным JSON, но невалидным `stage`, падает с `ValueError`.

---

## Таблица приоритетов (Что чинить в первую очередь)

| Приоритет | Пункт | Дефект | Почему в топе |
| :--- | :--- | :--- | :--- |
| **P0 (Critical)** | **A4** | Запись в `site-packages` по умолчанию | Ломает запуск в Docker/CI (`PermissionError`). Мусорит в dev. Требует изменения архитектуры хранения артефактов. |
| **P0 (Critical)** | **B1** | «Агенты-сироты» (молчаливый приём любого `stage`) | Silent failure. Пользователь не узнает об опечатке в конфигурации, агент просто не выполнится. Ломает доверие к агентскому пайплайну. |
| **P1 (Warning)** | **A1, A3** | Traceback'и вместо exit-кодов | Ломает интеграцию с CI/CD и shell-скриптами. Пользовательский UX уровня «alpha-версии». Чинится за 1 час общим декоратором. |
| **P1 (Warning)** | **A2** | Перегрузка exit-кода `2` | Невозможность отличить ошибку CLI от ошибки данных в bash-скриптах. Требует рефакторинга обработки ошибок на границе CLI. |
| **P2 (Warning)** | **B3** | Мёртвый параметр `path` + риск Path Traversal | Вводит в заблуждение. Если чинить (делать запись файла), нужно сразу закладывать санитизацию `id`. |
| **P3 (Nit)** | **B2** | Неочевидные приоритеты `resolve_agents` | Чистая документация. Кода не требует. |

**Резюме ревьюера:** Ядро (`stdlib-only`) явно写得 аккуратно, но **границы (CLI и валидация манифестов)** протекают. Пользовательский путь страдает от отсутствия единого CLI-фреймворка/декоратора для обработки ошибок и путей. Агентский путь страдает от излишней толерантности к невалидным данным (молчаливое создание сирот). Фокус первого спринта — P0.
