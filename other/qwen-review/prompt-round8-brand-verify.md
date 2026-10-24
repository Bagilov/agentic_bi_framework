# Ревью: brand-audit и engine-verify (решение «публиковать или нет»)

Ты — независимый ревьюер Python-кода. К промпту приложены **файлы** (3 бандла).

ВАЖНО: чат принимает не более ~5 вложений, поэтому код собран в 3 бандла — это
markdown, где секции разделены строкой
`==================== FILE: <путь> ====================`. Читай код из бандлов:
- `round8-code-1-brand.md` — `brand_audit.py`, `brand_audit_eval.py`,
  `brand_audit_extract.py`, `brand_audit_math.py`, `brand_audit_types.py`
- `round8-code-2-brand-config.md` — `brand.py`, `brand_config.py`,
  `brand_rules.py`, `brand_palette.py`, `brand_fonts.py`
- `round8-code-3-verify.md` — `engine_verify.py`, `engine_verify_core.py`,
  `engine_verify_checks.py`, `engine_verify_brand.py`, `rebuild.py`,
  `engine_container.py`

## Что за код

Пакет `agentic_bi` (stdlib-only ядро) собирает дашборд Power BI из декларативной
спеки и затем **сам себя проверяет** перед публикацией. Два независимых контура
проверки:

1. **Brand-audit** — проверяет соответствие брендбуку (палитра, шрифты, правила):
   `brand_audit_types.py` (модель результата), `brand_audit_extract.py` (извлечение
   фактических цветов/шрифтов из собранного layout — норм. hex, rgb(), имена тем),
   `brand_audit_math.py` (дельта цвета / контраст), `brand_audit_eval.py` (правила и
   вердикт), `brand_config.py` + `brand_rules.py` + `brand_palette.py` (каталог
   брендбука), `brand_fonts.py` (разбор стека шрифтов), `brand.py` (facade).
2. **Engine-verify** — сверяет реально открытый в Power BI Desktop отчёт (через
   Desktop-oracle/пайплайн) с ожидаемым layout: `engine_verify.py` (facade),
   `engine_verify_core.py` (сверка), `engine_verify_checks.py` (набор проверок),
   `engine_verify_brand.py` (мост brand-audit → verify), `rebuild.py` (пересборка
   `.pbix`), `engine_container.py` (контейнер/секции pbix).

Контекст: это **гейт публикации**. Ложно-зелёный вердикт (fail-open) опаснее
ложно-красного. Внешние данные (hex, rgb, имена шрифтов, layout из `.pbix`) —
недоверенные.

## Что вернуть

1. **Fail-open в вердикте.** Найди места, где отсутствие данных, пустой список,
   отсутствующий ключ или исключение приводят к «нарушений нет»/«ok».
   Файл:функция + условие.
2. **Разбор цвета/шрифта.** Где нормализация hex/rgb()/имени неверна или
   молча пропускает значение (например, нестандартная запись → элемент
   выпадает из проверки)? Учти регистр, `#`/без, 3/6/8 цифр, `rgb(...)`,
   пробелы, альфу.
3. **Правила и пороги.** Корректен ли приоритет правил и значений по умолчанию
   в `brand_rules`/`brand_audit_eval`? Есть ли дефолт, который тихо скрывает
   нарушение.
4. **Сверка verify.** Может ли `engine_verify_*` дать `ok`, если ожидаемый
   элемент отсутствует, дублируется или представлен в другом типе/регистре?
   Конкретные несоответствия с layout/rebuild/container.
5. **Дефекты.** Только высокоуверенные: что реально сломается или соврёт.
   Особое внимание — границы (пустой layout, один visual, дубликат id).

По каждому — файл:функция, условие, severity (critical/warning/nit). Если по
пункту нет замечаний — «нет замечаний». Не пересказывай код.
