# Сверка непустой production-истории

`reconciliation` подтверждает фактическое содержимое production, когда оно
соответствует известному Git manifest, но отличается от записанного current.
Операция не загружает файлы сайта. Используются существующие
`scripts/production.py`, `scripts/reconciliation.py`, история и журнал восстановления.

## Модель подтверждения

По [архитектурному ревью](2026-10-29-production-architecture-review.md) принята
политика `owner-explicit-v1`: один владелец, доверенный локальный инструмент,
явное подтверждение точного hash плана. Отдельный подписант, SSHSIG, root trust
store и независимый runner для новых операций не требуются.

Это процедурное согласие, записанное в событии, а не криптографическое доказательство
личности. Код не отличает владельца от процесса с полным доступом к той же учётной
записи. Агент обязан сначала показать конкретный план и получить отдельное
разрешение владельца. Нельзя самостоятельно подставлять подтверждение из намерения
«сделать deploy», переменной окружения, общего «да» или старого сообщения.

Разрешение на локальную реализацию и тесты не разрешает реальную reconciliation.
Первоначальная baseline adoption и её закрытый guard не изменены.

## Подготовка и применение

Команды ниже — план будущего применения. Подготовка плана не пишет metadata
и не обращается к сети. `reconciliation-check` только читает сервер и metadata.
Файлы плана и evidence следует хранить вне публикуемого payload.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py reconciliation-plan \
  d25e6727b111f9f8bfeb89c9415e3cca8ecef958 \
  --reason 'Неучтённые публикации; непосредственная предыдущая версия неизвестна' \
  > /private/tmp/portfolio-reconciliation-plan.json

PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py reconciliation-check \
  /private/tmp/portfolio-reconciliation-plan.json \
  > /private/tmp/portfolio-reconciliation-check.json
```

План содержит полный SHA, manifest, canonical manifest SHA-256, сервер, checkout,
recorded current/previous, history tip, hashes исходных bytes трёх metadata-файлов,
уникальный UUID, причину, политику подтверждения, путь резервной копии
и ожидаемый `previous=''`. Изменение любого поля меняет hash плана.

Для указанной версии ожидаются 98 файлов и manifest SHA-256:
`8d247cf9ea4c083028fce0979ab7a3ce9ebeca2c93ba0550cdab68a70856a055`.
`acb5848`, `59143e9` и `d25e672` имеют одинаковый production manifest;
это выбор снимка содержимого, а не доказательство исторической загрузки именно d25e672.

После просмотра плана и результатов проверки владелец отдельно подтверждает:
`RECONCILE <полный hash плана>`. Только затем разрешена команда:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py reconciliation-apply \
  /private/tmp/portfolio-reconciliation-plan.json \
  --confirm 'RECONCILE FULL_PLAN_HASH'
```

`FULL_PLAN_HASH` заменяется полным значением `hash` утверждённого плана.
API `save_reconciliation(repo, plan, statement)` принимает ту же точную строку.
`DEPLOY`, флаг пропуска проверок и подтверждение другого плана отклоняются.
CLI отклоняет JSON с повторяющимися ключами. План загружается один раз.

## Проверки и запись

Под общим эксклюзивным `.deploy/metadata.lock` выполняются:

1. Повторная проверка плана, исходных bytes metadata и неизменности истории.
2. Новое SSH/HTTPS наблюдение после подтверждения. SSH проверяет hashes всех
   managed-файлов до и после HTTPS; HTTPS проверяет status 200 и SHA-256 каждого
   manifest URL и главной `/`. Перенаправления и неожиданный compression запрещены.
3. Проверка свежего challenge, timestamps и отсутствия изменений hashes,
   дополнительных paths и защищённых файлов между SSH-наблюдениями.
4. Постоянная резервная копия `.deploy/backups/<operation-id>.json`.
5. Durable WAL `.deploy/reconciliation-pending.json`, затем history → current → previous.
6. Повторное чтение результата; удаление WAL только после успешной проверки.

Evidence содержит фактические stdout/stderr SSH, exit codes, HTTPS URL/status/hashes,
inventory и время. Ожидаемые hashes не подставляются как результаты наблюдения.
Managed symlinks запрещены. `.htaccess` и `.well-known/` не изменяются.

