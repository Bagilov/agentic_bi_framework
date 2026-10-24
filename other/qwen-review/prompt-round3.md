# Третий раунд ревью `agentic_bi_framework`: бинарный слой (ABF/`pbix_binary`)

Ты — независимый senior-ревьюер. Раунд 3. В раундах 1–2 разобрали состояние,
упаковку, security web_report и релиз. Здесь — **бинарный слой**, который
трогает сам `.pbix` (`pbix_binary/`, `engine_container.py`). Отвечай по пунктам,
с приоритетами и обоснованием. Код не переписывай — нужны оценка и решения.

## Контекст слоя (что он делает)

`agentic_bi.pbix_binary` правит `DataModel`-член `.pbix` на уровне байтов:
- `abf_codec.py` — XPress9-фрейминг члена `DataModel` (сигнатура 102 B +
  чанки `<uncompressed:u32><compressed:u32><body>`); пишет маркер на offset 20
  и CRC-32C по первым 28 байтам тела.
- `abf_model.py` — парсер ABF: XML-страница `BackupLogHeader` (72..4096),
  `backup_log` (UTF-16 с BOM) и `virtual_directory` (UTF-8).
- `abf_relayout.py` — пересборка ABF при замене/добавлении члена «неравной
  длины»: пересчитывает все абсолютные offset'ы.
- `patch_pipeline.py` — equal-length байтовые патчи + uneven member-патчи.
- `engine_container.py` — `swap_datamodel`: переписывает локальный заголовок,
  CRC/размеры, central directory и EOCD.

Всё это уже покрыто тестами (`tests/test_pbix_binary_*.py`, ~600 строк): есть
проверки согласованности индекса, round-trip sqlite, offset'ов, добавления
члена. Т.е. happy-path закреплён.

## ТРИ НАЙДЕННЫХ ДЕФЕКТА (все воспроизведены локально, не гипотезы)

### D-1. XML-экранирование: асимметрия writer/parser → порча вывода (High)

`abf_model.serialize_virtual_directory` собирает XML **вручную f-строками**:
```
f"<BackupFile><Path>{f.path}</Path><Size>{f.size}</Size>..."
```
Экранирования нет. При этом `parse_virtual_directory` читает через
`ET.fromstring`, т.е. **декодирует** `&amp;` → `&`. Симметрии нет:
- разбор корректного донора с `Path` = `A&amp;B_Storage_1234` даёт путь `A&B_Storage_1234`;
- запись этого же пути обратно даёт `<Path>A&B_Storage_1234</Path>` — невалидный XML.

Доказано end-to-end через реальный пайплайн:
```
donor parses; decoded path: ['A&B_Storage_1234']
apply_patches returned successfully: 971482 B
zip testzip(): None            <- zip валиден
SHIPPED DataModel BROKEN: ParseError: not well-formed (invalid token), column 587
```
То есть `apply_patches` **успешно возвращает** и на диск ложится `.pbix`, чей
`DataModel` больше не читается. `backup_log` той же функцией сериализуется
через `ET.tostring` и экранирует корректно — значит дефект локален для
vdir-сериализатора. В реальном доноре `templates/template.pbix` все 515 путей —
чистые 20-символьные hex-id, поэтому сегодня это не проявляется; но любой
донор с `&`, `<`, `>` в storage-path (например, member из workspace-пути с
`&`) его ловит.

### D-2. Смещение/размер из vdir не валидируются (Medium)

`parse_virtual_directory` принимает любые числа: проверил на
`<Size>-5</Size><m_cbOffsetHeader>-1</m_cbOffsetHeader>` и `999999999` —
парсится **без ошибок**. Дальше эти значения используются как истина:
```
member_blob с отрицательным offset вернул 0 байт и не упал
```
`parse_abf_index` проверяет только диапазон самого vdir и что последний
элемент — `LOG`; диапазоны членов (`offset >= PREFIX_SIZE`,
`offset + size <= vdir_offset`) не проверяются ни при разборе, ни при
извлечении. Для битого/враждебного `.pbix` это тихая выдача чужих байтов
вместо доменной ошибки.

