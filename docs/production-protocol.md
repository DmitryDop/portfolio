# Production release protocol

Версия схемы: 1. Сервер: `lineba:/home/l/linebaru/dopler/public_html/`.
URL: `https://dopler.lineband.ru/`. Baseline, deploy и rollback используют одну историю.
Помощник `scripts/production.py` работает только локально: он не выполняет rsync,
SSH, HTTP, commit или push. CLI не записывает metadata. Функция `save_history`
предназначена только для записи после фактической успешной verification;
её нельзя вызывать с synthetic evidence вне изолированных тестовых repos.

## Snapshot и manifest

Зафиксируй полный SHA существующего commit до загрузки. Prepare читает Git blobs,
а не рабочие файлы. `release.json` содержит `commit` и `manifest` — отображение
relative path → SHA-256 содержимого. Payload включает только явно разрешённые
tracked production paths. Manifest и release.json находятся вне payload.
Prepare прекращается при отсутствующих literal-ссылках. Динамические JS-ссылки,
внешние ресурсы, secrets и новые типы ресурсов требуют проверки человеком.
Readonly files снижают риск случайной записи, но не заменяют `check_snapshot`
и эксклюзивный доступ к каталогу до завершения загрузки.

## Metadata и доказательства

Сохраняются прежние `.deploy/production-current` и `production-previous`:
полный SHA с переводом строки либо пустой файл. Они являются зеркалами истории,
а не самостоятельным доказательством. Авторитетный журнал `.deploy/history.json`
создаётся только после первой полностью проверенной операции, не при подготовке.
Формат: `{"schema": 1, "events": [...]}`.

Каждое событие содержит:

- `id`: уникальный UUID операции; `operation`: baseline, deploy или rollback;
- `commit`: первоначальный TARGET_SHA; `before`: подтверждённый current до операции;
- `manifest`: все production paths и их SHA-256 из этого commit;
- `parent`: hash предыдущего события, пустая строка для первого;
- `evidence`: результаты фактической проверки; `hash`: SHA-256 canonical JSON события
  без поля hash (`canonical` из помощника).

Общие поля evidence: UTC/offset timestamp `verified_at`, configured `target` и `url`,
`http_status=200` для `/`, `root_sha256` тела `/`,
`remote_sha256` всех managed-файлов, `http_sha256` декодированных HTTP-тел всех
manifest URL и `http_statuses` (200 для каждого path). `transcript` — непустой
фактический журнал команд и результатов remote hashes, HTTP URL/status/hash.
Для deploy/rollback дополнительно обязательны `kind=upload`, `rsync_exit=0`, журнал
dry-run и загрузки, защиты серверных файлов и разрешённых удалений.
Старые upload events без kind читаются как upload; их hashes и содержимое не меняются.
Для baseline обязательны `kind=observation` и отсутствие поля rsync_exit вообще.
Baseline evidence не должно выдавать наблюдение за загрузку. Не записывай секреты.

HTTP hashes, remote hashes и root hash должны совпадать с manifest. Не заполняй
evidence ожидаемыми значениями: парси фактические ответы и сохраняй исходный журнал.
Не допускай redirects на другие домены. Compression декодируй до хеширования.
История валидируется по цепочке hashes, уникальности id, переходам, существованию
commits, соответствию manifest Git и полноте evidence. Она сохраняется в Git вместе
с SHA-зеркалами при отдельно разрешённом commit. Ранее подтверждённые события нельзя
переписывать. Hash chain обнаруживает повреждение относительно сохранённой истории,
но не является цифровой подписью или независимым доказательством сервера: проверяй
источник журналов и Git diff, не доверяй импортированной истории без проверки.

Перед deploy/rollback с известным current проверь live remote hashes относительно
последнего события current. Ручные изменения или частичная неудачная загрузка делают
live state неподтверждённым: остановись, не переносись на предыдущий Git commit.

## Переходы состояния

`load_history` и `validate_history` сверяют оба зеркала с историей. `transition` —
чистая функция, возвращающая новый журнал и SHA-зеркала без записи на диск.

| Состояние и успешная операция | Новый current | Новый previous |
| --- | --- | --- |
| Оба пусты, история отсутствует/пуста; baseline A | A | пусто |
| Оба пусты, история отсутствует; deploy A | A | пусто |
| A / пусто; повторный deploy A | A | пусто |
| A / пусто; deploy B | B | A |
| B / A; повторный deploy B | B | A |
| B / A; rollback A | A | B |
| Любая ошибка загрузки/verification | без изменения | без изменения |

Повтор SHA добавляет evidence нового успешного события, но не меняет previous.
Rollback target обязан совпадать с previous валидной истории и иметь подтверждение
успешной загрузки либо наблюдения baseline. Commit history metadata не является новым production deploy.
Первый deploy не восстанавливает сведения о неизвестной старой production-версии.

## Baseline adoption существующей production

Baseline подтверждает только наблюдаемое состояние в момент свежей verification.
Он не подтверждает исторический успех rsync или полный smoke-check прошлого deploy.
Старый журнал Claude Code можно сохранить как отдельный источник расследования:
неизвестный exit code остаётся неизвестным и не подставляется в observation evidence.

Baseline разрешён только первым событием при пустой истории и пустых обоих SHA-зеркалах
(отсутствующие файлы тоже считаются пустым состоянием). Существующие события не
переписываются. Непустая legacy metadata запрещает автоматическую adoption.

1. `python3 scripts/production.py baseline-plan <SHA>` только читает Git/metadata
   и печатает JSON-план. Нет SSH/HTTP, snapshot-каталога или записи metadata.
   TARGET_SHA разрешается один раз; manifest вычисляется из Git blobs.