В историю добавляется ровно одно событие `operation=reconciliation`,
`kind=observation`, без `rsync_exit`. Старые события и их hashes сохраняются.
`before` и `recorded_previous` фиксируют старые записи, но не утверждают, что они
были фактическими предшественниками нового содержимого.
Новый current — наблюдаемый commit; неизвестный previous всегда пустой.
Подтверждение хранится в `confirmation`: policy, purpose, plan hash, operation ID,
точная строка и timestamp. Повтор уже записанного содержимого или UUID запрещён.

Ранее подписанные события доступны для исторической проверки без переписывания.
Новые планы требуют `owner-explicit-v1`; старый подписанный план не принимается
как разрешение на новую запись. Pending-транзакция старой версии требует отдельного
расследования и плана миграции; автоматического преобразования нет.

## Резервная копия и сбой

Постоянная копия содержит исходные и целевые bytes всех трёх metadata-файлов,
новое событие с планом, подтверждением и evidence, operation ID и canonical hash.
Это тот же документ, который используется как WAL. Копия создаётся эксклюзивно
с правами 0600 и проверяется перед первой заменой metadata. Все записи используют
flush/fsync; для замен — временный файл, atomic replace и fsync каталога.
Копия сохраняется после завершения. Её существование не обозначает успех операции:
результат определяется историей, зеркалами и состоянием WAL.

Если резервная копия не создалась, metadata не изменяются. Существующая, включая
незавершённую, копия никогда не перезаписывается. После сбоя до WAL нужен новый
план с новым UUID и новое подтверждение; старый архив остаётся для расследования.

Пока WAL существует, обычные операции блокируются. Диагностика без записи:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py reconciliation-recovery-plan \
  > /private/tmp/portfolio-recovery-plan.json
```

План привязан к WAL, резервной копии, фактическим bytes metadata, действию
и результирующим current/previous. Нужное действие определяется автоматически:

| Состояние | Допустимое восстановление |
| --- | --- |
| Все metadata исходные; history не заменена | `abort-uncommitted`: убрать WAL, metadata не менять |
| History целевая; зеркала имеют исходные/целевые bytes | `finish-mirrors`: завершить только зеркала |
| Чужие bytes, повреждённая история, WAL или резервная копия | Отказ; отдельное расследование |

После отдельного подтверждения `RECOVER <полный hash recovery-плана>`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py reconciliation-recover \
  /private/tmp/portfolio-recovery-plan.json \
  --confirm 'RECOVER FULL_RECOVERY_PLAN_HASH'
```

API: `recover_reconciliation(repo, plan, statement)`. Он сохраняет отдельный
аудит восстановления в том же каталоге backups под UUID recovery-плана,
повторно проверяет bytes и завершает ранее проверенную транзакцию.
История не перезаписывается, новое событие не добавляется, сеть и upload
не используются. Оригинальная резервная копия остаётся неизменной.
При повторном прерывании готовится новый recovery-план по текущим bytes.
Stale lock не удаляется автоматически: сначала проверка отсутствия активной
операции и отдельное разрешение владельца.

## Возврат к deploy

После успешной reconciliation отдельно проверить `inspect`, event ID, архив,
отсутствие WAL/lock и свежие hashes production. Ожидается current=d25e672…,
previous пустой. Исторические d9bfc32… и 00ad3f0… остаются в журнале.

Дальше действует обычный deploy: новый pinned SHA, Git-blob snapshot, проверки
ресурсов, checksum dry-run и отдельная команда владельца `DEPLOY` для показанного
плана. После reconciliation перед deploy/rollback обязателен `live_current`.
Успешная публикация B поверх сверенного A даёт B/A; неизвестный rollback target
не назначается. Commit/push кода, metadata и архивов согласуются отдельно.

## Ограничения

Один согласованный процесс публикации и отсутствие сторонних загрузок на время
операции обязательны. Локальный lock не блокирует сервер или другие машины;
между последним наблюдением и локальной записью остаётся небольшое окно.
Hash chain и архив обнаруживают повреждение, но не защищают от злонамеренной
перезаписи пользователем с полным доступом к репозиторию. Первоначальная baseline
adoption по-прежнему отключена. Общая транзакция upload и metadata для штатного
deploy в этой задаче не добавлялась: восстановлена возможность подготовить
и применить существующую reconciliation после отдельного разрешения.
