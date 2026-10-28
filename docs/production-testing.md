# Локальные тесты production protocol

Запуск без production-доступа:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py baseline-plan HEAD
```

Все тестовые commits, history.json и SHA-зеркала создаются в disposable Git repos.
Основной репозиторий не коммитится; реальные metadata и сайт не меняются.
Нет SSH и запросов к production. Только отдельный интеграционный тест вызывает
rsync между временными локальными каталогами; HTTP-тела явно имитируются чтением
локальных файлов. Это не проверка реального сервера или исторического deploy.

Проверяются:

- baseline только при empty history/current/previous, pinned SHA и согласованный manifest;
- observation/upload evidence разделены; baseline не содержит выдуманный rsync exit code;
- подготовка плана и кандидата без записи; отказ без owner confirmation даже с env flags;
- повторная verification под lock; несовпадение SSH/HTTP hashes/statuses блокирует запись;
- изменение metadata после подготовки и во время повторной проверки блокирует запись;
- baseline A → deploy B → rollback A, содержимое, SHA, manifest и persisted history;
- обязательный live_current перед upload после baseline; повтор A не создаёт previous;
- отказ rollback после одного baseline; отказ второго baseline; защита цепочки;
- прежние deploy/rollback, interrupted writes, locks, CSS comment regression и snapshot checks.

Интеграционный тест проверяет внутренний storage primitive `_persist_history`
исключительно в disposable repo. Он не подменяет owner guard и не создаёт
фиктивного пользовательского подтверждения. Публичная adoption API остаётся
заблокированной: доверенный owner channel отсутствует. PASS локального storage
теста не означает, что реальная adoption разрешена или что подпись проверена.

Достоверность реальных observations, HTTP redirects/compression и защищённый
источник подтверждения требуют отдельного тестирования после подключения внешнего
доверенного компонента. Никаких production операций этот набор не выполняет.

## Результаты запуска 2026-10-08

| Проверка | Результат |
| --- | --- |
| Полный unittest discover | PASS — 47 тестов, 36.355 s, OK |
| Baseline A → deploy B → rollback A | PASS — A/пусто → B/A → A/B; manifest, bytes и persisted history |
| Исходные deploy/rollback и CSS-ссылки | PASS |
| Отказы при mismatch, изменении metadata и отсутствии owner confirmation | PASS |
| Повторная observation под lock; ошибка повторной verification | PASS — история не записывается |
| baseline-plan HEAD основного проекта | PASS — pinned 29cac2cf451e1136fb6da36ac5d091f8efd595d9, без SSH/HTTP и записи |
| inspect основного проекта | PASS — current=null, previous=null |
| git diff --check и diff сайта/metadata | PASS — whitespace errors нет; diff сайта/metadata пуст |

Bundled quick_validate skills не запустился: в системном Python отсутствует PyYAML.
Зависимости не устанавливались; YAML frontmatter проверен отдельно Ruby/Psych.
Фактическая adoption **НЕ ДОСТУПНА**: защищённый owner channel ещё не подключён.
Ни production verification, ни baseline adoption в этом запуске не выполнялись.

## Архив: тесты reconciliation с SSHSIG, версия 88b395c

`tests/test_reconciliation.py` добавляет 38 тестов к 47 существующим проверкам.
Все записи выполняются исключительно во временных disposable Git repos.
Файлы реального `.deploy/` не используются как цели записи.

Проверяются:

- неизменность старых событий, новое observation-событие, пустой неизвестный previous;
- привязка плана к SHA, manifest, checkout и точным bytes metadata;
- реальные SSHSIG sign/verify на временном тестовом ключе; неверные подписи,
  изменённые claims, истёкшие/будущие receipts, повтор receipt ID и операции;
- отказ без независимого trust store, запрет обхода через baseline/обычный writer;
- новые observations под lock, SHA-256 и статусы SSH/HTTPS, challenge и время;
- сборщик с подменёнными сетевыми транспортами и локальный запуск remote-reader
  на временных файлах; запрет redirects, SSH failures, symlinks и гонок на сервере;
- смена metadata до lock и во время observation, истечение approval перед WAL;
- сбои записи WAL, history, обоих зеркал, fsync и финальной очистки WAL;
- отдельный подписанный recovery-план, проверка исходной подписи, отказ при
  чужих bytes и stale lock, повторное прерывание восстановления;
- совместимость с последующим deploy/rollback и обязательным live_current;
- CLI подготовки плана без сети/записи и чтение новой истории через CLI inspect.

Подмена пути тестового signer происходит только внутри unit-тестов; это не установка
доверия и не подтверждение владельца production. Тесты не запускают SSH/HTTPS к сайту,
не проверяют реальные host keys/TLS и не подтверждают production readiness окружения.
Применение требует отдельной подготовки по `docs/production-reconciliation.md`.

Локальный запуск исходной реализации:
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` —
**PASS: 85 тестов, 83.155 s, OK**. `git diff --check` — PASS.
Исходные bytes production metadata, HEAD `540dd63…` и файлы сайта сохранены.
Реальная reconciliation, recovery, deploy, rollback и настройка доверия не выполнялись.

## Действующие тесты упрощённой reconciliation

Политика новых операций — `owner-explicit-v1`, согласно архитектурному ревью
и отдельному разрешению владельца. Новые тесты не создают ключей и не настраивают
доверие. Временные Git repos и сетевые имитации из существующего набора сохранены.

Вместо тестов SSHSIG проверяются точное подтверждение плана, отказ при общем «да»,
`DEPLOY`, неверном hash или изменённом плане. Сохранены проверки SHA-256, истории,
неизвестного previous, гонок, WAL, ошибок fsync и восстановления без upload.
Проверяются постоянный архив metadata, отказ при ошибке/повторном архивировании,
целостность исходной копии при recovery, отдельное подтверждение восстановления
и аудит recovery в том же каталоге backups. CLI проходит локальный цикл
plan → read-only check → owner-confirmed apply; JSON с повторными ключами отвергается.
Историческая совместимость подписанного события проверяется синтетической записью
без генерации ключей и без разрешения новых операций по legacy-плану.

Все записи выполняются только во временных repos. Тесты не подключаются к серверу,
не пишут реальные production metadata и не доказывают применение reconciliation.

Результат локального запуска 2026-10-29:
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` —
**PASS: 81 тест (47 существующих + 34 адаптированных reconciliation), 78.649 s, OK**.
`git diff --check` — PASS. Проверка локального плана для d25e672… подтверждает
98 файлов, ожидаемый manifest SHA-256 и пустой previous; сеть не использовалась.
Реальные metadata побайтно сохранены, каталог backups и WAL/lock в проекте
не создавались. HEAD остался 88b395c…; commit/push и production-операций не было.