### D-3. Амбигуозный equal-length патч применяется к первому совпадению молча (Medium)

`_apply_even` делает `bytes(abf).find(find)` и берёт **первое** вхождение:
```
occurrences of 64x NUL: 7356
ambiguous patch accepted with NO warning; log: ['replace: 64 B at offset 963']
total candidate sites ignored: 7355
```
Патч `{"kind":"replace_hex", "find": "00"*64, ...}` молча попал в offset 963,
хотя подходящих мест 7356. Для инструмента, который правит бинарную модель,
это опаснее явной ошибки: пользователь получает валидный zip с изменённым не
тем байтом.

### Плюс: у `apply_patches` нет пост-проверки результата

Ни `apply_patches`, ни `patch_cli._cmd_apply` не перечитывают собственный
вывод. `swap_datamodel` и `build_container` проверяют только `zip.testzip()`
(целостность архива), но не то, что `DataModel` внутри **читается**. Именно
поэтому D-1 доехал до файла на диске. Замечу: тесты `_assert_index_consistent`
делают ровно то, чего не делает продовый код.

## Что уже подтвердилось корректным (не переотчитываться)

- `decompress_datamodel` корректно отвергает усечённый чанк
  (`DataModelCodecError: truncated ... need 50 bytes`).
- `compress_datamodel`/`crc32c`, маркер и zero-padding до 4096 — round-trip
  закреплён тестами.
- `relayout_abf` пересчитывает offset'ы, prefix (signature + ADDITIONAL_LOG +
  PARTITIONS) остаётся verbatim, header пишется UTF-16LE без BOM в 4096-байтную
  страницу с проверкой переполнения.
- `swap_datamodel` корректно сдвигает центральный каталог и локальные заголовки
  членов, идущих после `DataModel`, и сохраняет метод сжатия.
- `backup_log` сериализуется через `ET.tostring` и экранирует правильно.

## Вопросы третьего раунда

1. **D-1**: правильно ли чинить **оба** направления — экранировать vdir при
   записи и при этом оставить `parse_virtual_directory` через `ET.fromstring`?
   Или надёжнее перевести vdir на `ET.tostring`/`SubElement` (как backup_log)?
   Есть ли причина держать ручную сборку vdir (например, точный порядок тегов
   и отсутствие XML-declaration, что важно для движка)? Нужен ли
   регрессионный тест с путём, содержащим `&`/`<`?
2. **D-2**: где именно должна жить валидация диапазонов — в
   `parse_virtual_directory` (доменное исключение), в `parse_abf_index`
   (согласованность индекса) или в `member_blob`/`relayout_abf` (граница
   использования)? Что считать нарушением: отрицательный offset, перекрытие
   членов, выход за vdir, `offset < PREFIX_SIZE`?
3. **D-3**: как правильно обработать множественные совпадения — падать по
   умолчанию, требовать явный `offset`/`index`/`count` в спецификации, или
   заменять все? Что тут безопаснее для инструмента правки модели, и как не
   сломать существующие сценарии (в тестах патчи применяются к уникальным
   строкам)?
4. **Пост-проверка**: стоит ли сделать `apply_patches` само-проверяющимся
   (перечитать `DataModel` из записанного файла и распарсить индекс) — и должна
   ли это быть обязательная часть или опциональный флаг `--verify`? Это дешевле,
   чем Desktop-oracle, и ловит именно D-1.
5. **Приоритет и группировка**: как ты расставишь D-1/D-2/D-3 и пост-проверку
   относительно уже запланированных этапов 0–4 (этап 0 — security web_report,
   этап 1 — CI/coverage/пути, этап 2 — тесты .pbix)? Что из этого блокер для
   0.0.1b2, а что — backlog до 1.0?
6. **Тесты формата**: каких инвариантов не хватает в `test_pbix_binary_*`
   помимо перечисленного (например, property-based round-trip
   `relayout → parse` для случайных замен, fuzz на усечённые vdir/backup_log,
   проверка, что `swap_datamodel` не меняет остальные члены байт-в-байт)?