2. План содержит operation=baseline, commit, manifest, target, url, исходные bytes
   metadata в hex/null и hash canonical JSON. Hash плана не является подписью.
   `check_baseline_plan` сверяет hash, Git manifest, empty state и точные bytes.
3. Проведи read-only SSH/HTTP verification всех managed-файлов и `/` по общим правилам.
   Сохрани фактические наблюдения и список extra server paths отдельно. Не удаляй их.
   `baseline_candidate` проверяет данные и возвращает кандидат без записи.
4. После просмотра плана требуется отдельное явное подтверждение владельца,
   привязанное к baseline, точному SHA и manifest hash. Команда DEPLOY не разрешает
   adoption автоматически. Подтверждение результата проверки не записывает baseline.
5. Публичная функция `save_baseline` проверяет план и обращается к доверенному
   каналу подтверждения, затем требует повторного НОВОГО observation. Callback
   live_verifier вызывается под metadata.lock непосредственно перед записью;
   результат старой проверки нельзя повторно выдавать за свежую verification.
   Metadata проверяется до и после callback, затем записывается история и зеркала.

**Текущее ограничение:** доверенный канал владельца не установлен.
`require_baseline_owner_confirmation` всегда возвращает отказ PermissionError.
Нет CLI-команды adoption, флага approve или переменной окружения, разрешающих запись.
`save_history` не принимает baseline: обход повторной проверки через него запрещён.
Обычная проверка и подготовка кандидата доступны; фактическая adoption пока отключена.

Это не криптографический guard против агента с доступом к Python-коду и filesystem.
Внутренний `_persist_history` — storage primitive, не security boundary. Нельзя
вызывать его для реальной adoption вручную или из skill. Для включения adoption
нужен защищённый внешний компонент, который проверит источник владельческого
подтверждения, подпись/одноразовый receipt для полного плана и выполнит запись.
Файл разрешения, локальная строка, callback с True или изменение guard не являются
подтверждением. В этой версии fake receipts и signing keys не создаются.

Для всех новых deploy/rollback в baseline-derived истории `transition` требует
`live_current`: отдельное observation текущего commit, полученное ДО загрузки.
Оно сохраняется как before_evidence и повторно проверяется валидатором истории.
Без успешной live verification A загрузка B не должна начинаться; current A не
переносится в previous. После успешной загрузки и verification B: B/A.
Rollback A требует live verification B и post-upload verification A: A/B.
Повторная публикация A после baseline остаётся A/пусто, новый baseline запрещён.

Валидатор старых upload-only histories не требует ретроспективного before_evidence,
чтобы не переписывать существующие события. Для них сохраняется обязательный
операционный live preflight из skills. Timestamp и hashes не доказывают происхождение
наблюдения; доверенный сборщик должен получать актуальные ответы, а не копировать evidence.

## Запись после успешной verification

1. Используй одну операцию за раз; исключи параллельные deploy/rollback и запись metadata.
   Сохрани исходные bytes всех трёх файлов до подготовки. Перед записью сверь их
   с сохранёнными bytes, а не только с SHA current. При изменении остановись.
2. Для upload вызови `transition(repo, history, current, previous, TARGET_SHA, evidence,
   operation, UUID, live_current=observation_before_upload)` при baseline-derived
   истории. Не считывай новый HEAD как deployed commit. Baseline использует отдельный API выше.
3. Вызови `save_history(repo, result, expected_bytes)`, где expected_bytes получены
   через `metadata_bytes` до подготовки. Она проверяет кандидат, берёт эксклюзивный
   metadata.lock, сверяет исходные bytes и разрешает только одно добавленное событие.
   Запись использует временные файлы в `.deploy/`, flush + fsync + os.replace;
   SHA-зеркала обновляются после журнала, затем выполняется fsync каталога.
   Не включай временные файлы или lock в commit. Ошибку fsync считай ошибкой записи.
4. Повторно прочитай все файлы через `load_history`. Покажи event id и current/previous.
   Только при согласованном состоянии объявляй полный успех.
5. Commit history и SHA-зеркал, push — исключительно по отдельному разрешению.
   Ошибка sync не означает необходимость повторного rsync.

Три файла нельзя атомарно переименовать одной операцией. При сбое между записями
inspect намеренно останавливается. Не повторяй загрузку и не исправляй зеркала молча:
покажи журнал и фактические hashes; после отдельного разрешения восстанови зеркала
из валидного завершённого события. Частичную загрузку нельзя обозначать успехом.
При аварии после verification, но до записи журнала, требуется проверка сохранённых
результатов и live state; автоматическое восстановление истории запрещено.
При оставшемся metadata.lock после аварии остановись; удалять lock можно только
после проверки отсутствия активной операции и отдельного согласования.

## Пустая и legacy metadata

Отсутствующие/пустые оба SHA-файла и отсутствие событий означают unknown current
и отсутствие target. Непустой SHA без событий, повреждённый JSON, отсутствующий
commit, несогласованное зеркало или previous=current блокируют процесс.
Не сбрасывай metadata и не создавай synthetic success. Миграция legacy SHA требует
отдельного согласования и проверяемых журналов прежней успешной загрузки.
Git history допустима для расследования, но не как доказательство deploy.

## Локальная проверка

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`
проверяет snapshots, контент, цепочку evidence и переходы на временных Git repos.
`PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py inspect` читает metadata.
`PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py check HEAD` проверяет ссылки
в зафиксированном commit без создания snapshot; missing references дают exit code 1.
Тесты не подключаются к production и не изменяют реальные SHA-файлы.
